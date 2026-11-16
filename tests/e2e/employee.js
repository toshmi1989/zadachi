// An employee in the browser: sees only their own tasks, changes their status. Needs a database seeded with tests/ijro/seed.py.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const actx = await b.newContext({ viewport: { width: 1440, height: 900 } }); const a = await actx.newPage();
  await a.goto(BASE + "/login"); await a.click("#to-manual").catch(() => {}); await a.fill("#login", "admin"); await a.fill("#pw2", "secret123"); await a.click("#s-manual button.btn"); await a.waitForSelector(".kpi");
  const api = async (m, p, body) => (await (await a.request.fetch(BASE + p, { method: m, data: body })).json());
  const users = (await api("GET", "/api/users")).items, me = users.find(u => u.login === "test.p");
  const other = await api("POST", "/api/users", { login: "other.o", name: "Other Olga", role: "user", password: "other-pass-1" });
  const list = (await api("GET", "/api/tasks?size=50&sort=num")).items;
  const give = list.filter(t => !/DON/.test(t.code)).slice(0, 2).map(t => t.id);
  await api("POST", "/api/tasks/bulk", { ids: give, assignee_id: other.id });
  const pw = (await api("POST", `/api/users/${me.id}/password`, {})).password;

  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); const p = await ctx.newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error" && !/403|404/.test(m.text())) errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.waitForSelector(".pitem"); await p.click(`.pitem:has-text("Test Person")`); await p.fill("#pw1", pw); await p.click("#s-pass button.btn"); await p.waitForSelector(".kpi"); await p.waitForTimeout(1200);
  ok((await p.textContent('#tabs a[data-r="tasks"]')).includes("Мои задачи"), "the menu says 'Мои задачи'");
  ok(/ваши/.test(await p.textContent("#hint")), "the dashboard explains that the list shows their own tasks");
  await p.goto(BASE + "/#/tasks"); await p.waitForSelector("#rows tr[data-id]"); await p.waitForTimeout(900);
  const codes = await p.$$eval("#rows tr[data-id] .code", t => t.map(x => x.textContent));
  ok(codes.length === 7, "the list has only their 7 tasks (9 minus the 2 given to somebody else): " + codes.length);
  const givenCodes = list.filter(t => give.includes(t.id)).map(t => t.code);
  ok(givenCodes.every(c => !codes.join(" ").includes(c)), "the tasks of the other person are not in the list");
  ok(await p.locator("#f-assignee").count() === 0 && await p.locator("#f-unit").count() === 0 && await p.locator(".cb").count() === 0, "no filters by people, no checkboxes, no bulk");
  const quick = await p.locator("[data-quick]").count(); ok(quick === 6, "a quick 'done' button on each of their 6 open tasks (the done one has none): " + quick);
  await p.screenshot({ path: OUT + "/110-employee-list.png" });
  // quick done and undo
  const row = p.locator("#rows tr[data-id]").first(); const rid = await row.getAttribute("data-id");
  await row.locator("[data-quick]").click(); await p.waitForSelector(".toast button"); await p.waitForTimeout(700);
  ok(/Выполнено/.test(await p.locator(`#rows tr[data-id="${rid}"] td:nth-child(6)`).textContent()), "marked done from the list");
  ok(await p.locator(`#rows tr[data-id="${rid}"] [data-quick]`).count() === 0, "a done task has no quick button");
  await p.click(".toast button"); await p.waitForTimeout(900);
  ok(await p.locator(`#rows tr[data-id="${rid}"] [data-quick]`).count() === 1, "'Отменить' brings it back");
  // the card
  await p.locator(`#rows tr[data-id="${rid}"] td:nth-child(3)`).click(); await p.waitForSelector(".drawer.on #e-st"); await p.waitForTimeout(700);
  ok(await p.locator("#e-as").count() === 0 && await p.locator("#e-close").count() === 0, "the card has no assignee or date fields");
  ok((await p.locator("#e-st button").allTextContents()).join("|") === "Не выполнено|В работе|Выполнено", "three statuses, no 'К сведению'");
  ok(!(await p.getAttribute("#e-st", "class")).includes("ro"), "the status buttons are active");
  await p.click('#e-st button[data-v="progress"]'); await p.waitForTimeout(900);
  ok((await p.textContent("#e-st button.on")) === "В работе" && /Test Person/.test(await p.textContent(".tl")), "status saved, the history names the employee");
  ok(!/Официальный срок/.test(await p.textContent(".drawer")), "the official term is still hidden");
  await p.screenshot({ path: OUT + "/111-employee-card.png" });
  await p.keyboard.press("Escape"); await p.waitForTimeout(500);
  // the dashboard does not open other people's lists
  await p.goto(BASE + "/#/dashboard"); await p.waitForSelector(".prow"); await p.waitForTimeout(1500);
  await p.locator('.prow:has-text("Other") .pname').first().click(); await p.waitForTimeout(500);
  ok(/доступны только ваши/.test(await p.textContent("#toasts")), "a click on somebody else's row says why nothing opens");
  ok(p.url().includes("dashboard"), "and stays on the dashboard");
  // API: the server says no too
  const t0 = givenCodes[0], gid = give[0];
  const r1 = await p.request.fetch(`${BASE}/api/tasks/${gid}`, { method: "PATCH", data: { status: "done" } }); ok(r1.status() === 404, "somebody else's task: 404 from the server (" + r1.status() + ")");
  const r2 = await p.request.fetch(`${BASE}/api/tasks/${rid}`, { method: "PATCH", data: { assignee_id: null } }); ok(r2.status() === 403, "own task, but another field: 403 (" + r2.status() + ")");
  // phone
  const m = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }); const mp = await m.newPage();
  await mp.goto(BASE + "/login"); await mp.waitForSelector(".pitem"); await mp.click(`.pitem:has-text("Test Person")`); await mp.fill("#pw1", pw); await mp.click("#s-pass button.btn"); await mp.waitForSelector(".kpi");
  await mp.goto(BASE + "/#/tasks"); await mp.waitForSelector("#rows tr[data-id]"); await mp.waitForTimeout(900);
  ok(await mp.locator("[data-quick]").first().isVisible(), "the quick button is visible on a phone");
  ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392)), "no horizontal scroll on the phone");
  await mp.screenshot({ path: OUT + "/112-employee-phone.png" });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
