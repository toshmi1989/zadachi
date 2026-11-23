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
  // tasks by their codes: only the codes are entered
  await a.click("#ed-add"); await a.waitForSelector("#nt-codes");
  ok(await a.locator(".modal input, .modal select").count() === 0 && await a.locator(".modal textarea").count() === 1, "adding asks only for the codes");
  await a.fill("#nt-codes", "edt1111, EDT2222\nnot-a-code"); await a.click(".modal button.pri"); await a.waitForSelector("#ed-rows tr[data-id]", { timeout: 8000 }); await a.waitForTimeout(1000);
  ok(/Добавлено: 2/.test(await a.textContent("body")), "two codes were added, the bad one is reported");
  await a.fill("#ed-q", "EDT1111"); await a.waitForTimeout(900);
  const newRow = a.locator("#ed-rows tr[data-id]").first();
  ok(/EDT1111/.test(await newRow.textContent()) && /ждёт данных с сайта/.test(await newRow.textContent()) && /по коду/.test(await newRow.textContent()), "the new task waits for its data from the site and is marked «по коду»");
  ok(/ждут данных с сайта/.test(await a.textContent("#ed-pend")), "a banner says that tasks wait for the script");
  await a.screenshot({ path: OUT + "/73-editor-codes.png" });
  // deleting
  const delId = await newRow.getAttribute("data-id");
  await newRow.locator(".ed-del").click(); await a.waitForSelector(".modal button.pri");
  await a.click(".modal [data-x]"); await a.waitForTimeout(300);
  ok((await a.request.get(BASE + `/api/tasks/${delId}`)).status() === 200, "«Отмена» keeps the task");
  await newRow.locator(".ed-del").click(); await a.waitForSelector(".modal button.pri"); await a.click(".modal button.pri"); await a.waitForTimeout(1200);
  ok((await a.request.get(BASE + `/api/tasks/${delId}`)).status() === 404 && /удалена/.test(await a.textContent("body")), "the task is deleted after the confirmation");
  await a.request.delete(BASE + `/api/tasks/${(await (await a.request.get(BASE + "/api/tasks?q=EDT2222&status=all")).json()).items[0].id}`);
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
