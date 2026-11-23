"use strict";
/* Dashboard: how the departments are doing, in one table at a time (tabs):
     «По месяцам»            - tasks done / not done in each month (the month of the term) and the percent done;
     «По видам документов»   - the same for Фармон, Қарор, Баён, ВМ, ПА;
     «По этапам согласования» - where the tasks that are not done stand: Justice -> Cabinet -> Chamber of Accounts.
   Every number is a button that opens the list of exactly those tasks. A management includes its divisions (the arrow folds them). The tasks «К сведению»
   are neither done nor open, so they are in no percent. */

function drill(p) {
  if (Z.me.tasks === "none") { toast("Список задач для вашей роли отключён администратором", "error"); return; }
  go("tasks", p);
}
function byToggle(onChange) {
  const wrap = document.createElement("div"); wrap.className = "ctl";
  wrap.innerHTML = '<span>Срок считать по:</span>';
  wrap.appendChild(seg([["close", "дате закрытия, иначе официальному"], ["strict", "только дате закрытия"], ["due", "официальному сроку"]], Z.by, v => {
    Z.by = v; try { localStorage.setItem("by", v); } catch (e) {} onChange(v);
  }));
  wrap.title = "«Дата закрытия, иначе официальный срок» — внутренний срок, который ставит администратор, а у задач без него официальный. «Только дата закрытия» — так видят дашборд все остальные пользователи: задачи без даты закрытия не попадают ни в один месяц и год. «Официальный срок» — срок из поручения.";
  return wrap;
}

routes.dashboard = async function (page, params) {
  /* the period of the dashboard: "" (all), "2027" (a year) or "2027-03" (a month): chosen in the header, the page is not drawn again, only the numbers are */
  let period = /^\d{4}(-\d{2})?$/.test((params && params.period) || "") ? params.period : "";
  const url = () => "/api/dashboard?by=" + Z.by + (period ? "&period=" + period : "");
  let d = await api(url());
  let T = d.totals;
  const MON = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  const monthShort = ym => MON[+ym.slice(5, 7) - 1] + " " + ym.slice(0, 4);
  const curYm = d.today.slice(0, 7);
  const todayStr = new Date(d.today + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
  let all = d.rows.concat(d.none ? [d.none] : []);
  const hasKids = id => d.rows.some(r => r.parent_id === id);
  const unitLabel = r => (r.num ? (r.level ? r.num + ". " : r.num + " · ") : "") + r.name;
  const worked = r => r.sum.done + r.sum.open;                         // done + not done: what the percent is made of
  const pc = (a, b) => b ? Math.round(100 * a / b) : 0;
  /* a bar of segments [number, kind]: the widths are the shares of the sum; a segment with 0 is not drawn */
  const bar = parts => { const sum = parts.reduce((s, x) => s + x[0], 0); return `<span class="bar" aria-hidden="true">${sum ? parts.filter(x => x[0] > 0).map(x => `<i class="${x[1]}" style="width:${(100 * x[0] / sum).toFixed(2)}%"></i>`).join("") : ""}</span>`; };
  const VIEWS = [["months", "По месяцам", "cal"], ["kinds", "По видам документов", "file"], ["stages", "По этапам согласования", "list"]];
  const st = { view: VIEWS.some(v => v[0] === (params && params.view)) ? params.view : "months", q: "", empty: false, collapsed: new Set() };
  /* the stages: the way of an answer (left to right), then what needs attention, then what is not known */
  const STAGE = { none: ["Ответ не введён", "Исполнитель ещё не ответил"], moj: ["Минюст (Адлия)", "Идёт согласование в Министерстве юстиции"], cab: ["Кабинет Министров", "Ответ у Кабинета Министров"],
    chamber: ["Счётная палата", "Ответ в Счётной палате"], info: ["Палата вернула", "Счётная палата вернула: принято к сведению или запрос информации, срок изменён"], returned: ["Возврат / запрос", "Нужны действия исполнителя"],
    other: ["Другое", "Этап не распознан, задача не найдена на сайте или нет ответов за последний месяц"], unchecked: ["Не проверялись", "Этапы ещё не читали: синхронизация читает только задачи, выбранные в «Настройках»"] };
  const STAGE_GROUPS = [["Путь согласования →", ["none", "moj", "cab", "chamber"]], ["Нужны действия", ["info", "returned"]], ["Нет данных", ["other", "unchecked"]]];

  /* when the data was last brought: «2026-11-23 09:13:05» -> «23.11.2026 09:13» */
  const stampOf = v => v ? v.slice(8, 10) + "." + v.slice(5, 7) + "." + v.slice(0, 4) + " " + v.slice(11, 16) : "";
  const upd = d.updated || {};
  const updLine = `<span class="upd" data-tip="Время последней проверки задач на сайте (кнопка «Синхронизировать» в скрипте) и последней загрузки базы">Обновлено: <b>${upd.sync ? stampOf(upd.sync) : "синхронизации ещё не было"}</b>${upd.sync ? " · синхронизация с ijro" : ""}${upd.base ? " · база загружена " + stampOf(upd.base) : ""}</span>`;
  page.innerHTML = `<div class="pagehead rise" style="--i:0"><div><h1>Дашборд</h1><p>${esc(todayStr)}</p><p class="upd-line">${updLine}</p></div><div class="controls" id="ctl"></div></div>`;
  const staff = ["admin", "specialist"].includes(Z.me.role);
  const MONF = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  const pbox = document.createElement("div"); pbox.className = "ctl rp";
  $("#ctl", page).appendChild(pbox);
  const periodBounds = pr => !pr ? {} : pr.length === 7 ? bounds(pr) : { date_from: pr + "-01-01", date_to: pr + "-12-31" };
  function paintPeriodBox() {
    const ys = [...new Set((d.periods || []).map(m => m.slice(0, 4)))], py = period.slice(0, 4), pm = period.slice(5, 7);
    const ms = py ? (d.periods || []).filter(m => m.startsWith(py)).map(m => m.slice(5, 7)) : [];
    pbox.innerHTML = `<span>Период:</span><select id="pp-y" aria-label="Год">${`<option value="">Все годы</option>` + ys.map(y => `<option value="${y}"${y === py ? " selected" : ""}>${y}</option>`).join("")}</select>`
      + `<select id="pp-m" aria-label="Месяц"${py ? "" : " disabled"}>${`<option value="">Все месяцы</option>` + ms.map(m => `<option value="${m}"${m === pm ? " selected" : ""}>${MONF[+m - 1]}</option>`).join("")}</select>`
      + (staff ? `<button type="button" class="btn sm" id="rp-go" data-tip="Сводная таблица по отделам департамента в формате министерства (Excel) за выбранный период">${icon("download")}Выгрузить в Excel</button>` : "");
    $("#pp-y", pbox).onchange = e => { period = e.target.value; reload(); };
    $("#pp-m", pbox).onchange = e => { period = py + (e.target.value ? "-" + e.target.value : ""); reload(); };
    const go = $("#rp-go", pbox); if (go) go.onclick = () => { location.href = "/api/report.xlsx?month=" + encodeURIComponent(period) + "&by=" + Z.by; };
  }
  if (Z.me.role === "admin") $("#ctl", page).appendChild(byToggle(() => reload()));   // only the administrator can switch between the closing date and the official term

  if (!T.total && !period) {
    page.insertAdjacentHTML("beforeend", `<div class="card empty rise" style="--i:1"><div class="big">📋</div><h2 style="justify-content:center">Задач пока нет</h2><p>Загрузите базу задач на странице «<a href="#/import">Импорт</a>».</p></div>`);
    return;
  }
  const kpiHtml = () => {
    const donePct = pc(T.done, T.done + T.open);
    return `      <button type="button" class="dk" data-go=""><span class="go">открыть список →</span><span class="l">Всего задач</span><b class="v">${T.total}</b>${bar([[T.done, "ok"], [T.open, "no"], [T.info, "info"]])}<small>${T.info ? `в том числе «к сведению»: ${T.info}` : "выполняемых задач в базе"}</small></button>
      <button type="button" class="dk ok" data-go="done"><span class="go">открыть список →</span><span class="l">Выполнено</span><b class="v">${T.done}</b>${bar([[T.done, "ok"], [T.open, "rest"]])}<small>${donePct}% от выполняемых</small></button>
      <button type="button" class="dk no" data-go="open"><span class="go">открыть список →</span><span class="l">Не выполнено</span><b class="v">${T.open}</b>${bar([[T.open, "no"], [T.done, "rest"]])}<small>${100 - donePct}% от выполняемых</small></button>
`;
  };
  page.insertAdjacentHTML("beforeend", `
    <section class="dkpis rise" style="--i:1" id="d-kpis">${kpiHtml()}    </section>
    <section class="card rise dboard" style="--i:2">
      <div class="dtabs" role="tablist">${VIEWS.map(v => `<button type="button" role="tab" class="dtab" data-view="${v[0]}">${icon(v[2])}${v[1]}</button>`).join("")}</div>
      <div class="dtools"><input type="search" id="d-q" placeholder="Найти отдел…" aria-label="Найти отдел"><label class="switchrow" style="margin:0"><input type="checkbox" id="d-empty"><span>Показывать отделы без задач</span></label><button type="button" class="btn sm" id="d-fold">Свернуть управления</button></div>
      <p class="dhelp" id="d-help"></p>
      <div class="tablewrap"><table class="dbt um" id="d-table"></table></div>
      <p class="hint dnote">Нажмите на число или процент: откроется список именно этих задач. Задачи «К сведению» в таблицы не входят. Задача относится к отделу ответственного; без ответственного или его отдела — строка «Без отдела».</p>
    </section>`);

  /* ---- cells ---- */
  const attrOf = a => Object.entries(a).filter(([, v]) => v !== undefined).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");
  const chip = (n, cls, a) => n ? `<button type="button" class="n ${cls}" ${attrOf(a)}>${n}</button>` : `<span class="n ${cls} z">0</span>`;
  /* one cell: the percent done and the number of tasks; a bar (done | not done); below it two buttons: done and not done */
  function pairCell(v, a, tip, extra = "") {
    const done = v ? v.done : 0, open = v ? v.open : 0, n = done + open;
    if (!n) return `<td class="dc z${extra}"><span class="dash">—</span></td>`;
    const p = pc(done, n);
    return `<td class="dc${extra}" data-tip="${esc(tip)}: выполнено ${done} из ${n} (${p}%)"><span class="cl"><b class="pc">${p}%</b><span class="of">из ${n}</span></span>${bar([[done, "ok"], [open, "no"]])}<span class="cnt">${chip(done, "ok", { ...a, st: "done" })}${chip(open, "no", { ...a, st: "open" })}</span></td>`;
  }
  function nameCell(r, total) {
    if (total) return `<td><div class="um-n"><span class="chev off"></span><button type="button" class="pname" data-u=""><span><b>Весь департамент</b></span></button></div></td>`;
    const kids = !r.level && r.id && hasKids(r.id), open = !st.collapsed.has(r.id), lbl = r.id ? unitLabel(r) : r.name;
    return `<td><div class="um-n"><button type="button" class="chev${kids ? "" : " off"}${open ? " open" : ""}" data-chev="${r.id}" aria-label="Свернуть или развернуть">${icon("chev")}</button><button type="button" class="pname" data-u="${r.id}" data-tip="<b>${esc(lbl)}</b>Открыть все задачи отдела"><span>${esc(lbl)}</span></button><small class="rt">${worked(r) ? worked(r) + " " + plural(worked(r), "задача", "задачи", "задач") : ""}</small></div></td>`;
  }
  /* which rows are on the screen */
  function visibleRows() {
    const q = st.q.trim().toLowerCase();
    if (q) {
      const hit = new Set(all.filter(r => unitLabel(r).toLowerCase().includes(q)).map(r => r.id));
      return all.filter(r => hit.has(r.id) || (!r.level && d.rows.some(k => k.parent_id === r.id && hit.has(k.id))));          // a management is kept for the context of its divisions
    }
    return all.filter(r => (st.empty || worked(r) > 0) && !(r.parent_id && st.collapsed.has(r.parent_id)));
  }
  const rowCls = (r, total) => `r ${total ? "total" : r.level ? "kid" : "mgmt"}`;
  const who = (r, total) => total ? "Весь департамент" : unitLabel(r);
  const uOf = (r, total) => total ? "" : r.id;
  const sumOf = r => ({ done: r.sum.done, open: r.sum.open });

  const OKB = '<span class="lg"><i class="sw ok"></i>выполнено</span>', NOB = '<span class="lg"><i class="sw no"></i>не выполнено</span>';
  const HELP = {
    months: `В ячейке: доля выполненных, число задач со сроком в этом месяце, полоса прогресса (${OKB} · ${NOB}) и две кнопки с числами. <b>Нажмите на кнопку</b>, чтобы открыть список этих задач. Текущий месяц отмечен в шапке.`,
    kinds: `В ячейке: доля выполненных, число задач вида, полоса прогресса (${OKB} · ${NOB}) и две кнопки с числами. <b>Нажмите на кнопку</b>, чтобы открыть список.`,
    stages: `Только невыполненные задачи. Слева направо путь ответа: исполнитель → Минюст → Кабинет Министров → Счётная палата. Полоса в ячейке — доля этапа среди невыполненных задач отдела; в последней колонке — доля невыполненных среди всех задач отдела (<span class="lg"><i class="sw no"></i>не выполнено</span> · <span class="lg"><i class="sw ok"></i>выполнено</span>). <b>Нажмите на число</b>, чтобы открыть список.`,
  };
  function paint() {
    $$(".dtab", page).forEach(b => { const on = b.dataset.view === st.view; b.classList.toggle("on", on); b.setAttribute("aria-selected", on); });
    $("#d-help", page).innerHTML = HELP[st.view];
    const rows = visibleRows();
    let head, line;
    if (st.view === "months") {
      head = `<tr><th>Отдел</th>${d.months.map(ym => `<th class="${ym === curYm ? "now" : ""}">${monthShort(ym)}${ym === curYm ? "<small>сейчас</small>" : ""}</th>`).join("")}${d.total.nodate.done + d.total.nodate.open ? `<th data-tip="Задачи без срока исполнения">Без срока</th>` : ""}<th class="sumc">Всего</th></tr>`;
      const hasNo = d.total.nodate.done + d.total.nodate.open > 0;
      line = (r, total) => `<tr class="${rowCls(r, total)}">${nameCell(r, total)}${d.months.map(ym => pairCell(r.months[ym], { u: uOf(r, total), ym }, `${who(r, total)} · ${monthShort(ym)}`)).join("")}${hasNo ? pairCell(r.nodate, { u: uOf(r, total), ym: "none" }, `${who(r, total)} · без срока`) : ""}${pairCell(sumOf(r), { u: uOf(r, total) }, `${who(r, total)} · всего`, " sumc")}</tr>`;
    } else if (st.view === "kinds") {
      head = `<tr><th>Отдел</th>${d.kinds.map(k => `<th>${esc(k)}</th>`).join("")}<th class="sumc">Всего</th></tr>`;
      line = (r, total) => `<tr class="${rowCls(r, total)}">${nameCell(r, total)}${d.kinds.map(k => pairCell(r.kinds[k], { u: uOf(r, total), k }, `${who(r, total)} · ${k}`)).join("")}${pairCell(sumOf(r), { u: uOf(r, total) }, `${who(r, total)} · всего`, " sumc")}</tr>`;
    } else {
      const cols = STAGE_GROUPS.flatMap(g => g[1]);
      head = `<tr class="grp"><th></th>${STAGE_GROUPS.map((g, i) => `<th colspan="${g[1].length}" class="g${i}">${g[0]}</th>`).join("")}<th></th></tr>`
        + `<tr><th>Отдел</th>${cols.map(k => `<th class="st-${k}" data-tip="${esc(STAGE[k][1])}">${esc(STAGE[k][0])}</th>`).join("")}<th class="sumc">Не выполнено</th></tr>`;
      line = (r, total) => {
        const open = r.sum.open, u = uOf(r, total);
        const cell = k => { const n = r.stages[k] || 0; return n ? `<td class="dc sc st-${k}" data-tip="${esc(who(r, total) + " · " + STAGE[k][0])}: ${n} из ${open} не выполненных"><span class="cl"><button type="button" class="n st" data-u="${esc(u)}" data-s="${k}">${n}</button><span class="of">${pc(n, open)}%</span></span>${bar([[n, "sg"], [open - n, "rest"]])}</td>` : `<td class="dc z"><span class="dash">—</span></td>`; };
        const all_ = r.sum.done + r.sum.open;
        return `<tr class="${rowCls(r, total)}">${nameCell(r, total)}${cols.map(cell).join("")}<td class="dc sc sumc">${open ? `<span class="cl"><button type="button" class="n st" data-u="${esc(u)}" data-st="open">${open}</button><span class="of">${pc(open, all_)}% от всех</span></span>${bar([[open, "no"], [r.sum.done, "ok"]])}` : '<span class="dash">—</span>'}</td></tr>`;
      };
    }
    $("#d-table", page).className = "dbt um v-" + st.view;
    $("#d-table", page).innerHTML = `<thead>${head}</thead><tbody>${line(d.total, true)}${rows.length ? rows.map(r => line(r, false)).join("") : `<tr><td colspan="30" class="hint" style="text-align:center;padding:18px">Отделов не найдено</td></tr>`}</tbody>`;
    const mgmts = d.rows.filter(r => !r.level && hasKids(r.id));
    $("#d-fold", page).textContent = mgmts.length && mgmts.every(r => st.collapsed.has(r.id)) ? "Развернуть управления" : "Свернуть управления";
  }
  paint();
  paintPeriodBox();

  /* ---- a new period or a new kind of date: only the numbers are fetched and drawn again, the page stays ---- */
  const syncUrl = () => { try { history.replaceState(null, "", "#/dashboard?view=" + st.view + (period ? "&period=" + period : "")); } catch (er) { /* the address stays; nothing breaks */ } };     // "back" from a list returns to this view and period
  let busy = 0;
  async function reload() {
    const my = ++busy, dash = $(".dboard", page), kp = $("#d-kpis", page);
    [dash, kp].forEach(el => el && el.classList.add("loading"));
    let nd;
    try { nd = await api(url()); } catch (e) { if (my === busy) { toast(e.message, "error"); [dash, kp].forEach(el => el && el.classList.remove("loading")); } return; }
    if (my !== busy) return;                                           // a newer choice is already on its way
    d = nd; T = d.totals; all = d.rows.concat(d.none ? [d.none] : []);
    const ys = new Set((d.periods || []).map(m => m.slice(0, 4)));
    if (period && !(d.periods || []).some(m => m.startsWith(period))) period = ys.has(period.slice(0, 4)) ? period.slice(0, 4) : "";      // the chosen month has no tasks by this date: the year, else all
    paintPeriodBox(); kp.innerHTML = kpiHtml(); paint(); syncUrl();
    [dash, kp].forEach(el => el && el.classList.remove("loading"));
  }

  /* ---- controls ---- */
  $(".dtabs", page).onclick = e => {
    const b = e.target.closest(".dtab"); if (!b) return;
    st.view = b.dataset.view; paint(); syncUrl();
  };
  $("#d-q", page).oninput = e => { st.q = e.target.value; paint(); };
  $("#d-empty", page).onchange = e => { st.empty = e.target.checked; paint(); };
  $("#d-fold", page).onclick = () => {
    const mgmts = d.rows.filter(r => !r.level && hasKids(r.id));
    if (mgmts.every(r => st.collapsed.has(r.id))) st.collapsed.clear(); else mgmts.forEach(r => st.collapsed.add(r.id));
    paint();
  };

  /* ---- every number opens its list ---- */
  const bounds = ym => { const last = new Date(+ym.slice(0, 4), +ym.slice(5, 7), 0).getDate(); return { date_from: ym + "-01", date_to: ym + "-" + String(last).padStart(2, "0") }; };
  page.addEventListener("click", e => {
    const go1 = e.target.closest(".dk"); if (go1) { drill({ ...(go1.dataset.go ? { status: go1.dataset.go } : {}), ...periodBounds(period) }); return; }
    const chev = e.target.closest("[data-chev]");
    if (chev) {
      if (chev.classList.contains("off")) return;
      const id = +chev.dataset.chev;
      st.collapsed.has(id) ? st.collapsed.delete(id) : st.collapsed.add(id);
      paint();
      return;
    }
    const b = e.target.closest("#d-table button[data-u], #d-table button[data-st], #d-table button[data-s], #d-table button[data-k], #d-table button[data-ym]");
    if (!b) return;
    const ds = b.dataset, p = {};
    if (ds.u !== undefined && ds.u !== "") p.unit = ds.u;                                // "0" = without a department
    if (ds.st) p.status = ds.st;
    if (ds.ym === "none") p.term = "none"; else if (ds.ym) Object.assign(p, bounds(ds.ym)); else Object.assign(p, periodBounds(period));      // the numbers are those of the chosen period: the list is too
    if (ds.k) p.kind = ds.k;
    if (ds.s) { p.stage = ds.s; p.status = "open"; }
    drill(p);
  });
};
routes.dashboard.title = "Дашборд";
