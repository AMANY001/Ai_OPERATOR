"""Public-web search adapter. Search results are leads, not verified facts."""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urlparse


def search_web_impl(query: str, limit: int = 10) -> dict:
    query = (query or "").strip()
    if len(query) < 3:
        raise ValueError("Search query must contain at least 3 characters.")
    limit = max(1, min(int(limit), 30))
    searched_at = datetime.now(timezone.utc).isoformat()
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
        normalized = []
        for item in results:
            url = str(item.get("href") or item.get("url") or "").strip()
            if not url.startswith(("https://", "http://")):
                continue
            title = str(item.get("title") or "Untitled result").strip()
            body = str(item.get("body") or item.get("snippet") or "").strip()
            normalized.append({
                "title": title[:300],
                "url": url,
                "snippet": body[:4000],
                "domain": urlparse(url).netloc.lower(),
                "retrieved_at": searched_at,
                "verification_status": "unverified_search_result",
                "is_sample": False,
            })
        return {"query": query, "results": normalized[:limit], "count": len(normalized[:limit]),
                "source_mode": "live_search" if normalized else "no_live_results", "searched_at": searched_at}
    except Exception as exc:
        # No fictional result is substituted for a general web query.
        return {"query": query, "results": [], "count": 0, "source_mode": "search_unavailable",
                "searched_at": searched_at, "warning": f"Web search unavailable: {type(exc).__name__}: {exc}"}
