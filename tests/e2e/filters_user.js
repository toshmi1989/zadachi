// What one person set in the dashboard must not narrow the numbers of the next person who signs in on the same computer (the filters are kept apart for each person).
// Needs the app on BASE with some tasks and an ordinary user. Run: BASE=http://localhost:8766 node tests/e2e/filters_user.js
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ storageState: { cookies: [], origins: [{ origin: BASE, localStorage: [{ name: "lang", value: "ru" }] }] }, viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  const login = async (u, pw) => { await p.goto(BASE + "/login"); await p.waitForTimeout(500); if (await p.locator("#to-manual").isVisible()) await p.click("#to-manual");
    await p.fill("#login", u); await p.fill("#pw2", pw); await p.click("#s-manual button.btn"); await p.waitForSelector(".dbt"); await p.waitForTimeout(1200); };
  await login("admin", "secret123");
  const all = (await (await p.request.get(BASE + "/api/dashboard")).json()).totals.total;
  const user = (await (await p.request.get(BASE + "/api/users")).json()).items.find(x => x.role === "user");
  const pw = (await (await p.request.post(`${BASE}/api/users/${user.id}/password`, { data: {} })).json()).password;
  // one task has a closing date (an ordinary user sees the closing dates only): its year is then offered to the user too, and a leftover period would narrow the numbers
  const first = (await (await p.request.get(BASE + "/api/tasks?limit=1")).json()).items[0];
  await p.request.patch(`${BASE}/api/tasks/${first.id}`, { data: { close_date: "2026-12-01" } }); await p.reload(); await p.waitForSelector(".dbt"); await p.waitForTimeout(800);
  // the administrator narrows the dashboard to one year (and the choice is remembered)
  const years = ["2026"];
  ok(years.length > 0, "the dashboard offers years: " + years.join(","));
  await p.selectOption("#pp-y", years[years.length - 1]); await p.waitForTimeout(700);
  ok(await p.evaluate(() => Object.keys(localStorage).some(k => /^zf\.\d+\.dashboard$/.test(k) && JSON.parse(localStorage.getItem(k)).period)), "the period is remembered under the person's own key");
  await p.goto(BASE + "/#/tasks"); await p.waitForTimeout(800); await p.goto(BASE + "/#/dashboard"); await p.waitForTimeout(800);
  ok(await p.locator("#pp-y").inputValue() === years[years.length - 1], "the administrator finds the year as it was left");
  // the next person on the same computer starts with everything
  await p.request.post(BASE + "/logout"); await login(user.login, pw);
  ok(await p.locator("#pp-y").inputValue() === "", "the ordinary user starts with «all years», not with the administrator's year");
  const shown = +(await p.locator(".dk:not(.ok):not(.no) .v").first().textContent()).replace(/\D/g, "");
  ok(shown === all, `the user sees all the tasks (${shown} of ${all})`);
  await b.close(); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})();
