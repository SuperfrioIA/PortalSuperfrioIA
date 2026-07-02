"""Ambiente Alembic do Hub.

A URL vem, nesta ordem: attributes (init_db em runtime) → alembic.ini →
backend.database.DATABASE_URL (uso via CLI sem nada configurado). O metadata
dos models é o alvo do autogenerate.
"""
from alembic import context
from sqlalchemy import create_engine

from backend.database import DATABASE_URL, Base

config = context.config
target_metadata = Base.metadata


def _resolve_url() -> str:
    return (
        config.attributes.get("sqlalchemy_url")
        or config.get_main_option("sqlalchemy.url")
        or DATABASE_URL
    )


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_resolve_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # ALTER no SQLite é limitado; batch mode recria a tabela por baixo
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
