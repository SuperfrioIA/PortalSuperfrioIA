
if(window.pdfjsLib&&window.__PDFW){var __b=atob(window.__PDFW),__n=__b.length,__a=new Uint8Array(__n);for(var __i=0;__i<__n;__i++)__a[__i]=__b.charCodeAt(__i);pdfjsLib.GlobalWorkerOptions.workerSrc=URL.createObjectURL(new Blob([__a],{type:"application/javascript"}));}
(function(){
  const $=id=>document.getElementById(id);
  const state={notes:[],rows:null,colmap:null,netCol:null,nfCol:null,romCol:null,results:[],extra:{},notasExcel:null,filter:"all",_id:0};
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

  function goStep(n){[1,2,3].forEach(i=>{$("scr"+i).classList.toggle("active",i===n);const st=$("st"+i);st.classList.toggle("active",i===n);st.classList.toggle("done",i<n);});window.scrollTo({top:0,behavior:"smooth"});}

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
  function validateNotes(){ $("toStep2").disabled=validNotes().length===0; }
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

  $("toStep2").addEventListener("click",()=>goStep(2));
  $("backStep1").addEventListener("click",()=>goStep(1));
  $("backStep1b").addEventListener("click",()=>goStep(1));
  $("backStep2").addEventListener("click",()=>goStep(2));
  // Navegação por clique nas etapas da sidebar (com travas p/ não abrir tela sem dados)
  const excelPronto=()=>!!(state.rows && state.netCol);
  $("st1").addEventListener("click",()=>goStep(1));
  $("st2").addEventListener("click",()=>{ if(validNotes().length) goStep(2); });
  $("st3").addEventListener("click",()=>{
    if(validNotes().length && excelPronto()){ conferir(); goStep(3); }
    else if(state.results.length){ goStep(3); }
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
            state.notes.push({id:++state._id,nf:disp,peso:pesoStr,origin:tipo+": "+f.name,flag:data.liq==null||!!data.pesoWarn,nfFlag:!!data.nfWarn,sif:data.sif||"",itens:data.itens||[],nfOriginal:disp,pesoOriginal:pesoStr});
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
      itens.push({codigo:g("cProd"), desc:g("xProd")||"", unid, qtd, peso:/^KG/i.test(unid)?qtd:null});
    }
    // Mesma validação do PDF: quando todos os itens têm peso (uCom="KG"), a soma tem que bater
    // com <pesoL>. Se não bater (ou <pesoL> não vier), a soma dos itens é quem manda.
    let pesoWarn=false;
    if(itens.length && itens.every(it=>it.peso!=null)){
      const soma=Math.round(itens.reduce((a,it)=>a+it.peso,0)*1000)/1000; // evita ruído de ponto flutuante
      if(liq==null){ liq=soma; }
      else if(Math.abs(soma-liq)>0.5){ pesoWarn=true; liq=soma; }
    }
    return {nf,liq,bru,nfWarn:false,pesoWarn,sif:extractSif(text),itens};
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
  // SIF (Serviço de Inspeção Federal) — valor do "LACRE SIF"/"SIF" dos dados adicionais
  function extractSif(s){
    if(!s) return "";
    let m=/LACRE\s+SIF\s*:?\s*([0-9][\w\/.\-]*)/i.exec(s);
    if(!m) m=/\bSIF\s*:?\s*([0-9][\w\/.\-]*)/i.exec(s);
    return m?m[1].replace(/[.\s]+$/,"").trim():"";
  }

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
    return {nf,liq,bru,nfWarn,pesoWarn,sif:extractSif(full),itens};
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
  const RX_ITEM=/((?=[A-Z0-9.\-\/]*\d)[A-Z0-9][A-Z0-9.\-\/]{1,19})\s+([A-Za-zÀ-ÿ][\s\S]{1,80}?)\s+(\d{4}\.?\d{2}\.?\d{2})\s+\d{2,3}[\s\/]+(\d{4})\s+([A-Z]{1,4})[\s\/]+(\d[\d.]*(?:,\d+)?)/;
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
        const unid=m[5], qtd=brNum(m[6]);
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
        itens.push({codigo, desc, unid, qtd, peso});
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
      const unid=m[5], qtd=brNum(m[6]);
      const desc=m[2].replace(/\s+/g," ").replace(/\s*-\s*$/,"").trim();
      const start=m.index+m[0].length;
      const end=(idx+1<matches.length)?matches[idx+1].index:body.length;
      const peso=extractPeso(body.slice(start,end),unid,qtd);
      return {codigo:m[1], desc, unid, qtd, peso};
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
        showDetectPanel(); $("conferir").disabled=!state.netCol;
      }catch(err){ $("dropSub").textContent="Erro ao ler o arquivo";
        $("detect").innerHTML='<div class="row err">Não consegui ler a planilha. Confira se é um .xlsx válido.</div>';
        $("detect").classList.add("show"); state.rows=null; $("conferir").disabled=true; } };
    r.readAsArrayBuffer(f);
  }
  // Colunas a capturar do relatório do WMS (para conferência e futura extração de dados)
  const CAMPOS=[
    {key:"unidade",      label:"Unidade",            exact:["unidade"]},
    {key:"cliente",      label:"Cliente",            exact:["cliente"]},
    {key:"romaneio",     label:"Romaneio",           exact:["romaneio"]},
    {key:"nf",           label:"NF",                 exact:["nf"], any:["nota fiscal"]},
    {key:"checkin",      label:"Data Checkin",       exact:["data checkin"]},
    {key:"fechamento",   label:"Data Fechamento",    exact:["data fechamento"], any:["data fecham"]},
    {key:"codProduto",   label:"Código Produto",     any:["codigo produto","cod produto"]},
    {key:"descProduto",  label:"Descrição Produto",  any:["descricao produto","descricao do produto"]},
    {key:"lote",         label:"Lote",               exact:["lote"]},
    {key:"dataProducao", label:"Data Produção",      any:["data producao","fabricacao"]},
    {key:"dataValidade", label:"Data Validade",      any:["data validade","validade"]},
    {key:"um",           label:"UM",                 exact:["um"], any:["unidade medida"]},
    {key:"qtdRecebida",  label:"Qtd Recebida",       any:["qtd recebida","quantidade recebida"]},
    {key:"pesoLiquido",  label:"Peso Líquido",       any:["peso liquido"]},
    {key:"pesoBruto",    label:"Peso Bruto",         any:["peso bruto"]},
    {key:"conferente",   label:"Conferente",         exact:["conferente"]},
  ];
  function detectColumns(rows){
    state.colmap={}; state.netCol=state.nfCol=state.romCol=null;
    if(!rows.length) return;
    const cols=Object.keys(rows[0]).map(k=>({k,n:sa(k)}));
    CAMPOS.forEach(c=>{
      let hit=null;
      if(c.exact){ const e=cols.find(o=>c.exact.includes(o.n)); if(e) hit=e.k; }
      if(!hit && c.any){ const a=cols.find(o=>c.any.some(s=>o.n.includes(s))); if(a) hit=a.k; }
      state.colmap[c.key]=hit;
    });
    state.netCol=state.colmap.pesoLiquido;
    state.nfCol=state.colmap.nf;
    state.romCol=state.colmap.romaneio;
  }
  function showDetectPanel(){
    const m=state.colmap||{};
    const found=CAMPOS.filter(c=>m[c.key]).length;
    const grid=CAMPOS.map(c=>{
      const ok=!!m[c.key];
      return `<div class="capitem ${ok?'ok':'miss'}"><span class="ck">${ok?'✓':'⚠'}</span><span>${c.label}${ok?'':' — não encontrada'}</span></div>`;
    }).join("");
    $("detect").innerHTML=
      `<p class="caphead">Colunas capturadas (${found} de ${CAMPOS.length})</p>`+
      `<div class="capgrid">${grid}</div>`+
      `<div class="captot"><span>Total de linhas lidas</span><b>${state.rows.length}</b></div>`;
    $("detect").classList.add("show");
  }

  $("conferir").addEventListener("click",()=>{ conferir(); goStep(3); });
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
  function rowMatchesNf(row,alvo){ const c=[]; if(state.nfCol)c.push(norm(row[state.nfCol])); if(state.romCol)c.push(norm(row[state.romCol])); return c.includes(alvo); }
  function conferir(){
    const notes=validNotes();
    state.results=notes.map(n=>{ const alvo=norm(n.nf);
      const matched=state.rows.filter(r=>rowMatchesNf(r,alvo));
      const recebido=matched.reduce((s,r)=>s+(Number(r[state.netCol])||0),0);
      return {nf:n.nf.trim(),alvo,esperado:parsePeso(n.peso)||0,recebido,matched,sif:n.sif||"",itens:n.itens||[]}; });
    const inf=new Set(state.results.map(r=>r.alvo)); const extra={}; const todasExcel=new Set();
    state.rows.forEach(r=>{ const v=state.nfCol?norm(r[state.nfCol]):(state.romCol?norm(r[state.romCol]):"");
      if(v){ todasExcel.add(v); if(!inf.has(v)) extra[v]=(extra[v]||0)+(Number(r[state.netCol])||0); } });
    state.extra=extra; state.notasExcel=(state.nfCol||state.romCol)?todasExcel.size:null; applyTolerance();
  }
  function applyTolerance(){
    const tol=parseFloat($("tol").value)||0; let nOk=0,nWarn=0,totDiff=0;
    state.results.forEach(r=>{ r.diff=r.recebido-r.esperado; r.none=r.matched.length===0;
      r.ok=Math.abs(r.diff)<=tol+1e-9 && !r.none; if(r.ok)nOk++;else{nWarn++;totDiff+=r.diff;} });
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
      const status=r.none?'<span class="pill none">Sem recebimento</span>':r.ok?'<span class="pill ok">Confere</span>':'<span class="pill warn">Divergência</span>';
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
  function buildDetail(r){
    const itens=(r.itens&&r.itens.length)?r.itens:null;
    const sif=esc(r.sif||"");
    let h="<table><thead><tr><th>Item</th><th>Descrição</th><th class=\"n\">Peso líq. esperado (kg)</th><th>SIF</th></tr></thead><tbody>";
    if(itens){
      itens.forEach((it,idx)=>{
        const pesoTxt=(it.peso!=null)?fmt3(it.peso):(fmt(it.qtd)+" "+(it.unid||""));
        h+=`<tr><td class="dt">${esc(it.codigo)||("#"+(idx+1))}</td><td class="dt">${esc(it.desc)||"—"}</td><td class="dt n">${pesoTxt}</td><td class="dt">${sif||"—"}</td></tr>`;
      });
      h+=`<tr class="dtot"><td class="dt"></td><td class="dt">Total esperado</td><td class="dt n">${fmt3(r.esperado)}</td><td class="dt"></td></tr>`;
    }else{
      h+=`<tr><td class="dt">—</td><td class="dt">Itens do produto não capturados do PDF (nota manual ou layout não reconhecido)</td><td class="dt n">${fmt3(r.esperado)}</td><td class="dt">${sif||"—"}</td></tr>`;
    }
    return h+"</tbody></table>";
  }

  addNote("","","manual"); // linha inicial em branco
})();

