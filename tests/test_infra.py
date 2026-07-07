"""Infra: idempotência do seed, migrations Alembic e headers de segurança.

Cobre comportamentos que blindam deploy/retomada:
- seed roda 2x sem duplicar e sem sobrescrever edição do admin (backfill ES);
- init_db (alembic upgrade head) é idempotente e o schema fica completo;
- banco legado (pré-Alembic) recebe stamp da baseline sem recriar/perder nada;
- middleware injeta os headers de segurança + CSP em toda resposta.
Cada teste restaura o que mexe; o de banco legado usa arquivo próprio.
"""
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import inspect, text

from backend.core.database import BASELINE_REVISION, db, engine, init_db
from backend.seed import seed_initial


# ============ Idempotência do seed ============

def _counts():
    tabelas = ["secoes", "apps", "roles", "usuarios", "role_apps", "usuario_roles"]
    with db() as conn:
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in tabelas}


def test_seed_idempotente():
    antes = _counts()
    seed_initial()  # insere só o que falta → não pode duplicar
    assert _counts() == antes


def test_seed_backfill_es_preenche_nulo():
    with db() as conn:
        conn.execute(text("UPDATE secoes SET nome_es = NULL WHERE slug = 'armazem'"))
    seed_initial()
    with db() as conn:
        val = conn.execute(text("SELECT nome_es FROM secoes WHERE slug = 'armazem'")).scalar_one()
    assert val == "Almacén"


def test_seed_backfill_es_nao_sobrescreve_edicao():
    with db() as conn:
        conn.execute(text("UPDATE secoes SET nome_es = 'EDITADO' WHERE slug = 'armazem'"))
    try:
        seed_initial()
        with db() as conn:
            val = conn.execute(text("SELECT nome_es FROM secoes WHERE slug = 'armazem'")).scalar_one()
        assert val == "EDITADO"  # backfill só toca quando nome_es IS NULL
    finally:
        with db() as conn:
            conn.execute(text("UPDATE secoes SET nome_es = 'Almacén' WHERE slug = 'armazem'"))


# ============ Migrations (Alembic) ============

def test_init_db_idempotente_e_schema_completo():
    init_db()  # roda de novo (já rodou no setup da sessão) — não pode estourar
    insp = inspect(engine)
    assert insp.has_table("alembic_version")
    usuarios = {c["name"] for c in insp.get_columns("usuarios")}
    secoes = {c["name"] for c in insp.get_columns("secoes")}
    apps = {c["name"] for c in insp.get_columns("apps")}
    assert "token_version" in usuarios
    assert {"nome_es", "descricao_es"} <= secoes
    assert {"nome_es", "descricao_es"} <= apps


# Schema como o init_db ANTIGO (pré-Alembic) deixava: CREATE TABLE originais
# + colunas adicionadas por _ensure_column (token_version, nome_es, descricao_es).
_DDL_LEGADO = [
    """CREATE TABLE usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        nome TEXT, email TEXT, password_hash TEXT,
        auth_source TEXT NOT NULL DEFAULT 'local',
        ativo INTEGER NOT NULL DEFAULT 1,
        is_admin INTEGER NOT NULL DEFAULT 0,
        token_version INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')),
        atualizado_em TEXT
    )""",
    """CREATE TABLE secoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE, nome TEXT NOT NULL,
        descricao TEXT, icone TEXT,
        ordem INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1,
        nome_es TEXT, descricao_es TEXT
    )""",
    """CREATE TABLE apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE, nome TEXT NOT NULL,
        descricao TEXT, icone TEXT,
        secao_id INTEGER NOT NULL REFERENCES secoes(id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        tipo_acesso TEXT NOT NULL DEFAULT 'url',
        badge TEXT,
        ordem INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')),
        atualizado_em TEXT,
        nome_es TEXT, descricao_es TEXT
    )""",
    """CREATE TABLE roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE, nome TEXT NOT NULL,
        descricao TEXT,
        ativo INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE role_apps (
        role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        PRIMARY KEY (role_id, app_id)
    )""",
    """CREATE TABLE usuario_roles (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, role_id)
    )""",
    "CREATE INDEX idx_apps_secao ON apps(secao_id)",
    "CREATE INDEX idx_apps_ativo ON apps(ativo)",
    "CREATE INDEX idx_secoes_ativo ON secoes(ativo)",
]


def test_banco_legado_recebe_stamp_sem_perder_dados():
    """Cenário do deploy do Lote 1: o portal.db de prod foi criado pelo código
    pré-Alembic. init_db deve carimbar (stamp) a baseline e seguir — sem tentar
    recriar tabela e sem tocar nos dados."""
    tmp = Path(tempfile.mkdtemp(prefix="superfrio_legacy_")) / "legado.db"
    conn = sqlite3.connect(tmp)
    for stmt in _DDL_LEGADO:
        conn.execute(stmt)
    conn.execute("INSERT INTO usuarios (username, password_hash) VALUES ('marcador', 'x')")
    conn.commit()
    conn.close()

    init_db(url=f"sqlite:///{tmp.as_posix()}")  # não pode estourar em CREATE TABLE

    conn = sqlite3.connect(tmp)
    try:
        ver = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert ver == BASELINE_REVISION
        sobrevive = conn.execute(
            "SELECT COUNT(*) FROM usuarios WHERE username = 'marcador'"
        ).fetchone()[0]
        assert sobrevive == 1
    finally:
        conn.close()


# ============ Headers de segurança / CSP ============

def test_security_headers_presentes(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_csp_restritiva(client):
    csp = client.get("/api/health").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


def test_raiz_nao_pode_ser_embutida(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_estatico_embutido_permite_self(client):
    r = client.get("/css/styles.css")
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    csp = r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in csp
    assert "script-src 'self'" in csp  # não afrouxa unsafe-inline, só frame-ancestors
