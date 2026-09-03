"""Auditoria — a prova do trigger de imutabilidade contra Postgres REAL.

`tests/test_auditoria.py` já prova o trigger no SQLite (dialeto usado pela
suíte padrão do Hub). Este arquivo prova só a metade que o SQLite não pode:
o mesmo trigger, compilado como função PL/pgSQL, recusando UPDATE e DELETE
num Postgres de verdade — mesmo raciocínio e mesmo banco de
`tests/test_volumetria_catering_postgres.py` (pulado inteiro, sem falhar,
quando o container não responde).

Usa o `superfrio-teste-db` (porta 5434, ver docs/EXECUCAO_LOCAL.md) só como
servidor: roda as migrations do Hub até head num banco próprio
(`auditoria_teste`) dentro dele, para não disputar o schema `public` com a
suíte da volumetria, que o zera a cada teste.
"""
import os
import socket

import psycopg
import pytest
from alembic import command

from backend.core.database import _alembic_config

_URL_SERVIDOR = os.environ.get(
    "VOLUMETRIA_TEST_DB_URL", "postgresql://hub_teste:teste@localhost:5434/hub_teste"
)
_BANCO_TESTE = "auditoria_teste"


def _partes_servidor():
    partes = psycopg.conninfo.conninfo_to_dict(_URL_SERVIDOR)
    return partes.get("host") or "localhost", int(partes.get("port") or 5432)


def _alcancavel() -> bool:
    """Mesma checagem em duas etapas de `test_volumetria_catering_postgres.py`:
    socket cru antes do driver, porque o relay de porta do WSL pode aceitar o
    TCP e nunca responder depois que a distro encerra sozinha."""
    try:
        host, porta = _partes_servidor()
        with socket.create_connection((host, porta), timeout=2):
            pass
        with psycopg.connect(_URL_SERVIDOR, connect_timeout=2):
            return True
    except (OSError, psycopg.Error, ValueError):
        return False


if not _alcancavel():
    pytest.skip(
        f"Postgres de teste indisponível em {_URL_SERVIDOR.split('@')[-1]} "
        "— ver docs/EXECUCAO_LOCAL.md (seção Postgres de teste da volumetria)",
        allow_module_level=True,
    )


def _url_banco_teste() -> str:
    partes = psycopg.conninfo.conninfo_to_dict(_URL_SERVIDOR)
    partes["dbname"] = _BANCO_TESTE
    return psycopg.conninfo.make_conninfo(**partes)


@pytest.fixture
def pg():
    """`auditoria_teste` recriado do zero e migrado até head a cada teste —
    banco próprio, não o `public` que a volumetria disputa."""
    with psycopg.connect(_URL_SERVIDOR, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {_BANCO_TESTE}")
            cur.execute(f"CREATE DATABASE {_BANCO_TESTE}")
    url = _url_banco_teste()
    command.upgrade(_alembic_config(url), "head")
    conn = psycopg.connect(url, autocommit=True)
    yield conn
    conn.close()
    with psycopg.connect(_URL_SERVIDOR, autocommit=True) as admin:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {_BANCO_TESTE}")


def _inserir_evento(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO auditoria_eventos (ocorrido_em, categoria, acao, resultado) "
            "VALUES ('2026-01-01 00:00:00', 'auditoria', 'auditoria.consultar', 'ok') "
            "RETURNING id"
        )
        return cur.fetchone()[0]


def test_migration_0008_sobe_com_a_funcao_e_o_trigger(pg):
    with pg.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'auditoria_eventos_bloquear'")
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = 'auditoria_eventos_imutavel' AND NOT tgisinternal"
        )
        assert cur.fetchone() is not None


def test_trigger_recusa_update_no_postgres(pg):
    id_ = _inserir_evento(pg)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with pg.cursor() as cur:
            cur.execute("UPDATE auditoria_eventos SET resultado = 'erro' WHERE id = %s", (id_,))


def test_trigger_recusa_delete_no_postgres(pg):
    id_ = _inserir_evento(pg)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with pg.cursor() as cur:
            cur.execute("DELETE FROM auditoria_eventos WHERE id = %s", (id_,))


def test_downgrade_remove_trigger_e_funcao(pg):
    url = _url_banco_teste()
    command.downgrade(_alembic_config(url), "0007")
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_proc WHERE proname = 'auditoria_eventos_bloquear'")
            assert cur.fetchone() is None
            cur.execute("SELECT to_regclass('auditoria_eventos')")
            assert cur.fetchone()[0] is None
