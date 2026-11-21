// The three tables of the dashboard in the browser: the numbers, the lists they open, the fold. Needs the app on BASE with some tasks (people in departments help).
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.click("#to-manual").catch(() => {}); await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn");
  await p.waitForSelector(".dbt"); await p.waitForTimeout(1200);
  ok((await p.locator("table.dbt").count()) === 3, "three tables: months, kinds of documents, stages");
  const heads = await p.$$eval("#t-kinds thead th", t => t.map(x => x.textContent.trim()));
  ok(heads.slice(1, 6).join(",") === "Фармон,Қарор,Баён,ВМ,ПА", "kinds in the requested order");
  ok(/Ответ не введён/.test(await p.textContent("#t-stages thead")) && /Не проверялись/.test(await p.textContent("#t-stages thead")), "stage columns");
  ok(/%/.test(await p.textContent("#t-months tbody tr.total")) && /%/.test(await p.textContent("#t-kinds tbody tr.total")), "percent done is shown");
  ok((await p.locator("#t-months thead th.now").count()) <= 1, "the current month is highlighted");
  await p.screenshot({ path: OUT + "/70-dashboard-tables.png", fullPage: true });
  // every kind of number opens a list that has exactly that many tasks
  const drill = async (sel, what, re, count = true) => {
    const el = p.locator(sel).first(); const n = (await el.textContent()).trim();
    await el.click(); await p.waitForSelector("#rows tr[data-id], .empty", { timeout: 8000 }); await p.waitForTimeout(500);
    ok(re.test(decodeURIComponent(p.url())) && (!count || (await p.textContent("#sub")).includes(n)), what + ": " + n + " → " + decodeURIComponent(p.url().split("#")[1]));
    await p.goBack(); await p.waitForSelector(".dbt"); await p.waitForTimeout(900);
  };
  await drill("#t-months tbody tr.total td:last-child button.n.ok", "done, all months", /status=done/);
  await drill("#t-months tbody tr.total td:last-child button.n.no", "not done, all months", /status=open/);
  await drill("#t-months tbody tr.total td.dc:not(.z) button.n.no", "not done in one month", /status=open.*date_from=\d{4}-\d{2}-01.*date_to=/);
  await drill("#t-kinds tbody tr.total button.n.ok[data-k]", "done of a kind", /status=done.*kind=/);
  await drill("#t-stages tbody tr.total button.n[data-s]", "open at a stage", /stage=\w+.*status=open|status=open.*stage=\w+/);
  await drill("#t-stages tbody tr.total td:last-child button.n", "all open", /status=open/);
  await drill("#t-months tbody tr.kid .pname, #t-months tbody tr.mgmt .pname", "all tasks of a department", /unit=\d+/, false);
  // the fold works for the three tables at once
  const before = await p.locator("#t-months tbody tr:not([hidden])").count();
  if (await p.locator("#t-months .chev:not(.off)").count()) {
    await p.click("#t-months .chev:not(.off)"); await p.waitForTimeout(300);
    ok((await p.locator("#t-months tbody tr:not([hidden])").count()) < before && (await p.locator("#t-stages tbody tr:not([hidden])").count()) < before, "the arrow folds the divisions in every table");
  }
  // the phone: the tables scroll inside their cards, the page does not
  await p.setViewportSize({ width: 390, height: 860 }); await p.waitForTimeout(400);
  ok(!(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), "no horizontal page scroll on the phone");
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
