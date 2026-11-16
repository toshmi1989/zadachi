"use strict";
/* Sign-in: pick your name from the list, then type the password. Without a list (switched off, or no JavaScript)
   the plain login + password form stays. The form always posts the same three fields: uid, login, password. */
(function () {
  const $ = s => document.querySelector(s);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const form = $("#f"), pick = $("#s-pick"), pass = $("#s-pass"), manual = $("#s-manual");
  const hue = id => (Number(id) * 47 + 210) % 360;
  const ini = n => { const p = n.split(/\s+/); return ((p[0] || "?")[0] + (p[1] ? p[1][0] : "")).toUpperCase(); };
  let people = [], current = null;

  const show = (sec, title) => {
    [pick, pass, manual].forEach(s => { s.hidden = s !== sec; });
    sec.classList.remove("step-in"); void sec.offsetWidth; sec.classList.add("step-in");
    $("#title").textContent = title;
  };
  const clearErr = () => { $("#err").textContent = ""; };
  const fire = (secInput, f) => secInput.addEventListener("input", f);
  const eyeIcon = '<svg viewBox="0 0 24 24" class="ic"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  $("#eye1").innerHTML = eyeIcon;
  $("#eye1").onclick = () => { const i = $("#pw1"); i.type = i.type === "password" ? "text" : "password"; i.focus(); };

  function paintList(filter) {
    const f = (filter || "").trim().toLowerCase();
    const items = people.filter(p => !f || p.name.toLowerCase().includes(f));
    $("#plist").innerHTML = items.length ? items.map((p, i) => `<button type="button" class="pitem" role="option" data-id="${p.id}" style="--i:${Math.min(i, 14)}">
      <span class="av" style="background:hsl(${hue(p.id)} 55% 48%)">${esc(ini(p.name))}</span><span class="nm">${esc(p.name)}</span></button>`).join("")
      : '<p class="hint" style="padding:14px 4px">Никого не нашли. Нажмите «Войти по логину».</p>';
  }
  function choose(p) {
    current = p;
    $("#uid").value = p.id;
    $("#who-av").style.background = `hsl(${hue(p.id)} 55% 48%)`; $("#who-av").textContent = ini(p.name);
    $("#who-name").textContent = p.name;
    show(pass, "Введите пароль");
    setTimeout(() => $("#pw1").focus(), 60);
  }
  function showPick() { current = null; $("#uid").value = ""; $("#pw1").value = ""; clearErr(); show(pick, "Кто вы?"); setTimeout(() => $("#q").focus(), 60); }
  function showManual() { current = null; $("#uid").value = ""; clearErr(); show(manual, "Вход по логину"); setTimeout(() => $("#login").focus(), 60); }

  // the real password field is a hidden input filled from whichever visible one is used, so the browser's password manager still works
  form.addEventListener("submit", () => { $("#password").value = (current ? $("#pw1") : $("#pw2")).value; });
  $("#plist").addEventListener("click", e => { const b = e.target.closest(".pitem"); if (b) choose(people.find(p => String(p.id) === b.dataset.id)); });
  $("#q").addEventListener("input", e => paintList(e.target.value));
  $("#q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); const first = $("#plist .pitem"); if (first) first.click(); } });
  $("#to-pick").onclick = showPick; $("#to-manual").onclick = showManual; $("#to-pick2").onclick = showPick;

  fetch("/api/login-users", { credentials: "same-origin" }).then(r => r.json()).then(d => {
    if (!d.enabled || !d.items.length) { show(manual, "Вход"); $("#login").focus(); return; }
    people = d.items; paintList("");
    $("#to-pick2").hidden = false; $("#nolist").hidden = true;
    const failed = document.body.dataset.uid, last = (() => { try { return localStorage.getItem("lastUid"); } catch (e) { return null; } })();
    const start = people.find(p => String(p.id) === (failed || last));
    if (start) { choose(start); } else showPick();
    form.addEventListener("submit", () => { if (current) { try { localStorage.setItem("lastUid", current.id); } catch (e) {} } });
  }).catch(() => { show(manual, "Вход"); });
  if (document.body.dataset.uid === "" && $("#login").value) $("#login").focus();
})();
