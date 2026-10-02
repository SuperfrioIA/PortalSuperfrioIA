"""Endurecimentos do Lote 4: perguntas simultâneas, teto do resultado enviado ao modelo e
avisos de ativação. Todos independentes do provedor e sem rede."""
import json
import threading

import pytest

from backend.ia import config, ferramentas, service
from backend.ia.politicas import ContextoDaPergunta, Recusa
from ia_ajuda import DOMINIO, Roteiro, eventos, marco_da_trilha, perguntar_http, usar_roteiro

USUARIO = {"id": 987654, "username": "simultaneas.teste", "role": "analista", "roles": []}


# ====================================================== perguntas simultâneas
def _bloqueante(monkeypatch):
    """Troca o miolo por uma pergunta que fica presa até o teste soltar."""
    entrou, solta = threading.Event(), threading.Event()
    chamadas = []

    def preso(user, **kwargs):
        chamadas.append(user["id"])
        entrou.set()
        assert solta.wait(10), "o teste não soltou a pergunta"
        return {"ok": True}

    monkeypatch.setattr(service, "_perguntar", preso)
    return entrou, solta, chamadas


def _pergunta_em_thread(resultados, indice):
    def corpo():
        try:
            resultados[indice] = service.perguntar(
                USUARIO, dominio_slug=DOMINIO, pergunta="x", conversa_id=None, ip="127.0.0.1")
        except Recusa as r:
            resultados[indice] = r

    t = threading.Thread(target=corpo)
    t.start()
    return t


def test_acima_do_limite_a_pergunta_e_recusada_com_429_e_auditada(monkeypatch):
    monkeypatch.setenv("IA_MAX_SIMULTANEAS", "1")
    entrou, solta, chamadas = _bloqueante(monkeypatch)
    marco = marco_da_trilha()
    resultados = {}
    primeira = _pergunta_em_thread(resultados, 0)
    assert entrou.wait(10)

    with pytest.raises(Recusa) as r:
        service.perguntar(USUARIO, dominio_slug=DOMINIO, pergunta="x", conversa_id=None, ip="127.0.0.1")
    assert r.value.status == 429 and r.value.motivo == "simultaneas"
    assert eventos(marco, "ia.bloqueio")[0]["detalhes"]["motivo"] == "simultaneas"

    solta.set()
    primeira.join(10)
    assert resultados[0] == {"ok": True} and chamadas == [USUARIO["id"]]
    assert service._EM_ANDAMENTO == {}, "a vaga tem que voltar"


def test_a_vaga_volta_depois_de_cada_pergunta_inclusive_quando_ela_falha(monkeypatch):
    monkeypatch.setenv("IA_MAX_SIMULTANEAS", "1")

    def quebra(user, **kwargs):
        raise RuntimeError("falha no meio")

    monkeypatch.setattr(service, "_perguntar", quebra)
    for _ in range(3):                                    # se a vaga vazasse, a 2ª já seria 429
        with pytest.raises(RuntimeError):
            service.perguntar(USUARIO, dominio_slug=DOMINIO, pergunta="x", conversa_id=None, ip=None)
    assert service._EM_ANDAMENTO == {}


def test_o_limite_e_por_usuario_nao_global(monkeypatch):
    monkeypatch.setenv("IA_MAX_SIMULTANEAS", "1")
    entrou, solta, chamadas = _bloqueante(monkeypatch)
    resultados = {}
    primeira = _pergunta_em_thread(resultados, 0)
    assert entrou.wait(10)
    outro = {**USUARIO, "id": USUARIO["id"] + 1, "username": "outro.usuario"}

    def corpo():
        resultados["outro"] = service.perguntar(outro, dominio_slug=DOMINIO, pergunta="x", conversa_id=None, ip=None)

    t = threading.Thread(target=corpo)
    t.start()
    solta.set()
    t.join(10)
    primeira.join(10)
    assert resultados["outro"] == {"ok": True} and sorted(chamadas) == [USUARIO["id"], outro["id"]]


def test_padrao_de_duas_simultaneas_e_valor_invalido_cai_no_padrao(monkeypatch):
    monkeypatch.delenv("IA_MAX_SIMULTANEAS", raising=False)
    assert config.max_simultaneas() == 2
    for ruim in ("0", "-1", "abc", ""):
        monkeypatch.setenv("IA_MAX_SIMULTANEAS", ruim)
        assert config.max_simultaneas() == 2


def test_pelo_http_a_pergunta_normal_continua_funcionando_depois_do_limite(client, usuario_ia):
    for _ in range(4):                                    # quatro seguidas: a vaga volta a cada uma
        assert perguntar_http(client, usuario_ia, "Quais unidades existem?")["estado"] == "ok"
    assert service._EM_ANDAMENTO == {}


# ============================================== teto do resultado enviado ao modelo
def test_resultado_acima_do_teto_vira_erro_para_o_modelo_e_fica_na_trilha(client, usuario_ia, monkeypatch):
    monkeypatch.setenv("IA_TAM_RESULTADO", "300")
    roteiro = usar_roteiro(monkeypatch, Roteiro([("descrever", {"dominio": DOMINIO})]))
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, "O que você sabe responder?")
    assert roteiro.resultados[0]["erro"] == "resultado_grande" and "Restrinja" in roteiro.resultados[0]["mensagem"]
    bloqueio = eventos(marco, "ia.bloqueio")[0]["detalhes"]
    assert bloqueio["motivo"] == "resultado_grande" and bloqueio["ferramenta"] == "descrever" and bloqueio["tamanho"] > 300
    assert "Quanto" not in json.dumps(roteiro.resultados[0]), "o modelo não recebe o resultado grande, só o erro"


def test_resultado_dentro_do_teto_passa_inteiro(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([("descrever", {"dominio": DOMINIO})]))
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, "O que você sabe responder?")
    assert "erro" not in roteiro.resultados[0] and roteiro.resultados[0]["dominio"] == DOMINIO
    assert not [e for e in eventos(marco, "ia.bloqueio") if e["detalhes"]["motivo"] == "resultado_grande"]


def test_os_blocos_do_hub_nao_passam_pelo_teto_so_o_que_vai_ao_modelo(client, usuario_ia, monkeypatch):
    monkeypatch.setenv("IA_TAM_RESULTADO", "300")
    from ia_ajuda import consulta

    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(detalhe="unidade")]))
    r = perguntar_http(client, usuario_ia, "Quanto entrou por unidade em agosto?")
    assert roteiro.resultados[0]["erro"] == "resultado_grande"
    assert r["mensagem"]["blocos"], "o usuário continua vendo o dado montado pelo Hub"


def test_o_teto_so_pega_quando_passa_e_o_padrao_tem_folga(monkeypatch):
    monkeypatch.delenv("IA_TAM_RESULTADO", raising=False)
    assert config.tamanho_maximo_do_resultado() == 20000
    ctx = ContextoDaPergunta(usuario={}, dominio=DOMINIO, hoje=__import__("datetime").date(2026, 9, 6))
    assert "erro" not in ferramentas.executar("listar_capacidades", {}, ctx)


# ============================================================ avisos de ativação
@pytest.fixture
def limpo(monkeypatch):
    for var in ("IA_HABILITADO", "IA_PROVEDOR", "IA_AUTOAPROVACAO", "ANTHROPIC_API_KEY", "SUPERFRIO_ENV"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_com_a_chave_mestra_desligada_nao_ha_aviso_nenhum(limpo):
    limpo.setenv("IA_PROVEDOR", "anthropic")
    assert config.avisos_de_ativacao() == []


def test_provedor_real_com_autoaprovacao_ligada_avisa(limpo):
    limpo.setenv("IA_HABILITADO", "true")
    limpo.setenv("IA_PROVEDOR", "anthropic")
    limpo.setenv("ANTHROPIC_API_KEY", "valor-so-de-teste")
    assert any("IA_AUTOAPROVACAO" in a for a in config.avisos_de_ativacao())
    limpo.setenv("IA_AUTOAPROVACAO", "false")
    assert config.avisos_de_ativacao() == []


def test_provedor_real_sem_chave_avisa_sem_mostrar_valor(limpo):
    limpo.setenv("IA_HABILITADO", "true")
    limpo.setenv("IA_PROVEDOR", "anthropic")
    limpo.setenv("IA_AUTOAPROVACAO", "false")
    avisos = config.avisos_de_ativacao()
    assert len(avisos) == 1 and "ANTHROPIC_API_KEY" in avisos[0]
    limpo.setenv("ANTHROPIC_API_KEY", "valor-so-de-teste")
    assert config.avisos_de_ativacao() == []
    assert "valor-so-de-teste" not in " ".join(config.avisos_de_ativacao())


def test_provedor_de_teste_ligado_em_producao_avisa(limpo):
    limpo.setenv("IA_HABILITADO", "true")
    limpo.setenv("SUPERFRIO_ENV", "prod")
    assert any("produção" in a for a in config.avisos_de_ativacao())
    limpo.setenv("SUPERFRIO_ENV", "dev")
    assert config.avisos_de_ativacao() == []


def test_o_boot_registra_os_avisos():
    import pathlib

    fonte = (pathlib.Path(__file__).resolve().parent.parent / "backend" / "main.py").read_text(encoding="utf-8")
    assert "ia_config.avisos_de_ativacao()" in fonte and 'warning("SuperfrioIA: %s"' in fonte
