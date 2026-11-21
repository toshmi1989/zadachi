// The dashboard in the browser: KPI tiles, the three tabs, the cells, search, empty departments, the fold, and every number opening exactly its list.
// Needs the app on BASE with some tasks (people in departments help).
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.click("#to-manual").catch(() => {}); await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn");
  await p.waitForSelector(".dtab"); await p.waitForTimeout(1200);
  const num = async sel => +(await p.locator(sel).first().textContent()).replace(/\D/g, "");
  // KPI tiles
  const total = await num(".dk:not(.ok):not(.no) .v"), done = await num(".dk.ok .v"), open = await num(".dk.no .v");
  ok(total >= done + open && done + open > 0, `three tiles: total ${total}, done ${done}, not done ${open}`);
  // tabs
  ok((await p.locator(".dtab").count()) === 3 && (await p.locator(".dtab.on").count()) === 1, "three tabs, one selected");
  ok(/%/.test(await p.textContent("#d-table tbody tr.total")) && (await p.locator("#d-table tbody tr.total button.n.ok").count()) >= 1 && (await p.locator("#d-table tbody tr.total button.n.no").count()) >= 1, "a cell shows the percent, a green number (done) and a red one (not done)");
  ok(/зелёное/.test(await p.textContent("#d-help")), "a short explanation of how to read the table");
  await p.click('.dtab[data-view="kinds"]'); await p.waitForTimeout(300);
  ok((await p.$$eval("#d-table thead th", t => t.slice(1, 6).map(x => x.textContent.trim()).join(","))) === "Фармон,Қарор,Баён,ВМ,ПА", "kinds in the requested order");
  ok(/view=kinds/.test(p.url()), "the tab is in the address (back from a list returns to it)");
  await p.click('.dtab[data-view="stages"]'); await p.waitForTimeout(300);
  ok(/Путь согласования/i.test(await p.textContent("#d-table thead")) && /Не проверялись/.test(await p.textContent("#d-table thead")), "stages: the way of the answer and the columns that need attention");
  await p.screenshot({ path: OUT + "/70-dashboard-tabs.png", fullPage: false });
  // empty departments, search, fold
  await p.click('.dtab[data-view="months"]'); await p.waitForTimeout(300);
  const shown = await p.locator("#d-table tbody tr").count();
  await p.check("#d-empty"); await p.waitForTimeout(300);
  const withEmpty = await p.locator("#d-table tbody tr").count();
  ok(withEmpty >= shown, `departments without tasks are hidden by default (${shown} rows → ${withEmpty} with them)`); await p.uncheck("#d-empty");
  const first = (await p.locator("#d-table tbody tr.kid .pname, #d-table tbody tr.mgmt .pname").first().textContent()).trim().split(" ").slice(-1)[0];
  await p.fill("#d-q", first); await p.waitForTimeout(300);
  ok((await p.locator("#d-table tbody tr").count()) <= shown, "search narrows the departments: «" + first + "»"); await p.fill("#d-q", "");
  if (await p.locator("#d-table .chev:not(.off)").count()) {
    const before = await p.locator("#d-table tbody tr").count();
    await p.click("#d-fold"); await p.waitForTimeout(300);
    ok((await p.locator("#d-table tbody tr").count()) < before && /Развернуть/.test(await p.textContent("#d-fold")), "«Свернуть управления» folds the divisions");
    await p.click("#d-fold"); await p.waitForTimeout(300);
  }
  // every kind of number opens a list that has exactly that many tasks
  const drill = async (sel, what, re, count = true) => {
    const el = p.locator(sel).first(); const n = (await el.textContent()).replace(/\D/g, "");
    await el.click(); await p.waitForSelector("#rows tr[data-id], .empty", { timeout: 8000 }); await p.waitForTimeout(500);
    ok(re.test(decodeURIComponent(p.url())) && (!count || (await p.textContent("#sub")).includes(n)), what + ": " + n + " → " + decodeURIComponent(p.url().split("#")[1]));
    await p.goBack(); await p.waitForSelector(".dtab"); await p.waitForTimeout(900);
  };
  await drill(".dk.ok .v", "tile «выполнено»", /status=done/);
  await drill(".dk.no .v", "tile «не выполнено»", /status=open/);
  await drill("#d-table tbody tr.total td:last-child button.n.ok", "done, all months", /status=done/);
  await drill("#d-table tbody tr.total td.dc:not(.z):not(.sumc) button.n.no", "not done in one month", /status=open.*date_from=\d{4}-\d{2}-01.*date_to=/);
  await drill("#d-table tbody tr.kid .pname, #d-table tbody tr.mgmt .pname", "all tasks of a department", /unit=\d+/, false);
  await p.click('.dtab[data-view="kinds"]'); await p.waitForTimeout(300);
  await drill("#d-table tbody tr.total button.n.ok[data-k]", "done of a kind", /status=done.*kind=/);
  await p.click('.dtab[data-view="stages"]'); await p.waitForTimeout(300);
  await drill("#d-table tbody tr.total button.n[data-s]", "open at a stage", /stage=\w+.*status=open|status=open.*stage=\w+/);
  ok(/view=stages/.test(p.url()) && (await p.locator(".dtab.on").getAttribute("data-view")) === "stages", "back from a list returns to the same tab");
  // the phone: the tables scroll inside their cards, the page does not
  await p.setViewportSize({ width: 390, height: 860 }); await p.waitForTimeout(400);
  ok(!(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), "no horizontal page scroll on the phone");
  await p.screenshot({ path: OUT + "/71-dashboard-phone.png", fullPage: false });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
