"""Non-secret environment diagnostics. Run: python diagnostics.py"""
from __future__ import annotations
import importlib.util
import os
import sys
from config import ensure_directories, get_settings
from state import init_db


def main() -> int:
    ensure_directories()
    settings = get_settings()
    init_db()
    print("AI Operator diagnostics")
    print("Python executable:", sys.executable)
    print("Python version:", sys.version.split()[0])
    for module in ["streamlit", "openpyxl", "pandas", "pydantic", "google.genai", "ddgs", "playwright", "mcp"]:
        available = importlib.util.find_spec(module) is not None
        print(f"Dependency {module}:", "available" if available else "MISSING")
    print("Gemini API key:", "configured (value hidden)" if settings.gemini_api_key else "not configured (offline planner will be used)")
    print("Database:", settings.database_path, "exists:", settings.database_path.exists())
    print("Output directory:", settings.output_dir, "exists:", settings.output_dir.is_dir())
    print("Spreadsheet failure simulation:", os.getenv("SIMULATE_SHEET_FAILURE", "0"))
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            executable = p.chromium.executable_path
            print("Playwright Chromium binary:", "available" if os.path.exists(executable) else "MISSING", executable)
    except Exception as exc:
        print("Playwright browser status:", f"unavailable ({type(exc).__name__}: {exc})")
    try:
        from mcp_client import list_tools
        tools = list_tools()
        print("MCP server:", "available", f"({len(tools)} tools discovered)")
    except Exception as exc:
        print("MCP server:", f"unavailable ({type(exc).__name__}: {exc})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
