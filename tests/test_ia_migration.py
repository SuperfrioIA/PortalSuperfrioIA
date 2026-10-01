"""SuperfrioIA — a migration 0011: sobe, desce e sobe de novo.

SQLite aqui (arquivo temporário, descartável). O mesmo ciclo no Postgres de teste
(porta 5434, container dedicado) está em `test_ia_migration_postgres.py`, que é
pulado quando o container não está de pé.
"""
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from backend.core.database import _alembic_config, init_db

TABELAS = {"ia_conversas", "ia_mensagens", "ia_consultas", "ia_concessoes"}


@pytest.fixture
def url(tmp_path):
    return f"sqlite:///{(tmp_path / 'migra.db').as_posix()}"


def tabelas(url):
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_sobe_ate_a_cabeca_cria_as_quatro_tabelas(url):
    init_db(url)
    assert TABELAS <= tabelas(url)


def test_desce_uma_revisao_remove_so_as_tabelas_do_ia(url):
    init_db(url)
    command.downgrade(_alembic_config(url), "0010")
    depois = tabelas(url)
    assert not (TABELAS & depois)
    assert {"usuarios", "apps", "auditoria_eventos", "volumetria_downloads"} <= depois   # o resto intacto


def test_sobe_de_novo_depois_de_descer(url):
    init_db(url)
    command.downgrade(_alembic_config(url), "0010")
    command.upgrade(_alembic_config(url), "head")
    assert TABELAS <= tabelas(url)


def test_o_schema_tem_os_indices_e_as_chaves_que_a_retencao_e_a_concessao_exigem(url):
    init_db(url)
    eng = create_engine(url)
    try:
        insp = inspect(eng)
        nomes = {i["name"]: i for i in insp.get_indexes("ia_concessoes")}
        for status in ("pendente", "ativa"):
            unico = nomes[f"uq_ia_concessoes_{status}"]
            assert unico["unique"] and unico["column_names"] == ["usuario_id", "dominio"]
        fks = {tuple(fk["constrained_columns"]): fk for fk in insp.get_foreign_keys("ia_consultas")}
        assert fks[("mensagem_id",)]["options"].get("ondelete") == "SET NULL"
        fks = {tuple(fk["constrained_columns"]): fk for fk in insp.get_foreign_keys("ia_mensagens")}
        assert fks[("conversa_id",)]["options"].get("ondelete") == "CASCADE"
        assert "idx_ia_mensagens_criado_em" in {i["name"] for i in insp.get_indexes("ia_mensagens")}
        assert "idx_ia_consultas_criado_em" in {i["name"] for i in insp.get_indexes("ia_consultas")}
    finally:
        eng.dispose()


def test_as_constraints_de_status_recusam_valor_fora_do_vocabulario(url):
    init_db(url)
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = ON"))
            with pytest.raises(Exception):
                conn.execute(text(
                    "INSERT INTO ia_concessoes (usuario_id, username, dominio, status, motivo_pedido, pedido_em, autoaprovacao) "
                    "VALUES (1, 'u', 'd', 'vencida', 'x', '2026-01-01 00:00:00', 0)"))
    finally:
        eng.dispose()


def test_a_cadeia_de_revisoes_nao_ramificou():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    assert script.get_heads() == ["0011"]
    assert script.get_revision("0011").down_revision == "0010"
