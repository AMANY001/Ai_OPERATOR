import os
import openpyxl
import pytest
from tools.spreadsheet_tools import save_to_sheet_impl, read_sheet_impl


def row(link, title="Python Intern"):
    return {"title": title, "company": "Sample Co", "link": link, "category": "internship", "is_sample": True}


def test_sheet_write_is_idempotent_and_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("SIMULATE_SHEET_FAILURE", "0")
    one = save_to_sheet_impl([row("https://careers.example/role")])
    two = save_to_sheet_impl([row("https://careers.example/role/")])
    read = read_sheet_impl()
    assert one["saved"] == 1
    assert two["saved"] == 0
    assert two["skipped_duplicates"] == 1
    assert read["count"] == 1
    assert read["rows"][0]["title"] == "Python Intern"


def test_simulated_failure_occurs_before_workbook_change(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("SIMULATE_SHEET_FAILURE", "1")
    with pytest.raises(RuntimeError, match="SIMULATED_SHEET_FAILURE"):
        save_to_sheet_impl([row("https://careers.example/role")])
    assert not (tmp_path / "output" / "opportunities.xlsx").exists()


def test_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    with pytest.raises(ValueError, match="inside the configured output directory"):
        save_to_sheet_impl([row("https://careers.example/role")], "../outside.xlsx")
