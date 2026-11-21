// The editor of tasks: the administrator and the specialist change the execution date, the responsible person and the status right in the row, and add a task by hand.
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const a = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
  a.on("pageerror", e => errs.push(e.message)); a.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await a.goto(BASE + "/login"); await a.click("#to-manual").catch(() => {}); await a.fill("#login", "admin"); await a.fill("#pw2", "secret123"); await a.click("#s-manual button.btn"); await a.waitForSelector(".dtab");
  // a specialist account
  const mk = await a.request.post(BASE + "/api/users", { data: { name: "Special Tester", login: "special.tester", role: "specialist" } });
  const users = (await (await a.request.get(BASE + "/api/users")).json()).items; const sp = users.find(u => u.login === "special.tester");
  const pw = (await (await a.request.post(BASE + `/api/users/${sp.id}/password`, { data: {} })).json()).password;
  // the administrator
  await a.goto(BASE + "/#/editor"); await a.waitForSelector("#ed-rows tr[data-id]"); await a.waitForTimeout(600);
  ok((await a.locator("#tabs a").allTextContents()).some(t => /Редактор/.test(t)), "«Редактор» is in the menu");
  const row = a.locator("#ed-rows tr[data-id]").first(), id = await row.getAttribute("data-id");
  await row.locator('input[data-f="close_date"]').fill("2026-12-17"); await row.locator('input[data-f="close_date"]').dispatchEvent("change");
  await a.waitForSelector(`#ed-rows tr[data-id="${id}"] .ed-saved`, { timeout: 5000 });
  ok((await (await a.request.get(BASE + `/api/tasks/${id}`)).json()).close_date === "2026-12-17", "the execution date is saved at once");
  const who = await row.locator('select[data-f="assignee_id"] option').nth(1).getAttribute("value");
  await row.locator('select[data-f="assignee_id"]').selectOption(who); await a.waitForSelector(`#ed-rows tr[data-id="${id}"] .ed-saved`, { timeout: 5000 });
  ok(String((await (await a.request.get(BASE + `/api/tasks/${id}`)).json()).assignee_id) === who, "the responsible person is saved at once");
  await a.screenshot({ path: OUT + "/72-editor.png", fullPage: false });
  // a task by hand
  await a.click("#ed-add"); await a.fill("#nt-text", "Подготовить справку для проверки редактора"); await a.selectOption("#nt-kind", "Қарор"); await a.fill("#nt-doc", "ПҚ-1 от 01.12.2026"); await a.fill("#nt-close", "2026-12-12");
  await a.click(".modal button.pri"); await a.waitForSelector("#ed-rows tr[data-id]", { timeout: 8000 }); await a.waitForTimeout(800);
  ok(/вручную/.test(await a.textContent("#ed-rows")) && /^M\d{5}/.test((await a.locator("#ed-rows tr .code b").first().textContent()).trim()), "the new task is in the list with its own code and the mark «вручную»");
  // the specialist
  const s = await (await b.newContext({ viewport: { width: 1400, height: 1000 } })).newPage();
  s.on("pageerror", e => errs.push(e.message));
  await s.goto(BASE + "/login"); await s.waitForSelector("#to-manual, #login", { timeout: 8000 }); if (await s.locator("#to-manual").isVisible()) await s.click("#to-manual");
  await s.fill("#login", "special.tester"); await s.fill("#pw2", pw); await s.click("#s-manual button.btn"); await s.waitForSelector(".dtab", { timeout: 8000 });
  const menu = (await s.locator("#tabs a").allTextContents()).join("|");
  ok(/Редактор/.test(menu) && /Задачи/.test(menu) && !/Пользователи|Импорт|Синхронизация|Настройки/.test(menu), "the specialist's menu: dashboard, tasks, editor; nothing of the administrator's: " + menu);
  await s.goto(BASE + "/#/editor"); await s.waitForSelector("#ed-rows tr[data-id]"); await s.waitForTimeout(500);
  ok(!/официальный/.test(await s.textContent("#ed-rows")), "the specialist does not see the official term");
  const sr = s.locator("#ed-rows tr[data-id]").first(), sid = await sr.getAttribute("data-id");
  await sr.locator('input[data-f="close_date"]').fill("2026-12-21"); await sr.locator('input[data-f="close_date"]').dispatchEvent("change");
  await s.waitForSelector(`#ed-rows tr[data-id="${sid}"] .ed-saved`, { timeout: 5000 });
  ok(true, "the specialist changes the execution date");
  await s.goto(BASE + "/#/import"); await s.waitForTimeout(800);
  ok(/только администратору|Раздел доступен/.test(await s.textContent("#view")), "the import page is refused to the specialist");
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
