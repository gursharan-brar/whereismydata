# WhereIsMyData

**An AI-assisted reader for Canadian privacy policies.**

[Try it live →](https://gursharan-brar.github.io/whereismydata)

Paste any privacy policy. Get an A–F grade scored against PIPEDA's fair information principles. Claude does the reading, you decide what to do with it.

![preview](docs/preview.png) <!-- add screenshot once deployed -->

---

## Why this exists

Canadian privacy policies are long, dense, and written so you won't read them. Most people scroll, click "I agree," and never find out:

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

---

## Two ways to use it

### 1. Web app — paste-and-go

[gursharan-brar.github.io/whereismydata](https://gursharan-brar.github.io/whereismydata)

- Bring your own [Anthropic API key](https://console.anthropic.com/settings/keys) ($5 signup credit covers ~500 scans)
- Paste a policy → click scan → get graded
- 100% in-browser. No server, no analytics, no tracking
- Your key stays in your tab; only goes to `api.anthropic.com`

### 2. Python CLI — batch scanning

For grading 50 policies at once. Fetches the policy text from a URL automatically.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# One company
python scan.py https://www.timhortons.ca --out tims.html

# A whole list
python scan.py --batch companies.txt --out reports/
```

---

## ⚠ This is AI. AI makes mistakes.

Claude Haiku reads policies fast but it can:

- Miss disclosures buried in linked sub-policies
- Misread legal hedging as clarity
- Get a status wrong on a vague disclosure

**Before citing a grade publicly or making a decision based on it, read the original policy yourself.** This is a first-pass reader, not a compliance audit, and definitely not legal advice.

The grading language deliberately avoids "violates PIPEDA" and uses "discloses / does not disclose clearly" — compliance is a legal call, not an AI call.

---

## Repo layout

```
whereismydata/
├── index.html          ← web app (drops into GitHub Pages)
├── styles.css          ← surveillance-terminal noir
├── app.js              ← client logic, Claude API call
├── scan.py             ← Python CLI for batch scanning
├── companies.txt       ← starter list of 50 Canadian sites
├── requirements.txt    ← Python deps
├── LICENSE
└── README.md
```

---

## Deploy your own

1. Fork this repo
2. Settings → Pages → Source: `main` branch, `/` root
3. Live at `<your-username>.github.io/whereismydata` in ~90 seconds

---

## Built by

**Gursharan Brar** · IT Services Diploma student at SAIT, Calgary
[LinkedIn](https://www.linkedin.com/in/brar-gursharan13/) · [Portfolio](https://gursharan-brar.github.io/brar-portfolio/) · [GitHub](https://github.com/gursharan-brar)

## License

MIT. Fork it, break it, improve it.
