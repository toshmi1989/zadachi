"use strict";
/* Administrator pages: users, Excel import, settings. */

routes.users = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  let items = (await api("/api/users")).items;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Пользователи</h1><p>Сотрудники из выгрузки появляются здесь сами. Чтобы человек мог войти — выдайте ему пароль.</p></div>
    <button class="btn pri" id="add">${icon("plus")}Добавить пользователя</button></div><div class="ulist" id="ul"></div>`;
  const paint = () => {
    $("#ul", page).innerHTML = items.map((u, i) => `<div class="card ucard rise${u.active ? "" : " off"}" style="--i:${Math.min(i, 12) + 1}" data-id="${u.id}">
      <div class="hd">${avatar(u.id, u.name, "lg")}<div style="min-width:0"><b>${esc(u.name)}</b><small>${esc(u.login)} · <span class="chip ${u.role === "admin" ? "progress" : ""}" style="padding:1px 8px">${u.role === "admin" ? "Администратор" : "Пользователь"}</span>${u.active ? "" : " · отключён"}</small></div></div>
      <div class="st"><span><b class="num">${u.open}</b>в работе</span><span><b class="num">${u.tasks}</b>всего задач</span></div>
      <div class="acts"><button class="btn sm" data-a="edit">Изменить</button><button class="btn sm" data-a="pw">${icon("key")}Выдать пароль</button>${u.tasks ? `<button class="btn sm" data-a="tasks">Задачи</button>` : ""}</div></div>`).join("");
  };
  paint();
  const reload = async () => { items = (await api("/api/users")).items; Z.meta = null; paint(); };
  const showPw = (name, login, pw) => infoDialog("Пароль выдан", `<p class="mt">Покажите его сотруднику <b>${esc(name)}</b> (логин <b>${esc(login)}</b>). Пароль виден только сейчас — потом его можно только выдать заново.</p>
    <div class="pw"><span id="pwv">${esc(pw)}</span><button class="btn sm" id="cp">${icon("copy")}Копировать</button></div>`).then(() => {});
  $("#add", page).onclick = async () => {
    const r = await formDialog({ title: "Новый пользователь", ok: "Создать", fields: [
      { name: "name", label: "Имя (как в выгрузке Excel)", required: true, hint: "Например: Bilalov Baxodir Erkinovich. Задачи с таким именем привяжутся автоматически." },
      { name: "login", label: "Логин", required: true, hint: "Латиница, цифры, точка, дефис" },
      { name: "role", label: "Роль", type: "select", value: "user", options: [["user", "Пользователь — видит дашборд"], ["admin", "Администратор — управляет всем"]] },
      { name: "password", label: "Пароль", type: "text", hint: "Оставьте пустым — система придумает сама" }],
      submit: d => api("/api/users", { method: "POST", json: d }).then(res => Object.assign(res, { _d: d })) });
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
      { name: "role", label: "Роль", type: "select", value: u.role, options: [["user", "Пользователь"], ["admin", "Администратор"]] },
      { name: "active", label: "Доступ", type: "select", value: u.active ? "1" : "0", options: [["1", "Активен"], ["0", "Отключён (войти нельзя, задачи остаются)"]] }],
      submit: d => api("/api/users/" + u.id, { method: "PATCH", json: Object.assign({}, d, { active: d.active === "1" }) }) });
    if (r) { toast("Сохранено"); reload(); }
  };
};
routes.users.title = "Пользователи";

routes.import = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  const hist = (await api("/api/import/history")).items;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Импорт из Excel</h1><p>Загрузите выгрузку — задачи появятся в списке и на дашборде. Повторная загрузка обновляет задачи по коду и не затирает ваши правки.</p></div></div>
    <div id="stage" class="rise" style="--i:1"></div>
    <div class="card rise" style="--i:2;margin-top:16px"><div class="card-head"><h2>Последние загрузки</h2></div>${hist.length ? `<table class="plain"><thead><tr><th>Когда</th><th>Файл</th><th>Кто</th><th>Новых</th><th>Обновлено</th></tr></thead><tbody>${hist.map(h => `<tr><td>${esc(h.created_at.slice(0, 16))}</td><td>${esc(h.filename)}</td><td>${esc(h.by || "")}</td><td class="num">${h.summary.created}</td><td class="num">${h.summary.updated}</td></tr>`).join("")}</tbody></table>` : '<p class="hint">Загрузок ещё не было.</p>'}</div>`;
  const stage = $("#stage", page);
  const dropHtml = (err) => `<label class="drop" id="drop" for="file"><div class="big">${icon("upload")}</div><b>Перетащите файл Excel сюда</b><p class="hint" style="margin:4px 0 0">или нажмите, чтобы выбрать · .xlsx, до 15 МБ</p>${err ? `<p class="err" style="margin-top:10px">${esc(err)}</p>` : ""}<input type="file" id="file" accept=".xlsx" hidden></label>`;
  function showDrop(err) {
    stage.innerHTML = dropHtml(err);
    const drop = $("#drop", stage), inp = $("#file", stage);
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => { if (e.dataTransfer.files[0]) preview(e.dataTransfer.files[0]); });
    inp.onchange = () => { if (inp.files[0]) preview(inp.files[0]); };
  }
  async function send(file, dry) { const f = new FormData(); f.append("file", file); return api("/api/import?dry=" + dry, { method: "POST", form: f }); }
  async function preview(file) {
    stage.innerHTML = `<div class="card"><div class="skel" style="height:24px;width:40%;margin-bottom:14px"></div><div class="skel" style="height:80px"></div></div>`;
    let s;
    try { s = await send(file, 1); } catch (e) { return showDrop(e.message); }
    const stat = (n, l, k) => `<div class="stat ${k || ""}"><b class="num">${n}</b><span>${l}</span></div>`;
    stage.innerHTML = `<div class="card"><h2>${icon("file")}${esc(file.name)}</h2><p class="sub">Проверка без записи: пока ничего не изменено.</p>
      <div class="stats">${stat(s.rows, "строк с задачами")}${stat(s.created, "новых задач", "k-done")}${stat(s.updated, "будет обновлено")}${stat(s.unchanged, "без изменений")}${stat(s.kept_manual, "с вашими правками (не тронем)")}</div>
      ${s.new_people.length ? `<div class="sec-t" style="margin-top:0">Новые сотрудники (${s.new_people.length}) — будут созданы без пароля</div><p>${s.new_people.map(p => `<span class="chip" style="margin:2px">${esc(p.name)}</span>`).join("")}</p>` : ""}
      ${s.warnings.length ? `<div class="sec-t">Проверьте после загрузки (${s.warnings.length})</div><ul class="warns">${s.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div style="display:flex;gap:10px;margin-top:18px"><button class="btn pri" id="go">Загрузить</button><button class="btn" id="back">Выбрать другой файл</button></div></div>`;
    $("#back", stage).onclick = () => showDrop();
    $("#go", stage).onclick = async ev => {
      ev.target.disabled = true;
      try { const r = await send(file, 0); done(r); } catch (e) { toast(e.message, "error"); ev.target.disabled = false; }
    };
  }
  function done(r) {
    Z.meta = null;
    stage.innerHTML = `<div class="card" style="text-align:center;padding:36px"><div class="okmark"><svg viewBox="0 0 24 24"><path d="m5 12 5 5 9-10"/></svg></div><h2 style="justify-content:center;font-size:20px">Готово</h2>
      <p>Новых задач: <b>${r.created}</b> · обновлено: <b>${r.updated}</b>${r.new_people.length ? ` · создано сотрудников: <b>${r.new_people.length}</b>` : ""}</p>
      ${r.new_people.length ? `<p class="hint">Чтобы сотрудники могли войти, выдайте им пароли на странице «Пользователи».</p>` : ""}
      <div style="display:flex;gap:10px;justify-content:center;margin-top:16px"><a class="btn pri" href="#/dashboard">Открыть дашборд</a><a class="btn" href="#/tasks">Список задач</a><button class="btn" id="again">Загрузить ещё</button></div></div>`;
    $("#again", stage).onclick = () => route();
  }
  showDrop();
};
routes.import.title = "Импорт";

routes.settings = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  const s = await api("/api/settings");
  const opts = [["all", "Все задачи, только просмотр", "Пользователь видит весь список и может переходить с дашборда к задачам, но не может ничего менять."],
                ["own", "Только свои задачи", "На дашборде видны все цифры, а в списке — только задачи, где он ответственный."],
                ["none", "Только дашборд", "Списка задач нет: пользователь видит лишь сводные цифры и графики."]];
  const b = s.backup.latest;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Настройки</h1></div></div>
    <div class="card rise" style="--i:1;max-width:760px"><div class="card-head"><div><h2>Что видит пользователь</h2><p class="sub">Администратор всегда видит и редактирует всё.</p></div></div><div class="opts" id="opts">${opts.map(o => `<button class="opt${s.users_tasks === o[0] ? " on" : ""}" data-v="${o[0]}"><span class="rd" style="margin-top:2px"></span><div><b>${o[1]}</b><span>${o[2]}</span></div></button>`).join("")}</div></div>
    <div class="card rise" style="--i:2;max-width:760px;margin-top:16px"><div class="card-head"><div><h2>${icon("db")}Резервные копии</h2><p class="sub">Автоматически каждые 6 часов, хранятся 14 последних — на этом же сервере.</p></div><button class="btn" id="bk">Сделать копию сейчас</button></div>
      <p id="bkinfo">${b.ok ? `Последняя копия проверена: <b>${esc(b.file)}</b> · задач внутри: ${b.tasks}` : `<span style="color:var(--c-overdue)">${esc(b.error || "копия не проверена")}</span>`}</p>
      <p class="hint">Копии лежат в папке данных (<code>/data/backups</code>). Периодически копируйте её на другой компьютер — иначе потеря сервера уносит и копии.</p></div>`;
  $("#opts", page).onclick = async e => {
    const o = e.target.closest(".opt"); if (!o || o.classList.contains("on")) return;
    try { await api("/api/settings", { method: "PUT", json: { users_tasks: o.dataset.v } }); $$(".opt", page).forEach(x => x.classList.toggle("on", x === o)); toast("Сохранено"); } catch (er) { toast(er.message, "error"); }
  };
  $("#bk", page).onclick = async ev => {
    ev.target.disabled = true;
    try { const r = await api("/api/backup", { method: "POST", json: {} }); toast("Копия создана: " + r.file); route(); } catch (er) { toast(er.message, "error"); ev.target.disabled = false; }
  };
};
routes.settings.title = "Настройки";
