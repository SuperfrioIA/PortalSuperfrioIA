# Hub SuperFrio & Icestar

Plataforma centralizadora dos apps internos da SuperFrio e Icestar. POC do CSC: vitrine de governança (cadastro de apps, permissionamento, deploy reprodutível).

## Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite (single-file, WAL) + bcrypt + JWT; migrations com Alembic
- **Frontend:** HTML único + JS vanilla + CSS (Montserrat via Google Fonts), sem build step
- **Deploy:** Docker (Linux container), volume persistente para o `.db`

## Como rodar

### Modo 1 — Dev local (sem Docker)

```powershell
.\run.ps1                 # cria .venv, instala deps, sobe uvicorn em :8000
.\run.ps1 -Port 8080      # outra porta
.\run.ps1 -NoReload       # sem auto-reload (mais próximo de prod)
```

Acesse http://127.0.0.1:8000

### Modo 2 — Docker (produção / VM)

```powershell
# Antes do primeiro build, defina o segredo do JWT:
$env:SUPERFRIO_JWT_SECRET = 'gere-uma-chave-forte-aqui'

.\build.ps1               # build + up -d
.\build.ps1 -Logs         # acompanha os logs do container
.\build.ps1 -Down         # para o container
.\build.ps1 -Reset        # apaga o .db (seed roda do zero no próximo up)
.\build.ps1 -NoCache      # rebuild forçando sem cache
```

O `docker-compose.yml` monta `./data:/app/data` — o `.db` sobrevive entre restarts e rebuilds. Para descartar o estado, use `-Reset`.

## Usuários de teste (seed inicial)

| Usuário | Senha | Tipo | Vê |
|---|---|---|---|
| `admin` | `admin123` | admin | tudo + governança |
| `operador.armazem` | `armazem123` | role `armazem-full` | só Armazém |
| `analista.bo` | `backoffice123` | roles `backoffice-full` + `faq-leitor` | Backoffice + FAQs |

Troque/desative essas senhas pela tela **Administração** assim que entrar em produção.

## Variáveis de ambiente

| Variável | Default | Descrição |
|---|---|---|
| `SUPERFRIO_JWT_SECRET` | `dev-secret-change-me` | Segredo HS256 dos tokens. **Trocar em produção.** |
| `SUPERFRIO_DB_PATH` | `data/portal.db` (local) / `/app/data/portal.db` (container) | Caminho do SQLite |
| `DATABASE_URL` | `sqlite:///<SUPERFRIO_DB_PATH>` | Connection string SQLAlchemy. Definir só quando sair do SQLite (ex.: Postgres no Lote 2) |
| `SUPERFRIO_ENV` | `dev` | Em `prod`, o startup falha se o `JWT_SECRET` continuar no default |
| `SUPERFRIO_FRAME_SRC` | `'self' https:` | Origens permitidas em `<iframe>` (CSP). Restrinja às URLs reais dos apps em produção |
| `HOST_PORT` | `8000` | Porta publicada na VM (host). Use outra se a 8000 estiver ocupada (ex.: `8001`) |

## Estrutura

```
backend/                # FastAPI app — Modular Monolith (um app, um processo, um banco)
  main.py               # entrypoint, lifespan (init_db + seed), monta routers + estáticos
  seed.py               # orquestra o seed dos módulos (python -m backend.seed)
  core/                 # infra compartilhada (sem regra de negócio)
    database.py         # engine/Session SQLAlchemy, Base, init_db (alembic upgrade head)
    http.py             # helpers HTTP genéricos (404 por id, 409 de UNIQUE, slug, PATCH parcial)
    limiter.py          # rate limit do login (slowapi)
    migrations/         # Alembic (env.py + versions/) — fonte da verdade do schema
  auth/                 # senhas/JWT + boundary de autenticação (futuro SSO Entra)
    service.py          # bcrypt, JWT, authenticate_user
    dependencies.py     # get_current_user, require_admin (usados por todos os routers)
    router.py           # /api/auth/login, /api/auth/me
  usuarios/             # contas, roles e vínculos de permissão
    models.py           # Usuario, Role, usuario_roles, role_apps
    service.py          # por_username, app_ids_permitidos (interface p/ outros módulos)
    router.py           # /api/admin/roles*, /api/admin/usuarios*
  portal/               # catálogo de seções/apps + home
    models.py           # Secao, App
    service.py          # apps_ativos_com_secao, app_ids_por_slug (interface p/ outros módulos)
    router.py           # /api/portal/home, /api/admin/secoes*, /api/admin/apps*
frontend/               # HTML único + CSS + JS vanilla
  index.html            # login + portal + admin (toggle via classe .hidden)
  css/styles.css        # identidade IceStar | SuperFrio (Montserrat, tema claro)
  js/
    app.js              # login, portal, helpers (window.SF)
    admin.js            # tela admin (tabs + tabelas + modais)
    i18n.js             # i18n PT/ES (window.SF.i18n), sem dependência
  img/                  # logos IceStar | SuperFrio + favicon
data/                   # gitignored, contém portal.db em runtime
alembic.ini             # config do Alembic pra uso via CLI (runtime não depende dele)
Dockerfile              # python:3.12-slim + uvicorn em 0.0.0.0:8000
docker-compose.yml      # porta 8000 + volume data + env
run.ps1                 # dev local
build.ps1               # docker build/up/down/reset/logs
```

## Endpoints principais

- `POST /api/auth/login` — form `username` + `password` → JWT
- `GET  /api/auth/me` — payload do token atual
- `GET  /api/portal/home` — seções + apps liberados para o usuário
- `GET  /api/admin/{secoes|apps|roles|usuarios}` — listas administrativas
- `POST /api/admin/{entidade}` — criar
- `PATCH /api/admin/{entidade}/{id}` — atualizar (parcial)
- `POST /api/admin/{entidade}/{id}/toggle` — ativar/desativar
- `POST /api/admin/usuarios/{id}/password` — reset de senha
- `GET  /api/health` — healthcheck do container

Documentação interativa (Swagger): http://127.0.0.1:8000/docs

## Deploy em VM Windows

1. Instale Docker Desktop com WSL2 na VM
2. Clone o repositório
3. `$env:SUPERFRIO_JWT_SECRET = 'chave-forte'`
4. `.\build.ps1`
5. Libere a porta 8000 no firewall da VM se outros usuários da rede precisam acessar
6. Acesse `http://<ip-da-vm>:8000` da rede interna

Para mudar a porta no host, defina `HOST_PORT` no `.env` (ex.: `HOST_PORT=8001`) — sem editar arquivos versionados. O default é 8000.

## Princípios da POC

- **Toggle ativo/inativo** em vez de DELETE — auditável
- **Slug é stable** — nunca editado depois de criado, mantém rastreabilidade
- **Trace Protheus sagrado** — campos do ERP nunca são renomeados (não aplicável a esta POC, mas é regra da casa)
- **Idempotência** — seed e init_db podem rodar 2x sem corromper estado
- **Schema versionado** — migrations Alembic aplicadas no startup; banco pré-Alembic é carimbado (stamp) automaticamente, sem migração manual
- **Modular Monolith** — módulos (`core`/`auth`/`usuarios`/`portal`) com fronteira lógica: um módulo nunca lê a tabela de outro, só chama o `service.py` do dono. Módulo novo nasce como pacote próprio e registra os models no `env.py` das migrations
- **HTML único + JS vanilla** — sem build step, fácil de manter pelo time CSC
