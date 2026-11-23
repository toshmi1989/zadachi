// ==UserScript==
// @name         Задачи ⇄ ijro: синхронизация статусов
// @namespace    zadachi
// @version      1.7.1
// @description  Читает статусы и ответы по задачам на edo.ijro.uz из вашей уже открытой сессии и передаёт их в платформу «Задачи». Скачивает выгрузки «Hisobot» (только чтение). Ничего не меняет на ijro.
// @match        https://edo.ijro.uz/*
// @connect      {{HOST}}
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        unsafeWindow
// @run-at       document-start
// @downloadURL  {{ORIGIN}}/ijro-sync.user.js
// @updateURL    {{ORIGIN}}/ijro-sync.user.js
// ==/UserScript==

/* What this script does and does not do.
 *  - It only READS: it asks edo.ijro.uz the same questions the site asks itself (task list by code, answers of a task).
 *    It never presses a button of the site, never sends an answer, never changes a status there.
 *  - Your sign-in stays in your browser. The session id of ijro is used here, in this tab, and is never sent anywhere.
 *  - What it sends to the platform: for each of its open tasks the status, the dates and the answers read from the site.
 *  - It pauses between requests and stops on any sign-in or rate error.
 */
(function (root) {
  "use strict";
  const SERVER = "{{ORIGIN}}";
  const VERSION = "1.7.1";

  /* ───────────── MessagePack (the site speaks it in both directions) ───────────── */
  const te = new TextEncoder(), td = new TextDecoder();
  function encode(value) {
    const out = [];
    const u8 = (...b) => out.push(Uint8Array.from(b));
    const be = (n, bytes) => { const a = new Uint8Array(bytes); for (let i = bytes - 1; i >= 0; i--) { a[i] = n % 256; n = Math.floor(n / 256); } out.push(a); };
    (function put(v) {
      if (v === null || v === undefined) return u8(0xc0);
      if (v === true) return u8(0xc3);
      if (v === false) return u8(0xc2);
      if (typeof v === "number") {
        if (Number.isInteger(v) && Math.abs(v) < 2 ** 53) {
          if (v >= 0) { if (v < 128) return u8(v); if (v < 256) { u8(0xcc, v); return; } if (v < 65536) { u8(0xcd); return be(v, 2); } if (v < 2 ** 32) { u8(0xce); return be(v, 4); } u8(0xcf); return be(v, 8); }
          if (v >= -32) return u8(256 + v);
          if (v >= -128) { u8(0xd0, 256 + v); return; }
          if (v >= -32768) { u8(0xd1); return be(65536 + v, 2); }
          if (v >= -(2 ** 31)) { u8(0xd2); return be(2 ** 32 + v, 4); }
          { u8(0xd3); const hi = Math.floor(v / 2 ** 32), lo = v - hi * 2 ** 32; be((hi + 2 ** 32) % 2 ** 32, 4); return be(lo, 4); }
        }
        const a = new Uint8Array(9); a[0] = 0xcb; new DataView(a.buffer).setFloat64(1, v); out.push(a); return;
      }
      if (typeof v === "string") {
        const b = te.encode(v), n = b.length;
        if (n < 32) u8(0xa0 | n); else if (n < 256) u8(0xd9, n); else if (n < 65536) { u8(0xda); be(n, 2); } else { u8(0xdb); be(n, 4); }
        out.push(b); return;
      }
      if (v instanceof Uint8Array) { const n = v.length; if (n < 256) u8(0xc4, n); else if (n < 65536) { u8(0xc5); be(n, 2); } else { u8(0xc6); be(n, 4); } out.push(v); return; }
      if (Array.isArray(v)) { const n = v.length; if (n < 16) u8(0x90 | n); else if (n < 65536) { u8(0xdc); be(n, 2); } else { u8(0xdd); be(n, 4); } v.forEach(put); return; }
      if (typeof v === "object") {
        const ks = Object.keys(v).filter(k => v[k] !== undefined), n = ks.length;
        if (n < 16) u8(0x80 | n); else if (n < 65536) { u8(0xde); be(n, 2); } else { u8(0xdf); be(n, 4); }
        ks.forEach(k => { put(k); put(v[k]); }); return;
      }
      throw new Error("msgpack: неподдерживаемое значение");
    })(value);
    let len = 0; out.forEach(a => len += a.length);
    const res = new Uint8Array(len); let o = 0; out.forEach(a => { res.set(a, o); o += a.length; });
    return res;
  }
  function decode(buf) {
    const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
    let p = 0;
    const need = n => { if (p + n > buf.length) throw new Error("msgpack: обрыв данных"); };
    const str = n => { need(n); const s = td.decode(buf.subarray(p, p + n)); p += n; return s; };
    const arr = n => { const a = new Array(n); for (let i = 0; i < n; i++) a[i] = read(); return a; };
    const map = n => { const m = {}; for (let i = 0; i < n; i++) { const k = read(); m[String(k)] = read(); } return m; };
    const bin = n => { need(n); const b = buf.slice(p, p + n); p += n; return b; };
    const ext = n => {   // type 13 carries a date: milliseconds as float64. Anything else is skipped.
      need(n + 1); const t = dv.getInt8(p); p += 1; let v = null;
      if (t === 13 && n === 8) v = dv.getFloat64(p); else if (t === 13 && n === 4) v = dv.getUint32(p) * 1000;
      p += n; return v;
    };
    function read() {
      need(1); const b = buf[p++];
      if (b < 0x80) return b; if (b >= 0xe0) return b - 256;
      if (b >= 0xa0 && b < 0xc0) return str(b & 0x1f);
      if (b >= 0x90 && b < 0xa0) return arr(b & 0x0f);
      if (b >= 0x80 && b < 0x90) return map(b & 0x0f);
      switch (b) {
        case 0xc0: return null; case 0xc2: return false; case 0xc3: return true;
        case 0xc4: { need(1); const n = buf[p++]; return bin(n); } case 0xc5: { need(2); const n = dv.getUint16(p); p += 2; return bin(n); } case 0xc6: { need(4); const n = dv.getUint32(p); p += 4; return bin(n); }
        case 0xc7: { need(1); const n = buf[p++]; return ext(n); } case 0xc8: { need(2); const n = dv.getUint16(p); p += 2; return ext(n); } case 0xc9: { need(4); const n = dv.getUint32(p); p += 4; return ext(n); }
        case 0xca: { need(4); const v = dv.getFloat32(p); p += 4; return v; } case 0xcb: { need(8); const v = dv.getFloat64(p); p += 8; return v; }
        case 0xcc: { need(1); return buf[p++]; } case 0xcd: { need(2); const v = dv.getUint16(p); p += 2; return v; } case 0xce: { need(4); const v = dv.getUint32(p); p += 4; return v; }
        case 0xcf: { need(8); const v = dv.getUint32(p) * 2 ** 32 + dv.getUint32(p + 4); p += 8; return v; }
        case 0xd0: { need(1); const v = dv.getInt8(p); p += 1; return v; } case 0xd1: { need(2); const v = dv.getInt16(p); p += 2; return v; } case 0xd2: { need(4); const v = dv.getInt32(p); p += 4; return v; }
        case 0xd3: { need(8); const v = dv.getInt32(p) * 2 ** 32 + dv.getUint32(p + 4); p += 8; return v; }
        case 0xd4: return ext(1); case 0xd5: return ext(2); case 0xd6: return ext(4); case 0xd7: return ext(8); case 0xd8: return ext(16);
        case 0xd9: { need(1); const n = buf[p++]; return str(n); } case 0xda: { need(2); const n = dv.getUint16(p); p += 2; return str(n); } case 0xdb: { need(4); const n = dv.getUint32(p); p += 4; return str(n); }
        case 0xdc: { need(2); const n = dv.getUint16(p); p += 2; return arr(n); } case 0xdd: { need(4); const n = dv.getUint32(p); p += 4; return arr(n); }
        case 0xde: { need(2); const n = dv.getUint16(p); p += 2; return map(n); } case 0xdf: { need(4); const n = dv.getUint32(p); p += 4; return map(n); }
      }
      throw new Error("msgpack: неизвестный тип 0x" + b.toString(16));
    }
    return read();
  }

  /* ───────────── reading the site ───────────── */
  class SessionError extends Error {}
  class RateError extends Error {}
  class TransientError extends Error {}   // the site is overloaded or unreachable right now: worth waiting, not worth giving up
  const DEFAULT_BODY = { limit: 20, offset: 0, statuses: [], type_ids: [], recipient_db_id: null, year: null, task_code: "", strict_search: false, document_number: null,
    document_type_id: null, from_due_date: null, to_due_date: null, document_from_date: null, document_to_date: null, undistributed_tasks: false, seen: null,
    main_recipient: false, is_rayosat: false, not_rayosat: false, tasks: [], due_date_sort: null, active_state_high_org_id: null, repeatable: false, recipient_user_id: null };
  const rid = () => Array.from({ length: 24 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");
  const toMs = v => {
    if (v == null) return null;
    if (typeof v === "string" && /^\d{10,20}(\.\d+)?$/.test(v)) { let n = Number(v); if (n >= 1e17) n /= 1e6; else if (n >= 1e14) n /= 1e3; v = n; }   // ms, seconds, microseconds or nanoseconds
    if (typeof v === "number") return v < 1e11 ? Math.round(v * 1000) : Math.round(v); if (v instanceof Date) return v.getTime(); const t = Date.parse(v); return isNaN(t) ? null : t; };
  /* the body that gave an answer, as the site shows it next to the answer (Ҳисоб палатаси, Вазирлар Маҳкамаси, Адлия вазирлиги ...): the name only, no person */
  const orgOf = a => {
    const so = a && a.send_org && typeof a.send_org === "object" ? a.send_org.name : null;
    const uo = a && a.sender_user_json && a.sender_user_json.organization;
    const v = so || (uo && (uo.name_uz || uo.name_ru || uo.name_uz_lat)) || "";
    return typeof v === "string" ? v.replace(/\s+/g, " ").trim().slice(0, 120) : "";
  };
  const pick = (o, keys) => { for (const k of keys) if (o && o[k] !== undefined && o[k] !== null) return o[k]; return undefined; };
  const listOf = r => {
    if (Array.isArray(r)) return r;
    if (r && typeof r === "object") { for (const k of ["data", "items", "list", "results", "rows", "tasks", "content"]) if (Array.isArray(r[k])) return r[k]; for (const k in r) if (Array.isArray(r[k])) return r[k]; }
    return [];
  };
  /* where the code of the task sits in an element of the answer is looked up, not assumed: the usual field names first,
     then any text value (up to three levels deep) that equals a task code */
  const CODE_RE = /^[A-Z]{3}\d{4}$/i;
  const codePath = (it, want) => {
    for (const k of ["task_code", "code", "taskCode"]) if (typeof it[k] === "string" && (!want || it[k].toUpperCase() === want.toUpperCase())) return k;
    const walk = (o, path, depth) => {
      if (!o || typeof o !== "object" || depth > 3) return null;
      for (const k of Object.keys(o)) {
        const v = o[k];
        if (typeof v === "string" && CODE_RE.test(v) && (!want || v.toUpperCase() === want.toUpperCase())) return path.concat(k).join(".");
        if (v && typeof v === "object" && !(v instanceof Uint8Array)) { const r = walk(v, path.concat(Array.isArray(v) ? k + "[]" : k), depth + 1); if (r) return r; if (Array.isArray(v)) { for (const e of v.slice(0, 3)) { const r2 = walk(e, path.concat(k + "[]"), depth + 1); if (r2) return r2; } } }
      }
      return null;
    };
    return walk(it, [], 0);
  };
  const getPath = (o, path) => path.split(".").reduce((a, k) => a == null ? a : a[k.replace("[]", "")], o);
  const itemCode = it => { const p = codePath(it, null); const v = p ? getPath(it, p) : ""; return typeof v === "string" ? v : ""; };
  const hasCode = (it, code) => { const p = codePath(it, code); return !!p; };

  function makeClient({ pageFetch, getSession, apiBase, sleep }) {
    async function raw(path, body) {   // one request, answer as is (for diagnostics)
      const s = getSession();
      if (!s.id) throw new SessionError("Не удалось получить сессию ijro: откройте любой раздел «Топшириқлар» на сайте и повторите.");
      const res = await pageFetch((/^https?:/.test(path) ? path : apiBase + path), { method: "POST", headers: { "Content-Type": "application/octet-stream", "x-session-id": s.id, "x-year": String(s.year), "x-request-id": rid() }, body: encode(body) });
      let data = null, err = null;
      try { data = decode(new Uint8Array(await res.arrayBuffer())); } catch (e) { err = String(e.message || e); }
      return { status: res.status, data, err };
    }
    const BACKOFF = [2000, 5000, 10000, 20000, 30000];
    const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);
    async function call(path, body, timeoutMs = 40000) {
      for (let attempt = 0; ; attempt++) {
        const s = getSession();
        if (!s.id) throw new SessionError("Не удалось получить сессию ijro: откройте любой раздел «Топшириқлар» на сайте и повторите.");
        let res = null, why = "";
        try {
          res = await withTimeout(pageFetch((/^https?:/.test(path) ? path : apiBase + path), { method: "POST", headers: { "Content-Type": "application/octet-stream", "x-session-id": s.id, "x-year": String(s.year), "x-request-id": rid() }, body: encode(body) }), timeoutMs);
        } catch (e) { why = "нет ответа от ijro"; }
        if (res) {
          if (res.status === 401 || res.status === 403) throw new SessionError("Сессия ijro закончилась или доступ закрыт (" + res.status + "). Войдите заново и повторите.");
          if (res.status === 429 || res.status >= 500) why = "ijro отвечает " + res.status;
          else if (!res.ok) throw new Error("ijro ответил " + res.status);
          else return decode(new Uint8Array(await res.arrayBuffer()));
        }
        if (attempt >= BACKOFF.length) throw new TransientError(why);
        await sleep(BACKOFF[attempt] * (0.8 + Math.random() * 0.4));   // 2, 5, 10, 20, 30 seconds: an overloaded site gets time to recover
      }
    }
    /* The site's list does not repeat the code of the task in its elements, but it filters by it (task_code) on the server. So a
       single hit for a full code IS that task. Several hits mean the filter was loose: ask again with the strict flag. An element
       that does carry a different code than the one asked for is rejected. */
    const ownCode = it => { for (const k of ["task_code", "code", "taskCode"]) if (typeof it[k] === "string") return it[k]; return ""; };
    async function find(code, section, info) {
      const s = getSession();
      const ask = async strict => {
        const body = bodyFor(code, section, { strict_search: strict });
        if (!body.recipient_db_id) throw new SessionError("Не удалось узнать вашу организацию: откройте на сайте раздел «Топшириқлар», дождитесь списка и повторите.");
        return listOf(await call("/task/v2/list-by-recipient", body)).filter(it => !ownCode(it) || ownCode(it).toUpperCase() === code.toUpperCase());
      };
      let items = await ask(false);
      if (items.length > 1) { if (info) info.ambiguous = items.length; items = await ask(true); }
      if (items.length > 1) { const exact = items.filter(it => hasCode(it, code)); items = exact.length === 1 ? exact : []; }
      return items[0] || null;
    }
    async function card(recipientId) {   // the card of a task: whether it is secret (the list does not say)
      const r = await call("/task/get-one", { recipient_id: recipientId });
      const flag = o => { const w = (x, d) => { if (!x || typeof x !== "object" || d > 3) return false; if (x.is_secret === true) return true; return Object.keys(x).some(k => w(x[k], d + 1)); }; return w(o, 0); };
      return { is_secret: flag(r), code: typeof (r && r.task_code) === "string" ? r.task_code : "", raw: r };
    }
    const answers = async recipientId => listOf(await call("/task-requests/list", { recipient_id: recipientId, period_id: null }));
    const bodyFor = (code, section, over) => { const s = getSession(); return Object.assign({}, DEFAULT_BODY, s.template || {}, { limit: 20, offset: 0, statuses: [], type_ids: section.type_ids, task_code: code, year: null, strict_search: false, recipient_db_id: s.recipientDb, document_number: null, document_type_id: null, from_due_date: null, to_due_date: null, document_from_date: null, document_to_date: null, tasks: [] }, over || {}); };
    return { call, raw, find, answers, bodyFor, card };
  }

  function snapshotOf(code, sectionId, it, answerList, loaded, days) {
    const periods = (Array.isArray(it.repeat_periods) ? it.repeat_periods : []).map(p => ({ order: p.order_index, status: p.status, recipient_status: p.recipient_status, due_ms: toMs(p.due_date) }));
    const num = v => typeof v === "number" && Number.isFinite(v) ? Math.trunc(v) : null;
    return {
      code, found: true, section: sectionId, recipient_id: String(pick(it, ["id", "recipient_id"]) ?? ""), task_ref: String(it.task_id ?? ""), status: num(it.status), is_done: !!it.is_done,
      overdue: (() => { const v = pick(it, ["overdue", "is_overdue", "expired"]); return v === undefined ? null : !!v; })(),
      repeatable: !!(it.repeatable) || periods.length > 0, due_ms: toMs(pick(it, ["task_due_date_ms", "due_date"])), done_ms: toMs(it.done_at), periods, is_secret: !!it.is_secret, answers_loaded: !!loaded,
      answers_total: (answerList || []).length,      // how many answers the site has; only the last `days` days are sent
      answers: (answerList || []).map(a => ({ a, t: toMs(pick(a, ["created_at_ms", "created_at", "date_row_ms", "date", "sent_at", "updated_at"])) })).filter(x => !days || !x.t || x.t >= Date.now() - days * 86400000).sort((x, y) => (x.t || 0) - (y.t || 0)).slice(-30).map(({ a, t }) => ({ sender_type: num(a.sender_type), state: num(a.state), active: !!a.active,
        org: orgOf(a), pd: toMs(a.period && a.period.due_date),
        at_ms: t, text: String(pick(a, ["contents", "comment", "text", "description", "content", "message", "note"]) ?? "").slice(0, 600) })),
    };
  }

  /* ───────────── the site's «Hisobot» export: new tasks and their texts, terms, responsible people ─────────────
     The button does three things: asks for a report (the answer carries a file id), asks for a one-time link to it (alive ~5 seconds), downloads the xlsx.
     We repeat exactly that, with the session of this tab, and hand the file to the platform, which imports it the same way as a file picked by hand. */
  const exportBody = (recipientDb, typeIds, statuses) => ({ limit: null, page: null, document_number: null, statuses, from_due_date: null, to_due_date: null, document_type_id: null,
    undistributed_tasks: false, seen: null, main_recipient: false, recipient_db_id: recipientDb, is_rayosat: false, not_rayosat: false, type_ids: typeIds, tasks: [], due_date_sort: null,
    active_state_high_org_id: null, repeatable: false, strict_search: false, year: null, recipient_user_id: null, document_from_date: null, document_to_date: null, offset: null });
  async function fetchExport(client, plan, recipientDb, section, tab, pageFetch) {
    const j1 = await client.call(plan.urls.export, exportBody(recipientDb, section.type_ids, tab.statuses), 180000);   // the site builds a big report for up to a minute
    if (!j1 || !j1.id) throw new Error("выгрузка: сайт не вернул номер файла");
    const j2 = await client.call(plan.urls.presigned, { file_id: j1.id });
    if (!j2 || !j2.url) throw new Error("выгрузка: сайт не дал ссылку на файл");
    const r = await pageFetch(j2.url, { credentials: "omit" });   // at once: the link lives about 5 seconds; no session headers go to the file host
    if (!r.ok) throw new Error("скачивание файла: HTTP " + r.status);
    const buf = await r.arrayBuffer(), head = new Uint8Array(buf.slice(0, 2));
    if (head[0] !== 0x50 || head[1] !== 0x4b) throw new Error("скачанный файл не xlsx");
    return buf;
  }
  async function runExports({ server, upload, client, recipientDb, onProgress, shouldStop, sleep, pageFetch, pause = 1500, run = "" }) {
    const plan = await server("GET", "/api/sync/export-plan");
    if (!recipientDb) throw new SessionError("Не удалось узнать вашу организацию: откройте на сайте раздел «Топшириқлар» и повторите.");
    const jobs = []; plan.sections.forEach(sec => plan.tabs.forEach(tab => jobs.push({ sec, tab })));
    const sum = { expected: jobs.length, files: 0, rows: 0, missing: 0, mode: "", created: 0, updated: 0, unchanged: 0, unmapped: new Set(), closing: null, errors: [], stopped: "" };
    for (let i = 0; i < jobs.length; i++) {
      if (shouldStop && shouldStop()) { sum.stopped = "Остановлено вами"; break; }
      const { sec, tab } = jobs[i];
      if (onProgress) onProgress({ i, n: jobs.length, what: sec.id + " / " + tab.id });
      try {
        const buf = await fetchExport(client, plan, recipientDb, sec, tab, pageFetch);
        const r = await upload("/api/sync/export?source=" + encodeURIComponent(sec.id + "-" + tab.id) + (i === jobs.length - 1 ? "&last=1" : "") + (run ? "&run=" + run : ""), buf);
        sum.files++; sum.rows += r.rows; sum.created += r.created; sum.updated += r.updated; sum.missing += r.missing || 0; sum.mode = r.mode || sum.mode; sum.unchanged += r.unchanged; (r.unmapped || []).forEach(x => sum.unmapped.add(x)); if (r.closing) sum.closing = r.closing;
      } catch (e) {
        if (e instanceof SessionError || e instanceof RateError) { sum.stopped = e.message; break; }
        sum.errors.push(sec.id + "/" + tab.id + ": " + (e.message || e));   // one list failing does not lose the others
      }
      await sleep(pause);
    }
    return sum;
  }

  /* ───────────── one synchronisation run ───────────── */
  async function runSync({ server, client, onProgress, shouldStop, sleep, chunk = 40, delay = 250, resume = false, parallel = 0 }) {
    const job = await server("GET", "/api/sync/job" + (resume ? "?resume=1" : ""));
    const sections = Object.fromEntries(job.sections.map(s => [s.id, s]));
    const order = hint => hint && sections[hint] ? [sections[hint]].concat(job.sections.filter(s => s.id !== hint)) : job.sections;
    const width = Math.max(1, Math.min(5, Math.trunc(parallel || job.parallel || 1)));      // how many tasks are read at the same time (the platform's setting)
    const buffer = [], failed = [], moved = { done: 0, progress: 0, due: 0 }; let done = 0, found = 0, sent = 0, taken = 0, stopped = "", pace = delay, streak = 0, okRun = 0, halt = false, fatal = null;
    const flush = async () => {
      if (!buffer.length) return; const items = buffer.splice(0, buffer.length);
      let r;
      try { r = await server("POST", "/api/sync/ingest", { run_id: job.run_id, items }); } catch (e) { buffer.unshift(...items); throw e; }   // what was read is not lost: the next attempt sends it again
      sent += items.length;
      if (r && r.moved) for (const k of Object.keys(moved)) moved[k] += r.moved[k] || 0;
    };
    const total = job.items.length;
    const progress = () => { if (onProgress) onProgress({ done: done + failed.length + taken, total, found, failed: failed.length, taken, moved }); };
    // one task: the snapshot to send (found or not), or a TransientError when the site could not answer after all retries
    async function checkOne(t) {
      let it = null, sec = null;
      for (const s of order(t.section)) { it = await client.find(t.code, s); await sleep(pace); if (it) { sec = s; break; } }
      if (!it) return { code: t.code, found: false };
      let ans = [], loaded = false, secret = !!it.is_secret;
      if (it.status !== 0 || it.is_done || it.repeatable) {
        const id = it.id ?? it.recipient_id;
        try {
          const cd = await client.card(id); secret = secret || cd.is_secret;
          if (cd.code && cd.code.toUpperCase() !== t.code.toUpperCase()) return { code: t.code, found: false };   // the card says it is another task: never trust it
        } catch (e) { if (e instanceof SessionError || e instanceof TransientError) throw e; secret = true; }   // a card that cannot be read: treated as secret, no answer text
        await sleep(pace);
        try { ans = await client.answers(id); loaded = true; } catch (e) { if (e instanceof SessionError || e instanceof TransientError) throw e; }
        await sleep(pace);
      }
      return Object.assign(snapshotOf(t.code, sec.id, it, ans, loaded, job.answers_days), { is_secret: secret });
    }
    /* the tasks are taken in small portions by several workers; before reading a portion the platform is asked which of it is free:
       what another person's run has taken or has just read is left to them (several people can press the button at once, and nobody reads the same twice) */
    let cursor = 0;
    const PORTION = 6;
    const pull = () => { const b = job.items.slice(cursor, cursor + PORTION); cursor += b.length; return b; };
    async function worker() {
      while (!halt) {
        const batch = pull(); if (!batch.length) return;
        let mine = batch;
        try {
          const g = await server("POST", "/api/sync/claim", { run_id: job.run_id, codes: batch.map(x => x.code) });
          if (g && Array.isArray(g.granted)) { const ok = new Set(g.granted); mine = batch.filter(x => ok.has(x.code)); taken += batch.length - mine.length; }
        } catch (e) { /* an older platform, or a hiccup: the portion is simply read by this run (reading twice is harmless) */ }
        for (const t of mine) {
          if (halt) return;
          if (shouldStop && shouldStop()) { stopped = stopped || "Остановлено вами"; halt = true; return; }
          try {
            const snap = await checkOne(t);
            buffer.push(snap); done++; if (snap.found) found++;
            streak = 0; if (++okRun >= 20 && pace > delay) { pace = Math.max(delay, Math.round(pace / 2)); okRun = 0; }
          } catch (e) {
            if (!(e instanceof TransientError)) throw e;
            failed.push(t.code); streak++; okRun = 0; pace = Math.min(pace * 2, 2500);   // a stubborn task is skipped, the whole run is not lost; the pace slows down
            if (streak >= 4) { stopped = stopped || "Сайт ijro сейчас не отвечает (" + e.message + "). Подождите несколько минут и нажмите «Продолжить»: уже проверенное повторно не читается."; halt = true; return; }
          }
          progress();
          if (buffer.length >= chunk) await flush();
        }
        progress();
      }
    }
    await Promise.all(Array.from({ length: width }, () => worker().catch(e => { halt = true; fatal = fatal || e; })));
    if (fatal) { stopped = fatal.message || String(fatal); if (!(fatal instanceof SessionError || fatal instanceof RateError)) { await flush().catch(() => {}); throw fatal; } }
    await flush();
    return { done, total, found, sent, stopped, failed, taken, moved, outside: job.outside_scope || 0, run_id: job.run_id };
  }

  /* what the answers look like, without any values that could be personal: names of fields and their types */
  const ownCodeOf = it => { for (const k of ["task_code", "code", "taskCode"]) if (typeof it[k] === "string") return it[k]; return ""; };
  const shapeDeep = (v, depth) => {
    if (v === null) return "null"; if (v instanceof Uint8Array) return "bytes";
    if (Array.isArray(v)) return depth > 0 && v.length ? { "array": v.length, "first": shapeDeep(v[0], depth - 1) } : "array(" + v.length + ")";
    if (typeof v === "object") { if (depth <= 0) return "object"; const r = {}; for (const k of Object.keys(v).slice(0, 60)) r[k] = shapeDeep(v[k], depth - 1); return r; }
    if (typeof v === "string") return "string(" + v.length + ")";
    if (typeof v === "boolean" || (typeof v === "number" && Math.abs(v) < 1000)) return v;
    return typeof v;
  };
  /* what the answers look like, without any value that could be personal: names of fields, their types, small numbers */
  async function diagnose({ server, client, session }) {
    const job = await server("GET", "/api/sync/job");
    const out = { script: VERSION, session: session ? { has_session_id: !!session.id, year: session.year, has_recipient_db_id: !!session.recipientDb, page_template_seen: !!session.template, template_keys: session.template ? Object.keys(session.template) : [] } : null, job_items: job.items.length, probes: [] };
    for (const t of job.items.slice(0, 15)) {
      for (const s of job.sections) {
        const info = {};
        const it = await client.find(t.code, s, info);
        if (it) {
          const id = it.id ?? it.recipient_id;
          const ans = await client.answers(id).catch(e => [{ error: String(e.message || e) }]);
          const cardRes = await client.card(id).then(c => ({ ok: true, is_secret: c.is_secret, shape: shapeDeep(c.raw, 2) }), e => ({ ok: false, error: String(e.message || e) }));
          const per = Array.isArray(it.repeat_periods) && it.repeat_periods[0] ? shapeDeep(it.repeat_periods[0], 1) : null;
          return Object.assign(out, { found: true, section: s.id, matched_by: ownCodeOf(it) ? "code_in_item" : "server_filter", ambiguous: info.ambiguous || 0, item: shapeDeep(it, 2), repeat_period: per, card: cardRes, answers_count: ans.length, answer: shapeDeep(ans[0], 3) });
        }
      }
    }
    // nothing found: show what the site answers to the same question, to see what differs
    const t = job.items[0];
    for (const s of job.sections) {
      for (const [name, over] of [["как в скрипте", {}], ["без типов документов", { type_ids: [] }], ["без кода, 1 запись", { type_ids: [], task_code: "", limit: 1 }]]) {
        const r = await client.raw("/task/v2/list-by-recipient", client.bodyFor(t.code, s, over));
        const list = listOf(r.data);
        out.probes.push({ section: s.id, variant: name, http: r.status, decode_error: r.err, answer: shapeDeep(r.data, 2), list_length: list.length, code_path_in_first: list[0] ? codePath(list[0], null) : null, code_is_here: list.some(x => hasCode(x, t.code)), sent_type_ids: (over.type_ids || s.type_ids).length });
      }
    }
    out.error = "Ни одна из первых задач не найдена на сайте";
    return out;
  }

  /* after the exports and the check of every open task: the platform finds the tasks that the site no longer lists as ours. Only a COMPLETE run is judged. */
  async function finishRun({ server, run, exp, sync }) {
    const complete = !!(exp && exp.files >= exp.expected && !exp.errors.length && !exp.stopped && sync && !sync.stopped && !sync.failed.length);
    return server("POST", "/api/sync/finish", { run, complete });
  }
  const newRun = () => (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : Array.from({ length: 32 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join(""));

  /* a call to the platform that failed for a reason that passes (no answer, the connection broke, the server is restarting: 5xx, 429) is repeated; any other answer is final.
     The platform's calls are safe to repeat: a batch of answers overwrites the same snapshots. */
  async function withRetry(fn, { tries = 3, waits = [3000, 10000], sleep } = {}) {
    let last;
    for (let i = 0; i < tries; i++) {
      try { return await fn(); } catch (e) {
        last = e; if (!e || !e.retryable || i === tries - 1) break;
        await sleep(waits[Math.min(i, waits.length - 1)]);
      }
    }
    if (last && last.retryable) last.message += " (попыток: " + tries + ")";
    throw last;
  }

  const core = { withRetry, orgOf, encode, decode, makeClient, runSync, finishRun, newRun, runExports, fetchExport, exportBody, diagnose, snapshotOf, itemCode, codePath, hasCode, shapeDeep, listOf, toMs, SessionError, RateError, TransientError, DEFAULT_BODY };
  if (typeof module !== "undefined" && module.exports) { module.exports = core; return; }
  if (typeof GM_xmlhttpRequest === "undefined" || typeof document === "undefined") return;

  /* ───────────── in the browser: hooks, panel ───────────── */
  const W = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
  const state = { id: "", year: new Date().getFullYear(), recipientDb: "", template: null };
  const pageFetch = W.fetch.bind(W);   // the original, taken before the hook below
  const noteHeaders = h => {
    try {
      const get = n => h instanceof W.Headers ? h.get(n) : Array.isArray(h) ? (h.find(x => String(x[0]).toLowerCase() === n) || [])[1] : h && (h[n] || h[n.replace(/(^|-)(\w)/g, (m, a, b) => a + b.toUpperCase())]);
      const id = get("x-session-id"), yr = get("x-year");
      if (id) state.id = String(id); if (yr) state.year = Number(yr) || state.year;
    } catch (e) { /* the site must never break because of this script */ }
  };
  const noteBody = (url, body) => {
    const handle = u8 => { try { const o = decode(u8); if (o && typeof o === "object" && !Array.isArray(o) && o.recipient_db_id) { state.recipientDb = o.recipient_db_id; if (/list-by-recipient/.test(url)) state.template = o; } } catch (e) { /* not msgpack */ } };
    try {
      if (body instanceof ArrayBuffer) handle(new Uint8Array(body)); else if (ArrayBuffer.isView(body)) handle(new Uint8Array(body.buffer, body.byteOffset, body.byteLength));
      else if (body && typeof body.arrayBuffer === "function") body.arrayBuffer().then(b => handle(new Uint8Array(b))).catch(() => {});
    } catch (e) { /* ignore */ }
  };
  const ours = url => /ijro\.uz\/api\//.test(String(url));
  const origFetch = W.fetch;
  W.fetch = function (input, init) {
    try { const url = typeof input === "string" ? input : input && input.url; if (ours(url)) { noteHeaders((init && init.headers) || (input && input.headers)); noteBody(url, init && init.body); } } catch (e) { /* ignore */ }
    return origFetch.apply(this, arguments);
  };
  try {
    const X = W.XMLHttpRequest.prototype, open = X.open, setH = X.setRequestHeader, send = X.send;
    X.open = function (m, u) { this.__zu = u; this.__zh = {}; return open.apply(this, arguments); };
    X.setRequestHeader = function (k, v) { try { if (this.__zh) this.__zh[String(k).toLowerCase()] = v; } catch (e) { /* ignore */ } return setH.apply(this, arguments); };
    X.send = function (b) { try { if (ours(this.__zu)) { noteHeaders(this.__zh); noteBody(this.__zu, b); } } catch (e) { /* ignore */ } return send.apply(this, arguments); };
  } catch (e) { /* ignore */ }

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const retryable = msg => Object.assign(new Error(msg), { retryable: true });
  const serverOnce = (method, path, body) => new Promise((resolve, reject) => {
    const key = GM_getValue("zk", "");
    if (!key) return reject(new Error("Нет ключа синхронизации: нажмите «Ключ…» и вставьте ключ из раздела «Синхронизация» платформы."));
    GM_xmlhttpRequest({ method, url: SERVER + path, headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" }, data: body ? JSON.stringify(body) : undefined, timeout: 60000,
      onload: r => { let j = null; try { j = JSON.parse(r.responseText); } catch (e) { /* ignore */ } if (r.status >= 200 && r.status < 300) resolve(j); else { const m = (j && j.error) || "Платформа ответила " + r.status; reject(r.status >= 500 || r.status === 429 ? retryable(m) : new Error(m)); } },
      onerror: () => reject(retryable("Нет связи с платформой " + SERVER)), ontimeout: () => reject(retryable("Платформа не отвечает")) });
  });
  const server = (method, path, body) => withRetry(() => serverOnce(method, path, body), { sleep });
  const upload = (path, buf) => new Promise((resolve, reject) => {   // the xlsx as it is, to the platform
    const key = GM_getValue("zk", "");
    if (!key) return reject(new Error("Нет ключа синхронизации"));
    GM_xmlhttpRequest({ method: "POST", url: SERVER + path, headers: { Authorization: "Bearer " + key, "Content-Type": "application/octet-stream" }, data: new Blob([buf]), timeout: 300000,
      onload: r => { let j = null; try { j = JSON.parse(r.responseText); } catch (e) { /* ignore */ } if (r.status >= 200 && r.status < 300) resolve(j); else reject(new Error((j && j.error) || "Платформа ответила " + r.status)); },
      onerror: () => reject(new Error("Нет связи с платформой")), ontimeout: () => reject(new Error("Платформа долго обрабатывает файл")) });
  });
  const client = () => makeClient({ pageFetch, getSession: () => state, apiBase: "https://adliya.ijro.uz/api", sleep });

  let stop = false, running = false, resume = false, withExports = GM_getValue("exports", "0") === "1";      // by default the script only reads the stages: the base of tasks is loaded on the platform from Excel
  function panel() {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;font:14px/1.4 system-ui,sans-serif";
    const sh = host.attachShadow({ mode: "open" });
    sh.innerHTML = `<style>
      button{font:inherit;cursor:pointer;border:1px solid #cfd6e6;background:#fff;border-radius:10px;padding:8px 12px}button.pri{background:#4f46e5;border-color:#4f46e5;color:#fff}
      .fab{box-shadow:0 8px 24px rgba(20,28,60,.25);border-radius:999px;padding:10px 16px;background:#4f46e5;color:#fff;border:0}
      .box{display:none;width:340px;background:#fff;color:#151b2e;border:1px solid #e4e8f1;border-radius:14px;box-shadow:0 18px 50px rgba(20,28,60,.3);padding:14px}
      .box.on{display:block}.row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.bar{height:8px;background:#eef1f8;border-radius:8px;overflow:hidden;margin:10px 0}.bar i{display:block;height:100%;width:0;background:#4f46e5;transition:width .3s}
      .log{max-height:150px;overflow:auto;font-size:12.5px;color:#56607a;white-space:pre-wrap}b{font-weight:600}</style>
      <div class="box" id="box"><b>Синхронизация с «Задачи»</b>
        <div class="log" id="hint">Читаю с сайта историю этапов (ответы Адлии, Кабинета, Счётной палаты) у задач из базы платформы и записываю её к ним. Какие задачи проверять, задают «Настройки» → «Импорт и синхронизация». Задачи и их статусы приходят из базы, которую вы загружаете на странице «Импорт». На ijro ничего не меняется.</div>
        <div class="bar"><i id="bar"></i></div><div class="log" id="log"></div>
        <div class="row"><button class="pri" id="go">Синхронизировать</button><button id="stop" disabled>Стоп</button><button id="diag">Диагностика</button><button id="key">Ключ…</button><button id="exp">Скачивать списки: выкл</button><button id="close">Закрыть</button></div></div>
      <button class="fab" id="fab">⇄ Задачи</button>`;
    const $ = id => sh.getElementById(id), log = t => { $("log").textContent = t; };
    $("fab").onclick = () => $("box").classList.toggle("on"); $("close").onclick = () => $("box").classList.remove("on");
    $("key").onclick = () => { const v = prompt("Ключ синхронизации (из раздела «Синхронизация» платформы):", ""); if (v !== null) { GM_setValue("zk", v.trim()); log(v.trim() ? "Ключ сохранён в этом браузере." : "Ключ удалён."); } };
    const showExp = () => { $("exp").textContent = "Скачивать списки: " + (withExports ? "вкл" : "выкл"); };
    $("exp").onclick = () => { withExports = !withExports; GM_setValue("exports", withExports ? "1" : "0"); showExp(); log(withExports ? "Перед проверкой статусов скачаются выгрузки «Hisobot» (новые задачи, тексты, сроки)." : "Выгрузки отключены: только статусы известных задач."); };
    showExp();
    $("stop").onclick = () => { stop = true; };
    $("diag").onclick = async () => {
      if (running) return; running = true; log("Диагностика…");
      try { const r = await diagnose({ server, client: client(), session: state }); const t = JSON.stringify(r, null, 2); log(t); try { await navigator.clipboard.writeText(t); log("Скопировано в буфер обмена. Отправьте это разработчику.\n" + t); } catch (e) { /* shown anyway */ } }
      catch (e) { log("Ошибка: " + e.message); } running = false;
    };
    $("go").onclick = async () => {
      if (running) return; running = true; stop = false; $("go").disabled = true; $("stop").disabled = false; $("bar").style.width = "0"; log("Запрашиваю список задач…");
      let exp = null; const run = newRun();
      if (withExports) {
        try {
          exp = await runExports({ server, upload, client: client(), recipientDb: state.recipientDb, sleep, pageFetch, shouldStop: () => stop, run, onProgress: p => { $("bar").style.width = Math.round(100 * p.i / p.n) + "%"; log(`Выгрузка ${p.i + 1} из ${p.n}: ${p.what}…`); } });
        } catch (e) { exp = { files: 0, errors: [e.message], unmapped: new Set(), created: 0, updated: 0, unchanged: 0, rows: 0, stopped: "" }; }
        if (exp.stopped) { log(exp.stopped); running = false; $("go").disabled = false; $("stop").disabled = true; return; }
        $("bar").style.width = "0";
      }
      let finLine = "";
      const expLine = () => !exp ? "" : `\nСписок: файлов ${exp.files}${exp.mode === "status" ? `, статусов обновлено ${exp.updated}, нет в базе ${exp.missing}${exp.missing ? " (добавьте через «Импорт базы задач»)" : ""}` : `, новых задач ${exp.created}, обновлено ${exp.updated}`}${exp.unmapped.size ? ", отделов без сопоставления " + exp.unmapped.size + " (откройте импорт в платформе)" : ""}${exp.errors.length ? "\nНе удалось: " + exp.errors.join("; ") : ""}`;
      try {
        const r = await runSync({ server, client: client(), sleep, resume, shouldStop: () => stop, onProgress: p => { $("bar").style.width = Math.round(100 * p.done / Math.max(1, p.total)) + "%"; log(`Проверено ${p.done} из ${p.total} · найдено на сайте ${p.found}${p.taken ? " · читают другие: " + p.taken : ""}${p.failed ? " · пропущено (сайт не ответил) " + p.failed : ""}`); } });
        let fin = null;
        if (exp) { try { fin = await finishRun({ server, run, exp, sync: r }); } catch (e) { fin = { judged: false, why: e.message }; } }
        finLine = !fin ? "" : !fin.judged ? "\nСнятие лишних задач: пропущено (" + fin.why + ")" : `\nСнятие лишних задач: не относятся к нашим выгрузкам ${fin.stale}${fin.archived ? ", убрано с дашборда " + fin.archived : ""}${fin.waiting ? ", ждут вашего решения в платформе (раздел «Синхронизация»)" : ""}${fin.unsure ? "; не проверялись или закрыты: " + fin.unsure : ""}`;
        resume = !!(r.stopped || r.failed.length);   // after an interrupted run the same button continues where it stopped
        log(`${r.stopped ? r.stopped + "\n" : ""}Проверено ${r.done} из ${r.total}, найдено ${r.found}, передано ${r.sent}.${r.taken ? "\nЗадач, которые в это время читал другой пользователь: " + r.taken + " (их результат уже в платформе)." : ""}\nСтатусы в платформе: ${r.moved.done + r.moved.progress ? "обновлено " + (r.moved.done + r.moved.progress) + " (выполнено " + r.moved.done + ", в работе " + r.moved.progress + ")" : "изменений нет"}${r.moved.due ? ", новых сроков: " + r.moved.due : ""}.${r.outside ? "\nНе проверялись " + r.outside + " невыполненных: вне периода, выбранного в «Настройках» («У каких задач читать историю этапов»)." : ""}${r.failed.length ? "\nНе удалось проверить " + r.failed.length + " (сайт не отвечал): " + r.failed.slice(0, 8).join(", ") + (r.failed.length > 8 ? "…" : "") + ". Нажмите «Продолжить»." : ""}\nОткройте в платформе раздел «Синхронизация»: там список изменений.${expLine()}${finLine}`);
      } catch (e) { resume = true; log("Ошибка: " + e.message + "\nНажмите «Продолжить»: уже проверенное повторно не читается."); }
      running = false; $("go").disabled = false; $("stop").disabled = true; $("go").textContent = resume ? "Продолжить" : "Синхронизировать";
    };
    document.documentElement.appendChild(host);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", panel); else panel();
})(typeof globalThis !== "undefined" ? globalThis : this);
