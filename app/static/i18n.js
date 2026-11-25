"use strict";
/* Interface language: Uzbek (Cyrillic, the default) or Russian.
   The program is written in Russian; in Uzbek mode every text that reaches the page (text nodes, placeholders, tooltips, titles) is translated through the dictionary
   of i18n-uz.js: whole texts first, then the phrases inside them, then a few rules for texts with numbers. A text that is not in the dictionary stays as it is (Russian):
   nothing breaks. The data (names, task texts, department names) is never in the dictionary and is never touched. The choice is kept in this browser. */
(function () {
  const I = window.I18N = window.I18N || { dict: {}, rules: [], pre: [] };
  let lang = "uz";
  try { const v = localStorage.getItem("lang"); if (v === "ru" || v === "uz") lang = v; } catch (e) { /* the default */ }
  I.lang = lang;
  document.documentElement.lang = lang;
  I.setLang = v => { try { localStorage.setItem("lang", v); } catch (e) { /* only not remembered */ } location.reload(); };

  /* ---- dates in words ---- */
  const WD = ["якшанба", "душанба", "сешанба", "чоршанба", "пайшанба", "жума", "шанба"];
  const MN = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
  I.longDate = d => lang === "uz" ? `${d.getFullYear()} йил ${d.getDate()} ${MN[d.getMonth()]}, ${WD[d.getDay()]}`
    : d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric", weekday: "long" });

  /* ---- the switch ---- */
  I.switcher = () => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "icon-btn lang-btn"; b.id = "lang"; b.setAttribute("data-notr", "");
    b.title = "Тил / Язык"; b.textContent = lang === "uz" ? "Рус" : "Ўзб";
    b.onclick = () => I.setLang(lang === "uz" ? "ru" : "uz");
    return b;
  };

  if (lang !== "uz") { I.tr = s => s; return; }

  /* ---- the translation of one text ---- */
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let phraseRe = null, wordRe = null;
  const memo = new Map();
  const L = "\\p{L}\\p{N}";
  const re = keys => keys.length ? new RegExp(keys.map(k => (/^[\p{L}\p{N}]/u.test(k) ? `(?<![${L}])` : "") + esc(k) + (/[\p{L}\p{N}]$/u.test(k) ? `(?![${L}])` : "")).join("|"), "gu") : null;
  const build = () => {
    const keys = Object.keys(I.dict).filter(k => k.length >= 3).sort((a, b) => b.length - a.length);
    const long = k => k.includes(" ") || k.length >= 14;         // phrases first, then the rules for numbers, then the single words
    phraseRe = re(keys.filter(long)); wordRe = re(keys.filter(k => !long(k)));
  };
  const sub = (rx, s) => rx ? s.replace(rx, m => I.dict[m] !== undefined ? I.dict[m] : m) : s;
  const translateCore = core => {
    const n = core.replace(/\s+/g, " ");
    if (Object.prototype.hasOwnProperty.call(I.dict, n)) return I.dict[n];
    if (!phraseRe) build();
    let out = n;
    for (const [r, to] of I.pre || []) out = out.replace(r, to);   // the rules that must see the text before its phrases are translated
    out = sub(phraseRe, out);
    for (const [r, to] of I.rules) out = out.replace(r, to);
    return sub(wordRe, out);
  };
  I.tr = s => {
    if (typeof s !== "string" || !/[А-Яа-яЁё]/.test(s)) return s;
    const hit = memo.get(s);
    if (hit !== undefined) return hit;
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s);
    const out = m[2] ? m[1] + translateCore(m[2]) + m[3] : s;
    if (memo.size > 6000) memo.clear();
    memo.set(s, out);
    return out;
  };

  /* ---- the page ---- */
  const ATTRS = ["placeholder", "title", "data-tip", "aria-label", "alt"];
  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT", "CODE", "PRE"]);
  const skipped = el => !!(el && el.closest && el.closest("[data-notr]"));
  function node(n) {
    if (n.nodeType === 3) {
      const p = n.parentNode;
      if (!p || SKIP.has(p.nodeName) || skipped(p)) return;
      const t = I.tr(n.nodeValue);
      if (t !== n.nodeValue) n.nodeValue = t;
    } else if (n.nodeType === 1) {
      if (n.nodeName === "SCRIPT" || n.nodeName === "STYLE" || skipped(n)) return;
      for (const a of ATTRS) { const v = n.getAttribute(a); if (v && /[А-Яа-яЁё]/.test(v)) { const t = I.tr(v); if (t !== v) n.setAttribute(a, t); } }
      if (SKIP.has(n.nodeName)) return;                    // the content of a field is the person's own text
      for (let c = n.firstChild; c; c = c.nextSibling) node(c);
    }
  }
  const obs = new MutationObserver(recs => {
    for (const r of recs) {
      if (r.type === "childList") r.addedNodes.forEach(node);
      else if (r.type === "characterData") node(r.target);
      else if (r.type === "attributes") { const v = r.target.getAttribute(r.attributeName); if (v) { const t = I.tr(v); if (t !== v) r.target.setAttribute(r.attributeName, t); } }
    }
  });
  I.start = () => {
    node(document.documentElement);
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", I.start); else I.start();

})();
