"""
Thin wrapper around Composio's "execute tool" REST endpoint.

Verified against Composio's own API reference (docs.composio.dev/reference/api-reference/tools):
  POST https://backend.composio.dev/api/v3.1/tools/execute/{tool_slug}
  header: x-api-key: <COMPOSIO_API_KEY>
  body:   {"arguments": {...tool-specific input...}}
  200 response: {"data": ..., "error": str|None, "successful": bool}

We call this directly with `requests` instead of the composio-core Python package:
the REST contract is the one thing Composio's own docs pin down exactly (endpoint,
headers, body shape), so building against it directly is more verifiable than
trusting an SDK method signature we haven't confirmed against the current docs.

Three tools from the COMPOSIO_SEARCH toolkit are used, and their output "data" field
is documented loosely as `string` — in practice this is a JSON-serializable value
that may arrive as a raw JSON string or an already-parsed object depending on the
tool. `_parse_data` below handles both defensively rather than assuming one.
"""

import json
import threading
import time

import requests

from . import config


class ComposioError(Exception):
    pass


class RateLimiter:
    """Simple min-interval limiter, shared across threads."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


_search_limiter = RateLimiter(config.SEARCH_REQUESTS_PER_SECOND)


def _parse_data(raw):
    """`data` may be a JSON string or an already-parsed object. Normalize to the latter."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _execute_tool(tool_slug: str, arguments: dict) -> dict:
    if not config.COMPOSIO_API_KEY:
        raise ComposioError(
            "COMPOSIO_API_KEY is not set. Add it to a .env file in the repo root."
        )

    url = f"{config.COMPOSIO_BASE_URL}/tools/execute/{tool_slug}"
    headers = {"x-api-key": config.COMPOSIO_API_KEY, "Content-Type": "application/json"}
    body = {"arguments": arguments}

    last_error = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url, headers=headers, json=body, timeout=config.REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(config.RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = ComposioError(
                f"{tool_slug} -> HTTP {resp.status_code}: {resp.text[:300]}"
            )
            time.sleep(config.RETRY_BASE_DELAY_SECONDS * (2 ** attempt))
            continue

        if resp.status_code != 200:
            raise ComposioError(f"{tool_slug} -> HTTP {resp.status_code}: {resp.text[:500]}")

        payload = resp.json()
        if not payload.get("successful", True):
            raise ComposioError(f"{tool_slug} -> tool reported failure: {payload.get('error')}")
        return payload

    raise ComposioError(f"{tool_slug} -> failed after {config.MAX_RETRIES} retries: {last_error}")


def search_web(query: str) -> dict:
    """COMPOSIO_SEARCH_WEB — returns results.answer (narrative) and results.citations (sources)."""
    _search_limiter.wait()
    payload = _execute_tool("COMPOSIO_SEARCH_WEB", {"query": query})
    return _parse_data(payload.get("data"))


def fetch_url_content(urls: list, max_characters: int = None) -> dict:
    """COMPOSIO_SEARCH_FETCH_URL_CONTENT — clean markdown text for public web pages."""
    arguments = {"urls": urls, "text": True}
    arguments["max_characters"] = max_characters or config.FETCH_MAX_CHARACTERS
    payload = _execute_tool("COMPOSIO_SEARCH_FETCH_URL_CONTENT", arguments)
    return _parse_data(payload.get("data"))


def groq_chat(messages: list, model: str = None, max_tokens: int = 1000, temperature: float = 0.0) -> str:
    """COMPOSIO_SEARCH_GROQ_CHAT — OpenAI-compatible chat completion. Returns message content text."""
    arguments = {
        "model": model or config.GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    payload = _execute_tool("COMPOSIO_SEARCH_GROQ_CHAT", arguments)
    data = _parse_data(payload.get("data"))

    if isinstance(data, dict) and data.get("choices"):
        content = data["choices"][0].get("message", {}).get("content")
        if content:
            return content
        raise ComposioError("COMPOSIO_SEARCH_GROQ_CHAT returned an empty choice.")
    if isinstance(data, str) and data.strip():
        return data
    raise ComposioError(f"COMPOSIO_SEARCH_GROQ_CHAT returned an unexpected shape: {data!r}")
