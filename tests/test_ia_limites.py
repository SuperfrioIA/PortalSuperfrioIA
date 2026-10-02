"""SuperfrioIA — cotas e limites por pergunta (DD-16, DD-24).

Dois contadores independentes: as **chamadas lógicas** ao indicador (teto de 3) e o
**trabalho interno** no banco (conexões/páginas). Uma única chamada lógica pode
estourar o segundo.
"""
import dw_falso
from ia_ajuda import (
    DOMINIO, Roteiro, consulta, eventos, marco_da_trilha, perguntar_http,
    registros_de_consulta, usar_roteiro,
)
from sqlalchemy import select

from backend.core.database import db
from backend.ia.models import IaMensagem

LENTE_INVALIDA = consulta(lente="kg")


# ============================================ teto de 3 chamadas lógicas
def test_a_quarta_chamada_logica_e_recusada_e_a_pergunta_termina(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta()] * 5))
    marco = marco_da_trilha()
    r = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    assert r["estado"] == "limite_consultas"
    assert "mais de 3 consultas" in r["mensagem"]["texto"]            # texto FIXO, o modelo não improvisa
    assert len(roteiro.resultados) == 3                              # a 4ª levantou; a 5ª nem foi pedida
    assert [(c["situacao"], c["motivo"]) for c in registros_de_consulta()] == \
        [("ok", None)] * 3 + [("bloqueio", "limite_consultas")]
    assert [e["detalhes"]["motivo"] for e in eventos(marco, "ia.bloqueio")] == ["limite_consultas"]


def test_tentativa_recusada_tambem_gasta_uma_das_tres(client, usuario_ia, monkeypatch):
    """Um modelo que erra em laço não pode ficar de graça."""
    roteiro = usar_roteiro(monkeypatch, Roteiro([LENTE_INVALIDA] * 3 + [consulta()]))
    r = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    assert r["estado"] == "limite_consultas"
    assert [x["erro"] for x in roteiro.resultados] == ["parametro_invalido"] * 3
    assert registros_de_consulta()[0]["parametros"] == '{"recusado": true}'   # sem o conteúdo recusado


def test_tres_chamadas_logicas_cabem(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(movimento="rec"), consulta(movimento="exp"), consulta(lente="vol")]))
    r = perguntar_http(client, usuario_ia, "Quanto entrou e saiu em agosto?")
    assert r["estado"] == "ok" and len(roteiro.resultados) == 3


def test_o_contrato_so_pode_apertar_o_teto_nunca_afrouxar(client, usuario_ia, monkeypatch):
    from backend.ia import dominios
    monkeypatch.setitem(dominios.obter(DOMINIO).dados, "limites", {"consultas_por_pergunta": 2})
    usar_roteiro(monkeypatch, Roteiro([consulta()] * 3))
    assert perguntar_http(client, usuario_ia, "x")["estado"] == "limite_consultas"
    monkeypatch.setitem(dominios.obter(DOMINIO).dados, "limites", {"consultas_por_pergunta": 99})
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta()] * 5))
    assert perguntar_http(client, usuario_ia, "x")["estado"] == "limite_consultas"
    assert len(roteiro.resultados) == 3                              # o limite de config (3) venceu os 99 do contrato


def test_o_teto_e_configuravel_por_ambiente(client, usuario_ia, monkeypatch):
    monkeypatch.setenv("IA_MAX_CONSULTAS", "1")
    usar_roteiro(monkeypatch, Roteiro([consulta(), consulta()]))
    assert perguntar_http(client, usuario_ia, "x")["estado"] == "limite_consultas"


# ====================================== limite interno, independente do teto
def test_uma_chamada_logica_pode_estourar_o_limite_interno(client, usuario_ia, ia_dw, monkeypatch):
    """62 unidades da fonte = 61 exibidas = 6 páginas, acima das 5 permitidas.
    Uma única chamada lógica; o limite interno é quem barra."""
    banco = ia_dw(n_unidades=62)
    usar_roteiro(monkeypatch, Roteiro([consulta(detalhe="unidade")]))
    r = perguntar_http(client, usuario_ia, "Qual unidade mais recebeu em agosto?")
    assert r["estado"] == "limite_interno"
    assert "ampla demais" in r["mensagem"]["texto"] or "abrangeria" in r["mensagem"]["texto"]
    c = registros_de_consulta()[0]
    assert c["chamadas_logicas"] == 1 and c["limite_interno_atingido"] == 1 and c["situacao"] == "bloqueio"
    assert len(banco.consultas) == 1                                  # leu a 1ª página para saber o tamanho, e parou


def test_cinco_paginas_cabem_e_seis_nao(client, usuario_ia, ia_dw, monkeypatch):
    for n_unidades, estado, paginas in ((61, "ok", 5), (62, "limite_interno", 1)):
        ia_dw(n_unidades=n_unidades)
        usar_roteiro(monkeypatch, Roteiro([consulta(detalhe="unidade")]))
        assert perguntar_http(client, usuario_ia, "x")["estado"] == estado
        assert registros_de_consulta()[-1]["paginas_lidas"] == paginas


def test_o_limite_de_operacoes_para_o_trabalho_mesmo_com_chamadas_logicas_de_sobra(
    client, usuario_ia, ia_dw, monkeypatch
):
    """3 operações permitidas: opções + 2 leituras. A 3ª consulta lógica não cabe,
    embora o teto de chamadas lógicas ainda permitisse."""
    monkeypatch.setenv("IA_MAX_OPERACOES_DW", "3")
    banco = ia_dw()
    usar_roteiro(monkeypatch, Roteiro([consulta(), consulta(movimento="exp"), consulta(lente="vol")]))
    r = perguntar_http(client, usuario_ia, "x")
    assert r["estado"] == "limite_interno"
    assert len(banco.conexoes) == 3                                   # 3 conexões ao DW, nem uma a mais
    assert [c["limite_interno_atingido"] for c in registros_de_consulta()] == [0, 0, 1]


def test_o_registro_das_operacoes_efetivas_bate_com_o_que_o_dw_viu(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw(n_unidades=14)
    usar_roteiro(monkeypatch, Roteiro([consulta(detalhe="unidade"), consulta(movimento="amb", faixa="atendido")]))
    perguntar_http(client, usuario_ia, "x")
    registros = registros_de_consulta()
    assert sum(c["chamadas_servico"] for c in registros) == len(banco.conexoes)
    assert sum(c["paginas_lidas"] for c in registros) == 3            # 2 páginas de unidades + 1 da conjunta
    assert sum(c["consultas_dw"] for c in registros) == len(banco.consultas) == 4   # 2 + (1 conjunta = 2 consultas)
    assert all(c["chamadas_logicas"] == 1 for c in registros)


def test_passos_de_ferramenta_tambem_tem_teto(client, usuario_ia, monkeypatch):
    monkeypatch.setenv("IA_MAX_PASSOS", "2")
    roteiro = usar_roteiro(monkeypatch, Roteiro([("listar_capacidades", {})] * 3))
    r = perguntar_http(client, usuario_ia, "x")
    assert r["estado"] == "passos" and len(roteiro.resultados) == 2


def test_valor_invalido_de_limite_cai_no_padrao_e_nao_derruba(monkeypatch):
    from backend.ia import config
    for ruim in ("abc", "0", "-3", ""):
        monkeypatch.setenv("IA_COTA_DIA", ruim)
        assert config.cota_diaria() == 30


# ================================================================== cota e tamanho
def test_31a_pergunta_do_dia_do_mesmo_usuario_e_recusada(client, usuario_ia, criar_usuario_ia, monkeypatch):
    monkeypatch.setenv("IA_COTA_DIA", "3")
    marco = marco_da_trilha()
    for _ in range(3):
        perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    r = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?", esperado=429)
    assert "Limite diário atingido (3 perguntas)" in r["detail"]
    assert [e["detalhes"]["motivo"] for e in eventos(marco, "ia.bloqueio")] == ["cota"]
    # a cota é por usuário: outra pessoa não é afetada
    assert client.get("/api/ia/dominios", headers=usuario_ia["headers"]).json()[0]["limites"]["perguntas_hoje"] == 3


def test_cota_padrao_e_30_e_pergunta_recusada_nao_consome(client, usuario_ia):
    d = client.get("/api/ia/dominios", headers=usuario_ia["headers"]).json()[0]
    assert d["limites"]["perguntas_por_dia"] == 30
    perguntar_http(client, usuario_ia, "", esperado=400)
    perguntar_http(client, usuario_ia, "x" * 1001, esperado=400)
    assert client.get("/api/ia/dominios", headers=usuario_ia["headers"]).json()[0]["limites"]["perguntas_hoje"] == 0


def test_pergunta_de_1000_caracteres_passa_e_de_1001_nao(client, usuario_ia, monkeypatch):
    usar_roteiro(monkeypatch, Roteiro([]))
    perguntar_http(client, usuario_ia, "a" * 1000)
    r = perguntar_http(client, usuario_ia, "a" * 1001, esperado=400)
    assert "até 1000 caracteres" in r["detail"]


def test_pergunta_recusada_por_tamanho_nao_vai_ao_banco_nem_ao_provedor(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([]))
    perguntar_http(client, usuario_ia, "z" * 1001, esperado=400)
    assert roteiro.contextos == []
    with db() as session:
        assert session.execute(select(IaMensagem.id)).first() is None


# ============================================================= fonte indisponível
def test_dw_fora_termina_a_pergunta_com_texto_fixo_e_registra_erro(client, usuario_ia, ia_dw, monkeypatch):
    erro = type("DatabaseError", (Exception,), {"__module__": "oracledb"})("DPY-4011")
    ia_dw(erro_na_consulta=erro)
    usar_roteiro(monkeypatch, Roteiro([consulta()]))
    marco = marco_da_trilha()
    r = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    assert r["estado"] == "indisponivel"
    assert "Não consegui consultar os dados agora" in r["mensagem"]["texto"]
    assert "DPY-4011" not in str(r) and "oracledb" not in str(r)       # nada do driver vaza
    assert registros_de_consulta()[0]["situacao"] == "erro"
    e = eventos(marco, "ia.erro")
    assert [x["detalhes"]["tipo"] for x in e] == ["dw_indisponivel"]


def test_contrato_divergente_no_dw_tambem_e_indisponivel(client, usuario_ia, ia_dw, monkeypatch):
    catalogo = {m: dw_falso._catalogo_do_contrato(m) for m in ("rec", "exp")}
    catalogo["rec"]["NK_CALENDARIO"] = "VARCHAR2"
    ia_dw(catalogo=catalogo)
    usar_roteiro(monkeypatch, Roteiro([consulta()]))
    r = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")
    assert r["estado"] == "indisponivel" and "NK_CALENDARIO" not in str(r)
