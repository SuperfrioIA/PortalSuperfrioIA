# Changelog

## [0.15.2] — 2026-09-03
### Corrigido
- Peso líquido e peso bruto da Volumetria de Transporte e de Estoque estavam rotulados "(t)" —
  na Matriz e no cabeçalho do CSV/Excel — mas o número mostrado é o kg cru do DW, sem nenhuma
  conversão por trás (diferente do catering, que divide por 1000 quando a lente é "t"). Corrigido
  o rótulo para "kg", que é o que a tela sempre mostrou de fato
- `/opcoes` da Volumetria de Transporte varria a tabela inteira do DW a cada abertura de tela
  (9 `SELECT DISTINCT`/`MIN`/`MAX`, ~9,4s medidos) — agora tem cache de processo com TTL de 1h,
  compartilhado entre todo mundo que abre a tela. Cliente/unidade novo é raro (~1x/6 meses); só o
  "atualizado até" fica sujeito ao atraso do TTL
### Alterado
- Filtros da Volumetria de Transporte e de Estoque trocam os `<select multiple>` nativos pelo
  mesmo painel "caixas com checkbox" do catering — com 8 dimensões na tela (transporte), os
  selects nativos ficavam todos abertos ao mesmo tempo, sem indicar "tudo" vs "nada" selecionado.
  O catering não foi tocado neste lote — ele já tem usuários e segue seu próprio plano
- Matriz da Volumetria de Transporte e de Estoque agora abre/fecha por nível (unidade → cliente →
  movimento/câmara), igual ao catering — antes renderizava tudo sempre expandido, e com dado real
  isso virava uma parede de linhas (uma unidade com 2 clientes de 6-7 câmaras cada já enchia a
  tela). Fechado por padrão; cada nó lembra se foi aberto, sem refazer a consulta ao servidor

## [0.15.1] — 2026-09-03
### Corrigido
- `oracledb` faltava no `requirements.txt` — Volumetria de Transporte e de Estoque respondiam
  503 "driver do Oracle não está instalado" mesmo com a credencial do DW já configurada. Não foi
  esquecido no rebase do 0.15.0: nunca chegou a entrar no arquivo em nenhum commit da branch

## [0.14.0] — 2026-09-03
### Adicionado
- Trilha de auditoria funcional (Fase 1) — quem fez o quê, quando, com que resultado. Cobre
  login/logout, login e SSO recusados, abertura de app pelo card, acesso negado, e diff
  (antes → depois) em toda mutação administrativa: usuários, roles, apps, seções, filiais,
  unidades de negócio, projetos IA, processos-abertos e integração in/out
- Nova aba **Auditoria** em Administração — filtra por período, usuário, app, categoria e
  resultado, com paginação e exportação em CSV (Excel-first)
- Tabela append-only por trigger de banco (`auditoria_eventos`) — nem o próprio código consegue
  alterar ou apagar um evento já gravado, só inserir
- Correlação entre o log técnico e a auditoria: toda resposta traz `X-Request-ID`, e o mesmo id
  aparece na linha de log e no evento da mesma requisição
### Observações
- Não é log técnico nem métrica operacional — os dois continuam existindo à parte. Retenção sem
  purga nesta fase (decisão pendente, ver `docs/AUDITORIA_FUNCIONAL.md`). Leitura restrita a
  administradores; um papel de auditor sem privilégio total é roadmap

## [0.15.0] — 2026-09-04
### Adicionado
- Volumetria de Transporte no Hub — nova tela de consulta (Matriz por unidade, cliente e tipo de movimento; planilha; download em CSV/Excel), lendo direto o DW Oracle (`FATO_VOL_TRN_CAT_V01`), sem banco intermediário. Card "Transporte de Catering" na seção Armazém
- Volumetria de Estoque no Hub — mesma ideia, sobre `FATO_VOL_EST_CAT_V01`, com uma diferença de fundo: a Matriz agrega em **modo posição** (a foto do último dia com dado de cada mês), não soma os dias — porque a tabela é um saldo diário, não um fluxo de movimentos. A tela declara isso; não existe total anual nem "soma da planilha bate com a Matriz" aqui, de propósito. Card "Estoque de Catering"
- Baixar as duas volumetrias novas é permissão própria por app (`volumetria-transporte:exportar`, `volumetria-estoque:exportar`), como no catering; consultar a tela exige só o acesso ao app
### Observações
- Dois módulos novos, independentes entre si e do `volumetria_catering` — não compartilham código (a base comum ficou para um lote futuro, se algum dia acontecer). Cada um tem a sua própria conexão, ticket de download e auditoria
- Sem a rede de segurança que o catering terá quando comparar o SQL do Postgres com o do Oracle (D3 do outro plano): as duas telas nascem lendo o DW direto, e a prova de que o SQL gerado é aceito pelo Oracle de verdade é `/api/volumetria-transporte/diagnostico-dw` e `/api/volumetria-estoque/diagnostico-dw` rodados na VM, não uma suíte automatizada
- Nenhuma role recebe `ver` destes apps pelo seed — só admin enxerga os cards até alguém decidir o acesso

## [0.13.0] — 2026-08-31
### Adicionado
- Análise de Mapa Estatísticos atualizada da v2.11 para a **v2.24** — o app agora se chama **PGA · Análise de Mapa Estatísticos** e ganhou o fluxo de **Expedição** ao lado do de Recebimento: são dois fluxos independentes, escolhidos na lateral, cada um com seus próprios arquivos e resultado. Trocar de fluxo não perde o que já estava carregado, e o Recebimento continua exatamente como era
- **Exportar para Excel** na tela de resultado — baixa o detalhamento item por item (13 colunas, incluindo a diferença em kg e se o SIF confere) mais os totais por nota numa segunda aba, sempre no recorte do filtro ativo (todas / conferem / divergem)
- **A nota diz se o número de inspeção é SIF ou SISB** — o relatório do WMS traz os dois na mesma coluna, e antes o produto de inspeção estadual aparecia como divergência sem ser. Agora, se não bate com o SIF mas bate com o SISB, confere pelo SISB; se não bate com nenhum, é divergência de verdade
- Coluna **Origem** no detalhamento (Nacional × Estrangeira), lida da própria nota. É informativa — não muda o resultado da conferência
### Alterado
- **Importação numa tela só** — as notas (PDF/XML) e o relatório do WMS ficam lado a lado, e o wizard passou de 3 para 2 passos: importar e conferir. Um botão só, que libera quando os dois lados estão carregados
- Tela mais larga e títulos do detalhamento em uma linha, para as colunas caberem sem quebrar
### Observações
- Continua sendo app estático embutido (Receita 1): sem backend, sem banco, sem rota nova, sem permissão nova além do `ver`. O endereço segue `/mapa-estatistico/`, então o cadastro em Administração não muda
- **Pendente na Expedição:** o relatório `rpt_jda_sif_expedicao_v01` só traz a NF de entrada, e é por ela que a conferência casa as linhas. Falta a operação confirmar se são mesmo essas as notas da expedição. Não afeta o Recebimento

## [0.12.0] — 2026-08-27
### Adicionado
- Volumetria de Catering no Hub — a tela de recebimento e expedição de catering (que morava num endereço próprio, com login próprio) passa a abrir por card no portal, com o login da Microsoft e o mesmo "Voltar ao hub" das outras telas. Matriz por unidade, cliente e mês, planilha com a linha crua e download em CSV ou Excel, sempre no recorte dos filtros
- Baixar a volumetria virou permissão — consultar a tela exige só o acesso ao app; baixar o arquivo é uma célula própria na matriz de acesso, e quem baixou o quê fica registrado. No endereço antigo, qualquer pessoa logada baixava
- A tela diz de quando é o dado — a data da última carga aparece no cabeçalho, e o detalhe (tabela, origem, quantas linhas) fica em "Fontes & método"
### Observações
- O número continua vindo do mesmo banco de sempre, alimentado pela carga que já roda duas vezes ao dia; o Hub só lê. Enquanto a transição durar, a tela antiga continua no ar e é a oficial

## [0.11.0] — 2026-08-25
### Adicionado
- Menu lateral separando Indicadores de Sistemas — os painéis de acompanhamento (Processos Abertos e Integração In/Out) ganharam um grupo próprio, e as áreas do catálogo viraram subitens de Sistemas. Clicar num painel no menu já abre o painel
- Governance TI e Mapa IA entraram no catálogo de apps — deixaram de ser botão fixo do menu e agora têm linha na matriz de acesso, como qualquer outro app. O card do Mapa IA passou a aparecer só para administradores (quem tiver o endereço direto continua abrindo, como nos outros apps embutidos)
- Campo "O que este app é" no cadastro de app — escolhe se ele aparece em Indicadores ou em Sistemas, sem depender de alteração no sistema
- Selo "Fora do Hub" nos cards — mostra de relance qual sistema abre em nova aba, com login próprio (o caso do Conciliador de Estoque), e qual roda aqui dentro
### Alterado
- Menu lateral mais enxuto — saíram "Todos os apps" e o rótulo "Seções"; clicar na marca no topo volta para a visão completa
- "Sistemas" no menu virou "Linha do tempo" — o nome passou a ser do grupo novo; a tela continua a mesma
- Novidades e Linha do tempo desceram para o bloco Governança, logo acima do idioma
- Contagem de cada área conta só sistemas — os painéis agora são contados no grupo Indicadores

## [0.10.0] — 2026-08-21
### Adicionado
- Entrar com Microsoft — login com a conta corporativa (Entra ID), sem senha nova para decorar. Em máquina corporativa já autenticada, entra sem pedir senha
- Filial no cadastro de usuário — cada pessoa passa a ter lotação, e a filial do CSC entrou no catálogo
- Filtros em toda a Administração — busca por texto e situação em todas as abas, mais filial e role em Usuários e região e unidade de negócio em Filiais
- Cabeçalho padrão nos apps embutidos — Mapa IA e Governance TI agora têm "Voltar ao hub" à esquerda e a marca à direita, como as outras telas
### Corrigido
- App embutido abrindo em branco — acontecia quando a URL era cadastrada sem a barra no fim, caso do Mapa Estatístico
- Duas barras de rolagem — a página de trás continuava rolando junto com o app aberto em tela cheia
- "Voltar ao hub" não funcionava — o link estava sendo bloqueado silenciosamente em todo app aberto pelo portal
- Login de todos podia ser bloqueado por um minuto — as tentativas erradas de uma pessoa contavam para a empresa inteira
- Tela branca com texto técnico — aparecia ao usar o botão Voltar do navegador depois de entrar pela Microsoft
- Acesso desativado dava erro de sistema — agora a pessoa lê que o acesso está desativado e a quem pedir
### Alterado
- Cadastro sem senha para quem usa a Microsoft — o e-mail passou a ser obrigatório, porque é ele que liga a pessoa à conta corporativa
- Primeiro acesso exige cadastro prévio — sem cadastro, a pessoa recebe orientação para pedir acesso ao administrador
- Lista de usuários mais enxuta — as colunas "Roles" e "O que isso dá de acesso" viraram uma só, com os nomes das roles no detalhe
- Login local virou acesso administrativo — fica recolhido na tela de entrada, para emergência

## [0.9.0] — 2026-08-20
### Adicionado
- Processos Abertos busca os relatórios sozinho — os arquivos do SLIN e do BY/JDA passam a ser lidos direto do FTP, no lugar do upload manual. Roda todo dia às 08:05, com uma segunda tentativa às 08:30 se o arquivo ainda não estiver lá
### Corrigido
- Selo de situação da carga — não aparecia na tela de Processos Abertos

## [0.8.0] — 2026-08-19
### Adicionado
- Gerador de QR Code (Bipagem) — novo app que gera e imprime a etiqueta de QR Code usada na bipagem
### Corrigido
- Salvar a imagem do QR Code — não funcionava com o app aberto dentro do portal
- Cabeçalho do Gerador de QR Code — estava fora do padrão das outras telas

## [0.7.0] — 2026-08-11
### Adicionado
- Integração In/Out — novo painel com pedidos integrados x manuais por unidade, mês a mês

## [0.6.2] — 2026-08-03
### Corrigido
- Processos Abertos contava só os processos do BY/JDA — os do SLIN ficavam de fora do painel
- Unidade partida em dois nomes na origem — MAQ com Mairinque e BSB com TAC BSB passaram a somar num número só
- App embutido mostrando versão antiga — continuava assim depois de uma atualização da plataforma

## [0.6.1] — 2026-07-30
### Corrigido
- Menu lateral cortado — aparecia truncado em telas de pouca altura
- Coluna de ações desalinhada — nas tabelas da Administração
- Rótulo "POC v0.1" no rodapé — removido da tela de entrada

## [0.6.0] — 2026-07-27
### Adicionado
- Projetos IA — nova tela com o radar dos projetos de IA da empresa: macrofases, cronograma e acompanhamento do rollout por filial
- Cadastro de Filiais na Administração — as 59 filiais de produção, espelhando o cadastro do Conciliador de Estoque, com código, cidade, UF, região e responsável
- Cadastro de Unidades de negócio — nova aba na Administração, para agrupar as filiais

## [0.5.0] — 2026-07-26
### Adicionado
- Matriz de acesso na tela de Administração — apps nas linhas, ações nas colunas (Ver, Editar, Exportar, Administrar), com marcação por coluna e por seção
- Catálogo de permissões declarado em código — cada módulo declara suas ações e um slug errado passa a derrubar o boot em vez de virar erro silencioso
- Endpoint único `GET /api/auth/me/permissoes` para o frontend consultar tudo que o usuário pode fazer, no lugar de um `/pode-editar` por app
- Coluna "Permissões de ação" na lista de roles e coluna "O que isso dá de acesso" na lista de usuários
- Passo obrigatório de declaração de permissão no guia de contribuição e no template de PR
### Corrigido
- Desativar uma role não revogava o acesso aos apps — a checagem ignorava `roles.ativo` e mantinha os cards visíveis para quem já tinha a role
### Alterado
- Processos Abertos passou a exigir a permissão `processos-abertos:editar` no lugar de uma role de nome fixo; ambientes que já tinham a role antiga são migrados automaticamente
- `GET /api/processos-abertos/pode-editar` está depreciado e será removido depois que o app embutido estiver no endpoint global

## [0.4.0] — 2026-07-07
### Adicionado
- Timeline de changelog e sistemas no portal — nova tela "Novidades" com o histórico de mudanças em linha do tempo
- Guia de contribuição e CODEOWNERS documentados no repositório
### Corrigido
- Changelog não aparecia na tela Novidades em produção — CHANGELOG.md agora incluído na imagem Docker
- Espaçamento entre os cards da timeline de novidades
- Clipping das bordas nas timelines de changelog e sistemas

## [0.3.0] — 2026-07-02
### Adicionado
- Modularização em Modular Monolith — módulos portal, auth e usuarios independentes (Lote 3)
- Postgres como banco de dados principal na VM (Lote 2)
- SQLAlchemy + Alembic substituem acesso SQLite direto; migrations versionadas (Lote 1)
- Apostila de arquitetura e vault Obsidian documentados no MEMORY.md

## [0.2.1] — 2026-07-01
### Adicionado
- Apresentação Governance TI embutida no portal como overlay em tela cheia

## [0.2.0] — 2026-06-23
### Corrigido
- Tela de admin trata sessão expirada (401) e redireciona automaticamente para o login
- Correção de flash de tela branca na inicialização do portal

## [0.1.3] — 2026-06-22
### Adicionado
- Porta de host configurável via variável HOST_PORT no .env (padrão 8000)
- Documentação interna movida para docs/ e excluída do git
### Segurança
- frame-src do CSP configurável via variável SUPERFRIO_FRAME_SRC — remove wildcard *
### Alterado
- Context manager db() e helpers consolidados no admin; suite de testes integrada

## [0.1.2] — 2026-06-11
### Adicionado
- Vitrine 3D inicializada com Three.js

## [0.1.1] — 2026-06-09
### Alterado
- Identidade visual alinhada à marca IceStar | SuperFrio (tema claro)
- Internacionalização PT/ES com troca de idioma e logo combinado

## [0.1.0] — 2026-05-29
### Adicionado
- Portal SuperFrio POC — hub interno com login JWT, seções, apps, roles e usuários (Lotes 1–4)
