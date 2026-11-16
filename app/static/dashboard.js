"use strict";
/* Dashboard: KPI cards, workload per person (bars + exact matrix), structure donut, deadline columns, nearest terms.
   Every number, bar, slice and column is a button: it opens the task list filtered to exactly what was clicked. */

function drill(p) {
  if (Z.me.tasks === "none") { toast("Список задач для вашей роли отключён администратором", "error"); return; }
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
  ctl.appendChild(byToggle(() => route()));
  const modeBox = document.createElement("div"); modeBox.className = "ctl"; modeBox.innerHTML = "<span>Показывать:</span>";
  modeBox.appendChild(seg([["count", "Количество"], ["pct", "Проценты"]], Z.mode, v => { Z.mode = v; try { localStorage.setItem("mode", v); } catch (e) {} applyMode(); }));
  ctl.appendChild(modeBox);

  let hint = "";
  try { if (!localStorage.getItem("hint1") && !scopeNote) hint = `<div class="hint-banner rise" style="--i:1" id="hint">${icon("info")}<span>Нажимайте на карточки, полосы, сектора и столбцы — откроется список именно этих задач.</span><button class="icon-btn" style="margin-left:auto;width:28px;height:28px;border:0;background:none;color:inherit" aria-label="Скрыть">${icon("x")}</button></div>`; } catch (e) {}

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
  function applyMode() { paintKpi(false); applyBars(); paintMatrix(); }
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

  /* ---- matrix: exact numbers ---- */
  const MCOL = [["overdue", "Просрочено"], ["week", "≤ 7 дн."], ["month", "8–30 дн."], ["later", "> 30 дн."], ["nodate", "Без срока"], ["done", "Выполнено"]];
  page.insertAdjacentHTML("beforeend", `
    <section class="card rise" style="--i:10;margin-bottom:16px"><div class="card-head"><div><h2>Сотрудники × сроки</h2><p class="sub">Точные цифры. Чем насыщеннее цвет, тем больше задач в столбце. Нажмите на ячейку — откроется список.</p></div></div>
      <div class="tablewrap"><table class="mx" id="mx"></table></div></section>`);
  const colMax = {}; MCOL.forEach(([k]) => colMax[k] = Math.max(1, ...people.map(p => p[k])));
  function paintMatrix() {
    const pc = Z.mode === "pct";
    const head = `<thead><tr><th>Сотрудник</th><th>Всего</th>${MCOL.map(([k, l]) => `<th><button class="lgd k-${k}" data-h="${k}" style="font-weight:500"><i></i>${l}</button></th>`).join("")}<th>% вып.</th></tr></thead>`;
    const cell = (p, k) => {
      const n = p[k], a = n ? (0.14 + 0.5 * n / colMax[k]).toFixed(2) : 0;
      return `<td><button class="cell k-${k}${n ? "" : " z"}" style="--a:${a}" data-id="${p.id}" data-key="${k}" data-tip="<b>${esc(p.name)}</b>${LABEL[k]}: ${n} (${pct(n, p.total)}%)"><span>${n ? (pc ? pct(n, p.total) + "%" : n) : "·"}</span></button></td>`;
    };
    const rows = people.map(p => `<tr class="r"><td><button class="pname" data-id="${p.id}">${avatar(p.id, p.name, "sm")}<span>${esc(p.id ? p.short : p.name)}</span></button></td>
      <td><button class="cell" data-id="${p.id}" data-key="all"><span>${p.total}</span></button></td>${MCOL.map(([k]) => cell(p, k)).join("")}
      <td><div class="mini"><span class="num" style="min-width:34px">${p.pct_done}%</span><span class="m"><i style="width:${p.pct_done}%"></i></span></div></td></tr>`).join("");
    const sum = `<tr class="r" style="font-weight:700"><td style="padding:8px 14px">Итого</td><td><button class="cell" data-key="all"><span>${T.total}</span></button></td>${MCOL.map(([k]) => `<td><button class="cell" data-key="${k}"><span>${pc ? pct(T[k], T.total) + "%" : T[k]}</span></button></td>`).join("")}<td><div class="mini"><span class="num" style="min-width:34px">${T.pct_done}%</span><span class="m"><i style="width:${T.pct_done}%"></i></span></div></td></tr>`;
    $("#mx", page).innerHTML = head + "<tbody>" + rows + sum + "</tbody>";
  }
  $("#mx", page).addEventListener("click", e => {
    const c = e.target.closest("[data-key],[data-h],.pname"); if (!c) return;
    const id = c.dataset.id; const extra = id !== undefined && id !== "" ? { assignee: id } : {};
    if (c.dataset.h) return bucketDrill(c.dataset.h);
    if (c.classList.contains("pname")) return drill(extra);
    if (c.dataset.key === "all") return drill(extra);
    bucketDrill(c.dataset.key, extra);
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
  paintMatrix();
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
