"""Volumetria de catering — o que se prova SEM o banco da nuvem-ia.

Este arquivo roda na suíte normal (SQLite, sem Postgres). Cobre:

- o contrato do módulo com o Hub: permissão no catálogo, app no seed (a célula
  `exportar` da matriz existe), router registrado, migration 0007 sobe e desce;
- as guardas: 401 sem login, 403 sem `ver`, 403 sem `exportar` — provadas SEM
  banco externo, porque a guarda vem antes da conexão;
- a falha graciosa: sem `VOLUMETRIA_DB_URL` (ou com banco fora do ar) o card
  responde 503 e `/api/health` continua 200;
- filtro inválido é 400 antes de qualquer conexão;
- a lógica pura portada da nuvem-ia (recorte, rótulos, contrato, formatação do
  CSV) e a comparação de drift (`schema.comparar`, que é pura de propósito);
- a auditoria no banco do Hub.

O SQL de verdade (Matriz, planilha, download, drift contra `information_schema`)
está em `test_volumetria_catering_postgres.py`, que exige o Postgres de teste
(ver docs/EXECUCAO_LOCAL.md) e é pulado quando ele não existe.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import inspect

from backend.core import permissoes as catalogo
from backend.core.database import _alembic_config, engine
from backend.volumetria_catering import auditoria, conexao, contrato, download, recorte, schema
from backend.volumetria_catering.permissoes import APP_SLUG, EXPORTAR

BASE = "/api/volumetria-catering"
JAN = {"de": "2026-01-01", "ate": "2026-01-31"}


@pytest.fixture(autouse=True)
def _sem_banco_externo(monkeypatch):
    """Nenhum teste daqui fala com Postgres: a variável sai do ambiente e o
    cache do contrato é zerado, para um teste não herdar estado de outro."""
    monkeypatch.delenv(conexao.ENV_URL, raising=False)
    schema.invalidar()
    yield
    schema.invalidar()


# ============ Contrato com o Hub: catálogo, seed, router ============

def test_permissao_exportar_esta_no_catalogo():
    assert catalogo.existe(EXPORTAR)
    p = catalogo.obter(EXPORTAR)
    assert p.app_slug == APP_SLUG
    assert p.acao == "exportar"
    assert p.modulo == "Volumetria de Catering"
    assert p.descricao
    # só `exportar`: consultar é `ver`, que é implícita
    assert catalogo.acoes_por_app()[APP_SLUG] == ["exportar"]


def test_app_esta_no_seed_e_a_matriz_tem_a_celula_exportar(client, admin_headers):
    m = client.get("/api/admin/matriz", headers=admin_headers).json()
    apps = {a["slug"]: a for s in m["secoes"] for a in s["apps"]}
    assert apps[APP_SLUG]["acoes"] == ["ver", "exportar"]
    assert m["orfas"] == []


def test_app_do_seed_e_indicador_embutido(client, admin_headers):
    home = client.get("/api/portal/home", headers=admin_headers).json()
    app = next(a for a in home["indicadores"] if a["slug"] == APP_SLUG)
    assert app["tipo_acesso"] == "iframe"
    assert app["url"] == "/volumetria-catering/"


def test_nenhuma_role_do_seed_ve_o_card(client, operador_headers, analista_headers):
    """Até a tela existir (H2), só admin enxerga o card — o seed não concede
    `ver` a ninguém. A URL ainda responde 404, então mostrar seria pior."""
    for headers in (operador_headers, analista_headers):
        home = client.get("/api/portal/home", headers=headers).json()
        assert APP_SLUG not in {a["slug"] for a in home["indicadores"]}


def test_migration_0007_criou_a_tabela_de_auditoria():
    insp = inspect(engine)
    assert insp.has_table("volumetria_downloads")
    colunas = {c["name"] for c in insp.get_columns("volumetria_downloads")}
    assert {"usuario", "formato", "recorte", "linhas", "status", "erro", "ip"} <= colunas


def test_migration_0007_sobe_e_desce(tmp_path):
    url = f"sqlite:///{(tmp_path / 'updown.db').as_posix()}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0006")
    command.upgrade(cfg, "head")


# ============ Falha graciosa: só o card degrada ============

def test_sem_url_o_card_responde_503_e_o_hub_continua(client, admin_headers):
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 503
    assert conexao.ENV_URL in r.json()["detail"]
    assert client.get("/api/health").status_code == 200


def test_banco_fora_do_ar_e_503_sem_vazar_a_url(client, admin_headers, monkeypatch):
    # porta 1: recusa imediata, não depende de nada instalado
    monkeypatch.setenv(conexao.ENV_URL, "postgresql://u:segredo@127.0.0.1:1/x")
    r = client.get(f"{BASE}/matriz", params=JAN, headers=admin_headers)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "não respondeu" in detail
    assert "segredo" not in detail and "127.0.0.1" not in detail
    assert client.get("/api/health").status_code == 200


def test_download_nao_abre_auditoria_quando_o_banco_esta_fora(client, admin_headers, monkeypatch):
    """A conferência do banco vem ANTES de abrir a auditoria: registro de
    download que não saiu é ruído na trilha."""
    monkeypatch.setenv(conexao.ENV_URL, "postgresql://u:s@127.0.0.1:1/x")
    antes = len(auditoria.listar(1000))
    r = client.get(f"{BASE}/download", params=JAN, headers=admin_headers)
    assert r.status_code == 503
    assert len(auditoria.listar(1000)) == antes


# ============ Guardas (vêm antes da conexão) ============

@pytest.mark.parametrize("rota", ["/opcoes", "/matriz", "/planilha", "/download", "/auditoria"])
def test_sem_login_401(client, rota):
    assert client.get(f"{BASE}{rota}", params=JAN).status_code == 401


@pytest.mark.parametrize("rota", ["/opcoes", "/matriz", "/planilha"])
def test_consulta_sem_ver_403(client, analista_headers, rota):
    r = client.get(f"{BASE}{rota}", params=JAN, headers=analista_headers)
    assert r.status_code == 403
    assert f"{APP_SLUG}:ver" in r.json()["detail"]


def test_download_sem_exportar_403_mesmo_com_ver(client, admin_headers):
    """`ver` libera a consulta; baixar é outra célula da matriz."""
    r = client.post(
        "/api/admin/roles",
        json={"slug": "vol-so-ver", "nome": "Vol — só ver", "apps": [APP_SLUG]},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/admin/usuarios",
        json={"username": "vol.leitor", "senha": "senha-de-teste-123", "roles": ["vol-so-ver"]},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    token = client.post(
        "/api/auth/login", data={"username": "vol.leitor", "password": "senha-de-teste-123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # passa pela guarda de `ver` (e para no banco ausente: 503, não 403)
    assert client.get(f"{BASE}/opcoes", headers=headers).status_code == 503
    r = client.get(f"{BASE}/download", params=JAN, headers=headers)
    assert r.status_code == 403
    assert EXPORTAR in r.json()["detail"]


def test_auditoria_so_admin(client, operador_headers, admin_headers):
    assert client.get(f"{BASE}/auditoria", headers=operador_headers).status_code == 403
    assert client.get(f"{BASE}/auditoria", headers=admin_headers).status_code == 200


# ============ Filtro inválido é 400, antes de qualquer conexão ============

# As mensagens do recorte são ASCII (convenção herdada da nuvem-ia): os trechos
# abaixo casam com o texto exato.
@pytest.mark.parametrize("params, trecho", [
    ({"de": "2026-13-01", "ate": "2026-01-31"}, "nao e uma data que existe"),
    ({"de": "01/01/2026", "ate": "2026-01-31"}, "AAAA-MM-DD"),
    ({"de": "2026-02-01", "ate": "2026-01-31"}, "periodo invertido"),
    ({**JAN, "movimento": "xyz"}, "movimento"),
    ({**JAN, "lente": "kg"}, "lente"),
    ({**JAN, "faixa": "entregue"}, "faixa"),
    ({**JAN, "dia": "abc"}, "nao e um numero"),
    ({**JAN, "dia": "32"}, "fora de 1..31"),
    ({**JAN, "movimento": "amb", "operacao": "SAIDA NORMAL"}, "operacao nao vale"),
])
def test_filtro_invalido_e_400_sem_tocar_no_banco(client, admin_headers, params, trecho):
    r = client.get(f"{BASE}/matriz", params=params, headers=admin_headers)
    assert r.status_code == 400, r.text
    assert trecho in r.json()["detail"]


@pytest.mark.parametrize("rota", ["/planilha", "/download"])
def test_visao_conjunta_e_so_da_matriz(client, admin_headers, rota):
    r = client.get(f"{BASE}{rota}", params={**JAN, "movimento": "amb"}, headers=admin_headers)
    assert r.status_code == 400
    assert "um movimento por vez" in r.json()["detail"]


def test_download_formato_desconhecido_400(client, admin_headers):
    r = client.get(f"{BASE}/download", params={**JAN, "formato": "pdf"}, headers=admin_headers)
    assert r.status_code == 400


# ============ Lógica pura portada da nuvem-ia ============

def test_dias_do_filtro_normaliza_ordena_e_deduplica():
    assert recorte.dias_do_filtro(("3", " 1", "1", 31)) == (1, 3, 31)
    assert recorte.dias_do_filtro(()) == ()
    with pytest.raises(recorte.FiltroInvalido):
        recorte.dias_do_filtro(("0",))
    with pytest.raises(recorte.FiltroInvalido):
        recorte.dias_do_filtro(("x",))


def test_rotulos_dos_meses_declaram_as_pontas_parciais():
    assert recorte.rotulos_dos_meses("2026-08-03", "2026-09-05") == {
        "2026-08": "2026-08 (03-31)",
        "2026-09": "2026-09 (01-05)",
    }
    # mês inteiro sai sem parênteses: anotar o óbvio treina a ignorar a anotação
    assert recorte.rotulos_dos_meses("2026-01-01", "2026-02-28") == {
        "2026-01": "2026-01", "2026-02": "2026-02",
    }


def test_meses_do_periodo_inclui_mes_vazio():
    assert recorte.meses_do_periodo("2025-11-15", "2026-02-01") == [
        "2025-11", "2025-12", "2026-01", "2026-02",
    ]


def test_rotulo_dos_dias_em_faixas():
    assert recorte.rotulo_dos_dias((1, 3, 4, 5, 9)) == "01, 03 a 05, 09"
    assert recorte.rotulo_dos_dias(range(4, 32)) == "04 a 31"
    assert recorte.rotulo_dos_dias((7, 8)) == "07, 08"
    assert recorte.rotulo_dos_dias(()) == ""
    assert recorte.aviso_dos_dias(()) is None
    assert "01, 03 a 05, 09" in recorte.aviso_dos_dias((1, 3, 4, 5, 9))


def test_data_do_recorte_e_estrita():
    assert recorte.data_do_recorte("2026-01-05") == date(2026, 1, 5)
    with pytest.raises(recorte.FiltroInvalido):
        recorte.data_do_recorte("20260105")  # o fromisoformat aceitaria; a tela não manda
    with pytest.raises(recorte.FiltroInvalido):
        recorte.data_do_recorte("2026-02-30")


def test_recorte_de_dois_movimentos_nao_escolhe_tabela_em_silencio():
    filtros = recorte.Filtros(**JAN, movimento=recorte.CONJUNTA).validar()
    with pytest.raises(recorte.FiltroInvalido):
        recorte.de_para_where(filtros)
    assert "cat_fato_recebimento" in recorte.de_para_where(filtros, "rec")[0]
    assert "cat_fato_expedicao" in recorte.de_para_where(filtros, "exp")[0]


def test_o_terceiro_movimento_e_da_tela_e_nao_do_dado():
    assert recorte.CONJUNTA not in contrato.MOVIMENTOS
    assert set(contrato.MOVIMENTOS) < set(recorte.MOVIMENTOS_DA_TELA)
    assert recorte.movimentos_do_recorte(recorte.CONJUNTA) == ("rec", "exp")
    assert recorte.CONJUNTA not in recorte.TABELA


def test_medida_confere_contra_o_contrato():
    assert recorte.medida("rec", "liq", "solicitado") == "qtde_peso2"
    assert recorte.medida("exp", "liq", "atendido") == "qtde_peso_atendido"
    assert recorte.medida("exp", "pal", "solicitado") is None  # pallet só na entrada
    assert recorte.medidas_da_lente("exp", "pal") == {}
    assert recorte.medidas_da_lente("rec", "vol") == {"": "qtde_vol2"}
    assert list(recorte.medidas_da_lente("exp", "val")) == list(contrato.FAIXAS)


def test_todo_valor_de_filtro_vai_parametrizado():
    filtros = recorte.Filtros(
        **JAN, unidades=("RMSPII'; DROP TABLE x; --",), clientes=("1",),
        tipos_estoque=("SECO",), operacoes=("OP",), dias=("5",),
    ).validar()
    sql, params = recorte.de_para_where(filtros)
    assert "DROP TABLE" not in sql
    assert params["unidades"] == ["RMSPII'; DROP TABLE x; --"]
    assert params["dias"] == [5]
    assert params["de"] == date(2026, 1, 1)


def test_contrato_tem_36_e_46_colunas():
    assert len(contrato.COLUNAS_REC) == 36
    assert len(contrato.COLUNAS_EXP) == 46
    nomes_rec = {n for n, _t, _n in contrato.COLUNAS_REC}
    nomes_exp = {n for n, _t, _n in contrato.COLUNAS_EXP}
    assert set(contrato.CHAVE_NATURAL) <= nomes_rec & nomes_exp
    assert contrato.IDENTIFICADORES_TEXTO <= nomes_rec & nomes_exp
    for lente, d in contrato.LENTES.items():
        assert d["rec"] in nomes_rec
        for faixa in contrato.FAIXAS:
            coluna = contrato.coluna_exp(lente, faixa)
            assert coluna is None or coluna in nomes_exp


def test_abertura_e_fuso_falham_nomeando_a_variavel(monkeypatch):
    hoje = date(2026, 8, 27)
    assert contrato.abertura_de(hoje) == date(2026, 1, 1)
    monkeypatch.setenv(contrato.ENV_ABERTURA_DE, "2025-06-01")
    assert contrato.abertura_de(hoje) == date(2025, 6, 1)
    monkeypatch.setenv(contrato.ENV_ABERTURA_DE, "junho")
    with pytest.raises(contrato.AberturaInvalida, match=contrato.ENV_ABERTURA_DE):
        contrato.abertura_de(hoje)

    assert contrato.fuso_exibicao() == "America/Sao_Paulo"
    monkeypatch.setenv(contrato.ENV_FUSO_EXIBICAO, "America/SaoPaulo")
    with pytest.raises(contrato.FusoInvalido, match=contrato.ENV_FUSO_EXIBICAO):
        contrato.fuso_exibicao()


def test_nome_do_arquivo_declara_movimento_periodo_e_dias():
    f = recorte.Filtros(de="2026-01-01", ate="2026-08-31", movimento="exp").validar()
    assert download.nome_do_arquivo(f, "csv") == "catering_saida_2026-01-01_a_2026-08-31.csv"
    f = recorte.Filtros(de="2026-01-01", ate="2026-08-31", dias=("1",)).validar()
    assert download.nome_do_arquivo(f, "xlsx") == "catering_entrada_2026-01-01_a_2026-08-31_dias.xlsx"


def test_para_csv_e_excel_first():
    assert download._para_csv(None) == ""
    assert download._para_csv(Decimal("100.500")) == "100,500"
    assert download._para_csv(date(2026, 1, 5)) == "05/01/2026"
    assert download._para_csv(datetime(2026, 1, 5, 9, 45, 0)) == "05/01/2026 09:45:00"
    assert download._para_csv(True) == "1"
    assert download._para_csv("0000000609") == "0000000609"


def test_download_leva_derivadas_e_o_contrato_inteiro():
    apelidos = [a for a, _s, _r in download.colunas("rec")]
    assert apelidos[:4] == ["dia", "unidade", "cliente", "tipo_estoque"]
    assert apelidos[4:] == [n for n, _t, _n in contrato.COLUNAS_REC]
    assert len(download.colunas("exp")) == 4 + 46


# ============ Drift: a comparação é pura e nomeia a coluna ============

_TIPO = {
    "INTEGER": ("integer", None, None),
    "SMALLINT": ("smallint", None, None),
    "TEXT": ("text", None, None),
    "DATE": ("date", None, None),
    "TIMESTAMP": ("timestamp without time zone", None, None),
    "NUMERIC(18,3)": ("numeric", 18, 3),
}


def _retrato_fiel():
    """Um `information_schema` sintético exatamente como o contrato descreve."""
    reais = {}
    for movimento, tabela in schema.TABELA_FATO.items():
        colunas = {
            "id": ("bigint", False, 64, 0),
            "carga_id": ("integer", False, 32, 0),
        }
        for nome, tipo, nulavel in contrato.colunas(movimento):
            dt, p, e = _TIPO[tipo]
            colunas[nome] = (dt, nulavel, p, e)
        reais[tabela] = colunas
    for tabela, colunas in schema.COLUNAS_DE_APOIO.items():
        reais[tabela] = {c: ("text", True, None, None) for c in colunas}
    return reais


def test_retrato_fiel_nao_tem_drift():
    assert schema.comparar(_retrato_fiel()) == []


def test_drift_coluna_faltando_nomeia_tabela_e_coluna():
    reais = _retrato_fiel()
    del reais["cat_fato_recebimento"]["qtde_pbrt2"]
    problemas = schema.comparar(reais)
    assert problemas == ["cat_fato_recebimento.qtde_pbrt2: coluna do contrato não existe no banco"]


def test_drift_coluna_a_mais_e_drift():
    """Coluna nova na nuvem-ia sem contrato aqui é justamente o que o download
    deixaria de levar — tem que gritar."""
    reais = _retrato_fiel()
    reais["cat_fato_expedicao"]["qtde_nova"] = ("integer", True, 32, 0)
    assert schema.comparar(reais) == [
        "cat_fato_expedicao.qtde_nova: coluna existe no banco e não está no contrato copiado"
    ]


def test_drift_tipo_precisao_e_nulabilidade():
    reais = _retrato_fiel()
    reais["cat_fato_recebimento"]["qtde_sku"] = ("bigint", True, 64, 0)
    reais["cat_fato_recebimento"]["qtde_vlr"] = ("numeric", True, 12, 2)
    reais["cat_fato_recebimento"]["nk_cliente"] = ("text", True, None, None)
    problemas = schema.comparar(reais)
    assert "cat_fato_recebimento.qtde_sku: tipo esperado INTEGER, banco tem bigint" in problemas
    assert "cat_fato_recebimento.qtde_vlr: esperado NUMERIC(18,3), banco tem NUMERIC(12,2)" in problemas
    assert "cat_fato_recebimento.nk_cliente: contrato diz NOT NULL, banco diz nulável" in problemas
    assert len(problemas) == 3


def test_drift_tabela_de_apoio_sumiu_ou_sem_grant():
    """`information_schema` esconde tabela em que o role não tem SELECT, então
    GRANT faltando no `hub_leitura` (lote H3) aparece igual a tabela ausente —
    a mensagem tem que nomear as duas causas."""
    reais = _retrato_fiel()
    del reais["cat_cargas"]
    del reais["cat_unidades"]["sigla"]
    problemas = schema.comparar(reais)
    assert "cat_cargas: tabela não existe ou o role da conexão não tem SELECT nela" in problemas
    assert "cat_unidades.sigla: coluna usada pela consulta não existe" in problemas


def test_configuracao_invalida_e_503_nomeando_a_variavel(client, admin_headers, monkeypatch):
    """Fuso escrito errado no .env da VM não pode virar 500 genérico: a mensagem
    do contrato existe para chegar em quem escreveu a variável."""
    monkeypatch.setenv(contrato.ENV_FUSO_EXIBICAO, "America/SaoPaulo")
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 503
    assert contrato.ENV_FUSO_EXIBICAO in r.json()["detail"]
    assert "America/SaoPaulo" in r.json()["detail"]


def test_url_malformada_e_503_e_nao_500(client, admin_headers, monkeypatch):
    monkeypatch.setenv(conexao.ENV_URL, "isto nao e uma url")
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 503
    assert "não respondeu" in r.json()["detail"]


def test_contrato_divergente_aponta_para_a_correcao():
    erro = schema.ContratoDivergente(["cat_fato_recebimento.x: sumiu"])
    assert "cat_fato_recebimento.x" in str(erro)
    assert contrato.ORIGEM in str(erro)
    assert "contrato.py" in str(erro)


# ============ Auditoria no banco do Hub ============

def test_auditoria_abre_fecha_e_falha(client, admin_headers):
    recorte_dict = {**JAN, "movimento": "rec", "unidades": ["RMSPII"], "dias": [5]}
    aberto = auditoria.abrir(recorte_dict, "csv", ip="10.0.0.1", usuario="admin")
    auditoria.fechar(aberto, 42)
    falho = auditoria.abrir(recorte_dict, "xlsx", ip=None, usuario="admin")
    auditoria.falhar(falho, RuntimeError("conexão caiu"))

    por_id = {r["id"]: r for r in auditoria.listar(1000)}
    assert por_id[aberto]["status"] == "ok"
    assert por_id[aberto]["linhas"] == 42
    assert por_id[aberto]["recorte"] == recorte_dict  # o recorte volta inteiro
    assert por_id[aberto]["terminado_em"]
    assert por_id[falho]["status"] == "erro"
    assert "conexão caiu" in por_id[falho]["erro"]
    assert por_id[falho]["linhas"] is None

    # mais recente primeiro, e a API devolve o mesmo
    api = client.get(f"{BASE}/auditoria", params={"limite": 2}, headers=admin_headers).json()
    assert [r["id"] for r in api] == [falho, aberto]


def test_auditoria_recusa_formato_fora_do_escopo():
    with pytest.raises(ValueError):
        auditoria.abrir({}, "pdf")
