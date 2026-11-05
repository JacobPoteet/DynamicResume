"use strict";
// The home page: every application on a board by stage, plus List, Timeline and Stats views.
// Stage changes are dated events in each application's tracking.yaml (see studio/tracking.py);
// the Applied date is the day it was marked submitted. Uses the helpers in app.js.

const COLUMNS = [["saved", "Saved"], ["drafting", "Drafting"], ["applied", "Applied"], ["screen", "Screen"], ["interviewing", "Interviewing"], ["offer", "Offer"]];
const TRAYS = [["rejected", "Rejected"], ["ghosted", "Ghosted"], ["withdrew", "Withdrew"]];
const COL_LABEL = Object.fromEntries([...COLUMNS, ...TRAYS]);
const EV_LABEL = { applied: "Applied", screen: "Screen", interview: "Interview", offer: "Offer", rejected: "Rejected", ghosted: "Ghosted", withdrew: "Withdrew", note: "Note" };
const EV_COLUMN = { applied: "applied", screen: "screen", interview: "interviewing", offer: "offer", rejected: "rejected", ghosted: "ghosted", withdrew: "withdrew" };
const COLUMN_EV = Object.fromEntries(Object.entries(EV_COLUMN).map(([k, v]) => [v, k]));
const CLOSED = ["rejected", "ghosted", "withdrew"];
const FORMATS = [["", "Not set"], ["phone", "Phone"], ["video", "Video"], ["onsite", "Onsite"], ["take-home", "Take-home"]];
const MODES = [["board", "Board"], ["list", "List"], ["timeline", "Timeline"], ["stats", "Stats"]];

// q and stage filter Board and List; sort and dir order List. All four are remembered per browser.
const T = { apps: [], stats: null, mode: "board", tray: pref.get("tray", ""), hist: null,
  q: pref.get("q", ""), stage: pref.get("stage", ""), sort: pref.get("sort", "updated"), dir: pref.get("dir", "desc") };

// ----- dates (local calendar days, "YYYY-MM-DD") -----

const pad2 = (n) => String(n).padStart(2, "0");
const isoDay = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const toDate = (iso) => { const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); };
const todayIso = () => isoDay(new Date());
const shiftDay = (iso, n) => { const d = toDate(iso); d.setDate(d.getDate() + n); return isoDay(d); };
const daysBetween = (a, b) => Math.round((toDate(b) - toDate(a)) / 86400000);

function fmtShort(iso) {
  const d = toDate(iso);
  const opts = { month: "short", day: "numeric" };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString(undefined, opts);
}

// "2026-11-06 14:00" -> "Fri, Nov 6, 2:00 PM"; a bare date has no time.
function fmtWhen(s) {
  const [day, time] = String(s).split(" ");
  const d = toDate(day);
  const opts = { weekday: "short", month: "short", day: "numeric" };
  if (time) {
    const [h, m] = time.split(":").map(Number);
    d.setHours(h, m);
    Object.assign(opts, { hour: "numeric", minute: "2-digit" });
  }
  return d.toLocaleString(undefined, opts);
}

const dayCount = (n) => `${n} ${n === 1 ? "day" : "days"}`;

// ----- page -----

async function showHome(mode = "board") {
  S.app = null;
  T.mode = mode;
  view(`<div class="page wide tracker">
    <div class="thead">
      <h1>Applications</h1>
      <nav class="tabs" aria-label="View">${MODES.map(([k, l]) => `<a href="#/${k === "board" ? "" : k}" class="${k === mode ? "on" : ""}" ${k === mode ? `aria-current="page"` : ""}>${l}</a>`).join("")}</nav>
      <span class="grow"></span>
      <button class="primary" id="new-app">New application</button>
    </div>
    ${filterBar(mode)}
    <div id="tbody"><div class="empty"><span class="spinner"></span></div></div>
  </div>
  <dialog id="new-dlg" class="dlg" aria-labelledby="new-h">${newAppForm()}</dialog>
  <dialog id="ev-dlg" class="dlg"></dialog>
  <dialog id="hist-dlg" class="hist-dlg" aria-labelledby="hist-h"></dialog>`);
  $("#new-app").onclick = openNewApp;
  wireFilters();
  $("#na-create").onclick = () => createApp(false);
  $("#na-save").onclick = () => createApp(false, true);
  if ($("#na-draft")) $("#na-draft").onclick = () => createApp(true);
  $("#na-cancel").onclick = () => $("#new-dlg").close();
  $("#hist-dlg").addEventListener("close", () => (T.hist = null));
  await refreshHome();
}

function newAppForm() {
  return `<div class="dlg-hd"><h2 id="new-h">New application</h2></div>
    <div class="stack">
      <div class="target">
        <label class="field">Studio<input id="na-studio" placeholder="Sample Studio"></label>
        <label class="field">Role<input id="na-role" placeholder="Gameplay Designer"></label>
      </div>
      <div id="na-from-box"></div>
      <label class="field">Link to the posting (optional)<input id="na-url" type="url" placeholder="https://"></label>
      <label class="field">Job listing<textarea id="na-listing" rows="12" placeholder="Paste the full listing"></textarea></label>
      <div class="muted" style="font-size:12px">${S.init.claude
        ? "Drafting runs Claude Code in this repo with read-only access (a minute or two). It picks and orders bullets, writes a cover letter, and lists what the master cannot back up. Without drafting, every priority 1 bullet starts selected."
        : "Starts with every priority 1 bullet selected. Install Claude Code to draft automatically."}</div>
      <div id="na-err" class="muted"></div>
      <div class="row dlg-ft">
        <span class="grow"></span>
        <button id="na-cancel" type="button">Cancel</button>
        <button id="na-save" title="Keep it as a lead in the Saved column. Needs only a studio and a role.">Save for later</button>
        <button id="na-create">${S.init.claude ? "Create without drafting" : "Create"}</button>
        ${S.init.claude ? `<button class="primary" id="na-draft">Create and draft with Claude</button>` : ""}
      </div>
    </div>`;
}

// Reload the applications and stats, then redraw the current view (and an open history).
async function refreshHome() {
  const [{ apps }, stats] = await Promise.all([api("GET", "/api/apps"), api("GET", "/api/stats")]);
  T.apps = apps;
  T.stats = stats;
  if (!$("#tbody")) return;
  redraw();
  if (T.hist && $("#hist-dlg").open) renderHistory();
  api("GET", "/api/versions").then((v) => (S.versions = { ...S.versions, ...v })).catch(() => {});
}

const appLabel = (a) => a.studio || a.name;
const findApp = (name) => T.apps.find((a) => a.name === name);

// ----- search, filter, start from -----

const stages = () => [...COLUMNS, ...TRAYS];
const filtering = () => Boolean(T.q.trim() || stages().some(([k]) => k === T.stage));

// The applications that pass the search box (every word in studio or role) and the stage menu.
function visible() {
  const words = T.q.toLowerCase().split(/\s+/).filter(Boolean);
  const stage = stages().some(([k]) => k === T.stage) ? T.stage : "";
  return T.apps.filter((a) => {
    const hay = `${appLabel(a)} ${a.role}`.toLowerCase();
    return (!stage || a.track.column === stage) && words.every((w) => hay.includes(w));
  });
}

// Drawn once by showHome, outside #tbody, so redrawing the board never takes focus from the box.
function filterBar(mode) {
  return `<div class="filters" id="filters" role="search" ${mode === "board" || mode === "list" ? "" : "hidden"}>
    <input type="search" id="f-q" placeholder="Search studio or role" aria-label="Search applications by studio or role" value="${esc(T.q)}" autocomplete="off">
    <select id="f-stage" aria-label="Filter by stage"><option value="">All stages</option>${stages().map(([k, l]) =>
      `<option value="${k}" ${k === T.stage ? "selected" : ""}>${l}</option>`).join("")}</select>
    <button type="button" class="ghost small" id="f-clear" hidden>Clear filters</button>
    <span class="faint" id="f-count" role="status"></span>
  </div>`;
}

function wireFilters() {
  $("#f-q").oninput = (e) => { T.q = e.target.value; pref.set("q", T.q); redraw(); };
  $("#f-stage").onchange = (e) => { T.stage = e.target.value; pref.set("stage", T.stage); redraw(); };
  $("#f-clear").onclick = clearFilters;
}

function clearFilters() {
  T.q = T.stage = "";
  pref.set("q", "");
  pref.set("stage", "");
  $("#f-q").value = "";
  $("#f-stage").value = "";
  redraw();
  $("#f-q").focus();
}

// Redraw the current view from what is already loaded.
function redraw() {
  if (!$("#tbody")) return;
  ({ board: renderBoard, list: renderList, timeline: renderTimeline, stats: renderStats })[T.mode]();
  const shown = visible().length, on = filtering();
  $("#f-clear").hidden = !on;
  $("#f-count").textContent = on && T.apps.length ? `${shown} of ${plural(T.apps.length, "application")}` : "";
}

// What Board and List show when the search or stage hides every application.
function noMatches() {
  return `<div class="card empty">No applications match${T.q.trim() ? ` "${esc(T.q.trim())}"` : ""}${stages().some(([k]) => k === T.stage) ? ` in ${esc(COL_LABEL[T.stage])}` : ""}.
    <div style="margin-top:12px"><button data-clear>Clear filters</button></div></div>`;
}

// New application. "Start from" lists every application, newest edit first.
function openNewApp() {
  const box = $("#na-from-box");
  box.innerHTML = T.apps.length ? `<label class="field">Start from (optional)<select id="na-from">
      <option value="">Nothing, pick priority 1 bullets</option>
      ${T.apps.map((a) => `<option value="${esc(a.name)}">${esc(appLabel(a))}, ${esc(a.role)} (${esc(COL_LABEL[a.track.column])})</option>`).join("")}</select></label>
    <label class="check" id="na-letter-row" hidden><input type="checkbox" id="na-letter"> Also copy its cover letter</label>
    <div class="muted" id="na-from-note" style="font-size:12px" hidden>Copies its bullets, overrides, headline and template into the new application. Tracking, job details and PDFs stay behind, and a submitted application is copied as it was sent.</div>` : "";
  if ($("#na-from")) $("#na-from").onchange = (e) => {
    $("#na-letter-row").hidden = $("#na-from-note").hidden = !e.target.value;
  };
  $("#new-dlg").showModal();
}

// ----- board -----

function sorted(apps, col) {
  // Drafts by last edit; everything else by the latest thing that happened to it.
  if (col === "drafting" || col === "saved") return [...apps].sort((a, b) => b.updated - a.updated);
  return [...apps].sort((a, b) => (b.track.updated || "").localeCompare(a.track.updated || "") || b.updated - a.updated);
}

// What wants doing, soonest first, whatever the search and stage filters are showing.
// tracking.summarize decides what is on the list.
function attentionItems() {
  return T.apps.flatMap((a) => (a.track.attention || []).map((x) => ({ ...x, app: a })))
    .sort((x, y) => String(x.date).localeCompare(String(y.date)));
}

// "today", "in 3 days" or "2 days ago" for a calendar day.
function relDay(iso) {
  const n = daysBetween(todayIso(), iso);
  return n === 0 ? "today" : n === 1 ? "tomorrow" : n === -1 ? "yesterday" : n > 0 ? `in ${dayCount(n)}` : `${dayCount(-n)} ago`;
}

function attentionRow(x) {
  const a = x.app, name = esc(a.name), label = esc(appLabel(a));
  const [what, acts] = x.kind === "debrief"
    ? [`${x.round ? `Round ${esc(x.round)}` : "Interview"} on ${esc(fmtWhen(x.date))} has no debrief`,
      `<button class="small" data-how-app="${name}" data-how="${esc(x.i)}" aria-label="How it went: ${label}">How it went</button>`]
    : x.kind === "follow_up"
    ? [`Follow up, due ${esc(relDay(x.date))}${x.note ? `: ${esc(x.note)}` : ""}`,
      `<button class="small" data-fu-edit="${name}" aria-label="Change the follow-up for ${label}">Change</button>
       <button class="small" data-fu-done="${name}" aria-label="Follow-up done: ${label}">Done</button>`]
    : [`${x.date < todayIso() ? "Deadline passed" : "Deadline"} ${esc(relDay(x.date))} (${esc(fmtShort(x.date))}), not sent yet`,
      `<button class="small" data-hist="${name}" aria-label="Open ${label}">Open</button>`];
  return `<li class="att-row"><button class="att-name" data-hist="${name}">${label}</button><span class="att-what">${what}</span><span class="att-acts">${acts}</span></li>`;
}

function attentionStrip() {
  const items = attentionItems();
  if (!items.length) return "";
  return `<section class="attention" aria-labelledby="att-h">
    <h2 id="att-h">Needs attention<span>${items.length}</span></h2>
    <ul>${items.map(attentionRow).join("")}</ul>
  </section>`;
}

function strip() {
  const s = T.stats;
  if (!s || !s.sent) return "";
  const next = s.upcoming[0];
  const cell = (label, value, title = "") => `<div class="metric" ${title ? `title="${esc(title)}"` : ""}><span>${label}</span><b>${value}</b></div>`;
  return `<div class="metrics">
    ${cell("Sent", s.sent)}
    ${cell("Heard back", s.reply_rate == null ? "–" : `${Math.round(s.reply_rate * 100)}%`, `${s.replied} of ${s.sent} replied`)}
    ${cell("Median days to reply", s.median_days_to_reply ?? "–")}
    ${cell("Active", s.active)}
    ${next ? `<button class="metric next" data-hist="${esc(next.app)}"><span>Next up</span><b>${esc(next.studio || next.app)} · ${esc(fmtWhen(next.scheduled))}</b></button>
      <a class="metric cal-link" href="/api/calendar" download title="A calendar file of every upcoming call and interview. Nothing is sent from here.">Add upcoming to calendar</a>` : ""}
  </div>`;
}

function cardMeta(a) {
  const t = a.track;
  const bits = [];
  if (t.column === "saved") {
    bits.push(`<span class="faint">Not started</span>`);
  } else if (t.column === "drafting") {
    bits.push(pdfPill(a.pdfs));
  } else if (CLOSED.includes(t.column)) {
    const from = t.closed_from === "applied" ? "no reply" : `after ${COL_LABEL[t.closed_from].toLowerCase()}`;
    bits.push(`<span class="faint">${esc(fmtShort(t.since))} · ${from}${t.days_to_close != null ? ` · ${dayCount(t.days_to_close)}` : ""}</span>`);
  } else {
    const what = t.column === "applied" ? `Sent ${fmtShort(t.applied)}` : `Since ${fmtShort(t.since)}`;
    bits.push(`<span class="faint">${esc(what)} · ${daysBetween(t.since, todayIso())} d</span>`);
    if (t.column === "interviewing" && t.round) bits.push(`<span class="pill plain">Round ${t.round}</span>`);
    if (t.next) bits.push(`<span class="pill" title="Scheduled">${esc(fmtWhen(t.next))}</span>`);
    if (t.follow_up) bits.push(`<span class="pill${t.follow_up.date <= todayIso() ? " warn" : " plain"}" title="${esc(t.follow_up.note || "Follow up")}">Follow up ${esc(fmtShort(t.follow_up.date))}</span>`);
    if (t.quiet) bits.push(`<span class="pill warn" title="Nothing logged and nothing scheduled for ${dayCount(t.days_quiet)}">Quiet ${t.days_quiet} d</span><button class="small ghosted" data-ghost="${esc(a.name)}">Ghosted?</button>`);
  }
  const j = a.job || {};
  if (j.deadline) bits.push(`<span class="pill${j.deadline < todayIso() && !a.submitted ? " warn" : ""}" title="Application deadline">Due ${esc(fmtShort(j.deadline))}</span>`);
  if (safeUrl(j.url)) bits.push(`<a class="tc-link" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener noreferrer" title="${esc(j.url)}">Posting ↗</a>`);
  if (t.column === "saved") bits.push(`<button class="small" data-start="${esc(a.name)}">Start drafting</button>`);
  return bits.join("");
}

function card(a) {
  return `<article class="tcard${a.track.quiet ? " quiet" : ""}" draggable="true" tabindex="0" data-app="${esc(a.name)}"
      aria-label="${esc(appLabel(a))}, ${esc(a.role)}, ${COL_LABEL[a.track.column]}">
    <strong>${esc(appLabel(a))}</strong>
    <div class="tc-role">${esc(a.role)}</div>
    <div class="tc-meta">${cardMeta(a)}</div>
  </article>`;
}

function renderBoard() {
  const by = Object.fromEntries([...COLUMNS, ...TRAYS].map(([k]) => [k, []]));
  const shown = visible();
  for (const a of shown) by[a.track.column].push(a);
  if (!T.apps.length) {
    $("#tbody").innerHTML = `<div class="card empty">Paste a job listing to start your first application.
      <div style="margin-top:12px"><button class="primary" data-new>New application</button></div></div>`;
    $("[data-new]").onclick = openNewApp;
    return;
  }
  if (!shown.length) {
    $("#tbody").innerHTML = `${attentionStrip()}${strip()}${noMatches()}`;
    $("[data-clear]").onclick = clearFilters;
    return wireBoard();
  }
  const open = TRAYS.some(([k]) => k === T.stage) ? T.stage : TRAYS.some(([k]) => k === T.tray) ? T.tray : "";  // a stage filter opens its tray
  $("#tbody").innerHTML = `${attentionStrip()}${strip()}
    <div class="board">${COLUMNS.map(([k, l]) => `
      <section class="col" ${k === "saved" ? "" : `data-drop="${k}"`} aria-label="${l}, ${by[k].length}">
        <h2>${l}<span>${by[k].length}</span></h2>
        <div class="cards">${sorted(by[k], k).map(card).join("") || `<div class="col-empty">${k === "drafting" ? "Nothing in progress" : k === "saved" ? "No saved leads" : "Drop a card here"}</div>`}</div>
      </section>`).join("")}
    </div>
    <div class="trays">${TRAYS.map(([k, l]) => `
      <button class="tray${open === k ? " on" : ""}" data-drop="${k}" data-tray="${k}" aria-expanded="${open === k}">
        ${l}<span>${by[k].length}</span></button>`).join("")}
    </div>
    ${open ? `<div class="tray-cards">${sorted(by[open], open).map(card).join("") || `<div class="col-empty">None yet</div>`}</div>` : ""}`;
  wireBoard();
}

function wireBoard() {
  const body = $("#tbody");
  body.onclick = (e) => {
    const t = e.target;
    if (t.closest("[data-start]")) return startDrafting(findApp(t.closest("[data-start]").dataset.start));
    if (t.closest("a[href]")) return;  // the posting link opens on its own
    const how = t.closest("[data-how]");
    if (how) {
      const a = findApp(how.dataset.howApp);
      const ev = a?.track.events.find((x) => String(x.i) === how.dataset.how);
      return ev && openDebrief(a, ev);
    }
    if (t.closest("[data-fu-edit]")) return openFollowUp(findApp(t.closest("[data-fu-edit]").dataset.fuEdit));
    if (t.closest("[data-fu-done]")) return finishFollowUp(findApp(t.closest("[data-fu-done]").dataset.fuDone));
    if (t.closest("[data-ghost]")) return openEvent(findApp(t.closest("[data-ghost]").dataset.ghost), { stage: "ghosted" });
    if (t.closest("[data-tray]")) {
      const k = t.closest("[data-tray]").dataset.tray;
      T.tray = T.tray === k ? "" : k;
      pref.set("tray", T.tray);
      return renderBoard();
    }
    const h = t.closest("[data-hist]") || t.closest(".tcard");
    if (h) openHistory(h.dataset.hist || h.dataset.app);
  };
  body.onkeydown = (e) => {
    const c = e.target.closest?.(".tcard");
    if (c && e.target === c && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      openHistory(c.dataset.app);
    }
  };
  let dragging = null;
  body.ondragstart = (e) => {
    const c = e.target.closest?.(".tcard");
    if (!c) return;
    dragging = c.dataset.app;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragging);
    c.classList.add("dragging");
  };
  body.ondragover = (e) => {
    const z = e.target.closest?.("[data-drop]");
    body.querySelectorAll(".drop-on").forEach((x) => x !== z && x.classList.remove("drop-on"));
    if (!dragging || !z) return;
    e.preventDefault();
    z.classList.add("drop-on");
  };
  body.ondragleave = (e) => {
    const z = e.target.closest?.("[data-drop]");
    if (z && !z.contains(e.relatedTarget)) z.classList.remove("drop-on");
  };
  body.ondrop = (e) => {
    const z = e.target.closest?.("[data-drop]");
    if (!dragging || !z) return;
    e.preventDefault();
    const a = findApp(dragging);
    dragging = null;
    z.classList.remove("drop-on");
    dropOn(a, z.dataset.drop);
  };
  body.ondragend = () => {
    dragging = null;
    body.querySelectorAll(".dragging,.drop-on").forEach((x) => x.classList.remove("dragging", "drop-on"));
  };
}

// Clears the saved flag in job.yaml, which moves a lead to Drafting.
async function startDrafting(a) {
  if (!a) return;
  const job = { ...a.job };
  delete job.saved;
  try {
    const r = await api("PUT", `/api/apps/${enc(a.name)}/job`, { job });
    if (r.conflict) return toast("job.yaml changed on disk. Reload the page, then try again.", true, 6000);
    await refreshHome();
    toast(`${esc(appLabel(a))} moved to Drafting`);
  } catch (e) {
    toast(esc(e.message), true);
  }
}

function dropOn(a, col) {
  const from = a.track.column;
  if (from === "saved") return col === "drafting" ? startDrafting(a) : toast("Start drafting first. Then move it to Applied when you send it.", true, 6000);
  if (col === "drafting") return from === "drafting" ? undefined : toast("Cards move forward from Drafting. Delete the entry to correct a stage.", true, 6000);
  if (from === "drafting" && col !== "applied") return toast("Move it to Applied first. That marks it submitted and freezes the PDFs you sent.", true, 6000);
  if (col === from && col !== "interviewing") return;
  openEvent(a, { stage: COLUMN_EV[col] });
}

// ----- move / edit dialog -----

// opts: {stage} for a new event, or {index, event} to edit one already logged. An interview's
// debrief has its own dialog (openDebrief), since it is written after the interview.
function openEvent(a, opts = {}) {
  if (!a) return;
  const t = a.track;
  const editing = opts.index != null;
  const drafting = t.column === "drafting";
  if (drafting && !editing) return openSend(a.name);  // the only move from Drafting is sending it
  const nextStage = { drafting: "applied", applied: "screen", screen: "interview", interviewing: "interview" }[t.column] || "note";
  const ev = { date: todayIso(), ...(opts.event || {}), stage: opts.event?.stage || opts.stage || nextStage };
  if (ev.stage === "interview" && !editing) ev.round = (t.round || 0) + 1;
  const choices = drafting ? ["applied"] : editing && ev.stage === "applied" ? ["applied"]
    : ["screen", "interview", "offer", "rejected", "ghosted", "withdrew", "note"];
  const dlg = $("#ev-dlg");
  const draw = () => {
    const s = ev.stage;
    const title = editing ? `Edit ${EV_LABEL[s].toLowerCase()}` : s === "note" ? "Add a note"
      : s === "interview" && t.column === "interviewing" ? `Add round ${ev.round}` : `Move to ${COL_LABEL[EV_COLUMN[s]]}`;
    const [sd, st] = String(ev.scheduled || "").split(" ");
    const people = ev.interviewers?.length ? ev.interviewers : [{}];
    dlg.setAttribute("aria-label", `${title}: ${appLabel(a)}`);
    dlg.innerHTML = `<form class="ev-form" novalidate>
      <div class="dlg-hd"><h2>${esc(title)}</h2><span class="muted">${esc(appLabel(a))} · ${esc(a.role)}</span></div>
      <div class="stack">
        ${choices.length > 1 ? `<label class="field">Stage<select id="ev-stage">${choices.map((c) => `<option value="${c}" ${c === s ? "selected" : ""}>${EV_LABEL[c]}</option>`).join("")}</select></label>` : ""}
        <div class="field"><span id="ev-when">${s === "ghosted" ? "When did you call it?" : s === "applied" ? "When did you send it?" : s === "note" ? "Date" : s === "interview" ? "When did you hear about it?" : "When did this happen?"}</span>
          <div class="row" role="group" aria-labelledby="ev-when">
            <button type="button" class="small" data-day="0">Today</button>
            <button type="button" class="small" data-day="-1">Yesterday</button>
            <input type="date" id="ev-date" value="${esc(ev.date)}" aria-label="Date" required>
          </div></div>
        ${s === "ghosted" ? `<div class="hint">Ghosted counts as a rejection but is left out of time-to-rejection, since it has no real end date.</div>` : ""}
        ${s === "screen" || s === "interview" ? `<div class="field"><span id="ev-sched">Scheduled for (optional)</span>
          <div class="row" role="group" aria-labelledby="ev-sched">
            <input type="date" id="ev-sdate" value="${esc(sd || "")}" aria-label="Scheduled date">
            <input type="time" id="ev-stime" value="${esc(st || "")}" aria-label="Scheduled time">
          </div></div>` : ""}
        ${s === "interview" ? `<div class="iv-grid">
            <label class="field">Round<input type="number" min="1" id="ev-round" value="${esc(ev.round ?? "")}"></label>
            <label class="field">Format<select id="ev-format">${FORMATS.map(([v, l]) => `<option value="${v}" ${v === (ev.format || "") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
            <label class="field">Length (min)<input type="number" min="0" step="5" id="ev-length" value="${esc(ev.length ?? "")}"></label>
          </div>
          <div class="field"><span>Interviewers</span>
            <div id="ev-people" class="stack" style="gap:6px">${people.map((p) => personRow(p)).join("")}</div>
            <div><button type="button" class="small" id="ev-addp">Add interviewer</button></div></div>
          <label class="field">Prep notes<textarea id="ev-prep" rows="2" placeholder="What to review before it">${esc(ev.prep || "")}</textarea></label>
          ${editing ? "" : `<div class="hint">Once the scheduled time has passed, the board asks how it went.</div>`}` : ""}
        <label class="field">Note<textarea id="ev-note" rows="2" placeholder="${s === "rejected" ? "Form email, feedback given" : "Anything worth remembering"}">${esc(ev.note || "")}</textarea></label>
        <div id="ev-err" class="ev-err" role="alert"></div>
        <div class="row dlg-ft">
          ${editing ? `<button type="button" class="ghost quiet-danger" id="ev-delete">Delete entry</button>` : ""}<span class="grow"></span>
          <button type="button" id="ev-cancel">Cancel</button>
          <button class="primary" type="submit">${editing ? "Save" : s === "note" ? "Add note" : s === "interview" && t.column === "interviewing" ? "Add round" : "Move"}</button>
        </div>
      </div></form>`;
    markDay();
    $("#ev-date", dlg).oninput = markDay;
    dlg.querySelectorAll("[data-day]").forEach((b) => (b.onclick = () => { $("#ev-date", dlg).value = shiftDay(todayIso(), Number(b.dataset.day)); markDay(); }));
    if ($("#ev-stage", dlg)) $("#ev-stage", dlg).onchange = (e) => {
      Object.assign(ev, collect());
      ev.stage = e.target.value;
      if (ev.stage === "interview" && ev.round == null && !editing) ev.round = (t.round || 0) + 1;
      draw();
      $("#ev-stage", dlg).focus();
    };
    if ($("#ev-addp", dlg)) $("#ev-addp", dlg).onclick = () => {
      $("#ev-people", dlg).insertAdjacentHTML("beforeend", personRow({}));
      [...dlg.querySelectorAll(".iv-name")].pop().focus();
    };
    $("#ev-people", dlg)?.addEventListener("click", (e) => {
      const rm = e.target.closest(".iv-rm");
      if (!rm) return;
      const rows = dlg.querySelectorAll(".iv-row");
      if (rows.length > 1) rm.closest(".iv-row").remove();
      else rows[0].querySelectorAll("input").forEach((i) => (i.value = ""));
    });
    $("#ev-cancel", dlg).onclick = () => dlg.close();
    if (editing) $("#ev-delete", dlg).onclick = remove;
    $(".ev-form", dlg).onsubmit = (e) => { e.preventDefault(); save(); };
  };
  const markDay = () => {
    const v = $("#ev-date", dlg).value;
    dlg.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("aria-pressed", String(v === shiftDay(todayIso(), Number(b.dataset.day)))));
  };
  const collect = () => {
    const val = (id) => $(`#${id}`, dlg)?.value.trim() ?? "";
    const out = { date: val("ev-date"), note: val("ev-note") };
    if ($("#ev-sdate", dlg)) {
      const d = val("ev-sdate"), tm = val("ev-stime");
      out.scheduled = d ? (tm ? `${d} ${tm}` : d) : "";
    }
    if (ev.stage === "interview") {
      Object.assign(out, { round: val("ev-round"), format: val("ev-format"), length: val("ev-length"), prep: val("ev-prep"),
        debrief: ev.debrief, no_debrief: ev.no_debrief });  // not on this form, so kept as they are
      out.interviewers = [...dlg.querySelectorAll(".iv-row")].map((r) => ({ name: $(".iv-name", r).value.trim(), role: $(".iv-role", r).value.trim() }))
        .filter((p) => p.name || p.role);
    }
    return out;
  };
  const remove = async () => {
    if (!confirm(`Delete the ${EV_LABEL[ev.stage].toLowerCase()} on ${fmtDay(ev.date)}?`)) return;
    try {
      await api("DELETE", `/api/apps/${enc(a.name)}/events/${opts.index}`);
      dlg.close();
      await refreshHome();
      toast("Deleted");
    } catch (e) {
      $("#ev-err", dlg).textContent = e.message;
    }
  };
  const save = async () => {
    const body = { ...collect(), stage: ev.stage };
    const err = $("#ev-err", dlg);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(body.date)) { err.textContent = "Pick the day it happened."; return $("#ev-date", dlg).focus(); }
    if ($("#ev-stime", dlg)?.value && !$("#ev-sdate", dlg).value) { err.textContent = "Add the scheduled date for that time."; return $("#ev-sdate", dlg).focus(); }
    err.textContent = "";
    const btn = $("button[type=submit]", dlg);
    btn.disabled = true;
    try {
      const r = editing
        ? await api("PUT", `/api/apps/${enc(a.name)}/events/${opts.index}`, { event: body })
        : await api("POST", `/api/apps/${enc(a.name)}/events`, { event: body });
      dlg.close();
      await refreshHome();
      if (editing) return toast("Saved");
      const what = body.stage === "note" ? `Added a note to ${esc(appLabel(a))}`
        : body.stage === "interview" && t.column === "interviewing" ? `Added round ${esc(body.round)} for ${esc(appLabel(a))}`
        : `Moved ${esc(appLabel(a))} to ${COL_LABEL[EV_COLUMN[body.stage]]}`;
      toast(`${what}. <a href="#" id="undo">Undo</a>`, false, 8000);
      $("#undo").onclick = (e) => { e.preventDefault(); undo(a.name, r); };
    } catch (e) {
      err.textContent = e.message;
      btn.disabled = false;
    }
  };
  draw();
  dlg.showModal();
  // Start on the field you most likely fill in.
  dlg.querySelector(ev.stage === "screen" || ev.stage === "interview" ? "#ev-sdate" : "#ev-note").focus();
}

// How it went: written after the interview, on an event already logged. Saves the whole event
// back, so everything the scheduling form holds stays as it is.
function openDebrief(a, e) {
  const dlg = $("#ev-dlg");
  const { i: index, ...fields } = e;
  const round = e.round ? `Round ${e.round}` : "Interview";
  const people = (e.interviewers || []).map((p) => p.name || p.role).filter(Boolean).join(", ");
  const summary = [round, e.scheduled && fmtWhen(e.scheduled), people && `with ${people}`].filter(Boolean).join(" · ");
  dlg.setAttribute("aria-label", `How it went: ${appLabel(a)}`);
  dlg.innerHTML = `<form class="ev-form" novalidate>
    <div class="dlg-hd"><h2>How it went</h2><span class="muted">${esc(appLabel(a))} · ${esc(a.role)}</span></div>
    <div class="stack">
      <div class="muted">${esc(summary)} <button type="button" class="small" id="ev-details">Edit details</button></div>
      <label class="field">Debrief<textarea id="ev-debrief" rows="5" placeholder="How it went, what they asked">${esc(e.debrief || "")}</textarea></label>
      <label class="field">Note<textarea id="ev-note" rows="2" placeholder="Anything worth remembering">${esc(e.note || "")}</textarea></label>
      <div id="ev-err" class="ev-err" role="alert"></div>
      <div class="row dlg-ft">
        <button type="button" class="ghost" id="ev-nodebrief" title="Stop asking about this interview, for one that was cancelled or left nothing to write down">No debrief</button>
        <span class="grow"></span>
        <button type="button" id="ev-cancel">Cancel</button>
        <button class="primary" type="submit">Save</button>
      </div>
    </div></form>`;
  const typed = () => ({ debrief: $("#ev-debrief", dlg).value.trim(), note: $("#ev-note", dlg).value.trim() });
  const save = async (extra, done) => {
    const err = $("#ev-err", dlg);
    err.textContent = "";
    try {
      await api("PUT", `/api/apps/${enc(a.name)}/events/${index}`, { event: { ...fields, ...typed(), ...extra } });
      dlg.close();
      await refreshHome();
      toast(done);
    } catch (x) {
      err.textContent = x.message;
    }
  };
  const nothing = $("#ev-nodebrief", dlg);
  const markEmpty = () => { nothing.disabled = Boolean($("#ev-debrief", dlg).value.trim()); };
  $("#ev-debrief", dlg).oninput = markEmpty;
  markEmpty();
  nothing.onclick = () => save({ debrief: "", no_debrief: true }, "Saved. The board will not ask about this one again.");
  $("#ev-cancel", dlg).onclick = () => dlg.close();
  $(".ev-form", dlg).onsubmit = (x) => { x.preventDefault(); save({}, "Saved"); };
  $("#ev-details", dlg).onclick = () => {  // what was typed so far goes along, to save with the details
    const event = { ...fields, ...typed() };
    dlg.close();
    openEvent(a, { index, event });
  };
  if (!dlg.open) dlg.showModal();
  $("#ev-debrief", dlg).focus();
}

// ----- follow-up (a reminder in tracking.yaml, not an event) -----

async function saveFollowUp(a, value) {
  await api("PUT", `/api/apps/${enc(a.name)}/follow-up`, { follow_up: value });
  await refreshHome();
}

function openFollowUp(a) {
  if (!a) return;
  const dlg = $("#ev-dlg"), cur = a.track.follow_up;
  dlg.setAttribute("aria-label", `Follow up: ${appLabel(a)}`);
  dlg.innerHTML = `<form class="ev-form" novalidate>
    <div class="dlg-hd"><h2>Follow up</h2><span class="muted">${esc(appLabel(a))} · ${esc(a.role)}</span></div>
    <div class="stack">
      <div class="field"><span id="fu-when">When?</span>
        <div class="row wrap" role="group" aria-labelledby="fu-when">
          <button type="button" class="small" data-days="3">In 3 days</button>
          <button type="button" class="small" data-days="7">In a week</button>
          <button type="button" class="small" data-days="14">In 2 weeks</button>
          <input type="date" id="fu-date" value="${esc(cur?.date || "")}" aria-label="Date" required>
        </div></div>
      <label class="field">What to do (optional)<input id="fu-note" value="${esc(cur?.note || "")}" placeholder="Email the recruiter"></label>
      <div class="muted" style="font-size:12px">The board reminds you on that day. Nothing is sent from here.</div>
      <div id="ev-err" class="ev-err" role="alert"></div>
      <div class="row dlg-ft">
        ${cur ? `<button type="button" class="ghost quiet-danger" id="fu-clear">Clear</button>` : ""}<span class="grow"></span>
        <button type="button" id="ev-cancel">Cancel</button>
        <button class="primary" type="submit">Save</button>
      </div>
    </div></form>`;
  const run = async (value, done) => {
    try {
      await saveFollowUp(a, value);
      dlg.close();
      toast(done);
    } catch (x) {
      $("#ev-err", dlg).textContent = x.message;
    }
  };
  dlg.querySelectorAll("[data-days]").forEach((b) => (b.onclick = () => { $("#fu-date", dlg).value = shiftDay(todayIso(), Number(b.dataset.days)); }));
  $("#ev-cancel", dlg).onclick = () => dlg.close();
  if (cur) $("#fu-clear", dlg).onclick = () => run(null, "Follow-up cleared");
  $(".ev-form", dlg).onsubmit = (x) => {
    x.preventDefault();
    const date = $("#fu-date", dlg).value;
    if (!date) { $("#ev-err", dlg).textContent = "Pick a day."; return $("#fu-date", dlg).focus(); }
    run({ date, note: $("#fu-note", dlg).value.trim() }, `Follow up on ${esc(fmtShort(date))}`);
  };
  dlg.showModal();
  $("#fu-date", dlg).focus();
}

// Done takes the reminder away. It logs nothing: only you know whether you heard anything.
async function finishFollowUp(a) {
  if (!a?.track.follow_up) return;
  const was = a.track.follow_up;
  try {
    await saveFollowUp(a, null);
    toast(`Follow-up done for ${esc(appLabel(a))}. <a href="#" id="undo">Undo</a>`, false, 8000);
    $("#undo").onclick = async (e) => {
      e.preventDefault();
      $("#toast").className = "";
      try {
        await saveFollowUp(a, was);
        toast("Undone");
      } catch (x) {
        toast(esc(x.message), true);
      }
    };
  } catch (x) {
    toast(esc(x.message), true);
  }
}

// True once a scheduled event's start has gone by, or if it has no scheduled time at all.
function eventStarted(e) {
  if (!e.scheduled) return true;
  const [d, tm] = String(e.scheduled).split(" ");
  if (!tm) return d <= todayIso();
  const [h, m] = tm.split(":").map(Number);
  const at = toDate(d);
  at.setHours(h, m);
  return at <= new Date();
}

const personRow = (p) => `<div class="iv-row">
  <input class="iv-name" placeholder="Name" value="${esc(p.name || "")}" aria-label="Interviewer name">
  <input class="iv-role" placeholder="Role" value="${esc(p.role || "")}" aria-label="Interviewer role">
  <button type="button" class="ghost small iv-rm" aria-label="Remove interviewer">Remove</button></div>`;

async function undo(name, r) {
  $("#toast").className = "";
  try {
    if (r.index != null) await api("DELETE", `/api/apps/${enc(name)}/events/${r.index}`);
    if (r.submitted) await api("POST", `/api/apps/${enc(name)}/unsubmit`);
    await reloadAfterSend(name);
    toast(r.submitted ? "Undone. It is a draft again." : "Undone");
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ----- send (opened from the editor, or by moving a draft to Applied) -----

// The dialog lives in index.html, so it is there on the board and in the editor. `info` is
// /api/apps/<name>/send-text; `busy` holds Cancel and Escape while a build or the mark runs.
const SEND = { info: null, busy: false, warnings: [] };

// Sending or undoing it from the editor changes whether the editor opens read-only.
async function reloadAfterSend(name) {
  if (S.app?.name !== name) return refreshHome();
  await loadApp(name);
  await showEditor(name, S.tab);
}

async function openSend(name) {
  if (S.conflict) return toast(CHOOSE_FIRST, true);
  await Promise.all([saveNow(), saveLetter(), saveListing()]);
  if (S.conflict) return toast(CHOOSE_FIRST, true);  // one of those saves met an outside edit
  let info;
  try {
    info = await api("GET", `/api/apps/${enc(name)}/send-text`);
  } catch (e) {
    return toast(esc(e.message), true, 8000);
  }
  if (info.submitted) {  // sent from the CLI since this page last loaded
    toast(`${esc(name)} is already marked sent, on ${esc(fmtDay(info.submitted.date))}.`, true, 6000);
    return refreshHome();
  }
  const dlg = $("#send-dlg");
  if (dlg.open) return;  // a second click on the way here
  Object.assign(SEND, { info, busy: false, warnings: [] });
  dlg.innerHTML = `<form id="sd-form" novalidate>
    <div class="dlg-hd"><h2 id="send-h">Send</h2><span class="muted">${esc(info.studio || name)} · ${esc(info.role)}</span></div>
    <div class="stack">
      <section class="send-step" aria-labelledby="sd-h-pdfs">
        <div class="row"><h3 id="sd-h-pdfs">PDFs</h3><span class="grow"></span><span class="faint" id="sd-built" role="status"></span><button type="button" id="sd-build"></button></div>
        <div id="sd-pdfs" class="stack"></div>
        <div id="sd-build-err" class="ev-err" role="alert"></div>
      </section>
      <section class="send-step" aria-labelledby="sd-h-copy">
        <h3 id="sd-h-copy">Copy for application forms</h3>
        <div id="sd-copy"></div>
        <label class="field" id="sd-manual-box" hidden><span id="sd-manual-for"></span>
          <textarea id="sd-manual" rows="6" readonly></textarea></label>
      </section>
      ${safeUrl(info.job?.url) ? `<a href="${esc(safeUrl(info.job.url))}" target="_blank" rel="noopener noreferrer">Open posting ↗</a>` : ""}
      <section class="send-step stack" aria-labelledby="sd-h-mark">
        <h3 id="sd-h-mark">Mark it sent</h3>
        <div class="field"><span id="sd-when">When did you send it?</span>
          <div class="row" role="group" aria-labelledby="sd-when">
            <button type="button" class="small" data-day="0">Today</button>
            <button type="button" class="small" data-day="-1">Yesterday</button>
            <input type="date" id="sd-date" value="${todayIso()}" aria-label="Date" required>
          </div></div>
        <label class="field">Note (optional)<textarea id="sd-note" rows="2" placeholder="Anything worth remembering"></textarea></label>
        <div class="muted" style="font-size:12px">Marking it sent freezes the PDFs, tailor, letter, listing and master as they are now. Nothing is sent from here.</div>
        <div id="sd-err" class="ev-err" role="alert"></div>
        <div class="row dlg-ft"><span class="grow"></span>
          <button type="button" id="sd-cancel">Cancel</button>
          <button class="primary" type="submit" id="sd-mark">Mark sent</button>
        </div>
      </section>
    </div></form>`;
  $("#sd-form", dlg).onsubmit = (e) => { e.preventDefault(); markSent(); };
  $("#sd-build", dlg).onclick = rebuildSend;
  $("#sd-cancel", dlg).onclick = () => dlg.close();
  $("#sd-copy", dlg).onclick = (e) => { const b = e.target.closest("[data-copy]"); if (b) copySend(b); };
  $("#sd-date", dlg).oninput = markSendDay;
  dlg.querySelectorAll("[data-day]").forEach((b) => (b.onclick = () => { $("#sd-date", dlg).value = shiftDay(todayIso(), Number(b.dataset.day)); markSendDay(); }));
  dlg.oncancel = (e) => { if (SEND.busy) e.preventDefault(); };
  markSendDay();
  renderSend();
  dlg.showModal();
  ($("#sd-build", dlg).hidden ? $("[data-copy]", dlg) : $("#sd-build", dlg)).focus();
}

function markSendDay() {
  const dlg = $("#send-dlg");
  const v = $("#sd-date", dlg).value;
  dlg.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("aria-pressed", String(v === shiftDay(todayIso(), Number(b.dataset.day)))));
}

// A PDF's state, for the row and the warnings: which pill, and whether a build would change it.
function sendPdf(kind) {
  const { pdfs, letter } = SEND.info;
  const x = pdfs[kind];
  if (x.exists && x.stale) return { cls: "warn", label: "Out of date", build: true };
  if (x.exists) return { cls: "good", label: "Current", build: false };
  if (kind === "letter" && !letter) return { cls: "plain", label: "No letter written", build: false };
  return { cls: "bad", label: "Missing", build: true };
}

// Draws the parts a rebuild can change. The date and note stay as typed.
function renderSend() {
  const { info, warnings, busy } = SEND;
  const dlg = $("#send-dlg");
  const row = (kind, label) => {
    const x = info.pdfs[kind], st = sendPdf(kind), fit = info.fit[kind];
    return `<div class="send-row"><span class="send-name">${label}</span><span class="pill ${st.cls}">${st.label}</span>
      ${x.exists && fit ? `<span class="faint">${esc(describeFill(fit))}</span>` : ""}<span class="grow"></span>
      ${x.exists ? `<a href="/files/apps/${enc(info.name)}/${enc(x.file)}?v=${Date.now()}" target="_blank" rel="noopener">Open ${label.toLowerCase()} ↗</a>` : ""}</div>`;
  };
  const resume = sendPdf("resume"), letter = sendPdf("letter");
  const over = info.pdfs.resume.exists && info.fit.resume?.pages > 1 ? info.fit.resume : null;
  const notes = [
    !info.pdfs.resume.exists && `Build the resume PDF first. Mark sent needs one.`,
    over && `The resume runs to ${over.pages} pages${over.spill_lines ? `. Cut about ${plural(over.spill_lines, "line")} to fit one` : ""}.`,
    (resume.label === "Out of date" || letter.label === "Out of date") && `The PDFs do not match your latest edits. Rebuild them, or mark it sent anyway if these are the files you sent.`,
    letter.label === "Missing" && `You wrote a letter, but it has no PDF yet. Marking it sent now leaves the letter out of the frozen files.`,
    info.error && `This application does not build: ${esc(info.error)}`,
    ...warnings.filter((w) => !/^RESUME IS/.test(w)).map(esc),  // the page count is said above
  ].filter(Boolean);
  $("#sd-pdfs", dlg).innerHTML = `${row("resume", "Resume")}${row("letter", "Letter")}
    ${notes.map((n) => `<div class="hint warn">${n}</div>`).join("")}`;
  const build = $("#sd-build", dlg);
  build.hidden = !resume.build && !letter.build && !busy;
  build.disabled = busy;
  build.className = info.pdfs.resume.exists ? "" : "primary";
  if (busy) build.innerHTML = `<span class="spinner"></span>Building…`;
  else build.textContent = info.pdfs.resume.exists ? "Rebuild" : "Build PDFs";
  $("#sd-mark", dlg).disabled = busy || !info.pdfs.resume.exists;
  $("#sd-cancel", dlg).disabled = busy;
  const copy = (key, label, sub) => `<div class="send-row"><span class="send-name">${esc(label)}${sub ? ` <span class="faint">${esc(sub)}</span>` : ""}</span><span class="grow"></span>
    <span class="send-copied" role="status"></span>
    <button type="button" class="small" data-copy="${esc(key)}" aria-label="Copy ${esc(label)}${sub ? `, ${esc(sub)}` : ""}">Copy</button></div>`;
  $("#sd-copy", dlg).innerHTML = [
    info.letter ? copy("letter", "Cover letter") : "",
    ...info.roles.map((r, i) => copy(`role-${i}`, `${r.title}, ${r.company}`, [r.game, r.dates].filter(Boolean).join(", "))),
    !info.roles.length && !info.error ? `<div class="muted" style="font-size:13px">No bullets selected yet.</div>` : "",
    copy("contact", "Contact details"),
  ].join("");
}

async function rebuildSend() {
  const name = SEND.info.name, dlg = $("#send-dlg");
  $("#sd-build-err", dlg).textContent = $("#sd-built", dlg).textContent = "";
  SEND.busy = true;
  renderSend();
  try {
    const r = await api("POST", `/api/apps/${enc(name)}/finalize`);
    const info = await api("GET", `/api/apps/${enc(name)}/send-text`);
    if (S.app?.name === name) {
      S.app.pdfs = r.pdfs;
      renderPdfState();
    } else {
      refreshHome().catch(() => {});  // the board's PDF pill, behind this dialog
    }
    if (!dlg.open) return;
    Object.assign(SEND, { info, warnings: r.warnings, busy: false });
    renderSend();
    $("#sd-built", dlg).textContent = "PDFs built";
    ($("#sd-build", dlg).hidden ? $("[data-copy]", dlg) : $("#sd-build", dlg)).focus();
  } catch (e) {
    SEND.busy = false;
    renderSend();
    $("#sd-build-err", dlg).textContent = e.message;
    $("#sd-build", dlg).focus();
  }
}

function sendTextFor(key) {
  const { info } = SEND;
  if (key === "letter") return info.letter;
  if (key === "contact") return info.contact;
  return info.roles[Number(key.slice("role-".length))].text;
}

async function copySend(btn) {
  const dlg = $("#send-dlg"), text = sendTextFor(btn.dataset.copy);
  const box = $("#sd-manual-box", dlg), said = btn.previousElementSibling;
  try {
    await navigator.clipboard.writeText(text);
    box.hidden = true;
    said.textContent = "Copied";
    setTimeout(() => { if (said.textContent === "Copied") said.textContent = ""; }, 2000);
  } catch {
    // No clipboard access: leave the text selected so Ctrl+C takes it.
    $("#sd-manual-for", dlg).textContent = `This browser blocked copying. ${btn.getAttribute("aria-label")} from here with Ctrl+C.`;
    box.hidden = false;
    const area = $("#sd-manual", dlg);
    area.value = text;
    area.focus();
    area.select();
  }
}

async function markSent() {
  const dlg = $("#send-dlg"), err = $("#sd-err", dlg);
  const { name, studio } = SEND.info;
  const date = $("#sd-date", dlg).value.trim(), note = $("#sd-note", dlg).value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { err.textContent = "Pick the day you sent it."; return $("#sd-date", dlg).focus(); }
  err.textContent = "";
  SEND.busy = true;
  renderSend();
  let r;
  try {
    r = await api("POST", `/api/apps/${enc(name)}/events`, { event: { stage: "applied", date, note } });
  } catch (e) {
    SEND.busy = false;
    renderSend();
    err.textContent = e.message;
    return $("#sd-mark", dlg).focus();
  }
  SEND.busy = false;
  dlg.close();
  $("#hist-dlg")?.close();  // a modal over the page would keep the Undo in the toast out of reach
  try {
    await reloadAfterSend(name);
  } catch (e) {
    toast(esc(e.message), true, 8000);
  }
  toast(`Marked ${esc(studio || name)} sent on ${esc(fmtShort(r.submitted.date))}. The PDFs are frozen. <a href="#" id="undo">Undo</a>`, false, 8000);
  $("#undo").onclick = (e) => { e.preventDefault(); undo(name, r); };
}

// ----- menus -----

// A button that opens a short menu. The menu is a popover, so it sits in the top layer above
// a modal and is never clipped. Items: {label, act, arg, hint, danger} run an action through
// the surrounding click handler; {label, href, tab} go somewhere; "-" is a divider.
let menuSeq = 0;
function menu(label, items, { cls = "", aria = "", end = false } = {}) {
  const id = `menu-${++menuSeq}`;
  const body = items.map((it) => it === "-" ? `<hr>`
    : it.href ? `<a role="menuitem" href="${it.href}"${it.tab ? ` target="_blank" rel="noopener"` : ""}>${esc(it.label)}${it.tab ? `<span class="faint" aria-label="(new tab)">↗</span>` : ""}</a>`
    : `<button type="button" role="menuitem" data-act="${it.act}"${it.arg != null ? ` data-arg="${esc(it.arg)}"` : ""}${it.danger ? ` class="danger"` : ""}>${esc(it.label)}${it.hint ? `<span class="faint">${esc(it.hint)}</span>` : ""}</button>`).join("");
  return `<button type="button" class="menu-btn ${cls}" popovertarget="${id}" aria-haspopup="menu" aria-expanded="false"${aria ? ` aria-label="${esc(aria)}"` : ""}>${label}</button>
    <div popover id="${id}" class="menu${end ? " menu-end" : ""}" role="menu">${body}</div>`;
}

const menuButton = (m) => document.querySelector(`[popovertarget="${m.id}"]`);
document.addEventListener("beforetoggle", (e) => {
  const m = e.target;
  if (!m.classList?.contains("menu") || e.newState !== "open") return;
  const r = menuButton(m).getBoundingClientRect();
  m.style.top = `${r.bottom + 4}px`;
  if (m.classList.contains("menu-end")) Object.assign(m.style, { right: `${innerWidth - r.right}px`, left: "auto" });
  else Object.assign(m.style, { left: `${r.left}px`, right: "auto" });
}, true);
document.addEventListener("toggle", (e) => {
  const m = e.target;
  if (!m.classList?.contains("menu")) return;
  const btn = menuButton(m);
  btn?.setAttribute("aria-expanded", String(e.newState === "open"));
  if (e.newState !== "open") return;
  const r = btn.getBoundingClientRect();
  if (r.bottom + 4 + m.offsetHeight > innerHeight - 8) m.style.top = `${Math.max(8, r.top - m.offsetHeight - 4)}px`;
  m.querySelector("[role=menuitem]")?.focus();
}, true);
document.addEventListener("keydown", (e) => {
  const m = e.target.closest?.(".menu");
  if (!m || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const items = [...m.querySelectorAll("[role=menuitem]")];
  const i = items.indexOf(document.activeElement);
  const n = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
  items[n].focus();
});
// Picking an item closes its menu (after the click has reached the handlers that act on it).
document.addEventListener("click", (e) => {
  const it = e.target.closest?.(".menu [role=menuitem]");
  if (it) it.closest(".menu").hidePopover();
});

// ----- history (a modal over the board) -----

function openHistory(name) {
  if (!findApp(name)) return;
  T.hist = name;
  renderHistory();
  const dlg = $("#hist-dlg");
  if (!dlg.open) dlg.showModal();
}

// The job's link, deadline and the rest, from job.yaml. Edit them on the Listing tab.
function jobDetail(a) {
  const j = a.job || {};
  const rows = [];
  if (j.url) rows.push(["Link", safeUrl(j.url) ? `<a href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener noreferrer">${esc(j.url)}</a>` : esc(j.url)]);
  if (j.deadline) rows.push(["Deadline", esc(fmtDay(j.deadline))]);
  for (const [k, label] of [["location", "Location"], ["salary", "Salary"], ["source", "Source"], ["referral", "Referral"], ["contact", "Contact"]]) {
    if (j[k]) rows.push([label, esc(j[k])]);
  }
  return rows.length ? `<dl class="h-dl job-dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>` : "";
}

function eventDetail(e) {
  const rows = [];
  if (e.scheduled) rows.push(["Scheduled", esc(fmtWhen(e.scheduled))]);
  const how = [e.format && FORMATS.find(([v]) => v === e.format)?.[1], e.length && `${e.length} min`].filter(Boolean);
  if (how.length) rows.push(["Format", esc(how.join(", "))]);
  if (e.interviewers?.length) rows.push(["With", e.interviewers.map((p) => esc(p.name || "") + (p.role ? ` <span class="faint">(${esc(p.role)})</span>` : "")).join(", ")]);
  if (e.prep) rows.push(["Prep", esc(e.prep)]);
  if (e.debrief) rows.push(["Debrief", esc(e.debrief)]);
  else if (e.no_debrief) rows.push(["Debrief", `<span class="faint">None</span>`]);
  return (rows.length ? `<dl class="h-dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>` : "")
    + (e.note ? `<p class="h-text">${esc(e.note)}</p>` : "");
}

// The stages ahead of where a card is (any, once it is closed), then the closed ones. Going
// back is a correction, made by editing or deleting the entry instead.
function moveItems(t) {
  const items = [];
  const order = ["applied", "screen", "interviewing", "offer"];
  const at = order.indexOf(t.column);
  for (const [stage, col] of [["screen", "screen"], ["interview", "interviewing"], ["offer", "offer"]]) {
    if (at >= 0 && (order.indexOf(col) < at || (col === t.column && col !== "interviewing"))) continue;
    const label = stage === "interview" ? (t.column === "interviewing" ? `Add round ${t.round + 1}` : "Interviewing") : COL_LABEL[col];
    items.push({ label, act: "stage", arg: stage });
  }
  if (items.length) items.push("-");
  for (const c of CLOSED) if (c !== t.column) items.push({ label: COL_LABEL[c], act: "stage", arg: c });
  return items;
}

function renderHistory() {
  const a = findApp(T.hist);
  const dlg = $("#hist-dlg");
  if (!a) return dlg.close();
  const t = a.track, sub = a.submitted, saved = t.column === "saved", drafting = t.column === "drafting" || saved;
  const sent = (k) => `/files/apps/${enc(a.name)}/submitted/${enc(sub[k])}`;
  const row = (day, cls, title, body, tools = "") => `<li class="h-ev ${cls}"><span class="h-date">${esc(fmtShort(day))}</span>
    <div class="h-body"><div class="h-line"><b>${title}</b>${tools}</div>${body}</div></li>`;
  const rows = [];
  if (t.applied) rows.push(row(t.applied, "st-applied", "Applied", `<p class="h-text faint">The day it was marked submitted.</p>`));
  for (const e of t.events) {
    rows.push(row(e.date, `st-${EV_COLUMN[e.stage] || "note"}`, `${EV_LABEL[e.stage]}${e.round ? ` · round ${e.round}` : ""}`, eventDetail(e),
      `${e.stage === "interview" && eventStarted(e) ? `<button class="small h-how" data-how="${e.i}" aria-label="How it went: ${EV_LABEL[e.stage]} on ${esc(fmtDay(e.date))}">${e.debrief ? "Edit debrief" : "How it went"}</button>` : ""}
       <button class="ghost small h-edit" data-edit="${e.i}" aria-label="Edit ${EV_LABEL[e.stage]} on ${esc(fmtDay(e.date))}">Edit</button>
       ${e.scheduled ? `<a class="h-cal" href="/api/apps/${enc(a.name)}/events/${e.i}/calendar" download aria-label="Add ${EV_LABEL[e.stage]} on ${esc(fmtDay(e.date))} to a calendar">Calendar</a>` : ""}`));
  }
  const status = saved ? "Saved lead, not started" : drafting ? "Still drafting"
    : CLOSED.includes(t.column) ? `${COL_LABEL[t.column]} ${t.closed_from === "applied" ? "with no reply" : `after ${COL_LABEL[t.closed_from].toLowerCase()}`}${t.days_to_close != null ? `, ${dayCount(t.days_to_close)} after applying` : ""}`
    : `${COL_LABEL[t.column]} since ${fmtShort(t.since)}${t.next ? ` · Next: ${fmtWhen(t.next)}` : ""}`;
  const open = [{ label: "Resume", href: `#/app/${enc(a.name)}/resume` }, { label: "Cover letter", href: `#/app/${enc(a.name)}/letter` },
    { label: "Listing", href: `#/app/${enc(a.name)}/listing` },
    ...(sub?.resume || sub?.letter ? ["-"] : []),
    ...(sub?.resume ? [{ label: "Resume as sent", href: sent("resume"), tab: true }] : []),
    ...(sub?.letter ? [{ label: "Letter as sent", href: sent("letter"), tab: true }] : [])];
  dlg.innerHTML = `<div class="dr-hd">
      <div class="grow"><h2 id="hist-h">${esc(appLabel(a))}</h2><div class="muted">${esc(a.role)}</div>
        <div class="h-status st-${t.column}">${esc(status)}</div></div>
      ${menu("⋯", [{ label: "Delete application…", act: "delete", danger: true }], { cls: "ghost icon", aria: "More actions", end: true })}
      <button class="ghost icon" id="h-close" aria-label="Close">✕</button></div>
    <div class="dr-bd stack">
      ${t.quiet ? `<div class="hint warn">Nothing logged or scheduled for ${dayCount(t.days_quiet)}. <button class="small" data-act="stage" data-arg="ghosted">Mark ghosted</button></div>` : ""}
      <div class="row wrap h-acts">
        ${saved ? `<button class="primary" data-start="${esc(a.name)}">Start drafting</button>`
          : drafting ? `<button class="primary" data-act="stage" data-arg="applied">Move to Applied</button>` : menu("Move to", moveItems(t), { cls: "primary" })}
        ${drafting ? "" : `<button data-act="note">Add note</button>`}
        ${t.applied && !CLOSED.includes(t.column) && !t.follow_up ? `<button data-act="follow">Set follow-up</button>` : ""}
        ${menu("Open", open)}
      </div>
      ${t.follow_up ? `<div class="hint h-follow"><span>Follow up ${esc(fmtShort(t.follow_up.date))}${t.follow_up.note ? `: ${esc(t.follow_up.note)}` : ""}</span> <button class="small" data-act="follow">Change</button></div>` : ""}
      ${jobDetail(a)}
      ${rows.length ? `<ol class="hist">${rows.join("")}</ol>` : `<div class="muted">Nothing logged yet. Move it to Applied when you send it.</div>`}
    </div>`;
  $("#h-close", dlg).onclick = () => dlg.close();
  dlg.onclick = (e) => {
    if (e.target === dlg) return dlg.close();  // the backdrop
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.start) return startDrafting(a);
    if (b.dataset.act === "stage") return openEvent(a, { stage: b.dataset.arg });
    if (b.dataset.act === "note") return openEvent(a, { stage: "note" });
    if (b.dataset.act === "follow") return openFollowUp(a);
    if (b.dataset.how) return openDebrief(a, t.events.find((x) => String(x.i) === b.dataset.how));
    if (b.dataset.act === "delete") return deleteApp(a);  // closes this once the board reloads without it
    if (b.dataset.edit) {
      const ev = t.events.find((x) => String(x.i) === b.dataset.edit);
      return openEvent(a, { index: ev.i, event: ev });
    }
  };
}

// ----- list -----

// Each sortable column: key -> [heading, first direction, sort value]. Rows with no value
// (never applied) always sort last.
const SORTS = {
  studio: ["Studio", "asc", (a) => `${appLabel(a)} ${a.role}`.toLowerCase()],
  stage: ["Stage", "asc", (a) => stages().findIndex(([k]) => k === a.track.column)],
  applied: ["Applied", "desc", (a) => a.track.applied || null],
  updated: ["Last update", "desc", (a) => a.updated],
};

function sortedList(apps) {
  const [, , value] = SORTS[T.sort] || SORTS.updated;
  const sign = T.dir === "asc" ? 1 : -1;
  return [...apps].sort((a, b) => {
    const x = value(a), y = value(b);
    if (x == null || y == null) return (x == null) - (y == null);
    return (x < y ? -sign : x > y ? sign : 0) || `${appLabel(a)} ${a.role}`.localeCompare(`${appLabel(b)} ${b.role}`);
  });
}

function renderList() {
  if (!SORTS[T.sort]) T.sort = "updated";
  const shown = sortedList(visible());
  if (!T.apps.length) {
    $("#tbody").innerHTML = `<section class="card"><div class="empty">No applications yet.</div></section>`;
    return;
  }
  if (!shown.length) {
    $("#tbody").innerHTML = noMatches();
    $("[data-clear]").onclick = clearFilters;
    return;
  }
  const head = Object.entries(SORTS).map(([k, [label]]) => {
    const on = T.sort === k;
    return `<th scope="col" aria-sort="${on ? (T.dir === "asc" ? "ascending" : "descending") : "none"}">
      <button type="button" class="sort" data-sort="${k}">${label}<span aria-hidden="true">${on ? (T.dir === "asc" ? " ▲" : " ▼") : ""}</span></button></th>`;
  }).join("");
  const rows = shown.map((a) => `
    <tr>
      <td class="l-app"><a href="#/app/${enc(a.name)}"><strong>${esc(appLabel(a))}</strong><span class="sub">${esc(a.role)}</span></a></td>
      <td><span class="pill ${CLOSED.includes(a.track.column) ? "plain" : ""}">${COL_LABEL[a.track.column]}</span></td>
      <td>${a.track.applied ? esc(fmtShort(a.track.applied)) : `<span class="faint">Not sent</span>`}</td>
      <td title="${esc(new Date(a.updated * 1000).toLocaleString())}">${ago(a.updated)}</td>
      <td class="pills"><span class="pill plain">${esc(a.template)}</span>${a.submitted
        ? `<span class="pill good" title="PDFs frozen as sent">Submitted ${esc(fmtDay(a.submitted.date))}</span>` : pdfPill(a.pdfs)}</td>
      <td><button class="ghost danger" data-delete="${esc(a.name)}" aria-label="Delete ${esc(appLabel(a))}, ${esc(a.role)}">Delete</button></td>
    </tr>`).join("");
  const focused = document.activeElement?.dataset?.sort;
  $("#tbody").innerHTML = `<section class="card list-wrap"><table class="app-table">
    <thead><tr>${head}<th scope="col">Files</th><th scope="col"><span class="sr">Actions</span></th></tr></thead>
    <tbody>${rows}</tbody></table></section>`;
  if (focused) $(`[data-sort="${focused}"]`)?.focus();  // the click redrew the header it was on
  $("#tbody").onclick = (e) => {
    const sort = e.target.closest("[data-sort]");
    if (sort) {
      const k = sort.dataset.sort;
      T.dir = T.sort === k ? (T.dir === "asc" ? "desc" : "asc") : SORTS[k][1];
      T.sort = k;
      pref.set("sort", T.sort);
      pref.set("dir", T.dir);
      return redraw();
    }
    const b = e.target.closest("[data-delete]");
    if (b) deleteApp(findApp(b.dataset.delete));
  };
}

// ----- timeline -----

function stops(a) {
  // [date, column] each time the application changed stage, starting with Applied.
  const out = [[a.track.applied, "applied"]];
  for (const e of a.track.events) {
    const col = EV_COLUMN[e.stage];
    if (col && col !== out[out.length - 1][1]) out.push([e.date, col]);
  }
  return out;
}

function renderTimeline() {
  const sent = T.apps.filter((a) => a.track.applied).sort((a, b) => a.track.applied.localeCompare(b.track.applied));
  if (!sent.length) {
    $("#tbody").innerHTML = `<div class="card empty">The timeline starts once you move an application to Applied.</div>`;
    return;
  }
  const today = todayIso();
  const dates = sent.flatMap((a) => [a.track.applied, ...a.track.events.flatMap((e) => [e.date, e.scheduled && e.scheduled.slice(0, 10)])]).filter(Boolean);
  const start = shiftDay(dates.reduce((m, d) => (d < m ? d : m)), -3);
  const end = shiftDay([today, ...dates].reduce((m, d) => (d > m ? d : m)), 4);
  const span = Math.max(daysBetween(start, end), 1);
  const x = (iso) => `${(daysBetween(start, iso) / span) * 100}%`;
  const ticks = [];
  for (let d = toDate(start); d <= toDate(end); d.setDate(d.getDate() + 1)) {
    if (d.getDate() === 1 || ticks.length === 0) ticks.push(isoDay(d));
  }
  const monthLbl = (iso) => toDate(iso).toLocaleDateString(undefined, { month: "short", ...(toDate(iso).getMonth() === 0 ? { year: "numeric" } : {}) });
  const rows = sent.map((a) => {
    const st = stops(a), t = a.track, closed = CLOSED.includes(t.column);
    const segs = st.map(([d, col], i) => {
      if (CLOSED.includes(col)) return "";
      const to = st[i + 1]?.[0] ?? (closed ? d : today);
      return `<i class="tl-seg st-${col}" style="left:${x(d)};width:calc(${x(to)} - ${x(d)})" title="${COL_LABEL[col]}: ${esc(fmtShort(d))} to ${esc(fmtShort(to))}"></i>`;
    }).join("");
    const end = closed ? `<i class="end st-${t.column}" style="left:${x(t.since)}" title="${COL_LABEL[t.column]} ${esc(fmtShort(t.since))}"></i>` : "";
    const dots = t.events.map((e) => `<i class="dot st-${EV_COLUMN[e.stage] || "note"}" style="left:${x(e.date)}" title="${EV_LABEL[e.stage]}${e.round ? ` round ${e.round}` : ""}, ${esc(fmtShort(e.date))}${e.note ? `: ${esc(e.note)}` : ""}"></i>`).join("");
    const sched = t.events.filter((e) => e.scheduled).map((e) => `<i class="sched" style="left:${x(e.scheduled.slice(0, 10))}" title="${EV_LABEL[e.stage]}${e.round ? ` round ${e.round}` : ""} scheduled ${esc(fmtWhen(e.scheduled))}"></i>`).join("");
    return `<div class="tl-row">
      <button class="tl-lbl" data-hist="${esc(a.name)}"><strong>${esc(appLabel(a))}</strong><span>${esc(a.role)}</span></button>
      <div class="tl-track">${segs}${end}${dots}${sched}</div></div>`;
  }).join("");
  $("#tbody").innerHTML = `<section class="card timeline">
    <div class="tl-row tl-head"><div></div><div class="tl-track">${ticks.map((d) => `<span class="tick" style="left:${x(d)}">${esc(monthLbl(d))}</span>`).join("")}
      <span class="today" style="left:${x(today)}">Today</span></div></div>
    <div class="tl-rows" style="--today:${x(today)}">${rows}</div>
    <div class="legend">${["applied", "screen", "interviewing", "offer"].map((c) => `<span><i class="tl-seg st-${c}"></i>${COL_LABEL[c]}</span>`).join("")}
      ${CLOSED.map((c) => `<span><i class="end st-${c}"></i>${COL_LABEL[c]}</span>`).join("")}<span><i class="sched"></i>Scheduled</span></div>
  </section>`;
  $("#tbody").onclick = (e) => { const b = e.target.closest("[data-hist]"); if (b) openHistory(b.dataset.hist); };
}

// ----- stats -----

function renderStats() {
  const s = T.stats;
  if (!s || !s.sent) {
    $("#tbody").innerHTML = `<div class="card empty">Stats start once you move an application to Applied.</div>`;
    return;
  }
  const pct = (n, d) => (d ? `${Math.round((n / d) * 100)}%` : "–");
  const days = (n) => (n == null ? "–" : `${Math.round(n * 10) / 10} d`);
  const metric = (label, value, sub = "") => `<div class="metric big"><span>${label}</span><b>${value}</b>${sub ? `<small>${sub}</small>` : ""}</div>`;
  const maxWeek = Math.max(1, ...s.weeks.map((w) => w.count));
  const formats = Object.entries(s.formats).sort((a, b) => b[1] - a[1]);
  const fmtName = (f) => FORMATS.find(([v]) => v === f)?.[1] || "Format not set";
  $("#tbody").innerHTML = `<div class="stats">
    <div class="metrics">
      ${metric("Sent", s.sent)}
      ${metric("Heard back", pct(s.replied, s.sent), `${s.replied} of ${s.sent}`)}
      ${metric("Median days to first reply", days(s.median_days_to_reply))}
      ${metric("Median days to rejection", days(s.median_days_to_close), "Ghosted left out")}
      ${metric("Active", s.active, s.quiet ? `${s.quiet} quiet for 30+ days` : "")}
      ${metric("Interviews", s.interviews)}
    </div>
    <div class="stats-grid">
      <section class="card"><div class="hd"><h2>How far applications got</h2></div><div class="bd">
        ${s.funnel.map((f) => `<div class="bar-row"><span>${COL_LABEL[f.stage]}</span>
          <div class="bar"><i class="st-${f.stage}" style="width:${(f.count / s.sent) * 100}%"></i></div>
          <b>${f.count}</b><span class="faint">${pct(f.count, s.sent)}</span></div>`).join("")}
      </div></section>
      <section class="card"><div class="hd"><h2>Where it ended</h2></div><div class="bd">
        <table class="tbl"><thead><tr><th>Last stage reached</th><th>Rejected</th><th>Median days</th><th>Ghosted</th></tr></thead><tbody>
        ${s.rejections_by_stage.map((r) => `<tr><td>${r.stage === "applied" ? "Applied (no reply)" : COL_LABEL[r.stage]}</td><td>${r.rejected}</td><td>${days(r.median_days)}</td><td>${r.ghosted}</td></tr>`).join("")}
        </tbody></table>
        <div class="faint" style="font-size:12px;margin-top:8px">Withdrew: ${s.outcomes.withdrew} · Offers: ${s.outcomes.offer}</div>
      </div></section>
      <section class="card"><div class="hd"><h2>Applications per week</h2></div><div class="bd">
        <div class="weeks">${s.weeks.map((w) => `<div class="wk" title="Week of ${esc(fmtShort(w.week))}: ${plural(w.count, "application")}">
          <i style="height:${(w.count / maxWeek) * 100}%"></i><span>${esc(fmtShort(w.week))}</span></div>`).join("")}</div>
      </div></section>
      <section class="card"><div class="hd"><h2>Interviews by format</h2></div><div class="bd">
        ${formats.length ? formats.map(([f, n]) => `<div class="bar-row"><span>${esc(fmtName(f))}</span>
          <div class="bar"><i class="st-interviewing" style="width:${(n / s.interviews) * 100}%"></i></div><b>${n}</b><span></span></div>`).join("")
          : `<div class="muted">No interviews logged yet.</div>`}
      </div></section>
      <section class="card"><div class="hd"><h2>Coming up</h2>${s.upcoming.length ? `<a href="/api/calendar" download>Add to calendar</a>` : ""}</div><div class="bd">
        ${s.upcoming.length ? `<ul class="upcoming">${s.upcoming.map((u) => `<li><button class="ghost" data-hist="${esc(u.app)}">
          <strong>${esc(u.studio || u.app)}</strong><span>${EV_LABEL[u.stage]}${u.round ? ` round ${u.round}` : ""}</span><span class="grow"></span><span>${esc(fmtWhen(u.scheduled))}</span></button></li>`).join("")}</ul>`
          : `<div class="muted">Nothing scheduled.</div>`}
      </div></section>
    </div></div>`;
  $("#tbody").onclick = (e) => { const b = e.target.closest("[data-hist]"); if (b) openHistory(b.dataset.hist); };
}
