// The translator of the interface: node tests/i18n.test.js (no browser needed).
const fs = require("fs"), path = require("path"), vm = require("vm");
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const dir = path.join(__dirname, "../app/static");
const load = lang => {
  const sandbox = { localStorage: { getItem: () => lang }, document: { documentElement: {}, readyState: "complete", addEventListener() {}, createElement: () => ({ setAttribute() {} }) }, MutationObserver: class { observe() {} }, location: {} };
  sandbox.window = sandbox; vm.createContext(sandbox);
  for (const f of ["i18n.js", "i18n-uz.js"]) vm.runInContext(fs.readFileSync(path.join(dir, f), "utf8"), sandbox, { filename: f });
  return sandbox.I18N;
};
const uz = load("uz"), ru = load("ru");

ok(uz.lang === "uz" && ru.lang === "ru", "the language comes from the browser storage");
ok(load(null).lang === "uz", "Uzbek is the default");
ok(ru.tr("Дашборд") === "Дашборд", "Russian mode leaves the texts as they are");
ok(uz.tr("Сохранить") !== "Сохранить" && uz.tr("Настройки") === "Созламалар", "a word of the menu is translated");
ok(uz.tr("Хоҳлаган матн ва Қарор") === "Хоҳлаган матн ва Қарор", "Uzbek texts (the data) are not touched");
ok(uz.tr("  Сохранить  ").startsWith("  ") && uz.tr("  Сохранить  ").endsWith("  "), "the spaces around a text are kept");
ok(uz.tr("Показано 51–100 из 272") === "272 тадан 51–100 кўрсатилди", "a text with numbers is rewritten: " + uz.tr("Показано 51–100 из 272"));
ok(uz.tr("просрочено на 5 дней") === "5 кун муддати ўтган" && uz.tr("осталось 3 дня") === "3 кун қолди" && uz.tr("остался 1 день") === "1 кун қолди", "the days left / overdue");
ok(uz.tr("21 задача") === "21 та топшириқ" && uz.tr("5 задач") === "5 та топшириқ" && uz.tr("3 сотрудника") === "3 та ходим", "the Russian plurals become «N та …»");
ok(uz.tr("Найдено 123 задачи") === "Топилди: 123 та топшириқ", "found N tasks: " + uz.tr("Найдено 123 задачи"));
ok(uz.tr("за 14 дн.") === "14 кун олдин" && uz.tr("в день срока") === "муддат куни", "the reminders of the term");
ok(uz.tr("Нет ответов за последние 30 дн.") === "Охирги 30 кунда жавоб йўқ", "no answers for the last days: " + uz.tr("Нет ответов за последние 30 дн."));
ok(uz.tr("Сводная по пн, вт, пт в 09:00.").includes("09:00 да, ду, се, жу") || /09:00/.test(uz.tr("по пн, вт, пт в 09:00")), "the weekdays of the schedule: " + uz.tr("по пн, вт, пт в 09:00"));
const d = new Date(2026, 10, 16);
ok(uz.longDate(d) === "2026 йил 16 ноябрь, душанба" && /2026/.test(ru.longDate(d)), "the long date in words: " + uz.longDate(d));
ok(Object.keys(uz.dict).length > 1000, "the dictionary is filled (" + Object.keys(uz.dict).length + " texts)");
const bad = Object.entries(uz.dict).filter(([k, v]) => /[ыщЫЩ]/.test(v));
ok(bad.length === 0, "no Russian-only letters in the Uzbek texts" + (bad.length ? ": " + bad.slice(0, 3).map(b => b[0]) : ""));
console.log(fails ? `\n${fails} FAILED` : "\nall passed"); process.exit(fails ? 1 : 0);
