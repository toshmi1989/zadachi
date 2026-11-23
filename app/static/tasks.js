"use strict";
/* Task list (filters, sorting, paging, bulk edit) and the task drawer. */

const FIELD = { assignee_id: "Ответственный", status: "Статус", close_date: "Дата закрытия", due: "Срок по ijro" };
const STAGE_NAME = { none: "Ответ не введён", moj: "Адлия вазирлигида", cab: "Вазирлар Маҳкамасида", chamber: "Ҳисоб палатасида", info: "Ҳисоб палатаси вернула (срок изменён)", returned: "Возврат / запрос", unchecked: "Не проверялись на сайте", other: "Другое (этап не распознан)" };
/* where the task is on its way (the answer goes Justice -> Cabinet -> Chamber of Accounts) */
function stageChip(t) {
  const g = t.site && t.site.stage;
  if (!g || !["todo", "progress"].includes(t.status) || ["period_unknown", "not_found", "removed"].includes(g.code)) return "";
  const dots = [1, 2, 3].map(i => `<i class="${g.n >= i ? "on" : ""}"></i>`).join("");
  return `<div style="margin-top:4px"><span class="stg ${g.attention ? "att" : ""} stg-${g.code}" data-tip="${esc(g.attention ? "Требует внимания" : "Этап согласования")}">${g.code === "none" ? "" : `<span class="stgd">${dots}</span>`}${esc(g.label)}</span></div>`;
}
const STK = { todo: "k-later", progress: "k-month", done: "k-done", info: "k-info" };

async function loadMeta() { if (!Z.meta) Z.meta = await api("/api/meta"); return Z.meta; }
const isAdmin = () => Z.me.role === "admin";

function deadlineCell(t) {
  if (!t.eff) return '<div class="dl">—<small>срок не указан</small></div>';
  const txt = daysText(t.days, t.status);
  return `<div class="dl">${fdate(t.eff)}<small class="${t.bucket}">${esc(txt)}</small></div>`;
}
function statusChip(t) {
  if (t.status === "done" || t.status === "info") return `<span class="chip ${t.status}"><i class="d"></i>${ST[t.status]}</span>`;
  const b = t.bucket;
  return `<span class="chip ${t.status === "progress" ? "progress" : b}"><i class="d"></i>${t.status === "progress" ? "В работе" : LABEL[b] || ST[t.status]}</span>`;
}

routes.tasks = async function (page, params) {
  if (Z.me.tasks === "none") throw new Error("Список задач для вашей роли отключён администратором");
  const meta = await loadMeta();
  const S = { unit: params.unit === undefined ? "" : params.unit, assignee: params.assignee || "", status: params.status || "", bucket: params.bucket || "", kind: params.kind || "",
              doc: params.doc || "", stage: params.stage || "", term: params.term || "", closing: params.closing || "", q: params.q || "", date_from: params.date_from || "", date_to: params.date_to || "",
              sort: params.sort || "eff", dir: params.dir || "asc", page: +params.page || 1 };
  const own = Z.me.tasks === "own" && !isAdmin();
  const sel = new Set();
  let data = null, reqId = 0;
  const admin = isAdmin();

  page.innerHTML = `
    <div class="pagehead rise" style="--i:0"><div><h1>Задачи</h1><p id="sub">&nbsp;</p></div><div class="controls" id="ctl"></div></div>
    <div class="filters rise" style="--i:1">
      <div class="grow">${icon("search")}<input id="q" type="search" placeholder="Поиск по тексту, коду, номеру документа  ( / )" value="${esc(S.q)}"></div>
      ${own ? "" : `<select class="f" id="f-unit" style="min-width:210px"><option value="">Все отделы</option><option value="0">Без отдела</option>${(meta.units || []).map(u => `<option value="${u.id}">${u.level ? "\u00a0\u00a0\u00a0" + esc(u.num) + ". " : esc(u.num) + " · "}${esc(u.name.length > 60 ? u.name.slice(0, 58) + "…" : u.name)}</option>`).join("")}</select>
      <select class="f" id="f-assignee"><option value="">Все сотрудники</option><option value="0">Не назначен</option>${meta.people.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>`}
      <select class="f" id="f-status"><option value="">Любой статус</option><option value="open">В работе (все открытые)</option><option value="todo">Не выполнено</option><option value="progress">Выполняется</option><option value="done">Выполнено</option><option value="info">К сведению</option></select>
      <select class="f" id="f-bucket"><option value="">Любой срок</option>${["overdue", "week", "month", "later", "nodate"].map(k => `<option value="${k}">${LABEL[k]}</option>`).join("")}</select>
      <select class="f" id="f-kind"><option value="">Все типы</option>${meta.kinds.map(k => `<option>${esc(k)}</option>`).join("")}</select>
      <select class="f" id="f-doc"><option value="">Все документы</option>${meta.docs.map(d => `<option value="${esc(d.doc)}">${esc(d.doc)} (${d.n})</option>`).join("")}</select>
    </div>
    <div class="active-chips" id="chips"></div>
    <div id="closing-bar"></div>
    <div class="tbl rise" style="--i:2"><div class="tbl-scroll"><table class="t"><thead><tr>
      ${admin ? '<th style="width:36px"><input type="checkbox" class="cb" id="all" aria-label="Выбрать все на странице"></th>' : ""}
      <th class="s" data-s="num" style="width:60px">№</th><th class="s" data-s="doc">Документ<span class="arr">↑</span></th><th>Содержание</th>
      <th class="s" data-s="assignee">Ответственный<span class="arr">↑</span></th><th class="s" data-s="eff">Срок<span class="arr">↑</span></th>
      ${admin ? '<th class="s" data-s="close">Дата закрытия<span class="arr">↑</span></th>' : ""}<th class="s" data-s="status">Статус<span class="arr">↑</span></th><th style="width:44px"></th>
    </tr></thead><tbody id="rows"></tbody></table></div><div class="pager" id="pager"></div></div>`;

  const ctl = $("#ctl", page);
  if (admin) ctl.appendChild(byToggle(() => { load(); }));
  const exp = document.createElement("a"); exp.className = "btn"; exp.innerHTML = icon("download") + "Excel"; exp.title = "Скачать текущий список в Excel";
  ctl.appendChild(exp);
  const set = (id, v) => { const el = $(id, page); if (el) el.value = v; };
  set("#f-unit", S.unit); set("#f-assignee", S.assignee); set("#f-status", S.status); set("#f-bucket", S.bucket); set("#f-kind", S.kind); set("#f-doc", S.doc);

  /* bulk bar (administrator) */
  let bulk = null;
  if (admin) {
    bulk = document.createElement("div"); bulk.className = "bulk";
    bulk.innerHTML = `<b id="bn"></b><select id="b-as"><option value="">Ответственный…</option><option value="0">Снять ответственного</option>${meta.people.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
      <select id="b-st"><option value="">Статус…</option>${["todo", "progress", "done", "info"].map(k => `<option value="${k}">${ST[k]}</option>`).join("")}</select>
      <input id="b-dt" type="date" title="Дата закрытия"><button class="btn sm" id="b-go">Применить</button><button class="x" id="b-x" aria-label="Снять выбор">${icon("x")}</button>`;
    document.body.appendChild(bulk);
    $("#b-x", bulk).onclick = () => { sel.clear(); paintSel(); };
    $("#b-go", bulk).onclick = async () => {
      const body = { ids: [...sel] };
      const a = $("#b-as", bulk).value, s = $("#b-st", bulk).value, dt = $("#b-dt", bulk).value;
      if (a !== "") body.assignee_id = a === "0" ? null : +a;
      if (s) body.status = s;
      if (dt) body.close_date = dt;
      if (Object.keys(body).length === 1) { toast("Выберите, что изменить", "error"); return; }
      try { const r = await api("/api/tasks/bulk", { method: "POST", json: body }); toast(`Изменено задач: ${r.changed} из ${r.total}`); sel.clear(); ["#b-as", "#b-st", "#b-dt"].forEach(i => $(i, bulk).value = ""); await load(); }
      catch (e) { toast(e.message, "error"); }
    };
  }
  function paintSel() {
    $$("#rows tr", page).forEach(tr => { const on = sel.has(+tr.dataset.id); tr.classList.toggle("sel", on); const cb = $(".cb", tr); if (cb) cb.checked = on; });
    const all = $("#all", page); if (all) { const ids = $$("#rows tr", page).map(r => +r.dataset.id); all.checked = ids.length > 0 && ids.every(i => sel.has(i)); }
    if (bulk) { $("#bn", bulk).textContent = `Выбрано: ${sel.size}`; bulk.classList.toggle("on", sel.size > 0); }
  }

  function chips() {
    const out = [];
    const nm = id => (meta.people.find(p => String(p.id) === String(id)) || {}).name || "?";
    if (S.unit !== "") { const un = (meta.units || []).find(x => String(x.id) === String(S.unit)); out.push(["unit", "Отдел: " + (S.unit === "0" ? "без отдела" : un ? (un.level ? un.num + ". " : "") + (un.name.length > 40 ? un.name.slice(0, 38) + "…" : un.name) : "?")]); }
    if (S.assignee !== "") out.push(["assignee", "Сотрудник: " + (S.assignee === "0" ? "не назначен" : nm(S.assignee))]);
    if (S.status) out.push(["status", "Статус: " + (LABEL[S.status] || ST[S.status])]);
    if (S.bucket) out.push(["bucket", "Срок: " + LABEL[S.bucket]]);
    if (S.date_from || S.date_to) out.push(["date", "Срок: " + (S.date_from ? fdate(S.date_from, 1) : "…") + " – " + (S.date_to ? fdate(S.date_to, 1) : "…")]);
    if (S.kind) out.push(["kind", "Тип: " + S.kind]);
    if (S.doc) out.push(["doc", "Документ: " + S.doc]);
    if (S.stage) out.push(["stage", "Этап: " + (STAGE_NAME[S.stage] || S.stage)]);
    if (S.term === "none") out.push(["term", "Без срока"]);
    if (S.closing) out.push(["closing", "Даты закрытия: предложены, не подтверждены"]);
    const cb = $("#closing-bar", page);
    if (cb) cb.innerHTML = admin && S.closing ? `<div class="note-bar"><span>Это предложенные даты закрытия. «Пересчитать» подберёт их заново по текущим правилам (даты, которые вы поставили или подтвердили, не меняются).</span><button class="btn sm" id="cl-redo">Пересчитать</button><button class="btn sm pri" id="cl-ok">Подтвердить все</button></div>` : "";
    if (cb && admin && S.closing) {
      $("#cl-redo", cb).onclick = async e => { e.target.disabled = true; try { const r = await api("/api/closing/suggest", { method: "POST", json: { redo: true } }); toast(`Пересчитано: ${r.proposed}` + (r.errors.length ? ". " + r.errors[0] : "")); load(); } catch (er) { toast(er.message, "error"); e.target.disabled = false; } };
      $("#cl-ok", cb).onclick = async e => { if (!confirm("Подтвердить все предложенные даты?")) return; try { const r = await api("/api/closing/confirm", { method: "POST", json: {} }); toast("Подтверждено: " + r.confirmed); load(); } catch (er) { toast(er.message, "error"); } };
    }
    $("#chips", page).innerHTML = out.map(c => `<span class="fchip" data-k="${c[0]}">${esc(c[1])}<button type="button" aria-label="Убрать фильтр">${icon("x")}</button></span>`).join("");
  }
  $("#chips", page).onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    const k = b.parentNode.dataset.k;
    if (k === "date") { S.date_from = S.date_to = ""; } else S[k] = "";
    ["unit", "assignee", "status", "bucket", "kind", "doc"].forEach(f => set("#f-" + f, S[f]));
    S.page = 1; load();
  };
  ["unit", "assignee", "status", "bucket", "kind", "doc"].forEach(f => { const el = $("#f-" + f, page); if (el) el.onchange = () => { S[f] = el.value; if (f === "bucket") { S.date_from = S.date_to = ""; } S.page = 1; load(); }; });
  let qt; $("#q", page).oninput = e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value.trim(); S.page = 1; load(); }, 280); };
  $$("th.s", page).forEach(th => th.onclick = () => { const k = th.dataset.s; if (S.sort === k) S.dir = S.dir === "asc" ? "desc" : "asc"; else { S.sort = k; S.dir = "asc"; } S.page = 1; load(); });
  const onKey = e => { if (e.key === "/" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); $("#q", page).focus(); } };
  document.addEventListener("keydown", onKey);

  function row(t, i) {
    const who = t.assignee_id ? `<span class="who">${avatar(t.assignee_id, t.assignee_name, "sm")}${esc(t.assignee)}</span>` : '<span class="who none">Не назначен</span>';
    return `<tr data-id="${t.id}" style="--i:${Math.min(i, 24)}" tabindex="0">
      ${admin ? `<td class="c-cb"><input type="checkbox" class="cb" aria-label="Выбрать"></td>` : ""}
      <td class="code num">${t.num || ""}<br><button type="button" class="codebtn" data-copy="${esc(t.code)}" data-tip="Нажмите, чтобы скопировать код">${esc(t.code)}${icon("copy")}</button></td>
      <td class="doc"><b>${esc(t.doc_no)}</b><small>${esc(t.kind)}${t.doc_date ? " · " + fdate(t.doc_date) : ""}</small></td>
      <td>${t.point ? `<span class="pt">${esc(t.point)}</span>` : ""}<div class="tx">${esc(t.text)}</div></td>
      <td>${who}</td><td>${deadlineCell(t)}</td>
      ${admin ? `<td>${t.close_date ? fdate(t.close_date) : '<span style="color:var(--text-3)">—</span>'}${t.close_src ? ` <span class="prop ${t.close_src}" data-tip="${esc((t.close_src === "ai" ? "Предложено ИИ. " : "Предложено по прежним решениям. ") + (t.close_note || "") + " Нажмите на задачу, чтобы подтвердить или изменить.")}">${t.close_src === "ai" ? "ИИ" : "авто"}</span>` : ""}</td>` : ""}
      <td>${statusChip(t)}${stageChip(t)}${t.tag ? `<div class="hint" style="margin-top:3px">${esc(t.tag)}</div>` : ""}${t.site && t.site.diff ? `<div style="margin-top:4px"><span class="chip done" data-tip="По данным ijro (проверено ${esc(t.site.checked_at.slice(0, 16))}).${admin ? " Применить можно в разделе «Синхронизация» или в карточке." : ""}">на сайте: ${esc(t.site.label)}</span></div>` : ""}${t.site && t.site.site_open_we_done ? '<div style="margin-top:4px"><span class="chip overdue" data-tip="У нас отмечена выполненной, а на сайте ещё нет">на сайте не закрыта</span></div>' : ""}</td>
      <td class="c-q">${t.can_edit && (t.status === "todo" || t.status === "progress") ? `<button class="quick" data-quick aria-label="Отметить выполненной" data-tip="Отметить выполненной">${icon("check")}</button>` : ""}</td></tr>`;
  }
  const flashId = { v: 0 };
  async function load() {
    const my = ++reqId;
    const rowsEl = $("#rows", page); rowsEl.style.opacity = ".45"; rowsEl.style.transition = "opacity .2s";
    const q = { unit: own ? "" : S.unit, assignee: own ? "" : S.assignee, status: S.status, bucket: S.bucket, kind: S.kind, doc: S.doc, stage: S.stage, term: S.term, closing: S.closing, q: S.q, date_from: S.date_from, date_to: S.date_to, sort: S.sort, dir: S.dir, by: Z.by };
    history.replaceState(null, "", "#/tasks" + (qs(Object.assign({}, q, { page: S.page > 1 ? S.page : "" })) ? "?" + qs(Object.assign({}, q, { page: S.page > 1 ? S.page : "" })) : ""));
    exp.href = "/api/tasks.xlsx?" + qs(q);
    try { data = await api("/api/tasks?" + qs(Object.assign({}, q, { page: S.page, size: 50 }))); } catch (e) { toast(e.message, "error"); return; }
    if (my !== reqId) return;
    const pages = Math.max(1, Math.ceil(data.total / 50));
    if (S.page > pages) { S.page = pages; return load(); }
    chips();
    $$("th.s", page).forEach(th => { const on = th.dataset.s === S.sort; th.classList.toggle("sorted", on); th.classList.toggle("desc", on && S.dir === "desc"); });
    $("#sub", page).textContent = data.total ? `Найдено ${data.total} ${plural(data.total, "задача", "задачи", "задач")}` + (own ? " · показаны только ваши" : "") : "Ничего не найдено";
    rowsEl.innerHTML = data.items.length ? data.items.map(row).join("") :
      `<tr style="cursor:default"><td colspan="9"><div class="empty"><div class="big">🔍</div><b>Нет задач под эти условия</b><p>Уберите часть фильтров — например, нажмите на крестик в синих плашках выше.</p></div></td></tr>`;
    rowsEl.style.opacity = 1;
    if (flashId.v) { const f = $(`tr[data-id="${flashId.v}"]`, rowsEl); if (f) { f.style.animation = "none"; f.classList.add("flash"); } flashId.v = 0; }
    const a = (S.page - 1) * 50 + 1, b = Math.min(S.page * 50, data.total);
    $("#pager", page).innerHTML = data.total ? `<span>Показано ${a}–${b} из ${data.total}</span><span class="pg"><button class="btn sm" id="pp" ${S.page <= 1 ? "disabled" : ""}>← Назад</button><span class="num">стр. ${S.page} из ${pages}</span><button class="btn sm" id="pn" ${S.page >= pages ? "disabled" : ""}>Вперёд →</button></span>` : "";
    const pp = $("#pp", page), pn = $("#pn", page);
    if (pp) pp.onclick = () => { S.page--; load(); window.scrollTo({ top: 0, behavior: "smooth" }); };
    if (pn) pn.onclick = () => { S.page++; load(); window.scrollTo({ top: 0, behavior: "smooth" }); };
    paintSel();
  }
  const body = $("#rows", page);
  body.addEventListener("click", async e => {
    const cp = e.target.closest("[data-copy]");
    if (cp) { copyText(cp.dataset.copy, "Код " + cp.dataset.copy + " скопирован"); return; }      // the code is copied; the card does not open
    if (e.target.closest("[data-ext]")) return;   // the link to ijro opens in a new tab and must not open the drawer
    const tr = e.target.closest("tr[data-id]"); if (!tr) return;
    const id = +tr.dataset.id;
    if (e.target.closest(".cb")) { e.target.checked ? sel.add(id) : sel.delete(id); paintSel(); return; }
    if (e.target.closest("[data-quick]")) {
      const t = data.items.find(x => x.id === id), prev = t.status;
      try {
        await api("/api/tasks/" + id, { method: "PATCH", json: { status: "done" } });
        toast("Задача отмечена выполненной", "ok", { label: "Отменить", run: async () => { await api("/api/tasks/" + id, { method: "PATCH", json: { status: prev } }); flashId.v = id; load(); } });
        flashId.v = id; load();
      } catch (er) { toast(er.message, "error"); }
      return;
    }
    openTask(id, () => { flashId.v = id; load(); });
  });
  body.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("tr[data-id]")) openTask(+e.target.dataset.id, () => load()); });
  const all = $("#all", page);
  if (all) all.onchange = () => { $$("#rows tr[data-id]", page).forEach(r => all.checked ? sel.add(+r.dataset.id) : sel.delete(+r.dataset.id)); paintSel(); };

  await load();
  return () => { document.removeEventListener("keydown", onKey); if (bulk) { bulk.classList.remove("on"); setTimeout(() => bulk.remove(), 400); } };
};
routes.tasks.title = "Задачи";

/* ───────── drawer ───────── */
async function openTask(id, onChange) {
  let t;
  try { t = await api(`/api/tasks/${id}?by=${Z.by}`); } catch (e) { toast(e.message, "error"); return; }
  const admin = isAdmin();
  let people = [];
  if (admin) { try { people = (await loadMeta()).people; } catch (e) {} }
  let changed = false;
  const box = layer("drawer", `<div class="dr-h"><div><h2 id="dr-t"></h2><p class="hint" id="dr-s" style="margin:4px 0 0"></p></div><button class="icon-btn" data-x aria-label="Закрыть">${icon("x")}</button></div><div class="dr-b" id="dr-b"></div>`, () => { if (changed && onChange) onChange(); });
  $("[data-x]", box).onclick = () => box.close();
  const stOpts = [["todo", "Не выполнено"], ["progress", "В работе"], ["done", "Выполнено"], ["info", "К сведению"]];
  function paint(first) {
    $("#dr-t").textContent = t.code;
    $("#dr-s").textContent = `${t.kind} ${t.doc_no}${t.doc_date ? " от " + fdate(t.doc_date) : ""}`;
    const b = $("#dr-b", box);
    b.classList.toggle("still", !first);
    const dtext = daysText(t.days, t.status);
    const canStatus = admin || (t.can_edit && t.status !== "info");   // an employee cannot touch a task taken "for information"
    b.innerHTML = `
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px">${statusChip(t)}${dtext ? `<span class="hint">${esc(dtext)}</span>` : ""}</div>
      ${t.point ? `<div class="sec-t" style="margin-top:0">${esc(t.point)}</div>` : ""}
      <div class="dtext">${esc(t.text)}</div>
      <div class="kv">
        ${admin ? `<div><div class="k">Официальный срок</div><div class="v">${fdate(t.due)}</div></div>` : ""}
        ${admin && t.close_src ? `<div class="full"><div class="warn">${icon("info")}<span><b>${t.close_src === "ai" ? "Дата предложена ИИ" : "Дата предложена по прежним решениям"}.</b> ${esc(t.close_note || "")}</span><button class="btn sm pri" id="close-ok" style="margin-left:auto">Подтвердить</button></div></div>` : ""}
        <div${admin ? "" : ' class="full"'}><div class="k">${admin ? "Дата закрытия" : "Срок (дата закрытия)"}</div>${admin ? `<div style="display:flex;gap:6px"><input type="date" id="e-close" value="${esc(t.close_date || "")}"><button class="btn sm" id="e-clear" title="Очистить" ${t.close_date ? "" : "disabled"}>${icon("x")}</button></div>` : `<div class="v">${fdate(t.close_date)}</div>`}</div>
        <div class="full"><div class="k">Ответственный</div>${admin ? `<select id="e-as"><option value="">— не назначен —</option>${people.map(p => `<option value="${p.id}"${p.id === t.assignee_id ? " selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : `<div class="v" style="display:flex;gap:8px;align-items:center">${t.assignee_id ? avatar(t.assignee_id, t.assignee_name, "sm") + esc(t.assignee_name) : "Не назначен"}</div>`}
          ${t.unit ? `<span class="hint">Отдел: ${esc(t.unit)}</span>` : ""}
          ${t.assignee_raw && t.assignee_raw !== t.assignee_name ? `<span class="hint">В выгрузке: ${esc(t.assignee_raw)}</span>` : ""}</div>
        <div class="full"><div class="k">Статус${!admin && t.can_edit ? ' <span class="hint" style="font-weight:400">· вы можете менять статус своей задачи</span>' : ""}</div><div class="stbtns${canStatus ? "" : " ro"}" id="e-st">${stOpts.filter(s => admin || s[0] !== "info" || t.status === "info").map(s => `<button type="button" class="${STK[s[0]]}${t.status === s[0] ? " on" : ""}" data-v="${s[0]}">${s[1]}</button>`).join("")}</div>${t.tag ? `<span class="hint">Пометка в выгрузке: ${esc(t.tag)}</span>` : ""}</div>
      </div>
      ${siteBlock(t, admin)}
      <div class="sec-t">История изменений</div>
      ${t.events.length ? `<div class="tl">${t.events.map(e => `<div class="ev"><b>${FIELD[e.field] || esc(e.field)}:</b> ${e.old ? esc(e.old) : "—"} → <b>${e.new ? esc(e.new) : "—"}</b><br><small>${esc(e.who || "система")} · ${esc(e.created_at.slice(0, 16))}</small></div>`).join("")}</div>` : '<p class="hint">Изменений пока не было.</p>'}`;
    const save = async (patch, ok) => {
      try {
        const r = await api("/api/tasks/" + id + "?by=" + Z.by, { method: "PATCH", json: patch });
        t = r; changed = changed || r.changed; paint(false); if (r.changed) toast(ok || "Сохранено");
      } catch (e) { toast(e.message, "error"); paint(false); }
    };
    if (canStatus) $("#e-st", b).onclick = e => { const x = e.target.closest("button"); if (x && !x.classList.contains("on")) save({ status: x.dataset.v }, "Статус: " + ST[x.dataset.v]); };
    const rl = $("#site-relock", b);
    if (rl) rl.onclick = async () => { try { await api(`/api/tasks/${id}/site-check`, { method: "POST", json: { on: true } }); changed = true; t = await api(`/api/tasks/${id}?by=${Z.by}`); paint(false); toast("Задача снова сверяется с сайтом: статус обновится при следующей синхронизации"); } catch (e) { toast(e.message, "error"); } };
    if (!admin) return;
    const sb = $("#site-apply", b);
    if (sb) sb.onclick = async () => { try { await api("/api/sync/apply", { method: "POST", json: { task_ids: [id] } }); changed = true; const r = await api(`/api/tasks/${id}?by=${Z.by}`); t = r; paint(false); toast("Статус обновлён по данным ijro"); } catch (e) { toast(e.message, "error"); } };
    $("#e-as", b).onchange = e => save({ assignee_id: e.target.value ? +e.target.value : null }, "Ответственный изменён");
    const co = $("#close-ok", b); if (co) co.onclick = async () => { try { await api("/api/closing/confirm", { method: "POST", json: { ids: [id] } }); changed = true; t = await api(`/api/tasks/${id}?by=${Z.by}`); paint(false); toast("Дата подтверждена"); } catch (e) { toast(e.message, "error"); } };
    $("#e-close", b).onchange = e => save({ close_date: e.target.value || null }, "Дата закрытия сохранена");
    $("#e-clear", b).onclick = () => save({ close_date: null }, "Дата закрытия очищена");
  }
  paint(true);
}


/* the block "С ijro.uz" in a task card (administrators): what the site says, the answers, the link */
/* the steps: entered -> Justice -> Cabinet -> Chamber of Accounts -> removed from control */
function stageBlock(t, admin) {
  const g = t.site && t.site.stage;
  if (!g || g.code === "not_found") return "";      // periodic tasks have the same staged view (the stage of the period that our deadline stands for)
  const steps = g.steps.map((x, i) => `<div class="step ${g.n > i || g.code === "removed" ? "past" : ""} ${g.n === i && g.code !== "removed" ? "now" : ""} ${g.code === "info" && i === 3 ? "warnstep" : ""}"><span class="sd">${g.n > i || g.code === "removed" ? "✓" : i + 1}</span><b>${esc(x.label)}</b><small>${esc(x.hint)}</small></div>`).join("");
  const nd = g.new_due ? g.new_due.split("-").reverse().join(".") : "";
  return `<div class="sec-t" style="margin-top:12px">Этап согласования</div><div class="stepper">${steps}</div>
    <p class="hint" style="margin:6px 0 0"><b>${esc(g.label)}</b> — ${esc(g.hint)}</p>
    ${admin && g.evidence ? `<p class="hint" style="margin:6px 0 0" data-tip="Почему задача в этом этапе: даты, по которым платформа решает, менялся ли срок после ответа Палаты">Проверка срока: ${esc(g.evidence)}.</p>` : ""}
    ${g.code === "info" ? `<div class="warn" style="margin-top:10px">${icon("alert")}<span>Счётная палата вернула задачу (принято к сведению или запрос информации): она <b>не выполнена</b>${admin && nd ? `, срок на сайте изменён на <b>${esc(nd)}</b> (мы обновили его у себя)` : ", срок изменён"}.</span></div>` : ""}
    ${g.code === "returned" || g.code === "chamber_other" ? `<div class="warn" style="margin-top:10px">${icon("alert")}<span>${esc(g.hint)}.</span></div>` : ""}`;
}
function siteBlock(t, admin) {
  const s = t.site;
  if (!s) return admin ? `<div class="sec-t">С ijro.uz</div><p class="hint">Эту задачу ещё не проверяли. Запустите синхронизацию (<a href="#/sync">раздел «Синхронизация»</a>).</p>` : "";
  const head = !s.found ? `<span class="chip week">Не найдена на сайте</span>` : `<span class="chip ${s.proposed === "done" ? "done" : s.proposed === "progress" ? "progress" : "todo"}">${esc(s.label)}</span>`;
  return `<div class="sec-t">С ijro.uz</div>
    <div class="site-box"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${head}<span class="hint">проверено ${esc(s.checked_at.slice(0, 16))}</span>
      <a class="btn sm" style="margin-left:auto" href="${esc(s.link)}" target="_blank" rel="noopener noreferrer" ${s.exact_link ? "" : `data-copycode="${esc(t.code)}"`}>${icon("ext")}${s.exact_link ? "Открыть задачу на ijro" : "Открыть раздел и скопировать код"}</a></div>
      ${stageBlock(t, admin)}
      ${s.note ? `<p class="hint" style="margin:8px 0 0">${esc(s.note)}</p>` : ""}
      ${s.locked ? `<div class="warn" style="margin-top:10px">${icon("info")}<span>Статус изменён вручную: с официальным сайтом эта задача больше не сверяется (её статус и срок остаются такими, как вы поставили).</span>${["admin", "specialist"].includes(Z.me.role) ? '<button class="btn sm" id="site-relock" style="margin-left:auto">Сверять снова</button>' : ""}</div>` : ""}
      ${s.diff ? `<div class="warn" style="margin-top:10px">${icon("info")}<span>На сайте: <b>${esc(s.proposed_label)}</b>, ${admin ? "у нас" : "у вас"}: <b>${esc(ST[t.status])}</b>.</span>${admin ? '<button class="btn sm pri" id="site-apply" style="margin-left:auto">Применить</button>' : ""}</div>` : ""}
      ${s.site_open_we_done ? `<div class="warn" style="margin-top:10px">${icon("alert")}<span>${admin ? "У нас" : "У вас"} задача отмечена выполненной, а на сайте ещё нет: возможно, ответ не отправлен или не принят.</span></div>` : ""}
      ${s.secret ? '<p class="hint" style="margin:8px 0 0">Задача помечена секретной: тексты ответов не копируются в платформу.</p>' : ""}
      ${s.answers_total > s.answers.length && s.answers_days ? `<p class="hint" style="margin:10px 0 0">Показаны ответы за последние ${s.answers_days} дн. Старше: ${s.answers_total - s.answers.length} (не загружаются; период меняется в «Настройках»).</p>` : ""}${s.answers.length ? `<div class="sec-t" style="margin-top:14px">Ответы на сайте (${s.answers.length}) · сначала новые</div><div class="tl">${s.answers.map(a => `<div class="ev"><b>${esc(a.type)}</b>${a.org ? `<span class="who" data-tip="Кто дал ответ на сайте">${esc(a.org)}</span>` : ""}${a.state === -1 ? ' <span class="chip overdue" style="padding:0 7px">отклонён</span>' : ""}<br>${a.text ? `<span>${esc(a.text.length > 280 ? a.text.slice(0, 278) + "…" : a.text)}</span><br>` : ""}<small>${esc(a.at)}</small></div>`).join("")}</div>` : ""}</div>`;
}
