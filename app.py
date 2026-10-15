"""Streamlit front end for the AI Operator local-first workflow."""
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
import streamlit as st
# Streamlit Community Cloud secrets are copied into environment variables before child MCP processes start.
try:
    for _secret_key in ("GEMINI_API_KEY", "GEMINI_MODEL", "DATABASE_PATH", "OUTPUT_DIR"):
        if not os.getenv(_secret_key) and _secret_key in st.secrets:
            os.environ[_secret_key] = str(st.secrets[_secret_key])
except Exception:
    # Local .env configuration remains the normal development path.
    pass
from config import ensure_directories, get_settings
from state import init_db, list_tasks, get_task, list_steps, get_step, get_approval, get_audit_log
from agent import start_task, approve_task, reject_task, resume_approved_task, resume_research_task

ensure_directories()
init_db()
st.set_page_config(page_title="AI Operator", page_icon="⚙️", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px;}
.hero {padding: 1.3rem 1.5rem; border: 1px solid rgba(128,128,128,.25); border-radius: 18px; margin-bottom: 1rem;
       background: linear-gradient(120deg, rgba(91,95,230,.12), rgba(0,180,160,.06));}
.hero h1 {margin-bottom: .25rem; letter-spacing: -.04em;}
.muted {opacity: .72; font-size: .92rem;}
div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.2); padding: .6rem .75rem; border-radius: 12px;}
</style>
<div class="hero">
  <h1>⚙️ AI Operator</h1>
  <div class="muted">Plan → execute permitted actions → preserve progress → recover → verify.</div>
</div>
""", unsafe_allow_html=True)

settings = get_settings()
with st.sidebar:
    st.header("Control centre")
    st.caption("Local-first execution. Research results are not treated as verified facts until checked.")
    simulation = st.toggle("Simulate spreadsheet failure", value=os.getenv("SIMULATE_SHEET_FAILURE", "0") == "1",
                           help="Demo only: makes spreadsheet writes fail before touching the workbook.")
    os.environ["SIMULATE_SHEET_FAILURE"] = "1" if simulation else "0"
    st.divider()
    st.subheader("Environment")
    st.write("**Python:**", Path(os.sys.executable).name)
    st.write("**Gemini:**", "Configured" if settings.gemini_api_key else "Optional / not configured")
    st.write("**SQLite:**", str(settings.database_path))
    st.write("**Output:**", str(settings.output_dir))
    st.write("**MCP:**", "Enabled through local stdio server")
    st.info("This release automates research and approved local outputs. It does not submit job applications, send emails, or purchase tickets.")

with st.form("goal_form", clear_on_submit=False):
    st.subheader("What should the operator do?")
    default_goal = "Find three internships for a third-year computer science student, compare eligibility, save the best matches to a spreadsheet with links, and draft personalised emails for each."
    goal = st.text_area("Natural-language goal", value=default_goal, height=105,
                        placeholder="Describe the goal, constraints, and desired outputs...")
    c1, c2 = st.columns(2)
    with c1:
        student_name = st.text_input("Name for draft personalization (optional)", value="")
        degree = st.text_input("Degree / field", value="Computer Science")
        year = st.text_input("Education year", value="third-year")
    with c2:
        skills = st.text_input("Skills (comma-separated)", value="Python, machine learning, SQL, Git")
        location = st.text_input("Preferred location (optional)", value="India / Remote")
        st.caption("Profile information is only used in ranking and drafts; verify the generated text before using it.")
    submitted = st.form_submit_button("▶ Plan and research", type="primary", use_container_width=True)

if submitted:
    if not goal.strip():
        st.error("Enter a goal first.")
    else:
        profile = {"name": student_name.strip(), "degree": degree.strip(), "year": year.strip(),
                   "skills": [s.strip() for s in skills.split(",") if s.strip()], "location": location.strip()}
        with st.spinner("Discovering MCP tools, validating the goal, and executing safe research steps..."):
            task_id = start_task(goal.strip(), profile)
        st.session_state["active_task_id"] = task_id
        st.session_state["task_history_selector"] = task_id
        st.rerun()

tasks = list_tasks(100)
if not tasks:
    st.info("Start with the goal above. Your task history and step state are persisted in SQLite.")
    st.stop()

all_ids = [task["id"] for task in tasks]
active_id = st.session_state.get("active_task_id", all_ids[0])
if active_id not in all_ids:
    active_id = all_ids[0]
with st.sidebar:
    selected_id = st.selectbox(
        "Task history", all_ids, index=all_ids.index(active_id), key="task_history_selector",
        format_func=lambda tid: f"{next((t['status'].upper() for t in tasks if t['id'] == tid), 'TASK')} · {next((t['goal'][:56] for t in tasks if t['id'] == tid), tid)}"
    )
st.session_state["active_task_id"] = selected_id
active_id = selected_id

task = get_task(active_id)
if not task:
    st.error("Selected task could not be loaded from SQLite.")
    st.stop()
steps = list_steps(active_id)
step_map = {step["step_key"]: step for step in steps}
status = task["status"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Task status", status.replace("_", " ").title())
m2.metric("Execution steps", len(steps))
m3.metric("Completed / verified", sum(s["status"] in {"done", "verified"} for s in steps))
m4.metric("Retry attempts", sum(int(s["attempts"]) for s in steps))

st.markdown("### Current goal")
st.write(task["goal"])

if status == "blocked":
    st.warning(task.get("result_json", {}).get("message", "This goal is not supported by the installed adapters."))
    st.caption("No external action was attempted. Add a provider-specific integration before enabling consequential automation.")
elif status == "failed":
    st.error(task.get("result_json", {}).get("error", "Task failed. See the step log for details."))
elif status == "paused":
    st.warning(task.get("result_json", {}).get("message", task.get("result_json", {}).get("error", "Task is paused.")))
elif status == "rejected":
    st.info("The proposed output was rejected. No approved write was performed after rejection.")
elif status == "completed":
    result = task.get("result_json", {})
    if result.get("verified"):
        st.success("VERIFIED: the requested local output was written and independently checked.")
    else:
        st.warning("The task has a completion record, but the result is not marked verified. Review the report below.")

research_step = step_map.get("research")
research_payload = (research_step or {}).get("result_json", {})
items = research_payload.get("items", [])
if items:
    st.markdown("### Ranked opportunities")
    if research_payload.get("source_mode") == "local_sample_fallback":
        st.warning("Showing synthetic fallback records because live search returned no usable results. These are NOT real openings.")
    elif research_payload.get("source_mode") == "live_search":
        st.warning("Live search leads are unverified. Confirm availability, eligibility, deadline, and application route on the official site.")
    if research_payload.get("warning"):
        st.caption(research_payload["warning"])
    df = pd.DataFrame(items)
    display_cols = [c for c in ["fit_score", "title", "company", "location", "eligibility", "eligibility_status", "deadline", "link", "verification_status", "is_sample"] if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True,
                 column_config={"link": st.column_config.LinkColumn("Source / posting", display_text="Open link"),
                                "fit_score": st.column_config.ProgressColumn("Fit score", min_value=0, max_value=100, format="%d")})
    with st.expander("Ranking explanation and source data"):
        for item in items:
            st.markdown(f"**{item.get('fit_score', 0)}/100 — {item.get('title', 'Untitled')}**")
            for reason in item.get("ranking_reasons", []):
                st.write(f"• {reason}")
            st.caption(item.get("description", ""))

prepared_step = step_map.get("prepared_outputs")
prepared = (prepared_step or {}).get("result_json", {})
approval = get_approval(active_id)

if status == "awaiting_approval" and prepared and (not approval or approval.get("status") == "pending"):
    st.markdown("---\n### Human approval required")
    st.warning("Nothing in this section is written until you approve the exact proposed local output.")
    proposal = (approval or {}).get("proposed_action_json", {})
    st.write(proposal.get("summary", "Review the proposed changes below."))
    if prepared.get("workflow") == "opportunity_search":
        st.markdown("**Proposed spreadsheet rows**")
        st.dataframe(pd.DataFrame(prepared.get("rows", [])), use_container_width=True, hide_index=True)
        st.markdown("**Personalised email drafts (files only; no email will be sent)**")
        for index, draft in enumerate(prepared.get("drafts", []), 1):
            with st.expander(f"Draft {index}: {draft['opportunity'].get('title', 'Opportunity')} — {draft['opportunity'].get('company', 'Company')}"):
                st.code(draft.get("draft", ""), language="text")
    elif prepared.get("workflow") == "web_research":
        st.markdown("**Proposed research report**")
        st.markdown(prepared.get("report", ""))

    b1, b2 = st.columns(2)
    with b1:
        if st.button("✅ Approve and execute these local writes", type="primary", use_container_width=True, key=f"approve_{active_id}"):
            try:
                approve_task(active_id)
                with st.spinner("Writing approved outputs, retrying transient failures, and verifying by reading them back..."):
                    outcome = resume_approved_task(active_id)
                st.session_state["last_outcome"] = outcome
            except Exception as exc:
                st.error(f"Approval or execution failed: {type(exc).__name__}: {exc}")
            st.rerun()
    with b2:
        if st.button("Reject proposed outputs", use_container_width=True, key=f"reject_{active_id}"):
            try:
                reject_task(active_id)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not reject action: {exc}")

if status in {"failed", "running", "paused"} and not (approval and approval.get("status") in {"approved", "pending", "rejected"}):
    st.markdown("### Resume from saved checkpoint")
    st.info("The agent will reuse successful steps. Only a missing or unfinished read-only research step may be retried; output writes still require approval.")
    if st.button("↻ Resume research / preparation", type="primary", key=f"resume_research_{active_id}"):
        with st.spinner("Loading saved plan and resuming from the first incomplete step..."):
            outcome = resume_research_task(active_id)
        st.session_state["last_outcome"] = outcome
        st.rerun()

if status in {"paused", "failed", "running", "awaiting_approval"} and approval and approval.get("status") == "approved":
    st.markdown("### Resume approved action")
    st.info("The approved payload and earlier research are stored. Resumption reuses them; it does not rerun the search. Duplicate workbook rows are skipped.")
    if st.button("↻ Resume the failed step", type="primary", key=f"resume_{active_id}"):
        with st.spinner("Resuming the existing approved write and verifying the result..."):
            outcome = resume_approved_task(active_id)
        st.session_state["last_outcome"] = outcome
        st.rerun()

if status == "completed":
    result = task.get("result_json", {})
    verification = result.get("verification", {})
    st.markdown("### Final verification report")
    if verification.get("status") == "VERIFIED" or result.get("verified"):
        st.success("VERIFIED — read-back checks passed.")
    else:
        st.error("UNVERIFIED — inspect missing outputs and retry status below.")
    st.json(result)
    for path_str in ([result.get("sheet_path")] + result.get("draft_paths", []) + [result.get("report_path")]):
        if path_str and Path(path_str).is_file():
            path = Path(path_str)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if path.suffix.lower() == ".xlsx" else "text/plain"
            with path.open("rb") as handle:
                st.download_button(f"Download {path.name}", data=handle.read(), file_name=path.name, mime=mime, key=f"download_{active_id}_{path.name}")

with st.expander("Execution plan and durable step state", expanded=True):
    for idx, step in enumerate(steps, 1):
        icon = {"done": "✅", "verified": "🔎", "running": "⏳", "awaiting_approval": "🛂", "failed": "❌", "blocked": "⛔", "rejected": "🚫", "paused": "⏸️"}.get(step["status"], "▫️")
        st.markdown(f"**{icon} {idx}. {step['name']}** — `{step['status']}` · tool: `{step['tool_name'] or 'internal'}` · attempts: {step['attempts']}")
        if step.get("error"):
            st.error(step["error"])
        if step.get("step_key") == "tool_discovery":
            tool_result = step.get("result_json", {}).get("tools", [])
            if tool_result:
                st.dataframe(pd.DataFrame([{"name": t["name"], "description": t["description"]} for t in tool_result]), use_container_width=True, hide_index=True)
        if step.get("step_key") == "output_writes" and step.get("status") in {"failed", "paused"}:
            st.caption("The persisted research and approved payload remain available for recovery.")

with st.expander("Audit trail", expanded=False):
    log = get_audit_log(active_id, limit=200)
    if log:
        audit_df = pd.DataFrame([{"timestamp": row["timestamp"], "event": row["event"], "details": row["details_json"]} for row in log])
        st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No audit events recorded yet.")

st.caption("Production note: this is a local-first foundation. It does not submit forms, send email, execute payments, or claim live ticket availability. Provider-specific integrations require their own authorization, tests, and approval screens.")
