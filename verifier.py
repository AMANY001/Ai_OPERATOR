"""Independent verification helpers for persisted artifacts."""
from __future__ import annotations
from pathlib import Path
from tools.spreadsheet_tools import read_sheet_impl


def verify_spreadsheet(expected_rows: list[dict], filepath: str = "opportunities.xlsx", sheet_name: str = "Opportunities") -> dict:
    actual = read_sheet_impl(filepath, sheet_name)
    expected_urls = {str(row.get("link", "")).strip().rstrip("/").lower() for row in expected_rows if row.get("link")}
    actual_urls = [str(row.get("link", "")).strip().rstrip("/").lower() for row in actual.get("rows", []) if row.get("link")]
    actual_set = set(actual_urls)
    missing = sorted(expected_urls - actual_set)
    duplicates = sorted({url for url in actual_urls if actual_urls.count(url) > 1})
    verified = actual.get("exists") and not missing and not duplicates
    return {
        "status": "VERIFIED" if verified else "FAILED",
        "path": actual.get("path"),
        "sheet_name": sheet_name,
        "expected_count": len(expected_urls),
        "actual_count": actual.get("count", 0),
        "missing_urls": missing,
        "duplicate_urls": duplicates,
        "verified": verified,
    }


def verify_files(paths: list[str], required_text: list[str] | None = None) -> dict:
    required_text = required_text or []
    results = []
    for index, path_str in enumerate(paths):
        path = Path(path_str)
        item = {"path": str(path), "exists": path.is_file(), "content_ok": False}
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            phrase = required_text[index] if index < len(required_text) else ""
            item["content_ok"] = (not phrase) or (phrase.lower() in content.lower())
            item["bytes"] = path.stat().st_size
        results.append(item)
    return {"status": "VERIFIED" if all(r["exists"] and r["content_ok"] for r in results) else "FAILED",
            "verified": all(r["exists"] and r["content_ok"] for r in results), "files": results}
