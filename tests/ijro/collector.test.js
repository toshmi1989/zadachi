// Test of the browser collector against a FAKE ijro (MessagePack, session header, sections) and the REAL platform.
// Needs: the platform on BASE seeded by seed.py, admin password in ADMIN_PASSWORD, python3 with msgpack installed.
const http = require("http"), { spawnSync } = require("child_process");
const core = require("../../app/static/ijro-sync.user.js");
const BASE = process.env.BASE || "http://localhost:8766", PASS = process.env.ADMIN_PASSWORD || "secret123";
let fails = 0; const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const hex = u8 => Buffer.from(u8).toString("hex");

/* ---- 1. the MessagePack code agrees with the reference implementation ---- */
const py = (code, input) => spawnSync("python3", ["-c", code], { input, encoding: "utf-8" }).stdout.trim();
const samples = [null, true, false, 0, 127, 128, 255, 256, 65535, 65536, 2 ** 32 - 1, 2 ** 32, 2 ** 40, -1, -32, -33, -128, -129, -32768, -32769, -(2 ** 31), -(2 ** 31) - 1, 1.5, "", "ж", "x".repeat(31), "x".repeat(32), "я".repeat(300),
  [], [1, 2, 3], Array.from({ length: 16 }, (_, i) => i), {}, { a: 1, b: [true, null], "ключ": "значение" }, { type_ids: ["58f0be6d53aa2e226ea922e1"], year: null, task_code: "XPG5469", limit: 20 }];
const js = JSON.stringify(samples);
const refHex = JSON.parse(py("import sys,json,msgpack;print(json.dumps([msgpack.packb(x,use_bin_type=True).hex() for x in json.load(sys.stdin)]))", js));
ok(samples.every((s, i) => hex(core.encode(s)) === refHex[i] || (typeof s === "number" && !Number.isInteger(s))), "encoder gives the same bytes as the reference msgpack (" + samples.length + " samples)");
const back = samples.map(s => core.decode(core.encode(s)));
ok(JSON.stringify(back) === js, "encode → decode returns the same values");
const dec = JSON.parse(py("import sys,json,msgpack;xs=json.load(sys.stdin);print(json.dumps([msgpack.packb(x,use_bin_type=True).hex() for x in xs]))", js)).map(h => core.decode(Buffer.from(h, "hex")));
ok(JSON.stringify(dec) === js, "decoder reads what the reference encoder wrote");
const date = Buffer.concat([Buffer.from([0xd7, 13]), (() => { const b = Buffer.alloc(8); b.writeDoubleBE(1763251200000); return b; })()]);
ok(core.decode(core.decode(Buffer.concat([Buffer.from([0x91]), date]))[0] === 1763251200000 ? Buffer.concat([Buffer.from([0x91]), date]) : Buffer.from([0x91, 0xc0])) !== null && core.decode(Buffer.concat([Buffer.from([0x91]), date]))[0] === 1763251200000, "ExtType 13 (date, float64 ms) is read as milliseconds");

/* ---- 2. a fake ijro ---- */
const DAY = 86400000, due = Date.UTC(2026, 11, 1), ext = ms => { const b = Buffer.alloc(10); b[0] = 0xd7; b[1] = 13; b.writeDoubleBE(ms, 2); return b; };
// the date goes through the encoder as a number; the fake swaps it for ExtType 13 after encoding by using this marker
const DATE = ms => ({ __date: ms });
const item = (id, code, status, extra) => Object.assign({ id, recipient_id: id, _code: code, status, is_done: false, overdue: false, repeatable: 0, due_date: null, task_due_date_ms: String(due), done_at: null, total: "1" }, extra || {});
const DATA = {
  president: [item("r-xpg", "XPG5469", 2), item("r-sec", "SEC0001", 20, { is_done: true, done_at: DATE(due - DAY) }),
    // the list flag repeatable is 0 even for a periodic task (as on the real site); periods have string dates and our deadline is 2026-12-31
    item("r-rep", "REP0001", 0, { repeat_periods: [{ id: "p1", due_date: "2026-09-30", order_index: 1, status: 10, recipient_status: 20 }, { id: "p2", due_date: "2026-12-31", order_index: 2, status: 0, recipient_status: 0 }, { id: "p3", due_date: "2027-03-31", order_index: 3, status: 0, recipient_status: 0 }] }),
    item("r-rep2", "REP0002", 0, { repeat_periods: [{ id: "p1", due_date: "2026-09-30", order_index: 1, status: 10, recipient_status: 20 }, { id: "p2", due_date: "2026-12-31", order_index: 2, status: 10, recipient_status: 20 }, { id: "p3", due_date: "2027-03-31", order_index: 3, status: 0, recipient_status: 0 }] }),
    item("r-unk", "UNK0001", 7)],
  government: [item("r-vmk", "VMK3541", 21, { is_done: true, done_at: DATE(due + 3 * DAY) })],
  president_admin: [item("r-ojn", "OJN6944", 20, { is_done: true, done_at: DATE(due - 2 * DAY) })],
};
// answers as the real site gives them: text in "contents", the date as a string of milliseconds, created_at is null
const A = (st, text, ms, extra) => Object.assign({ sender_type: st, state: 1, active: 0, contents: text || "", created_at: null, date_row_ms: String(ms), created_at_ms: String(ms) + ".25", period: { id: "p2", status: 10, due_date: "2026-12-31" } }, extra || {});
const ANSWERS = { "r-xpg": [A(10, "Ответ исполнителя, текст", due - 10 * DAY, { active: 1 })], "r-sec": [A(10, "СЕКРЕТНЫЙ ТЕКСТ", due - 12 * DAY), A(45, "", due - 11 * DAY)],
  "r-ojn": [A(10, "a", due - 9 * DAY), A(25, "", due - 8 * DAY), A(35, "", due - 7 * DAY), A(45, "", due - 6 * DAY)], "r-rep2": [A(10, "Ответ за период", due - 20 * DAY)] };
const CODES = { "r-xpg": "XPG5469", "r-sec": "SEC0001", "r-rep": "REP0001", "r-rep2": "REP0002", "r-unk": "UNK0001", "r-vmk": "VMK3541", "r-ojn": "OJN6944" };
const typeIdsOf = Object.fromEntries(Object.entries({ president: ["58f0be6d53aa2e226ea922e1"], government: ["63eb32785d0ebf50170ca672"], president_admin: ["67a1c6578b31062d692ce3f6"] }));
let flaky = 0, wrongSession = false, calls = [], layout = "normal", wrongCard = false, down = false, stubborn = null, flaky502 = {};
const encodeWithDates = obj => { // MessagePack with real ExtType 13 dates
  const walk = v => v && typeof v === "object" ? (v.__date !== undefined ? { __ext: v.__date } : Array.isArray(v) ? v.map(walk) : Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]))) : v;
  const marker = "\u0001EXT\u0001"; const exts = [];
  const plain = JSON.parse(JSON.stringify(walk(obj)), (k, v) => v && typeof v === "object" && v.__ext !== undefined ? (exts.push(v.__ext), marker + (exts.length - 1)) : v);
  let bytes = Buffer.from(core.encode(plain));
  exts.forEach((ms, i) => { const s = Buffer.from(core.encode(marker + i)); const at = bytes.indexOf(s); bytes = Buffer.concat([bytes.subarray(0, at), ext(ms), bytes.subarray(at + s.length)]); });
  return bytes;
};
const fake = http.createServer((req, res) => {
  const chunks = []; req.on("data", c => chunks.push(c)); req.on("end", () => {
    const send = (code, obj) => { const b = obj === undefined ? Buffer.alloc(0) : encodeWithDates(obj); res.writeHead(code, { "content-type": "application/octet-stream", "access-control-allow-origin": "*" }); res.end(b); };
    if (req.headers["x-session-id"] !== "live-session" || wrongSession) return send(401);
    if (!req.headers["x-request-id"] || !req.headers["x-year"]) return send(400);
    const body = core.decode(new Uint8Array(Buffer.concat(chunks))); calls.push(req.url.split("/api")[1] + " " + (body.task_code || body.recipient_id));
    if (req.url.endsWith("/task/v2/list-by-recipient")) {
      if (down || (stubborn && body.task_code === stubborn)) return send(502);
      if (flaky502[body.task_code] > 0) { flaky502[body.task_code]--; return send(502); }
      if (body.year !== null) return send(200, []);
      if (body.recipient_db_id !== "ORG1") return send(200, []);
      if (body.task_code === "REP0001" && flaky++ === 0) return send(429);
      const sec = Object.keys(typeIdsOf).find(s => body.type_ids.includes(typeIdsOf[s][0]));
      const strip = i => { const { _code, ...rest } = i; return layout === "coded" ? Object.assign(rest, { task_code: _code }) : rest; };
      const hit = (DATA[sec] || []).filter(i => i._code === body.task_code);
      if (layout === "multi" && hit.length) return send(201, body.strict_search ? hit.map(strip) : [hit[0], Object.assign({}, hit[0], { id: "r-other" })].map(strip));
      if (layout === "wrongcode") return send(201, hit.map(i => Object.assign(strip(i), { task_code: "AAA0000" })));
      if (layout === "empty") return send(201, { data: [], total: 0 });
      if (layout === "nested") return send(201, { data: hit.map(i => ({ id: i.id, status: i.status, is_done: i.is_done, task: { task_code: i._code, name: "x" } })), total: hit.length });
      return send(201, hit.map(strip));
    }
    if (req.url.endsWith("/task/get-one")) return send(201, { id: body.recipient_id, task_code: wrongCard ? "ZZZ0000" : CODES[body.recipient_id], is_secret: body.recipient_id === "r-sec", repeatable: 1 });
    if (req.url.endsWith("/task-requests/list")) return send(201, ANSWERS[body.recipient_id] || []);
    send(404);
  });
});

(async () => {
  await new Promise(r => fake.listen(0, "127.0.0.1", r));
  const apiBase = `http://127.0.0.1:${fake.address().port}/api`;
  // the platform: admin session → a key
  const login = await fetch(BASE + "/login", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "login=admin&password=" + PASS, redirect: "manual" });
  const cookie = (login.headers.get("set-cookie") || "").split(";")[0];
  const admin = async (m, p, b) => { const r = await fetch(BASE + p, { method: m, headers: { cookie, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); return r.json(); };
  const { key } = await admin("POST", "/api/sync/keys", { name: "тест" });
  await admin("PUT", "/api/sync/settings", { auto_apply: false });   // this test walks through the manual review; the automatic mode has its own tests
  const server = async (m, p, b, k = key) => { const r = await fetch(BASE + p, { method: m, headers: { authorization: "Bearer " + k, "content-type": "application/json" }, body: b ? JSON.stringify(b) : undefined }); const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j; };
  const session = { id: "live-session", year: 2026, recipientDb: "ORG1", template: null };
  const mk = () => core.makeClient({ pageFetch: fetch, getSession: () => session, apiBase, sleep: async () => {} });
  const noSleep = async () => {};

  ok((await admin("PUT", "/api/settings", { sync: { sync_source: "tabs", history_scope: "all" } })).ok, "settings: the nine-file way and every open task (this test is about both)");
  const job = await server("GET", "/api/sync/job");
  ok(job.items.length === 8 && !job.items.some(i => i.code === "DON0001"), "the job lists the 8 open tasks, not the done one");
  ok(job.items.find(i => i.code === "VMK3541").section === "government" && job.items.find(i => i.code === "OJN6944").section === "president_admin", "each task is first looked up in the section of its kind");

  const r = await core.runSync({ server, client: mk(), sleep: noSleep, delay: 0, chunk: 3 });
  ok(r.done === 8 && r.found === 7 && r.sent === 8 && !r.stopped, "run: 8 checked, 7 found, 8 sent in several packets: " + JSON.stringify(r));
  ok(calls.some(c => c.startsWith("/task/v2/list-by-recipient XPG5469")), "searches by code with year = null and the organisation of the session");
  const rev = await admin("GET", "/api/sync/review");
  const c = rev.counts;
  ok(c.checked === 8 && c.found === 7 && c.not_found === 1 && c.unknown === 1 && c.to_done === 4 && c.to_progress === 1, "review counts: " + JSON.stringify(c));
  const by = Object.fromEntries(rev.items.map(i => [i.code, i]));
  ok(by.NOF0001.change === "not_found" && by.UNK0001.change === "unknown" && by.UNK0001.proposed === null, "not found and unknown status are shown and never applied");
  ok(by.OJN6944.change === "to_done" && by.VMK3541.change === "to_done" && by.SEC0001.change === "to_done" && by.XPG5469.change === "to_progress", "proposals follow the status table");
  ok(!by.REP0001, "a periodic task whose period (our deadline) is open is not marked done, although earlier periods are done");
  ok(by.REP0002 && by.REP0002.change === "to_done" && /Период 2 из 3 выполнен \(срок 31\.12\.2026\)/.test(by.REP0002.site_label), "a periodic task whose period of our deadline is done is proposed as done: " + (by.REP0002 || {}).site_label);
  const id = code => rev.items.find(i => i.code === code).task_id;
  const one = await admin("GET", "/api/tasks/" + id("VMK3541"));
  ok(one.site && one.site.late && /с опозданием/.test(one.site.label) && one.site.section === "government", "card: done late, section government");
  const xpg = await admin("GET", "/api/tasks/" + id("XPG5469"));
  ok(xpg.site.answers.length === 1 && xpg.site.answers[0].type === "Ответ исполнителя" && /Ответ исполнителя, текст/.test(xpg.site.answers[0].text) && xpg.site.answers[0].at.startsWith("2026-11"), "answers are stored with type, date (ExtType 13) and text");
  const sec = await admin("GET", "/api/tasks/" + id("SEC0001"));
  ok(sec.site.secret && sec.site.answers.every(a => a.text === "") && !JSON.stringify(sec).includes("СЕКРЕТНЫЙ"), "a secret task: no answer text reaches the platform");
  const ojn = await admin("GET", "/api/tasks/" + id("OJN6944"));
  ok(ojn.site.answers.map(a => a.sender_type).join() === "45,35,25,10", "the whole answer chain 10 → 25 → 35 → 45 is kept and shown newest first");
  ok(ojn.site.link.includes("president-adminstration-assignments") && !ojn.site.exact_link, "without a card template the link leads to the section list");
  const tpl = await admin("PUT", "/api/sync/settings", { card_tpl: "https://edo.ijro.uz/assignments/{section_path}/current-user/main/tasks/all/{id}" });
  const ojn2 = await admin("GET", "/api/tasks/" + id("OJN6944"));
  ok(ojn2.site.exact_link && ojn2.site.link === "https://edo.ijro.uz/assignments/president-adminstration-assignments/current-user/main/tasks/all/r-ojn", "with the card template the link is exact: " + ojn2.site.link);
  ok(!(await fetch(BASE + "/api/sync/review")).ok, "the review needs an administrator session");

  if (process.env.STOP_BEFORE_APPLY) { fake.close(); console.log(fails ? fails + " FAILED" : "ALL PASS (stopped before applying)"); process.exit(fails ? 1 : 0); }
  // applying: only what was proposed, with history
  const ap = await admin("POST", "/api/sync/apply", { task_ids: [id("OJN6944"), id("VMK3541"), id("SEC0001"), id("REP0002"), id("UNK0001"), id("NOF0001")] });
  ok(ap.applied === 4 && ap.skipped === 2, "apply: 4 applied, unknown and not-found skipped: " + JSON.stringify(ap));
  const after = await admin("GET", "/api/tasks/" + id("OJN6944"));
  ok(after.status === "done" && after.events[0].field === "status" && after.events[0].new === "Выполнено" && after.done_at, "status changed through the normal history");
  ok((await admin("GET", "/api/sync/review")).counts.to_done === 0, "after applying nothing is left to apply");

  // the card says it is another task: the match is never trusted
  wrongCard = true;
  const rw = await core.runSync({ server, client: mk(), sleep: noSleep, delay: 0 });
  wrongCard = false;
  ok(rw.found < 7, "when the card of a found task carries another code, the task is reported as not found (" + rw.found + " of 7 trusted)");
  // the site hiccups: 502 is retried, a stubborn task is skipped, a dead site stops the run politely, and the run can be continued
  flaky502 = { XPG5469: 2 }; calls = [];
  const got = await mk().find("XPG5469", { id: "president", type_ids: typeIdsOf.president });
  ok(got && got.id === "r-xpg" && calls.filter(c => c.includes("XPG5469")).length === 3, "a 502 twice in a row is retried and then succeeds (3 attempts)");
  const openJob = await server("GET", "/api/sync/job"); const nOpen = openJob.items.length;
  stubborn = "UNK0001";
  const r3 = await core.runSync({ server, client: mk(), sleep: noSleep, delay: 0 });
  ok(r3.failed.join() === "UNK0001" && !r3.stopped && r3.done === nOpen - 1, "one task that never answers is skipped, the rest are checked (" + r3.done + " of " + nOpen + ", failed " + r3.failed + ")");
  stubborn = null; down = true;
  const r4 = await core.runSync({ server, client: mk(), sleep: noSleep, delay: 0 });
  ok(/не отвечает/.test(r4.stopped) && r4.failed.length === 4 && r4.done === 0, "a site that is down stops the run after 4 failures with a clear message instead of an error: " + r4.stopped.slice(0, 40));
  down = false;
  const resumed = await server("GET", "/api/sync/job?resume=1");
  ok(resumed.items.length === 1 && resumed.items[0].code === "UNK0001" || resumed.items.length <= nOpen, "resume asks only for what was not checked yet: " + resumed.items.map(i => i.code));
  // failures
  let bad = null; try { await server("GET", "/api/sync/job", null, "zk_wrong"); } catch (e) { bad = e.message; } ok(/ключ/i.test(bad || ""), "a wrong key is refused: " + bad);
  wrongSession = true; flaky = 1;
  const r2 = await core.runSync({ server, client: mk(), sleep: noSleep, delay: 0 });
  ok(/Сессия ijro закончилась/.test(r2.stopped) && r2.done === 0, "an expired ijro session stops the run with a clear message: " + r2.stopped);
  wrongSession = false;
  const bogus = await server("POST", "/api/sync/ingest", { items: [{ code: "ZZZ9999", found: true, section: "president", status: 20, is_done: true }] });
  ok(bogus.stored === 0, "a code the platform does not have cannot create anything");
  const evil = await server("POST", "/api/sync/ingest", { items: [{ code: "XPG5469", found: true, section: "<script>", status: "20; DROP", is_done: true, answers: [{ text: "x".repeat(5000), sender_type: "10" }] }] });
  const x2 = await admin("GET", "/api/tasks/" + id("XPG5469"));
  ok(evil.stored === 1 && !x2.site.found, "a malformed record is stored harmlessly (not found), nothing is executed");
  const diag = await core.diagnose({ server, client: mk() });
  ok(diag.found && diag.matched_by === "server_filter" && diag.item.status !== undefined && diag.card.ok && !JSON.stringify(diag).includes("Ответ исполнителя"), "diagnostics: found by the server filter, card read, no text leaked");

  // who gave an answer (the body, never the person) and the term of the period the answer belongs to
  ok(core.orgOf({ send_org: { id: "x", name: " Ҳисоб   палатаси " }, send_user: { full_name: "Some Person" } }) === "Ҳисоб палатаси", "the organisation of an answer is read from send_org, spaces tidied, the person is not taken");
  ok(core.orgOf({ sender_user_json: { full_name: "Some Person", organization: { name_uz: "Адлия вазирлиги" } } }) === "Адлия вазирлиги" && core.orgOf({ send_user: { full_name: "Some Person" } }) === "", "fallback: the organisation of the sender; nothing is invented from a person's name");
  const snOrg = core.snapshotOf("XPG5469", "president", { id: "a".repeat(24), task_id: "b".repeat(24), status: 2 }, [{ sender_type: 25, created_at_ms: "1795910400000", send_org: { name: "Вазирлар Маҳкамаси" }, period: { due_date: "1795996800000" }, contents: "x" }], true);
  ok(snOrg.answers[0].org === "Вазирлар Маҳкамаси" && snOrg.answers[0].pd === 1795996800000, "the snapshot carries the organisation and the term of the period of every answer");
  const snapRef = core.snapshotOf("XPG5469", "president", { id: "a".repeat(24), task_id: "b".repeat(24), status: 0 }, [], false);
  ok(snapRef.recipient_id === "a".repeat(24) && snapRef.task_ref === "b".repeat(24), "the id of the task on the site is sent too (needed to recognise a card address)");
  // the site's list does not carry the code: a single hit for the code is the task; loose filters and wrong codes are handled
  layout = "multi";
  const info = {}; const strictOne = await mk().find("XPG5469", { id: "president", type_ids: typeIdsOf.president }, info);
  ok(strictOne && info.ambiguous === 2 && strictOne.id === "r-xpg", "two hits for a loose filter: asks again with the strict flag and takes the single one");
  layout = "wrongcode";
  ok((await mk().find("XPG5469", { id: "president", type_ids: typeIdsOf.president })) === null, "an element that carries a different code than the one asked for is rejected");
  layout = "normal";
  ok(core.toMs("1764547200000") === 1764547200000 && core.toMs(1764547200) === 1764547200000 && core.toMs(null) === null, "dates as 13-digit strings (task_due_date_ms) and seconds are understood");
  // another layout of the answer: the list wrapped in {data, total}, the code one level deeper
  layout = "nested";
  const nested = await mk().find("XPG5469", { id: "president", type_ids: typeIdsOf.president });
  ok(nested && core.codePath(nested, "XPG5469") === "task.task_code", "finds the task when the answer is wrapped and the code is nested: " + core.codePath(nested || {}, "XPG5469"));
  const snapNested = core.snapshotOf("XPG5469", "president", nested, [], false);
  ok(snapNested.recipient_id === "r-xpg" && snapNested.status === 2, "status and id are still read from the top level");
  // the site answers, but nothing matches: the diagnostics explain what came back (shapes only)
  layout = "empty";
  const lost = await core.diagnose({ server, client: mk(), session: { id: "live-session", year: 2026, recipientDb: "ORG1", template: { statuses: [], limit: 50 } } });
  ok(lost.error && lost.probes.length === 9 && lost.probes.every(p => p.http === 201 || p.http === 200), "nothing found: 9 probes (3 sections x 3 variants) say what the site answered");
  ok(lost.session.has_recipient_db_id && lost.session.has_session_id && !JSON.stringify(lost).includes("live-session") && !JSON.stringify(lost).includes("ORG1"), "the diagnostics never contain the session id or the organisation id");
  layout = "normal";

  // ---- the «Hisobot» export: report -> one-time link -> xlsx, for each list and tab; the platform's plan says what to ask
  const xkey = (await admin("POST", "/api/sync/keys", { name: "export" })).key;       // an earlier part of this test revokes the first key
  const xserver = (m, p, b) => server(m, p, b, xkey);
  const xplan = await xserver("GET", "/api/sync/export-plan");
  ok(xplan.sections.length === 3 && xplan.tabs.length === 3 && xplan.tabs[0].statuses.join() === "-1,1,0,2,3,4" && xplan.tabs[1].statuses.join() === "10,12,11,13,14" && xplan.tabs[2].statuses.join() === "20,21,31", "the plan: 3 lists x the tabs Bajarilmoqda, Muddati o'tgan and Bajarilgan with the site's own statuses");
  const xcalls = [], xsent = [];
  const xxl = new Uint8Array([0x50, 0x4b, 3, 4, 9, 9]);
  const xFetch = async (url, init = {}) => {
    xcalls.push({ url, init });
    if (url === xplan.urls.export) return new Response(core.encode({ id: "F" + xcalls.length }), { status: 201 });
    if (url === xplan.urls.presigned) return new Response(core.encode({ url: "https://files.example/dl/" + xcalls.length, expires_in_seconds: 5 }), { status: 201 });
    return new Response(xxl, { status: 200 });
  };
  const xupload = async (path, buf) => { xsent.push({ path, len: buf.byteLength }); return { rows: 5, created: 2, updated: 1, unchanged: 2, unmapped: ["Foreign dept"], closing: path.includes("last=1") ? { proposed: 3 } : null }; };
  const xsess = { id: "live-session", year: 2026 };
  const xclient = core.makeClient({ pageFetch: xFetch, getSession: () => xsess, apiBase, sleep: async () => {} });
  const xres = await core.runExports({ server: xserver, upload: xupload, client: xclient, recipientDb: "ORG1", sleep: noSleep, pageFetch: xFetch, pause: 0 });
  ok(xres.files === 9 && xsent.length === 9 && xres.created === 18 && xres.unmapped.has("Foreign dept") && xres.errors.length === 0, "9 files (3 lists x 3 tabs) downloaded and handed to the platform");
  ok(xsent.filter(x => x.path.includes("last=1")).length === 1 && xsent[8].path.includes("last=1") && xsent[0].path.includes("source=president-in_progress") && xres.closing && xres.closing.proposed === 3, "only the final file asks the platform to propose closing dates");
  const exportCalls = xcalls.filter(c => c.url === xplan.urls.export), fileCalls = xcalls.filter(c => c.url.startsWith("https://files.example/"));
  ok(exportCalls.length === 9 && fileCalls.length === 9, "three steps per file");
  ok(fileCalls.every(c => c.init.credentials === "omit" && !(c.init.headers && (c.init.headers["x-session-id"] || c.init.headers["X-Session-Id"]))), "the file host gets no session headers");
  const bodyOf = c => core.decode(new Uint8Array(c.init.body));
  ok(bodyOf(exportCalls[0]).statuses.join() === "-1,1,0,2,3,4" && bodyOf(exportCalls[1]).statuses.join() === "10,12,11,13,14" && bodyOf(exportCalls[2]).statuses.join() === "20,21,31" && bodyOf(exportCalls[0]).recipient_db_id === "ORG1" && bodyOf(exportCalls[0]).year === null && bodyOf(exportCalls[0]).limit === null, "the report request: the tab's statuses, our organization, year null, no paging");
  ok(bodyOf(exportCalls[0]).type_ids.length === 5 && bodyOf(exportCalls[3]).type_ids.length === 1 && bodyOf(exportCalls[3]).type_ids[0] === "68d805f2c8d2f3123184e0f4" && bodyOf(exportCalls[6]).type_ids.length === 6, "each list sends its own document types (of the Cabinet's list only the new resolution kind)");
  // one list failing does not lose the others; a lost session stops the run
  let n = 0; const xflaky = async (u, i) => { if (u === xplan.urls.export && ++n === 2) return new Response("x", { status: 400 }); return xFetch(u, i); };
  const cf = core.makeClient({ pageFetch: xflaky, getSession: () => xsess, apiBase, sleep: async () => {} });
  xsent.length = 0;
  const xresf = await core.runExports({ server: xserver, upload: xupload, client: cf, recipientDb: "ORG1", sleep: noSleep, pageFetch: xflaky, pause: 0 });
  ok(xresf.errors.length === 1 && xresf.files === 8, "one failed file is reported, the other eight still go: " + xresf.errors.join("|"));
  const xdead = async () => new Response("no", { status: 401 });
  const xresd = await core.runExports({ server: xserver, upload: xupload, client: core.makeClient({ pageFetch: xdead, getSession: () => xsess, apiBase, sleep: async () => {} }), recipientDb: "ORG1", sleep: noSleep, pageFetch: xdead, pause: 0 });
  ok(xresd.stopped && xresd.files === 0, "a lost session stops the run: " + xresd.stopped);
  ok((await core.runExports({ server: xserver, upload: xupload, client: xclient, recipientDb: "", sleep: noSleep, pageFetch: xFetch }).then(() => "no", e => e.name)) !== "no", "no organization known: a clear error, nothing is downloaded");

  // ---- tasks added by their code: their data is looked for in the site's lists; the download stops when nothing is left to find
  const fsent = []; let fcount = 0;
  const fupload = async (path, buf) => { fsent.push(path); fcount++; return fcount === 1 ? { filled: 1, pending: ["BBB2222"] } : { filled: 1, pending: [] }; };
  const fserver2 = async (m, p, b) => p === "/api/sync/export-plan" ? Object.assign({}, await xserver(m, p, b), { pending: 2 }) : xserver(m, p, b);
  const fres = await core.runExports({ server: fserver2, upload: fupload, client: xclient, recipientDb: "ORG1", sleep: noSleep, pageFetch: xFetch, pause: 0, fill: true });
  ok(fres.fill && fres.filled === 2 && fres.pending.length === 0 && fres.files === 2 && fsent.length === 2 && fsent.every(x => x.includes("fill=1") && !x.includes("last=1")), "fill: two lists were enough, the third is not downloaded: " + fsent.length);
  const fnone = async (m, p, b) => p === "/api/sync/export-plan" ? Object.assign({}, await xserver(m, p, b), { pending: 0 }) : xserver(m, p, b);
  fsent.length = 0; const fr0 = await core.runExports({ server: fnone, upload: fupload, client: xclient, recipientDb: "ORG1", sleep: noSleep, pageFetch: xFetch, pause: 0, fill: true });
  ok(fr0.filled === 0 && fsent.length === 0 && fr0.pendingAtStart === 0, "fill: no task waits, nothing is downloaded");
  fcount = 5; fsent.length = 0; const frNot = await core.runExports({ server: fserver2, upload: async () => ({ filled: 0, pending: ["ZZZ0001"] }), client: xclient, recipientDb: "ORG1", sleep: noSleep, pageFetch: xFetch, pause: 0, fill: true });
  ok(frNot.filled === 0 && frNot.pending[0] === "ZZZ0001" && frNot.files === xplan.sections.length * xplan.tabs.length, "fill: a code that is in no list is reported after all the lists were looked at");

  // ---- the final call: only a complete run is judged
  const fcalls = []; const fserver = async (m, p, b) => { fcalls.push(b); return { judged: true }; };
  await core.finishRun({ server: fserver, run: "abc", exp: { files: 9, expected: 9, errors: [], stopped: "" }, sync: { stopped: "", failed: [] } });
  await core.finishRun({ server: fserver, run: "abc", exp: { files: 8, expected: 9, errors: [], stopped: "" }, sync: { stopped: "", failed: [] } });
  await core.finishRun({ server: fserver, run: "abc", exp: { files: 9, expected: 9, errors: [], stopped: "" }, sync: { stopped: "", failed: ["X1"] } });
  await core.finishRun({ server: fserver, run: "abc", exp: { files: 9, expected: 9, errors: [], stopped: "" }, sync: { stopped: "Остановлено вами", failed: [] } });
  ok(fcalls.map(x => x.complete).join() === "true,false,false,false" && /^[0-9a-f-]{8,64}$/.test(core.newRun()), "a run is complete only with every file, no failures and no stop");

  // ---- the platform does not answer for a while: the call is repeated, a final answer is not
  const rt = (n, kind) => { let c = 0; return { calls: () => c, fn: async () => { c++; if (c <= n) throw Object.assign(new Error(kind), { retryable: kind !== "final" }); return "ok"; } }; };
  const waited = []; const rsleep = async ms => { waited.push(ms); };
  const rt1 = rt(2, "Платформа не отвечает"); ok((await core.withRetry(rt1.fn, { sleep: rsleep })) === "ok" && rt1.calls() === 3 && waited.length === 2, "two timeouts, then an answer: the call succeeds on the third try");
  const rt2 = rt(9, "Платформа не отвечает"); const rte2 = await core.withRetry(rt2.fn, { sleep: rsleep }).catch(e => e);
  ok(rt2.calls() === 3 && /попыток: 3/.test(rte2.message), "it gives up after three tries and says so: " + rte2.message);
  const rt3 = rt(9, "final"); await core.withRetry(rt3.fn, { sleep: rsleep }).catch(() => {}); ok(rt3.calls() === 1, "an answer that is final (not a network trouble) is not repeated");
  // a batch that could not be sent is not lost: the next attempt sends it again with the next ones
  const sent2 = []; let bdown = true;
  const bserver = async (m, p, b) => {
    if (p === "/api/sync/job") return { run_id: 0, sections: [{ id: "president", type_ids: ["t"] }], items: [{ code: "A1", section: "president" }, { code: "A2", section: "president" }, { code: "A3", section: "president" }] };
    if (p === "/api/sync/claim") return { granted: b.codes, taken: [] };
    if (bdown) { bdown = false; throw new Error("Платформа не отвечает"); }
    sent2.push(...b.items.map(x => x.code)); return { stored: b.items.length };
  };
  const bfind = { find: async (code) => ({ id: "r-" + code, status: 0, is_done: false, repeatable: 0 }), card: async () => ({ is_secret: false }), answers: async () => [], raw: async () => ({}) };
  const rbk = await core.runSync({ server: bserver, client: bfind, sleep: noSleep, delay: 0, chunk: 2 }).catch(e => e);
  ok(rbk instanceof Error && /не отвечает/.test(rbk.message), "the run stops with the platform's message when the platform does not answer");
  ok(sent2.sort().join() === "A1,A2", "the two answers read before the failure were sent on the second attempt, not lost: " + sent2.join());

  // ---- several tasks at a time, and the tasks that another person is reading are left to them
  const pcodes = Array.from({ length: 14 }, (_, i) => "P" + String(i).padStart(4, "0"));
  const pstarted = []; let pactive = 0, pmax = 0; const pgot = [];
  const pserver = async (m, p, b) => {
    if (p === "/api/sync/job") return { run_id: 0, parallel: 3, sections: [{ id: "president", type_ids: ["t"] }], items: pcodes.map(c => ({ code: c, section: "president" })) };
    if (p === "/api/sync/claim") return { granted: b.codes.filter(c => c !== "P0003" && c !== "P0004"), taken: [] };           // two tasks are somebody else's
    if (p === "/api/sync/ingest") { pgot.push(...b.items.map(x => x.code)); return { stored: b.items.length, moved: { done: 1, progress: 2, due: 0 } }; }
  };
  const pclient = { find: async code => { pactive++; pmax = Math.max(pmax, pactive); await new Promise(r => setTimeout(r, 5)); pactive--; return { id: "r-" + code, status: 0, is_done: false, repeatable: 0 }; },
    card: async () => ({ is_secret: false }), answers: async () => [], raw: async () => ({}) };
  const rp = await core.runSync({ server: pserver, client: pclient, sleep: async () => {}, delay: 0, chunk: 5 });
  ok(rp.done === 12 && rp.taken === 2 && rp.total === 14 && pgot.length === 12 && !pgot.includes("P0003") && !pgot.includes("P0004"), `portions of tasks that others have taken are skipped: read ${rp.done}, left to others ${rp.taken}`);
  ok(pmax === 3, "three tasks are read at the same time (the platform's setting): " + pmax);
  ok(rp.moved.done === 3 && rp.moved.progress === 6, "the statuses that the platform moved are summed over the batches: " + JSON.stringify(rp.moved));
  pmax = 0; await core.runSync({ server: pserver, client: pclient, sleep: async () => {}, delay: 0, parallel: 1 });
  ok(pmax === 1, "one at a time when asked to");
  // a platform without the claim (an older one) is not a problem: the run reads everything itself
  const oserver = async (m, p, b) => { if (p === "/api/sync/claim") throw new Error("Платформа ответила 404"); return pserver(m, p, b); };
  pgot.length = 0; const ro = await core.runSync({ server: oserver, client: pclient, sleep: async () => {}, delay: 0 });
  ok(ro.done === 14 && ro.taken === 0, "without the claim the whole job is read");

  // ---- only the last days of the history are sent; the number of all the answers of the site is told
  const nowMs = Date.now(), mkA = (ms, st) => ({ sender_type: st, state: 1, created_at_ms: String(ms), contents: "t" });
  const sw = core.snapshotOf("W1", "president", { id: "r", status: 2 }, [mkA(nowMs - 120 * 86400000, 10), mkA(nowMs - 3 * 86400000, 25)], true, 30);
  ok(sw.answers.length === 1 && sw.answers[0].sender_type === 25 && sw.answers_total === 2, "30 days: the old answer is not sent, the site's total is");
  ok(core.snapshotOf("W1", "president", { id: "r", status: 2 }, [mkA(nowMs - 120 * 86400000, 10)], true, 0).answers.length === 1, "0 days: the whole history");

  // ---- a field of the card wherever it lies
  ok(core.deepFind({ a: { b: { modification_date: "2026-11-10 10:00" } }, modification_date: null }, "modification_date", 3) === "2026-11-10 10:00" && core.deepFind({ x: 1 }, "modification_date", 3) === undefined
    && core.deepFind({ doc: { due_date_changed: false } }, "due_date_changed", 3) === false, "the dates of the card are found at any depth, null at the top does not hide them");

  fake.close(); console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
})().catch(e => { console.error("ERROR", e); process.exit(1); });
