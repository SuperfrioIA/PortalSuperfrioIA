"""Acesso a dados via SQLAlchemy + migrations Alembic.

O schema é versionado em backend/core/migrations (fonte da verdade). Os models
ficam em cada módulo de domínio (`portal/models.py`, `usuarios/models.py`),
todos pendurados no `Base` daqui. Trocar de banco é só a DATABASE_URL
(SQLite ↔ Postgres desde o Lote 2).
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(os.environ.get("SUPERFRIO_DB_PATH", "data/portal.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Revisão que representa o schema que o init_db antigo criava. Banco legado
# (tabelas existentes, sem alembic_version) é carimbado aqui — nunca em head,
# senão migrations futuras seriam puladas.
BASELINE_REVISION = "0001"


def _make_engine(url: str) -> Engine:
    kwargs = {}
    if url.startswith("sqlite"):
        # conexões cruzam threads (threadpool do FastAPI), como no sqlite3 antigo
        kwargs["connect_args"] = {"check_same_thread": False}
        db_file = url.removeprefix("sqlite:///")
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, **kwargs)
    if eng.dialect.name == "sqlite":
        @event.listens_for(eng, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute("PRAGMA journal_mode = WAL")
            cur.close()
    return eng


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _now() -> str:
    """Timestamp UTC no mesmo formato do datetime('now') do SQLite."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def db():
    """Sessão com commit no fim (em sucesso), rollback em erro e close garantido."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Base(DeclarativeBase):
    pass


def _alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["sqlalchemy_url"] = url
    return cfg


def init_db(url: str | None = None) -> None:
    """Aplica as migrations Alembic até head (idempotente).

    Banco legado — criado pelo init_db antigo, com schema completo mas sem
    alembic_version — é carimbado na baseline e segue para o upgrade normal.
    """
    target = url or DATABASE_URL
    eng = engine if target == DATABASE_URL else _make_engine(target)
    try:
        cfg = _alembic_config(target)
        insp = inspect(eng)
        if insp.has_table("usuarios") and not insp.has_table("alembic_version"):
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")
    finally:
        if eng is not engine:
            eng.dispose()
