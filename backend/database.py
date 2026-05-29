import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("SUPERFRIO_DB_PATH", "data/portal.db"))


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        nome TEXT,
        email TEXT,
        password_hash TEXT,
        auth_source TEXT NOT NULL DEFAULT 'local',
        ativo INTEGER NOT NULL DEFAULT 1,
        is_admin INTEGER NOT NULL DEFAULT 0,
        token_version INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')),
        atualizado_em TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS secoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        descricao TEXT,
        icone TEXT,
        ordem INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        descricao TEXT,
        icone TEXT,
        secao_id INTEGER NOT NULL REFERENCES secoes(id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        tipo_acesso TEXT NOT NULL DEFAULT 'url',
        badge TEXT,
        ordem INTEGER NOT NULL DEFAULT 0,
        ativo INTEGER NOT NULL DEFAULT 1,
        criado_em TEXT NOT NULL DEFAULT (datetime('now')),
        atualizado_em TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        descricao TEXT,
        ativo INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_apps (
        role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        app_id INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
        PRIMARY KEY (role_id, app_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usuario_roles (
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        PRIMARY KEY (usuario_id, role_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_apps_secao ON apps(secao_id)",
    "CREATE INDEX IF NOT EXISTS idx_apps_ativo ON apps(ativo)",
    "CREATE INDEX IF NOT EXISTS idx_secoes_ativo ON secoes(ativo)",
]


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    conn = get_conn()
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for stmt in SCHEMA:
            conn.execute(stmt)
        _ensure_column(conn, "usuarios", "token_version", "token_version INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    finally:
        conn.close()
