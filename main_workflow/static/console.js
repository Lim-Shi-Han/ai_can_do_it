const $ = (id) => document.getElementById(id);
let lastGrid = {};
let options = null;

function showMembers() {
  if (!options) return;
  const ch = $("slackChannel").value;
  const target = $("jiraTarget").value;
  $("slackMembers").textContent = `Members of #${ch}: ${((options.channel_members || {})[ch] || []).join(", ") || "none"}`;
  $("jiraMembers").textContent = `Members of ${target}: ${((options.jira_members || {})[target] || []).join(", ") || "none"}`;
}

function fill(id, values, selected) {
  $(id).innerHTML = values.map((v) => `<option${v === selected ? " selected" : ""}>${esc(v)}</option>`).join("");
}

async function loadOptions() {
  const o = await api("GET", "/api/console/options");
  const keep = options ? { su: $("slackUser").value, sc: $("slackChannel").value, ju: $("jiraUser").value, jt: $("jiraTarget").value, ji: $("jiraIssue").value } : null;
  options = o;
  fill("slackUser", o.users, keep ? keep.su : "ShiHan");
  fill("slackChannel", o.channels, keep ? keep.sc : "payment-incident-001");
  fill("jiraUser", o.users, keep ? keep.ju : "Terrance");
  fill("jiraTarget", o.jira_targets, keep ? keep.jt : "PAY");
  fill("jiraIssue", o.issues, keep ? keep.ji : o.issues[0]);
  fill("jiraStatus", o.statuses, "Done");
  $("jiraAction").hidden = !o.jira;
  fill("driveUser", o.users, "ShiHan");
  fill("auditUser", o.users, "Elson");
  $("auditors").textContent = o.auditors.join(", ") || "none";
  showMembers();
  $("driveAction").hidden = !o.drive;
}

async function loadGrid() {
  $("gridRefresh").disabled = true;
  $("gridChecked").textContent = "checking…";
  try {
    const g = await api("GET", "/api/console/grid");
    const head = `<tr><th>Document</th>${g.users.map((u) => `<th>${esc(u)}</th>`).join("")}</tr>`;
    const rows = g.rows.map((r) => {
      const cells = g.users.map((u) => {
        const key = `${r.source}|${r.doc_id}|${u}`;
        const v = r.cells[u];
        const changed = key in lastGrid && lastGrid[key] !== v;
        lastGrid[key] = v;
        const mark = v === true ? '<span class="yes">✓</span>' : v === false ? '<span class="no">·</span>' : '<span class="unk" title="check failed">?</span>';
        return `<td class="${changed ? "flash" : ""}">${mark}</td>`;
      }).join("");
      return `<tr><td title="${esc(r.title)}"><span class="p-${esc(r.source)}"><span class="dot"></span></span> ${esc(r.title)} <span class="meta">v${esc(r.version)}</span></td>${cells}</tr>`;
    }).join("");
    $("grid").innerHTML = head + rows;
    $("gridChecked").textContent = `checked ${clock(g.checked_at)}`;
  } catch (err) {
    $("gridChecked").textContent = err.message;
  } finally {
    $("gridRefresh").disabled = false;
  }
}

function renderGate(entries) {
  $("gateFeed").innerHTML = entries.map((e) => {
    const d = e.data;
    if (e.event === "context_dropped") {
      return `<li><time>${clock(e.ts)}</time><b>${esc(e.user)}</b> · chat history trimmed
        ${d.dropped.map((x) => `<div class="meta">↺ dropped “${esc(x.question.slice(0, 60))}”: ${x.problems.map((p) => `${esc(platform(p.source).label)} ${esc(p.doc_id)} ${esc(p.reason)}`).join(", ")}</div>`).join("")}</li>`;
    }
    const decisions = (d.decisions || []).map((x) =>
      `<div class="decision"><span class="${x.allowed ? "allow" : "deny"}">${x.allowed ? "ALLOW" : "DENY"}</span><span>${esc(platform(x.source).label)} · ${esc(x.title)}${x.reason.includes("refreshed") ? ` <span class="tag">${esc(x.reason.split(";")[1])}</span>` : ""}</span></div>`
    ).join("");
    return `<li><time>${clock(e.ts)}</time><b>${esc(e.user)}</b> asked “${esc(d.question)}”
      <details><summary class="meta">${(d.decisions || []).filter((x) => x.allowed).length} allowed · ${(d.decisions || []).filter((x) => !x.allowed).length} denied · ${(d.cited || []).length} cited</summary>${decisions}</details></li>`;
  }).join("") || '<li class="meta">No questions yet.</li>';
}

async function loadFeed() {
  try {
    const f = await api("GET", "/api/console/feed");
    $("activity").innerHTML = f.activity.map((a) =>
      `<li class="${a.ok ? "" : "fail"}"><time>${clock(a.ts)}</time>${esc(a.text)}</li>`).join("") || '<li class="meta">Nothing yet.</li>';
    const open = new Set([...document.querySelectorAll("#gateFeed details[open]")].map((d) => d.closest("li").innerText.slice(0, 40)));
    renderGate(f.gate);
    document.querySelectorAll("#gateFeed li").forEach((li) => { if (open.has(li.innerText.slice(0, 40))) li.querySelector("details")?.setAttribute("open", ""); });
  } catch (_) { /* server restarting */ }
}

async function act(button) {
  const action = button.dataset.act;
  const grant = button.dataset.grant === "1";
  const body = { action, grant };
  if (action === "slack_access") Object.assign(body, { user: $("slackUser").value, channel: $("slackChannel").value });
  if (action === "jira_access") Object.assign(body, { user: $("jiraUser").value, target: $("jiraTarget").value });
  if (action === "jira_status") Object.assign(body, { key: $("jiraIssue").value, status: $("jiraStatus").value });
  if (action === "drive_access") Object.assign(body, { user: $("driveUser").value });
  if (action === "audit_role") Object.assign(body, { user: $("auditUser").value });
  if (action === "reset" && !confirm("Reset the rehearsal? This restores the stand-in data and the original runbook, and clears every chat.")) return;

  document.querySelectorAll("[data-act]").forEach((b) => (b.disabled = true));
  try {
    const r = await api("POST", "/api/console/action", body);
    toast(r.message, r.ok);
    if (action === "reset") lastGrid = {};
    if (["audit_role", "slack_access", "jira_access", "jira_status", "sync_now", "reset"].includes(action)) await loadOptions();
    await Promise.all([loadFeed(), action === "sync_now" ? Promise.resolve() : loadGrid()]);
  } catch (err) {
    toast(err.message, false);
  } finally {
    document.querySelectorAll("[data-act]").forEach((b) => (b.disabled = false));
  }
}

document.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => act(b)));
$("gridRefresh").addEventListener("click", loadGrid);
$("slackChannel").addEventListener("change", showMembers);
$("jiraTarget").addEventListener("change", showMembers);

loadOptions().then(loadGrid);
loadFeed();
setInterval(loadFeed, 3000);
