/* Hub SuperFrio & Icestar — frontend único (login + home) */

const API = ""; // mesmo host (FastAPI serve os estáticos)
const TOKEN_KEY = "sf_portal_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY) || null,
  user: null,
  secoes: [],         // [{slug, nome, icone, ordem, apps:[...]}]
  currentSecao: "__all__",
  query: "",
};

// Exposto pro admin.js
window.SF = window.SF || {};
window.SF.state = state;
window.SF.TOKEN_KEY = TOKEN_KEY;

// Atalhos i18n (i18n.js carrega antes deste arquivo)
const t = (k) => window.SF.i18n.t(k);
const pick = (rec, f) => window.SF.i18n.pick(rec, f);

/* ---------- Ícones SVG ---------- */
// Stroke icons (linha) — combinam com o estilo discreto da Maria.
const ICONS = {
  warehouse: '<path d="M3 21V9l9-6 9 6v12"/><path d="M9 21V12h6v9"/>',
  briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  scale: '<path d="M3 21h18"/><path d="M12 3v18"/><path d="M5 9l-2 6h6l-2-6"/><path d="M19 9l-2 6h6l-2-6"/><path d="M5 9h14"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  cart: '<circle cx="9" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/><path d="M2 3h3l2.7 12.4a2 2 0 0 0 2 1.6h8.6a2 2 0 0 0 2-1.6L23 6H6"/>',
  document: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  truck: '<rect x="1" y="6" width="13" height="10" rx="1"/><path d="M14 9h4l3 3v4h-7z"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  default: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18"/><path d="M9 21V9"/>',
};
function iconSvg(key) {
  const body = ICONS[key] || ICONS.default;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
}

/* ---------- Auth ---------- */
async function login(username, password) {
  const body = new URLSearchParams({ username, password });
  const res = await fetch(`${API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || t("login.err.auth"));
  }
  const data = await res.json();
  state.token = data.access_token;
  state.user = data.user;
  localStorage.setItem(TOKEN_KEY, state.token);
  return data;
}

async function fetchHome() {
  const res = await fetch(`${API}/api/portal/home`, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (res.status === 401) {
    logout();
    throw new Error(t("session.expired"));
  }
  if (!res.ok) throw new Error(t("home.loaderr"));
  return res.json();
}

function logout() {
  state.token = null;
  state.user = null;
  state.secoes = [];
  state.currentSecao = "__all__";
  state.query = "";
  localStorage.removeItem(TOKEN_KEY);
  showLogin();
}

/* ---------- Render ---------- */
function showLogin() {
  document.getElementById("screen-login").classList.remove("hidden");
  document.getElementById("screen-portal").classList.add("hidden");
  document.getElementById("login-error").classList.remove("visible");
  document.getElementById("form-login").reset();
  setTimeout(() => document.getElementById("login-username").focus(), 50);
}

function showPortal() {
  document.getElementById("screen-login").classList.add("hidden");
  document.getElementById("screen-portal").classList.remove("hidden");
}

function initials(nome) {
  if (!nome) return "··";
  const parts = nome.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function greet() {
  const h = new Date().getHours();
  if (h < 5) return t("greet.dawn");
  if (h < 12) return t("greet.morning");
  if (h < 18) return t("greet.afternoon");
  return t("greet.night");
}

function renderHeader() {
  const u = state.user;
  if (!u) return;
  document.getElementById("user-nome").textContent = u.nome || u.username;
  document.getElementById("user-role").textContent = u.is_admin ? t("role.admin") : t("role.user");
  document.getElementById("user-avatar").textContent = initials(u.nome || u.username);
  const primeiroNome = (u.nome || u.username).split(/\s+/)[0];
  document.getElementById("greeting").textContent = `${greet()}, ${primeiroNome}`;

  // Botão admin só para administrador
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.classList.toggle("hidden", !u.is_admin);
  });
}

function renderSidebar() {
  const cont = document.getElementById("sidebar-secoes");
  cont.innerHTML = "";
  state.secoes.forEach((s) => {
    const btn = document.createElement("button");
    btn.className = "sidebar-link";
    btn.dataset.secao = s.slug;
    btn.innerHTML = `
      ${iconSvg(s.icone || "default").replace('<svg ', '<svg class="icon" ')}
      ${escapeHtml(pick(s, "nome"))}
      <span class="count">${s.apps.length}</span>
    `;
    btn.addEventListener("click", () => {
      state.currentSecao = s.slug;
      renderActiveSecao();
      renderContent();
    });
    cont.appendChild(btn);
  });

  const total = state.secoes.reduce((acc, s) => acc + s.apps.length, 0);
  document.getElementById("count-all").textContent = total;
}

function renderActiveSecao() {
  document.querySelectorAll(".sidebar-link").forEach((el) => {
    el.classList.toggle("active", el.dataset.secao === state.currentSecao);
  });
}

function filteredSecoes() {
  const q = state.query.trim().toLowerCase();
  let secoes = state.secoes;
  if (state.currentSecao !== "__all__") {
    secoes = secoes.filter((s) => s.slug === state.currentSecao);
  }
  if (!q) return secoes;
  return secoes
    .map((s) => ({
      ...s,
      apps: s.apps.filter(
        (a) =>
          (a.nome || "").toLowerCase().includes(q) ||
          (a.descricao || "").toLowerCase().includes(q)
      ),
    }))
    .filter((s) => s.apps.length > 0);
}

function badgeHtml(app) {
  if (app.badge) {
    const cls = app.badge.toLowerCase() === "new" ? "new" : app.badge.toLowerCase() === "beta" ? "beta" : "";
    return `<span class="app-card-badge ${cls}">${escapeHtml(app.badge)}</span>`;
  }
  if (app.tipo_acesso === "iframe") {
    return `<span class="app-card-badge iframe">${escapeHtml(t("badge.embed"))}</span>`;
  }
  return "";
}

function cardHtml(app) {
  const arrow = app.tipo_acesso === "iframe"
    ? `<svg class="arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`
    : `<svg class="arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7"/><polyline points="7 7 17 7 17 17"/></svg>`;
  const acessoLabel = app.tipo_acesso === "iframe" ? t("card.open.iframe") : t("card.open.url");

  return `
    <a class="app-card" data-slug="${escapeHtml(app.slug)}" href="${escapeHtml(app.url)}">
      <div class="app-card-top">
        <div class="app-card-icon">${iconSvg(app.icone || "default")}</div>
        ${badgeHtml(app)}
      </div>
      <h3 class="app-card-title">${escapeHtml(pick(app, "nome"))}</h3>
      <p class="app-card-desc">${escapeHtml(pick(app, "descricao"))}</p>
      <div class="app-card-foot">
        <span>${escapeHtml(acessoLabel)}</span>
        ${arrow}
      </div>
    </a>
  `;
}

function renderContent() {
  const cont = document.getElementById("content");
  const secoes = filteredSecoes();

  if (secoes.length === 0) {
    cont.innerHTML = `
      <div class="empty-state">
        <h3>${escapeHtml(t("empty.title"))}</h3>
        <p>${escapeHtml(state.query ? t("empty.search") : t("empty.noapps"))}</p>
      </div>
    `;
    return;
  }

  let html = "";
  secoes.forEach((s) => {
    html += `
      <section class="section-block">
        <div class="section-block-head">
          <h2>${escapeHtml(pick(s, "nome"))}</h2>
          <span class="count-chip">${s.apps.length} app${s.apps.length === 1 ? "" : "s"}</span>
          <span class="rule"></span>
        </div>
        <div class="app-grid">
          ${s.apps.map(cardHtml).join("")}
        </div>
      </section>
    `;
  });
  cont.innerHTML = html;

  cont.querySelectorAll(".app-card").forEach((el) => {
    el.addEventListener("click", (ev) => {
      ev.preventDefault();
      const slug = el.dataset.slug;
      const app = findAppBySlug(slug);
      if (!app) return;
      openApp(app);
    });
  });
}

function findAppBySlug(slug) {
  for (const s of state.secoes) {
    const a = s.apps.find((x) => x.slug === slug);
    if (a) return a;
  }
  return null;
}

function openApp(app) {
  if (app.tipo_acesso === "iframe") {
    document.getElementById("iframe-title").textContent = app.nome;
    document.getElementById("iframe-url").textContent = app.url;
    document.getElementById("iframe-content").src = app.url;
    document.getElementById("iframe-overlay").classList.add("visible");
  } else {
    window.open(app.url, "_blank", "noopener");
  }
}

function closeIframe() {
  document.getElementById("iframe-overlay").classList.remove("visible");
  document.getElementById("iframe-content").src = "about:blank";
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

window.SF.escapeHtml = escapeHtml;
window.SF.iconSvg = iconSvg;

/* ---------- Bootstrap ---------- */
async function loadPortal() {
  try {
    const data = await fetchHome();
    state.user = data.user;
    state.secoes = data.secoes;
    showPortal();
    renderHeader();
    renderSidebar();
    renderActiveSecao();
    renderContent();
  } catch (e) {
    console.error(e);
    showLogin();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  /* Form de login */
  document.getElementById("form-login").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    const btn = document.getElementById("login-submit");
    const err = document.getElementById("login-error");
    err.classList.remove("visible");
    btn.disabled = true;
    btn.textContent = t("login.submitting");
    try {
      await login(username, password);
      await loadPortal();
    } catch (e) {
      err.textContent = e.message || t("login.err.generic");
      err.classList.add("visible");
    } finally {
      btn.disabled = false;
      btn.textContent = t("login.submit");
    }
  });

  /* Busca */
  const search = document.getElementById("search");
  let tmr;
  search.addEventListener("input", () => {
    clearTimeout(tmr);
    tmr = setTimeout(() => {
      state.query = search.value;
      renderContent();
    }, 120);
  });

  /* Logout */
  document.getElementById("btn-logout").addEventListener("click", () => {
    if (confirm(t("confirm.logout"))) logout();
  });

  /* Troca de idioma: re-renderiza o conteúdo dinâmico do portal */
  window.addEventListener("sf:langchange", () => {
    if (!state.user) return;
    renderHeader();
    renderSidebar();
    renderActiveSecao();
    renderContent();
  });

  /* Abrir/voltar admin (handlers vivem em admin.js) */
  document.getElementById("btn-open-admin").addEventListener("click", () => {
    if (window.SF && window.SF.openAdmin) window.SF.openAdmin();
  });
  document.getElementById("btn-back-portal").addEventListener("click", () => {
    document.getElementById("screen-admin").classList.add("hidden");
    document.getElementById("screen-portal").classList.remove("hidden");
  });

  /* "Todos os apps" no topo da sidebar */
  document
    .querySelector(".sidebar-link[data-secao='__all__']")
    .addEventListener("click", () => {
      state.currentSecao = "__all__";
      renderActiveSecao();
      renderContent();
    });

  /* iframe overlay */
  document.getElementById("iframe-close").addEventListener("click", closeIframe);
  document.getElementById("iframe-overlay").addEventListener("click", (ev) => {
    if (ev.target.id === "iframe-overlay") closeIframe();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && document.getElementById("iframe-overlay").classList.contains("visible")) {
      closeIframe();
    }
  });

  /* Auto-login se já tem token */
  if (state.token) {
    loadPortal();
  } else {
    showLogin();
  }
});
