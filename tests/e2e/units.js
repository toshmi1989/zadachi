// Department matrix and unit assignment in the browser. Needs the app on BASE with demo data where people are assigned to units.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.click("#to-manual").catch(() => {}); await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn");
  await p.waitForSelector("#um"); await p.waitForTimeout(1800);
  const heads = await p.$$eval("#um thead th", t => t.map(x => x.textContent.trim()));
  ok(heads.slice(1, 6).join(",") === "Фармон,Қарор,Баён,ВМ,ПА", "kind columns in the requested order: " + heads.join("|"));
  ok((await p.locator("#um tbody tr.total").count()) === 1 && /Департамент жами/.test(await p.textContent("#um tr.total")), "total row 'Департамент жами'");
  ok((await p.locator("#um tr.mgmt:not(.total)").count()) >= 6, "six managements are rows");
  await p.locator("#um").scrollIntoViewIfNeeded(); await p.waitForTimeout(500);
  await p.screenshot({ path: OUT + "/60-unit-matrix.png", fullPage: true });
  // collapse a management
  const kids = await p.locator('#um tr.kid:not([hidden])').count();
  await p.click('#um tr.mgmt[data-id] .chev:not(.off)'); await p.waitForTimeout(500);
  ok((await p.locator('#um tr.kid:not([hidden])').count()) < kids, "chevron collapses the divisions");
  await p.click('#um tr.mgmt[data-id] .chev:not(.off)'); await p.waitForTimeout(500);
  ok((await p.locator('#um tr.kid:not([hidden])').count()) === kids, "and expands them again");
  // metric switch
  const before = await p.textContent("#um tr.total");
  await p.click('#um-ctl button[data-v="overdue"]'); await p.waitForTimeout(500);
  ok((await p.textContent("#um tr.total")) !== before, "metric 'Просрочено' changes the numbers");
  await p.click('.seg button[data-v="pct"]'); await p.waitForTimeout(700);
  ok(/%/.test(await p.textContent("#um tbody tr.mgmt:not(.total)")), "percent mode shows %");
  await p.click('.seg button[data-v="count"]'); await p.click('#um-ctl button[data-v="total"]'); await p.waitForTimeout(400);
  // drill: a cell opens tasks for exactly that unit and kind
  const cell = p.locator('#um tr.kid .cell:not(.z)[data-kind]').first();
  const unit = await cell.getAttribute("data-unit"), kind = await cell.getAttribute("data-kind"), n = +(await cell.textContent());
  await cell.click(); await p.waitForSelector("#rows tr[data-id]");
  ok(p.url().includes("unit=" + unit) && p.url().includes("kind=" + encodeURIComponent(kind)), "cell opens the list filtered by unit and kind: " + decodeURIComponent(p.url().split("#")[1]));
  ok((await p.textContent("#sub")).includes(String(n)), "the list has exactly the number from the cell (" + n + ")");
  ok(await p.locator(".fchip").count() === 2, "two filter chips (department and type)");
  await p.screenshot({ path: OUT + "/61-unit-drill.png" });
  // bars per unit
  await p.goto(BASE + "/#/dashboard"); await p.waitForSelector("#ubars .prow"); await p.waitForTimeout(1500);
  ok(await p.locator("#ubars .prow").count() >= 10, "bars per unit are drawn");
  await p.locator("#ubars").scrollIntoViewIfNeeded(); await p.screenshot({ path: OUT + "/62-unit-bars.png" });
  await p.click("#ubars .prow.lvl1 .seg-b:not([style*='display: none'])"); await p.waitForSelector("#rows tr[data-id]");
  ok(/unit=\d+/.test(p.url()) && /(bucket|status)=/.test(p.url()), "a unit bar segment opens unit + deadline group");
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
  await mp.goto(BASE + "/login"); await mp.click("#to-manual").catch(() => {}); await mp.fill("#login", "admin"); await mp.fill("#pw2", "secret123"); await mp.click("#s-manual button.btn"); await mp.waitForSelector("#um"); await mp.waitForTimeout(1200);
  ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392)), "no horizontal page scroll on the phone (the matrix scrolls inside its card)");
  await mp.locator("#ubars").scrollIntoViewIfNeeded(); await mp.screenshot({ path: OUT + "/66-phone-units.png" });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
