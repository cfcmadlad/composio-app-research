"""
CLI entrypoint for the research agent.

Usage (from repo root, with .env containing COMPOSIO_API_KEY):
    python -m agent.run --check              # verify the key works, no full run
    python -m agent.run --limit 5            # dry run on the first 5 apps
    python -m agent.run --pass 1              # full run across all 100 -> data/results/pass1.json
    python -m agent.run --pass 2 --ids 12,47  # re-run just specific apps (e.g. corrections)
"""

import argparse
import json
import sys

from . import composio_client as cc
from . import config
from .pipeline import run_pipeline


def load_apps():
    with open(config.APPS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def check_setup():
    if not config.COMPOSIO_API_KEY:
        print("COMPOSIO_API_KEY not set. Add it to a .env file in the repo root.")
        sys.exit(1)
    print("COMPOSIO_API_KEY is set. Making one test call (COMPOSIO_SEARCH_WEB)...")
    try:
        data = cc.search_web("Stripe developer API documentation")
    except cc.ComposioError as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
    print("OK. Raw response shape:")
    print(json.dumps(data, indent=2)[:2000])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify setup and exit")
    parser.add_argument("--pass", dest="pass_num", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="only process the first N apps")
    parser.add_argument("--ids", type=str, default=None, help="comma-separated app ids to run")
    args = parser.parse_args()

    if args.check:
        check_setup()
        return

    apps = load_apps()
    if args.ids:
        wanted = {int(x) for x in args.ids.split(",")}
        apps = [a for a in apps if a["id"] in wanted]
    elif args.limit:
        apps = apps[: args.limit]

    if not apps:
        print("No apps selected.")
        return

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    total = len(apps)
    done = 0

    def on_result(result):
        nonlocal done
        done += 1
        status = "NEEDS HUMAN" if result.get("needs_human") else "ok"
        reason = f" ({result['reason']})" if result.get("needs_human") else ""
        print(f"[{done}/{total}] #{result['id']} {result['name']} -> {status}{reason}")

    print(f"Running pass {args.pass_num} over {total} app(s), concurrency={config.PIPELINE_CONCURRENCY}...")
    results = run_pipeline(apps, on_result=on_result)

    ok_results = [r for r in results if not r.get("needs_human")]
    needs_human = [r for r in results if r.get("needs_human")]

    out_file = config.RESULTS_DIR / f"pass{args.pass_num}.json"
    needs_human_file = config.RESULTS_DIR / f"needs_human_pass{args.pass_num}.json"

    # Merge into whatever's already on disk instead of overwriting it - a targeted
    # re-run (--ids / --limit) must not wipe out the rest of a completed pass.
    # (Found the hard way: an --ids re-run of 3 apps once overwrote a completed
    # 100-app pass1.json down to those same 3 apps.)
    def load(path):
        return {item["id"]: item for item in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}

    ok_by_id = load(out_file)
    needs_human_by_id = load(needs_human_file)

    touched_ids = {a["id"] for a in apps}
    for tid in touched_ids:
        ok_by_id.pop(tid, None)
        needs_human_by_id.pop(tid, None)
    for r in ok_results:
        ok_by_id[r["id"]] = r
    for r in needs_human:
        needs_human_by_id[r["id"]] = r

    merged_ok = [ok_by_id[k] for k in sorted(ok_by_id)]
    merged_needs_human = [needs_human_by_id[k] for k in sorted(needs_human_by_id)]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(merged_ok, f, indent=2)
    with open(needs_human_file, "w", encoding="utf-8") as f:
        json.dump(merged_needs_human, f, indent=2)

    print(f"\nDone. This run: {len(ok_results)} researched, {len(needs_human)} need a human.")
    print(f"File totals after merge: {len(merged_ok)} researched, {len(merged_needs_human)} need a human.")
    print(f"  -> {out_file}")
    print(f"  -> {needs_human_file}")


if __name__ == "__main__":
    main()
