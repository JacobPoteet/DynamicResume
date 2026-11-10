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
// Click a toast (outside its links) to dismiss it early.
document.addEventListener("click", (e) => {
  if (e.target.closest("#toast") && !e.target.closest("a")) $("#toast").className = "";
});

// Header save state. kind: dirty, busy, ok or bad (sets the colored dot).
function status(text, kind = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = kind ? `st-${kind}` : "";
}
const view = (html) => ($("#view").innerHTML = html);

// Per-browser UI preferences; storage can be unavailable, so never depend on it.
const pref = {
  get: (k, d) => { try { return localStorage.getItem(`dr-${k}`) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(`dr-${k}`, v); } catch { /* ignore */ } },
};

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
  conflict: null,  // files the server would not save over because they changed on disk
  keep: null,      // files the person chose to replace anyway
  outsideChange: false,  // files changed on disk and the reload is waiting for an edit to finish
  outsideNoted: false,   // the person has been told so
  ui: { editing: null, expanded: {}, lastSel: {}, focusReq: null },
};
// Tabs can veto reloading after an outside edit (unsaved typing, a running draft).
const ON_OUTSIDE_EDIT = { blocked: () => false };

// ---------- routing ----------

let lastHash = location.hash;
function route() {
  if (S.init.needs_master) return showFirstRun();
  const [a, b, c] = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (a !== "master" && lastHash.startsWith("#/master") && masterDirty()) {
    if (!confirm("You have unsaved master changes. Leave and discard them?")) {
      history.replaceState(null, "", lastHash);
      return;
    }
    M.draft = null;
  }
  if (S.conflict && !(a === "app" && b === S.app?.name)) {
    if (!confirm("Your latest edit is not saved because the file changed on disk. Leave and discard the edit?")) {
      history.replaceState(null, "", lastHash);
      return;
    }
    dropUnsaved();
    S.conflict = null;
  }
  lastHash = location.hash;
  const section = a === "master" ? "master" : a === "snapshots" ? "snapshots" : "apps";
  document.querySelectorAll(".top nav a").forEach((n) => n.classList.toggle("on", n.dataset.nav === section));
  commitStudio();
  saveNow();
  saveLetter();
  saveListing();
  const go = a === "app" && b ? showEditor(b, c || "resume")
    : a === "master" ? showMaster(b === "raw" ? "raw" : b === "gaps" ? "gaps" : "bullets")
    : a === "snapshots" ? showSnapshots()
    : showHome(["list", "timeline", "stats"].includes(a) ? a : "board");
  go.catch((e) => view(`<div class="page"><div class="card"><div class="bd">${esc(e.message)}</div></div></div>`));
}

// ---------- first run ----------

// No master yet: nothing else in the app can load, so explain that and offer the demo as a start.
function showFirstRun() {
  $("#snap-btn").hidden = true;
  view(`<div class="page"><section class="card">
    <div class="hd"><h1>Welcome to DynamicResume</h1></div>
    <div class="bd stack">
      <p style="margin:0">There is no master file yet at <code>${esc(S.init.master_file)}</code>. The master holds every position, bullet and skill you could show, and each application picks from it.</p>
      <p style="margin:0">Start from the demo master, a fictional career, and replace it with your own on the Master page. Or create that file yourself, and this page moves on when it appears.</p>
      <div class="row"><button class="primary" id="first-run">Start from the demo master</button><span id="first-run-err"></span></div>
    </div>
  </section></div>`);
  $("#first-run").onclick = async () => {
    try {
      const r = await api("POST", "/api/master/start-from-demo");
      S.versions = { ...S.versions, ...r.versions };
      toast(`Copied the demo to ${esc(r.master_file)}. Replace it with your own history on the Master page.`, false, 8000);
      masterAppeared();
    } catch (e) {
      $("#first-run-err").innerHTML = `<span class="pill bad">${esc(e.message)}</span>`;
    }
  };
}

function masterAppeared() {
  S.init.needs_master = false;
  $("#snap-btn").hidden = false;
  route();
}

// ---------- home ----------

// "2026-10-22" -> "Oct 22, 2026", read as a local date (no time zone shift).
function fmtDay(iso) {
  const [y, m, d] = String(iso).split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : String(iso);
}

function pdfPill(pdfs) {
  if (!pdfs || !pdfs.resume.exists) return `<span class="pill plain">No PDFs</span>`;
  if (pdfs.resume.stale || (pdfs.letter.exists && pdfs.letter.stale)) return `<span class="pill warn">PDFs out of date</span>`;
  return `<span class="pill good">PDFs current</span>`;
}

async function deleteApp(a) {
  const label = [a.studio, a.role].filter(Boolean).join(", ") || a.name;
  const kept = a.submitted ? "everything, the PDFs you sent included" : "everything but the PDFs";
  if (!confirm(`Delete ${label}?\n\nThis removes applications/${a.name}, its PDFs included. A snapshot is taken first (it keeps ${kept}).`)) return;
  try {
    const r = await api("DELETE", `/api/apps/${enc(a.name)}`);
    toast(`Deleted ${esc(label)}. Saved first as ${esc(r.backup)}.`, false, 7000);
    refreshHome();
  } catch (e) {
    toast(esc(e.message), true);
  }
}

async function createApp(draft, save = false) {
  const body = { studio: $("#na-studio").value, role: $("#na-role").value, listing: $("#na-listing").value };
  const link = $("#na-url").value.trim();
  const got = Object.fromEntries(Object.entries(T.imported || {}).filter(([, v]) => v));
  if (link || save || Object.keys(got).length) body.job = { ...got, ...(link ? { url: link } : {}), ...(save ? { saved: true } : {}) };
  const from = $("#na-from")?.value;
  if (from) Object.assign(body, { start_from: from, copy_letter: $("#na-letter").checked });
  // A repeat studio and role makes a numbered folder, so a second click would make a second application.
  const buttons = ["#na-create", "#na-draft", "#na-save"].map((id) => $(id)).filter(Boolean);
  buttons.forEach((b) => (b.disabled = true));
  try {
    if (draft && !body.listing.trim()) throw new Error("Paste the listing first so Claude has something to draft from.");
    const { name, dropped } = await api("POST", "/api/apps", body);
    // The application exists from here on: a draft that fails to start must not lead to a retry that makes another.
    const notes = dropped?.length ? [`Left out ${plural(dropped.length, "item")} the master no longer has: ${esc(dropped.join(", "))}.`] : [];
    if (draft) await api("POST", `/api/apps/${enc(name)}/draft`).catch((e) => notes.push(`Created, but the draft did not start: ${esc(e.message)}`));
    if (save) {
      $("#new-dlg").close();
      await refreshHome();
      return toast([`Saved ${esc(body.studio.trim())} to the Saved column.`, ...notes].join("<br>"), notes.length > 0, notes.length ? 12000 : 4000);
    }
    location.hash = `#/app/${enc(name)}/${draft ? "listing" : "resume"}`;
    if (notes.length) toast(notes.join("<br>"), true, 12000);
  } catch (e) {
    $("#na-err").innerHTML = `<span class="pill bad">${esc(e.message)}</span>`;
    buttons.forEach((b) => (b.disabled = false));
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
  S.master = app.master || m.master;  // a submitted application renders from its frozen copy
  S.usage = m.usage;
  S.app = app;
  normalizeTailor(app.tailor);
  S.previews = {};
  S.versions = v;
  S.conflict = S.keep = null;
  S.outsideChange = S.outsideNoted = false;
  S.ui.editing = null;
  S.ui.focusReq = null;
  if (S.init.claude) checkDraft(name);
}

async function showEditor(name, tab) {
  if (!S.app || S.app.name !== name || !S.master) await loadApp(name);
  S.tab = tab;
  const t = S.app.tailor;
  const tabs = [["resume", "Resume"], ["letter", "Cover letter"], ["listing", "Listing"]].filter(([k]) => TABS[k]);
  const tpl = t.template || S.init.default_template;
  const paper = t.paper || S.master.basics?.paper || S.init.default_paper;
  const sub = S.app.submitted;
  const tools = sub ? `
      <span class="pill good" title="Builds skip this application">Submitted ${esc(fmtDay(sub.date))}</span>
      <span class="row">${["resume", "letter"].filter((k) => sub[k]).map((k) => `<a class="pill" href="${sentUrl(sub[k])}" target="_blank" title="The PDF as sent">${k === "resume" ? "Resume" : "Letter"} as sent</a>`).join("")}</span>
      <button id="unsubmit" title="Make this application editable again">Unsubmit</button>` : `
      <label class="row muted" style="font-size:13px"><span class="tpl-word">Template</span>
        <select id="tpl" aria-label="Resume template">${S.init.templates.map((x) => `<option ${x === tpl ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      </label>
      <label class="row muted" style="font-size:13px" title="Page size for the resume and the cover letter"><span class="tpl-word">Paper</span>
        <select id="paper" aria-label="Paper size">${S.init.papers.map((x) => `<option value="${esc(x)}" ${x === paper ? "selected" : ""}>${x === "letter" ? "US Letter" : esc(x.toUpperCase())}</option>`).join("")}</select>
      </label>
      <span id="pdf-state"></span>
      <button id="submit" title="Rebuild the PDFs, copy text for forms, open the posting and mark it sent">Send</button>
      <button class="primary" id="finalize">Build PDFs</button>`;
  view(`<div class="editor">
    <div class="ebar">
      <a href="#/" class="btn ghost">← Applications</a>
      <h1 id="e-title" title=""></h1>
      <nav class="tabs">${tabs.map(([k, l]) => `<a href="#/app/${enc(name)}/${k}" class="${k === tab ? "on" : ""}" ${k === tab ? `aria-current="page"` : ""}>${l}</a>`).join("")}</nav>
      <span class="grow"></span>${tools}
    </div>
    <div class="conflict" id="conflict" role="alert" hidden></div>
    <section class="card" id="impact" hidden></section>
    <section class="card" id="fit-report" hidden></section>
    <div class="panes"><div class="pane left" id="left"></div><div class="pane right" id="right"></div></div>
  </div>`);
  renderTitle();
  renderConflict();
  renderImpact();
  renderFitReport();
  TABS[tab].left();
  const kind = TABS[tab].preview;
  if (sub) return showSent(kind);
  renderPdfState();
  $("#tpl").onchange = (e) => { t.template = e.target.value; queueSave(0); };
  // Paper also changes the letter, whose preview a resume save does not refresh.
  $("#paper").onchange = (e) => { t.paper = e.target.value; delete S.previews.letter; queueSave(0); };
  $("#finalize").onclick = finalize;
  $("#submit").onclick = () => openSend(name);
  if (S.previews[kind]) renderPreview(kind);
  else {
    $("#right").innerHTML = `<div class="pv-head">
        <div class="fillline"><span class="pv-busy"><span class="spinner"></span>Rendering the preview</span></div>
        <div class="meter"></div>
      </div>
      <div class="pages ${fitClass()}"><div class="sheet ghost ${paper === "a4" ? "a4" : ""}"></div></div>`;
    setBusy(true);
    fitSheets();
    refreshPreview(kind);
  }
}

function renderTitle() {
  const tg = S.app.tailor.target || {};
  const el = $("#e-title");
  el.textContent = el.title = [tg.studio, tg.role].filter(Boolean).join(" · ") || S.app.name;
}

function pdfUrl(file) {
  return `/files/apps/${enc(S.app.name)}/${enc(file)}?v=${Date.now()}`;
}

function sentUrl(file) {
  return `/files/apps/${enc(S.app.name)}/submitted/${enc(file)}`;
}

// A submitted application is read-only: the left pane is inert and the right shows the PDF as sent.
function showSent(kind) {
  const sub = S.app.submitted;
  const left = $("#left");
  left.inert = true;
  left.insertAdjacentHTML("afterbegin", `<div class="sent-note">Submitted ${esc(fmtDay(sub.date))}. This application is frozen so
    the PDFs stay exactly as sent. Unsubmit it to edit or rebuild.</div>`);
  const file = sub[kind] || sub.resume;
  $("#right").innerHTML = `<div class="pv-head"><div class="fillline">
      <span class="pill good">As sent</span><span class="muted">${esc(file)}</span>${sub.stale ? `<span class="pill warn" title="The PDFs did not match the latest edits when they were frozen">Built before the last edits</span>` : ""}
      <span class="grow"></span><a href="${sentUrl(file)}" target="_blank">Open in a new tab</a></div></div>
    <details class="sent-job"><summary>Job details</summary>${jobCard()}</details>
    <iframe class="sent-pdf" src="${sentUrl(file)}" title="${kind === "letter" ? "Cover letter" : "Resume"} as sent"></iframe>`;
  $("#unsubmit").onclick = unsubmit;
}

async function unsubmit() {
  if (!confirm("Unsubmit this application? You can edit and rebuild it again. If the PDFs here still match the ones you sent, the frozen copy is removed; otherwise it is kept in a dated folder.")) return;
  try {
    const r = await api("POST", `/api/apps/${enc(S.app.name)}/unsubmit`);
    toast(r.kept ? `Editable again. The PDFs you sent are kept in ${esc(r.kept)}.` : "Editable again.", false, 7000);
    await loadApp(S.app.name);
    showEditor(S.app.name, S.tab);
  } catch (e) {
    toast(esc(e.message), true, 8000);
  }
}

function renderPdfState() {
  const el = $("#pdf-state");
  if (!el) return;
  const p = S.app.pdfs;
  const link = (x, label) => x.exists
    ? `<a class="pill ${x.stale ? "warn" : "good"}" href="${pdfUrl(x.file)}" target="_blank" title="${x.stale ? "Does not match your latest changes. Build PDFs to update it." : "Up to date"}">${label}${x.stale ? " (old)" : ""}</a>`
    : "";
  el.innerHTML = `<span class="row">${link(p.resume, "Resume PDF")}${link(p.letter, "Letter PDF")}</span>`;
}

async function finalize() {
  if (S.conflict) return toast(CHOOSE_FIRST, true);
  const btn = $("#finalize");
  await Promise.all([saveNow(), saveLetter(), saveListing()]);
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Building…`;
  try {
    const r = await api("POST", `/api/apps/${enc(S.app.name)}/finalize`);
    S.app.pdfs = r.pdfs;
    noteChanges(r);
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
let savesInFlight = 0;

function queueSave(delay = 300) {
  savePending = true;
  status("Unsaved changes", "dirty");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, delay);
}

async function saveNow() {
  clearTimeout(saveTimer);
  if (!savePending || !S.app || S.conflict?.includes("tailor.yaml")) return;
  savePending = false;
  const seq = ++saveSeq;
  const name = S.app.name;
  status("Saving…", "busy");
  setBusy(true);
  savesInFlight++;
  try {
    const r = await api("PUT", `/api/apps/${enc(name)}/tailor`, { tailor: cleanTailor(S.app.tailor), keep: S.keep });
    if (r.conflict) {
      if (S.app?.name === name) savePending = true;
      return showConflict(r.conflict, name);
    }
    S.versions = { ...S.versions, ...r.versions };
    if (seq !== saveSeq || !S.app || S.app.name !== name) return;
    S.previews.resume = r.preview;
    if (r.pdfs) S.app.pdfs = r.pdfs;  // a studio rename changes the file names
    noteChanges(r);
    if (r.studio_notes != null && !listingDirty.has("notes")) S.app.studio_notes = r.studio_notes;
    if (r.warnings?.length) toast(r.warnings.map(esc).join("<br>"), true, 9000);
    renderPdfState();
    if (TABS[S.tab]?.preview === "resume") renderPreview("resume");
    else refreshPreview(TABS[S.tab].preview);
    status("Saved", "ok");
  } catch (e) {
    toast(esc(e.message), true);
    status("Save failed", "bad");
    setBusy(false);
  } finally {
    savesInFlight--;
  }
}

window.addEventListener("beforeunload", (e) => {
  commitStudio();
  if (savePending) { saveNow(); e.preventDefault(); }
});

// ----- outside edits: the server will not save over a file that changed on disk -----

const CHOOSE_FIRST = "A file changed on disk. Choose which version to keep first.";

function showConflict(files, name) {
  setBusy(false);
  status("Not saved", "bad");
  if (S.app?.name !== name) {
    return toast(`${files.map(esc).join(", ")} for ${esc(name)} changed on disk, so your last edit there was not saved.`, true, 9000);
  }
  S.conflict = [...new Set([...(S.conflict || []), ...files])];
  renderConflict();
}

function renderConflict() {
  const el = $("#conflict");
  if (!el) return;
  el.hidden = !S.conflict;
  el.innerHTML = !S.conflict ? "" : `<span class="grow"><strong>${S.conflict.map(esc).join(", ")} changed on disk while you were editing.</strong>
      Your latest edit here is not saved yet.</span>
    <button data-conflict="disk" title="Discard your unsaved edit here and load what is on disk">Use the file on disk</button>
    <button class="primary" data-conflict="mine" title="Save what this page shows, replacing the outside change">Keep my edit</button>`;
}

function dropUnsaved() {
  clearTimeout(saveTimer);
  clearTimeout(letterTimer);
  clearTimeout(listingTimer);
  savePending = letterPending = false;
  listingDirty.clear();
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-conflict]");
  if (!b || !S.conflict || !S.app) return;
  if (b.dataset.conflict === "disk") {
    dropUnsaved();
    await loadApp(S.app.name);
    showEditor(S.app.name, S.tab);
    status("");
    return toast("Loaded the files from disk");
  }
  S.keep = S.conflict;
  S.conflict = null;
  S.outsideChange = false;
  renderConflict();
  await Promise.all([saveNow(), saveLetter(), saveListing()]);
  S.keep = null;
});

// ---------- preview ----------

const setBusy = (on) => $("#right")?.classList.toggle("busy", on);
const fitClass = () => (pref.get("fit", "width") === "page" ? "fit-page" : "");

// "Whole page" sizes each sheet to the height left under the sticky preview header.
function fitSheets() {
  const el = $("#right");
  if (!el) return;
  const head = $(".pv-head", el);
  const h = el.clientHeight - (head ? head.offsetHeight : 0) - 34;
  el.style.setProperty("--sheet-h", `${Math.max(h, 240)}px`);
}
window.addEventListener("resize", fitSheets);

document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-pv]");
  if (!b) return;
  pref.set("fit", b.dataset.pv);
  document.querySelectorAll("[data-pv]").forEach((x) => x.setAttribute("aria-pressed", x === b));
  $(".pages")?.classList.toggle("fit-page", b.dataset.pv === "page");
  fitSheets();
});

function fitControl() {
  const page = pref.get("fit", "width") === "page";
  return `<span class="seg" role="group" aria-label="Preview size">
    <button data-pv="width" aria-pressed="${!page}" title="Scale the page to the pane width">Fit width</button>
    <button data-pv="page" aria-pressed="${page}" title="Show the whole page at once">Whole page</button>
  </span>`;
}

async function refreshPreview(kind) {
  if (!S.app) return;
  const name = S.app.name;
  setBusy(true);
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
  const resume = kind === "resume";
  // A resume should fill its one page (90% or more counts as full); a short letter is fine.
  const full = pct >= 90 || !resume;
  const meter = over ? "over" : pct >= 90 ? "" : "room";
  let line = `<span class="muted">No layout information</span>`;
  if (f.pages != null) {
    const free = resume && f.lines_free != null ? `<span class="muted">about ${plural(f.lines_free, "line")} free</span>` : "";
    line = over
      ? `<span class="pill bad">Over one page</span><span><strong>${f.pages} pages</strong>, about ${plural(f.spill_lines ?? 0, "line")} on page ${f.pages}. Cut that much to fit one page.</span>`
      : `<span class="pill ${full ? "good" : ""}">${full ? "Fits one page" : "Room left"}</span><span>${pct}% full</span>${free}`;
  }
  const warnings = [
    ...(p.ok ? [] : [`<li class="err">${esc(p.error)}</li>`]),
    ...(p.warnings || []).map((w) => `<li>${esc(w)}</li>`),
  ].join("");
  const label = f.pages == null ? "Page fill unknown" : over ? `${f.pages} pages` : `One page, ${pct}% full`;
  el.innerHTML = `
    <div class="pv-head">
      <div class="fillline">${line}<span class="grow"></span>
        <span class="pv-busy" role="status"><span class="spinner"></span>Updating</span>${resume ? `<button class="small" data-fit-act="run" title="Over a page: use short texts, then cut the bullets that fit the listing least. Room left: suggest bullets to add.">Fit to page</button>` : ""}${fitControl()}</div>
      <div class="meter ${meter}" role="img" aria-label="${label}"><i style="width:${over ? 100 : pct}%"></i>${resume && !over ? `<b style="left:90%" title="90%: counts as a full page"></b>` : ""}</div>
      ${warnings ? `<ul class="warnings">${warnings}</ul>` : ""}
    </div>
    <div class="pages ${fitClass()}">${(p.pages || []).map((u, i) => `
      <div class="sheet ${i > 0 ? "over" : ""}"><img src="${u}" alt="Page ${i + 1} of the ${resume ? "resume" : "cover letter"}">${i > 0 ? `<span class="pill bad lbl">Page ${i + 1}</span>` : ""}</div>`).join("")}
    </div>`;
  setBusy(false);
  fitSheets();
  if (resume) updateFitBadges();
}

// Line counts the template measured for each selected bullet, shown on the Resume tab.
function fitBadge(id) {
  const f = S.previews.resume?.fill?.bullets?.[id];
  if (!f) return "";
  const tight = f.lines > 1 && f.last < 0.3;
  return `${plural(f.lines, "line")}${tight ? ` <span class="tight" title="The last line is only ${Math.round(f.last * 100)}% full. Trimming a few words saves a whole line.">short last line</span>` : ""}`;
}
function updateFitBadges() {
  document.querySelectorAll("#left [data-fit]").forEach((el) => (el.innerHTML = fitBadge(el.dataset.fit)));
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

// studio/fit.py scores bullets the same way to decide what Fit to page cuts.
function words(text) {
  const stop = new Set(S.init.stop_words);
  return new Set((text.toLowerCase().match(/[a-z][a-z0-9+#/-]{4,}/g) || []).filter((w) => !stop.has(w)));
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
  if (reqs.length) return `Fits: ${reqs.slice(0, 2).map((r) => r.text).join("; ")}${reqs.length > 2 ? ` +${reqs.length - 2}` : ""}`;
  if (requirements().length) return "";
  const s = bulletScore(b);
  return s > 1 ? `Shares ${s} words with the listing` : "";
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
      <label class="field wide">Headline (one line under your name)<input data-field="headline" value="${esc(t.headline)}"
        placeholder="${esc((m.basics || {}).headline || "Your title | two to four focus areas from the listing")}"></label>
    </div><div id="changes-slot"></div>`;
  html += reqsBlock() + unknownBlock();
  if ((m.games || []).length) html += sec("Games", (t.template || S.init.default_template) === "resume-games" ? "" : "only resume-games shows this section") + gamesBlock();
  html += sec("Experience", "drag to reorder (Alt+Up/Down from the keyboard), double-click a bullet to edit") +m.positions.map((p) => ownerBlock(p, "positions")).join("");
  if ((m.projects || []).length) html += sec("Personal projects", "selected projects print in this order") + projectOrder().map((p) => ownerBlock(p, "projects")).join("");
  html += sec("Skills", "click a skill to move it to the front of its line") + skillsBlock();
  left.innerHTML = html;
  renderChanges();
  const ta = left.querySelector("textarea[data-edit]");
  if (ta) {
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
}

// Selected projects in the tailor's order (the resume's), then the rest in master order.
function projectOrder() {
  const all = S.master.projects || [];
  const on = Object.keys(S.app.tailor.projects || {});
  return [...on.map((id) => all.find((p) => p.id === id)).filter(Boolean), ...all.filter((p) => !on.includes(p.id))];
}

function sec(title, hint = "") {
  return `<div class="sec"><h2>${esc(title)}</h2>${hint ? `<span class="faint" style="font-size:12px">${esc(hint)}</span>` : ""}</div>`;
}

// Ids in the tailor that the master does not have (an edit made outside the app). The build
// stops on them, so each gets a row with a way out. A missing bullet sits in its position's list.
function missingRow(kind, owner, id, what) {
  const attrs = what ? `data-act="drop-unknown" data-kind="${kind}" data-id="${esc(id)}"` : `data-act="drop-missing"`;
  return `<li class="b missing" data-kind="${kind}" data-owner="${esc(owner)}" data-id="${esc(id)}">
    <span class="grip"></span>
    <div class="body"><span class="pill bad">Not in the master</span> <code>${esc(id)}</code>
      <div class="meta">This application selects this ${what || "bullet"}, but the master does not have it${what ? "" : " here"}, so the resume cannot build. Remove it from this application, or add it back to the master.</div></div>
    <span class="acts"><button class="ghost small" ${attrs} aria-label="Remove ${esc(id)} from this application">Remove</button></span>
  </li>`;
}

function unknownBlock() {
  const t = S.app.tailor;
  const lacks = (list) => (id) => !(list || []).some((x) => x.id === id);
  const rows = [
    ...Object.keys(t.positions || {}).filter(lacks(S.master.positions)).map((id) => missingRow("positions", "", id, "position")),
    ...Object.keys(t.projects || {}).filter(lacks(S.master.projects)).map((id) => missingRow("projects", "", id, "project")),
    ...(t.games || []).filter(lacks(S.master.games)).map((id) => missingRow("games", "", id, "game")),
  ];
  return rows.length ? sec("Not in the master") + `<div class="pos"><ul>${rows.join("")}</ul></div>` : "";
}

function ownerBlock(p, kind) {
  const sel = selected(kind, p.id);
  const on = sel !== null;
  const bullets = p.bullets || [];
  const byId = Object.fromEntries(bullets.map((b) => [b.id, b]));
  const chosen = on ? sel.map((id) => byId[id]).filter(Boolean) : [];
  const missing = on ? sel.filter((id) => !byId[id]) : [];
  const rest = sortRest(bullets.filter((b) => !on || !sel.includes(b.id)));
  const title = kind === "positions" ? `${p.company} · ${p.title}` : p.name;
  const sub = kind === "positions"
    ? [p.product, p.engine, `${p.start} to ${p.end}`].filter(Boolean).join(" · ")
    : p.summary || "";
  const focus = S.ui.focusReq != null ? requirements()[S.ui.focusReq] : null;
  const open = on || S.ui.expanded[p.id] || (focus && bullets.some((b) => reqMatches(focus, b)));
  const rows = !open ? "" : `<ul data-kind="${kind}" data-owner="${esc(p.id)}">
    ${missing.map((id) => missingRow(kind, p.id, id)).join("")}
    ${chosen.map((b) => bulletRow(b, kind, p.id, true)).join("")}
    ${on && rest.length ? `<li class="divider">Not selected</li>` : ""}
    ${rest.map((b) => bulletRow(b, kind, p.id, false)).join("")}
  </ul>`;
  return `<div class="pos ${on ? "" : "off"}">
    <div class="phead">
      <input type="checkbox" data-act="owner" data-kind="${kind}" data-owner="${esc(p.id)}" ${on ? "checked" : ""}
        title="${on ? "Leave this off the resume" : "Put this on the resume"}" aria-label="Show ${esc(title)} on the resume">
      <div class="grow"><div class="ttl">${esc(title)}</div><div class="sub">${esc(sub)}</div></div>
      <span class="count" title="Bullets selected">${chosen.length} of ${bullets.length}</span>
      ${on && kind === "projects" && Object.keys(S.app.tailor.projects).indexOf(p.id) > 0
        ? `<button class="ghost small" data-act="project-up" data-owner="${esc(p.id)}" title="Print this project before the one above">Move up</button>` : ""}
      ${on ? "" : `<button class="ghost small" data-act="expand" data-owner="${esc(p.id)}" aria-expanded="${!!open}">${open ? "Hide" : "Show"} bullets</button>`}
    </div>
    ${rows}
  </div>`;
}

function bulletRow(b, kind, owner, isSel) {
  const ov = (S.app.tailor.overrides || {})[b.id];
  const useShort = !!b.short && (S.app.tailor.short || []).includes(b.id);
  const text = ov ?? (useShort ? b.short : b.text);
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
    <span class="grip" title="Drag to reorder, or focus the checkbox and press Alt+Up or Alt+Down" aria-hidden="true">⠿</span>
    <input type="checkbox" data-act="bullet" ${isSel ? "checked" : ""}
      aria-label="${isSel ? "On the resume" : "Add to the resume"}: ${esc(text)}"${isSel ? ` aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"` : ""}>
    <div class="body">
      <div class="text" title="Double-click to edit">${esc(text)}</div>
      <div class="meta">
        <code>${esc(b.id)}</code><span>p${b.priority ?? 3}</span><span>${esc((b.tags || []).join(", "))}</span>
        ${ov != null ? `<span class="ov" title="Master text: ${esc(b.text)}">Edited for this application</span>` : ""}
        ${b.variant_of ? `<span title="Another version of ${esc(b.variant_of)}; the resume can use one of the two">variant of ${esc(b.variant_of)}</span>` : ""}
        ${b.short ? `<button class="ghost small short" data-act="short" aria-pressed="${useShort}" title="${useShort ? "Using the short text. Click for the full text." : `Use the short text: ${esc(b.short)}`}">Short</button>` : ""}
        ${isSel ? `<span class="fit" data-fit="${esc(b.id)}">${fitBadge(b.id)}</span>` : ""}
        ${label ? `<span class="score">${esc(label)}</span>` : ""}
      </div>
    </div>
    <span class="acts"><button class="ghost small" data-act="edit" aria-label="Edit bullet text">Edit</button></span>
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
    return `<div class="grp ${on ? "" : "off"}">
      <div class="row">
        <label class="grow"><input type="checkbox" data-act="sg" data-g="${esc(g)}" ${on ? "checked" : ""}><strong>${esc(g)}</strong></label>
        ${on ? `<button class="ghost small" data-act="sg-up" data-g="${esc(g)}" ${i === 0 ? "disabled" : ""} title="Move up" aria-label="Move ${esc(g)} up">↑</button>
                <button class="ghost small" data-act="sg-down" data-g="${esc(g)}" ${i === chosen.length - 1 ? "disabled" : ""} title="Move down" aria-label="Move ${esc(g)} down">↓</button>` : ""}
      </div>
      ${on ? `<div class="items">${byGroup[g].map((it) => {
        const n = first.indexOf(it);
        return `<button class="skill ${n >= 0 ? "first" : ""}" data-act="skill" data-item="${esc(it)}" aria-pressed="${n >= 0}">${n >= 0 ? `${n + 1}. ` : ""}${esc(it)}</button>`;
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

// Ticking one version of a bullet unticks the other (variant_of): the build refuses both.
function untickVariant(kind, owner, id) {
  const o = (S.master[kind] || []).find((p) => p.id === owner);
  const b = findBullet(kind, owner, id);
  const sel = selected(kind, owner) || [];
  for (const x of (o?.bullets || []).filter((x) => x.id !== id && (x.id === b?.variant_of || x.variant_of === id))) {
    if (!sel.includes(x.id)) continue;
    setBulletSelected(kind, owner, x.id, false);
    toast(`Unticked ${esc(x.id)}: it is another version of ${esc(id)}.`);
  }
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

// Re-rendering replaces the left pane, so put keyboard focus back on the same control.
function focusKey(el) {
  if (!el?.closest?.("#left") || !el.dataset?.act) return null;
  return { act: el.dataset.act, id: el.closest(".b")?.dataset.id, owner: el.dataset.owner, g: el.dataset.g, item: el.dataset.item, i: el.dataset.i };
}
function restoreFocus(k) {
  if (!k || document.activeElement?.matches?.("textarea[data-edit]")) return;
  const same = (x) => x.closest(".b")?.dataset.id === k.id && x.dataset.owner === k.owner &&
    x.dataset.g === k.g && x.dataset.item === k.item && x.dataset.i === k.i;
  [...document.querySelectorAll(`#left [data-act="${k.act}"]`)].find(same)?.focus();
}
function rerenderLeft(k = focusKey(document.activeElement)) {
  TABS[S.tab].left();
  restoreFocus(k);
}

function changed(k) {
  rerenderLeft(k);
  queueSave();
}

document.addEventListener("change", (e) => {
  const el = e.target;
  if (!S.app || !el.closest("#left")) return;
  const t = S.app.tailor;
  const act = el.dataset.act;
  const li = el.closest(".b");
  if (el.dataset.field === "studio") return commitStudio();
  if (act === "bullet") {
    setBulletSelected(li.dataset.kind, li.dataset.owner, li.dataset.id, el.checked);
    if (el.checked) untickVariant(li.dataset.kind, li.dataset.owner, li.dataset.id);
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
  if (el.dataset.field === "role") {
    t.target = t.target || {};
    t.target.role = el.value;
    renderTitle();
  } else if (FIELD_SETTERS[el.dataset.field]) {
    FIELD_SETTERS[el.dataset.field](el.value);
  } else {
    return;
  }
  queueSave(600);
});

// The studio name is saved when the field is left, not on each keystroke. Saving a new name
// renames the PDFs and moves the studio's notes, and a half-typed name could match another studio.
function commitStudio() {
  const el = $("#left [data-field=studio]");
  if (!el || !S.app) return;
  const t = S.app.tailor;
  if (el.value === ((t.target || {}).studio ?? "")) return;
  t.target = t.target || {};
  t.target.studio = el.value;
  renderTitle();
  queueSave(0);
}

const FIELD_SETTERS = {};
FIELD_SETTERS.headline = (v) => {
  if (v.trim()) S.app.tailor.headline = v;
  else delete S.app.tailor.headline;
};

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  if (!S.app || !el || !el.closest("#left") || el.tagName === "INPUT") return;
  const t = S.app.tailor;
  const act = el.dataset.act;
  const li = el.closest(".b");
  const backToRow = li && { act: "edit", id: li.dataset.id };
  if (act === "project-up") {
    const keys = Object.keys(t.projects);
    const i = keys.indexOf(el.dataset.owner);
    [keys[i - 1], keys[i]] = [keys[i], keys[i - 1]];
    t.projects = Object.fromEntries(keys.map((k) => [k, t.projects[k]]));
    changed();
  } else if (act === "edit") {
    S.ui.editing = li.dataset.id;
    TABS[S.tab].left();
  } else if (act === "edit-cancel") {
    S.ui.editing = null;
    rerenderLeft(backToRow);
  } else if (act === "ov-save" || act === "ov-drop") {
    const b = findBullet(li.dataset.kind, li.dataset.owner, li.dataset.id);
    const text = act === "ov-drop" ? b.text : li.querySelector("textarea").value.replace(/\s+/g, " ").trim();
    t.overrides = t.overrides || {};
    if (!text || text === b.text) delete t.overrides[b.id];
    else t.overrides[b.id] = text;
    setBulletSelected(li.dataset.kind, li.dataset.owner, b.id, true);
    S.ui.editing = null;
    changed(backToRow);
  } else if (act === "master-save") {
    const text = li.querySelector("textarea").value.replace(/\s+/g, " ").trim();
    if (!text) return;
    let b, before;
    try {
      // Edit the file as it is now: master.yaml may have changed on disk since this page loaded it.
      S.master = (await api("GET", "/api/master")).master;
      b = findBullet(li.dataset.kind, li.dataset.owner, li.dataset.id);
      if (!b) throw new Error("This bullet is no longer in master.yaml.");
      before = b.text;
      b.text = text;
      const r = await api("PUT", "/api/master", { master: S.master });
      S.master = r.master;
      S.usage = r.usage;
      S.versions = { ...S.versions, ...r.versions };
      if (t.overrides) delete t.overrides[b.id];
      setBulletSelected(li.dataset.kind, li.dataset.owner, b.id, true);
      S.ui.editing = null;
      const others = (S.usage[b.id] || []).filter((n) => n !== S.app.name);
      toast(`Saved to master.${others.length ? ` Also used by ${others.map(esc).join(", ")}.` : ""}`);
      changed(backToRow);
      await saveNow();  // the check reads this application's tailor from disk
      runImpact();
    } catch (err) {
      if (b) b.text = before;
      toast(esc(err.message), true);
    }
  } else if (act === "short") {
    const list = (t.short = t.short || []);
    const i = list.indexOf(li.dataset.id);
    i >= 0 ? list.splice(i, 1) : list.push(li.dataset.id);
    if (!list.length) delete t.short;
    changed({ act: "short", id: li.dataset.id });
  } else if (act === "expand") {
    S.ui.expanded[el.dataset.owner] = !S.ui.expanded[el.dataset.owner];
    rerenderLeft();
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

CLICK_ACTIONS["drop-missing"] = (el) => {
  const t = S.app.tailor;
  const { kind, owner, id } = el.closest(".b").dataset;
  setBulletSelected(kind, owner, id, false);
  if (t.overrides) delete t.overrides[id];
  if (t.short) t.short = t.short.filter((x) => x !== id);
  changed();
};
CLICK_ACTIONS["drop-unknown"] = (el) => {
  const t = S.app.tailor;
  if (el.dataset.kind === "games") t.games = t.games.filter((x) => x !== el.dataset.id);
  else delete t[el.dataset.kind][el.dataset.id];
  changed();
};

document.addEventListener("keydown", (e) => {
  // Alt+Up/Down on a selected bullet's checkbox moves it, the keyboard version of dragging.
  if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && e.target.matches?.(".b.sel input[data-act=bullet]")) {
    e.preventDefault();
    const li = e.target.closest(".b");
    const list = S.app.tailor[li.dataset.kind][li.dataset.owner].bullets;
    const i = list.indexOf(li.dataset.id);
    const j = e.key === "ArrowUp" ? i - 1 : i + 1;
    if (i < 0 || j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    return changed();
  }
  if (!e.target.matches("textarea[data-edit]")) return;
  if (e.key === "Escape") $("[data-act=edit-cancel]")?.click();
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("[data-act=ov-save]")?.click();
});

document.addEventListener("dblclick", (e) => {
  const li = e.target.closest(".b");
  if (!S.app || !li || !e.target.closest(".text") || !li.closest("#left") || S.ui.editing) return;
  S.ui.editing = li.dataset.id;
  TABS[S.tab].left();
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

// ---------- cover letter tab ----------

TABS.letter = { left: renderLetterLeft, preview: "letter" };

function renderLetterLeft() {
  const cl = S.app.tailor.cover_letter || {};
  $("#left").innerHTML = `<div class="stack letter">
    <div class="target">
      <label class="field">Greeting<input data-field="cl-greeting" value="${esc(cl.greeting)}" placeholder="Dear Hiring Team,"></label>
      <label class="field">Closing<input data-field="cl-closing" value="${esc(cl.closing)}" placeholder="Sincerely,"></label>
    </div>
    <label class="field">Date (optional, printed above the greeting)<input data-field="cl-date" value="${esc(cl.date)}" placeholder="October 22, 2026"></label>
    <label class="field">Letter body: plain paragraphs with a blank line between them. Markdown prints as typed.
      <textarea id="letter-text" placeholder="${S.init.claude ? "Draft with Claude on the Listing tab writes a first version here." : ""}">${esc(S.app.letter || "")}</textarea></label>
    <div class="muted" id="letter-count" style="font-size:12px"></div>
  </div>`;
  countLetter();
}

function countLetter() {
  const text = S.app.letter || "";
  const paras = text.split(/\n\s*\n/).filter((p) => p.trim()).length;
  const n = (text.match(/\S+/g) || []).length;
  $("#letter-count").textContent = `${plural(n, "word")} in ${plural(paras, "paragraph")}. Most letters land between 250 and 400 words.`;
}

function setLetterField(key, value) {
  const t = S.app.tailor;
  t.cover_letter = t.cover_letter || {};
  if (value.trim()) t.cover_letter[key] = value;
  else delete t.cover_letter[key];
  if (!Object.keys(t.cover_letter).length) delete t.cover_letter;
}
FIELD_SETTERS["cl-greeting"] = (v) => setLetterField("greeting", v);
FIELD_SETTERS["cl-closing"] = (v) => setLetterField("closing", v);
FIELD_SETTERS["cl-date"] = (v) => setLetterField("date", v);

let letterTimer = null;
let letterPending = false;
document.addEventListener("input", (e) => {
  if (!S.app || e.target.id !== "letter-text") return;
  S.app.letter = e.target.value;
  countLetter();
  letterPending = true;
  status("Unsaved changes", "dirty");
  clearTimeout(letterTimer);
  letterTimer = setTimeout(saveLetter, 600);
});

async function saveLetter() {
  clearTimeout(letterTimer);
  if (!letterPending || !S.app || S.conflict?.includes("cover-letter.md")) return;
  letterPending = false;
  const name = S.app.name;
  status("Saving…", "busy");
  setBusy(true);
  savesInFlight++;
  try {
    const r = await api("PUT", `/api/apps/${enc(name)}/letter`, { text: S.app.letter, keep: S.keep });
    if (r.conflict) {
      if (S.app?.name === name) letterPending = true;
      return showConflict(r.conflict, name);
    }
    S.versions = { ...S.versions, ...r.versions };
    if (S.app?.name !== name) return;
    S.previews.letter = r.preview;
    S.app.pdfs = r.pdfs;
    noteChanges(r);
    renderPdfState();
    if (S.tab === "letter") renderPreview("letter");
    status("Saved", "ok");
  } catch (e) {
    toast(esc(e.message), true);
    status("Save failed", "bad");
    setBusy(false);
  } finally {
    savesInFlight--;
  }
}

// ---------- job details (job.yaml; open after submitting) ----------

const JOB_FIELDS = [["url", "Link", "https://…", "url"], ["location", "Location", "Remote, Austin TX"], ["salary", "Salary", "120k to 140k"],
  ["source", "Source", "Careers page, LinkedIn, a friend"], ["referral", "Referral", "Who referred you"],
  ["deadline", "Deadline", "", "date"], ["contact", "Contact", "Name, role, email"]];

// Only http and https links are shown as links; anything else stays plain text.
function safeUrl(u) {
  try {
    const x = new URL(String(u || "").trim());
    return x.protocol === "http:" || x.protocol === "https:" ? x.href : "";
  } catch { return ""; }
}

function jobCard() {
  const j = S.app.job || {};
  return `<section class="card job-card" id="job-card">
    <div class="hd"><h2>Job details</h2><span class="grow"></span><span class="faint" style="font-size:12px">job.yaml</span></div>
    <div class="bd stack">
      ${j.saved && !S.app.submitted ? `<div class="hint">A saved lead. <button class="small primary" data-act="job-start">Start drafting</button></div>` : ""}
      <div class="job-grid">${JOB_FIELDS.map(([k, label, ph, type]) => `<label class="field">${label}
        <input data-job="${k}" type="${type || "text"}" value="${esc(j[k] || "")}" placeholder="${esc(ph || "")}"></label>`).join("")}</div>
      <div id="job-link">${jobLink(j.url)}</div>
    </div></section>`;
}

function jobLink(u) {
  const href = safeUrl(u);
  return href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">Open the posting ↗</a>`
    : u ? `<span class="pill bad">The link must start with http:// or https://</span>` : "";
}

CLICK_ACTIONS["job-start"] = async () => {
  S.app.job = { ...S.app.job };
  delete S.app.job.saved;
  queueListingSave("job");
  await saveListing();
  TABS[S.tab].left();
  toast("Moved to Drafting");
};

document.addEventListener("input", (e) => {
  const k = S.app && e.target.dataset?.job;
  if (!k) return;
  const v = e.target.value.trim();
  S.app.job = { ...S.app.job };
  if (v) S.app.job[k] = v;
  else delete S.app.job[k];
  if (k === "url") $("#job-link").innerHTML = jobLink(v);
  // The server refuses a bad link, so hold job saves until it is valid; the pill says why.
  if (S.app.job.url && !safeUrl(S.app.job.url)) return;
  queueListingSave("job");
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
          <ul class="gaps">${sp.gaps.map((g) => `<li>${esc(g.text ?? g)}${g.topic ? ` <span class="pill plain" title="Topic: counts this gap across applications on Master, Gaps">${esc(g.topic)}</span>` : ""}</li>`).join("")}</ul>
          <p class="muted" style="font-size:12px;margin:6px 0 0">If you have done these things, add bullets on the <a href="#/master">Master</a> page, then tick them on the Resume tab.</p></div>` : ""}
      </div>
    </section>` : ""}
    ${S.app.submitted ? "" : jobCard()}
    <section class="card">
      <div class="hd"><h2>Your notes about ${esc((S.app.tailor.target || {}).studio || "this studio")}</h2><span class="grow"></span>
        <span class="faint" style="font-size:12px">${S.init.example ? "examples/" : ""}data/studios.yaml, shared by every application to this studio</span></div>
      <div class="bd"><textarea id="studio-notes" rows="3" placeholder="Games of theirs you have played, people you know there, why you want to work with them. Drafts use these in the cover letter.">${esc(S.app.studio_notes || "")}</textarea></div>
    </section>
    <section class="card">
      <div class="hd"><h2>Requirements</h2><span class="grow"></span><span class="faint" style="font-size:12px">drive the chips and bullet ranking on the Resume tab</span></div>
      <div class="bd">
        ${reqs.length ? `<div class="req-row faint" style="font-size:11px"><span title="Required">Req.</span><span>Requirement</span><span>Tags</span><span></span></div>` : ""}
        ${reqs.map((r, i) => `<div class="req-row" data-i="${i}">
          <input type="checkbox" data-req="must" ${r.must ? "checked" : ""} title="Required (unticked = nice to have)" aria-label="Required">
          <input type="text" data-req="text" value="${esc(r.text)}" aria-label="Requirement">
          <input type="text" data-req="tags" value="${esc((r.tags || []).join(", "))}" placeholder="tags" aria-label="Tags">
          <button class="ghost small" data-act="req-del" title="Remove" aria-label="Remove this requirement">✕</button>
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
  if (el.id === "studio-notes") {
    S.app.studio_notes = el.value;
    return queueListingSave("notes");
  }
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
  if (S.app && (e.target.id === "listing-text" || e.target.id === "studio-notes" || (e.target.dataset.req && e.target.dataset.req !== "must"))) onListingInput(e.target);
});
document.addEventListener("change", (e) => {
  if (S.app && e.target.dataset.req === "must") onListingInput(e.target);
});

let listingTimer = null;
const listingDirty = new Set();
function queueListingSave(what) {
  listingDirty.add(what);
  status("Unsaved changes", "dirty");
  clearTimeout(listingTimer);
  listingTimer = setTimeout(saveListing, 600);
}
async function saveListing() {
  clearTimeout(listingTimer);
  if (!listingDirty.size || !S.app || ["listing.md", "listing.yaml", "studios.yaml", "job.yaml"].some((f) => S.conflict?.includes(f))) return;
  const name = S.app.name;
  const body = { keep: S.keep };
  if (listingDirty.has("text")) body.text = S.app.listing;
  if (listingDirty.has("spec")) body.spec = S.app.listing_spec;
  const notes = listingDirty.has("notes");
  const dirty = [...listingDirty];
  listingDirty.clear();
  status("Saving…", "busy");
  savesInFlight++;
  try {
    const clashed = (r) => {
      if (!r.conflict) return false;
      if (S.app?.name === name) dirty.forEach((d) => listingDirty.add(d));
      showConflict(r.conflict, name);
      return true;
    };
    if (notes) {
      const r = await api("PUT", `/api/apps/${enc(name)}/studio-notes`, { notes: S.app.studio_notes, keep: S.keep });
      if (clashed(r)) return;
      S.versions = { ...S.versions, ...r.versions };
    }
    if (dirty.includes("job")) {
      const r = await api("PUT", `/api/apps/${enc(name)}/job`, { job: S.app.job || {}, keep: S.keep });
      if (clashed(r)) return;
      S.versions = { ...S.versions, ...r.versions };
      if (S.app?.name === name) S.app.track = r.track;
    }
    if (body.text != null || body.spec) {
      const r = await api("PUT", `/api/apps/${enc(name)}/listing`, body);
      if (clashed(r)) return;
      S.versions = { ...S.versions, ...r.versions };
    }
    status("Saved", "ok");
  } catch (e) {
    if (S.app?.name === name) dirty.forEach((d) => listingDirty.add(d));  // nothing is dropped: the next save retries
    toast(esc(e.message), true);
    status("Save failed", "bad");
  } finally {
    savesInFlight--;
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
  if (running) html = `<div class="row"><span class="pill row" style="gap:6px"><span class="spinner" style="width:9px;height:9px"></span>Drafting… ${secs} s</span><span class="muted" style="font-size:12px">usually one to three minutes</span></div>`;
  if (j.state === "error") html += `<p><span class="pill bad">Draft failed</span> ${esc(j.error)}</p>`;
  if (j.state === "done") html += `<p><span class="pill good">Draft written</span> ${j.result?.fit ? esc(fitSummary(j.result.fit)) : ""} ${j.result?.warnings?.length ? esc(j.result.warnings.join("; ")) : ""}</p>`;
  if (running || j.state === "error") html += `<div class="draft-log mono">${j.log.map(esc).join("\n")}</div>`;
  box.innerHTML = html;
}

CLICK_ACTIONS["draft-start"] = async () => {
  if (S.conflict) return toast(CHOOSE_FIRST, true);
  if (S.app.listing_spec?.drafted && !confirm("Redraft? This replaces the bullet choices, overrides and cover letter. A snapshot is taken first.")) return;
  if (S.app.job?.saved) {
    S.app.job = { ...S.app.job };
    delete S.app.job.saved;
    queueListingSave("job");
  }
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
      const fit = j.result?.fit;
      if (fit?.changed || fit?.suggest?.length) S.fitReports[name] = fit;
      else delete S.fitReports[name];
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

// ----- fit to page: the report panel, Undo, and adding a suggested bullet -----

S.fitReports = {};  // application name -> the last report, until it is dismissed

function pageLabel(f) {
  if (!f || f.pages == null) return "unknown";
  return f.pages > 1 ? `${f.pages} pages` : `1 page, ${Math.round(f.fill * 100)}% full`;
}

function fitSummary(r) {
  if (!r.measured) return "";
  const did = [];
  if (r.shortened.length) did.push(`shortened ${plural(r.shortened.length, "bullet")}`);
  if (r.cut.length) did.push(`cut ${plural(r.cut.length, "bullet")}`);
  if (!did.length) return `${pageLabel(r.after)}.`;
  return `${pageLabel(r.before)} to ${pageLabel(r.after)}: ${did.join(", ")}.`;
}

function renderFitReport() {
  const el = $("#fit-report");
  if (!el) return;
  const r = S.app && S.fitReports[S.app.name];
  el.hidden = !r;
  if (!r) return (el.innerHTML = "");
  const rows = (items, extra) => items.map((b) => `<li><span class="muted">${esc(b.where)}:</span> ${esc(b.text)}${extra(b)}</li>`).join("");
  const group = (title, html) => (html ? `<div><strong>${esc(title)}</strong><ul class="fit-list">${html}</ul></div>` : "");
  el.innerHTML = `<div class="hd"><h2>Fit to page</h2><span class="muted">${esc(fitSummary(r))}</span><span class="grow"></span>
      ${r.previous ? `<button class="small" data-fit-act="undo" title="Put back the bullets and wording as they were before the fit">Undo</button>` : ""}
      <button class="ghost small" data-fit-act="dismiss">Dismiss</button></div>
    <div class="bd stack">
      ${r.over ? `<p class="fit-note"><span class="pill bad">Still over one page</span> Every position is down to its last bullet, so the rest is your call.</p>` : ""}
      ${group("Using the short text", rows(r.shortened, () => ""))}
      ${group("Cut", rows(r.cut, (b) => `<div class="faint">${esc(b.reason)}</div>`))}
      ${r.uncovered.length ? `<p class="fit-note"><span class="pill warn">No longer covered</span> ${r.uncovered.map((u) => esc(u.text) + (u.must ? " (required)" : "")).join("; ")}</p>` : ""}
      ${r.cut.length ? `<p class="fit-note muted">Check that the cover letter does not lean on a cut bullet.</p>` : ""}
      ${group("Room left: bullets you could add", rows(r.suggest, (b) => `<div class="faint">${esc(b.reason)}. The page would be ${Math.round(b.fill * 100)}% full.
        <button class="small" data-fit-act="add" data-kind="${esc(b.kind)}" data-owner="${esc(b.owner)}" data-id="${esc(b.id)}" aria-label="Add ${esc(b.id)}">Add</button></div>`))}
    </div>`;
}

async function runFit(btn) {
  if (S.conflict) return toast(CHOOSE_FIRST, true);
  const name = S.app.name;
  await saveNow();
  if (S.conflict) return;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>Fitting…`;
  setBusy(true);
  try {
    const r = await api("POST", `/api/apps/${enc(name)}/fit`, { keep: S.keep });
    if (r.conflict) return showConflict(r.conflict, name);
    if (S.app?.name !== name) return;
    S.versions = { ...S.versions, ...r.versions };
    S.app.tailor = normalizeTailor(r.tailor);
    S.app.pdfs = r.pdfs;
    S.app.changes = r.changes;
    S.previews.resume = r.preview;
    const report = r.report;
    if (report.changed || report.suggest.length) S.fitReports[name] = report;
    else {
      delete S.fitReports[name];
      toast(report.measured ? `${esc(fitSummary(report))} Nothing to change.` : "Could not measure the page, so nothing was changed.", !report.measured, 6000);
    }
    renderFitReport();
    renderPdfState();
    rerenderLeft();
    if (TABS[S.tab]?.preview === "resume") renderPreview("resume");
    else setBusy(false);
  } catch (e) {
    toast(esc(e.message), true, 8000);
    setBusy(false);
    btn.disabled = false;
    btn.textContent = "Fit to page";
  }
}

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-fit-act]");
  if (!el || !S.app) return;
  const name = S.app.name;
  const report = S.fitReports[name];
  const act = el.dataset.fitAct;
  if (act === "run") return runFit(el);
  if (act === "dismiss") delete S.fitReports[name];
  if (act === "undo" && report?.previous) {
    if (S.conflict) return toast(CHOOSE_FIRST, true);
    S.app.tailor = normalizeTailor(clone(report.previous));
    delete S.fitReports[name];
    queueSave(0);
    rerenderLeft();
  }
  if (act === "add" && report) {
    const sel = S.app.tailor[el.dataset.kind]?.[el.dataset.owner];
    if (!sel) return;
    sel.bullets = [...(sel.bullets || []), el.dataset.id];
    report.suggest = report.suggest.filter((b) => b.id !== el.dataset.id);
    if (!report.suggest.length && !report.changed) delete S.fitReports[name];
    queueSave(0);
    rerenderLeft();
  }
  renderFitReport();
});

// ----- what changed since the last kept version (a build, or the version before a redraft) -----

function noteChanges(r) {
  if (!("changes" in r)) return;
  S.app.changes = r.changes;
  renderChanges();
}

function renderChanges() {
  const el = $("#changes-slot");
  if (!el) return;
  const c = S.app.changes;
  if (!c) return (el.innerHTML = "");
  const rows = (items, html) => items?.length ? items.map(html).join("") : "";
  const group = (title, list) => (list ? `<div><strong>${esc(title)}</strong><ul class="fit-list">${list}</ul></div>` : "");
  const bullet = (b) => `<li><span class="muted">${esc(b.where)}:</span> ${esc(b.text)}</li>`;
  const counts = [["added", c.added], ["removed", c.removed], ["moved", c.moved], ["reworded", c.reworded]]
    .filter(([, v]) => v?.length).map(([k, v]) => `${v.length} ${k}`);
  if (c.fields?.length) counts.push(plural(c.fields.length, "other change"));
  if (c.letter?.length) counts.push("letter changed");
  el.innerHTML = `<details class="changes" ${S.ui.changesOpen ? "open" : ""}>
    <summary><strong>Changed since ${esc(c.since)}</strong> <span class="muted">${esc(counts.join(", "))}</span></summary>
    <div class="stack">
      ${group("Added", rows(c.added, bullet))}
      ${group("Removed", rows(c.removed, bullet))}
      ${group("Moved", rows(c.moved, bullet))}
      ${group("Reworded", rows(c.reworded, (b) => `<li><span class="muted">${esc(b.where)}:</span> ${esc(b.text)}<div class="faint">Was: ${esc(b.before)}</div></li>`))}
      ${group("Other", rows(c.fields, (f) => `<li>${esc(f.label)}: ${esc(f.after)}<div class="faint">Was: ${esc(f.before)}</div></li>`))}
      ${group("Cover letter", rows(c.letter, (p) => `<li><span class="pill ${p.change === "added" ? "good" : "plain"}">${p.change === "added" ? "New" : "Removed"}</span> ${esc(p.text)}</li>`))}
    </div>
  </details>`;
  el.firstElementChild.ontoggle = (e) => (S.ui.changesOpen = e.target.open);
}

ON_OUTSIDE_EDIT.blocked = () =>
  $("#send-dlg").open || listingDirty.size > 0 || letterPending || S.draft[S.app?.name]?.state === "running" ||
  !!document.activeElement?.closest?.("#left") && /^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName) && document.activeElement.type !== "checkbox";

// ---------- master ----------

// Edits collect in M.draft and are written together with Save. The server merges them into
// master.yaml without disturbing its comments, and keeps the previous file in master-history.
const M = {
  base: null, draft: null, text: "", rawText: null, usage: {}, used: {}, mode: "bullets", saving: false, error: "",
  open: {},                                 // sections with their details form showing
  exp: new Set(),                           // ids of the bullets expanded for editing
  closed: new Set(["basics", "education", "games", "skills"]),  // collapsed sections
  q: "", tag: "", show: "", active: "",
};
const clone = (x) => JSON.parse(JSON.stringify(x));
const masterDirty = () => !!M.draft && (JSON.stringify(M.draft) !== JSON.stringify(M.base) || (M.rawText != null && M.rawText !== M.text));

async function loadMaster() {
  const r = await api("GET", "/api/master");
  M.base = r.master;
  M.draft = clone(r.master);
  M.text = r.text;
  M.rawText = null;
  M.usage = r.usage;
  M.used = r.used;
}

async function showMaster(mode = "bullets") {
  S.app = null;
  if (!M.draft || !masterDirty()) await loadMaster();
  if (mode !== M.mode && masterDirty()) {
    toast("Save or discard your changes before switching views.");
    location.hash = M.mode === "raw" ? "#/master/raw" : "#/master";
    return;
  }
  M.mode = mode;
  view(`<div class="master">
    <div class="page ${mode === "bullets" ? "m-page" : ""}" style="padding-bottom:20px">
      <div class="row" style="margin-bottom:14px">
        <h1>Master</h1>
        <nav class="tabs"><a href="#/master" class="${mode === "bullets" ? "on" : ""}">Edit</a><a href="#/master/raw" class="${mode === "raw" ? "on" : ""}">Raw YAML</a><a href="#/master/gaps" class="${mode === "gaps" ? "on" : ""}">Gaps</a></nav>
        <span class="grow"></span><span class="muted" style="font-size:12px">${esc(S.init.example ? "examples/data/master.yaml" : "data/master.yaml")} · <span id="m-total"></span></span>
        <button class="small" data-mact="check" title="Rebuild every unsubmitted application into build/check/ and report what changed">Check applications</button>
      </div>
      <section class="card" id="impact" hidden></section>
      <div id="mbody" class="stack"></div>
    </div>
    <div class="savebar" id="savebar" hidden>
      <span id="save-msg">Unsaved changes</span><span class="grow"></span>
      <button class="ghost" data-mact="discard">Discard</button><button class="primary" data-mact="save" title="Ctrl+S">Save master</button>
    </div>
  </div>`);
  renderMasterBody();
  renderImpact();
}

const owners = () => [...M.draft.positions, ...(M.draft.projects || [])];

function renderMasterBody() {
  const body = $("#mbody");
  if (!body) return;
  $("#m-total").textContent = plural(owners().reduce((n, o) => n + (o.bullets || []).length, 0), "bullet");
  if (M.mode === "gaps") return renderGaps();
  if (M.mode === "raw") {
    body.innerHTML = `<p class="muted" style="margin:0;font-size:13px">The whole file, comments included. Saving checks that it parses and builds before writing,
      and refuses to take away anything an unsubmitted application uses.</p>
      <textarea class="raw" id="raw-master" spellcheck="false">${esc(M.rawText ?? M.text)}</textarea>`;
    return updateSavebar();
  }
  const base = baseBullets();
  body.innerHTML = `<datalist id="tag-list">${allTags().map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
    <div class="m-layout">
      <nav class="m-rail" id="jump" aria-label="Sections of the master"></nav>
      <div class="m-main">
        ${masterFilters()}
        <div class="m-group">
          ${contactCard()}${educationCard()}${gamesCard()}${skillsCard()}
        </div>
        <div class="m-group">
          <div class="m-group-head"><h2>Positions</h2><span class="faint">newest first, the order the resume prints them</span><span class="grow"></span><button class="small" data-mact="add-owner" data-kind="positions">Add position</button></div>
          ${M.draft.positions.map((o, i) => ownerCard("positions", o, i, base)).join("")}
        </div>
        <div class="m-group">
          <div class="m-group-head"><h2>Projects</h2><span class="grow"></span><button class="small" data-mact="add-owner" data-kind="projects">Add project</button></div>
          ${(M.draft.projects || []).map((o, i) => ownerCard("projects", o, i, base)).join("")}
        </div>
      </div>
    </div>`;
  growAll();
  applyFilter();
  updateSavebar();
}

// Text boxes grow to fit, so a long bullet never scrolls inside its own box.
function grow(el) {
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight + 2}px`;
}
const growAll = (root = document) => root.querySelectorAll("textarea[data-auto]").forEach(grow);

const allTags = () => [...new Set(owners().flatMap((o) => (o.bullets || []).flatMap((b) => b.tags || [])))].sort();

// Bullets keyed by id, as JSON, for spotting which rows differ from the saved file.
function baseBullets() {
  const out = {};
  for (const o of [...M.base.positions, ...(M.base.projects || [])]) for (const b of o.bullets || []) out[b.id] = JSON.stringify(b);
  return out;
}
const bulletDirty = (b, base = baseBullets()) => base[b.id] !== JSON.stringify(b);

// Gaps from every application's listing, grouped by topic, most common first. Open ones lead;
// ones marked done or not me sit under Closed, and come back up if a later draft raises them again.
async function renderGaps() {
  const body = $("#mbody");
  body.innerHTML = `<p class="muted">Loading…</p>`;
  const { gaps } = await api("GET", "/api/gaps");
  if (M.mode !== "gaps" || $("#mbody") !== body) return;
  M.gaps = gaps;
  const open = gaps.filter((g) => !g.state || g.raised_again), closed = gaps.filter((g) => g.state && !g.raised_again);
  body.innerHTML = `<p class="muted" style="margin:0;font-size:13px">What listings asked for that the master could not back up, from every application's listing.yaml,
      most common first. Write a bullet when you have done it, or mark it Not me.</p>
    ${open.length ? open.map(gapCard).join("")
      : `<div class="empty">${gaps.length ? "Every gap is closed." : "No gaps recorded yet. Drafting with Claude lists them on each application's Listing tab."}</div>`}
    ${closed.length ? `<details class="gap-closed"><summary>Closed (${closed.length})</summary><div class="stack">${closed.map(gapCard).join("")}</div></details>` : ""}`;
  body.querySelectorAll("[data-gap]").forEach((b) => (b.onclick = () => gapAction(b.dataset.gap, b.dataset.key)));
  updateSavebar();
}

const GAP_STATE = { done: "Done", "not-me": "Not me" };

function gapCard(g) {
  const k = esc(g.key), st = g.state;
  const status = st ? `<span class="pill ${st.state === "done" ? "good" : "plain"}" title="Closed ${esc(st.date)}">${GAP_STATE[st.state]}${st.bullet ? `: ${esc(st.bullet)}` : ""}</span>` : "";
  const again = g.raised_again ? `<span class="pill warn" title="A listing drafted after you closed it asks for this again">Raised again</span>` : "";
  const acts = st && !g.raised_again
    ? `<button class="small ghost" data-gap="reopen" data-key="${k}">Reopen</button>`
    : `${S.init.claude ? `<button class="small" data-gap="write" data-key="${k}" title="Claude asks what you did, then writes a bullet from your answers for you to review">Write a bullet</button>` : ""}
       <button class="small ghost" data-gap="done" data-key="${k}" title="The master covers this now">Done</button>
       <button class="small ghost" data-gap="not-me" data-key="${k}" title="You have not done this; stop listing it as open">Not me</button>`;
  return `<section class="card"><div class="hd row wrap"><strong class="grow">${esc(g.topic || g.items[0].text)}</strong>
      ${again}${status}<span class="pill ${g.apps.length > 1 ? "warn" : "plain"}">${plural(g.apps.length, "application")}</span>${acts}</div>
    <ul class="bd gap-items">${g.items.map((i) => `<li><a href="#/app/${enc(i.app)}/listing">${esc(i.studio)}</a>: ${esc(i.text)}</li>`).join("")}</ul></section>`;
}

async function gapAction(act, key) {
  if (act === "write") return openWriteBullet(M.gaps.find((g) => g.key === key));
  const before = M.gaps.find((g) => g.key === key)?.state;
  try {
    await api("PUT", "/api/gaps/state", { key, state: act === "reopen" ? null : act });
    await renderGaps();
    const undo = act !== "reopen" ? ` <button class="small" id="gap-undo">Undo</button>` : "";
    toast(act === "reopen" ? "Reopened." : `Marked ${GAP_STATE[act].toLowerCase()}.${undo}`);
    if ($("#gap-undo")) $("#gap-undo").onclick = async () => {
      await api("PUT", "/api/gaps/state", { key, state: before?.state || null, note: before?.note });
      renderGaps();
    };
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// Write a bullet: Claude asks what you did, you answer, Claude writes a bullet from the answers
// only, and you edit it before Add to master. Nothing reaches the master before that.
function openWriteBullet(g) {
  const dlg = $("#gap-dlg"), W = { g, questions: [], closed: false };
  const title = esc(g.topic || g.items[0].text);
  const wire = () => dlg.querySelectorAll("[data-w=close]").forEach((b) => (b.onclick = () => dlg.close()));
  const shell = (inner) => {
    dlg.innerHTML = `<div class="dlg-hd"><h2 id="gap-h">Write a bullet: ${title}</h2></div><div class="stack">${inner}</div>`;
    wire();
  };
  const waiting = (what) => shell(`<div class="row"><span class="spinner" style="width:10px;height:10px"></span><span>${what}</span></div>
    <span class="muted" style="font-size:12px">Claude reads the master with read-only tools. This usually takes under a minute.</span>
    <div class="row dlg-ft"><span class="grow"></span><button type="button" data-w="close">Cancel</button></div>`);
  const fail = (e, retry) => {
    shell(`<span class="pill bad">${esc(e.message)}</span><div class="row dlg-ft"><span class="grow"></span>
      <button type="button" data-w="close">Close</button><button type="button" class="primary" data-w="retry">Try again</button></div>`);
    dlg.querySelector("[data-w=retry]").onclick = retry;
  };
  const err = (msg) => ($("#w-err").innerHTML = `<span class="pill bad">${esc(msg)}</span>`);
  dlg.onclose = () => (W.closed = true);

  async function ask() {
    waiting("Claude is working out what to ask…");
    try {
      W.questions = (await api("POST", "/api/gaps/questions", { key: g.key })).questions;
      if (!W.closed) answer();
    } catch (e) {
      if (!W.closed) fail(e, ask);
    }
  }

  function answer(prev = []) {
    shell(`<p class="muted" style="margin:0;font-size:13px">Answer in your own words. Leave out anything you did not do; Claude uses only what you write here.</p>
      ${W.questions.map((q, i) => `<label class="field">${esc(q)}<textarea rows="3" data-a="${i}">${esc(prev[i] || "")}</textarea></label>`).join("")}
      <div id="w-err"></div>
      <div class="row dlg-ft"><span class="grow"></span><button type="button" data-w="close">Cancel</button>
        <button type="button" class="primary" data-w="propose">Write the bullet</button></div>`);
    dlg.querySelector("[data-w=propose]").onclick = propose;
  }

  async function propose() {
    const answers = W.questions.map((q, i) => ({ q, a: dlg.querySelector(`[data-a="${i}"]`)?.value ?? W.answers?.[i]?.a ?? "" }));
    if (!answers.some((x) => x.a.trim())) return void err("Answer at least one question first.");
    W.answers = answers;
    waiting("Claude is writing the bullet from your answers…");
    try {
      const r = await api("POST", "/api/gaps/propose", { key: g.key, answers });
      if (!W.closed) review(r);
    } catch (e) {
      if (!W.closed) fail(e, propose);
    }
  }

  function review(r) {
    const back = `<button type="button" data-w="back">Back to answers</button>`;
    if (r.none) {
      shell(`<p>${esc(r.none)}</p><div class="row dlg-ft"><span class="grow"></span>${back}
        <button type="button" data-w="close">Close</button><button type="button" class="primary" data-w="notme">Mark Not me</button></div>`);
      dlg.querySelector("[data-w=notme]").onclick = () => { dlg.close(); gapAction("not-me", g.key); };
    } else {
      shell(`<label class="field">Bullet<textarea id="w-text" rows="3">${esc(r.text)}</textarea></label>
        <label class="field">Short version (optional)<input id="w-short" value="${esc(r.short)}"></label>
        <div class="row wrap">
          <label class="field grow">Goes under<select id="w-owner"><option value="">Choose…</option>
            ${r.owners.map((o) => `<option value="${esc(o.id)}" ${o.id === r.owner ? "selected" : ""}>${esc(o.label)}${o.kind === "project" ? " (project)" : ""}</option>`).join("")}</select></label>
          <label class="field">Priority<select id="w-pri">${[1, 2, 3].map((p) => `<option ${p === r.priority ? "selected" : ""}>${p}</option>`).join("")}</select></label>
        </div>
        <label class="field">Tags (comma separated)<input id="w-tags" value="${esc(r.tags.join(", "))}"></label>
        ${r.unsupported ? `<div class="muted" style="font-size:12px"><strong>Still not shown by your answers:</strong> ${esc(r.unsupported)}</div>` : ""}
        ${(r.warnings || []).map((w) => `<span class="pill warn">${esc(w)}</span>`).join(" ")}
        <div id="w-err"></div>
        <div class="row dlg-ft"><span class="grow"></span>${back}<button type="button" data-w="close">Cancel</button>
          <button type="button" class="primary" data-w="add">Add to master</button></div>`);
      dlg.querySelector("[data-w=add]").onclick = add;
    }
    dlg.querySelector("[data-w=back]").onclick = () => answer(W.answers.map((x) => x.a));
  }

  async function add() {
    const bullet = { text: $("#w-text").value, short: $("#w-short").value, owner: $("#w-owner").value,
      priority: Number($("#w-pri").value), tags: $("#w-tags").value.split(",").map((t) => t.trim()).filter(Boolean) };
    if (!bullet.text.trim()) return void err("The bullet has no text.");
    if (!bullet.owner) return void err("Choose where it goes.");
    try {
      const r = await api("POST", "/api/gaps/bullet", { key: g.key, bullet });
      if (r.versions) S.versions = { ...S.versions, ...r.versions };
      dlg.close();
      await loadMaster();
      renderMasterBody();  // the bullet count too, not only the gaps
      toast(`Added ${esc(r.id)} to the master and marked the gap done. Find it on the Edit tab.`, false, 7000);
    } catch (e) {
      err(e.message);
    }
  }

  dlg.showModal();
  ask();
}

const fitLabel = (f) => !f ? "no earlier build" : f.pages == null ? "unknown"
  : f.pages > 1 ? `${f.pages} pages (about ${plural(f.spill_lines ?? 0, "line")} over)` : `1 page, ${Math.round(f.fill * 100)}%`;

// After a master save (or on request), rebuild every unsubmitted application into build/check/
// and list the ones whose resume changed, so a master edit never breaks one unnoticed.
async function runImpact() {
  M.impact = { busy: true };
  renderImpact();
  try {
    M.impact = { rows: (await api("POST", "/api/check")).rows };
  } catch (e) {
    M.impact = { error: e.message };
  }
  renderImpact();
}

function renderImpact() {
  const el = $("#impact");
  if (!el) return;
  const im = M.impact;
  el.hidden = !im;
  if (!im) return;
  const head = `<div class="hd"><h2 class="grow">Effect on your applications</h2><button class="ghost small" data-mact="impact-close">Dismiss</button></div>`;
  if (im.busy) return (el.innerHTML = head + `<div class="bd row"><span class="spinner"></span>Rebuilding every application against this master…</div>`);
  if (im.error) return (el.innerHTML = head + `<div class="bd"><span class="pill bad">Check failed</span> ${esc(im.error)}</div>`);
  const rows = im.rows.filter((r) => r.changed || r.over);
  if (!rows.length) return (el.innerHTML = head + `<div class="bd muted">No resume changed: ${plural(im.rows.length, "application")} build the same as last time.</div>`);
  el.innerHTML = head + `<ul class="bd impact">${rows.map((r) => `<li>
      <a href="#/app/${enc(r.name)}/resume">${esc(r.name)}</a>: ${esc(fitLabel(r.before))} → ${r.error ? `<span class="pill bad">${esc(r.error)}</span>` : esc(fitLabel(r.after))}
      ${r.over ? `<span class="pill bad">Over one page</span>` : ""}
      ${r.warnings.map((w) => `<div class="muted" style="font-size:12px">${esc(w)}</div>`).join("")}</li>`).join("")}</ul>
    ${rows.some((r) => !r.before) ? `<div class="bd faint" style="font-size:12px;padding-top:0">"No earlier build" means the application has not been built since fit tracking was added; Build PDFs once to set a baseline.</div>` : ""}`;
}

// ----- master page: finding bullets -----

function masterFilters() {
  const tags = allTags().map((t) => `<option value="${esc(t)}" ${t === M.tag ? "selected" : ""}>${esc(t)}</option>`).join("");
  const shows = [["", "All bullets"], ["unused", "Not used by an application"], ["noshort", "No short version"], ["unsaved", "Unsaved changes"]];
  return `<div class="m-tools">
    <input type="search" data-mfilter="q" value="${esc(M.q)}" placeholder="Search bullets" aria-label="Search bullets by text, id or tag">
    <select data-mfilter="tag" aria-label="Filter by tag"><option value="">All tags</option>${tags}</select>
    <select data-mfilter="show" aria-label="Show">${shows.map(([v, l]) => `<option value="${v}" ${v === M.show ? "selected" : ""}>${l}</option>`).join("")}</select>
    <span class="muted" id="m-count" role="status"></span>
    <button class="ghost small" data-mact="collapse-all" id="m-collapse"></button>
  </div>`;
}

function bulletMatches(b, base) {
  const hay = `${b.text} ${b.short || ""} ${b.id} ${(b.tags || []).join(" ")}`.toLowerCase();
  if (!M.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  if (M.tag && !(b.tags || []).includes(M.tag)) return false;
  if (M.show === "unused" && (M.usage[b.id] || []).length) return false;
  if (M.show === "noshort" && b.short) return false;
  if (M.show === "unsaved" && !bulletDirty(b, base)) return false;
  return true;
}

// Hides what does not match without rebuilding the page, so typing keeps the search box's focus.
function applyFilter() {
  const main = $(".m-main");
  if (!main) return;
  const on = !!(M.q.trim() || M.tag || M.show);
  const base = baseBullets();
  main.classList.toggle("m-filtering", on);
  let shown = 0;
  let total = 0;
  main.querySelectorAll("[data-kind]").forEach((card) => {
    const o = M.draft[card.dataset.kind][Number(card.dataset.oi)];
    let hits = 0;
    card.querySelectorAll("[data-bi]").forEach((row) => {
      const hit = bulletMatches(o.bullets[Number(row.dataset.bi)], base);
      row.hidden = on && !hit;
      if (hit) hits++;
      total++;
    });
    shown += hits;
    card.hidden = on && !hits;
  });
  main.querySelectorAll(".m-group").forEach((g) => (g.hidden = on && !g.querySelector("[data-kind]:not([hidden])")));
  $("#m-count").textContent = on ? `${shown} of ${plural(total, "bullet")}` : "";
  const collapse = $("#m-collapse");
  collapse.hidden = on;
  collapse.textContent = ownerKeys().every((k) => M.closed.has(k)) ? "Expand all" : "Collapse all";
}

const ownerKey = (kind, o) => `${kind}:${o.id}`;
const ownerKeys = () => ["positions", "projects"].flatMap((kind) => (M.draft[kind] || []).map((o) => ownerKey(kind, o)));

// ----- master page: the outline -----

function renderJump() {
  const nav = $("#jump");
  if (!nav) return;
  const companies = M.draft.positions.map((o) => o.company);
  const baseOwner = (kind, o) => (M.base[kind] || []).find((p) => p.id === o.id);
  const ownerDirty = (kind, o) => JSON.stringify(o) !== JSON.stringify(baseOwner(kind, o));
  const link = (target, key, label, dirty, n) => `<button class="m-link ${target === M.active ? "on" : ""}" data-mact="jump" data-target="${target}" data-key="${esc(key)}"${dirty ? ` title="Unsaved changes"` : ""}>
      <span class="m-link-name">${esc(label)}</span>${dirty ? `<span class="m-dot" aria-label="Unsaved changes"></span>` : ""}${n != null ? `<span class="m-n">${n}</span>` : ""}</button>`;
  const section = (key, label) => link(`m-${key}`, key, label, JSON.stringify(M.draft[key] ?? null) !== JSON.stringify(M.base[key] ?? null));
  const posLabel = (o) => (companies.filter((c) => c === o.company).length > 1 ? `${o.company} (${[o.title, o.team].filter(Boolean).join(", ")})` : o.company) || "New position";
  nav.innerHTML = `<div class="m-rail-head">Profile</div>
    ${section("basics", "Contact")}${section("education", "Education")}${section("games", "Games")}${section("skills", "Skills")}
    <div class="m-rail-head">Positions</div>
    ${M.draft.positions.map((o, i) => link(`m-positions-${i}`, ownerKey("positions", o), posLabel(o), ownerDirty("positions", o), (o.bullets || []).length)).join("")}
    <div class="m-rail-head">Projects</div>
    ${(M.draft.projects || []).map((o, i) => link(`m-projects-${i}`, ownerKey("projects", o), o.name || "New project", ownerDirty("projects", o), (o.bullets || []).length)).join("")}`;
}

// The outline follows the page, marking the section at the top of the view.
let spyQueued = false;
window.addEventListener("scroll", () => {
  if (spyQueued || !$("#jump")) return;
  spyQueued = true;
  requestAnimationFrame(() => {
    spyQueued = false;
    const nav = $("#jump");
    if (!nav) return;
    let active = "";
    for (const sec of document.querySelectorAll(".m-main section[id]")) {
      if (!sec.hidden && sec.getBoundingClientRect().top <= 130) active = sec.id;
    }
    if (active === M.active) return;
    M.active = active;
    nav.querySelectorAll(".m-link").forEach((l) => l.classList.toggle("on", l.dataset.target === active));
  });
}, { passive: true });

// ----- master page: small shared pieces -----

const reorder = (act, i, n, what) => `<span class="reorder">
    <button class="ghost small" data-mact="${act}" data-dir="-1" aria-label="Move ${esc(what)} up" title="Move up" ${i === 0 ? "disabled" : ""}>↑</button>
    <button class="ghost small" data-mact="${act}" data-dir="1" aria-label="Move ${esc(what)} down" title="Move down" ${i === n - 1 ? "disabled" : ""}>↓</button>
  </span>`;

function sectionCard(key, id, title, summary, inner) {
  const closed = M.closed.has(key);
  return `<section class="card m-sec ${closed ? "closed" : ""}" id="${id}" data-sec="${esc(key)}">
    <div class="hd"><button class="m-tog" data-mact="toggle" aria-expanded="${!closed}">
      <span class="m-chev" aria-hidden="true"></span><span class="m-head"><strong>${esc(title)}</strong><span class="m-sub muted">${esc(summary)}</span></span></button></div>
    <div class="m-body">${inner}</div>
  </section>`;
}

// Sets a field, dropping it when emptied so the file never gains `team: ''`, and keeping
// the file's usual key order when a field comes back.
function setField(o, key, value, order, required) {
  if (!value && !required) {
    delete o[key];
    return;
  }
  const isNew = !(key in o);
  o[key] = value;
  if (!isNew) return;
  const rank = (k) => { const i = order.indexOf(k); return i < 0 ? order.length : i; };
  const sorted = Object.entries(o).sort((a, b) => rank(a[0]) - rank(b[0]));
  for (const [k] of sorted) delete o[k];
  for (const [k, v] of sorted) o[k] = v;
}

const ID_RULE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;
const slug = (text, words = 5) => String(text).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ").slice(0, words).join("-");
const uniqueId = (wanted, taken) => {
  let id = wanted;
  for (let n = 2; taken.has(id); n++) id = `${wanted}-${n}`;
  return id;
};

const FIELD_ORDER = {
  bullets: ["id", "text", "short", "variant_of", "tags", "priority"],
  positions: ["id", "company", "product", "engine", "game", "title", "team", "location", "start", "end", "bullets"],
  projects: ["id", "name", "url", "summary", "bullets"],
  basics: ["name", "email", "phone", "location", "linkedin", "headline", "paper"],
  games: ["id", "name", "start", "end"],
  education: ["school", "credential", "location", "start", "end"],
};
const REQUIRED = { positions: ["company", "title", "start", "end"], projects: ["name"], basics: ["name"], games: ["name", "start", "end"], education: ["school", "start", "end"] };
const FIELD_LABEL = {
  company: "Company", title: "Title", team: "Team", product: "Product", engine: "Engine", location: "Location", start: "Start", end: "End",
  name: "Name", url: "Link", summary: "Summary", email: "Email", phone: "Phone", linkedin: "LinkedIn", headline: "Default headline",
  school: "School", credential: "Credential",
};
const DATE_HINT = "YYYY-MM or present";
const fieldInput = (scope, o, f) => `<label class="field"><span>${FIELD_LABEL[f]}${REQUIRED[scope].includes(f) ? "" : ` <span class="faint">optional</span>`}</span>
    <input data-sf="${scope}" data-f="${f}" value="${esc(o[f])}"${f === "start" || f === "end" ? ` placeholder="${DATE_HINT}"` : ""}></label>`;

// An id that nothing depends on can change; one an application uses stays put, because the
// application refers to it.
function idInput(kind, value, apps, what) {
  return apps.length
    ? `<div class="field">ID <code class="m-id" title="Used by ${esc(apps.join(", "))}, so it cannot change">${esc(value)}</code></div>`
    : `<label class="field">ID <input data-idf="${kind}" value="${esc(value)}" spellcheck="false" title="${esc(what)}"></label>`;
}

// ----- master page: bullets -----

// The template wraps a bullet at about this many characters. Close enough to compare bullets;
// a real build reports the exact fit.
const CHARS_PER_LINE = 120;
const lineCount = (text) => Math.max(1, Math.ceil(text.length / CHARS_PER_LINE));

function lintText(text) {
  const out = [];
  if (text.includes(S.init.em_dash)) out.push("em dash");
  const low = text.toLowerCase();
  for (const phrase of S.init.banned || []) if (low.includes(phrase)) out.push(`"${phrase}"`);
  return out;
}
const lintPills = (text) => lintText(text || "").map((w) => `<span class="pill warn">${esc(w)}</span>`).join(" ");
const textHint = (text) => (text ? `<span>About ${plural(lineCount(text), "line")} on the page</span> ${lintPills(text)}` : "");

function masterRow(kind, o, b, bi, base) {
  const prio = b.priority ?? 3;
  const dirty = bulletDirty(b, base) ? "dirty" : "";
  const n = (o.bullets || []).length;
  if (!M.exp.has(b.id)) {
    const tags = (b.tags || []).join(", ");
    return `<div class="mb ${dirty}" data-bi="${bi}" data-bid="${esc(b.id)}">
      <button class="mb-open" data-mact="b-open" aria-expanded="false" title="Edit this bullet">
        <span class="mb-text">${b.text ? esc(b.text) : `<span class="faint">No text yet</span>`}</span>
        <span class="mb-meta"><span class="mb-p mb-p${prio}">p${prio}</span>${tags ? ` · ${esc(tags)}` : ""} ${lintPills(`${b.text} ${b.short || ""}`)}</span>
      </button>
      ${reorder("b-move", bi, n, b.id)}
    </div>`;
  }
  const used = M.usage[b.id] || [];
  const others = (o.bullets || []).filter((x) => x !== b);
  const clip = (t) => (t.length > 60 ? `${t.slice(0, 60)}…` : t);
  const targets = [...M.draft.positions.map((p) => ["positions", p]), ...(M.draft.projects || []).map((p) => ["projects", p])].filter(([, p]) => p !== o);
  return `<div class="mb open ${dirty}" data-bi="${bi}" data-bid="${esc(b.id)}">
    <label class="field">Text<textarea data-bf="text" data-auto rows="2" placeholder="What you did, with a concrete result">${esc(b.text)}</textarea></label>
    <div class="mb-hint" data-hint="text">${textHint(b.text)}</div>
    <label class="field"><span>Short version <span class="faint">optional, for when a page runs a line over</span></span><textarea data-bf="short" data-auto rows="1">${esc(b.short || "")}</textarea></label>
    <div class="mb-hint" data-hint="short">${textHint(b.short || "")}</div>
    <div class="mb-grid">
      <label class="field"><span>Tags <span class="faint">comma separated</span></span><input data-bf="tags" list="tag-list" value="${esc((b.tags || []).join(", "))}"></label>
      <label class="field">Priority<select data-bf="priority" title="1 = strongest">${[1, 2, 3].map((p) => `<option value="${p}" ${prio === p ? "selected" : ""}>p${p}</option>`).join("")}</select></label>
    </div>
    <div class="mb-grid mb-grid-3">
      ${idInput("bullet", b.id, used, "Short and stable. Applications refer to a bullet by its id.")}
      <label class="field">Another version of<select data-bf="variant"><option value="">Nothing</option>
        ${others.map((x) => `<option value="${esc(x.id)}" ${b.variant_of === x.id ? "selected" : ""}>${esc(clip(x.text || x.id))}</option>`).join("")}</select></label>
      <label class="field">Move to<select data-mmove><option value="">Choose a section</option>
        ${targets.map(([k, p]) => `<option value="${k}:${esc(p.id)}">${esc(k === "positions" ? `${p.company}, ${p.title}` : p.name)}</option>`).join("")}</select></label>
    </div>
    <div class="row mb-foot">
      <span class="muted">${used.length ? `Used by ${esc(used.join(", "))}` : "Not used by an application"}</span>
      <span class="grow"></span>
      <button class="ghost small danger" data-mact="del" aria-label="Delete bullet ${esc(b.id)}">Delete</button>
      <button class="small" data-mact="b-close">Done</button>
    </div>
  </div>`;
}

const rowOwner = (row) => {
  const card = row.closest("[data-kind]");
  return { kind: card.dataset.kind, o: M.draft[card.dataset.kind][Number(card.dataset.oi)] };
};

// Redraws one row, which keeps the scroll position and everything else on the page as it is.
function redrawRow(row, focus) {
  const { kind, o } = rowOwner(row);
  const bi = Number(row.dataset.bi);
  row.insertAdjacentHTML("beforebegin", masterRow(kind, o, o.bullets[bi], bi, baseBullets()));
  const next = row.previousElementSibling;
  row.remove();
  growAll(next);
  if (focus) next.querySelector(focus)?.focus();
  return next;
}

// A bullet and the versions tied to it by variant_of, which must stay in one section.
function variantFamily(o, b) {
  return o.bullets.filter((x) => x === b || x.variant_of === b.id || b.variant_of === x.id);
}

// ----- master page: sections -----

const OWNER_FIELDS = {
  positions: ["company", "title", "team", "product", "engine", "location", "start", "end"],
  projects: ["name", "url", "summary"],
};
const ownerHead = (kind, o) => (kind === "positions" ? `${o.company || "New position"}, ${[o.title, o.team].filter(Boolean).join(", ")}` : o.name || "New project");
const ownerSub = (kind, o) => (kind === "positions" ? `${o.start || "?"} to ${o.end || "?"}${o.product ? `, ${o.product}` : ""}` : o.url || "");

function ownerCard(kind, o, oi, base) {
  const key = ownerKey(kind, o);
  const closed = M.closed.has(key);
  const open = !!M.open[key];
  const list = M.draft[kind];
  const single = kind === "positions" ? "position" : "project";
  const gameSel = kind === "positions" ? `<label class="field"><span>Game <span class="faint">optional</span></span><select data-sf="${kind}" data-f="game"><option value="">None</option>
      ${(M.draft.games || []).map((g) => `<option value="${esc(g.id)}" ${o.game === g.id ? "selected" : ""}>${esc(g.name || g.id)}</option>`).join("")}</select></label>` : "";
  const apps = (M.used[single] || {})[o.id] || [];
  return `<section class="card m-sec ${closed ? "closed" : ""}" id="m-${kind}-${oi}" data-kind="${kind}" data-oi="${oi}" data-sec="${esc(key)}">
    <div class="hd"><button class="m-tog" data-mact="toggle" aria-expanded="${!closed}">
        <span class="m-chev" aria-hidden="true"></span>
        <span class="m-head"><strong data-owner-head>${esc(ownerHead(kind, o))}</strong><span class="m-sub muted" data-owner-sub>${esc(ownerSub(kind, o))}</span></span></button>
      ${reorder("owner-move", oi, list.length, single)}
      <button class="ghost small" data-mact="details" aria-expanded="${open}">${open ? "Hide details" : "Edit details"}</button></div>
    <div class="m-body">
      ${open ? `<div class="m-details">
        ${OWNER_FIELDS[kind].map((f) => fieldInput(kind, o, f)).join("")}
        ${gameSel}
        ${idInput(single, o.id, apps, "Short and stable. Applications refer to it by this id.")}
        <div class="row m-details-foot"><span class="muted">${apps.length ? `Used by ${esc(apps.join(", "))}` : "Not used by an application"}</span><span class="grow"></span>
          <button class="ghost small danger" data-mact="owner-del">Delete ${single}</button></div>
      </div>` : ""}
      ${(o.bullets || []).map((b, bi) => masterRow(kind, o, b, bi, base)).join("")}
      <div class="mb-add"><button class="ghost small" data-mact="add">Add bullet</button></div>
    </div>
  </section>`;
}

function contactCard() {
  const b = M.draft.basics;
  const paper = `<label class="field"><span>Default paper <span class="faint">optional</span></span><select data-sf="basics" data-f="paper"><option value="">${esc(S.init.default_paper)} (the default)</option>
    ${S.init.papers.map((p) => `<option value="${esc(p)}" ${b.paper === p ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>`;
  return sectionCard("basics", "m-basics", "Contact", [b.name, b.email].filter(Boolean).join(", "), `<div class="m-details">
    ${["name", "email", "phone", "location", "linkedin", "headline"].map((f) => fieldInput("basics", b, f)).join("")}${paper}</div>`);
}

function itemRow(list, i, n, inner, what) {
  return `<div class="m-item" data-list="${list}" data-i="${i}"><div class="m-item-fields">${inner}</div>
    <div class="m-item-acts">${reorder("item-move", i, n, what)}<button class="ghost small danger" data-mact="item-del" aria-label="Delete ${esc(what)}">Delete</button></div></div>`;
}

function educationCard() {
  const items = M.draft.education || [];
  return sectionCard("education", "m-education", "Education", `${items.length} ${items.length === 1 ? "entry" : "entries"}`, `
    ${items.map((e, i) => itemRow("education", i, items.length, ["school", "credential", "location", "start", "end"].map((f) => fieldInput("education", e, f)).join(""), e.school || "this entry")).join("")}
    <div class="mb-add"><button class="ghost small" data-mact="add-item" data-list="education">Add education</button></div>`);
}

const gameUsers = (g) => [...((M.used.game || {})[g.id] || []), ...M.draft.positions.filter((p) => p.game === g.id).map((p) => `position ${p.id}`)];

function gamesCard() {
  const items = M.draft.games || [];
  return sectionCard("games", "m-games", "Games", plural(items.length, "game"), `
    ${items.map((g, i) => itemRow("games", i, items.length, ["name", "start", "end"].map((f) => fieldInput("games", g, f)).join("") + idInput("game", g.id, gameUsers(g), "Positions and applications refer to a game by this id."), g.name || "this game")).join("")}
    <div class="mb-add"><button class="ghost small" data-mact="add-item" data-list="games">Add game</button></div>`);
}

function skillsCard() {
  const items = M.draft.skills || [];
  return sectionCard("skills", "m-skills", "Skills", plural(items.length, "group"), `
    ${items.map((g, i) => {
      const apps = (M.used["skill group"] || {})[g.group] || [];
      const name = apps.length
        ? `<div class="field">Group <code class="m-id" title="Used by ${esc(apps.join(", "))}, so its name cannot change">${esc(g.group)}</code></div>`
        : `<label class="field">Group<input data-gf="group" value="${esc(g.group)}"></label>`;
      return itemRow("skills", i, items.length, `${name}<label class="field m-wide"><span>Skills <span class="faint">comma separated, one line on the resume</span></span><textarea data-gf="items" data-auto rows="1">${esc((g.items || []).join(", "))}</textarea></label>`, g.group || "this group");
    }).join("")}
    <div class="mb-add"><button class="ghost small" data-mact="add-item" data-list="skills">Add skill group</button></div>`);
}

// ----- master page: saving -----

function masterSummary() {
  if (M.mode === "raw") return "Unsaved changes to the YAML";
  const base = baseBullets();
  const seen = new Set();
  let edited = 0;
  let added = 0;
  for (const b of owners().flatMap((o) => o.bullets || [])) {
    seen.add(b.id);
    if (!(b.id in base)) added++;
    else if (base[b.id] !== JSON.stringify(b)) edited++;
  }
  const removed = Object.keys(base).filter((id) => !seen.has(id)).length;
  const parts = [[edited, "edited"], [added, "added"], [removed, "deleted"]].filter(([n]) => n).map(([n, w]) => `${plural(n, "bullet")} ${w}`);
  const same = (key) => JSON.stringify(M.draft[key] ?? null) === JSON.stringify(M.base[key] ?? null);
  const shell = (list) => JSON.stringify((list || []).map((o) => ({ ...o, bullets: undefined })));
  const order = (list) => JSON.stringify((list || []).map((o) => (o.bullets || []).map((b) => b.id)));
  if (!same("basics")) parts.push("contact details");
  if (!same("education")) parts.push("education");
  if (!same("games")) parts.push("games");
  if (!same("skills")) parts.push("skills");
  if (shell(M.draft.positions) !== shell(M.base.positions)) parts.push("positions");
  if (shell(M.draft.projects) !== shell(M.base.projects)) parts.push("projects");
  if (!parts.length && (order(M.draft.positions) !== order(M.base.positions) || order(M.draft.projects) !== order(M.base.projects))) parts.push("bullet order");
  return parts.length ? `Unsaved changes: ${parts.join(", ")}` : "Unsaved changes";
}

function updateSavebar() {
  const bar = $("#savebar");
  if (!bar) return;
  bar.hidden = !masterDirty() && !M.saving && !M.error;
  renderJump();
  if (M.saving) return;
  $("#save-msg").innerHTML = M.error ? `<span class="pill bad">Not saved</span> ${esc(M.error)}` : esc(masterSummary());
}

// What a form can leave wrong, caught here with a plain message. The server checks it as well.
function masterProblems() {
  const out = [];
  const date = /^(\d{4}-\d{1,2}|present)$/i;
  const need = (label, o, fields) => {
    for (const f of fields) if (!String(o[f] ?? "").trim()) out.push(`${label} needs ${FIELD_LABEL[f].toLowerCase()}`);
    for (const f of ["start", "end"]) if (o[f] && !date.test(String(o[f]))) out.push(`${label}: ${f} should be ${DATE_HINT}, not "${o[f]}"`);
  };
  need("Contact", M.draft.basics, REQUIRED.basics);
  for (const p of M.draft.positions) need(`Position ${p.company || p.id}`, p, REQUIRED.positions);
  for (const p of M.draft.projects || []) need(`Project ${p.name || p.id}`, p, REQUIRED.projects);
  for (const g of M.draft.games || []) need(`Game ${g.name || g.id}`, g, REQUIRED.games);
  for (const e of M.draft.education || []) need(`Education ${e.school || ""}`.trim(), e, REQUIRED.education);
  for (const g of M.draft.skills || []) if (!String(g.group ?? "").trim()) out.push("A skill group needs a name");
  for (const b of owners().flatMap((o) => o.bullets || [])) if (!b.text.trim()) out.push(`Bullet ${b.id} has no text`);
  return out;
}

const splitList = (v) => v.split(",").map((t) => t.replace(/\s+/g, " ").trim()).filter(Boolean);

document.addEventListener("input", (e) => {
  const el = e.target;
  if (!el.closest(".master")) return;
  if (el.dataset.mfilter) {
    M[el.dataset.mfilter] = el.value;
    return applyFilter();
  }
  if (el.dataset.mmove !== undefined || el.dataset.idf) return;  // these act on change, below
  M.error = "";
  if (el.id === "raw-master") {
    M.rawText = el.value;
    return updateSavebar();
  }
  if (el.dataset.auto !== undefined) grow(el);
  const card = el.closest("[data-kind]");
  if (el.dataset.sf) {
    const scope = el.dataset.sf;
    const list = el.closest("[data-list]");
    const target = scope === "basics" ? M.draft.basics : list ? M.draft[scope][Number(list.dataset.i)] : M.draft[scope][Number(card.dataset.oi)];
    setField(target, el.dataset.f, el.value.trim() === "" ? "" : el.value, FIELD_ORDER[scope], (REQUIRED[scope] || []).includes(el.dataset.f));
    if (card) {
      $("[data-owner-head]", card).textContent = ownerHead(card.dataset.kind, target);
      $("[data-owner-sub]", card).textContent = ownerSub(card.dataset.kind, target);
    }
  }
  const row = el.closest("[data-bi]");
  if (row && el.dataset.bf) {
    const b = rowOwner(row).o.bullets[Number(row.dataset.bi)];
    const f = el.dataset.bf;
    if (f === "text") b.text = el.value.replace(/\s*\n\s*/g, " ");
    if (f === "tags") b.tags = splitList(el.value);
    if (f === "short") setField(b, "short", el.value.trim() ? el.value.replace(/\s*\n\s*/g, " ") : "", FIELD_ORDER.bullets);
    if (f === "priority") b.priority = Number(el.value);
    if (f === "variant") setField(b, "variant_of", el.value, FIELD_ORDER.bullets);
    if (f === "text" || f === "short") $(`[data-hint=${f}]`, row).innerHTML = textHint(f === "text" ? b.text : b.short || "");
    row.classList.toggle("dirty", bulletDirty(b));
  }
  const g = el.closest('[data-list="skills"]');
  if (g && el.dataset.gf) {
    const group = M.draft.skills[Number(g.dataset.i)];
    if (el.dataset.gf === "group") group.group = el.value;
    if (el.dataset.gf === "items") group.items = splitList(el.value);
  }
  updateSavebar();
});

const idProblem = (id, taken) => (!ID_RULE.test(id) ? "Use lowercase letters, numbers and hyphens for an id." : taken ? `The id ${esc(id)} is already used. Pick another.` : "");

// Changing an id, once the field is left. Everything that points at the old id moves with it.
function renameBullet(el) {
  const row = el.closest("[data-bi]");
  const { o } = rowOwner(row);
  const b = o.bullets[Number(row.dataset.bi)];
  const id = el.value.trim();
  if (id === b.id) return;
  const bad = idProblem(id, allIds().has(id));
  if (bad) {
    el.value = b.id;
    return toast(bad, true);
  }
  applyBulletId(o, b, id, row);
}

function applyBulletId(o, b, id, row) {
  for (const x of o.bullets) if (x.variant_of === b.id) x.variant_of = id;
  document.querySelectorAll('.master select[data-bf="variant"] option').forEach((opt) => {
    if (opt.value === b.id) opt.value = id;
  });
  if (M.exp.delete(b.id)) M.exp.add(id);
  b.id = id;
  row.dataset.bid = id;
  const input = $("[data-idf=bullet]", row);
  if (input) input.value = id;
  row.classList.toggle("dirty", bulletDirty(b));
  updateSavebar();
}

function renameThing(el) {
  const kind = el.dataset.idf;
  const id = el.value.trim();
  const list = el.closest("[data-list]");
  const card = el.closest("[data-kind]");
  const obj = kind === "game" ? M.draft.games[Number(list.dataset.i)] : M.draft[card.dataset.kind][Number(card.dataset.oi)];
  if (id === obj.id) return;
  const siblings = kind === "game" ? M.draft.games : M.draft[card.dataset.kind];
  const bad = idProblem(id, siblings.some((x) => x.id === id));
  if (bad) {
    el.value = obj.id;
    return toast(bad, true);
  }
  applyThingId(kind, obj, id, card);
  el.value = id;
}

function applyThingId(kind, obj, id, card) {
  if (kind === "game") {
    for (const p of M.draft.positions) if (p.game === obj.id) p.game = id;
    obj.id = id;
    return updateSavebar();
  }
  const from = ownerKey(card.dataset.kind, obj);
  obj.id = id;
  const to = ownerKey(card.dataset.kind, obj);
  if (M.closed.delete(from)) M.closed.add(to);
  if (M.open[from]) {
    delete M.open[from];
    M.open[to] = true;
  }
  card.dataset.sec = to;
  updateSavebar();
}

// A new item starts with a placeholder id. The first real name replaces it, so nobody has to
// invent an id, and after that it stays put unless changed by hand.
const PLACEHOLDER_ID = /^new-(position|project|game)(-\d+)?$/;
const PLACEHOLDER_BULLET = /^(.*-)?new(-\d+)?$/;

function autoIds(el) {
  const row = el.closest("[data-bi]");
  if (row && el.dataset.bf === "text") {
    const { o } = rowOwner(row);
    const b = o.bullets[Number(row.dataset.bi)];
    const m = b.id.match(PLACEHOLDER_BULLET);
    const wanted = slug(b.text, 4);
    if (m && !(b.id in baseBullets()) && wanted.length > 1) {
      const taken = allIds();
      taken.delete(b.id);
      applyBulletId(o, b, uniqueId(`${m[1] || ""}${wanted}`, taken), row);
    }
    return;
  }
  if (!el.dataset.sf) return;
  const card = el.closest("[data-kind]");
  const list = el.closest('[data-list="games"]');
  if (!card && !list) return;
  const obj = list ? M.draft.games[Number(list.dataset.i)] : M.draft[card.dataset.kind][Number(card.dataset.oi)];
  if (!PLACEHOLDER_ID.test(obj.id)) return;
  const wanted = slug(list || card.dataset.kind === "projects" ? obj.name || "" : [obj.company, obj.title].filter(Boolean).join(" "));
  if (wanted.length < 2) return;
  const siblings = new Set((list ? M.draft.games : M.draft[card.dataset.kind]).filter((x) => x !== obj).map((x) => x.id));
  applyThingId(list ? "game" : card.dataset.kind === "positions" ? "position" : "project", obj, uniqueId(wanted, siblings), card);
  const input = $("[data-idf]", list || card);
  if (input) input.value = obj.id;
}

document.addEventListener("change", (e) => {
  const el = e.target;
  if (!el.closest(".master")) return;
  if (el.dataset.bf === "priority") el.dispatchEvent(new Event("input", { bubbles: true }));
  if (el.dataset.idf === "bullet") renameBullet(el);
  else if (el.dataset.idf) renameThing(el);
  else if (el.dataset.mmove !== undefined) moveBullet(el);
  else autoIds(el);
});

function moveBullet(el) {
  const row = el.closest("[data-bi]");
  const { o } = rowOwner(row);
  const b = o.bullets[Number(row.dataset.bi)];
  const split = el.value.indexOf(":");
  const toKind = el.value.slice(0, split);
  const target = (M.draft[toKind] || []).find((p) => p.id === el.value.slice(split + 1));
  if (!target) return;
  const family = variantFamily(o, b);
  const names = family.map((x) => x.id).join(" and ");
  const apps = [...new Set(family.flatMap((x) => M.usage[x.id] || []))];
  if (apps.length) {
    el.value = "";
    const them = family.length > 1 ? "them" : "it";
    return toast(`${esc(names)} ${family.length > 1 ? "are" : "is"} used by ${apps.map(esc).join(", ")}. Untick ${them} there first, then move ${them} here.`, true, 7000);
  }
  o.bullets = o.bullets.filter((x) => !family.includes(x));
  target.bullets = [...(target.bullets || []), ...family];
  M.closed.delete(ownerKey(toKind, target));
  renderMasterBody();
  toast(`Moved ${esc(names)} to ${esc(toKind === "positions" ? target.company : target.name)}.`);
  document.querySelector(`.master [data-bid="${CSS.escape(b.id)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function swap(list, i, dir) {
  const j = i + dir;
  if (j < 0 || j >= list.length) return false;
  [list[i], list[j]] = [list[j], list[i]];
  return true;
}

// After a redraw, puts the keyboard back on the button that was just pressed, if it still can be.
function refocus(selector) {
  const el = document.querySelector(selector);
  if (el && !el.disabled) el.focus();
}

function collapseRow(row) {
  const { o } = rowOwner(row);
  const b = o.bullets[Number(row.dataset.bi)];
  M.exp.delete(b.id);
  if (!b.text.trim() && !(b.id in baseBullets())) {  // a new bullet nothing was typed into
    o.bullets.splice(o.bullets.indexOf(b), 1);
    return renderMasterBody();
  }
  redrawRow(row, ".mb-open");
  updateSavebar();
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const row = e.target.closest?.(".master .mb.open");
  if (row) collapseRow(row);
});

function setClosed(sec, closed) {
  if (!sec) return;
  sec.classList.toggle("closed", closed);
  $(".m-tog", sec)?.setAttribute("aria-expanded", String(!closed));
  if (!closed) growAll(sec);
}

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-mact]");
  if (!el || !el.closest(".master, #impact")) return;
  const act = el.dataset.mact;
  const card = el.closest("[data-kind]");
  const owner = card && M.draft[card.dataset.kind][Number(card.dataset.oi)];
  const row = el.closest("[data-bi]");
  const sec = el.closest("[data-sec]");
  if (act === "check") {
    await runImpact();
  } else if (act === "impact-close") {
    M.impact = null;
    renderImpact();
  } else if (act === "jump") {
    if (M.q || M.tag || M.show) {  // the section may be filtered out, so show everything again
      M.q = M.tag = M.show = "";
      M.closed.delete(el.dataset.key);
      renderMasterBody();
    } else if (M.closed.delete(el.dataset.key)) {
      setClosed(document.getElementById(el.dataset.target), false);
      applyFilter();
    }
    document.getElementById(el.dataset.target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (act === "toggle") {
    const closing = !M.closed.has(sec.dataset.sec);
    if (closing) M.closed.add(sec.dataset.sec);
    else M.closed.delete(sec.dataset.sec);
    setClosed(sec, closing);
    applyFilter();
  } else if (act === "collapse-all") {
    const closing = !ownerKeys().every((k) => M.closed.has(k));
    for (const k of ownerKeys()) {
      if (closing) M.closed.add(k);
      else M.closed.delete(k);
    }
    renderMasterBody();
  } else if (act === "details") {
    const key = sec.dataset.sec;
    M.open[key] = !M.open[key];
    M.closed.delete(key);
    renderMasterBody();
    refocus(`#${card.id} [data-mact=details]`);
  } else if (act === "b-open") {
    M.exp.add(row.dataset.bid);
    redrawRow(row, "textarea[data-bf=text]");
  } else if (act === "b-close") {
    collapseRow(row);
  } else if (act === "b-move") {
    const id = row.dataset.bid;
    if (!swap(owner.bullets, Number(row.dataset.bi), Number(el.dataset.dir))) return;
    renderMasterBody();
    refocus(`.master [data-bid="${CSS.escape(id)}"] [data-mact=b-move][data-dir="${el.dataset.dir}"]`);
  } else if (act === "del") {
    const b = owner.bullets[Number(row.dataset.bi)];
    const used = M.usage[b.id] || [];
    if (used.length) return toast(`${esc(b.id)} is used by ${used.map(esc).join(", ")}. Untick it there first, then delete it here.`, true, 7000);
    if (!confirm(`Delete bullet ${b.id}?\n\n${b.text}`)) return;
    owner.bullets.splice(owner.bullets.indexOf(b), 1);
    for (const x of owner.bullets) if (x.variant_of === b.id) delete x.variant_of;
    M.exp.delete(b.id);
    renderMasterBody();
  } else if (act === "add") {
    const id = uniqueId(`${commonPrefix((owner.bullets || []).map((b) => b.id))}new`, allIds());
    owner.bullets = owner.bullets || [];
    owner.bullets.push({ id, text: "", tags: [], priority: 2 });
    M.exp.add(id);
    renderMasterBody();
    const next = document.querySelector(`.master [data-bid="${CSS.escape(id)}"]`);
    next?.scrollIntoView({ block: "center" });
    $("textarea[data-bf=text]", next)?.focus();
  } else if (act === "add-owner") {
    const kind = el.dataset.kind;
    const single = kind === "positions" ? "position" : "project";
    M.draft[kind] = M.draft[kind] || [];
    const id = uniqueId(`new-${single}`, new Set(M.draft[kind].map((o) => o.id)));
    const fresh = kind === "positions" ? { id, company: "", title: "", start: "", end: "present", bullets: [] } : { id, name: "", bullets: [] };
    if (kind === "positions") M.draft[kind].unshift(fresh);
    else M.draft[kind].push(fresh);
    const key = ownerKey(kind, fresh);
    M.open[key] = true;
    M.closed.delete(key);
    renderMasterBody();
    const next = document.getElementById(`m-${kind}-${M.draft[kind].indexOf(fresh)}`);
    next?.scrollIntoView({ block: "center" });
    $("[data-sf]", next)?.focus();
  } else if (act === "owner-move") {
    const id = owner.id;
    const kind = card.dataset.kind;
    if (!swap(M.draft[kind], Number(card.dataset.oi), Number(el.dataset.dir))) return;
    renderMasterBody();
    const i = M.draft[kind].findIndex((o) => o.id === id);
    refocus(`#m-${kind}-${i} > .hd [data-mact=owner-move][data-dir="${el.dataset.dir}"]`);
  } else if (act === "owner-del") {
    const kind = card.dataset.kind;
    const single = kind === "positions" ? "position" : "project";
    const apps = [...new Set([...((M.used[single] || {})[owner.id] || []), ...(owner.bullets || []).flatMap((b) => M.usage[b.id] || [])])];
    if (apps.length) return toast(`${esc(ownerHead(kind, owner))} is used by ${apps.map(esc).join(", ")}. Remove it there first, then delete it here.`, true, 7000);
    if (!confirm(`Delete ${ownerHead(kind, owner)} and its ${plural((owner.bullets || []).length, "bullet")}?`)) return;
    M.draft[kind].splice(M.draft[kind].indexOf(owner), 1);
    renderMasterBody();
  } else if (act === "add-item") {
    const list = el.dataset.list;
    M.draft[list] = M.draft[list] || [];
    M.draft[list].push(list === "games" ? { id: uniqueId("new-game", new Set(M.draft.games.map((g) => g.id))), name: "", start: "", end: "present" }
      : list === "education" ? { school: "", start: "", end: "" }
      : { group: "", items: [] });
    renderMasterBody();
    const items = document.querySelectorAll(`.master .m-item[data-list="${list}"]`);
    $("input", items[items.length - 1])?.focus();
  } else if (act === "item-move") {
    const box = el.closest("[data-list]");
    const list = box.dataset.list;
    const i = Number(box.dataset.i);
    const dir = Number(el.dataset.dir);
    if (!swap(M.draft[list], i, dir)) return;
    renderMasterBody();
    refocus(`.master .m-item[data-list="${list}"][data-i="${i + dir}"] [data-mact=item-move][data-dir="${dir}"]`);
  } else if (act === "item-del") {
    const box = el.closest("[data-list]");
    const list = box.dataset.list;
    const item = M.draft[list][Number(box.dataset.i)];
    const apps = list === "games" ? gameUsers(item) : list === "skills" ? (M.used["skill group"] || {})[item.group] || [] : [];
    const label = item.name || item.school || item.group;
    if (apps.length) return toast(`${esc(label)} is used by ${apps.map(esc).join(", ")}. Remove it there first, then delete it here.`, true, 7000);
    if (label && !confirm(`Delete ${label}?`)) return;
    M.draft[list].splice(Number(box.dataset.i), 1);
    renderMasterBody();
  } else if (act === "discard") {
    if (!confirm("Discard your unsaved master changes?")) return;
    M.draft = clone(M.base);
    M.rawText = null;
    M.error = "";
    M.exp.clear();
    renderMasterBody();
  } else if (act === "save") {
    await saveMaster();
  }
});

function commonPrefix(ids) {
  const parts = ids.map((id) => id.split("-")[0]);
  return parts.length && parts.every((p) => p === parts[0]) ? `${parts[0]}-` : "";
}

function allIds() {
  return new Set(owners().flatMap((o) => (o.bullets || []).map((b) => b.id)));
}

async function saveMaster() {
  if (M.mode !== "raw") {
    const problems = masterProblems();
    if (problems.length) {
      M.error = problems.slice(0, 2).join(". ") + (problems.length > 2 ? `. And ${problems.length - 2} more.` : ".");
      return updateSavebar();
    }
  }
  M.saving = true;
  M.error = "";
  $("#save-msg").textContent = "Saving…";
  try {
    const body = M.mode === "raw" && M.rawText != null ? { text: M.rawText } : { master: M.draft };
    const r = await api("PUT", "/api/master", body);
    M.base = r.master;
    M.draft = clone(r.master);
    M.text = r.text;
    M.rawText = null;
    M.usage = r.usage;
    M.used = r.used;
    S.versions = { ...S.versions, ...r.versions };
    S.master = null;
    renderMasterBody();
    const warns = r.warnings.length ? ` Check: ${r.warnings.map(esc).join("; ")}` : "";
    toast(`Master saved. The previous version is in master-history.${warns}`, !!warns, warns ? 9000 : 4000);
    runImpact();
  } catch (err) {
    M.error = err.message;
  } finally {
    M.saving = false;
    updateSavebar();
  }
}

window.addEventListener("beforeunload", (e) => {
  if (masterDirty()) e.preventDefault();
});

// Ctrl+S saves now instead of opening the browser's save dialog.
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== "s") return;
  if (location.hash.startsWith("#/master")) {
    e.preventDefault();
    if (masterDirty() && !M.saving) saveMaster();
  } else if (S.app) {
    e.preventDefault();
    commitStudio();
    saveNow();
    saveLetter();
    saveListing();
  }
});

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
        Tracking history stays as it is now, because it records what really happened; a snapshot's copy comes back only for an application that has none, such as a deleted one.
        Separately, every save of <code>master.yaml</code> keeps the previous version in <code>snapshots/master-history/</code>.</p>
        <div class="row"><input id="snap-label" placeholder="Label (optional), e.g. before-big-rewrite" style="max-width:380px"><button class="primary" id="snap-create">Take snapshot</button></div>
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
  if (!confirm(`Restore ${name}?\n\nThis writes the snapshot's files over your current master.yaml, applications and templates. Tracking history stays as it is now, unless an application has none (a deleted one coming back). A snapshot of the current state is taken first.`)) return;
  try {
    const r = await api("POST", `/api/snapshots/${enc(name)}/restore`);
    S.app = null;
    const kept = r.kept_tracking ? ` Kept the current tracking history for ${plural(r.kept_tracking, "application")}.` : "";
    toast(`Restored ${plural(r.restored, "file")}.${kept} Previous state saved as ${esc(r.backup)}.`, false, 7000);
    showSnapshots();
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ---------- outside edits ----------

// Poll file times so edits made in a text editor or by Claude Code show up here.
let serverLost = false;
async function pollVersions() {
  if (document.hidden || savePending || savesInFlight || S.conflict || !S.versions) return;
  const name = S.app?.name;
  let v;
  try {
    v = await api("GET", `/api/versions${name ? `?app=${enc(name)}` : ""}`);
  } catch {
    status("Server not responding", "bad");
    serverLost = true;
    return;
  }
  if (serverLost) status("");
  serverLost = false;
  if (S.init.needs_master) {
    if (v.master) masterAppeared();
    return;
  }
  if (savePending || savesInFlight || S.conflict) return;  // a save started meanwhile: its write is not an outside edit
  const moved = Object.keys(v).some((k) => k in S.versions && v[k] > S.versions[k] + 0.001);
  S.versions = { ...S.versions, ...v };
  if (moved && !S.app && location.hash.startsWith("#/master")) {
    if (masterDirty()) return toast("master.yaml changed on disk while you have unsaved edits here. Saving will overwrite those outside changes.", true, 8000);
    M.draft = null;
    showMaster(M.mode);
    return toast("Reloaded: master.yaml changed on disk");
  }
  if (moved && !S.app && $("#tbody")) {
    // The board: something changed from the CLI or Claude. Leave it alone while a dialog is open.
    if (!document.querySelector("dialog[open], .menu:popover-open")) refreshHome();
    return;
  }
  if (!S.app || S.app.name !== name) return;
  if (moved) S.outsideChange = true;
  if (!S.outsideChange) return;
  // Not in the middle of an edit. The change stays pending and loads on a later poll, once the
  // edit is done. If the edit saves first, the server refuses it and offers a choice.
  if (S.ui.editing || ON_OUTSIDE_EDIT.blocked()) {
    if (!S.outsideNoted) toast("Files changed on disk. They load here when you finish this edit.", false, 7000);
    S.outsideNoted = true;
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
  if (S.init.data_home) {
    const b = $("#home-badge");
    b.hidden = false;
    b.title = `This checkout is a git worktree, so data and applications come from ${S.init.data_home}`;
  }
  document.title = S.init.example ? "DynamicResume (example)" : "DynamicResume";
  $("#snap-btn").onclick = () => takeSnapshot();
  S.versions = await api("GET", "/api/versions");
  window.addEventListener("hashchange", route);
  route();
  setInterval(pollVersions, 2000);
})();
