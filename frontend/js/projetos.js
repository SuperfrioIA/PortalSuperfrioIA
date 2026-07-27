/* Hub SuperFrio & Icestar — tela Projetos IA (Radar de projetos)
   Camada de apresentação sobre /api/projetos-ia: fase atual, atraso e status
   de rollout já vêm calculados do backend (ver backend/projetos_ia/service.py)
   — este arquivo só renderiza e cuida da edição via API. */
(() => {
  const SF = window.SF;
  if (!SF) {
    console.error("projetos.js carregado antes de app.js");
    return;
  }
  const escapeHtml = SF.escapeHtml;
  const t = (k) => SF.i18n.t(k);

  const FASES = [
    "proj.fase.0", "proj.fase.1", "proj.fase.2", "proj.fase.3",
    "proj.fase.4", "proj.fase.5", "proj.fase.6",
  ];
  const FASE_INICIO_ROLLOUT = 4;
  const ST_LBL_KEY = { treinada: "proj.roll.treinada", agendada: "proj.roll.agendada", pendente: "proj.roll.pendente", nao_se_aplica: "proj.roll.naoaplica" };

  function grupo(fase) {
    return fase <= 2 ? "aval" : fase === 3 ? "constr" : fase <= 5 ? "impl" : "sup";
  }

  const PJ = {
    projetos: [],
    filiais: [],
    podeEditar: false,
    visao: "cards",
    filtro: { area: "", fase: "", ti: "", acel: "", status: "" },
    detalheSlug: null,
    detalheAba: "geral",
  };

  /* ---------- HTTP helper (mesmo padrão de admin.js) ---------- */
  async function api(method, path, body) {
    const opts = { method, headers: { Authorization: `Bearer ${SF.state.token}` } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
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

  /* ---------- Datas (só formatação/posicionamento — derivação é do backend) ---------- */
  function T(iso) { return new Date(iso + "T00:00:00").getTime(); }
  function fmt(iso) { if (!iso) return ""; const p = iso.split("-"); return `${p[2]}/${p[1]}/${p[0]}`; }
  function fmtCurto(iso) { if (!iso) return ""; const p = iso.split("-"); return `${p[2]}/${p[1]}`; }
  function hojeIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  /* ---------- Abrir / fechar / carregar ---------- */
  async function openProjetosIa() {
    document.getElementById("screen-portal").classList.add("hidden");
    document.getElementById("screen-projetos").classList.remove("hidden");
    PJ.detalheSlug = null;
    PJ.visao = "cards";
    PJ.filtro = { area: "", fase: "", ti: "", acel: "", status: "" };
    await carregarTudo();
  }
  SF.openProjetosIa = openProjetosIa;
  SF.renderProjetosIa = render;

  async function carregarTudo() {
    const body = document.getElementById("proj-body");
    body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
      const perm = await api("GET", "/api/auth/me/permissoes");
      PJ.podeEditar = (perm.permissoes || []).includes("projetos-ia:editar");
      const [projetos, filiais] = await Promise.all([
        api("GET", "/api/projetos-ia"),
        PJ.podeEditar ? api("GET", "/api/projetos-ia/filiais") : Promise.resolve([]),
      ]);
      PJ.projetos = projetos;
      PJ.filiais = filiais;
      render();
    } catch (e) {
      if (e.sessionExpired) return;
      body.innerHTML = `<div class="empty-state"><h3>${escapeHtml(t("proj.err.load"))}</h3><p>${escapeHtml(e.message)}</p></div>`;
    }
  }

  async function recarregarProjeto(slug) {
    const atualizado = await api("GET", `/api/projetos-ia/${encodeURIComponent(slug)}`);
    const i = PJ.projetos.findIndex((p) => p.slug === slug);
    if (i >= 0) PJ.projetos[i] = atualizado;
    else PJ.projetos.push(atualizado);
    return atualizado;
  }

  function render() {
    if (!document.getElementById("screen-projetos") || document.getElementById("screen-projetos").classList.contains("hidden")) return;
    if (PJ.detalheSlug) renderDetalhe();
    else renderLista();
  }

  /* ---------- Lista ---------- */
  function uniq(arr) { return [...new Set(arr)].filter(Boolean).sort(); }

  function filtrados() {
    return PJ.projetos.filter((p) =>
      (!PJ.filtro.area || p.area === PJ.filtro.area) &&
      (!PJ.filtro.fase || String(p.fase_atual) === PJ.filtro.fase) &&
      (!PJ.filtro.ti || p.responsavel_ti === PJ.filtro.ti) &&
      (!PJ.filtro.acel || p.acelerador === PJ.filtro.acel) &&
      (!PJ.filtro.status || (PJ.filtro.status === "atrasado") === (p.atrasado_dias > 0))
    );
  }

  function faseBadge(fase) {
    return `<span class="pill fase-${grupo(fase)}">${escapeHtml(t(FASES[fase]))}</span>`;
  }

  function renderLista() {
    const body = document.getElementById("proj-body");
    const counts = { aval: 0, constr: 0, impl: 0, sup: 0 };
    PJ.projetos.forEach((p) => counts[grupo(p.fase_atual)]++);
    const vis = filtrados();
    const temFiltro = PJ.filtro.area || PJ.filtro.fase || PJ.filtro.ti || PJ.filtro.acel || PJ.filtro.status;

    const sel = (id, labelKey, opts, val) =>
      `<select id="${id}" aria-label="${escapeHtml(t(labelKey))}"><option value="">${escapeHtml(t(labelKey))}</option>` +
      opts.map((o) => `<option value="${escapeHtml(o.v)}"${String(o.v) === val ? " selected" : ""}>${escapeHtml(o.t)}</option>`).join("") +
      "</select>";

    let corpo;
    if (!PJ.projetos.length) corpo = `<div class="proj-vazio">${escapeHtml(t("proj.vazio.nenhum"))}</div>`;
    else if (!vis.length) corpo = `<div class="proj-vazio">${escapeHtml(t("proj.vazio.filtro"))}</div>`;
    else if (PJ.visao === "cards") corpo = viewCards(vis);
    else if (PJ.visao === "gantt") corpo = viewGantt(vis);
    else corpo = viewRollout(vis);

    body.innerHTML = `
      <div class="proj-tiles">
        <div class="proj-tile total"><div class="n">${PJ.projetos.length}</div><div class="l">${escapeHtml(t("proj.tiles.total"))}</div></div>
        <div class="proj-tile"><div class="n">${counts.aval}</div><div class="l">${escapeHtml(t("proj.tiles.aval"))}</div></div>
        <div class="proj-tile"><div class="n">${counts.constr}</div><div class="l">${escapeHtml(t("proj.tiles.constr"))}</div></div>
        <div class="proj-tile"><div class="n">${counts.impl}</div><div class="l">${escapeHtml(t("proj.tiles.impl"))}</div></div>
        <div class="proj-tile"><div class="n">${counts.sup}</div><div class="l">${escapeHtml(t("proj.tiles.sup"))}</div></div>
      </div>
      <div class="proj-toolbar">
        ${sel("flt-area", "proj.filtro.area", uniq(PJ.projetos.map((p) => p.area)).map((a) => ({ v: a, t: a })), PJ.filtro.area)}
        ${sel("flt-fase", "proj.filtro.fase", FASES.map((k, i) => ({ v: i, t: t(k) })), PJ.filtro.fase)}
        ${sel("flt-ti", "proj.filtro.ti", uniq(PJ.projetos.map((p) => p.responsavel_ti)).map((a) => ({ v: a, t: a })), PJ.filtro.ti)}
        ${sel("flt-acel", "proj.filtro.acelerador", uniq(PJ.projetos.map((p) => p.acelerador)).map((a) => ({ v: a, t: a })), PJ.filtro.acel)}
        ${sel("flt-status", "proj.filtro.status", [{ v: "emdia", t: t("proj.filtro.status.emdia") }, { v: "atrasado", t: t("proj.filtro.status.atrasado") }], PJ.filtro.status)}
        <button class="proj-clear${temFiltro ? " on" : ""}" id="flt-limpar">${escapeHtml(t("proj.limpar"))}</button>
        <span class="proj-toolbar-spacer"></span>
        ${PJ.podeEditar ? `<button class="btn-primary inline" id="proj-btn-novo">${escapeHtml(t("proj.novo"))}</button>` : ""}
        <div class="proj-views" role="tablist">
          <button class="${PJ.visao === "cards" ? "on" : ""}" data-v="cards">${escapeHtml(t("proj.view.cards"))}</button>
          <button class="${PJ.visao === "gantt" ? "on" : ""}" data-v="gantt">${escapeHtml(t("proj.view.gantt"))}</button>
          <button class="${PJ.visao === "rollout" ? "on" : ""}" data-v="rollout">${escapeHtml(t("proj.view.rollout"))}</button>
        </div>
      </div>
      ${corpo}`;

    const bind = (id, campo) => document.getElementById(id).addEventListener("change", (e) => { PJ.filtro[campo] = e.target.value; renderLista(); });
    bind("flt-area", "area"); bind("flt-fase", "fase"); bind("flt-ti", "ti"); bind("flt-acel", "acel"); bind("flt-status", "status");
    document.getElementById("flt-limpar").addEventListener("click", () => {
      PJ.filtro = { area: "", fase: "", ti: "", acel: "", status: "" };
      renderLista();
    });
    body.querySelectorAll(".proj-views button").forEach((b) => b.addEventListener("click", () => { PJ.visao = b.dataset.v; renderLista(); }));
    const btnNovo = document.getElementById("proj-btn-novo");
    if (btnNovo) btnNovo.addEventListener("click", abrirModalNovoProjeto);
    body.querySelectorAll("[data-id]").forEach((el) => el.addEventListener("click", () => abrirDetalhe(el.dataset.id)));
  }

  async function abrirDetalhe(slug) {
    PJ.detalheSlug = slug;
    PJ.detalheAba = "geral";
    const body = document.getElementById("proj-body");
    body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
      // O item em cache (vindo da lista) não traz o array bruto de rollout —
      // só o resumo. Busca o detalhe completo antes de renderizar.
      await recarregarProjeto(slug);
      render();
    } catch (e) {
      if (e.sessionExpired) return;
      body.innerHTML = `<div class="empty-state"><h3>${escapeHtml(t("proj.err.load"))}</h3><p>${escapeHtml(e.message)}</p></div>`;
    }
  }

  function viewCards(vis) {
    return `<div class="proj-grid">${vis.map((p) => {
      const at = p.atrasado_dias;
      const rs = p.rollout_resumo;
      let roll = "";
      if (rs && p.fase_atual >= FASE_INICIO_ROLLOUT) {
        roll = rs.pendentes || rs.agendadas
          ? `<span class="mini-roll"><span class="mrbar"><i style="width:${rs.pct}%"></i></span><span><b>${rs.treinadas}/${rs.previstas}</b> ${escapeHtml(t("proj.rollout.treinadas"))}${rs.proximo_treinamento ? ` · ${escapeHtml(t("proj.rollout.proximo"))} <b>${escapeHtml(rs.proximo_treinamento.filial_nome)}</b> ${fmtCurto(rs.proximo_treinamento.data)}` : ""}</span></span>`
          : `<span class="mini-roll"><span class="mrbar"><i style="width:100%"></i></span><span>${escapeHtml(t("proj.rollout.concluido"))} · <b>${rs.treinadas}/${rs.previstas}</b></span></span>`;
      }
      return `
        <button class="proj-card" data-id="${escapeHtml(p.slug)}">
          <span class="proj-card-top">${faseBadge(p.fase_atual)}${at ? `<span class="pill atraso">${escapeHtml(t("proj.atrasado"))} ${at}d</span>` : ""}</span>
          <span><h4>${escapeHtml(p.nome)}</h4><span class="area">${escapeHtml(p.area)}</span></span>
          <span class="obj">${escapeHtml(p.objetivo)}</span>
          ${roll}
          <span class="marco">${p.proximo_marco_texto ? `${escapeHtml(t("proj.marco.prefix"))} <b>${escapeHtml(p.proximo_marco_texto)}</b> · <b>${fmt(p.proximo_marco_data)}</b>` : escapeHtml(t("proj.marco.suporte"))}</span>
          <span class="quem">${escapeHtml(t("proj.card.acelerador"))} <b>${escapeHtml(p.acelerador)}</b> · TI <b>${escapeHtml(p.responsavel_ti || t("admin.dash"))}</b></span>
        </button>`;
    }).join("")}</div>`;
  }

  /* ---------- Gantt helpers ---------- */
  const MES_KEY = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  function pct(iso, min, max) { return Math.max(0, Math.min(100, ((T(iso) - T(min)) / (T(max) - T(min))) * 100)); }
  function eixoMeses(min, max) {
    const out = [];
    const d = new Date(min + "T00:00:00");
    d.setDate(1);
    let primeiro = true;
    while (d.getTime() <= T(max)) {
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
      const px = pct(iso, min, max);
      if (px < 94) out.push({ px, lbl: MES_KEY[d.getMonth()] + (primeiro || d.getMonth() === 0 ? " " + String(d.getFullYear()).slice(2) : "") });
      primeiro = false;
      d.setMonth(d.getMonth() + 1);
    }
    return out;
  }
  function ganttShell(min, max, rowsHtml, legendHtml) {
    const eixo = eixoMeses(min, max).map((m) => `<span style="left:${m.px}%">${m.lbl}</span>`).join("");
    const hoje = pct(hojeIso(), min, max);
    return `<div class="gantt"><div class="gantt-inner">
      <div class="g-axis">${eixo}</div>
      ${rowsHtml}
      <div class="g-hoje" style="left:${hoje}%"></div>
    </div>${legendHtml}</div>`;
  }
  function barra(min, max, ini, fim, cls, title) {
    const l = pct(ini, min, max), w = Math.max(1.2, pct(fim, min, max) - l);
    return `<div class="g-bar ${cls}" style="left:${l}%;width:${w}%" title="${escapeHtml(title)}"></div>`;
  }

  function viewGantt(vis) {
    const hoje = hojeIso();
    const todasDatas = vis.flatMap((p) => p.fases.flatMap((f) => [f.previsto_inicio, f.previsto_fim]).filter(Boolean));
    const MIN = todasDatas.length ? todasDatas.reduce((a, b) => (a < b ? a : b)) : hoje;
    const maxCandidatos = [...todasDatas, hoje];
    const MAXRAW = maxCandidatos.reduce((a, b) => (a > b ? a : b));
    const MAX = new Date(T(MAXRAW) + 45 * 86400000).toISOString().slice(0, 10);
    const SEGS = [
      { ii: 0, fi: 2, cls: "seg-aval", nmKey: "proj.legend.aval" },
      { ii: 3, fi: 3, cls: "seg-constr", nmKey: "proj.legend.constr" },
      { ii: 4, fi: 5, cls: "seg-impl", nmKey: "proj.legend.impl" },
      { ii: 6, fi: 6, cls: "seg-sup", nmKey: "proj.legend.sup" },
    ];
    const rows = vis.map((p) => {
      const at = p.atrasado_dias;
      const bars = SEGS.map((s) => {
        const ini = p.fases[s.ii].previsto_inicio, fim = p.fases[s.fi].previsto_fim || MAX;
        const futura = T(ini) > T(hoje);
        const aberta = !p.fases[s.fi].previsto_fim;
        return barra(MIN, MAX, ini, fim, `${s.cls}${futura ? " faded" : ""}${aberta ? " open" : ""}`, `${t(s.nmKey)}: ${fmt(ini)} → ${p.fases[s.fi].previsto_fim ? fmt(p.fases[s.fi].previsto_fim) : t("proj.crono.aberto")}`);
      }).join("");
      const marco = p.proximo_marco_data ? `<div class="g-marco" style="left:${pct(p.proximo_marco_data, MIN, MAX)}%" title="${escapeHtml(t("proj.marco.prefix"))} ${escapeHtml(p.proximo_marco_texto || "")} — ${fmt(p.proximo_marco_data)}"></div>` : "";
      return `<div class="g-row" data-id="${escapeHtml(p.slug)}" style="cursor:pointer">
        <div class="g-lbl">${escapeHtml(p.nome)}<span class="sub${at ? " late" : ""}">${at ? `${escapeHtml(t("proj.atrasado"))} ${at}d` : escapeHtml(t(FASES[p.fase_atual]))}</span></div>
        <div class="g-track">${bars}${marco}</div>
      </div>`;
    }).join("");
    const legenda = `<div class="g-legend">
      <span><i class="sw-aval"></i>${escapeHtml(t("proj.legend.aval"))}</span>
      <span><i class="sw-constr"></i>${escapeHtml(t("proj.legend.constr"))}</span>
      <span><i class="sw-impl"></i>${escapeHtml(t("proj.legend.impl"))}</span>
      <span><i class="sw-sup"></i>${escapeHtml(t("proj.legend.sup"))}</span>
      <span><i class="sw-marco"></i>${escapeHtml(t("proj.legend.marco"))}</span>
      <span><i class="sw-hoje"></i>${escapeHtml(t("proj.legend.hoje"))}</span>
    </div>`;
    return ganttShell(MIN, MAX, rows, legenda);
  }

  function viewRollout(vis) {
    const rows = vis.map((p) => {
      const rs = p.rollout_resumo;
      if (!rs || p.fase_atual < FASE_INICIO_ROLLOUT) {
        return `<button class="roll-row off" data-id="${escapeHtml(p.slug)}">
          <span class="nm">${escapeHtml(p.nome)}<span class="sub">${escapeHtml(t(FASES[p.fase_atual]))}</span></span>
          <span class="bar"><span class="mrbar"><i style="width:0%"></i></span></span>
          <span class="num">—</span><span class="prox">${escapeHtml(t("proj.rollout.aindanao"))}</span></button>`;
      }
      return `<button class="roll-row" data-id="${escapeHtml(p.slug)}">
        <span class="nm">${escapeHtml(p.nome)}<span class="sub">${escapeHtml(t(FASES[p.fase_atual]))}</span></span>
        <span class="bar"><span class="mrbar"><i style="width:${rs.pct}%"></i></span><b style="font-size:12px;color:var(--text)">${rs.pct}%</b></span>
        <span class="num"><b>${rs.treinadas}</b>/${rs.previstas} ${escapeHtml(t("proj.rollout.treinadas"))}${rs.agendadas ? ` · ${rs.agendadas} ${escapeHtml(t("proj.roll.agendadas"))}` : ""}</span>
        <span class="prox">${rs.proximo_treinamento ? `${escapeHtml(t("proj.rollout.proximo"))} <b>${escapeHtml(rs.proximo_treinamento.filial_nome)} — ${fmtCurto(rs.proximo_treinamento.data)}</b>` : rs.pendentes > 0 ? escapeHtml(t("proj.roll.semagendamento")) : escapeHtml(t("proj.rollout.concluido"))}</span>
      </button>`;
    }).join("");
    return `<div class="roll-rows">${rows}</div>`;
  }

  /* ---------- Detalhe ---------- */
  function renderDetalhe() {
    const body = document.getElementById("proj-body");
    const p = PJ.projetos.find((x) => x.slug === PJ.detalheSlug);
    if (!p) { PJ.detalheSlug = null; renderLista(); return; }
    const at = p.atrasado_dias;
    // rollout_resumo vem null quando ainda não há nenhuma filial no escopo —
    // a aba precisa aparecer mesmo assim (é onde a primeira é incluída).
    const rs = p.rollout_resumo || { previstas: 0, treinadas: 0, agendadas: 0, pendentes: 0, nao_se_aplica: 0, pct: 0, proximo_treinamento: null };
    const temRoll = p.fase_atual >= FASE_INICIO_ROLLOUT;

    const stepper = `<div class="stepper-wrap"><div class="stepper">${FASES.map((k, i) => {
      const done = i < p.fase_atual && p.fases[i] && p.fases[i].concluido_em;
      const cls = i < p.fase_atual ? "done" : i === p.fase_atual ? "cur" : "";
      return done
        ? `<button type="button" class="step ${cls}" data-fase="${i}" title="${escapeHtml(t("proj.fase.verconclusao"))}"><i></i><span>${escapeHtml(t(k))}</span></button>`
        : `<div class="step ${cls}"><i></i><span>${escapeHtml(t(k))}</span></div>`;
    }).join("")}</div></div><div class="fase-nota" id="fase-nota" hidden></div>`;

    const abas = [{ k: "geral", tk: "proj.tab.geral" }, { k: "crono", tk: "proj.tab.crono" }];
    if (temRoll) abas.push({ k: "roll", tk: "proj.tab.roll" });
    const tabsHtml = `<div class="det-tabs">${abas.map((a) => `<button class="${PJ.detalheAba === a.k ? "on" : ""}" data-aba="${a.k}">${escapeHtml(t(a.tk))}</button>`).join("")}</div>`;

    let pane;
    if (PJ.detalheAba === "crono") pane = paneCrono(p);
    else if (PJ.detalheAba === "roll") pane = paneRollout(p, rs);
    else pane = paneGeral(p, at, rs, temRoll);

    body.innerHTML = `
      <button type="button" class="back-link" id="proj-back-lista">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><polyline points="12 19 5 12 12 5"/></svg>
        <span>${escapeHtml(t("proj.voltarlista"))}</span>
      </button>
      <div class="proj-det-head">
        <div>
          <h3>${escapeHtml(p.nome)}</h3>
          <p class="sub">${escapeHtml(p.objetivo)}</p>
          <span style="display:inline-flex;gap:12px;align-items:center">${faseBadge(p.fase_atual)}${at ? `<span class="pill atraso">${escapeHtml(t("proj.atrasado"))} ${at}d</span>` : ""}</span>
        </div>
        ${PJ.podeEditar ? `<div><button type="button" class="btn-primary inline" id="proj-btn-editar">${escapeHtml(t("proj.det.editar"))}</button></div>` : ""}
      </div>
      ${stepper}
      ${tabsHtml}
      <div class="det-pane">${pane}</div>`;

    document.getElementById("proj-back-lista").addEventListener("click", () => { PJ.detalheSlug = null; render(); });
    const btnEditar = document.getElementById("proj-btn-editar");
    if (btnEditar) btnEditar.addEventListener("click", () => abrirModalEditarProjeto(p));
    body.querySelectorAll(".det-tabs button").forEach((b) => b.addEventListener("click", () => { PJ.detalheAba = b.dataset.aba; render(); }));

    const nota = document.getElementById("fase-nota");
    let faseSel = null;
    body.querySelectorAll("button.step").forEach((btn) => btn.addEventListener("click", () => {
      const i = Number(btn.dataset.fase);
      body.querySelectorAll(".step.sel").forEach((el) => el.classList.remove("sel"));
      if (faseSel === i) { faseSel = null; nota.hidden = true; return; }
      faseSel = i;
      btn.classList.add("sel");
      const f = p.fases[i];
      nota.innerHTML = `<b>${escapeHtml(t(FASES[i]))}</b> — ${escapeHtml(t("proj.fase.concluidaem"))} <b class="data">${fmt(f.concluido_em)}</b>` +
        (f.observacao ? ` · &ldquo;${escapeHtml(f.observacao)}&rdquo;` : "") +
        (f.registrado_por ? ` <span style="opacity:.8">· ${escapeHtml(t("proj.fase.registradopor"))} ${escapeHtml(f.registrado_por)}</span>` : "");
      nota.hidden = false;
    }));

    if (PJ.detalheAba === "roll") ligarAbaRollout(p, rs);
  }

  function paneGeral(p, at, rs, temRoll) {
    return `<div class="exec">
      <div class="exec-txt">
        <div class="bloco"><span class="k">${escapeHtml(t("proj.geral.problema"))}</span><p>${escapeHtml(p.problema)}</p></div>
        <div class="bloco"><span class="k">${escapeHtml(t("proj.geral.beneficio"))}</span><p>${escapeHtml(p.beneficio)}</p></div>
        <div class="bloco"><span class="k">${escapeHtml(t("proj.geral.publico"))}</span><p>${escapeHtml(p.publico)}</p></div>
      </div>
      <div class="exec-meta">
        <div><span class="k">${escapeHtml(t("proj.geral.area"))}</span><span class="v">${escapeHtml(p.area)}</span></div>
        <div><span class="k">${escapeHtml(t("proj.geral.acelerador"))}</span><span class="v">${escapeHtml(p.acelerador)}</span></div>
        <div><span class="k">${escapeHtml(t("proj.geral.ti"))}</span><span class="v">${escapeHtml(p.responsavel_ti || t("admin.dash"))}</span></div>
        <div><span class="k">${escapeHtml(t("proj.geral.keyuser"))}</span><span class="v">${escapeHtml(p.key_user || t("admin.dash"))}</span></div>
        <div class="marco-box"><span class="k">${escapeHtml(t("proj.geral.proximopasso"))}</span><span class="v">${p.proximo_marco_texto ? escapeHtml(p.proximo_marco_texto) : escapeHtml(t("proj.geral.suporte"))}</span></div>
        ${p.proximo_marco_data ? `<div><span class="k">${escapeHtml(t("proj.geral.previsao"))}</span><span class="v data">${fmt(p.proximo_marco_data)}${at ? ` <span class="pill atraso" style="margin-left:6px">${escapeHtml(t("proj.atrasado"))}</span>` : ""}</span></div>` : ""}
        ${temRoll ? `<div><span class="k">${escapeHtml(t("proj.geral.rollout"))}</span><span class="v">${rs.treinadas}/${rs.previstas} (${rs.pct}%)</span></div>` : ""}
        <div><span class="k">${escapeHtml(t("proj.geral.atualizacao"))}</span><span class="v data">${p.atualizado_em ? fmt(p.atualizado_em.slice(0, 10)) : t("admin.dash")}</span></div>
      </div>
    </div>`;
  }

  function paneCrono(p) {
    const hoje = hojeIso();
    const fins = p.fases.map((f) => f.previsto_fim).filter(Boolean);
    const MIN = p.fases[0].previsto_inicio;
    const maxT = Math.max(...fins.map(T), T(hoje), p.proximo_marco_data ? T(p.proximo_marco_data) : 0);
    const MAX = new Date(maxT + 45 * 86400000).toISOString().slice(0, 10);
    const rows = FASES.map((k, i) => {
      const f = p.fases[i];
      const done = i < p.fase_atual, cur = i === p.fase_atual;
      const aberta = !f.previsto_fim;
      const fim = f.previsto_fim || MAX;
      const cls = done ? "done" : cur ? "cur" : "fut";
      const late = cur && p.atrasado_dias;
      let extra = "";
      if (done && f.concluido_em) extra = `<div class="g-tick" style="left:${pct(f.concluido_em, MIN, MAX)}%" title="${escapeHtml(t("proj.fase.concluidaem"))} ${fmt(f.concluido_em)}"></div>`;
      return `<div class="g-row">
        <div class="g-lbl" style="font-size:11px">${escapeHtml(t(k))}${late ? `<span class="sub late">${escapeHtml(t("proj.atrasada"))} ${p.atrasado_dias}d</span>` : ""}</div>
        <div class="g-track">${barra(MIN, MAX, f.previsto_inicio, fim, cls + (aberta ? " open" : ""), `${t(k)}: ${t("proj.crono.previsto")} ${fmt(f.previsto_inicio)} → ${f.previsto_fim ? fmt(f.previsto_fim) : t("proj.crono.aberto")}`)}
        ${extra}
        ${p.proximo_marco_data && cur ? `<div class="g-marco" style="left:${pct(p.proximo_marco_data, MIN, MAX)}%" title="${escapeHtml(t("proj.marco.prefix"))} ${escapeHtml(p.proximo_marco_texto || "")} — ${fmt(p.proximo_marco_data)}"></div>` : ""}
        </div>
      </div>`;
    }).join("");
    const legenda = `<div class="g-legend">
      <span><i class="sw-fconcluida"></i>${escapeHtml(t("proj.legend.faseconcluida"))}</span>
      <span><i class="sw-tick"></i>${escapeHtml(t("proj.legend.concluisaoreal"))}</span>
      <span><i class="sw-fatual"></i>${escapeHtml(t("proj.legend.faseatual"))}</span>
      <span><i class="sw-previsto"></i>${escapeHtml(t("proj.legend.previsto"))}</span>
      <span><i class="sw-marco"></i>${escapeHtml(t("proj.legend.marco"))}</span>
      <span><i class="sw-hoje"></i>${escapeHtml(t("proj.legend.hoje"))}</span>
    </div>`;
    return ganttShell(MIN, MAX, rows, legenda) + `<p style="font-size:11.5px;color:var(--text3);margin-top:10px">${escapeHtml(t("proj.crono.hint"))}</p>`;
  }

  function paneRollout(p, rs) {
    const regioes = [...new Set(p.rollout.map((f) => f.filial_regiao))];
    const chip = (f) => {
      const dt = f.data ? `<small>${fmtCurto(f.data)}</small>` : "";
      return f.status === "nao_se_aplica"
        ? `<span class="fchip st-nao_se_aplica" title="${escapeHtml(t(ST_LBL_KEY[f.status]))}">${escapeHtml(f.filial_nome)}</span>`
        : `<button type="button" class="fchip st-${f.status}" data-fil="${f.filial_id}" title="${escapeHtml(t(ST_LBL_KEY[f.status]))}">${escapeHtml(f.filial_nome)}${dt}</button>`;
    };
    const grupos = regioes.map((r) => `<div class="ro-reg"><h5>${escapeHtml(r)}</h5><div class="ro-chips">${p.rollout.filter((f) => f.filial_regiao === r).map(chip).join("")}</div></div>`).join("");
    const filiaisDisponiveis = PJ.podeEditar ? PJ.filiais.filter((fl) => !p.rollout.some((r) => r.filial_id === fl.id)) : [];
    const incluir = PJ.podeEditar
      ? `<button type="button" class="fchip add-fchip" id="proj-btn-incluir-filial">+ ${escapeHtml(t("proj.roll.incluir"))}</button>`
      : "";
    return `
      <div class="ro-sum">
        <span class="item"><b>${rs.previstas}</b> ${escapeHtml(t("proj.roll.previstas"))}</span>
        <span class="item"><b>${rs.treinadas}</b> ${escapeHtml(t("proj.roll.treinadas"))}</span>
        <span class="item"><b>${rs.agendadas}</b> ${escapeHtml(t("proj.roll.agendadas"))}</span>
        <span class="item"><b>${rs.pendentes}</b> ${escapeHtml(t("proj.roll.pendentes"))}</span>
        ${rs.nao_se_aplica ? `<span class="item">${rs.nao_se_aplica} ${escapeHtml(t("proj.roll.naoaplica"))}</span>` : ""}
        <span class="bar"><span class="mrbar"><i style="width:${rs.pct}%"></i></span><b>${rs.pct}%</b></span>
        <span class="item">${
          rs.proximo_treinamento
            ? `${escapeHtml(t("proj.roll.proximotreinamento"))}: <b>${escapeHtml(rs.proximo_treinamento.filial_nome)} — ${fmt(rs.proximo_treinamento.data)}</b>`
            : rs.previstas === 0
              ? `<b>${escapeHtml(t("proj.roll.semescopo"))}</b>`
              : rs.pendentes > 0
                ? `<b>${escapeHtml(t("proj.roll.semagendamento"))}</b>`
                : `<b>${escapeHtml(t("proj.rollout.concluido"))}</b>`
        }</span>
      </div>
      <div class="ro-filtros">
        <button class="on" data-st="">${escapeHtml(t("proj.roll.filtro.todas"))} (${p.rollout.length})</button>
        <button data-st="treinada">${escapeHtml(t("proj.roll.treinadas"))} (${rs.treinadas})</button>
        <button data-st="agendada">${escapeHtml(t("proj.roll.agendadas"))} (${rs.agendadas})</button>
        <button data-st="pendente">${escapeHtml(t("proj.roll.pendentes"))} (${rs.pendentes})</button>
        ${rs.nao_se_aplica ? `<button data-st="nao_se_aplica">${escapeHtml(t("proj.roll.naoaplica"))} (${rs.nao_se_aplica})</button>` : ""}
        <span class="proj-toolbar-spacer"></span>
        ${incluir}
      </div>
      <div class="ro-det" id="ro-det" hidden></div>
      ${grupos}
      <p style="font-size:11.5px;color:var(--text3);margin-top:4px">${escapeHtml(t("proj.roll.hint"))}</p>`;
  }

  function ligarAbaRollout(p, rs) {
    const body = document.getElementById("proj-body");
    const roDet = document.getElementById("ro-det");
    if (!roDet) return;
    let filSel = null;

    function mostrarFilial(filialId) {
      const f = p.rollout.find((x) => x.filial_id === filialId);
      if (!f) { roDet.hidden = true; return; }
      let html = `<b>${escapeHtml(f.filial_nome)}</b> (${escapeHtml(f.filial_uf || "—")}) — ${escapeHtml(t(ST_LBL_KEY[f.status]))}` +
        (f.data ? `${f.status === "agendada" ? ` ${t("proj.roll.para")}` : ` ${t("proj.roll.em")}`} <b>${fmt(f.data)}</b>` : "") +
        (f.publico_treinado ? ` · ${escapeHtml(t("proj.roll.publico"))}: ${escapeHtml(f.publico_treinado)}` : "") +
        (f.key_user_local ? ` · ${escapeHtml(t("proj.roll.keyuserlocal"))}: <b>${escapeHtml(f.key_user_local)}</b>` : "");
      if (PJ.podeEditar) {
        html += `<div class="ro-edit">
          <label>${escapeHtml(t("proj.roll.data"))} <input type="date" id="re-data" value="${f.data || ""}"></label>
          <label>${escapeHtml(t("proj.roll.publico"))} <input type="text" id="re-publico" value="${escapeHtml(f.publico_treinado || "")}"></label>
          <label>${escapeHtml(t("proj.roll.keyuserlocal"))} <input type="text" id="re-keyuser" value="${escapeHtml(f.key_user_local || "")}"></label>
          <label><input type="checkbox" id="re-naoaplica" ${f.nao_se_aplica ? "checked" : ""}> ${escapeHtml(t("proj.roll.naoaplica"))}</label>
          <button type="button" class="btn-primary inline" id="re-salvar">${escapeHtml(t("admin.modal.save"))}</button>
          <button type="button" class="btn-ghost" id="re-remover">${escapeHtml(t("proj.roll.remover"))}</button>
        </div>`;
      }
      roDet.innerHTML = html;
      roDet.hidden = false;

      const btnSalvar = document.getElementById("re-salvar");
      if (btnSalvar) btnSalvar.addEventListener("click", async () => {
        try {
          await api("PATCH", `/api/projetos-ia/${encodeURIComponent(p.slug)}/rollout/${filialId}`, {
            data: document.getElementById("re-data").value || null,
            publico_treinado: document.getElementById("re-publico").value || null,
            key_user_local: document.getElementById("re-keyuser").value || null,
            nao_se_aplica: document.getElementById("re-naoaplica").checked,
          });
          await recarregarProjeto(p.slug);
          render();
        } catch (e) { alert(t("admin.save.fail") + ": " + e.message); }
      });
      const btnRemover = document.getElementById("re-remover");
      if (btnRemover) btnRemover.addEventListener("click", async () => {
        if (!confirm(t("proj.roll.confirmremover"))) return;
        try {
          await api("DELETE", `/api/projetos-ia/${encodeURIComponent(p.slug)}/rollout/${filialId}`);
          await recarregarProjeto(p.slug);
          render();
        } catch (e) { alert(t("admin.save.fail") + ": " + e.message); }
      });
    }

    body.querySelectorAll(".fchip[data-fil]").forEach((ch) => ch.addEventListener("click", () => {
      const filialId = Number(ch.dataset.fil);
      body.querySelectorAll(".fchip.sel").forEach((el) => el.classList.remove("sel"));
      if (filSel === filialId) { filSel = null; roDet.hidden = true; return; }
      filSel = filialId;
      ch.classList.add("sel");
      mostrarFilial(filialId);
    }));

    body.querySelectorAll(".ro-filtros button[data-st]").forEach((b) => b.addEventListener("click", () => {
      const st = b.dataset.st;
      body.querySelectorAll(".ro-filtros button[data-st]").forEach((x) => x.classList.toggle("on", x === b));
      body.querySelectorAll(".fchip").forEach((ch) => {
        const chipSt = [...ch.classList].find((c) => c.startsWith("st-"))?.slice(3) || "";
        ch.style.display = !st || chipSt === st ? "" : "none";
      });
      body.querySelectorAll(".ro-reg").forEach((rg) => {
        const algum = [...rg.querySelectorAll(".fchip")].some((ch) => ch.style.display !== "none");
        rg.style.display = algum ? "" : "none";
      });
    }));

    const btnIncluir = document.getElementById("proj-btn-incluir-filial");
    if (btnIncluir) btnIncluir.addEventListener("click", () => abrirModalIncluirFilial(p));
  }

  /* ==================================================================
     Modais (novo/editar projeto, incluir filial) — reaproveitam
     #proj-modal-overlay, com sua própria lógica de save/erro.
     ================================================================== */
  const MODAL = { onSave: null };

  function abrirModal(titleKey, buildBody, onSave) {
    document.getElementById("proj-modal-title").textContent = t(titleKey);
    document.getElementById("proj-modal-form").innerHTML = buildBody();
    document.getElementById("proj-modal-error").textContent = "";
    MODAL.onSave = onSave;
    document.getElementById("proj-modal-overlay").classList.add("visible");
  }
  function fecharModal() {
    document.getElementById("proj-modal-overlay").classList.remove("visible");
    MODAL.onSave = null;
  }

  function campoTexto(id, labelKey, val, required) {
    return `<div class="form-field"><label for="${id}">${escapeHtml(t(labelKey))}</label>
      <input id="${id}" value="${escapeHtml(val || "")}" ${required ? "required" : ""}></div>`;
  }
  function campoArea(id, labelKey, val, required) {
    return `<div class="form-field"><label for="${id}">${escapeHtml(t(labelKey))}</label>
      <textarea id="${id}" ${required ? "required" : ""}>${escapeHtml(val || "")}</textarea></div>`;
  }
  function campoData(id, labelKey, val) {
    return `<div class="form-field"><label for="${id}">${escapeHtml(t(labelKey))}</label>
      <input type="date" id="${id}" value="${val || ""}"></div>`;
  }

  function linhasFasesForm(fases) {
    return FASES.map((k, i) => {
      const f = fases ? fases[i] : null;
      return `<div class="row-2" style="margin-bottom:8px">
        <div class="form-field" style="margin-bottom:0">
          <label>${escapeHtml(t(k))} — ${escapeHtml(t("proj.f.previstoinicio"))}</label>
          <input type="date" id="pf-inicio-${i}" value="${f ? f.previsto_inicio || "" : ""}" required>
        </div>
        <div class="form-field" style="margin-bottom:0">
          <label>${escapeHtml(t("proj.f.previstofim"))}${i === FASES.length - 1 ? ` (${escapeHtml(t("proj.f.opcional"))})` : ""}</label>
          <input type="date" id="pf-fim-${i}" value="${f ? f.previsto_fim || "" : ""}">
        </div>
      </div>`;
    }).join("");
  }

  function abrirModalNovoProjeto() {
    abrirModal("proj.modal.novo", () => `
      ${campoTexto("pf-slug", "proj.f.slug", "", true)}
      ${campoTexto("pf-nome", "proj.f.nome", "", true)}
      ${campoTexto("pf-area", "proj.f.area", "", true)}
      ${campoTexto("pf-objetivo", "proj.f.objetivo", "", true)}
      ${campoArea("pf-problema", "proj.f.problema", "", true)}
      ${campoArea("pf-beneficio", "proj.f.beneficio", "", true)}
      ${campoArea("pf-publico", "proj.f.publico", "", true)}
      <div class="row-2">
        ${campoTexto("pf-acelerador", "proj.f.acelerador", "", true)}
        ${campoTexto("pf-ti", "proj.f.ti", "")}
      </div>
      <div class="row-2">
        ${campoTexto("pf-keyuser", "proj.f.keyuser", "")}
        ${campoTexto("pf-marcotexto", "proj.f.marcotexto", "")}
      </div>
      ${campoData("pf-marcodata", "proj.f.marcodata", "")}
      <fieldset class="mtx-fs"><legend>${escapeHtml(t("proj.f.plano"))}</legend>${linhasFasesForm(null)}</fieldset>
    `, async () => {
      const plano = FASES.map((_, i) => ({
        previsto_inicio: document.getElementById(`pf-inicio-${i}`).value,
        previsto_fim: document.getElementById(`pf-fim-${i}`).value || null,
      }));
      const body = {
        slug: document.getElementById("pf-slug").value.trim(),
        nome: document.getElementById("pf-nome").value.trim(),
        area: document.getElementById("pf-area").value.trim(),
        objetivo: document.getElementById("pf-objetivo").value.trim(),
        problema: document.getElementById("pf-problema").value.trim(),
        beneficio: document.getElementById("pf-beneficio").value.trim(),
        publico: document.getElementById("pf-publico").value.trim(),
        acelerador: document.getElementById("pf-acelerador").value.trim(),
        responsavel_ti: document.getElementById("pf-ti").value.trim() || null,
        key_user: document.getElementById("pf-keyuser").value.trim() || null,
        proximo_marco_texto: document.getElementById("pf-marcotexto").value.trim() || null,
        proximo_marco_data: document.getElementById("pf-marcodata").value || null,
        plano,
      };
      const criado = await api("POST", "/api/projetos-ia", body);
      PJ.projetos.push(criado);
      fecharModal();
      abrirDetalhe(criado.slug);
    });
  }

  function abrirModalEditarProjeto(p) {
    abrirModal("proj.modal.editar", () => `
      ${campoTexto("pf-nome", "proj.f.nome", p.nome, true)}
      ${campoTexto("pf-area", "proj.f.area", p.area, true)}
      ${campoTexto("pf-objetivo", "proj.f.objetivo", p.objetivo, true)}
      ${campoArea("pf-problema", "proj.f.problema", p.problema, true)}
      ${campoArea("pf-beneficio", "proj.f.beneficio", p.beneficio, true)}
      ${campoArea("pf-publico", "proj.f.publico", p.publico, true)}
      <div class="row-2">
        ${campoTexto("pf-acelerador", "proj.f.acelerador", p.acelerador, true)}
        ${campoTexto("pf-ti", "proj.f.ti", p.responsavel_ti)}
      </div>
      <div class="row-2">
        ${campoTexto("pf-keyuser", "proj.f.keyuser", p.key_user)}
        ${campoTexto("pf-marcotexto", "proj.f.marcotexto", p.proximo_marco_texto)}
      </div>
      ${campoData("pf-marcodata", "proj.f.marcodata", p.proximo_marco_data)}
      <fieldset class="mtx-fs"><legend>${escapeHtml(t("proj.f.fases"))}</legend>
        ${FASES.map((k, i) => {
          const f = p.fases[i];
          return `<div style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px dashed var(--border)">
            <div style="font-size:12px;font-weight:700;margin-bottom:6px">${escapeHtml(t(k))}</div>
            <div class="row-2" style="margin-bottom:6px">
              <div class="form-field" style="margin-bottom:0"><label>${escapeHtml(t("proj.f.previstoinicio"))}</label><input type="date" id="ef-inicio-${i}" value="${f.previsto_inicio || ""}" required></div>
              <div class="form-field" style="margin-bottom:0"><label>${escapeHtml(t("proj.f.previstofim"))}</label><input type="date" id="ef-fim-${i}" value="${f.previsto_fim || ""}"></div>
            </div>
            <div class="row-2">
              <div class="form-field" style="margin-bottom:0"><label>${escapeHtml(t("proj.fase.concluir"))}</label><input type="date" id="ef-concluido-${i}" value="${f.concluido_em || ""}"></div>
              <div class="form-field" style="margin-bottom:0"><label>${escapeHtml(t("proj.fase.observacao"))}</label><input type="text" id="ef-obs-${i}" value="${escapeHtml(f.observacao || "")}"></div>
            </div>
          </div>`;
        }).join("")}
      </fieldset>
    `, async () => {
      await api("PATCH", `/api/projetos-ia/${encodeURIComponent(p.slug)}`, {
        nome: document.getElementById("pf-nome").value.trim(),
        area: document.getElementById("pf-area").value.trim(),
        objetivo: document.getElementById("pf-objetivo").value.trim(),
        problema: document.getElementById("pf-problema").value.trim(),
        beneficio: document.getElementById("pf-beneficio").value.trim(),
        publico: document.getElementById("pf-publico").value.trim(),
        acelerador: document.getElementById("pf-acelerador").value.trim(),
        responsavel_ti: document.getElementById("pf-ti").value.trim() || null,
        key_user: document.getElementById("pf-keyuser").value.trim() || null,
        proximo_marco_texto: document.getElementById("pf-marcotexto").value.trim() || null,
        proximo_marco_data: document.getElementById("pf-marcodata").value || null,
      });
      for (let i = 0; i < FASES.length; i++) {
        const f = p.fases[i];
        const novo = {
          previsto_inicio: document.getElementById(`ef-inicio-${i}`).value || null,
          previsto_fim: document.getElementById(`ef-fim-${i}`).value || null,
          concluido_em: document.getElementById(`ef-concluido-${i}`).value || null,
          observacao: document.getElementById(`ef-obs-${i}`).value.trim() || null,
        };
        const mudou = novo.previsto_inicio !== (f.previsto_inicio || null) ||
          novo.previsto_fim !== (f.previsto_fim || null) ||
          novo.concluido_em !== (f.concluido_em || null) ||
          novo.observacao !== (f.observacao || null);
        if (mudou) await api("PATCH", `/api/projetos-ia/${encodeURIComponent(p.slug)}/fases/${i}`, novo);
      }
      await recarregarProjeto(p.slug);
      fecharModal();
      render();
    });
  }

  function abrirModalIncluirFilial(p) {
    const disponiveis = PJ.filiais.filter((fl) => !p.rollout.some((r) => r.filial_id === fl.id));
    abrirModal("proj.roll.incluir", () => `
      <div class="form-field"><label for="rf-filial">${escapeHtml(t("proj.roll.filial"))}</label>
        <select id="rf-filial" required>
          ${disponiveis.map((fl) => `<option value="${fl.id}">${escapeHtml(fl.nome)} (${escapeHtml(fl.uf || "—")})</option>`).join("")}
        </select>
      </div>
      ${disponiveis.length === 0 ? `<p class="field-hint">${escapeHtml(t("proj.roll.semdisponiveis"))}</p>` : ""}
    `, async () => {
      const filialId = Number(document.getElementById("rf-filial").value);
      if (!filialId) throw new Error(t("proj.roll.semdisponiveis"));
      await api("POST", `/api/projetos-ia/${encodeURIComponent(p.slug)}/rollout`, { filial_id: filialId });
      await recarregarProjeto(p.slug);
      fecharModal();
      render();
    });
  }

  /* ---------- Wiring do modal e da tela ---------- */
  document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("proj-modal-overlay");
    const fechar = () => fecharModal();
    document.getElementById("proj-modal-close").addEventListener("click", fechar);
    document.getElementById("proj-modal-cancel").addEventListener("click", fechar);
    document.getElementById("proj-modal-save").addEventListener("click", async () => {
      const erroEl = document.getElementById("proj-modal-error");
      erroEl.textContent = "";
      const btn = document.getElementById("proj-modal-save");
      const form = document.getElementById("proj-modal-form");
      if (!form.reportValidity()) return;
      btn.disabled = true;
      btn.textContent = t("admin.modal.saving");
      try {
        if (MODAL.onSave) await MODAL.onSave();
      } catch (e) {
        erroEl.textContent = e.message || t("admin.save.fail");
      } finally {
        btn.disabled = false;
        btn.textContent = t("admin.modal.save");
      }
    });
    let mouseDownTarget = null;
    overlay.addEventListener("mousedown", (ev) => { mouseDownTarget = ev.target; });
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay && mouseDownTarget === overlay) fechar();
      mouseDownTarget = null;
    });
  });
})();
