"""Task lifecycle: discover tools, plan, research, seek approval, write, and verify."""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any
from config import ensure_directories, get_settings
from planner import plan_goal
from mcp_client import list_tools as discover_mcp_tools, call_tool
from tools.internship_tools import rank_opportunities
from tools.email_tools import render_email_draft, _slug
from permissions import requires_approval
from state import (
    create_task, upsert_step, get_step, list_steps, get_task, set_task_status, set_task_plan,
    update_step, create_approval, get_approval, decide_approval, add_tool_run, append_audit,
)
from verifier import verify_spreadsheet, verify_files


def hash_json(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _call_with_deadline(tool: str, args: dict, deadline: float):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("The task execution time limit was reached.")
    return call_tool(tool, args, timeout_seconds=remaining)


def _record_tool_result(task_id: str, step_key: str, tool: str, args: dict, retries: int | None = None,
                        deadline: float | None = None) -> dict:
    max_attempts = retries or get_settings().max_retries
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        if deadline is not None and time.monotonic() >= deadline:
            last_error = "TimeoutError: The task execution time limit was reached."
            break
        update_step(task_id, step_key, "running", increment_attempts=True)
        try:
            result = _call_with_deadline(tool, args, deadline) if deadline is not None else call_tool(tool, args)
            add_tool_run(task_id, step_key, tool, attempt, "done", result=result)
            return result
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            add_tool_run(task_id, step_key, tool, attempt, "failed", error=last_error)
            update_step(task_id, step_key, "running", error=last_error)
            if attempt < max_attempts:
                time.sleep(min(2 ** (attempt - 1), 3))
    update_step(task_id, step_key, "failed", error=last_error)
    raise RuntimeError(f"Tool '{tool}' failed after {max_attempts} attempts: {last_error}")


def _requested_count(goal: str, default: int = 3) -> int:
    match = re.search(r"\b(\d{1,2})\s+(?:internships?|jobs?|opportunities|roles)\b", goal, re.I)
    if not match:
        match = re.search(r"\btop\s+(\d{1,2})\b", goal, re.I)
    return max(1, min(int(match.group(1)), 10)) if match else default


def _prepare_opportunity_rows(items: list[dict]) -> list[dict]:
    columns = ("title", "company", "category", "location", "eligibility", "eligibility_status", "deadline",
               "fit_score", "ranking_reasons", "link", "description", "source_mode", "verification_status",
               "is_sample", "contact_email")
    return [{key: item.get(key, "") for key in columns} for item in items]


def _make_report(goal: str, search_result: dict) -> str:
    results = search_result.get("results", [])
    lines = ["# AI Operator Research Report", "", f"**Goal:** {goal}",
             f"**Generated:** {datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"**Search mode:** {search_result.get('source_mode', 'unknown')}", "",
             "> Search snippets are leads, not independently verified facts. Open original sources before relying on them.", ""]
    if not results:
        lines += ["## Results", "No usable live web results were returned.",
                  "The agent has not fabricated replacement results or treated its own fallback data as live research.", ""]
    for index, item in enumerate(results, 1):
        lines += [f"## {index}. {item.get('title', 'Untitled')}", "",
                  f"- URL: {item.get('url', '')}", f"- Domain: {item.get('domain', '')}",
                  f"- Retrieved at: {item.get('retrieved_at', '')}",
                  f"- Status: {item.get('verification_status', 'unverified')}", "",
                  str(item.get("snippet", "")).strip(), ""]
    return "\n".join(lines)


def start_task(goal: str, profile: dict | None = None) -> str:
    """Create a durable task and execute only safe research/preparation steps."""
    ensure_directories()
    profile = profile or {}
    deadline = time.monotonic() + get_settings().task_timeout_seconds
    # Discover the real MCP capability set before planning. The planner never invents tool availability.
    task_id = create_task(goal, {"profile": profile})
    discovery_step = upsert_step(task_id, "tool_discovery", "Discover MCP tools", "list_tools", "running")
    try:
        tools = discover_mcp_tools()
        tool_names = [tool["name"] for tool in tools]
        update_step(task_id, "tool_discovery", "done", {"tools": tools})
        append_audit(task_id, "tools_discovered", {"tool_names": tool_names})
    except Exception as exc:
        error = f"MCP discovery failed: {type(exc).__name__}: {exc}"
        update_step(task_id, "tool_discovery", "failed", error=error)
        decision, planner_mode = plan_goal(goal)
        set_task_plan(task_id, {"decision": decision.model_dump(), "planner_mode": planner_mode,
                                "profile": profile, "discovered_tool_names": []})
        append_audit(task_id, "plan_created_after_discovery_failure", {"workflow": decision.workflow, "planner_mode": planner_mode})
        set_task_status(task_id, "failed", {"error": error})
        return task_id

    decision, planner_mode = plan_goal(goal)
    set_task_plan(task_id, {"decision": decision.model_dump(), "planner_mode": planner_mode,
                            "profile": profile, "discovered_tool_names": tool_names})
    append_audit(task_id, "plan_created", {"decision": decision.model_dump(), "planner_mode": planner_mode,
                                             "based_on_discovered_tools": tool_names})

    if decision.workflow == "unsupported":
        set_task_status(task_id, "blocked", {"message": decision.unsupported_reason, "planner_mode": planner_mode})
        append_audit(task_id, "task_blocked_unsupported_workflow", {"reason": decision.unsupported_reason})
        return task_id

    required_tools = (["search_internships", "save_to_sheet", "read_sheet", "draft_email"] if decision.workflow == "opportunity_search" and decision.category == "internship"
                      else ["search_jobs", "save_to_sheet", "read_sheet", "draft_email"] if decision.workflow == "opportunity_search"
                      else ["search_web", "save_report"])
    missing_tools = sorted(set(required_tools) - set(tool_names))
    if missing_tools:
        message = "Required capabilities were not discovered from the MCP server: " + ", ".join(missing_tools)
        set_task_status(task_id, "blocked", {"message": message, "missing_tools": missing_tools, "verified": False})
        append_audit(task_id, "task_blocked_missing_tools", {"missing_tools": missing_tools})
        return task_id

    if decision.workflow == "opportunity_search":
        search_tool = "search_internships" if decision.category == "internship" else "search_jobs"
        search_step = upsert_step(task_id, "research", "Search and rank opportunities", search_tool, "pending")
        try:
            search_result = _record_tool_result(task_id, "research", search_tool,
                                                {"query": decision.query, "limit": decision.limit}, deadline=deadline)
            items = search_result.get("items", [])
            profile_for_rank = dict(profile)
            profile_for_rank.setdefault("year", "third-year")
            profile_for_rank.setdefault("degree", "Computer Science")
            ranked = rank_opportunities(items, decision.query, profile_for_rank)
            target_count = _requested_count(goal, 3)
            selected = ranked[:target_count]
            research_payload = {
                "query": decision.query, "category": decision.category,
                "source_mode": search_result.get("source_mode", "unknown"),
                "warning": search_result.get("warning", ""), "all_count": len(ranked),
                "target_count": target_count, "items": selected, "all_ranked": ranked,
                "profile": profile, "tool": search_tool,
            }
            update_step(task_id, "research", "done", research_payload)
        except Exception as exc:
            update_step(task_id, "research", "failed", error=str(exc))
            set_task_status(task_id, "failed", {"error": str(exc), "stage": "research"})
            return task_id

        rows = _prepare_opportunity_rows(selected)
        drafts = []
        for item in selected:
            draft_text = render_email_draft(item, profile)
            draft_key = _slug(str(item.get("company") or "company")) + "_" + _slug(str(item.get("title") or "opportunity"))
            drafts.append({"key": draft_key, "opportunity": item, "profile": profile, "draft": draft_text})
        prepared = {"workflow": "opportunity_search", "rows": rows, "drafts": drafts,
                    "filepath": "opportunities.xlsx", "sheet_name": "Opportunities"}
        upsert_step(task_id, "prepared_outputs", "Prepare reviewed spreadsheet rows and email drafts", "prepare_outputs", "done", prepared)
        upsert_step(task_id, "output_writes", "Write approved spreadsheet and email drafts", "save_to_sheet", "awaiting_approval", {})
        rows_hash = hash_json(rows)
        draft_hashes = {draft["key"]: hashlib.sha256(draft["draft"].encode("utf-8")).hexdigest() for draft in drafts}
        proposal = {
            "action_type": "opportunity_outputs",
            "approved_tools": ["save_to_sheet", "draft_email"],
            "rows_sha256": rows_hash,
            "draft_sha256_by_key": draft_hashes,
            "summary": f"Save {len(rows)} opportunity rows to output/opportunities.xlsx and write {len(drafts)} local email drafts.",
            "row_count": len(rows), "draft_count": len(drafts),
        }
        approval_id = create_approval(task_id, proposal)
        update_step(task_id, "output_writes", "awaiting_approval", {"approval_id": approval_id, "proposal": proposal})
        set_task_status(task_id, "awaiting_approval", {"planner_mode": planner_mode, "source_mode": research_payload["source_mode"],
                                                       "item_count": len(selected), "verified": False})
        append_audit(task_id, "outputs_prepared_for_review", {"row_count": len(rows), "draft_count": len(drafts), "approval_id": approval_id})
        return task_id

    # General web research workflow. Research is free/read-only; saving a report is approval-gated.
    search_step = upsert_step(task_id, "research", "Search the public web", "search_web", "pending")
    try:
        result = _record_tool_result(task_id, "research", "search_web", {"query": decision.query, "limit": decision.limit}, deadline=deadline)
        report = _make_report(goal, result)
        research_payload = {"query": decision.query, "source_mode": result.get("source_mode", "unknown"),
                            "count": result.get("count", 0), "results": result.get("results", []),
                            "warning": result.get("warning", "")}
        update_step(task_id, "research", "done", research_payload)
        if not result.get("results"):
            set_task_status(task_id, "paused", {"message": result.get("warning", "No live results found."),
                                                  "verified": False, "research_count": 0})
            append_audit(task_id, "research_empty", {"source_mode": result.get("source_mode")})
            return task_id
        filename = f"research_{task_id[:8]}.md"
        prepared = {"workflow": "web_research", "report": report, "filename": filename}
        upsert_step(task_id, "prepared_outputs", "Prepare research report", "prepare_report", "done", prepared)
        upsert_step(task_id, "output_writes", "Save approved research report", "save_report", "awaiting_approval", {})
        proposal = {"action_type": "research_report", "approved_tools": ["save_report"],
                    "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
                    "summary": f"Save a {len(report)}-character report to output/reports/{filename}.", "filename": filename}
        approval_id = create_approval(task_id, proposal)
        update_step(task_id, "output_writes", "awaiting_approval", {"approval_id": approval_id, "proposal": proposal})
        set_task_status(task_id, "awaiting_approval", {"planner_mode": planner_mode, "research_count": result.get("count", 0), "verified": False})
        return task_id
    except Exception as exc:
        update_step(task_id, "research", "failed", error=str(exc))
        set_task_status(task_id, "failed", {"error": str(exc), "stage": "web_research"})
        return task_id


def approve_task(task_id: str) -> None:
    decide_approval(task_id, "approved", "User approved the exact previewed action.")
    append_audit(task_id, "write_execution_approved", {})


def reject_task(task_id: str, note: str = "Rejected by user") -> None:
    decide_approval(task_id, "rejected", note)
    update_step(task_id, "output_writes", "rejected", error=note)
    set_task_status(task_id, "rejected", {"message": note, "verified": False})


def resume_approved_task(task_id: str) -> dict:
    """Execute the exact approved payload with retries and independent read-back verification."""
    task = get_task(task_id)
    if not task:
        raise ValueError("Task does not exist")
    if task.get("status") == "completed":
        return task.get("result_json") or {"verified": False, "message": "Task is already complete; no write was repeated."}
    approval = get_approval(task_id)
    if not approval or approval.get("status") != "approved":
        raise PermissionError("Task has no approved action. Review and approve the preview first.")
    prepared_step = get_step(task_id, "prepared_outputs")
    if not prepared_step:
        raise ValueError("Prepared output payload is missing; cannot safely resume.")
    prepared = prepared_step["result_json"]
    output_step = get_step(task_id, "output_writes")
    if not output_step:
        raise ValueError("Output write step is missing.")
    proposal = approval["proposed_action_json"]
    approval_id = approval["id"]
    settings = get_settings()
    deadline = time.monotonic() + settings.task_timeout_seconds
    update_step(task_id, "output_writes", "running", result={"approval_id": approval_id})
    set_task_status(task_id, "running", {"message": "Executing approved local writes.", "verified": False})
    last_error = ""

    for attempt in range(1, settings.max_retries + 1):
        update_step(task_id, "output_writes", "running", increment_attempts=True, error="")
        try:
            if prepared["workflow"] == "opportunity_search":
                rows = prepared["rows"]
                sheet_result = _call_with_deadline("save_to_sheet", {
                    "rows": rows, "filepath": prepared.get("filepath", "opportunities.xlsx"),
                    "sheet_name": prepared.get("sheet_name", "Opportunities"), "approval_id": approval_id,
                }, deadline)
                draft_results = []
                for draft in prepared["drafts"]:
                    draft_results.append(_call_with_deadline("draft_email", {
                        "opportunity": draft["opportunity"], "student_profile": draft["profile"],
                        "approval_id": approval_id,
                    }, deadline))
                # Re-read the workbook through the separately discovered MCP read tool.
                sheet_readback = _call_with_deadline("read_sheet", {
                    "filepath": prepared.get("filepath", "opportunities.xlsx"),
                    "sheet_name": prepared.get("sheet_name", "Opportunities"),
                }, deadline)
                actual_rows = sheet_readback.get("rows", [])
                expected_links = {str(r.get("link", "")).strip().rstrip("/").lower() for r in rows if r.get("link")}
                actual_links = [str(r.get("link", "")).strip().rstrip("/").lower() for r in actual_rows if r.get("link")]
                missing_links = sorted(expected_links - set(actual_links))
                duplicates = sorted({link for link in actual_links if actual_links.count(link) > 1})
                draft_paths = [r.get("path", "") for r in draft_results]
                file_verification = verify_files(draft_paths, [d["opportunity"].get("title", "") for d in prepared["drafts"]])
                verified = not missing_links and not duplicates and sheet_readback.get("exists") and file_verification["verified"]
                verification = {
                    "status": "VERIFIED" if verified else "FAILED", "verified": verified,
                    "sheet_path": sheet_readback.get("path"), "expected_links": sorted(expected_links),
                    "missing_links": missing_links, "duplicate_links": duplicates,
                    "sheet_row_count": sheet_readback.get("count", len(actual_rows)),
                    "sheet_write_result": sheet_result, "draft_verification": file_verification,
                }
                result_payload = {"verification": verification, "draft_paths": draft_paths,
                                  "sheet_path": sheet_readback.get("path"), "verified": verified}
            else:
                report_result = _call_with_deadline("save_report", {
                    "content": prepared["report"], "filename": prepared["filename"], "approval_id": approval_id,
                }, deadline)
                report_path = report_result.get("path", "")
                content = open(report_path, "r", encoding="utf-8").read() if report_path else ""
                verified = bool(report_path and content == prepared["report"])
                result_payload = {"verified": verified, "report_path": report_path,
                                  "verification": {"status": "VERIFIED" if verified else "FAILED", "verified": verified},
                                  "report_write_result": report_result}

            add_tool_run(task_id, "output_writes", "approved_output_writes", attempt, "done" if result_payload["verified"] else "failed", result=result_payload)
            if result_payload["verified"]:
                update_step(task_id, "output_writes", "verified", result=result_payload, error="")
                set_task_status(task_id, "completed", result_payload)
                append_audit(task_id, "task_verified_complete", result_payload["verification"])
                return result_payload
            last_error = "Write operation returned, but independent verification found missing or inconsistent output."
            update_step(task_id, "output_writes", "failed", result=result_payload, error=last_error)
            set_task_status(task_id, "paused", {**result_payload, "error": last_error, "verified": False})
            return result_payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            add_tool_run(task_id, "output_writes", "approved_output_writes", attempt, "failed", error=last_error)
            update_step(task_id, "output_writes", "running", error=last_error)
            append_audit(task_id, "approved_write_attempt_failed", {"attempt": attempt, "error": last_error})
            if time.monotonic() >= deadline:
                break
            if attempt < settings.max_retries:
                time.sleep(min(2 ** (attempt - 1), 3))
    update_step(task_id, "output_writes", "failed", error=last_error)
    paused_result = {"verified": False, "error": last_error, "message": "The approved write did not complete. Earlier research is preserved; turn off simulated failure or resolve the issue and resume."}
    set_task_status(task_id, "paused", paused_result)
    append_audit(task_id, "task_paused_after_retries", paused_result)
    return paused_result


def _create_opportunity_approval(task_id: str, profile: dict, research_payload: dict, goal: str) -> None:
    selected = research_payload.get("items", [])
    rows = _prepare_opportunity_rows(selected)
    drafts = []
    for item in selected:
        draft_text = render_email_draft(item, profile)
        draft_key = _slug(str(item.get("company") or "company")) + "_" + _slug(str(item.get("title") or "opportunity"))
        drafts.append({"key": draft_key, "opportunity": item, "profile": profile, "draft": draft_text})
    prepared = {"workflow": "opportunity_search", "rows": rows, "drafts": drafts,
                "filepath": "opportunities.xlsx", "sheet_name": "Opportunities"}
    upsert_step(task_id, "prepared_outputs", "Prepare reviewed spreadsheet rows and email drafts", "prepare_outputs", "done", prepared)
    upsert_step(task_id, "output_writes", "Write approved spreadsheet and email drafts", "save_to_sheet", "awaiting_approval", {})
    proposal = {
        "action_type": "opportunity_outputs", "approved_tools": ["save_to_sheet", "draft_email"],
        "rows_sha256": hash_json(rows),
        "draft_sha256_by_key": {d["key"]: hashlib.sha256(d["draft"].encode("utf-8")).hexdigest() for d in drafts},
        "summary": f"Save {len(rows)} opportunity rows to output/opportunities.xlsx and write {len(drafts)} local email drafts.",
        "row_count": len(rows), "draft_count": len(drafts),
    }
    create_approval(task_id, proposal)
    set_task_status(task_id, "awaiting_approval", {"source_mode": research_payload.get("source_mode", "unknown"),
                                                   "item_count": len(selected), "verified": False,
                                                   "resumed_from_checkpoint": True})
    append_audit(task_id, "outputs_prepared_for_review_after_resume", {"row_count": len(rows), "draft_count": len(drafts)})


def _create_report_approval(task_id: str, goal: str, result: dict) -> None:
    if not result.get("results"):
        set_task_status(task_id, "paused", {"message": result.get("warning", "No live results found."), "verified": False,
                                              "resumed_from_checkpoint": True})
        return
    report = _make_report(goal, result)
    filename = f"research_{task_id[:8]}.md"
    prepared = {"workflow": "web_research", "report": report, "filename": filename}
    upsert_step(task_id, "prepared_outputs", "Prepare research report", "prepare_report", "done", prepared)
    upsert_step(task_id, "output_writes", "Save approved research report", "save_report", "awaiting_approval", {})
    proposal = {"action_type": "research_report", "approved_tools": ["save_report"],
                "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
                "summary": f"Save a {len(report)}-character report to output/reports/{filename}.", "filename": filename}
    create_approval(task_id, proposal)
    set_task_status(task_id, "awaiting_approval", {"source_mode": result.get("source_mode", "unknown"),
                                                   "research_count": result.get("count", 0), "verified": False,
                                                   "resumed_from_checkpoint": True})


def resume_research_task(task_id: str) -> dict:
    """Resume a task interrupted before its approval stage; safe read-only work may be rerun."""
    task = get_task(task_id)
    deadline = time.monotonic() + get_settings().task_timeout_seconds
    if not task:
        raise ValueError("Task does not exist")
    if task.get("status") == "completed":
        return task.get("result_json") or {"verified": False, "message": "Task is already complete."}
    approval = get_approval(task_id)
    if approval and approval.get("status") == "approved":
        return resume_approved_task(task_id)
    if approval and approval.get("status") == "rejected":
        return {"verified": False, "message": "The prior proposal was rejected. Start a new task to create a new proposal."}
    if approval and approval.get("status") == "pending":
        set_task_status(task_id, "awaiting_approval", {"message": "A prepared action is already waiting for approval.", "verified": False})
        return {"verified": False, "message": "Review and approve the existing proposal; it was not regenerated."}

    plan_data = task.get("plan_json", {})
    decision_data = plan_data.get("decision")
    from models.schemas import PlanDecision
    # If the process stopped immediately after task creation, complete discovery before creating a plan.
    if not decision_data:
        discovery = get_step(task_id, "tool_discovery")
        if not discovery or discovery.get("status") != "done":
            upsert_step(task_id, "tool_discovery", "Discover MCP tools", "list_tools", "running")
            try:
                discovered = discover_mcp_tools()
                update_step(task_id, "tool_discovery", "done", {"tools": discovered})
            except Exception as exc:
                update_step(task_id, "tool_discovery", "failed", error=f"{type(exc).__name__}: {exc}")
                set_task_status(task_id, "paused", {"error": str(exc), "verified": False})
                return {"verified": False, "error": str(exc)}
        discovery = get_step(task_id, "tool_discovery")
        discovered_names = [item["name"] for item in discovery["result_json"].get("tools", [])]
        decision, planner_mode = plan_goal(task["goal"])
        set_task_plan(task_id, {"decision": decision.model_dump(), "planner_mode": planner_mode,
                                "profile": plan_data.get("profile", {}), "discovered_tool_names": discovered_names})
        plan_data = get_task(task_id).get("plan_json", {})
        decision_data = plan_data.get("decision")
    if not decision_data:
        raise ValueError("Saved plan could not be reconstructed safely.")
    decision = PlanDecision.model_validate(decision_data)
    profile = plan_data.get("profile", {})
    if decision.workflow == "unsupported":
        set_task_status(task_id, "blocked", {"message": decision.unsupported_reason, "verified": False})
        return {"verified": False, "message": decision.unsupported_reason}

    discovery = get_step(task_id, "tool_discovery")
    if not discovery or discovery.get("status") != "done":
        upsert_step(task_id, "tool_discovery", "Discover MCP tools", "list_tools", "running")
        try:
            discovered = discover_mcp_tools()
            update_step(task_id, "tool_discovery", "done", {"tools": discovered})
            append_audit(task_id, "tools_rediscovered_on_resume", {"tool_names": [t["name"] for t in discovered]})
            discovery = get_step(task_id, "tool_discovery")
        except Exception as exc:
            update_step(task_id, "tool_discovery", "failed", error=f"{type(exc).__name__}: {exc}")
            set_task_status(task_id, "paused", {"error": str(exc), "verified": False})
            return {"verified": False, "error": str(exc)}

    discovered_names = [item["name"] for item in (discovery or {}).get("result_json", {}).get("tools", [])]
    required_tools = (["search_internships", "save_to_sheet", "read_sheet", "draft_email"] if decision.workflow == "opportunity_search" and decision.category == "internship"
                      else ["search_jobs", "save_to_sheet", "read_sheet", "draft_email"] if decision.workflow == "opportunity_search"
                      else ["search_web", "save_report"])
    missing_tools = sorted(set(required_tools) - set(discovered_names))
    if missing_tools:
        message = "Required capabilities were not discovered from the MCP server: " + ", ".join(missing_tools)
        set_task_status(task_id, "blocked", {"message": message, "missing_tools": missing_tools, "verified": False})
        return {"verified": False, "message": message}

    research = get_step(task_id, "research")
    empty_web_results = bool(research and decision.workflow == "web_research" and research.get("status") == "done"
                             and not research.get("result_json", {}).get("results"))
    if not research or research.get("status") != "done" or empty_web_results:
        if decision.workflow == "opportunity_search":
            tool = "search_internships" if decision.category == "internship" else "search_jobs"
            upsert_step(task_id, "research", "Search and rank opportunities", tool, "pending")
            try:
                search_result = _record_tool_result(task_id, "research", tool, {"query": decision.query, "limit": decision.limit}, deadline=deadline)
                profile_for_rank = dict(profile)
                profile_for_rank.setdefault("year", "third-year")
                profile_for_rank.setdefault("degree", "Computer Science")
                ranked = rank_opportunities(search_result.get("items", []), decision.query, profile_for_rank)
                target_count = _requested_count(task["goal"], 3)
                research_payload = {"query": decision.query, "category": decision.category,
                                    "source_mode": search_result.get("source_mode", "unknown"),
                                    "warning": search_result.get("warning", ""), "all_count": len(ranked),
                                    "target_count": target_count, "items": ranked[:target_count],
                                    "all_ranked": ranked, "profile": profile, "tool": tool}
                update_step(task_id, "research", "done", research_payload)
                research = get_step(task_id, "research")
            except Exception as exc:
                update_step(task_id, "research", "failed", error=str(exc))
                set_task_status(task_id, "paused", {"error": str(exc), "stage": "research", "verified": False})
                return {"verified": False, "error": str(exc)}
        else:
            upsert_step(task_id, "research", "Search the public web", "search_web", "pending")
            try:
                result = _record_tool_result(task_id, "research", "search_web", {"query": decision.query, "limit": decision.limit}, deadline=deadline)
                research_payload = {"query": decision.query, "source_mode": result.get("source_mode", "unknown"),
                                    "count": result.get("count", 0), "results": result.get("results", []),
                                    "warning": result.get("warning", "")}
                update_step(task_id, "research", "done", research_payload)
                research = get_step(task_id, "research")
            except Exception as exc:
                update_step(task_id, "research", "failed", error=str(exc))
                set_task_status(task_id, "paused", {"error": str(exc), "stage": "web_research", "verified": False})
                return {"verified": False, "error": str(exc)}

    # Reuse the saved research payload; never repeat successful research just to prepare output files.
    prepared_step = get_step(task_id, "prepared_outputs")
    if prepared_step:
        if not get_approval(task_id) or get_approval(task_id).get("status") == "rejected":
            prepared = prepared_step["result_json"]
            if prepared.get("workflow") == "opportunity_search":
                _create_opportunity_approval(task_id, profile, research["result_json"], task["goal"])
            elif prepared.get("workflow") == "web_research":
                stored = research["result_json"]
                result = {"query": stored.get("query", decision.query), "source_mode": stored.get("source_mode", "unknown"),
                          "count": stored.get("count", 0), "results": stored.get("results", []), "warning": stored.get("warning", "")}
                _create_report_approval(task_id, task["goal"], result)
        else:
            set_task_status(task_id, "awaiting_approval", {"message": "Existing prepared outputs are ready for review.", "verified": False})
        return {"verified": False, "status": "awaiting_approval", "message": "Resumed from the saved checkpoint."}

    research_payload = research["result_json"] if research else {}
    if decision.workflow == "opportunity_search":
        _create_opportunity_approval(task_id, profile, research_payload, task["goal"])
    else:
        result = {"query": research_payload.get("query", decision.query), "source_mode": research_payload.get("source_mode", "unknown"),
                  "count": research_payload.get("count", 0), "results": research_payload.get("results", []),
                  "warning": research_payload.get("warning", "")}
        _create_report_approval(task_id, task["goal"], result)
    return {"verified": False, "status": "awaiting_approval", "message": "Research checkpoint reused; outputs are ready for review."}
