# MEMORY — Portal SuperFrio (POC)

Documento de transferência para retomar este projeto em outro chat.

---

## Contexto

POC de **plataforma centralizadora dos apps internos da SuperFrio** ("sisteminhas" feitos no vibe code do CSC). O portal lista cards de cada app por seção (Armazém, Backoffice…) e leva o usuário ao app correspondente. Objetivo final: empacotar com Docker + Git, publicar em VM Windows com Docker, mostrar arquitetura de governança ao time.

Não é só um portal — é a vitrine da governança: cadastro de apps, permissionamento, versionamento, deploy reprodutível.

---

## Decisões travadas

- **Stack**: FastAPI + SQLite (single-file, WAL) + HTML único + Tailwind via CDN. Sem build step. Padrão SuperFrio.
- **Auth**: JWT + bcrypt. Função `authenticate_user()` é o único boundary — hoje valida local, amanhã faz LDAP bind (campo `auth_source` já no schema).
- **Permissionamento**: por app individual + roles. Roles agrupam apps; usuários recebem N roles. Admin (`is_admin=1`) bypassa tudo.
- **Linkagem dos apps**: campo `tipo_acesso` no cadastro (`url` ou `iframe`). Default `url`. Maria decide por app no Lote 3.
- **Cadastro de apps**: seed inicial + CRUD admin pela UI (Lote 3). Demonstra governança ao vivo.
- **Renomeação de campos do Protheus**: nunca. Etapas internas podem ser renomeadas.
- **Migrations**: ALTER TABLE no startup, idempotente (`INSERT OR IGNORE` no seed).

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

Frontend único HTML+CSS+JS vanilla, sem Tailwind/build step. Paleta herdada do app irmão Contas Recorrentes (Nunito, --sf-dark `#295494`, --sf-light `#29abe2`).

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

## Fora de escopo (confirmado)

- LDAP/AD real — só o stub fica pronto (`authenticate_user` com branch por `auth_source`)
- Auditoria de cliques (quem abriu qual app quando) — próxima POC
- Reset de senha, multi-tenant, dashboard de uso
- HTTPS no portal — VM interna, HTTP basta pra POC

---

## Estrutura atual do projeto

```
SuperfrioIA/
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── auth.py
│   ├── seed.py
│   └── routers/
│       ├── __init__.py
│       ├── auth.py
│       ├── portal.py
│       └── admin.py
├── data/                  # gitignored, contém portal.db em runtime
├── frontend/
│   ├── index.html         # login + portal + admin (single page)
│   ├── css/styles.css
│   ├── js/
│   │   ├── app.js         # login, portal, helpers compartilhados (window.SF)
│   │   └── admin.js       # tela admin (CRUD apps/secoes/roles/usuarios)
│   └── img/superfrio-logo.jpg
├── .venv/                 # gitignored
├── requirements.txt
├── .gitignore
└── MEMORY.md              # este arquivo
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

> Estou retomando a POC do **Portal SuperFrio** (plataforma centralizadora de apps internos da SuperFrio e Icestar). Leia o `MEMORY.md` no diretório raiz pra entender o contexto. Lotes 1 (backend + auth), 2 (frontend), 3 (admin CRUD) e 4 (Docker + smoke test) estão concluídos. Resta validar o deploy real em VM Windows (firewall, JWT_SECRET de produção, etc). Ative o modo SuperFrio (`/superfrio`) antes.

Stack: FastAPI + SQLite + Tailwind CDN + Docker. Ambiente: Windows + PowerShell.
