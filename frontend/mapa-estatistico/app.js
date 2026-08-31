
if(window.pdfjsLib&&window.__PDFW){var __b=atob(window.__PDFW),__n=__b.length,__a=new Uint8Array(__n);for(var __i=0;__i<__n;__i++)__a[__i]=__b.charCodeAt(__i);pdfjsLib.GlobalWorkerOptions.workerSrc=URL.createObjectURL(new Blob([__a],{type:"application/javascript"}));}
(function(){
  const $=id=>document.getElementById(id);
  /* ---------- v2.23: dois fluxos independentes (Recebimento × Expedição) ----------
     Decisão de arquitetura: a Expedição NÃO é uma cópia do código. É o MESMO motor
     (importação → tratamento → resultado) rodando sobre um ESTADO PRÓPRIO, com os rótulos
     vindos de MODULOS. Duplicar o código significaria manter duas vezes cada correção de
     regra (SIF/SISB, peso, origem) — e elas divergiriam na primeira manutenção.
     O que a Expedição vai ter de diferente (layout de relatório, regras de cruzamento) entra
     como configuração aqui, sem tocar no fluxo de Recebimento, que continua exatamente como
     estava. Trocar de fluxo não perde nada: cada lado guarda seus arquivos e seu resultado. */
  const MODULOS={
    receb:{
      id:"receb", nome:"Recebimento", verbo:"recebido", semX:"Sem recebimento", arquivo:"recebimento",
      wmsH2:"Recebimento WMS", wmsTitulo:"Relatório de recebimento", thQtdX:"Recebido (XLSX)",
      // Coluna do relatório usada para casar com a NF conferida (a 1ª que existir no arquivo).
      chaveNf:["nf"],
      wmsNota:'Relatório extraído do <b>WMS</b> pelo Pentaho — caminho <span class="path">Pentaho › Unidades › rpt_jda_recebimento_dtl_v03</span> <a class="notelink" href="http://operationsreports.superfrio.com.br:8080/pentaho/api/repos/%3Apublic%3Aunidades%3Arpt_jda_recebimento_dtl_v03.prpt/viewer" target="_blank" rel="noopener">Abrir no Pentaho ↗</a>. Ele pode conter linhas de <b>várias notas</b> — cada uma é filtrada pela sua <b>NF</b>.'
    },
    exped:{
      id:"exped", nome:"Expedição", verbo:"expedido", semX:"Sem expedição", arquivo:"expedicao",
      wmsH2:"Expedição WMS", wmsTitulo:"Relatório de expedição", thQtdX:"Expedido (XLSX)",
      // v2.24: o relatório de expedição NÃO tem coluna "NF". Tem duas colunas de nota de
      // entrada: "NF Entrada PO_NUM" (campo livre do WMS — vem com sufixo de carga "7602.7",
      // ou até com código de pedido "AJT160626...") e "NF Entrada STR7" (o número já limpo
      // pelo próprio relatório: "7602", "1572498"). O casamento usa a STR7 — medido no
      // arquivo real, PO_NUM e STR7 divergem em 58 das 2304 linhas, e em todas elas quem
      // está certo é a STR7. PO_NUM fica como reserva, caso um relatório venha sem a STR7.
      chaveNf:["nfEntradaStr7","nfEntradaPoNum"],
      wmsNota:'Relatório <span class="path">rpt_jda_sif_expedicao_v01</span> extraído do <b>WMS</b>. O casamento usa a coluna <b>NF Entrada STR7</b> (número da nota já limpo pelo relatório) — a <b>NF Entrada PO_NUM</b> é campo livre e vem com sufixo de carga (ex.: <span class="path">7602.7</span>). Produtos sem SIF (não cárneos) são lidos normalmente e não entram na conferência de inspeção.'
    }
  };
  const novoEstado=()=>({notes:[],rows:null,colmap:null,netCol:null,nfCol:null,romCol:null,results:[],extra:{},
                         notasExcel:null,filter:"all",_id:0,step:1,tol:"0",ui:null});
  const mods={receb:novoEstado(),exped:novoEstado()};
  let modulo="receb";
  // `state` é `let` (era `const`): todo o app continua escrevendo em `state` sem saber que
  // existem dois — na troca de fluxo o ponteiro passa a apontar para o outro estado.
  let state=mods[modulo];
  const MOD=()=>MODULOS[modulo];
  const norm=s=>{ if(s==null) return ""; return String(s).split("-")[0].replace(/\D/g,"").replace(/^0+/,""); };
  const sa=s=>String(s||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
  const fmt=n=>Number(n).toLocaleString("pt-BR",{minimumFractionDigits:0,maximumFractionDigits:3});
  // sempre com 3 casas — mesma precisão do peso líquido extraído do XML/PDF (ex.: "4.400,000", não "4.400")
  const fmt3=n=>Number(n).toLocaleString("pt-BR",{minimumFractionDigits:3,maximumFractionDigits:3});
  const brNum=s=>parseFloat(String(s).replace(/\./g,"").replace(",","."));
  const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  function parsePeso(v){
    if(v==null) return NaN;
    let s=String(v).trim();
    if(s==="") return NaN;
    if(s.includes(",")){ s=s.replace(/\./g,"").replace(",","."); } // formato BR: ponto=milhar, vírgula=decimal
    const n=parseFloat(s);
    return isNaN(n)?NaN:n;
  }
  // Mantém o formato do nome do arquivo (com zero à frente). Procura no nome um grupo de
  // dígitos que, sem zeros à esquerda, seja igual à NF extraída; senão prefixa um "0".
  function nfComoNoArquivo(nome,nf){
    const grupos=String(nome||"").match(/\d+/g)||[];
    for(const g of grupos){ if(g.replace(/^0+/,"")===nf) return g; }
    return nf?("0"+nf):nf;
  }

  // v2.17: wizard de 2 passos (1 = importar notas + Excel na mesma tela, 2 = resultado).
  // v2.23: o passo passou a ser guardado no estado do fluxo, para a troca voltar onde parou.
  function goStep(n){state.step=n;[1,2].forEach(i=>{$("scr"+i).classList.toggle("active",i===n);const st=$("st"+i);st.classList.toggle("active",i===n);st.classList.toggle("done",i<n);});window.scrollTo({top:0,behavior:"smooth"});}

  /* ---------- v2.23: troca entre Recebimento e Expedição ---------- */
  function aplicarRotulos(){
    const m=MOD();
    $("eyebrow1").textContent="Análise · "+m.nome;
    $("eyebrow2").textContent="Análise · "+m.nome;
    $("wmsH2").textContent=m.wmsH2;
    $("wmsTitulo").textContent=m.wmsTitulo;
    $("wmsNota").innerHTML=m.wmsNota;
    $("thQtdX").textContent=m.thQtdX;
    $("leadRes").textContent="Peso líquido esperado (nota) × "+m.verbo+" (WMS), por NF. Clique numa linha para ver o detalhe por lote.";
    [["modReceb","receb"],["modExped","exped"]].forEach(([id,k])=>{
      const el=$(id); el.classList.toggle("active",modulo===k); el.setAttribute("aria-pressed",String(modulo===k));
    });
  }
  // A lista de arquivos importados e o painel de colunas são escritos direto no DOM (não dá
  // para redesenhá-los a partir do estado), então o HTML deles é guardado no fluxo que sai.
  const UI_PADRAO={pdfList:"",pdfListShow:false,pdfTitle:"Arraste os PDFs ou XMLs aqui ou clique para selecionar",
                   dropTitle:"Arraste a planilha aqui ou clique para selecionar",dropSub:"Formato .xlsx, .xls ou .csv",
                   detect:"",detectShow:false};
  function snapshotUI(){
    state.tol=$("tol").value;
    state.ui={pdfList:$("pdfList").innerHTML,pdfListShow:$("pdfList").classList.contains("show"),
              pdfTitle:$("pdfTitle").textContent,dropTitle:$("dropTitle").textContent,dropSub:$("dropSub").textContent,
              detect:$("detect").innerHTML,detectShow:$("detect").classList.contains("show")};
  }
  function restoreUI(){
    const u=state.ui||UI_PADRAO;
    $("pdfList").innerHTML=u.pdfList; $("pdfList").classList.toggle("show",u.pdfListShow);
    $("pdfTitle").textContent=u.pdfTitle;
    $("dropTitle").textContent=u.dropTitle; $("dropSub").textContent=u.dropSub;
    $("detect").innerHTML=u.detect; $("detect").classList.toggle("show",u.detectShow);
    $("tol").value=state.tol;
  }
  // Fluxo ainda sem conferência feita: KPIs em "—" (e não em zero, que sugeriria "conferi e deu 0").
  function resetResultado(){
    ["sNotas","sExcel","sOk","sWarn","sDiff"].forEach(id=>{ const e=$(id); if(e) e.textContent="—"; });
    $("sDiff").parentElement.className="stat";
    $("resBody").innerHTML=""; $("extra").innerHTML=""; $("filterInfo").textContent="";
  }
  function trocarModulo(m){
    if(m===modulo) return;
    snapshotUI();                                   // guarda o que está na tela no fluxo que sai
    modulo=m; state=mods[m];                        // ponteiro passa para o outro estado
    aplicarRotulos(); restoreUI();
    if(!state.notes.length) addNote(); else renderNotes();   // renderNotes já chama syncConferir
    updateFilterButtons();
    if(state.results.length) applyTolerance(); else resetResultado();
    goStep(state.step);
  }

  /* ---------- notes table ---------- */
  function updateEditedBadge(tr,n){
    const orgTd = tr.querySelector("td.org");
    const nfEdited = n.origin!=="manual" && n.nfOriginal!==undefined && n.nf!==n.nfOriginal;
    const peEdited = n.origin!=="manual" && n.pesoOriginal!==undefined && n.peso!==n.pesoOriginal;
    let badge = orgTd.querySelector(".edited-badge");
    if(nfEdited||peEdited){
      if(!badge){ badge=document.createElement("span"); badge.className="edited-badge"; badge.textContent="✏️ Editado manualmente"; orgTd.appendChild(badge); }
    } else if(badge){ badge.remove(); }
  }
  function addNote(nf="",peso="",origin="manual",flag=false){ state.notes.push({id:++state._id,nf:String(nf),peso:String(peso),origin,flag,nfOriginal:String(nf),pesoOriginal:String(peso)}); renderNotes(); }
  function removeNote(id){
    const n=state.notes.find(n=>n.id===id);
    const temDados=n&&(n.nf.trim()!==""||n.peso.trim()!=="");
    if(temDados && !confirm(`Remover a nota ${n.nf?("NF "+n.nf):"(sem NF)"}? Essa ação não pode ser desfeita.`)) return;
    state.notes=state.notes.filter(n=>n.id!==id); if(!state.notes.length) addNote(); else{renderNotes();}
  }
  function renderNotes(){
    const tb=$("notesBody"); tb.innerHTML="";
    state.notes.forEach(n=>{
      const tr=document.createElement("tr");
      const nfEdited = n.origin!=="manual" && n.nfOriginal!==undefined && n.nf!==n.nfOriginal;
      const peEdited = n.origin!=="manual" && n.pesoOriginal!==undefined && n.peso!==n.pesoOriginal;
      tr.innerHTML=
        `<td class="nf"><input type="text" inputmode="numeric" aria-label="Número da NF" placeholder="ex: 25027" value="${esc(n.nf)}"></td>`+
        `<td class="pe"><input type="text" inputmode="decimal" aria-label="Peso líquido esperado (kg)" placeholder="ex: 27000,000" value="${esc(n.peso)}"></td>`+
        `<td class="org"><span class="origin">${esc(n.origin)}</span>${(nfEdited||peEdited)?'<span class="edited-badge">✏️ Editado manualmente</span>':''}</td>`+
        `<td class="rm"><button class="iconbtn" title="Remover" aria-label="Remover nota">×</button></td>`;
      const [inNf,inPe]=tr.querySelectorAll("input");
      if(n.flag) inPe.classList.add("flag");
      if(n.nfFlag) inNf.classList.add("flag");
      if(nfEdited && !n.nfFlag) inNf.classList.add("edited");
      if(peEdited && !n.flag) inPe.classList.add("edited");
      inNf.title = nfEdited ? `Valor original extraído: ${n.nfOriginal}` : "";
      inPe.title = peEdited ? `Valor original extraído: ${n.pesoOriginal}` : "";
      inNf.addEventListener("input",()=>{
        n.nf=inNf.value;n.nfFlag=false;inNf.classList.remove("flag");
        const ed = n.origin!=="manual" && n.nfOriginal!==undefined && n.nf!==n.nfOriginal;
        inNf.classList.toggle("edited",ed); inNf.title = ed?`Valor original extraído: ${n.nfOriginal}`:"";
        updateEditedBadge(tr,n); validateNotes();
      });
      inPe.addEventListener("input",()=>{
        n.peso=inPe.value;n.flag=false;inPe.classList.remove("flag");
        const ed = n.origin!=="manual" && n.pesoOriginal!==undefined && n.peso!==n.pesoOriginal;
        inPe.classList.toggle("edited",ed); inPe.title = ed?`Valor original extraído: ${n.pesoOriginal}`:"";
        updateEditedBadge(tr,n); validateNotes();
      });
      tr.querySelector(".iconbtn").addEventListener("click",()=>removeNote(n.id));
      tb.appendChild(tr);
    });
    validateNotes();
  }
  const validNotes=()=>state.notes.filter(n=>n.nf.trim()!=="" && n.peso!=="" && !isNaN(parsePeso(n.peso)));
  // Declaração de função (hoisted) porque syncConferir é chamado por renderNotes, que roda
  // na inicialização — antes do ponto onde este helper aparece no arquivo.
  function excelPronto(){ return !!(state.rows && state.netCol); }
  // v2.17: com as duas importações na mesma tela, o único botão de avanço é o "Conferir",
  // e ele só libera quando os DOIS lados estão prontos (antes o gate era em dois passos:
  // "Continuar para importação" exigia as notas e "Conferir" exigia o Excel).
  function syncConferir(){ $("conferir").disabled = !(validNotes().length && excelPronto()); }
  const validateNotes=syncConferir;
  function clearEmpty(){ state.notes=state.notes.filter(n=>n.nf.trim()!=="" || n.peso.trim()!==""); }

  $("addRow").addEventListener("click",()=>addNote());
  $("bulkBtn").addEventListener("click",()=>{
    const lines=$("bulkTxt").value.split(/\r?\n/).map(l=>l.trim()).filter(Boolean); let added=0;
    clearEmpty();
    lines.forEach(l=>{ const p=l.split(/[;,\t]+/).map(x=>x.trim()).filter(Boolean);
      if(p.length>=2){const nfV=p[0],peV=String(brNum(p[p.length-1]));state.notes.push({id:++state._id,nf:nfV,peso:peV,origin:"lista",flag:false,nfOriginal:nfV,pesoOriginal:peV});added++;}
      else if(p.length===1){state.notes.push({id:++state._id,nf:p[0],peso:"",origin:"lista",flag:true,nfOriginal:p[0],pesoOriginal:""});added++;}
    });
    if(added){$("bulkTxt").value="";renderNotes();}
  });

  $("backStep1b").addEventListener("click",()=>goStep(1));
  // Navegação por clique nas etapas da sidebar (com travas p/ não abrir tela sem dados)
  $("st1").addEventListener("click",()=>goStep(1));
  $("st2").addEventListener("click",()=>{
    if(validNotes().length && excelPronto()){ conferir(); goStep(2); }
    else if(state.results.length){ goStep(2); }
  });

  /* ---------- PDF import ---------- */
  const pdfDrop=$("pdfDrop"),pdfInput=$("pdfFile");
  ["dragenter","dragover"].forEach(e=>pdfDrop.addEventListener(e,ev=>{ev.preventDefault();pdfDrop.classList.add("drag");}));
  ["dragleave","drop"].forEach(e=>pdfDrop.addEventListener(e,ev=>{ev.preventDefault();pdfDrop.classList.remove("drag");}));
  pdfDrop.addEventListener("drop",ev=>{ if(ev.dataTransfer.files.length) handlePdfs(ev.dataTransfer.files); });
  pdfInput.addEventListener("change",()=>{ if(pdfInput.files.length) handlePdfs(pdfInput.files); });

  async function handlePdfs(files){
    $("pdfList").classList.add("show");
    clearEmpty();
    const total=files.length; let processed=0;
    for(const f of files){
      processed++;
      $("pdfTitle").textContent=`Processando ${processed} de ${total}…`;
      const isXml=/\.xml$/i.test(f.name)||f.type==="text/xml"||f.type==="application/xml";
      const tipo=isXml?"XML":"PDF";
      const itm=document.createElement("div"); itm.className="it";
      itm.innerHTML=`<span class="ic busy">…</span><span class="fn">${esc(f.name)}</span><span class="vals"></span>`;
      $("pdfList").appendChild(itm);
      try{
        const data=isXml?await extractXml(f):await extractPdf(f);
        if(data.nf){
          const disp=nfComoNoArquivo(f.name,data.nf);
          const jaExiste=state.notes.some(n=>String(n.nf).trim()===String(disp).trim());
          if(jaExiste){
            itm.querySelector(".ic").className="ic warn"; itm.querySelector(".ic").textContent="↺";
            itm.querySelector(".vals").textContent="NF "+disp+" · já importada — ignorada";
          }else{
            const pesoStr=data.liq!=null?String(data.liq):"";
            state.notes.push({id:++state._id,nf:disp,peso:pesoStr,origin:tipo+": "+f.name,flag:data.liq==null||!!data.pesoWarn,nfFlag:!!data.nfWarn,sif:data.sif||"",sisb:data.sisb||"",itens:data.itens||[],nfOriginal:disp,pesoOriginal:pesoStr});
            const okAll=data.liq!=null && !data.nfWarn && !data.pesoWarn;
            itm.querySelector(".ic").className="ic "+(okAll?"ok":"warn");
            itm.querySelector(".ic").textContent=okAll?"✓":"⚠";
            const obs=[]; if(data.nfWarn) obs.push("revisar NF"); if(data.liq==null) obs.push("revisar peso");
            if(data.pesoWarn) obs.push("peso do cabeçalho não batia com a soma dos itens — usado o valor somado");
            itm.querySelector(".vals").textContent="NF "+disp+(data.liq!=null?(" · "+fmt(data.liq)+" kg"):"")+(obs.length?" · "+obs.join(", "):"");
          }
        }else{
          itm.querySelector(".ic").className="ic warn"; itm.querySelector(".ic").textContent="⚠";
          itm.querySelector(".vals").textContent="NF não identificada — adicione manual";
        }
      }catch(err){
        console.error("Falha ao ler "+f.name+":",err);
        itm.querySelector(".ic").className="ic warn"; itm.querySelector(".ic").textContent="⚠";
        itm.querySelector(".vals").textContent="não consegui ler este "+tipo+" ("+(err&&err.message?err.message:"erro desconhecido")+")";
      }
      renderNotes();
    }
    $("pdfTitle").textContent="Adicionar mais arquivos (PDF ou XML)";
  }

  async function extractXml(file){
    const text=await file.text();
    return parseXmlNFe(text);
  }
  // Lê a NF-e a partir do XML — descrição vem de <xProd> (fonte oficial)
  function parseXmlNFe(text){
    const doc=new DOMParser().parseFromString(text,"text/xml");
    const first=t=>{ const el=doc.getElementsByTagName(t); return el.length?el[0]:null; };
    const txt=(el)=>el?el.textContent.trim():null;
    let nf=null;
    const nNF=first("nNF"); if(nNF&&txt(nNF)) nf=String(parseInt(txt(nNF),10));
    const infNFe=first("infNFe");
    if(!nf && infNFe){ const id=(infNFe.getAttribute("Id")||"").replace(/\D/g,""); if(id.length===44) nf=String(parseInt(id.substr(25,9),10)); }
    let liq=null,bru=null;
    const pl=first("pesoL"); if(pl&&txt(pl)) liq=parseFloat(txt(pl));
    const pb=first("pesoB"); if(pb&&txt(pb)) bru=parseFloat(txt(pb));
    const itens=[];
    const prods=doc.getElementsByTagName("prod");
    for(let i=0;i<prods.length;i++){
      const p=prods[i];
      const g=t=>{ const e=p.getElementsByTagName(t); return e.length?e[0].textContent.trim():null; };
      const unid=g("uCom")||""; const qtd=g("qCom")?parseFloat(g("qCom")):null;
      // Origem (Tabela "A"): a tag <orig> fica no <imposto><ICMS><ICMSxx> do mesmo <det>,
      // fora do <prod> — por isso a busca sobe para o elemento pai.
      const det=p.parentNode;
      const og=det?det.getElementsByTagName("orig"):null;
      const cst=(og&&og.length)?og[0].textContent.trim():null;
      itens.push({codigo:g("cProd"), desc:g("xProd")||"", unid, qtd, cst, peso:/^KG/i.test(unid)?qtd:null});
    }
    // Mesma validação do PDF: quando todos os itens têm peso (uCom="KG"), a soma tem que bater
    // com <pesoL>. Se não bater (ou <pesoL> não vier), a soma dos itens é quem manda.
    let pesoWarn=false;
    if(itens.length && itens.every(it=>it.peso!=null)){
      const soma=Math.round(itens.reduce((a,it)=>a+it.peso,0)*1000)/1000; // evita ruído de ponto flutuante
      if(liq==null){ liq=soma; }
      else if(Math.abs(soma-liq)>0.5){ pesoWarn=true; liq=soma; }
    }
    return {nf,liq,bru,nfWarn:false,pesoWarn,sif:extractSif(text),sisb:extractSisb(text),itens};
  }

  async function extractPdf(file){
    const buf=await file.arrayBuffer();
    const pdf=await pdfjsLib.getDocument({data:buf}).promise;
    let full=""; const items=[];
    for(let p=1;p<=pdf.numPages;p++){
      const page=await pdf.getPage(p);
      const tc=await page.getTextContent();
      tc.items.forEach(it=>{ full+=it.str+" "; items.push({s:it.str,x:it.transform[4],y:it.transform[5]}); });
    }
    return parseDanfe(full,items);
  }

  // valida o dígito verificador (mód-11) de uma chave NF-e de 44 dígitos
  function chaveDvOk(k){
    let w=2,sum=0;
    for(let i=42;i>=0;i--){ sum+=parseInt(k[i],10)*w; w=(w===9)?2:w+1; }
    const r=sum%11; const dv=(r===0||r===1)?0:11-r;
    return dv===parseInt(k[43],10);
  }
  const nNFdaChave=k=>String(parseInt(k.substr(25,9),10));
  /* ---------- Origem da mercadoria: NACIONAL × ESTRANGEIRA ---------- */
  // Tabela "A" da NF-e (Origem da Mercadoria ou Serviço). É o 1º dígito do CST impresso na
  // tabela de itens do DANFE (ex.: CST "050" -> origem 0) e a tag <orig> do ICMS no XML.
  // Fonte oficial e por item — mais confiável que a descrição do produto.
  const ORIGEM_TAB={
    "0":"Nacional, exceto as indicadas nos códigos 3, 4, 5 e 8",
    "1":"Estrangeira — Importação direta, exceto a indicada no código 6",
    "2":"Estrangeira — Adquirida no mercado interno, exceto a indicada no código 7",
    "3":"Nacional, mercadoria ou bem com Conteúdo de Importação superior a 40% e igual ou inferior a 70%",
    "4":"Nacional, cuja produção tenha sido feita em conformidade com os processos produtivos básicos (DL 288/1967 e leis correlatas)",
    "5":"Nacional, mercadoria ou bem com Conteúdo de Importação inferior ou igual a 40%",
    "6":"Estrangeira — Importação direta, sem similar nacional, constante em lista de Resolução Camex e gás natural",
    "7":"Estrangeira — Adquirida no mercado interno, sem similar nacional, constante em lista de Resolução Camex e gás natural",
    "8":"Nacional — Mercadoria ou bem com Conteúdo de Importação superior a 70%"
  };
  const ORIGEM_ESTRANGEIRA=new Set(["1","2","6","7"]);   // os demais (0,3,4,5,8) são nacionais
  // Converte o CST (ou a tag <orig>) no código de origem da Tabela "A".
  // "050"/"0102" -> "0" (1º dígito); "2" -> "2". CST de 2 dígitos NÃO carrega origem -> null.
  function origFromCst(cst){
    const d=String(cst==null?"":cst).replace(/\D/g,"");
    if(!d) return null;
    const c=(d.length>=3)?d[0]:(d.length===1?d:null);
    if(c==null||!ORIGEM_TAB[c]) return null;
    return {code:c, nacional:!ORIGEM_ESTRANGEIRA.has(c), src:"cst"};
  }
  // Fallback: mapeia a descrição do produto quando o CST não foi capturado.
  // Só termos inequívocos — nada de siglas curtas ("AR", "PY"), que dariam falso positivo
  // dentro de palavras de descrição de carne/embalagem.
  const RX_DESC_EST=/\b(IMPORTAD[OA]S?|IMPORTACAO|IMPORT|ESTRANGEIR[OA]S?|URUGUAI[OA]?S?|ARGENTIN[OA]S?|PARAGUAI[OA]?S?|CHILEN[OA]S?|BOLIVIAN[OA]S?|MERCOSUL)\b/;
  const RX_DESC_NAC=/\b(NACIONAL(?:ES)?|NAC)\b/;
  function origFromDesc(desc){
    const t=sa(desc||"").toUpperCase();
    if(!t) return null;
    const est=RX_DESC_EST.test(t), nac=RX_DESC_NAC.test(t);
    if(est===nac) return null;                            // nenhum termo, ou os dois -> inconclusivo
    return {code:null, nacional:nac, src:"desc"};
  }
  // Origem de um item: CST manda; se não veio, cai para a descrição.
  function origemItem(it){
    if(!it) return null;
    return origFromCst(it.cst) || origFromDesc(it.desc);
  }
  // Célula da coluna Origem no detalhamento.
  function origemCell(o){
    if(!o) return "—";
    const rot=o.nacional?"Nacional":"Estrangeira";
    if(o.src==="cst"){
      return `<span class="orig" title="${esc("CST/origem "+o.code+" — "+ORIGEM_TAB[o.code])}">`+
             `${rot} <span class="oc">(${o.code})</span></span>`;
    }
    return `<span class="orig infer" title="Inferida pela descrição do produto — o CST/origem não foi capturado nesta nota">`+
           `${rot} <span class="oc">(desc.)</span></span>`;
  }

  // SIF (Serviço de Inspeção Federal) — extrai SÓ O NÚMERO do SIF dos dados adicionais.
  // O rótulo costuma vir como "LACRE SIF :0006974/SIF1889", onde o SIF real é só o "1889"
  // (número após o "SIF" interno). Se não houver "SIF" interno, usa o 1º grupo de dígitos
  // do token (ex.: "236-ICMS" -> 236, "2544" -> 2544).
  // Generalizado na v2.14 para atender SIF e SISB com a mesma mecânica — `rot` é o trecho de
  // regex do rótulo (alternativas mais longas primeiro, ex.: "SISBI|SISB").
  function extractReg(s,rot){
    if(!s) return "";
    let m=new RegExp("LACRE\\s+(?:"+rot+")\\s*:?\\s*([0-9][\\w\\/.\\-]*)","i").exec(s);
    if(!m) m=new RegExp("\\b(?:"+rot+")\\s*:?\\s*([0-9][\\w\\/.\\-]*)","i").exec(s);
    if(!m) return "";
    const tok=m[1].replace(/[.\s]+$/,"").trim();
    const inner=[...tok.matchAll(new RegExp("(?:"+rot+")\\s*(\\d+)","ig"))];  // "0006974/SIF1889" -> 1889
    if(inner.length) return inner[inner.length-1][1];
    const num=/(\d+)/.exec(tok);                            // senão, o número do token
    return num?num[1]:"";
  }
  const extractSif =s=>extractReg(s,"SIF");
  // SISB — Sistema Brasileiro de Inspeção de Produtos de Origem Animal (SISBI/POA). Mesmo
  // tratamento do SIF: aceita "SISBI" e "SISB", com ou sem "LACRE" na frente.
  const extractSisb=s=>extractReg(s,"SISBI|SISB");

  // Acha o Y (geometria PDF) da linha de cabeçalho "CÓD/DESCRIÇÃO/NCM" da tabela de itens —
  // usado para excluir os tokens da tabela de produtos ao procurar o peso do CABEÇALHO da nota.
  function findTableHeaderY(items){
    if(!items||!items.length) return null;
    const TOLY=3;
    const toks=items.map(it=>({x:it.x,y:it.y,s:(it.s||"").trim()})).filter(it=>it.s!=="");
    toks.sort((a,b)=>(b.y-a.y)||(a.x-b.x));
    const lines=[]; let cur=null;
    toks.forEach(it=>{ if(!cur||Math.abs(it.y-cur.y)>TOLY){cur={y:it.y,parts:[]};lines.push(cur);} cur.parts.push(it); });
    lines.forEach(l=>{ l.text=l.parts.map(p=>p.s).filter(Boolean).join(" ").replace(/\s+/g," ").trim(); });
    const hl=lines.find(l=>{ const t=l.text.toUpperCase(); return /C[ÓO]D/.test(t)&&/DESCRI[ÇC][ÃA]O/.test(t)&&/NCM/.test(t); });
    return hl?hl.y:null;
  }
  function parseDanfe(full,items){
    // ---- Número da NF: chave de acesso da NF-e (autoritativa) + Nº impresso como apoio ----
    // Coleta candidatos a chave de 44 dígitos (contíguos e formatados 4-4-4...)
    const cands=new Set();
    (full.match(/\d{44}/g)||[]).forEach(k=>cands.add(k));
    let g; const reKey=/(?:\d{4}[\s.]+){10}\d{4}/g;
    while((g=reKey.exec(full))){ cands.add(g[0].replace(/\D/g,"")); }
    // Mantém só chaves NF-e plausíveis: UF válida (11–53), modelo 55/65 e dígito verificador correto.
    // Isso descarta boletos, números longos aleatórios e textos como "Nº 02032900".
    const validKeys=[...cands].filter(k=>k.length===44
        && /^(?:1[1-9]|2[0-9]|3[0-5]|4[1-3]|5[0-3])/.test(k)
        && (k.substr(20,2)==="55"||k.substr(20,2)==="65")
        && chaveDvOk(k));
    // Nº impresso no DANFE ("Nº 000.344.799") — apenas apoio/desempate
    let nfPrinted=null;
    const t=full.match(/N[ºo°]\s*0*([\d][\d.]{4,})/i);
    if(t){ const d=t[1].replace(/\D/g,"").replace(/^0+/,""); if(d) nfPrinted=d; }
    // Decisão: a CHAVE validada manda. O Nº impresso só resolve empate (várias chaves) ou serve de fallback.
    let nf=null, nfWarn=false;
    if(validKeys.length===1){
      nf=nNFdaChave(validKeys[0]);                 // chave única e válida → confiável
    }else if(validKeys.length>1){
      const bate=nfPrinted ? validKeys.find(k=>nNFdaChave(k)===nfPrinted) : null;
      if(bate){ nf=nfPrinted; }                    // várias chaves (ex.: nota referenciada) → usa a que bate com o Nº
      else { nf=nNFdaChave(validKeys[0]); nfWarn=true; }
    }else if(nfPrinted){
      nf=nfPrinted; nfWarn=true;                   // sem chave válida → usa o Nº impresso e marca p/ revisão
    }

    const itens=parseItens(full,items);
    // Restringe a busca do peso do CABEÇALHO à região ANTES da tabela de itens (por posição, não
    // por valor). Numa nota de item único o peso do item é IGUAL ao peso líquido do cabeçalho —
    // filtrar "valores iguais ao peso de algum item" (abordagem anterior) removia o próprio peso
    // líquido correto nesse caso, sobrando só o peso bruto como único candidato. Usando a posição
    // (tudo que vem depois do cabeçalho "CÓD/DESCRIÇÃO/NCM" da tabela é ignorado) evita isso.
    const tableY=findTableHeaderY(items);
    const headerIdx=full.search(/dados do produto/i);
    const headerText=headerIdx>=0?full.slice(0,headerIdx):full;
    const headerItems=tableY!=null?items.filter(it=>it.y>=tableY-1):items;
    // pesos: números com exatamente 3 casas decimais (padrão dos campos de peso da DANFE)
    const re=/\d{1,3}(?:\.\d{3})*,\d{3}(?!\d)/g;
    const found=(headerText.match(re)||[]).map(brNum).filter(v=>!isNaN(v));
    let liq=null,bru=null;
    if(found.length===1){ liq=found[0]; }
    else if(found.length>=2){
      // tenta achar pelo rótulo "LÍQUIDO"
      const lab=headerItems.find(it=>/l[ií]quido/i.test(it.s));
      if(lab){
        let best=null,bd=1e9;
        headerItems.forEach(it=>{ if(!re.test(it.s)){re.lastIndex=0;return;} re.lastIndex=0;
          const val=brNum(it.s.match(re)[0]);
          const dy=lab.y-it.y, dx=Math.abs(it.x-lab.x);
          if(dy>=-2){ const d=dy+dx*0.15; if(d<bd){bd=d;best=val;} }
        });
        if(best!=null && !isNaN(best)) liq=best;
      }
      if(liq==null){ liq=Math.min(...found); } // fallback: líquido é o menor dos pesos
      bru=Math.max(...found);
    }
    // Validação: confere a soma dos pesos dos itens contra o peso líquido do cabeçalho.
    // A soma vem direto da coluna PESO de cada produto, então é mais confiável que a heurística
    // de proximidade de rótulo quando todos os itens têm peso. Se a soma bate com ALGUM peso
    // impresso na nota (= ela É o PESO LÍQUIDO oficial), quem errou foi a heurística de rótulo
    // (ex.: layout Fricasa, onde o valor do BRUTO cai mais perto do rótulo "PESO LIQUIDO" do que
    // o próprio valor do líquido) — usa o valor impresso SEM avisar. Só avisa quando a soma não
    // corresponde a nenhum peso impresso.
    let pesoWarn=false;
    if(itens && itens.length && itens.every(it=>it.peso!=null)){
      const soma=Math.round(itens.reduce((s,it)=>s+it.peso,0)*1000)/1000; // evita ruído de ponto flutuante
      if(liq==null){ liq=soma; }
      else if(Math.abs(soma-liq)>0.5){
        const impresso=found.find(v=>Math.abs(v-soma)<=0.5);
        if(impresso!=null){ liq=impresso; }   // soma confere com o líquido impresso → sem aviso
        else { pesoWarn=true; liq=soma; }
      }
    }
    return {nf,liq,bru,nfWarn,pesoWarn,sif:extractSif(full),sisb:extractSisb(full),itens};
  }
  // Extrai itens da tabela "DADOS DO PRODUTO/SERVIÇOS".
  // Principal: reconstrói as LINHAS pela geometria (agrupa por Y, ordena por X), porque vários
  // DANFEs (ex.: layout Btz/Jaguafrangos) entregam o texto fora de ordem de leitura — a descrição
  // vem depois dos valores e os rótulos das seções vêm todos juntos, o que fazia a região colapsar
  // e nenhum item ser capturado. Se a geometria não achar nada, cai no método antigo por texto.
  // COD  DESC  NCM(8)  CST(2-3)  CFOP(4)  UNID  QTD
  // O código exige >=1 dígito (lookahead) para não casar com sobras do cabeçalho ("ICMS","IPI","AL.")
  // que às vezes ficam grudadas na mesma linha do primeiro item, confundindo código/descrição.
  // CST/CFOP e UNID/QTDE podem vir separados por espaço OU grudados com "/" (ex.: DANFE BRF/Sadia:
  // "050/5905", "CX/1.980"), e a QTDE nesse layout é inteira (sem vírgula decimal) — daí o [\s\/]+
  // como separador e a parte decimal da QTDE ser opcional.
  // O CST (grupo 4) passou a ser capturado na v2.12: seu 1º dígito é a origem da mercadoria
  // (Tabela "A" da NF-e). Grupos: 1=código 2=descrição 3=NCM 4=CST 5=CFOP 6=UNID 7=QTDE.
  const RX_ITEM=/((?=[A-Z0-9.\-\/]*\d)[A-Z0-9][A-Z0-9.\-\/]{1,19})\s+([A-Za-zÀ-ÿ][\s\S]{1,80}?)\s+(\d{4}\.?\d{2}\.?\d{2})\s+(\d{2,3})[\s\/]+(\d{4})\s+([A-Z]{1,4})[\s\/]+(\d[\d.]*(?:,\d+)?)/;
  const RX_END=/^-{5,}|informa[cç][oõ]es\s+complementares|c[aá]lculo do issqn|dados adicionais|reservado ao fisco/i;
  // A coluna PESO fica no fim da linha do DANFE, depois de VL.UNIT/VALOR TOTAL/B.ICMS/...,
  // e é o único valor da linha com 3 casas decimais (os demais valores monetários usam 2).
  const RX_PESO=/\d[\d.]*,\d{3}(?!\d)/g;
  function extractPeso(trailingText,unid,qtd){
    const nums=trailingText.match(RX_PESO);
    if(nums&&nums.length) return brNum(nums[nums.length-1]);
    return /^KG/i.test(unid)?qtd:null;
  }
  function parseItensGeo(items){
    if(!items||!items.length) return null;
    const TOLY=3;
    const toks=items.map(it=>({x:it.x,y:it.y,s:(it.s||"").trim()})).filter(it=>it.s!=="");
    toks.sort((a,b)=>(b.y-a.y)||(a.x-b.x));              // topo→base, esq→dir
    const lines=[]; let cur=null;
    toks.forEach(it=>{ if(!cur||Math.abs(it.y-cur.y)>TOLY){cur={y:it.y,parts:[]};lines.push(cur);} cur.parts.push(it); });
    lines.forEach(l=>{ l.parts.sort((a,b)=>a.x-b.x);
      l.text=l.parts.map(p=>p.s).filter(Boolean).join(" ").replace(/\s+/g," ").trim();
      l.minx=Math.min.apply(null,l.parts.map(p=>p.x)); });
    // acha o cabeçalho da tabela e onde começam as colunas DESCRIÇÃO e NCM
    let hi=-1, descX=98, ncmX=298;
    for(let i=0;i<lines.length;i++){ const t=lines[i].text.toUpperCase();
      if(/C[ÓO]D/.test(t)&&/DESCRI[ÇC][ÃA]O/.test(t)&&/NCM/.test(t)){
        hi=i;
        const dp=lines[i].parts.find(p=>/DESCRI[ÇC][ÃA]O/i.test(p.s)); if(dp) descX=dp.x;
        const np=lines[i].parts.find(p=>/NCM/i.test(p.s)); if(np) ncmX=np.x;
        break; } }
    if(hi<0) return null;
    const itens=[];
    for(let i=hi+1;i<lines.length;i++){
      const L=lines[i];
      if(RX_END.test(L.text)) break;
      const m=RX_ITEM.exec(L.text);
      if(m){
        const codigo=m[1]; let desc=m[2].replace(/\s+/g," ").trim();
        const cst=m[4], unid=m[6], qtd=brNum(m[7]);
        // anexa quebras de linha da descrição (abaixo, na coluna da descrição, sem ser item nem fim)
        let j=i+1;
        while(j<lines.length){
          const N=lines[j];
          if(RX_END.test(N.text)||RX_ITEM.test(N.text)) break;
          const inDesc=N.minx>=descX-2 && N.minx<ncmX-2;
          const looksData=/\d{4}\.?\d{2}\.?\d{2}/.test(N.text);
          if(inDesc && !looksData && N.text.length<=60){ desc+=" "+N.text; j++; } else break;
        }
        desc=desc.replace(/\s+/g," ").replace(/\s*-\s*$/,"").trim();
        const peso=extractPeso(L.text.slice(m.index+m[0].length),unid,qtd);
        itens.push({codigo, desc, unid, qtd, cst, peso});
        i=j-1;
      }
    }
    return itens.length?itens:null;
  }
  function parseItensTexto(full){
    let region=full;
    const s=/dados do produto/i.exec(full);
    if(s){
      const sIdx=s.index; const tail=full.slice(sIdx+10);
      const ends=[/c[aá]lculo do issqn/i,/dados adicionais/i,/informa[cç][oõ]es complementares/i,/reservado ao fisco/i];
      let eIdx=-1;
      ends.forEach(rx=>{ const m=rx.exec(tail); if(m){ const idx=sIdx+10+m.index; if(eIdx<0||idx<eIdx) eIdx=idx; } });
      region=(eIdx>sIdx)?full.slice(sIdx,eIdx):full.slice(sIdx);
    }
    const h=/al[ií]?q[^a-z0-9]*ipi/i.exec(region);
    const body=h?region.slice(h.index+h[0].length):region;
    const rx=new RegExp(RX_ITEM.source,"g");
    const matches=[]; let m;
    while((m=rx.exec(body))) matches.push(m);
    const itens=matches.map((m,idx)=>{
      const unid=m[6], qtd=brNum(m[7]);
      const desc=m[2].replace(/\s+/g," ").replace(/\s*-\s*$/,"").trim();
      const start=m.index+m[0].length;
      const end=(idx+1<matches.length)?matches[idx+1].index:body.length;
      const peso=extractPeso(body.slice(start,end),unid,qtd);
      return {codigo:m[1], desc, unid, qtd, cst:m[4], peso};
    });
    return itens;
  }
  function parseItens(full,items){
    return parseItensGeo(items) || parseItensTexto(full);
  }

  /* ---------- Excel ---------- */
  const drop=$("drop"),fileInput=$("file");
  ["dragenter","dragover"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("drag");}));
  ["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("drag");}));
  drop.addEventListener("drop",ev=>{ if(ev.dataTransfer.files[0]) handleFile(ev.dataTransfer.files[0]); });
  fileInput.addEventListener("change",()=>{ if(fileInput.files[0]) handleFile(fileInput.files[0]); });
  function handleFile(f){
    $("dropTitle").textContent=f.name; $("dropSub").textContent="Lendo planilha…";
    const r=new FileReader();
    r.onload=e=>{ try{
        const wb=XLSX.read(new Uint8Array(e.target.result),{type:"array"});
        const ws=wb.Sheets[wb.SheetNames[0]];
        state.rows=XLSX.utils.sheet_to_json(ws,{defval:null});
        detectColumns(state.rows);
        $("dropSub").textContent=state.rows.length+" linhas · aba "+wb.SheetNames[0];
        showDetectPanel(); syncConferir();
      }catch(err){ $("dropSub").textContent="Erro ao ler o arquivo";
        $("detect").innerHTML='<div class="row err">Não consegui ler a planilha. Confira se é um .xlsx válido.</div>';
        $("detect").classList.add("show"); state.rows=null; syncConferir(); } };
    r.readAsArrayBuffer(f);
  }
  // Colunas a capturar do relatório do WMS (para conferência e futura extração de dados).
  // v2.24: cada fluxo tem a SUA lista — os dois relatórios não têm as mesmas colunas.
  const CAMPOS_RECEB=[
    {key:"unidade",      label:"Unidade",            exact:["unidade"]},
    {key:"cliente",      label:"Cliente",            exact:["cliente"]},
    {key:"romaneio",     label:"Romaneio",           exact:["romaneio"]},
    {key:"nf",           label:"NF",                 exact:["nf"], any:["nota fiscal"]},
    {key:"checkin",      label:"Data Checkin",       exact:["data checkin"]},
    {key:"fechamento",   label:"Data Fechamento",    exact:["data fechamento"], any:["data fecham"]},
    {key:"codProduto",   label:"Código Produto",     any:["codigo produto","cod produto"]},
    {key:"descProduto",  label:"Descrição Produto",  any:["descricao produto","descricao do produto"]},
    {key:"sif",          label:"SIF",                exact:["sif"]},
    // O relatório do WMS não traz coluna de SISB: o número vem na coluna SIF e é identificado
    // pela nota (ver classificaInsp). Marcada como `opcional` para não virar alerta na captura.
    {key:"sisb",         label:"SISB",               exact:["sisb","sisbi"], opcional:"vem na coluna SIF, identificado pela nota"},
    {key:"lote",         label:"Lote",               exact:["lote"]},
    {key:"dataProducao", label:"Data Produção",      any:["data producao","fabricacao"]},
    {key:"dataValidade", label:"Data Validade",      any:["data validade","validade"]},
    {key:"um",           label:"UM",                 exact:["um"], any:["unidade medida"]},
    {key:"qtdRecebida",  label:"Qtd Recebida",       any:["qtd recebida","quantidade recebida"]},
    {key:"pesoLiquido",  label:"Peso Líquido",       any:["peso liquido"]},
    {key:"pesoBruto",    label:"Peso Bruto",         any:["peso bruto"]},
    {key:"conferente",   label:"Conferente",         exact:["conferente"]},
  ];
  // Expedição — relatório `rpt_jda_sif_expedicao_v01`. Difere do recebimento em três pontos:
  // a nota vem em duas colunas ("NF Entrada PO_NUM" livre e "NF Entrada STR7" limpa), a
  // quantidade é "Qtd Expedida", e há campos de inspeção que o recebimento não tem
  // (Lacre SIF, Certificação, Habilitação, Rastreabilidade, Família).
  // Cuidado ao mexer: "SIF" é `exact` de propósito — se virasse `any`, casaria com "Lacre SIF",
  // que é OUTRA coisa (o SIF do lacre do veículo, ex. "0013743/SIF159", diferente do SIF do
  // produto na mesma linha, ex. "0104").
  const CAMPOS_EXPED=[
    {key:"unidade",        label:"Unidade",             exact:["unidade"]},
    {key:"cliente",        label:"Cliente",             exact:["cliente"]},
    {key:"romaneio",       label:"Romaneio",            exact:["romaneio"]},
    {key:"pedidoSaida",    label:"Pedido de Saída",     any:["pedido de saida","pedido saida"]},
    {key:"nfEntradaStr7",  label:"NF Entrada STR7",     exact:["nf entrada str7"], any:["str7"]},
    {key:"nfEntradaPoNum", label:"NF Entrada PO_NUM",   exact:["nf entrada po_num"], any:["po_num"]},
    {key:"checkin",        label:"Data Checkin",        exact:["data checkin"]},
    {key:"fechamento",     label:"Data Fechamento",     exact:["data fechamento"], any:["data fecham"]},
    {key:"codProduto",     label:"Código Produto",      any:["codigo produto","cod produto"]},
    {key:"descProduto",    label:"Descrição Produto",   any:["descricao produto","descricao do produto"]},
    {key:"familia",        label:"Família",             exact:["familia"]},
    {key:"sif",            label:"SIF",                 exact:["sif"]},
    {key:"lacreSif",       label:"Lacre SIF",           exact:["lacre sif"]},
    {key:"sisb",           label:"SISB",                exact:["sisb","sisbi"], opcional:"vem na coluna SIF, identificado pela nota"},
    {key:"lote",           label:"Lote",                exact:["lote"]},
    {key:"dataProducao",   label:"Data Produção",       any:["data producao","fabricacao"]},
    {key:"dataValidade",   label:"Data Validade",       any:["data validade","validade"]},
    {key:"um",             label:"UM",                  exact:["um"], any:["unidade medida"]},
    {key:"qtdExpedida",    label:"Qtd Expedida",        any:["qtd expedida","quantidade expedida"]},
    {key:"pesoLiquido",    label:"Peso Líquido",        any:["peso liquido"]},
    {key:"pesoBruto",      label:"Peso Bruto",          any:["peso bruto"]},
    {key:"conferente",     label:"Conferente",          exact:["conferente"]},
    {key:"certificacao",   label:"Certificação",        exact:["certificacao"]},
    {key:"habilitacao",    label:"Habilitação",         exact:["habilitacao"]},
    {key:"rastreabilidade",label:"Rastreabilidade",     exact:["rastreabilidade"]},
  ];
  const CAMPOS_POR_MODULO={receb:CAMPOS_RECEB,exped:CAMPOS_EXPED};
  function camposAtuais(){ return CAMPOS_POR_MODULO[modulo]; }
  function detectColumns(rows){
    state.colmap={}; state.netCol=state.nfCol=state.romCol=null;
    if(!rows.length) return;
    const cols=Object.keys(rows[0]).map(k=>({k,n:sa(k)}));
    camposAtuais().forEach(c=>{
      let hit=null;
      if(c.exact){ const e=cols.find(o=>c.exact.includes(o.n)); if(e) hit=e.k; }
      if(!hit && c.any){ const a=cols.find(o=>c.any.some(s=>o.n.includes(s))); if(a) hit=a.k; }
      state.colmap[c.key]=hit;
    });
    state.netCol=state.colmap.pesoLiquido;
    // v2.24: a coluna de NF varia por fluxo (receb: "NF"; exped: "NF Entrada STR7", com
    // "NF Entrada PO_NUM" de reserva). A 1ª da lista que existir no arquivo é a que vale.
    state.nfCol=(MOD().chaveNf||["nf"]).map(k=>state.colmap[k]).find(Boolean)||null;
    state.romCol=state.colmap.romaneio;
  }
  function showDetectPanel(){
    const m=state.colmap||{};
    const campos=camposAtuais();
    const found=campos.filter(c=>m[c.key]).length;
    // Coluna ausente que é ausente **por projeto** (`opcional`, hoje só o SISB) não é alerta:
    // sai em tom informativo, com a explicação de onde o dado é lido no lugar dela.
    const grid=campos.map(c=>{
      const ok=!!m[c.key], info=!ok&&!!c.opcional;
      const cls=ok?'ok':(info?'info':'miss'), ico=ok?'✓':(info?'ⓘ':'⚠');
      const nota=ok?'':(info?' — '+c.opcional:' — não encontrada');
      return `<div class="capitem ${cls}"><span class="ck">${ico}</span><span>${c.label}${nota}</span></div>`;
    }).join("");
    $("detect").innerHTML=
      `<p class="caphead">Colunas capturadas (${found} de ${campos.length})</p>`+
      `<div class="capgrid">${grid}</div>`+
      `<div class="captot"><span>Total de linhas lidas</span><b>${state.rows.length}</b></div>`;
    $("detect").classList.add("show");
  }

  $("conferir").addEventListener("click",()=>{ conferir(); goStep(2); });
  $("tol").addEventListener("input",()=>applyTolerance());
  // Filtros por clique (ou teclado, já que são <div role="button">) nos KPIs
  // (DANFE importadas = todas, Conferem = ok, Divergem = divergentes)
  [["fAll","all"],["fOk","ok"],["fWarn","warn"]].forEach(([id,f])=>{
    const el=$(id);
    el.addEventListener("click",()=>setFilter(f));
    el.addEventListener("keydown",ev=>{ if(ev.key==="Enter"||ev.key===" "){ ev.preventDefault(); setFilter(f); } });
  });
  updateFilterButtons();
  $("thToggleAll").addEventListener("click",toggleAllDetails);
  $("thToggleAll").addEventListener("keydown",ev=>{ if(ev.key==="Enter"||ev.key===" "){ ev.preventDefault(); toggleAllDetails(); } });

  /* ---------- reconcile ---------- */
  // Casa uma linha do Excel com a NF conferida SEMPRE pela coluna "NF" do relatório do WMS.
  // O romaneio NÃO entra no match: um mesmo romaneio agrupa várias notas fiscais, então
  // casar por romaneio somaria o peso líquido de outras NFs do romaneio (super-contagem).
  function rowMatchesNf(row,alvo){ return state.nfCol ? norm(row[state.nfCol])===alvo : false; }
  function conferir(){
    const notes=validNotes();
    state.results=notes.map(n=>{ const alvo=norm(n.nf);
      const matched=state.rows.filter(r=>rowMatchesNf(r,alvo));
      const recebido=matched.reduce((s,r)=>s+(Number(r[state.netCol])||0),0);
      const res={nf:n.nf.trim(),alvo,esperado:parsePeso(n.peso)||0,recebido,matched,sif:n.sif||"",sisb:n.sisb||"",itens:n.itens||[]};
      // divergência de inspeção: número do WMS não casou nem com o SIF nem com o SISB da NF
      // em algum item recebido (mesma regra do detalhe — ver classificaInsp)
      const grps=xlsxPorProduto(res); let sifDiv=false;
      (res.itens||[]).forEach(it=>{ const key=sa(it.codigo||"")||sa(it.desc||""); const g=key?grps.get(key):null;
        if(g && it.peso!=null && classificaInsp(res.sif,res.sisb,g.sifs,g.sisbs).bad) sifDiv=true; });
      res.sifDiv=sifDiv;
      return res; });
    const inf=new Set(state.results.map(r=>r.alvo)); const extra={}; const todasExcel=new Set();
    state.rows.forEach(r=>{ const v=state.nfCol?norm(r[state.nfCol]):"";
      if(v){ todasExcel.add(v); if(!inf.has(v)) extra[v]=(extra[v]||0)+(Number(r[state.netCol])||0); } });
    state.extra=extra; state.notasExcel=state.nfCol?todasExcel.size:null; applyTolerance();
  }
  function applyTolerance(){
    const tol=parseFloat($("tol").value)||0; let nOk=0,nWarn=0,totDiff=0;
    state.results.forEach(r=>{ r.diff=r.recebido-r.esperado; r.none=r.matched.length===0;
      r.ok=Math.abs(r.diff)<=tol+1e-9 && !r.none && !r.sifDiv; if(r.ok)nOk++;else{nWarn++;totDiff+=r.diff;} });
    $("sNotas").textContent=state.results.length;
    $("sExcel").textContent=(state.notasExcel==null)?"—":state.notasExcel;
    $("sOk").textContent=nOk; $("sWarn").textContent=nWarn;
    const sd=$("sDiff"); sd.textContent=(totDiff>0?"+":totDiff<0?"−":"")+fmt3(Math.abs(totDiff));
    sd.parentElement.className="stat "+(Math.abs(totDiff)<=tol+1e-9?"ok":"warn"); renderResults();
  }
  function passaFiltro(r){ return state.filter==="all" || (state.filter==="ok"&&r.ok) || (state.filter==="warn"&&!r.ok); }
  function renderResults(){
    const tb=$("resBody"); tb.innerHTML=""; let shown=0;
    state.results.forEach((r,i)=>{
      if(!passaFiltro(r)) return; shown++;
      const cls=r.diff>1e-9?"pos":r.diff<-1e-9?"neg":"zero"; const sign=r.diff>1e-9?"+":r.diff<-1e-9?"−":"";
      const status=r.none?'<span class="pill none">'+MOD().semX+'</span>':r.ok?'<span class="pill ok">Confere</span>':'<span class="pill warn">Divergência</span>';
      const tr=document.createElement("tr"); tr.className="note"; tr.dataset.i=i;
      tr.innerHTML=`<td><span class="caret">▸</span> ${esc(r.nf)}</td><td class="n">${fmt3(r.esperado)}</td><td class="n">${fmt3(r.recebido)}</td><td class="n diff ${cls}">${sign}${fmt3(Math.abs(r.diff))}</td><td>${status}</td>`;
      tr.addEventListener("click",()=>toggleDetail(tr,i)); tb.appendChild(tr);
    });
    if(shown===0 && state.results.length){
      const tr=document.createElement("tr"); tr.innerHTML='<td colspan="5" style="text-align:center;color:var(--muted);padding:18px">Nenhuma nota nesse filtro.</td>'; tb.appendChild(tr);
    }
    const labels={all:"todas as notas",ok:"apenas as que conferem",warn:"apenas as divergentes"};
    const fi=$("filterInfo"); if(fi) fi.textContent="Mostrando: "+labels[state.filter]+" — "+shown+" de "+state.results.length;
    const ex=$("extra"); const keys=Object.keys(state.extra||{});
    ex.innerHTML=keys.length?`⚠️ O Excel tem <b>${keys.length}</b> nota(s) fora da sua lista: ${keys.map(k=>esc(k)+" ("+fmt(state.extra[k])+" kg)").join(", ")}. Adicione-as se também precisam ser conferidas.`:"";
    const th=$("thToggleAll"); if(th){ th.classList.remove("open"); th.setAttribute("aria-pressed","false"); } // renderResults sempre recomeça com tudo fechado
  }
  function setFilter(f){ state.filter=f; updateFilterButtons(); renderResults(); }
  function updateFilterButtons(){ [["fAll","all"],["fOk","ok"],["fWarn","warn"]].forEach(([id,f])=>{ const el=$(id); if(el){ el.classList.toggle("active",state.filter===f); el.setAttribute("aria-pressed",String(state.filter===f)); } }); }
  function openDetail(tr,i){
    if(tr.nextElementSibling&&tr.nextElementSibling.classList.contains("detail")) return;
    tr.classList.add("open");
    const det=document.createElement("tr"); det.className="detail";
    det.innerHTML=`<td colspan="5"><div class="inner">${buildDetail(state.results[i])}</div></td>`; tr.after(det);
  }
  function closeDetail(tr){
    const next=tr.nextElementSibling;
    if(next&&next.classList.contains("detail")) next.remove();
    tr.classList.remove("open");
  }
  function syncToggleAllHeader(){
    const rows=[...document.querySelectorAll("#resBody tr.note")];
    const th=$("thToggleAll"); if(!th||!rows.length) return;
    const allOpen=rows.every(r=>r.classList.contains("open"));
    th.classList.toggle("open",allOpen); th.setAttribute("aria-pressed",String(allOpen));
  }
  function toggleDetail(tr,i){
    if(tr.nextElementSibling&&tr.nextElementSibling.classList.contains("detail")) closeDetail(tr);
    else openDetail(tr,i);
    syncToggleAllHeader();
  }
  function toggleAllDetails(){
    const rows=[...document.querySelectorAll("#resBody tr.note")];
    if(!rows.length) return;
    const allOpen=rows.every(tr=>tr.classList.contains("open"));
    rows.forEach(tr=>allOpen?closeDetail(tr):openDetail(tr,Number(tr.dataset.i)));
    syncToggleAllHeader();
  }
  // Agrupa as linhas do WMS casadas com a NF por produto (código; cai p/ descrição),
  // somando o peso líquido e juntando os SIFs distintos daquele produto no XLSX.
  // Extrai o número comparável do SIF, tolerando os formatos que aparecem na NF:
  // usa o número após "SIF" (ex.: "0006974/SIF1889" -> 1889); senão o 1º grupo de dígitos
  // (ex.: "236-ICMS" -> 236, "2544" -> 2544); ignora zeros à esquerda.
  function sifNum(s){
    if(!s) return "";
    const t=String(s);
    const all=[...t.matchAll(/SIF\s*0*(\d+)/ig)];
    let d = all.length ? all[all.length-1][1] : ((/(\d+)/.exec(t)||[])[1]||"");
    return d ? (d.replace(/^0+/,"")||"0") : "";
  }
  // v2.22 — O relatório do WMS **não tem coluna própria de SISB**: o número de inspeção do
  // produto chega todo na coluna "SIF", seja ele um SIF ou um SISB. Quem diz o que é aquele
  // número é a NOTA. Regra pedida pelo usuário, na ordem:
  //   1) bate com o SIF da NF   -> é SIF  → fica na coluna SIF (XLSX) e confere;
  //   2) senão, bate com o SISB -> é SISB → vai para a coluna SISB (XLSX) e confere lá;
  //   3) não bate com nenhum dos dois     -> divergência.
  // Substituiu o `sifDiverge` da v2.10, que só sabia comparar SIF × SIF e por isso acusava
  // divergência em produto de inspeção estadual (SISB) cujo número batia perfeitamente.
  // `sisbsProprios` são os valores que vieram de uma coluna SISB de verdade, quando o
  // relatório tiver uma: esses não passam por classificação, já nasceram identificados.
  function classificaInsp(nfSif,nfSisb,valores,sisbsProprios){
    const nSif=sifNum(nfSif), nSisb=sifNum(nfSisb);
    const sifs=[], sisbs=[...(sisbsProprios||[])], soltos=[];
    [...(valores||[])].forEach(v=>{
      const n=sifNum(v);
      if(n && nSif && n===nSif) sifs.push(v);
      else if(n && nSisb && n===nSisb) sisbs.push(v);
      else soltos.push(v);                                 // não casou com SIF nem com SISB
    });
    // Só acusa divergência quando havia com o que comparar: nota sem SIF e sem SISB não
    // autoriza conclusão nenhuma sobre o número que veio do WMS (mesma cautela do sifDiverge).
    return {sifs,sisbs,soltos,bad:soltos.length>0 && !!(nSif||nSisb)};
  }
  function xlsxPorProduto(r){
    const cCod=state.colmap.codProduto, cDsc=state.colmap.descProduto, cSif=state.colmap.sif, cSisb=state.colmap.sisb, net=state.netCol;
    const map=new Map();
    (r.matched||[]).forEach(row=>{
      const codRaw=cCod?String(row[cCod]??"").trim():"";
      const dscRaw=cDsc?String(row[cDsc]??"").trim():"";
      const key=sa(codRaw)||sa(dscRaw)||"?";
      let g=map.get(key);
      if(!g){ g={codigo:codRaw,desc:dscRaw,peso:0,sifs:new Set(),sisbs:new Set()}; map.set(key,g); }
      g.peso+=Number(row[net])||0;
      const s=cSif?String(row[cSif]??"").trim():""; if(s) g.sifs.add(s);
      const sb=cSisb?String(row[cSisb]??"").trim():""; if(sb) g.sisbs.add(sb);
    });
    return map;
  }
  const stat=(txt,cls)=>`<span class="dstat ${cls}">${txt}</span>`;
  // Linhas do detalhamento de UMA nota, como DADOS (sem HTML) — v2.19.
  // Fonte única para a tabela na tela (buildDetail) e para a exportação em Excel
  // (exportarExcel): a regra de status/SIF/origem mora só aqui, então os dois nunca divergem.
  // Cada linha traz o peso como número (pesoNF/pesoX, null quando não há) E como texto já
  // formatado em pt-BR (pesoNFtxt/pesoXtxt) — a tela usa o texto, o Excel usa o número.
  function detailRows(r){
    const itens=(r.itens&&r.itens.length)?r.itens:null;
    const sifNF=r.sif||"", sisbNF=r.sisb||"";
    const grupos=xlsxPorProduto(r);
    const usados=new Set();
    const out=[];
    if(itens){
      itens.forEach((it,idx)=>{
        const key=sa(it.codigo||"")||sa(it.desc||"");
        const g=key?grupos.get(key):null; if(g) usados.add(key);
        // Classifica o número de inspeção que veio do WMS: SIF, SISB ou nenhum dos dois.
        const cl=g?classificaInsp(sifNF,sisbNF,g.sifs,g.sisbs):null;
        let st,cls,sifBad=false;
        if(!g){ st="Só na NF"; cls="warn"; }                                   // esperado, mas não recebido
        else if(it.peso==null){ st="Verificar"; cls="warn"; }                  // sem peso numérico p/ comparar
        else {
          const pesoOk=Math.abs(it.peso-g.peso)<=5e-4;
          sifBad=cl.bad;                                                       // não casou nem com SIF nem com SISB da NF
          if(pesoOk && !sifBad){ st="Confere"; cls="ok"; } else { st="Divergência"; cls="warn"; }
        }
        out.push({
          cod:it.codigo||("#"+(idx+1)), desc:it.desc||"—", orig:origemItem(it),
          pesoNF:(it.peso!=null)?it.peso:null,
          pesoNFtxt:(it.peso!=null)?fmt3(it.peso):(fmt(it.qtd)+" "+(it.unid||"")).trim(),
          sifNF:sifNF||"—", sisbNF:sisbNF||"—",
          pesoX:g?g.peso:null, pesoXtxt:g?fmt3(g.peso):"—",
          // SIF (XLSX) fica com o que é SIF + o que não casou com nada (veio dessa coluna e
          // precisa ficar visível); SISB (XLSX) recebe o que a nota identificou como SISB.
          sifX:cl?(cl.sifs.concat(cl.soltos).join(", ")||"—"):"—",
          sisbX:cl?(cl.sisbs.join(", ")||"—"):"—",
          st, cls, sifBad
        });
      });
      // Produtos presentes no XLSX mas sem item correspondente na NF (recebidos a mais):
      // não há CST desse lado, então a origem só pode sair da descrição do produto no WMS.
      grupos.forEach((g,key)=>{ if(usados.has(key)) return;
        out.push({
          cod:g.codigo||"—", desc:g.desc||"—", orig:origFromDesc(g.desc),
          pesoNF:null, pesoNFtxt:"—", sifNF:"—", sisbNF:"—",
          pesoX:g.peso, pesoXtxt:fmt3(g.peso),
          sifX:[...g.sifs].join(", ")||"—", sisbX:[...g.sisbs].join(", ")||"—",
          st:"Só no XLSX", cls:"warn", sifBad:false
        });
      });
    }else{
      // nota manual / layout não reconhecido: sem itens da NF para alinhar por produto
      const okTot=Math.abs((r.esperado||0)-(r.recebido||0))<=5e-4 && !r.none;
      out.push({
        cod:"—", desc:"Itens não capturados do PDF (nota manual ou layout não reconhecido)", orig:null,
        pesoNF:r.esperado, pesoNFtxt:fmt3(r.esperado), sifNF:sifNF||"—", sisbNF:sisbNF||"—",
        pesoX:r.recebido, pesoXtxt:fmt3(r.recebido), sifX:"—", sisbX:"—",
        st:okTot?"Confere":(r.none?MOD().semX:"Divergência"),
        cls:okTot?"ok":(r.none?"none":"warn"), sifBad:false
      });
    }
    return out;
  }
  function buildDetail(r){
    const linhas=detailRows(r);
    const cell=(v,cls)=>`<td class="dt${cls?" "+cls:""}">${v}</td>`;
    const linha=(rowCls,cod,desc,orig,pesoNF,sifNFv,sisbNFv,pesoX,sifX,sisbX,status)=>
      `<tr${rowCls?` class="${rowCls}"`:""}>`+cell(cod)+cell(desc)+cell(orig)+cell(pesoNF,"n")+cell(sifNFv)+cell(sisbNFv)+cell(pesoX,"n")+cell(sifX)+cell(sisbX)+cell(status)+"</tr>";
    // Descrição 21% -> 30% na v2.16 (empurra a Origem p/ a direita). A folga saiu de Item, Status e
    // dos pesos/SIF/SISB — que de todo modo já estão presos na largura mínima do próprio título (nowrap da v2.15).
    let h="<table><colgroup><col style=\"width:5%\"><col style=\"width:30%\"><col style=\"width:10%\"><col style=\"width:10%\"><col style=\"width:6%\"><col style=\"width:6%\"><col style=\"width:10%\"><col style=\"width:6%\"><col style=\"width:6%\"><col style=\"width:11%\"></colgroup><thead><tr>"+
      "<th>Item</th><th>Descrição</th><th>Origem</th>"+
      "<th class=\"n\">Peso líq. KG (NF)</th><th>SIF (NF)</th><th>SISB (NF)</th>"+
      "<th class=\"n\">Peso líq. KG (XLSX)</th><th>SIF (XLSX)</th><th>SISB (XLSX)</th><th>Status</th>"+
      "</tr></thead><tbody>";
    linhas.forEach(d=>{
      const sifNFc=d.sifBad?`<span class="sifbad">${esc(d.sifNF)}</span>`:esc(d.sifNF);
      const sifXc =d.sifBad?`<span class="sifbad">${esc(d.sifX)}</span>`:esc(d.sifX);
      h+=linha(d.cls==="ok"?"":"dwarn",esc(d.cod),esc(d.desc),origemCell(d.orig),d.pesoNFtxt,sifNFc,esc(d.sisbNF),d.pesoXtxt,sifXc,esc(d.sisbX),stat(d.st,d.cls));
    });
    // Totais: esperado (NF) × recebido (XLSX)
    h+="<tr class=\"dtot\">"+cell("")+cell("Total")+cell("")+cell(fmt3(r.esperado),"n")+cell("")+cell("")+cell(fmt3(r.recebido),"n")+cell("")+cell("")+cell("")+"</tr>";
    return h+"</tbody></table>";
  }

  /* ---------- Exportação para Excel (v2.19; colunas revisadas na v2.20) ---------- */
  // Mesma estrutura do detalhamento na tela, achatada: uma linha por item, com a coluna NOTA
  // à frente. Sem linhas de "Total" no meio dos dados (elas quebrariam filtro/tabela dinâmica
  // no Excel) — os totais por nota vão na 2ª aba, "Resumo por NF".
  // v2.20: entram "Diferença (kg)" e "Diferença (SIF)", e o Excel deixa de ter travessão ("—"):
  // pesos/SIF/SISB sem informação saem ZERADOS (0) e texto sem informação sai em branco.
  const EXP_HEAD=["NOTA","ITEM (NF)","DESCRIÇÃO (NF)","ORIGEM (NF)","Peso líq. KG (NF)","SIF (NF)","SISB (NF)",
                  "Peso líq. KG (XLSX)","SIF (XLSX)","SISB (XLSX)","Diferença (kg)","Diferença (SIF)","Status"];
  // Versão texto da coluna Origem (a da tela é HTML): "Nacional (0)" / "Estrangeira (desc.)".
  // No Excel, origem não identificada sai em branco (na tela continua "—").
  function origemTexto(o){
    if(!o) return "";
    return (o.nacional?"Nacional":"Estrangeira")+" ("+(o.src==="cst"?o.code:"desc.")+")";
  }
  // Sem informação -> 0 (colunas de SIF/SISB e de peso). "—" conta como sem informação.
  const zeroSe = v => { const s=String(v==null?"":v).trim(); return (!s||s==="—")?0:v; };
  // Texto: "—" e vazio saem em branco (nunca o travessão).
  const txtSe  = v => { const s=String(v==null?"":v).trim(); return (s==="—")?"":s; };
  // Peso: número quando há; senão o texto alternativo (ex.: "5 CX"); senão 0.
  const pesoSe = (num,txt) => (num!=null)?num:zeroSe(txt);
  const r3 = n => Math.round(n*1000)/1000;                           // mata ruído de float na diferença
  const FMT3="#,##0.000";
  function exportarExcel(){
    if(!state.results.length){ alert("Nada para exportar — faça a conferência primeiro."); return; }
    const notas=state.results.filter(passaFiltro);
    if(!notas.length){ alert("Nenhuma nota no filtro atual. Troque o filtro e tente de novo."); return; }
    const aoa=[EXP_HEAD.slice()];
    notas.forEach(r=>{
      detailRows(r).forEach(d=>{
        // Diferença por item = recebido (XLSX) − esperado (NF), mesmo sinal da tabela da tela.
        // Lado ausente vale 0, então "Só na NF" sai negativo e "Só no XLSX" sai positivo.
        const dif=r3((d.pesoX!=null?d.pesoX:0)-(d.pesoNF!=null?d.pesoNF:0));
        aoa.push([r.nf, txtSe(d.cod), txtSe(d.desc), origemTexto(d.orig),
                  pesoSe(d.pesoNF,d.pesoNFtxt), zeroSe(d.sifNF), zeroSe(d.sisbNF),
                  pesoSe(d.pesoX,d.pesoXtxt), zeroSe(d.sifX), zeroSe(d.sisbX),
                  dif, d.sifBad?"NOK":"OK", d.st]);
      });
    });
    const ws=XLSX.utils.aoa_to_sheet(aoa);
    ws["!cols"]=[{wch:12},{wch:12},{wch:52},{wch:18},{wch:18},{wch:12},{wch:12},{wch:20},{wch:12},{wch:12},{wch:14},{wch:14},{wch:16}];
    ws["!autofilter"]={ref:XLSX.utils.encode_range({s:{r:0,c:0},e:{r:aoa.length-1,c:EXP_HEAD.length-1}})};
    marcaFmt3(ws,aoa.length,[4,7,10]);                               // E, H e K = pesos e diferença
    // Aba 2: totais por nota — espelha a tabela principal da tela.
    const res=[["NOTA","Peso líq. KG esperado (NF)","Peso líq. KG "+MOD().verbo+" (XLSX)","Diferença (kg)","Status"]];
    notas.forEach(r=>res.push([r.nf,r.esperado,r.recebido,r.recebido-r.esperado,
      r.none?MOD().semX:(r.ok?"Confere":"Divergência")]));
    const ws2=XLSX.utils.aoa_to_sheet(res);
    ws2["!cols"]=[{wch:12},{wch:26},{wch:28},{wch:16},{wch:18}];
    marcaFmt3(ws2,res.length,[1,2,3]);
    const wb=XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb,ws,"Detalhamento");
    XLSX.utils.book_append_sheet(wb,ws2,"Resumo por NF");
    const suf={all:"",ok:"_conferem",warn:"_divergem"}[state.filter]||"";
    XLSX.writeFile(wb,"PGA_"+MOD().arquivo+"_mapa_estatistico_"+stamp()+suf+".xlsx");
  }
  // Aplica o formato de 3 casas nas colunas de peso (só nas células que são número mesmo).
  function marcaFmt3(ws,nLinhas,cols){
    for(let r=1;r<nLinhas;r++) cols.forEach(c=>{
      const cel=ws[XLSX.utils.encode_cell({r,c})];
      if(cel&&cel.t==="n") cel.z=FMT3;
    });
  }
  const stamp=()=>{ const d=new Date(),p=n=>String(n).padStart(2,"0");
    return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+"_"+p(d.getHours())+p(d.getMinutes()); };
  $("exportXlsx").addEventListener("click",exportarExcel);

  $("modReceb").addEventListener("click",()=>trocarModulo("receb"));
  $("modExped").addEventListener("click",()=>trocarModulo("exped"));
  aplicarRotulos();

  addNote("","","manual"); // linha inicial em branco (fluxo inicial = Recebimento)
})();

