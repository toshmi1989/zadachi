"use strict";
/* Shared helpers: API, icons, formatting, router, toasts, drawer/modal, tooltip. No framework, no build. */
const Z = { me: null, by: "close", mode: "count", meta: null };
try { Z.by = localStorage.getItem("by") === "due" ? "due" : "close"; Z.mode = localStorage.getItem("mode") === "pct" ? "pct" : "count"; } catch (e) {}

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const ICON = {
  dash: '<path d="M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
  auto: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  stack: '<path d="m12 2 10 5-10 5L2 7zM2 12l10 5 10-5M2 17l10 5 10-5"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 9.7-9.7M18 5l3 3M15 8l2 2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  chev: '<path d="m6 9 6 6 6-6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  db: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.7-4 3-9 3s-9-1.3-9-3M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/>',
  sync: '<path d="M21 12a9 9 0 0 1-15.4 6.4L3 16M3 12a9 9 0 0 1 15.4-6.4L21 8M21 3v5h-5M3 21v-5h5"/>',
  ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"/>',
  send: '<path d="m22 2-7 20-4-9-9-4zM22 2 11 13"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
};
const icon = (n, cls) => `<svg class="ic${cls ? " " + cls : ""}" viewBox="0 0 24 24" aria-hidden="true">${ICON[n] || ""}</svg>`;

/* ───────── API ───────── */
async function api(path, opts) {
  opts = opts || {};
  const init = { method: opts.method || "GET", headers: {}, credentials: "same-origin" };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.form) init.body = opts.form;
  let r;
  try { r = await fetch(path, init); } catch (e) { throw new Error("Нет связи с сервером"); }
  if (r.status === 401) { location.href = "/login"; throw new Error("Требуется вход"); }
  let data = null;
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((data && (data.error || data.detail)) || "Ошибка " + r.status);
  return data;
}
function qs(o) { const p = new URLSearchParams(); Object.keys(o).forEach(k => { if (o[k] !== "" && o[k] != null) p.set(k, o[k]); }); return p.toString(); }

/* ───────── formatting ───────── */
const MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
function fdate(iso, short) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return short ? `${d} ${MON[m - 1]}` : `${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}.${y}`;
}
function plural(n, one, few, many) { n = Math.abs(n); const a = n % 10, b = n % 100; return b > 10 && b < 20 ? many : a === 1 ? one : a > 1 && a < 5 ? few : many; }
function daysText(days, status) {
  if (days == null) return "срок не указан";
  if (status === "done" || status === "info") return "";
  if (days < 0) return `просрочено на ${-days} ${plural(-days, "день", "дня", "дней")}`;
  if (days === 0) return "срок сегодня";
  if (days === 1) return "остался 1 день";
  return `осталось ${days} ${plural(days, "день", "дня", "дней")}`;
}
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
function initials(name) { const p = String(name || "?").split(/\s+/); return ((p[0] || "?")[0] + (p[1] ? p[1][0] : "")).toUpperCase(); }
function hue(id) { return (Number(id) * 47 + 210) % 360; }
function avatar(id, name, cls) {
  if (!id) return `<span class="av ${cls || ""}" style="background:var(--c-nodate)">?</span>`;
  return `<span class="av ${cls || ""}" style="background:hsl(${hue(id)} 55% 48%)">${esc(initials(name))}</span>`;
}
const KEYS = ["overdue", "week", "month", "later", "nodate", "done", "info"];
const LABEL = { overdue: "Просрочено", week: "Срок ≤ 7 дней", month: "8–30 дней", later: "Позже 30 дней", nodate: "Без срока", done: "Выполнено", info: "К сведению", open: "В работе" };
const ST = { todo: "Не выполнено", progress: "В работе", done: "Выполнено", info: "К сведению" };

function countUp(el, to, ms) {
  if (!el) return;
  if (reduced() || to === 0) { el.textContent = to; return; }
  const t0 = performance.now(); ms = ms || 900;
  const step = t => { const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3); el.textContent = Math.round(to * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
/* a sliding pill under the active button of a segmented control */
function seg(items, value, onChange, cls) {
  const box = document.createElement("div");
  box.className = "seg " + (cls || "");
  box.innerHTML = '<span class="pill"></span>' + items.map(i => `<button type="button" data-v="${esc(i[0])}">${esc(i[1])}</button>`).join("");
  const pill = $(".pill", box);
  const place = () => {
    const b = $("button.on", box); if (!b || !b.offsetWidth) return;
    pill.style.left = b.offsetLeft + "px"; pill.style.width = b.offsetWidth + "px";
  };
  const set = (v, fire) => { $$("button", box).forEach(b => b.classList.toggle("on", b.dataset.v === v)); place(); if (fire) onChange(v); };
  box.addEventListener("click", e => { const b = e.target.closest("button"); if (b && !b.classList.contains("on")) set(b.dataset.v, true); });
  set(value, false);
  requestAnimationFrame(() => { place(); setTimeout(place, 80); });
  box.set = set;
  return box;
}

/* ───────── toasts ───────── */
function toast(msg, kind, action) {
  const box = $("#toasts"); if (!box) return;
  const el = document.createElement("div");
  el.className = "toast " + (kind || "ok"); el.setAttribute("role", kind === "error" ? "alert" : "status");
  el.innerHTML = icon(kind === "error" ? "alert" : "check") + `<span>${esc(msg)}</span>` + (action ? `<button type="button">${esc(action.label)}</button>` : "");
  box.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("on")));
  const close = () => { el.classList.remove("on"); setTimeout(() => el.remove(), 380); };
  if (action) $("button", el).onclick = () => { action.run(); close(); };
  setTimeout(close, action ? 6500 : kind === "error" ? 5200 : 2800);
}

/* ───────── tooltip ───────── */
const tip = $("#tip");
document.addEventListener("pointermove", e => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  if (!t || e.pointerType === "touch") { tip.classList.remove("on"); return; }
  tip.innerHTML = t.dataset.tip; tip.classList.add("on");
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(innerWidth - w - 8, Math.max(8, e.clientX + 14)) + "px";
  tip.style.top = (e.clientY + 18 + h > innerHeight ? e.clientY - h - 12 : e.clientY + 18) + "px";
});
document.addEventListener("pointerleave", () => tip.classList.remove("on"));
document.addEventListener("scroll", () => tip.classList.remove("on"), true);

/* ───────── ripple on buttons ───────── */
document.addEventListener("pointerdown", e => {
  const b = e.target.closest(".btn"); if (!b || reduced()) return;
  const r = b.getBoundingClientRect(), s = Math.max(r.width, r.height), d = document.createElement("span");
  d.className = "rip"; d.style.cssText = `width:${s}px;height:${s}px;left:${e.clientX - r.left - s / 2}px;top:${e.clientY - r.top - s / 2}px`;
  b.appendChild(d); setTimeout(() => d.remove(), 600);
});

/* ───────── modal & drawer ───────── */
function layer(kind, html, onClose) {
  const root = $(kind === "drawer" ? "#drawer-root" : "#modal-root");
  const scrim = document.createElement("div"); scrim.className = "scrim";
  const box = document.createElement("div"); box.className = kind; box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
  box.innerHTML = html;
  root.innerHTML = ""; root.append(scrim, box);
  const prev = document.activeElement;
  let closed = false;
  const close = () => {
    if (closed) return; closed = true;
    scrim.classList.remove("on"); box.classList.remove("on");
    document.removeEventListener("keydown", key);
    setTimeout(() => { if (root.contains(box)) root.innerHTML = ""; }, 420);
    if (prev && prev.focus) try { prev.focus({ preventScroll: true }); } catch (e) {}
    if (onClose) onClose();
  };
  const key = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", key);
  scrim.onclick = close;
  requestAnimationFrame(() => requestAnimationFrame(() => { scrim.classList.add("on"); box.classList.add("on"); }));
  box.close = close; box.layer = true;
  return box;
}
/* form dialog: fields [{name,label,type,value,options,hint,required}] → resolves to values or null */
function formDialog(o) {
  return new Promise(resolve => {
    let done = false;
    const html = `<h2>${esc(o.title)}</h2>${o.text ? `<p class="mt">${esc(o.text)}</p>` : ""}<form novalidate>` +
      (o.fields || []).map(f => {
        const id = "f_" + f.name, v = f.value == null ? "" : f.value;
        const ctl = f.type === "select" ? `<select id="${id}" name="${f.name}">${f.options.map(op => `<option value="${esc(op[0])}"${String(op[0]) === String(v) ? " selected" : ""}>${esc(op[1])}</option>`).join("")}</select>`
          : `<input id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(v)}" autocomplete="off" ${f.disabled ? "disabled" : ""}>`;
        return `<div class="fld"><label for="${id}">${esc(f.label)}</label>${ctl}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ""}</div>`;
      }).join("") + `<p class="err" id="ferr"></p><div class="acts"><button type="button" class="btn" data-x>Отмена</button><button class="btn pri">${esc(o.ok || "Сохранить")}</button></div></form>`;
    const box = layer("modal", html, () => { if (!done) resolve(null); });
    const form = $("form", box);
    $("[data-x]", box).onclick = () => box.close();
    setTimeout(() => { const f = $("input,select", box); if (f) f.focus(); }, 120);
    form.onsubmit = async e => {
      e.preventDefault();
      const data = {}; new FormData(form).forEach((v, k) => data[k] = v);
      (o.fields || []).forEach(f => { if (f.disabled) data[f.name] = f.value; });
      const bad = (o.fields || []).find(f => f.required && !String(data[f.name] || "").trim());
      if (bad) { $("#ferr", box).textContent = `Заполните: ${bad.label}`; return; }
      if (o.submit) {
        try { const r = await o.submit(data); done = true; box.close(); resolve(r === undefined ? data : r); }
        catch (err) { $("#ferr", box).textContent = err.message; }
      } else { done = true; box.close(); resolve(data); }
    };
  });
}
function infoDialog(title, html, ok) {
  return new Promise(resolve => {
    const box = layer("modal", `<h2>${esc(title)}</h2>${html}<div class="acts"><button class="btn pri" data-x>${esc(ok || "Готово")}</button></div>`, resolve);
    $("[data-x]", box).onclick = () => box.close();
  });
}
function copyText(t) { try { navigator.clipboard.writeText(t); toast("Скопировано"); } catch (e) { toast("Выделите и скопируйте вручную", "error"); } }

/* ───────── router ───────── */
const routes = {};
let current = null;
function parseHash() {
  const h = location.hash.replace(/^#\/?/, "");
  const [name, q] = h.split("?");
  const params = {}; new URLSearchParams(q || "").forEach((v, k) => params[k] = v);
  return { name: name || "dashboard", params };
}
function go(name, params) { const q = qs(params || {}); location.hash = "#/" + name + (q ? "?" + q : ""); }
async function route() {
  const { name, params } = parseHash();
  const def = routes[name] || routes.dashboard;
  const view = $("#view");
  if (current && current.cleanup) { try { current.cleanup(); } catch (e) {} }
  const old = view.firstElementChild;
  if (old && !reduced()) { old.classList.add("leave"); await new Promise(r => setTimeout(r, 150)); }
  view.innerHTML = '<div class="page"><div class="skel" style="height:120px;margin-bottom:14px"></div><div class="skel" style="height:300px"></div></div>';
  window.scrollTo({ top: 0 });
  const page = document.createElement("div"); page.className = "page";
  try {
    const cleanup = await def(page, params);
    current = { cleanup };
    view.innerHTML = ""; view.appendChild(page);
  } catch (e) {
    view.innerHTML = `<div class="page"><div class="card empty"><div class="big">⚠️</div><h2 style="justify-content:center">${esc(e.message)}</h2><p><a href="#/dashboard">На дашборд</a></p></div></div>`;
  }
  markNav(name);
  document.title = (def.title ? def.title + " · " : "") + "Задачи";
}
function markNav(name) {
  $$("#tabs a, #bottom a").forEach(a => a.classList.toggle("on", a.dataset.r === name));
  const a = $("#tabs a.on"), ink = $("#ink");
  if (a) { ink.style.left = a.offsetLeft + "px"; ink.style.width = a.offsetWidth + "px"; ink.style.opacity = 1; } else ink.style.opacity = 0;
}

/* copy a text to the clipboard (the code of a task); where the clipboard API is not allowed the old way is used */
function copyText(text, done) {
  const ok = () => toast(done || "Скопировано: " + text);
  const old = () => { const t = document.createElement("textarea"); t.value = text; t.style.cssText = "position:fixed;opacity:0;top:0"; document.body.appendChild(t); t.select(); let r = false; try { r = document.execCommand("copy"); } catch (e) { /* no */ } t.remove(); r ? ok() : toast("Не удалось скопировать: выделите код и нажмите Ctrl+C", "error"); };
  try { navigator.clipboard.writeText(text).then(ok, old); } catch (e) { old(); }
}

/* A link to ijro that cannot open the task itself (no card address known) leads to the section and copies the code of the task:
   it only has to be pasted into the search field of the site. */
document.addEventListener("click", e => {
  const a = e.target.closest && e.target.closest("a[data-copycode]");
  if (!a) return;
  const code = a.dataset.copycode;
  try { navigator.clipboard.writeText(code).then(() => toast("Код " + code + " скопирован: вставьте его в поиск на ijro"), () => {}); } catch (err) { /* the link still opens */ }
});
