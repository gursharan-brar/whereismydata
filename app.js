/* ===========================================================================
   WhereIsMyData — client logic
   Two modes:
     Static mode  — rubric fetched from rubric.json, JS calls api.anthropic.com
                    directly. Works from file:// or GitHub Pages. No server needed.
     Server mode  — rubric fetched from /api/rubric, URL scanning calls
                    POST /api/scan-url on the local backend.
   No analytics. No tracking. No third-party scripts.
   =========================================================================== */

const STORAGE_KEY = "wimd_api_key";

// ---------------------------------------------------------------------------
// Rubric — loaded from /api/rubric (server mode) or rubric.json (static mode).
// Populated by loadRubric() before anything that needs it runs.
// ---------------------------------------------------------------------------
let RUBRIC = [];          // [{key, label, looking_for, weight}, ...]
let RUBRIC_DATA = null;   // full rubric.json object (includes prompt template, model, etc.)

async function loadRubric() {
  // Try the API endpoint first (server mode).
  // Fall back to the bundled rubric.json file (static / GitHub Pages mode).
  for (const url of ["/api/rubric", "rubric.json"]) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) continue;
      RUBRIC_DATA = await resp.json();
      RUBRIC = RUBRIC_DATA.items;
      return;
    } catch (_) {
      // Try next source
    }
  }
  // If both fail, the user will get a clear error when they try to scan.
  console.error("WhereIsMyData: could not load rubric from /api/rubric or rubric.json");
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function flash(msg, kind = "info") {
  const s = $("status");
  s.innerHTML = kind === "info" && msg.includes("...")
    ? `<span class="dots">${escapeHtml(msg.replace(/\.+$/, ""))}</span>`
    : escapeHtml(msg);
  s.className = `status show ${kind}`;
}
function clearFlash() {
  $("status").className = "status";
  $("status").textContent = "";
}

// ---------------------------------------------------------------------------
// API key handling
// ---------------------------------------------------------------------------
function updateKeyStatus() {
  const k = $("apiKey").value.trim();
  const status = $("keyStatus");
  if (!k) status.textContent = "No key entered.";
  else if (!k.startsWith("sk-ant-")) status.textContent = "⚠ Doesn't look like an Anthropic key";
  else status.textContent = `Key loaded · ${k.length} chars`;
}

$("apiKey").addEventListener("input", updateKeyStatus);

$("toggleKey").addEventListener("click", () => {
  const input = $("apiKey");
  const btn = $("toggleKey");
  if (input.type === "password") {
    input.type = "text";
    btn.textContent = "hide";
    btn.setAttribute("aria-pressed", "true");
  } else {
    input.type = "password";
    btn.textContent = "show";
    btn.setAttribute("aria-pressed", "false");
  }
});

$("rememberKey").addEventListener("click", () => {
  const v = $("apiKey").value.trim();
  if (!v) { flash("Enter a key first.", "error"); return; }
  try {
    localStorage.setItem(STORAGE_KEY, v);
    flash("Key saved in this browser only.", "info");
  } catch (e) {
    flash("Could not save key locally.", "error");
  }
});

$("clearKey").addEventListener("click", () => {
  $("apiKey").value = "";
  try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  updateKeyStatus();
  flash("Key cleared.", "info");
});

// Restore saved key
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) $("apiKey").value = saved;
} catch (e) {}

// ---------------------------------------------------------------------------
// Policy textarea
// ---------------------------------------------------------------------------
$("policyText").addEventListener("input", () => {
  $("charCount").textContent = $("policyText").value.length.toLocaleString();
});

const SAMPLE_POLICY = `Acme Corp Privacy Policy
Last updated: January 15, 2026

We at Acme Corp care about your privacy. This policy describes how we collect, use, and share information about you when you use our services.

Information we collect:
- Account information: name, email address, phone number when you sign up
- Usage data: how you interact with our app, pages viewed, features used
- Device information: IP address, browser type, operating system
- Location data: approximate location based on IP

How we use it:
We use this information to provide our services, improve our product, send you marketing emails (you can opt out), and analyze usage patterns.

Sharing:
We share data with our service providers (cloud hosting, email delivery, analytics) and with law enforcement when legally required. We do not sell your personal information.

Data storage:
Your data is stored on servers operated by our cloud provider in the United States. By using our service, you consent to the transfer of your data to the US.

How long we keep it:
We retain your data as long as your account is active, and for up to 2 years after account closure for legal and accounting purposes.

Your rights:
You can access, correct, or delete your data by emailing privacy@acmecorp.example. If you have a complaint, you can contact the Office of the Privacy Commissioner of Canada.

Contact:
Privacy Officer: privacy@acmecorp.example
`;

$("loadSampleBtn").addEventListener("click", () => {
  $("policyText").value = SAMPLE_POLICY;
  $("charCount").textContent = SAMPLE_POLICY.length.toLocaleString();
});

// ---------------------------------------------------------------------------
// Grading helpers
// ---------------------------------------------------------------------------
function letterGrade(score) {
  if (!RUBRIC_DATA) {
    // Fallback hardcoded boundaries if rubric hasn't loaded
    if (score >= 85) return "A";
    if (score >= 70) return "B";
    if (score >= 55) return "C";
    if (score >= 40) return "D";
    return "F";
  }
  const g = RUBRIC_DATA.grades;
  if (score >= g.A) return "A";
  if (score >= g.B) return "B";
  if (score >= g.C) return "C";
  if (score >= g.D) return "D";
  return "F";
}

function gradeColor(g) {
  return {
    A: "var(--c-grade-a)", B: "var(--c-grade-b)", C: "var(--c-grade-c)",
    D: "var(--c-grade-d)", F: "var(--c-grade-f)",
  }[g];
}

function gradeTag(g) {
  return {
    A: "STRONG · clear disclosures",
    B: "GOOD · minor gaps",
    C: "OK · missing key disclosures",
    D: "WEAK · several gaps",
    F: "POOR · major disclosures missing",
  }[g];
}

function calculateScore(scoringItems) {
  // scoringItems: { key: {status, ...}, ... }
  let total = 0;
  for (const item of RUBRIC) {
    const status = (scoringItems[item.key] || {}).status || "no";
    if (status === "yes") total += item.weight;
    else if (status === "partial") total += item.weight * 0.5;
  }
  return Math.round(total * 10) / 10;
}

// ---------------------------------------------------------------------------
// Claude call — direct browser → api.anthropic.com (static / text mode)
// ---------------------------------------------------------------------------
function buildPrompt(policyText) {
  if (!RUBRIC_DATA) throw new Error("Rubric not loaded yet — try again in a moment.");
  const rubricForPrompt = RUBRIC.map(r => ({
    key: r.key, label: r.label, looking_for: r.looking_for,
  }));
  return RUBRIC_DATA.scoring_prompt
    .replace("%RUBRIC_JSON%", JSON.stringify(rubricForPrompt, null, 2))
    .replace("%POLICY_TEXT%", policyText);
}

async function callClaudeDirect(apiKey, prompt) {
  const model = RUBRIC_DATA ? RUBRIC_DATA.model : "claude-haiku-4-5-20251001";
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model,
      max_tokens: 2500,
      messages: [{ role: "user", content: prompt }],
    }),
  });

  if (!resp.ok) {
    let body;
    try { body = await resp.json(); } catch (e) { body = await resp.text(); }
    const msg = typeof body === "object"
      ? (body.error?.message || JSON.stringify(body))
      : body;
    throw new Error(`Anthropic API ${resp.status} · ${msg}`);
  }

  const data = await resp.json();
  let raw = (data.content[0].text || "").trim();
  raw = raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "");
  return JSON.parse(raw);
}

// ---------------------------------------------------------------------------
// Backend call — browser → local server → Anthropic (server / URL mode)
// ---------------------------------------------------------------------------
async function callBackendScanUrl(apiKey, url) {
  const resp = await fetch("/api/scan-url", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-anthropic-key": apiKey,
    },
    body: JSON.stringify({ url }),
  });
  if (!resp.ok) {
    let body;
    try { body = await resp.json(); } catch (e) { body = await resp.text(); }
    const detail = typeof body === "object" ? (body.detail || JSON.stringify(body)) : body;
    throw new Error(`Server error ${resp.status} · ${detail}`);
  }
  return resp.json(); // {score, grade, summary, items, policy_url, truncated, ...}
}

async function callBackendScanText(apiKey, policyText) {
  const resp = await fetch("/api/scan-text", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-anthropic-key": apiKey,
    },
    body: JSON.stringify({ policy_text: policyText }),
  });
  if (!resp.ok) {
    let body;
    try { body = await resp.json(); } catch (e) { body = await resp.text(); }
    const detail = typeof body === "object" ? (body.detail || JSON.stringify(body)) : body;
    throw new Error(`Server error ${resp.status} · ${detail}`);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Render results
// ---------------------------------------------------------------------------
function renderResults(scoreData) {
  // scoreData can come from either path:
  //   direct Claude call → {items: {...}, summary: "..."} — we calculate score here
  //   backend call       → {score, grade, summary, items: {...}}    — pre-calculated

  let score, grade, summaryText, items;

  if (scoreData.score !== undefined) {
    // Backend response — score already calculated
    score = scoreData.score;
    grade = scoreData.grade;
    summaryText = scoreData.summary || "—";
    items = scoreData.items;
  } else {
    // Direct Claude response
    items = scoreData.items;
    score = calculateScore(items);
    grade = letterGrade(score);
    summaryText = scoreData.summary || "—";
  }

  $("gradeLetter").textContent = grade;
  $("gradeLetter").style.color = gradeColor(grade);
  $("scoreNum").textContent = score;
  $("gradeTag").textContent = gradeTag(grade);
  $("summaryBox").textContent = summaryText;

  const breakdown = $("breakdown");
  breakdown.innerHTML = "";
  for (const item of RUBRIC) {
    const r = items[item.key] || { status: "no", note: "Not addressed in the policy.", evidence: "" };
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `
      <div class="item-label">${escapeHtml(item.label)}</div>
      <span class="badge ${r.status}">${(r.status || "no").toUpperCase()}</span>
      <div class="item-note">${escapeHtml(r.note || "—")}</div>
      ${r.evidence ? `<div class="item-evidence">› ${escapeHtml(r.evidence)}</div>` : ""}
    `;
    breakdown.appendChild(div);
  }

  $("results").classList.add("show");
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------------------
// Rubric table (rendered from loaded RUBRIC, not hardcoded)
// ---------------------------------------------------------------------------
function renderRubricTable() {
  const tbody = $("rubricBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const item of RUBRIC) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="crit">${escapeHtml(item.label)}</td>
      <td class="look">${escapeHtml(item.looking_for)}</td>
      <td class="weight">${item.weight}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// Server availability check (silent — used to decide URL mode availability)
// ---------------------------------------------------------------------------
let _serverAvailable = false;

async function checkServerAvailability() {
  try {
    const resp = await fetch("/api/rubric", { method: "HEAD" });
    _serverAvailable = resp.ok;
  } catch (_) {
    _serverAvailable = false;
  }
  // Update the URL input note visibility
  const urlNote = $("urlModeNote");
  if (urlNote) {
    urlNote.textContent = _serverAvailable
      ? "Server detected — URL mode is active."
      : "URL mode requires the local server running. For static GitHub Pages, use the textarea.";
    urlNote.style.color = _serverAvailable ? "var(--c-yes, #6fcf72)" : "";
  }
}

// ---------------------------------------------------------------------------
// Main scan handler
// ---------------------------------------------------------------------------
$("scanBtn").addEventListener("click", async () => {
  if (RUBRIC.length === 0) {
    flash("Rubric still loading — wait a moment and try again.", "error");
    return;
  }

  const apiKey = $("apiKey").value.trim();
  const urlInput = ($("policyUrl") ? $("policyUrl").value.trim() : "");
  let policyText = $("policyText").value.trim();

  if (!apiKey) { flash("Add your Anthropic API key first.", "error"); return; }
  if (!apiKey.startsWith("sk-ant-")) {
    flash("That doesn't look like an Anthropic key.", "error"); return;
  }

  $("scanBtn").disabled = true;
  $("results").classList.remove("show");

  try {
    let scoreData;

    if (urlInput) {
      // --- URL mode: requires the local server ---
      if (!_serverAvailable) {
        flash("URL mode requires the local server (python server.py serve). Use the textarea instead.", "error");
        $("scanBtn").disabled = false;
        return;
      }
      flash("Fetching and scanning the URL with Claude...", "info");
      scoreData = await callBackendScanUrl(apiKey, urlInput);

    } else {
      // --- Text mode: direct browser → Anthropic ---
      if (policyText.length < 200) {
        flash("Paste the full privacy policy (at least 200 characters).", "error");
        $("scanBtn").disabled = false;
        return;
      }
      let truncated = false;
      const maxChars = RUBRIC_DATA ? RUBRIC_DATA.max_policy_chars : 60000;
      if (policyText.length > maxChars) {
        policyText = policyText.slice(0, maxChars);
        truncated = true;
      }
      flash(`Reading the policy with Claude...${truncated ? " (truncated to fit)" : ""}`, "info");
      const prompt = buildPrompt(policyText);
      scoreData = await callClaudeDirect(apiKey, prompt);
      if (!scoreData.items) throw new Error("Model returned no rubric items.");
    }

    clearFlash();
    renderResults(scoreData);
  } catch (err) {
    console.error(err);
    flash(`Scan failed: ${err.message}`, "error");
  } finally {
    $("scanBtn").disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(async () => {
  await loadRubric();
  renderRubricTable();
  updateKeyStatus();
  await checkServerAvailability();
})();
