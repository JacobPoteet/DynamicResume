"use strict";
// DynamicResume editor. Plain JS, no build step. State lives in S; every change to the
// tailor is saved to tailor.yaml (debounced) and the server answers with a fresh preview.

const $ = (sel, el = document) => el.querySelector(sel);
const enc = encodeURIComponent;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function api(method, path, body) {
  const opts = { method, headers: { "X-Studio": "1" } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

let toastTimer;
function toast(html, bad = false, ms = 4000) {
  const t = $("#toast");
  t.innerHTML = html;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), ms);
}
const status = (text) => ($("#status").textContent = text);
const view = (html) => ($("#view").innerHTML = html);

function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

const S = {
  init: null,      // /api/init
  master: null,    // master.yaml as plain data
  usage: {},       // bullet id -> application names
  app: null,       // {name, tailor, listing, listing_spec, letter, pdfs}
  tab: "resume",
  previews: {},    // kind -> preview response
  versions: null,  // file mtimes last seen, to notice outside edits
  ui: { editing: null, expanded: {}, lastSel: {}, focusReq: null },
};
// Tabs can veto reloading after an outside edit (unsaved typing, a running draft).
const ON_OUTSIDE_EDIT = { blocked: () => false };

// ---------- routing ----------

function route() {
  const [a, b, c] = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const section = a === "master" ? "master" : a === "snapshots" ? "snapshots" : "apps";
  document.querySelectorAll(".top nav a").forEach((n) => n.classList.toggle("on", n.dataset.nav === section));
  saveNow();
  const go = a === "app" && b ? showEditor(b, c || "resume")
    : a === "master" ? showMaster()
    : a === "snapshots" ? showSnapshots()
    : showHome();
  go.catch((e) => view(`<div class="page"><div class="card"><div class="bd">${esc(e.message)}</div></div></div>`));
}

// ---------- home ----------

function pdfPill(pdfs) {
  if (!pdfs || !pdfs.resume.exists) return `<span class="pill plain">No PDFs</span>`;
  if (pdfs.resume.stale || (pdfs.letter.exists && pdfs.letter.stale)) return `<span class="pill warn">PDFs out of date</span>`;
  return `<span class="pill good">PDFs current</span>`;
}

async function showHome() {
  S.app = null;
  const { apps } = await api("GET", "/api/apps");
  const rows = apps.map((a) => `
    <li><a href="#/app/${enc(a.name)}">
      <strong>${esc(a.studio || a.name)}</strong>
      <span class="pills"><span class="pill plain">${esc(a.template)}</span>${pdfPill(a.pdfs)}</span>
      <span class="sub">${esc(a.role)} · edited ${ago(a.updated)}</span>
    </a></li>`).join("");
  view(`<div class="page"><div class="home">
    <section class="card">
      <div class="hd"><h1>Applications</h1><span class="grow"></span><span class="muted">${apps.length}</span></div>
      ${apps.length ? `<ul class="app-list">${rows}</ul>` : `<div class="empty">Paste a job listing on the right to start your first application.</div>`}
    </section>
    <section class="card">
      <div class="hd"><h2>New application</h2></div>
      <div class="bd stack">
        <div class="target">
          <label class="field">Studio<input id="na-studio" placeholder="Sample Studio"></label>
          <label class="field">Role<input id="na-role" placeholder="Gameplay Designer"></label>
        </div>
        <label class="field">Job listing<textarea id="na-listing" rows="12" placeholder="Paste the full listing"></textarea></label>
        <div class="row" id="na-actions">
          ${S.init.claude ? `<button class="primary" id="na-draft">Create and draft with Claude</button>` : ""}
          <button id="na-create">${S.init.claude ? "Create without drafting" : "Create"}</button>
        </div>
        <div class="muted" style="font-size:12px">${S.init.claude
          ? "Drafting runs Claude Code in this repo with read-only access (a minute or two). It picks and orders bullets, writes a cover letter, and lists what the master cannot back up. Without drafting, every priority 1 bullet starts selected."
          : "Starts with every priority 1 bullet selected. Install Claude Code to draft automatically."}</div>
        <div id="na-err" class="muted"></div>
      </div>
    </section>
  </div></div>`);
  $("#na-create").onclick = () => createApp(false);
  if ($("#na-draft")) $("#na-draft").onclick = () => createApp(true);
}

async function createApp(draft) {
  const body = { studio: $("#na-studio").value, role: $("#na-role").value, listing: $("#na-listing").value };
  try {
    if (draft && !body.listing.trim()) throw new Error("Paste the listing first so Claude has something to draft from.");
    const { name } = await api("POST", "/api/apps", body);
    if (draft) await api("POST", `/api/apps/${enc(name)}/draft`);
    location.hash = `#/app/${enc(name)}/${draft ? "listing" : "resume"}`;
  } catch (e) {
    $("#na-err").innerHTML = `<span class="pill bad">${esc(e.message)}</span>`;
  }
}

// ---------- editor ----------

function normalizeTailor(t) {
  t.positions = t.positions || {};
  // projects may be a plain list (all bullets); the editor always keeps explicit ids.
  const byId = Object.fromEntries((S.master.projects || []).map((p) => [p.id, p]));
  if (Array.isArray(t.projects)) t.projects = Object.fromEntries(t.projects.map((id) => [id, null]));
  for (const [id, v] of Object.entries(t.projects || {})) {
    if (!v || !v.bullets) t.projects[id] = { bullets: (byId[id]?.bullets || []).map((b) => b.id) };
  }
  for (const [id, v] of Object.entries(t.positions)) if (!v || !v.bullets) t.positions[id] = { bullets: [] };
  return t;
}

function cleanTailor(t) {
  const out = JSON.parse(JSON.stringify(t));
  if (out.overrides && !Object.keys(out.overrides).length) delete out.overrides;
  if (out.skills_first && !out.skills_first.length) delete out.skills_first;
  if (out.projects && !Object.keys(out.projects).length) delete out.projects;
  return out;
}

async function loadApp(name) {
  const [app, m, v] = await Promise.all([
    api("GET", `/api/apps/${enc(name)}`), api("GET", "/api/master"), api("GET", `/api/versions?app=${enc(name)}`),
  ]);
  S.master = m.master;
  S.usage = m.usage;
  S.app = app;
  normalizeTailor(app.tailor);
  S.previews = {};
  S.versions = v;
  S.ui.editing = null;
  S.ui.focusReq = null;
  if (S.init.claude) checkDraft(name);
}

async function showEditor(name, tab) {
  if (!S.app || S.app.name !== name) await loadApp(name);
  S.tab = tab;
  const t = S.app.tailor;
  const tabs = [["resume", "Resume"], ["letter", "Cover letter"], ["listing", "Listing"]].filter(([k]) => TABS[k]);
  const tpl = t.template || S.init.default_template;
  view(`<div class="editor">
    <div class="ebar">
      <a href="#/" class="btn ghost">← Applications</a>
      <h1 id="e-title"></h1>
      <nav class="tabs">${tabs.map(([k, l]) => `<a href="#/app/${enc(name)}/${k}" class="${k === tab ? "on" : ""}">${l}</a>`).join("")}</nav>
      <span class="grow"></span>
      <label class="row muted" style="font-size:13px">Template
        <select id="tpl">${S.init.templates.map((x) => `<option ${x === tpl ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      </label>
      <span id="pdf-state"></span>
      <button class="primary" id="finalize">Build PDFs</button>
    </div>
    <div class="panes"><div class="pane left" id="left"></div><div class="pane right" id="right"></div></div>
  </div>`);
  renderTitle();
  renderPdfState();
  $("#tpl").onchange = (e) => { t.template = e.target.value; queueSave(0); };
  $("#finalize").onclick = finalize;
  TABS[tab].left();
  const kind = TABS[tab].preview;
  if (S.previews[kind]) renderPreview(kind);
  else {
    $("#right").innerHTML = `<div class="empty">Rendering…</div>`;
    refreshPreview(kind);
  }
}

function renderTitle() {
  const tg = S.app.tailor.target || {};
  $("#e-title").textContent = [tg.studio, tg.role].filter(Boolean).join(" · ") || S.app.name;
}

function pdfUrl(file) {
  return `/files/${S.init.apps_rel}/${enc(S.app.name)}/${enc(file)}?v=${Date.now()}`;
}

function renderPdfState() {
  const el = $("#pdf-state");
  if (!el) return;
  const p = S.app.pdfs;
  const link = (x, label) => x.exists
    ? `<a class="pill ${x.stale ? "warn" : "good"}" href="${pdfUrl(x.file)}" target="_blank" title="${x.stale ? "Older than your latest changes" : "Up to date"}">${label}${x.stale ? " (old)" : ""}</a>`
    : "";
  el.innerHTML = `<span class="row">${link(p.resume, "Resume PDF")}${link(p.letter, "Letter PDF")}</span>`;
}

async function finalize() {
  const btn = $("#finalize");
  await saveNow();
  btn.disabled = true;
  btn.textContent = "Building…";
  try {
    const r = await api("POST", `/api/apps/${enc(S.app.name)}/finalize`);
    S.app.pdfs = r.pdfs;
    renderPdfState();
    const parts = [`<a href="${r.resume}" target="_blank">Resume</a> (${describeFill(r.resume_fill)})`];
    if (r.letter) parts.push(`<a href="${r.letter}" target="_blank">Cover letter</a> (${describeFill(r.letter_fill)})`);
    const warns = r.warnings.length ? `<br>${r.warnings.map(esc).join("<br>")}` : "";
    toast(`PDFs built: ${parts.join(" · ")}${warns}`, false, 8000);
  } catch (e) {
    toast(esc(e.message), true, 8000);
  } finally {
    btn.disabled = false;
    btn.textContent = "Build PDFs";
  }
}

function describeFill(f) {
  if (!f || f.pages == null) return "page count unknown";
  return f.pages > 1 ? `${f.pages} pages` : `1 page, ${Math.round(f.fill * 100)}% full`;
}

// ---------- saving ----------

let saveTimer = null;
let saveSeq = 0;
let savePending = false;

function queueSave(delay = 300) {
  savePending = true;
  status("Unsaved changes");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, delay);
}

async function saveNow() {
  clearTimeout(saveTimer);
  if (!savePending || !S.app) return;
  savePending = false;
  const seq = ++saveSeq;
  const name = S.app.name;
  status("Saving…");
  $(".pages")?.classList.add("busy");
  try {
    const r = await api("PUT", `/api/apps/${enc(name)}/tailor`, { tailor: cleanTailor(S.app.tailor) });
    S.versions = { ...S.versions, ...r.versions };
    if (seq !== saveSeq || !S.app || S.app.name !== name) return;
    S.previews.resume = r.preview;
    for (const k of ["resume", "letter"]) if (S.app.pdfs[k].exists) S.app.pdfs[k].stale = true;
    renderPdfState();
    if (TABS[S.tab]?.preview === "resume") renderPreview("resume");
    status("Saved");
  } catch (e) {
    toast(esc(e.message), true);
    status("Save failed");
  }
}

window.addEventListener("beforeunload", (e) => {
  if (savePending) { saveNow(); e.preventDefault(); }
});

// ---------- preview ----------

async function refreshPreview(kind) {
  if (!S.app) return;
  const name = S.app.name;
  $(".pages")?.classList.add("busy");
  try {
    const p = await api("POST", `/api/apps/${enc(name)}/preview/${kind}`);
    if (!S.app || S.app.name !== name) return;
    S.previews[kind] = p;
    if (TABS[S.tab]?.preview === kind) renderPreview(kind);
  } catch (e) {
    S.previews[kind] = { ok: false, error: e.message, warnings: [] };
    renderPreview(kind);
  }
}

async function renderPreview(kind) {
  const el = $("#right");
  const p = S.previews[kind];
  if (!el || !p) return;
  // Load the new page images before swapping them in so the pane does not flicker or jump.
  await Promise.all((p.pages || []).map((u) => new Promise((ok) => {
    const img = new Image();
    img.onload = img.onerror = ok;
    img.src = u;
  })));
  if (S.previews[kind] !== p || !$("#right")) return;
  const f = p.fill || {};
  const over = f.pages > 1;
  const pct = f.fill == null ? 0 : Math.round(f.fill * 100);
  const meter = over ? "over" : pct < 90 ? "room" : "";
  let line = `<span class="muted">No layout information</span>`;
  if (f.pages != null) {
    line = over
      ? `<strong>${f.pages} pages</strong><span>runs ${pct}% into page ${f.pages}, trim to fit one page</span>`
      : `<strong>1 page</strong><span>${pct}% full</span><span class="muted">about ${plural(f.lines_free, "line")} free</span>`;
  }
  const warnings = [
    ...(p.ok ? [] : [`<li class="err">${esc(p.error)}</li>`]),
    ...(p.warnings || []).map((w) => `<li>${esc(w)}</li>`),
  ].join("");
  el.innerHTML = `
    <div class="pv-head">
      <div class="fillline">${line}</div>
      <div class="meter ${meter}"><i style="width:${over ? 100 : pct}%"></i></div>
      ${warnings ? `<ul class="warnings">${warnings}</ul>` : ""}
    </div>
    <div class="pages">${(p.pages || []).map((u, i) => `
      <div class="sheet"><img src="${u}" alt="Page ${i + 1}">${i > 0 ? `<span class="pill bad lbl">Page ${i + 1}</span>` : ""}</div>`).join("")}
    </div>`;
}

// ---------- resume tab ----------

const TABS = {
  resume: { left: renderResumeLeft, preview: "resume" },
};

function selected(kind, id) {
  const v = (S.app.tailor[kind] || {})[id];
  return v === undefined ? null : v.bullets;
}

// ----- listing match: ranks the unselected bullets and drives the requirement chips -----

const STOP = new Set(("about above after again along also among based being below between build built could " +
  "design designed designer during each every first from have having into large like made make making more most " +
  "other over same should since some such than that their them then there these they this those through under " +
  "using very well were what when where which while will with within work worked working would years your").split(" "));

function words(text) {
  return new Set((text.toLowerCase().match(/[a-z][a-z0-9+#/-]{4,}/g) || []).filter((w) => !STOP.has(w)));
}

let listingWordsCache = { text: null, words: new Set() };
function listingWords() {
  if (listingWordsCache.text !== S.app.listing) listingWordsCache = { text: S.app.listing, words: words(S.app.listing) };
  return listingWordsCache.words;
}

function requirements() {
  return S.app?.listing_spec?.requirements || [];
}

// Claude names the bullets that back each requirement; without names, fall back to shared tags.
function reqMatches(r, b) {
  if (!r || !b) return false;
  if ((r.bullets || []).length) return r.bullets.includes(b.id);
  return (b.tags || []).some((t) => (r.tags || []).includes(t));
}

function bulletScore(b) {
  const reqs = requirements();
  if (reqs.length) {
    return reqs.reduce((s, r) => s + (reqMatches(r, b) ? (r.must ? 2 : 1) : 0), 0);
  }
  const lw = listingWords();
  let s = 0;
  for (const w of words(ownText(b))) if (lw.has(w)) s++;
  for (const t of b.tags || []) if (S.app.listing.toLowerCase().includes(t.replace("-", " "))) s++;
  return s;
}

function ownText(b) {
  return (S.app.tailor.overrides || {})[b.id] ?? b.text;
}

function matchLabel(b) {
  const reqs = requirements().filter((r) => reqMatches(r, b));
  if (reqs.length) return `fits: ${reqs.slice(0, 2).map((r) => r.text).join("; ")}${reqs.length > 2 ? ` +${reqs.length - 2}` : ""}`;
  if (requirements().length) return "";
  const s = bulletScore(b);
  return s > 1 ? `${s} listing words` : "";
}

function allBullets() {
  const out = {};
  for (const kind of ["positions", "projects"]) for (const o of S.master[kind] || []) for (const b of o.bullets || []) out[b.id] = b;
  return out;
}

function selectedIds() {
  const ids = new Set();
  for (const kind of ["positions", "projects"]) for (const v of Object.values(S.app.tailor[kind] || {})) for (const id of v.bullets || []) ids.add(id);
  return ids;
}

function reqsBlock() {
  const reqs = requirements();
  if (!reqs.length) {
    return S.init.claude ? `<p class="muted" style="font-size:12px;margin:14px 0 0">Draft with Claude on the Listing tab to see which of the listing's requirements your selected bullets cover.</p>` : "";
  }
  const byId = allBullets();
  const sel = [...selectedIds()].map((id) => byId[id]).filter(Boolean);
  const covered = reqs.map((r) => sel.some((b) => reqMatches(r, b)));
  const focus = S.ui.focusReq;
  const chips = reqs.map((r, i) => `<button class="chip ${covered[i] ? "ok" : ""} ${r.must ? "" : "nice"} ${focus === i ? "on" : ""}"
      data-act="req" data-i="${i}" title="${r.must ? "Required" : "Nice to have"}, ${covered[i] ? "covered" : "not covered"} by the selected bullets. Click to highlight bullets that fit.">
      ${covered[i] ? "✓ " : ""}${esc(r.text)}${r.must ? "" : " (nice)"}</button>`).join("");
  return `<div class="reqs" style="margin-top:14px">
    <div class="row"><span class="muted" style="font-size:12px">Listing requirements: ${covered.filter(Boolean).length} of ${reqs.length} covered</span>
      ${focus != null ? `<button class="ghost small" data-act="req" data-i="${focus}">Clear highlight</button>` : ""}</div>
    <div class="chips">${chips}</div>
  </div>`;
}

function sortRest(bullets) {
  return [...bullets].sort((a, b) => bulletScore(b) - bulletScore(a) || (a.priority ?? 3) - (b.priority ?? 3));
}

function renderResumeLeft() {
  const left = $("#left");
  const m = S.master;
  const t = S.app.tailor;
  const tg = t.target || {};
  let html = `
    <div class="target">
      <label class="field">Studio (used in PDF names)<input data-field="studio" value="${esc(tg.studio)}"></label>
      <label class="field">Role<input data-field="role" value="${esc(tg.role)}"></label>
    </div>`;
  html += reqsBlock();
  if ((m.games || []).length) html += sec("Games", (t.template || S.init.default_template) === "resume-games" ? "" : "only resume-games shows this section") + gamesBlock();
  html += sec("Experience", "drag selected bullets to reorder") + m.positions.map((p) => ownerBlock(p, "positions")).join("");
  if ((m.projects || []).length) html += sec("Personal projects") + m.projects.map((p) => ownerBlock(p, "projects")).join("");
  html += sec("Skills", "click a skill to move it to the front of its line") + skillsBlock();
  left.innerHTML = html;
  const ta = left.querySelector("textarea[data-edit]");
  if (ta) {
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
}

function sec(title, hint = "") {
  return `<div class="sec"><h2>${esc(title)}</h2>${hint ? `<span class="faint" style="font-size:12px">${esc(hint)}</span>` : ""}</div>`;
}

function ownerBlock(p, kind) {
  const sel = selected(kind, p.id);
  const on = sel !== null;
  const bullets = p.bullets || [];
  const byId = Object.fromEntries(bullets.map((b) => [b.id, b]));
  const chosen = on ? sel.map((id) => byId[id]).filter(Boolean) : [];
  const rest = sortRest(bullets.filter((b) => !on || !sel.includes(b.id)));
  const title = kind === "positions" ? `${p.company} · ${p.title}` : p.name;
  const sub = kind === "positions"
    ? [p.product, p.engine, `${p.start} to ${p.end}`].filter(Boolean).join(" · ")
    : p.summary || "";
  const focus = S.ui.focusReq != null ? requirements()[S.ui.focusReq] : null;
  const open = on || S.ui.expanded[p.id] || (focus && bullets.some((b) => reqMatches(focus, b)));
  const rows = !open ? "" : `<ul data-kind="${kind}" data-owner="${esc(p.id)}">
    ${chosen.map((b) => bulletRow(b, kind, p.id, true)).join("")}
    ${on && rest.length ? `<li class="divider">Not selected</li>` : ""}
    ${rest.map((b) => bulletRow(b, kind, p.id, false)).join("")}
  </ul>`;
  return `<div class="pos ${on ? "" : "off"}">
    <div class="phead">
      <input type="checkbox" data-act="owner" data-kind="${kind}" data-owner="${esc(p.id)}" ${on ? "checked" : ""}
        title="${on ? "Leave this off the resume" : "Put this on the resume"}">
      <div class="grow"><div class="ttl">${esc(title)}</div><div class="sub">${esc(sub)}</div></div>
      <span class="faint" style="font-size:12px">${chosen.length}/${bullets.length}</span>
      ${on ? "" : `<button class="ghost small" data-act="expand" data-owner="${esc(p.id)}">${open ? "Hide" : "Show"} bullets</button>`}
    </div>
    ${rows}
  </div>`;
}

function bulletRow(b, kind, owner, isSel) {
  const ov = (S.app.tailor.overrides || {})[b.id];
  const text = ov ?? b.text;
  const attrs = `data-kind="${kind}" data-owner="${esc(owner)}" data-id="${esc(b.id)}"`;
  if (S.ui.editing === b.id) {
    return `<li class="b ${isSel ? "sel" : ""}" ${attrs}>
      <span class="grip"></span>
      <div class="body edit">
        <textarea data-edit rows="3">${esc(text)}</textarea>
        ${ov != null ? `<div class="orig">Master text: ${esc(b.text)}</div>` : ""}
        <div class="row">
          <button class="small primary" data-act="ov-save" title="Ctrl+Enter">Use for this application</button>
          <button class="small" data-act="master-save" title="Change the bullet in master.yaml for every application">Save to master</button>
          ${ov != null ? `<button class="small ghost" data-act="ov-drop">Use master text</button>` : ""}
          <button class="small ghost" data-act="edit-cancel" title="Esc">Cancel</button>
        </div>
      </div>
    </li>`;
  }
  const label = isSel ? "" : matchLabel(b);
  const reqHit = S.ui.focusReq != null && reqMatches(requirements()[S.ui.focusReq], b);
  return `<li class="b ${isSel ? "sel" : ""} ${reqHit ? "hl" : ""}" ${attrs} ${isSel ? `draggable="true"` : ""}>
    <span class="grip" title="Drag to reorder">⠿</span>
    <input type="checkbox" data-act="bullet" ${isSel ? "checked" : ""}>
    <div class="body">
      <div class="text">${esc(text)}</div>
      <div class="meta">
        <code>${esc(b.id)}</code><span>p${b.priority ?? 3}</span><span>${esc((b.tags || []).join(", "))}</span>
        ${ov != null ? `<span class="ov">edited for this application</span>` : ""}
        ${label ? `<span class="score">${esc(label)}</span>` : ""}
      </div>
    </div>
    <span class="acts"><button class="ghost small" data-act="edit" title="Edit text">Edit</button></span>
  </li>`;
}

function gamesBlock() {
  const all = S.master.games || [];
  const t = S.app.tailor;
  const sel = t.games ?? all.map((g) => g.id);
  return `<div class="pos games">${all.map((g) => `
    <label><input type="checkbox" data-act="game" data-id="${esc(g.id)}" ${sel.includes(g.id) ? "checked" : ""}>
      <span>${esc(g.name)} <span class="faint">${esc(g.start)} to ${esc(g.end)}</span></span></label>`).join("")}
  </div>`;
}

function skillGroupOrder() {
  const groups = (S.master.skills || []).map((g) => g.group);
  const chosen = (S.app.tailor.skill_groups ?? groups).filter((g) => groups.includes(g));
  return { groups, chosen, ordered: [...chosen, ...groups.filter((g) => !chosen.includes(g))] };
}

function skillsBlock() {
  const { chosen, ordered } = skillGroupOrder();
  const first = S.app.tailor.skills_first || [];
  const byGroup = Object.fromEntries((S.master.skills || []).map((g) => [g.group, g.items || []]));
  return `<div class="pos skills">${ordered.map((g) => {
    const on = chosen.includes(g);
    const i = chosen.indexOf(g);
    return `<div class="grp">
      <div class="row">
        <input type="checkbox" data-act="sg" data-g="${esc(g)}" ${on ? "checked" : ""}>
        <strong class="grow" style="${on ? "" : "color:var(--muted)"}">${esc(g)}</strong>
        ${on ? `<button class="ghost small" data-act="sg-up" data-g="${esc(g)}" ${i === 0 ? "disabled" : ""} title="Move up">↑</button>
                <button class="ghost small" data-act="sg-down" data-g="${esc(g)}" ${i === chosen.length - 1 ? "disabled" : ""} title="Move down">↓</button>` : ""}
      </div>
      ${on ? `<div class="items">${byGroup[g].map((it) => {
        const n = first.indexOf(it);
        return `<button class="skill ${n >= 0 ? "first" : ""}" data-act="skill" data-item="${esc(it)}">${n >= 0 ? `${n + 1}. ` : ""}${esc(it)}</button>`;
      }).join("")}</div>` : ""}
    </div>`;
  }).join("")}</div>`;
}

// ----- editor events (delegated on #view, so they survive re-renders) -----

function findBullet(kind, owner, id) {
  const o = (S.master[kind] || []).find((p) => p.id === owner);
  return o && (o.bullets || []).find((b) => b.id === id);
}

function setBulletSelected(kind, owner, id, on) {
  const t = S.app.tailor;
  t[kind] = t[kind] || {};
  if (!t[kind][owner]) t[kind][owner] = { bullets: [] };
  const list = t[kind][owner].bullets;
  const i = list.indexOf(id);
  if (on && i < 0) list.push(id);
  if (!on && i >= 0) list.splice(i, 1);
}

function setOwner(kind, owner, on) {
  const t = S.app.tailor;
  t[kind] = t[kind] || {};
  const key = `${kind}:${owner}`;
  if (on) {
    t[kind][owner] = { bullets: S.ui.lastSel[key] || [] };
  } else {
    S.ui.lastSel[key] = t[kind][owner]?.bullets || [];
    delete t[kind][owner];
  }
}

function changed() {
  TABS[S.tab].left();
  queueSave();
}

document.addEventListener("change", (e) => {
  const el = e.target;
  if (!S.app || !el.closest("#left")) return;
  const t = S.app.tailor;
  const act = el.dataset.act;
  const li = el.closest(".b");
  if (act === "bullet") {
    setBulletSelected(li.dataset.kind, li.dataset.owner, li.dataset.id, el.checked);
  } else if (act === "owner") {
    setOwner(el.dataset.kind, el.dataset.owner, el.checked);
  } else if (act === "game") {
    const all = (S.master.games || []).map((g) => g.id);
    const set = new Set(t.games ?? all);
    el.checked ? set.add(el.dataset.id) : set.delete(el.dataset.id);
    t.games = all.filter((id) => set.has(id));
  } else if (act === "sg") {
    const { chosen } = skillGroupOrder();
    t.skill_groups = el.checked ? [...chosen, el.dataset.g] : chosen.filter((g) => g !== el.dataset.g);
  } else {
    return;
  }
  changed();
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (!S.app || !el.closest("#left") || !el.dataset.field) return;
  const t = S.app.tailor;
  if (el.dataset.field === "studio" || el.dataset.field === "role") {
    t.target = t.target || {};
    t.target[el.dataset.field] = el.value;
    renderTitle();
  } else if (FIELD_SETTERS[el.dataset.field]) {
    FIELD_SETTERS[el.dataset.field](el.value);
  } else {
    return;
  }
  queueSave(600);
});

const FIELD_SETTERS = {};

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  if (!S.app || !el || !el.closest("#left") || el.tagName === "INPUT") return;
  const t = S.app.tailor;
  const act = el.dataset.act;
  const li = el.closest(".b");
  if (act === "edit") {
    S.ui.editing = li.dataset.id;
    TABS[S.tab].left();
  } else if (act === "edit-cancel") {
    S.ui.editing = null;
    TABS[S.tab].left();
  } else if (act === "ov-save" || act === "ov-drop") {
    const b = findBullet(li.dataset.kind, li.dataset.owner, li.dataset.id);
    const text = act === "ov-drop" ? b.text : li.querySelector("textarea").value.replace(/\s+/g, " ").trim();
    t.overrides = t.overrides || {};
    if (!text || text === b.text) delete t.overrides[b.id];
    else t.overrides[b.id] = text;
    setBulletSelected(li.dataset.kind, li.dataset.owner, b.id, true);
    S.ui.editing = null;
    changed();
  } else if (act === "master-save") {
    const b = findBullet(li.dataset.kind, li.dataset.owner, li.dataset.id);
    const text = li.querySelector("textarea").value.replace(/\s+/g, " ").trim();
    if (!text) return;
    const before = b.text;
    b.text = text;
    try {
      const r = await api("PUT", "/api/master", { master: S.master });
      S.master = r.master;
      S.usage = r.usage;
      S.versions = { ...S.versions, ...r.versions };
      if (t.overrides) delete t.overrides[b.id];
      setBulletSelected(li.dataset.kind, li.dataset.owner, b.id, true);
      S.ui.editing = null;
      const others = (S.usage[b.id] || []).filter((n) => n !== S.app.name);
      toast(`Saved to master.${others.length ? ` Also used by ${others.map(esc).join(", ")}.` : ""}`);
      changed();
    } catch (err) {
      b.text = before;
      toast(esc(err.message), true);
    }
  } else if (act === "expand") {
    S.ui.expanded[el.dataset.owner] = !S.ui.expanded[el.dataset.owner];
    TABS[S.tab].left();
  } else if (act === "skill") {
    const list = (t.skills_first = t.skills_first || []);
    const i = list.indexOf(el.dataset.item);
    i >= 0 ? list.splice(i, 1) : list.push(el.dataset.item);
    changed();
  } else if (act === "sg-up" || act === "sg-down") {
    const { chosen } = skillGroupOrder();
    const i = chosen.indexOf(el.dataset.g);
    const j = act === "sg-up" ? i - 1 : i + 1;
    [chosen[i], chosen[j]] = [chosen[j], chosen[i]];
    t.skill_groups = chosen;
    changed();
  } else if (CLICK_ACTIONS[act]) {
    CLICK_ACTIONS[act](el, e);
  }
});

const CLICK_ACTIONS = {};

document.addEventListener("keydown", (e) => {
  if (!e.target.matches("textarea[data-edit]")) return;
  if (e.key === "Escape") $("[data-act=edit-cancel]")?.click();
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("[data-act=ov-save]")?.click();
});

// ----- drag to reorder selected bullets within one position -----

let drag = null;
document.addEventListener("dragstart", (e) => {
  const li = e.target.closest?.(".b.sel");
  if (!li) return;
  drag = { kind: li.dataset.kind, owner: li.dataset.owner, id: li.dataset.id };
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", li.dataset.id);
  li.classList.add("dragging");
});
document.addEventListener("dragover", (e) => {
  const li = e.target.closest?.(".b.sel");
  document.querySelectorAll(".drop-before,.drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));
  if (!drag || !li || li.dataset.owner !== drag.owner || li.dataset.kind !== drag.kind) return;
  e.preventDefault();
  const r = li.getBoundingClientRect();
  li.classList.add(e.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
});
document.addEventListener("drop", (e) => {
  const li = e.target.closest?.(".b.sel");
  if (!drag || !li || li.dataset.owner !== drag.owner) return;
  e.preventDefault();
  const after = li.classList.contains("drop-after");
  const list = S.app.tailor[drag.kind][drag.owner].bullets;
  list.splice(list.indexOf(drag.id), 1);
  const at = list.indexOf(li.dataset.id);
  if (at >= 0) list.splice(after ? at + 1 : at, 0, drag.id);
  else list.push(drag.id);
  drag = null;
  changed();
});
document.addEventListener("dragend", () => {
  drag = null;
  document.querySelectorAll(".dragging,.drop-before,.drop-after").forEach((x) => x.classList.remove("dragging", "drop-before", "drop-after"));
});

// ---------- listing tab ----------

TABS.listing = { left: renderListingLeft, preview: "resume" };

CLICK_ACTIONS.req = (el) => {
  const i = Number(el.dataset.i);
  S.ui.focusReq = S.ui.focusReq === i ? null : i;
  TABS[S.tab].left();
};

function renderListingLeft() {
  const sp = S.app.listing_spec;
  const reqs = sp?.requirements || [];
  $("#left").innerHTML = `<div class="stack listing">
    ${S.init.claude ? `<section class="card">
      <div class="hd"><h2>Draft with Claude</h2><span class="grow"></span><span id="draft-btn"></span></div>
      <div class="bd" id="draft-box"></div>
    </section>` : ""}
    ${sp && (sp.notes || (sp.gaps || []).length) ? `<section class="card">
      <div class="hd"><h2>Claude's notes</h2><span class="grow"></span><span class="faint" style="font-size:12px">${esc(sp.drafted || "")}</span></div>
      <div class="bd stack">
        ${sp.notes ? `<p style="margin:0">${esc(sp.notes)}</p>` : ""}
        ${(sp.gaps || []).length ? `<div><strong>The master cannot back these up yet</strong>
          <ul class="gaps">${sp.gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul>
          <p class="muted" style="font-size:12px;margin:6px 0 0">If you have done these things, add bullets on the <a href="#/master">Master</a> page, then tick them on the Resume tab.</p></div>` : ""}
      </div>
    </section>` : ""}
    <section class="card">
      <div class="hd"><h2>Requirements</h2><span class="grow"></span><span class="faint" style="font-size:12px">drive the chips and bullet ranking on the Resume tab</span></div>
      <div class="bd">
        ${reqs.length ? `<div class="req-row faint" style="font-size:11px"><span title="Required">Req.</span><span>Requirement</span><span>Tags</span><span></span></div>` : ""}
        ${reqs.map((r, i) => `<div class="req-row" data-i="${i}">
          <input type="checkbox" data-req="must" ${r.must ? "checked" : ""} title="Required (unticked = nice to have)">
          <input type="text" data-req="text" value="${esc(r.text)}">
          <input type="text" data-req="tags" value="${esc((r.tags || []).join(", "))}" placeholder="tags">
          <button class="ghost small" data-act="req-del" title="Remove">✕</button>
        </div>`).join("")}
        <div class="row" style="margin-top:8px"><button class="small" data-act="req-add">Add requirement</button>
          ${reqs.length ? "" : `<span class="muted" style="font-size:12px">None yet. Drafting with Claude fills these in from the listing.</span>`}</div>
      </div>
    </section>
    <section class="card">
      <div class="hd"><h2>Listing</h2><span class="grow"></span><span class="faint" style="font-size:12px">listing.md</span></div>
      <div class="bd"><textarea class="raw" id="listing-text">${esc(S.app.listing)}</textarea></div>
    </section>
  </div>`;
  renderDraftBox();
}

function ensureSpec() {
  const tg = S.app.tailor.target || {};
  if (!S.app.listing_spec) S.app.listing_spec = { studio: tg.studio || "", role: tg.role || "", requirements: [], gaps: [], notes: "" };
  S.app.listing_spec.requirements = S.app.listing_spec.requirements || [];
  return S.app.listing_spec;
}

CLICK_ACTIONS["req-add"] = () => {
  ensureSpec().requirements.push({ text: "", must: true, tags: [], bullets: [] });
  renderListingLeft();
  queueListingSave("spec");
  [...document.querySelectorAll("[data-req=text]")].pop()?.focus();
};
CLICK_ACTIONS["req-del"] = (el) => {
  ensureSpec().requirements.splice(Number(el.closest(".req-row").dataset.i), 1);
  S.ui.focusReq = null;
  renderListingLeft();
  queueListingSave("spec");
};

function onListingInput(el) {
  if (el.id === "listing-text") {
    S.app.listing = el.value;
    return queueListingSave("text");
  }
  const r = ensureSpec().requirements[Number(el.closest(".req-row").dataset.i)];
  if (el.dataset.req === "must") r.must = el.checked;
  if (el.dataset.req === "text") r.text = el.value;
  if (el.dataset.req === "tags") r.tags = el.value.split(",").map((t) => t.trim()).filter(Boolean);
  queueListingSave("spec");
}
document.addEventListener("input", (e) => {
  if (S.app && (e.target.id === "listing-text" || (e.target.dataset.req && e.target.dataset.req !== "must"))) onListingInput(e.target);
});
document.addEventListener("change", (e) => {
  if (S.app && e.target.dataset.req === "must") onListingInput(e.target);
});

let listingTimer = null;
const listingDirty = new Set();
function queueListingSave(what) {
  listingDirty.add(what);
  status("Unsaved changes");
  clearTimeout(listingTimer);
  listingTimer = setTimeout(saveListing, 600);
}
async function saveListing() {
  clearTimeout(listingTimer);
  if (!listingDirty.size || !S.app) return;
  const body = {};
  if (listingDirty.has("text")) body.text = S.app.listing;
  if (listingDirty.has("spec")) body.spec = S.app.listing_spec;
  listingDirty.clear();
  try {
    const r = await api("PUT", `/api/apps/${enc(S.app.name)}/listing`, body);
    S.versions = { ...S.versions, ...r.versions };
    status("Saved");
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ----- draft job -----

let draftTimer = null;
S.draft = {};

function renderDraftBox() {
  const box = $("#draft-box");
  if (!box) return;
  const j = S.draft[S.app.name] || { state: "idle" };
  const redraft = !!S.app.listing_spec?.drafted;
  const running = j.state === "running";
  $("#draft-btn").innerHTML = running
    ? `<button class="small" data-act="draft-cancel">Cancel</button>`
    : `<button class="small primary" data-act="draft-start">${redraft ? "Redraft" : "Draft with Claude"}</button>`;
  const secs = Math.round(((j.finished || Date.now() / 1000) - (j.started || 0)));
  let html = `<p class="muted" style="margin:0;font-size:13px">Claude Code reads the master and this listing with read-only access, picks and orders bullets,
    rewords a few where it helps, writes a cover letter, and lists anything the master cannot back up. It follows CLAUDE.md and your local rules.
    ${redraft ? " Redrafting replaces the current bullet choices, overrides and cover letter; a snapshot is taken first." : ""}</p>`;
  if (running) html = `<div class="row"><span class="pill">Drafting… ${secs} s</span><span class="muted" style="font-size:12px">usually one to three minutes</span></div>`;
  if (j.state === "error") html += `<p><span class="pill bad">Draft failed</span> ${esc(j.error)}</p>`;
  if (j.state === "done") html += `<p><span class="pill good">Draft written</span> ${j.result?.warnings?.length ? esc(j.result.warnings.join("; ")) : ""}</p>`;
  if (running || j.state === "error") html += `<div class="draft-log mono">${j.log.map(esc).join("\n")}</div>`;
  box.innerHTML = html;
}

CLICK_ACTIONS["draft-start"] = async () => {
  if (S.app.listing_spec?.drafted && !confirm("Redraft? This replaces the bullet choices, overrides and cover letter. A snapshot is taken first.")) return;
  await saveNow();
  await saveListing();
  try {
    S.draft[S.app.name] = await api("POST", `/api/apps/${enc(S.app.name)}/draft`);
    renderDraftBox();
    watchDraft(S.app.name);
  } catch (e) {
    toast(esc(e.message), true);
  }
};
CLICK_ACTIONS["draft-cancel"] = async () => {
  S.draft[S.app.name] = await api("POST", `/api/apps/${enc(S.app.name)}/draft/cancel`);
  renderDraftBox();
};

function watchDraft(name) {
  clearInterval(draftTimer);
  draftTimer = setInterval(async () => {
    let j;
    try {
      j = await api("GET", `/api/apps/${enc(name)}/draft`);
    } catch {
      return;
    }
    S.draft[name] = j;
    if (S.app?.name === name) renderDraftBox();
    if (j.state === "running") return;
    clearInterval(draftTimer);
    if (j.state === "done" && S.app?.name === name) {
      await loadApp(name);
      S.draft[name] = j;
      location.hash = `#/app/${enc(name)}/resume`;
      showEditor(name, "resume");
      toast(`Draft ready.${j.result?.notes ? ` ${esc(j.result.notes)}` : ""}`, false, 9000);
    } else if (j.state === "error") {
      toast(`Draft failed: ${esc(j.error)}`, true, 9000);
    }
  }, 1500);
}

async function checkDraft(name) {
  try {
    const j = await api("GET", `/api/apps/${enc(name)}/draft`);
    S.draft[name] = j;
    if (j.state === "running") watchDraft(name);
    renderDraftBox();
  } catch { /* the draft box just stays idle */ }
}

ON_OUTSIDE_EDIT.blocked = () =>
  listingDirty.size > 0 || S.draft[S.app?.name]?.state === "running" ||
  !!document.activeElement?.closest?.("#left") && /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName) && document.activeElement.type !== "checkbox";

// ---------- master ----------

async function showMaster() {
  view(`<div class="page"><div class="card"><div class="bd">Master editing arrives in the next update. Edit <code>data/master.yaml</code> in your editor for now; open applications refresh on save.</div></div></div>`);
}

// ---------- snapshots ----------

async function showSnapshots() {
  S.app = null;
  const { snapshots } = await api("GET", "/api/snapshots");
  const rows = snapshots.map((s) => `
    <li>
      <div class="grow"><div class="mono">${esc(s.name)}</div>
        <div class="muted" style="font-size:12px">${plural(s.files, "file")} · ${(s.size / 1024).toFixed(0)} KB · ${ago(s.created)}</div></div>
      <button data-restore="${esc(s.name)}">Restore</button>
    </li>`).join("");
  view(`<div class="page stack">
    <section class="card">
      <div class="hd"><h1>Snapshots</h1></div>
      <div class="bd stack">
        <p class="muted" style="margin:0">A snapshot zips <code>master.yaml</code>, every application folder (without PDFs), the templates${S.init.example ? "" : ", <code>Local/</code> and <code>CLAUDE.local.md</code>"} into <code>snapshots/</code>. Take one before a big change.
        Restoring writes those files back over the current ones. It takes a new snapshot first, and files created after the snapshot are left alone.
        Separately, every save of <code>master.yaml</code> keeps the previous version in <code>snapshots/master-history/</code>.</p>
        <div class="row"><input id="snap-label" placeholder="Label (optional), e.g. before-ghost-story-bullets" style="max-width:380px"><button class="primary" id="snap-create">Take snapshot</button></div>
      </div>
    </section>
    <section class="card">${snapshots.length ? `<ul class="snap-list">${rows}</ul>` : `<div class="empty">No snapshots yet.</div>`}</section>
  </div>`);
  $("#snap-create").onclick = () => takeSnapshot($("#snap-label").value);
  document.querySelectorAll("[data-restore]").forEach((b) => (b.onclick = () => restoreSnapshot(b.dataset.restore)));
}

async function takeSnapshot(label = "") {
  await saveNow();
  try {
    const s = await api("POST", "/api/snapshots", { label });
    toast(`Snapshot saved: ${esc(s.path)} (${plural(s.files, "file")})`);
    if (location.hash.startsWith("#/snapshots")) showSnapshots();
  } catch (e) {
    toast(esc(e.message), true);
  }
}

async function restoreSnapshot(name) {
  if (!confirm(`Restore ${name}?\n\nThis writes the snapshot's files over your current master.yaml, applications and templates. A snapshot of the current state is taken first.`)) return;
  try {
    const r = await api("POST", `/api/snapshots/${enc(name)}/restore`);
    S.app = null;
    toast(`Restored ${plural(r.restored, "file")}. Previous state saved as ${esc(r.backup)}.`, false, 7000);
    showSnapshots();
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ---------- outside edits ----------

// Poll file times so edits made in a text editor or by Claude Code show up here.
let serverLost = false;
async function pollVersions() {
  if (document.hidden || savePending || !S.versions) return;
  const name = S.app?.name;
  let v;
  try {
    v = await api("GET", `/api/versions${name ? `?app=${enc(name)}` : ""}`);
  } catch {
    status("Server not responding");
    serverLost = true;
    return;
  }
  if (serverLost) status("");
  serverLost = false;
  const moved = Object.keys(v).some((k) => k in S.versions && v[k] > S.versions[k] + 0.001);
  S.versions = { ...S.versions, ...v };
  if (!moved || !S.app || S.app.name !== name) return;
  if (S.ui.editing || ON_OUTSIDE_EDIT.blocked()) {
    toast("Files changed on disk. Finish your edit, then reload the page to see them.");
    return;
  }
  await loadApp(name);
  showEditor(name, S.tab);
  toast("Reloaded: files changed on disk");
}

// ---------- start ----------

(async function start() {
  S.init = await api("GET", "/api/init");
  $("#example-badge").hidden = !S.init.example;
  document.title = S.init.example ? "DynamicResume (example)" : "DynamicResume";
  $("#snap-btn").onclick = () => takeSnapshot();
  S.versions = await api("GET", "/api/versions");
  window.addEventListener("hashchange", route);
  route();
  setInterval(pollVersions, 2000);
})();
