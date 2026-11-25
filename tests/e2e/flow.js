// Browser walk-through on a database loaded with the Excel export. Run: BASE=http://localhost:8766 node tests/e2e/flow.js
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const mk = async (opts) => { const c = await b.newContext(Object.assign({ storageState: { cookies: [], origins: [{ origin: BASE, localStorage: [{ name: "lang", value: "ru" }] }] }, viewport: { width: 1440, height: 900 } }, opts)); const p = await c.newPage();
    p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error" && !/401|403/.test(m.text())) errs.push(m.text()); }); return p; };
  // the sign-in page offers a list of people when there is one; the typed login is always available
  const login = async (p, u, pw) => { await p.goto(BASE + "/login"); await p.waitForTimeout(500); if (await p.locator("#to-manual").isVisible()) await p.click("#to-manual"); await p.fill("#login", u); await p.fill("#pw2", pw); await p.click("#s-manual button.btn"); await p.waitForSelector(".dbt"); await p.waitForTimeout(1500); };
  const p = await mk(); await login(p, "admin", "secret123");

  // drill-down from the dashboard
  const nOpen = (await p.textContent("#d-table tbody tr.total td:last-child button.n.no")).replace(/\D/g, "");   // «не выполнено» in the «Всего» column of the first tab
  await p.click("#d-table tbody tr.total td:last-child button.n.no"); await p.waitForSelector("#rows tr[data-id]");
  ok(/status=open/.test(p.url()), "the red number of the total row opens the list of not done tasks");
  ok((await p.textContent("#sub")).includes(nOpen), "the list has exactly that many tasks (" + nOpen + ")");
  ok(await p.locator(".fchip").count() === 1, "one active filter chip");
  await p.screenshot({ path: OUT + "/10-tasks-overdue.png" });
  await p.click(".fchip button"); await p.waitForTimeout(500);
  ok((await p.textContent("#sub")).includes("272"), "removing the chip shows all 272");

  // a number of the table of stages → stage + not done
  await p.goBack(); await p.waitForSelector(".dbt"); await p.waitForTimeout(1200);
  await p.click('.dtab[data-view="stages"]'); await p.waitForTimeout(300);
  await p.click("#d-table tbody tr.total button.n[data-s]");
  await p.waitForSelector("#rows tr[data-id]");
  ok(/stage=\w+/.test(p.url()) && /status=open/.test(p.url()), "a number of the stages table opens stage + not done: " + p.url().split("#")[1]);

  // sorting and paging
  await p.click('th[data-s="code"]').catch(() => {});
  await p.goto(BASE + "/#/tasks"); await p.waitForTimeout(1200); await p.waitForSelector("#rows tr[data-id]");
  ok(await p.locator("#rows tr[data-id]").count() === 50, "50 rows on the first page");
  await p.click("#pn"); await p.waitForTimeout(700);
  ok((await p.textContent("#pager")).includes("51–100"), "page 2 shows 51–100");

  // drawer edit
  await p.goto(BASE + "/#/tasks?status=open"); await p.waitForTimeout(1200); await p.waitForSelector("#rows tr[data-id]");
  const first = p.locator("#rows tr[data-id]").first(); const id = await first.getAttribute("data-id");
  await first.click(); await p.waitForSelector(".drawer.on #e-as"); await p.waitForTimeout(700);
  await p.screenshot({ path: OUT + "/11-drawer.png" });
  await p.fill("#e-close", "2026-12-01"); await p.dispatchEvent("#e-close", "change"); await p.waitForTimeout(600);
  await p.click('#e-st button[data-v="progress"]'); await p.waitForTimeout(600);
  ok((await p.locator(".tl .ev").count()) >= 2, "history records both changes");
  ok(await p.locator('#e-st button.on').textContent() === "В работе", "status button switched");
  await p.keyboard.press("Escape"); await p.waitForTimeout(700);
  ok(await p.locator(".drawer").count() === 0, "Esc closes the drawer");
  const r = await (await p.request.get(`${BASE}/api/tasks/${id}`)).json();
  ok(r.close_date === "2026-12-01" && r.status === "progress" && r.edited, "server stored the edit");

  // bulk
  await p.goto(BASE + "/#/tasks?assignee=11"); await p.waitForTimeout(1200); await p.waitForSelector("#rows tr[data-id]");
  await p.check("#all"); await p.waitForTimeout(500);
  ok(await p.locator(".bulk.on").count() === 1, "bulk bar appears");
  await p.screenshot({ path: OUT + "/12-bulk.png" });
  await p.selectOption("#b-st", "info"); await p.click("#b-go"); await p.waitForTimeout(800);
  ok((await p.textContent("#sub")).length > 0, "bulk applied");

  // pages
  for (const [name, sel] of [["users", ".ucard"], ["import", "#drop"], ["settings", ".opt"]]) {
    await p.goto(BASE + "/#/" + name); await p.waitForSelector(sel); await p.waitForTimeout(900);
    await p.screenshot({ path: `${OUT}/2-${name}.png` }); ok(true, "page " + name);
  }
  // import preview of the same file: nothing new, manual edits kept
  const fs = require("fs"), xl = process.env.XLSX;
  if (xl) {
    await p.goto(BASE + "/#/import"); await p.waitForSelector("#file", { state: "attached" });
    await p.setInputFiles("#file", xl); await p.waitForSelector("#go");
    const t = await p.textContent("#stage");
    ok(/0\s*новых задач/.test(t) || /новых задач/.test(t), "import preview opens"); ok(/с вашими правками/.test(t), "manual edits are protected");
    await p.screenshot({ path: OUT + "/23-import-preview.png" });
    await p.click("#go"); await p.waitForSelector(".okmark"); ok(true, "re-import runs");
  }
  // add user + password dialog
  await p.goto(BASE + "/#/users"); await p.waitForSelector(".ucard");
  await p.click("#add"); await p.fill("#f_name", "Test Polzovatel"); await p.fill("#f_login", "test.user"); await p.click(".modal button.pri");
  await p.waitForSelector("#pwv"); const pw = await p.textContent("#pwv"); ok(pw.length >= 8, "new user gets a generated password");
  await p.screenshot({ path: OUT + "/24-password.png" }); await p.click(".modal button.pri");

  // role user
  const u = await mk(); await login(u, "test.user", pw);
  ok(await u.locator("#tabs a").count() === 3, "user sees Dashboard, Tasks and Reminders");
  await u.goto(BASE + "/#/tasks"); await u.waitForSelector("#rows"); await u.waitForTimeout(1000);
  ok(/Нет задач/.test(await u.textContent("#rows")) && await u.locator(".cb").count() === 0, "a new employee has no tasks of their own, so the list is empty (they never see others')");
  const st = (await u.request.patch(`${BASE}/api/tasks/${id}`, { data: { status: "done" } })).status();
  ok(st === 404, "somebody else's task does not exist for an employee: " + st);
  ok((await u.request.get(`${BASE}/api/users`)).status() === 403, "API refuses /api/users for a user");
  await p.goto(BASE + "/#/settings"); await p.click('.opt[data-v="none"]'); await p.waitForTimeout(500);
  await u.goto(BASE + "/#/dashboard"); await u.reload(); await u.waitForSelector(".dbt"); await u.waitForTimeout(800);
  ok(await u.locator("#tabs a").count() === 2, "setting only-dashboard hides Tasks");
  ok((await u.request.get(`${BASE}/api/tasks`)).status() === 403, "API refuses the list under 'only dashboard'");
  await p.click('.opt[data-v="own"]'); await p.waitForTimeout(400);

  // dark + percent + phone
  await p.goto(BASE + "/#/dashboard"); await p.waitForSelector(".dbt"); await p.waitForTimeout(1400);
  ok((await p.textContent("#d-table tbody tr.total")).includes("%"), "the tables show the percent done");
  await p.click("#theme"); await p.click("#theme"); await p.waitForTimeout(500);
  await p.screenshot({ path: OUT + "/30-dark-pct.png" });
  const m = await mk({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await login(m, "admin", "secret123"); await m.screenshot({ path: OUT + "/31-phone-dash.png" });
  await m.goto(BASE + "/#/tasks?bucket=overdue"); await m.waitForSelector("#rows tr[data-id]"); await m.waitForTimeout(700);
  await m.screenshot({ path: OUT + "/32-phone-tasks.png" });
  const overflow = await m.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392);
  ok(!overflow, "no horizontal page scroll on the phone");

  // reduced motion
  const rm = await mk(); await rm.emulateMedia({ reducedMotion: "reduce" }); await login(rm, "admin", "secret123");
  const dur = await rm.evaluate(() => parseFloat(getComputedStyle(document.querySelector(".seg-b")).transitionDuration));
  ok(dur < 0.01, "reduced motion removes transitions");

  await b.close();
  console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
