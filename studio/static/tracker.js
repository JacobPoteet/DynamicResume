"use strict";
// The home page: every application on a board by stage, plus List, Timeline and Stats views.
// Stage changes are dated events in each application's tracking.yaml (see studio/tracking.py);
// the Applied date is the day it was marked submitted. Uses the helpers in app.js.

const COLUMNS = [["drafting", "Drafting"], ["applied", "Applied"], ["screen", "Screen"], ["interviewing", "Interviewing"], ["offer", "Offer"]];
const TRAYS = [["rejected", "Rejected"], ["ghosted", "Ghosted"], ["withdrew", "Withdrew"]];
const COL_LABEL = Object.fromEntries([...COLUMNS, ...TRAYS]);
const EV_LABEL = { applied: "Applied", screen: "Screen", interview: "Interview", offer: "Offer", rejected: "Rejected", ghosted: "Ghosted", withdrew: "Withdrew", note: "Note" };
const EV_COLUMN = { applied: "applied", screen: "screen", interview: "interviewing", offer: "offer", rejected: "rejected", ghosted: "ghosted", withdrew: "withdrew" };
const COLUMN_EV = Object.fromEntries(Object.entries(EV_COLUMN).map(([k, v]) => [v, k]));
const CLOSED = ["rejected", "ghosted", "withdrew"];
const FORMATS = [["", "Not set"], ["phone", "Phone"], ["video", "Video"], ["onsite", "Onsite"], ["take-home", "Take-home"]];
const MODES = [["board", "Board"], ["list", "List"], ["timeline", "Timeline"], ["stats", "Stats"]];

const T = { apps: [], stats: null, mode: "board", tray: pref.get("tray", ""), hist: null };

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
    <div id="tbody"><div class="empty"><span class="spinner"></span></div></div>
  </div>
  <dialog id="new-dlg" class="dlg" aria-labelledby="new-h">${newAppForm()}</dialog>
  <dialog id="ev-dlg" class="dlg"></dialog>
  <dialog id="hist-dlg" class="hist-dlg" aria-labelledby="hist-h"></dialog>`);
  $("#new-app").onclick = () => $("#new-dlg").showModal();
  $("#na-create").onclick = () => createApp(false);
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
      <label class="field">Job listing<textarea id="na-listing" rows="12" placeholder="Paste the full listing"></textarea></label>
      <div class="muted" style="font-size:12px">${S.init.claude
        ? "Drafting runs Claude Code in this repo with read-only access (a minute or two). It picks and orders bullets, writes a cover letter, and lists what the master cannot back up. Without drafting, every priority 1 bullet starts selected."
        : "Starts with every priority 1 bullet selected. Install Claude Code to draft automatically."}</div>
      <div id="na-err" class="muted"></div>
      <div class="row dlg-ft">
        <button id="na-cancel" type="button">Cancel</button>
        <span class="grow"></span>
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
  ({ board: renderBoard, list: renderList, timeline: renderTimeline, stats: renderStats })[T.mode]();
  if (T.hist && $("#hist-dlg").open) renderHistory();
  api("GET", "/api/versions").then((v) => (S.versions = { ...S.versions, ...v })).catch(() => {});
}

const appLabel = (a) => a.studio || a.name;
const findApp = (name) => T.apps.find((a) => a.name === name);

// ----- board -----

function sorted(apps, col) {
  // Drafts by last edit; everything else by the latest thing that happened to it.
  if (col === "drafting") return [...apps].sort((a, b) => b.updated - a.updated);
  return [...apps].sort((a, b) => (b.track.updated || "").localeCompare(a.track.updated || "") || b.updated - a.updated);
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
    ${next ? `<button class="metric next" data-hist="${esc(next.app)}"><span>Next up</span><b>${esc(next.studio || next.app)} · ${esc(fmtWhen(next.scheduled))}</b></button>` : ""}
  </div>`;
}

function cardMeta(a) {
  const t = a.track;
  const bits = [];
  if (t.column === "drafting") {
    bits.push(pdfPill(a.pdfs));
  } else if (CLOSED.includes(t.column)) {
    const from = t.closed_from === "applied" ? "no reply" : `after ${COL_LABEL[t.closed_from].toLowerCase()}`;
    bits.push(`<span class="faint">${esc(fmtShort(t.since))} · ${from}${t.days_to_close != null ? ` · ${dayCount(t.days_to_close)}` : ""}</span>`);
  } else {
    const what = t.column === "applied" ? `Sent ${fmtShort(t.applied)}` : `Since ${fmtShort(t.since)}`;
    bits.push(`<span class="faint">${esc(what)} · ${daysBetween(t.since, todayIso())} d</span>`);
    if (t.column === "interviewing" && t.round) bits.push(`<span class="pill plain">Round ${t.round}</span>`);
    if (t.next) bits.push(`<span class="pill" title="Scheduled">${esc(fmtWhen(t.next))}</span>`);
    if (t.quiet) bits.push(`<span class="pill warn" title="Nothing logged and nothing scheduled for ${dayCount(t.days_quiet)}">Quiet ${t.days_quiet} d</span><button class="small ghosted" data-ghost="${esc(a.name)}">Ghosted?</button>`);
  }
  return bits.join("");
}

function card(a) {
  return `<article class="tcard${a.track.quiet ? " quiet" : ""}" draggable="true" tabindex="0" data-app="${esc(a.name)}"
      aria-label="${esc(appLabel(a))}, ${esc(a.role)}, ${COL_LABEL[a.track.column]}">
    <div class="tc-top"><strong>${esc(appLabel(a))}</strong>
      <button class="ghost small tc-move" data-move="${esc(a.name)}" aria-label="Move ${esc(appLabel(a))}">Move</button></div>
    <div class="tc-role">${esc(a.role)}</div>
    <div class="tc-meta">${cardMeta(a)}</div>
  </article>`;
}

function renderBoard() {
  const by = Object.fromEntries([...COLUMNS, ...TRAYS].map(([k]) => [k, []]));
  for (const a of T.apps) by[a.track.column].push(a);
  if (!T.apps.length) {
    $("#tbody").innerHTML = `<div class="card empty">Paste a job listing to start your first application.
      <div style="margin-top:12px"><button class="primary" data-new>New application</button></div></div>`;
    $("[data-new]").onclick = () => $("#new-dlg").showModal();
    return;
  }
  const open = TRAYS.some(([k]) => k === T.tray) ? T.tray : "";
  $("#tbody").innerHTML = `${strip()}
    <div class="board">${COLUMNS.map(([k, l]) => `
      <section class="col" ${k === "drafting" ? "" : `data-drop="${k}"`} aria-label="${l}, ${by[k].length}">
        <h2>${l}<span>${by[k].length}</span></h2>
        <div class="cards">${sorted(by[k], k).map(card).join("") || `<div class="col-empty">${k === "drafting" ? "Nothing in progress" : "Drop a card here"}</div>`}</div>
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
    if (t.closest("[data-ghost]")) return openEvent(findApp(t.closest("[data-ghost]").dataset.ghost), { stage: "ghosted" });
    if (t.closest("[data-move]")) return openEvent(findApp(t.closest("[data-move]").dataset.move));
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

function dropOn(a, col) {
  const from = a.track.column;
  if (from === "drafting" && col !== "applied") return toast("Move it to Applied first. That marks it submitted and freezes the PDFs you sent.", true, 6000);
  if (col === from && col !== "interviewing") return;
  openEvent(a, { stage: COLUMN_EV[col] });
}

// ----- move / edit dialog -----

// opts: {stage} for a new event, or {index, event} to edit one already logged.
function openEvent(a, opts = {}) {
  if (!a) return;
  const t = a.track;
  const editing = opts.index != null;
  const drafting = t.column === "drafting";
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
        <div class="field"><span id="ev-when">${s === "ghosted" ? "When did you call it?" : s === "applied" ? "When did you send it?" : s === "note" ? "Date" : "When did this happen?"}</span>
          <div class="row" role="group" aria-labelledby="ev-when">
            <button type="button" class="small" data-day="0">Today</button>
            <button type="button" class="small" data-day="-1">Yesterday</button>
            <input type="date" id="ev-date" value="${esc(ev.date)}" aria-label="Date" required>
          </div></div>
        ${s === "applied" && drafting ? `<div class="hint">This marks it submitted: the PDFs, tailor, letter and listing are frozen as they are now.${a.pdfs?.resume?.stale ? " <b>The PDFs are older than your latest edits.</b>" : ""}</div>` : ""}
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
          <label class="field">Debrief<textarea id="ev-debrief" rows="2" placeholder="How it went, what they asked">${esc(ev.debrief || "")}</textarea></label>` : ""}
        <label class="field">Note<textarea id="ev-note" rows="2" placeholder="${s === "rejected" ? "Form email, feedback given" : "Anything worth remembering"}">${esc(ev.note || "")}</textarea></label>
        <div id="ev-err" class="ev-err" role="alert"></div>
        <div class="row dlg-ft">
          <button type="button" id="ev-cancel">Cancel</button><span class="grow"></span>
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
      Object.assign(out, { round: val("ev-round"), format: val("ev-format"), length: val("ev-length"),
        prep: val("ev-prep"), debrief: val("ev-debrief") });
      out.interviewers = [...dlg.querySelectorAll(".iv-row")].map((r) => ({ name: $(".iv-name", r).value.trim(), role: $(".iv-role", r).value.trim() }))
        .filter((p) => p.name || p.role);
    }
    return out;
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
        : `Moved ${esc(appLabel(a))} to ${COL_LABEL[EV_COLUMN[body.stage]]}${r.submitted ? ` and marked it submitted on ${esc(fmtShort(r.submitted.date))}` : ""}`;
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

const personRow = (p) => `<div class="iv-row">
  <input class="iv-name" placeholder="Name" value="${esc(p.name || "")}" aria-label="Interviewer name">
  <input class="iv-role" placeholder="Role" value="${esc(p.role || "")}" aria-label="Interviewer role">
  <button type="button" class="ghost small iv-rm" aria-label="Remove interviewer">Remove</button></div>`;

async function undo(name, r) {
  $("#toast").className = "";
  try {
    if (r.index != null) await api("DELETE", `/api/apps/${enc(name)}/events/${r.index}`);
    if (r.submitted) await api("POST", `/api/apps/${enc(name)}/unsubmit`);
    await refreshHome();
    toast(r.submitted ? "Undone. It is a draft again." : "Undone");
  } catch (e) {
    toast(esc(e.message), true);
  }
}

// ----- history (a modal over the board) -----

function openHistory(name) {
  if (!findApp(name)) return;
  T.hist = name;
  renderHistory();
  const dlg = $("#hist-dlg");
  if (!dlg.open) dlg.showModal();
}

function eventDetail(e) {
  const rows = [];
  if (e.scheduled) rows.push(["Scheduled", esc(fmtWhen(e.scheduled))]);
  const how = [e.format && FORMATS.find(([v]) => v === e.format)?.[1], e.length && `${e.length} min`].filter(Boolean);
  if (how.length) rows.push(["Format", esc(how.join(", "))]);
  if (e.interviewers?.length) rows.push(["With", e.interviewers.map((p) => esc(p.name || "") + (p.role ? ` <span class="faint">(${esc(p.role)})</span>` : "")).join(", ")]);
  if (e.prep) rows.push(["Prep", esc(e.prep)]);
  if (e.debrief) rows.push(["Debrief", esc(e.debrief)]);
  return (rows.length ? `<dl class="h-dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>` : "")
    + (e.note ? `<p class="h-text">${esc(e.note)}</p>` : "");
}

function renderHistory() {
  const a = findApp(T.hist);
  const dlg = $("#hist-dlg");
  if (!a) return dlg.close();
  const t = a.track, sub = a.submitted;
  const sent = (k) => `/files/apps/${enc(a.name)}/submitted/${enc(sub[k])}`;
  const row = (day, cls, title, body, tools = "") => `<li class="h-ev ${cls}"><span class="h-date">${esc(fmtShort(day))}</span>
    <div class="h-body"><div class="h-line"><b>${title}</b>${tools}</div>${body}</div></li>`;
  const rows = [];
  if (t.applied) rows.push(row(t.applied, "st-applied", "Applied", `<p class="h-text faint">The day it was marked submitted.</p>`));
  for (const e of t.events) {
    const what = `${EV_LABEL[e.stage]} on ${esc(fmtDay(e.date))}`;
    rows.push(row(e.date, `st-${EV_COLUMN[e.stage] || "note"}`, `${EV_LABEL[e.stage]}${e.round ? ` · round ${e.round}` : ""}`, eventDetail(e),
      `<button class="ghost small" data-edit="${e.i}" aria-label="Edit ${what}">Edit</button><button class="ghost small danger" data-del="${e.i}" aria-label="Delete ${what}">Delete</button>`));
  }
  const status = t.column === "drafting" ? "Still drafting"
    : CLOSED.includes(t.column) ? `${COL_LABEL[t.column]} ${t.closed_from === "applied" ? "with no reply" : `after ${COL_LABEL[t.closed_from].toLowerCase()}`}${t.days_to_close != null ? `, ${dayCount(t.days_to_close)} after applying` : ""}`
    : `${COL_LABEL[t.column]} since ${fmtShort(t.since)}${t.next ? ` · Next: ${fmtWhen(t.next)}` : ""}`;
  const links = [[`#/app/${enc(a.name)}/resume`, "Open in editor", false], [`#/app/${enc(a.name)}/listing`, "Listing", false],
    ...(sub?.resume ? [[sent("resume"), "Resume as sent", true]] : []), ...(sub?.letter ? [[sent("letter"), "Letter as sent", true]] : [])];
  dlg.innerHTML = `<div class="dr-hd">
      <div class="grow"><h2 id="hist-h">${esc(appLabel(a))}</h2><div class="muted">${esc(a.role)}</div>
        <div class="h-status st-${t.column}">${esc(status)}</div></div>
      <button class="ghost" id="h-close" aria-label="Close">✕</button></div>
    <div class="dr-bd stack">
      ${t.quiet ? `<div class="hint warn">Nothing logged or scheduled for ${dayCount(t.days_quiet)}. <button class="small" data-act="ghost">Mark ghosted</button></div>` : ""}
      <div class="row wrap h-acts">
        <button class="primary" data-act="move">${t.column === "drafting" ? "Move to Applied" : "Move"}</button>
        ${t.column === "drafting" ? "" : `<button data-act="note">Add note</button>`}
        <span class="h-links">${links.map(([href, l, tab]) => `<a href="${href}"${tab ? ` target="_blank"` : ""}>${l}</a>`).join("")}</span>
      </div>
      ${rows.length ? `<ol class="hist">${rows.join("")}</ol>` : `<div class="muted">Nothing logged yet. Move it to Applied when you send it.</div>`}
    </div>
    <div class="dr-ft"><button class="ghost danger" data-act="delete">Delete application</button></div>`;
  $("#h-close", dlg).onclick = () => dlg.close();
  dlg.onclick = async (e) => {
    if (e.target === dlg) return dlg.close();  // the backdrop
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.act === "move") return openEvent(a);
    if (b.dataset.act === "note") return openEvent(a, { stage: "note" });
    if (b.dataset.act === "ghost") return openEvent(a, { stage: "ghosted" });
    if (b.dataset.act === "delete") return deleteApp(a);  // closes this once the board reloads without it
    if (b.dataset.edit) {
      const ev = t.events.find((x) => String(x.i) === b.dataset.edit);
      return openEvent(a, { index: ev.i, event: ev });
    }
    if (b.dataset.del) {
      const ev = t.events.find((x) => String(x.i) === b.dataset.del);
      if (!confirm(`Delete the ${EV_LABEL[ev.stage].toLowerCase()} on ${fmtDay(ev.date)}?`)) return;
      try {
        await api("DELETE", `/api/apps/${enc(a.name)}/events/${ev.i}`);
        await refreshHome();
        toast("Deleted");
      } catch (err) {
        toast(esc(err.message), true);
      }
    }
  };
}

// ----- list -----

function renderList() {
  const rows = T.apps.map((a) => `
    <li><a href="#/app/${enc(a.name)}">
      <strong>${esc(appLabel(a))}</strong>
      <span class="pills"><span class="pill ${CLOSED.includes(a.track.column) ? "plain" : ""}">${COL_LABEL[a.track.column]}</span><span class="pill plain">${esc(a.template)}</span>${a.submitted
        ? `<span class="pill good" title="PDFs frozen as sent">Submitted ${esc(fmtDay(a.submitted.date))}</span>` : pdfPill(a.pdfs)}</span>
      <span class="sub">${esc(a.role)} · edited ${ago(a.updated)}</span>
    </a><button class="ghost danger" data-delete="${esc(a.name)}" aria-label="Delete ${esc(appLabel(a))}, ${esc(a.role)}">Delete</button></li>`).join("");
  $("#tbody").innerHTML = `<section class="card">${rows ? `<ul class="app-list">${rows}</ul>` : `<div class="empty">No applications yet.</div>`}</section>`;
  $("#tbody").onclick = (e) => {
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
      return `<i class="seg st-${col}" style="left:${x(d)};width:calc(${x(to)} - ${x(d)})" title="${COL_LABEL[col]}: ${esc(fmtShort(d))} to ${esc(fmtShort(to))}"></i>`;
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
    <div class="legend">${["applied", "screen", "interviewing", "offer"].map((c) => `<span><i class="seg st-${c}"></i>${COL_LABEL[c]}</span>`).join("")}
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
      <section class="card"><div class="hd"><h2>Coming up</h2></div><div class="bd">
        ${s.upcoming.length ? `<ul class="upcoming">${s.upcoming.map((u) => `<li><button class="ghost" data-hist="${esc(u.app)}">
          <strong>${esc(u.studio || u.app)}</strong><span>${EV_LABEL[u.stage]}${u.round ? ` round ${u.round}` : ""}</span><span class="grow"></span><span>${esc(fmtWhen(u.scheduled))}</span></button></li>`).join("")}</ul>`
          : `<div class="muted">Nothing scheduled.</div>`}
      </div></section>
    </div></div>`;
  $("#tbody").onclick = (e) => { const b = e.target.closest("[data-hist]"); if (b) openHistory(b.dataset.hist); };
}
