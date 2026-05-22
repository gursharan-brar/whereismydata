"""
WhereIsMyData — Canadian privacy policy scanner
Backend server + CLI

Modes:
  python server.py serve                          # start FastAPI on port 8000
  python server.py https://example.com            # scan one URL, write report.html
  python server.py https://example.com --out x.html
  python server.py --batch companies.txt --out reports/

API endpoints (when running as server):
  GET  /                    serves index.html
  GET  /static/*            serves app.js, rubric.json, etc.
  GET  /api/rubric          returns rubric.json content
  POST /api/scan-url        body: {url}  header: x-anthropic-key
  POST /api/scan-text       body: {policy_text}  header: x-anthropic-key

The server never logs the x-anthropic-key header. It passes the key straight
through to the Anthropic SDK and discards it. No key is stored server-side.

What it is NOT:
  Legal advice. This is an AI-assisted reading tool. Verify everything
  yourself before acting on it.
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# Load rubric from rubric.json — single source of truth
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
_RUBRIC_PATH = _HERE / "rubric.json"

with _RUBRIC_PATH.open(encoding="utf-8") as _f:
    _RUBRIC_DATA = json.load(_f)

RUBRIC = _RUBRIC_DATA["items"]           # list of {key, label, looking_for, weight}
GRADES = _RUBRIC_DATA["grades"]          # {"A": 85, "B": 70, ...}
SCORING_PROMPT_TEMPLATE = _RUBRIC_DATA["scoring_prompt"]
MODEL = _RUBRIC_DATA["model"]
MAX_POLICY_CHARS = _RUBRIC_DATA["max_policy_chars"]

# Sanity check
_total_weight = sum(item["weight"] for item in RUBRIC)
assert _total_weight == 100, f"Rubric weights must sum to 100, got {_total_weight}"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (compatible; WhereIsMyDataBot/1.0; "
    "+https://github.com/gursharan-brar/whereismydata)"
)

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
# Grading helpers
# ---------------------------------------------------------------------------

def letter_grade(score: float) -> str:
    for letter in ("A", "B", "C", "D"):
        if score >= GRADES[letter]:
            return letter
    return "F"


def calculate_score(scoring: dict) -> tuple[float, str]:
    total = 0.0
    for item in RUBRIC:
        key = item["key"]
        weight = item["weight"]
        status = scoring["items"].get(key, {}).get("status", "no")
        if status == "yes":
            total += weight
        elif status == "partial":
            total += weight * 0.5
    score = round(total, 1)
    return score, letter_grade(score)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_html(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text


def find_policy_url(home_url: str, home_html: str) -> str | None:
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
    candidates.sort(key=lambda u: ("privacy" not in u.lower(), len(u)))
    return candidates[0] if candidates else None


def extract_text_from_html(html_str: str) -> str:
    soup = BeautifulSoup(html_str, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def fetch_policy(company_url: str) -> dict:
    """Fetch and extract policy text from a company URL.

    Returns a dict with keys: company_url, policy_url, policy_text, truncated.
    Raises RuntimeError if no policy link is found.
    """
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

    return {
        "company_url": company_url,
        "policy_url": policy_url,
        "policy_text": policy_text,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Claude scoring
# ---------------------------------------------------------------------------

def score_policy(client: Anthropic, policy_text: str) -> dict:
    """Send policy text to Claude and return the raw scoring dict."""
    rubric_for_prompt = [
        {"key": item["key"], "label": item["label"], "looking_for": item["looking_for"]}
        for item in RUBRIC
    ]
    prompt = (
        SCORING_PROMPT_TEMPLATE
        .replace("%RUBRIC_JSON%", json.dumps(rubric_for_prompt, indent=2))
        .replace("%POLICY_TEXT%", policy_text)
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


# ---------------------------------------------------------------------------
# HTML report renderer (CLI output only)
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhereIsMyData — TITLE_PLACEHOLDER</title>
<style>
  :root {
    --bg: #0a0e17; --surface: #111824; --surface-2: #182233;
    --text: #e6eaf2; --muted: #8a96ab; --accent: #5eead4;
    --yes: #4ade80; --partial: #fbbf24; --no: #f87171;
    --grade-a: #4ade80; --grade-b: #86efac; --grade-c: #fbbf24;
    --grade-d: #fb923c; --grade-f: #f87171;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: 'Inter', system-ui, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.55; }
  .wrap { max-width: 880px; margin: 0 auto; padding: 48px 24px 96px; }
  .brand { font-size: 13px; letter-spacing: .18em; text-transform: uppercase;
           color: var(--accent); margin-bottom: 8px; }
  h1 { margin: 0 0 8px; font-size: 36px; font-weight: 700; letter-spacing: -.02em; }
  .url { color: var(--muted); font-size: 14px; word-break: break-all; margin-bottom: 32px; }
  .url a { color: var(--muted); }
  .grade-card { background: linear-gradient(135deg, var(--surface), var(--surface-2));
    border: 1px solid #1f2a3d; border-radius: 16px; padding: 32px;
    display: flex; align-items: center; gap: 32px; margin-bottom: 32px; }
  .grade-letter { font-size: 96px; font-weight: 800; line-height: 1;
                  font-family: ui-monospace, monospace; }
  .grade-meta .score { font-size: 14px; color: var(--muted);
    text-transform: uppercase; letter-spacing: .12em; }
  .grade-meta .number { font-size: 32px; font-weight: 700; margin-top: 4px; }
  .summary { background: var(--surface); border-left: 3px solid var(--accent);
    padding: 20px 24px; border-radius: 8px; margin-bottom: 40px; color: #c9d2e2; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .18em;
       color: var(--muted); margin: 40px 0 16px; }
  .item { background: var(--surface); border: 1px solid #1f2a3d;
    border-radius: 10px; padding: 18px 20px; margin-bottom: 12px; }
  .item-head { display: flex; justify-content: space-between; align-items: center;
    gap: 16px; margin-bottom: 8px; }
  .item-label { font-weight: 600; font-size: 16px; }
  .badge { font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .1em; padding: 4px 10px; border-radius: 999px; }
  .badge.yes { background: rgba(74,222,128,.12); color: var(--yes); }
  .badge.partial { background: rgba(251,191,36,.12); color: var(--partial); }
  .badge.no { background: rgba(248,113,113,.12); color: var(--no); }
  .item-note { color: #c9d2e2; font-size: 14.5px; margin: 6px 0; }
  .item-evidence { color: var(--muted); font-size: 13px; font-style: italic;
    border-top: 1px dashed #1f2a3d; padding-top: 8px; margin-top: 8px; }
  .disclaimer { margin-top: 48px; padding: 20px 24px;
    background: rgba(248,113,113,.06); border: 1px solid rgba(248,113,113,.2);
    border-radius: 10px; color: #fbcaca; font-size: 13.5px; }
  .disclaimer strong { color: #fecaca; }
  .footer { margin-top: 32px; text-align: center; color: var(--muted); font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="brand">WhereIsMyData · Canadian Privacy Scan</div>
  <h1>COMPANY_DISPLAY_PLACEHOLDER</h1>
  <div class="url">Policy scanned: <a href="POLICY_URL_PLACEHOLDER">POLICY_URL_PLACEHOLDER</a></div>
  <div class="grade-card">
    <div class="grade-letter" style="color:var(GRADE_COLOR_PLACEHOLDER)">GRADE_PLACEHOLDER</div>
    <div class="grade-meta">
      <div class="score">Overall score</div>
      <div class="number">SCORE_PLACEHOLDER / 100</div>
    </div>
  </div>
  <div class="summary">SUMMARY_PLACEHOLDER</div>
  <h2>Breakdown</h2>
  ITEMS_HTML_PLACEHOLDER
  <div class="disclaimer">
    <strong>&#9888;&#65039; This is an AI-generated reading, not legal advice.</strong><br>
    Claude Haiku read the policy text and scored it against a rubric based on
    PIPEDA's fair information principles. AI makes mistakes — it can miss
    context, misread legalese, or get a status wrong. Before acting on this
    report (publishing, citing, or making decisions), <strong>read the
    original policy yourself and verify every claim</strong>. This tool is a
    first-pass reader, not a compliance audit.
  </div>
  <div class="footer">Generated by WhereIsMyData · MODEL_PLACEHOLDER</div>
</div>
</body>
</html>"""

_ITEM_TEMPLATE = """\
  <div class="item">
    <div class="item-head">
      <div class="item-label">ITEM_LABEL_PLACEHOLDER</div>
      <span class="badge ITEM_STATUS_PLACEHOLDER">ITEM_STATUS_DISPLAY_PLACEHOLDER</span>
    </div>
    <div class="item-note">ITEM_NOTE_PLACEHOLDER</div>
    ITEM_EVIDENCE_PLACEHOLDER
  </div>"""

_GRADE_COLORS = {
    "A": "--grade-a", "B": "--grade-b", "C": "--grade-c",
    "D": "--grade-d", "F": "--grade-f",
}


def render_report(fetch_result: dict, scoring: dict, score: float, grade: str) -> str:
    items_html_parts = []
    for item in RUBRIC:
        key = item["key"]
        label = item["label"]
        r = scoring["items"].get(key, {})
        status = r.get("status", "no")
        note = html.escape(r.get("note", "—"))
        evidence = r.get("evidence", "")
        evidence_html = (
            f'<div class="item-evidence">Evidence: {html.escape(evidence)}</div>'
            if evidence else ""
        )
        chunk = (
            _ITEM_TEMPLATE
            .replace("ITEM_LABEL_PLACEHOLDER", html.escape(label))
            .replace("ITEM_STATUS_PLACEHOLDER", status)
            .replace("ITEM_STATUS_DISPLAY_PLACEHOLDER", status.upper())
            .replace("ITEM_NOTE_PLACEHOLDER", note)
            .replace("ITEM_EVIDENCE_PLACEHOLDER", evidence_html)
        )
        items_html_parts.append(chunk)

    company_display = urlparse(fetch_result["company_url"]).netloc or fetch_result["company_url"]
    policy_url = fetch_result["policy_url"]

    report = (
        _REPORT_TEMPLATE
        .replace("TITLE_PLACEHOLDER", html.escape(company_display))
        .replace("COMPANY_DISPLAY_PLACEHOLDER", html.escape(company_display))
        .replace("POLICY_URL_PLACEHOLDER", html.escape(policy_url))
        .replace("GRADE_COLOR_PLACEHOLDER", _GRADE_COLORS.get(grade, "--grade-f"))
        .replace("GRADE_PLACEHOLDER", grade)
        .replace("SCORE_PLACEHOLDER", str(score))
        .replace("SUMMARY_PLACEHOLDER", html.escape(scoring.get("summary", "")))
        .replace("ITEMS_HTML_PLACEHOLDER", "\n".join(items_html_parts))
        .replace("MODEL_PLACEHOLDER", MODEL)
    )
    return report


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel

    app = FastAPI(title="WhereIsMyData", version="2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # user-supplied key only; no server secrets at risk
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Serve static assets (app.js, rubric.json)
    app.mount("/static", StaticFiles(directory=str(_HERE)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(_HERE / "index.html"))

    @app.get("/api/rubric")
    async def get_rubric():
        return JSONResponse(_RUBRIC_DATA)

    class ScanUrlBody(BaseModel):
        url: str

    class ScanTextBody(BaseModel):
        policy_text: str

    def _client_from_request(request: Request) -> Anthropic:
        # IMPORTANT: this header is never logged anywhere in this file.
        api_key = request.headers.get("x-anthropic-key", "").strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="x-anthropic-key header is required")
        return Anthropic(api_key=api_key)

    def _build_response(fetch_result: dict, scoring: dict) -> dict:
        score, grade = calculate_score(scoring)
        return {
            "company_url": fetch_result.get("company_url"),
            "policy_url": fetch_result.get("policy_url"),
            "truncated": fetch_result.get("truncated", False),
            "score": score,
            "grade": grade,
            "summary": scoring.get("summary", ""),
            "items": scoring.get("items", {}),
        }

    @app.post("/api/scan-url")
    async def scan_url(body: ScanUrlBody, request: Request):
        client = _client_from_request(request)
        try:
            fetch_result = fetch_policy(body.url)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        try:
            scoring = score_policy(client, fetch_result["policy_text"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Claude error: {e}")
        return _build_response(fetch_result, scoring)

    @app.post("/api/scan-text")
    async def scan_text(body: ScanTextBody, request: Request):
        client = _client_from_request(request)
        policy_text = body.policy_text[:MAX_POLICY_CHARS]
        truncated = len(body.policy_text) > MAX_POLICY_CHARS
        try:
            scoring = score_policy(client, policy_text)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Claude error: {e}")
        fetch_result = {
            "company_url": None,
            "policy_url": None,
            "truncated": truncated,
        }
        return _build_response(fetch_result, scoring)

except ImportError:
    # FastAPI not installed — server mode unavailable, CLI still works fine
    app = None  # type: ignore


# ---------------------------------------------------------------------------
# CLI (scan.py behaviour preserved)
# ---------------------------------------------------------------------------

def _scan_one_cli(client: Anthropic, url: str, out_path: Path) -> dict:
    print(f"→ Fetching {url}")
    fetch_result = fetch_policy(url)
    print(f"  Found policy: {fetch_result['policy_url']}")
    if fetch_result["truncated"]:
        print(f"  (truncated to {MAX_POLICY_CHARS} chars)")

    print("  Scoring with Claude...")
    scoring = score_policy(client, fetch_result["policy_text"])
    score, grade = calculate_score(scoring)
    print(f"  Score: {score}/100  Grade: {grade}")

    html_report = render_report(fetch_result, scoring, score, grade)
    out_path.write_text(html_report, encoding="utf-8")
    print(f"  Report → {out_path}")

    return {
        "company": urlparse(url).netloc,
        "url": url,
        "policy_url": fetch_result["policy_url"],
        "score": score,
        "grade": grade,
        "summary": scoring.get("summary", ""),
        "report_path": str(out_path),
    }


def _run_server():
    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn not installed. Run: pip install uvicorn[standard]", file=sys.stderr)
        sys.exit(1)
    if app is None:
        print("ERROR: fastapi not installed. Run: pip install fastapi", file=sys.stderr)
        sys.exit(1)
    print("Starting WhereIsMyData server on http://localhost:8000")
    print("Docs at http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)


def main():
    # Special-case: `python server.py serve`
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        _run_server()
        return

    ap = argparse.ArgumentParser(
        description="WhereIsMyData CLI — scan Canadian privacy policies",
        epilog="Run as server: python server.py serve",
    )
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
            line.strip()
            for line in Path(args.batch).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for url in urls:
            try:
                slug = re.sub(r"[^a-z0-9]+", "-",
                              urlparse(url).netloc.lower()).strip("-")
                result = _scan_one_cli(client, url, out_dir / f"{slug}.html")
                results.append(result)
            except Exception as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                results.append({"url": url, "error": str(e)})
        (out_dir / "results.json").write_text(json.dumps(results, indent=2))
        print(f"\nBatch complete. Index → {out_dir / 'results.json'}")
        return

    if not args.url:
        ap.error("provide a URL or use --batch")
    _scan_one_cli(client, args.url, Path(args.out))


if __name__ == "__main__":
    main()
