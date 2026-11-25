"use strict";
/* Editor of tasks (administrator and specialist). The execution date, the responsible person and the status are changed right in the row and saved at once;
   a task can be added by hand. A task added by hand has its own code (M00001 ...) and is never taken off the dashboard by a loaded base.
   The official term is the administrator's: the specialist sees and sets only the execution date (the closing date). */

routes.editor = async function (page, params) {
  if (!["admin", "specialist"].includes(Z.me.role)) throw new Error("Раздел доступен администратору и специалисту");
  const admin = Z.me.role === "admin";
  const meta = await loadMeta();
  const SIZE = 50;
  if (!Object.keys(params || {}).length) params = savedFilters("editor");      // a click on the menu: the filters are as they were left
  const S = { q: params.q || "", unit: params.unit || "", assignee: params.assignee || "", status: params.status === undefined ? "open" : params.status === "all" ? "" : params.status, kind: params.kind || "", nodate: params.term === "none", page: +params.page || 1 };
  const ST = [["todo", "Не выполнено"], ["progress", "В работе"], ["done", "Выполнено"], ["info", "К сведению"]];
  const kinds = [...new Set(["Фармон", "Қарор", "Баён", "ВМ", "ПА", ...meta.kinds.filter(Boolean)])];
  const personOpts = sel => `<option value="">Не назначен</option>` + meta.people.map(p => `<option value="${p.id}"${String(sel) === String(p.id) ? " selected" : ""}>${esc(p.short || p.name)}</option>`).join("");
  const unitOpts = (sel, all) => `<option value="">${all}</option>` + (meta.units || []).map(u => `<option value="${u.id}"${String(sel) === String(u.id) ? " selected" : ""}>${esc((u.level ? "— " : "") + (u.num ? u.num + ". " : "") + u.name)}</option>`).join("");

  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Редактор задач</h1><p>Срок исполнения, ответственный и статус меняются прямо в строке и сохраняются сразу. Задачи добавляются по кодам: остальное скрипт найдёт на сайте сам.</p></div>
      <div class="controls"><button class="btn pri" id="ed-add">${icon("plus")}Добавить по кодам</button></div></div>
    <div id="ed-scope"></div>
    <div id="ed-pend"></div>
    <section class="card rise" style="--i:1">
      <div class="ed-filters">
        <input id="ed-q" type="search" placeholder="Поиск: код, документ или текст…" value="${esc(S.q)}">
        <select id="ed-unit" title="Отдел">${unitOpts(S.unit, "Все отделы")}</select>
        <select id="ed-assignee" title="Ответственный"><option value="">Все ответственные</option><option value="0"${S.assignee === "0" ? " selected" : ""}>Не назначен</option>${meta.people.map(p => `<option value="${p.id}"${String(S.assignee) === String(p.id) ? " selected" : ""}>${esc(p.short || p.name)}</option>`).join("")}</select>
        <select id="ed-status" title="Статус"><option value="open"${S.status === "open" ? " selected" : ""}>Не выполнено и в работе</option><option value=""${S.status === "" ? " selected" : ""}>Все статусы</option><option value="done"${S.status === "done" ? " selected" : ""}>Выполнено</option><option value="info"${S.status === "info" ? " selected" : ""}>К сведению</option></select>
        <select id="ed-kind" title="Вид документа"><option value="">Все виды</option>${kinds.map(k => `<option${S.kind === k ? " selected" : ""}>${esc(k)}</option>`).join("")}</select>
        <label class="switchrow" style="margin:0"><input type="checkbox" id="ed-nodate"${S.nodate ? " checked" : ""}><span>Без срока исполнения</span></label>
      </div>
      <div class="tablewrap"><table class="plain edt"><thead><tr><th>Код</th><th>Задача</th><th>Ответственный</th><th>Срок исполнения</th><th>Статус</th><th></th><th></th></tr></thead><tbody id="ed-rows"></tbody></table></div>
      <div class="ed-foot"><span class="hint" id="ed-count"></span><span><button class="btn sm" id="ed-prev">← Назад</button> <button class="btn sm" id="ed-next">Вперёд →</button></span></div>
    </section>`;
  const rowsBox = $("#ed-rows", page);
  $("#ed-scope", page).appendChild(scopeSeg(() => { S.page = 1; load(); }));                       // the editor works with one group of tasks at a time

  const query = () => new URLSearchParams(Object.entries({ q: S.q, unit: S.unit, assignee: S.assignee, status: S.status, kind: S.kind, term: S.nodate ? "none" : "", sort: "eff", dir: "asc", size: SIZE, page: S.page, scope: Z.scope }).filter(([, v]) => v !== "" && v !== false)).toString();
  let total = 0;
  async function load() {
    saveFilters("editor", { q: S.q, unit: S.unit, assignee: S.assignee, status: S.status === "" ? "all" : S.status, kind: S.kind, term: S.nodate ? "none" : "" });
    rowsBox.innerHTML = `<tr><td colspan="7"><div class="skel" style="height:80px"></div></td></tr>`;
    let d;
    try { d = await api("/api/tasks?" + query()); } catch (e) { rowsBox.innerHTML = `<tr><td colspan="7" class="err">${esc(e.message)}</td></tr>`; return; }
    total = d.total;
    try {
      const pd = await api("/api/tasks-pending");
      $("#ed-pend", page).innerHTML = pd.count ? `<div class="warn" style="margin-bottom:14px">${icon("alert")}<span>Задач, которые ждут данных с сайта: <b>${pd.count}</b> (${esc(pd.codes.slice(0, 6).join(", "))}${pd.count > 6 ? "…" : ""}). Нажмите «Синхронизировать» в скрипте на ijro: он найдёт текст, документ, срок и ответственного. Если задача долго не заполняется, проверьте код.</span></div>` : "";
    } catch (e) { /* the banner is only a hint */ }
    rowsBox.innerHTML = d.items.length ? d.items.map(row).join("") : `<tr><td colspan="7"><div class="empty" style="padding:28px"><div class="big">📋</div>Задач по этим условиям нет</div></td></tr>`;
    const from = d.total ? (S.page - 1) * SIZE + 1 : 0;
    $("#ed-count", page).textContent = d.total ? `Показано ${from}–${Math.min(S.page * SIZE, d.total)} из ${d.total}` : "";
    $("#ed-prev", page).disabled = S.page <= 1;
    $("#ed-next", page).disabled = S.page * SIZE >= d.total;
  }
  function row(t) {
    const text = (t.text || "").split("\n")[0];
    return `<tr data-id="${t.id}" class="ed-r st-${t.status}">
      <td class="code"><b>${esc(t.code)}</b>${t.by_code ? `<div><span class="chip info" style="padding:0 7px">по коду</span></div>` : t.manual ? `<div><span class="chip info" style="padding:0 7px">вручную</span></div>` : ""}<div class="hint">${esc(t.kind)}</div></td>
      <td class="ed-t">${t.pending ? `<span class="chip week" style="padding:0 7px">ждёт данных с сайта</span><div class="tx">Текст, документ и срок заполнятся при следующей синхронизации.</div>` : `<b>${esc(t.doc_no)}</b>${t.point ? ` · <span class="hint">${esc(t.point)}</span>` : ""}<div class="tx">${esc(text.length > 170 ? text.slice(0, 168) + "…" : text)}</div>`}</td>
      <td><select class="ed-f" data-f="assignee_id" data-prev="${t.assignee_id || ""}">${personOpts(t.assignee_id)}</select><div class="hint">${esc(t.unit || "")}</div></td>
      <td><input type="date" class="ed-f" data-f="close_date" data-prev="${t.close_date || ""}" value="${t.close_date || ""}">${admin && t.due ? `<div class="hint">официальный: ${esc(fdate(t.due))}</div>` : ""}</td>
      <td><select class="ed-f" data-f="status" data-prev="${t.status}">${ST.map(s => `<option value="${s[0]}"${t.status === s[0] ? " selected" : ""}>${s[1]}</option>`).join("")}</select></td>
      <td class="ed-ok" aria-live="polite"></td>
      <td><button type="button" class="btn sm danger ed-del" data-tip="Удалить задачу" aria-label="Удалить задачу ${esc(t.code)}">${icon("trash")}</button></td></tr>`;
  }

  /* a change in a row is saved at once; on a refusal the value goes back */
  rowsBox.addEventListener("change", async e => {
    const el = e.target.closest(".ed-f"); if (!el) return;
    const tr = el.closest("tr"), f = el.dataset.f, id = tr.dataset.id, mark = $(".ed-ok", tr);
    const value = f === "assignee_id" ? (el.value ? +el.value : null) : (el.value || null);
    el.disabled = true; mark.textContent = "…";
    try {
      const r = await api("/api/tasks/" + id, { method: "PATCH", json: { [f]: value } });
      el.dataset.prev = el.value; mark.innerHTML = `<span class="ed-saved">✓ сохранено</span>`;
      if (f === "status") tr.className = "ed-r st-" + r.status;
      setTimeout(() => { if (mark.isConnected) mark.textContent = ""; }, 2200);
    } catch (er) { el.value = el.dataset.prev; mark.textContent = ""; toast(er.message, "error"); }
    el.disabled = false;
  });
  /* deleting a task: a confirmation first */
  rowsBox.addEventListener("click", async e => {
    const b = e.target.closest(".ed-del"); if (!b) return;
    const tr = b.closest("tr"), id = tr.dataset.id, code = $(".code b", tr).textContent;
    const r = await formDialog({ title: "Удалить задачу " + code + "?", ok: "Удалить",
      text: "Задача исчезнет из базы вместе с её историей и этапами с сайта. Это нельзя отменить кнопкой. Если задача есть в файлах базы с сайта, она вернётся при следующей загрузке этих файлов.", fields: [],
      submit: () => api("/api/tasks/" + id, { method: "DELETE" }) });
    if (r) { Z.meta = null; toast("Задача " + code + " удалена"); load(); }
  });
  let qt;
  $("#ed-q", page).oninput = e => { clearTimeout(qt); qt = setTimeout(() => { S.q = e.target.value.trim(); S.page = 1; load(); }, 300); };
  [["ed-unit", "unit"], ["ed-assignee", "assignee"], ["ed-status", "status"], ["ed-kind", "kind"]].forEach(([id, k]) => { $("#" + id, page).onchange = e => { S[k] = e.target.value; S.page = 1; load(); }; });
  $("#ed-nodate", page).onchange = e => { S.nodate = e.target.checked; S.page = 1; load(); };
  $("#ed-prev", page).onclick = () => { if (S.page > 1) { S.page--; load(); } };
  $("#ed-next", page).onclick = () => { if (S.page * SIZE < total) { S.page++; load(); } };

  /* adding by codes: the platform creates the tasks, the script fills them from the site */
  $("#ed-add", page).onclick = () => {
    const box = layer("modal", `<h2>Добавить задачи по кодам</h2><p class="mt">Введите коды задач с сайта: по одному в строке или через пробел. Остальное (текст, документ, срок, ответственного) скрипт найдёт на сайте сам при следующей синхронизации. Добавленные так задачи не пропадают при загрузке базы.</p>
      <form novalidate>
        <div class="fld"><label for="nt-codes">Коды задач *</label><textarea id="nt-codes" name="codes" rows="7" placeholder="HUC5926&#10;YKF2161&#10;XPG5469" spellcheck="false"></textarea><span class="hint">Код — три буквы и четыре цифры, как в карточке задачи на сайте.</span></div>
        <p class="err" id="ferr"></p><div class="acts"><button type="button" class="btn" data-x>Отмена</button><button class="btn pri">Добавить</button></div></form>`);
    $("[data-x]", box).onclick = () => box.close();
    setTimeout(() => $("#nt-codes", box).focus(), 120);
    $("form", box).onsubmit = async e => {
      e.preventDefault();
      const codes = $("#nt-codes", box).value.trim();
      if (!codes) { $("#ferr", box).textContent = "Введите хотя бы один код"; return; }
      try {
        const r = await api("/api/tasks/by-codes", { method: "POST", json: { codes } });
        box.close(); Z.meta = null;
        const parts = [`Добавлено: ${r.created.length}`];
        if (r.existing.length) parts.push(`уже были: ${r.existing.length}`);
        if (r.invalid.length) parts.push(`не похожи на код: ${r.invalid.slice(0, 4).join(", ")}`);
        toast(parts.join(" · "), r.created.length ? undefined : "error");
        S.status = "open"; S.page = 1; load();
      } catch (er) { $("#ferr", box).textContent = er.message; }
    };
  };
  await load();
};
routes.editor.title = "Редактор задач";
