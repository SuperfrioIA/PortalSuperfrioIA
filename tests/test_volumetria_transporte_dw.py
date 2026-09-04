"""Volumetria de transporte — contrato, recorte, Matriz/planilha/download e a
conexão com o DW Oracle.

## O limite desta suíte

**Nenhum teste daqui conecta no DW.** Tudo roda contra `CursorFalso`/
`ConexaoFalsa`, no mesmo padrão de `tests/test_volumetria_catering_dw.py`.

**Diferença importante em relação ao catering**: lá, `matriz.py`/`planilha.py`/
`download.py` ainda leem o Postgres (`nuvem-db`), e por isso têm suíte própria
contra um container real (`test_volumetria_catering_postgres.py`). Aqui não —
este módulo nasce lendo o DW direto, sem o D3 do outro plano (que provaria a
tradução do SQL comparando Postgres × Oracle). Por isso as consultas de
Matriz/planilha/download são testadas **contra cursor falso**: prova o SQL, os
binds e o mapeamento de linha, não prova que o DW aceita o statement. O
aceite de dado real é `/diagnostico-dw` na VM (mesmo texto do D1).

## Duas guardas de somente leitura

Mesmo desenho do catering: **estática** (nenhum literal com palavra de
escrita, nenhuma chamada a `commit`/`rollback`/`executemany`) e **de runtime**
(`CursorFalso` estoura em qualquer `execute` que não comece por `SELECT`).
"""

import ast
import pathlib
import re

import pytest

from backend.volumetria_transporte import (
    conexao_dw,
    contrato,
    download,
    matriz,
    planilha,
    recorte,
    router,
    schema_dw,
)

BASE = "/api/volumetria-transporte"
DIAG = f"{BASE}/diagnostico-dw"

TIPO_NO_DW = {
    "TEXT": "VARCHAR2", "INTEGER": "NUMBER", "NUMERIC": "NUMBER",
    "DATE": "DATE", "TIMESTAMP": "DATE",
}


def catalogo_do_contrato(**sobrescritas):
    tipos = {
        contrato.coluna_dw(nome): TIPO_NO_DW[tipo]
        for nome, tipo, _nulo in contrato.COLUNAS_SELECT
    }
    tipos.update(sobrescritas)
    return tipos


# ------------------------------------------------------------ driver falso
class CursorFalso:
    """Execute/fetchall/fetchone/description/arraysize — só o que os módulos
    usam. `resultados` é uma fila: cada `execute()` consome o próximo item."""

    def __init__(self, conexao, resultados=None, descricao=None):
        self.conexao = conexao
        self.arraysize = 100
        self.prefetchrows = 101
        self._fila = list(resultados or [])
        self._resultado = []
        self.description = descricao or []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        return iter(self._resultado)

    def execute(self, sql, binds=None):
        self.conexao.executados.append((sql, dict(binds or {})))
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError(f"comando que não é leitura: {sql!r}")
        if self.conexao.erro is not None:
            raise self.conexao.erro
        if "ALL_TAB_COLUMNS" in sql:
            tabela = binds["tabela"]
            self._resultado = list(self.conexao.catalogo.get(tabela, {}).items())
        elif self._fila:
            self._resultado = self._fila.pop(0)
        else:
            self._resultado = []

    def fetchall(self):
        return list(self._resultado)

    def fetchone(self):
        return self._resultado[0] if self._resultado else None


class ConexaoFalsa:
    def __init__(self, catalogo=None, erro=None, resultados=None, descricao=None):
        self.catalogo = catalogo if catalogo is not None else _CATALOGO_BOM
        self.erro = erro
        self.executados = []
        self.fechada = False
        self._resultados = resultados
        self._descricao = descricao

    def cursor(self):
        return CursorFalso(self, resultados=self._resultados, descricao=self._descricao)

    def close(self):
        self.fechada = True


def _tabela_curta():
    return contrato.tabela().partition(".")[2]


_CATALOGO_BOM = {_tabela_curta(): catalogo_do_contrato()}


class DriverFalso:
    class _Defaults:
        fetch_decimals = False

    def __init__(self, conexao=None, erro=None):
        self.defaults = self._Defaults()
        self.conexao = conexao or ConexaoFalsa()
        self.erro = erro
        self.chamadas = []

    def connect(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.erro is not None:
            raise self.erro
        return self.conexao


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    for var in (
        conexao_dw.ENV_USUARIO, conexao_dw.ENV_SENHA, conexao_dw.ENV_HOST,
        conexao_dw.ENV_PORTA, conexao_dw.ENV_SERVICO, contrato.ENV_TABELA,
    ):
        monkeypatch.delenv(var, raising=False)
    schema_dw.invalidar()
    router._cache_opcoes.update({"dados": None, "expira_em": 0.0})
    yield
    schema_dw.invalidar()
    router._cache_opcoes.update({"dados": None, "expira_em": 0.0})


@pytest.fixture
def com_credencial(monkeypatch):
    monkeypatch.setenv(conexao_dw.ENV_USUARIO, "hub_leitura_dw")
    monkeypatch.setenv(conexao_dw.ENV_SENHA, "senha-de-mentira")


@pytest.fixture
def driver(monkeypatch):
    falso = DriverFalso()
    monkeypatch.setattr(conexao_dw, "_driver", lambda: falso)
    return falso


# ============================================================== contrato
def test_tabela_tem_padrao_medido():
    assert contrato.tabela() == contrato.TABELA_PADRAO


def test_tabela_vem_de_configuracao(monkeypatch):
    monkeypatch.setenv(contrato.ENV_TABELA, "OUTRO_SCHEMA.OUTRA_TABELA")
    assert contrato.tabela() == "OUTRO_SCHEMA.OUTRA_TABELA"


def test_nome_de_objeto_invalido_nao_entra_no_sql(monkeypatch):
    monkeypatch.setenv(contrato.ENV_TABELA, "'; drop table x --")
    with pytest.raises(contrato.TabelaInvalida):
        contrato.tabela()


def test_coluna_dw_e_a_nossa_em_maiusculas_menos_a_pk():
    assert contrato.coluna_dw("pk_dw") == contrato.PK_DW
    assert contrato.coluna_dw("nk_wms_filial") == "NK_WMS_FILIAL"


def test_fora_nunca_aparece_no_select():
    nomes_select = {n for n, _t, _n in contrato.COLUNAS_SELECT}
    assert nomes_select.isdisjoint(contrato.FORA)
    assert "sk_cliente" in contrato.FORA
    assert "dw_processo" in contrato.FORA


def test_colunas_arquivo_nao_leva_o_que_e_so_interno():
    # dw_data_alteracao/nk_instancia/nk_empresa são "interno": nunca no arquivo
    assert "dw_data_alteracao" not in contrato.COLUNAS_ARQUIVO
    assert "nk_instancia" not in contrato.COLUNAS_ARQUIVO
    assert "raz_social" in contrato.COLUNAS_ARQUIVO  # tela também está no arquivo


def test_identificadores_texto_sao_colunas_do_contrato():
    nomes = {n for n, _t, _n, _d in contrato.COLUNAS}
    assert contrato.IDENTIFICADORES_TEXTO <= nomes


def test_abertura_de_ano_corrente(monkeypatch):
    from datetime import date
    monkeypatch.delenv(contrato.ENV_ABERTURA_DE, raising=False)
    assert contrato.abertura_de(date(2026, 9, 4)) == date(2026, 1, 1)


def test_abertura_de_invalida_nomeia_a_variavel(monkeypatch):
    monkeypatch.setenv(contrato.ENV_ABERTURA_DE, "não é data")
    from datetime import date
    with pytest.raises(contrato.AberturaInvalida):
        contrato.abertura_de(date(2026, 9, 4))


# ================================================================ recorte
def test_onde_periodo_simples():
    f = recorte.Filtros(de="2026-01-01", ate="2026-09-03").validar()
    clausulas, params = recorte.onde(f)
    assert clausulas == ["f.nk_calendario >= :de", "f.nk_calendario <= :ate"]
    assert params == {"de": recorte.data_do_recorte("2026-01-01"), "ate": recorte.data_do_recorte("2026-09-03")}


def test_onde_com_dias_e_unidades():
    f = recorte.Filtros(
        de="2026-01-01", ate="2026-09-03", dias=("5", "10"), unidades=("RMSPII", "RMRJ"),
    ).validar()
    clausulas, params = recorte.onde(f)
    assert any("EXTRACT(DAY FROM f.nk_calendario) IN" in c for c in clausulas)
    assert any(c.startswith("f.nk_wms_filial IN") for c in clausulas)
    assert params["dia0"] == 5 and params["dia1"] == 10
    assert {v for k, v in params.items() if k.startswith("uni")} == {"RMSPII", "RMRJ"}


def test_periodo_invertido_e_invalido():
    with pytest.raises(recorte.FiltroInvalido):
        recorte.Filtros(de="2026-09-03", ate="2026-01-01").validar()


def test_lente_fora_do_contrato_e_invalida():
    with pytest.raises(recorte.FiltroInvalido):
        recorte.Filtros(de="2026-01-01", ate="2026-01-31", lente="xyz").validar()


def test_dia_fora_de_1_31_e_invalido():
    with pytest.raises(recorte.FiltroInvalido):
        recorte.Filtros(de="2026-01-01", ate="2026-01-31", dias=("32",)).validar()


def test_rotulo_dos_meses_declara_ponta_parcial():
    rotulos = recorte.rotulos_dos_meses("2026-08-03", "2026-09-05")
    assert rotulos["2026-08"] == "2026-08 (03-31)"
    assert rotulos["2026-09"] == "2026-09 (01-05)"


def test_mes_inteiro_nao_ganha_parenteses():
    rotulos = recorte.rotulos_dos_meses("2026-08-01", "2026-08-31")
    assert rotulos["2026-08"] == "2026-08"


def test_placa_rotulo_normaliza_a_sentinela():
    assert contrato.PLACA_SENTINELA in recorte.PLACA_ROTULO
    assert contrato.PLACA_ROTULO_VAZIA in recorte.PLACA_ROTULO


def test_de_para_where_usa_a_tabela_do_contrato():
    f = recorte.Filtros(de="2026-01-01", ate="2026-01-31").validar()
    sql, _params = recorte.de_para_where(f)
    assert sql.startswith(f"FROM {contrato.tabela()} f")


# ================================================================== matriz
def test_matriz_sql_agrupa_pela_hierarquia_e_soma_a_lente():
    f = recorte.Filtros(de="2026-01-01", ate="2026-01-31", lente="val").validar()
    sql, params = matriz._sql(f)
    assert "SUM(f.qtde_vlr) AS medida" in sql
    assert "GROUP BY f.nk_wms_filial, f.nk_cliente, f.raz_social, f.tipo_movimento" in sql
    assert params["de"] == recorte.data_do_recorte("2026-01-01")


def test_matriz_consultar_mapeia_linhas_e_soma_total():
    f = recorte.Filtros(de="2026-01-01", ate="2026-01-31").validar()
    descricao = [("UNIDADE",), ("CLIENTE_CHAVE",), ("CLIENTE_ROTULO",),
                 ("TIPO_MOVIMENTO",), ("MES",), ("MEDIDA",), ("LINHAS",)]
    linhas_fake = [("RMSPII", "123", "Cliente X", "1-Embarque", "2026-01", 100, 3)]
    conexao = ConexaoFalsa(resultados=[linhas_fake], descricao=descricao)
    with conexao.cursor() as cur:
        resultado = matriz.consultar(cur, f)
    assert resultado["total_linhas"] == 3
    assert resultado["linhas"][0]["unidade"] == "RMSPII"
    assert resultado["linhas"][0]["cliente_rotulo"] == "Cliente X"
    assert resultado["hierarquia"] == list(contrato.HIERARQUIA)


# ================================================================ planilha
def test_planilha_colunas_e_so_o_que_e_tela_sem_as_medidas():
    cols = [c for c, _s, _r in planilha.colunas()]
    assert "qtde_peso" not in cols
    assert "nk_wms_filial" in cols
    assert "placa" in cols


def test_planilha_sql_pagina_com_offset():
    f = recorte.Filtros(de="2026-01-01", ate="2026-01-31", pagina=3).validar()
    sql, _params = planilha._sql(f, 3)
    assert "OFFSET 200 ROWS FETCH NEXT 100 ROWS ONLY" in sql


def test_placa_na_planilha_usa_expressao_normalizada():
    cols = dict((c, s) for c, s, _r in planilha.colunas())
    assert cols["placa"] == recorte.PLACA_ROTULO


# ================================================================ download
def test_download_colunas_e_tela_mais_arquivo_na_ordem_do_contrato():
    nomes = [c for c, _s, _r in download.colunas()]
    assert nomes == list(contrato.COLUNAS_ARQUIVO)


def test_download_pk_dw_usa_coluna_dw_e_nao_o_nome_cru():
    # Regressão (04/set/2026): o SQL gerado usava `f.pk_dw`, e o DW não tem
    # essa coluna — o nome real é `PK_FATO_VOL_TRN_CAT` (ORA-00904 em
    # produção, só no download: Matriz/planilha nunca selecionam `pk_dw`).
    sql = dict((c, s) for c, s, _r in download.colunas())
    assert sql["pk_dw"] == f"f.{contrato.PK_DW}"
    assert "f.pk_dw" not in sql["pk_dw"]


def test_nome_do_arquivo_leva_o_periodo():
    f = recorte.Filtros(de="2026-01-01", ate="2026-09-03").validar()
    assert download.nome_do_arquivo(f, "csv") == "volumetria_transporte_2026-01-01_a_2026-09-03.csv"


def test_nome_do_arquivo_marca_filtro_de_dia():
    f = recorte.Filtros(de="2026-01-01", ate="2026-09-03", dias=("5",)).validar()
    assert "_dias" in download.nome_do_arquivo(f, "csv")


@pytest.mark.parametrize("valor,esperado", [
    (None, ""), (True, "1"), (False, "0"),
])
def test_para_csv_casos_basicos(valor, esperado):
    assert download._para_csv(valor) == esperado


def test_para_csv_decimal_usa_virgula():
    from decimal import Decimal
    assert download._para_csv(Decimal("320.144")) == "320,144"


def test_xlsx_recusa_acima_do_teto(monkeypatch):
    f = recorte.Filtros(de="2026-01-01", ate="2026-01-31").validar()
    conexao = ConexaoFalsa(resultados=[[(download.TETO_XLSX + 1,)], []])
    monkeypatch.setattr(download.conexao_dw, "conectar", lambda: conexao)
    with pytest.raises(download.DownloadGrandeDemais):
        download.gerar_xlsx(f)
    assert conexao.fechada


# ============================================================== schema_dw
def test_contrato_batendo_nao_tem_problema_nem_aviso():
    problemas, avisos = schema_dw.comparar(catalogo_do_contrato())
    assert problemas == [] and avisos == []


def test_coluna_do_contrato_que_sumiu_e_problema():
    tipos = catalogo_do_contrato()
    del tipos["NK_WMS_FILIAL"]
    problemas, _avisos = schema_dw.comparar(tipos)
    assert any("NK_WMS_FILIAL" in p for p in problemas)


def test_medida_em_ponto_flutuante_e_problema():
    tipos = catalogo_do_contrato(QTDE_PESO="FLOAT")
    problemas, _avisos = schema_dw.comparar(tipos)
    assert any("QTDE_PESO" in p and "float" in p for p in problemas)


def test_coluna_nova_no_dw_e_aviso_e_nao_problema():
    tipos = catalogo_do_contrato(COLUNA_NOVA="VARCHAR2")
    problemas, avisos = schema_dw.comparar(tipos)
    assert problemas == []
    assert any("COLUNA_NOVA" in a for a in avisos)


def test_tabela_invisivel_aponta_para_as_duas_causas():
    problemas, _avisos = schema_dw.comparar({})
    assert "não existe" in problemas[0]
    assert "privilégio" in problemas[0]


def test_garantir_usa_cache_e_falha_nunca_entra_nele():
    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        schema_dw.garantir(cur)
    total_apos_primeira = len(conexao.executados)
    with conexao.cursor() as cur:
        schema_dw.garantir(cur)
    assert len(conexao.executados) == total_apos_primeira  # segunda não bateu no DW

    schema_dw.invalidar()
    conexao_com_erro = ConexaoFalsa(catalogo={})
    with pytest.raises(schema_dw.ContratoDivergenteDW):
        with conexao_com_erro.cursor() as cur:
            schema_dw.garantir(cur)
    with conexao_com_erro.cursor() as cur:
        with pytest.raises(schema_dw.ContratoDivergenteDW):
            schema_dw.garantir(cur)  # falha não entrou em cache: confere de novo


# ========================================================= endpoints (router)
def test_opcoes_exige_login(client):
    assert client.get(f"{BASE}/opcoes").status_code == 401


def test_opcoes_exige_ver(client, operador_headers):
    # Nenhuma role recebe `ver` deste app pelo seed (03/set) — só admin.
    r = client.get(f"{BASE}/opcoes", headers=operador_headers)
    assert r.status_code == 403


def test_diagnostico_exige_admin(client, operador_headers):
    assert client.get(DIAG, headers=operador_headers).status_code == 403


def _conexao_com_opcoes(voltas=1):
    from datetime import date, datetime

    uma_volta = [
        [],  # sql_zero_linhas() do garantir() — consome uma posição da fila também
        [("SP",)], [("PALLET",)], [("FROTA",)], [("ENTRADA",)],
        [("FINALIZADA",)], [("OK",)], [("BAIXADO",)],
        [(1, "Cliente Um")],
        [(date(2026, 1, 1), date(2026, 9, 1), datetime(2026, 9, 1, 10, 0))],
    ]
    return ConexaoFalsa(resultados=uma_volta * voltas)


def test_opcoes_usa_cache_e_nao_bate_no_dw_duas_vezes_seguidas(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = _conexao_com_opcoes()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)

    r1 = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r1.status_code == 200
    total_apos_primeira = len(conexao.executados)
    assert total_apos_primeira > 0

    r2 = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r2.status_code == 200
    assert len(conexao.executados) == total_apos_primeira  # segunda não bateu no DW
    assert r2.json() == r1.json()


def test_opcoes_revarre_o_dw_depois_do_ttl_vencer(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = _conexao_com_opcoes(voltas=2)
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)

    assert client.get(f"{BASE}/opcoes", headers=admin_headers).status_code == 200
    total_apos_primeira = len(conexao.executados)

    router._cache_opcoes["expira_em"] = 0.0  # simula TTL vencido, sem precisar de time.sleep
    schema_dw.invalidar()  # o TTL do /opcoes (1h) é bem maior que o do garantir() (10min)
    assert client.get(f"{BASE}/opcoes", headers=admin_headers).status_code == 200
    assert len(conexao.executados) > total_apos_primeira  # revarreu


def test_diagnostico_sem_credencial_e_503_nomeando_a_variavel(client, admin_headers):
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 503
    assert conexao_dw.ENV_USUARIO in r.json()["detail"]


def test_diagnostico_aprova_e_fecha_a_conexao(client, admin_headers, com_credencial, monkeypatch):
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ok"] is True
    assert corpo["resultado"]["problemas"] == []
    assert conexao.fechada


def test_diagnostico_relata_divergencia_em_200_nao_em_503(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = ConexaoFalsa(catalogo={})
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_diagnostico_nao_devolve_a_senha(client, admin_headers, com_credencial, monkeypatch):
    monkeypatch.setattr(conexao_dw, "conectar", lambda: ConexaoFalsa())
    r = client.get(DIAG, headers=admin_headers)
    assert "senha-de-mentira" not in r.text


def test_download_ticket_exige_permissao_exportar(client, operador_headers):
    r = client.post(
        f"{BASE}/download/ticket",
        params={"de": "2026-01-01", "ate": "2026-01-31"},
        headers=operador_headers,
    )
    assert r.status_code == 403


# ==================================================== somente leitura
_PALAVRAS_DE_ESCRITA = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE",
    "ALTER", "GRANT", "REVOKE", "COMMIT",
)
_METODOS_DE_ESCRITA = {"commit", "rollback", "executemany", "setinputsizes"}

# O router NÃO entra: SQL vem de recorte/matriz/planilha/download, e o router
# só monta prosa de erro — varrê-lo por palavra daria falso positivo eterno
# ("DELETE" nunca aparece, mas "CREATE" poderia num texto de ajuda um dia).
_MODULOS_DO_DW = (conexao_dw, schema_dw, recorte, matriz, planilha, download)


def _arvore(modulo):
    return ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))


def _docstrings(arvore):
    encontradas = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            texto = ast.get_docstring(no, clean=False)
            if texto is not None:
                encontradas.add(texto)
    return encontradas


@pytest.mark.parametrize("modulo", _MODULOS_DO_DW, ids=lambda m: m.__name__)
def test_guarda_estatica_nenhum_literal_escreve(modulo):
    arvore = _arvore(modulo)
    prosa = _docstrings(arvore)
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Constant) and isinstance(no.value, str)):
            continue
        if no.value in prosa:
            continue
        for palavra in _PALAVRAS_DE_ESCRITA:
            assert not re.search(rf"\b{palavra}\b", no.value, re.IGNORECASE), (
                f"literal de {modulo.__name__} com palavra de escrita "
                f"({palavra}): {no.value!r}"
            )


@pytest.mark.parametrize("modulo", _MODULOS_DO_DW, ids=lambda m: m.__name__)
def test_guarda_estatica_nenhuma_chamada_de_escrita_no_driver(modulo):
    chamados = {
        no.func.attr
        for no in ast.walk(_arvore(modulo))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
    }
    assert not (chamados & _METODOS_DE_ESCRITA), (
        f"chamada de escrita em {modulo.__name__}: {sorted(chamados & _METODOS_DE_ESCRITA)}"
    )


def test_guarda_de_runtime_diagnostico_so_emite_select(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    assert client.get(DIAG, headers=admin_headers).status_code == 200
    assert conexao.executados, "o teste não exercitou nada"
    for sql, _binds in conexao.executados:
        assert sql.lstrip().upper().startswith("SELECT"), sql


def test_nenhum_alter_session_e_emitido(com_credencial, monkeypatch):
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "_driver", lambda: DriverFalso(conexao=conexao))
    conexao_dw.conectar()
    assert conexao.executados == [], "conectar() não emite comando nenhum"
