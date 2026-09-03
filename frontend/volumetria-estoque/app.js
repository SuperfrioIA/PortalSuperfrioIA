/* Volumetria de Estoque — tela sobre backend/volumetria_estoque/.
 *
 * Irmã de frontend/volumetria-transporte/app.js — mesma estrutura (selects
 * nativos, árvore montada aqui a partir de linhas achatadas). A diferença
 * real: os valores que chegam do backend já são POSIÇÃO (a foto do último
 * dia com dado de cada mês, uma linha por unidade/cliente/câmara/mês — ver
 * backend/volumetria_estoque/matriz.py), não algo para somar por dia. A
 * árvore aqui soma só entre NÓS DA HIERARQUIA (câmara → cliente → unidade),
 * nunca entre meses nem entre dias — isso o backend já resolveu.
 */
const API = '/api/volumetria-estoque';
const $ = (s) => document.querySelector(s);

const FILTROS_CAIXAS = ['unidade', 'cliente', 'camara', 'status_lote'];

let OPCOES = null;
let PODE_EXPORTAR = false;

const ESTADO = {
  de: '', ate: '', dia: [], lente: 'liq',
  unidade: [], cliente: [], camara: [], status_lote: [],
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
  popularSelect('camara', OPCOES.camaras);
  popularSelect('status_lote', OPCOES.status_lote);

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
      <li><strong>A Matriz é POSIÇÃO, não soma.</strong> Cada célula mostra a
      foto do <strong>último dia com dado</strong> de cada mês, dentro do
      recorte — não a soma dos dias do mês. É assim porque a tabela é um
      saldo diário (a mesma posição registrada todo dia), e somar 30 fotos
      contaria o mesmo estoque 30 vezes.</li>
      <li>Por isso <strong>não existe total anual</strong> nem "soma da
      planilha bate com a Matriz": a planilha mostra todo dia cru do
      recorte, a Matriz mostra só o último de cada mês.</li>
      <li>O filtro de <strong>dia do mês</strong> aqui significa "a foto
      daquele dia", não "só aqueles dias somados".</li>
      <li><strong>"(sem câmara)"</strong> é uma opção de filtro própria — a
      coluna aceita linha sem câmara informada, e essa linha nunca some do
      total.</li>
      <li>Download exige a permissão de exportar; consultar a Matriz e a
      planilha só exige acesso ao app.</li>
    </ul>`;

  try {
    const rp = await fetch('/api/auth/me/permissoes', {headers: cabecalhoAuth()});
    const permissoes = rp.ok ? await rp.json() : [];
    PODE_EXPORTAR = (permissoes.permissoes || permissoes || []).includes('volumetria-estoque:exportar');
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
    if (!raiz.has(l.unidade)) raiz.set(l.unidade, {total: {}, clientes: new Map()});
    const u = raiz.get(l.unidade);
    u.total[l.mes] = (u.total[l.mes] || 0) + valor;

    if (!u.clientes.has(l.cliente)) {
      u.clientes.set(l.cliente, {rotulo: l.cliente_rotulo, total: {}, camaras: new Map()});
    }
    const c = u.clientes.get(l.cliente);
    c.total[l.mes] = (c.total[l.mes] || 0) + valor;

    if (!c.camaras.has(l.camara)) c.camaras.set(l.camara, {total: {}, dias: {}});
    const cam = c.camaras.get(l.camara);
    cam.total[l.mes] = (cam.total[l.mes] || 0) + valor;
    cam.dias[l.mes] = l.dia;
  }
  return raiz;
}

function fmt(n) {
  return Number(n || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function fmtData(iso) {
  if (!iso) return '';
  const [a, m, d] = iso.split('-');
  return `${d}/${m}/${a}`;
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
    corpo += `<tr class="n0"><td class="rotulo">${unidade}</td>`
      + meses.map((m) => `<td>${u.total[m] ? fmt(u.total[m]) : '<span class="vazio">—</span>'}</td>`).join('')
      + '</tr>';
    for (const m of meses) totalGeral[m] = (totalGeral[m] || 0) + (u.total[m] || 0);

    for (const [, c] of [...u.clientes].sort((a, b) => a[1].rotulo.localeCompare(b[1].rotulo))) {
      corpo += `<tr class="n1"><td class="rotulo" style="--recuo:14px">${c.rotulo}</td>`
        + meses.map((m) => `<td>${c.total[m] ? fmt(c.total[m]) : '<span class="vazio">—</span>'}</td>`).join('')
        + '</tr>';
      for (const [camara, cam] of [...c.camaras].sort((a, b) => a[0].localeCompare(b[0]))) {
        corpo += `<tr class="n2"><td class="rotulo" style="--recuo:28px">${camara}</td>`
          + meses.map((m) => {
              const v = cam.total[m];
              const titulo = v ? ` title="Posição de ${fmtData(cam.dias[m])}"` : '';
              return `<td${titulo}>${v ? fmt(v) : '<span class="vazio">—</span>'}</td>`;
            }).join('')
          + '</tr>';
      }
    }
  }

  const rodape = `<tr><td class="rotulo">Total (${dados.lente.nome}, ${dados.lente.unidade}) — soma das posições, não histórico</td>`
    + meses.map((m) => `<td>${fmt(totalGeral[m])}</td>`).join('') + '</tr>';

  $('.rolagem').innerHTML = `<table>
    <thead><tr><th class="rotulo">Unidade / Cliente / Câmara</th>${th}</tr></thead>
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

  $('#titulo').textContent = ESTADO.aba === 'matriz' ? 'Matriz (posição de fim de mês)' : 'Planilha';
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
