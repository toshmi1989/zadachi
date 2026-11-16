// ==UserScript==
// @name         Задачи ⇄ ijro: синхронизация статусов
// @namespace    zadachi
// @version      1.0.2
// @description  Читает статусы и ответы по задачам на edo.ijro.uz из вашей уже открытой сессии и передаёт их в платформу «Задачи». Ничего не меняет на ijro.
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
  const DEFAULT_BODY = { limit: 20, offset: 0, statuses: [], type_ids: [], recipient_db_id: null, year: null, task_code: "", strict_search: false, document_number: null,
    document_type_id: null, from_due_date: null, to_due_date: null, document_from_date: null, document_to_date: null, undistributed_tasks: false, seen: null,
    main_recipient: false, is_rayosat: false, not_rayosat: false, tasks: [], due_date_sort: null, active_state_high_org_id: null, repeatable: false, recipient_user_id: null };
  const rid = () => Array.from({ length: 24 }, () => "0123456789abcdef"[Math.floor(Math.random() * 16)]).join("");
  const toMs = v => { if (v == null) return null; if (typeof v === "string" && /^\d{10,13}$/.test(v)) v = Number(v); if (typeof v === "number") return v < 1e11 ? Math.round(v * 1000) : Math.round(v); if (v instanceof Date) return v.getTime(); const t = Date.parse(v); return isNaN(t) ? null : t; };
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
      const res = await pageFetch(apiBase + path, { method: "POST", headers: { "Content-Type": "application/octet-stream", "x-session-id": s.id, "x-year": String(s.year), "x-request-id": rid() }, body: encode(body) });
      let data = null, err = null;
      try { data = decode(new Uint8Array(await res.arrayBuffer())); } catch (e) { err = String(e.message || e); }
      return { status: res.status, data, err };
    }
    async function call(path, body, tries = 2) {
      const s = getSession();
      if (!s.id) throw new SessionError("Не удалось получить сессию ijro: откройте любой раздел «Топшириқлар» на сайте и повторите.");
      const res = await pageFetch(apiBase + path, { method: "POST", headers: { "Content-Type": "application/octet-stream", "x-session-id": s.id, "x-year": String(s.year), "x-request-id": rid() }, body: encode(body) });
      if (res.status === 401 || res.status === 403) throw new SessionError("Сессия ijro закончилась или доступ закрыт (" + res.status + "). Войдите заново и повторите.");
      if (res.status === 429) throw new RateError("Сайт просит замедлиться (429)");
      if (res.status >= 500 && tries > 1) { await sleep(2000); return call(path, body, tries - 1); }
      if (!res.ok) throw new Error("ijro ответил " + res.status);
      return decode(new Uint8Array(await res.arrayBuffer()));
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
      return { is_secret: flag(r), raw: r };
    }
    const answers = async recipientId => listOf(await call("/task-requests/list", { recipient_id: recipientId, period_id: null }));
    const bodyFor = (code, section, over) => { const s = getSession(); return Object.assign({}, DEFAULT_BODY, s.template || {}, { limit: 20, offset: 0, statuses: [], type_ids: section.type_ids, task_code: code, year: null, strict_search: false, recipient_db_id: s.recipientDb, document_number: null, document_type_id: null, from_due_date: null, to_due_date: null, document_from_date: null, document_to_date: null, tasks: [] }, over || {}); };
    return { call, raw, find, answers, bodyFor, card };
  }

  function snapshotOf(code, sectionId, it, answerList, loaded) {
    const periods = (Array.isArray(it.repeat_periods) ? it.repeat_periods : []).map(p => ({ order: p.order_index, status: p.status, recipient_status: p.recipient_status, due_ms: toMs(p.due_date) }));
    const num = v => typeof v === "number" && Number.isFinite(v) ? Math.trunc(v) : null;
    return {
      code, found: true, section: sectionId, recipient_id: String(pick(it, ["id", "recipient_id"]) ?? ""), status: num(it.status), is_done: !!it.is_done,
      overdue: (() => { const v = pick(it, ["overdue", "is_overdue", "expired"]); return v === undefined ? null : !!v; })(),
      repeatable: !!(it.repeatable), due_ms: toMs(pick(it, ["task_due_date_ms", "due_date"])), done_ms: toMs(it.done_at), periods, is_secret: !!it.is_secret, answers_loaded: !!loaded,
      answers: (answerList || []).slice(-30).map(a => ({ sender_type: num(a.sender_type), state: num(a.state), active: !!a.active,
        at_ms: toMs(pick(a, ["created_at", "date", "sent_at", "updated_at", "created"])), text: String(pick(a, ["comment", "text", "description", "content", "message", "note"]) ?? "").slice(0, 600) })),
    };
  }

  /* ───────────── one synchronisation run ───────────── */
  async function runSync({ server, client, onProgress, shouldStop, sleep, chunk = 40, delay = 250 }) {
    const job = await server("GET", "/api/sync/job");
    const sections = Object.fromEntries(job.sections.map(s => [s.id, s]));
    const order = hint => hint && sections[hint] ? [sections[hint]].concat(job.sections.filter(s => s.id !== hint)) : job.sections;
    const buffer = []; let done = 0, found = 0, sent = 0, stopped = "";
    const flush = async () => { if (!buffer.length) return; const items = buffer.splice(0, buffer.length); await server("POST", "/api/sync/ingest", { run_id: job.run_id, items }); sent += items.length; };
    try {
      for (const t of job.items) {
        if (shouldStop && shouldStop()) { stopped = "Остановлено вами"; break; }
        let it = null, sec = null, tries = 0;
        for (const s of order(t.section)) {
          for (;;) {
            try { it = await client.find(t.code, s); break; }
            catch (e) { if (e instanceof RateError && ++tries <= 3) { await sleep(5000 * tries); continue; } throw e; }
          }
          await sleep(delay);
          if (it) { sec = s; break; }
        }
        if (!it) buffer.push({ code: t.code, found: false });
        else {
          found++;
          let ans = [], loaded = false, secret = !!it.is_secret;
          if (it.status !== 0 || it.is_done || it.repeatable) {
            const id = it.id ?? it.recipient_id;
            // when the card cannot be read the task is treated as secret: no answer text is copied
            try { secret = secret || (await client.card(id)).is_secret; } catch (e) { if (e instanceof SessionError || e instanceof RateError) throw e; secret = true; }
            await sleep(delay);
            ans = await client.answers(id).catch(e => { if (e instanceof SessionError || e instanceof RateError) throw e; return []; }); loaded = true; await sleep(delay);
          }
          buffer.push(Object.assign(snapshotOf(t.code, sec.id, it, ans, loaded), { is_secret: secret }));
        }
        done++;
        if (onProgress) onProgress({ done, total: job.items.length, found });
        if (buffer.length >= chunk) await flush();
      }
    } catch (e) { stopped = e.message || String(e); if (!(e instanceof SessionError || e instanceof RateError)) { await flush().catch(() => {}); throw e; } }
    await flush();
    return { done, total: job.items.length, found, sent, stopped, run_id: job.run_id };
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
    const out = { script: "1.0.1", session: session ? { has_session_id: !!session.id, year: session.year, has_recipient_db_id: !!session.recipientDb, page_template_seen: !!session.template, template_keys: session.template ? Object.keys(session.template) : [] } : null, job_items: job.items.length, probes: [] };
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

  const core = { encode, decode, makeClient, runSync, diagnose, snapshotOf, itemCode, codePath, hasCode, shapeDeep, listOf, toMs, SessionError, RateError, DEFAULT_BODY };
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
  const server = (method, path, body) => new Promise((resolve, reject) => {
    const key = GM_getValue("zk", "");
    if (!key) return reject(new Error("Нет ключа синхронизации: нажмите «Ключ…» и вставьте ключ из раздела «Синхронизация» платформы."));
    GM_xmlhttpRequest({ method, url: SERVER + path, headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" }, data: body ? JSON.stringify(body) : undefined, timeout: 60000,
      onload: r => { let j = null; try { j = JSON.parse(r.responseText); } catch (e) { /* ignore */ } if (r.status >= 200 && r.status < 300) resolve(j); else reject(new Error((j && j.error) || "Платформа ответила " + r.status)); },
      onerror: () => reject(new Error("Нет связи с платформой " + SERVER)), ontimeout: () => reject(new Error("Платформа не отвечает")) });
  });
  const client = () => makeClient({ pageFetch, getSession: () => state, apiBase: "https://adliya.ijro.uz/api", sleep });

  let stop = false, running = false;
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
        <div class="log" id="hint">Читаю статусы открытых задач на ijro и передаю их в платформу. На ijro ничего не меняется.</div>
        <div class="bar"><i id="bar"></i></div><div class="log" id="log"></div>
        <div class="row"><button class="pri" id="go">Синхронизировать</button><button id="stop" disabled>Стоп</button><button id="diag">Диагностика</button><button id="key">Ключ…</button><button id="close">Закрыть</button></div></div>
      <button class="fab" id="fab">⇄ Задачи</button>`;
    const $ = id => sh.getElementById(id), log = t => { $("log").textContent = t; };
    $("fab").onclick = () => $("box").classList.toggle("on"); $("close").onclick = () => $("box").classList.remove("on");
    $("key").onclick = () => { const v = prompt("Ключ синхронизации (из раздела «Синхронизация» платформы):", ""); if (v !== null) { GM_setValue("zk", v.trim()); log(v.trim() ? "Ключ сохранён в этом браузере." : "Ключ удалён."); } };
    $("stop").onclick = () => { stop = true; };
    $("diag").onclick = async () => {
      if (running) return; running = true; log("Диагностика…");
      try { const r = await diagnose({ server, client: client(), session: state }); const t = JSON.stringify(r, null, 2); log(t); try { await navigator.clipboard.writeText(t); log("Скопировано в буфер обмена. Отправьте это разработчику.\n" + t); } catch (e) { /* shown anyway */ } }
      catch (e) { log("Ошибка: " + e.message); } running = false;
    };
    $("go").onclick = async () => {
      if (running) return; running = true; stop = false; $("go").disabled = true; $("stop").disabled = false; $("bar").style.width = "0"; log("Запрашиваю список задач…");
      try {
        const r = await runSync({ server, client: client(), sleep, shouldStop: () => stop, onProgress: p => { $("bar").style.width = Math.round(100 * p.done / Math.max(1, p.total)) + "%"; log(`Проверено ${p.done} из ${p.total} · найдено на сайте ${p.found}`); } });
        log(`${r.stopped ? "Остановлено: " + r.stopped + "\n" : ""}Проверено ${r.done} из ${r.total}, найдено ${r.found}, передано ${r.sent}.\nОткройте в платформе раздел «Синхронизация»: там список изменений.`);
      } catch (e) { log("Ошибка: " + e.message); }
      running = false; $("go").disabled = false; $("stop").disabled = true;
    };
    document.documentElement.appendChild(host);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", panel); else panel();
})(typeof globalThis !== "undefined" ? globalThis : this);
