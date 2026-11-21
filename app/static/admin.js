"use strict";
/* Administrator pages: users, Excel import, settings. */

routes.users = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  const first = await api("/api/users");
  let items = first.items, units = first.units;
  const unitOpts = () => [["", "— не указан —"]].concat(units.map(u => [String(u.id), (u.level ? "\u00a0\u00a0\u00a0" + u.num + ". " : u.num + " · ") + (u.name.length > 70 ? u.name.slice(0, 68) + "…" : u.name)]));
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Пользователи</h1><p>Сотрудники из выгрузки появляются здесь сами. Чтобы человек мог войти — выдайте ему пароль.</p></div>
    <button class="btn pri" id="add">${icon("plus")}Добавить пользователя</button></div>
    <div class="ufilter rise" style="--i:1"><div id="usum" class="hint"></div><div id="uflt"></div></div><div class="ulist" id="ul"></div>`;
  let flt = "all";   // administrators do not need a department, so they never count as "without a department"
  const FILTERS = { all: () => true, notg: u => !u.tg_linked, nounit: u => !u.unit_id && u.role !== "admin", nopw: u => !u.pw_set };
  function paintFilter() {
    const act = items.filter(u => u.active), n = f => act.filter(FILTERS[f]).length;
    $("#usum", page).innerHTML = `Telegram привязан: <b>${act.length - n("notg")}</b> из ${act.length} · отдел указан: <b>${act.filter(u => u.role !== "admin").length - n("nounit")}</b> из ${act.filter(u => u.role !== "admin").length} · пароль выдан: <b>${act.length - n("nopw")}</b> из ${act.length}`;
    const box = $("#uflt", page); box.innerHTML = "";
    box.appendChild(seg([["all", "Все · " + items.length], ["notg", "Без Telegram · " + n("notg")], ["nounit", "Без отдела · " + n("nounit")], ["nopw", "Без пароля · " + n("nopw")]], flt, v => { flt = v; paint(); }));
  }
  const badges = u => [
    u.tg_linked ? `<span class="chip ${u.remind ? "done" : "info"}" data-tip="${u.remind ? "Telegram привязан, напоминания включены" : "Telegram привязан, но напоминания выключены самим человеком"}"><i class="d"></i>Telegram${u.tg_username ? " @" + esc(u.tg_username) : ""}${u.remind ? "" : " · напоминания выкл"}</span>`
      : '<span class="chip todo" data-tip="Не привязал Telegram: напоминаний в боте не получает"><i class="d"></i>Нет Telegram</span>',
    u.unit ? `<span class="chip progress" data-tip="${esc(u.unit)}"><i class="d"></i>${esc(u.unit.length > 34 ? u.unit.slice(0, 32) + "…" : u.unit)}</span>`
      : u.role === "admin" ? "" : '<span class="chip week" data-tip="Не внесён ни в один отдел: его задачи попадают в строку «Без отдела»"><i class="d"></i>Отдел не указан</span>',
    u.pw_set ? "" : '<span class="chip overdue" data-tip="Пароль ещё не выдан: войти он не может"><i class="d"></i>Пароль не выдан</span>',
  ].join("");
  const paint = () => {
    paintFilter();
    const list = items.filter(FILTERS[flt]);
    $("#ul", page).innerHTML = !list.length ? '<div class="card empty" style="grid-column:1/-1"><div class="big">🎉</div><b>Здесь никого нет</b><p>По этому условию все в порядке.</p></div>' : list.map((u, i) => `<div class="card ucard rise${u.active ? "" : " off"}" style="--i:${Math.min(i, 12) + 1}" data-id="${u.id}">
      <div class="hd">${avatar(u.id, u.name, "lg")}<div style="min-width:0"><b>${esc(u.name)}</b><small>${esc(u.login)} · <span class="chip ${u.role === "admin" ? "progress" : u.role === "specialist" ? "info" : ""}" style="padding:1px 8px">${u.role === "admin" ? "Администратор" : u.role === "specialist" ? "Специалист" : "Пользователь"}</span>${u.active ? "" : " · отключён"}</small></div></div>
      <div class="badges">${badges(u)}</div>
      <div class="st"><span><b class="num">${u.open}</b>в работе</span><span><b class="num">${u.tasks}</b>всего задач</span></div>
      <div class="acts"><button class="btn sm" data-a="edit">Изменить</button><button class="btn sm" data-a="pw">${icon("key")}Выдать пароль</button>${u.tasks ? `<button class="btn sm" data-a="tasks">Задачи</button>` : ""}</div></div>`).join("");
  };
  paint();
  const reload = async () => { const r = await api("/api/users"); items = r.items; units = r.units; Z.meta = null; paint(); };
  const showPw = (name, login, pw) => infoDialog("Пароль выдан", `<p class="mt">Покажите его сотруднику <b>${esc(name)}</b> (логин <b>${esc(login)}</b>). Пароль виден только сейчас — потом его можно только выдать заново.</p>
    <div class="pw"><span id="pwv">${esc(pw)}</span><button class="btn sm" id="cp">${icon("copy")}Копировать</button></div>`).then(() => {});
  $("#add", page).onclick = async () => {
    const r = await formDialog({ title: "Новый пользователь", ok: "Создать", fields: [
      { name: "name", label: "Имя (как в выгрузке Excel)", required: true, hint: "Например: Bilalov Baxodir Erkinovich. Задачи с таким именем привяжутся автоматически." },
      { name: "login", label: "Логин", required: true, hint: "Латиница, цифры, точка, дефис" },
      { name: "unit", label: "Отдел", type: "select", value: "", options: unitOpts() },
      { name: "role", label: "Роль", type: "select", value: "user", options: [["user", "Пользователь — видит дашборд"], ["specialist", "Специалист — редактирует задачи"], ["admin", "Администратор — управляет всем"]] },
      { name: "password", label: "Пароль", type: "text", hint: "Оставьте пустым — система придумает сама" }],
      submit: d => api("/api/users", { method: "POST", json: Object.assign({}, d, { unit_id: d.unit ? +d.unit : null }) }).then(res => Object.assign(res, { _d: d })) });
    if (!r) return;
    await reload();
    if (r.linked_tasks) toast(`Привязано задач из выгрузки: ${r.linked_tasks}`);
    if (r.password) { const p = showPw(r._d.name, r._d.login, r.password); setTimeout(() => { const b = $("#cp"); if (b) b.onclick = () => copyText(r.password); }, 50); await p; } else toast("Пользователь создан");
  };
  $("#ul", page).onclick = async e => {
    const b = e.target.closest("[data-a]"); if (!b) return;
    const u = items.find(x => x.id === +b.closest(".ucard").dataset.id);
    if (b.dataset.a === "tasks") return go("tasks", { assignee: u.id });
    if (b.dataset.a === "pw") {
      const r = await formDialog({ title: "Пароль для " + u.name, text: "Оставьте поле пустым, чтобы система придумала пароль сама. Старые входы пользователя будут завершены.", ok: "Выдать",
        fields: [{ name: "password", label: "Свой пароль (необязательно)", hint: "Не короче 8 символов" }],
        submit: d => api(`/api/users/${u.id}/password`, { method: "POST", json: d }) });
      if (!r) return;
      if (r.password) { const p = showPw(u.name, u.login, r.password); setTimeout(() => { const c = $("#cp"); if (c) c.onclick = () => copyText(r.password); }, 50); await p; } else toast("Пароль задан");
      return;
    }
    const r = await formDialog({ title: "Изменить: " + u.login, fields: [
      { name: "name", label: "Имя", value: u.name, required: true },
      { name: "excel_name", label: "Имя в выгрузке Excel", value: u.excel_name, hint: "Если в файле оно записано иначе, чем выше" },
      { name: "unit", label: "Отдел", type: "select", value: u.unit_id ? String(u.unit_id) : "", options: unitOpts() },
      { name: "role", label: "Роль", type: "select", value: u.role, options: [["user", "Пользователь"], ["specialist", "Специалист"], ["admin", "Администратор"]] },
      { name: "active", label: "Доступ", type: "select", value: u.active ? "1" : "0", options: [["1", "Активен"], ["0", "Отключён (войти нельзя, задачи остаются)"]] }],
      submit: d => api("/api/users/" + u.id, { method: "PATCH", json: Object.assign({}, d, { active: d.active === "1", unit_id: d.unit ? +d.unit : null }) }) });
    if (r) { toast("Сохранено"); reload(); }
  };
};
routes.users.title = "Пользователи";

routes.import = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  const hist = (await api("/api/import/history")).items;
  const cfg = Object.fromEntries((await api("/api/settings")).sync.fields.map(f => [f.key, f.value]));      // the window of terms for the base load comes from Settings
  const mode = "base";       // every load is the base: it overwrites what is on the server (the stages come from the «Синхронизировать» button of the script)
  const overwrite = cfg.base_manual !== "keep", replace = cfg.base_absent !== "keep";      // Settings: what the base does with hand edits and with tasks that are not in it
  /* Settings: which rows of the files are taken (the filters are independent; each is off when the person has already selected the rows) */
  const F = { dept: cfg.base_f_dept !== "0", exec: cfg.base_f_exec === "1", kind: cfg.base_f_kind === "1", window: cfg.base_f_window === "1" };
  const filters = [F.dept && "отделы нашей структуры (какие отделы наши, выбираете ниже)", F.exec && "исполнитель «Соғлиқни сақлаш вазирлиги»", F.kind && "без соисполнителей и лишних видов документов", F.window && "сроки в окне"].filter(Boolean);
  let confirmed = false;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Импорт базы задач</h1><p>Каждая загрузка — это база: файлы Excel с сайта перезаписывают задачи на сервере. Этапы к ним записывает кнопка «Синхронизировать» в скрипте.</p></div></div>
    <div id="modebar" class="card rise" style="--i:1;margin-bottom:16px"></div>
    <div id="stage" class="rise" style="--i:1"></div>
    <div class="card rise" style="--i:2;margin-top:16px"><div class="card-head"><h2>Последние загрузки</h2></div>${hist.length ? `<table class="plain"><thead><tr><th>Когда</th><th>Файл</th><th>Кто</th><th>Вид</th><th>Новых</th><th>Обновлено</th></tr></thead><tbody>${hist.map(h => `<tr><td>${esc(h.created_at.slice(0, 16))}</td><td>${esc(h.filename)}</td><td>${esc(h.by || "")}</td><td>${h.summary.mode === "status" ? "статусы" : "база"}${h.summary.overwritten ? ` <small class="hint">(перезаписано ${h.summary.overwritten})</small>` : ""}</td><td class="num">${h.summary.created}</td><td class="num">${h.summary.updated}</td></tr>`).join("")}</tbody></table>` : '<p class="hint">Загрузок ещё не было.</p>'}</div>`;
  const stage = $("#stage", page);
  const modeBar = $("#modebar", page);
  modeBar.innerHTML = `<b>Как загрузка обращается с тем, что уже есть на сервере</b>
    <ul class="hint" style="margin:8px 0 0;padding-left:18px">
      <li><b>Какие строки берутся:</b> ${filters.length ? "только " + filters.join("; ") + "<br><span class=\"hint\">остальные строки не загружаются, в предпросмотре видно сколько</span>" : "<b>все строки файлов</b> (вы отобрали их сами)"}.</li>
      <li><b>Задачи из файла</b> добавляются, а у существующих обновляются тексты, документ, срок, статус и ответственный.</li>
      <li><b>Ваши ручные правки:</b> ${overwrite ? "<b>перезаписываются</b> значениями из файла (перед загрузкой покажем сколько)" : "сохраняются"}.</li>
      <li><b>Задачи, которых нет в загруженных файлах:</b> ${replace ? "<b>снимаются с дашборда</b>, в том числе выполненные: в базе остаётся только то, что в файлах («Нет на сайте»; ничего не удаляется, при следующей загрузке вернутся; добавленные вручную не трогаются)" : "остаются как есть"}.</li>
      <li>Файлов можно выбрать несколько сразу (например, по одному на раздел): они читаются вместе как одна база.</li></ul>
    <p class="hint" style="margin:8px 0 0">Это можно изменить в «Настройках» → «Импорт и синхронизация».</p>`;
  const dropHtml = (err) => `<label class="drop" id="drop" for="file"><div class="big">${icon("upload")}</div><b>Перетащите файлы Excel сюда</b><p class="hint" style="margin:4px 0 0">или нажмите, чтобы выбрать · .xlsx, можно несколько файлов сразу, до 40 МБ каждый</p>${err ? `<p class="err" style="margin-top:10px">${esc(err)}</p>` : ""}<input type="file" id="file" accept=".xlsx" multiple hidden></label>`;
  function showDrop(err) {
    stage.innerHTML = dropHtml(err);
    const drop = $("#drop", stage), inp = $("#file", stage);
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => { if (e.dataTransfer.files.length) preview([...e.dataTransfer.files]); });
    inp.onchange = () => { if (inp.files.length) preview([...inp.files]); };
  }
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const presets = { soon: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 30)), iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 60))]; },
    next: () => { const t = new Date(); return [iso(new Date(t.getFullYear(), t.getMonth() + 1, 1)), iso(new Date(t.getFullYear(), t.getMonth() + 2, 0))]; }, all: () => ["2000-01-01", "2099-12-31"] };
  const fromCfg = () => { const t = new Date(), d = n => iso(new Date(t.getFullYear(), t.getMonth(), t.getDate() + n)); return [/^\d+$/.test(cfg.base_back) ? d(-cfg.base_back) : "2000-01-01", /^\d+$/.test(cfg.base_fwd) ? d(+cfg.base_fwd) : "2099-12-31"]; };
  let win = fromCfg(), useAi = false;   // the window of terms for the base load: from Settings (by default the last 30 days and the next 60)
  async function send(files, dry) {
    const f = new FormData(); files.forEach(x => f.append("file", x));
    return api(`/api/import?dry=${dry}&due_from=${win[0]}&due_to=${win[1]}&ai=${useAi ? 1 : 0}&mode=${mode}&overwrite=${overwrite ? 1 : 0}&replace=${replace ? 1 : 0}&confirm=${confirmed ? 1 : 0}&f_dept=${F.dept ? 1 : 0}&f_exec=${F.exec ? 1 : 0}&f_kind=${F.kind ? 1 : 0}&f_window=${F.window ? 1 : 0}`, { method: "POST", form: f });
  }
  /* the raw export of the site: only our departments, a window of terms, the closing dates are proposed */
  function siteBlock(s, files) {
    const r = s.site; if (!r) return "";
    const unitOpts = (sel) => `<option value="">${F.dept ? "— не наш отдел (не загружать) —" : "— не наш отдел —"}</option>${sel ? "" : `<option value="__new__">＋ наш: создать новый отдел из этого названия</option>`}` + r.units.map(u => `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${esc(u.name.length > 60 ? u.name.slice(0, 58) + "…" : u.name)}</option>`).join("");
    const how = d => d.how === "confirmed" ? "подтверждено вами" : d.how === "auto" ? "найден по названию" : d.how === "people" ? "предложено по сотрудникам" : d.suggest ? "похоже на" : "";
    const dep = r.departments;                                    // every department of the files: the person decides which of them are ours
    const missing = r.departments.filter(d => !d.unit_id);
    return `<div class="sec-t" style="margin-top:0">Выгрузка с сайта ijro</div>
      ${F.window ? `<div class="inl" style="gap:12px;flex-wrap:wrap;margin-bottom:10px"><label class="hint">Сроки с <input type="date" id="w-from" value="${win[0]}"></label><label class="hint">по <input type="date" id="w-to" value="${win[1]}"></label><button class="btn sm" id="w-go">Пересчитать</button>
        <span class="hint">Быстро: <a href="#" class="w-pre" data-p="soon">−30 / +60 дней</a> · <a href="#" class="w-pre" data-p="next">следующий месяц</a> · <a href="#" class="w-pre" data-p="all">все сроки</a>. Берутся задачи наших отделов со сроком в окне.</span></div>` : ""}
      <div class="stats">${[[r.file_tasks, "задач в файле"], [r.tasks, filters.length ? "попадёт в базу" : "задач в файлах"], ...(F.dept ? [[r.skipped.not_ours, "строк отделов, которые не наши (не берём)"]] : []), ...(F.window ? [[r.skipped.window, "строк вне окна сроков"]] : []), ...(r.skipped.coexec ? [[r.skipped.coexec, "строк соисполнителей (не берём)"]] : []), ...(r.skipped.executor ? [[r.skipped.executor, "строк другого исполнителя, не Соғлиқни сақлаш вазирлиги (не берём)"]] : []), ...(r.skipped.doc_type ? [[r.skipped.doc_type, "строк прочих видов документов Кабинета министров (не берём)"]] : [])].map(([n, l]) => `<div class="stat"><b class="num">${n}</b><span>${l}</span></div>`).join("")}</div>
      <details ${dep.some(d => !d.unit_id) ? "open" : ""} style="margin:10px 0"><summary><b>Отделы в выгрузке и соответствие нашей структуре</b> <span class="hint">(${r.departments.filter(d => d.unit_id).length} из ${r.departments.length} есть в структуре)</span></summary>
        ${missing.length ? `<div class="warn" style="margin:8px 0">${icon("info")}<span>Отделов из файлов нет в структуре департамента: <b>${missing.length}</b>. ${F.dept ? "Строки этих отделов не загружаются" : "Их задачи попадут в строку «Без отдела»"}. Выберите наш отдел в списке справа у тех, что нужны, либо добавьте их все в структуру (потом их можно переименовать, перенести в управление или скрыть в «Настройках») или сопоставьте с существующим отделом ниже.</span><button type="button" class="btn sm pri" id="dep-add" data-names="${esc(JSON.stringify(missing.map(d => d.name)))}" style="margin-left:auto;white-space:nowrap">Добавить в структуру (${missing.length})</button></div>` : ""}
        <div class="scroll-x"><table class="plain"><thead><tr><th>Отдел в выгрузке</th><th>Строк</th><th>Наш отдел</th><th></th></tr></thead><tbody>${dep.map(d => `<tr><td>${esc(d.name)}<div class="hint">${esc(d.people.join(", "))}</div></td><td class="num">${d.rows}</td>
          <td><select class="dep-map" data-key="${esc(d.key)}" data-name="${esc(d.name)}" data-init="${d.unit_id || ""}">${unitOpts(d.unit_id || null)}</select></td><td class="hint">${how(d)}${!d.unit_id && d.suggest ? `<div>Предложение: ${esc(d.suggest_name.length > 36 ? d.suggest_name.slice(0, 34) + "…" : d.suggest_name)} <a href="#" class="dep-sg" data-unit="${d.suggest}">выбрать</a></div>` : ""}</td></tr>`).join("")}</tbody></table></div>
        <div class="inl" style="margin-top:8px"><button class="btn sm pri" id="dep-save">Запомнить соответствие и пересчитать</button><span class="hint">Запоминается только то, что вы изменили, и действует на следующие выгрузки. Строки сотрудников, которые у нас уже есть, берутся и без этого.</span></div></details>
      ${r.people_moves && r.people_moves.length ? `<details open style="margin:10px 0"><summary><b>Сотрудники в другом отделе, чем в выгрузке: ${r.people_moves.length}</b></summary><div class="scroll-x"><table class="plain"><thead><tr><th></th><th>Сотрудник</th><th>У нас сейчас</th><th>По выгрузке</th><th>Задач</th></tr></thead><tbody>${r.people_moves.map(m => `<tr><td><input type="checkbox" class="pm-one" data-u="${m.user_id}" data-w="${m.wanted_id}"></td><td>${esc(m.name)}</td><td>${esc(m.now)}</td><td>${esc(m.wanted)}</td><td class="num">${m.tasks}</td></tr>`).join("")}</tbody></table></div><div class="inl" style="margin-top:8px"><button class="btn sm pri" id="pm-save">Перевести отмеченных</button><span class="hint">Меняется только отдел сотрудника у нас; его задачи не затрагиваются.</span></div></details>` : ""}
      ${r.absent && r.absent.length ? `<details style="margin:10px 0"><summary><b>Есть у нас, но нет в выгрузке: ${r.absent.length}</b> <span class="hint">— возможно, уже выполнены на сайте (ничего не меняется)</span></summary><p class="hint" style="margin:6px 0">${r.absent.slice(0, 40).map(a => esc(a.code)).join(", ")}${r.absent.length > 40 ? "…" : ""}</p></details>` : ""}
      <label class="switchrow"><input type="checkbox" id="use-ai" ${useAi ? "checked" : ""}><span><b>Подобрать даты закрытия автоматически</b> — по тому, как вы ставили даты раньше (и с помощью ИИ, если он подключён в «Настройках»). По умолчанию выключено: сроки исполнения ставит специалист в «Редакторе», а без даты закрытия месяц задачи берётся по официальному сроку. Предложенные даты помечаются, их можно подтвердить или поправить.</span></label>`;
  }
  function bindSite(files) {
    const g = id => $(id, stage); if (!g("#w-go") && !g("#use-ai")) return;
    const re = async () => { if (g("#w-from") && g("#w-to")) win = [g("#w-from").value || win[0], g("#w-to").value || win[1]]; await preview(files); };      // the window row exists only when the platform selects the rows
    if (g("#w-go")) g("#w-go").onclick = re;
    $$(".w-pre", stage).forEach(a => a.onclick = async e => { e.preventDefault(); win = presets[a.dataset.p](); await preview(files); });
    if (g("#pm-save")) g("#pm-save").onclick = async () => {
      const moves = $$(".pm-one:checked", stage).map(x => ({ user_id: +x.dataset.u, unit_id: +x.dataset.w }));
      if (!moves.length) { toast("Отметьте сотрудников", "error"); return; }
      try { const r = await api("/api/import/people-units", { method: "PUT", json: { moves } }); toast("Переведено: " + r.moved); await re(); } catch (e) { toast(e.message, "error"); }
    };
    if (g("#use-ai")) g("#use-ai").onchange = e => { useAi = e.target.checked; };
    $$(".dep-sg", stage).forEach(a => a.onclick = e => { e.preventDefault(); a.closest("tr").querySelector(".dep-map").value = a.dataset.unit; });
    if (g("#dep-add")) g("#dep-add").onclick = async e => {
      e.target.disabled = true;
      try { const x = await api("/api/import/add-units", { method: "POST", json: { names: JSON.parse(e.target.dataset.names) } }); Z.meta = null; toast("Добавлено отделов: " + x.created); await re(); }
      catch (er) { toast(er.message, "error"); e.target.disabled = false; }
    };
    if (g("#dep-save")) g("#dep-save").onclick = async () => {
      const map = {}, fresh = [];
      $$(".dep-map", stage).forEach(sel => {
        if (sel.value === "__new__") fresh.push(sel.dataset.name);                                              // «Создать новый отдел»: it is created from the name, then it matches by itself
        else if (sel.value !== sel.dataset.init) map[sel.dataset.key] = sel.value ? +sel.value : null;           // only what the person changed or chose
      });
      if (!Object.keys(map).length && !fresh.length) { toast("Ничего не изменено"); return; }
      try {
        if (fresh.length) { const x = await api("/api/import/add-units", { method: "POST", json: { names: fresh } }); Z.meta = null; toast("Создано отделов: " + x.created); }
        if (Object.keys(map).length) { await api("/api/import/aliases", { method: "PUT", json: { map } }); toast("Соответствие запомнено"); }
        await re();
      } catch (e) { toast(e.message, "error"); }
    };
  }
  async function preview(files) {
    stage.innerHTML = `<div class="card"><div class="skel" style="height:24px;width:40%;margin-bottom:14px"></div><div class="skel" style="height:80px"></div></div>`;
    let s;
    try { s = await send(files, 1); } catch (e) { return showDrop(e.message); }
    const stat = (n, l, k) => `<div class="stat ${k || ""}"><b class="num">${n}</b><span>${l}</span></div>`;
    const ab = s.absent_tasks;
    stage.innerHTML = `<div class="card"><h2>${icon("file")}${files.length > 1 ? files.length + " файла(ов) как одна база" : esc(files[0].name)}</h2><p class="sub">Проверка без записи: пока ничего не изменено.${files.length > 1 ? " Файлы: " + files.map(f => esc(f.name)).join(", ") + "." : ""}</p>
      <div class="stats">${stat(s.rows, "строк с задачами")}${stat(s.created, "новых задач", "k-done")}${stat(s.updated, "будет обновлено")}${stat(s.unchanged, "без изменений")}${overwrite ? stat(s.overwritten, "ваших правок будет перезаписано", s.overwritten ? "k-overdue" : "") : stat(s.kept_manual, "с вашими правками (не тронем)")}${replace && ab ? stat(ab.count, "уйдёт с дашборда (нет в базе)", ab.count ? "k-overdue" : "") : ""}</div>
      ${siteBlock(s, files)}
      ${ab && ab.count ? `<details ${ab.needs_confirm ? "open" : ""} style="margin:10px 0"><summary><b>Уйдёт с дашборда: ${ab.count} из ${ab.total} задач${ab.done ? ` (выполненных: ${ab.done})` : ""}</b> <span class="hint">— их нет в загруженных файлах (статус «Нет на сайте», ничего не удаляется)</span></summary>
        <div class="scroll-x"><table class="plain"><thead><tr><th>Код</th><th>Статус</th><th>Документ</th><th>Срок</th><th>Текст</th></tr></thead><tbody>${ab.sample.map(t => `<tr><td>${esc(t.code)}</td><td class="hint">${t.status === "done" ? "выполнено" : t.status === "info" ? "к сведению" : "не выполнено"}</td><td>${esc(t.doc_no || "")}</td><td>${t.due ? esc(t.due.split("-").reverse().join(".")) : "—"}</td><td>${esc((t.text || "").split("\n")[0].slice(0, 90))}</td></tr>`).join("")}</tbody></table></div>
        ${ab.count > ab.sample.length ? `<p class="hint">Показаны первые ${ab.sample.length}.</p>` : ""}</details>` : ""}
      ${ab && ab.needs_confirm ? `<div class="warn" style="margin:10px 0">${icon("alert")}<span><b>Уходит больше четверти задач.</b> Так бывает, если загружен не весь набор файлов (например, один раздел из трёх). Проверьте, что выбраны все файлы, или подтвердите снятие.</span><label class="switchrow" style="margin:8px 0 0"><input type="checkbox" id="conf-rm"><span><b>Подтверждаю: снять ${ab.count} задач</b></span></label></div>` : ""}
      ${s.new_people.length ? `<div class="sec-t" style="margin-top:0">Новые сотрудники (${s.new_people.length}) — будут созданы без пароля</div><p>${s.new_people.map(p => `<span class="chip" style="margin:2px">${esc(p.name)}</span>`).join("")}</p>` : ""}
      ${s.warnings.length ? `<div class="sec-t">Проверьте после загрузки (${s.warnings.length})</div><ul class="warns">${s.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div style="display:flex;gap:10px;margin-top:18px"><button class="btn pri" id="go" ${ab && ab.needs_confirm ? "disabled" : ""}>Загрузить базу</button><button class="btn" id="back">Выбрать другие файлы</button></div></div>`;
    bindSite(files);
    $("#back", stage).onclick = () => { confirmed = false; showDrop(); };
    const cr = $("#conf-rm", stage); if (cr) cr.onchange = () => { confirmed = cr.checked; $("#go", stage).disabled = !cr.checked; };
    $("#go", stage).onclick = async ev => {
      ev.target.disabled = true;
      try { const r = await send(files, 0); done(r); } catch (e) { toast(e.message, "error"); ev.target.disabled = false; }
    };
  }
  function done(r) {
    Z.meta = null;
    stage.innerHTML = `<div class="card" style="text-align:center;padding:36px"><div class="okmark"><svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg></div><h2 style="justify-content:center;font-size:20px">Готово</h2>
      <p>Новых задач: <b>${r.created}</b> · обновлено: <b>${r.updated}</b>${r.overwritten ? ` · перезаписано ваших правок: <b>${r.overwritten}</b>` : ""}${r.absent_tasks && r.absent_tasks.taken_off ? ` · снято с дашборда: <b>${r.absent_tasks.taken_off}</b>` : ""}${r.new_people.length ? ` · создано сотрудников: <b>${r.new_people.length}</b>` : ""}</p>
      <p class="hint">Теперь нажмите «Синхронизировать» в скрипте на сайте ijro: этапы запишутся к этим задачам.</p>
      ${r.new_people.length ? `<p class="hint">Чтобы сотрудники могли войти, выдайте им пароли на странице «Пользователи».</p>` : ""}
      ${r.closing ? `<div class="card" style="text-align:left;margin:14px auto;max-width:560px"><b>Даты закрытия</b><p style="margin:6px 0">Предложено: <b>${r.closing.proposed}</b>${r.closing.proposed ? ` (по прежним решениям: ${r.closing.by_history}, ИИ: ${r.closing.by_ai})` : ""}.</p>
        ${r.closing.errors.length ? `<div class="warn">${icon("alert")}<span>${r.closing.errors.map(esc).join("<br>")}</span></div>` : ""}
        ${r.closing.proposed ? `<p class="hint">Это предложения, а не окончательные даты: по прежним примерам совпадение с вашим выбором около 6 из 10. Просмотрите список и подтвердите.</p><div class="inl"><a class="btn pri" href="#/tasks?status=open&closing=proposed">Посмотреть предложенные</a><button class="btn" id="conf-all">Подтвердить все</button></div>` : ""}</div>` : ""}
      <div style="display:flex;gap:10px;justify-content:center;margin-top:16px"><a class="btn pri" href="#/dashboard">Открыть дашборд</a><a class="btn" href="#/tasks">Список задач</a><button class="btn" id="again">Загрузить ещё</button></div></div>`;
    $("#again", stage).onclick = () => route();
    const ca = $("#conf-all", stage); if (ca) ca.onclick = async () => { try { const x = await api("/api/closing/confirm", { method: "POST", json: {} }); toast("Подтверждено: " + x.confirmed); ca.disabled = true; } catch (e) { toast(e.message, "error"); } };
  }
  /* «Очистить базу»: erases every task. A copy of the database is made first; the person confirms by typing the word. */
  page.insertAdjacentHTML("beforeend", `<div class="card rise" style="--i:3;margin-top:16px;border-color:color-mix(in srgb,var(--c-overdue) 45%,var(--line))"><div class="card-head"><div><h2>Очистить базу</h2>
    <p class="sub">Стирает <b>все задачи</b> вместе с их историей и этапами, в том числе добавленные вручную и снятые с дашборда. Сотрудники, структура департамента и настройки остаются. Перед очисткой делается копия базы.</p></div>
    <button class="btn danger" id="clear-all">${icon("x")}Очистить базу</button></div></div>`);
  $("#clear-all", page).onclick = async () => {
    let info; try { info = await api("/api/import/clear"); } catch (e) { toast(e.message, "error"); return; }
    if (!info.tasks) { toast("В базе нет задач"); return; }
    const r = await formDialog({ title: "Стереть все задачи?", ok: "Стереть все задачи",
      text: `Будет стёрто задач: ${info.tasks}` + (info.manual ? `, из них добавленных вручную: ${info.manual}` : "") + (info.gone ? `, снятых с дашборда: ${info.gone}` : "") + ". Это нельзя отменить кнопкой: вернуть можно только из копии базы, которая будет сделана перед очисткой.",
      fields: [{ name: "confirm", label: `Для подтверждения введите слово ${info.word}`, required: true }],
      submit: d => api("/api/import/clear", { method: "POST", json: d }) });
    if (r) { Z.meta = null; toast("Стёрто задач: " + r.deleted + ". Копия базы: " + r.backup); route(); }
  };
  showDrop();
};
routes.import.title = "Импорт";

routes.settings = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  const s = await api("/api/settings");
  const opts = [["all", "Все задачи", "Сотрудник видит весь список, но менять статус может только у своих задач."],
                ["own", "Только свои задачи (по умолчанию)", "В списке только задачи, где сотрудник ответственный, и их статус он меняет сам. На дашборде видна общая картина."],
                ["none", "Только дашборд", "Списка задач нет: пользователь видит лишь сводные цифры и графики."]];
  const b = s.backup.latest;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Настройки</h1></div></div>
    <div class="card rise" style="--i:1;max-width:760px"><div class="card-head"><div><h2>Что видит пользователь</h2><p class="sub">Администратор всегда видит и редактирует всё.</p></div></div><div class="opts" id="opts">${opts.map(o => `<button class="opt${s.users_tasks === o[0] ? " on" : ""}" data-v="${o[0]}"><span class="rd" style="margin-top:2px"></span><div><b>${o[1]}</b><span>${o[2]}</span></div></button>`).join("")}</div></div>
    <div class="card rise" style="--i:2;max-width:760px;margin-top:16px"><div class="card-head"><div><h2>${icon("users")}Страница входа</h2><p class="sub">Можно выбрать себя из списка и ввести только пароль.</p></div></div>
      <div class="row" style="padding-top:0"><div class="lb"><b>Показывать список сотрудников</b><span>Имена видны любому, кто откроет страницу входа. Администраторы в список не попадают, они вводят логин. Выключите, если имена сотрудников не должны быть видны посторонним.</span></div><label class="sw"><input type="checkbox" id="ll"${s.login_list ? " checked" : ""}><span class="trk"><i></i></span></label></div></div>
    <div class="card rise" style="--i:3;max-width:760px;margin-top:16px" id="sync-card"></div>
    <div class="card rise" style="--i:3;max-width:760px;margin-top:16px" id="units-card"></div>
    <div class="card rise" style="--i:3;max-width:760px;margin-top:16px" id="ai-card"></div>
    <div class="card rise" style="--i:4;max-width:760px;margin-top:16px"><div class="card-head"><div><h2>${icon("db")}Резервные копии</h2><p class="sub">Автоматически каждые 6 часов, хранятся 14 последних — на этом же сервере.</p></div><button class="btn" id="bk">Сделать копию сейчас</button></div>
      <p id="bkinfo">${b.ok ? `Последняя копия проверена: <b>${esc(b.file)}</b> · задач внутри: ${b.tasks}` : `<span style="color:var(--c-overdue)">${esc(b.error || "копия не проверена")}</span>`}</p>
      <p class="hint">Копии лежат в папке данных (<code>/data/backups</code>). Периодически копируйте её на другой компьютер — иначе потеря сервера уносит и копии.</p></div>`;
  $("#opts", page).onclick = async e => {
    const o = e.target.closest(".opt"); if (!o || o.classList.contains("on")) return;
    try { await api("/api/settings", { method: "PUT", json: { users_tasks: o.dataset.v } }); $$(".opt", page).forEach(x => x.classList.toggle("on", x === o)); toast("Сохранено"); } catch (er) { toast(er.message, "error"); }
  };
  /* how tasks and their statuses come in: every choice says what it does */
  const sc = $("#sync-card", page);
  function paintSync() {
    const S = s.sync;
    const field = f => f.kind === "choice"
      ? `<div class="sec-t" style="margin-top:16px">${esc(f.title)}</div><div class="opts" data-key="${f.key}">${f.options.map(o => `<button class="opt${f.value === o.value ? " on" : ""}" data-v="${esc(o.value)}"><span class="rd" style="margin-top:2px"></span><div><b>${esc(o.label)}</b><span>${esc(o.help)}</span></div></button>`).join("")}</div>`
      : f.kind === "switch"
        ? `<div class="row" style="padding-top:8px"><div class="lb"><b>${esc(f.title)}</b><span>${esc(f.help)}</span></div><label class="sw"><input type="checkbox" class="sync-sw" data-sync="1" data-key="${f.key}"${f.value === "1" ? " checked" : ""}><span class="trk"><i></i></span></label></div>`
        : `<div class="row" style="align-items:flex-start;gap:16px"><div class="lb"><b>${esc(f.title)}</b><span>${esc(f.help)}</span></div><input type="number" min="0" max="3660" class="sync-days" data-key="${f.key}" value="${esc(f.value)}" placeholder="без ограничения" style="width:130px;flex:none"></div>`;
    const sw = (key, title, text, on) => `<div class="row" style="padding-top:0"><div class="lb"><b>${esc(title)}</b><span>${esc(text)}</span></div><label class="sw"><input type="checkbox" class="sync-sw" data-key="${key}"${on ? " checked" : ""}><span class="trk"><i></i></span></label></div>`;
    sc.innerHTML = `<div class="card-head"><div><h2>${icon("sync")}Импорт и синхронизация</h2><p class="sub">Как платформа получает задачи и их этапы. У каждого пункта написано, что он делает. Изменения действуют со следующей загрузки или синхронизации.</p></div></div>`
      + S.groups.map(g => `<div style="margin-top:22px;padding-top:6px;border-top:1px solid var(--line)"><h3 style="margin:10px 0 2px;font-size:15px">${esc(g.title)}</h3><p class="hint" style="margin:0 0 4px">${esc(g.help)}</p>
        ${S.fields.filter(f => f.group === g.id).map(field).join("")}
        ${g.id === "history" ? sw("auto_apply", "Применять изменения статуса автоматически", "Очевидное применяется само: на сайте задача выполнена, ответ дан и идёт согласование. Статус автоматически не понижается. Выключите, если хотите видеть каждое изменение на экране «Синхронизация» и применять его кнопкой.", S.auto_apply) : ""}
        ${g.id === "lists" ? sw("auto_archive", "Убирать с дашборда задачи, которых нет в списках сайта", "Относится только к режиму, когда скрипт сам скачивает списки: после полной синхронизации задачи, которых сайт больше не относит к нашим, получают статус «Нет на сайте» (не больше четверти открытых за раз, остальное ждёт вашего решения). Когда базу загружаете вы, то же делает настройка «Задачи, которых нет в загруженной базе».", S.auto_archive) : ""}</div>`).join("");
  }
  paintSync();
  sc.addEventListener("click", async e => {
    const o = e.target.closest(".opt"); if (!o || o.classList.contains("on")) return;
    const key = o.closest(".opts").dataset.key;
    try { await api("/api/settings", { method: "PUT", json: { sync: { [key]: o.dataset.v } } }); s.sync.fields.find(f => f.key === key).value = o.dataset.v; paintSync(); toast("Сохранено"); } catch (er) { toast(er.message, "error"); }
  });
  sc.addEventListener("change", async e => {
    const d = e.target.closest(".sync-days"), w = e.target.closest(".sync-sw");
    try {
      if (d) { await api("/api/settings", { method: "PUT", json: { sync: { [d.dataset.key]: d.value.trim() } } }); s.sync.fields.find(f => f.key === d.dataset.key).value = d.value.trim(); toast("Сохранено"); }
      else if (w && w.dataset.sync) { await api("/api/settings", { method: "PUT", json: { sync: { [w.dataset.key]: w.checked ? "1" : "0" } } }); s.sync.fields.find(f => f.key === w.dataset.key).value = w.checked ? "1" : "0"; toast("Сохранено"); }
      else if (w) { await api("/api/sync/settings", { method: "PUT", json: { [w.dataset.key]: w.checked } }); s.sync[w.dataset.key] = w.checked; toast("Сохранено"); }
    } catch (er) { toast(er.message, "error"); if (d) paintSync(); if (w) w.checked = !w.checked; }
  });
  /* the language model for the closing dates */
  const ac = $("#ai-card", page);
  async function paintAi() {
    const a = await api("/api/ai");
    ac.innerHTML = `<div class="card-head"><div><h2>${icon("info")}ИИ для дат закрытия</h2><p class="sub">Подбор даты закрытия без ручного чтения задач. Без ключа даты подбираются по тому, как вы ставили их раньше; ИИ (OpenAI) уточняет выбор.</p></div></div>
      <div class="row" style="padding-top:0"><div class="lb"><b>Подключить ИИ</b><span>${a.key_set ? "Ключ задан" + (a.key_from_env ? " (из переменной сервера)" : a.key_tail ? " " + esc(a.key_tail) : "") : "Ключ не задан"}</span></div><label class="sw"><input type="checkbox" id="ai-on" ${a.enabled ? "checked" : ""}><span class="trk"><i></i></span></label></div>
      <div class="fields" style="display:grid;gap:10px;margin-top:8px"><label>Ключ OpenAI (API key)<input id="ai-key" type="password" autocomplete="off" placeholder="${a.key_set ? "оставьте пустым, чтобы не менять" : "sk-..."}"></label>
        <label>Модель<input id="ai-model" list="ai-models" value="${esc(a.model)}"><datalist id="ai-models"><option value="gpt-4o-mini"><option value="gpt-4.1-mini"><option value="gpt-4o"><option value="gpt-4.1"><option value="gpt-5-mini"></datalist></label>
        <label>Адрес сервиса <span class="hint">(необязательно, для прокси; по умолчанию api.openai.com)</span><input id="ai-url" value="${esc(a.base_url)}" placeholder="https://api.openai.com/v1"></label></div>
      <div class="inl" style="margin-top:12px"><button class="btn pri" id="ai-save">Сохранить</button><button class="btn" id="ai-test">Проверить связь</button>${a.key_set && !a.key_from_env ? '<button class="btn" id="ai-clear">Удалить ключ</button>' : ""}<span id="ai-msg" class="hint"></span></div>
      <p class="hint" style="margin-top:10px">Ключ хранится на сервере в базе данных и в браузер не возвращается. Модель получает только тексты задач и даты. ${a.history.accuracy != null ? `На ваших прежних решениях (${a.history.history} задач) подбор по аналогии выбирает ваш шаблон даты в <b>${Math.round(a.history.accuracy * 100)}%</b> случаев для задач из нового месяца (если всегда брать самый частый — ${Math.round(a.history.always_the_most_common * 100)}%). Это немного: даты нужно просматривать. Правила, которые соблюдаются всегда: не раньше «сразу» и не ближе <b>${a.history.buffer_days} дн.</b> к официальному сроку (при близком сроке запас меньше).` : "Для подбора по аналогии нужно не меньше 20 задач с вашей датой закрытия."}</p>`;
    const msg = (t, bad) => { const m = $("#ai-msg", ac); m.textContent = t; m.style.color = bad ? "var(--c-overdue)" : ""; };
    $("#ai-save", ac).onclick = async () => { try { await api("/api/ai", { method: "PUT", json: { enabled: $("#ai-on", ac).checked, model: $("#ai-model", ac).value, base_url: $("#ai-url", ac).value, key: $("#ai-key", ac).value } }); toast("Сохранено"); paintAi(); } catch (e) { toast(e.message, "error"); } };
    $("#ai-test", ac).onclick = async () => { msg("Проверяю…"); try { await api("/api/ai", { method: "PUT", json: { model: $("#ai-model", ac).value, base_url: $("#ai-url", ac).value, key: $("#ai-key", ac).value } }); const r = await api("/api/ai/test", { method: "POST", json: {} }); msg(r.message, !r.ok); } catch (e) { msg(e.message, true); } };
    const cl = $("#ai-clear", ac); if (cl) cl.onclick = async () => { if (!confirm("Удалить сохранённый ключ?")) return; await api("/api/ai", { method: "PUT", json: { clear_key: true, enabled: false } }); paintAi(); };
  }
  paintAi();
  /* structure of the department */
  const uc = $("#units-card", page);
  async function paintStructure() {
    const items = (await api("/api/units")).items;
    uc.innerHTML = `<div class="card-head"><div><h2>${icon("stack")}Структура департамента</h2><p class="sub">Управления и отделы. К ним привязываются сотрудники (страница «Пользователи»), по ним строится дашборд.</p></div><button class="btn sm" id="u-add">${icon("plus")}Управление</button></div>` +
      items.map(u => `<div class="unit-row ${u.level ? "kid" : "mgmt"}${u.active ? "" : " off"}" data-id="${u.id}"><span class="unum">${esc(u.num)}</span><span class="nm">${esc(u.name)}</span><span class="ppl">${u.people ? u.people + " " + plural(u.people, "сотрудник", "сотрудника", "сотрудников") : ""}</span>
        <span class="acts"><button class="btn sm" data-a="ren">Изменить</button>${u.level ? "" : `<button class="btn sm" data-a="add">+ Отдел</button>`}<button class="btn sm" data-a="vis">${u.active ? "Скрыть" : "Показать"}</button>${u.people || items.some(x => x.parent_id === u.id) ? "" : `<button class="btn sm danger" data-a="del">Удалить</button>`}</span></div>`).join("");
    const ask = (title, fields, submit) => formDialog({ title, fields, submit });
    $("#u-add", uc).onclick = async () => { if (await ask("Новое управление", [{ name: "name", label: "Название", required: true }, { name: "num", label: "Номер", hint: "Пусто — следующий римский номер" }], d => api("/api/units", { method: "POST", json: d }))) { Z.meta = null; toast("Управление добавлено"); paintStructure(); } };
    uc.onclick = async e => {
      const b = e.target.closest("[data-a]"); if (!b) return;
      const u = items.find(x => x.id === +b.closest(".unit-row").dataset.id);
      let ok = false;
      if (b.dataset.a === "ren") ok = await ask("Изменить", [{ name: "num", label: "Номер", value: u.num }, { name: "name", label: "Название", value: u.name, required: true }], d => api("/api/units/" + u.id, { method: "PATCH", json: d }));
      else if (b.dataset.a === "add") ok = await ask("Новый отдел в «" + (u.name.length > 40 ? u.name.slice(0, 38) + "…" : u.name) + "»", [{ name: "name", label: "Название", required: true }, { name: "num", label: "Номер", hint: "Пусто — следующий по порядку" }], d => api("/api/units", { method: "POST", json: Object.assign({}, d, { parent_id: u.id }) }));
      else if (b.dataset.a === "vis") { try { await api("/api/units/" + u.id, { method: "PATCH", json: { active: !u.active } }); ok = true; } catch (er) { toast(er.message, "error"); } }
      else if (b.dataset.a === "del") { if (await formDialog({ title: "Удалить «" + u.name.slice(0, 50) + "»?", text: "Это нельзя отменить. Удалить можно только пустой отдел; иначе скройте его.", ok: "Удалить", fields: [] })) { try { await api("/api/units/" + u.id, { method: "DELETE" }); ok = true; } catch (er) { toast(er.message, "error"); } } }
      if (ok) { Z.meta = null; toast("Сохранено"); paintStructure(); }
    };
  }
  await paintStructure();
  $("#ll", page).onchange = async e => { try { await api("/api/settings", { method: "PUT", json: { login_list: e.target.checked } }); toast(e.target.checked ? "Список на странице входа включён" : "Список на странице входа выключен"); } catch (er) { toast(er.message, "error"); e.target.checked = !e.target.checked; } };
  $("#bk", page).onclick = async ev => {
    ev.target.disabled = true;
    try { const r = await api("/api/backup", { method: "POST", json: {} }); toast("Копия создана: " + r.file); route(); } catch (er) { toast(er.message, "error"); ev.target.disabled = false; }
  };
};
routes.settings.title = "Настройки";
