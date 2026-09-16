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
- [x] Stage 2 — research agent that fetches docs and extracts the four signals
- [x] Stage 3 — verification loop (sampled cross-check, first pass vs corrected pass)
- [x] Stage 4 — pattern/cluster analysis over the results
- [ ] Stage 5 — single-page HTML deliverable

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

The agent is a Python pipeline that, for each app, calls Composio's own tools
(`COMPOSIO_SEARCH_WEB`, `COMPOSIO_SEARCH_FETCH_URL_CONTENT`, `COMPOSIO_SEARCH_GROQ_CHAT`)
through Composio's REST API directly — search for the real docs, fetch the actual
page content, then have an LLM extract the five required signals with a per-field
evidence URL. Nothing here is hand-filled: every row in `data/results/pass1.json`
came from a live web fetch and a live model call.

### Setup

1. Get a free Composio API key at [dashboard.composio.dev](https://dashboard.composio.dev)
   (Settings → API Keys). No credit card required.
2. In the repo root, create a `.env` file:
   ```
   COMPOSIO_API_KEY=your_key_here
   ```
3. Install dependencies:
   ```bash
   python -m pip install -r agent/requirements.txt
   ```
   If you hit `SSLCertVerificationError` on Windows (common when antivirus/VPN
   software intercepts TLS), run `python -m pip install pip-system-certs` — it makes
   Python trust the OS certificate store instead of only its bundled list.

### Run it

```bash
python -m agent.run --check              # verify the key works, one test call
python -m agent.run --limit 5            # dry run on the first 5 apps
python -m agent.run --pass 1             # full run across all 100 apps
python -m agent.run --pass 2 --ids 12,47 # re-run specific apps (e.g. corrections)
```

Output: `data/results/pass{N}.json` (successfully researched apps) and
`data/results/needs_human_pass{N}.json` (apps where search found nothing usable,
a fetch failed, or the model's output didn't parse after a retry — logged with a
reason, not silently dropped).

### Then the pattern analysis

```bash
python analysis/patterns.py --pass 1
```

Aggregates `pass1.json` into the headline numbers: auth method distribution,
self-serve vs gated by category, common blockers, easy wins vs apps that need
outreach. Writes `data/results/patterns_pass1.json`.

### Real issues hit while building this (kept here, not swept under the rug)

- Composio's own docs example model (`llama-3.3-70b-versatile`) is decommissioned
  on Groq's live backend — swapped to `openai/gpt-oss-120b`.
- The model initially guessed "MCP" meant "Managed Connectivity Platform" instead
  of Model Context Protocol — fixed by defining it explicitly in the extraction prompt.
- A name-only search query missed doc pages relevant to a signal the app's own hint
  already pointed at (Otter AI's hint says "MCP server"; the first query didn't find
  it) — fixed by folding any parenthetical hint text into the search query.
- Name collisions: searching "Sherlock" and "Mermaid CLI" by name alone surfaced
  unrelated products that happen to share the name (Ansys Sherlock / CloudFerro
  Sherlock AI instead of the OSINT tool; an unrelated Rust crate instead of the real
  mermaid-js CLI) — fixed by always fetching the app's own hinted URL directly
  instead of trusting search to find the right entity.
- `run.py` overwrote `data/results/pass{N}.json` instead of merging, so a targeted
  re-run of a few apps (while testing the fix above) silently destroyed a completed
  100-app pass. Fixed to merge by app ID. A real baseline for the 20-app verification
  sample was lost to this and had to be reconstructed with a `PIPELINE_NAIVE_MODE=1`
  flag that reproduces the pre-fix behavior — kept in the code as a record of it,
  not as a normal run mode.
