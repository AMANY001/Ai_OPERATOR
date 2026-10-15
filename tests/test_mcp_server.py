import pytest
pytest.importorskip("mcp", reason="MCP SDK is installed by requirements.txt; skipped in this offline build environment")
from mcp_client import list_tools

def test_mcp_server_discovers_expected_tools():
    tools = list_tools()
    names = {item["name"] for item in tools}
    assert {"search_internships", "search_jobs", "search_web", "save_to_sheet", "read_sheet", "draft_email", "browser_open", "browser_extract", "save_report"}.issubset(names)
