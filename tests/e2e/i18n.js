// The Uzbek interface: walks the pages and lists the texts that stayed Russian (data - names, task texts - is Uzbek or proper names and is not listed).
// Run: BASE=http://localhost:8766 node tests/e2e/i18n.js   (needs the app with some tasks)
const { chromium } = require("playwright");
const BASE = process.env.BASE || "http://localhost:8766";
const RU = /[ыщЫЩ]|\p{L}(ть|ться|ый|ой|ая|ое|ых|ие|ние|ого|ому)(?![\p{L}])|(^|[\s(«"])(не|на|в|по|и|для|или|из|за|от|до|что|как|все|нет|есть|при|без|это|ещё|уже|только|будет|были|был|так)([\s.,:;)»"]|$)/iu;
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const p = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  p.on("pageerror", e => errs.push(e.message)); p.on("console", m => { if (m.type() === "error" && !/401|403/.test(m.text())) errs.push(m.text()); });
  p.setDefaultTimeout(6000); p.on("dialog", d => d.dismiss().catch(() => {}));
  const seen = new Map();
  const scan = async where => {
    const list = await p.evaluate(() => {
      const out = [], ATTRS = ["placeholder", "title", "data-tip", "aria-label", "alt"];
      const walk = n => {
        if (n.nodeType === 3) { const t = n.nodeValue.trim(); if (t && /[А-Яа-яЁё]/.test(t) && !(n.parentNode.closest && n.parentNode.closest("[data-notr]")) && !/^(SCRIPT|STYLE)$/.test(n.parentNode.nodeName)) out.push(t); }
        else if (n.nodeType === 1) { if (/^(SCRIPT|STYLE)$/.test(n.nodeName)) return; for (const a of ATTRS) { const v = n.getAttribute(a); if (v && /[А-Яа-яЁё]/.test(v)) out.push(v.replace(/<[^>]+>/g, " ").trim()); } if (!/^(TEXTAREA|CODE|PRE)$/.test(n.nodeName)) n.childNodes.forEach(walk); }
      };
      walk(document.documentElement); return out;
    });
    for (const t of list) if (RU.test(t) && !seen.has(t)) seen.set(t, where);
  };
  const go = async (hash, where, wait) => { await p.goto(BASE + "/" + hash); await p.waitForTimeout(wait || 1500); await scan(where || hash); };
  // the sign-in page
  await p.goto(BASE + "/login"); await p.waitForTimeout(800); await scan("login");
  ok(await p.locator("#lang").count() === 1, "the language switch is on the sign-in page");
  if (await p.locator("#to-manual").isVisible()) { await p.click("#to-manual"); await scan("login manual"); }
  await p.fill("#login", "admin"); await p.fill("#pw2", "secret123"); await p.click("#s-manual button.btn"); await p.waitForSelector(".dbt"); await p.waitForTimeout(1500);
  ok(await p.evaluate(() => document.documentElement.lang) === "uz", "Uzbek is the default language");
  await scan("dashboard");
  for (const v of ["stages", "units", "people"]) { await p.click(`.dtab[data-view="${v}"]`).catch(() => {}); await p.waitForTimeout(400); await scan("dashboard " + v); }
  for (const h of ["#/tasks", "#/editor", "#/import", "#/sync", "#/settings", "#/users", "#/reminders"]) await go(h);
  // every harmless button of the pages: the dialogs and messages that appear after a click
  const SAFE = /ижрочи|ВМ топшир|ўчир|тозала|чиқиш|юклаб|Excel|юклаш|синхронизацияни бошла|Ҳамма|тўхтат|алмаштир/i;
  for (const h of ["#/tasks", "#/editor", "#/import", "#/sync", "#/settings", "#/users", "#/reminders"]) {
    console.log("buttons of " + h); await go(h, h + " buttons", 1200);
    const n = await p.locator("main button:visible, main .btn:visible").count();
    for (let i = 0; i < Math.min(n, 25); i++) {
      const el = p.locator("main button:visible, main .btn:visible").nth(i);
      const t = ((await el.textContent().catch(() => "")) || "").trim();
      if (!t || SAFE.test(t) || /^\d+$/.test(t)) continue;
      await el.click({ timeout: 1500 }).catch(() => {}); await p.waitForTimeout(350); await scan(h + " after [" + t.slice(0, 25) + "]");
      await p.keyboard.press("Escape"); await p.waitForTimeout(200);
      if (!p.url().includes(h.slice(1))) await go(h, h, 800);
    }
  }
  // the card of a task, dialogs, the menu
  await p.evaluate(() => { try { Object.keys(localStorage).filter(k => k.startsWith("zf.")).forEach(k => localStorage.removeItem(k)); } catch (e) {} });   // the buttons above may have set a filter
  await go("#/tasks"); await p.waitForSelector("#rows tr[data-id]");
  await p.locator("#rows tr[data-id]").first().click(); await p.waitForSelector(".drawer.on"); await p.waitForTimeout(800); await scan("drawer"); await p.keyboard.press("Escape"); await p.waitForTimeout(500);
  const btn = async (sel, where) => { if (await p.locator(sel).count()) { await p.locator(sel).first().click().catch(() => {}); await p.waitForTimeout(500); await scan(where); await p.keyboard.press("Escape"); await p.waitForTimeout(300); } };
  await btn("#new-task, #add", "task create dialog");
  await go("#/users"); await btn(".btn.pri, #add-user, #new-user", "users dialog");
  // the tooltips of the dashboard
  await go("#/dashboard"); await p.locator(".kpi, .dk").first().hover().catch(() => {}); await p.waitForTimeout(300); await scan("tooltip");
  // the switch to Russian leaves the program as it was
  await p.click("#lang"); await p.waitForTimeout(1500);
  ok(await p.evaluate(() => document.documentElement.lang) === "ru", "the switch gives Russian");
  ok((await p.textContent("body")).includes("Дашборд"), "Russian interface is untouched");
  await p.click("#lang"); await p.waitForTimeout(1500);
  ok(await p.evaluate(() => document.documentElement.lang) === "uz", "and back to Uzbek");
  console.log("\nRussian texts left: " + seen.size);
  for (const [t, w] of seen) console.log(`  [${w}] ${t.slice(0, 160)}`);
  console.log("page errors: " + errs.length); errs.slice(0, 5).forEach(e => console.log("  " + e));
  ok(errs.length === 0, "no errors in the console");
  await b.close();
  console.log(fails ? `\n${fails} FAILED` : "\nall passed"); process.exit(fails ? 1 : 0);
})();
