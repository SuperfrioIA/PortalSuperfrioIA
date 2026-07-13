/* Hub SuperFrio & Icestar — i18n (PT/ES) leve, sem dependência */
(() => {
  const LANG_KEY = "sf_lang";
  const SUPPORTED = ["pt", "es"];

  const DICT = {
    pt: {
      "login.aside.tag": "Hub Interno",
      "login.aside.h1": "Tudo da operação SuperFrio e Icestar em um lugar só.",
      "login.aside.p": "Acesse os apps internos da SuperFrio e Icestar — Armazém, Backoffice e governança — com um único login e suas permissões já aplicadas.",
      "login.aside.foot": "SuperFrio & Icestar · POC v0.1",
      "login.title": "Entrar",
      "login.subtitle": "Use seu usuário corporativo para acessar o hub.",
      "login.username": "Usuário",
      "login.password": "Senha",
      "login.submit": "Entrar",
      "login.submitting": "Entrando...",
      "login.err.auth": "Falha na autenticação",
      "login.err.generic": "Falha ao entrar",
      "session.expired": "Sessão expirada",
      "home.loaderr": "Erro ao carregar o hub",
      "portal.brand.sub": "Hub Interno",
      "portal.nav.label": "Navegação",
      "portal.nav.all": "Todos os apps",
      "portal.nav.governanca": "Governance TI",
      "portal.sections.label": "Seções",
      "portal.gov.label": "Governança",
      "portal.gov.admin": "Administração",
      "portal.lang.label": "Idioma",
      "portal.logout": "Sair",
      "portal.head.eyebrow": "Apps internos SuperFrio & Icestar",
      "portal.head.subtitle": "Selecione um app abaixo. Você está vendo apenas o que está liberado para o seu perfil.",
      "portal.search.placeholder": "Buscar app pelo nome ou descrição...",
      "greet.dawn": "Boa madrugada",
      "greet.morning": "Bom dia",
      "greet.afternoon": "Boa tarde",
      "greet.night": "Boa noite",
      "role.admin": "Administrador",
      "role.user": "Usuário",
      "card.open.iframe": "Abrir aqui",
      "card.open.url": "Abrir em nova aba",
      "badge.embed": "embed",
      "empty.title": "Nenhum app encontrado",
      "empty.search": "Tente outro termo de busca.",
      "empty.noapps": "Você não tem apps liberados nesta seção.",
      "confirm.logout": "Sair do hub?",
      "confirm.discard": "Descartar o preenchimento? O que você digitou será perdido.",
      "iframe.close": "Fechar",
      "admin.back": "Voltar ao hub",
      "admin.title": "Governança",
      "admin.subtitle": "Cadastro de seções, apps, roles e usuários. Toggle desativa sem apagar (auditável).",
      "admin.tab.apps": "Apps",
      "admin.tab.secoes": "Seções",
      "admin.tab.roles": "Roles",
      "admin.tab.usuarios": "Usuários",
      "admin.apps.heading": "Apps cadastrados",
      "admin.apps.new": "+ Novo app",
      "admin.secoes.heading": "Seções",
      "admin.secoes.new": "+ Nova seção",
      "admin.roles.heading": "Roles",
      "admin.roles.new": "+ Nova role",
      "admin.usuarios.heading": "Usuários",
      "admin.usuarios.new": "+ Novo usuário",
      "admin.modal.save": "Salvar",
      "admin.modal.saving": "Salvando...",
      "admin.modal.cancel": "Cancelar",
      "admin.err.load": "Erro ao carregar admin: ",
      "admin.err.generic": "Erro: ",
      "admin.save.fail": "Falha ao salvar",
      "admin.col.app": "App",
      "admin.col.secao": "Seção",
      "admin.col.tipo": "Tipo",
      "admin.col.badge": "Badge",
      "admin.col.ordem": "Ordem",
      "admin.col.status": "Status",
      "admin.col.acoes": "Ações",
      "admin.col.icone": "Ícone",
      "admin.col.apps": "Apps",
      "admin.col.role": "Role",
      "admin.col.appsLiberados": "Apps liberados",
      "admin.col.usuarios": "Usuários",
      "admin.col.usuario": "Usuário",
      "admin.col.email": "Email",
      "admin.col.roles": "Roles",
      "admin.empty.apps": "Nenhum app cadastrado.",
      "admin.empty.secoes": "Nenhuma seção cadastrada.",
      "admin.empty.roles": "Nenhuma role cadastrada.",
      "admin.empty.usuarios": "Nenhum usuário cadastrado.",
      "admin.act.edit": "Editar",
      "admin.act.deactivate": "Desativar",
      "admin.act.reactivate": "Reativar",
      "admin.act.password": "Senha",
      "admin.status.active.m": "ativo",
      "admin.status.inactive.m": "inativo",
      "admin.status.active.f": "ativa",
      "admin.status.inactive.f": "inativa",
      "admin.type.admin": "admin",
      "admin.type.user": "usuário",
      "admin.cantDeactivateSelf": "Não pode desativar a si mesmo",
      "admin.noApps": "— sem apps —",
      "admin.dash": "—",
      "admin.new.app": "Novo app",
      "admin.edit.app": "Editar app",
      "admin.new.secao": "Nova seção",
      "admin.edit.secao": "Editar seção",
      "admin.new.role": "Nova role",
      "admin.edit.role": "Editar role",
      "admin.new.usuario": "Novo usuário",
      "admin.edit.usuario": "Editar usuário",
      "admin.pwd.title": "Resetar senha",
      "admin.f.slug": "Slug",
      "admin.f.slugLocked": "(não editável)",
      "admin.f.ordem": "Ordem",
      "admin.f.nome": "Nome",
      "admin.f.nomePt": "Nome (PT)",
      "admin.f.nomeEs": "Nome (ES)",
      "admin.f.nomeEsHint": "Exibido quando o idioma do hub for Espanhol. Vazio usa o nome em Português.",
      "admin.f.descricao": "Descrição",
      "admin.f.descricaoPt": "Descrição (PT)",
      "admin.f.descricaoEs": "Descrição (ES)",
      "admin.f.icone": "Ícone",
      "admin.f.iconeHint": "Ícone exibido na sidebar (warehouse, briefcase, etc).",
      "admin.f.secao": "Seção",
      "admin.f.url": "URL",
      "admin.f.tipoAcesso": "Tipo de acesso",
      "admin.f.tipoUrl": "URL — abre em nova aba",
      "admin.f.tipoIframe": "Iframe — embute no hub",
      "admin.f.badge": "Badge",
      "admin.f.noBadge": "— sem badge —",
      "admin.f.appsLiberados": "Apps liberados",
      "admin.f.noAppsYet": "Nenhum app cadastrado ainda.",
      "admin.f.username": "Username",
      "admin.f.email": "Email",
      "admin.f.nomeCompleto": "Nome completo",
      "admin.f.senhaInicial": "Senha inicial",
      "admin.f.senhaHint": "Mínimo 8 caracteres. O usuário pode trocar depois.",
      "admin.f.isAdmin": "É administrador (acessa governança)",
      "admin.f.cantEditOwnBit": "não pode editar o próprio bit",
      "admin.f.roles": "Roles",
      "admin.f.noRolesYet": "Nenhuma role cadastrada ainda.",
      "admin.f.none": "— nenhum —",
      "admin.pwd.newPass": "Nova senha",
      "admin.pwd.hint": "Mínimo 8 caracteres. O usuário precisa entrar de novo após o reset.",
      "admin.pwd.tooShort": "Senha deve ter ao menos 8 caracteres",
      "portal.nav.changelog": "Novidades",
      "changelog.back": "Voltar ao hub",
      "changelog.eyebrow": "Portal SuperFrio & Icestar",
      "changelog.title": "Novidades",
      "changelog.subtitle": "Melhorias e correções do Portal SuperFrio & Icestar.",
      "changelog.filter.all": "Tudo",
      "changelog.filter.feature": "Melhorias",
      "changelog.filter.fix": "Correções",
      "changelog.hint": "↔ arraste para ver a linha do tempo inteira · acima = melhorias, abaixo = correções",
      "changelog.tag.feature": "Melhoria",
      "changelog.tag.fix": "Correção",
      "changelog.today": "HOJE",
      "changelog.err": "Erro ao carregar novidades",
      "changelog.empty": "Nenhuma entrada registrada.",
    },
    es: {
      "login.aside.tag": "Hub Interno",
      "login.aside.h1": "Toda la operación SuperFrio e Icestar en un solo lugar.",
      "login.aside.p": "Accede a las apps internas de SuperFrio e Icestar — Almacén, Backoffice y gobernanza — con un único inicio de sesión y tus permisos ya aplicados.",
      "login.aside.foot": "SuperFrio & Icestar · POC v0.1",
      "login.title": "Ingresar",
      "login.subtitle": "Usa tu usuario corporativo para acceder al hub.",
      "login.username": "Usuario",
      "login.password": "Contraseña",
      "login.submit": "Ingresar",
      "login.submitting": "Ingresando...",
      "login.err.auth": "Error de autenticación",
      "login.err.generic": "Error al ingresar",
      "session.expired": "Sesión expirada",
      "home.loaderr": "Error al cargar el hub",
      "portal.brand.sub": "Hub Interno",
      "portal.nav.label": "Navegación",
      "portal.nav.all": "Todas las apps",
      "portal.nav.governanca": "Governance TI",
      "portal.sections.label": "Secciones",
      "portal.gov.label": "Gobernanza",
      "portal.gov.admin": "Administración",
      "portal.lang.label": "Idioma",
      "portal.logout": "Salir",
      "portal.head.eyebrow": "Apps internas SuperFrio & Icestar",
      "portal.head.subtitle": "Selecciona una app abajo. Estás viendo solo lo que está habilitado para tu perfil.",
      "portal.search.placeholder": "Buscar app por nombre o descripción...",
      "greet.dawn": "Buenas noches",
      "greet.morning": "Buenos días",
      "greet.afternoon": "Buenas tardes",
      "greet.night": "Buenas noches",
      "role.admin": "Administrador",
      "role.user": "Usuario",
      "card.open.iframe": "Abrir aquí",
      "card.open.url": "Abrir en nueva pestaña",
      "badge.embed": "embed",
      "empty.title": "Ninguna app encontrada",
      "empty.search": "Prueba otro término de búsqueda.",
      "empty.noapps": "No tienes apps habilitadas en esta sección.",
      "confirm.logout": "¿Salir del hub?",
      "confirm.discard": "¿Descartar el formulario? Se perderá lo que escribiste.",
      "iframe.close": "Cerrar",
      "admin.back": "Volver al hub",
      "admin.title": "Gobernanza",
      "admin.subtitle": "Registro de secciones, apps, roles y usuarios. El toggle desactiva sin borrar (auditable).",
      "admin.tab.apps": "Apps",
      "admin.tab.secoes": "Secciones",
      "admin.tab.roles": "Roles",
      "admin.tab.usuarios": "Usuarios",
      "admin.apps.heading": "Apps registradas",
      "admin.apps.new": "+ Nueva app",
      "admin.secoes.heading": "Secciones",
      "admin.secoes.new": "+ Nueva sección",
      "admin.roles.heading": "Roles",
      "admin.roles.new": "+ Nuevo rol",
      "admin.usuarios.heading": "Usuarios",
      "admin.usuarios.new": "+ Nuevo usuario",
      "admin.modal.save": "Guardar",
      "admin.modal.saving": "Guardando...",
      "admin.modal.cancel": "Cancelar",
      "admin.err.load": "Error al cargar admin: ",
      "admin.err.generic": "Error: ",
      "admin.save.fail": "Error al guardar",
      "admin.col.app": "App",
      "admin.col.secao": "Sección",
      "admin.col.tipo": "Tipo",
      "admin.col.badge": "Badge",
      "admin.col.ordem": "Orden",
      "admin.col.status": "Estado",
      "admin.col.acoes": "Acciones",
      "admin.col.icone": "Icono",
      "admin.col.apps": "Apps",
      "admin.col.role": "Rol",
      "admin.col.appsLiberados": "Apps habilitadas",
      "admin.col.usuarios": "Usuarios",
      "admin.col.usuario": "Usuario",
      "admin.col.email": "Email",
      "admin.col.roles": "Roles",
      "admin.empty.apps": "Ninguna app registrada.",
      "admin.empty.secoes": "Ninguna sección registrada.",
      "admin.empty.roles": "Ningún rol registrado.",
      "admin.empty.usuarios": "Ningún usuario registrado.",
      "admin.act.edit": "Editar",
      "admin.act.deactivate": "Desactivar",
      "admin.act.reactivate": "Reactivar",
      "admin.act.password": "Contraseña",
      "admin.status.active.m": "activo",
      "admin.status.inactive.m": "inactivo",
      "admin.status.active.f": "activa",
      "admin.status.inactive.f": "inactiva",
      "admin.type.admin": "admin",
      "admin.type.user": "usuario",
      "admin.cantDeactivateSelf": "No puede desactivarse a sí mismo",
      "admin.noApps": "— sin apps —",
      "admin.dash": "—",
      "admin.new.app": "Nueva app",
      "admin.edit.app": "Editar app",
      "admin.new.secao": "Nueva sección",
      "admin.edit.secao": "Editar sección",
      "admin.new.role": "Nuevo rol",
      "admin.edit.role": "Editar rol",
      "admin.new.usuario": "Nuevo usuario",
      "admin.edit.usuario": "Editar usuario",
      "admin.pwd.title": "Restablecer contraseña",
      "admin.f.slug": "Slug",
      "admin.f.slugLocked": "(no editable)",
      "admin.f.ordem": "Orden",
      "admin.f.nome": "Nombre",
      "admin.f.nomePt": "Nombre (PT)",
      "admin.f.nomeEs": "Nombre (ES)",
      "admin.f.nomeEsHint": "Se muestra cuando el idioma del hub es Español. Vacío usa el nombre en Portugués.",
      "admin.f.descricao": "Descripción",
      "admin.f.descricaoPt": "Descripción (PT)",
      "admin.f.descricaoEs": "Descripción (ES)",
      "admin.f.icone": "Icono",
      "admin.f.iconeHint": "Icono mostrado en la barra lateral (warehouse, briefcase, etc).",
      "admin.f.secao": "Sección",
      "admin.f.url": "URL",
      "admin.f.tipoAcesso": "Tipo de acceso",
      "admin.f.tipoUrl": "URL — abre en nueva pestaña",
      "admin.f.tipoIframe": "Iframe — incrusta en el hub",
      "admin.f.badge": "Badge",
      "admin.f.noBadge": "— sin badge —",
      "admin.f.appsLiberados": "Apps habilitadas",
      "admin.f.noAppsYet": "Aún no hay apps registradas.",
      "admin.f.username": "Username",
      "admin.f.email": "Email",
      "admin.f.nomeCompleto": "Nombre completo",
      "admin.f.senhaInicial": "Contraseña inicial",
      "admin.f.senhaHint": "Mínimo 8 caracteres. El usuario puede cambiarla después.",
      "admin.f.isAdmin": "Es administrador (accede a gobernanza)",
      "admin.f.cantEditOwnBit": "no puede editar su propio bit",
      "admin.f.roles": "Roles",
      "admin.f.noRolesYet": "Aún no hay roles registrados.",
      "admin.f.none": "— ninguno —",
      "admin.pwd.newPass": "Nueva contraseña",
      "admin.pwd.hint": "Mínimo 8 caracteres. El usuario debe ingresar de nuevo tras el restablecimiento.",
      "admin.pwd.tooShort": "La contraseña debe tener al menos 8 caracteres",
      "portal.nav.changelog": "Novedades",
      "changelog.back": "Volver al hub",
      "changelog.eyebrow": "Portal SuperFrio & Icestar",
      "changelog.title": "Novedades",
      "changelog.subtitle": "Mejoras y correcciones del Portal SuperFrio & Icestar.",
      "changelog.filter.all": "Todo",
      "changelog.filter.feature": "Mejoras",
      "changelog.filter.fix": "Correcciones",
      "changelog.hint": "↔ desliza para ver la línea de tiempo completa · arriba = mejoras, abajo = correcciones",
      "changelog.tag.feature": "Mejora",
      "changelog.tag.fix": "Corrección",
      "changelog.today": "HOY",
      "changelog.err": "Error al cargar novedades",
      "changelog.empty": "Sin entradas registradas.",
    },
  };

  let current = localStorage.getItem(LANG_KEY);
  if (!SUPPORTED.includes(current)) current = "pt";

  function t(key) {
    const lang = DICT[current] ? current : "pt";
    return (DICT[lang] && DICT[lang][key]) || DICT.pt[key] || key;
  }

  function getLang() {
    return current;
  }

  /** Escolhe campo PT ou ES de um registro (fallback PT se ES vazio). */
  function pick(rec, field) {
    if (!rec) return "";
    if (current === "es") return rec[field + "_es"] || rec[field] || "";
    return rec[field] || "";
  }

  /** Aplica traduções nos elementos estáticos marcados no HTML. */
  function applyStatic(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    scope.querySelectorAll("[data-i18n-ph]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-ph")));
    });
    scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
      el.setAttribute("title", t(el.getAttribute("data-i18n-title")));
    });
  }

  function markActiveButtons() {
    document.querySelectorAll(".lang-switch button[data-lang]").forEach((b) => {
      b.classList.toggle("active", b.dataset.lang === current);
      b.setAttribute("aria-pressed", b.dataset.lang === current ? "true" : "false");
    });
  }

  function setLang(lang) {
    if (!SUPPORTED.includes(lang) || lang === current) {
      markActiveButtons();
      return;
    }
    current = lang;
    localStorage.setItem(LANG_KEY, lang);
    document.documentElement.lang = lang === "es" ? "es" : "pt-BR";
    markActiveButtons();
    applyStatic();
    // Avisa app.js / admin.js para re-renderizar conteúdo dinâmico.
    window.dispatchEvent(new CustomEvent("sf:langchange", { detail: { lang } }));
  }

  window.SF = window.SF || {};
  window.SF.i18n = { t, getLang, setLang, pick, applyStatic };

  document.addEventListener("DOMContentLoaded", () => {
    document.documentElement.lang = current === "es" ? "es" : "pt-BR";
    document.querySelectorAll(".lang-switch button[data-lang]").forEach((b) => {
      b.addEventListener("click", () => setLang(b.dataset.lang));
    });
    markActiveButtons();
    applyStatic();
  });
})();
