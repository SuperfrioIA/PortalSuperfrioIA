"""SuperfrioIA — a migration 0011 no Postgres de teste (container dedicado, porta 5434).

Pulado quando o container não está de pé (mesmo padrão de `test_auditoria_postgres.py`):
a suíte normal continua verde sem ele. Para rodar, ver `docs/EXECUCAO_LOCAL.md` §3.1.
Nunca aponte para a 5433 (é da nuvem-ia) nem para banco com dado de verdade: este
teste cria um banco próprio e o apaga no fim.
"""
import os
import socket
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

URL_ADMIN = os.environ.get("IA_TEST_PG_ADMIN_URL", "postgresql+psycopg://hub_teste:teste@127.0.0.1:5434/hub_teste")
TABELAS = {"ia_conversas", "ia_mensagens", "ia_consultas", "ia_concessoes"}


def _porta_aberta(host="127.0.0.1", porta=5434) -> bool:
    try:
        with socket.create_connection((host, porta), timeout=1.5):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _porta_aberta(), reason="Postgres de teste (5434) fora do ar")


@pytest.fixture
def banco_proprio():
    from backend.core.database import _alembic_config

    nome = f"ia_migra_{uuid.uuid4().hex[:8]}"
    admin = create_engine(URL_ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{nome}"'))
    url = URL_ADMIN.rsplit("/", 1)[0] + f"/{nome}"
    try:
        yield url, _alembic_config(url)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)'))
        admin.dispose()


def _tabelas(url):
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_sobe_desce_e_sobe_no_postgres(banco_proprio):
    url, cfg = banco_proprio
    command.upgrade(cfg, "head")
    assert TABELAS <= _tabelas(url)
    command.downgrade(cfg, "0010")
    assert not (TABELAS & _tabelas(url))
    command.upgrade(cfg, "head")
    assert TABELAS <= _tabelas(url)


def test_indices_unicos_parciais_e_chaves_no_postgres(banco_proprio):
    url, cfg = banco_proprio
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            definicoes = dict(conn.execute(text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'ia_concessoes'")).all())
            assert "WHERE (status = 'pendente'" in definicoes["uq_ia_concessoes_pendente"]
            assert "UNIQUE" in definicoes["uq_ia_concessoes_ativa"]
            regras = dict(conn.execute(text(
                "SELECT tc.table_name, rc.delete_rule FROM information_schema.referential_constraints rc "
                "JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name "
                "WHERE tc.table_name IN ('ia_consultas', 'ia_mensagens')")).all())
            assert regras == {"ia_consultas": "SET NULL", "ia_mensagens": "CASCADE"}
    finally:
        eng.dispose()


def test_duplo_pendente_e_recusado_pelo_banco(banco_proprio):
    url, cfg = banco_proprio
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    linha = ("INSERT INTO ia_concessoes (usuario_id, username, dominio, status, motivo_pedido, pedido_em, autoaprovacao) "
             "VALUES (1, 'u', 'd', 'pendente', 'x', '2026-01-01 00:00:00', 0)")
    try:
        with eng.begin() as conn:
            conn.execute(text(linha))
        with pytest.raises(Exception, match="uq_ia_concessoes_pendente"):
            with eng.begin() as conn:
                conn.execute(text(linha))
    finally:
        eng.dispose()
