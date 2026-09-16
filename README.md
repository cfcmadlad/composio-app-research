# composio-app-research

Take-home assignment for the Composio AI Product Ops Intern role: research 100 apps
across 10 categories and determine, for each, how buildable it is as an agent
toolkit today.

For each app we capture:

1. **Category** and a one-line description
2. **Auth method** (OAuth2, API key, Basic, token, other)
3. **Self-serve vs gated** — can a developer get credentials free/on trial, or is it
   paid-plan / admin-approval / partnership-gated
4. **API surface** — documented REST/GraphQL, how broad, existing MCP or not
5. **Buildability verdict** — could this be an agent toolkit today, and the main
   blocker if not

with a source URL as evidence for every answer.

## Status

- [x] Stage 1 — project structure + clean seed data (`data/apps.json`)
- [ ] Stage 2 — research agent that fetches docs and extracts the four signals
- [ ] Stage 3 — verification loop (sampled cross-check, first pass vs corrected pass)
- [ ] Stage 4 — single-page HTML deliverable

## Data

`data/apps.json` is the seed list of 100 apps, transcribed from the assignment.
Each record is intentionally raw — `id`, `category_id`, `category`, `name`, `hint`
(the website/hint text as given) — with no pre-guessed docs URLs. Resolving each
`hint` to real, evidenced findings is the research agent's job (stage 2).

Note: the assignment PDF was truncated at 8 pages / app #85, cutting off the rest
of "Finance and Fintech" and omitting category 10 ("AI, Research and Media-native",
apps 91–100) entirely. The full 100 were recovered from the live Notion page linked
in the PDF footer.

## Running the research agent

_Added in stage 2._
