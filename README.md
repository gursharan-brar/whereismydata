# WhereIsMyData

**An AI-assisted reader for Canadian privacy policies.**

[Try it live →](https://gursharan-brar.github.io/whereismydata)

Paste any privacy policy — or give the tool a URL and let it fetch the policy itself.
Get an A–F grade scored against PIPEDA's fair information principles.
Claude does the reading, you decide what to do with it.

![preview](docs/preview.png) <!-- add screenshot once deployed -->

---

## Why this exists

Canadian privacy policies are long, dense, and written so you won't read them.
Most people scroll, click "I agree," and never find out:

1. Where their data is stored
2. Who else gets to see it
3. How long it's kept
4. What rights they actually have

This tool reads the thing for you and gives you a clear, scannable answer.

---

## What it checks (11 criteria, weighted to 100)

| Criterion | Weight |
|---|---|
| Accountability — privacy officer named, contact given | 10 |
| Purpose identified — why data is collected | 10 |
| Consent is clear — how given, how withdrawn | 10 |
| Data minimization — limited to what's needed | 8 |
| Third-party sharing — who, why | 12 |
| **Data storage location** — where it lives + cross-border transfer | **12** |
| Retention period stated | 8 |
| Security measures described | 8 |
| User rights — access, correct, delete, complain | 10 |
| Plain language — readable by a non-lawyer | 6 |
| Last-updated date visible | 6 |

**Grading:** A (85+) · B (70–84) · C (55–69) · D (40–54) · F (<40)

Each item is scored **yes** (full weight), **partial** (half), or **no** (zero).

The rubric, grade boundaries, scoring prompt, and model are all defined once
in [`rubric.json`](rubric.json) at the repo root. Both the Python backend and
the browser JS read from this file — there is no duplication.

---

## Two ways to use it

### Static mode — GitHub Pages, no install

[gursharan-brar.github.io/whereismydata](https://gursharan-brar.github.io/whereismydata)

- Bring your own [Anthropic API key](https://console.anthropic.com/settings/keys) ($5 signup credit covers ~500 scans)
- **Paste** a policy into the textarea → click scan → get graded
- Your browser calls `api.anthropic.com` directly — no server in the middle
- 100% client-side. No install, no analytics, no tracking
- Works offline (once the page is loaded) and from `file://`

### Server mode — local or self-hosted

Adds URL fetching: give it a company homepage and the server finds and extracts
the privacy policy text automatically. Also better for batch work.

```bash
# Install
pip install -r requirements.txt

# Start the server
python server.py serve
# → http://localhost:8000

# Batch scan a list of companies (writes HTML reports to reports/)
export ANTHROPIC_API_KEY=sk-ant-...
python server.py --batch companies.txt --out reports/

# Scan one company from the CLI
python server.py https://www.timhortons.ca --out tims.html
```

Open `http://localhost:8000` in your browser. The web UI is served by the
backend. Enter a URL in the **Company URL** field (panel B) and the server
fetches and scores the policy for you. The textarea paste flow still works
exactly as in static mode — the server just adds the URL option.

#### Deploy to Railway (free tier)

The server can be deployed to [Railway](https://railway.app) for ~$0/month on
the hobby tier, so the URL-scanning version works publicly without anyone
needing to run anything locally.

1. Fork this repo
2. New project → Deploy from GitHub repo
3. Railway auto-detects the `Procfile` and runs:
   `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Your app is live at `<project>.up.railway.app`

Users still supply their own API key via the browser UI — the server never
holds a key.

---

## ⚠ This is AI. AI makes mistakes.

Claude Haiku reads policies fast but it can:

- Miss disclosures buried in linked sub-policies
- Misread legal hedging as clarity
- Get a status wrong on a vague disclosure

**Before citing a grade publicly or making a decision based on it, read the
original policy yourself.** This is a first-pass reader, not a compliance
audit, and definitely not legal advice.

The grading language deliberately avoids "violates PIPEDA" and uses
"discloses / does not disclose clearly" — compliance is a legal call, not an AI call.

---

## Repo layout

```
whereismydata/
├── index.html          ← web app (static GitHub Pages + served by backend)
├── app.js              ← client logic; fetches rubric from /api/rubric or rubric.json
├── rubric.json         ← single source of truth: rubric, grades, prompt, model
├── server.py           ← FastAPI backend + CLI (replaces scan.py)
├── companies.txt       ← starter list of Canadian sites for batch scanning
├── requirements.txt    ← Python deps
├── Procfile            ← Railway / Heroku deploy
├── LICENSE
└── README.md
```

---

## Deploy static version (GitHub Pages)

1. Fork this repo
2. Settings → Pages → Source: `main` branch, `/` root
3. Live at `<your-username>.github.io/whereismydata` in ~90 seconds

Only `index.html`, `app.js`, and `rubric.json` are needed. Everything else
is for the server mode.

---

## Built by

**Gursharan Brar** · IT Services Diploma student at SAIT, Calgary
[LinkedIn](https://www.linkedin.com/in/brar-gursharan13/) · [Portfolio](https://gursharan-brar.github.io/brar-portfolio/) · [GitHub](https://github.com/gursharan-brar)

## License

MIT. Fork it, break it, improve it.
