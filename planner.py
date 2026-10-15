"""Constrained intent planner. LLM output is advisory and never grants permissions."""
from __future__ import annotations
import json
import re
from models.schemas import PlanDecision
from config import get_settings

_BOOKING_WORDS = re.compile(r"\b(book|purchase|buy|pay for|reserve|reservation|checkout)\b", re.I)
_TRAVEL_WORDS = re.compile(r"\b(flight|airline|train ticket|bus ticket|hotel booking|event ticket|travel booking)\b", re.I)
_JOB_WORDS = re.compile(r"\b(job|jobs|career|hiring|full.time|entry.level|vacanc(?:y|ies)|apply for)\b", re.I)
_INTERNSHIP_WORDS = re.compile(r"\b(internship|internships|intern)\b", re.I)
_RESEARCH_WORDS = re.compile(r"\b(search|research|find|compare|summari[sz]e|investigate|look up)\b", re.I)
_APPLICATION_SUBMISSION_WORDS = re.compile(r"\bapply\s+(?:for|to)\b|\bsubmit(?:ting)?\s+(?:an?\s+)?application\b|\b(?:send|sending)\s+(?:an?\s+)?(?:email|message|invitation)\b|\b(?:schedule|reschedule|accept)\s+(?:an?\s+)?interview\b", re.I)


def _focused_query(goal: str, category: str) -> str:
    """Strip execution/output clauses so search engines receive a focused topic."""
    text = " ".join((goal or "").split())
    text = re.split(r"[,;]|\b(?:and then|then|save|draft|prepare|compare|rank|write a report|export)\b", text, maxsplit=1, flags=re.I)[0]
    text = re.sub(r"^\s*(?:please\s+)?(?:find|search(?: for)?|research|look up|show me|identify)\s+", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:the )?(?:top )?\d+\s+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .:-")
    if category == "internship" and not _INTERNSHIP_WORDS.search(text):
        text += " internships"
    if category == "job" and not _JOB_WORDS.search(text):
        text += " entry-level jobs"
    return (text or goal.strip())[:500]


def deterministic_plan(goal: str) -> PlanDecision:
    clean = " ".join((goal or "").split())
    if len(clean) < 3:
        raise ValueError("Please enter a goal containing at least 3 characters.")
    # Booking and purchasing are deliberately not wired to live reservation providers in this release.
    if _BOOKING_WORDS.search(clean) and _TRAVEL_WORDS.search(clean):
        return PlanDecision(
            workflow="unsupported", category="general", query=clean[:500], limit=10,
            reason="The goal includes a booking or purchase.",
            unsupported_reason=("This build can research public information, but has no live airline, railway, bus, hotel, or event reservation adapter. "
                                "It will not imply that availability is live or attempt a purchase. Use the official provider to complete a booking."),
        )
    if _APPLICATION_SUBMISSION_WORDS.search(clean):
        return PlanDecision(
            workflow="unsupported", category="general", query=clean[:500], limit=10,
            reason="The goal requests an external submission or communication.",
            unsupported_reason=("This release can research job/internship leads and prepare local draft files, but it does not submit applications, send emails, or schedule/accept interviews. "
                                "No external action was attempted. Rephrase the goal as research and draft preparation, or add and test an authorized provider integration."),
        )
    if _INTERNSHIP_WORDS.search(clean):
        return PlanDecision(workflow="opportunity_search", category="internship", query=_focused_query(clean, "internship"), limit=20,
                            reason="Internship-related goal mapped to the internship research workflow.")
    if _JOB_WORDS.search(clean):
        return PlanDecision(workflow="opportunity_search", category="job", query=_focused_query(clean, "job"), limit=20,
                            reason="Job-related goal mapped to the job lead research workflow. Submission itself is not automated in this build.")
    if _RESEARCH_WORDS.search(clean):
        return PlanDecision(workflow="web_research", category="general", query=_focused_query(clean, "general"), limit=10,
                            reason="General public-web research workflow.")
    return PlanDecision(workflow="unsupported", category="general", query=clean[:500], limit=10,
                        reason="No supported workflow was confidently identified.",
                        unsupported_reason="This release supports public-web research, internship/job lead research, local spreadsheet writes, and email draft files. Add an authorized adapter for other actions.")


def plan_goal(goal: str) -> tuple[PlanDecision, str]:
    """Return (decision, planner_mode). Without a key or on API failure use deterministic routing."""
    fallback = deterministic_plan(goal)
    settings = get_settings()
    if not settings.gemini_api_key:
        return fallback, "deterministic_offline"
    # Keep the model on a narrow intent-classification job. It never chooses arbitrary functions.
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = (
            "Classify the user goal for a desktop AI Operator. Return only the supplied JSON schema. "
            "Allowed workflows: opportunity_search (only internship or job lead research), web_research (public-web research), "
            "unsupported (actions whose required integration is absent, including actual booking/purchase/payment and automatic job submission). "
            "Never authorize external submissions or purchases. Do not change the user's intent. "
            f"User goal: {goal}\n"
            "The application enforces permissions separately; this classification grants no permission."
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=PlanDecision.model_json_schema(),
                temperature=0.1,
            ),
        )
        parsed = PlanDecision.model_validate_json(response.text or "")
        # Preserve the deterministic extraction of the search topic; the model may classify intent but does not widen scope.
        parsed = parsed.model_copy(update={"query": fallback.query, "category": fallback.category, "limit": fallback.limit})
        # Policy backstop: a requested transaction cannot be downgraded to a safe research workflow.
        if _BOOKING_WORDS.search(goal) and _TRAVEL_WORDS.search(goal):
            return fallback, "deterministic_policy_override"
        return parsed, "gemini_structured_output"
    except Exception:
        return fallback, "deterministic_fallback_after_llm_error"
