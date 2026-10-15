"""Opportunity search and deterministic ranking."""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from config import ROOT_DIR
from tools.web_search import search_web_impl


def _fallback(category: str) -> list[dict]:
    filename = "internships.json" if category == "internship" else "sample_jobs.json"
    path = ROOT_DIR / "data" / filename
    with path.open("r", encoding="utf-8") as f:
        records = json.load(f)
    return records


def _company_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        return host or "Unknown"
    except Exception:
        return "Unknown"


def _normalize_live(result: dict, category: str) -> dict:
    text = f"{result.get('title', '')} {result.get('snippet', '')}"
    return {
        "title": result.get("title") or "Untitled opportunity",
        "company": _company_from_url(result.get("url", "")),
        "location": "Not stated in search snippet",
        "eligibility": "Not verified; inspect the original posting",
        "deadline": "Not stated in search snippet",
        "link": result.get("url", ""),
        "description": result.get("snippet", ""),
        "contact_email": "",
        "is_sample": False,
        "source_mode": "live_search",
        "verification_status": "unverified_search_result",
        "category": category,
    }


def search_opportunities_impl(query: str, limit: int = 20, category: str = "internship") -> dict:
    query = (query or "").strip()
    if len(query) < 3:
        raise ValueError("Opportunity query must contain at least 3 characters.")
    if category not in {"internship", "job"}:
        raise ValueError("category must be internship or job")
    limit = max(1, min(int(limit), 30))
    search_query = query
    if category == "internship" and "internship" not in query.lower() and "intern" not in query.lower():
        search_query += " internships"
    if category == "job" and not any(x in query.lower() for x in ("job", "jobs", "role", "hiring")):
        search_query += " entry level jobs"
    web = search_web_impl(search_query, limit=limit)
    live_items = [
        _normalize_live(item, category)
        for item in web.get("results", [])
        if item.get("url")
    ]
    # Search results are leads; never imply their eligibility, deadline, or vacancy is verified.
    if live_items:
        return {"query": search_query, "category": category, "items": live_items[:limit],
                "count": min(len(live_items), limit), "source_mode": "live_search",
                "warning": "Search snippets are unverified. Open the official posting to confirm availability and eligibility."}
    fallback = _fallback(category)[:limit]
    for item in fallback:
        item["category"] = category
    return {"query": search_query, "category": category, "items": fallback,
            "count": len(fallback), "source_mode": "local_sample_fallback",
            "warning": "Live search returned no usable results. Every returned item is synthetic sample data, not a real opening."}


def rank_opportunities(items: list[dict], query: str, profile: dict | None = None) -> list[dict]:
    """Rank leads transparently; unknown eligibility is never treated as confirmed eligibility."""
    profile = profile or {}
    skill_text = " ".join(profile.get("skills", []) if isinstance(profile.get("skills"), list)
                          else str(profile.get("skills", "")).replace(",", " ").split()).lower()
    skills = [s for s in re.split(r"[\s,;/]+", skill_text) if len(s) > 1]
    query_tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9+#.]+", query) if len(t) > 2]
    ranked = []
    for original in items:
        item = dict(original)
        searchable = " ".join(str(item.get(k, "")) for k in ("title", "company", "description", "eligibility")).lower()
        score = 20
        reasons: list[str] = []
        skill_hits = sorted({skill for skill in skills if skill in searchable})
        if skill_hits:
            score += min(30, len(skill_hits) * 7)
            reasons.append("Skill keywords found: " + ", ".join(skill_hits[:6]))
        title_hits = [token for token in query_tokens if token in str(item.get("title", "")).lower()]
        if title_hits:
            score += min(25, len(set(title_hits)) * 5)
            reasons.append("Title overlaps with requested keywords")
        if item.get("is_sample"):
            score -= 5
            reasons.append("Sample-only record; not a live vacancy")
        elif item.get("verification_status") != "verified_official_posting":
            reasons.append("Live-search lead; source and eligibility still need verification")
        eligibility = str(item.get("eligibility", "")).lower()
        year = str(profile.get("year", "")).lower()
        if year and year in eligibility:
            score += 10
            reasons.append("Education year appears in the stated eligibility")
        else:
            reasons.append("Eligibility is unknown or not fully verified")
        item["fit_score"] = max(0, min(100, score))
        item["ranking_reasons"] = reasons
        if item.get("is_sample"):
            item["eligibility_status"] = "SAMPLE_ONLY"
        elif "not verified" in str(item.get("eligibility", "")).lower() or "not stated" in str(item.get("eligibility", "")).lower():
            item["eligibility_status"] = "UNKNOWN"
        else:
            item["eligibility_status"] = "NEEDS_MANUAL_VERIFICATION"
        ranked.append(item)
    return sorted(ranked, key=lambda x: x.get("fit_score", 0), reverse=True)
