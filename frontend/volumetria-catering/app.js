// Volumetria de catering — tela do Hub (lote H2 de docs/PLANO_VOLUMETRIA_CATERING.md).
//
// Porte do `<script>` inline de `catering/web/matriz.html` da nuvem-ia (main de
// 27/ago/2026, após o V3.7.3). Arquivo externo porque o CSP do portal é
// `script-src 'self'`: inline não roda, e a tela abriria em branco sem erro
// visível.
//
// O que mudou do original, e por quê:
//
// - a base da API virou `/api/volumetria-catering` (o módulo tem prefixo aqui);
// - autenticação é o `Authorization: Bearer` do portal, em `busca()` — um lugar
//   só. A V3 usava cookie de sessão, que o Hub não tem;
// - `/api/eu` não existe no Hub: quem sabe o que a pessoa pode é o endpoint
//   global `/api/auth/me/permissoes`, e ele só decide se o download aparece.
//   Nome, papel, "Sair" e link de Administração saíram da tela — identidade é
//   da shell do portal, não de cada app;
// - 401/403/503 ganham mensagem própria em vez de "Recorte recusado", e 401 NÃO
//   navega para /login (dentro do iframe daria frame em branco);
// - o download passa por um **ticket de curta duração**: navegação não carrega
//   header `Authorization`, e o CSV precisa continuar saindo em streaming (ver
//   `baixa()` no fim do arquivo).
//
// A tela nunca renderiza identificador cru e nunca soma nada: todo total vem
// do backend (lição do V2.1). Aqui só há formatação e navegação.
const $ = s => document.querySelector(s);

// O módulo tem prefixo próprio no Hub; a V3 respondia na raiz.
const API = '/api/volumetria-catering';
// A célula da matriz de acesso que libera o download (na V3, qualquer logado
// baixava — trazer isso para uma permissão foi um dos motivos do porte).
const PERMISSAO_EXPORTAR = 'volumetria-catering:exportar';
const ROTULO_NIVEL = {unidade:'Unidade', cliente:'Cliente', faixa:'Faixa',
                     operacao:'Operação', tipo_estoque:'Tipo de estoque',
                     movimento:'Movimento'};
// O terceiro movimento e "as duas juntas" (V3.7.2). O rotulo e a regra de "so
// na Matriz" vem do backend (`/api/opcoes`), para nao existirem em duas copias.
const CONJUNTA = 'amb';
const trilha = niveis => niveis.map(n => ROTULO_NIVEL[n] || n).join(' › ');

/* O aviso do zero a esquerda fica no controle do CSV, nao numa parede de texto:
   e uma ressalva que muda como o arquivo e LIDO, entao vive onde ela e lida. O
   xlsx nao tem o problema, e a nota diz por que. */
const NOTA_DOWNLOAD =
  'O CSV sai no recorte inteiro, em streaming. Atenção: o Excel corta o zero à '
  + 'esquerda de guia e CNPJ ao abrir CSV por duplo clique — para conferir '
  + 'identificador, baixe em Excel (xlsx), que preserva.';
const NOTA_DOWNLOAD_CONJUNTA =
  'O download responde por um movimento por vez: as duas tabelas do DW têm 36 e '
  + '46 colunas, então não existe linha crua "entrada + saída". Escolha Entrada '
  + 'ou Saída para baixar. A soma dos dois é uma leitura da Matriz, que agrega.';
// Novo no Hub: baixar é uma célula da matriz de acesso. A nota diz o que pedir,
// e a quem — em vez de deixar a pessoa achar que o botão sumiu por defeito.
const NOTA_SEM_EXPORTAR =
  'Baixar o recorte exige a permissão "exportar" deste app. Consultar a Matriz e '
  + 'a planilha na tela não exige — peça a um administrador do portal se você '
  + 'precisa do arquivo.';

let OPCOES = null, ESTADO = {
  visao:'matriz', movimento:'rec', lente:'liq', faixa:'solicitado',
  pagina:1, abertos:new Set()
};

// AAAA-MM-DD -> DD/MM/AAAA. A API fala ISO; a tela fala como quem le.
const dataBR = iso => iso.split('-').reverse().join('/');

// Limpar volta para o MESMO padrao com que a tela abriu, e nao para o periodo
// inteiro do banco: "limpar filtro" tem que devolver a tela que a pessoa
// recebeu, senao o botao vira uma terceira coisa que ninguem pediu.
function abreNoPadrao(){
  $('#de').value = OPCOES.abertura.de;
  $('#ate').value = OPCOES.abertura.ate;
}

const fmt = (valor, unidade) => {
  if (valor === null || valor === undefined) return '<span class="vazio">—</span>';
  let n = Number(valor);
  if (unidade === 't') { n = n / 1000; }          // a fonte manda kg
  const casas = unidade === 't' ? 1 : (unidade === 'R$' ? 0 : 0);
  return n.toLocaleString('pt-BR', {minimumFractionDigits:casas, maximumFractionDigits:casas});
};

function botoes(alvo, itens, chaveEstado, aoTrocar){
  const el = $(alvo); el.innerHTML = '';
  itens.forEach(it => {
    const b = document.createElement('button');
    b.textContent = it.rotulo;
    b.setAttribute('aria-pressed', ESTADO[chaveEstado] === it.chave);
    if (it.desabilitado) b.disabled = true;
    b.onclick = () => { ESTADO[chaveEstado] = it.chave; ESTADO.pagina = 1;
                        if (aoTrocar) aoTrocar(); desenhaBotoes(); carrega(); };
    el.appendChild(b);
  });
}

// O rotulo do movimento escolhido, vindo das opcoes do servidor.
const rotuloMovimento = () => {
  const m = (OPCOES.movimentos || []).find(x => x.chave === ESTADO.movimento);
  return m ? m.rotulo : ESTADO.movimento;
};

/* Entrada + saida e visao de MATRIZ, e nao do recorte inteiro (V3.7.2).

   A Matriz agrega, e por isso pode somar os dois movimentos. A planilha mostra
   linha crua e o download leva a linha inteira -- e as duas tabelas do DW tem 36
   e 46 colunas. Nao existe "linha crua entrada + saida", entao os dois saem de
   cena aqui em vez de o servidor recusar depois de a pessoa clicar. O servidor
   recusa igual (400), e essa recusa continua sendo a trava de verdade.

   O filtro de operacao tambem sai: as duas listas de `descr_oper_wms` sao
   diferentes, e filtrar por uma delas zeraria o outro movimento em silencio. */
function limitesDoMovimento(){
  const conjunta = ESTADO.movimento === CONJUNTA;

  const operacao = CAIXAS.get('#operacao');
  if (operacao){
    if (conjunta) zeraCaixa('#operacao');
    operacao.botao.disabled = conjunta;
    operacao.titulo = conjunta
      ? 'Não vale em Entrada + saída: as duas tabelas têm listas de operação '
        + 'diferentes. Escolha Entrada ou Saída para filtrar por operação.'
      : '';
    atualizaCaixa('#operacao');
  }

  // Sem `exportar` os botões não estão na tela (`carregaPermissoes`), e a nota
  // explica a falta em vez de alternar entre duas ressalvas de download que a
  // pessoa não vai poder fazer.
  if (!PODE_EXPORTAR){ $('#nota-download').textContent = NOTA_SEM_EXPORTAR; return; }
  ['#baixar-csv', '#baixar-xlsx'].forEach(alvo => { $(alvo).disabled = conjunta; });
  $('#nota-download').textContent = conjunta ? NOTA_DOWNLOAD_CONJUNTA : NOTA_DOWNLOAD;
}

function desenhaBotoes(){
  botoes('#movimento', (OPCOES.movimentos || []).map(m => ({
    chave: m.chave, rotulo: m.rotulo
  })), 'movimento', () => {
    ESTADO.abertos = new Set();
    // A planilha nao existe na conjunta: sair para a Matriz ANTES de carregar,
    // senao o primeiro pedido sai para um endpoint que vai recusar.
    if (ESTADO.movimento === CONJUNTA && ESTADO.visao === 'planilha')
      ESTADO.visao = 'matriz';
    preencheOperacoes();
  });

  botoes('#lente', OPCOES.lentes.map(l => ({
    chave:l.chave, rotulo:l.nome,
    // Pallet fica visível mas desabilitado onde não existe: esconder faria
    // parecer que a medida não existe; desabilitado diz que ela não existe ALI.
    // Na conjunta ele também sai — a soma seria só a entrada com o nome de
    // "movimentação", que é número certo com nome errado.
    desabilitado: ESTADO.movimento !== 'rec' && l.so_entrada
  })), 'lente');

  botoes('#faixa', OPCOES.faixas.map(f => ({chave:f.chave, rotulo:f.rotulo})), 'faixa');
  // A faixa responde uma pergunta DIFERENTE nas duas visões, então o rótulo
  // muda: na saída ela é um nível da árvore ("Faixa da expedição"); na conjunta
  // ela escolhe qual das três colunas da expedição entra na soma.
  $('#campo-faixa').style.display = ESTADO.movimento === 'rec' ? 'none' : '';
  $('#rotulo-faixa').textContent = ESTADO.movimento === CONJUNTA
    ? 'A expedição entra como' : 'Faixa da expedição';

  // Trocar de visao reseta a pagina: a Matriz pagina UNIDADE (12) e a planilha
  // pagina LINHA (100) -- carregar a pagina 7 da planilha na Matriz mostraria
  // vazio e pareceria defeito.
  botoes('#visao', [
    {chave:'matriz', rotulo:'Matriz'},
    {chave:'planilha', rotulo:'Planilha',
     desabilitado: ESTADO.movimento === CONJUNTA}
  ], 'visao', () => { ESTADO.pagina = 1; });

  limitesDoMovimento();
}

function opcoesSelect(alvo, itens){
  const el = $(alvo); el.innerHTML = '';
  itens.forEach(it => {
    const o = document.createElement('option');
    o.value = it.chave !== undefined ? it.chave : it;
    o.textContent = it.rotulo !== undefined ? it.rotulo : it;
    el.appendChild(o);
  });
}

function preencheOperacoes(){
  opcoesSelect('#operacao', OPCOES.operacoes[ESTADO.movimento] || []);
  // A lista de operacao e POR MOVIMENTO: trocar Entrada/Saida troca as opcoes,
  // e o painel de caixas tem que ser remontado sobre elas. Inerte na primeira
  // chamada, que acontece antes de `criaCaixas()`.
  //
  // `zeraCaixa` e nao so `atualizaCaixa`: "nenhum marcado" sobre uma lista de
  // opcoes que deixou de existir nao significa nada, e travaria o Aplicar sem
  // a pessoa ter como desfazer -- o filtro que ela precisaria mexer nem mostra
  // mais os mesmos itens.
  zeraCaixa('#operacao');
  atualizaCaixa('#operacao');
}

const selecionados = alvo => Array.from($(alvo).selectedOptions).map(o => o.value);

/* ------------------------------------- filtros com caixas de selecao (V3.7.1)

   O `<select multiple>` CONTINUA sendo a fonte da verdade: ele fica no DOM,
   escondido, e o painel de caixas so o comanda. Por isso `parametros()`,
   `opcoesSelect()` e o botao Limpar seguem lendo e escrevendo o mesmo lugar de
   sempre -- isto e uma camada de interface sobre o recorte, e nao uma
   reescrita dele. Nenhum arquivo de backend mudou neste lote.

   Por que trocar o select nativo: a CAPACIDADE de escolher varios sempre
   existiu, e a DESCOBERTA nao. No select nativo o clique simples SUBSTITUI a
   selecao e so Ctrl acrescenta -- comportamento do navegador, que nao estava
   escrito em lugar nenhum da tela.

   A regra que o desenho fixa (V3_PLANO, lote V3.7.1, decisao 1): "tudo
   marcado" e "sem filtro" sao o MESMO estado, e o que vai na URL e nada.
   Marcar os 14 clientes de hoje nao e a mesma coisa que nao filtrar: se um
   cliente novo entrar na carga amanha, "sem filtro" inclui ele e "os 14 que eu
   marquei" nao. Entao `normaliza()` desfaz a selecao completa, e o estado
   "todas as opcoes selecionadas" nunca chega a existir no select. Isso tambem
   deixa a auditoria do download honesta ("sem filtro de cliente") e nao infla
   a URL.

   Consequencia visivel, e ela e deliberada: com nada selecionado o painel
   mostra TUDO marcado e o botao diz "Todos". Desmarcar um item ali significa
   "todos menos este" -- que e exatamente o que as caixas marcadas estavam
   dizendo. E nao existe estado "nenhum item": desmarcar o ultimo selecionado
   volta para "Todos", porque recorte sem nenhuma unidade nao e uma tela que
   alguem pediu, e um rotulo dizendo "Todos" com as caixas vazias seria a tela
   mentindo. */

const CAIXAS = new Map();
const COM_CAIXAS = ['#unidade', '#cliente', '#tipo', '#operacao', '#dia'];

/* TRES estados, e nao dois (V3.7.3)

   O V3.7.1 tinha dois: "Todos" (selecao vazia) e "N selecionados". Faltava o
   terceiro, e a falta era um defeito de verdade: para ver **um** cliente entre
   14 era preciso desmarcar 13, um por um. Pedido da Maria em 27/ago/2026 --
   "poderiamos clicar no selecionar tudo pra des-selecionar tudo?".

   O que impedia isso no V3.7.1: no backend "nenhum selecionado" e "todos" sao
   o MESMO estado -- lista de filtro vazia = nenhuma clausula no `WHERE`. Entao
   desmarcar tudo mostraria zero caixas e uma Matriz com tudo dentro: a tela
   mentindo sobre o proprio recorte. Por isso o "Selecionar tudo" nascia
   desabilitado quando marcado.

   O que destrava: **o painel nao aplica nada na hora.** Marcar caixa so mexe no
   `<select>` escondido, e quem recarrega e o Aplicar. Entao "nenhum marcado"
   pode existir como estado de EDICAO, que nunca chega ao servidor -- e aí nao
   existe numero errado para a tela mostrar.

   Os tres, e como a selecao do select distingue:

     selecao vazia + `vazio=false`  -> "Todos"              (sem filtro na URL)
     selecao vazia + `vazio=true`   -> "Nenhum selecionado" (NAO pode aplicar)
     selecao com itens              -> "N selecionados"     (`vazio` sempre false)

   `vazio` mora no widget e nao no select de proposito: o select nao tem onde
   guardar isso, e inventar uma opcao sentinela dentro dele contaminaria
   `parametros()`, a auditoria e o download -- que e exatamente o que o desenho
   do V3.7.1 protegia. */

// Sem filtro = nenhuma opcao selecionada.
const semFiltro = el => !Array.from(el.options).some(o => o.selected);

// Estado 3: marcado nenhum, DE PROPOSITO. So o widget sabe.
const estaVazio = sel => {
  const w = CAIXAS.get(sel);
  return !!(w && w.vazio && semFiltro($(sel)));
};

// Volta o filtro para "Todos" -- selecao limpa E fora do estado vazio. Usado
// pelo Limpar, pela troca de movimento e quando a lista de opcoes e refeita:
// "nenhum marcado" sobre uma lista que deixou de existir nao significa nada.
function zeraCaixa(sel){
  const el = $(sel);
  if (el) Array.from(el.options).forEach(o => { o.selected = false; });
  const w = CAIXAS.get(sel);
  if (w) w.vazio = false;
}

function normaliza(el){
  const todas = Array.from(el.options);
  if (todas.length && todas.every(o => o.selected))
    todas.forEach(o => { o.selected = false; });
}

function rotuloFechado(sel){
  const el = $(sel);
  if (estaVazio(sel)) return 'Nenhum selecionado';
  if (semFiltro(el)) return 'Todos';
  const marcadas = Array.from(el.selectedOptions);
  return marcadas.length === 1 ? marcadas[0].textContent
                               : `${marcadas.length} selecionados`;
}

// Os filtros no estado 3, pelo nome que a tela mostra. Vazio = da para aplicar.
const caixasVazias = () =>
  COM_CAIXAS.filter(estaVazio).map(sel => CAIXAS.get(sel).nome);

function montaPainel(sel){
  const w = CAIXAS.get(sel), el = $(sel);
  w.painel.innerHTML = '';
  const vazio = estaVazio(sel);
  const todos = !vazio && semFiltro(el);

  const tudo = document.createElement('label');
  tudo.className = 'caixa tudo';
  const marca = document.createElement('input');
  marca.type = 'checkbox';
  marca.checked = todos;
  // Agora ele ALTERNA: marcado -> desmarca todas; desmarcado -> volta a Todos.
  marca.onchange = () => {
    if (todos) { w.vazio = true; }          // tudo marcado -> tudo desmarcado
    else { zeraCaixa(sel); }                // qualquer outro estado -> Todos
    atualizaCaixa(sel);
  };
  tudo.append(marca, document.createTextNode('Selecionar tudo'));
  w.painel.appendChild(tudo);

  Array.from(el.options).forEach(opcao => {
    const linha = document.createElement('label');
    linha.className = 'caixa';
    linha.title = opcao.textContent;
    const caixa = document.createElement('input');
    caixa.type = 'checkbox';
    caixa.checked = todos || opcao.selected;
    caixa.onchange = () => {
      if (vazio){
        // saindo do estado 3: o primeiro marcado e o filtro inteiro. E este o
        // ganho do lote -- "so a SAPORE" passa de 13 cliques para 2.
        w.vazio = false;
        Array.from(el.options).forEach(o => { o.selected = o === opcao; });
      } else if (semFiltro(el)){
        // estava em "Todos": desmarcar um e pedir "todos menos este"
        Array.from(el.options).forEach(o => { o.selected = o !== opcao; });
      } else {
        opcao.selected = !opcao.selected;
        // Desmarcar o ULTIMO agora para em "Nenhum", e nao volta para "Todos"
        // como no V3.7.1. Saltar para "todos marcados" depois de a pessoa
        // desmarcar era o painel fazendo o contrario do clique; e agora existe
        // um estado que descreve o que ela fez.
        if (semFiltro(el)) w.vazio = true;
      }
      normaliza(el);
      atualizaCaixa(sel);
    };
    linha.append(caixa, document.createTextNode(opcao.textContent));
    w.painel.appendChild(linha);
  });
}

function atualizaCaixa(sel){
  const w = CAIXAS.get(sel);
  if (!w) return;                       // chamado antes de `criaCaixas()`
  w.botao.textContent = rotuloFechado(sel);
  w.botao.classList.toggle('vazio', estaVazio(sel));
  w.botao.title = estaVazio(sel)
    ? `${w.nome}: nenhum selecionado. Escolha ao menos um, ou marque `
      + `"Selecionar tudo" para voltar a Todos.`
    : w.titulo;
  if (w.painel.hidden) return;
  // Remontar o painel perde o foco, e sem isto as setas param de andar depois
  // do primeiro clique. O indice e estavel: "Selecionar tudo" e sempre o 0.
  const antes = Array.from(w.painel.querySelectorAll('input'))
    .indexOf(document.activeElement);
  montaPainel(sel);
  const agora = w.painel.querySelectorAll('input');
  const volta = antes >= 0 ? agora[antes] : null;
  if (volta && !volta.disabled) volta.focus();
  else if (antes >= 0) w.botao.focus();
}

const atualizaCaixas = () => COM_CAIXAS.forEach(atualizaCaixa);

function fechaCaixas(menos){
  CAIXAS.forEach((w, sel) => {
    if (sel === menos || w.painel.hidden) return;
    w.painel.hidden = true;
    w.botao.setAttribute('aria-expanded', 'false');
  });
}

function abreCaixa(sel){
  const w = CAIXAS.get(sel);
  if (!w || w.botao.disabled) return;
  fechaCaixas(sel);
  w.painel.hidden = false;
  w.botao.setAttribute('aria-expanded', 'true');
  montaPainel(sel);
  const primeira = w.painel.querySelector('input:not([disabled])');
  if (primeira) primeira.focus();
}

function criaCaixas(){
  COM_CAIXAS.forEach(sel => {
    const el = $(sel);
    if (!el || CAIXAS.has(sel)) return;
    const caixa = document.createElement('div');
    caixa.className = 'caixas';
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'abre-filtro' + (sel === '#dia' ? ' curta' : '');
    botao.setAttribute('aria-expanded', 'false');
    botao.setAttribute('aria-haspopup', 'true');
    const painel = document.createElement('div');
    painel.className = 'painel';
    painel.hidden = true;
    caixa.append(botao, painel);
    el.parentNode.insertBefore(caixa, el.nextSibling);
    // O select some SO DEPOIS de o substituto existir -- ver o comentario do CSS.
    el.classList.add('escondido');
    // `nome` e o rotulo que a pessoa ve, e existe para a recusa do Aplicar
    // poder dizer QUAL filtro esta pendente. `vazio` e o estado 3.
    const etiqueta = el.parentNode.querySelector('label');
    CAIXAS.set(sel, {
      botao, painel,
      titulo: el.title || '',
      nome: (etiqueta ? etiqueta.textContent : sel.replace('#', '')).trim(),
      vazio: false,
    });

    botao.onclick = () => { painel.hidden ? abreCaixa(sel) : fechaCaixas(); };
    painel.onkeydown = evento => {
      if (evento.key === 'Escape'){ fechaCaixas(); botao.focus(); return; }
      if (evento.key !== 'ArrowDown' && evento.key !== 'ArrowUp') return;
      evento.preventDefault();
      const foco = Array.from(painel.querySelectorAll('input:not([disabled])'));
      const i = foco.indexOf(document.activeElement);
      const proxima = foco[evento.key === 'ArrowDown' ? i + 1 : i - 1];
      if (proxima) proxima.focus();
    };
    // O rotulo passa a apontar para o botao: clicar em "CLIENTE" tem que abrir
    // o painel, e nao focar um select que ninguem ve mais.
    const rotulo = el.parentNode.querySelector('label[for="' + el.id + '"]');
    if (rotulo){
      rotulo.removeAttribute('for');
      rotulo.style.cursor = 'pointer';
      rotulo.onclick = () => abreCaixa(sel);
    }
  });
  atualizaCaixas();
}

// Clique fora fecha; clique DENTRO nao. Se clicar numa caixa fechasse o painel,
// marcar tres itens exigiria abrir tres vezes -- que e o problema do
// Ctrl+clique com outra roupa (V3_PLANO, lote V3.7.1, decisao 3).
document.addEventListener('mousedown', evento => {
  if (!evento.target.closest('.caixas')) fechaCaixas();
});
document.addEventListener('keydown', evento => {
  if (evento.key === 'Escape') fechaCaixas();
});

function parametros(){
  const p = new URLSearchParams();
  p.set('de', $('#de').value); p.set('ate', $('#ate').value);
  p.set('movimento', ESTADO.movimento); p.set('lente', ESTADO.lente);
  p.set('faixa', ESTADO.faixa); p.set('pagina', ESTADO.pagina);
  selecionados('#unidade').forEach(v => p.append('unidade', v));
  selecionados('#cliente').forEach(v => p.append('cliente', v));
  selecionados('#tipo').forEach(v => p.append('tipo_estoque', v));
  selecionados('#operacao').forEach(v => p.append('operacao', v));
  selecionados('#dia').forEach(v => p.append('dia', v));
  return p;
}

// A assinatura do recorte SEM a pagina -- e o que o download leva. Serve para
// saber se o total de linhas que a tela tem em maos ainda descreve o que a
// pessoa esta pedindo (ver `totalDoRecorte`).
function assinatura(){
  const p = parametros();
  p.delete('pagina');
  return p.toString();
}

// O total de linhas do recorte carregado, com a assinatura dele. Perguntar
// "sao 434 mil linhas, continuar?" com o numero de OUTRO recorte e pior que
// nao perguntar: quem mexeu nos filtros sem apertar Aplicar levaria o susto
// errado, ou nenhum.
let TOTAL = {assinatura: null, linhas: null};

async function totalDoRecorte(){
  if (TOTAL.assinatura === assinatura()) return TOTAL.linhas;
  // filtro mexido e nao aplicado: busca o numero do recorte que vai sair
  const r = await busca(API + '/planilha?' + parametros().toString());
  if (!r.ok) return null;   // deixa o servidor recusar e explicar, como sempre
  return (await r.json()).paginacao.total_linhas;
}

// Separador de caminho: unit separator, que nao aparece em sigla, CNPJ
// nem descricao de operacao -- e por isso nao pode colidir com chave.
function caminho(pai, no){ return pai + '\u001f' + no.chave; }

function linhas(nos, meses, unidade, nivel, pai, saida){
  nos.forEach(no => {
    const id = caminho(pai, no);
    const temFilhos = no.filhos && no.filhos.length;
    const aberto = ESTADO.abertos.has(id);
    const tr = document.createElement('tr');
    tr.className = 'n' + nivel + (no.nivel === 'faixa' ? ' faixa' : '');
    const td = document.createElement('td');
    td.className = 'rotulo';
    td.style.setProperty('--recuo', (nivel * 16) + 'px');
    if (temFilhos){
      const b = document.createElement('button');
      b.className = 'abre'; b.textContent = aberto ? '−' : '+';
      b.setAttribute('aria-expanded', aberto);
      b.onclick = () => { aberto ? ESTADO.abertos.delete(id) : ESTADO.abertos.add(id);
                          redesenha(); };
      td.appendChild(b);
    } else { td.appendChild(document.createTextNode('   ')); }
    td.appendChild(document.createTextNode(no.rotulo === null ? '(sem rótulo)' : no.rotulo));
    tr.appendChild(td);
    meses.forEach(m => {
      const c = document.createElement('td');
      c.innerHTML = fmt(no.valores[m], unidade);
      tr.appendChild(c);
    });
    saida.push(tr);
    if (temFilhos && aberto) linhas(no.filhos, meses, unidade, nivel + 1, id, saida);
  });
  return saida;
}

let ULTIMO = null;

function redesenha(){
  if (!ULTIMO) return;
  const d = ULTIMO, u = d.lente.unidade;
  const tabela = document.createElement('table');

  const thead = document.createElement('thead');
  const trh = document.createElement('tr');
  const th0 = document.createElement('th');
  th0.className = 'rotulo';
  th0.textContent = trilha(d.niveis);
  trh.appendChild(th0);
  // `2026-08 (03-31)` quando a ponta do periodo corta o mes: um total rotulado
  // como o mes que nao e o mes inteiro e o numero que alguem copia para um
  // relatorio. O rotulo vem do backend, do lado da definicao do recorte.
  d.meses.forEach(m => { const th = document.createElement('th');
    th.textContent = (d.rotulos_meses && d.rotulos_meses[m]) || m;
    trh.appendChild(th); });
  thead.appendChild(trh); tabela.appendChild(thead);

  const tbody = document.createElement('tbody');
  if (!d.linhas.length){
    const tr = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = d.meses.length + 1; td.className = 'rotulo';
    td.innerHTML = '<span class="vazio">Nenhuma linha no recorte.</span>';
    tr.appendChild(td); tbody.appendChild(tr);
  } else {
    linhas(d.linhas, d.meses, u, 0, '', []).forEach(tr => tbody.appendChild(tr));
  }
  tabela.appendChild(tbody);

  const tfoot = document.createElement('tfoot');
  const trf = document.createElement('tr');
  const tdf = document.createElement('td');
  tdf.className = 'rotulo'; tdf.textContent = 'Total do recorte';
  trf.appendChild(tdf);
  d.meses.forEach(m => { const td = document.createElement('td');
    td.innerHTML = fmt(d.total[m], u); trf.appendChild(td); });
  tfoot.appendChild(trf); tabela.appendChild(tfoot);

  const alvo = $('.rolagem');
  alvo.innerHTML = ''; alvo.appendChild(tabela);
}

function paginacao(p){
  const el = $('#paginacao');
  if (p.paginas <= 1){ el.innerHTML = `${p.total_unidades} unidade(s)`; return; }
  el.innerHTML = '';
  const info = document.createElement('span');
  info.textContent = `Página ${p.pagina} de ${p.paginas} — ${p.total_unidades} unidades, ${p.por_pagina} por página`;
  const anterior = document.createElement('button');
  anterior.className = 'secundario'; anterior.textContent = '‹ Anterior';
  anterior.disabled = p.pagina <= 1;
  anterior.onclick = () => { ESTADO.pagina--; carrega(); };
  const proxima = document.createElement('button');
  proxima.className = 'secundario'; proxima.textContent = 'Próxima ›';
  proxima.disabled = p.pagina >= p.paginas;
  proxima.onclick = () => { ESTADO.pagina++; carrega(); };
  el.append(info, anterior, proxima);
}

function metodo(d){
  const cargas = (OPCOES.cargas || []).map(c =>
    `<li><code>${c.tabela}</code> — carga <strong>${c.fonte}</strong> concluída em ${c.quando}, ${Number(c.linhas).toLocaleString('pt-BR')} linhas</li>`
  ).join('');
  $('#metodo').innerHTML = `
    <div>
      <strong>De quando é o dado</strong>
      <ul>${cargas || '<li>Nenhuma carga concluída.</li>'}</ul>
    </div>
    <div>
      <strong>Como o número é somado</strong>
      <ul>
        <li>Agrega pela <strong>data do movimento</strong> (<code>nk_calendario</code>), não pela data da solicitação. Guia pedida em 31/jan e expedida em 02/fev conta em fevereiro.</li>
        <li>Hierarquia: ${trilha(d.niveis)}. Coluna é o mês — e quando o período começa ou termina no meio de um mês, o cabeçalho declara os dias que entraram.</li>
        <li>O filtro <strong>Dia do mês</strong> recorta dentro de <em>todos</em> os meses do período: escolher 01 a 05 com janeiro a agosto traz os cinco primeiros dias de cada um dos oito meses.</li>
        <li>Escopo: catering — instâncias <code>SLIN</code>. Volume de outras instâncias do DW é outro negócio e está fora.</li>
      </ul>
    </div>
    <div>
      <strong>De-para e classificação</strong>
      <ul>
        <li>A unidade da SANCA vem do DW com sigla <code>RMSPV</code> e é exibida como <strong>RMSPIV</strong>. É a única exceção.</li>
        <li>Cliente é a raiz do CNPJ; o rótulo é a razão social de maior peso quando a mesma raiz aparece com mais de uma grafia.</li>
        <li><code>NAO_CLASSIFICADO</code> em tipo de estoque é sentinela, não erro: significa nome de estoque que a regra ainda não classifica.</li>
      </ul>
    </div>
    <div>
      <strong>Limitações declaradas</strong>
      <ul>
        <li>A <code>FATO_VOL_REC_CAT_V01</code> não traz guia de recebimento cancelada — a tabela só carrega guia confirmada.</li>
        <li>Na expedição, guia cancelada tem peso apenas na faixa <em>solicitado</em>: ~3% do número dessa faixa é pedido que não saiu. Trocar para <em>atendido</em> ou <em>separado</em> zera isso.</li>
      </ul>
    </div>`;
}

/* Os parametros do download: SEMPRE o recorte inteiro dos filtros -- `pagina`
   sai de proposito (baixar uma pagina so nao e baixar o recorte, contrato).

   O MESMO conjunto vai no pedido do ticket e na navegacao que baixa, porque e
   sobre ele que o servidor assina: ticket de um recorte nao serve para outro. */
function parametrosDownload(formato){
  const p = parametros();
  p.delete('pagina');
  p.set('formato', formato);
  return p;
}

/* ---------------------------------------------- falar com a API, um lugar só

   O Bearer do portal entra aqui (mesmo `sf_portal_token` dos outros apps
   embutidos). A tela é servida como estático, sem login: quem abre a URL direto
   recebe o HTML e nada mais — todo dado exige identidade no backend.

   Três status NÃO são "recorte recusado" e ganham mensagem própria (V3.4: 401 é
   "a sessão expirou", não "o servidor deu erro" — sem o desvio, a tela mandaria
   a pessoa mexer nos filtros para resolver um problema de login):

   - **401** não navega para `/login` como na V3. Aqui a tela roda dentro do
     iframe do portal, e a página de login é `X-Frame-Options: DENY` — o
     redirecionamento daria um frame em branco. Vira mensagem com saída para o
     hub no topo (`target="_top"`), que é onde o login existe;
   - **403** é falta de acesso ao app (a coluna Ver da matriz) e a mensagem do
     backend já diz o que pedir a um administrador;
   - **503** é o banco da nuvem-ia fora do ar ou o contrato divergindo do schema
     (a falha graciosa do desenho): degrada só este card, e a mensagem diz isso
     para ninguém achar que o Hub caiu. */
class RespostaRecusada extends Error {}

const cabecalhoAuth = () => {
  const token = localStorage.getItem('sf_portal_token') || '';
  return token ? {'Authorization': 'Bearer ' + token} : {};
};

// O `detail` do FastAPI quando existe; o statusText quando a resposta não é
// JSON (502 do proxy, por exemplo).
async function detalhe(resposta){
  try { return (await resposta.json()).detail || resposta.statusText; }
  catch (e) { return resposta.statusText; }
}

const SAIDA_HUB = '<a href="/" target="_top">Voltar ao hub</a>';

function mostraBloqueio(status, causa){
  const texto = {
    401: '<strong>Sua sessão expirou.</strong><br>Entre de novo no portal para '
       + `ver a volumetria — o login mora fora desta tela. ${SAIDA_HUB}.`,
    403: `<strong>Sem acesso a este painel.</strong><br>${causa}`,
    503: '<strong>O painel da volumetria está indisponível.</strong><br>'
       + `${causa}<br>O restante do Hub continua funcionando. ${SAIDA_HUB}.`,
  }[status];
  $('.rolagem').innerHTML = `<div class="erro">${texto}</div>`;
  $('#paginacao').innerHTML = '';
}

async function busca(url, opcoes = {}){
  const resposta = await fetch(url, {
    ...opcoes,
    headers: {...cabecalhoAuth(), ...(opcoes.headers || {})},
  });
  if ([401, 403, 503].includes(resposta.status)){
    mostraBloqueio(resposta.status, await detalhe(resposta));
    throw new RespostaRecusada(String(resposta.status));
  }
  return resposta;
}

/* Quem pode baixar. O endpoint global de permissões do Hub nunca devolve
   401/403 (anônimo recebe lista vazia), então ele NÃO passa por `busca()`: aqui
   uma falha não é bloqueio da tela, é só "não mostra os botões".

   Sem `exportar` os dois botões saem da tela em vez de ficarem clicáveis para
   dar 403 — a tela diz que falta uma permissão em vez de deixar a pessoa
   descobrir isso no erro. A guarda que vale continua sendo a do servidor. */
let PODE_EXPORTAR = false;

async function carregaPermissoes(){
  try {
    const r = await fetch('/api/auth/me/permissoes', {headers: cabecalhoAuth()});
    const eu = await r.json();
    PODE_EXPORTAR = (eu.permissoes || []).includes(PERMISSAO_EXPORTAR);
  } catch (e) {
    PODE_EXPORTAR = false;
  }
  $('#baixar-csv').hidden = !PODE_EXPORTAR;
  $('#baixar-xlsx').hidden = !PODE_EXPORTAR;
}

// A procedência no cabeçalho: de quando é o dado que está na tela. O detalhe
// (tabela, fonte, linhas) fica em "Fontes & método"; aqui vai a última carga,
// que é o que responde "isto está atualizado?" sem abrir nada.
function mostraProcedencia(){
  const cargas = OPCOES.cargas || [];
  $('#procedencia').textContent = cargas.length
    ? `Última carga: ${cargas[0].quando}`
    : 'Nenhuma carga concluída';
}

/* A trava do estado 3, e ela mora aqui de proposito (V3.7.3).

   "Nenhum marcado" nao pode virar consulta: no `WHERE` ele seria indistinguivel
   de "sem filtro", e a Matriz voltaria com TUDO enquanto o painel mostra zero
   caixas -- a tela mentindo, que e exatamente o que o V3.7.1 evitou desabilitando
   o botao.

   Guardar em `carrega()` e nao no Aplicar cobre todos os caminhos de uma vez: o
   Aplicar, a paginacao, e a troca de movimento/medida/faixa/visao, que tambem
   recarregam. Um `if` no Aplicar deixaria os outros passarem. */
function travadoPorFiltroVazio(){
  const pendentes = caixasVazias();
  if (!pendentes.length) return false;
  const quais = pendentes.join(', ');
  const um = pendentes.length === 1;
  $('.rolagem').innerHTML =
    `<div class="erro"><strong>${um ? 'Filtro sem seleção' : 'Filtros sem seleção'}: `
    + `${quais}.</strong><br>Escolha ao menos um item, ou marque `
    + `"Selecionar tudo" para voltar a Todos. Enquanto isso a Matriz não é `
    + `recalculada — o recorte pedido não descreve nenhuma linha.</div>`;
  $('#paginacao').innerHTML = '';
  return true;
}

async function carrega(){
  if (travadoPorFiltroVazio()) return;
  if (ESTADO.visao === 'planilha') return carregaPlanilha();
  // `.rolagem` e o container ESTAVEL: o `#corpo` inicial e substituido
  // pela tabela no primeiro desenho e deixa de existir.
  const alvo = $('.rolagem');
  alvo.innerHTML = '<div class="carregando">Carregando…</div>';
  let resposta;
  try { resposta = await busca(API + '/matriz?' + parametros().toString()); }
  // Sessão, acesso e banco fora do ar já foram explicados por `busca()`:
  // repintar aqui daria "Falha de rede: Error: 503" e esconderia a causa.
  catch (e) {
    if (!(e instanceof RespostaRecusada))
      alvo.innerHTML = `<div class="erro">Falha de rede: ${e}</div>`;
    return;
  }
  if (!resposta.ok){
    alvo.innerHTML = `<div class="erro">Recorte recusado: ${await detalhe(resposta)}</div>`;
    return;
  }
  const d = await resposta.json();
  ULTIMO = d;
  TOTAL = {assinatura: assinatura(), linhas: d.total_linhas};
  const faixa = () => OPCOES.faixas.find(f => f.chave === d.filtros.faixa).rotulo;
  $('#titulo').textContent = `Matriz — ${rotuloMovimento()}, ${d.lente.nome}`;
  $('#desc').textContent = ESTADO.movimento === CONJUNTA
    ? `O + abre unidade › cliente › expedição e recebimento. O total da linha é `
      + `a movimentação — os dois somados —, que é como o BI lê a matriz. A `
      + `expedição entra pela faixa ${faixa()}. Tipo de operação não abre aqui: `
      + `veja num movimento só. ${d.lente.nome} em ${d.lente.unidade}, por mês.`
    : `${d.lente.nome} em ${d.lente.unidade}, por mês. `
      + (ESTADO.movimento === 'exp' ? `Faixa: ${faixa()}.` : '');
  $('#avisos').innerHTML = (d.avisos || [])
    .map(a => `<p class="aviso">${a}</p>`).join('');
  redesenha(); paginacao(d.paginacao); metodo(d);
}

// --------------------------------------------------------------- planilha
function desenhaPlanilha(d){
  const tabela = document.createElement('table');
  tabela.className = 'planilha';
  const thead = document.createElement('thead');
  const trh = document.createElement('tr');
  d.colunas.forEach((c, i) => {
    const th = document.createElement('th');
    if (i === 0) th.className = 'primeira';
    th.textContent = c.rotulo;
    trh.appendChild(th);
  });
  thead.appendChild(trh); tabela.appendChild(thead);

  const tbody = document.createElement('tbody');
  if (!d.linhas.length){
    const tr = document.createElement('tr'); const td = document.createElement('td');
    td.colSpan = d.colunas.length; td.className = 'primeira';
    td.innerHTML = '<span class="vazio">Nenhuma linha no recorte.</span>';
    tr.appendChild(td); tbody.appendChild(tr);
  }
  const numericas = new Set(['valor','solicitado','atendido','separado']);
  d.linhas.forEach(linha => {
    const tr = document.createElement('tr');
    d.colunas.forEach((c, i) => {
      const td = document.createElement('td');
      if (i === 0) td.className = 'primeira';
      const valor = linha[c.chave];
      if (numericas.has(c.chave)){
        td.innerHTML = fmt(valor, d.lente.unidade);
        td.classList.add('numero');
      } else if (c.chave === 'dia'){
        td.textContent = valor ? formataDia(valor) : '';
      } else {
        const texto = valor === null || valor === undefined ? '' : String(valor);
        td.textContent = texto;
        // o texto inteiro fica no title: cortar na tela nao pode esconder dado
        td.title = texto;
        td.style.textAlign = 'left';
        if (c.chave === 'cliente' || c.chave === 'operacao') td.classList.add('texto');
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tabela.appendChild(tbody);

  const alvo = $('.rolagem');
  alvo.innerHTML = ''; alvo.appendChild(tabela);
}

// A API manda a data como AAAA-MM-DD; a tela mostra no formato de quem le.
const formataDia = iso => iso.split('-').reverse().join('/');

function paginacaoPlanilha(p){
  const el = $('#paginacao');
  el.innerHTML = '';
  const info = document.createElement('span');
  const total = Number(p.total_linhas).toLocaleString('pt-BR');
  info.textContent = p.paginas <= 1
    ? `${total} linha(s)`
    : `Página ${p.pagina} de ${p.paginas} — ${total} linhas, ${p.por_pagina} por página`;
  el.appendChild(info);
  if (p.paginas <= 1) return;
  const anterior = document.createElement('button');
  anterior.className = 'secundario'; anterior.textContent = '‹ Anterior';
  anterior.disabled = p.pagina <= 1;
  anterior.onclick = () => { ESTADO.pagina--; carrega(); };
  const proxima = document.createElement('button');
  proxima.className = 'secundario'; proxima.textContent = 'Próxima ›';
  proxima.disabled = p.pagina >= p.paginas;
  proxima.onclick = () => { ESTADO.pagina++; carrega(); };
  el.append(anterior, proxima);
}

async function carregaPlanilha(){
  const alvo = $('.rolagem');
  alvo.innerHTML = '<div class="carregando">Carregando…</div>';
  let resposta;
  try { resposta = await busca(API + '/planilha?' + parametros().toString()); }
  catch (e) {
    if (!(e instanceof RespostaRecusada))
      alvo.innerHTML = `<div class="erro">Falha de rede: ${e}</div>`;
    return;
  }
  if (!resposta.ok){
    alvo.innerHTML = `<div class="erro">Recorte recusado: ${await detalhe(resposta)}</div>`;
    return;
  }
  const d = await resposta.json();
  TOTAL = {assinatura: assinatura(), linhas: d.paginacao.total_linhas};
  $('#titulo').textContent = `Planilha — ${rotuloMovimento()}, ${d.lente.nome}`;
  $('#desc').textContent =
    `Uma linha por registro do DW, no mesmo recorte da Matriz. ${d.lente.nome} em ${d.lente.unidade}.`;
  $('#avisos').innerHTML = (d.avisos || []).map(a => `<p class="aviso">${a}</p>`).join('');
  desenhaPlanilha(d); paginacaoPlanilha(d.paginacao);
  metodo({niveis: ESTADO.movimento === 'exp'
    ? ['unidade','cliente','faixa','operacao'] : ['unidade','cliente','operacao']});
}

async function inicia(){
  // As opções vêm primeiro: sem elas a tela não tem o que montar, e é este
  // pedido que descobre sessão expirada, falta de acesso ao app ou banco da
  // nuvem-ia fora do ar. Nesses casos `busca()` pinta a mensagem e para aqui.
  OPCOES = await (await busca(API + '/opcoes')).json();
  // Antes de `desenhaBotoes()`, que já consulta `PODE_EXPORTAR`.
  await carregaPermissoes();
  mostraProcedencia();
  // A tela abre em janeiro do ano corrente ate hoje (`CAT_ABERTURA_DE`), e nao
  // no periodo inteiro que existe no banco: com 3,6 anos de historico dentro dele,
  // abrir em min..max daria 44 colunas sem ninguem pedir. O alcance real fica
  // na dica ao lado -- quem nao sabe que 2023 esta ali nao filtra para tras.
  abreNoPadrao();
  $('#dica-periodo').textContent = OPCOES.periodo.de
    ? `${dataBR(OPCOES.periodo.de)} a ${dataBR(OPCOES.periodo.ate)}`
    : 'nenhuma carga ainda';
  opcoesSelect('#unidade', OPCOES.unidades);
  opcoesSelect('#cliente', OPCOES.clientes);
  opcoesSelect('#tipo', OPCOES.tipos_estoque);
  // Dia do MES, 01..31: e calendario, nao dimensao lida do dado. Mes sem dia
  // 31 simplesmente nao casa com a selecao -- e o certo, e nao um erro.
  opcoesSelect('#dia', Array.from({length: 31},
    (_, i) => ({chave: String(i + 1).padStart(2, '0'),
                rotulo: String(i + 1).padStart(2, '0')})));
  preencheOperacoes();
  // Depois de TODAS as listas estarem preenchidas: o painel se monta sobre as
  // opcoes que existem, e e aqui que os selects saem da tela (V3.7.1).
  criaCaixas();
  desenhaBotoes();
  $('#aplicar').onclick = () => { ESTADO.pagina = 1; carrega(); };

  // A nota do download vive em `limitesDoMovimento()`, que a troca conforme o
  // movimento -- ver as duas constantes no topo do script.
  // O download navega (nao e fetch), entao um 401 apareceria como JSON cru na
  // tela. Confere a sessao antes de navegar -- `busca` redireciona se caiu.
  //
  // O mesmo raciocinio vale para o tamanho do recorte, e por isso ele e
  // conferido aqui e nao depois: com o historico completo no banco, o recorte
  // inteiro passa de 400 mil linhas. No CSV isso e um pedido legitimo e sai em
  // streaming -- so precisa de confirmacao. No xlsx o servidor RECUSA (ele nao
  // streama), e como o download navega essa recusa apareceria como uma pagina
  // de JSON cru. Os dois numeros vem do Python, para nao existir uma segunda
  // copia deles aqui; o teto que vale de verdade continua sendo o do servidor.
  const baixa = async (formato) => {
    // O download NAVEGA (nao e fetch), entao a recusa aqui e `alert` e nao a
    // area de erro da tela -- e ela e propria: `carrega()` nao roda neste
    // caminho, e sem esta guarda o arquivo sairia com o recorte inteiro
    // enquanto o painel mostra zero caixas marcadas.
    const pendentes = caixasVazias();
    if (pendentes.length){
      alert(`Sem seleção em: ${pendentes.join(', ')}.\n\nEscolha ao menos um `
        + `item, ou marque "Selecionar tudo" para voltar a Todos.`);
      return;
    }
    let linhas;
    try { linhas = await totalDoRecorte(); }
    catch (e) {
      // 401/403/503 já estão explicados na tela por `busca()`.
      if (!(e instanceof RespostaRecusada)) alert('Falha de rede: ' + e);
      return;
    }
    if (linhas !== null){
      const br = Number(linhas).toLocaleString('pt-BR');
      if (formato === 'xlsx' && linhas > OPCOES.teto_xlsx){
        alert(`O recorte tem ${br} linhas e o Excel (xlsx) não passa de `
          + `${Number(OPCOES.teto_xlsx).toLocaleString('pt-BR')} — ele é montado `
          + `inteiro na memória antes de sair.\n\nBaixe em CSV, que sai em `
          + `streaming e não tem teto, ou estreite o período.`);
        return;
      }
      if (linhas > OPCOES.teto_confirmacao && !confirm(
            `O recorte tem ${br} linhas. O arquivo vai ser grande e o download `
            + `pode demorar.\n\nContinuar?`)) return;
    }
    /* A navegação NÃO carrega o header `Authorization` — o token do portal mora
       no localStorage, e é só o JavaScript que o alcança. Então a tela pede um
       TICKET (POST autenticado, validade de um minuto, amarrado a este recorte)
       e navega com ele na query string.

       O caminho alternativo seria baixar por `fetch` e salvar um Blob, mas isso
       traria o arquivo inteiro para a memória da aba — e o CSV sai em streaming
       justamente porque o recorte passa de 400 mil linhas. Com o ticket, o
       streaming, o nome do `Content-Disposition` e a barra de download do
       navegador continuam iguais aos da V3. */
    const p = parametrosDownload(formato);
    let ticket;
    try {
      const r = await busca(API + '/download/ticket?' + p.toString(), {method: 'POST'});
      if (!r.ok){ alert('O download foi recusado: ' + await detalhe(r)); return; }
      ticket = (await r.json()).ticket;
    } catch (e) {
      if (!(e instanceof RespostaRecusada))
        alert('Falha de rede ao preparar o download: ' + e);
      return;
    }
    p.set('ticket', ticket);
    window.location = API + '/download?' + p.toString();
  };
  $('#baixar-csv').onclick = () => baixa('csv');
  $('#baixar-xlsx').onclick = () => baixa('xlsx');
  $('#limpar').onclick = () => {
    // A lista dos cinco vive em `COM_CAIXAS`, e nao repetida aqui: com duas
    // copias, o sexto filtro entraria numa e nao na outra, e o Limpar deixaria
    // um filtro em pe sem dizer. `zeraCaixa` tambem tira do estado "nenhum
    // marcado" -- Limpar tem que devolver a tela que a pessoa recebeu, e ela
    // nao recebeu um filtro pendente.
    COM_CAIXAS.forEach(zeraCaixa);
    atualizaCaixas();
    abreNoPadrao();
    ESTADO.pagina = 1; ESTADO.abertos = new Set(); carrega();
  };
  carrega();
}

// Sessão expirada, falta de acesso ao app e banco fora do ar já estão escritos
// na tela por `busca()`. Engolir aqui evita o "Uncaught (in promise)" que
// mandaria quem abre o console procurar um defeito que não existe.
inicia().catch(e => { if (!(e instanceof RespostaRecusada)) throw e; });
