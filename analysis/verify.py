"""
Stage 3: score manual/browser-use cross-checks of pipeline output against real docs.

Reads data/verification/manual_checks.json, a list of entries like:
  {
    "app_id": 1, "app_name": "Salesforce", "dimension": "auth_methods",
    "pass0_value": "...", "pass2_value": "...", "ground_truth": "...",
    "pass0_correct": true, "pass2_correct": true,
    "evidence_url": "...", "notes": "...", "checked_via": "browser-use"
  }
dimension is one of: auth_methods, self_serve, api_surface, buildability.
Each of the 20 sampled apps gets one entry per dimension (80 checks total).

Ground truth is established once per field by reading the real docs, then both
pass0 (pre-fix pipeline) and pass2 (post-fix pipeline) are scored against it -
cheaper than re-researching twice, and it's what actually answers "did the fix
help": pass0_accuracy vs pass2_accuracy on the identical 20-app sample.

This script only aggregates what a human (or browser-use session) recorded. It
does not decide correctness itself.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VERIFICATION_DIR = DATA_DIR / "verification"
CHECKS_FILE = VERIFICATION_DIR / "manual_checks.json"

DIMENSIONS = ["auth_methods", "self_serve", "api_surface", "buildability"]


def score(checks: list, key: str) -> dict:
    total = len(checks)
    correct = sum(1 for c in checks if c.get(key))
    by_dimension = {}
    for dim in DIMENSIONS:
        dim_checks = [c for c in checks if c["dimension"] == dim]
        dim_correct = sum(1 for c in dim_checks if c.get(key))
        by_dimension[dim] = {
            "total": len(dim_checks),
            "correct": dim_correct,
            "accuracy_pct": round(100 * dim_correct / len(dim_checks), 1) if dim_checks else None,
        }
    misses = [
        {
            "app_id": c["app_id"],
            "app_name": c["app_name"],
            "dimension": c["dimension"],
            "value": c.get("pass0_value" if key == "pass0_correct" else "pass2_value"),
            "ground_truth": c.get("ground_truth"),
            "evidence_url": c.get("evidence_url"),
            "notes": c.get("notes"),
        }
        for c in checks
        if not c.get(key)
    ]
    return {
        "total_checks": total,
        "correct_checks": correct,
        "accuracy_pct": round(100 * correct / total, 1) if total else None,
        "by_dimension": by_dimension,
        "misses": misses,
    }


def generate_template():
    """Pre-fill the 20-apps x 4-dimensions checklist with pass0/pass2 values
    already populated from disk, leaving only ground_truth + correctness for
    an actual read of the real docs to fill in."""
    sample = json.loads((VERIFICATION_DIR / "sample.json").read_text(encoding="utf-8"))

    def load_pass(n):
        path = DATA_DIR / "results" / f"pass{n}.json"
        if not path.exists():
            return {}
        return {r["id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}

    pass0 = load_pass(0)
    pass2 = load_pass(2)

    def value_for(record: dict, dimension: str):
        if not record:
            return None
        if dimension == "auth_methods":
            return record.get("auth_methods")
        if dimension == "self_serve":
            return {"self_serve": record.get("self_serve"), "gating_reason": record.get("gating_reason")}
        if dimension == "api_surface":
            return {"summary": record.get("api_surface_summary"), "mcp_exists": record.get("mcp_exists")}
        if dimension == "buildability":
            return {"buildable_today": record.get("buildable_today"), "blocker": record.get("blocker")}
        return None

    template = []
    for app in sample["apps"]:
        for dim in DIMENSIONS:
            template.append(
                {
                    "app_id": app["id"],
                    "app_name": app["name"],
                    "dimension": dim,
                    "pass0_value": value_for(pass0.get(app["id"]), dim),
                    "pass2_value": value_for(pass2.get(app["id"]), dim),
                    "ground_truth": None,
                    "pass0_correct": None,
                    "pass2_correct": None,
                    "evidence_url": None,
                    "notes": None,
                    "checked_via": None,
                }
            )

    CHECKS_FILE.write_text(json.dumps(template, indent=2), encoding="utf-8")
    print(f"Template with {len(template)} checks -> {CHECKS_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-template", action="store_true")
    args = parser.parse_args()

    if args.generate_template:
        generate_template()
        return

    if not CHECKS_FILE.exists():
        print("No checks file yet. Run --generate-template first, then fill it in.")
        return
    checks = json.loads(CHECKS_FILE.read_text(encoding="utf-8"))
    completed = [c for c in checks if c.get("pass2_correct") is not None]
    if not completed:
        print("No completed checks yet.")
        return

    result = {
        "checks_completed": len(completed),
        "checks_total_in_file": len(checks),
        "pass0": score(completed, "pass0_correct"),
        "pass2": score(completed, "pass2_correct"),
    }

    out_file = VERIFICATION_DIR / "accuracy.json"
    out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"\n-> {out_file}")


if __name__ == "__main__":
    main()
