# HANDOFF — Analisador de Mapa Estatísticos (NF × WMS) — SuperFrio/IceStar

**Status:** Confirmado funcionando pelo usuário após modularização (teste real no navegador com upload de PDF/XLSX). Integrado ao Hub SuperFrio & Icestar em 2026-07-07 como app da seção **QHSE**, `tipo_acesso = iframe`. Atualizado para **v2.0** em 2026-07-08 (validação de peso por soma dos itens). ✅

---

## 1. O que é o projeto

Ferramenta HTML standalone (offline) para reconciliar o **peso líquido esperado** extraído de notas fiscais (DANFE PDF / NF-e XML) contra o **peso recebido pelo WMS** (relatório Excel `rpt_jda_recebimento_dtl_v03`). Fluxo em wizard de 3 passos:

1. Importar DANFE (PDF) ou NF-e (XML) — extrai NF, chave de acesso, peso líquido esperado, itens.
2. Importar relatório WMS (Excel) — mapeia 16 colunas de recebimento.
3. Reconciliação — cruza por NF, mostra divergências, permite expandir detalhes por nota.

Marca SuperFrio | IceStar (Conexão LATAM). Padrão visual: Montserrat, gradiente azul escuro `#0A2A5E→#10468F`, amarelo `#FFC400` para alertas/estado ativo.

---

## 2. Estrutura de arquivos ATUAL (dentro do Hub SuperFrio & Icestar)

Vive em `frontend/mapa-estatistico/` deste repositório (Receita 1 do [CONTRIBUTING.md](../../CONTRIBUTING.md) — HTML estático embutido via iframe, sem backend, sem banco):

```
frontend/mapa-estatistico/
  index.html        13 KB   ← HTML + CSS (edite este)
  app.js             ~?KB   ← lógica do app, extraído do <script> inline (edite este)
  vendor/
    xlsx.min.js       882 KB  ← SheetJS — NÃO EDITAR
    pdf.min.js        320 KB  ← PDF.js (lib principal) — NÃO EDITAR
    pdf.worker.b64.js 1,45 MB ← worker PDF.js em base64 (window.__PDFW="...") — NÃO EDITAR
```

**Origem:** migrado de um repositório separado (`QSSA_Qualidade\Programa QSSA`, arquivo único `analise_mapa_estatistico_v1_9.html`). Na migração, o `<script>` inline foi extraído para `app.js` porque o CSP do portal (`script-src 'self'`) bloqueia script inline — só `/governanca/` tem exceção documentada, que não foi copiada aqui.

**⚠️ CRÍTICO — estrutura de pastas:** a pasta `vendor/` tem que ficar **no mesmo diretório** do `index.html`. Os scripts são carregados via caminho relativo:

```html
<script src="vendor/xlsx.min.js"></script>
<script src="vendor/pdf.min.js"></script>
<script src="vendor/pdf.worker.b64.js"></script>
<script src="app.js"></script>
```

Continua 100% offline — não depende de CDN nem internet (exceto a fonte Montserrat via Google Fonts, já liberada pelo CSP padrão do portal em `style-src`/`font-src`).

### Como o app usa os vendors (não foi alterado, só preservado)
- `window.__PDFW` é a string base64 do worker do PDF.js. O próprio `app.js` faz `atob()` nela e monta o `workerSrc` via Blob/URL local.
- `XLSX` e `pdfjsLib` são globals — sem import/export ES module.

---

## 3. Como é servido / acessado

O Hub serve todo `frontend/` como estático (`backend/main.py`, `StaticFiles`). O app é acessado em `/mapa-estatistico/` e cadastrado na tela **Administração** do portal como card na seção **QHSE**, `tipo_acesso = iframe`. Roda em iframe sandboxed (sem `allow-same-origin`) — como não depende de cookie/localStorage do domínio do portal, funciona normalmente.

---

## 4. Regras de trabalho OBRIGATÓRIAS para próximas sessões

1. **Nunca** rodar `grep`, `cat` ou regex ampla contra `index.html`/`app.js` de uma vez sem necessidade — ainda pode ter linhas longas (CSS, funções de lógica). Usar sempre `grep -n` para achar a linha, depois editar cirurgicamente.
2. **Nunca abrir os arquivos em `vendor/`** — são bibliotecas de terceiros, read-only, e são grandes o bastante para estourar contexto se lidos por engano (`pdf.worker.b64.js` sozinho tem 1,45 MB numa única linha).
3. Para editar a lógica do app: `grep -n "termo" frontend/mapa-estatistico/app.js` → localizar linha → editar com contexto único (não reescrever o arquivo inteiro).
4. Se precisar atualizar SheetJS ou PDF.js no futuro: trocar o arquivo correspondente em `vendor/` diretamente — não precisa re-extrair nada do HTML.
5. Qualquer novo `<script>`/`<style>` inline em `index.html` vai ser bloqueado pelo CSP padrão do portal — mantenha tudo em `app.js`/CSS já existente.

---

## 5. Pendências conhecidas

- **Alinhamento da coluna de resultados** na sub-tabela de detalhes por invoice (mencionado em handoff anterior à modularização — ainda não resolvido).

## 6. Histórico resumido (contexto de sessões anteriores, pré-integração ao Hub)

- Construído do zero em versões v1.0 → v1.3 → v1.7: wizard de 3 passos, validação de chave de acesso NF-e (DV mod-11), mapeamento de 16 colunas do relatório WMS, linhas de detalhe expansíveis por NF.
- Bugs de extração corrigidos ao longo do caminho: número de NF errado (corrigido usando a chave DV-validada como fonte de verdade), zeros à esquerda cortados na exibição da NF, parser de itens do PDF capturando "informação complementar" como descrição de produto (corrigido limitando por região), código de contêiner sendo lido como código de produto, texto de anotação fiscal vazando pra descrição, tokens do PDF.js chegando fora de ordem (corrigido agrupando por posição Y/X geometricamente).
- Padrão visual SuperFrio aplicado rigorosamente: Montserrat, gradiente azul `#0A2A5E→#10468F`, amarelo `#FFC400` para estados ativos/alertas de divergência.

### 2026-07-03 — Correção do peso esperado por item na tela de divergência (v1.9)

Na Etapa 3 (divergências), o detalhe por nota mostrava "PESO LÍQ. ESPERADO (KG)" em **CX** (contagem de caixas) em vez do peso real em KG para itens cujo `UNID.` do DANFE não era "KG". Dois bugs distintos, ambos em `RX_ITEM`/`parseItensGeo`/`parseItensTexto`:

1. **Peso não extraído da coluna PESO do DANFE.** O regex `RX_ITEM` só capturava até a coluna QUANT.; a coluna PESO (bem mais à direita, depois de VL.UNITÁRIO/VALOR TOTAL/B.ICMS/.../AL.IPI) nunca era lida. Quando `unid !== "KG"`, o código caía num fallback que exibia `qtd + " " + unid` (ex.: "440 CX"). Corrigido com `extractPeso()`, que varre o texto após o match de `RX_ITEM` e pega o último número com **3 casas decimais** (o peso é a única coluna da linha com 3 decimais — valores monetários usam 2).
2. **Código/descrição do primeiro item de cada nota contaminados com sobras do cabeçalho da tabela** (ex.: código aparecendo como "ICMS" ou "IPI", descrição prefixada com "VALOR IPI AL.ICMS AL.IPI PESO..."). Causa: o grupo de captura do código aceitava qualquer sequência de letras maiúsculas, inclusive rótulos de coluna. Corrigido exigindo que o código contenha ao menos um dígito (lookahead `(?=[A-Z0-9.\-\/]*\d)`), já que códigos reais são sempre do tipo "00-105.292".

Validado simulando linhas reais do DANFE (não foi possível reprocessar um PDF real ponta a ponta na sessão) — código, descrição e peso em KG saem corretos. Usuário confirmou "deu certo" após reimportar.

### 2026-07-08 — v2.0: validação do peso do cabeçalho pela soma dos itens

Mesclada a partir do `analise_mapa_estatistico_v2_0.html` editado fora do Hub (pasta QSSA), re-extraído em `index.html` + `app.js` (vendors conferidos por hash — idênticos). Mudanças:

1. **Validação cruzada do peso líquido (PDF e XML):** quando todos os itens têm peso, a soma da coluna PESO é conferida contra o peso líquido do cabeçalho. Se a soma bate com algum peso impresso na nota, ela é a fonte de verdade silenciosa (corrige o layout Fricasa, onde a heurística de proximidade de rótulo pegava o peso BRUTO); se não corresponde a nenhum valor impresso, marca `pesoWarn` e avisa na lista de importação.
2. **Busca do peso do cabeçalho restrita à região antes da tabela de itens** (`findTableHeaderY`, por posição Y da linha "CÓD/DESCRIÇÃO/NCM") — em nota de item único, o filtro anterior por valor descartava o próprio peso líquido correto.
3. **`fmt3`** — pesos sempre exibidos com 3 casas decimais.
4. Visual/texto: rodapé "v2.0", botão "Continuar para importação" movido para cima do card de conferência, textos da nota informativa e cabeçalhos da tabela de resultado ajustados, `.pdflist .vals` com quebra de linha.

Validado no navegador via servidor estático local após a re-extração: libs carregam, worker inicializa, wizard renderiza sem erro de console.

### 2026-07-07 — Migração para o Hub SuperFrio & Icestar

Arquivo único `analise_mapa_estatistico_v1_9.html` (repositório separado `QSSA_Qualidade\Programa QSSA`) copiado para `frontend/mapa-estatistico/` deste repositório e dividido em `index.html` (HTML+CSS) + `app.js` (lógica), por exigência do CSP do portal. `vendor/` copiado sem alteração. Testado no navegador (via servidor estático local) após a extração: PDF.js e SheetJS carregam e inicializam corretamente, wizard renderiza, interações (adicionar nota manual) funcionam sem erro de console. Cadastro do app no portal (seção QHSE, iframe) feito manualmente pela tela Administração, fora deste commit.

---

## 7. Próximo passo sugerido

Resolver a pendência do alinhamento da coluna de resultados na sub-tabela de detalhes.
