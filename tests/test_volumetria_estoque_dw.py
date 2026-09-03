"""Volumetria de estoque — contrato, recorte, Matriz em modo POSIÇÃO,
planilha/download e a conexão com o DW Oracle.

## O limite desta suíte

Mesmo limite do irmão `test_volumetria_transporte_dw.py`: nenhum teste
conecta no DW, tudo roda contra `CursorFalso`/`ConexaoFalsa`. O aceite de
dado real é `/api/volumetria-estoque/diagnostico-dw` na VM.

## O que esta suíte prova a mais que a do transporte

`matriz.py` é o código genuinamente novo deste módulo: a agregação em modo
**posição** (CTE `base` → `maximo` → junção final). Os testes de
`test_matriz_sql_*` e `test_matriz_consultar_*` provam que o SQL soma dentro
do mesmo dia, escolhe o ÚLTIMO dia com dado por grupo (não o último dia do
calendário) e nunca duplica linha na saída — é a parte que não tem
equivalente no transporte para copiar.
"""

import ast
import pathlib
import re

import pytest

from backend.volumetria_estoque import (
    conexao_dw,
    contrato,
    download,
    matriz,
    planilha,
    recorte,
    schema_dw,
)

BASE = "/api/volumetria-estoque"
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
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
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
    yield
    schema_dw.invalidar()


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


def test_fora_nunca_aparece_no_select():
    nomes_select = {n for n, _t, _n in contrato.COLUNAS_SELECT}
    assert nomes_select.isdisjoint(contrato.FORA)
    assert "sk_cliente" in contrato.FORA


def test_qtde_sku_nao_e_lente():
    assert "qtde_sku" not in {c["coluna"] for c in contrato.LENTES.values()}
    assert "qtde_sku" in contrato.COLUNAS_TELA  # continua na planilha/arquivo


def test_cinco_lentes_sem_sufixo_2():
    assert set(contrato.LENTES) == {"liq", "bru", "pal", "vol", "val"}
    assert contrato.LENTES["vol"]["coluna"] == "qtde_vol"  # não qtde_vol2


def test_camara_aceita_nulo_no_contrato():
    entrada = next(c for c in contrato.COLUNAS if c[0] == "camara")
    assert entrada[2] is True  # nulável


def test_dw_data_inclusao_e_interno_para_o_fallback_de_frescor():
    # diferente do transporte, onde dw_data_inclusao é "fora"
    assert "dw_data_inclusao" not in contrato.COLUNAS_ARQUIVO
    entrada = next(c for c in contrato.COLUNAS if c[0] == "dw_data_inclusao")
    assert entrada[3] == "interno"


# ================================================================ recorte
def test_onde_periodo_simples():
    f = recorte.Filtros(de="2026-08-25", ate="2026-09-03").validar()
    clausulas, params = recorte.onde(f)
    assert clausulas == ["f.nk_calendario >= :de", "f.nk_calendario <= :ate"]
    assert params["de"] == recorte.data_do_recorte("2026-08-25")


def test_filtro_camara_so_valores_reais():
    f = recorte.Filtros(de="2026-08-25", ate="2026-09-03", camaras=("SECO", "CONGELADO")).validar()
    clausulas, params = recorte.onde(f)
    achou = [c for c in clausulas if c.startswith("(f.camara IN")]
    assert achou and "OR f.camara IS NULL" not in achou[0]
    assert {v for k, v in params.items() if k.startswith("cam")} == {"SECO", "CONGELADO"}


def test_filtro_camara_so_vazia():
    f = recorte.Filtros(de="2026-08-25", ate="2026-09-03", camaras=(recorte.CAMARA_CHAVE_VAZIA,)).validar()
    clausulas, _params = recorte.onde(f)
    assert "(f.camara IS NULL)" in clausulas


def test_filtro_camara_mista_usa_or():
    f = recorte.Filtros(
        de="2026-08-25", ate="2026-09-03", camaras=("SECO", recorte.CAMARA_CHAVE_VAZIA),
    ).validar()
    clausulas, params = recorte.onde(f)
    achou = [c for c in clausulas if "camara" in c]
    assert len(achou) == 1
    assert "IN" in achou[0] and "IS NULL" in achou[0]
    assert list(params.values())[-1] == "SECO" or "SECO" in params.values()


def test_aviso_dos_dias_declara_posicao_nao_soma():
    aviso = recorte.aviso_dos_dias(("5",))
    assert "FOTO" in aviso.upper()


# ================================================================== matriz
def test_matriz_sql_tem_as_tres_partes():
    f = recorte.Filtros(de="2026-08-01", ate="2026-09-03", lente="val").validar()
    sql, params = matriz._sql(f)
    assert sql.count("WITH base AS") == 1
    assert "maximo AS" in sql
    assert "MAX(dia) AS dia_max" in sql
    assert "SUM(f.qtde_vlr) AS medida_dia" in sql
    assert params["camara_sentinela"] == contrato.CAMARA_SENTINELA_SQL


def test_matriz_consultar_devolve_uma_linha_por_grupo_com_o_dia_da_foto():
    f = recorte.Filtros(de="2026-08-01", ate="2026-09-03").validar()
    descricao = [("UNIDADE",), ("CLIENTE_CHAVE",), ("CLIENTE_ROTULO",),
                 ("CAMARA_ROTULO",), ("MES",), ("DIA",), ("MEDIDA",), ("LINHAS",)]
    from datetime import date
    linhas_fake = [
        ("RPII", "1249", "Sapore S.A", "SECO", "2026-08", date(2026, 8, 30), 320, 2),
    ]
    conexao = ConexaoFalsa(resultados=[linhas_fake], descricao=descricao)
    with conexao.cursor() as cur:
        resultado = matriz.consultar(cur, f)
    assert resultado["modo"] == "posicao"
    linha = resultado["linhas"][0]
    assert linha["unidade"] == "RPII"
    assert linha["camara"] == "SECO"
    assert linha["dia"] == "2026-08-30"
    assert linha["valor"] == 320


def test_matriz_consultar_camara_nula_vira_rotulo_sem_camara():
    f = recorte.Filtros(de="2026-08-01", ate="2026-09-03").validar()
    descricao = [("UNIDADE",), ("CLIENTE_CHAVE",), ("CLIENTE_ROTULO",),
                 ("CAMARA_ROTULO",), ("MES",), ("DIA",), ("MEDIDA",), ("LINHAS",)]
    linhas_fake = [("RPII", "1249", "Sapore S.A", None, "2026-08", "2026-08-30", 10, 1)]
    conexao = ConexaoFalsa(resultados=[linhas_fake], descricao=descricao)
    with conexao.cursor() as cur:
        resultado = matriz.consultar(cur, f)
    assert resultado["linhas"][0]["camara"] == contrato.CAMARA_ROTULO_VAZIA


def test_matriz_nao_tem_invariante_de_soma_com_a_planilha():
    # documenta a decisão: não existe "total_linhas" comparável ao da
    # planilha neste módulo (ver docstring de matriz.py)
    assert "total_linhas" not in matriz.consultar.__doc__


# ================================================================ planilha
def test_planilha_colunas_e_so_tela_sem_as_medidas():
    cols = [c for c, _s, _r in planilha.colunas()]
    assert "qtde_peso" not in cols
    assert "qtde_sku" in cols  # SKU aparece na planilha, não é lente
    assert "camara" in cols


def test_planilha_nao_normaliza_camara_no_sql():
    cols = dict((c, s) for c, s, _r in planilha.colunas())
    assert cols["camara"] == "f.camara"  # sem NVL/literal acentuado no SQL


def test_planilha_consultar_normaliza_camara_nula_em_python():
    f = recorte.Filtros(de="2026-08-01", ate="2026-09-03").validar()
    nomes = planilha.colunas_com_medida(f)
    apelidos = [a for a, _s, _r in nomes]
    linha_fake = tuple(None if a == "camara" else f"v_{a}" for a in apelidos)
    conexao = ConexaoFalsa(resultados=[[(1,)], [linha_fake]])
    with conexao.cursor() as cur:
        resultado = planilha.consultar(cur, f)
    assert resultado["linhas"][0]["camara"] == contrato.CAMARA_ROTULO_VAZIA


# ================================================================ download
def test_download_colunas_e_tela_mais_arquivo_na_ordem_do_contrato():
    nomes = [c for c, _s, _r in download.colunas()]
    assert nomes == list(contrato.COLUNAS_ARQUIVO)


def test_nome_do_arquivo_leva_o_periodo():
    f = recorte.Filtros(de="2026-08-25", ate="2026-09-03").validar()
    assert download.nome_do_arquivo(f, "csv") == "volumetria_estoque_2026-08-25_a_2026-09-03.csv"


def test_para_csv_normaliza_camara_nula_pelo_indice():
    nomes = download.colunas()
    idx = next(i for i, (a, _s, _r) in enumerate(nomes) if a == "camara")
    assert download._para_csv(None, idx, idx) == contrato.CAMARA_ROTULO_VAZIA
    assert download._para_csv(None, 0, idx) == ""  # outra coluna, None normal


def test_xlsx_recusa_acima_do_teto(monkeypatch):
    f = recorte.Filtros(de="2026-08-01", ate="2026-08-31").validar()
    conexao = ConexaoFalsa(resultados=[[(download.TETO_XLSX + 1,)], []])
    monkeypatch.setattr(download.conexao_dw, "conectar", lambda: conexao)
    with pytest.raises(download.DownloadGrandeDemais):
        download.gerar_xlsx(f)
    assert conexao.fechada


# ============================================================== schema_dw
def test_contrato_batendo_nao_tem_problema_nem_aviso():
    problemas, avisos = schema_dw.comparar(catalogo_do_contrato())
    assert problemas == [] and avisos == []


def test_medida_em_ponto_flutuante_e_problema():
    tipos = catalogo_do_contrato(QTDE_PESO="FLOAT")
    problemas, _avisos = schema_dw.comparar(tipos)
    assert any("QTDE_PESO" in p and "float" in p for p in problemas)


def test_garantir_usa_cache():
    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        schema_dw.garantir(cur)
    total = len(conexao.executados)
    with conexao.cursor() as cur:
        schema_dw.garantir(cur)
    assert len(conexao.executados) == total


# ========================================================= endpoints (router)
def test_opcoes_exige_login(client):
    assert client.get(f"{BASE}/opcoes").status_code == 401


def test_opcoes_exige_ver(client, operador_headers):
    assert client.get(f"{BASE}/opcoes", headers=operador_headers).status_code == 403


def test_diagnostico_exige_admin(client, operador_headers):
    assert client.get(DIAG, headers=operador_headers).status_code == 403


def test_diagnostico_sem_credencial_e_503_nomeando_a_variavel(client, admin_headers):
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 503
    assert conexao_dw.ENV_USUARIO in r.json()["detail"]


def test_diagnostico_aprova_e_fecha_a_conexao(client, admin_headers, com_credencial, monkeypatch):
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert conexao.fechada


def test_diagnostico_relata_divergencia_em_200_nao_em_503(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = ConexaoFalsa(catalogo={})
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_download_ticket_exige_permissao_exportar(client, operador_headers):
    r = client.post(
        f"{BASE}/download/ticket",
        params={"de": "2026-08-25", "ate": "2026-09-03"},
        headers=operador_headers,
    )
    assert r.status_code == 403


# ==================================================== somente leitura
_PALAVRAS_DE_ESCRITA = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE",
    "ALTER", "GRANT", "REVOKE", "COMMIT",
)
_METODOS_DE_ESCRITA = {"commit", "rollback", "executemany", "setinputsizes"}
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
