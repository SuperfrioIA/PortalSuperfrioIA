// Dashboard Integração In/Out — frontend/integracao-in-out/ (Receita 1 do
// CONTRIBUTING.md). Roda inteiro no navegador: lê o rpt_jda_in_out_volumetry,
// agrega e manda o resultado pro backend, que guarda a base compartilhada em
// data/integracao_in_out.json.
//
// Arquivo externo (não inline) porque o CSP do portal é `script-src 'self'`.

Chart.register(ChartDataLabels);
Chart.defaults.set('plugins.datalabels',{display:false}); // off by default; enabled per-chart
// Mesma tabela de apelidos do Processos Abertos (frontend/processos-abertos/app.js):
// o mesmo armazém aparece com nomes diferentes dependendo da origem do relatório.
// São apelidos da MESMA unidade — MAQ e MAQII, ou RMSP e RMSPII, são unidades
// diferentes e continuam separadas de propósito.
const UNIT_ALIASES={'RIO DE JANEIRO':'RMRJ','RMSPII - BARUERI':'RMSPII','SF RPII - RIBEIRAO':'RPII','MAIRINQUE':'MAQ','FORTALEZA':'FOR','RECIFE':'REC','RMSPIV - SANCA':'RMSPV','UNIDADE CURITIBA':'CWBIII','TAC BSB':'BSB','TAMBORÉ':'RMSPII'};
const MONTHS=['01','02','03','04','05','06','07','08','09','10','11','12'];
const MLAB={'01':'Jan','02':'Fev','03':'Mar','04':'Abr','05':'Mai','06':'Jun','07':'Jul','08':'Ago','09':'Set','10':'Out','11':'Nov','12':'Dez'};
const METRIC_NAME=['Pedidos','Linhas','Ondas'];
// Paleta de marca (Plataforma LATAM). --green/--amber/--red são semânticas de
// status, não identidade visual — mesma separação do CSS.
const C={navy:'#0A2A5E',blue:'#1E6FD9',green:'#1E8449',greenL:'#2ECC71',amber:'#E67E22',amberL:'#F39C12',red:'#C0392B',line:'#E0E4EC',muted:'#4A5E7A',manual:'#C7D2E3',outbound:'#16A085'};

let DATA=null;
let state={metric:0,dir:'IN',tdir:'IN',cdir:'IN',csort:'vol',rdir:'IN',sdir:'IN',unitEvo:null,mdir:'IN',mval:'pct'};
let charts={};
// metric index -> [i_index, t_index] in the 6-length vector [io,to,il,tl,iw,tw]
function MI(){return [state.metric*2, state.metric*2+1];}

function pct(i,t){return t>0? i/t : null;}
function fmtN(n){return Math.round(n||0).toLocaleString('pt-BR');}
function fmtP(x){return x===null?'–':Math.round(x*100)+'%';}
function pillClass(x){if(x===null)return '';return x>=0.8?'pg':x>=0.5?'pa':'pr';}

function emptyAgg(){return {agg:{IN:{},OUT:{}},cli:{IN:{},OUT:{}},climap:{}};}
function addRow(D,dir,wh,cli,integ,mo,oc,lc,wc){
  const A=D.agg[dir]; if(!A[wh])A[wh]={}; if(!A[wh][mo])A[wh][mo]=[0,0,0,0,0,0];
  const a=A[wh][mo]; a[1]+=oc;a[3]+=lc;a[5]+=wc; if(integ){a[0]+=oc;a[2]+=lc;a[4]+=wc;}
  const Cc=D.cli[dir]; if(!Cc[cli])Cc[cli]={}; if(!Cc[cli][mo])Cc[cli][mo]=[0,0,0,0,0,0];
  const c=Cc[cli][mo]; c[1]+=oc;c[3]+=lc;c[5]+=wc; if(integ){c[0]+=oc;c[2]+=lc;c[4]+=wc;}
}
// Colunas do rpt_jda_in_out_volumetry (JDA), índice 0-based:
//   A0 Movement Type · B1 Instance Id · C2 WH Id · D3 Client Id · E4 User Id
//   F5 Year · G6 Month · H7 Order Count · I8 Order Lines Count · J9 Wave Count
const COL={mov:0,wh:2,cli:3,user:4,ano:5,mes:6,pedidos:7,linhas:8,ondas:9};

function normalizar(v){return String(v==null?'':v).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();}

// A coluna E lista quem participou do pedido e pode trazer vários nomes
// separados por vírgula ("ANA, INTEGRACAO, JOSE"). Basta a palavra aparecer em
// qualquer posição pra linha contar como integrada. Comparação sem acento e sem
// caixa: hoje o JDA exporta "INTEGRACAO", mas "Integração" também vale.
function temIntegracao(userId){return normalizar(userId).indexOf('INTEGRACAO')>=0;}

const RE_MES=/^(0[1-9]|1[0-2])$/, RE_ANO=/^\d{4}$/;

// Devolve {anos:{'2026':{agg,cli,climap}}, linhas:n} — o agregado vai pro
// backend nesse formato, um bloco por ano.
function parseWorkbook(wb){
  const sh=wb.Sheets[wb.SheetNames[0]];
  const rows=XLSX.utils.sheet_to_json(sh,{header:1,defval:null});
  const anos={},vol={};let lidas=0;
  for(let r=1;r<rows.length;r++){
    const row=rows[r];if(!row)continue;
    const mt=row[COL.mov],wh0=row[COL.wh];
    if(mt==null||wh0==null)continue;
    const mes=String(row[COL.mes]==null?'':row[COL.mes]).trim().padStart(2,'0');
    const ano=String(row[COL.ano]==null?'':row[COL.ano]).trim();
    if(!RE_MES.test(mes)||!RE_ANO.test(ano))continue;
    const oc=Number(row[COL.pedidos])||0,lc=Number(row[COL.linhas])||0,wc=Number(row[COL.ondas])||0;
    const bruto=String(wh0).trim();
    const wh=UNIT_ALIASES[bruto.toUpperCase()]||bruto;
    const cliBruto=String(row[COL.cli]==null?'':row[COL.cli]).trim();
    const cli=cliBruto||'(sem cliente)';
    const dir=normalizar(mt).indexOf('INBOUND')>=0?'IN':'OUT';
    if(!anos[ano])anos[ano]=emptyAgg();
    if(!vol[ano])vol[ano]={};
    if(!vol[ano][cli])vol[ano][cli]={};
    vol[ano][cli][wh]=(vol[ano][cli][wh]||0)+oc;
    addRow(anos[ano],dir,wh,cli,temIntegracao(row[COL.user]),mes,oc,lc,wc);
    lidas++;
  }
  // Cliente que opera em mais de uma unidade fica na de MAIOR VOLUME de pedidos.
  // A alternativa (primeira ou última linha do arquivo) depende só da ordem do
  // export e chega a apontar a unidade onde o cliente tem ~10% do volume dele.
  // Desempate por nome pra que reprocessar o mesmo arquivo dê sempre o mesmo mapa.
  Object.entries(vol).forEach(([ano,porCliente])=>{
    const mapa=anos[ano].climap;
    Object.entries(porCliente).forEach(([cli,porUnidade])=>{
      mapa[cli]=Object.entries(porUnidade).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]))[0][0];
    });
  });
  return {anos,linhas:lidas};
}

// ── base compartilhada ──────────────────────────────────────────────────────
const API='/api/integracao-in-out';
const PERMISSAO_EDITAR='integracao-in-out:editar';
const BASE_VAZIA={anos:{},atualizado_em:null,arquivo:null};
let BASE=BASE_VAZIA;
let anoAtivo=null;

// Presente só no .html gerado por "Baixar página" (ver baixarPagina() mais
// abaixo) — o script injetado na exportação define isso antes deste arquivo
// rodar, pra ele nascer com os dados gravados em vez de ir buscar na API.
const SNAPSHOT=window.__SNAPSHOT__||null;

async function fetchBase(){
  if(SNAPSHOT)return SNAPSHOT.base;
  try{
    const r=await fetch(API+'/base');
    if(!r.ok)throw new Error('status '+r.status);
    return await r.json();
  }catch(e){console.error('Falha ao carregar a base compartilhada',e);return BASE_VAZIA;}
}

// Endpoint global de permissões: um só pra toda a plataforma, em vez de um
// /pode-editar por app. Nunca devolve 401/403 — anônimo recebe lista vazia.
async function fetchPodeEditar(){
  try{
    const token=localStorage.getItem('sf_portal_token')||'';
    const r=await fetch('/api/auth/me/permissoes',{headers:{'Authorization':'Bearer '+token}});
    if(!r.ok)throw new Error('status '+r.status);
    const corpo=await r.json();
    return (corpo.permissoes||[]).indexOf(PERMISSAO_EDITAR)!==-1;
  }catch(e){console.error('Falha ao checar permissao de edicao',e);return false;}
}

function anosDisponiveis(){return Object.keys(BASE.anos||{}).sort();}

// Os gráficos leem DATA — um ano por vez. Trocar de ano é só reapontar.
function aplicarAno(ano){
  anoAtivo=ano;
  const b=(BASE.anos||{})[ano]||{};
  const agg=b.agg||{},cli=b.cli||{};
  DATA={agg:{IN:agg.IN||{},OUT:agg.OUT||{}},cli:{IN:cli.IN||{},OUT:cli.OUT||{}},climap:b.climap||{}};
}

// O seletor de ano só existe quando há mais de um — o relatório do JDA traz um
// ano por vez, então na prática ele fica invisível até a virada do ano.
function renderYearChips(){
  const box=document.getElementById('yearchips');const anos=anosDisponiveis();
  if(anos.length<2){box.classList.add('hidden');box.innerHTML='';return;}
  box.classList.remove('hidden');
  box.innerHTML=anos.map(a=>`<div class="chip sm${a===anoAtivo?' active':''}" data-ano="${a}">${a}</div>`).join('');
  box.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{aplicarAno(c.dataset.ano);renderYearChips();renderAll();});
}

function renderCarimbo(){
  const stamp=document.getElementById('datestamp'),badge=document.getElementById('heroBadge'),pill=document.getElementById('filepill');
  if(!BASE.atualizado_em){
    stamp.textContent='';badge.textContent='sem base';
    pill.textContent='Nenhuma base carregada ainda — envie o relatório do JDA.';
    return;
  }
  const d=new Date(BASE.atualizado_em);
  const quando=d.toLocaleDateString('pt-BR')+' '+d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  stamp.textContent='Base atualizada em '+quando;
  badge.textContent=quando;
  pill.textContent='Base: '+(BASE.arquivo||'relatório do JDA');
}

function activeMonths(){const s=new Set();['IN','OUT'].forEach(d=>Object.values(DATA.agg[d]).forEach(mo=>Object.keys(mo).forEach(m=>{s.add(m);})));return MONTHS.filter(m=>s.has(m));}
function dirTotals(dir){const[ii,ti]=MI();let i=0,t=0;Object.values(DATA.agg[dir]).forEach(mo=>Object.entries(mo).forEach(([m,v])=>{i+=v[ii];t+=v[ti];}));return[i,t];}
function monthTotals(dir){const[ii,ti]=MI();const out={};activeMonths().forEach(m=>{let i=0,t=0;Object.values(DATA.agg[dir]).forEach(mo=>{if(mo[m]){i+=mo[m][ii];t+=mo[m][ti];}});out[m]=[i,t];});return out;}
function unitRows(dir){const[ii,ti]=MI();const rows=[];Object.entries(DATA.agg[dir]).forEach(([wh,mo])=>{let i=0,t=0;Object.entries(mo).forEach(([m,v])=>{i+=v[ii];t+=v[ti];});rows.push({wh,i,t,man:t-i,p:pct(i,t)});});const grand=rows.reduce((s,r)=>s+r.t,0);rows.forEach(r=>r.share=grand>0?r.t/grand:0);rows.sort((a,b)=>b.t-a.t);return {rows,grand};}

function renderKPIs(){
  const [inI,inT]=dirTotals('IN'),[outI,outT]=dirTotals('OUT');
  const totT=inT+outT,totI=inI+outI;
  const units=new Set([...Object.keys(DATA.agg.IN),...Object.keys(DATA.agg.OUT)]);
  // month-over-month delta for overall %
  const ms=activeMonths();
  let deltaTxt='—',deltaCls='trend-fl';
  if(ms.length>=2){
    const mtIn=monthTotals('IN'),mtOut=monthTotals('OUT');
    const last=ms[ms.length-1],prev=ms[ms.length-2];
    const pv=pct(mtIn[prev][0]+mtOut[prev][0],mtIn[prev][1]+mtOut[prev][1]);
    const lv=pct(mtIn[last][0]+mtOut[last][0],mtIn[last][1]+mtOut[last][1]);
    if(pv!==null&&lv!==null){const d=(lv-pv)*100;deltaTxt=(d>=0?'▲ +':'▼ ')+d.toFixed(1)+'pp vs. mês ant.';deltaCls=d>0.05?'trend-up':d<-0.05?'trend-dn':'trend-fl';}
  }
  const k=[
    {c:'b-navy',l:'Total ('+METRIC_NAME[state.metric]+')',v:fmtN(totT),s:'Inbound + Outbound'},
    {c:'b-green',l:'% Integrado geral',v:fmtP(pct(totI,totT)),s:`<span class="${deltaCls}">${deltaTxt}</span>`},
    {c:'b-blue',l:'% Integrado inbound',v:fmtP(pct(inI,inT)),s:fmtN(inT)+' '+METRIC_NAME[state.metric].toLowerCase()},
    {c:'b-amber',l:'% Integrado outbound',v:fmtP(pct(outI,outT)),s:fmtN(outT)+' '+METRIC_NAME[state.metric].toLowerCase()},
    {c:'b-navy',l:'Unidades ativas',v:units.size,s:'com movimentação'}
  ];
  document.getElementById('kpis').innerHTML=k.map(x=>`<div class="kpi ${x.c}"><div class="k-label">${x.l}</div><div class="k-val">${x.v}</div><div class="k-sub">${x.s}</div></div>`).join('');
  document.getElementById('metricName').textContent=METRIC_NAME[state.metric];
}

function destroy(id){if(charts[id]){charts[id].destroy();delete charts[id];}}

function evoChart(){
  destroy('evo');const ms=activeMonths();
  function series(dir,col){const mt=monthTotals(dir);const arr=ms.map(m=>{const p=pct(mt[m][0],mt[m][1]);return p===null?null:Math.round(p*1000)/10;});return {label:dir==='IN'?'Inbound':'Outbound',data:arr,borderColor:col,backgroundColor:col+'22',tension:.35,spanGaps:true,pointRadius:4,pointBackgroundColor:col,borderWidth:3,fill:false,datalabels:{display:true,align:'top',offset:6,color:col,font:{weight:'700',size:10},formatter:(v,ctx)=>{if(v==null)return '';const i=ctx.dataIndex;const prev=ctx.dataset.data[i-1];let s=v+'%';if(i>0&&prev!=null){const d=v-prev;s+='\n'+(d>=0?'+':'')+d.toFixed(1)+'pp';}return s;}}};}
  let ds=[];
  if(state.dir==='IN')ds=[series('IN',C.blue)];
  else if(state.dir==='OUT')ds=[series('OUT',C.outbound)];
  else ds=[series('IN',C.blue),series('OUT',C.outbound)];
  charts.evo=new Chart(document.getElementById('evoChart'),{type:'line',data:{labels:ms.map(m=>MLAB[m]),datasets:ds},
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:24}},plugins:{legend:{display:state.dir==='BOTH',position:'top'},
      tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y==null?'–':c.parsed.y+'%')}}},
      scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:C.line}},x:{grid:{display:false}}}}});
}
function volChart(){
  destroy('vol');const ms=activeMonths();const dir=state.dir==='BOTH'?'IN':state.dir;const mt=monthTotals(dir);
  const integ=ms.map(m=>mt[m][0]),manual=ms.map(m=>mt[m][1]-mt[m][0]);
  charts.vol=new Chart(document.getElementById('volChart'),{type:'bar',data:{labels:ms.map(m=>MLAB[m]),datasets:[
    {label:'Integrado',data:integ,backgroundColor:C.green,borderRadius:3,datalabels:{display:true,color:'#fff',font:{weight:'700',size:10},formatter:v=>v>0?fmtN(v):''}},
    {label:'Manual',data:manual,backgroundColor:C.manual,borderRadius:3,datalabels:{display:true,color:'#5a6b85',font:{weight:'700',size:10},formatter:v=>v>0?fmtN(v):''}}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'top'}},scales:{x:{stacked:true,grid:{display:false}},y:{stacked:true,grid:{color:C.line},ticks:{callback:v=>fmtN(v)}}}}});
}
function donutChart(){
  destroy('donut');const [inI,inT]=dirTotals('IN'),[outI,outT]=dirTotals('OUT');
  const integ=inI+outI,manual=(inT-inI)+(outT-outI),tot=integ+manual;
  charts.donut=new Chart(document.getElementById('donutChart'),{type:'doughnut',data:{labels:['Integrado','Manual'],datasets:[{data:[integ,manual],backgroundColor:[C.green,C.manual],borderWidth:2,borderColor:'#fff'}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'62%',plugins:{legend:{position:'bottom'},
      datalabels:{display:true,color:'#fff',font:{weight:'800',size:14},formatter:(v)=>tot>0?Math.round(v/tot*100)+'%':''},
      tooltip:{callbacks:{label:c=>c.label+': '+fmtN(c.parsed)+' ('+(tot>0?Math.round(c.parsed/tot*100):0)+'%)'}}}}});
}
function dirChart(){
  destroy('dir');const [inI,inT]=dirTotals('IN'),[outI,outT]=dirTotals('OUT');
  const totBy=[inT,outT];
  charts.dir=new Chart(document.getElementById('dirChart'),{type:'bar',data:{labels:['Inbound','Outbound'],datasets:[
    {label:'Integrado',data:[inI,outI],backgroundColor:C.green,borderRadius:4,datalabels:{display:true,color:'#fff',font:{weight:'700',size:11},formatter:(v,ctx)=>{const t=totBy[ctx.dataIndex];return t>0?Math.round(v/t*100)+'%':'';}}},
    {label:'Manual',data:[inT-inI,outT-outI],backgroundColor:C.manual,borderRadius:4,datalabels:{display:true,color:'#5a6b85',font:{weight:'700',size:11},formatter:(v,ctx)=>{const t=totBy[ctx.dataIndex];return t>0&&v/t>0.06?Math.round(v/t*100)+'%':'';}}}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'top'}},scales:{x:{stacked:true,grid:{color:C.line},ticks:{callback:v=>fmtN(v)}},y:{stacked:true,grid:{display:false}}}}});
}
function rankChart(){
  destroy('rank');const {rows}=unitRows(state.rdir);const top=rows.slice(0,12);
  const cols=top.map(r=>r.p===null?C.muted:(r.p>=0.8?C.greenL:r.p>=0.5?C.amber:C.red));
  charts.rank=new Chart(document.getElementById('rankChart'),{type:'bar',data:{labels:top.map(r=>r.wh),datasets:[
    {label:'Total',data:top.map(r=>r.t),backgroundColor:cols,borderRadius:4,
     datalabels:{display:true,anchor:'end',align:'end',color:C.navy,font:{weight:'700',size:10},formatter:(v,ctx)=>fmtN(v)+'  ('+fmtP(top[ctx.dataIndex].p)+')'}}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,layout:{padding:{right:70}},plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>'Total: '+fmtN(c.parsed.x)+' · '+fmtP(top[c.dataIndex].p)+' integrado'}}},
      scales:{x:{grid:{color:C.line},ticks:{callback:v=>fmtN(v)}},y:{grid:{display:false}}}}});
}
function scatterChart(){
  destroy('scatter');const {rows}=unitRows(state.sdir);const pts=rows.filter(r=>r.t>0&&r.p!==null);
  const maxT=Math.max(...pts.map(r=>r.t),1);
  const data=pts.map(r=>({x:Math.round(r.p*1000)/10,y:r.t,r:6+Math.sqrt(r.t/maxT)*26,wh:r.wh,p:r.p}));
  const col=v=>v>=80?C.green:v>=50?C.amber:C.red;
  charts.scatter=new Chart(document.getElementById('scatterChart'),{type:'bubble',data:{datasets:[{data,
    backgroundColor:data.map(d=>col(d.x)+'cc'),borderColor:data.map(d=>col(d.x)),borderWidth:1.5,
    datalabels:{display:true,color:C.navy,font:{weight:'700',size:10},align:'top',offset:2,formatter:(v,ctx)=>ctx.dataset.data[ctx.dataIndex].wh}}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>{const d=c.raw;return d.wh+': '+fmtP(d.p)+' integrado · '+fmtN(d.y)+' '+METRIC_NAME[state.metric].toLowerCase();}}}},
      scales:{x:{min:0,max:100,title:{display:true,text:'% Integrado'},ticks:{callback:v=>v+'%'},grid:{color:C.line}},
        y:{type:'logarithmic',title:{display:true,text:'Volume ('+METRIC_NAME[state.metric].toLowerCase()+', log)'},grid:{color:C.line}}}}});
}

function allUnits(){const s=new Set([...Object.keys(DATA.agg.IN),...Object.keys(DATA.agg.OUT)]);return [...s].sort();}
function unitMonthPct(wh,dir){const[ii,ti]=MI();const mo=DATA.agg[dir][wh]||{};return activeMonths().map(m=>{const v=mo[m];if(!v)return null;const p=pct(v[ii],v[ti]);return p===null?null:Math.round(p*1000)/10;});}
function populateUnitSel(){
  const units=allUnits();const sel=document.getElementById('unitSel');
  if(!state.unitEvo||!units.includes(state.unitEvo)){
    // default to the unit with highest total volume
    const {rows}=unitRows('IN');const byVol=[...rows].sort((a,b)=>b.t-a.t);
    state.unitEvo=(byVol[0]&&byVol[0].wh)||units[0];
  }
  sel.innerHTML=units.map(u=>`<option value="${u}"${u===state.unitEvo?' selected':''}>${u}</option>`).join('');
}
function unitEvoChart(){
  destroy('unitEvo');const ms=activeMonths();const wh=state.unitEvo;
  const dsIn=unitMonthPct(wh,'IN'),dsOut=unitMonthPct(wh,'OUT');
  const mk=(label,data,col)=>({label,data,borderColor:col,backgroundColor:col+'22',tension:.35,spanGaps:true,pointRadius:4,pointBackgroundColor:col,borderWidth:3,fill:false,
    datalabels:{display:true,align:'top',offset:6,color:col,font:{weight:'700',size:10},formatter:v=>v==null?'':v+'%'}});
  charts.unitEvo=new Chart(document.getElementById('unitEvoChart'),{type:'line',data:{labels:ms.map(m=>MLAB[m]),datasets:[
    mk('Inbound',dsIn,C.blue),mk('Outbound',dsOut,C.outbound)]},
    options:{responsive:true,maintainAspectRatio:false,layout:{padding:{top:24}},plugins:{legend:{position:'top'},
      tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y==null?'–':c.parsed.y+'%')}}},
      scales:{y:{min:0,max:100,ticks:{callback:v=>v+'%'},grid:{color:C.line}},x:{grid:{display:false}}}}});
}
function heatColor(p){ // p in [0,1] -> pastel red -> amber -> green
  if(p===null)return '#f6f8fb';
  const stops=[[0,244,199,199],[0.4,250,224,190],[0.7,250,240,200],[0.8,205,234,205],[1,181,224,197]];
  let a=stops[0],b=stops[stops.length-1];
  for(let i=0;i<stops.length-1;i++){if(p>=stops[i][0]&&p<=stops[i+1][0]){a=stops[i];b=stops[i+1];break;}}
  const t=(p-a[0])/((b[0]-a[0])||1);
  const r=Math.round(a[1]+(b[1]-a[1])*t),g=Math.round(a[2]+(b[2]-a[2])*t),bl=Math.round(a[3]+(b[3]-a[3])*t);
  return `rgb(${r},${g},${bl})`;
}
function volShade(v,maxV){ // light blue pastel scale for volume
  if(!v)return '#f6f8fb';
  const t=Math.min(1,Math.sqrt(v/maxV));
  const r=Math.round(240-(240-186)*t),g=Math.round(245-(245-213)*t),b=Math.round(252-(252-240)*t);
  return `rgb(${r},${g},${b})`;
}
function textColorFor(p){return '#1b2b45';}
function renderMatrix(){
  const[ii,ti]=MI();const dir=state.mdir;const ms=activeMonths();const units=allUnits();const showPct=state.mval==='pct';
  // header
  let head='<thead><tr><th class="munit">Filial</th>';
  ms.forEach(m=>head+=`<th>${MLAB[m]}</th>`);
  head+='<th class="htot">Total</th></tr></thead>';
  // precompute max volume for vol shading
  let maxV=1;
  units.forEach(wh=>{const mo=DATA.agg[dir][wh]||{};ms.forEach(m=>{const v=mo[m];if(v&&v[ti]>maxV)maxV=v[ti];});});
  const colTot={};ms.concat(['TOT']).forEach(m=>colTot[m]=[0,0]);
  let body='<tbody>';
  const cell=(c,t,isTot)=>{
    const p=pct(c,t);
    if(t===0)return `<td class="hcell dash${isTot?' htot':''}">–</td>`;
    if(showPct){
      const bg=heatColor(p);const tc=textColorFor(p);
      return `<td class="hcell${isTot?' htot':''}" style="background:${bg};color:${tc}" title="${fmtN(t)} pedidos · ${fmtN(c)} integrados">${Math.round(p*100)}%</td>`;
    }else{
      const bg=volShade(t,maxV);const tc='#1b2b45';
      return `<td class="hcell${isTot?' htot':''}" style="background:${bg};color:${tc}" title="${fmtP(p)} integrado">${fmtN(t)}</td>`;
    }
  };
  units.forEach(wh=>{
    const mo=DATA.agg[dir][wh]||{};let rowI=0,rowT=0;let cells='';
    ms.forEach(m=>{const v=mo[m];const c=v?v[ii]:0,t=v?v[ti]:0;rowI+=c;rowT+=t;colTot[m][0]+=c;colTot[m][1]+=t;cells+=cell(c,t,false);});
    colTot.TOT[0]+=rowI;colTot.TOT[1]+=rowT;cells+=cell(rowI,rowT,true);
    body+=`<tr><td class="munit">${wh}</td>${cells}</tr>`;
  });
  let trow='<tr class="mtotal"><td class="munit">TOTAL</td>';
  ms.forEach(m=>{trow+=cell(colTot[m][0],colTot[m][1],false);});
  trow+=cell(colTot.TOT[0],colTot.TOT[1],true)+'</tr>';
  body+=trow+'</tbody>';
  document.getElementById('matrixTable').innerHTML=head+body;
  // legend
  const leg=document.getElementById('heatLegend');
  if(showPct){
    leg.innerHTML='<div class="heatscale"><span style="margin-right:6px">0%</span>'+
      [0,0.2,0.4,0.5,0.6,0.7,0.8,0.9,1].map(p=>`<span class="sw" style="background:${heatColor(p)}"></span>`).join('')+
      '<span style="margin-left:6px">100% integrado</span></div>';
  }else{
    leg.innerHTML='<div class="heatscale"><span style="margin-right:6px">menor</span>'+
      [0,.15,.35,.6,.85,1].map(t=>`<span class="sw" style="background:${volShade(t*maxV,maxV)}"></span>`).join('')+
      '<span style="margin-left:6px">maior volume</span></div>';
  }
}
function renderUnitTable(){
  const {rows}=unitRows(state.tdir);
  document.querySelector('#unitTable tbody').innerHTML=rows.map(r=>{
    const p=r.p;const w=p===null?0:Math.round(p*100);const barCol=p===null?'#eee':(p>=0.8?C.greenL:p>=0.5?C.amber:C.red);
    return `<tr><td class="l unit">${r.wh}</td><td>${fmtN(r.i)}</td><td>${fmtN(r.man)}</td><td>${fmtN(r.t)}</td>
      <td><span class="pct-pill ${pillClass(p)}">${fmtP(p)}</span></td>
      <td class="l"><div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${barCol}"></div></div></td>
      <td>${(r.share*100).toFixed(1)}%</td></tr>`;}).join('')||'<tr><td colspan="7" class="empty">Sem dados</td></tr>';
}
function renderCliTable(){
  const[ii,ti]=MI();const dir=state.cdir;
  const entries=Object.entries(DATA.cli[dir]).map(([c,mo])=>{let i=0,t=0;Object.entries(mo).forEach(([m,v])=>{i+=v[ii];t+=v[ti];});return {c,i,t,man:t-i,p:pct(i,t),wh:DATA.climap[c]||'—'};}).filter(e=>e.t>0);
  if(state.csort==='vol')entries.sort((a,b)=>b.t-a.t);else entries.sort((a,b)=>{const pa=a.p===null?2:a.p,pb=b.p===null?2:b.p;return pa-pb||b.t-a.t;});
  const top=entries.slice(0,25);
  document.querySelector('#cliTable tbody').innerHTML=top.map(r=>{
    const p=r.p;const w=p===null?0:Math.round(p*100);const barCol=p===null?'#eee':(p>=0.8?C.greenL:p>=0.5?C.amber:C.red);
    return `<tr><td class="l unit">${r.c}</td><td class="l">${r.wh}</td><td>${fmtN(r.i)}</td><td>${fmtN(r.man)}</td><td>${fmtN(r.t)}</td>
      <td><span class="pct-pill ${pillClass(p)}">${fmtP(p)}</span></td>
      <td class="l"><div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${barCol}"></div></div></td></tr>`;}).join('')||'<tr><td colspan="7" class="empty">Sem dados</td></tr>';
}
function diagData(){
  const[ii,ti]=MI();const units=new Set([...Object.keys(DATA.agg.IN),...Object.keys(DATA.agg.OUT)]);const rows=[];
  units.forEach(wh=>{let inI=0,inT=0,outI=0,outT=0;
    if(DATA.agg.IN[wh])Object.entries(DATA.agg.IN[wh]).forEach(([m,v])=>{inI+=v[ii];inT+=v[ti];});
    if(DATA.agg.OUT[wh])Object.entries(DATA.agg.OUT[wh]).forEach(([m,v])=>{outI+=v[ii];outT+=v[ti];});
    const tot=inT+outT,integ=inI+outI;rows.push({wh,inI,inT,outI,outT,tot,p:pct(integ,tot),pin:pct(inI,inT),pout:pct(outI,outT)});});
  rows.sort((a,b)=>b.tot-a.tot);return rows;
}
function renderDiag(){
  const rows=diagData();
  const crit=rows.filter(r=>r.p!==null&&r.p<0.5),att=rows.filter(r=>r.p!==null&&r.p>=0.5&&r.p<0.8),ok=rows.filter(r=>r.p!==null&&r.p>=0.8);
  const zone=(t,arr,cls,desc)=>`<div class="kpi ${cls}"><div class="k-label">${t}</div><div class="k-val">${arr.length}</div><div class="k-sub">${desc}</div><div style="margin-top:8px;font-size:11.5px;color:var(--muted);font-weight:700">${arr.slice(0,8).map(r=>r.wh).join(' · ')||'—'}</div></div>`;
  document.getElementById('zones').innerHTML=zone('◉ Crítico &lt; 50%',crit,'b-red','baixa integração — priorizar')+zone('◉ Atenção 50–79%',att,'b-amber','em evolução')+zone('◉ Em linha ≥ 80%',ok,'b-green','operando bem');
  const zlabel=p=>p===null?['—','']:p<0.5?['Crítico','pr']:p<0.8?['Atenção','pa']:['Em linha','pg'];
  document.querySelector('#diagTable tbody').innerHTML=rows.map(r=>{const[zl,zc]=zlabel(r.p);
    return `<tr><td class="l"><span class="pct-pill ${zc}">${zl}</span></td><td class="l unit">${r.wh}</td><td>${fmtN(r.tot)}</td>
      <td>${fmtN(r.inI)}</td><td><span class="pct-pill ${pillClass(r.pin)}">${fmtP(r.pin)}</span></td>
      <td>${fmtN(r.outI)}</td><td><span class="pct-pill ${pillClass(r.pout)}">${fmtP(r.pout)}</span></td>
      <td><span class="pct-pill ${pillClass(r.p)}">${fmtP(r.p)}</span></td></tr>`;}).join('');
  scatterChart();
}

function renderAll(){renderKPIs();evoChart();volChart();donutChart();dirChart();rankChart();populateUnitSel();unitEvoChart();renderMatrix();renderUnitTable();renderCliTable();renderDiag();
  renderCarimbo();}

document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));t.classList.add('active');
  const tab=t.dataset.tab;document.getElementById('tab-dash').classList.toggle('hidden',tab!=='dash');document.getElementById('tab-diag').classList.toggle('hidden',tab!=='diag');});
function chipGroup(sel,cb){document.querySelectorAll(sel+' .chip').forEach(c=>c.onclick=()=>{document.querySelectorAll(sel+' .chip').forEach(x=>x.classList.remove('active'));c.classList.add('active');cb(c);});}
document.querySelectorAll('[data-metric]').forEach(c=>c.onclick=()=>{document.querySelectorAll('[data-metric]').forEach(x=>x.classList.remove('active'));c.classList.add('active');state.metric=+c.dataset.metric;renderAll();});
chipGroup('#dirchips',c=>{state.dir=c.dataset.dir;evoChart();volChart();});
chipGroup('#rankdir',c=>{state.rdir=c.dataset.rdir;rankChart();});
chipGroup('#tabledir',c=>{state.tdir=c.dataset.tdir;renderUnitTable();});
chipGroup('#clidir',c=>{state.cdir=c.dataset.cdir;renderCliTable();});
chipGroup('#scatterdir',c=>{state.sdir=c.dataset.sdir;scatterChart();});
document.querySelectorAll('[data-csort]').forEach(c=>c.onclick=()=>{document.querySelectorAll('[data-csort]').forEach(x=>x.classList.remove('active'));c.classList.add('active');state.csort=c.dataset.csort;renderCliTable();});
document.getElementById('unitSel').onchange=e=>{state.unitEvo=e.target.value;unitEvoChart();};
chipGroup('#matrixdir',c=>{state.mdir=c.dataset.mdir;renderMatrix();});
chipGroup('#matrixval',c=>{state.mval=c.dataset.mval;renderMatrix();});

// ── baixar página (instantâneo autônomo) ────────────────────────────────────
// Gera um .html que abre sozinho fora do Hub — mesmo CSS e mesmo app.js deste
// arquivo, com as bibliotecas de gráfico embutidas inline (sem depender da
// pasta vendor/) e os dados atuais (BASE) gravados no arquivo em vez de
// buscados da API. xlsx.min.js fica de fora: o instantâneo é só leitura, não
// tem upload. Sem biblioteca nova — o próprio navegador monta o arquivo.
function baixarArquivo(blob,nome){
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download=nome;
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(()=>URL.revokeObjectURL(url),5000);
}
async function baixarPagina(){
  const btn=document.getElementById('btnDownload');
  const rotulo=btn.textContent;
  btn.disabled=true;btn.textContent='Gerando…';
  try{
    // Lido do próprio <script> da página em vez de escrito à mão aqui: o
    // ?v= deste arquivo muda toda vez que o app.js é editado (cache-bust), e
    // um valor fixo neste texto ficaria desatualizado no primeiro bump.
    const scriptSrc=document.querySelector('script[src^="app.js"]').getAttribute('src');
    const [tpl,chartJs,dataLabelsJs,appJs]=await Promise.all([
      fetch(location.pathname).then(r=>r.text()),
      fetch('vendor/chart.umd.js').then(r=>r.text()),
      fetch('vendor/chartjs-plugin-datalabels.min.js').then(r=>r.text()),
      fetch(scriptSrc).then(r=>r.text()),
    ]);
    // BASE pode ter nome de unidade/cliente vindo de um Excel externo (JDA) —
    // sem isso, um valor com "</script>" no meio escaparia da tag e injetaria
    // HTML/JS arbitrário no arquivo baixado.
    const safe=s=>s.replace(/<\/(script)/gi,'<\\/$1');
    const snapshot=JSON.stringify({em:new Date().toISOString(),base:BASE});
    const html=tpl
      .replace('<script src="vendor/chart.umd.js"></script>','<script>'+safe(chartJs)+'</script>')
      .replace('<script src="vendor/chartjs-plugin-datalabels.min.js"></script>','<script>'+safe(dataLabelsJs)+'</script>')
      .replace('<script src="vendor/xlsx.min.js"></script>','')
      .replace('<script src="'+scriptSrc+'"></script>','<script>window.__SNAPSHOT__='+safe(snapshot)+';</script>\n<script>'+safe(appJs)+'</script>');
    const c=new Date();
    const carimbo=c.toISOString().slice(0,16).replace('T','_').replace(/:/g,'');
    baixarArquivo(new Blob([html],{type:'text/html;charset=utf-8'}),'integracao-in-out_'+carimbo+'.html');
  }catch(err){
    console.error(err);
    alert('Não consegui gerar o arquivo: '+err.message);
  }finally{
    btn.disabled=false;btn.textContent=rotulo;
  }
}
document.getElementById('btnDownload').onclick=baixarPagina;

// ── upload do relatório ─────────────────────────────────────────────────────
document.getElementById('btnUpload').onclick=()=>document.getElementById('file').click();
document.getElementById('file').onchange=e=>{
  const f=e.target.files[0];if(!f)return;
  const pill=document.getElementById('filepill');
  const fr=new FileReader();
  fr.onload=async ev=>{
    try{
      pill.textContent='Lendo '+f.name+'…';
      const wb=XLSX.read(new Uint8Array(ev.target.result),{type:'array'});
      const {anos,linhas}=parseWorkbook(wb);
      if(!Object.keys(anos).length){
        alert('Não encontrei linhas válidas. Verifique se é a base crua do JDA (Movement Type, WH Id, Client Id, User Id, Year, Month, Order/Lines/Wave Count).');
        renderCarimbo();return;
      }
      pill.textContent='Salvando '+linhas.toLocaleString('pt-BR')+' linhas…';
      const token=localStorage.getItem('sf_portal_token')||'';
      const res=await fetch(API+'/base',{method:'POST',
        headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
        body:JSON.stringify({arquivo:f.name,linhas,anos})});
      if(res.status===401||res.status===403){pill.textContent='Você não tem permissão para atualizar esta base.';return;}
      if(!res.ok)throw new Error('status '+res.status);
      BASE=await res.json();
      const disponiveis=anosDisponiveis();
      aplicarAno(disponiveis[disponiveis.length-1]||null);
      renderYearChips();renderAll();
      document.querySelector('.wrap').scrollIntoView({behavior:'smooth'});
    }catch(err){
      console.error(err);
      alert('Erro ao ler ou salvar o arquivo: '+err.message);
      renderCarimbo();
    }finally{e.target.value='';}
  };
  fr.readAsArrayBuffer(f);
};

function renderSnapshotBanner(){
  const d=new Date(SNAPSHOT.em);
  const quando=d.toLocaleDateString('pt-BR')+' '+d.toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
  document.body.insertAdjacentHTML('afterbegin','<div class="snapshot-banner">Instantâneo baixado em '+quando+' — arquivo estático, sem conexão com o servidor. Os dados não se atualizam sozinhos.</div>');
}

(async function init(){
  // No instantâneo autônomo não existe backend pra perguntar permissão nem
  // pra receber upload — os dois controles somem e a base já vem embutida.
  const [base,podeEditar]=await Promise.all([fetchBase(),SNAPSHOT?Promise.resolve(false):fetchPodeEditar()]);
  BASE=base;
  if(SNAPSHOT){
    document.getElementById('btnUpload').remove();
    document.getElementById('file').remove();
    document.getElementById('btnDownload').remove();
    renderSnapshotBanner();
  }else if(podeEditar){
    document.getElementById('btnUpload').classList.remove('hidden');
  }
  const anos=anosDisponiveis();
  aplicarAno(anos[anos.length-1]||null);
  renderYearChips();
  renderAll();
})();
