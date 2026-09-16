import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
APPS_FILE = DATA_DIR / "apps.json"
RESULTS_DIR = DATA_DIR / "results"

COMPOSIO_BASE_URL = "https://backend.composio.dev/api/v3.1"
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY")

# Model choice for the extraction step, routed through Composio's hosted Groq tool.
# NOTE: Composio's docs list "llama-3.3-70b-versatile" as an option, but live
# testing (2026-09-16) showed Groq has decommissioned it (HTTP 404 model_not_found).
# Swapped to a model actually live on Groq's current backend.
GROQ_MODEL = "openai/gpt-oss-120b"

# Composio's own docs for COMPOSIO_SEARCH_WEB say "throttle to ~1-2 requests/second;
# bursty queries trigger HTTP 429" and for COMPOSIO_SEARCH_GROQ_CHAT say
# "limit concurrency to ~3 concurrent calls". These constants exist to honor that,
# not as arbitrary tuning knobs.
SEARCH_REQUESTS_PER_SECOND = 1.5
PIPELINE_CONCURRENCY = 3

FETCH_MAX_CHARACTERS = 12000
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 30
