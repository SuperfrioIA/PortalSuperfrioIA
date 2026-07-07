# MEMORY — Hub SuperFrio & Icestar (POC)

Documento de transferência para retomar este projeto em outro chat.

> **Estado atual (2026-06-09):** código da POC **completo e blindado**. Lotes 1–4
> (backend, frontend, admin CRUD, Docker) + Lote 5 (i18n PT/ES + identidade IceStar |
> SuperFrio tema claro) + **auditoria de segurança** inteira (todos os itens
> crítico/alto/médio resolvidos — ver [AUDITORIA_SEGURANCA.md](docs/AUDITORIA_SEGURANCA.md)).
> Falta **executar** o deploy real na VM (HTTPS, JWT_SECRET prod, firewall).
>
> **Migração da plataforma (2026-07-02): Lotes 1, 2 e 3 CONCLUÍDOS.**
> Lote 1 = SQLAlchemy + Alembic (branch `feat/migracao-lote1-sqlalchemy`); Lote 2 = Postgres no
> compose (feito em outro chat, commitado na mesma branch); Lote 3 = modularização
> core/auth/usuarios/portal (branch `feat/migracao-lote3-modularizacao`). Suíte de 56 testes +
> smoke em uvicorn real (banco novo e legado) verdes em todos.
> **Lote 4 (absorver Contas Recorrentes) foi CANCELADO em 2026-07-02 por decisão da Maria — o
> Contas fica como app separado.** A migração encerra no Lote 3; próximos candidatos: deploy dos
> lotes na VM e a auditoria de cliques (Degrau 2, trilha paralela do plano).
> Ver [PLANO_MIGRACAO_PLATAFORMA.md](docs/PLANO_MIGRACAO_PLATAFORMA.md) e as seções "Migração
> Plataforma" abaixo.
>
> **Direção de arquitetura (revisada 2026-07-01):** a plataforma será um **Modular Monolith** —
> **um único projeto, um processo, um banco**, organizado em **módulos** (Core, Auth, Usuários,
> Dashboard, Contas, FAT, Estoque, Inventário, IA, APIs), cada um dono das próprias telas,
> services, models, migrations, permissões e testes. Módulos conversam por **chamada de função
> via service** (nunca SELECT na tabela do outro), não por HTTP. **Um único banco** com separação
> lógica por **schema** (Postgres) ou prefixo (`tb_financeiro_...` no SQLite). Login/permissões/
> auditoria centralizados nos módulos `Auth`/`Usuários`. **Não** é monólito bagunçado (Protheus)
> **nem** microsserviços desde já ("Monolith First" do Fowler) — extrair um módulo pra serviço
> fica pro futuro, se algum crescer o suficiente. **Substitui** a direção SCS de 2026-06-26.
> Decisão completa, ressalvas e referências em
> [ARQUITETURA_PLATAFORMA.md](docs/ARQUITETURA_PLATAFORMA.md).

---

## Contexto

POC de **plataforma centralizadora dos apps internos da SuperFrio** ("sisteminhas" feitos no vibe code do CSC). O portal lista cards de cada app por seção (Armazém, Backoffice…) e leva o usuário ao app correspondente. Objetivo final: empacotar com Docker + Git, publicar em VM Windows com Docker, mostrar arquitetura de governança ao time.

Não é só um portal — é a vitrine da governança: cadastro de apps, permissionamento, versionamento, deploy reprodutível.

---

## Decisões travadas

- **Stack**: FastAPI + SQLite (single-file, WAL) + HTML único + CSS/JS vanilla. **Sem Tailwind, sem build step.** Padrão SuperFrio.
- **Auth**: JWT + bcrypt. Função `authenticate_user()` é o único boundary — hoje valida local, amanhã faz LDAP bind (campo `auth_source` já no schema).
- **Permissionamento**: por app individual + roles. Roles agrupam apps; usuários recebem N roles. Admin (`is_admin=1`) bypassa tudo.
- **Linkagem dos apps**: campo `tipo_acesso` no cadastro (`url` ou `iframe`). Default `url`. Maria decide por app no Lote 3.
- **Cadastro de apps**: seed inicial + CRUD admin pela UI (Lote 3). Demonstra governança ao vivo.
- **Renomeação de campos do Protheus**: nunca. Etapas internas podem ser renomeadas.
- **Migrations**: Alembic (`backend/migrations/`), aplicadas no startup (`alembic upgrade head` programático no `init_db`; banco pré-Alembic recebe `stamp` da baseline). Seed idempotente insere só o que falta. *(Substituiu o ALTER TABLE na mão + `INSERT OR IGNORE` no Lote 1 da migração, 2026-07-02.)*
- **Direção do banco (decidido 2026-06-09, ainda NÃO executado):** sair do SQLite e ir pra um **servidor Postgres na PRÓPRIA VM** (container no mesmo `docker-compose`), com **um único banco** e separação lógica por **schema** por domínio (`hub`, `financeiro`, `estoque`...) — **revisado 2026-07-01**: era "um database por app", mas com a plataforma virando **Modular Monolith** passou a ser **um banco só**, isolamento por schema (Postgres) ou prefixo de tabela (`tb_financeiro_...` no SQLite). Backup central num lugar só. **Não depende da TI.** Migração via **SQLAlchemy** (hoje é `sqlite3` na mão, ~47 pontos) pra que trocar depois pro SQL Server corporativo (cenário 3) seja só `connection string`. Esse lote vem **antes** do Degrau 2 (auditoria de cliques nasce já no Postgres). O código/migração dá pra fazer e testar **local** com Docker; só o deploy aguarda a VM.
- **Direção de plataforma (revisada 2026-07-01):** a plataforma é um **Modular Monolith** — um
  projeto/processo/banco único, dividido em **módulos** com fronteira clara. Módulos compartilham
  Auth, permissões, auditoria e infra, mas cada um é dono do seu domínio (telas/services/models/
  migrations/permissões/testes). **Regra de ouro:** um módulo nunca lê a tabela/model de outro
  direto — só via **service** do módulo dono (`Financeiro → EstoqueService → ProdutoRepository`).
  A fronteira é lógica (não forçada pelo compilador) → exige disciplina + code review + (futuro)
  teste de arquitetura. Resolve a troca de dados por **chamada de função**, sem HTTP/token entre
  serviços. **Substitui** a direção SCS/apps-separados de 2026-06-26 (que fica como degrau seguinte:
  extrair módulo→serviço se justificar). Apps já existentes (Contas Recorrentes) são **absorvidos
  como módulo** — tem custo (remover auth próprio, mover tabelas). Login único mira o **Entra** no
  futuro (Degrau 3), via módulo `Auth`. Detalhes/refs em
  [ARQUITETURA_PLATAFORMA.md](docs/ARQUITETURA_PLATAFORMA.md).

---

## Lote 1 — CONCLUÍDO

Backend FastAPI completo + auth + seed + smoke test passando.

**Arquivos criados:**
- `backend/database.py` — schema (usuarios, secoes, apps, roles, role_apps, usuario_roles), WAL, `init_db()` idempotente
- `backend/auth.py` — bcrypt, JWT, `authenticate_user()` (boundary AD), `get_current_user`, `require_admin`
- `backend/seed.py` — 2 seções, 7 apps, 3 roles, 3 usuários (idempotente)
- `backend/routers/auth.py` — `POST /api/auth/login`, `GET /api/auth/me`
- `backend/routers/portal.py` — `GET /api/portal/home` (filtrado por permissão)
- `backend/routers/admin.py` — leituras protegidas (CRUD vem no Lote 3)
- `backend/main.py` — FastAPI + CORS + lifespan (init_db + seed)
- `requirements.txt`, `.gitignore`

**Smoke test validou:**
- admin/admin123 → vê 7 apps em 2 seções
- operador.armazem/armazem123 → vê só 3 apps (Armazém)
- operador em `/api/admin/*` → 403
- senha errada → 401

---

## Lote 2 — CONCLUÍDO (Frontend)

Frontend único HTML+CSS+JS vanilla, sem Tailwind/build step.

> ⚠️ **Paleta/tipografia desta seção foram SUBSTITUÍDAS no Lote 5.** Originalmente herdadas do
> app irmão Contas Recorrentes (Nunito, `--sf-dark #295494`, `--sf-light #29abe2`). Hoje vale a
> identidade IceStar | SuperFrio (Montserrat, tema claro) — ver Lote 5.

**Arquivos criados:**
- `frontend/index.html` — duas telas no mesmo arquivo (login e portal), trocadas via classe `.hidden`
- `frontend/css/styles.css` — paleta SuperFrio + login split (aside com gradiente azul + grid sutil) + portal Moonday (sidebar 248px + grid responsivo)
- `frontend/js/app.js` — auth via `URLSearchParams` (OAuth2PasswordRequestForm), token em `localStorage`, fetch `/api/portal/home`, render de sidebar + grid, busca client-side, iframe overlay para `tipo_acesso=iframe`, ícones SVG inline (mapeados por seed: warehouse, briefcase, book, scale, chat, cart, document, truck)
- `frontend/img/superfrio-logo.jpg` — logo copiado do app irmão
- `backend/main.py` — `app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")` no fim (após os routers)

**Smoke test validou:**
- `GET /` devolve `index.html` (200)
- `GET /css/styles.css`, `/js/app.js`, `/img/superfrio-logo.jpg` → 200
- Login admin → 2 seções, 7 apps na home
- Login operador.armazem → só Armazém (3 apps)
- Login com senha errada → 401

**Decisões de UI:**
- Tipografia: Nunito (mantém identidade com Contas Recorrentes)
- Login: split layout — aside esquerda com gradiente sf-dark→sf-light + grid sutil, form à direita
- Sidebar: "Todos os apps" + uma entrada por seção, com contagem; usuário + logout no rodapé
- Cards: hover translateY(-1px) + shadow, sem animação piscante, badge sutil (NEW=verde, BETA=âmbar, iframe=azul)
- Saudação dinâmica por hora (Bom dia/Boa tarde/Boa noite + primeiro nome)
- Busca client-side filtra por nome ou descrição

---

## Lote 3 — CONCLUÍDO (Admin CRUD)

CRUD completo (apps, seções, roles, usuários) via UI. Toggle ativo/inativo, sem DELETE — auditável.

**Backend (`backend/routers/admin.py`):**
- Pydantic models: `SecaoCreate/Update`, `AppCreate/Update`, `RoleCreate/Update`, `UsuarioCreate/Update`, `PasswordReset`
- Seções: `POST /api/admin/secoes`, `PATCH /api/admin/secoes/{id}`, `POST /api/admin/secoes/{id}/toggle`
- Apps: `POST/PATCH /api/admin/apps[/{id}]`, `POST .../toggle`; valida `tipo_acesso ∈ {url, iframe}`
- Roles: `POST/PATCH /api/admin/roles[/{id}]`, `POST .../toggle`; gerencia `role_apps` via slugs
- Usuários: `POST/PATCH /api/admin/usuarios[/{id}]`, `POST .../toggle`, `POST .../password`; gerencia `usuario_roles`
- Lockouts: admin não pode desativar a si mesmo nem remover o próprio `is_admin`
- Slug é stable (não editável depois de criado); `_ensure_slug` valida formato
- 409 em slug/username duplicado; 400 em payload inválido; 403 quando não-admin acessa
- `atualizado_em` carimba via `datetime('now')` em apps/usuarios

**Frontend:**
- `frontend/index.html` — botão "Administração" na sidebar (classe `.admin-only`, escondido se não é admin) + tela `#screen-admin` com tabs Apps/Seções/Roles/Usuários + modal genérico
- `frontend/css/styles.css` — tabs, tabela admin, pills (on/off/admin/iframe/url/new/beta), modal centralizado com overlay
- `frontend/js/admin.js` — novo arquivo: estado isolado, fetch helper, render de tabelas, modal builders por entidade, submit POST/PATCH, toggle
- `frontend/js/app.js` — expõe `window.SF` (state, escapeHtml, iconSvg) e abre/volta da tela admin; mostra `.admin-only` quando `is_admin=true`

**Validado por smoke test (curl):**
- POST/PATCH/toggle em todas as 4 entidades
- Slug duplicado → 409; tipo_acesso inválido → 400; app/role/usuário slug inexistente → 400
- Admin tenta desativar-se → 400; admin tenta tirar próprio admin bit → 400
- Operador não-admin em `/api/admin/*` → 403
- Reset de senha: login com senha velha 401, com senha nova 200

**Faltou validar visualmente** (precisa da Maria abrir no navegador):
- Render das 4 tabelas (apps, seções, roles, usuários)
- Modais de criar/editar para cada entidade
- Toggle ativo/inativo no UI
- Reset de senha pelo botão "Senha" na linha do usuário

---

## Lote 4 — CONCLUÍDO (Docker + entrega VM Windows)

**Entregue (2026-05-26):**
- `Dockerfile` (`python:3.12-slim`) — uvicorn em 0.0.0.0:8000, healthcheck `/api/health`, `SUPERFRIO_DB_PATH=/app/data/portal.db`
- `docker-compose.yml` — porta 8000, volume `./data:/app/data`, env `SUPERFRIO_JWT_SECRET` (default `dev-secret-change-me`)
- `.dockerignore` — exclui `.venv`, `.git`, `.claude`, `data/`, `*.db`, `MEMORY.md`, `*.md`, scripts `.ps1`
- `run.ps1` — dev local (cria `.venv`, instala deps, sobe uvicorn). Flags `-Port`, `-NoReload`
- `build.ps1` — `docker compose build` + `up -d`. Flags `-NoCache`, `-Down`, `-Reset` (apaga `.db`), `-Logs`

**Entregue (2026-05-29):**
- `README.md` — stack, modos de rodar (dev local + Docker), usuários seed, env vars, estrutura, endpoints, passos pra deploy em VM Windows
- Smoke test em container limpo validou:
  - Build da imagem do zero (sem cache base, baixou python:3.12-slim, instalou deps em 7.9s)
  - Container fica `healthy` (healthcheck do Dockerfile funciona)
  - `/api/health` → `{"status":"ok"}`
  - Login admin/admin123 → home com 7 apps em 2 seções
  - Login operador.armazem → só Armazém (3 apps)
  - Estáticos (`/`, `/js/admin.js`, `/img/superfrio-logo.jpg`) → 200
  - **Persistência**: usuário criado via `POST /api/admin/usuarios` sobrevive a `docker compose down` + `up`
  - **Seed idempotente**: `restart` em DB existente não duplica registros (mantém 2/7/3/3 em secoes/apps/roles/usuarios)
  - **Reset funciona**: `-Reset` apaga o `.db` do volume, próximo up re-seed do zero

**Falta (depende da Maria):**
- Validar em VM Windows alvo (Docker Desktop + WSL2)
- Trocar `SUPERFRIO_JWT_SECRET` antes do deploy real
- Liberar porta 8000 no firewall da VM se outros usuários da rede precisam acessar

---

## Lote 5 — CONCLUÍDO (i18n PT/ES + Identidade IceStar | SuperFrio)

Dois eixos entregues após a POC base: internacionalização e troca completa da identidade visual.

**i18n PT/ES (sem dependência, sem build):**
- `frontend/js/i18n.js` — **novo**. Dicionário `DICT` (pt/es) embutido, idioma em `localStorage` (`sf_lang`, default `pt`). Expõe `window.SF.i18n = { t, getLang, setLang, pick, applyStatic }`.
  - Estáticos traduzidos por atributo no HTML: `data-i18n` (texto), `data-i18n-ph` (placeholder), `data-i18n-title` (title).
  - Conteúdo dinâmico (apps/seções) usa `pick(rec, "nome")` → lê `nome_es`/`descricao_es` com **fallback para PT** se ES vazio.
  - Trocar idioma dispara evento `sf:langchange`; `app.js`/`admin.js` re-renderizam o conteúdo dinâmico.
  - Switch PT/ES (`.lang-switch button[data-lang]`) em 3 lugares: login, sidebar do portal, header do admin.
- **Schema** (`backend/database.py`): colunas `nome_es` e `descricao_es` em `secoes` e `apps`, via `_ensure_column` (ALTER idempotente, não quebra DB existente).
- `backend/seed.py` — popula ES nos 2 seções + 7 apps; backfill `UPDATE ... WHERE nome_es IS NULL` para linhas antigas (idempotente).
- `backend/routers/portal.py` — `/api/portal/home` devolve os campos `_es`.
- `backend/routers/admin.py` — modelos aceitam `nome_es`/`descricao_es`; UI do admin tem campos Nome (PT)/(ES) e Descrição (PT)/(ES).

**Identidade IceStar | SuperFrio — tema claro (substitui a paleta antiga):**
- `frontend/css/styles.css` — reescrito sob o **Manual de Marca BR v1.0 (Plataforma LATAM)**, tema claro ("Apresentação Clean"): fundos claros predominantes, azuis da marca como acento/estrutura, **amarelo `#FFC400` reservado a CTAs**.
  - Tipografia: **Montserrat** (era Nunito).
  - Azuis: institucional `#071A3A`, corporativo `#0A2A5E`, principal `#1E6FD9`, conexão `#3FA9F5`. Fundo `#EEF3FA`. Gradientes oficiais (`--grad-institucional`, `--grad-conexao`).
  - Motivos aprovados: onda (wave), glow, conexão. Único bloco institucional escuro = painel hero do login (momento de marca).
- Logos novos em `frontend/img/`: `icestar-superfrio-logo.png` (sidebar/admin), `icestar-superfrio-logo-white.png` (login hero), `favicon.png`. O antigo `superfrio-logo.jpg` segue no repo mas não é mais usado.
- Skill `superfrio` (identidade visual) é a fonte dos tokens — aplicar ao mexer em qualquer coisa visual.

**Decisão travada:** tema **claro** é o padrão dos apps internos. Fundo azul-escuro como fundo primário foi rejeitado ("feio").

---

## Auditoria de Segurança — CONCLUÍDA (2026-05-29)

Auditoria completa documentada em [AUDITORIA_SEGURANCA.md](docs/AUDITORIA_SEGURANCA.md). Modelo de ameaça: atacante já dentro da rede interna. **3 críticos + 4 altos + 4 médios resolvidos e validados por smoke test**; 2 baixos deferidos com justificativa.

**Correções que mudaram o código (não esquecer ao retomar):**
- `backend/limiter.py` — **novo**: instância única do `Limiter` (slowapi). Login limitado a `5/minute` por IP (429 na 6ª).
- `backend/auth.py` — `JWT_EXP_HOURS` 8→**3h**; em `SUPERFRIO_ENV=prod` o startup **falha** se o secret continuar no default; payload do JWT carrega `tv` (token_version).
- `backend/database.py` — coluna `token_version` em `usuarios` (ALTER idempotente). Reset de senha incrementa `tv` → invalida todos os tokens em circulação. `UPDATE usuarios SET token_version = token_version + 1` = logout global.
- `backend/main.py` — **CORS aberto removido** (front e back mesma origem); middleware de **security headers + CSP** (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP restritiva).
- `backend/routers/admin.py` — `_check_url()` rejeita URL fora de `http/https` (400); `PASSWORD_MIN_LEN=8`; `except sqlite3.IntegrityError` específico (era `except Exception`).
- `frontend/index.html` — `.login-hint` (credenciais seed expostas) **removido**; sandbox do iframe **sem** `allow-same-origin` (apps que dependiam de cookie do portal devem usar `tipo_acesso=url`).
- Docker: container roda como **uid 1000** (não-root) via `entrypoint.sh` (**novo**) + `gosu`; `requirements.txt` ganhou `slowapi==0.1.9`.

**Deferidos (baixos):** B1 — **HTTPS é BLOQUEANTE para prod** (decisão de deploy, não de código: TLS + proxy + firewall 443/bloqueia 8000). B2 — SQL dinâmico nos PATCH sem vetor real hoje (chaves vêm de modelo Pydantic fechado; documentado).

**Pendência operacional pré-deploy:** trocar senha do `admin`, gerar `SUPERFRIO_JWT_SECRET` (64 hex), `SUPERFRIO_ENV=prod`, HTTPS, firewall, backup do `data/portal.db`.

---

## Migração Plataforma — Lote 1 CONCLUÍDO (2026-07-02): SQLAlchemy + Alembic

Primeiro lote do [PLANO_MIGRACAO_PLATAFORMA.md](docs/PLANO_MIGRACAO_PLATAFORMA.md): os ~74 pontos
de `sqlite3` na mão viraram SQLAlchemy, e o schema passou a ser versionado por Alembic. **O banco
continua SQLite** — trocar de banco (Lote 2) é só a `DATABASE_URL`. Comportamento externo idêntico
(mesmos endpoints, mesmas respostas, mesmos erros).

**O que mudou:**
- `backend/database.py` — engine + `SessionLocal` + models ORM das 6 tabelas (`Usuario`, `Secao`,
  `App`, `Role` + Tables `role_apps`/`usuario_roles`). `db()` agora rende uma Session (commit no
  sucesso, rollback em erro — mesma semântica de antes). `DATABASE_URL` (env) com default
  `sqlite:///<SUPERFRIO_DB_PATH>`. `ativo`/`is_admin` seguem **Integer 0/1** (respostas JSON
  idênticas). `init_db()` = `alembic upgrade head` programático; **banco legado (sem
  `alembic_version`) recebe `stamp` da baseline `0001`** — deploy em prod não precisa de comando
  manual. `_now()` gera timestamp UTC no formato do `datetime('now')` (portável pro Postgres).
- `backend/migrations/` — env.py (URL: attributes → ini → DATABASE_URL; `render_as_batch` p/
  SQLite) + baseline `0001_schema_inicial.py` (schema completo, equivalente ao init_db antigo).
  `alembic.ini` na raiz só pra CLI (`alembic revision --autogenerate` etc.); runtime não lê ele.
- `backend/auth.py`, `seed.py`, `routers/portal.py`, `routers/admin.py` — queries reescritas em
  SQLAlchemy (expression language + mappings). Seed trocou `INSERT OR IGNORE` (dialeto SQLite)
  por check-then-insert portável. `_unique_or_409` captura `sqlalchemy.exc.IntegrityError`
  (mensagens SQLite **e** Postgres).
- Testes — mesma cobertura/semântica, SQL cru dos fixtures via `text()`. `test_infra.py` trocou
  os testes de `_ensure_column` (aposentado) por: init_db idempotente + schema completo, e
  **banco legado recebe stamp sem perder dados** (cenário do cutover em prod).
- `requirements.txt` — `+ sqlalchemy==2.0.51`, `+ alembic==1.18.5`. `Dockerfile` — `COPY alembic.ini`.

**Validado:** suíte pytest (56 testes) verde; smoke com uvicorn real em banco **novo** (health,
login admin/operador, home filtrada, CRUD, 409, reset de senha invalidando token) e em banco
**legado pré-Alembic** (stamp `0001`, seed completa o que falta, usuário legado preserva login).
Build Docker não foi validado local (sem Docker nesta máquina) — validar na VM.

**Deploy (playbook do plano):** `git pull` + `docker compose up -d --build`. Nada manual de
migration — o startup carimba/aplica sozinho. Rollback = voltar o commit e rebuild (schema não mudou).

---

## Migração Plataforma — Lote 2 CONCLUÍDO (2026-07-02): Postgres no compose

Feito em outro chat; commitado aqui (`164a88b`). Service `db` (postgres:16-alpine) no
`docker-compose.yml`, **sem porta publicada** (só rede interna do compose), healthcheck +
`depends_on: service_healthy`. `DATABASE_URL` com **fallback pro SQLite** do volume `./data` —
rollback = comentar a linha no `.env`. Seed standalone (`python -m backend.seed`) pro banco novo.
`+psycopg[binary]==3.2.13`; `.env.example` documenta as variáveis. Código de acesso a dados não
mudou (graças ao Lote 1). **Deploy na VM ainda pendente** (subir compose com `.env` de prod).

---

## Migração Plataforma — Lote 3 CONCLUÍDO (2026-07-02): Modularização

O backend virou **Modular Monolith de verdade**: pacotes `core/`, `auth/`, `usuarios/` e
`portal/`, cada um dono dos próprios models/service/router/seed. **Zero mudança de comportamento**
(mesmos endpoints/respostas/erros — suíte e smoke idênticos aos dos lotes anteriores).

**Estrutura e donos:**
- `core/` — infra sem domínio: `database.py` (engine/Session/Base/init_db), `http.py` (helpers
  genéricos: `row_or_404`, `unique_or_409`, `ensure_slug`, `apply_update`, `ids_por_slug_or_400`
  — recebem o model do chamador), `limiter.py`, `migrations/` (chain Alembic única e central).
- `auth/` — sem tabela própria: `service.py` (bcrypt/JWT/`authenticate_user`),
  `dependencies.py` (`get_current_user`/`require_admin`), `router.py` (login/me). Consulta
  usuário via `usuarios.service`.
- `usuarios/` — dono de `usuarios`, `roles`, `usuario_roles`, `role_apps` (o grant role→app é do
  domínio de permissões). `service.py`: `por_username`, `app_ids_permitidos`.
- `portal/` — dono de `secoes` e `apps`. `service.py`: `apps_ativos_com_secao`,
  `app_ids_por_slug`, `slugs_por_app_ids`.

**Regra de ouro aplicada** (documentada em `backend/__init__.py`): módulo nunca lê tabela de
outro — a home do portal pede os app_ids permitidos ao `usuarios.service`; roles resolvem slugs
de apps via `portal.service`. Routers orquestram services de vários módulos. A fronteira é
lógica — cobrar em code review.

**Decisões práticas do lote:**
- Migrations **continuam centrais** em `core/migrations` (chain única) em vez de por módulo —
  simplicidade > pureza; módulo novo só importa seu `models.py` no `env.py`.
- URLs dos endpoints **não mudaram** (`/api/admin/...` continua valendo pro frontend inteiro).
- Seed: `backend/seed.py` virou orquestrador (portal → usuarios, mesma transação);
  `python -m backend.seed` do Lote 2 continua funcionando.
- Frontend intocado.

**Módulo novo (ex.: auditoria de cliques, IA, inventário):** criar pacote com
`models.py`/`service.py`/`router.py`, importar models no `env.py` das migrations, incluir router
no `main.py`, migration Alembic pro schema. Nasce dentro da plataforma — custo de integração zero.

---

## Documentos de apoio (em docs/, fora do git)

- [AUDITORIA_SEGURANCA.md](docs/AUDITORIA_SEGURANCA.md) — auditoria completa (achados, correções, smoke test).
- [ROADMAP_EVOLUCAO.md](docs/ROADMAP_EVOLUCAO.md) — 5 degraus pós-POC (esforço × valor). Ordem prática: 1 (URLs bonitas/proxy) → 2 (auditoria de cliques) sem depender de TI; 3 (SSO Entra) em paralelo com a Infra; 4 (SQL Server) sob demanda; 5 (HA) só se um app virar crítico.
- [GUIA_PUBLICACAO_REDE.md](docs/GUIA_PUBLICACAO_REDE.md) — receita de publicação na rede + proxy reverso (Caddy) pronta pra colar.
- [GUIA_NOVO_USUARIO_VM.md](docs/GUIA_NOVO_USUARIO_VM.md) — runbook pra dar acesso de git/deploy na VM a uma pessoa nova (chave SSH, grupos `docker`/`devs`, deploy key do repo, `core.sharedRepository`). Escrito depois do onboarding real do Gabriel (2026-07-07).
- [GUIA_SEGURANCA_APPS_EMBUTIDOS.md](docs/GUIA_SEGURANCA_APPS_EMBUTIDOS.md) — guia de estudo: CSP (todas as diretivas explicadas), sandbox de iframe, o trade-off do `allow-same-origin`, tabela de headers por rota pós 2026-07-07.
- [TROUBLESHOOTING_APPS_IFRAME.md](docs/TROUBLESHOOTING_APPS_IFRAME.md) — os 4 problemas reais resolvidos na integração do app Mapa de Estoque (URL relativa, frame-ancestors, sandbox origem opaca, worker-src blob), com sintoma/causa/fix/PR de cada um.
- [HUB_VS_PADROES_INDUSTRIA.md](docs/HUB_VS_PADROES_INDUSTRIA.md) — comparativo do Hub frente às práticas de grandes empresas.
- [ARQUITETURA_PLATAFORMA.md](docs/ARQUITETURA_PLATAFORMA.md) — decisão (2026-06-26) de virar plataforma centralizadora: modelo Self-Contained Systems + identidade central, como os sisteminhas compartilham dados, com referências da indústria.
- [PLANO_MIGRACAO_PLATAFORMA.md](docs/PLANO_MIGRACAO_PLATAFORMA.md) — o *como* da migração pro Modular Monolith, em lotes (1 SQLAlchemy+Alembic → 2 Postgres → 3 modularização → 4 absorver Contas), com playbook de deploy e quando usar Fable × Opus.
- [APOSTILA_ARQUITETURA.html](docs/APOSTILA_ARQUITETURA.html) — apostila de estudo da Maria (2026-07-02): arquitetura pós-Lotes 1–3 explicada do zero, APIs, critérios plataforma × base própria, GitHub/CI/CODEOWNERS, método de trabalho, glossário e trilha de estudo. Versão mapa mental em `docs/obsidian/Arquitetura Plataforma/` (+ zip).
- [README.md](README.md) — stack, modos de rodar, usuários seed, env vars, deploy.

---

## Fora de escopo (confirmado)

- **Absorver o Contas Recorrentes como módulo (era o Lote 4 do plano de migração) — CANCELADO em 2026-07-02 por decisão da Maria.** O Contas segue como app separado, com banco e auth próprios. Se a decisão mudar, o plano do lote está no PLANO_MIGRACAO_PLATAFORMA.md (e o contas.db foi declarado re-seedável, o que simplificaria).
- LDAP/AD real — só o stub fica pronto (`authenticate_user` com branch por `auth_source`). **Virou Degrau 3 (SSO Entra) no ROADMAP_EVOLUCAO.md.**
- Auditoria de cliques (quem abriu qual app quando). **Virou Degrau 2 no ROADMAP — é o próximo lote candidato (alto valor, não depende de TI).**
- Multi-tenant, dashboard de uso
- ~~Reset de senha~~ — **na verdade FOI implementado no Lote 3** (`POST /api/admin/usuarios/{id}/password`, com incremento de `token_version`).
- HTTPS no portal — **reclassificado:** deferido como **BLOQUEANTE para prod** na auditoria (B1). HTTP só serve pra ambiente de teste.

---

## Estrutura atual do projeto

```
SuperfrioIA/
├── backend/               # Modular Monolith — regra de ouro em backend/__init__.py
│   ├── __init__.py        # docstring com o mapa dos módulos + regra de ouro
│   ├── main.py            # FastAPI + security headers/CSP + monta routers dos módulos
│   ├── seed.py            # orquestrador do seed (portal → usuarios); python -m backend.seed
│   ├── core/              # infra: database.py, http.py, limiter.py, migrations/ (Alembic)
│   ├── auth/              # service.py (bcrypt/JWT/boundary AD), dependencies.py, router.py
│   ├── usuarios/          # models (Usuario/Role/vínculos), service, seed, router (/api/admin)
│   └── portal/            # models (Secao/App), service, seed, router (/api/portal + /api/admin)
├── data/                  # gitignored, contém portal.db em runtime
├── frontend/
│   ├── index.html         # login + portal + admin (single page), atributos data-i18n
│   ├── css/styles.css     # identidade IceStar | SuperFrio (Montserrat, tema claro)
│   ├── js/
│   │   ├── app.js         # login, portal, helpers compartilhados (window.SF)
│   │   ├── admin.js       # tela admin (CRUD apps/secoes/roles/usuarios)
│   │   └── i18n.js        # i18n PT/ES (window.SF.i18n), sem dependência
│   └── img/               # icestar-superfrio-logo.png, *-white.png, favicon.png (+ superfrio-logo.jpg legado)
├── alembic.ini            # config Alembic pra CLI (runtime não depende dele)
├── Dockerfile             # python:3.12-slim, user uid 1000, entrypoint
├── entrypoint.sh          # chown do volume + gosu app (drop de root)
├── docker-compose.yml     # porta 8000, volume data, SUPERFRIO_ENV/JWT_SECRET
├── .dockerignore
├── run.ps1                # dev local (venv + uvicorn)
├── build.ps1              # docker compose build/up; flags -NoCache/-Down/-Reset/-Logs
├── requirements.txt       # inclui slowapi==0.1.9
├── .gitignore
├── README.md              # versionado — porta de entrada do repo
├── MEMORY.md              # este arquivo — versionado (doc autoritativo de retomada)
└── docs/                  # gitignored — documentação interna (não vai pro GitHub)
    ├── AUDITORIA_SEGURANCA.md
    ├── ROADMAP_EVOLUCAO.md
    ├── GUIA_PUBLICACAO_REDE.md
    └── HUB_VS_PADROES_INDUSTRIA.md
```

---

## Como rodar localmente

```powershell
# venv + deps (primeira vez)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# subir o servidor
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

Acesso: http://127.0.0.1:8000

---

## Usuários de teste (seed)

| Usuário | Senha | Tipo | Vê |
|---|---|---|---|
| `admin` | `admin123` | admin | tudo |
| `operador.armazem` | `armazem123` | role `armazem-full` | só Armazém |
| `analista.bo` | `backoffice123` | roles `backoffice-full` + `faq-leitor` | Backoffice + FAQs |

---

## Apps no seed

**Armazém:** FAQ BlueYonder, FAQ Slin, Conciliação de Estoque (NEW)
**Backoffice:** Dúvidas Financeiro, Compras 2.0 (BETA), ConciliaFAT, Controle de Recebimento

---

## Para retomar em outro chat

Cole o seguinte na primeira mensagem:

> Estou retomando a POC do **Hub SuperFrio & Icestar** (plataforma centralizadora de apps internos da SuperFrio e Icestar). Leia o `MEMORY.md` no diretório raiz pra entender o contexto. Lotes 1 (backend + auth), 2 (frontend), 3 (admin CRUD), 4 (Docker + smoke test) e 5 (i18n PT/ES + identidade IceStar | SuperFrio) estão concluídos, mais a auditoria de segurança (`AUDITORIA_SEGURANCA.md`). Da migração pra Modular Monolith (`docs/PLANO_MIGRACAO_PLATAFORMA.md`), os Lotes 1 (SQLAlchemy + Alembic), 2 (Postgres no compose) e 3 (modularização core/auth/usuarios/portal) estão concluídos; o Lote 4 (absorver Contas Recorrentes) foi cancelado. Falta o deploy dos lotes na VM. Ative o modo SuperFrio (`/superfrio`) antes.

Stack: FastAPI + SQLite (WAL) + HTML/CSS/JS vanilla (sem build) + Docker. Ambiente: Windows + PowerShell.
