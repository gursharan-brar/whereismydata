"""
WhereIsMyData — Canadian privacy policy scanner

What it does:
  Takes a URL, finds the privacy policy, runs it through Claude Haiku,
  scores it against a PIPEDA-grounded rubric, outputs an HTML report card.

What it is NOT:
  Legal advice. This is an AI-assisted reading tool. Verify everything
  yourself before acting on it.

Usage:
  python scan.py https://example.com
  python scan.py https://example.com --out report.html
  python scan.py --batch companies.txt --out reports/

Setup:
  pip install anthropic requests beautifulsoup4
  export ANTHROPIC_API_KEY=sk-ant-...
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"
MAX_POLICY_CHARS = 60000  # truncate giant policies before sending to model
REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (compatible; WhereIsMyDataBot/1.0; "
    "+https://github.com/gursharan-brar/whereismydata)"
)

# Privacy-policy link hints (case-insensitive substring match on link text/href)
POLICY_HINTS = [
    "privacy policy",
    "privacy notice",
    "privacy statement",
    "privacy",
    "data protection",
    "/privacy",
    "/privacy-policy",
    "/privacy-notice",
]

# ---------------------------------------------------------------------------
# Rubric — grounded in PIPEDA's 10 fair information principles + Alberta PIPA
# ---------------------------------------------------------------------------
# Each item: (key, label, what we look for, weight)
# Total weight = 100. Grade letter is derived from total score.

RUBRIC = [
    ("accountability",
     "Accountability",
     "Names a privacy officer or contact and gives a way to reach them",
     10),
    ("purpose_identified",
     "Purpose identified",
     "States WHY data is being collected, in plain language, before/at collection",
     10),
    ("consent_clear",
     "Consent is clear",
     "Explains how consent is obtained and how users can withdraw it",
     10),
    ("data_minimization",
     "Data minimization",
     "Limits collection to what's needed for the stated purpose — no vague 'and other data'",
     8),
    ("third_party_sharing",
     "Third-party sharing disclosed",
     "Lists categories of third parties data is shared with, and why",
     12),
    ("data_location",
     "Data storage location disclosed",
     "Says WHERE data is stored (Canada / US / EU / 'globally') and notes cross-border transfer",
     12),
    ("retention",
     "Retention period stated",
     "Says how long data is kept, or the criteria used to decide",
     8),
    ("security",
     "Security measures described",
     "Describes safeguards (encryption, access controls) in more than one generic sentence",
     8),
    ("user_rights",
     "User rights spelled out",
     "Tells users how to access, correct, or delete their data, and how to complain",
     10),
    ("plain_language",
     "Plain language",
     "Readable by a non-lawyer. No wall-of-text legalese. Has headings, structure",
     6),
    ("last_updated",
     "Last-updated date visible",
     "Shows when the policy was last revised",
     6),
]

TOTAL_WEIGHT = sum(w for _, _, _, w in RUBRIC)
assert TOTAL_WEIGHT == 100, f"Rubric weights should sum to 100, got {TOTAL_WEIGHT}"


def letter_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

@dataclass
class FetchedPolicy:
    company_url: str
    policy_url: str
    policy_text: str
    truncated: bool


def fetch_html(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text


def find_policy_url(home_url: str, home_html: str) -> str | None:
    """Look for a privacy-policy link on the homepage."""
    soup = BeautifulSoup(home_html, "html.parser")
    candidates = []

    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip().lower()
        href = a["href"].lower()
        for hint in POLICY_HINTS:
            if hint in text or hint in href:
                full = urljoin(home_url, a["href"])
                candidates.append(full)
                break

    # Prefer links containing "privacy" in the path
    candidates.sort(key=lambda u: ("privacy" not in u.lower(), len(u)))
    return candidates[0] if candidates else None


def extract_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Drop script/style/nav noise
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n")
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def fetch_policy(company_url: str) -> FetchedPolicy:
    home_html = fetch_html(company_url)
    policy_url = find_policy_url(company_url, home_html)
    if not policy_url:
        raise RuntimeError(f"Could not find a privacy policy link on {company_url}")

    policy_html = fetch_html(policy_url)
    policy_text = extract_text_from_html(policy_html)

    truncated = False
    if len(policy_text) > MAX_POLICY_CHARS:
        policy_text = policy_text[:MAX_POLICY_CHARS]
        truncated = True

    return FetchedPolicy(
        company_url=company_url,
        policy_url=policy_url,
        policy_text=policy_text,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Claude scoring
# ---------------------------------------------------------------------------

SCORING_PROMPT = """You are reading a privacy policy and scoring it against a rubric \
grounded in Canada's PIPEDA fair information principles and Alberta's PIPA.

You are NOT making a legal determination. You are checking whether the policy \
TEXT discloses certain things clearly. Hedge accordingly. Never write \
"violates PIPEDA" — write "the policy does/does not disclose X clearly."

For each rubric item, return:
  - status: "yes" (clearly addressed), "partial" (mentioned vaguely), or "no" (missing/unclear)
  - evidence: 1-2 short quotes or paraphrases from the policy (under 15 words each)
  - note: one short sentence explaining your call

Rubric:
{rubric_json}

Privacy policy text (may be truncated):
---
{policy_text}
---

Return ONLY valid JSON, no preamble, no markdown fences, in this exact shape:
{{
  "items": {{
    "<key>": {{"status": "yes|partial|no", "evidence": "...", "note": "..."}},
    ...
  }},
  "summary": "2-3 sentence plain-English summary of the policy's strengths and weaknesses"
}}
"""


def score_policy(client: Anthropic, policy: FetchedPolicy) -> dict:
    rubric_for_prompt = [
        {"key": k, "label": label, "looking_for": looking}
        for k, label, looking, _ in RUBRIC
    ]
    prompt = SCORING_PROMPT.format(
        rubric_json=json.dumps(rubric_for_prompt, indent=2),
        policy_text=policy.policy_text,
    )

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    # Strip accidental fences just in case
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def calculate_score(scoring: dict) -> tuple[float, str]:
    total = 0.0
    for key, _, _, weight in RUBRIC:
        item = scoring["items"].get(key, {})
        status = item.get("status", "no")
        if status == "yes":
            total += weight
        elif status == "partial":
            total += weight * 0.5
    return round(total, 1), letter_grade(total)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhereIsMyData — {company_display}</title>
<style>
  :root {{
    --bg: #0a0e17;
    --surface: #111824;
    --surface-2: #182233;
    --text: #e6eaf2;
    --muted: #8a96ab;
    --accent: #5eead4;
    --accent-dim: #2dd4bf;
    --yes: #4ade80;
    --partial: #fbbf24;
    --no: #f87171;
    --grade-a: #4ade80;
    --grade-b: #86efac;
    --grade-c: #fbbf24;
    --grade-d: #fb923c;
    --grade-f: #f87171;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: 'Geist', 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.55;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 48px 24px 96px; }}
  .brand {{
    font-size: 13px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 8px;
  }}
  h1 {{
    margin: 0 0 8px;
    font-size: 36px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }}
  .url {{
    color: var(--muted);
    font-size: 14px;
    word-break: break-all;
    margin-bottom: 32px;
  }}
  .url a {{ color: var(--muted); }}
  .grade-card {{
    background: linear-gradient(135deg, var(--surface), var(--surface-2));
    border: 1px solid #1f2a3d;
    border-radius: 16px;
    padding: 32px;
    display: flex;
    align-items: center;
    gap: 32px;
    margin-bottom: 32px;
  }}
  .grade-letter {{
    font-size: 96px;
    font-weight: 800;
    line-height: 1;
    color: var(--grade-{grade_lower});
    font-family: 'Geist Mono', ui-monospace, monospace;
  }}
  .grade-meta .score {{
    font-size: 14px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }}
  .grade-meta .number {{
    font-size: 32px;
    font-weight: 700;
    margin-top: 4px;
  }}
  .summary {{
    background: var(--surface);
    border-left: 3px solid var(--accent);
    padding: 20px 24px;
    border-radius: 8px;
    margin-bottom: 40px;
    color: #c9d2e2;
  }}
  h2 {{
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--muted);
    margin: 40px 0 16px;
  }}
  .item {{
    background: var(--surface);
    border: 1px solid #1f2a3d;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 12px;
  }}
  .item-head {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    margin-bottom: 8px;
  }}
  .item-label {{ font-weight: 600; font-size: 16px; }}
  .badge {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 4px 10px;
    border-radius: 999px;
  }}
  .badge.yes {{ background: rgba(74, 222, 128, 0.12); color: var(--yes); }}
  .badge.partial {{ background: rgba(251, 191, 36, 0.12); color: var(--partial); }}
  .badge.no {{ background: rgba(248, 113, 113, 0.12); color: var(--no); }}
  .item-note {{ color: #c9d2e2; font-size: 14.5px; margin: 6px 0; }}
  .item-evidence {{
    color: var(--muted);
    font-size: 13px;
    font-style: italic;
    border-top: 1px dashed #1f2a3d;
    padding-top: 8px;
    margin-top: 8px;
  }}
  .disclaimer {{
    margin-top: 48px;
    padding: 20px 24px;
    background: rgba(248, 113, 113, 0.06);
    border: 1px solid rgba(248, 113, 113, 0.2);
    border-radius: 10px;
    color: #fbcaca;
    font-size: 13.5px;
  }}
  .disclaimer strong {{ color: #fecaca; }}
  .footer {{
    margin-top: 32px;
    text-align: center;
    color: var(--muted);
    font-size: 12px;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">WhereIsMyData · Canadian Privacy Scan</div>
  <h1>{company_display}</h1>
  <div class="url">Policy scanned: <a href="{policy_url}">{policy_url}</a></div>

  <div class="grade-card">
    <div class="grade-letter">{grade}</div>
    <div class="grade-meta">
      <div class="score">Overall score</div>
      <div class="number">{score} / 100</div>
    </div>
  </div>

  <div class="summary">{summary}</div>

  <h2>Breakdown</h2>
  {items_html}

  <div class="disclaimer">
    <strong>⚠️ This is an AI-generated reading, not legal advice.</strong><br>
    Claude Haiku read the policy text and scored it against a rubric based on
    PIPEDA's fair information principles. AI makes mistakes — it can miss
    context, misread legalese, or get a status wrong. Before acting on this
    report (publishing, citing, or making decisions), <strong>read the
    original policy yourself and verify every claim</strong>. This tool is a
    first-pass reader, not a compliance audit.
  </div>

  <div class="footer">Generated by WhereIsMyData · {model}</div>
</div>
</body>
</html>
"""


ITEM_TEMPLATE = """  <div class="item">
    <div class="item-head">
      <div class="item-label">{label}</div>
      <span class="badge {status}">{status_display}</span>
    </div>
    <div class="item-note">{note}</div>
    {evidence_html}
  </div>
"""


def render_report(policy: FetchedPolicy, scoring: dict, score: float, grade: str) -> str:
    items_html = []
    for key, label, _, _ in RUBRIC:
        item = scoring["items"].get(key, {})
        status = item.get("status", "no")
        note = item.get("note", "—")
        evidence = item.get("evidence", "")
        evidence_html = (
            f'<div class="item-evidence">Evidence: {evidence}</div>'
            if evidence else ""
        )
        items_html.append(ITEM_TEMPLATE.format(
            label=label,
            status=status,
            status_display=status.upper(),
            note=note,
            evidence_html=evidence_html,
        ))

    company_display = urlparse(policy.company_url).netloc or policy.company_url

    return REPORT_TEMPLATE.format(
        company_display=company_display,
        policy_url=policy.policy_url,
        grade=grade,
        grade_lower=grade.lower(),
        score=score,
        summary=scoring.get("summary", ""),
        items_html="\n".join(items_html),
        model=MODEL,
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scan_one(client: Anthropic, url: str, out_path: Path) -> dict:
    print(f"→ Fetching {url}")
    policy = fetch_policy(url)
    print(f"  Found policy: {policy.policy_url}")
    if policy.truncated:
        print(f"  (truncated to {MAX_POLICY_CHARS} chars)")

    print("  Scoring with Claude...")
    scoring = score_policy(client, policy)
    score, grade = calculate_score(scoring)
    print(f"  Score: {score}/100  Grade: {grade}")

    html = render_report(policy, scoring, score, grade)
    out_path.write_text(html, encoding="utf-8")
    print(f"  Report → {out_path}")

    return {
        "company": urlparse(url).netloc,
        "url": url,
        "policy_url": policy.policy_url,
        "score": score,
        "grade": grade,
        "summary": scoring.get("summary", ""),
        "report_path": str(out_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="Company URL (homepage)")
    ap.add_argument("--batch", help="Text file with one URL per line")
    ap.add_argument("--out", default="report.html",
                    help="Output HTML file (single) or directory (batch)")
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: set ANTHROPIC_API_KEY env var", file=sys.stderr)
        sys.exit(1)

    client = Anthropic()

    if args.batch:
        urls = [
            line.strip() for line in Path(args.batch).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for url in urls:
            try:
                slug = re.sub(r"[^a-z0-9]+", "-",
                              urlparse(url).netloc.lower()).strip("-")
                result = scan_one(client, url, out_dir / f"{slug}.html")
                results.append(result)
            except Exception as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                results.append({"url": url, "error": str(e)})
        (out_dir / "results.json").write_text(json.dumps(results, indent=2))
        print(f"\nBatch complete. Index → {out_dir/'results.json'}")
        return

    if not args.url:
        ap.error("provide a URL or use --batch")
    scan_one(client, args.url, Path(args.out))


if __name__ == "__main__":
    main()
