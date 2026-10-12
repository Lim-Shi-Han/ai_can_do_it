const PLATFORMS = {
  confluence: { label: "Confluence", standIn: false },
  gdrive: { label: "Drive", standIn: false },
  "jira-fixture": { label: "Jira", standIn: true },
  "slack-fixture": { label: "Slack", standIn: true },
  jira: { label: "Jira", standIn: false },
  slack: { label: "Slack", standIn: false },
};

function platform(source) {
  return PLATFORMS[source] || { label: source, standIn: false };
}

async function api(method, path, body, session) {
  const headers = { "Content-Type": "application/json" };
  if (session) headers["X-Session"] = session;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function clock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function platformChip(source, extra = "") {
  const p = platform(source);
  return `<span class="chip p-${esc(source)}"><span class="dot"></span>${esc(p.label)}${p.standIn ? ' <span class="tag">stand-in</span>' : ""}${extra}</span>`;
}

const SECTION_RE = /^\s*(?:#{1,6}\s*)?\**\s*(confirmed|unconfirmed or provisional|unconfirmed|provisional|missing)\s*\**\s*:?\s*$/i;

function inline(text, turnId) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[S(\d+)\]/g, (_, n) => `<a class="cite" href="#${turnId}-S${n}">S${n}</a>`);
}

function renderAnswer(answer, turnId) {
  const sections = [];
  let current = { name: "", lines: [] };
  for (const line of answer.split("\n")) {
    const m = line.match(SECTION_RE);
    if (m) {
      if (current.name || current.lines.some((l) => l.trim())) sections.push(current);
      current = { name: m[1], lines: [] };
    } else {
      current.lines.push(line);
    }
  }
  sections.push(current);

  return sections.map(({ name, lines }) => {
    let html = "";
    let inList = false;
    for (const raw of lines) {
      const line = raw.trim();
      const item = line.match(/^[-*•]\s+(.*)/);
      if (item) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${inline(item[1], turnId)}</li>`;
        continue;
      }
      if (inList) { html += "</ul>"; inList = false; }
      if (line) html += `<p>${inline(line.replace(/^#+\s*/, ""), turnId)}</p>`;
    }
    if (inList) html += "</ul>";
    const key = name.toLowerCase().startsWith("confirmed") ? "confirmed" : name.toLowerCase().startsWith("missing") ? "missing" : name ? "provisional" : "";
    return `<div class="section ${key}">${name ? `<h4>${esc(name)}</h4>` : ""}${html}</div>`;
  }).join("");
}

function renderCards(citations, turnId) {
  return citations.map((c) => {
    const link = /^https?:/.test(c.url);
    const tag = link ? "a" : "div";
    const attrs = link ? ` href="${esc(c.url)}" target="_blank" rel="noopener"` : "";
    return `<${tag} class="card p-${esc(c.source)}" id="${turnId}-${esc(c.tag)}"${attrs}>
      <div class="t"><span class="cite">${esc(c.tag)}</span> ${esc(c.title)}</div>
      <div class="m">${platformChip(c.source)} <span>v${esc(c.version)}</span> <span>updated ${esc(ago(c.updated_at))}</span></div>
    </${tag}>`;
  }).join("");
}

function toast(message, ok = true) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = (ok ? "" : "⚠ ") + message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}
