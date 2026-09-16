# -*- coding: utf-8 -*-
"""
Builds site/index.html from the real research data. Nothing in the output page
is hand-typed content that could drift from the underlying JSON - re-run this
after any pipeline re-run to regenerate the report.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

apps = {a["id"]: a for a in json.loads((DATA / "apps.json").read_text(encoding="utf-8"))}
results = {r["id"]: r for r in json.loads((DATA / "results" / "pass2.json").read_text(encoding="utf-8"))}
patterns = json.loads((DATA / "results" / "patterns_pass2.json").read_text(encoding="utf-8"))
accuracy = json.loads((DATA / "verification" / "accuracy.json").read_text(encoding="utf-8"))
sample = json.loads((DATA / "verification" / "sample.json").read_text(encoding="utf-8"))
checks = json.loads((DATA / "verification" / "manual_checks.json").read_text(encoding="utf-8"))
pass0 = {r["id"]: r for r in json.loads((DATA / "results" / "pass0.json").read_text(encoding="utf-8"))}

# --- One known, disclosed correction: verification found Stripe's self_serve
# field wrong in BOTH passes. Apply it only to what's DISPLAYED, never to the
# underlying pass2.json (that stays the honest, untouched agent output).
CORRECTIONS = {
    81: {"self_serve": True, "gating_reason": None},
}
display = {k: dict(v) for k, v in results.items()}
for app_id, patch in CORRECTIONS.items():
    display[app_id].update(patch)

sample_ids = {a["id"] for a in sample["apps"]}


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def badge(kind, label):
    return f'<span class="badge badge-{kind}">{esc(label)}</span>'


# ---------- Stat strip ----------
total = patterns["total_apps"]
self_serve_n = sum(1 for r in display.values() if r["self_serve"])
gated_n = total - self_serve_n
mcp_n = patterns["mcp_exists_count"]
top_auth = max(patterns["auth_method_distribution"].items(), key=lambda kv: kv[1])

stat_tiles = f"""
<div class="stat-tile"><div class="stat-num">{total}</div><div class="stat-label">apps researched</div></div>
<div class="stat-tile"><div class="stat-num">{self_serve_n}%</div><div class="stat-label">self&#8209;serve credentials</div></div>
<div class="stat-tile"><div class="stat-num">{top_auth[0]}</div><div class="stat-label">most common auth ({top_auth[1]} apps)</div></div>
<div class="stat-tile"><div class="stat-num">{mcp_n}</div><div class="stat-label">already have an MCP server</div></div>
<div class="stat-tile stat-tile-accent"><div class="stat-num">{accuracy['pass0']['accuracy_pct']}%&nbsp;&rarr;&nbsp;{accuracy['pass2']['accuracy_pct']}%</div><div class="stat-label">verified accuracy, pass 1 &rarr; pass 2</div></div>
"""

# ---------- Category breakdown bars ----------
# Recomputed from `display` (corrected), not read from patterns_pass2.json
# directly - that file was aggregated from the raw, pre-correction pass2.json
# and would silently keep Stripe misclassified as gated under Finance and Fintech.
cat_totals = {}
for app_id, r in display.items():
    cat = apps[app_id]["category"]
    entry = cat_totals.setdefault(cat, {"total": 0, "self_serve": 0})
    entry["total"] += 1
    if r["self_serve"]:
        entry["self_serve"] += 1

cat_rows = []
for cat in sorted(cat_totals):
    stats = cat_totals[cat]
    ss_pct = round(100 * stats["self_serve"] / stats["total"])
    cat_rows.append(f"""
    <div class="cat-row">
      <div class="cat-name">{esc(cat)}</div>
      <div class="cat-bar"><div class="cat-bar-fill" style="width:{ss_pct}%"></div></div>
      <div class="cat-frac">{stats['self_serve']}/{stats['total']} self&#8209;serve</div>
    </div>""")
cat_breakdown_html = "\n".join(cat_rows)

# ---------- Gating reason themes (real "blocker" signal - buildable_today was
# true for all 100, so the actual friction lives in gating_reason). Hand-built
# from the 9 apps `display` actually marks as gated post-correction - not from
# patterns_pass2.json's raw (pre-correction) gating list, which still had 10.
gated_names_corrected = {apps[aid]["name"] for aid, r in display.items() if not r["self_serve"]}
assert gated_names_corrected == {
    "Pylon", "WhatsApp Business", "Google Ads", "Pinterest",
    "Magento (Adobe Commerce)", "Waterfall.io", "PitchBook", "NotebookLM", "Otter AI",
}, f"gated set changed, update gate_buckets: {gated_names_corrected}"
gate_buckets = {
    "Contact sales / partnership": ["Pylon", "Waterfall.io", "PitchBook", "Otter AI"],
    "Manual review / approval process": ["WhatsApp Business", "Google Ads", "Pinterest"],
    "Requires separate paid infrastructure": ["Magento (Adobe Commerce)", "NotebookLM"],
}
gate_bucket_html = "\n".join(
    f'<li><strong>{esc(theme)}</strong> &mdash; {esc(", ".join(names))}</li>'
    for theme, names in gate_buckets.items()
)

# Easy wins / needs outreach, recomputed from `display` so the two numbers
# always sum to the total (previously easy_wins_n used the raw pre-correction
# list and undercounted by one - Stripe fell through both buckets).
easy_wins_n = sum(1 for r in display.values() if r["self_serve"])
needs_outreach_n = total - easy_wins_n
assert easy_wins_n + needs_outreach_n == total

# ---------- Findings table ----------
def auth_badges(methods):
    return " ".join(badge("auth", m) for m in methods)


table_rows = []
categories_seen = []
for app_id in sorted(display):
    r = display[app_id]
    a = apps[app_id]
    if a["category"] not in categories_seen:
        categories_seen.append(a["category"])
    corrected = " data-corrected=\"1\"" if app_id in CORRECTIONS else ""
    ss_badge = badge("good", "Self-serve") if r["self_serve"] else badge("warn", "Gated")
    mcp_badge = badge("mcp", "MCP") if r["mcp_exists"] else ""
    verdict_badge = badge("good", "200 Buildable") if r["buildable_today"] else badge("bad", "403 Blocked")
    corrected_mark = ' <span class="corrected-mark" title="Corrected via hand verification - see Verification section">*</span>' if app_id in CORRECTIONS else ""
    evidence = r.get("auth_evidence_url") or (r.get("source_urls") or [""])[0]
    table_rows.append(f"""
    <tr class="find-row" data-category="{esc(a['category'])}" data-selfserve="{'yes' if r['self_serve'] else 'no'}" data-auth="{esc('|'.join(r['auth_methods']))}"{corrected}>
      <td class="td-name"><a href="{esc(evidence)}" target="_blank" rel="noopener">{esc(a['name'])}</a>{corrected_mark}<div class="td-desc">{esc(r['one_line_description'])}</div></td>
      <td class="td-category">{esc(a['category'])}</td>
      <td class="td-auth">{auth_badges(r['auth_methods'])}</td>
      <td class="td-selfserve">{ss_badge}</td>
      <td class="td-surface">{mcp_badge}</td>
      <td class="td-verdict">{verdict_badge}</td>
    </tr>""")
table_rows_html = "\n".join(table_rows)
category_options = "\n".join(f'<option value="{esc(c)}">{esc(c)}</option>' for c in categories_seen)

# ---------- Verification: dimension accuracy ----------
dim_labels = {
    "auth_methods": "Auth method",
    "self_serve": "Self-serve status",
    "api_surface": "API surface / MCP",
    "buildability": "Buildability verdict",
}
dim_rows = []
for dim, label in dim_labels.items():
    p0 = accuracy["pass0"]["by_dimension"][dim]
    p2 = accuracy["pass2"]["by_dimension"][dim]
    dim_rows.append(f"""
    <tr>
      <td>{esc(label)}</td>
      <td class="num">{p0['correct']}/{p0['total']} &nbsp;({p0['accuracy_pct']}%)</td>
      <td class="num">{p2['correct']}/{p2['total']} &nbsp;({p2['accuracy_pct']}%)</td>
    </tr>""")
dim_rows_html = "\n".join(dim_rows)

# ---------- Verification misses (honest, both passes) ----------
def miss_list(misses, title):
    if not misses:
        return f"<p class='miss-empty'>No misses in {esc(title)}.</p>"
    items = []
    for m in misses:
        val = m["value"]
        val_str = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        items.append(f"""
        <li class="miss-item">
          <div class="miss-head"><strong>{esc(m['app_name'])}</strong> &middot; {esc(dim_labels.get(m['dimension'], m['dimension']))}</div>
          <div class="miss-body">Said: <code>{esc(val_str)}</code></div>
          <div class="miss-body">Reality: {esc(m['ground_truth'])}</div>
          <div class="miss-evidence"><a href="{esc(m['evidence_url'])}" target="_blank" rel="noopener">{esc(m['evidence_url'])}</a></div>
        </li>""")
    return f'<ul class="miss-list">{"".join(items)}</ul>'


pass0_misses_html = miss_list(accuracy["pass0"]["misses"], "pass 1")
pass2_misses_html = miss_list(accuracy["pass2"]["misses"], "pass 2")

sample_names = ", ".join(a["name"] for a in sample["apps"])

# ---------- Agent bug log ----------
bug_log = [
    ("A model no longer served",
     "Composio's own documentation lists <code>llama-3.3-70b-versatile</code> as an example model. It returned "
     "HTTP 404 (<code>model_not_found</code>) on Groq's live backend — the model has since been retired. "
     "Replaced it with <code>openai/gpt-oss-120b</code>."),
    ("“MCP” misread",
     "The extraction model first read MCP as “Managed Connectivity Platform,” not Model Context Protocol. "
     "Corrected by defining the term in the prompt itself."),
    ("A search that missed its own hint",
     "Otter AI's own hint names an MCP server, but a query built from the app's name alone never found the page "
     "that would confirm or deny it, so the first pass reported none. Fixed by folding the hint's own text into "
     "the search query."),
    ("Two names, wrong products",
     "Searching “Sherlock” and “Mermaid CLI” by name returned unrelated products that happen to "
     "share the name — Ansys Sherlock, an unrelated Rust crate — instead of the tools the assignment "
     "actually meant. Fixed by fetching the hint's own URL directly, rather than trusting search to pick the "
     "right one."),
    ("A results file overwritten",
     "A targeted re-run of three apps, made to test the fix above, silently overwrote a completed hundred-app "
     "results file instead of merging into it. The writer was fixed to merge by app ID. The data lost to this "
     "was reconstructed under a documented, explicitly labeled naive-mode flag, so the before-and-after "
     "comparison later in this report is not invented."),
    ("One extraction that failed, then didn't",
     "Otter AI's JSON response was cut off mid-string on the first attempt — Groq's output is not fully "
     "deterministic. It succeeded on a second attempt. Kept here rather than removed: this is a real property "
     "of extraction at this scale, not an exception to it."),
]
bug_log_html = "\n".join(
    f'<div class="bug-item"><div class="bug-title">{esc(t)}</div><div class="bug-body">{b}</div></div>'
    for t, b in bug_log
)

TEMPLATE_PATH = Path(__file__).with_name("template.html")
OUT_PATH = Path(__file__).with_name("index.html")

template = TEMPLATE_PATH.read_text(encoding="utf-8")
out = (
    template
    .replace("{{STAT_TILES}}", stat_tiles)
    .replace("{{CAT_BREAKDOWN}}", cat_breakdown_html)
    .replace("{{GATE_BUCKETS}}", gate_bucket_html)
    .replace("{{EASY_WINS_N}}", str(easy_wins_n))
    .replace("{{NEEDS_OUTREACH_N}}", str(needs_outreach_n))
    .replace("{{SELF_SERVE_PCT}}", str(self_serve_n))
    .replace("{{GATED_PCT}}", str(gated_n))
    .replace("{{TABLE_ROWS}}", table_rows_html)
    .replace("{{CATEGORY_OPTIONS}}", category_options)
    .replace("{{TOTAL_APPS}}", str(total))
    .replace("{{DIM_ROWS}}", dim_rows_html)
    .replace("{{PASS0_ACC}}", str(accuracy["pass0"]["accuracy_pct"]))
    .replace("{{PASS2_ACC}}", str(accuracy["pass2"]["accuracy_pct"]))
    .replace("{{PASS0_CORRECT}}", str(accuracy["pass0"]["correct_checks"]))
    .replace("{{PASS2_CORRECT}}", str(accuracy["pass2"]["correct_checks"]))
    .replace("{{TOTAL_CHECKS}}", str(accuracy["pass0"]["total_checks"]))
    .replace("{{PASS0_MISSES}}", pass0_misses_html)
    .replace("{{PASS2_MISSES}}", pass2_misses_html)
    .replace("{{SAMPLE_NAMES}}", esc(sample_names))
    .replace("{{BUG_LOG}}", bug_log_html)
    .replace("{{MCP_N}}", str(mcp_n))
)

OUT_PATH.write_text(out, encoding="utf-8")
print(f"Wrote {OUT_PATH} ({len(out):,} bytes)")
