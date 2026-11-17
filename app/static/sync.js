"use strict";
/* Synchronisation with edo.ijro.uz: install the browser collector, keys, card address, what would change. */

const CHANGE_LABEL = { to_done: "Выполнена на сайте", to_progress: "Ответ дан на сайте", to_todo: "В работе без ответа", site_open_we_done: "У нас выполнена, на сайте нет", not_found: "Не найдена на сайте", unknown: "Неизвестный статус" };
const CHANGE_CHIP = { to_done: "done", to_progress: "progress", to_todo: "todo", site_open_we_done: "overdue", not_found: "week", unknown: "week" };

routes.sync = async function (page) {
  if (!isAdmin()) throw new Error("Раздел доступен только администратору");
  let [rev, keys, stale] = await Promise.all([api("/api/sync/review"), api("/api/sync/keys"), api("/api/sync/stale")]);
  let filter = "apply", chosen = new Set();
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Синхронизация с ijro.uz</h1><p>Статусы и ответы по задачам берутся с официального сайта через ваш браузер. Платформа сама на сайт не заходит и ничего там не меняет.</p></div></div>
    <div class="two"><div class="card rise" style="--i:1" id="s-how"></div><div class="card rise" style="--i:2" id="s-key"></div></div>
    <div class="card rise" style="--i:3;margin-bottom:16px" id="s-stale"></div>
    <div class="card rise" style="--i:3;margin-bottom:16px" id="s-rev"></div>
    <div class="card rise" style="--i:4" id="s-runs"></div>`;

  /* ---- how it works + install ---- */
  $("#s-how", page).innerHTML = `<div class="card-head"><div><h2>${icon("sync")}Как пользоваться</h2><p class="sub">Один раз настроить, потом нажимать кнопку</p></div></div>
    <ol class="steps"><li>Поставьте в браузер расширение <b>Tampermonkey</b> (Chrome, Edge, Firefox).</li>
    <li><a class="btn sm pri" href="/ijro-sync.user.js" target="_blank" rel="noopener">${icon("download")}Установить скрипт</a> Tampermonkey предложит подтвердить установку.</li>
    <li>Справа создайте <b>ключ</b> и вставьте его в скрипте: на сайте ijro появится кнопка «⇄ Задачи», в ней «Ключ…».</li>
    <li>Войдите на <b>edo.ijro.uz</b> как обычно (ЭЦП или OneID), откройте любой раздел «Топшириқлар» и нажмите «Синхронизировать».</li>
    <li>Вернитесь сюда: ниже список того, что изменится. Решаете вы.</li></ol>
    <p class="hint" style="margin-top:12px">Скрипт только читает. Ваш вход на ijro остаётся в браузере и никуда не передаётся: платформа получает лишь статусы и ответы по вашим открытым задачам.</p>`;

  /* ---- keys and card address ---- */
  const kb = $("#s-key", page);
  const paintKeys = () => {
    kb.innerHTML = `<div class="card-head"><div><h2>${icon("key")}Ключ и адрес карточки</h2><p class="sub">Ключ открывает только приём данных на этой платформе</p></div></div>
      <div class="inl"><input id="k-name" placeholder="Название, например «Ноутбук Ахмедова»" style="flex:1;min-width:200px"><button class="btn" id="k-new">Создать ключ</button></div>
      <div id="k-shown"></div>
      ${keys.items.length ? `<div class="scroll-x"><table class="plain" style="margin-top:12px"><thead><tr><th>Ключ</th><th>Создан</th><th>Последний раз</th><th></th></tr></thead><tbody>${keys.items.map(k => `<tr class="${k.revoked ? "off" : ""}"><td>${esc(k.name)}${k.revoked ? ' <span class="chip todo">отозван</span>' : ""}</td><td class="num">${esc(k.created_at.slice(0, 10))}</td><td class="num">${k.last_used ? esc(k.last_used.slice(0, 16)) : "—"}</td><td>${k.revoked ? "" : `<button class="btn sm danger" data-rev="${k.id}">Отозвать</button>`}</td></tr>`).join("")}</tbody></table></div>` : ""}
      <div class="blk" style="margin-top:18px"><div class="k">Адрес карточки задачи на ijro<small>чтобы по клику открывалась именно задача</small></div>
        <div class="inl" style="margin-bottom:8px"><input id="k-url" placeholder="Вставьте адрес открытой карточки любой задачи с ijro" style="flex:1;min-width:240px"><button class="btn sm pri" id="k-detect" type="button">Определить</button></div>
        <p class="hint" style="margin:0 0 10px">Проще всего: откройте на ijro любую задачу, которую уже проверила синхронизация, скопируйте адрес из строки браузера и вставьте сюда. Шаблон определится сам.</p>
        <div class="inl"><input id="k-tpl" placeholder="https://edo.ijro.uz/assignments/{section_path}/current-user/main/tasks/all/{id}" value="${esc(rev.card_tpl || "")}" style="flex:1;min-width:240px"><button class="btn sm" id="k-tpl-save">Сохранить</button></div>
        <p class="hint" style="margin:6px 0 0">Откройте любую задачу на ijro, скопируйте адрес из строки браузера и вместо номера задачи впишите <span class="code">{id}</span>, а вместо названия раздела <span class="code">{section_path}</span> (оно подставится само: president-assignments, government-assignments, president-adminstration-assignments). Пока адрес не задан, ссылка ведёт в нужный раздел.</p></div>`;
    $("#k-new", kb).onclick = async () => {
      const name = $("#k-name", kb).value.trim() || "Ключ";
      try {
        const r = await api("/api/sync/keys", { method: "POST", json: { name } });
        keys = await api("/api/sync/keys"); paintKeys();
        $("#k-shown", kb).innerHTML = `<div class="warn">${icon("alert")}<span>Ключ показан один раз. Скопируйте и вставьте в скрипте («⇄ Задачи» → «Ключ…»).</span></div><div class="pw" style="font-size:13px;word-break:break-all"><span>${esc(r.key)}</span><button class="btn sm" id="k-copy">${icon("copy")}Копировать</button></div>`;
        $("#k-copy", kb).onclick = () => copyText(r.key);
      } catch (e) { toast(e.message, "error"); }
    };
    $$("[data-rev]", kb).forEach(b => b.onclick = async () => {
      if (!await formDialog({ title: "Отозвать ключ?", text: "Скрипт с этим ключом перестанет передавать данные. Это можно сделать в любой момент заново, создав новый ключ.", ok: "Отозвать", fields: [] })) return;
      await api("/api/sync/keys/" + b.dataset.rev, { method: "DELETE" }); keys = await api("/api/sync/keys"); paintKeys(); toast("Ключ отозван");
    });
    $("#k-detect", kb).onclick = async () => {
      const url = $("#k-url", kb).value.trim(); if (!url) { toast("Вставьте адрес карточки", "error"); return; }
      try {
        const r = await api("/api/sync/detect-template", { method: "POST", json: { url } });
        $("#k-tpl", kb).value = r.template;
        toast(`Шаблон определён по задаче ${r.code}. Проверьте и нажмите «Сохранить»`);
      } catch (e) { toast(e.message, "error"); }
    };
    $("#k-tpl-save", kb).onclick = async () => {
      try { await api("/api/sync/settings", { method: "PUT", json: { card_tpl: $("#k-tpl", kb).value } }); rev = await api("/api/sync/review"); toast("Адрес сохранён"); paintRev(); } catch (e) { toast(e.message, "error"); }
    };
  };
  paintKeys();

  /* ---- what would change ---- */
  const c = () => rev.counts;
  const FILTERS = [["apply", "К применению"], ["to_done", "Выполнены на сайте"], ["to_progress", "Ответ дан"], ["site_open_we_done", "Расходятся"], ["not_found", "Не найдены"], ["unknown", "Неизвестные"], ["all", "Все"]];
  const matches = i => filter === "all" || (filter === "apply" ? !!i.proposed && ["to_done", "to_progress", "to_todo"].includes(i.change) : i.change === filter);
  /* ---- tasks the site no longer lists as ours ---- */
  function paintStale() {
    const box = $("#s-stale", page), n = stale.items.length;
    box.innerHTML = `<label class="switchrow"><input type="checkbox" id="auto-arch" ${stale.auto_archive ? "checked" : ""}><span><b>Убирать с дашборда задачи, которых нет в выгрузках сайта</b> — после полной синхронизации открытые задачи, которые сайт не относит к нашим (другой вид документа, не наш отдел, соисполнитель), получают статус «Нет на сайте» и пропадают с дашборда. Ничего не удаляется: если задача снова появится в выгрузке, она вернётся сама. Если таких больше четверти открытых, они ждут вашего решения здесь.</span></label>`
      + (n ? `<div class="warn" style="margin:12px 0">${icon("alert")}<span>Ждут решения: <b>${n}</b> задач не относятся к нашим выгрузкам.</span></div><div class="scroll-x" style="max-height:340px;overflow:auto"><table class="plain"><thead><tr><th>Задача</th><th>Вид</th><th>Срок</th><th>Ответственный</th></tr></thead><tbody>${stale.items.map(i => `<tr><td><b>${esc(i.code)}</b> <span class="hint">${esc(i.doc_no)}</span><div style="color:var(--text-2);font-size:13px">${esc(i.text)}</div></td><td>${esc(i.kind)}</td><td>${esc(i.due || "")}</td><td>${esc(i.assignee || "")}</td></tr>`).join("")}</tbody></table></div>
        <div class="inl" style="margin-top:12px"><button class="btn pri" id="arch-go">Убрать с дашборда (${n})</button><span class="hint">Статус «Нет на сайте»; задачи можно найти в списке по этому статусу.</span></div>` : "");
    $("#auto-arch", page).onchange = async e => { try { await api("/api/sync/settings", { method: "PUT", json: { auto_archive: e.target.checked } }); stale.auto_archive = e.target.checked; toast(e.target.checked ? "Автоматическое снятие включено" : "Автоматическое снятие выключено: решения будут ждать здесь"); } catch (er) { toast(er.message, "error"); e.target.checked = !e.target.checked; } };
    const go = $("#arch-go", page);
    if (go) go.onclick = async () => { go.disabled = true; try { const r = await api("/api/sync/archive", { method: "POST", json: {} }); toast("Убрано с дашборда: " + r.archived); stale = await api("/api/sync/stale"); paintStale(); } catch (er) { toast(er.message, "error"); go.disabled = false; } };
  }
  function paintRev() {
    const k = c(), list = rev.items.filter(matches);
    if (!k.checked) {
      $("#s-rev", page).innerHTML = `<div class="card-head"><h2>Что изменится</h2></div><div class="empty" style="padding:30px"><div class="big">🔄</div><b>Синхронизаций ещё не было</b><p>Когда вы нажмёте «Синхронизировать» на сайте ijro, здесь появится список изменений.</p></div>`;
      return;
    }
    const ago = rev.runs[0] ? rev.runs[0].started_at.slice(0, 16) : "";
    $("#s-rev", page).innerHTML = `<label class="switchrow"><input type="checkbox" id="auto-apply" ${rev.auto_apply ? "checked" : ""}><span><b>Применять автоматически</b> — после каждой проверки ясные изменения вносятся сами: ответ введён → «В работе», снято с контроля → «Выполнено», «маълумот учун қабул қилинди» → задача снова открыта с новым сроком. Остальное остаётся на ручную проверку.</span></label><div class="card-head"><div><h2>Что изменится</h2><p class="sub">Последняя синхронизация: ${esc(ago)}. Проверено ${k.checked} из ${rev.open_total} открытых задач, найдено на сайте ${k.found}.</p></div><div id="f-seg"></div></div>
      <div class="stats" style="margin:0 0 14px">
        <div class="stat"><b class="num">${k.to_done}</b><span>выполнены на сайте</span></div><div class="stat"><b class="num">${k.to_progress}</b><span>ответ дан, идёт согласование</span></div>
        <div class="stat"><b class="num">${k.site_open_we_done}</b><span>у нас выполнено, на сайте нет</span></div><div class="stat"><b class="num">${k.not_found}</b><span>не найдены на сайте</span></div><div class="stat"><b class="num">${k.unknown}</b><span>статус не определён</span></div></div>
      ${list.length ? `<div class="scroll-x"><table class="plain"><thead><tr><th style="width:34px"><input type="checkbox" class="cb" id="r-all"></th><th>Задача</th><th>У нас</th><th>На сайте</th><th></th></tr></thead><tbody>${list.map(i => `<tr data-id="${i.task_id}">
        <td>${i.proposed && ["to_done", "to_progress", "to_todo"].includes(i.change) ? `<input type="checkbox" class="cb r-one" ${chosen.has(i.task_id) ? "checked" : ""}>` : ""}</td>
        <td><b>${esc(i.code)}</b> <span class="hint">${esc(i.doc_no)}${i.point ? " · " + esc(i.point) : ""}</span><div style="color:var(--text-2);font-size:13px;max-width:460px">${esc(i.text.length > 110 ? i.text.slice(0, 108) + "…" : i.text)}</div>${i.assignee ? `<span class="hint">${esc(i.assignee)}</span>` : ""}</td>
        <td><span class="chip ${i.our_status === "done" ? "done" : i.our_status === "info" ? "info" : i.our_status === "progress" ? "progress" : "todo"}">${esc(ST[i.our_status])}</span></td>
        <td><span class="chip ${CHANGE_CHIP[i.change] || "todo"}">${esc(i.site_label)}</span>${i.note ? `<div class="hint">${esc(i.note)}</div>` : ""}</td>
        <td><a class="btn sm" href="${esc(i.link)}" target="_blank" rel="noopener noreferrer" ${i.exact_link ? "" : `data-copycode="${esc(i.code)}"`} data-tip="${i.exact_link ? "Открыть задачу на ijro" : "Откроется раздел на ijro, код задачи скопируется"}">${icon("ext")}ijro</a></td></tr>`).join("")}</tbody></table></div>
        <div class="inl" style="margin-top:14px"><button class="btn pri" id="r-apply">Применить выбранные (<span id="r-n">0</span>)</button><button class="btn" id="r-done">Применить все «Выполнено» (${k.to_done})</button></div>`
        : `<div class="empty" style="padding:24px"><div class="big">✅</div><b>В этой группе ничего нет</b></div>`}`;
    $("#f-seg", page).appendChild(seg(FILTERS.map(f => [f[0], f[1]]), filter, v => { filter = v; chosen = new Set(); paintRev(); }));
    $("#auto-apply", page).onchange = async e => { try { await api("/api/sync/settings", { method: "PUT", json: { auto_apply: e.target.checked } }); rev.auto_apply = e.target.checked; toast(e.target.checked ? "Автоприменение включено" : "Автоприменение выключено: изменения — только вручную"); } catch (er) { toast(er.message, "error"); e.target.checked = !e.target.checked; } };
    const upd = () => { const n = $("#r-n", page); if (n) n.textContent = chosen.size; };
    $$(".r-one", page).forEach(cb => cb.onchange = () => { const id = +cb.closest("tr").dataset.id; cb.checked ? chosen.add(id) : chosen.delete(id); upd(); });
    const all = $("#r-all", page); if (all) all.onchange = () => { $$(".r-one", page).forEach(cb => { cb.checked = all.checked; const id = +cb.closest("tr").dataset.id; all.checked ? chosen.add(id) : chosen.delete(id); }); upd(); };
    const doApply = async ids => {
      if (!ids.length) { toast("Отметьте задачи", "error"); return; }
      if (!await formDialog({ title: `Изменить статус у ${ids.length} ${plural(ids.length, "задачи", "задач", "задач")}?`, text: "Статусы станут такими, как на сайте. Каждое изменение запишется в историю задачи.", ok: "Применить", fields: [] })) return;
      try { const r = await api("/api/sync/apply", { method: "POST", json: { task_ids: ids } }); toast(`Изменено задач: ${r.applied}`); chosen = new Set(); rev = await api("/api/sync/review"); paintRev(); } catch (e) { toast(e.message, "error"); }
    };
    const ap = $("#r-apply", page); if (ap) ap.onclick = () => doApply([...chosen]);
    const dn = $("#r-done", page); if (dn) dn.onclick = () => doApply(rev.items.filter(i => i.change === "to_done").map(i => i.task_id));
    $$("tbody tr[data-id]", page).forEach(tr => tr.addEventListener("click", e => { if (e.target.closest("a,input,button")) return; openTask(+tr.dataset.id); }));
  }
  paintRev();
  paintStale();

  /* ---- history of runs ---- */
  $("#s-runs", page).innerHTML = `<div class="card-head"><h2>Запуски</h2></div>` + (rev.runs.length ? `<div class="scroll-x"><table class="plain"><thead><tr><th>Когда</th><th>Ключ</th><th>Ожидалось</th><th>Получено</th><th>Найдено на сайте</th></tr></thead><tbody>${rev.runs.map(r => `<tr><td class="num">${esc(r.started_at.slice(0, 16))}</td><td>${esc(r.key_name || "")}</td><td class="num">${r.expected}</td><td class="num">${r.received}</td><td class="num">${r.found}</td></tr>`).join("")}</tbody></table></div>` : '<p class="hint">Запусков ещё не было.</p>');
};
routes.sync.title = "Синхронизация";
