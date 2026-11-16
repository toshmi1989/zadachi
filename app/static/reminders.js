"use strict";
/* Reminders: Telegram linking, personal rules, defaults for everyone (administrator), preview and log. */

const DAY_CHIPS = [14, 7, 5, 3, 2, 1, 0];
const WD = [[1, "Пн"], [2, "Вт"], [3, "Ср"], [4, "Чт"], [5, "Пт"], [6, "Сб"], [7, "Вс"]];
const OVERDUE_OPTS = [[0, "не напоминать"], [1, "каждый день"], [2, "через день"], [3, "раз в 3 дня"], [7, "раз в неделю"]];
const dayLabel = n => n === 0 ? "в день срока" : n === 1 ? "за 1 день" : `за ${n} дн.`;
const swHtml = (id, on) => `<label class="sw"><input type="checkbox" id="${id}"${on ? " checked" : ""}><span class="trk"><i></i></span></label>`;
const chipsHtml = (vals, sel, lab, cls) => `<div class="tgcs">${vals.map(v => `<button type="button" class="tgc ${cls || ""}${sel.includes(v) ? " on" : ""}" data-v="${v}">${lab(v)}</button>`).join("")}</div>`;
const optsHtml = (opts, cur) => opts.map(o => `<option value="${o[0]}"${Number(o[0]) === Number(cur) ? " selected" : ""}>${o[1]}</option>`).join("");
/* several quick changes (a chip, then the time) are sent as one request: pending patches are merged, not overwritten */
function debounced(send, ms) { let t, pending = {}; return patch => { Object.assign(pending, patch); clearTimeout(t); t = setTimeout(() => { const p = pending; pending = {}; send(p); }, ms || 450); }; }
const saved = () => toast("Сохранено");

routes.reminders = async function (page) {
  const admin = isAdmin();
  const [tg, rm] = await Promise.all([api("/api/telegram"), api("/api/reminders/me")]);
  const g = admin ? await api("/api/reminders/settings") : null;
  let timer = null;
  const cleanup = () => { if (timer) clearInterval(timer); };

  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Напоминания</h1><p>Бот в Telegram присылает одну сводку в день: что просрочено и у чего скоро срок.</p></div></div>
    <div class="two"><div class="card rise" style="--i:1" id="c-tg"></div><div class="card rise" style="--i:2" id="c-me"></div></div>
    ${admin ? `<div class="card rise" style="--i:3;margin-bottom:16px" id="c-g"></div><div class="two"><div class="card rise" style="--i:4" id="c-pv"></div><div class="card rise" style="--i:5" id="c-log"></div></div>` : ""}`;

  /* ---------- Telegram ---------- */
  function paintTg(s) {
    const box = $("#c-tg", page);
    let body;
    if (!s.configured) {
      body = admin ? `<div class="warn">${icon("alert")}<span>Бот ещё не подключён.</span></div>
        <ol class="steps"><li>В Telegram откройте <b>@BotFather</b>, отправьте <span class="code">/newbot</span> и придумайте имя.</li>
        <li>Токен, который он пришлёт, впишите на сервере в файл <span class="code">.env</span> строкой <span class="code">TELEGRAM_BOT_TOKEN=…</span>. Никому его не отправляйте и не вставляйте в чаты.</li>
        <li>Перезапустите: <span class="code">python3 manage.py deploy zadachi</span>.</li></ol>
        <p class="hint">Нужен отдельный бот именно для этой платформы: один токен нельзя использовать в двух приложениях сразу.</p>` : `<p class="hint">Администратор ещё не подключил бота. Когда это произойдёт, здесь появится кнопка привязки.</p>`;
    } else if (s.linked) {
      body = `<div class="tgbox"><span class="tgico ok">${icon("check")}</span><div><b>Telegram привязан</b><br><span class="hint">${s.username ? "@" + esc(s.username) + " · " : ""}бот @${esc(s.bot)}</span></div></div>
        <div class="inl" style="margin-top:16px"><button class="btn" id="tg-test">${icon("send")}Отправить проверочное сообщение</button><button class="btn danger" id="tg-un">Отвязать</button></div>
        <p class="hint" style="margin-top:12px">В самом Telegram работают команды: /my — мои задачи сейчас, /stop и /start — выключить и включить.</p>`;
    } else {
      body = `<div class="tgbox"><span class="tgico">${icon("send")}</span><div><b>Привяжите Telegram</b><br><span class="hint">Это займёт десять секунд, пароль вводить не нужно.</span></div></div>
        <div id="linkarea" style="margin-top:16px"><button class="btn tg" id="tg-link">Привязать Telegram</button></div>`;
    }
    box.innerHTML = `<div class="card-head"><h2>${icon("send")}Telegram</h2></div>${s.error && admin ? `<div class="warn">${icon("alert")}<span>Ошибка бота: ${esc(s.error)}</span></div>` : ""}${body}`;
    const link = $("#tg-link", box);
    if (link) link.onclick = async () => {
      link.disabled = true;
      try {
        const r = await api("/api/telegram/link", { method: "POST", json: {} });
        $("#linkarea", box).innerHTML = `<a class="btn tg" href="${esc(r.url)}" target="_blank" rel="noopener">${icon("send")}Открыть Telegram</a>
          <p class="hint" style="margin:12px 0 4px">Нажмите «Старт» в чате с ботом. Или отправьте ему вручную: <span class="code">/start ${esc(r.code)}</span></p>
          <p style="margin:8px 0 0"><span class="pulse"></span><span class="hint">Ждём подтверждения… код действует ${r.minutes} минут</span></p>`;
        timer = setInterval(async () => {
          try { const s2 = await api("/api/telegram"); if (s2.linked) { cleanup(); toast("Telegram привязан"); paintTg(s2); } } catch (e) {}
        }, 2500);
      } catch (e) { toast(e.message, "error"); link.disabled = false; }
    };
    const t = $("#tg-test", box);
    if (t) t.onclick = async () => { t.disabled = true; try { await api("/api/telegram/test", { method: "POST", json: {} }); toast("Сообщение отправлено — проверьте Telegram"); } catch (e) { toast(e.message, "error"); } t.disabled = false; };
    const un = $("#tg-un", box);
    if (un) un.onclick = async () => { await api("/api/telegram/unlink", { method: "POST", json: {} }); toast("Telegram отвязан"); paintTg(await api("/api/telegram")); };
  }
  paintTg(tg);

  /* ---------- my rules ---------- */
  let mine = rm.mine, defs = rm.defaults;
  const saveMine = debounced(async patch => { try { const r = await api("/api/reminders/me", { method: "PUT", json: patch }); mine = r.mine; defs = r.defaults; paintMine(); saved(); } catch (e) { toast(e.message, "error"); } }, 350);
  function paintMine() {
    const box = $("#c-me", page);
    box.innerHTML = `<div class="card-head"><div><h2>${icon("bell")}Мои напоминания</h2><p class="sub">Как часто и о чём вам писать</p></div></div>
      <div class="row"><div class="lb"><b>Присылать напоминания</b><span>${mine.remind ? "включено" : "выключено — бот молчит"}</span></div>${swHtml("m-on", mine.remind)}</div>
      <div id="m-rules" style="${mine.remind ? "" : "opacity:.45;pointer-events:none"};transition:opacity .3s">
      <div class="blk"><div class="k">Предупреждать о сроке<small>${mine.custom_days ? "ваша настройка" : "как у всех"}</small></div>${chipsHtml(DAY_CHIPS, mine.days, dayLabel)}</div>
      <div class="blk"><div class="k">О просроченных напоминать<small>${mine.custom_overdue ? "ваша настройка" : "как у всех"}</small></div><select id="m-over" style="max-width:240px">${optsHtml(OVERDUE_OPTS, mine.overdue)}</select></div>
      <div class="row" style="margin-top:8px"><div class="lb"><b>Сообщать о новых задачах</b><span>сразу, когда администратор назначил вам задачу</span></div>${swHtml("m-asg", mine.notify_assign)}</div>
      ${mine.custom_days || mine.custom_overdue ? `<button class="btn sm" id="m-reset" style="margin-top:10px">Вернуть настройки «как у всех»</button>` : ""}
      <p class="hint" style="margin-top:12px">Сводка приходит ${defs.weekdays.length === 7 ? "каждый день" : "по " + defs.weekdays.map(d => WD[d - 1][1].toLowerCase()).join(", ")} в ${esc(defs.time)}${defs.enabled ? "" : " — сейчас администратор отключил напоминания для всех"}.</p></div>`;
    $("#m-on", box).onchange = e => saveMine({ remind: e.target.checked });
    $("#m-asg", box).onchange = e => saveMine({ notify_assign: e.target.checked });
    $("#m-over", box).onchange = e => saveMine({ overdue: +e.target.value });
    $(".tgcs", box).onclick = e => {
      const b = e.target.closest(".tgc"); if (!b) return;
      b.classList.toggle("on");
      saveMine({ days: $$(".tgc.on", box).map(x => +x.dataset.v) });
    };
    const r = $("#m-reset", box); if (r) r.onclick = () => saveMine({ days: null, overdue: null });
  }
  paintMine();
  if (!admin) return cleanup;

  /* ---------- defaults for everyone ---------- */
  let G = g;
  const saveG = debounced(async patch => { try { G = await api("/api/reminders/settings", { method: "PUT", json: patch }); saved(); } catch (e) { toast(e.message, "error"); } }, 450);
  const box = $("#c-g", page);
  box.innerHTML = `<div class="card-head"><div><h2>${icon("gear")}Общие настройки</h2><p class="sub">Для всех сотрудников. Каждый может изменить их для себя на этой же странице.</p></div></div>
    <div class="two" style="margin-bottom:0"><div>
      <div class="row"><div class="lb"><b>Напоминания включены</b><span>выключатель для всех сразу</span></div>${swHtml("g-on", G.enabled)}</div>
      <div class="blk"><div class="k">Во сколько присылать<small>время Ташкента</small></div><input type="time" id="g-time" value="${esc(G.time)}"></div>
      <div class="blk"><div class="k">В какие дни недели</div><div id="g-wd">${chipsHtml(WD.map(w => w[0]), G.weekdays, v => WD[v - 1][1], "sq")}</div></div>
      <div class="blk"><div class="k">Какой срок считать</div><div id="g-by"></div></div>
    </div><div>
      <div class="blk" style="margin-top:0"><div class="k">Предупреждать о сроке по умолчанию</div><div id="g-days">${chipsHtml(DAY_CHIPS, G.days, dayLabel)}</div></div>
      <div class="blk"><div class="k">О просроченных напоминать по умолчанию</div><select id="g-over" style="max-width:240px">${optsHtml(OVERDUE_OPTS, G.overdue)}</select></div>
      <div class="row"><div class="lb"><b>Сводка для администраторов</b><span>просрочено и скоро срок по всем сотрудникам</span></div>${swHtml("g-adm", G.admin)}</div>
      <div class="blk"><div class="k">Сколько задач в одном сообщении<small>остальные — «и ещё N»</small></div><input type="number" id="g-max" min="3" max="40" value="${G.max}"></div>
      <div class="blk"><div class="k">Адрес сайта для ссылок в сообщениях</div><div class="inl"><input id="g-url" placeholder="https://zadachi.example.uz" value="${esc(G.public_url)}" style="flex:1;min-width:200px"><button class="btn sm" id="g-url-fill" type="button">Подставить текущий</button></div></div>
    </div></div>`;
  $("#g-by", box).appendChild(seg([["close", "дате закрытия"], ["due", "официальному сроку"]], G.by, v => saveG({ by: v })));
  $("#g-on", box).onchange = e => saveG({ enabled: e.target.checked });
  $("#g-adm", box).onchange = e => saveG({ admin: e.target.checked });
  $("#g-time", box).onchange = e => saveG({ time: e.target.value });
  $("#g-over", box).onchange = e => saveG({ overdue: +e.target.value });
  $("#g-max", box).onchange = e => saveG({ max: +e.target.value });
  $("#g-url", box).onchange = e => saveG({ public_url: e.target.value.trim() });
  $("#g-url-fill", box).onclick = () => { $("#g-url", box).value = location.origin; saveG({ public_url: location.origin }); };
  $("#g-wd", box).onclick = e => { const b = e.target.closest(".tgc"); if (!b) return; b.classList.toggle("on"); const v = $$("#g-wd .tgc.on", box).map(x => +x.dataset.v); if (!v.length) { b.classList.add("on"); toast("Нужен хотя бы один день", "error"); return; } saveG({ weekdays: v }); };
  $("#g-days", box).onclick = e => { const b = e.target.closest(".tgc"); if (!b) return; b.classList.toggle("on"); saveG({ days: $$("#g-days .tgc.on", box).map(x => +x.dataset.v) }); };

  /* ---------- preview and manual run ---------- */
  const SC = { would_send: ["done", "уйдёт"], sent: ["done", "отправлено"], nothing: ["todo", "нет задач под правила"], no_telegram: ["todo", "Telegram не привязан"], off: ["todo", "выключено у себя"], already: ["info", "сегодня уже было"], error: ["overdue", "ошибка"] };
  const pv = $("#c-pv", page);
  pv.innerHTML = `<div class="card-head"><div><h2>${icon("eye")}Кому и что уйдёт</h2><p class="sub">Проверка по текущим правилам. Ничего не отправляется.</p></div></div><div id="pv-body"><button class="btn" id="pv-go">Показать, что уйдёт сегодня</button></div>`;
  let pvItems = [];
  const showPv = (items, sentMode) => {
    pvItems = items;
    $("#pv-body", pv).innerHTML = `<table class="plain"><thead><tr><th>Сотрудник</th><th>Результат</th><th>Просрочено</th><th>Скоро</th><th></th></tr></thead><tbody>${items.map((r, i) => {
      const [k, l] = SC[r.status] || ["todo", r.status];
      return `<tr><td>${esc(r.name)}</td><td><span class="chip ${k}" ${r.reason ? `data-tip="${esc(r.reason)}"` : ""}>${l}</span></td><td class="num">${r.overdue || "·"}</td><td class="num">${r.soon || "·"}</td><td>${r.text ? `<button class="btn sm" data-i="${i}">Текст</button>` : ""}</td></tr>`;
    }).join("")}</tbody></table>
      <div class="inl" style="margin-top:14px"><button class="btn" id="pv-go">Обновить</button><button class="btn pri" id="pv-run">${icon("send")}Отправить сейчас всем</button></div>`;
    bindPv();
  };
  function bindPv() {
    $("#pv-go", pv).onclick = async ev => { ev.target.disabled = true; try { showPv((await api("/api/reminders/preview")).items); } catch (e) { toast(e.message, "error"); } };
    const run = $("#pv-run", pv);
    if (run) run.onclick = async () => {
      const ok = await formDialog({ title: "Отправить напоминания сейчас?", text: "Сообщения уйдут всем, у кого привязан Telegram и есть что напомнить, независимо от расписания.", ok: "Отправить", fields: [] });
      if (!ok) return;
      try { const r = await api("/api/reminders/run", { method: "POST", json: {} }); const n = r.items.filter(x => x.status === "sent").length; toast(`Отправлено сообщений: ${n}`); showPv(r.items, true); loadLog(); } catch (e) { toast(e.message, "error"); }
    };
    $$("[data-i]", pv).forEach(b => b.onclick = () => { const r = pvItems[+b.dataset.i]; infoDialog("Сообщение для " + r.name, `<div class="tgmsg">${r.text}</div>`, "Закрыть"); });
  }
  bindPv();

  /* ---------- log ---------- */
  async function loadLog() {
    const items = (await api("/api/reminders/log")).items;
    $("#c-log", page).innerHTML = `<div class="card-head"><div><h2>${icon("file")}Что отправлялось</h2><p class="sub">Последние 30 сообщений</p></div></div>` + (items.length ?
      `<div style="max-height:340px;overflow:auto"><table class="plain"><thead><tr><th>Когда</th><th>Кому</th><th>Итог</th></tr></thead><tbody>${items.map(l => `<tr><td class="num">${esc(l.created_at.slice(5, 16))}</td><td>${esc(l.name)}</td><td>${l.ok ? `<span class="chip done">${l.kind === "manual" ? "вручную" : "отправлено"}${l.count ? " · " + l.count : ""}</span>` : `<span class="chip overdue" data-tip="${esc(l.detail)}">ошибка</span>`}</td></tr>`).join("")}</tbody></table></div>` : '<p class="hint">Пока ничего не отправлялось.</p>');
  }
  await loadLog();
  return cleanup;
};
routes.reminders.title = "Напоминания";
