"""End-to-end workflow tests with MCP transport mocked; real MCP discovery has a separate test."""
from __future__ import annotations
import hashlib
import json
from agent import start_task, approve_task, resume_approved_task
from state import get_task, get_step, get_approval, get_approval_by_id
from tools.email_tools import draft_email_impl, render_email_draft, _slug
from tools.internship_tools import search_opportunities_impl
from tools.spreadsheet_tools import save_to_sheet_impl, read_sheet_impl
from agent import hash_json


def test_scenario_b_recovers_without_research_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("MAX_RETRIES", "3")
    monkeypatch.setenv("SIMULATE_SHEET_FAILURE", "1")
    import agent
    monkeypatch.setattr(agent.time, "sleep", lambda *_: None)
    tool_names = ["search_internships", "search_jobs", "search_web", "save_to_sheet", "read_sheet", "draft_email", "browser_open", "browser_extract", "save_report"]
    monkeypatch.setattr(agent, "discover_mcp_tools", lambda: [{"name": n, "description": "test tool", "input_schema": {}} for n in tool_names])
    search_calls = {"count": 0}

    def fake_call_tool(name, args, timeout_seconds=None):
        if name == "search_internships":
            search_calls["count"] += 1
            return search_opportunities_impl(args["query"], args.get("limit", 20), "internship")
        if name == "save_to_sheet":
            approval = get_approval_by_id(args["approval_id"])
            assert approval and approval["status"] == "approved"
            proposal = approval["proposed_action_json"]
            assert "save_to_sheet" in proposal["approved_tools"]
            assert hash_json(args["rows"]) == proposal["rows_sha256"]
            return save_to_sheet_impl(args["rows"], args.get("filepath", "opportunities.xlsx"), args.get("sheet_name", "Opportunities"))
        if name == "draft_email":
            approval = get_approval_by_id(args["approval_id"])
            assert approval and approval["status"] == "approved"
            key = _slug(str(args["opportunity"].get("company") or "company")) + "_" + _slug(str(args["opportunity"].get("title") or "opportunity"))
            text = render_email_draft(args["opportunity"], args["student_profile"])
            assert hashlib.sha256(text.encode()).hexdigest() == approval["proposed_action_json"]["draft_sha256_by_key"][key]
            return draft_email_impl(args["opportunity"], args["student_profile"], True)
        if name == "read_sheet":
            return read_sheet_impl(args.get("filepath", "opportunities.xlsx"), args.get("sheet_name", "Opportunities"))
        raise AssertionError(f"Unexpected tool call: {name}")

    monkeypatch.setattr(agent, "call_tool", fake_call_tool)
    task_id = start_task(
        "Find three internships for a third-year computer science student, compare eligibility, save the best matches to a spreadsheet, and draft personalised emails.",
        {"name": "Alex Example", "degree": "Computer Science", "year": "third-year", "skills": ["Python", "SQL"]},
    )
    assert get_task(task_id)["status"] == "awaiting_approval"
    assert get_step(task_id, "research")["status"] == "done"
    assert search_calls["count"] == 1

    approve_task(task_id)
    first_try = resume_approved_task(task_id)
    assert first_try["verified"] is False
    assert get_task(task_id)["status"] == "paused"
    assert read_sheet_impl()["count"] == 0
    assert search_calls["count"] == 1

    monkeypatch.setenv("SIMULATE_SHEET_FAILURE", "0")
    final = resume_approved_task(task_id)
    assert final["verified"] is True, final
    assert get_task(task_id)["status"] == "completed"
    assert read_sheet_impl()["count"] == 3
    assert len(final["draft_paths"]) == 3
    assert search_calls["count"] == 1  # Research was not repeated during write recovery.
    # A repeated resume of a completed task must not repeat any writes.
    repeated = resume_approved_task(task_id)
    assert repeated["verified"] is True
    assert read_sheet_impl()["count"] == 3
