/* ===========================================================================
   WhereIsMyData — client logic
   All work happens in the browser. No server, no analytics.
   =========================================================================== */

const MODEL = "claude-haiku-4-5-20251001";
const MAX_POLICY_CHARS = 60000;
const STORAGE_KEY = "wimd_api_key";

// ---------------------------------------------------------------------------
// Rubric — grounded in PIPEDA fair information principles + Alberta PIPA
// ---------------------------------------------------------------------------
const RUBRIC = [
  { key: "accountability", label: "Accountability",
    looking: "Names a privacy officer or contact and gives a way to reach them",
    weight: 10 },
  { key: "purpose_identified", label: "Purpose identified",
    looking: "States WHY data is being collected, in plain language, before/at collection",
    weight: 10 },
  { key: "consent_clear", label: "Consent is clear",
    looking: "Explains how consent is obtained and how users can withdraw it",
    weight: 10 },
  { key: "data_minimization", label: "Data minimization",
    looking: "Limits collection to what's needed for the stated purpose — no vague 'and other data'",
    weight: 8 },
  { key: "third_party_sharing", label: "Third-party sharing",
    looking: "Lists categories of third parties data is shared with, and why",
    weight: 12 },
  { key: "data_location", label: "Data storage location",
    looking: "Says WHERE data is stored (Canada / US / EU / 'globally') and notes cross-border transfer",
    weight: 12 },
  { key: "retention", label: "Retention period",
    looking: "Says how long data is kept, or the criteria used to decide",
    weight: 8 },
  { key: "security", label: "Security measures",
    looking: "Describes safeguards (encryption, access controls) in more than one generic sentence",
    weight: 8 },
  { key: "user_rights", label: "User rights",
    looking: "Tells users how to access, correct, or delete their data, and how to complain",
    weight: 10 },
  { key: "plain_language", label: "Plain language",
    looking: "Readable by a non-lawyer. No wall-of-text legalese. Has headings, structure",
    weight: 6 },
  { key: "last_updated", label: "Last-updated date",
    looking: "Shows when the policy was last revised",
    weight: 6 },
];

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

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
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

$("loadSampleBtn").addEventListener("click", () => {
  $("policyText").value = SAMPLE_POLICY;
  $("charCount").textContent = SAMPLE_POLICY.length.toLocaleString();
});

// ---------------------------------------------------------------------------
// Scoring
// ---------------------------------------------------------------------------
function letterGrade(score) {
  if (score >= 85) return "A";
  if (score >= 70) return "B";
  if (score >= 55) return "C";
  if (score >= 40) return "D";
  return "F";
}

function gradeColor(g) {
  return {
    A: "var(--c-grade-a)",
    B: "var(--c-grade-b)",
    C: "var(--c-grade-c)",
    D: "var(--c-grade-d)",
    F: "var(--c-grade-f)",
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

function calculateScore(scoring) {
  let total = 0;
  for (const item of RUBRIC) {
    const status = (scoring.items[item.key] || {}).status || "no";
    if (status === "yes") total += item.weight;
    else if (status === "partial") total += item.weight * 0.5;
  }
  return Math.round(total * 10) / 10;
}

// ---------------------------------------------------------------------------
// Claude call (direct browser → api.anthropic.com)
// ---------------------------------------------------------------------------
function buildPrompt(policyText) {
  const rubricForPrompt = RUBRIC.map(r => ({
    key: r.key, label: r.label, looking_for: r.looking,
  }));
  return `You are reading a privacy policy and scoring it against a rubric grounded in Canada's PIPEDA fair information principles and Alberta's PIPA.

You are NOT making a legal determination. You are checking whether the policy TEXT discloses certain things clearly. Hedge accordingly. Never write "violates PIPEDA" — write "the policy does/does not disclose X clearly."

For each rubric item, return:
  - status: "yes" (clearly addressed), "partial" (mentioned vaguely), or "no" (missing/unclear)
  - evidence: 1-2 short quotes or paraphrases from the policy (under 15 words each)
  - note: one short sentence explaining your call

Rubric:
${JSON.stringify(rubricForPrompt, null, 2)}

Privacy policy text (may be truncated):
---
${policyText}
---

Return ONLY valid JSON, no preamble, no markdown fences, in this exact shape:
{
  "items": {
    "<key>": {"status": "yes|partial|no", "evidence": "...", "note": "..."}
  },
  "summary": "2-3 sentence plain-English summary of the policy's strengths and weaknesses"
}`;
}

async function callClaude(apiKey, prompt) {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model: MODEL,
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
// Render results
// ---------------------------------------------------------------------------
function renderResults(scoring) {
  const score = calculateScore(scoring);
  const grade = letterGrade(score);

  $("gradeLetter").textContent = grade;
  $("gradeLetter").style.color = gradeColor(grade);
  $("scoreNum").textContent = score;
  $("gradeTag").textContent = gradeTag(grade);
  $("summaryBox").textContent = scoring.summary || "—";

  const breakdown = $("breakdown");
  breakdown.innerHTML = "";
  for (const item of RUBRIC) {
    const r = scoring.items[item.key] || {
      status: "no",
      note: "Not addressed in the policy.",
      evidence: ""
    };
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
// Rubric table
// ---------------------------------------------------------------------------
function renderRubricTable() {
  const tbody = $("rubricBody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const item of RUBRIC) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="crit">${escapeHtml(item.label)}</td>
      <td class="look">${escapeHtml(item.looking)}</td>
      <td class="weight">${item.weight}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
$("scanBtn").addEventListener("click", async () => {
  const apiKey = $("apiKey").value.trim();
  let policyText = $("policyText").value.trim();

  if (!apiKey) { flash("Add your Anthropic API key first.", "error"); return; }
  if (!apiKey.startsWith("sk-ant-")) {
    flash("That doesn't look like an Anthropic key.", "error"); return;
  }
  if (policyText.length < 200) {
    flash("Paste the full privacy policy (at least 200 characters).", "error"); return;
  }

  let truncated = false;
  if (policyText.length > MAX_POLICY_CHARS) {
    policyText = policyText.slice(0, MAX_POLICY_CHARS);
    truncated = true;
  }

  $("scanBtn").disabled = true;
  $("results").classList.remove("show");
  flash(`Reading the policy with Claude...${truncated ? " (truncated to fit)" : ""}`, "info");

  try {
    const prompt = buildPrompt(policyText);
    const scoring = await callClaude(apiKey, prompt);
    if (!scoring.items) throw new Error("Model returned no rubric items.");
    clearFlash();
    renderResults(scoring);
  } catch (err) {
    console.error(err);
    flash(`Scan failed: ${err.message}`, "error");
  } finally {
    $("scanBtn").disabled = false;
  }
});

// Init
updateKeyStatus();
renderRubricTable();
