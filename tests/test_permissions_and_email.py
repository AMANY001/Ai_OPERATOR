from permissions import requires_approval, risk_for, READ_ONLY, LOCAL_WRITE
from tools.email_tools import render_email_draft


def test_local_writes_require_approval_by_default(monkeypatch):
    monkeypatch.delenv("APPROVAL_REQUIRED_FOR_FILE_WRITES", raising=False)
    assert requires_approval("save_to_sheet") is True
    assert risk_for("save_to_sheet") == LOCAL_WRITE
    assert risk_for("search_web") == READ_ONLY


def test_email_draft_does_not_invent_recruiter_email():
    text = render_email_draft({"title": "Sample role", "company": "Sample employer", "link": "https://example.com", "contact_email": ""}, {})
    assert "[Recruiter email" in text
    assert "Subject: Application inquiry" in text
    assert "does not" not in text.lower()
