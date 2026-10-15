"""Local stdio MCP server. Write tools require an approved, payload-bound approval ID."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from tools.internship_tools import search_opportunities_impl
from tools.web_search import search_web_impl
from tools.spreadsheet_tools import save_to_sheet_impl, read_sheet_impl
from tools.email_tools import draft_email_impl, render_email_draft
from tools.browser_tools import browser_open_impl, browser_extract_impl
from config import ensure_directories, get_settings
from state import get_approval_by_id

mcp = FastMCP("AI Operator", json_response=True)


def _sha256(value) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_approved(approval_id: str, tool_name: str) -> dict:
    if not approval_id:
        raise PermissionError(f"{tool_name} requires an explicit approved approval_id.")
    approval = get_approval_by_id(approval_id)
    if not approval or approval.get("status") != "approved":
        raise PermissionError("No matching approved action exists. The UI approval gate must be completed first.")
    proposed = approval.get("proposed_action_json") or {}
    if tool_name not in proposed.get("approved_tools", []):
        raise PermissionError(f"Approval does not cover tool '{tool_name}'.")
    return proposed


@mcp.tool()
def search_internships(query: str, limit: int = 20) -> dict:
    """Search web leads for internships; returns labelled local sample data when no live leads are available."""
    return search_opportunities_impl(query, limit, "internship")


@mcp.tool()
def search_jobs(query: str, limit: int = 20) -> dict:
    """Search public job leads; results are unverified and sample records are explicitly labelled."""
    return search_opportunities_impl(query, limit, "job")


@mcp.tool()
def search_web(query: str, limit: int = 10) -> dict:
    """Search the public web and return search leads with URLs and retrieval timestamps."""
    return search_web_impl(query, limit)


@mcp.tool()
def save_to_sheet(rows: list[dict], filepath: str = "opportunities.xlsx", sheet_name: str = "Opportunities", approval_id: str = "") -> dict:
    """Append rows to an output workbook. Requires approval bound to the exact reviewed rows."""
    proposed = _require_approved(approval_id, "save_to_sheet")
    if _sha256(rows) != proposed.get("rows_sha256"):
        raise PermissionError("Rows differ from the content reviewed during approval. Request approval again.")
    return save_to_sheet_impl(rows, filepath, sheet_name)


@mcp.tool()
def read_sheet(filepath: str = "opportunities.xlsx", sheet_name: str = "Opportunities") -> dict:
    """Read rows from a workbook inside the configured output directory."""
    return read_sheet_impl(filepath, sheet_name)


@mcp.tool()
def draft_email(opportunity: dict, student_profile: dict, approval_id: str = "") -> dict:
    """Write and verify a local email draft. It never sends email and requires approval for the reviewed draft."""
    proposed = _require_approved(approval_id, "draft_email")
    expected = proposed.get("draft_sha256_by_key", {})
    from tools.email_tools import _slug
    key = _slug(str(opportunity.get("company") or "company")) + "_" + _slug(str(opportunity.get("title") or "opportunity"))
    text = render_email_draft(opportunity, student_profile)
    if expected.get(key) != hashlib.sha256(text.encode("utf-8")).hexdigest():
        raise PermissionError("Draft content differs from the version reviewed during approval. Request approval again.")
    return draft_email_impl(opportunity, student_profile, write=True)


@mcp.tool()
def browser_open(url: str, timeout_ms: int = 20000) -> dict:
    """Load a public HTTP(S) website with local Playwright; cannot submit forms or make purchases."""
    return browser_open_impl(url, timeout_ms)


@mcp.tool()
def browser_extract(url: str, max_chars: int = 12000, timeout_ms: int = 20000) -> dict:
    """Extract readable text from a public HTTP(S) page using local Playwright."""
    return browser_extract_impl(url, max_chars, timeout_ms)


@mcp.tool()
def save_report(content: str, filename: str = "research_report.md", approval_id: str = "") -> dict:
    """Save a Markdown or text research report under output/reports after exact-content approval."""
    proposed = _require_approved(approval_id, "save_report")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if digest != proposed.get("report_sha256"):
        raise PermissionError("Report content differs from the content reviewed during approval.")
    if len(content) > 100_000:
        raise ValueError("Report exceeds the 100 KB size limit.")
    ensure_directories()
    safe_name = Path(filename).name
    if not safe_name or Path(safe_name).suffix.lower() not in {".md", ".txt"}:
        raise ValueError("Report filename must be a .md or .txt filename.")
    path = (get_settings().output_dir / "reports" / safe_name).resolve()
    if (get_settings().output_dir / "reports").resolve() not in path.parents:
        raise ValueError("Report path is outside output/reports.")
    path.write_text(content, encoding="utf-8")
    if path.read_text(encoding="utf-8") != content:
        raise IOError("Report write verification failed.")
    return {"path": str(path), "verified": True, "bytes": path.stat().st_size}


def main() -> None:
    ensure_directories()
    # Keep stdout reserved for MCP stdio protocol; do not print from this process.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
