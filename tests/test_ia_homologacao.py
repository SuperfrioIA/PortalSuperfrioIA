"""O roteiro de homologação (`scripts/homologar_ia.py`) provado em processo, sem rede.

Na DEV quem roda é a Duda; aqui o mesmo código roda contra o Hub de teste (DW sintético, provedor
falso) por um adaptador de HTTP sobre o TestClient. Prova a LÓGICA dos passos, inclusive que ele
falha quando deve. NÃO prova nada sobre a VM de DEV, o provedor real nem o DW real.
"""
import argparse
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest
import yaml

import dw_falso
from backend.ia import service

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "homologar_ia.py"
SENHA = "senha-de-teste-123"


@pytest.fixture(scope="module")
def hom():
    spec = importlib.util.spec_from_file_location("homologar_ia", SCRIPT)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class HttpDeTeste:
    """Mesma interface do `Http` real, sobre o TestClient do Hub."""

    def __init__(self, client):
        self.client = client

    def pedir(self, metodo, caminho, corpo=None, token=None, form=None):
        r = self.client.request(metodo, caminho, json=corpo if form is None else None, data=form,
                                headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None


def _args(**mudar):
    base = dict(usuario="", admin_usuario="admin", sem_concessao_usuario="", passos="",
                pergunta="Quanto de peso líquido entrou em agosto de 2026?", gabarito="", exigir_provedor="")
    return argparse.Namespace(**{**base, **mudar})


def _senhas(usuario="admin123"):
    return lambda quem: {"usuario": SENHA, "admin": "admin123", "sem": SENHA}[quem]


def _rodar(hom, client, usuario_ia, sem=None, **mudar):
    args = _args(usuario=usuario_ia["username"], sem_concessao_usuario=sem["username"] if sem else "", **mudar)
    return hom.executar(HttpDeTeste(client), args, _senhas())


def _situacoes(passos):
    return {p.nome: p.situacao for p in passos}


# ============================================================ o caminho feliz
def test_todos_os_passos_automaticos_passam_contra_o_hub_de_teste(hom, client, usuario_ia, criar_usuario_ia):
    sem = criar_usuario_ia("semconcessao")
    passos, ctx = _rodar(hom, client, usuario_ia, sem)
    assert _situacoes(passos) == {"saude": "PASSOU", "dominios": "PASSOU", "pergunta": "PASSOU",
                                  "sem-concessao": "PASSOU", "revogacao": "PASSOU", "auditoria": "PASSOU",
                                  "gabarito": "PULADO"}, [(p.nome, p.evidencias) for p in passos]
    assert ctx["provedor"] == "falso"


def test_a_revogacao_vale_na_hora_e_o_usuario_volta_a_perguntar_depois_de_novo_pedido(hom, client, usuario_ia):
    passos, _ = _rodar(hom, client, usuario_ia, passos="dominios,revogacao")
    revogacao = next(p for p in passos if p.nome == "revogacao")
    assert revogacao.situacao == "PASSOU"
    texto = " ".join(revogacao.evidencias)
    assert "revogar -> 200" in texto and "-> 403 (esperado 403" in texto and "depois de aprovar de novo -> 200" in texto


def test_o_provedor_exigido_precisa_ser_o_que_o_hub_usa(hom, client, usuario_ia):
    passos, _ = _rodar(hom, client, usuario_ia, passos="dominios", exigir_provedor="anthropic")
    assert _situacoes(passos)["dominios"] == "FALHOU" and "esperava o provedor anthropic" in " ".join(passos[0].evidencias)


# =============================================================== os que falham
def test_senha_errada_falha_no_login_sem_rodar_mais_nada(hom, client, usuario_ia):
    args = _args(usuario=usuario_ia["username"])
    passos, _ = hom.executar(HttpDeTeste(client), args, lambda quem: "senha-errada")
    assert [p.nome for p in passos] == ["login"] and passos[0].situacao == "FALHOU"


def test_o_passo_pergunta_falha_se_a_resposta_traz_o_gasto_do_provedor(hom, client, usuario_ia, monkeypatch):
    monkeypatch.setattr(service, "_meta_publica", lambda meta: dict(meta, uso={"custo_brl": "1.0"}))
    passos, _ = _rodar(hom, client, usuario_ia, passos="pergunta")
    assert passos[0].situacao == "FALHOU" and "traz `uso`" in " ".join(passos[0].evidencias)


def test_o_passo_pergunta_falha_se_o_texto_nao_repete_o_quadro_do_hub(hom, client, usuario_ia, monkeypatch):
    monkeypatch.setattr(service, "perguntar", lambda *a, **k: {
        "estado": "ok", "conversa_id": 1,
        "mensagem": {"id": 1, "papel": "ia", "texto": "Foram 1,0 t.", "meta": {"provedor": "x"},
                     "blocos": [{"tipo": "tiles", "itens": [{"n": "9.999,9 t", "l": "x"}]}]}})
    passos, _ = _rodar(hom, client, usuario_ia, passos="pergunta")
    assert passos[0].situacao == "FALHOU" and "nenhum número do texto é o do quadro" in " ".join(passos[0].evidencias)


def test_usuario_sem_concessao_e_recusado_com_mensagem_neutra(hom, client, usuario_ia, criar_usuario_ia):
    sem = criar_usuario_ia("semconcessao")
    passos, _ = _rodar(hom, client, usuario_ia, sem, passos="sem-concessao")
    assert passos[0].situacao == "PASSOU" and "recusado com 403" in " ".join(passos[0].evidencias)


class _TrilhaFabricada:
    """Resposta de auditoria montada à mão: a trilha de verdade é imutável e compartilhada pela
    sessão, e um evento 'ruim' gravado aqui contaminaria os outros testes."""

    def __init__(self, eventos):
        self.eventos = eventos

    def pedir(self, metodo, caminho, corpo=None, token=None, form=None):
        return 200, {"itens": self.eventos, "total": len(self.eventos)}


def test_a_auditoria_reprova_evento_que_guarda_texto(hom):
    eventos = [{"acao": "ia.pergunta", "detalhes": {"dominio": "x", "pergunta": "quanto entrou?"}},
               {"acao": "ia.consulta", "detalhes": {}}, {"acao": "ia.resposta", "detalhes": {}}]
    p = hom.passo_auditoria(_TrilhaFabricada(eventos), {"token_admin": "t"}).fim()
    assert p.situacao == "FALHOU" and "campo de texto" in " ".join(p.evidencias)


def test_a_auditoria_reprova_quando_falta_um_evento_esperado(hom):
    eventos = [{"acao": "ia.pergunta", "detalhes": {}}, {"acao": "ia.resposta", "detalhes": {}}]
    p = hom.passo_auditoria(_TrilhaFabricada(eventos), {"token_admin": "t"}).fim()
    assert p.situacao == "FALHOU" and "ia.consulta AUSENTE" in " ".join(p.evidencias)


def test_a_auditoria_passa_com_os_eventos_sem_texto(hom):
    eventos = [{"acao": a, "detalhes": {"dominio": "x", "hash": "abc"}} for a in ("ia.pergunta", "ia.consulta", "ia.resposta")]
    assert hom.passo_auditoria(_TrilhaFabricada(eventos), {"token_admin": "t"}).fim().situacao == "PASSOU"


# ================================================================== o gabarito
def _gabarito(tmp_path, tela):
    arquivo = tmp_path / "gabarito.yaml"
    arquivo.write_text(yaml.safe_dump([
        {"id": "G01", "pergunta": "Quanto de peso líquido entrou em agosto de 2026?", "tela": tela},
        {"id": "G02", "pergunta": "Qual a movimentação?", "tela": ""}], allow_unicode=True), encoding="utf-8")
    return str(arquivo)


def test_gabarito_confere_o_numero_da_tela_com_o_da_resposta(hom, client, usuario_ia, tmp_path):
    certo = f"{dw_falso.pt_br(dw_falso.soma_t(['2026-08']), 1)} t"
    passos, _ = _rodar(hom, client, usuario_ia, passos="gabarito", gabarito=_gabarito(tmp_path, certo))
    assert passos[0].situacao == "PASSOU" and f"G01: tela = IA ({certo})" in passos[0].evidencias[0]
    assert not any("G02" in e for e in passos[0].evidencias), "entrada sem `tela` não conta"


def test_gabarito_reprova_quando_a_tela_mostra_outro_numero(hom, client, usuario_ia, tmp_path):
    passos, _ = _rodar(hom, client, usuario_ia, passos="gabarito", gabarito=_gabarito(tmp_path, "1,0 t"))
    assert passos[0].situacao == "FALHOU" and "a tela mostra 1,0 t" in " ".join(passos[0].evidencias)


def test_gabarito_vazio_nao_passa_em_branco(hom, client, usuario_ia, tmp_path):
    passos, _ = _rodar(hom, client, usuario_ia, passos="gabarito", gabarito=_gabarito(tmp_path, ""))
    assert passos[0].situacao == "FALHOU" and "nenhuma entrada com `tela` preenchida" in " ".join(passos[0].evidencias)


# =============================================================== relatório e travas
def test_o_relatorio_nao_tem_senha_token_nem_texto_de_pergunta(hom, client, usuario_ia, criar_usuario_ia):
    sem = criar_usuario_ia("semconcessao")
    passos, ctx = _rodar(hom, client, usuario_ia, sem)
    texto = hom.relatorio("https://dev.exemplo.interno", ctx, passos)
    assert SENHA not in texto and "admin123" not in texto and "Bearer" not in texto
    assert _args().pergunta not in texto and "Quanto de peso" not in texto
    assert "dev.exemplo.interno" in texto and "**PASSOU**" in texto
    assert "Passos PULADOS não foram verificados" in texto


def test_o_relatorio_diz_nao_aprovado_quando_algum_passo_falha(hom):
    p = hom.Passo("pergunta")
    p.falha("x")
    texto = hom.relatorio("http://x", {}, [p.fim()])
    assert "**NÃO aprovado**: falharam pergunta" in texto


def test_passo_desligar_so_roda_em_terminal_interativo(hom, client, usuario_ia):
    passos, _ = _rodar(hom, client, usuario_ia, passos="dominios,desligar")
    assert _situacoes(passos)["desligar"] == "PULADO"


def test_passo_desconhecido_e_recusado(hom, client, usuario_ia):
    with pytest.raises(SystemExit, match="passos desconhecidos"):
        _rodar(hom, client, usuario_ia, passos="saude,inventado")


def test_o_script_exige_confirmar_que_o_alvo_e_ambiente_de_teste():
    r = subprocess.run([sys.executable, str(SCRIPT), "--url", "http://x.interno", "--usuario", "u"], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8", timeout=60,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 2 and "--confirmo-ambiente-de-teste" in r.stderr


def test_o_script_recusa_url_que_nao_e_http(hom):
    r = subprocess.run([sys.executable, str(SCRIPT), "--url", "ftp://x", "--confirmo-ambiente-de-teste", "--usuario", "u"],
                       cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode != 0 and "URL inválida" in (r.stderr + r.stdout)


def test_senha_nunca_e_argumento_e_o_script_so_fala_http():
    fonte = SCRIPT.read_text(encoding="utf-8")
    assert "--senha" not in fonte and "--password" not in fonte
    for proibido in ("subprocess", "paramiko", "ssh ", "docker ", "psycopg", "oracledb", "sqlalchemy"):
        assert proibido not in fonte.replace("`docker compose up -d`", ""), proibido
    assert "getpass.getpass" in fonte and "IA_HOMOLOG_SENHA" in fonte
