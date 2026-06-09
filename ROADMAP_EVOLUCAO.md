# Roadmap de evolução do Hub — degrau a degrau

Os próximos passos do Hub depois da POC, na ordem **menor esforço / maior valor**.
Cada degrau é um lote independente: dá pra parar em qualquer um e o Hub continua de pé.
Nenhum exige reescrever o que já existe — a arquitetura deixou as portas abertas
(boundary de auth pronto pra AD, `SUPERFRIO_DB_PATH` configurável, deploy por Git/Docker).

> Comparativo de onde o Hub está hoje frente às grandes empresas:
> [HUB_VS_PADROES_INDUSTRIA.md](HUB_VS_PADROES_INDUSTRIA.md).

---

## Visão geral

| # | Degrau | Esforço | Valor | Depende de |
|---|---|---|---|---|
| 1 | URLs bonitas (proxy reverso) | Baixo | Médio | nada — só TI pro DNS |
| 2 | Auditoria de cliques | Médio | **Alto** (governança) | nada |
| 3 | Login único corporativo (SSO/Entra) | Alto | **Alto** | TI/Infra (Entra) |
| 4 | Banco em SQL Server | Médio | Sob demanda | TI (instância SQL) |
| 5 | Alta disponibilidade / réplica | Alto | Baixo (por ora) | — não recomendado ainda |

Faça na ordem. Os degraus 1 e 2 entregam valor sem depender de ninguém de fora.

---

## Degrau 1 — URLs bonitas (proxy reverso)

**O que é:** trocar `http://10.0.5.20:8000` por `http://hub.apps.superfrio.com.br`.
Sem porta, sem decorar número, com cara profissional.

**Por que:** é a "cara de governança" que a POC quer mostrar, e custa pouco. Cada app
novo vira um subdomínio limpo.

**Esforço:** baixo — **já está especificado** no
[GUIA_PUBLICACAO_REDE.md, seção 4](GUIA_PUBLICACAO_REDE.md), com receita pronta de Caddy
pra colar. Só falta executar na VM.

**O que muda no código:** nada no Hub. Adiciona-se um container "porteiro" (Caddy) na
frente, e o app entra na rede compartilhada `rede-apps`.

**Pré-requisito externo:** pedir à TI um registro DNS — idealmente um *wildcard*
`*.apps.superfrio.com.br → IP da VM` (assim todo app futuro já funciona sem novo pedido).

---

## Degrau 2 — Auditoria de cliques

**O que é:** registrar quem abriu qual app e quando. Hoje o Hub controla *acesso*
(quem pode ver), mas não registra *uso* (quem de fato abriu).

**Por que:** é o que transforma o Hub de "lista de links" em **vitrine de governança
com dados**. Permite responder "quais apps são realmente usados?", "quem nunca entrou
no Compras 2.0?" — exatamente o tipo de relatório que justifica a plataforma ao CSC.
Está marcado como "próxima POC" no `MEMORY.md`.

**Esforço:** médio. Encaixa direto no padrão `historico_*` da casa.

**O que muda no código:**
- `database.py` — nova tabela `historico_acessos` (`usuario_id`, `app_id`, `aberto_em`).
  ALTER/CREATE idempotente no `init_db()`, igual ao resto.
- `routers/portal.py` — um endpoint `POST /api/portal/abrir/{app_slug}` que carimba o
  acesso e devolve a URL; o front chama ele ao clicar no card.
- `routers/admin.py` — uma leitura `GET /api/admin/uso` com a contagem por app/usuário.
- `frontend` — o card passa a registrar antes de abrir; uma aba simples de "Uso" no Admin.

**Decisão a confirmar antes de codar:** registrar **todo** clique (mais dado, tabela
cresce) ou só o **primeiro acesso por dia** por usuário/app (mais enxuto). Para CSC, o
segundo costuma bastar.

---

## Degrau 3 — Login único corporativo (SSO via Entra)

**O que é:** o usuário loga uma vez no ambiente Microsoft e entra no Hub sem digitar
senha de novo — e, por tabela, nos apps. É o que o Entra "My Apps" faz.

**Por que:** é o **maior gap real** frente às grandes, e o que mais agrada usuário final
(uma senha a menos) e segurança (some o gerenciamento de senha local). Como a SuperFrio
já é casa Microsoft, encosta na infra que já existe.

**Esforço:** alto — mas a arquitetura já preparou o terreno. A função
`authenticate_user()` é o **único boundary** de login, e o schema já tem o campo
`auth_source`. Trocar "valida senha local" por "valida contra o Entra" acontece num
lugar só.

**O que muda no código:**
- `auth.py` — branch no `authenticate_user()` por `auth_source` (`local` vs `entra`);
  fluxo OIDC/SAML contra o Entra.
- `.env` — credenciais do app registrado no Entra (client id/secret) — nunca no git.
- `frontend` — botão "Entrar com conta SuperFrio" além (ou no lugar) do login local.

**Pré-requisito externo:** a TI/Infra registrar o Hub como aplicação no **Entra ID** e
fornecer as credenciais. Este degrau **não começa** sem isso.

**Dica:** dá pra manter o login local como *fallback* (`auth_source=local`) para contas
de serviço/teste, e usar Entra para as pessoas. O boundary suporta os dois lado a lado.

---

## Degrau 4 — Banco em SQL Server

**O que é:** sair do SQLite (arquivo único) para um servidor de banco de verdade —
idealmente o SQL Server que a TI já mantém, ou Azure SQL.

**Por que:** só vale **sob demanda**. SQLite aguenta dezenas de usuários internos
tranquilo; ele aperta em **escrita concorrente pesada**. Enquanto o Hub for leitura
(abrir apps) com escrita ocasional (admin cadastrando), SQLite basta. Suba este degrau
quando: muitos apps gravando muito, ou a TI exigir o banco na infra corporativa
(backup/HA central).

**Esforço:** médio. Depende de uma coisa: **se o backend usa SQLAlchemy**, a troca é
quase só mudar a string de conexão. Se for SQL escrito na mão, é refazer a camada de
acesso a dados — verificar antes de prometer prazo.

**O que muda no código:**
- `.env` — `DATABASE_URL` apontando pro servidor:
  `mssql+pyodbc://hub:senha@sqlserver-csc/hub` (segredo só na VM, fora do git).
- `database.py` — usar a `DATABASE_URL`; `SUPERFRIO_DB_PATH` (SQLite) vira o default de dev.
- Migrar os dados existentes do `.db` para o SQL Server (script de carga única).

**Governança a decidir:** um servidor de banco **compartilhado com um "database" por app**
(Hub, Contas, Relatórios isolados dentro dele) — recomendado pro CSC: um lugar pra
cuidar, backup central, apps ainda separados logicamente.

---

## Degrau 5 — Alta disponibilidade / réplica

**O que é:** o banco e o app deixam de ser "uma máquina só" — viram conjunto com
réplica e failover (se um cai, outro assume).

**Por que NÃO agora:** é o degrau das grandes (Netflix, bancos) e **não se justifica**
para apps internos de CSC. Custo e complexidade altos, ganho baixo no cenário atual.
Fica registrado só para fechar o raciocínio: existe, mas não é prioridade.

**Quando reconsiderar:** se algum app do Hub virar crítico de operação (parar = parar
o armazém) e exigir "não pode cair nunca". Aí entra a TI com infra dedicada — provável
que via Azure (gerenciado), não na mão.

---

## Como tocar isto

Um degrau por vez, validando antes do próximo — o padrão de lotes de sempre. Sugestão
de sequência prática: **1 → 2** primeiro (entregam valor sem depender de TI), depois
abrir o pedido de **3** (SSO) com a Infra em paralelo, e deixar **4** para quando o uso
pedir. **5** só se um app virar crítico.
