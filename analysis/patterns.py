"""
Stage 4: turn the 100 per-app results into the headline patterns.

This is scripted aggregation over real pipeline output, not a hand-written
narrative - re-running it after pass 2 corrections should change the numbers,
and it does (that's how the pass1 -> pass2 accuracy story stays honest).
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = DATA_DIR / "results"

# Keyword buckets for canonicalizing free-text blocker/gating_reason strings into
# a small set of themes. Checked in order; first match wins. Anything that matches
# nothing lands in "other" with its raw text kept, so the bucket list itself can be
# refined by eyeballing what ends up there - not asserted as exhaustive up front.
BLOCKER_BUCKETS = [
    ("Paid plan required", ["paid plan", "subscription", "premium", "upgrade", "paid tier"]),
    ("Admin / IT approval", ["admin approval", "workspace admin", "org admin", "it approval", "organization admin"]),
    ("Partnership / contact sales", ["partnership", "contact sales", "sales team", "become a partner", "apply for access", "request access"]),
    ("Enterprise-only", ["enterprise", "enterprise plan", "enterprise workspace"]),
    ("Narrow / limited API surface", ["limited", "narrow", "read-only", "read only", "restricted scope", "no write"]),
    ("No public API found", ["no public api", "not publicly available", "private api", "internal only", "no documented api"]),
    ("Docs unclear / insufficient", ["unclear", "not documented", "couldn't find", "could not find", "no documentation", "ambiguous"]),
]


def canonicalize_blocker(text: str) -> str:
    if not text:
        return "None"
    lower = text.lower()
    for label, keywords in BLOCKER_BUCKETS:
        if any(kw in lower for kw in keywords):
            return label
    return "Other"


def load_results(pass_num: int):
    ok_file = RESULTS_DIR / f"pass{pass_num}.json"
    needs_human_file = RESULTS_DIR / f"needs_human_pass{pass_num}.json"
    ok = json.loads(ok_file.read_text(encoding="utf-8")) if ok_file.exists() else []
    needs_human = (
        json.loads(needs_human_file.read_text(encoding="utf-8")) if needs_human_file.exists() else []
    )
    return ok, needs_human


def analyze(ok_results: list, needs_human: list, total_apps: int) -> dict:
    auth_counter = Counter()
    for r in ok_results:
        for method in r.get("auth_methods", []):
            auth_counter[method] += 1

    self_serve_count = sum(1 for r in ok_results if r.get("self_serve"))
    gated_count = sum(1 for r in ok_results if not r.get("self_serve"))

    category_stats = defaultdict(
        lambda: {"total": 0, "self_serve": 0, "gated": 0, "buildable": 0, "blocked": 0, "needs_human": 0}
    )
    for r in ok_results:
        cat = category_stats[r["category"]]
        cat["total"] += 1
        if r.get("self_serve"):
            cat["self_serve"] += 1
        else:
            cat["gated"] += 1
        if r.get("buildable_today"):
            cat["buildable"] += 1
        else:
            cat["blocked"] += 1
    for r in needs_human:
        category_stats[r["category"]]["total"] += 1
        category_stats[r["category"]]["needs_human"] += 1

    blocker_counter = Counter()
    for r in ok_results:
        if not r.get("buildable_today"):
            bucket = canonicalize_blocker(r.get("blocker") or r.get("gating_reason") or "")
            blocker_counter[bucket] += 1

    mcp_count = sum(1 for r in ok_results if r.get("mcp_exists"))

    easy_wins = [
        r["name"]
        for r in ok_results
        if r.get("self_serve") and r.get("buildable_today") and r.get("confidence") != "low"
    ]
    needs_outreach = [r["name"] for r in ok_results if not r.get("self_serve")]

    return {
        "total_apps": total_apps,
        "researched_ok": len(ok_results),
        "needs_human_count": len(needs_human),
        "auth_method_distribution": dict(auth_counter),
        "self_serve_vs_gated": {"self_serve": self_serve_count, "gated": gated_count},
        "category_breakdown": {k: v for k, v in sorted(category_stats.items())},
        "blocker_distribution": dict(blocker_counter.most_common()),
        "mcp_exists_count": mcp_count,
        "easy_wins": sorted(easy_wins),
        "needs_outreach": sorted(needs_outreach),
        "needs_human_apps": [{"id": r["id"], "name": r["name"], "reason": r["reason"]} for r in needs_human],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pass", dest="pass_num", type=int, default=1)
    args = parser.parse_args()

    apps = json.loads((DATA_DIR / "apps.json").read_text(encoding="utf-8"))
    ok_results, needs_human = load_results(args.pass_num)
    report = analyze(ok_results, needs_human, total_apps=len(apps))

    out_file = RESULTS_DIR / f"patterns_pass{args.pass_num}.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\n-> {out_file}")


if __name__ == "__main__":
    main()
