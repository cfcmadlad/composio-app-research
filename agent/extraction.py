"""
Builds the extraction prompt and parses the model's JSON response.

The schema below maps 1:1 onto the assignment's required fields:
  - auth method(s)
  - self-serve vs gated
  - API surface (breadth, MCP)
  - buildability verdict + blocker
  - evidence URL per answer (not one URL for the whole app - one per field,
    pulled only from the pages we actually fetched)
"""

import json
import re

REQUIRED_FIELDS = [
    "one_line_description",
    "auth_methods",
    "auth_evidence_url",
    "self_serve",
    "gating_reason",
    "self_serve_evidence_url",
    "api_surface_summary",
    "api_surface_evidence_url",
    "mcp_exists",
    "mcp_notes",
    "mcp_evidence_url",
    "buildable_today",
    "blocker",
    "confidence",
    "notes",
]

VALID_AUTH_METHODS = {"OAuth2", "API key", "Basic", "token", "other"}

SYSTEM_PROMPT = """You are a precise research analyst for an AI agent-tooling company. \
Your job is to read fetched developer-documentation text for one app and extract \
structured facts about how it could be turned into an agent toolkit.

Rules:
- Use ONLY the provided source text. Never invent a fact that isn't supported by it.
- Every evidence_url field MUST be one of the exact URLs given in the source list below \
(copy it verbatim), or null if that field cannot be answered from the given sources.
- auth_methods must be a subset of: OAuth2, API key, Basic, token, other.
- "MCP" means Model Context Protocol (Anthropic's open standard letting AI agents call \
external tools over a standard interface) - NOT "Managed Connectivity Platform" or any \
other expansion. Only set mcp_exists=true if the source text explicitly mentions an MCP \
server, MCP integration, or the Model Context Protocol for this app.
- Watch for name collisions: a source page can belong to a DIFFERENT product that \
happens to share the app's name (e.g. an app called "Sherlock" has multiple unrelated \
products with that name). If a source's content doesn't actually match the app's \
category or description, do not use it - say so in "notes" and lower confidence instead.
- Prefer official sources (the vendor's own domain: developer docs, API reference) over \
third-party pages (personal GitHub repos, blogs, forum posts). If the only sources \
available are third-party/unofficial, still answer but say so explicitly in "notes" and \
set confidence no higher than "medium".
- If the sources don't clearly answer a field, still make your best call but set \
"confidence" to "low" and explain the gap in "notes".
- Output ONLY valid JSON matching the schema below. No markdown code fences, no prose \
before or after, no trailing commas.

Schema:
{
  "one_line_description": string,
  "auth_methods": string[],
  "auth_evidence_url": string|null,
  "self_serve": boolean,
  "gating_reason": string|null,
  "self_serve_evidence_url": string|null,
  "api_surface_summary": string,
  "api_surface_evidence_url": string|null,
  "mcp_exists": boolean,
  "mcp_notes": string|null,
  "mcp_evidence_url": string|null,
  "buildable_today": boolean,
  "blocker": string|null,
  "confidence": "high"|"medium"|"low",
  "notes": string
}"""


def build_user_prompt(app: dict, sources: list) -> str:
    """
    app: {"name": ..., "category": ..., "hint": ...}
    sources: [{"url": ..., "text": ...}, ...]  (already truncated by the fetch step)
    """
    lines = [
        f"App: {app['name']}",
        f"Category: {app['category']}",
        f"Source hint from the research brief: {app['hint']}",
        "",
        "Fetched source pages:",
    ]
    if not sources:
        lines.append("(none — web search / fetch returned nothing usable for this app)")
    for src in sources:
        lines.append(f"\n--- SOURCE: {src['url']} ---\n{src['text']}")
    return "\n".join(lines)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def parse_llm_json(raw: str) -> dict:
    """Raises ValueError with a clear message on any structural problem."""
    text = _strip_code_fences(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise ValueError("model JSON is not an object")

    missing = [f for f in REQUIRED_FIELDS if f not in obj]
    if missing:
        raise ValueError(f"model JSON missing required fields: {missing}")

    bad_auth = [m for m in obj.get("auth_methods", []) if m not in VALID_AUTH_METHODS]
    if bad_auth:
        raise ValueError(f"invalid auth_methods values: {bad_auth}")

    return obj
