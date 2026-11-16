"use strict";
/* Dashboard: KPI cards, workload per person (bars + exact matrix), structure donut, deadline columns, nearest terms.
   Every number, bar, slice and column is a button: it opens the task list filtered to exactly what was clicked. */

function drill(p) {
  if (Z.me.tasks === "none") { toast("Список задач для вашей роли отключён администратором", "error"); return; }
  if (Z.me.role !== "admin" && Z.me.tasks === "own" && p.assignee !== undefined && String(p.assignee) !== String(Z.me.id)) {   // the list would be empty: say why
    toast("В списке вам доступны только ваши задачи. Откройте свою строку или карточку.", "error"); return;
  }
  go("tasks", p);
}
function bucketDrill(key, extra) {
  const p = Object.assign({}, extra || {});
  if (key === "done" || key === "info") p.status = key; else if (key === "open") p.status = "open"; else p.bucket = key;
  drill(p);
}
function byToggle(onChange) {
  const wrap = document.createElement("div"); wrap.className = "ctl";
  wrap.innerHTML = '<span>Срок считать по:</span>';
  wrap.appendChild(seg([["close", "дате закрытия"], ["due", "официальному сроку"]], Z.by, v => {
    Z.by = v; try { localStorage.setItem("by", v); } catch (e) {} onChange(v);
  }));
  wrap.title = "«Дата закрытия» — внутренний срок, который ставит администратор (в выгрузке — «Ёпиш муддати»). «Официальный срок» — срок из поручения («Топшириқ муддати»).";
  return wrap;
}

routes.dashboard = async function (page) {
  const d = await api("/api/dashboard?by=" + Z.by);
  const T = d.totals, people = d.people;
  const maxTotal = Math.max(1, ...people.map(p => p.total));
  const scopeNote = Z.me.tasks === "none";
  const todayStr = new Date(d.today + "T00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", weekday: "long" });

  /* ---- header ---- */
  page.innerHTML = `
    <div class="pagehead rise" style="--i:0"><div><h1>Дашборд</h1><p>${esc(todayStr)} · на контроле ${T.total} ${plural(T.total, "задача", "задачи", "задач")}</p></div>
      <div class="controls" id="ctl"></div></div>`;
  const ctl = $("#ctl", page);
  if (Z.me.role === "admin") ctl.appendChild(byToggle(() => route()));   // only the administrator can switch between the closing date and the official term
  const modeBox = document.createElement("div"); modeBox.className = "ctl"; modeBox.innerHTML = "<span>Показывать:</span>";
  modeBox.appendChild(seg([["count", "Количество"], ["pct", "Проценты"]], Z.mode, v => { Z.mode = v; try { localStorage.setItem("mode", v); } catch (e) {} applyMode(); }));
  ctl.appendChild(modeBox);

  let hint = "";
  try { if (!localStorage.getItem("hint1") && !scopeNote) hint = `<div class="hint-banner rise" style="--i:1" id="hint">${icon("info")}<span>${Z.me.role !== "admin" && Z.me.tasks === "own" ? "На дашборде общая картина по всем. Нажмите на число или полосу, и в списке откроются <b>ваши</b> задачи этой группы." : "Нажимайте на карточки, полосы, сектора и столбцы — откроется список именно этих задач."}</span><button class="icon-btn" style="margin-left:auto;width:28px;height:28px;border:0;background:none;color:inherit" aria-label="Скрыть">${icon("x")}</button></div>`; } catch (e) {}

  const kpi = [
    { id: "all", cls: "", icon: "stack", lbl: "Всего задач", n: T.total, of: T.total, meta: `${T.open} в работе · ${T.done} выполнено`, go: () => drill({}) },
    { id: "open", cls: "k-month", icon: "clock", lbl: "В работе", n: T.open, of: T.total, meta: "ещё не выполнены", go: () => bucketDrill("open") },
    { id: "overdue", cls: "k-overdue", icon: "alert", lbl: "Просрочено", n: T.overdue, of: T.open, meta: "от задач в работе", go: () => bucketDrill("overdue") },
    { id: "week", cls: "k-week", icon: "cal", lbl: "Срок ≤ 7 дней", n: T.week, of: T.open, meta: "от задач в работе", go: () => bucketDrill("week") },
    { id: "done", cls: "k-done", icon: "check", lbl: "Выполнено", n: T.done, of: T.total - T.info, meta: d.closed_14d ? `+${d.closed_14d} за 14 дней` : "от всех задач", go: () => bucketDrill("done") },
  ];
  page.insertAdjacentHTML("beforeend", hint + `<section class="kpis">${kpi.map((k, i) => `
    <button class="kpi rise ${k.cls}" style="--i:${i + 1}" data-k="${k.id}">
      <div class="lbl">${k.lbl}${icon(k.icon)}</div>
      <div class="val num"><span class="v">0</span><small class="u"></small></div>
      <div class="meta">${esc(k.meta)}</div>
      <div class="meter"><i style="width:${pct(k.n, k.of)}%"></i></div>
    </button>`).join("")}</section>`);
  const h = $("#hint", page); if (h) $("button", h).onclick = () => { try { localStorage.setItem("hint1", "1"); } catch (e) {} h.style.transition = "all .3s"; h.style.opacity = 0; h.style.transform = "translateY(-8px)"; setTimeout(() => h.remove(), 300); };
  kpi.forEach(k => {
    const el = $(`.kpi[data-k="${k.id}"]`, page);
    el.onclick = k.go;
    el.dataset.n = k.n; el.dataset.p = pct(k.n, k.of);
    el.dataset.tip = `<b>${k.lbl}</b>${k.n} из ${k.of} · ${pct(k.n, k.of)}%`;
  });
  function paintKpi(first) {
    $$(".kpi", page).forEach(el => {
      const n = +el.dataset.n, p = +el.dataset.p, v = $(".v", el), u = $(".u", el);
      if (Z.mode === "pct" && el.dataset.k !== "all") { v.textContent = p; u.textContent = "%"; }
      else { if (first) countUp(v, n); else v.textContent = n; u.textContent = el.dataset.k === "all" ? "" : `${p}%`; }
    });
  }
  paintKpi(true);

  /* ---- people: bars + legend ---- */
  const legend = KEYS.map(k => `<button type="button" class="lgd k-${k}" data-key="${k}"><i></i>${LABEL[k]}</button>`).join("");
  page.insertAdjacentHTML("beforeend", `
    <section class="grid2">
      <div class="card rise" style="--i:6">
        <div class="card-head"><div><h2>Нагрузка по сотрудникам</h2><p class="sub">У кого сколько задач и в каких сроках. Нажмите на цвет — увидите эти задачи сотрудника.</p></div><div id="sortbox"></div></div>
        <div class="legend" id="legend">${legend}</div>
        <div class="people" id="people"></div>
      </div>
      <div class="card rise" style="--i:7">
        <div class="card-head"><div><h2>Структура задач</h2><p class="sub">Доли от всех ${T.total}</p></div></div>
        <div class="donut-wrap"><div class="donut" id="donut"></div><div class="dleg" id="dleg"></div></div>
      </div>
    </section>`);

  const peopleBox = $("#people", page);
  peopleBox.innerHTML = people.map(p => `
    <div class="prow" data-id="${p.id}">
      <button class="pname" data-tip="<b>${esc(p.name)}</b>Открыть все задачи сотрудника">${avatar(p.id, p.name, "sm")}<span>${esc(p.id ? p.short : p.name)}</span></button>
      <div class="bar">${KEYS.map(k => `<button type="button" class="seg-b k-${k}" data-key="${k}" aria-label="${esc(p.name)}: ${LABEL[k]} ${p[k]}"><span></span></button>`).join("")}</div>
      <div class="ptot num"><b></b><small></small></div>
    </div>`).join("");
  const rowOf = id => $(`.prow[data-id="${id}"]`, peopleBox);
  people.forEach(p => {
    const r = rowOf(p.id);
    $(".pname", r).onclick = () => drill({ assignee: p.id });
    $$(".seg-b", r).forEach(b => {
      const k = b.dataset.key, n = p[k];
      b.dataset.tip = `<b>${esc(p.name)}</b>${LABEL[k]}: ${n} · ${pct(n, p.total)}% его задач`;
      b.onclick = () => bucketDrill(k, { assignee: p.id });
    });
  });
  function applyMode() { paintKpi(false); applyBars(); paintMatrix(); paintUnits(); }
  function applyBars() {
    people.forEach(p => {
      const r = rowOf(p.id);
      $$(".seg-b", r).forEach(b => {
        const n = p[b.dataset.key];
        const w = Z.mode === "pct" ? pct100(n, p.total) : (n / maxTotal) * 100;
        b.style.width = w + "%"; b.style.display = n ? "" : "none";
        b.classList.toggle("wide", w >= 6);
        $("span", b).textContent = Z.mode === "pct" ? Math.round(w) + "%" : n;
      });
      $(".ptot b", r).textContent = Z.mode === "pct" ? p.pct_done + "%" : p.total;
      $(".ptot small", r).textContent = Z.mode === "pct" ? "выполнено" : (p.total ? p.pct_done + "% вып." : "нет задач");
    });
    applyUnitBars();
  }
  const pct100 = (a, b) => b ? 100 * a / b : 0;

  /* legend = focus one category across all people */
  let focus = "";
  $("#legend", page).onclick = e => {
    const b = e.target.closest(".lgd"); if (!b) return;
    focus = focus === b.dataset.key ? "" : b.dataset.key;
    $$("#legend .lgd", page).forEach(x => x.classList.toggle("off", !!focus && x.dataset.key !== focus));
    $$(".bar", peopleBox).forEach(bar => { bar.classList.toggle("dim", !!focus); $$(".seg-b", bar).forEach(s => s.classList.toggle("hit", s.dataset.key === focus)); });
  };

  /* sorting with a FLIP animation */
  const sorters = {
    open: (a, b) => b.open - a.open || b.overdue - a.overdue,
    overdue: (a, b) => b.overdue - a.overdue || b.open - a.open,
    pct: (a, b) => a.pct_done - b.pct_done || b.open - a.open,
    name: (a, b) => a.name.localeCompare(b.name),
  };
  let sortKey = "open";
  const sb = seg([["open", "В работе"], ["overdue", "Просрочено"], ["pct", "% выполнения"], ["name", "А–Я"]], sortKey, v => {
    sortKey = v;
    const first = new Map($$(".prow", peopleBox).map(r => [r, r.getBoundingClientRect().top]));
    [...people].sort(sorters[v]).forEach(p => peopleBox.appendChild(rowOf(p.id)));
    if (reduced()) return;
    $$(".prow", peopleBox).forEach(r => {
      const dy = first.get(r) - r.getBoundingClientRect().top;
      if (!dy) return;
      r.style.transition = "none"; r.style.transform = `translateY(${dy}px)`;
      requestAnimationFrame(() => { r.style.transition = "transform .5s var(--ease), background .2s"; r.style.transform = ""; });
    });
  });
  $("#sortbox", page).appendChild(sb);

  /* ---- donut ---- */
  const dTot = KEYS.map(k => ({ key: k, n: T[k] })).filter(x => x.n > 0);
  const C = 263.9;
  let off = 0, svg = '<svg viewBox="0 0 100 100"><circle class="trk" cx="50" cy="50" r="42" pathLength="100"/>';
  dTot.forEach(s => {
    const len = (100 * s.n) / T.total;
    svg += `<circle class="k-${s.key}" data-key="${s.key}" cx="50" cy="50" r="42" pathLength="100" stroke="var(--k)" stroke-dasharray="0 100" data-len="${Math.max(0, len - (dTot.length > 1 ? 0.7 : 0))}" stroke-dashoffset="${-off}" data-tip="<b>${LABEL[s.key]}</b>${s.n} · ${pct(s.n, T.total)}%"/>`;
    off += len;
  });
  svg += "</svg>";
  const donut = $("#donut", page);
  donut.innerHTML = svg + `<div class="mid"><b class="num" id="dm-b">${pct(T.done, T.total - T.info)}%</b><span id="dm-s">выполнено</span></div>`;
  $("#dleg", page).innerHTML = dTot.map(s => `<button class="drow k-${s.key}" data-key="${s.key}"><i></i><span>${LABEL[s.key]}</span><b class="num">${s.n}</b><em class="num">${pct(s.n, T.total)}%</em></button>`).join("");
  const hot = k => {
    $$("circle[data-key]", donut).forEach(c => c.classList.toggle("hot", c.dataset.key === k));
    donut.classList.toggle("dim", !!k);
    $$(".drow", page).forEach(r => r.classList.toggle("hot", r.dataset.key === k));
    if (k) { $("#dm-b").textContent = pct(T[k], T.total) + "%"; $("#dm-s").textContent = LABEL[k]; }
    else { $("#dm-b").textContent = pct(T.done, T.total - T.info) + "%"; $("#dm-s").textContent = "выполнено"; }
  };
  $$("circle[data-key],.drow", page).forEach(el => {
    el.onmouseenter = () => hot(el.dataset.key); el.onmouseleave = () => hot("");
    el.onfocus = () => hot(el.dataset.key); el.onblur = () => hot("");
    el.onclick = () => bucketDrill(el.dataset.key);
  });

  /* ---- departments: matrix "unit x kind of document" and workload bars per unit ---- */
  const UN = d.units, UROWS = UN.rows.concat(UN.none ? [UN.none] : []);
  const KIND_SUB = { "ВМ": "Вазирлар Маҳкамаси", "ПА": "Президент администрацияси" };
  const METRICS = [["total", "Всего"], ["open", "В работе"], ["overdue", "Просрочено"], ["week", "≤ 7 дн."], ["done", "Выполнено"]];
  const MET_K = { total: "", open: "k-month", overdue: "k-overdue", week: "k-week", done: "k-done" };
  const MET_DRILL = { total: {}, open: { status: "open" }, overdue: { bucket: "overdue" }, week: { bucket: "week" }, done: { status: "done" } };
  let metric = "total"; try { metric = localStorage.getItem("umMetric") || "total"; if (!MET_DRILL[metric]) metric = "total"; } catch (e) {}
  const collapsed = new Set();
  const hasKids = id => UN.rows.some(r => r.parent_id === id);
  page.insertAdjacentHTML("beforeend", `
    <section class="card rise" style="--i:7;margin-bottom:16px"><div class="card-head"><div><h2>Отделы × типы документов</h2>
      <p class="sub">Сколько задач у каждого управления и отдела по каждому типу документа. Нажмите на число — откроется список. Стрелка слева сворачивает отделы управления.</p></div><div id="um-ctl"></div></div>
      <div class="tablewrap"><table class="mx um" id="um"></table></div></section>
    <section class="card rise" style="--i:8;margin-bottom:16px"><div class="card-head"><div><h2>Нагрузка по отделам</h2>
      <p class="sub">Сроки по задачам каждого отдела. У управления — сумма с его отделами. Нажмите на цвет — увидите эти задачи.</p></div></div>
      <div class="people" id="ubars"></div></section>`);
  /* the department matrix stands right under "Нагрузка по отделам" */
  const umSection = $("#um", page).closest("section");
  const ubarsSection = $("#ubars", page).closest("section");
  umSection.style.setProperty("--i", 8); umSection.style.marginBottom = "16px";
  ubarsSection.after(umSection);
  $("#um-ctl", page).appendChild(seg(METRICS, metric, v => { metric = v; try { localStorage.setItem("umMetric", v); } catch (e) {} paintUnits(); }));
  const unitLabel = r => (r.num ? (r.level ? r.num + ". " : r.num + " · ") : "") + r.name;
  function paintUnits() {
    const pc = Z.mode === "pct", cols = UN.columns;
    const val = (c, k) => c[k] || 0;
    let mx = 1; UN.rows.forEach(r => cols.forEach(k => { mx = Math.max(mx, val(r.cells[k], metric)); }));
    const cell = (c, rowSum, attrs, bold, absolute) => {
      const n = val(c, metric), a = n ? (0.12 + 0.5 * n / mx).toFixed(2) : 0;
      const txt = !n ? "·" : (pc && !absolute) ? pct(n, val(rowSum, metric)) + "%" : n;
      return `<td><button class="cell ${MET_K[metric]}${n ? "" : " z"}${bold ? " b" : ""}" style="--a:${absolute ? 0 : a}" ${attrs}><span>${txt}</span></button></td>`;
    };
    const head = `<thead><tr><th>Отдел</th>${cols.map(k => `<th><button class="lgd" data-kind="${esc(k)}" ${KIND_SUB[k] ? `data-tip="<b>${esc(k)}</b>${KIND_SUB[k]}"` : ""} style="font-weight:600"><span>${esc(k)}</span></button></th>`).join("")}<th>Итого</th><th>% вып.</th></tr></thead>`;
    const rowHtml = (r, cls) => {
      const kids = !r.level && r.id && hasKids(r.id), open = !collapsed.has(r.id);
      const lbl = r.id ? unitLabel(r) : r.name;
      return `<tr class="r um-r ${cls}${r.parent_id ? " kid" : ""}" data-id="${r.id}" ${r.parent_id ? `data-parent="${r.parent_id}"` : ""} ${r.parent_id && collapsed.has(r.parent_id) ? "hidden" : ""}>
        <td><div class="um-n"><button class="chev${kids ? "" : " off"}${open ? " open" : ""}" data-chev="${r.id}" aria-label="Свернуть или развернуть">${icon("chev")}</button>
        <button class="pname" data-unit="${r.id}" data-tip="<b>${esc(lbl)}</b>Открыть все задачи"><span>${esc(lbl)}</span></button></div></td>
        ${cols.map(k => cell(r.cells[k], r.sum, `data-unit="${r.id}" data-kind="${esc(k)}"`, !r.level)).join("")}
        ${cell(r.sum, r.sum, `data-unit="${r.id}" data-all="1"`, true, true)}
        <td><div class="mini"><span class="num" style="min-width:34px">${r.sum.pct_done}%</span><span class="m"><i style="width:${r.sum.pct_done}%"></i></span></div></td></tr>`;
    };
    const T = UN.total;
    const totalRow = `<tr class="r um-r mgmt total"><td><div class="um-n"><span class="chev off"></span><button class="pname" data-unit="" style="font-weight:700"><span>Департамент жами</span></button></div></td>
      ${cols.map(k => cell(T.cells[k], T.sum, `data-kind="${esc(k)}"`, true)).join("")}${cell(T.sum, T.sum, `data-all="1"`, true, true)}
      <td><div class="mini"><span class="num" style="min-width:34px">${T.sum.pct_done}%</span><span class="m"><i style="width:${T.sum.pct_done}%"></i></span></div></td></tr>`;
    $("#um", page).innerHTML = head + "<tbody>" + totalRow + UN.rows.map(r => rowHtml(r, r.level ? "" : "mgmt")).join("") + (UN.none ? rowHtml(UN.none, "mgmt none") : "") + "</tbody>";
  }
  $("#um", page).addEventListener("click", e => {
    const chev = e.target.closest("[data-chev]");
    if (chev) {
      if (chev.classList.contains("off")) return;
      const id = +chev.dataset.chev, wasClosed = collapsed.has(id);
      wasClosed ? collapsed.delete(id) : collapsed.add(id);
      chev.classList.toggle("open", wasClosed);
      $$(`tr[data-parent="${id}"]`, page).forEach(tr => { tr.hidden = !wasClosed; if (wasClosed) { tr.style.animation = "none"; void tr.offsetWidth; tr.style.animation = ""; } });
      return;
    }
    const t = e.target.closest("[data-unit],[data-kind],[data-all]"); if (!t) return;
    const p = Object.assign({}, MET_DRILL[metric]);
    const unit = t.dataset.unit !== undefined ? t.dataset.unit : "";
    if (unit !== "") p.unit = unit;
    if (t.dataset.kind) p.kind = t.dataset.kind;
    drill(p);
  });
  /* bars per unit: the same look as the bars per person */
  const ubars = $("#ubars", page), uMax = Math.max(1, ...UROWS.map(r => r.sum.total));
  ubars.innerHTML = UROWS.map(r => `<div class="prow u${r.level ? " lvl1" : " mgmt"}" data-uid="${r.id}">
      <button class="pname" data-tip="<b>${esc(r.name)}</b>Открыть все задачи">${r.id ? `<span class="unum">${esc(r.num)}</span>` : ""}<span>${esc(r.name)}</span></button>
      <div class="bar">${KEYS.map(k => `<button type="button" class="seg-b k-${k}" data-key="${k}" data-tip="<b>${esc(r.name)}</b>${LABEL[k]}: ${r.sum[k]} · ${pct(r.sum[k], r.sum.total)}% задач отдела" aria-label="${esc(r.name)}: ${LABEL[k]} ${r.sum[k]}"><span></span></button>`).join("")}</div>
      <div class="ptot num"><b></b><small></small></div></div>`).join("");
  $$(".prow", ubars).forEach(row => {
    const r = UROWS.find(x => String(x.id) === row.dataset.uid);
    $(".pname", row).onclick = () => drill({ unit: r.id });
    $$(".seg-b", row).forEach(b => b.onclick = () => bucketDrill(b.dataset.key, { unit: r.id }));
  });
  function applyUnitBars() {
    $$(".prow", ubars).forEach(row => {
      const r = UROWS.find(x => String(x.id) === row.dataset.uid);
      $$(".seg-b", row).forEach(b => {
        const n = r.sum[b.dataset.key], w = Z.mode === "pct" ? pct100(n, r.sum.total) : (n / uMax) * 100;
        b.style.width = w + "%"; b.style.display = n ? "" : "none"; b.classList.toggle("wide", w >= 6);
        $("span", b).textContent = Z.mode === "pct" ? Math.round(w) + "%" : n;
      });
      $(".ptot b", row).textContent = Z.mode === "pct" ? r.sum.pct_done + "%" : r.sum.total;
      $(".ptot small", row).textContent = Z.mode === "pct" ? "выполнено" : (r.sum.total ? r.sum.pct_done + "% вып." : "нет задач");
    });
  }

  /* ---- timeline ---- */
  const maxT = Math.max(1, ...d.timeline.map(x => x.count));
  page.insertAdjacentHTML("beforeend", `
    <section class="grid2 even">
      <div class="card rise" style="--i:8"><div class="card-head"><div><h2>Сроки по неделям</h2><p class="sub">Сколько задач в работе нужно закрыть в каждую неделю</p></div></div>
        <div class="cols" id="cols">${d.timeline.map((x, i) => {
          const cls = x.key === "overdue" ? "k-overdue" : x.key === "w0" ? "k-week" : x.key === "later" ? "k-later" : x.key === "nodate" ? "k-nodate" : "k-month";
          return `<button class="col ${cls}${x.count ? "" : " zero"}" data-i="${i}" data-tip="<b>${esc(x.label)}</b>${x.count} ${plural(x.count, "задача", "задачи", "задач")} в работе" aria-label="${esc(x.label)}: ${x.count}">
            <div class="track"><div class="b" data-h="${(x.count / maxT) * 100}"><span class="cnt num">${x.count}</span></div></div><span class="l">${esc(x.label)}</span></button>`;
        }).join("")}</div></div>
      <div class="card rise" style="--i:9"><div class="card-head"><div><h2>Ближайшие сроки</h2><p class="sub">Первые по сроку задачи в работе</p></div></div>
        <div class="up" id="up">${d.upcoming.length ? d.upcoming.map(u => {
          const k = u.days == null ? "nodate" : u.days < 0 ? "overdue" : u.days <= 7 ? "week" : "month";
          const n = u.days == null ? "—" : Math.abs(u.days);
          return `<button class="urow k-${k}" data-id="${u.id}"><div class="when"><b class="num">${u.days != null && u.days < 0 ? "−" : ""}${n}</b><small>${u.days == null ? "" : plural(n, "день", "дня", "дней")}</small></div>
            <div class="tx"><p>${esc(u.point ? u.point + " · " : "")}${esc(u.text)}</p><small>${esc(u.assignee)} · ${esc(u.doc_no)} · ${fdate(u.eff)}</small></div></button>`;
        }).join("") : '<div class="empty"><div class="big">🎉</div>Всё выполнено</div>'}</div></div>
    </section>`);
  $$(".col", page).forEach(b => b.onclick = () => {
    const x = d.timeline[+b.dataset.i];
    if (x.key === "overdue") bucketDrill("overdue");
    else if (x.key === "nodate") bucketDrill("nodate");
    else drill({ status: "open", date_from: x.from, date_to: x.to || "" });
  });
  $$(".urow", page).forEach(b => b.onclick = () => { if (Z.me.tasks === "none") return; openTask(+b.dataset.id); });

  /* ---- matrix "people x deadlines": the whole picture, or one month split by the day of the month ---- */
  const MCOL = [["overdue", "Просрочено"], ["week", "≤ 7 дн."], ["month", "8–30 дн."], ["later", "> 30 дн."], ["nodate", "Без срока"], ["done", "Выполнено"]];
  const RANGES = [["d10", "до 10 числа", "1–10 числа", "k-week", 1, 10], ["d15", "до 15 числа", "11–15 числа", "k-month", 11, 15],
                  ["d20", "до 20 числа", "16–20 числа", "k-later", 16, 20], ["d31", "после 20 числа", "21 число и до конца месяца", "k-nodate", 21, 31]];
  const MONTH_NAMES = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
  const monthLabel = ym => MONTH_NAMES[+ym.slice(5, 7) - 1] + " " + ym.slice(0, 4);
  let period = "all"; try { const saved = localStorage.getItem("mxPeriod"); if (saved && d.months.includes(saved)) period = saved; } catch (e) {}
  const ZERO = { d10: 0, d15: 0, d20: 0, d31: 0, total: 0, done: 0 };
  const mOf = p => (p.months && p.months[period]) || ZERO;
  page.insertAdjacentHTML("beforeend", `
    <section class="card rise" style="--i:10;margin-bottom:16px"><div class="card-head"><div><h2>Сотрудники × сроки</h2><p class="sub" id="mx-sub"></p></div><div id="mx-ctl"></div></div>
      <div class="tablewrap"><table class="mx" id="mx"></table></div></section>`);
  /* "Сотрудники × сроки" stands right under the KPI cards */
  const mxSection = $("#mx", page).closest("section");
  mxSection.style.setProperty("--i", 6);
  $(".kpis", page).after(mxSection);
  $("#mx-ctl", page).appendChild(seg([["all", "Всего"]].concat(d.months.map(m => [m, monthLabel(m)])), period, v => { period = v; try { localStorage.setItem("mxPeriod", v); } catch (e) {} paintMatrix(); }));
  const monthBounds = (ym, a, b) => { const last = new Date(+ym.slice(0, 4), +ym.slice(5, 7), 0).getDate(); return { date_from: `${ym}-${String(a).padStart(2, "0")}`, date_to: `${ym}-${String(Math.min(b, last)).padStart(2, "0")}` }; };
  function paintMatrix() {
    const pc = Z.mode === "pct", month = period !== "all";
    $("#mx-sub", page).textContent = month
      ? `Задачи со сроком в месяце «${monthLabel(period)}»: сколько приходится на каждую часть месяца. Срок считается по выбранной выше дате. Нажмите на ячейку — откроется список.`
      : "Точные цифры. Чем насыщеннее цвет, тем больше задач в столбце. Нажмите на ячейку — откроется список.";
    const cols = month ? RANGES.map(r => ({ key: r[0], label: r[1], tip: r[2], cls: r[3] })).concat([{ key: "done", label: "Выполнено", tip: "Выполнено из задач месяца", cls: "k-done" }])
                       : MCOL.map(([k, l]) => ({ key: k, label: l, tip: l, cls: "k-" + k }));
    const val = (p, k) => month ? mOf(p)[k] : p[k];
    const tot = p => month ? mOf(p).total : p.total;
    const doneOf = p => month ? mOf(p).done : p.done;
    const pdone = p => { const t = tot(p) - (month ? 0 : p.info); return t > 0 ? Math.round(100 * doneOf(p) / t) : 0; };
    const colMax = {}; cols.forEach(c => colMax[c.key] = Math.max(1, ...people.map(p => val(p, c.key))));
    const head = `<thead><tr><th>Сотрудник</th><th>${month ? "За месяц" : "Всего"}</th>${cols.map(c => `<th><button class="lgd ${c.cls}" data-h="${c.key}" ${c.tip !== c.label ? `data-tip="<b>${esc(c.label)}</b>${esc(c.tip)}"` : ""} style="font-weight:500"><i></i>${esc(c.label)}</button></th>`).join("")}<th>% вып.</th></tr></thead>`;
    const cell = (p, c) => {
      const n = val(p, c.key), a = n ? (0.14 + 0.5 * n / colMax[c.key]).toFixed(2) : 0, t = tot(p);
      return `<td><button class="cell ${c.cls}${n ? "" : " z"}" style="--a:${a}" data-id="${p.id}" data-key="${c.key}" data-tip="<b>${esc(p.name)}</b>${esc(c.label)}: ${n} (${pct(n, t)}% его задач${month ? " месяца" : ""})"><span>${n ? (pc ? pct(n, t) + "%" : n) : "·"}</span></button></td>`;
    };
    const rows = people.map(p => `<tr class="r"><td><button class="pname" data-id="${p.id}">${avatar(p.id, p.name, "sm")}<span>${esc(p.id ? p.short : p.name)}</span></button></td>
      <td><button class="cell" data-id="${p.id}" data-key="all"><span>${tot(p)}</span></button></td>${cols.map(c => cell(p, c)).join("")}
      <td><div class="mini"><span class="num" style="min-width:34px">${pdone(p)}%</span><span class="m"><i style="width:${pdone(p)}%"></i></span></div></td></tr>`).join("");
    const sumOf = k => people.reduce((a, p) => a + val(p, k), 0), sumTot = people.reduce((a, p) => a + tot(p), 0), sumDone = people.reduce((a, p) => a + doneOf(p), 0);
    const sumPct = month ? pct(sumDone, sumTot) : T.pct_done;
    const sum = `<tr class="r" style="font-weight:700"><td style="padding:8px 14px">Итого</td><td><button class="cell" data-key="all"><span>${month ? sumTot : T.total}</span></button></td>${cols.map(c => { const n = month ? sumOf(c.key) : T[c.key]; return `<td><button class="cell" data-key="${c.key}"><span>${pc ? pct(n, month ? sumTot : T.total) + "%" : n}</span></button></td>`; }).join("")}<td><div class="mini"><span class="num" style="min-width:34px">${sumPct}%</span><span class="m"><i style="width:${sumPct}%"></i></span></div></td></tr>`;
    $("#mx", page).innerHTML = head + "<tbody>" + rows + sum + "</tbody>";
  }
  $("#mx", page).addEventListener("click", e => {
    const c = e.target.closest("[data-key],[data-h],.pname"); if (!c) return;
    const id = c.dataset.id; const extra = id !== undefined && id !== "" ? { assignee: id } : {};
    const key = c.dataset.h || c.dataset.key;
    if (c.classList.contains("pname")) return drill(extra);
    if (period === "all") {
      if (c.dataset.h) return bucketDrill(c.dataset.h);
      return key === "all" ? drill(extra) : bucketDrill(key, extra);
    }
    // a month is open: the list is limited to the days of that part of the month
    const r = RANGES.find(x => x[0] === key);
    const bounds = r ? monthBounds(period, r[4], r[5]) : monthBounds(period, 1, 31);
    drill(Object.assign({}, extra, bounds, key === "done" ? { status: "done" } : {}));
  });

  /* ---- kinds & documents ---- */
  const hb = (rows, label, param) => rows.map(r => {
    const mx = Math.max(1, ...rows.map(x => x.total));
    const rest = r.open - r.overdue;
    return `<button class="hb" data-v="${esc(r[param])}" data-tip="<b>${esc(r[param])}</b>Всего ${r.total} · просрочено ${r.overdue} · в работе ${rest} · выполнено ${r.done}">
      <span class="nm">${esc(r[param])}</span><div class="tr" data-w="${(r.total / mx) * 100}"><i class="k-overdue" data-w="${pct100(r.overdue, r.total)}"></i><i class="k-month" data-w="${pct100(rest, r.total)}"></i><i class="k-done" data-w="${pct100(r.done + r.info, r.total)}"></i></div>
      <span class="n num"><b>${r.total}</b></span></button>`;
  }).join("");
  page.insertAdjacentHTML("beforeend", `
    <section class="grid2 even">
      <div class="card rise" style="--i:11"><div class="card-head"><div><h2>По типам документов</h2><p class="sub">красный — просрочено · синий — в работе · зелёный — выполнено</p></div></div><div class="hbars" id="kinds">${hb(d.kinds, "kind", "kind")}</div></div>
      <div class="card rise" style="--i:12"><div class="card-head"><div><h2>Документы с наибольшим числом открытых задач</h2><p class="sub">Топ-10 по задачам в работе</p></div></div><div class="hbars" id="docs">${hb(d.docs, "doc", "doc")}</div></div>
    </section>`);
  $("#kinds", page).onclick = e => { const b = e.target.closest(".hb"); if (b) drill({ kind: b.dataset.v }); };
  $("#docs", page).onclick = e => { const b = e.target.closest(".hb"); if (b) drill({ doc: b.dataset.v }); };

  /* ---- start animations after first paint ---- */
  paintMatrix(); paintUnits();
  [...people].sort(sorters.open).forEach(p => peopleBox.appendChild(rowOf(p.id)));
  requestAnimationFrame(() => requestAnimationFrame(() => {
    applyBars();
    $$("circle[data-len]", donut).forEach((c, i) => { c.style.transitionDelay = i * 90 + "ms"; c.setAttribute("stroke-dasharray", `${c.dataset.len} ${100 - c.dataset.len}`); });
    $$(".col .b", page).forEach((b, i) => { b.style.transitionDelay = i * 70 + "ms"; b.style.height = Math.max(b.dataset.h, 0) + "%"; });
    $$(".hb .tr", page).forEach(t => { t.style.width = t.dataset.w + "%"; $$("i", t).forEach(i => i.style.width = i.dataset.w + "%"); });
  }));
  $$(".hb .tr", page).forEach(t => { t.style.width = "0%"; t.style.transition = "width .9s var(--ease)"; $$("i", t).forEach(i => i.style.width = "0%"); });
};
routes.dashboard.title = "Дашборд";
