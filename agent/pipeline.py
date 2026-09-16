"""
Per-app research pipeline: search -> fetch -> extract, with a needs_human escape
hatch at every step that can fail. Nothing here silently guesses; a failure is
recorded, not papered over.
"""

import datetime
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from . import composio_client as cc
from . import config
from . import extraction

# Set to reproduce the pre-fix pipeline behavior (search-only, no direct hint-URL
# fetch) for building an honest pass-1 baseline on the verification sample after
# the real pass-1 data for it was lost to the run.py overwrite bug. Not used in
# normal operation.
NAIVE_MODE = bool(os.environ.get("PIPELINE_NAIVE_MODE"))


def _hint_domain(hint: str) -> str:
    """Best-effort bare domain out of a raw hint string, for ranking search results.
    e.g. 'twenty.com (open-source CRM)' -> 'twenty.com'."""
    match = re.search(r"([a-z0-9-]+\.)+[a-z]{2,}", hint.lower())
    return match.group(0) if match else ""


def _hint_url(hint: str) -> str:
    """Full URL (domain + path) out of a raw hint string, e.g.
    'github.com/sherlock-project/sherlock' -> 'https://github.com/sherlock-project/sherlock'.

    Exists because search-by-name alone can land on a same-named but unrelated
    product (verified live: 'Sherlock' -> Ansys Sherlock / CloudFerro Sherlock AI
    instead of github.com/sherlock-project/sherlock; 'Mermaid CLI' -> an unrelated
    Rust crate instead of github.com/mermaid-js/mermaid-cli). When the assignment's
    own hint already gives a specific URL, fetching it directly sidesteps that
    ambiguity instead of hoping search resolves it correctly."""
    match = re.search(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s()]*)?", hint.lower())
    if not match:
        return ""
    url = match.group(0).rstrip("/.,")
    return url if url.startswith("http") else f"https://{url}"


def _extract_citation_urls(search_data) -> list:
    """Verified live against COMPOSIO_SEARCH_WEB (2026-09-16): the response `data`
    is {"answer": str, "citations": [{"url": ..., "title": ..., ...}, ...]} at the
    TOP LEVEL - not nested under a "results" key as the docs prose implied. Kept
    the nested-shape fallback too in case other queries/tool versions differ."""
    candidates = []
    if isinstance(search_data, dict):
        top_citations = search_data.get("citations")
        if isinstance(top_citations, list):
            for c in top_citations:
                if isinstance(c, dict) and c.get("url"):
                    candidates.append(c["url"])
                elif isinstance(c, str):
                    candidates.append(c)

        results = search_data.get("results")
        if isinstance(results, dict):
            citations = results.get("citations")
            if isinstance(citations, list):
                for c in citations:
                    if isinstance(c, dict) and c.get("url"):
                        candidates.append(c["url"])
                    elif isinstance(c, str):
                        candidates.append(c)
            organic = results.get("organic_results")
            if isinstance(organic, list):
                for r in organic:
                    if isinstance(r, dict) and r.get("url"):
                        candidates.append(r["url"])
    # Live testing (2026-09-16) showed COMPOSIO_SEARCH_WEB occasionally returns
    # truncated citation URLs with a literal "..." in them (e.g.
    # "https://docs.stripe.com/api?s...="), not just a display artifact - it's in
    # the raw JSON. Fetching those would just waste a call, so drop them here.
    seen = set()
    out = []
    for url in candidates:
        if "..." in url:
            continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _rank_urls(urls: list, hint: str, limit: int) -> list:
    domain = _hint_domain(hint)
    if not domain:
        return urls[:limit]

    def score(url):
        try:
            host = urlparse(url).netloc.lower()
        except ValueError:
            return 1
        return 0 if domain in host else 1

    return sorted(urls, key=score)[:limit]


def _extract_fetched_pages(fetch_data, requested_urls: list) -> list:
    """Same caveat as _extract_citation_urls: handle a couple of plausible shapes
    for the fetch tool's output instead of assuming one exact structure."""
    pages = []
    if isinstance(fetch_data, dict):
        results = fetch_data.get("results", fetch_data)
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and r.get("url") and r.get("text"):
                    pages.append({"url": r["url"], "text": r["text"]})
        elif isinstance(results, dict):
            for url, val in results.items():
                text = val.get("text") if isinstance(val, dict) else val
                if isinstance(text, str) and text.strip():
                    pages.append({"url": url, "text": text})
    if not pages and requested_urls and isinstance(fetch_data, str):
        # Fallback: a single combined text blob for a single-URL request.
        pages.append({"url": requested_urls[0], "text": fetch_data})
    return pages


def research_app(app: dict, search_query_template: str = None) -> dict:
    """Returns a result dict. On unrecoverable failure, returns a dict with
    "needs_human": True and a "reason" instead of raising, so the caller can
    keep going through the other 99 apps."""
    base = {
        "id": app["id"],
        "category": app["category"],
        "name": app["name"],
        "hint": app["hint"],
        "researched_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    # Live testing (2026-09-16, Otter AI/#92) showed a query built from the app
    # name alone can miss the exact page that confirms/denies a signal the
    # assignment's own hint already points at (its hint says "MCP server", but a
    # name-only query didn't surface any MCP-specific page). Fold any parenthetical
    # annotation in the hint into the query so it's actually checked, not skipped.
    hint_annotation = re.findall(r"\(([^)]+)\)", app.get("hint", ""))
    hint_suffix = f" {' '.join(hint_annotation)}" if hint_annotation else ""
    query = (
        search_query_template or "{name} developer API documentation authentication"
    ).format(**app) + hint_suffix

    try:
        search_data = cc.search_web(query)
        search_citations = _extract_citation_urls(search_data)
    except cc.ComposioError as exc:
        search_citations = []
        search_error = str(exc)
    else:
        search_error = None

    # Always try the hint's own URL directly, not just search results - fixes the
    # Sherlock/Mermaid CLI-style name collisions where search finds an unrelated
    # same-named product instead of the one the assignment actually pointed at.
    direct_url = "" if NAIVE_MODE else _hint_url(app.get("hint", ""))
    ranked_search_urls = _rank_urls(search_citations, app["hint"], limit=2)
    urls = ([direct_url] if direct_url else []) + [
        u for u in ranked_search_urls if u != direct_url
    ]
    urls = urls[:3]

    if not urls:
        reason = f"search_failed: {search_error}" if search_error else "search_no_citations"
        return {**base, "needs_human": True, "reason": reason, "search_query": query}

    try:
        fetch_data = cc.fetch_url_content(urls)
    except cc.ComposioError as exc:
        return {
            **base,
            "needs_human": True,
            "reason": f"fetch_failed: {exc}",
            "search_query": query,
            "attempted_urls": urls,
        }

    pages = _extract_fetched_pages(fetch_data, urls)
    if not pages:
        return {
            **base,
            "needs_human": True,
            "reason": "fetch_returned_no_usable_text",
            "search_query": query,
            "attempted_urls": urls,
        }

    prompt = extraction.build_user_prompt(app, pages)
    messages = [
        {"role": "system", "content": extraction.SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    raw = None
    for attempt in range(2):
        try:
            raw = cc.groq_chat(messages)
            parsed = extraction.parse_llm_json(raw)
            return {
                **base,
                "needs_human": False,
                "search_query": query,
                "source_urls": [p["url"] for p in pages],
                **parsed,
            }
        except (cc.ComposioError, ValueError) as exc:
            if attempt == 0:
                messages.append({"role": "assistant", "content": raw or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": f"That response was invalid ({exc}). "
                        "Return ONLY valid JSON matching the schema, nothing else.",
                    }
                )
                continue
            return {
                **base,
                "needs_human": True,
                "reason": f"extraction_failed: {exc}",
                "search_query": query,
                "source_urls": [p["url"] for p in pages],
            }


def run_pipeline(apps: list, concurrency: int = None, on_result=None) -> list:
    """Runs research_app across all given apps with bounded concurrency.
    on_result(result_dict) is called as each app finishes, for live progress."""
    concurrency = concurrency or config.PIPELINE_CONCURRENCY
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(research_app, app): app for app in apps}
        for future in as_completed(futures):
            app = futures[future]
            try:
                result = future.result()
            except Exception:  # noqa: BLE001 - a crash here is itself a finding
                result = {
                    "id": app["id"],
                    "category": app["category"],
                    "name": app["name"],
                    "hint": app["hint"],
                    "needs_human": True,
                    "reason": f"pipeline_crash: {traceback.format_exc(limit=3)}",
                }
            results.append(result)
            if on_result:
                on_result(result)
    results.sort(key=lambda r: r["id"])
    return results
