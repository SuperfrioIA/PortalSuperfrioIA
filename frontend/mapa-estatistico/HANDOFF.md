# HANDOFF — Analisador de Mapa Estatísticos (NF × WMS) — SuperFrio/IceStar

**Status:** **v2.24** — release atual no Hub (2026-08-31). Integrado ao Hub SuperFrio & Icestar em 2026-07-07 como app da seção **QHSE**, `tipo_acesso = iframe`. Marcos: **v2.0** em 2026-07-08 (validação de peso por soma dos itens), **v2.11** em 2026-07-22, **v2.24** em 2026-08-31 (ver changelogs abaixo). O sistema passou a se chamar **PGA · Análise de Mapa Estatísticos** na v2.21. ✅

---

## Changelog v2.11 → v2.24 (2026-08-31)

Portado do standalone (`QSSA_Qualidade\Programa QSSA`, `analise_mapa_estatistico_v2_24.html`)
preservando a estrutura modular do Hub. O port foi verificado por **round-trip**: remontar
`index.html` + `app.js` reproduz o standalone v2.24 byte a byte, tirando as 10 linhas do
"Voltar ao hub" (CSS + âncora) e a troca do `<script>` inline por `<script src="app.js">`.

**Fluxo e navegação**

- **Wizard de 3 → 2 passos (v2.17):** notas (PDF/XML) e relatório do WMS foram unificados numa
  tela só, lado a lado, com um único botão "Conferir" que libera quando os dois lados estão
  carregados. A sidebar agora tem "1 Importar dados" e "2 Resultado".
- **Dois fluxos independentes — Recebimento × Expedição (v2.23):** seletor na sidebar, cada
  fluxo com estado próprio (arquivos, notas, resultado); trocar de fluxo não perde nada. Não é
  código duplicado — é o mesmo motor sobre estados separados, com rótulos vindos de `MODULOS`.
  **O Recebimento não mudou.**
- **Expedição ligada ao relatório real (v2.24):** lê o `rpt_jda_sif_expedicao_v01`, com lista de
  colunas própria (25). O casamento é pela **NF Entrada STR7** — a `PO_NUM` é campo livre e
  divergia em 58 de 2304 linhas do arquivo real. O `Lacre SIF` é capturado à parte do `SIF` do
  produto, e produto sem SIF passa sem virar divergência.

**Regras de conferência**

- **SIF × SISB (v2.14, v2.22):** o relatório do WMS não tem coluna de SISB — o número de
  inspeção (SIF **ou** SISB) vem todo na coluna SIF. Agora **a nota diz o que ele é**:
  `classificaInsp` (que substituiu `sifDiverge`) bate com o SIF → é SIF; senão bate com o
  SISB → migra para a coluna SISB e confere lá; não bate com nenhum → divergência. Corrige
  falso positivo em produto de inspeção estadual. O SISB da NF é capturado em coluna própria.
- **Coluna Origem (v2.12, v2.13):** NACIONAL × ESTRANGEIRA pela **Tabela "A" da NF-e** (1º dígito
  do CST no DANFE / tag `<orig>` no XML), com fallback pela descrição do produto quando o CST
  não vem. É **informativa** — não altera Confere/Divergência. Sem cor, só negrito.

**Exportação para Excel (novo)**

- **Botão ⤓ Exportar para Excel (v2.19):** gera `.xlsx` com o detalhamento por item achatado na
  aba **Detalhamento** e os totais por nota na aba **Resumo por NF**. Respeita o filtro ativo
  (todas / conferem / divergem). A regra de status/SIF/origem foi extraída para `detailRows()`,
  fonte única da tela e do Excel.
- **Detalhamento com 13 colunas (v2.20):** entraram `Diferença (kg)` (numérica, `0` quando não há
  diferença) e `Diferença (SIF)` (`OK`/`NOK`). O arquivo **não traz mais `—`**: SIF/SISB/pesos sem
  informação saem zerados e texto sem informação sai em branco. A tela segue com o travessão.
- Prefixo `PGA_` no nome do arquivo exportado (v2.21).

**Identidade e layout**

- **Renome para PGA (v2.21):** selo `PGA` na sidebar, `<title>` e prefixo do `.xlsx`. Só
  identidade, sem mexer em lógica.
- `.content` de 1180 → 1440px e títulos do detalhamento em uma linha (`nowrap`), para as colunas
  caberem sem quebrar (v2.15); coluna Descrição de 21% → 30% (v2.16); os dois cards de importação
  com altura fixa e igual (620px), com a lista de arquivos e o painel de colunas rolando por
  dentro (v2.18).

**Nada mudou em `vendor/`** — os 3 arquivos são idênticos aos do standalone (conferido por hash
após normalizar CRLF). Nenhuma dependência nova, nenhum `<script>`/`on*=` inline: o CSP do
portal segue respeitado sem exceção.

---

## Changelog v2.0 → v2.11 (2026-07-22)

Todas as mudanças abaixo estão em `app.js` (lógica) e `index.html` (CSS/títulos):

- **Casamento sempre pela coluna NF** (`rowMatchesNf`): o romaneio saiu do match. Um mesmo romaneio agrupa várias notas, então casar por romaneio somava o peso de outras NFs e gerava **falsa divergência**. Corrigido.
- **Coluna SIF capturada do WMS** (`CAMPOS` ganhou `{key:"sif"}`) e novo `xlsxPorProduto` (agrupa as linhas do WMS por produto: soma peso e junta SIFs).
- **Detalhamento por produto** (`buildDetail`): tabela NF × XLSX lado a lado — Item · Descrição · Peso líq. KG (NF) · SIF (NF) · Peso líq. KG (XLSX) · SIF (XLSX) · **Status por item**. Linha destacada em amarelo quando não confere; status em texto colorido (azul "Confere" / dourado "Divergência"), sem box.
- **Comparação de SIF** (`sifNum`/`sifDiverge`): SIF da NF × SIF do XLSX; se divergem, o item e a NF viram Divergência (mesmo com peso batendo; Δ em kg segue 0). SIFs divergentes destacados.
- **`extractSif` retorna só o número do SIF** (ex.: `LACRE SIF :0006974/SIF1889` → `1889`), evitando falso positivo na comparação e limpando a exibição.
- **Títulos** da tabela principal: "NF (XML)" e "Esperado (XML)".
- **Layout**: separador vertical único entre SIF (NF) e Peso líq. XLSX (comparativo NF|XLSX); código do item em uma linha.

Origem: desenvolvido/validado em standalone (repo pessoal) e portado para cá preservando a estrutura modular (index.html + app.js). Baseline v2.0 era idêntico ao standalone v2.0, então o port foi 1:1 por função.

---

## 1. O que é o projeto

Ferramenta HTML standalone (offline) para reconciliar o **peso líquido esperado** extraído de notas fiscais (DANFE PDF / NF-e XML) contra o **peso registrado pelo WMS**. Desde a v2.23 são **dois fluxos independentes**, escolhidos na sidebar:

| Fluxo | Relatório do WMS | Casamento |
|---|---|---|
| **Recebimento** | `rpt_jda_recebimento_dtl_v03` (18 colunas) | coluna NF |
| **Expedição** | `rpt_jda_sif_expedicao_v01` (25 colunas) | NF Entrada STR7 |

Wizard de **2 passos** (era 3 até a v2.16 — ver changelog da v2.17):

1. **Importar dados** (tela única): DANFE (PDF) / NF-e (XML) — extrai NF, chave de acesso, peso
   líquido esperado, itens — **e** o relatório do WMS (Excel), lado a lado. A tabela de
   conferência das notas fica abaixo.
2. **Resultado** — cruza as notas, mostra divergências de peso e de SIF/SISB, permite expandir o
   detalhamento por item e exportar tudo para Excel.

Marca SuperFrio | IceStar (Conexão LATAM). Padrão visual: Montserrat, gradiente azul escuro `#0A2A5E→#10468F`, amarelo `#FFC400` para alertas/estado ativo.

---

## 2. Estrutura de arquivos ATUAL (dentro do Hub SuperFrio & Icestar)

Vive em `frontend/mapa-estatistico/` deste repositório (Receita 1 do [CONTRIBUTING.md](../../CONTRIBUTING.md) — HTML estático embutido via iframe, sem backend, sem banco):

```
frontend/mapa-estatistico/
  index.html         77 KB  ← HTML + CSS (edite este)
  app.js             46 KB   ← lógica do app, extraído do <script> inline (edite este)
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

O Hub serve todo `frontend/` como estático (`backend/main.py`, `StaticFiles`). O app é acessado em `/mapa-estatistico/` e cadastrado na tela **Administração** do portal como card na seção **QHSE**, `tipo_acesso = iframe`. Roda em iframe sandboxed. **Atualizado:** desde 2026-07-07 o sandbox inclui `allow-same-origin` (item A1 de `docs/AUDITORIA_SEGURANCA.md`) justamente porque o worker do PDF.js é montado via Blob e falha com origem opaca. O app não depende de cookie/localStorage do domínio do portal, mas tecnicamente teria acesso — trade-off consciente da plataforma, documentado no CONTRIBUTING.

---

## 4. Regras de trabalho OBRIGATÓRIAS para próximas sessões

1. **Nunca** rodar `grep`, `cat` ou regex ampla contra `index.html`/`app.js` de uma vez sem necessidade — ainda pode ter linhas longas (CSS, funções de lógica). Usar sempre `grep -n` para achar a linha, depois editar cirurgicamente.
2. **Nunca abrir os arquivos em `vendor/`** — são bibliotecas de terceiros, read-only, e são grandes o bastante para estourar contexto se lidos por engano (`pdf.worker.b64.js` sozinho tem 1,45 MB numa única linha).
3. Para editar a lógica do app: `grep -n "termo" frontend/mapa-estatistico/app.js` → localizar linha → editar com contexto único (não reescrever o arquivo inteiro).
4. Se precisar atualizar SheetJS ou PDF.js no futuro: trocar o arquivo correspondente em `vendor/` diretamente — não precisa re-extrair nada do HTML.
5. Qualquer novo `<script>`/`<style>` inline em `index.html` vai ser bloqueado pelo CSP padrão do portal — mantenha tudo em `app.js`/CSS já existente.

---

## 5. Pendências conhecidas

- **Expedição — confirmar quais notas são (v2.24).** O `rpt_jda_sif_expedicao_v01` só traz **NF de
  entrada**, e é por ela que o casamento é feito (`NF Entrada STR7`). Falta confirmar com a
  operação se as notas conferidas na expedição são mesmo as de entrada, ou se é preciso outra
  fonte para a NF de saída. **Não bloqueia o Recebimento**, que não mudou.
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

Confirmar com a operação a pendência da Expedição (qual NF o relatório traz), e depois resolver o
alinhamento da coluna de resultados na sub-tabela de detalhes.
