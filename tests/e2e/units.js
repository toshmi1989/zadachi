// Department matrix and unit assignment in the browser. Needs the app on BASE with demo data where people are assigned to units.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.click("#to-manual").catch(() => {}); await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn");
  await p.waitForSelector("#d-table"); await p.click('.dtab[data-view="kinds"]'); await p.waitForTimeout(1500);
  const heads = await p.$$eval("#d-table thead th", t => t.map(x => x.textContent.trim()));
  ok(heads.slice(1, 6).join(",") === "Фармон,Қарор,Баён,ВМ,ПА", "kind columns in the requested order: " + heads.join("|"));
  ok((await p.locator("#d-table tbody tr.total").count()) === 1 && /Департамент жами/.test(await p.textContent("#d-table tr.total")), "total row 'Департамент жами'");
  ok((await p.locator("#d-table tr.mgmt:not(.total)").count()) >= 6, "six managements are rows");
  await p.click('.dtab[data-view="months"]'); await p.waitForTimeout(300); const nm = await p.locator("#d-table thead th").count();
  await p.click('.dtab[data-view="stages"]'); await p.waitForTimeout(300); const ns = await p.locator("#d-table thead th").count();
  ok(nm >= 3 && ns >= 8, "months and stages tabs are drawn"); await p.click('.dtab[data-view="kinds"]'); await p.waitForTimeout(300);
  await p.locator("#d-table").scrollIntoViewIfNeeded(); await p.waitForTimeout(500);
  await p.screenshot({ path: OUT + "/60-dashboard-tables.png", fullPage: true });
  // collapse a management: the three tables fold together
  const kids = await p.locator('#d-table tr.kid:not([hidden])').count();
  await p.click('#d-table tr.mgmt .chev:not(.off)'); await p.waitForTimeout(500);
  ok((await p.locator('#d-table tr.kid:not([hidden])').count()) < kids && true, "chevron collapses the divisions");
  await p.click('#d-table tr.mgmt .chev:not(.off)'); await p.waitForTimeout(500);
  ok((await p.locator('#d-table tr.kid:not([hidden])').count()) === kids, "and expands them again");
  // drill: a number opens tasks for exactly that unit and kind
  const cell = p.locator('#d-table tr.kid button.n[data-k]').first();
  const unit = await cell.getAttribute("data-u"), kind = await cell.getAttribute("data-k"), st = await cell.getAttribute("data-st"), n = +(await cell.textContent());
  await cell.click(); await p.waitForSelector("#rows tr[data-id]");
  ok(p.url().includes("unit=" + unit) && p.url().includes("kind=" + encodeURIComponent(kind)) && p.url().includes("status=" + st), "number opens the list filtered by unit, kind and status: " + decodeURIComponent(p.url().split("#")[1]));
  ok((await p.textContent("#sub")).includes(String(n)), "the list has exactly the number from the cell (" + n + ")");
  ok(await p.locator(".fchip").count() === 3, "three filter chips (department, type, status)");
  await p.screenshot({ path: OUT + "/61-unit-drill.png" });
  // task list: unit filter
  await p.goto(BASE + "/#/tasks"); await p.waitForSelector("#f-unit"); await p.waitForTimeout(800);
  await p.selectOption("#f-unit", "0"); await p.waitForTimeout(800);
  ok(/без отдела/.test(await p.textContent("#chips")), "filter 'Без отдела' works");
  // users page: assign unit
  await p.goto(BASE + "/#/users"); await p.waitForSelector(".ucard"); await p.waitForTimeout(800);
  await p.screenshot({ path: OUT + "/63-users-units.png" });
  const card = p.locator(".ucard", { hasText: "Without Unit" });
  await card.locator('[data-a="edit"]').click(); await p.waitForSelector("#f_unit");
  await p.selectOption("#f_unit", await p.$eval("#f_unit", sel => [...sel.options].find(o => /Ташхислаш/.test(o.textContent)).value)); await p.screenshot({ path: OUT + "/64-user-dialog.png" });
  await p.click(".modal button.pri"); await p.waitForTimeout(900);
  ok(/Ташхислаш/.test(await p.locator(".ucard", { hasText: "Without Unit" }).textContent()), "user card shows the department after saving");
  // settings: structure editor
  await p.goto(BASE + "/#/settings"); await p.waitForSelector("#u-add"); await p.waitForTimeout(900);
  ok(await p.locator(".unit-row").count() >= 12, "structure editor lists all units");
  await p.screenshot({ path: OUT + "/65-structure.png", fullPage: true });
  await p.click("#u-add"); await p.fill("#f_name", "Тестовое управление"); await p.click(".modal button.pri"); await p.waitForTimeout(900);
  ok(await p.locator(".unit-row", { hasText: "Тестовое управление" }).count() === 1, "a new management is added");
  const row = p.locator(".unit-row", { hasText: "Тестовое управление" });
  await row.locator('[data-a="add"]').click(); await p.fill("#f_name", "Тестовый отдел"); await p.click(".modal button.pri"); await p.waitForTimeout(900);
  ok(await p.locator(".unit-row.kid", { hasText: "Тестовый отдел" }).count() === 1, "a division is added inside it");
  await p.locator(".unit-row.kid", { hasText: "Тестовый отдел" }).locator('[data-a="del"]').click(); await p.click(".modal button.pri"); await p.waitForTimeout(800);
  await p.locator(".unit-row", { hasText: "Тестовое управление" }).locator('[data-a="del"]').click(); await p.click(".modal button.pri"); await p.waitForTimeout(800);
  ok(await p.locator(".unit-row", { hasText: "Тестов" }).count() === 0, "empty units can be deleted");
  // phone
  const m = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }); const mp = await m.newPage();
  await mp.goto(BASE + "/login"); await mp.click("#to-manual").catch(() => {}); await mp.fill("#login", "admin"); await mp.fill("#pw2", "secret123"); await mp.click("#s-manual button.btn"); await mp.waitForSelector("#d-table"); await mp.waitForTimeout(1200);
  ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392)), "no horizontal page scroll on the phone (the tables scroll inside their cards)");
  await mp.locator("#d-table").scrollIntoViewIfNeeded(); await mp.screenshot({ path: OUT + "/66-phone-units.png" });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
