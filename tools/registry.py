"""Local metadata for capability health and risk classification."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    risk: str
    needs_network: bool

TOOL_METADATA = {
    "search_internships": ToolMetadata("search_internships", "Search internship leads; falls back to explicitly labelled sample data.", "READ_ONLY", True),
    "search_jobs": ToolMetadata("search_jobs", "Search job leads; falls back to explicitly labelled sample data.", "READ_ONLY", True),
    "search_web": ToolMetadata("search_web", "Search the public web and return unverified search leads.", "READ_ONLY", True),
    "save_to_sheet": ToolMetadata("save_to_sheet", "Append records to an output workbook with URL-based deduplication.", "LOCAL_WRITE", False),
    "read_sheet": ToolMetadata("read_sheet", "Read and return rows from a workbook under the output directory.", "READ_ONLY", False),
    "draft_email": ToolMetadata("draft_email", "Create and verify a local email draft; never sends email.", "LOCAL_WRITE", False),
    "browser_open": ToolMetadata("browser_open", "Open a public HTTP(S) page using local Playwright.", "READ_ONLY", True),
    "browser_extract": ToolMetadata("browser_extract", "Extract readable text from a public HTTP(S) page.", "READ_ONLY", True),
    "save_report": ToolMetadata("save_report", "Save a research report under output/reports after approval.", "LOCAL_WRITE", False),
}


def get_tool_metadata() -> list[dict]:
    return [vars(v) for v in TOOL_METADATA.values()]
