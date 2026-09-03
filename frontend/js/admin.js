/* Hub SuperFrio & Icestar — tela administrativa (apps, seções, roles, usuários) */
(() => {
  const SF = window.SF;
  if (!SF) {
    console.error("admin.js carregado antes de app.js");
    return;
  }
  const escapeHtml = SF.escapeHtml;
  const iconSvg = SF.iconSvg;
  const t = (k) => SF.i18n.t(k);

  const PASSWORD_MIN_LEN = 8;

  const ADM = {
    tab: "apps",
    secoes: [],
    apps: [],
    roles: [],
    usuarios: [],
    filiais: [],
    unidades_negocio: [],
    // Filtros por aba (texto + status + extras). Ver `filtroDe`.
    filtros: {},
    // Estrutura da matriz de acesso (app × ação), vinda de /api/admin/matriz.
    // Linhas = catálogo de apps (banco); colunas = vocabulário fixo (código).
    matriz: { acoes: [], secoes: [], descricoes: {}, orfas: [] },
    editing: null,   // {entity, record} ou null
  };

  const ACAO_VER = "ver";

  // Região por UF — mesmo mapa do seed das filiais (backend/projetos_ia/seed.py).
  // O Conciliador não tem região; aqui ela existe porque a tela de rollout
  // agrupa as filiais por ela.
  const REGIAO_POR_UF = {
    SP: "Sudeste", RJ: "Sudeste", MG: "Sudeste", ES: "Sudeste",
    PR: "Sul", SC: "Sul", RS: "Sul",
    MT: "Centro-Oeste", MS: "Centro-Oeste", GO: "Centro-Oeste", DF: "Centro-Oeste",
    AM: "Norte", PA: "Norte", AC: "Norte", RO: "Norte", RR: "Norte", AP: "Norte", TO: "Norte",
    BA: "Nordeste", PE: "Nordeste", CE: "Nordeste", MA: "Nordeste", PI: "Nordeste",
    RN: "Nordeste", PB: "Nordeste", SE: "Nordeste", AL: "Nordeste",
  };

  // Rótulo da ação: usa o i18n quando existe a chave, senão o nome vindo da API.
  function acaoLabel(acao) {
    const k = `admin.acao.${acao.slug}`;
    const traduzido = t(k);
    return traduzido === k ? acao.nome : traduzido;
  }

  // Vira true quando o usuário digita algo no formulário do modal. Usado para
  // pedir confirmação antes de descartar (ESC ou clique no fundo do overlay).
  let modalDirty = false;

  /* ---------- HTTP helper ---------- */
  async function api(method, path, body) {
    const opts = {
      method,
      headers: { Authorization: `Bearer ${SF.state.token}` },
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      // Sessão expirou enquanto a tela ficou ociosa: volta pro login em vez
      // de travar com um erro críptico de "credenciais inválidas".
      if (SF.logout) SF.logout(t("session.expired"));
      const e = new Error(t("session.expired"));
      e.sessionExpired = true;
      throw e;
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j && j.detail) detail = j.detail;
      } catch {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  /* ---------- Load all ---------- */
  async function loadAll() {
    const [secoes, apps, roles, usuarios, matriz, filiais, unidades] = await Promise.all([
      api("GET", "/api/admin/secoes"),
      api("GET", "/api/admin/apps"),
      api("GET", "/api/admin/roles"),
      api("GET", "/api/admin/usuarios"),
      api("GET", "/api/admin/matriz"),
      api("GET", "/api/admin/filiais"),
      api("GET", "/api/admin/unidades-negocio"),
    ]);
    ADM.secoes = secoes;
    ADM.apps = apps;
    ADM.roles = roles;
    ADM.usuarios = usuarios;
    ADM.matriz = matriz;
    ADM.filiais = filiais;
    ADM.unidades_negocio = unidades;
  }

  /* ---------- Open / close ---------- */
  async function openAdmin() {
    document.getElementById("screen-portal").classList.add("hidden");
    document.getElementById("screen-admin").classList.remove("hidden");
    setActiveTab(ADM.tab);
    try {
      await loadAll();
      renderActiveTab();
    } catch (e) {
      if (e.sessionExpired) return;
      alert(t("admin.err.load") + e.message);
    }
  }
  SF.openAdmin = openAdmin;

  function setActiveTab(tab) {
    ADM.tab = tab;
    document.querySelectorAll(".admin-tab").forEach((el) => {
      el.classList.toggle("active", el.dataset.tab === tab);
    });
    document.querySelectorAll(".admin-pane").forEach((el) => {
      el.classList.toggle("hidden", el.id !== `pane-${tab}`);
    });
  }

  function renderActiveTab() {
    if (ADM.tab === "apps") renderApps();
    else if (ADM.tab === "secoes") renderSecoes();
    else if (ADM.tab === "roles") renderRoles();
    else if (ADM.tab === "usuarios") renderUsuarios();
    else if (ADM.tab === "filiais") renderFiliais();
    else if (ADM.tab === "unidades-negocio") renderUnidadesNegocio();
    else if (ADM.tab === "auditoria") renderAuditoria();
  }

  /* ---------- Filtros: um componente para as 6 abas ----------
     Tudo client-side: `loadAll()` já traz as listas inteiras, então filtrar é
     instantâneo e não precisa de endpoint novo.

     O padrão é **status "ativos"**: a lista mostra só o que está em uso. Para um
     cadastro desativado não parecer apagado, a barra sempre informa "N de M" e
     mostra o botão Limpar quando algum filtro está ligado. */
  const STATUS_OPCOES = ["ativos", "inativos", "todos"];

  function filtroDe(entity) {
    if (!ADM.filtros[entity]) {
      ADM.filtros[entity] = { texto: "", status: "ativos", extras: {} };
    }
    return ADM.filtros[entity];
  }

  /* Monta a barra uma vez por aba. Não pode ser remontada a cada render: refazer
     o HTML do campo de busca a cada tecla digitada tiraria o foco dele. */
  function montarBarraFiltros(cont, entity, extras) {
    const f = filtroDe(entity);
    cont.innerHTML = `
      <input type="search" class="filtro-busca" value="${attr(f.texto)}"
             placeholder="${attr(t("admin.filtro.buscaPh"))}" aria-label="${attr(t("admin.filtro.buscaPh"))}">
      <select class="filtro-status" aria-label="${attr(t("admin.filtro.statusLabel"))}">
        ${STATUS_OPCOES.map(
          (s) =>
            `<option value="${s}" ${f.status === s ? "selected" : ""}>${escapeHtml(
              t("admin.filtro.status." + s)
            )}</option>`
        ).join("")}
      </select>
      ${extras
        .map(
          (e) =>
            `<select class="filtro-extra" data-key="${attr(e.key)}" aria-label="${attr(e.todos)}"></select>`
        )
        .join("")}
      <span class="filtro-contagem"></span>
      <button type="button" class="filtro-limpar hidden">${escapeHtml(t("admin.filtro.limpar"))}</button>`;

    cont.querySelector(".filtro-busca").addEventListener("input", (ev) => {
      f.texto = ev.target.value;
      renderActiveTab();
    });
    cont.querySelector(".filtro-status").addEventListener("change", (ev) => {
      f.status = ev.target.value;
      renderActiveTab();
    });
    cont.querySelectorAll(".filtro-extra").forEach((sel) => {
      sel.addEventListener("change", () => {
        f.extras[sel.dataset.key] = sel.value;
        renderActiveTab();
      });
    });
    cont.querySelector(".filtro-limpar").addEventListener("click", () => {
      ADM.filtros[entity] = { texto: "", status: "ativos", extras: {} };
      cont.querySelector(".filtro-busca").value = "";
      cont.querySelector(".filtro-status").value = "ativos";
      renderActiveTab();
    });
  }

  /* Opções dos combos vêm dos dados carregados, que mudam a cada save — então são
     refeitas a cada render. Se a opção escolhida deixou de existir, o filtro cai
     para "todos" sozinho em vez de esconder a lista inteira. */
  function atualizarExtras(cont, entity, extras) {
    const f = filtroDe(entity);
    extras.forEach((e) => {
      const sel = cont.querySelector(`.filtro-extra[data-key="${e.key}"]`);
      if (!sel) return;
      const escolhido = f.extras[e.key] || "";
      sel.innerHTML =
        `<option value="">${escapeHtml(e.todos)}</option>` +
        e.opcoes()
          .map(
            (o) =>
              `<option value="${attr(o.value)}" ${
                String(o.value) === escolhido ? "selected" : ""
              }>${escapeHtml(o.label)}</option>`
          )
          .join("");
      sel.value = escolhido;
      f.extras[e.key] = sel.value;
    });
  }

  function filtrarRows(entity, rows, texto, extras) {
    const f = filtroDe(entity);
    const termo = f.texto.trim().toLowerCase();
    return rows.filter((r) => {
      if (f.status === "ativos" && !r.ativo) return false;
      if (f.status === "inativos" && r.ativo) return false;
      if (termo && texto && String(texto(r)).toLowerCase().indexOf(termo) === -1) return false;
      return extras.every((e) => {
        const v = f.extras[e.key];
        return !v || e.casa(r, v);
      });
    });
  }

  function filtroLigado(entity) {
    const f = filtroDe(entity);
    return (
      !!f.texto.trim() ||
      f.status !== "ativos" ||
      Object.keys(f.extras).some((k) => f.extras[k])
    );
  }

  /* ---------- Render genérico de tabela ----------
     Monta a barra de filtros, thead + tbody e religa as ações de linha. Cada aba
     só descreve suas colunas (headers), como renderiza uma linha (rowHtml), o que
     a busca textual varre (texto) e seus filtros próprios (extras). */
  function renderTable(tbl, { entity, emptyMsg, headers, rows, rowHtml, texto, extras }) {
    const filtrosExtras = extras || [];
    const cont = document.getElementById(`filtros-${entity}`);
    if (cont) {
      if (cont.dataset.montado !== "1") {
        montarBarraFiltros(cont, entity, filtrosExtras);
        cont.dataset.montado = "1";
      }
      atualizarExtras(cont, entity, filtrosExtras);
    }

    const visiveis = filtrarRows(entity, rows, texto, filtrosExtras);

    if (cont) {
      cont.querySelector(".filtro-contagem").textContent =
        visiveis.length === rows.length
          ? `${rows.length}`
          : `${visiveis.length} ${t("admin.filtro.de")} ${rows.length}`;
      cont.querySelector(".filtro-limpar").classList.toggle("hidden", !filtroLigado(entity));
    }

    if (visiveis.length === 0) {
      // Distingue "não tem cadastro" de "o filtro escondeu tudo" — sem isso a
      // tela mente sobre o estado do banco.
      const msg = rows.length > 0 ? t("admin.filtro.vazio") : emptyMsg;
      tbl.innerHTML = `<tbody><tr><td>${escapeHtml(msg)}</td></tr></tbody>`;
      return;
    }
    tbl.innerHTML =
      `<thead><tr>${headers.join("")}</tr></thead>` +
      `<tbody>${visiveis.map(rowHtml).join("")}</tbody>`;
    bindRowActions(tbl, entity);
  }

  /* Valores distintos de um campo, para alimentar um combo de filtro. */
  function opcoesDistintas(lista, valor, rotulo) {
    const vistos = new Map();
    lista.forEach((item) => {
      const v = valor(item);
      if (v !== null && v !== undefined && v !== "" && !vistos.has(String(v))) {
        vistos.set(String(v), { value: String(v), label: rotulo(item) });
      }
    });
    return [...vistos.values()].sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
  }

  const th = (key) => `<th>${escapeHtml(t(key))}</th>`;
  const thRight = (key) => `<th style="width:160px;text-align:right">${escapeHtml(t(key))}</th>`;

  /* ---------- Render: APPS ---------- */
  function renderApps() {
    renderTable(document.getElementById("table-apps"), {
      entity: "apps",
      emptyMsg: t("admin.empty.apps"),
      rows: ADM.apps,
      texto: (a) => `${a.nome} ${a.slug} ${a.secao_nome} ${a.url || ""} ${a.tipo_acesso} ${a.tipo_conteudo}`,
      headers: [
        `<th style="width:42px"></th>`,
        th("admin.col.app"), th("admin.col.secao"), th("admin.col.conteudo"),
        th("admin.col.tipo"), th("admin.col.badge"), th("admin.col.ordem"),
        th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (a) => `<tr>
        <td><span class="app-card-icon" style="width:30px;height:30px">${iconSvg(a.icone || "default")}</span></td>
        <td>
          <div class="col-nome">${escapeHtml(a.nome)}</div>
          <div class="col-slug">${escapeHtml(a.slug)}</div>
        </td>
        <td>${escapeHtml(a.secao_nome)}</td>
        <td><span class="pill ${escapeHtml(a.tipo_conteudo)}">${escapeHtml(t(`admin.conteudo.${a.tipo_conteudo}`))}</span></td>
        <td><span class="pill ${a.tipo_acesso}">${escapeHtml(a.tipo_acesso)}</span></td>
        <td>${a.badge ? `<span class="pill ${a.badge.toLowerCase()}">${escapeHtml(a.badge)}</span>` : `<span class="col-meta">${escapeHtml(t("admin.dash"))}</span>`}</td>
        <td>${a.ordem}</td>
        <td><span class="pill ${a.ativo ? "on" : "off"}">${escapeHtml(a.ativo ? t("admin.status.active.m") : t("admin.status.inactive.m"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${a.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${a.id}">${escapeHtml(a.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`,
    });
  }

  /* ---------- Render: SEÇÕES ---------- */
  function renderSecoes() {
    renderTable(document.getElementById("table-secoes"), {
      entity: "secoes",
      emptyMsg: t("admin.empty.secoes"),
      rows: ADM.secoes,
      texto: (s) => `${s.nome} ${s.slug}`,
      headers: [
        th("admin.col.secao"), th("admin.col.icone"), th("admin.col.apps"),
        th("admin.col.ordem"), th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (s) => `<tr>
        <td>
          <div class="col-nome">${escapeHtml(s.nome)}</div>
          <div class="col-slug">${escapeHtml(s.slug)}</div>
        </td>
        <td><span class="col-meta">${escapeHtml(s.icone || t("admin.dash"))}</span></td>
        <td>${s.apps_count}</td>
        <td>${s.ordem}</td>
        <td><span class="pill ${s.ativo ? "on" : "off"}">${escapeHtml(s.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${s.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${s.id}">${escapeHtml(s.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`,
    });
  }

  /* ---------- Render: ROLES ---------- */
  function renderRoles() {
    renderTable(document.getElementById("table-roles"), {
      entity: "roles",
      emptyMsg: t("admin.empty.roles"),
      rows: ADM.roles,
      texto: (r) => `${r.nome} ${r.slug} ${(r.apps || []).join(" ")} ${(r.permissoes || []).join(" ")}`,
      headers: [
        th("admin.col.role"), th("admin.col.appsLiberados"), th("admin.col.permissoes"),
        th("admin.col.usuarios"), th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (r) => {
        const pills = r.apps.map((a) => `<span class="pill url">${escapeHtml(a)}</span>`).join(" ");
        // Permissões de ação ficam numa coluna própria, com pílula de outra cor:
        // é a distinção que a tela antiga não fazia (a role aparecia como "sem apps").
        const perms = (r.permissoes || [])
          .map((p) => `<span class="pill perm">${escapeHtml(p)}</span>`)
          .join(" ");
        return `<tr>
        <td>
          <div class="col-nome">${escapeHtml(r.nome)}</div>
          <div class="col-slug">${escapeHtml(r.slug)}</div>
        </td>
        <td><div class="pill-stack">${pills || `<span class="col-meta">${escapeHtml(t("admin.noApps"))}</span>`}</div></td>
        <td><div class="pill-stack">${perms || `<span class="col-meta">${escapeHtml(t("admin.noPerms"))}</span>`}</div></td>
        <td>${r.usuarios_count}</td>
        <td><span class="pill ${r.ativo ? "on" : "off"}">${escapeHtml(r.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${r.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${r.id}">${escapeHtml(r.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`;
      },
    });
  }

  /* ---------- Acesso efetivo de um usuário ----------
     Soma das roles ATIVAS — role desativada não conta, igual ao backend.
     Calculado aqui porque a lista de roles (com apps e permissões) já está
     carregada; evita um endpoint por usuário só para montar a coluna.

     Desde 21/08/2026 esta célula substitui a coluna "Roles": a lista de pílulas
     com o nome de cada role dizia quase a mesma coisa que esta coluna e deixava a
     tabela poluída. Os nomes continuam a um passo de distância — no `title` da
     pílula e na tela de edição do usuário. */
  function acessoEfetivoHtml(u) {
    if (u.is_admin) {
      return `<span class="pill admin-total">${escapeHtml(t("admin.acesso.adminTotal"))}</span>
              <div class="col-meta">${escapeHtml(t("admin.acesso.adminTudo"))}</div>`;
    }
    const ativas = ADM.roles.filter((r) => r.ativo && u.roles.indexOf(r.slug) !== -1);
    // Role que o usuário tem mas está desativada: não concede nada (igual ao
    // backend), e mesmo assim precisa ser visível — senão a pessoa "perdeu acesso"
    // sem explicação na tela.
    const inativas = u.roles.filter((slug) => !ativas.some((r) => r.slug === slug));

    const apps = new Set();
    const perms = new Set();
    ativas.forEach((r) => {
      (r.apps || []).forEach((a) => apps.add(a));
      (r.permissoes || []).forEach((p) => perms.add(p));
    });

    if (!ativas.length && !inativas.length) {
      return `<span class="col-meta">${escapeHtml(t("admin.acesso.semAcesso"))}</span>`;
    }

    const legenda = [
      ativas.length ? ativas.map((r) => r.slug).join(", ") : t("admin.acesso.semRoleAtiva"),
      inativas.length ? `${t("admin.acesso.roleInativa")}: ${inativas.join(", ")}` : "",
    ]
      .filter(Boolean)
      .join(" · ");

    const partes = [
      `<span class="pill role" title="${attr(legenda)}">${ativas.length} ${escapeHtml(
        ativas.length === 1 ? t("admin.acesso.role") : t("admin.acesso.roles")
      )}</span>`,
    ];
    if (apps.size) {
      partes.push(`<span class="pill url">${apps.size} ${escapeHtml(t("admin.acesso.apps"))}</span>`);
    }
    if (perms.size) {
      partes.push(`<span class="pill perm">${perms.size} ${escapeHtml(t("admin.acesso.perms"))}</span>`);
    }
    if (inativas.length) {
      partes.push(
        `<span class="pill off" title="${attr(inativas.join(", "))}">${inativas.length} ${escapeHtml(
          t("admin.acesso.inativas")
        )}</span>`
      );
    }
    return `<div class="pill-stack">${partes.join(" ")}</div>`;
  }

  /* ---------- Render: USUÁRIOS ---------- */
  function renderUsuarios() {
    renderTable(document.getElementById("table-usuarios"), {
      entity: "usuarios",
      emptyMsg: t("admin.empty.usuarios"),
      rows: ADM.usuarios,
      texto: (u) =>
        `${u.nome || ""} ${u.username} ${u.email || ""} ${u.filial_codigo || ""} ${
          u.filial_nome || ""
        } ${u.roles.join(" ")}`,
      extras: [
        {
          key: "filial",
          todos: t("admin.filtro.todasFiliais"),
          // Só as filiais que aparecem em algum cadastro — combo de 60 itens em que
          // 58 não filtram nada é pior que não ter filtro. "-" acha quem está sem
          // lotação, que hoje é a maioria dos cadastros antigos.
          opcoes: () =>
            opcoesDistintas(
              ADM.usuarios,
              (u) => (u.filial_id ? String(u.filial_id) : "-"),
              (u) =>
                u.filial_id
                  ? `${u.filial_codigo || ""} · ${u.filial_nome || ""}`.trim()
                  : t("admin.filtro.semFilial")
            ),
          casa: (u, v) => (v === "-" ? !u.filial_id : String(u.filial_id) === v),
        },
        {
          key: "role",
          todos: t("admin.filtro.todasRoles"),
          opcoes: () => ADM.roles.map((r) => ({ value: r.slug, label: r.nome })),
          casa: (u, v) => u.roles.indexOf(v) !== -1,
        },
      ],
      headers: [
        th("admin.col.usuario"), th("admin.col.acesso"),
        th("admin.col.tipo"), th("admin.col.status"),
        `<th style="width:220px;text-align:right">${escapeHtml(t("admin.col.acoes"))}</th>`,
      ],
      rowHtml: (u) => {
        const meEu = SF.state.user && SF.state.user.username === u.username;
        return `<tr>
        <td>
          <div class="col-nome">${escapeHtml(u.nome || u.username)}</div>
          <div class="col-slug">${escapeHtml(u.username)}</div>
          <div class="col-meta">${escapeHtml(u.email || t("admin.dash"))}</div>
          <div class="col-meta">${escapeHtml(
            u.filial_codigo ? `${u.filial_codigo} · ${u.filial_nome}` : t("admin.semFilial")
          )}</div>
        </td>
        <td>${acessoEfetivoHtml(u)}</td>
        <td>${u.is_admin ? `<span class="pill admin">${escapeHtml(t("admin.type.admin"))}</span>` : `<span class="col-meta">${escapeHtml(t("admin.type.user"))}</span>`}</td>
        <td><span class="pill ${u.ativo ? "on" : "off"}">${escapeHtml(u.ativo ? t("admin.status.active.m") : t("admin.status.inactive.m"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${u.id}">${escapeHtml(t("admin.act.edit"))}</button>
          ${
            // Quem entra pela Microsoft não tem senha local pra redefinir.
            u.auth_source === "ad"
              ? ""
              : `<button data-act="passwd" data-id="${u.id}">${escapeHtml(t("admin.act.password"))}</button>`
          }
          <button class="danger" data-act="toggle" data-id="${u.id}" ${meEu ? `disabled title="${escapeHtml(t("admin.cantDeactivateSelf"))}"` : ""}>${escapeHtml(u.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`;
      },
    });
  }

  /* ---------- Render: FILIAIS ---------- */
  function renderFiliais() {
    renderTable(document.getElementById("table-filiais"), {
      entity: "filiais",
      emptyMsg: t("admin.empty.filiais"),
      rows: ADM.filiais,
      texto: (f) =>
        `${f.codigo || ""} ${f.nome} ${f.cidade || ""} ${f.uf || ""} ${f.regiao} ${
          f.responsavel || ""
        } ${f.unidade_negocio_nome || ""}`,
      extras: [
        {
          key: "regiao",
          todos: t("admin.filtro.todasRegioes"),
          opcoes: () => opcoesDistintas(ADM.filiais, (f) => f.regiao, (f) => f.regiao),
          casa: (f, v) => f.regiao === v,
        },
        {
          key: "bu",
          todos: t("admin.filtro.todasBu"),
          opcoes: () =>
            opcoesDistintas(
              ADM.filiais,
              (f) => f.unidade_negocio_nome || "-",
              (f) => f.unidade_negocio_nome || t("admin.filtro.semBu")
            ),
          // "-" é o marcador de "sem B.U": filtrar por ele é um caso de uso real
          // (achar filial que ninguém vinculou ainda).
          casa: (f, v) => (v === "-" ? !f.unidade_negocio_nome : f.unidade_negocio_nome === v),
        },
      ],
      headers: [
        th("admin.col.codigo"), th("admin.col.filial"), th("admin.col.cidade"),
        th("admin.col.uf"), th("admin.col.regiao"), th("admin.col.bu"),
        th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (f) => `<tr>
        <td>${escapeHtml(f.codigo || t("admin.dash"))}</td>
        <td><div class="col-nome">${escapeHtml(f.nome)}</div></td>
        <td>${escapeHtml(f.cidade || t("admin.dash"))}</td>
        <td>${escapeHtml(f.uf || t("admin.dash"))}</td>
        <td>${escapeHtml(f.regiao)}</td>
        <td>${escapeHtml(f.unidade_negocio_nome || t("admin.dash"))}</td>
        <td><span class="pill ${f.ativo ? "on" : "off"}">${escapeHtml(f.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${f.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${f.id}">${escapeHtml(f.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`,
    });
  }

  /* ---------- Render: UNIDADES DE NEGÓCIO (B.U) ---------- */
  function renderUnidadesNegocio() {
    renderTable(document.getElementById("table-unidades-negocio"), {
      entity: "unidades-negocio",
      emptyMsg: t("admin.empty.un"),
      rows: ADM.unidades_negocio,
      texto: (u) => `${u.nome} ${u.responsavel || ""}`,
      headers: [
        th("admin.col.bu"), th("admin.col.responsavel"), th("admin.col.filiaisVinculadas"),
        th("admin.col.status"), thRight("admin.col.acoes"),
      ],
      rowHtml: (u) => `<tr>
        <td><div class="col-nome">${escapeHtml(u.nome)}</div></td>
        <td>${escapeHtml(u.responsavel || t("admin.dash"))}</td>
        <td>${u.filiais}</td>
        <td><span class="pill ${u.ativo ? "on" : "off"}">${escapeHtml(u.ativo ? t("admin.status.active.f") : t("admin.status.inactive.f"))}</span></td>
        <td class="actions"><div class="actions-row">
          <button data-act="edit" data-id="${u.id}">${escapeHtml(t("admin.act.edit"))}</button>
          <button class="danger" data-act="toggle" data-id="${u.id}">${escapeHtml(u.ativo ? t("admin.act.deactivate") : t("admin.act.reactivate"))}</button>
        </div></td>
      </tr>`,
    });
  }

  /* ---------- Row actions ---------- */
  function bindRowActions(tableEl, entity) {
    tableEl.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = parseInt(btn.dataset.id, 10);
        const act = btn.dataset.act;
        if (act === "edit") {
          const rec = findRecord(entity, id);
          if (rec) openModal(entity, rec);
        } else if (act === "toggle") {
          try {
            await api("POST", `/api/admin/${entity}/${id}/toggle`);
            await loadAll();
            renderActiveTab();
          } catch (e) {
            if (e.sessionExpired) return;
            alert(t("admin.err.generic") + e.message);
          }
        } else if (act === "passwd") {
          openPasswordModal(id);
        }
      });
    });
  }

  function findRecord(entity, id) {
    const map = {
      apps: ADM.apps, secoes: ADM.secoes, roles: ADM.roles, usuarios: ADM.usuarios,
      filiais: ADM.filiais, "unidades-negocio": ADM.unidades_negocio,
    };
    return (map[entity] || []).find((r) => r.id === id);
  }

  /* ---------- Modal: formulários ---------- */
  function openModal(entity, record) {
    ADM.editing = { entity, record, mode: "form" };
    const isNew = !record;
    const titles = {
      apps: isNew ? t("admin.new.app") : `${t("admin.edit.app")} — ${record.nome}`,
      secoes: isNew ? t("admin.new.secao") : `${t("admin.edit.secao")} — ${record.nome}`,
      roles: isNew ? t("admin.new.role") : `${t("admin.edit.role")} — ${record.nome}`,
      usuarios: isNew ? t("admin.new.usuario") : `${t("admin.edit.usuario")} — ${record.username}`,
      filiais: isNew ? t("admin.new.filial") : `${t("admin.edit.filial")} — ${record.nome}`,
      "unidades-negocio": isNew ? t("admin.new.un") : `${t("admin.edit.un")} — ${record.nome}`,
    };
    const form = document.getElementById("modal-form");
    document.getElementById("modal-title").textContent = titles[entity];
    form.innerHTML = buildForm(entity, record);
    // A matriz precisa de mais largura que os formulários comuns.
    document.querySelector("#modal-overlay .modal")
      .classList.toggle("modal--wide", entity === "roles");
    if (entity === "roles") wireMatriz(form);
    document.getElementById("modal-error").textContent = "";
    modalDirty = false;
    document.getElementById("modal-overlay").classList.add("visible");
    setTimeout(() => {
      const first = document.querySelector("#modal-form input,#modal-form select,#modal-form textarea");
      if (first) first.focus();
    }, 30);
  }

  function openPasswordModal(userId) {
    const u = findRecord("usuarios", userId);
    if (!u) return;
    ADM.editing = { entity: "usuarios", record: u, mode: "password" };
    document.getElementById("modal-title").textContent = `${t("admin.pwd.title")} — ${u.username}`;
    document.getElementById("modal-form").innerHTML = `
      <div class="form-field">
        <label>${escapeHtml(t("admin.pwd.newPass"))}</label>
        <input name="senha" type="password" required minlength="${PASSWORD_MIN_LEN}" autocomplete="new-password">
        <div class="field-hint">${escapeHtml(t("admin.pwd.hint"))}</div>
      </div>
    `;
    document.getElementById("modal-error").textContent = "";
    modalDirty = false;
    document.getElementById("modal-overlay").classList.add("visible");
  }

  function closeModal() {
    document.getElementById("modal-overlay").classList.remove("visible");
    ADM.editing = null;
    modalDirty = false;
  }

  // Fechamento "leve" (ESC / clique no fundo): se o formulário já foi mexido,
  // pede confirmação para não perder o preenchimento sem querer. X e Cancelar
  // são gestos explícitos e continuam fechando direto (chamam closeModal).
  function requestClose() {
    if (modalDirty && !confirm(t("confirm.discard"))) return;
    closeModal();
  }

  /* ---------- Form builders ---------- */
  function buildForm(entity, r) {
    if (entity === "secoes") return formSecao(r);
    if (entity === "apps") return formApp(r);
    if (entity === "roles") return formRole(r);
    if (entity === "usuarios") return formUsuario(r);
    if (entity === "filiais") return formFilial(r);
    if (entity === "unidades-negocio") return formUnidadeNegocio(r);
    return "";
  }

  // Opções de B.U: ativas + a que já está vinculada (mesmo inativa), pra editar
  // uma filial não desfazer o vínculo sem querer.
  function buOptions(atual) {
    const disponiveis = ADM.unidades_negocio.filter((u) => u.ativo || u.id === atual);
    return (
      `<option value="">${escapeHtml(t("admin.f.semBu"))}</option>` +
      disponiveis
        .map((u) => {
          const rotulo = u.ativo ? u.nome : `${u.nome} ${t("admin.f.buInativa")}`;
          return `<option value="${u.id}" ${u.id === atual ? "selected" : ""}>${escapeHtml(rotulo)}</option>`;
        })
        .join("")
    );
  }

  function formFilial(r) {
    return `
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.codigo"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="codigo" required maxlength="20" value="${attr(r && r.codigo)}" ${r ? "disabled" : ""} placeholder="ex: 1020">
          ${r ? "" : `<div class="field-hint">${escapeHtml(t("admin.f.codigoHint"))}</div>`}
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.col.filial"))}</label>
          <input name="nome" required value="${attr(r && r.nome)}" placeholder="ex: RMSPI">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.cidade"))}</label>
          <input name="cidade" value="${attr(r && r.cidade)}" placeholder="ex: São Paulo">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.uf"))}</label>
          <input name="uf" value="${attr(r && r.uf)}" maxlength="4" placeholder="ex: SP">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.regiao"))}</label>
          <input name="regiao" required value="${attr(r && r.regiao)}" placeholder="ex: Sudeste">
          <div class="field-hint">${escapeHtml(t("admin.f.regiaoHint"))}</div>
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.responsavel"))}</label>
          <input name="responsavel" value="${attr(r && r.responsavel)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.bu"))}</label>
        <select name="unidade_negocio_id">${buOptions(r && r.unidade_negocio_id)}</select>
      </div>
    `;
  }

  function formUnidadeNegocio(r) {
    return `
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.buNome"))}</label>
        <input name="nome" required maxlength="120" value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.responsavel"))}</label>
        <input name="responsavel" maxlength="120" value="${attr(r && r.responsavel)}">
      </div>
      <div class="field-hint">${escapeHtml(t("admin.f.buHint"))}</div>
    `;
  }

  function attr(v) {
    return escapeHtml(v == null ? "" : String(v));
  }

  function formSecao(r) {
    return `
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: tecnologia">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.ordem"))}</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomePt"))}</label>
          <input name="nome" required value="${attr(r && r.nome)}">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomeEs"))}</label>
          <input name="nome_es" value="${attr(r && r.nome_es)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoPt"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoEs"))}</label>
        <textarea name="descricao_es">${attr(r && r.descricao_es)}</textarea>
        <div class="field-hint">${escapeHtml(t("admin.f.nomeEsHint"))}</div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.icone"))}</label>
        <select name="icone">${iconOptions(r && r.icone)}</select>
        <div class="field-hint">${escapeHtml(t("admin.f.iconeHint"))}</div>
      </div>
    `;
  }

  function formApp(r) {
    const secaoOpts = ADM.secoes
      .map((s) => `<option value="${s.id}" ${r && r.secao_id === s.id ? "selected" : ""}>${escapeHtml(s.nome)}</option>`)
      .join("");
    return `
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: faq-blueyonder">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.ordem"))}</label>
          <input name="ordem" type="number" value="${attr(r ? r.ordem : 0)}" step="1">
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomePt"))}</label>
          <input name="nome" required value="${attr(r && r.nome)}">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomeEs"))}</label>
          <input name="nome_es" value="${attr(r && r.nome_es)}">
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoPt"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricaoEs"))}</label>
        <textarea name="descricao_es">${attr(r && r.descricao_es)}</textarea>
        <div class="field-hint">${escapeHtml(t("admin.f.nomeEsHint"))}</div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.secao"))}</label>
          <select name="secao_id" required>${secaoOpts}</select>
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.icone"))}</label>
          <select name="icone">${iconOptions(r && r.icone)}</select>
        </div>
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.url"))}</label>
        <input name="url" required value="${attr(r && r.url)}" placeholder="https://...">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.tipoConteudo"))}</label>
        <select name="tipo_conteudo">
          <option value="sistema" ${(!r || r.tipo_conteudo !== "indicador") ? "selected" : ""}>${escapeHtml(t("admin.f.conteudoSistema"))}</option>
          <option value="indicador" ${r && r.tipo_conteudo === "indicador" ? "selected" : ""}>${escapeHtml(t("admin.f.conteudoIndicador"))}</option>
        </select>
        <div class="field-hint">${escapeHtml(t("admin.f.conteudoHint"))}</div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.tipoAcesso"))}</label>
          <select name="tipo_acesso">
            <option value="url" ${(!r || r.tipo_acesso === "url") ? "selected" : ""}>${escapeHtml(t("admin.f.tipoUrl"))}</option>
            <option value="iframe" ${r && r.tipo_acesso === "iframe" ? "selected" : ""}>${escapeHtml(t("admin.f.tipoIframe"))}</option>
          </select>
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.badge"))}</label>
          <select name="badge">
            <option value="" ${!r || !r.badge ? "selected" : ""}>${escapeHtml(t("admin.f.noBadge"))}</option>
            <option value="NEW" ${r && r.badge === "NEW" ? "selected" : ""}>NEW</option>
            <option value="BETA" ${r && r.badge === "BETA" ? "selected" : ""}>BETA</option>
          </select>
        </div>
      </div>
    `;
  }

  /* ---------- Matriz de acesso (app × ação) ----------
     Substitui a lista solta de "apps liberados". A coluna `ver` é o antigo grant
     role→app; as demais são as permissões declaradas em código pelos módulos.
     Célula "—" = o app não tem aquela ação (não é checkbox desmarcado). */
  function matrizHtml(marcados) {
    const acoes = ADM.matriz.acoes || [];
    const secoes = ADM.matriz.secoes || [];
    if (!acoes.length || !secoes.length) {
      return `<fieldset>
        <legend>${escapeHtml(t("admin.f.matriz"))}</legend>
        <div class="col-meta">${escapeHtml(t("admin.f.noAppsYet"))}</div>
      </fieldset>`;
    }

    const thead = acoes
      .map(
        (a) => `<th data-col="${escapeHtml(a.slug)}">
          <span class="mtx-hname">${escapeHtml(acaoLabel(a))}</span>
          <input type="checkbox" class="mtx-all" data-acao="${escapeHtml(a.slug)}"
                 aria-label="${escapeHtml(acaoLabel(a))}">
        </th>`
      )
      .join("");

    const corpo = secoes
      .map((s) => {
        const linhas = s.apps
          .map((app) => {
            const cells = acoes
              .map((a) => {
                const key = `${app.slug}:${a.slug}`;
                if (app.acoes.indexOf(a.slug) === -1) {
                  return `<td data-col="${escapeHtml(a.slug)}"><span class="mtx-na">—</span></td>`;
                }
                const desc = (ADM.matriz.descricoes || {})[key] || "";
                return `<td data-col="${escapeHtml(a.slug)}">
                  <input type="checkbox" class="mtx-cb"
                         data-app="${escapeHtml(app.slug)}" data-acao="${escapeHtml(a.slug)}"
                         ${marcados.has(key) ? "checked" : ""}
                         title="${escapeHtml(desc)}"
                         aria-label="${escapeHtml(acaoLabel(a))} — ${escapeHtml(app.nome)}">
                </td>`;
              })
              .join("");
            const busca = `${app.nome} ${app.slug}`.toLowerCase();
            return `<tr data-secao="${escapeHtml(s.slug)}" data-busca="${escapeHtml(busca)}">
              <th class="mtx-app">
                <span class="col-nome">${escapeHtml(app.nome)}</span>
                <span class="col-slug">${escapeHtml(app.slug)}</span>
              </th>${cells}
            </tr>`;
          })
          .join("");
        return `<tr class="mtx-grp" data-grp="${escapeHtml(s.slug)}">
          <th colspan="${acoes.length + 1}">
            <span class="mtx-gname">${escapeHtml(s.nome)}</span>
            <button type="button" class="mtx-gall" data-secao="${escapeHtml(s.slug)}">${escapeHtml(t("admin.f.matrizSecaoAll"))}</button>
          </th>
        </tr>${linhas}`;
      })
      .join("");

    const orfas = (ADM.matriz.orfas || []).length
      ? `<div class="mtx-orfas">
           ${escapeHtml(t("admin.f.matrizOrfas"))}
           ${ADM.matriz.orfas.map((o) => `<code>${escapeHtml(o.slug)}</code>`).join(" ")}
         </div>`
      : "";

    return `<fieldset class="mtx-fs">
      <legend>${escapeHtml(t("admin.f.matriz"))}</legend>
      <div class="field-hint">${escapeHtml(t("admin.f.matrizHint"))}</div>
      <input type="search" class="mtx-filtro" placeholder="${escapeHtml(t("admin.f.matrizFiltro"))}"
             aria-label="${escapeHtml(t("admin.f.matrizFiltro"))}">
      <div class="mtx-wrap">
        <table class="mtx">
          <thead><tr><th class="mtx-app">${escapeHtml(t("admin.f.matrizApp"))}</th>${thead}</tr></thead>
          <tbody>${corpo}</tbody>
        </table>
      </div>
      <div class="mtx-regra" hidden>${escapeHtml(t("admin.f.matrizVerAuto"))}</div>
      ${orfas}
    </fieldset>`;
  }

  /* Liga os comportamentos da matriz depois que o innerHTML do modal é montado. */
  function wireMatriz(form) {
    const tabela = form.querySelector("table.mtx");
    if (!tabela) return;
    const regra = form.querySelector(".mtx-regra");
    const cbDe = (app, acao) =>
      tabela.querySelector(`.mtx-cb[data-app="${app}"][data-acao="${acao}"]`);

    function avisarRegra() {
      if (!regra) return;
      regra.hidden = false;
      clearTimeout(regra._t);
      regra._t = setTimeout(() => { regra.hidden = true; }, 5000);
    }

    // Liberar uma ação num app que a pessoa não pode abrir seria permissão morta:
    // marcar qualquer ação marca `ver`; desmarcar `ver` limpa a linha.
    function aplicarRegraVer(app, acao, ligado) {
      if (acao !== ACAO_VER && ligado) {
        const ver = cbDe(app, ACAO_VER);
        if (ver && !ver.checked) { ver.checked = true; return true; }
      }
      if (acao === ACAO_VER && !ligado) {
        tabela.querySelectorAll(`.mtx-cb[data-app="${app}"]`).forEach((c) => {
          if (c.dataset.acao !== ACAO_VER) c.checked = false;
        });
      }
      return false;
    }

    tabela.addEventListener("change", (ev) => {
      const cb = ev.target;
      if (cb.classList.contains("mtx-cb")) {
        if (aplicarRegraVer(cb.dataset.app, cb.dataset.acao, cb.checked)) avisarRegra();
        return;
      }
      if (cb.classList.contains("mtx-all")) {
        const acao = cb.dataset.acao;
        tabela.querySelectorAll(`.mtx-cb[data-acao="${acao}"]`).forEach((c) => {
          if (c.closest("tr").hidden) return;   // respeita o filtro
          c.checked = cb.checked;
          aplicarRegraVer(c.dataset.app, acao, cb.checked);
        });
      }
    });

    tabela.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".mtx-gall");
      if (!btn) return;
      tabela.querySelectorAll(`tr[data-secao="${btn.dataset.secao}"]`).forEach((tr) => {
        if (tr.hidden) return;
        tr.querySelectorAll(".mtx-cb").forEach((c) => { c.checked = true; });
      });
      // marcar em massa também suja o formulário (o listener de input não pega isto)
      form.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Destaca a coluna sob o cursor — sem isso é fácil errar de coluna na horizontal.
    function marcarColuna(acao, ligado) {
      tabela.querySelectorAll(`[data-col="${acao}"]`).forEach((el) => {
        el.classList.toggle("on-col", ligado);
      });
    }
    tabela.addEventListener("mouseover", (ev) => {
      const c = ev.target.closest("[data-col]");
      if (c) marcarColuna(c.dataset.col, true);
    });
    tabela.addEventListener("mouseout", (ev) => {
      const c = ev.target.closest("[data-col]");
      if (c) marcarColuna(c.dataset.col, false);
    });

    const filtro = form.querySelector(".mtx-filtro");
    if (filtro) {
      filtro.addEventListener("input", () => {
        const termo = filtro.value.trim().toLowerCase();
        tabela.querySelectorAll("tbody tr[data-busca]").forEach((tr) => {
          tr.hidden = !!termo && tr.dataset.busca.indexOf(termo) === -1;
        });
        tabela.querySelectorAll("tbody tr.mtx-grp").forEach((tr) => {
          const visiveis = tabela.querySelectorAll(
            `tr[data-secao="${tr.dataset.grp}"]:not([hidden])`
          ).length;
          tr.hidden = visiveis === 0;
        });
      });
    }
  }

  function formRole(r) {
    // Estado inicial da grade: `ver` vem de role.apps, o resto de role.permissoes.
    const marcados = new Set();
    ((r && r.apps) || []).forEach((a) => marcados.add(`${a}:${ACAO_VER}`));
    ((r && r.permissoes) || []).forEach((p) => marcados.add(p));
    return `
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.slug"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
        <input name="slug" required value="${attr(r && r.slug)}" ${r ? "disabled" : ""} placeholder="ex: armazem-full">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.nome"))}</label>
        <input name="nome" required value="${attr(r && r.nome)}">
      </div>
      <div class="form-field">
        <label>${escapeHtml(t("admin.f.descricao"))}</label>
        <textarea name="descricao">${attr(r && r.descricao)}</textarea>
      </div>
      ${matrizHtml(marcados)}
    `;
  }

  function formUsuario(r) {
    const selected = new Set(r ? r.roles : []);
    const roleChecks = ADM.roles
      .map(
        (rl) => `
        <label class="check-row">
          <input type="checkbox" name="roles" value="${escapeHtml(rl.slug)}" ${selected.has(rl.slug) ? "checked" : ""}>
          <span>${escapeHtml(rl.nome)}</span>
          <span class="meta">${escapeHtml(rl.slug)} · ${rl.apps.length} app(s)</span>
        </label>`
      )
      .join("");

    const meEu = r && SF.state.user && SF.state.user.username === r.username;
    // Filial ativa + a que já está gravada (mesmo inativa) — trocar a lotação de
    // alguém não pode depender de a filial dele continuar ativa.
    const filiais = ADM.filiais
      .filter((f) => f.ativo || (r && r.filial_id === f.id))
      .map(
        (f) => `<option value="${f.id}" ${r && r.filial_id === f.id ? "selected" : ""}>
                  ${escapeHtml(f.codigo ? `${f.codigo} · ${f.nome}` : f.nome)}
                </option>`
      )
      .join("");
    // Cadastro novo é sempre acesso Microsoft (decisão 21/08/2026): a pessoa não
    // tem senha local, entra pelo botão do Entra e o e-mail é o que casa com o
    // token. Usuário local sobrevive apenas como acesso de emergência já criado —
    // a API ainda aceita criar um, esta tela é que não oferece.
    return `
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.username"))} ${r ? escapeHtml(t("admin.f.slugLocked")) : ""}</label>
          <input name="username" required value="${attr(r && r.username)}" ${r ? "disabled" : ""} placeholder="ex: jose.silva">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.email"))} ${escapeHtml(t("admin.f.obrigatorio"))}</label>
          <input name="email" type="email" required value="${attr(r && r.email)}" placeholder="jose.silva@superfrio.com.br">
          <div class="field-hint">${escapeHtml(t("admin.f.emailHint"))}</div>
        </div>
      </div>
      <div class="row-2">
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.nomeCompleto"))}</label>
          <input name="nome" value="${attr(r && r.nome)}">
        </div>
        <div class="form-field">
          <label>${escapeHtml(t("admin.f.filial"))}</label>
          <select name="filial_id">
            <option value="">${escapeHtml(t("admin.f.semFilial"))}</option>
            ${filiais}
          </select>
        </div>
      </div>
      ${r ? "" : `
      <div class="field-hint acesso-hint">${escapeHtml(t("admin.f.acessoMicrosoft"))}</div>`}
      <div class="form-field">
        <label class="check-row" style="margin:0">
          <input type="checkbox" name="is_admin" ${r && r.is_admin ? "checked" : ""} ${meEu ? "disabled" : ""}>
          <span>${escapeHtml(t("admin.f.isAdmin"))}</span>
          ${meEu ? `<span class="meta">${escapeHtml(t("admin.f.cantEditOwnBit"))}</span>` : ""}
        </label>
      </div>
      <fieldset>
        <legend>${escapeHtml(t("admin.f.roles"))}</legend>
        ${roleChecks || `<div class="col-meta">${escapeHtml(t("admin.f.noRolesYet"))}</div>`}
      </fieldset>
    `;
  }

  function iconOptions(current) {
    const opts = [
      "", "warehouse", "briefcase", "book", "scale", "chat", "cart", "document",
      "truck", "radar", "chip", "network", "presentation", "chart",
    ];
    return opts
      .map((o) => `<option value="${o}" ${o === (current || "") ? "selected" : ""}>${o || t("admin.f.none")}</option>`)
      .join("");
  }

  /* ---------- Submit ---------- */
  async function submitModal() {
    if (!ADM.editing) return;
    const { entity, record, mode } = ADM.editing;
    const form = document.getElementById("modal-form");
    const errEl = document.getElementById("modal-error");
    const saveBtn = document.getElementById("modal-save");
    errEl.textContent = "";
    saveBtn.disabled = true;
    saveBtn.textContent = t("admin.modal.saving");

    try {
      if (mode === "password") {
        const senha = form.querySelector("[name='senha']").value;
        if (!senha || senha.length < PASSWORD_MIN_LEN) throw new Error(t("admin.pwd.tooShort"));
        await api("POST", `/api/admin/usuarios/${record.id}/password`, { senha });
      } else {
        const body = collectForm(entity, form, record);
        if (record) {
          await api("PATCH", `/api/admin/${entity}/${record.id}`, body);
        } else {
          await api("POST", `/api/admin/${entity}`, body);
        }
      }
      closeModal();
      await loadAll();
      renderActiveTab();
    } catch (e) {
      if (e.sessionExpired) return;
      errEl.textContent = e.message || t("admin.save.fail");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = t("admin.modal.save");
    }
  }

  function collectForm(entity, form, record) {
    const fd = new FormData(form);
    const isNew = !record;
    const out = {};

    if (entity === "secoes") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.nome_es = (fd.get("nome_es") || "").trim() || null;
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.descricao_es = (fd.get("descricao_es") || "").trim() || null;
      out.icone = (fd.get("icone") || "").trim() || null;
      out.ordem = parseInt(fd.get("ordem") || "0", 10) || 0;
    } else if (entity === "apps") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.nome_es = (fd.get("nome_es") || "").trim() || null;
      out.descricao = (fd.get("descricao") || "").trim() || null;
      out.descricao_es = (fd.get("descricao_es") || "").trim() || null;
      out.icone = (fd.get("icone") || "").trim() || null;
      out.secao_id = parseInt(fd.get("secao_id"), 10);
      out.url = (fd.get("url") || "").trim();
      out.tipo_acesso = fd.get("tipo_acesso") || "url";
      out.tipo_conteudo = fd.get("tipo_conteudo") || "sistema";
      out.badge = (fd.get("badge") || "").trim() || null;
      out.ordem = parseInt(fd.get("ordem") || "0", 10) || 0;
    } else if (entity === "roles") {
      if (isNew) out.slug = (fd.get("slug") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.descricao = (fd.get("descricao") || "").trim() || null;
      // A grade é uma coisa só na tela, mas duas na API: `ver` grava em role_apps,
      // as demais ações em role_permissoes.
      const apps = [];
      const permissoes = [];
      form.querySelectorAll(".mtx-cb:checked").forEach((cb) => {
        if (cb.dataset.acao === ACAO_VER) apps.push(cb.dataset.app);
        else permissoes.push(`${cb.dataset.app}:${cb.dataset.acao}`);
      });
      out.apps = apps;
      out.permissoes = permissoes;
    } else if (entity === "usuarios") {
      // Sem `senha`: a API interpreta a ausência como acesso Microsoft e grava
      // auth_source='ad' sem senha local nenhuma.
      if (isNew) out.username = (fd.get("username") || "").trim();
      out.nome = (fd.get("nome") || "").trim() || null;
      out.email = (fd.get("email") || "").trim() || null;
      out.filial_id = parseInt(fd.get("filial_id"), 10) || null;
      out.is_admin = !!fd.get("is_admin");
      out.roles = fd.getAll("roles");
    } else if (entity === "filiais") {
      // `codigo` só na criação: é a chave de negócio e a API não aceita mudá-lo.
      if (isNew) out.codigo = (fd.get("codigo") || "").trim();
      out.nome = (fd.get("nome") || "").trim();
      out.cidade = (fd.get("cidade") || "").trim() || null;
      out.uf = (fd.get("uf") || "").trim().toUpperCase() || null;
      out.regiao = (fd.get("regiao") || "").trim();
      out.responsavel = (fd.get("responsavel") || "").trim() || null;
      const bu = (fd.get("unidade_negocio_id") || "").trim();
      out.unidade_negocio_id = bu ? parseInt(bu, 10) : null;
    } else if (entity === "unidades-negocio") {
      out.nome = (fd.get("nome") || "").trim();
      out.responsavel = (fd.get("responsavel") || "").trim() || null;
    }
    return out;
  }

  /* ---------- Render: AUDITORIA ----------
     Diferente das outras 6 abas: não vem do `loadAll()` (a tabela cresce sem
     teto), busca sob demanda com paginação/filtros server-side — cada
     `renderAuditoria()` refaz o GET com o estado atual de AUD. */
  const AUD = {
    pagina: 1,
    porPagina: 50,
    catalogoPronto: false,
  };

  function filtrosAuditoria() {
    const v = (id) => document.getElementById(id).value.trim();
    const out = {};
    if (v("auditoria-de")) out.de = v("auditoria-de");
    if (v("auditoria-ate")) out.ate = v("auditoria-ate");
    if (v("auditoria-ator")) out.ator_username = v("auditoria-ator");
    if (v("auditoria-app")) out.app_slug = v("auditoria-app");
    if (v("auditoria-categoria")) out.categoria = v("auditoria-categoria");
    if (v("auditoria-resultado")) out.resultado = v("auditoria-resultado");
    return out;
  }

  async function carregarCatalogoAuditoria() {
    if (AUD.catalogoPronto) return;
    AUD.catalogoPronto = true; // marca antes: uma falha não deve tentar de novo a cada render

    const selApp = document.getElementById("auditoria-app");
    [...ADM.apps]
      .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"))
      .forEach((app) => {
        const opt = document.createElement("option");
        opt.value = app.slug;
        opt.textContent = app.nome;
        selApp.appendChild(opt);
      });

    try {
      const catalogo = await api("GET", "/api/admin/auditoria/catalogo");
      const categorias = [...new Set(catalogo.map((e) => e.categoria))].sort();
      const selCategoria = document.getElementById("auditoria-categoria");
      categorias.forEach((cat) => {
        const opt = document.createElement("option");
        opt.value = cat;
        opt.textContent = cat;
        selCategoria.appendChild(opt);
      });
    } catch (e) {
      if (!e.sessionExpired) console.error("catálogo de auditoria:", e.message);
    }
  }

  function fmtQuando(iso) {
    // `ocorrido_em` é UTC sem fuso no texto (mesmo formato do datetime()
    // do SQLite) — mostrado como veio, com o sufixo deixando isso explícito.
    return iso ? `${iso} UTC` : "—";
  }

  function alvoAuditoria(ev) {
    if (!ev.alvo_tipo) return "—";
    const rotulo = ev.alvo_rotulo || ev.alvo_id || "";
    return `${escapeHtml(ev.alvo_tipo)}${rotulo ? ": " + escapeHtml(String(rotulo)) : ""}`;
  }

  function linhaAuditoria(ev) {
    const detalhes = ev.detalhes && Object.keys(ev.detalhes).length
      ? `<code class="col-meta">${escapeHtml(JSON.stringify(ev.detalhes))}</code>`
      : "";
    return `<tr>
      <td class="col-meta">${escapeHtml(fmtQuando(ev.ocorrido_em))}</td>
      <td>${escapeHtml(ev.ator_username || t("admin.auditoria.sem_ator"))}</td>
      <td class="col-slug">${escapeHtml(ev.app_slug || "—")}</td>
      <td><span class="col-slug">${escapeHtml(ev.categoria)}.${escapeHtml(ev.acao)}</span></td>
      <td>${alvoAuditoria(ev)}</td>
      <td><span class="pill ${escapeHtml(ev.resultado === "ok" ? "on" : ev.resultado)}">${escapeHtml(ev.resultado)}</span></td>
      <td>${detalhes}</td>
    </tr>`;
  }

  function renderPaginacaoAuditoria(total) {
    const cont = document.getElementById("paginacao-auditoria");
    const totalPaginas = Math.max(1, Math.ceil(total / AUD.porPagina));
    cont.innerHTML = `
      <span>${t("admin.auditoria.total").replace("{n}", total)}</span>
      <button id="auditoria-pag-ant" ${AUD.pagina <= 1 ? "disabled" : ""}>&larr;</button>
      <span>${AUD.pagina} / ${totalPaginas}</span>
      <button id="auditoria-pag-prox" ${AUD.pagina >= totalPaginas ? "disabled" : ""}>&rarr;</button>
    `;
    const ant = document.getElementById("auditoria-pag-ant");
    const prox = document.getElementById("auditoria-pag-prox");
    if (ant) ant.addEventListener("click", () => { AUD.pagina -= 1; renderAuditoria(); });
    if (prox) prox.addEventListener("click", () => { AUD.pagina += 1; renderAuditoria(); });
  }

  async function renderAuditoria() {
    await carregarCatalogoAuditoria();
    const tbl = document.getElementById("table-auditoria");
    const params = new URLSearchParams({
      ...filtrosAuditoria(),
      pagina: AUD.pagina,
      por_pagina: AUD.porPagina,
    });
    let pagina;
    try {
      pagina = await api("GET", `/api/admin/auditoria?${params}`);
    } catch (e) {
      if (e.sessionExpired) return;
      tbl.innerHTML = `<tbody><tr><td>${escapeHtml(t("admin.err.load") + e.message)}</td></tr></tbody>`;
      return;
    }
    if (pagina.itens.length === 0) {
      tbl.innerHTML = `<tbody><tr><td>${escapeHtml(t("admin.auditoria.vazio"))}</td></tr></tbody>`;
    } else {
      tbl.innerHTML =
        `<thead><tr>${[
          "admin.auditoria.col.quando", "admin.auditoria.col.ator", "admin.auditoria.col.app",
          "admin.auditoria.col.evento", "admin.auditoria.col.alvo", "admin.auditoria.col.resultado",
          "admin.auditoria.col.detalhes",
        ].map(th).join("")}</tr></thead>` +
        `<tbody>${pagina.itens.map(linhaAuditoria).join("")}</tbody>`;
    }
    renderPaginacaoAuditoria(pagina.total);
  }

  function exportarAuditoria() {
    const params = new URLSearchParams(filtrosAuditoria());
    // `require_admin` exige o Bearer — uma navegação de `<a href>` puro não
    // carrega o header, então baixa por fetch e entrega o blob ao navegador.
    fetch(`/api/admin/auditoria/exportar?${params}`, {
      headers: { Authorization: `Bearer ${SF.state.token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "auditoria.csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => alert(t("admin.auditoria.err.exportar") + e.message));
  }

  /* ---------- Bindings ---------- */
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".admin-tab").forEach((el) => {
      el.addEventListener("click", () => {
        setActiveTab(el.dataset.tab);
        renderActiveTab();
      });
    });

    document.getElementById("btn-new-app").addEventListener("click", () => openModal("apps", null));
    document.getElementById("btn-new-secao").addEventListener("click", () => openModal("secoes", null));
    document.getElementById("btn-new-role").addEventListener("click", () => openModal("roles", null));
    document.getElementById("btn-new-usuario").addEventListener("click", () => openModal("usuarios", null));
    document.getElementById("btn-new-filial").addEventListener("click", () => openModal("filiais", null));
    document.getElementById("btn-new-un").addEventListener("click", () => openModal("unidades-negocio", null));

    document.getElementById("btn-auditoria-filtrar").addEventListener("click", () => {
      AUD.pagina = 1;
      renderAuditoria();
    });
    document.getElementById("btn-auditoria-exportar").addEventListener("click", (ev) => {
      ev.preventDefault();
      exportarAuditoria();
    });

    document.getElementById("modal-close").addEventListener("click", closeModal);
    document.getElementById("modal-cancel").addEventListener("click", closeModal);

    // Clique no fundo só fecha se o clique COMEÇOU e TERMINOU no próprio fundo.
    // Sem isso, selecionar texto dentro de um campo e soltar o mouse fora do
    // modal disparava um "click" no overlay (ancestral comum) e fechava sem querer.
    const modalOverlay = document.getElementById("modal-overlay");
    let modalMouseDownTarget = null;
    modalOverlay.addEventListener("mousedown", (ev) => {
      modalMouseDownTarget = ev.target;
    });
    modalOverlay.addEventListener("click", (ev) => {
      if (ev.target === modalOverlay && modalMouseDownTarget === modalOverlay) requestClose();
      modalMouseDownTarget = null;
    });

    // Qualquer digitação/alteração no formulário marca o modal como "sujo".
    // O listener fica no container (#modal-form), que persiste mesmo quando o
    // innerHTML é reconstruído a cada openModal — input events fazem bubbling.
    document.getElementById("modal-form").addEventListener("input", () => {
      modalDirty = true;
    });

    // Digitar a UF preenche a região quando ela ainda está vazia — nunca
    // sobrescreve o que a pessoa escreveu.
    document.getElementById("modal-form").addEventListener("input", (ev) => {
      if (!ev.target || ev.target.name !== "uf") return;
      const campoRegiao = document.querySelector("#modal-form [name='regiao']");
      if (!campoRegiao || campoRegiao.value.trim()) return;
      const regiao = REGIAO_POR_UF[ev.target.value.trim().toUpperCase()];
      if (regiao) campoRegiao.value = regiao;
    });

    document.getElementById("modal-save").addEventListener("click", submitModal);
    document.getElementById("modal-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      submitModal();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && document.getElementById("modal-overlay").classList.contains("visible")) {
        requestClose();
      }
    });

    /* Troca de idioma: re-renderiza a tabela ativa se a tela admin estiver aberta */
    window.addEventListener("sf:langchange", () => {
      const adminVisible = !document.getElementById("screen-admin").classList.contains("hidden");
      if (adminVisible) renderActiveTab();
    });
  });
})();
