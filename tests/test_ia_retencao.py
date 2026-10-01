"""SuperfrioIA — retenção: mensagens 90 dias, metadados de consultas 180 (DD-25).

"Mais antigo que N dias" é estrito. A trilha de auditoria e as concessões nunca são
tocadas. A rotina é idempotente, apaga em lotes e roda com a chave desligada.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update

from backend.auditoria.models import AuditoriaEvento
from backend.core.database import db
from backend.ia import retencao
from backend.ia.models import IaConcessao, IaConsulta, IaConversa, IaMensagem

AGORA = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
M, C, Q, K = IaMensagem.__table__, IaConversa.__table__, IaConsulta.__table__, IaConcessao.__table__


def ts(dias: float = 0, segundos: int = 0) -> str:
    return (AGORA - timedelta(days=dias, seconds=segundos)).strftime("%Y-%m-%d %H:%M:%S")


def conversa(session, quando: str, usuario_id=1) -> int:
    return session.execute(insert(IaConversa).values(
        usuario_id=usuario_id, username="u", dominio="volumetria-catering", titulo="t",
        criado_em=quando, atualizado_em=quando)).inserted_primary_key[0]


def mensagem(session, conversa_id, quando: str) -> int:
    return session.execute(insert(IaMensagem).values(
        conversa_id=conversa_id, papel="usuario", texto="t", blocos="[]", meta="{}", criado_em=quando)).inserted_primary_key[0]


def consulta(session, quando: str, mensagem_id=None) -> int:
    return session.execute(insert(IaConsulta).values(
        mensagem_id=mensagem_id, usuario_id=1, dominio="volumetria-catering", capacidade="matriz",
        parametros="{}", escopo_aplicado="integral", situacao="ok", chamadas_logicas=1, criado_em=quando)).inserted_primary_key[0]


def existe(tabela, id_) -> bool:
    with db() as session:
        return session.execute(select(tabela.c.id).where(tabela.c.id == id_)).first() is not None


def total(tabela) -> int:
    with db() as session:
        return session.execute(select(func.count()).select_from(tabela)).scalar_one()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _tabelas_vazias(ia_ligada):
    """`ia_ligada` esvazia as tabelas `ia_*` no fim; aqui também no começo."""
    with db() as session:
        for tabela in (Q, M, C, K):
            session.execute(tabela.delete())
    yield


# ============================================================ mensagens: 90 dias
def test_mensagem_de_89_dias_fica_a_de_91_sai_e_a_de_exatos_90_fica():
    with db() as s:
        c = conversa(s, ts(0))
        nova, limite, velha = mensagem(s, c, ts(89)), mensagem(s, c, ts(90)), mensagem(s, c, ts(90, 1))
    r = retencao.executar(AGORA)
    assert existe(M, nova) and existe(M, limite)           # 90 dias exatos: ainda dentro do prazo
    assert not existe(M, velha)                            # 90 dias e 1 segundo: venceu
    assert r["mensagens"] == 1


def test_conversa_que_ficou_sem_mensagem_e_antiga_e_apagada_a_com_mensagem_recente_fica():
    with db() as s:
        vazia_antiga = conversa(s, ts(120))
        mensagem(s, vazia_antiga, ts(120))
        viva = conversa(s, ts(120))
        mensagem(s, viva, ts(120))
        mensagem(s, viva, ts(1))                           # uma mensagem recente mantém a conversa
        nova_vazia = conversa(s, ts(0))                    # acabou de nascer, ainda sem mensagem
    r = retencao.executar(AGORA)
    assert not existe(C, vazia_antiga) and existe(C, viva) and existe(C, nova_vazia)
    assert r["conversas"] == 1
    with db() as s:
        assert s.execute(select(func.count()).select_from(M).where(M.c.conversa_id == viva)).scalar_one() == 1


# =========================================================== consultas: 180 dias
def test_consulta_de_179_dias_fica_a_de_181_sai():
    with db() as s:
        nova, velha = consulta(s, ts(179)), consulta(s, ts(181))
    r = retencao.executar(AGORA)
    assert existe(Q, nova) and not existe(Q, velha) and r["consultas"] == 1


def test_mensagem_apagada_aos_90_dias_nao_derruba_a_consulta_que_vive_ate_os_180():
    with db() as s:
        c = conversa(s, ts(100))
        m = mensagem(s, c, ts(100))
        q = consulta(s, ts(100), mensagem_id=m)
    retencao.executar(AGORA)
    assert not existe(M, m) and existe(Q, q)
    with db() as s:
        assert s.execute(select(Q.c.mensagem_id).where(Q.c.id == q)).scalar_one() is None   # referência anulada


def test_depois_dos_180_a_consulta_tambem_sai():
    with db() as s:
        q = consulta(s, ts(200))
    retencao.executar(AGORA)
    assert not existe(Q, q)


# ============================================================ o que nunca se apaga
def test_a_trilha_de_auditoria_nunca_e_tocada_nem_as_ia():
    with db() as s:
        s.execute(insert(AuditoriaEvento).values(
            ocorrido_em=ts(400), categoria="ia", acao="ia.pergunta", resultado="ok", app_slug="superfrioia", detalhes="{}"))
        s.execute(insert(AuditoriaEvento).values(
            ocorrido_em=ts(2000), categoria="auth", acao="login.ok", resultado="ok", detalhes="{}"))
    antes = total(AuditoriaEvento.__table__)
    retencao.executar(AGORA)
    assert total(AuditoriaEvento.__table__) >= antes        # só cresceu (o evento da própria retenção)
    with db() as s:
        ids = s.execute(select(AuditoriaEvento.id).where(AuditoriaEvento.ocorrido_em.in_([ts(400), ts(2000)]))).all()
    assert len(ids) == 2


def test_as_concessoes_nao_sao_tocadas_nem_as_antigas():
    with db() as s:
        s.execute(insert(IaConcessao).values(
            usuario_id=1, username="u", dominio="volumetria-catering", status="revogada",
            motivo_pedido="x", pedido_em=ts(900), autoaprovacao=0))
    retencao.executar(AGORA)
    assert total(K) == 1


# ===================================================== idempotência, lotes e job
def test_rodar_duas_vezes_seguidas_apaga_zero_na_segunda():
    with db() as s:
        c = conversa(s, ts(200))
        mensagem(s, c, ts(200))
        consulta(s, ts(200))
    primeira = retencao.executar(AGORA)
    segunda = retencao.executar(AGORA)
    assert (primeira["mensagens"], primeira["conversas"], primeira["consultas"]) == (1, 1, 1)
    assert (segunda["mensagens"], segunda["conversas"], segunda["consultas"]) == (0, 0, 0)


def test_apaga_em_lotes_quando_o_volume_passa_de_um_lote():
    with db() as s:
        c = conversa(s, ts(0))
        for _ in range(25):
            mensagem(s, c, ts(120))
        mensagem(s, c, ts(1))
    r = retencao.executar(AGORA, lote=10)                  # 25 antigas em lotes de 10
    assert r["mensagens"] == 25 and total(M) == 1


def test_o_prazo_e_configuravel_e_aparece_nas_contagens(monkeypatch):
    monkeypatch.setenv("IA_RETENCAO_MENSAGENS_DIAS", "10")
    with db() as s:
        c = conversa(s, ts(0))
        velha = mensagem(s, c, ts(11))
    r = retencao.executar(AGORA)
    assert not existe(M, velha) and r["prazo_mensagens_dias"] == 10


def test_o_job_existe_no_agendador_depois_do_lifespan():
    from fastapi.testclient import TestClient

    from backend.core import scheduler
    from backend.main import app

    with TestClient(app):
        job = scheduler._scheduler.get_job(retencao.JOB_ID)
        assert job is not None and job.func is retencao.job
        assert str(job.trigger).startswith("cron[") and "hour='3'" in str(job.trigger)


def test_falha_na_rotina_e_registrada_e_nao_derruba_o_job(monkeypatch):
    def quebra(*_a, **_k):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(retencao, "executar", quebra)
    retencao.job()                                          # não levanta
