/* Hub SuperFrio & Icestar — tela SuperfrioIA (Lote 2)
   Camada de apresentação sobre /api/ia. O número que aparece vem pronto do
   servidor (ferramenta -> derivação do Hub); este arquivo só renderiza e nunca
   calcula nada. Todo texto dinâmico passa por escapeHtml; sem handler inline
   (CSP script-src 'self'). Desenho: docs/SUPERFRIOIA_CHAT_MOCKUP.html. */
(() => {
  const SF = window.SF;
  if (!SF) {
    console.error("superfrioia.js carregado antes de app.js");
    return;
  }
  const escapeHtml = SF.escapeHtml;
  const t = (k) => SF.i18n.t(k);
  const tn = (k, vars) => Object.keys(vars).reduce((s, v) => s.replace(`{${v}}`, vars[v]), t(k));

  const IA = {
    dominios: [],
    slug: null,
    conversas: [],
    conversaId: null,
    mensagens: [],
    enviando: false,
    admin: { pendentes: [], vigentes: [] },
    falha: null, // {chave, repetir}
  };

  const $ = (id) => document.getElementById(id);
  const tela = () => $("screen-superfrioia");
  const visivel = () => tela() && !tela().classList.contains("hidden");

  /* ---------- HTTP ---------- */
  async function api(method, path, body) {
    const opts = { method, headers: { Authorization: `Bearer ${SF.state.token}` } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      // showLogin() não esconde as outras telas; esta se esconde antes de sair.
      tela().classList.add("hidden");
      if (SF.logout) SF.logout(t("session.expired"));
      const e = new Error(t("session.expired"));
      e.sessionExpired = true;
      throw e;
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j && j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      } catch (_e) { /* corpo sem JSON */ }
      const e = new Error(detail);
      e.status = res.status;
      throw e;
    }
    return res.status === 204 ? null : res.json();
  }

  /* ---------- Texto seguro ---------- */
  function texto(s) {
    // escapa TUDO primeiro; só então troca **negrito** e quebra de linha por tags nossas
    return escapeHtml(String(s ?? ""))
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function quando(iso) {
    if (!iso) return "";
    const d = new Date(iso.replace(" ", "T") + "Z");
    if (Number.isNaN(d.getTime())) return "";
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  const dominio = () => IA.dominios.find((d) => d.slug === IA.slug) || null;

  /* ---------- Abrir / fechar / carregar ---------- */
  async function abrir() {
    $("screen-portal").classList.add("hidden");
    tela().classList.remove("hidden");
    IA.conversaId = null;
    IA.mensagens = [];
    IA.falha = null;
    await carregar();
  }
  SF.openSuperfrioIa = abrir;
  SF.renderSuperfrioIa = render;

  function fechar() {
    tela().classList.add("hidden");
    $("screen-portal").classList.remove("hidden");
  }

  function corpoComAviso(chave, classe = "ia-aviso--indisponivel", repetir = false) {
    $("ia-body").innerHTML = `
      <div class="empty-state">
        <h3>${escapeHtml(t(chave))}</h3>
        ${repetir ? `<p><button class="btn-ghost" data-acao="recarregar">${escapeHtml(t("ia.tentar"))}</button></p>` : ""}
      </div>`;
  }

  async function carregar() {
    $("ia-body").innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
      IA.dominios = await api("GET", "/api/ia/dominios");
    } catch (e) {
      if (e.sessionExpired) return;
      if (e.status === 404) return corpoComAviso("ia.err.desligado");
      if (e.status === 403) return corpoComAviso("ia.err.sem_acesso");
      return corpoComAviso("ia.err.carregar", "", true);
    }
    if (!IA.dominios.length) {
      $("ia-body").innerHTML = `<div class="empty-state"><h3>${escapeHtml(t("ia.sem_dominio.titulo"))}</h3><p>${escapeHtml(t("ia.sem_dominio.texto"))}</p></div>`;
      return;
    }
    if (!IA.dominios.some((d) => d.slug === IA.slug)) IA.slug = IA.dominios[0].slug;
    await Promise.all([carregarConversas(), carregarAdmin()]);
    render();
  }

  async function carregarConversas() {
    try {
      const todas = await api("GET", "/api/ia/conversas");
      IA.conversas = todas.filter((c) => c.dominio === IA.slug);
    } catch (e) {
      if (!e.sessionExpired) IA.conversas = [];
    }
  }

  async function carregarAdmin() {
    const d = dominio();
    IA.admin = { pendentes: [], vigentes: [] };
    if (!d || !d.pode_administrar) return;
    try {
      const todas = await api("GET", `/api/ia/administracao/concessoes?dominio=${encodeURIComponent(d.slug)}`);
      IA.admin.pendentes = todas.filter((c) => c.status === "pendente");
      IA.admin.vigentes = todas.filter((c) => c.vigente);
    } catch (e) {
      if (!e.sessionExpired) IA.admin = { pendentes: [], vigentes: [] };
    }
  }

  /* ---------- Renderização ---------- */
  function render() {
    if (!visivel() || !IA.dominios.length) return;
    const d = dominio();
    if (!d) return;
    const rascunho = $("ia-pergunta") ? $("ia-pergunta").value : "";
    const liberado = d.acesso.estado === "liberado";
    // quem aprova mas não consulta (só `administrar`) tem a fila como conteúdo principal: vem primeiro
    const adminPrimeiro = d.pode_administrar && !liberado ? blocoAdmin() : "";
    $("ia-body").innerHTML = `
      ${adminPrimeiro}
      <div class="ia-layout">
        <aside class="ia-aside">
          ${blocoDominio(d)}
          ${liberado ? blocoExemplos(d) : ""}
          <div class="ia-bloco" id="ia-conversas"></div>
        </aside>
        <section class="ia-painel">
          <div class="ia-painel-head">
            <div class="titulo">${escapeHtml(d.nome)} <span class="pill ${liberado ? "on" : "off"}">${escapeHtml(t(`ia.status.${d.acesso.estado}`))}</span></div>
            <div class="fonte">${escapeHtml(t("ia.fonte"))}: <code>${escapeHtml(d.fonte || d.slug)}</code></div>
          </div>
          ${liberado ? painelDeConversa(d) : painelDeAcesso(d)}
        </section>
      </div>
      ${d.pode_administrar && liberado ? blocoAdmin() : ""}`;
    renderConversas();
    if (liberado) {
      renderThread();
      const ta = $("ia-pergunta");
      if (ta) { ta.value = rascunho; ta.disabled = IA.enviando; }
    }
    SF.i18n.applyStatic($("ia-body"));
  }

  function blocoDominio(d) {
    const opcoes = IA.dominios.map((x) => `<option value="${escapeHtml(x.slug)}"${x.slug === IA.slug ? " selected" : ""}>${escapeHtml(x.nome)}</option>`).join("");
    return `
      <div class="ia-bloco">
        <h3>${escapeHtml(t("ia.dominio"))}</h3>
        <select class="ia-dominio" id="ia-dominio" aria-label="${escapeHtml(t("ia.dominio"))}">${opcoes}</select>
        <div class="ia-dominio-meta">
          <span class="pill indicador">${escapeHtml(d.classificacao)}</span>
          <span class="pill iframe">${escapeHtml(d.provedor && d.provedor.nome === "falso" ? t("ia.selo.teste") : (d.provedor ? d.provedor.rotulo : ""))}</span>
        </div>
      </div>`;
  }

  function blocoExemplos(d) {
    const itens = (d.exemplos || []).map((e) => `<button class="ia-exemplo" data-acao="exemplo" data-texto="${escapeHtml(e)}">${escapeHtml(e)}</button>`).join("");
    return `<div class="ia-bloco"><h3>${escapeHtml(t("ia.exemplos"))}</h3>${itens}</div>`;
  }

  function renderConversas() {
    const el = $("ia-conversas");
    if (!el) return;
    const d = dominio();
    const liberado = d.acesso.estado === "liberado";
    if (!liberado && !IA.conversas.length) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    const itens = IA.conversas.map((c) => {
      const conteudo = `<span class="titulo">${escapeHtml(c.titulo)}</span><span class="quando">${escapeHtml(quando(c.atualizado_em))}</span>`;
      // sem acesso (revogado, vencido...) a conversa aparece FECHADA: título "(acesso revogado)", sem clique
      return liberado && !c.acesso_revogado
        ? `<button class="ia-conversa${c.id === IA.conversaId ? " active" : ""}" data-acao="conversa" data-id="${Number(c.id)}">${conteudo}</button>`
        : `<div class="ia-conversa fechada" aria-disabled="true">${conteudo}</div>`;
    }).join("");
    el.innerHTML = `
      <h3>${escapeHtml(t("ia.conversas"))}</h3>
      ${itens || `<div class="ia-vazio">${escapeHtml(t("ia.sem_conversas"))}</div>`}
      ${liberado ? `<button class="btn-ghost ia-nova" data-acao="nova">${escapeHtml(t("ia.nova"))}</button>
      <div class="ia-cota">${escapeHtml(tn("ia.cota", { n: d.limites.perguntas_hoje, max: d.limites.perguntas_por_dia }))}</div>` : ""}`;
  }

  function painelDeConversa(d) {
    return `
      <div class="ia-thread" id="ia-thread" aria-live="polite"></div>
      <div class="ia-composer">
        <div class="ia-composer-box">
          <textarea id="ia-pergunta" rows="1" maxlength="${Number(d.limites.tamanho_da_pergunta)}" aria-label="${escapeHtml(t("ia.perguntar"))}" placeholder="${escapeHtml(tn("ia.placeholder", { dominio: d.nome }))}"></textarea>
          <button class="btn-primary inline" id="ia-enviar" data-acao="enviar">${escapeHtml(t("ia.perguntar"))}</button>
        </div>
        <div class="dica"><span>${escapeHtml(t("ia.dica"))}</span><span>${escapeHtml(t("ia.dica.regra"))}</span></div>
      </div>`;
  }

  function painelDeAcesso(d) {
    const e = d.acesso.estado;
    const caixa = (chave, extra = "", form = false) => `
      <div class="ia-acesso">
        <h2>${escapeHtml(t(`ia.acesso.${chave}.titulo`))}</h2>
        <p>${escapeHtml(t(`ia.acesso.${chave}.texto`))}${extra}</p>
        ${form ? `<textarea id="ia-motivo" maxlength="500" placeholder="${escapeHtml(t("ia.acesso.motivo.ph"))}"></textarea>
        <button class="btn-primary inline" data-acao="pedir">${escapeHtml(t("ia.acesso.pedir"))}</button>
        <div class="ia-erro" id="ia-acesso-erro" role="alert"></div>` : ""}
      </div>`;
    if (e === "pendente") return caixa("pendente");
    if (e === "sem_ver_sistema") return caixa("sem_ver");
    if (e === "negada") return caixa("negada", ` <strong>${escapeHtml(d.acesso.motivo || "—")}</strong>`, true);
    if (e === "revogada") return caixa("revogada", "", true);
    if (e === "vencida") return caixa("vencida", "", true);
    return caixa("sem_concessao", "", true);
  }

  /* ---------- Conversa ---------- */
  function renderThread() {
    const el = $("ia-thread");
    if (!el) return;
    el.innerHTML = IA.mensagens.map(mensagemHtml).join("") + (IA.enviando ? pensandoHtml() : "");
    el.scrollTop = el.scrollHeight;
  }

  function pensandoHtml() {
    return `
      <div class="ia-msg ia-msg--ia" id="ia-pensando">
        <div class="quem">${escapeHtml(t("ia.ia"))}</div>
        <div class="balao"><div class="ia-steps">
          <div class="ia-step done"><span class="dot"></span> ${escapeHtml(t("ia.step.1"))}</div>
          <div class="ia-step cur"><span class="dot"></span> ${escapeHtml(t("ia.step.2"))}</div>
          <div class="ia-step"><span class="dot"></span> ${escapeHtml(t("ia.step.3"))}</div>
        </div></div>
      </div>`;
  }

  function mensagemHtml(m) {
    if (m.papel === "usuario") {
      return `<div class="ia-msg ia-msg--user"><div class="quem">${escapeHtml(t("ia.voce"))}</div><div class="balao">${escapeHtml(m.texto)}</div></div>`;
    }
    const meta = m.meta || {};
    const estado = meta.estado || "ok";
    const rotuloSelo = meta.provedor === "falso" ? t("ia.selo.teste") : meta.rotulo_do_provedor;
    const selo = rotuloSelo ? `<span class="ia-selo">${escapeHtml(rotuloSelo)}</span>` : "";
    const cab = `<div class="quem">${escapeHtml(t("ia.ia"))} ${selo}</div>`;

    if (m.aviso) { // aviso local (cota, permissão, indisponível...), não vem de uma resposta
      return `<div class="ia-msg ia-msg--ia">${cab}<div class="balao">${avisoHtml(m.aviso.classe, m.aviso.titulo, m.aviso.texto, m.aviso.repetir)}</div></div>`;
    }
    if (["limite_consultas", "limite_interno", "passos"].includes(estado)) {
      return `<div class="ia-msg ia-msg--ia">${cab}<div class="balao">${avisoHtml("ia-aviso--escopo", t("ia.aviso.limite"), m.texto)}</div></div>`;
    }
    if (["indisponivel", "erro"].includes(estado)) {
      return `<div class="ia-msg ia-msg--ia">${cab}<div class="balao">${avisoHtml("ia-aviso--indisponivel", t("ia.aviso.indisponivel"), m.texto, true)}</div></div>`;
    }
    const foraDeEscopo = /^\*\*Isso está fora do que este domínio responde/.test(m.texto || "");
    const corpo = foraDeEscopo
      ? avisoHtml("ia-aviso--escopo", t("ia.aviso.escopo"), String(m.texto).replace(/^\*\*[^*]+\*\*\s*/, ""))
      : `<p>${texto(m.texto)}</p>`;
    const blocos = (m.blocos || []).map(blocoHtml).join("");
    return `
      <div class="ia-msg ia-msg--ia" data-mensagem="${Number(m.id) || 0}">
        ${cab}
        <div class="balao">
          ${corpo}
          ${blocos ? `<div class="ia-blocos">${blocos}</div>` : ""}
          ${feedbackHtml(m)}
        </div>
      </div>`;
  }

  function avisoHtml(classe, titulo, corpo, repetir = false) {
    const seguros = ["ia-aviso--escopo", "ia-aviso--permissao", "ia-aviso--indisponivel", "ia-aviso--vazio"];
    const c = seguros.includes(classe) ? classe : "ia-aviso--indisponivel";
    return `<div class="ia-aviso ${c}"><strong>${escapeHtml(titulo)}</strong>${texto(corpo)}</div>${repetir ? `<div class="ia-acoes" style="margin-top:10px"><button class="btn-ghost" data-acao="repetir">${escapeHtml(t("ia.tentar"))}</button></div>` : ""}`;
  }

  function feedbackHtml(m) {
    if (!m.id) return "";
    const on = (v) => (m.feedback === v ? " on" : "");
    return `<div class="ia-feedback" aria-label="">
      <button data-acao="feedback" data-valor="1" data-id="${Number(m.id)}" class="${on(1).trim()}" title="${escapeHtml(t("ia.fb.sim"))}">👍</button>
      <button data-acao="feedback" data-valor="-1" data-id="${Number(m.id)}" class="${on(-1).trim()}" title="${escapeHtml(t("ia.fb.nao"))}">👎</button></div>`;
  }

  function blocoHtml(b) {
    if (b.tipo === "tiles") {
      return `<div class="proj-tiles">${(b.itens || []).map((i, n) => `<div class="proj-tile${n === 0 ? " total" : ""}"><div class="n">${escapeHtml(i.n)}</div><div class="l">${escapeHtml(i.l)}</div></div>`).join("")}</div>`;
    }
    if (b.tipo === "barras") {
      return `<div class="ia-chart" role="img" aria-label="${escapeHtml(b.titulo)}"><div class="titulo">${escapeHtml(b.titulo)}</div>${
        (b.itens || []).map((i, n) => {
          const largura = Math.max(0, Math.min(100, Number(i.largura) || 0));
          return `<div class="ia-bar${n === 0 ? " top" : ""}"><span class="rot" title="${escapeHtml(i.rotulo)}">${escapeHtml(i.rotulo)}</span><div class="trilho"><div class="fill" style="width:${largura}%"></div></div><span class="val">${escapeHtml(i.exibido)}</span></div>`;
        }).join("")}</div>`;
    }
    if (b.tipo === "tabela") {
      const cab = (b.colunas || []).map((c) => `<th>${escapeHtml(c)}</th>`).join("");
      const linhas = (b.linhas || []).map((l) => `<tr>${l.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("");
      return `<details class="ia-tabela"><summary>${escapeHtml(t("ia.tabela"))} (${(b.linhas || []).length})</summary><div class="admin-table-wrap"><table class="admin-table"><thead><tr>${cab}</tr></thead><tbody>${linhas}</tbody></table></div></details>`;
    }
    if (b.tipo === "avisos") {
      return `<div class="ia-aviso ia-aviso--vazio"><ul>${(b.itens || []).map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul></div>`;
    }
    if (b.tipo === "fonte") {
      const frescor = Object.values(b.atualizado_ate || {}).filter(Boolean).join(" · ");
      return `<div class="ia-fonte"><span>${escapeHtml(t("ia.fonte"))}: <code>${escapeHtml(b.nome)}</code></span>${
        (b.filtros || []).map((f) => `<span>· ${escapeHtml(f)}</span>`).join("")}<span>· ${escapeHtml(tn("ia.fonte.linhas", { n: b.linhas_lidas }))}</span>${
        frescor ? `<span>· ${escapeHtml(t("ia.fonte.atualizado"))} ${escapeHtml(frescor)}</span>` : ""}</div>`;
    }
    return "";
  }

  /* ---------- Admin: fila de pedidos ---------- */
  function blocoAdmin() {
    const pend = IA.admin.pendentes.map((c) => `
      <tr><td>${escapeHtml(c.username)}</td><td>${escapeHtml(quando(c.pedido_em))}</td><td>${escapeHtml(c.motivo_pedido)}</td>
      <td><div class="ia-admin-acoes">
        <button class="btn-ghost" data-acao="aprovar" data-id="${Number(c.id)}">${escapeHtml(t("ia.admin.aprovar"))}</button>
        <button class="btn-ghost" data-acao="negar" data-id="${Number(c.id)}">${escapeHtml(t("ia.admin.negar"))}</button></div></td></tr>`).join("");
    const vig = IA.admin.vigentes.map((c) => `
      <tr><td>${escapeHtml(c.username)}${c.autoaprovacao ? ` <span class="pill perm">${escapeHtml(t("ia.admin.autoaprovada"))}</span>` : ""}</td>
      <td>${escapeHtml(quando(c.validade_ate))}${c.vence_em_30_dias ? ` <span class="pill indicador">${escapeHtml(tn("ia.admin.vence", { n: "≤30" }))}</span>` : ""}</td><td></td>
      <td><div class="ia-admin-acoes"><button class="btn-ghost" data-acao="revogar" data-id="${Number(c.id)}">${escapeHtml(t("ia.admin.revogar"))}</button></div></td></tr>`).join("");
    const tabela = (titulo, linhas, colValidade) => `
      <h3 style="margin:14px 0 6px;font-size:12px">${escapeHtml(titulo)}</h3>
      ${linhas ? `<div class="admin-table-wrap"><table class="admin-table"><thead><tr>
        <th>${escapeHtml(t("ia.admin.col.usuario"))}</th><th>${escapeHtml(colValidade ? t("ia.admin.col.validade") : t("ia.admin.col.pedido"))}</th>
        <th>${escapeHtml(t("ia.admin.col.motivo"))}</th><th></th></tr></thead><tbody>${linhas}</tbody></table></div>`
        : `<div class="ia-vazio">${escapeHtml(t("ia.admin.vazio"))}</div>`}`;
    return `
      <div class="ia-bloco ia-admin" id="ia-admin">
        <h3>${escapeHtml(t("ia.admin.titulo"))}</h3>
        <input class="ia-admin-motivo" id="ia-admin-motivo" maxlength="300" placeholder="${escapeHtml(t("ia.admin.motivo.ph"))}">
        <div class="ia-erro" id="ia-admin-erro" role="alert"></div>
        ${tabela(t("ia.admin.pendentes"), pend, false)}
        ${tabela(t("ia.admin.vigentes"), vig, true)}
      </div>`;
  }

  async function decidir(acao, id) {
    const motivoEl = $("ia-admin-motivo");
    const erroEl = $("ia-admin-erro");
    const motivo = motivoEl ? motivoEl.value.trim() : "";
    erroEl.textContent = "";
    if (acao !== "aprovar" && !motivo) {
      erroEl.textContent = t("ia.admin.motivo.ph");
      motivoEl.focus();
      return;
    }
    try {
      await api("POST", `/api/ia/administracao/concessoes/${id}/${acao}`, acao === "aprovar" ? { motivo: motivo || null } : { motivo });
      await carregarAdmin();
      render();
    } catch (e) {
      if (!e.sessionExpired) erroEl.textContent = t("ia.admin.err") + e.message;
    }
  }

  /* ---------- Ações ---------- */
  async function pedirAcesso() {
    const campo = $("ia-motivo");
    const motivo = campo.value.trim();
    const erro = $("ia-acesso-erro");
    erro.textContent = "";
    if (!motivo) { // o servidor também recusa (400); aqui a pessoa vê o porquê e o foco vai ao campo
      erro.textContent = t("ia.acesso.motivo.obrigatorio");
      campo.focus();
      return;
    }
    try {
      await api("POST", "/api/ia/concessoes/pedidos", { dominio: IA.slug, motivo });
      await carregar();
    } catch (e) {
      if (!e.sessionExpired) erro.textContent = e.message;
    }
  }

  async function abrirConversa(id) {
    try {
      const c = await api("GET", `/api/ia/conversas/${id}`);
      IA.conversaId = c.id;
      IA.mensagens = c.mensagens;
    } catch (e) {
      if (e.sessionExpired) return;
      IA.conversaId = id;
      IA.mensagens = [{ papel: "ia", texto: "", meta: {}, aviso: { classe: "ia-aviso--permissao", titulo: t("ia.aviso.permissao"), texto: e.message } }];
    }
    renderConversas();
    renderThread();
  }

  function novaConversa() {
    IA.conversaId = null;
    IA.mensagens = [];
    IA.falha = null;
    renderConversas();
    renderThread();
    const ta = $("ia-pergunta");
    if (ta) ta.focus();
  }

  async function enviar(textoDaPergunta) {
    const ta = $("ia-pergunta");
    const pergunta = (textoDaPergunta ?? (ta ? ta.value : "")).trim();
    if (!pergunta || IA.enviando) return;
    IA.enviando = true;
    IA.falha = null;
    IA.mensagens.push({ papel: "usuario", texto: pergunta });
    if (ta) { ta.value = ""; ta.disabled = true; }
    $("ia-enviar").disabled = true;
    renderThread();
    try {
      const r = await api("POST", "/api/ia/perguntas", { dominio: IA.slug, pergunta, conversa_id: IA.conversaId });
      IA.conversaId = r.conversa_id;
      // o servidor devolve a pergunta já mascarada: a tela mostra o que foi gravado, não o CPF digitado
      const bolha = [...IA.mensagens].reverse().find((m) => m.papel === "usuario");
      if (bolha && r.pergunta) bolha.texto = r.pergunta;
      IA.mensagens.push(r.mensagem);
      if (r.dados_pessoais_mascarados && r.dados_pessoais_mascarados.length) {
        IA.mensagens.push({ papel: "ia", texto: "", meta: {}, aviso: { classe: "ia-aviso--vazio", titulo: "", texto: t("ia.mascarado") } });
      }
      const d = dominio();
      if (d) d.limites.perguntas_hoje = r.perguntas_hoje;
      IA.falha = null;
    } catch (e) {
      if (e.sessionExpired) return;
      IA.mensagens.push({ papel: "ia", texto: "", meta: {}, aviso: avisoDoErro(e) });
      IA.falha = { pergunta };
      if (e.status === 403) await carregar(); // a concessão pode ter sido revogada: relê o estado
    } finally {
      IA.enviando = false;
    }
    await carregarConversas();
    if (visivel()) {
      renderConversas();
      renderThread();
      const caixa = $("ia-pergunta");
      if (caixa) { caixa.disabled = false; $("ia-enviar").disabled = false; caixa.focus(); }
    }
  }

  function avisoDoErro(e) {
    if (e.status === 429) return { classe: "ia-aviso--indisponivel", titulo: t("ia.aviso.cota"), texto: e.message };
    if (e.status === 403) return { classe: "ia-aviso--permissao", titulo: t("ia.aviso.permissao"), texto: e.message };
    if (e.status === 400 || e.status === 404) return { classe: "ia-aviso--escopo", titulo: t("ia.aviso.escopo"), texto: e.message };
    return { classe: "ia-aviso--indisponivel", titulo: t("ia.aviso.indisponivel"), texto: t("ia.aviso.indisponivel.texto"), repetir: true };
  }

  async function feedback(id, valor, botao) {
    try {
      await api("POST", `/api/ia/mensagens/${id}/feedback`, { valor });
      const m = IA.mensagens.find((x) => x.id === id);
      if (m) m.feedback = valor;
      botao.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === botao));
    } catch (e) { /* feedback é opcional: falhar não atrapalha a conversa */ }
  }

  /* ---------- Eventos (delegação: um listener, nada de handler inline) ---------- */
  function ligar() {
    const raiz = $("ia-body");
    raiz.addEventListener("click", (ev) => {
      const el = ev.target.closest("[data-acao]");
      if (!el) return;
      const acao = el.dataset.acao;
      if (acao === "exemplo") { const ta = $("ia-pergunta"); if (ta) { ta.value = el.dataset.texto; ta.focus(); } }
      else if (acao === "enviar") enviar();
      else if (acao === "nova") novaConversa();
      else if (acao === "conversa") abrirConversa(Number(el.dataset.id));
      else if (acao === "pedir") pedirAcesso();
      else if (acao === "recarregar") carregar();
      else if (acao === "repetir" && IA.falha) {
        IA.mensagens = IA.mensagens.slice(0, -2); // tira a pergunta e o aviso, e repete
        enviar(IA.falha.pergunta);
      } else if (acao === "feedback") feedback(Number(el.dataset.id), Number(el.dataset.valor), el);
      else if (["aprovar", "negar", "revogar"].includes(acao)) decidir(acao, Number(el.dataset.id));
    });
    raiz.addEventListener("change", async (ev) => {
      if (ev.target.id !== "ia-dominio") return;
      IA.slug = ev.target.value;
      IA.conversaId = null;
      IA.mensagens = [];
      await Promise.all([carregarConversas(), carregarAdmin()]);
      render();
    });
    raiz.addEventListener("keydown", (ev) => {
      if (ev.target.id === "ia-pergunta" && ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        enviar();
      }
    });
    raiz.addEventListener("input", (ev) => {
      if (ev.target.id === "ia-pergunta") {
        ev.target.style.height = "auto";
        ev.target.style.height = `${Math.min(ev.target.scrollHeight, 160)}px`;
      }
    });
    $("btn-back-from-superfrioia").addEventListener("click", fechar);
    window.addEventListener("sf:langchange", () => { if (visivel()) render(); });
  }
  ligar();
})();
