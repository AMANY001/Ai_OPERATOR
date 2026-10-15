"""Email draft generation. This module never sends email."""
from __future__ import annotations
import re
from pathlib import Path
from config import ensure_directories, get_settings


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return (slug or "company")[:70]


def render_email_draft(opportunity: dict, student_profile: dict | None = None) -> str:
    profile = student_profile or {}
    name = (profile.get("name") or "[Your name]").strip()
    degree = (profile.get("degree") or "Computer Science student").strip()
    year = (profile.get("year") or "undergraduate").strip()
    skills = profile.get("skills", [])
    if isinstance(skills, str):
        skills = [x.strip() for x in skills.split(",") if x.strip()]
    skills_line = ", ".join(skills[:8]) if skills else "my relevant coursework and projects"
    title = str(opportunity.get("title") or "the opportunity")
    company = str(opportunity.get("company") or "the team")
    link = str(opportunity.get("link") or "[official posting link]")
    recipient = str(opportunity.get("contact_email") or "[Recruiter email — verify from the official company website]")
    sample_notice = "\nNOTE: This is a sample-only opportunity; do not send this draft." if opportunity.get("is_sample") else ""
    return (
        f"To: {recipient}\n"
        f"Subject: Application inquiry — {title}\n\n"
        f"Dear Hiring Team at {company},\n\n"
        f"I am {name}, a {year} {degree} student, and I am interested in the {title} opportunity. "
        f"My current skills and learning focus include {skills_line}. I would welcome the opportunity "
        f"to contribute while continuing to develop my practical experience.\n\n"
        f"Could you please let me know whether this opportunity is currently open and what the official "
        f"application process requires? I have included the posting link for reference: {link}\n\n"
        f"Thank you for your time and consideration.\n\n"
        f"Regards,\n{name}\n"
        f"{sample_notice}\n"
    )


def draft_email_impl(opportunity: dict, student_profile: dict | None = None, write: bool = True) -> dict:
    text = render_email_draft(opportunity, student_profile)
    if not write:
        return {"draft": text, "written": False, "path": None}
    ensure_directories()
    folder = get_settings().output_dir / "drafts"
    filename = _slug(str(opportunity.get("company") or "company")) + "_" + _slug(str(opportunity.get("title") or "opportunity")) + ".txt"
    path = (folder / filename).resolve()
    if folder.resolve() not in path.parents:
        raise ValueError("Draft path escaped the configured drafts directory.")
    path.write_text(text, encoding="utf-8")
    reread = path.read_text(encoding="utf-8")
    if reread != text:
        raise IOError(f"Draft verification failed for {path}")
    return {"draft": text, "written": True, "path": str(path), "verified": True}
