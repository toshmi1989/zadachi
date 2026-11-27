"use strict";
/* Start-up: who am I, navigation by role, theme, account menu. */
(async function () {
  try { Z.me = await api("/api/me"); } catch (e) { return; }
  try { Object.keys(localStorage).filter(k => /^zf\.[a-z]+$/.test(k)).forEach(k => localStorage.removeItem(k)); } catch (e) { /* the filters kept before they were separate for each person are dropped */ }
  const me = Z.me, admin = me.role === "admin", staff = admin || me.role === "specialist";
  const nav = [["dashboard", "Дашборд", "dash"]];
  if (me.tasks !== "none") nav.push(["tasks", !admin && me.tasks === "own" ? "Мои задачи" : "Задачи", "list"]);
  if (staff) nav.push(["editor", "Редактор", "list"]);
  nav.push(["reminders", "Напоминания", "bell"]);
  if (admin) nav.push(["users", "Пользователи", "users"], ["import", "Импорт", "upload"], ["sync", "Синхронизация", "sync"], ["settings", "Настройки", "gear"]);
  $("#tabs").insertAdjacentHTML("beforeend", nav.map(n => `<a href="#/${n[0]}" data-r="${n[0]}">${icon(n[2])}${n[1]}</a>`).join(""));
  $("#bottom").innerHTML = nav.map(n => `<a href="#/${n[0]}" data-r="${n[0]}">${icon(n[2])}${n[1]}</a>`).join("");
  $("#me-av").outerHTML = avatar(me.id, me.name, "").replace("<span", '<span id="me-av"');
  $("#me-name").textContent = me.short; $("#me-role").textContent = me.role_label;

  $(".top-r").insertBefore(I18N.switcher(), $("#theme"));                 // the language: Uzbek (default) / Russian

  /* theme: auto → light → dark */
  const themeBtn = $("#theme");
  const cur = () => { try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; } };
  const paintTheme = () => { const t = cur(); themeBtn.innerHTML = icon(t === "dark" ? "moon" : t === "light" ? "sun" : "auto"); themeBtn.title = "Тема: " + ({ auto: "как в системе", light: "светлая", dark: "тёмная" })[t]; };
  themeBtn.onclick = () => {
    const next = { auto: "light", light: "dark", dark: "auto" }[cur()];
    try { next === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", next); } catch (e) {}
    if (next === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", next);
    paintTheme();
  };
  paintTheme();

  /* account menu */
  $("#me").onclick = () => {
    const box = layer("modal", `<div style="display:flex;gap:14px;align-items:center;margin-bottom:16px">${avatar(me.id, me.name, "lg")}<div><h2 style="margin:0">${esc(me.name)}</h2><span class="hint">${esc(me.login)} · ${esc(me.role_label)}</span></div></div>
      <div class="acts" style="justify-content:flex-start;flex-wrap:wrap"><button class="btn" id="chpw">${icon("key")}Сменить пароль</button>
      <form method="post" action="/logout" style="margin:0"><button class="btn">${icon("logout")}Выйти</button></form></div>`);
    $("#chpw", box).onclick = async () => {
      box.close();
      const r = await formDialog({ title: "Смена пароля", fields: [{ name: "old", label: "Текущий пароль", type: "password" }, { name: "new", label: "Новый пароль", type: "password", hint: "Не короче 8 символов" }],
        submit: d => api("/api/me/password", { method: "POST", json: d }) });
      if (r) toast("Пароль изменён");
    };
  };
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => markNav(parseHash().name));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => markNav(parseHash().name));
  if (!location.hash) location.hash = "#/dashboard"; else route();
})();
