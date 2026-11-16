// Sync screen, the block in the task card and the links in the list. Run after: seed.py + collector.test.js with STOP_BEFORE_APPLY=1.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1440, height: 1000 } }); const p = await ctx.newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.click("#to-manual").catch(() => {}); await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn"); await p.waitForSelector(".kpi");
  ok(await p.locator('#tabs a[data-r="sync"]').count() === 1, "'Синхронизация' is in the menu for the administrator");
  await p.click('#tabs a[data-r="sync"]'); await p.waitForSelector("#s-rev .plain"); await p.waitForTimeout(900);
  await p.screenshot({ path: OUT + "/100-sync.png", fullPage: true });
  ok(/Установить скрипт/.test(await p.textContent("#s-how")) && (await p.getAttribute("#s-how a.pri", "href")) === "/ijro-sync.user.js", "install link points to the script");
  const rows = await p.locator("#s-rev tbody tr").count(); ok(rows === 5, "the default filter 'К применению' lists 5 tasks (4 done + 1 answered): " + rows);
  await p.click('#f-seg button[data-v="not_found"]'); await p.waitForTimeout(500); ok(/NOF0001/.test(await p.textContent("#s-rev tbody")) && await p.locator("#s-rev .r-one").count() === 0, "'Не найдены' has no checkboxes: nothing to apply");
  await p.click('#f-seg button[data-v="unknown"]'); await p.waitForTimeout(500); ok(/UNK0001/.test(await p.textContent("#s-rev tbody")) && /Неизвестный статус/.test(await p.textContent("#s-rev tbody")), "unknown status is listed and not applicable");
  await p.click('#f-seg button[data-v="apply"]'); await p.waitForTimeout(500);
  // key
  await p.fill("#k-name", "Ноутбук"); await p.click("#k-new"); await p.waitForSelector("#k-shown .pw"); ok(/^zk_/.test(await p.textContent("#k-shown .pw span")), "a key is shown once");
  // card template
  await p.fill("#k-tpl", "https://edo.ijro.uz/assignments/{section_path}/current-user/main/tasks/all/{id}"); await p.click("#k-tpl-save"); await p.waitForTimeout(700);
  // choose two and apply
  await p.locator("#s-rev tbody tr", { hasText: "OJN6944" }).locator(".r-one").check(); await p.locator("#s-rev tbody tr", { hasText: "VMK3541" }).locator(".r-one").check();
  ok((await p.textContent("#r-n")) === "2", "counter of chosen tasks");
  await p.click("#r-apply"); await p.waitForSelector(".modal button.pri"); await p.screenshot({ path: OUT + "/101-sync-confirm.png" }); await p.click(".modal button.pri"); await p.waitForTimeout(1200);
  ok((await p.locator("#s-rev tbody tr").count()) === 3, "after applying 2 of 5, 3 remain");
  // list: link to ijro and the chip
  await p.goto(BASE + "/#/tasks?q=XPG5469"); await p.waitForSelector("#rows tr[data-id]"); await p.waitForTimeout(800);
  const link = p.locator("#rows a.ext").first();
  const href = await link.getAttribute("href"); ok(/^https:\/\/edo\.ijro\.uz\/assignments\/president-assignments\/current-user\/main\/tasks\/all\/r-xpg$/.test(href), "the code in the list is a link to the exact task on ijro: " + href);
  ok(await link.getAttribute("target") === "_blank" && /noopener/.test(await link.getAttribute("rel")), "opens in a new tab, noopener");
  ok(/на сайте: Ответ дан/.test(await p.textContent("#rows")), "the list shows that the site disagrees");
  const [popup] = await Promise.all([ctx.waitForEvent("page", { timeout: 3000 }).catch(() => null), link.click()]); if (popup) await popup.close().catch(() => {});
  ok(!p.url().includes("drawer") && await p.locator(".drawer.on").count() === 0, "clicking the link does not open the drawer");
  await p.screenshot({ path: OUT + "/102-list-link.png" });
  // card
  await p.click("#rows tr[data-id] td:nth-child(3)"); await p.waitForSelector(".drawer.on .site-box"); await p.waitForTimeout(700);
  ok(/Ответы на сайте \(1\)/.test(await p.textContent(".site-box")) && /Ответ исполнителя/.test(await p.textContent(".site-box")), "the card shows the answers from the site");
  await p.screenshot({ path: OUT + "/103-card-site.png" });
  await p.click("#site-apply"); await p.waitForTimeout(1000);
  ok(/В работе/.test(await p.textContent(".stbtns button.on")) && await p.locator("#site-apply").count() === 0, "'Применить' in the card changes the status and the warning disappears");
  await p.keyboard.press("Escape"); await p.waitForTimeout(500);
  // phone
  const m = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }); const mp = await m.newPage();
  await mp.goto(BASE + "/login"); await mp.click("#to-manual").catch(() => {}); await mp.fill("#login", "admin"); await mp.fill("#pw2", "secret123"); await mp.click("#s-manual button.btn"); await mp.waitForSelector(".kpi");
  await mp.goto(BASE + "/#/sync"); await mp.waitForSelector("#s-rev"); await mp.waitForTimeout(900);
  ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392)), "no horizontal page scroll on the phone");
  await mp.screenshot({ path: OUT + "/104-sync-phone.png" });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
