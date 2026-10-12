const SUGGESTIONS = [
  "What caused the INC-PAY-001 outage, what is the latest recovery procedure, and what work remains?",
  "What blockers were raised in Slack for INC-PAY-001?",
  "Were there any security findings for INC-PAY-001?",
  "How many payment attempts timed out during INC-PAY-001?",
];

const $ = (id) => document.getElementById(id);
let users = [];
let session = null;
let turnCount = 0;

function currentUser() {
  return users.find((u) => u.name === $("user").value);
}

function store(key, value) {
  try { sessionStorage.setItem(key, value); } catch (_) { /* private mode */ }
}

function renderAccounts() {
  const u = currentUser();
  $("accounts").innerHTML = Object.entries(u.accounts).map(([source, has]) =>
    `<span class="chip p-${esc(source)} ${has ? "" : "off"}" title="${has ? "account linked" : "no account on this platform"}"><span class="dot"></span>${esc(platform(source).label)}</span>`
  ).join("");
  document.querySelector('[data-tab="audit"]').hidden = !u.can_audit;
  if (!u.can_audit) showTab("chat");
}

function emptyState(notice) {
  const u = currentUser();
  $("chat").innerHTML = (notice ? `<div class="banner">ⓘ ${esc(notice)} A new chat has started; your question is back in the box below.</div>` : "") + `<div class="empty">
    <h2>Signed in as ${esc(u.name)} · ${esc(u.role)}</h2>
    <div>Answers use only documents ${esc(u.name)} can open in each platform at the moment of asking.</div>
    <div class="suggestions">${SUGGESTIONS.map((s) => `<button class="btn" type="button">${esc(s)}</button>`).join("")}</div>
  </div>`;
  $("chat").querySelectorAll(".suggestions button").forEach((b) =>
    b.addEventListener("click", () => { $("question").value = b.textContent; ask(); }));
}

function load(key) {
  try { return sessionStorage.getItem(key); } catch (_) { return null; }
}

function saveTranscript() {
  store("transcript", turnCount ? $("chat").innerHTML : "");
  store("turnCount", String(turnCount));
}

async function startSession(name, notice) {
  users = await api("GET", "/api/users");
  const res = await api("POST", "/api/session", { user: name });
  session = res.session;
  store("session", session);
  store("user", name);
  turnCount = 0;
  saveTranscript();
  renderAccounts();
  emptyState(notice);
}

async function resumeSession() {
  // a reload or back navigation keeps the same chat, so revocation still applies to earlier answers
  const saved = load("session");
  if (!saved) return false;
  try {
    const res = await api("GET", "/api/session", null, saved);
    if (res.user !== $("user").value) return false;
    session = saved;
    turnCount = Number(load("turnCount") || 0);
    renderAccounts();
    if (turnCount && load("transcript")) $("chat").innerHTML = load("transcript");
    else emptyState();
    return true;
  } catch (_) {
    return false;
  }
}

async function ask() {
  const question = $("question").value.trim();
  if (!question) return;
  if (!turnCount) $("chat").innerHTML = "";
  const turnId = `t${++turnCount}`;
  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML = `<div class="question"><span class="who">${esc($("user").value)}</span><span>${esc(question)}</span></div>
    <div class="answer none thinking">Checking access and reading sources…</div>`;
  $("chat").appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "end" });
  $("question").value = "";
  $("askBtn").disabled = true;

  try {
    const r = await api("POST", "/api/ask", { question }, session);
    const banner = r.dropped
      ? `<div class="banner">ⓘ Earlier answers were removed from this chat: their sources changed or are no longer available to you.</div>`
      : "";
    const body = r.citations.length
      ? `<div class="answer">${renderAnswer(r.answer, turnId)}</div><div class="cards">${renderCards(r.citations, turnId)}</div>`
      : `<div class="answer none">${esc(r.answer)}</div>`;
    for (const seq of r.dropped_turns || []) redactTurn(seq);
    turn.dataset.seq = r.audit_seq;
    turn.innerHTML = banner + turn.querySelector(".question").outerHTML + body + `<div class="meta">audit #${r.audit_seq}</div>`;
    saveTranscript();
  } catch (err) {
    if (err.status === 401) {
      await startSession($("user").value, err.message);
      $("question").value = question;
    } else {
      turn.querySelector(".answer").outerHTML = `<div class="answer none error">${esc(err.message)}</div>`;
      saveTranscript();
    }
  } finally {
    $("askBtn").disabled = false;
    $("question").focus();
  }
}

function redactTurn(seq) {
  const old = $("chat").querySelector(`.turn[data-seq="${seq}"]`);
  if (!old) return;
  old.querySelectorAll(".answer, .cards, .banner").forEach((el) => el.remove());
  old.querySelector(".question").insertAdjacentHTML("afterend",
    `<div class="answer none">This answer was removed: its sources changed or are no longer available to you.</div>`);
}

function loseAuditAccess(message) {
  const u = currentUser();
  if (u) u.can_audit = false;
  document.querySelector('[data-tab="audit"]').hidden = true;
  showTab("chat");
  toastMessage(message);
}

function toastMessage(message) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

async function refreshSync() {
  try {
    const s = await api("GET", "/api/sync");
    $("syncbar").innerHTML = s.sources.map((r) => {
      const err = s.errors[r.source];
      return `<span class="p-${esc(r.source)} ${err ? "err" : ""}" title="${esc(err || "")}"><span class="dot"></span> ${esc(platform(r.source).label)}${platform(r.source).standIn ? "*" : ""} ${err ? "sync failing" : `synced ${ago(r.last_run)}`} · ${r.docs} docs</span>`;
    }).join("") + (s.sources.some((r) => platform(r.source).standIn) ? `<span>* stand-in</span>` : "");
  } catch (_) { /* server restarting */ }
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $("chatView").hidden = name !== "chat";
  $("composer").hidden = name !== "chat";
  $("auditView").hidden = name !== "audit";
  if (name === "audit") searchAudit();
}

async function searchAudit() {
  const params = new URLSearchParams(new FormData($("auditForm")));
  try {
    const rows = await api("GET", `/api/audit?${params}`, null, session);
    $("auditCount").textContent = `${rows.length} entr${rows.length === 1 ? "y" : "ies"}`;
    $("entries").innerHTML = rows.map(renderEntry).join("") || `<div class="empty">No entries match.</div>`;
  } catch (err) {
    $("entries").innerHTML = "";
    if (err.status === 403) return loseAuditAccess(err.message);
    $("entries").innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

function renderEntry(r) {
  const d = r.data;
  const decisions = r.matched?.length ? r.matched : d.decisions || [];
  const allowed = decisions.filter((x) => x.allowed).length;
  const denied = decisions.length - allowed;
  let body = "";
  if (d.question) body += `<p><b>Asked:</b> ${esc(d.question)}</p>`;
  if (decisions.length) {
    body += decisions.map((x) => `<div class="decision"><span class="${x.allowed ? "allow" : "deny"}">${x.allowed ? "ALLOW" : "DENY"}</span>
      <span>${platformChip(x.source)} <span class="mono">${esc(x.doc_id)}</span> v${esc(x.version ?? "–")} · ${esc(x.title)} <span class="meta">(${esc(x.reason)})</span></span></div>`).join("");
  }
  if (d.dropped) body += d.dropped.map((x) => `<p><b>Dropped earlier turn:</b> “${esc(x.question)}” — ${x.problems.map((p) => `${esc(p.source)} ${esc(p.doc_id)}: ${esc(p.reason)}`).join(", ")}</p>`).join("");
  if (d.updated) body += `<p><b>Synced:</b> ${d.updated.map((u) => `${esc(u.title)} v${esc(u.version)}`).join(", ") || "–"}</p>`;
  if (d.cited?.length) body += `<p><b>Cited:</b> ${d.cited.map((c) => `${esc(c.source)}:${esc(c.doc_id)} v${esc(c.version)}`).join(", ")}</p>`;
  if (d.answer) body += `<p><b>Answer:</b> ${esc(d.answer)}</p>`;
  if (d.filters) body += `<p><b>Filters:</b> <span class="mono">${esc(JSON.stringify(d.filters))}</span></p>`;
  return `<details class="entry"><summary>
      <span class="mono">#${r.seq}</span><span class="meta">${esc(new Date(r.ts).toLocaleString())}</span>
      <b>${esc(r.user)}</b><span class="tag">${esc(r.event)}</span>
      ${decisions.length ? `<span class="allow">${allowed} allow</span><span class="deny">${denied} deny</span>` : ""}
      <span>${esc((d.question || "").slice(0, 90))}</span>
    </summary><div class="body">${body}</div></details>`;
}

async function verify() {
  try {
    const v = await api("POST", "/api/audit/verify", {}, session);
    $("verifyResult").innerHTML = v.problems.length
      ? `<span class="verify bad">✗ Tampered: ${v.problems.map((p) => `#${p.seq} ${esc(p.reason)}`).join("; ")}</span>`
      : `<span class="verify ok">✓ Intact: ${v.count} entries, hash chain verified</span>`;
  } catch (err) {
    $("verifyResult").innerHTML = "";
    if (err.status === 403) return loseAuditAccess(err.message);
    $("verifyResult").innerHTML = `<span class="error">${esc(err.message)}</span>`;
  }
}

async function init() {
  users = await api("GET", "/api/users");
  $("user").innerHTML = users.map((u) => `<option value="${esc(u.name)}">${esc(u.name)} · ${esc(u.role)}</option>`).join("");
  document.querySelector('#auditForm [name="user"]').innerHTML += users.map((u) => `<option>${esc(u.name)}</option>`).join("");
  const saved = load("user");
  $("user").value = users.some((u) => u.name === saved) ? saved : "ShiHan";
  if (!(await resumeSession())) await startSession($("user").value);

  $("user").addEventListener("change", () => startSession($("user").value));
  $("askForm").addEventListener("submit", (e) => { e.preventDefault(); ask(); });
  $("resetBtn").addEventListener("click", async () => {
    await api("POST", "/api/reset-chat", {}, session).catch(() => startSession($("user").value));
    turnCount = 0;
    saveTranscript();
    emptyState();
  });
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("auditSearch").addEventListener("click", searchAudit);
  $("auditForm").addEventListener("submit", (e) => { e.preventDefault(); searchAudit(); });
  $("auditVerify").addEventListener("click", verify);

  refreshSync();
  setInterval(refreshSync, 10000);
}

init().catch((err) => { document.body.innerHTML = `<p class="error" style="padding:20px">${esc(err.message)}</p>`; });
