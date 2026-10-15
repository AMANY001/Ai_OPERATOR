"""Central permission policy. The LLM cannot override these classifications."""
from __future__ import annotations
import os

READ_ONLY = "READ_ONLY"
LOCAL_WRITE = "LOCAL_WRITE"
EXTERNAL_ACTION = "EXTERNAL_ACTION"
FINANCIAL_ACTION = "FINANCIAL_ACTION"

RISK_BY_TOOL = {
    "search_internships": READ_ONLY,
    "search_jobs": READ_ONLY,
    "search_web": READ_ONLY,
    "read_sheet": READ_ONLY,
    "browser_open": READ_ONLY,
    "browser_extract": READ_ONLY,
    "save_to_sheet": LOCAL_WRITE,
    "draft_email": LOCAL_WRITE,
    "save_report": LOCAL_WRITE,
    "submit_job_application": EXTERNAL_ACTION,
    "send_email": EXTERNAL_ACTION,
    "book_ticket": FINANCIAL_ACTION,
    "purchase": FINANCIAL_ACTION,
}


def risk_for(tool_name: str) -> str:
    return RISK_BY_TOOL.get(tool_name, EXTERNAL_ACTION)  # unknown tools fail closed


def requires_approval(tool_name: str) -> bool:
    risk = risk_for(tool_name)
    if risk == READ_ONLY:
        return False
    if risk == LOCAL_WRITE:
        return os.getenv("APPROVAL_REQUIRED_FOR_FILE_WRITES", "1") != "0"
    if risk == EXTERNAL_ACTION:
        return os.getenv("APPROVAL_REQUIRED_FOR_EXTERNAL_ACTIONS", "1") != "0"
    if risk == FINANCIAL_ACTION:
        return os.getenv("APPROVAL_REQUIRED_FOR_FINANCIAL_ACTIONS", "1") != "0"
    return True
