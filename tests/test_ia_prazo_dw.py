"""Prazo de EXECUÇÃO das consultas ao DW feitas pela IA (pendência M6 da revisão do Lote 4).

Uma consulta ao DW que não volta segurava a thread e a vaga de simultâneas do usuário. O prazo
(`call_timeout` do driver) vale SÓ dentro do contexto que a IA abre; a tela da Volumetria, que já está
em produção sem esse limite, segue exatamente como estava. Sem DW real: driver de mentira.
"""
import threading

import pytest

from backend.ia import config
from backend.volumetria_catering import conexao_dw, service
from ia_ajuda import perguntar_http


class _Conexao:
    call_timeout = 0


class _Driver:
    class defaults:
        fetch_decimals = False

    def __init__(self):
        self.conexoes = []

    def connect(self, **kwargs):
        c = _Conexao()
        self.conexoes.append(c)
        return c


@pytest.fixture
def driver(monkeypatch):
    d = _Driver()
    monkeypatch.setenv("DW_LEITURA_USUARIO", "usuario-de-teste")
    monkeypatch.setenv("DW_LEITURA_SENHA", "senha-de-teste")
    monkeypatch.setattr(conexao_dw, "configurar_driver", lambda: d)
    return d


# ============================================================ a conexão
def test_a_tela_abre_conexao_sem_prazo_de_execucao_como_sempre(driver):
    """Sem o contexto da IA, nada muda: a conexão não recebe `call_timeout`."""
    conexao_dw.conectar()
    assert driver.conexoes[0].call_timeout == 0


def test_dentro_do_contexto_a_conexao_recebe_o_prazo_em_milissegundos(driver):
    with conexao_dw.com_limite_de_execucao(20.0):
        conexao_dw.conectar()
    assert driver.conexoes[0].call_timeout == 20000


def test_o_contexto_nao_vaza_para_depois_nem_para_outra_thread(driver):
    vistos = []
    with conexao_dw.com_limite_de_execucao(7):
        t = threading.Thread(target=lambda: (conexao_dw.conectar(), vistos.append("outra")))
        t.start()
        t.join()
    conexao_dw.conectar()                                  # depois de sair do bloco
    assert [c.call_timeout for c in driver.conexoes] == [0, 0], "nem a outra thread nem o 'depois' herdam o prazo"


def test_contextos_aninhados_voltam_ao_valor_de_fora(driver):
    with conexao_dw.com_limite_de_execucao(10):
        with conexao_dw.com_limite_de_execucao(3):
            conexao_dw.conectar()
        conexao_dw.conectar()
    assert [c.call_timeout for c in driver.conexoes] == [3000, 10000]


def test_o_contexto_e_desfeito_mesmo_quando_o_bloco_levanta(driver):
    with pytest.raises(RuntimeError):
        with conexao_dw.com_limite_de_execucao(5):
            raise RuntimeError("falhou")
    conexao_dw.conectar()
    assert driver.conexoes[0].call_timeout == 0


def test_o_servico_expoe_o_contexto_para_a_ia_sem_ela_tocar_na_conexao(driver):
    with service.com_limite_de_execucao(4):
        conexao_dw.conectar()
    assert driver.conexoes[0].call_timeout == 4000


# ============================================================== a IA o usa
def test_toda_consulta_da_ia_ao_dw_abre_o_prazo_e_a_chamada_direta_ao_servico_nao(client, usuario_ia, monkeypatch):
    vistos = []
    original = conexao_dw.conectar                       # o DW de mentira instalado pelo fixture

    def espiao():
        vistos.append(conexao_dw._LIMITE_DE_EXECUCAO_S.get())
        return original()

    monkeypatch.setattr(conexao_dw, "conectar", espiao)
    perguntar_http(client, usuario_ia, "Quanto de peso líquido entrou em agosto de 2026?")
    assert vistos and all(v == config.limite_de_execucao_dw_s() == 20.0 for v in vistos), vistos

    vistos.clear()
    service.opcoes()                                      # o caminho da tela: sem prazo
    assert vistos and all(v is None for v in vistos), vistos


def test_o_prazo_e_configuravel_e_variavel_vazia_cai_no_padrao(monkeypatch):
    assert config.limite_de_execucao_dw_s() == 20.0
    monkeypatch.setenv("IA_DW_TIMEOUT_S", "5")
    assert config.limite_de_execucao_dw_s() == 5.0
    for ruim in ("", "abc", "0", "-3"):
        monkeypatch.setenv("IA_DW_TIMEOUT_S", ruim)
        assert config.limite_de_execucao_dw_s() == 20.0


def test_consulta_que_estoura_o_prazo_termina_a_pergunta_como_fonte_indisponivel(client, usuario_ia, ia_dw):
    """O driver devolve o erro de prazo (DPY-4024) no `execute`: a pergunta termina neutra, a vaga volta."""
    from backend.ia import service as ia_service

    banco = ia_dw()
    banco.erro_na_consulta = type("DatabaseError", (Exception,), {"__module__": "oracledb"})("DPY-4024: call timeout of 20000 ms exceeded")
    r = perguntar_http(client, usuario_ia, "Quanto de peso líquido entrou em agosto de 2026?")
    assert r["estado"] == "indisponivel"
    assert ia_service._EM_ANDAMENTO == {}, "a vaga do usuário não pode ficar presa"
