"use strict";
/* Dashboard: three tables of departments. Every number is a button that opens the list of exactly those tasks.
     1. departments x months: tasks done / not done in each month (the month of the term) and the percent done;
     2. departments x kinds of documents (Фармон, Қарор, Баён, ВМ, ПА): done / not done and the percent;
     3. departments x stages of the approval (Justice -> Cabinet -> Chamber of Accounts): where the open tasks are.
   A management includes its divisions (the arrow folds them). «К сведению» is neither done nor open, so it is not in the percent. */

function drill(p) {
  if (Z.me.tasks === "none") { toast("Список задач для вашей роли отключён администратором", "error"); return; }
  go("tasks", p);
}
function byToggle(onChange) {
  const wrap = document.createElement("div"); wrap.className = "ctl";
  wrap.innerHTML = '<span>Срок считать по:</span>';
  wrap.appendChild(seg([["close", "дате закрытия"], ["due", "официальному сроку"]], Z.by, v => {
    Z.by = v; try { localStorage.setItem("by", v); } catch (e) {} onChange(v);
  }));
  wrap.title = "«Дата закрытия» — внутренний срок, который ставит администратор (в выгрузке — «Ёпиш муддати»). «Официальный срок» — срок из поручения («Топшириқ муддати»). От этого зависит, к какому месяцу относится задача.";
  return wrap;
}

routes.dashboard = async function (page) {
  const d = await api("/api/dashboard?by=" + Z.by);
  const T = d.totals;
  const MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const monthShort = ym => MON[+ym.slice(5, 7) - 1] + " " + ym.slice(0, 4);
  const curYm = d.today.slice(0, 7);
  const todayStr = new Date(d.today + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
  const rows = d.rows.concat(d.none ? [d.none] : []);
  const hasKids = id => d.rows.some(r => r.parent_id === id);
  const unitLabel = r => (r.num ? (r.level ? r.num + ". " : r.num + " · ") : "") + r.name;
  const collapsed = new Set();
  const noDate = d.total.nodate.done + d.total.nodate.open > 0;

  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Дашборд</h1><p>${esc(todayStr)} · ${T.total} ${plural(T.total, "задача", "задачи", "задач")}: выполнено ${T.done}, не выполнено ${T.open}${T.info ? `, к сведению ${T.info}` : ""}</p></div>
    <div class="controls" id="ctl"></div></div>`;
  if (Z.me.role === "admin") $("#ctl", page).appendChild(byToggle(() => route()));   // only the administrator can switch between the closing date and the official term

  if (!T.total) {
    page.insertAdjacentHTML("beforeend", `<div class="card empty rise" style="--i:1"><div class="big">📋</div><h2 style="justify-content:center">Задач пока нет</h2><p>Загрузите базу задач на странице «<a href="#/import">Импорт</a>».</p></div>`);
    return;
  }

  let hint = "";
  try { if (!localStorage.getItem("hint2")) hint = `<div class="hint-banner rise" style="--i:1" id="hint">${icon("info")}<span>Нажимайте на любое число в таблицах: откроется список именно этих задач. Зелёное число — выполнено, красное — не выполнено; стрелка слева сворачивает отделы управления.</span><button class="icon-btn" style="margin-left:auto;width:28px;height:28px;border:0;background:none;color:inherit" aria-label="Скрыть">${icon("x")}</button></div>`; } catch (e) {}
  const card = (i, title, sub, id) => `<section class="card rise" style="--i:${i};margin-bottom:16px"><div class="card-head"><div><h2>${title}</h2><p class="sub">${sub}</p></div></div><div class="tablewrap"><table class="dbt um" id="${id}"></table></div></section>`;
  page.insertAdjacentHTML("beforeend", hint
    + card(1, "Отделы по месяцам", `Задачи, срок которых приходится на месяц: <b class="okc">выполнено</b> / <b class="noc">не выполнено</b> и процент выполнения. Подсвеченный столбец — текущий месяц.`, "t-months")
    + card(2, "Отделы по видам документов", `Сколько задач по каждому виду документа: <b class="okc">выполнено</b> / <b class="noc">не выполнено</b> и процент выполнения.`, "t-kinds")
    + card(3, "Отделы по этапам согласования", `Где сейчас задачи, которые ещё не выполнены: ответ Адлии → Кабинет Министров → Счётная палата. Столбец «Не проверялись» — этапы ещё не читали (какие задачи читает синхронизация, задаёт «Настройки»).`, "t-stages")
    + `<p class="hint" style="margin:-6px 0 16px">Задачи со статусом «К сведению» в таблицы не входят. Задача относится к отделу ответственного; задачи без ответственного или его отдела — в строке «Без отдела».</p>`);
  const h = $("#hint", page); if (h) $("button", h).onclick = () => { try { localStorage.setItem("hint2", "1"); } catch (e) {} h.style.transition = "all .3s"; h.style.opacity = 0; h.style.transform = "translateY(-8px)"; setTimeout(() => h.remove(), 300); };

  /* ---- cells ---- */
  const attrOf = a => Object.entries(a).filter(([, v]) => v !== undefined).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");
  const num = (n, cls, a) => n ? `<button type="button" class="n ${cls}" ${attrOf(a)}>${n}</button>` : `<span class="n ${cls} z">0</span>`;
  /* done / not done with the percent; the background shows the share that is done */
  function pairCell(v, a, tip) {
    const done = v ? v.done : 0, open = v ? v.open : 0, n = done + open;
    if (!n) return `<td class="dc z">·</td>`;
    const p = Math.round(100 * done / n);
    return `<td class="dc" style="--p:${p}%" data-tip="${esc(tip)}: выполнено ${done}, не выполнено ${open} · ${p}%"><span class="pr">${num(done, "ok", { ...a, st: "done" })}<i>/</i>${num(open, "no", { ...a, st: "open" })}</span><em>${p}%</em></td>`;
  }
  function nameCell(r, total) {
    if (total) return `<td><div class="um-n"><span class="chev off"></span><button type="button" class="pname" data-u="" style="font-weight:700"><span>Департамент жами</span></button></div></td>`;
    const kids = !r.level && r.id && hasKids(r.id), open = !collapsed.has(r.id), lbl = r.id ? unitLabel(r) : r.name;
    return `<td><div class="um-n"><button type="button" class="chev${kids ? "" : " off"}${open ? " open" : ""}" data-chev="${r.id}" aria-label="Свернуть или развернуть">${icon("chev")}</button><button type="button" class="pname" data-u="${r.id}" data-tip="<b>${esc(lbl)}</b>Открыть все задачи отдела"><span>${esc(lbl)}</span></button></div></td>`;
  }
  const trCls = (r, total) => `r ${total ? "total" : r.level ? "kid" : "mgmt"}`;
  const trAttr = r => r.parent_id && collapsed.has(r.parent_id) ? "hidden" : "";
  const sumOf = r => ({ done: r.sum.done, open: r.sum.open });
  const tbl = (id, head, body) => { $(id, page).innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`; };

  /* 1. departments x months */
  function paintMonths() {
    const head = `<th>Отдел</th>${d.months.map(ym => `<th class="${ym === curYm ? "now" : ""}">${monthShort(ym)}</th>`).join("")}${noDate ? `<th data-tip="Задачи без срока">Без срока</th>` : ""}<th>Всего</th>`;
    const line = (r, total) => `<tr class="${trCls(r, total)}" ${total ? "" : trAttr(r)}>${nameCell(r, total)}${d.months.map(ym => pairCell(r.months[ym], { u: total ? "" : r.id, ym }, `${total ? "Департамент" : unitLabel(r)} · ${monthShort(ym)}`)).join("")}`
      + `${noDate ? pairCell(r.nodate, { u: total ? "" : r.id, ym: "none" }, `${total ? "Департамент" : unitLabel(r)} · без срока`) : ""}${pairCell(sumOf(r), { u: total ? "" : r.id }, `${total ? "Департамент" : unitLabel(r)} · всего`)}</tr>`;
    tbl("#t-months", head, line(d.total, true) + rows.map(r => line(r, false)).join(""));
  }
  /* 2. departments x kinds of documents */
  function paintKinds() {
    const head = `<th>Отдел</th>${d.kinds.map(k => `<th>${esc(k)}</th>`).join("")}<th>Всего</th>`;
    const line = (r, total) => `<tr class="${trCls(r, total)}" ${total ? "" : trAttr(r)}>${nameCell(r, total)}${d.kinds.map(k => pairCell(r.kinds[k], { u: total ? "" : r.id, k }, `${total ? "Департамент" : unitLabel(r)} · ${k}`)).join("")}${pairCell(sumOf(r), { u: total ? "" : r.id }, `${total ? "Департамент" : unitLabel(r)} · всего`)}</tr>`;
    tbl("#t-kinds", head, line(d.total, true) + rows.map(r => line(r, false)).join(""));
  }
  /* 3. departments x stages: the open tasks and where they are */
  function paintStages() {
    const head = `<th>Отдел</th>${d.stages.map(s => `<th class="st-${s.key}" data-tip="${esc(s.hint)}">${esc(s.label)}</th>`).join("")}<th>Всего в работе</th>`;
    const line = (r, total) => {
      const open = r.sum.open, u = total ? "" : r.id, who = total ? "Департамент" : unitLabel(r);
      const cell = s => { const n = r.stages[s.key] || 0; return n ? `<td class="dc sc st-${s.key}" data-tip="${esc(who + " · " + s.label)}: ${n} из ${open} в работе"><button type="button" class="n st" data-u="${esc(u)}" data-s="${s.key}">${n}</button><em>${pct(n, open)}%</em></td>` : `<td class="dc z">·</td>`; };
      return `<tr class="${trCls(r, total)}" ${total ? "" : trAttr(r)}>${nameCell(r, total)}${d.stages.map(cell).join("")}<td class="dc sc">${open ? `<button type="button" class="n st" data-u="${esc(u)}" data-st="open">${open}</button>` : '<span class="n z">0</span>'}</td></tr>`;
    };
    tbl("#t-stages", head, line(d.total, true) + rows.map(r => line(r, false)).join(""));
  }
  const paintAll = () => { paintMonths(); paintKinds(); paintStages(); };
  paintAll();

  /* ---- every number opens its list ---- */
  const bounds = ym => { const last = new Date(+ym.slice(0, 4), +ym.slice(5, 7), 0).getDate(); return { date_from: ym + "-01", date_to: ym + "-" + String(last).padStart(2, "0") }; };
  page.addEventListener("click", e => {
    const chev = e.target.closest("[data-chev]");
    if (chev) {
      if (chev.classList.contains("off")) return;
      const id = +chev.dataset.chev;
      collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id);
      paintAll();                                     // one fold for the three tables
      return;
    }
    const b = e.target.closest("button[data-u], button[data-st], button[data-s], button[data-k], button[data-ym]");
    if (!b || !b.closest(".dbt")) return;
    const ds = b.dataset, p = {};
    if (ds.u !== undefined && ds.u !== "") p.unit = ds.u;                                // "0" = without a department
    if (ds.st) p.status = ds.st;
    if (ds.ym === "none") p.term = "none"; else if (ds.ym) Object.assign(p, bounds(ds.ym));
    if (ds.k) p.kind = ds.k;
    if (ds.s) { p.stage = ds.s; p.status = "open"; }
    drill(p);
  });
};
routes.dashboard.title = "Дашборд";
