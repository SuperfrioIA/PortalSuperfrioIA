"""Acesso a dados via SQLAlchemy + migrations Alembic.

O schema é versionado em backend/migrations (fonte da verdade); o init_db()
antigo (CREATE TABLE + _ensure_column na mão) foi aposentado no Lote 1 da
migração pra Modular Monolith. O banco continua SQLite — trocar de banco é
só a DATABASE_URL (Lote 2: Postgres).
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, ForeignKey, Index, Integer, Table, Text, create_engine, event, inspect
from sqlalchemy import text as sa_text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

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


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="local", server_default=sa_text("'local'")
    )
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    is_admin: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    atualizado_em: Mapped[str | None] = mapped_column(Text)


class Secao(Base):
    __tablename__ = "secoes"
    __table_args__ = (
        Index("idx_secoes_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    icone: Mapped[str | None] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    nome_es: Mapped[str | None] = mapped_column(Text)
    descricao_es: Mapped[str | None] = mapped_column(Text)


class App(Base):
    __tablename__ = "apps"
    __table_args__ = (
        Index("idx_apps_secao", "secao_id"),
        Index("idx_apps_ativo", "ativo"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    icone: Mapped[str | None] = mapped_column(Text)
    secao_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("secoes.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    tipo_acesso: Mapped[str] = mapped_column(
        Text, nullable=False, default="url", server_default=sa_text("'url'")
    )
    badge: Mapped[str | None] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa_text("0"))
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))
    criado_em: Mapped[str] = mapped_column(Text, nullable=False, default=_now)
    atualizado_em: Mapped[str | None] = mapped_column(Text)
    nome_es: Mapped[str | None] = mapped_column(Text)
    descricao_es: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    nome: Mapped[str] = mapped_column(Text, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=sa_text("1"))


role_apps = Table(
    "role_apps",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("app_id", Integer, ForeignKey("apps.id", ondelete="CASCADE"), primary_key=True),
)

usuario_roles = Table(
    "usuario_roles",
    Base.metadata,
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


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
