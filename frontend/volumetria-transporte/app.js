/* Volumetria de Transporte — tela sobre backend/volumetria_transporte/.
 *
 * Irmã de frontend/volumetria-catering/app.js, mas escrita do zero (T1 não
 * foi feito, não há engine compartilhado) e mais simples em dois pontos
 * deliberados:
 *
 * - filtros são `<select multiple>` nativos, não o painel "caixas" do
 *   catering — a maior cardinalidade medida no T0 (unidade) tem 6 opções,
 *   então o widget mais elaborado não paga o custo aqui;
 * - a Matriz chega do backend como LINHAS ACHATADAS
 *   (`{unidade, cliente, tipo_movimento, mes, valor, linhas}`), e é este
 *   arquivo que monta a árvore — o backend não pré-monta (ver matriz.py).
 *   A árvore renderiza sempre expandida (sem os botões de abrir/fechar do
 *   catering): primeira versão, funcional, sem a interação extra.
 */
const API = '/api/volumetria-transporte';
const $ = (s) => document.querySelector(s);

const FILTROS_CAIXAS = [
  'unidade', 'cliente', 'tipo_estoque', 'tipo_movimento',
  'tipo_viagem', 'status_viagem', 'status_wms', 'status_baixa',
];

let OPCOES = null;
let PODE_EXPORTAR = false;

const ESTADO = {
  de: '', ate: '', dia: [], lente: 'liq',
  unidade: [], cliente: [], tipo_estoque: [], tipo_movimento: [],
  tipo_viagem: [], status_viagem: [], status_wms: [], status_baixa: [],
  pagina: 1, aba: 'matriz',
};

class RespostaRecusada extends Error {}

const cabecalhoAuth = () => {
  const token = localStorage.getItem('sf_portal_token') || '';
  return token ? {'Authorization': 'Bearer ' + token} : {};
};

async function detalhe(resposta) {
  try { return (await resposta.json()).detail || resposta.statusText; }
  catch (e) { return resposta.statusText; }
}

const SAIDA_HUB = '<a href="/" target="_top">Voltar ao hub</a>';

function mostraBloqueio(status, causa) {
  const texto = {
    401: '<strong>Sua sessão expirou.</strong><br>Entre de novo no portal para '
       + `ver a volumetria — o login mora fora desta tela. ${SAIDA_HUB}.`,
    403: `<strong>Sem acesso a este painel.</strong><br>${causa}`,
    503: '<strong>O painel está indisponível.</strong><br>'
       + `${causa}<br>O restante do Hub continua funcionando. ${SAIDA_HUB}.`,
  }[status];
  $('.rolagem').innerHTML = `<div class="erro">${texto}</div>`;
  $('#paginacao').innerHTML = '';
}

async function busca(url, opcoes = {}) {
  const resposta = await fetch(url, {
    ...opcoes,
    headers: {...cabecalhoAuth(), ...(opcoes.headers || {})},
  });
  if ([401, 403, 503].includes(resposta.status)) {
    mostraBloqueio(resposta.status, await detalhe(resposta));
    throw new RespostaRecusada(String(resposta.status));
  }
  return resposta;
}

/* ------------------------------------------------------- selects nativos */
function popularSelect(id, valores) {
  const el = $('#' + id);
  el.innerHTML = '';
  for (const v of valores) {
    const opt = document.createElement('option');
    if (typeof v === 'object') { opt.value = v.chave; opt.textContent = v.rotulo; }
    else { opt.value = v; opt.textContent = v; }
    el.appendChild(opt);
  }
}

function selecionados(id) {
  return [...$('#' + id).selectedOptions].map((o) => o.value);
}

function aplicaSelecao(id, valores) {
  const el = $('#' + id);
  const conjunto = new Set(valores);
  for (const opt of el.options) opt.selected = conjunto.has(opt.value);
}

/* ------------------------------------------------------------- parâmetros */
function parametros() {
  const p = new URLSearchParams();
  p.set('de', ESTADO.de);
  p.set('ate', ESTADO.ate);
  p.set('lente', ESTADO.lente);
  p.set('pagina', String(ESTADO.pagina));
  for (const d of ESTADO.dia) p.append('dia', d);
  for (const id of FILTROS_CAIXAS) for (const v of ESTADO[id]) p.append(id, v);
  return p;
}

function parametrosDownload(formato) {
  const p = parametros();
  p.delete('pagina');
  p.set('formato', formato);
  return p;
}

/* ------------------------------------------------------------------ opções */
async function carregaOpcoes() {
  const r = await busca(API + '/opcoes');
  OPCOES = await r.json();

  ESTADO.de = OPCOES.abertura.de;
  ESTADO.ate = OPCOES.abertura.ate;
  $('#de').value = ESTADO.de;
  $('#ate').value = ESTADO.ate;

  const diaOpcoes = Array.from({length: 31}, (_, i) => String(i + 1).padStart(2, '0'));
  popularSelect('dia', diaOpcoes);
  popularSelect('unidade', OPCOES.unidades);
  popularSelect('cliente', OPCOES.clientes);
  popularSelect('tipo_estoque', OPCOES.tipos_estoque);
  popularSelect('tipo_movimento', OPCOES.tipos_movimento);
  popularSelect('tipo_viagem', OPCOES.tipos_viagem);
  popularSelect('status_viagem', OPCOES.status_viagem);
  popularSelect('status_wms', OPCOES.status_wms);
  popularSelect('status_baixa', OPCOES.status_baixa);

  const grupo = $('#lente');
  grupo.innerHTML = '';
  for (const l of OPCOES.lentes) {
    const b = document.createElement('button');
    b.textContent = l.nome;
    b.setAttribute('aria-pressed', String(l.chave === ESTADO.lente));
    b.onclick = () => {
      ESTADO.lente = l.chave;
      [...grupo.children].forEach((c) => c.setAttribute('aria-pressed', String(c === b)));
    };
    grupo.appendChild(b);
  }

  $('#procedencia').textContent = OPCOES.atualizado_ate
    ? `Atualizado até ${OPCOES.atualizado_ate}`
    : 'Sem data de atualização informada pelo DW';

  $('#metodo').innerHTML = `
    <p>Fonte: <code>${OPCOES.contrato}</code>, lida direto do DW Oracle a cada
    consulta — sem banco intermediário no Hub.</p>
    <ul>
      <li>A Matriz agrupa por <strong>unidade → cliente → tipo de movimento</strong>,
      mês nas colunas.</li>
      <li>O filtro de <strong>dia do mês</strong> recorta DENTRO de cada mês do
      período — não substitui o período.</li>
      <li>A placa <code>&gt;&gt;&gt; SEM PLACA &lt;&lt;&lt;</code> do DW aparece
      na tela como <strong>"sem placa"</strong>.</li>
      <li>Download exige a permissão de exportar; consultar a Matriz e a
      planilha só exige acesso ao app.</li>
    </ul>`;

  try {
    const rp = await fetch('/api/auth/me/permissoes', {headers: cabecalhoAuth()});
    const permissoes = rp.ok ? await rp.json() : [];
    PODE_EXPORTAR = (permissoes.permissoes || permissoes || []).includes('volumetria-transporte:exportar');
  } catch (e) { PODE_EXPORTAR = false; }
  $('#baixar-csv').style.display = PODE_EXPORTAR ? '' : 'none';
  $('#baixar-xlsx').style.display = PODE_EXPORTAR ? '' : 'none';
  $('#nota-download').textContent = PODE_EXPORTAR
    ? '' : 'Sem permissão de exportar — peça a um administrador.';
}

/* -------------------------------------------------------------- a Matriz */
function constroiArvore(linhas) {
  const raiz = new Map();
  for (const l of linhas) {
    const valor = Number(l.valor || 0);
    if (!raiz.has(l.unidade)) raiz.set(l.unidade, {total: {}, linhas: 0, clientes: new Map()});
    const u = raiz.get(l.unidade);
    u.total[l.mes] = (u.total[l.mes] || 0) + valor;
    u.linhas += l.linhas;

    if (!u.clientes.has(l.cliente)) {
      u.clientes.set(l.cliente, {rotulo: l.cliente_rotulo, total: {}, linhas: 0, movimentos: new Map()});
    }
    const c = u.clientes.get(l.cliente);
    c.total[l.mes] = (c.total[l.mes] || 0) + valor;
    c.linhas += l.linhas;

    if (!c.movimentos.has(l.tipo_movimento)) c.movimentos.set(l.tipo_movimento, {total: {}, linhas: 0});
    const m = c.movimentos.get(l.tipo_movimento);
    m.total[l.mes] = (m.total[l.mes] || 0) + valor;
    m.linhas += l.linhas;
  }
  return raiz;
}

function fmt(n) {
  return Number(n || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function renderMatriz(dados) {
  const meses = Object.keys(dados.meses);
  const arvore = constroiArvore(dados.linhas);

  if (arvore.size === 0) {
    $('.rolagem').innerHTML = '<div class="carregando">Nenhuma linha neste recorte.</div>';
    $('#paginacao').innerHTML = '';
    return;
  }

  const th = meses.map((m) => `<th>${dados.meses[m]}</th>`).join('');
  let corpo = '';
  const totalGeral = {};

  for (const [unidade, u] of [...arvore].sort((a, b) => a[0].localeCompare(b[0]))) {
    corpo += `<tr class="n0"><td class="rotulo">${unidade} (${u.linhas} linha(s))</td>`
      + meses.map((m) => `<td>${u.total[m] ? fmt(u.total[m]) : '<span class="vazio">—</span>'}</td>`).join('')
      + '</tr>';
    for (const m of meses) totalGeral[m] = (totalGeral[m] || 0) + (u.total[m] || 0);

    for (const [, c] of [...u.clientes].sort((a, b) => a[1].rotulo.localeCompare(b[1].rotulo))) {
      corpo += `<tr class="n1"><td class="rotulo" style="--recuo:14px">${c.rotulo}</td>`
        + meses.map((m) => `<td>${c.total[m] ? fmt(c.total[m]) : '<span class="vazio">—</span>'}</td>`).join('')
        + '</tr>';
      for (const [tipoMov, mv] of [...c.movimentos].sort((a, b) => a[0].localeCompare(b[0]))) {
        corpo += `<tr class="n2"><td class="rotulo" style="--recuo:28px">${tipoMov}</td>`
          + meses.map((m) => `<td>${mv.total[m] ? fmt(mv.total[m]) : '<span class="vazio">—</span>'}</td>`).join('')
          + '</tr>';
      }
    }
  }

  const rodape = `<tr><td class="rotulo">Total (${dados.lente.nome}, ${dados.lente.unidade})</td>`
    + meses.map((m) => `<td>${fmt(totalGeral[m])}</td>`).join('') + '</tr>';

  $('.rolagem').innerHTML = `<table>
    <thead><tr><th class="rotulo">Unidade / Cliente / Movimento</th>${th}</tr></thead>
    <tbody>${corpo}</tbody>
    <tfoot>${rodape}</tfoot>
  </table>`;
  $('#paginacao').innerHTML = '';
}

/* ------------------------------------------------------------ a planilha */
function renderPlanilha(dados) {
  if (dados.linhas.length === 0) {
    $('.rolagem').innerHTML = '<div class="carregando">Nenhuma linha neste recorte.</div>';
    $('#paginacao').innerHTML = '';
    return;
  }
  const th = dados.colunas.map((c, i) =>
    `<th class="${i === 0 ? 'primeira' : ''}">${c.rotulo}</th>`).join('');
  const linhas = dados.linhas.map((l) => {
    const tds = dados.colunas.map((c, i) => {
      const v = l[c.chave];
      const cls = i === 0 ? 'primeira' : (typeof v === 'number' || c.chave === 'medida' ? 'numero' : 'texto');
      return `<td class="${cls}" title="${v ?? ''}">${v ?? ''}</td>`;
    }).join('');
    return `<tr>${tds}</tr>`;
  }).join('');
  $('.rolagem').innerHTML = `<table class="planilha">
    <thead><tr>${th}</tr></thead>
    <tbody>${linhas}</tbody>
  </table>`;

  const totalPaginas = dados.total_paginas;
  $('#paginacao').innerHTML = `
    <button class="secundario" id="pag-ant" ${ESTADO.pagina <= 1 ? 'disabled' : ''}>Anterior</button>
    <span>Página ${dados.pagina} de ${totalPaginas} — ${dados.total_linhas.toLocaleString('pt-BR')} linha(s)</span>
    <button class="secundario" id="pag-prox" ${ESTADO.pagina >= totalPaginas ? 'disabled' : ''}>Próxima</button>`;
  const ant = $('#pag-ant'); if (ant) ant.onclick = () => { ESTADO.pagina--; carrega(); };
  const prox = $('#pag-prox'); if (prox) prox.onclick = () => { ESTADO.pagina++; carrega(); };
}

/* ------------------------------------------------------------------ carga */
async function carrega() {
  $('.rolagem').innerHTML = '<div class="carregando">Carregando…</div>';
  const p = parametros();
  const endpoint = ESTADO.aba === 'matriz' ? '/matriz' : '/planilha';
  let r;
  try { r = await busca(`${API}${endpoint}?${p.toString()}`); }
  catch (e) { if (e instanceof RespostaRecusada) return; throw e; }
  const dados = await r.json();

  $('#titulo').textContent = ESTADO.aba === 'matriz' ? 'Matriz' : 'Planilha';
  $('#avisos').innerHTML = dados.aviso_dias ? `<div class="aviso">${dados.aviso_dias}</div>` : '';

  if (ESTADO.aba === 'matriz') renderMatriz(dados);
  else renderPlanilha(dados);
}

/* --------------------------------------------------------------- download */
async function baixa(formato) {
  const p = parametrosDownload(formato);
  let ticket;
  try {
    const r = await busca(API + '/download/ticket?' + p.toString(), {method: 'POST'});
    if (!r.ok) { alert('O download foi recusado: ' + await detalhe(r)); return; }
    ticket = (await r.json()).ticket;
  } catch (e) {
    if (!(e instanceof RespostaRecusada)) alert('Falha de rede ao preparar o download: ' + e);
    return;
  }
  p.set('ticket', ticket);
  window.location = API + '/download?' + p.toString();
}

/* --------------------------------------------------------------------- UI */
function leEstadoDosFiltros() {
  ESTADO.de = $('#de').value;
  ESTADO.ate = $('#ate').value;
  ESTADO.dia = selecionados('dia');
  for (const id of FILTROS_CAIXAS) ESTADO[id] = selecionados(id);
}

async function inicia() {
  await carregaOpcoes();

  $('#aplicar').onclick = () => { leEstadoDosFiltros(); ESTADO.pagina = 1; carrega(); };
  $('#limpar').onclick = () => {
    $('#de').value = OPCOES.abertura.de;
    $('#ate').value = OPCOES.abertura.ate;
    for (const id of ['dia', ...FILTROS_CAIXAS]) aplicaSelecao(id, []);
    leEstadoDosFiltros();
    ESTADO.pagina = 1;
    carrega();
  };
  $('#aba-matriz').onclick = () => {
    ESTADO.aba = 'matriz'; ESTADO.pagina = 1;
    $('#aba-matriz').setAttribute('aria-pressed', 'true');
    $('#aba-planilha').setAttribute('aria-pressed', 'false');
    carrega();
  };
  $('#aba-planilha').onclick = () => {
    ESTADO.aba = 'planilha'; ESTADO.pagina = 1;
    $('#aba-matriz').setAttribute('aria-pressed', 'false');
    $('#aba-planilha').setAttribute('aria-pressed', 'true');
    carrega();
  };
  $('#baixar-csv').onclick = () => baixa('csv');
  $('#baixar-xlsx').onclick = () => baixa('xlsx');

  carrega();
}

inicia().catch((e) => { if (!(e instanceof RespostaRecusada)) throw e; });
