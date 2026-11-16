// Browser walk-through of the reminders page against a fake Telegram (tests/fake_telegram.py on :9911).
// Run the app with TELEGRAM_BOT_TOKEN=123456:TEST-TOKEN TELEGRAM_API=http://127.0.0.1:9911, then: BASE=... node tests/e2e/reminders.js
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766", OUT = process.env.OUT || "/tmp/zrun/shots", FAKE = "http://127.0.0.1:9911";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const sent = async () => (await fetch(FAKE + "/__sent")).json();
(async () => {
  const b = await chromium.launch(); const errs = [];
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); const p = await ctx.newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
  await p.goto(BASE + "/login"); await p.fill("#login", "admin"); await p.fill("#password", "secret123"); await p.click("button.btn.pri");
  await p.waitForSelector(".kpi"); await p.click('#tabs a[data-r="reminders"]'); await p.waitForSelector("#tg-link"); await p.waitForTimeout(900);
  await p.screenshot({ path: OUT + "/40-rem-unlinked.png", fullPage: true });

  await p.click("#tg-link"); await p.waitForSelector("#linkarea a.tg");
  const href = await p.getAttribute("#linkarea a.tg", "href"); const code = href.split("start=")[1];
  ok(/^https:\/\/t\.me\/zadachi_test_bot\?start=.{8,}/.test(href), "deep link built: " + href.replace(code, "<code>"));
  await p.screenshot({ path: OUT + "/41-rem-waiting.png" });
  await fetch(FAKE + "/__push", { method: "POST", body: JSON.stringify({ chat_id: 777, text: "/start " + code, username: "admin_tg" }) });
  await p.waitForSelector(".tgico.ok", { timeout: 20000 }); ok(true, "page notices the link by itself");
  ok((await sent()).some(m => /Готово/.test(m.text)), "bot confirmed in the chat");
  await p.click("#tg-test"); await p.waitForTimeout(800); ok((await sent()).some(m => /Проверка связи/.test(m.text)), "test message arrives");

  await p.click('#m-rules .tgc[data-v="14"]'); await p.waitForTimeout(900);
  let me = await (await p.request.get(BASE + "/api/reminders/me")).json(); ok(me.mine.days.includes(14) && me.mine.custom_days, "personal day chip saved");
  await p.selectOption("#m-over", "3"); await p.waitForTimeout(900);
  me = await (await p.request.get(BASE + "/api/reminders/me")).json(); ok(me.mine.overdue === 3, "personal overdue frequency saved");
  await p.click("#m-reset"); await p.waitForTimeout(900);
  me = await (await p.request.get(BASE + "/api/reminders/me")).json(); ok(!me.mine.custom_days && !me.mine.custom_overdue, "reset to 'like everyone'");

  await p.fill("#g-time", "10:15"); await p.dispatchEvent("#g-time", "change"); await p.click('#g-wd .tgc[data-v="6"]'); await p.click("#g-url-fill"); await p.waitForTimeout(1200);
  const g = await (await p.request.get(BASE + "/api/reminders/settings")).json();
  ok(g.time === "10:15" && g.weekdays.includes(6) && g.public_url === BASE, "global settings saved: " + JSON.stringify([g.time, g.weekdays, g.public_url]));
  await p.click("#pv-go"); await p.waitForSelector("#pv-body table"); await p.waitForTimeout(500);
  await p.screenshot({ path: OUT + "/42-rem-admin.png", fullPage: true });
  const rowsTxt = await p.textContent("#pv-body"); ok(/уйдёт/.test(rowsTxt), "preview lists who would get a message");
  await p.click("#pv-body [data-i]"); await p.waitForSelector(".tgmsg"); await p.waitForTimeout(500);
  await p.screenshot({ path: OUT + "/43-rem-message.png" }); ok(/Задачи на контроле|Сводка по задачам/.test(await p.textContent(".tgmsg")), "message preview opens");
  await p.keyboard.press("Escape"); await p.waitForTimeout(500);
  const n0 = (await sent()).length;
  await p.click("#pv-run"); await p.waitForSelector(".modal button.pri"); await p.click(".modal button.pri"); await p.waitForTimeout(1500);
  ok((await sent()).length > n0, "manual run sends a digest"); ok(/вручную|отправлено/.test(await p.textContent("#c-log")), "log shows the send");
  await p.click(".tgc.on[data-v='14']").catch(() => {});
  // phone
  const m = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }); const mp = await m.newPage();
  await mp.goto(BASE + "/login"); await mp.fill("#login", "admin"); await mp.fill("#password", "secret123"); await mp.click("button.btn.pri"); await mp.waitForSelector(".kpi");
  await mp.goto(BASE + "/#/reminders"); await mp.waitForSelector("#c-me"); await mp.waitForTimeout(900);
  ok(!(await mp.evaluate(() => document.documentElement.scrollWidth > 392 || innerWidth > 392)), "no horizontal scroll on the phone");
  await mp.screenshot({ path: OUT + "/44-rem-phone.png" });
  await b.close(); console.log(errs.length ? "JS ERRORS:\n" + errs.join("\n") : "no JS errors"); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
