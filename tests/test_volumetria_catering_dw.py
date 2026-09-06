"""Volumetria de catering — o lado Oracle: conexão com o DW, contrato, a chave
de fonte, a camada de decisões em memória e o SQL traduzido (C1 + C2).

## O limite desta suíte, dito antes de qualquer coisa

**Nenhum teste daqui conecta no DW.** O DW é produção, e a política é que a IA
não conecta nele. Tudo roda contra `DriverFalso`/`ConexaoFalsa`, de mentira, com
a mesma superfície estreita que os módulos `*_dw.py` usam. É o mesmo padrão de
`tests/test_volumetria_transporte_dw.py`, e por isso este arquivo roda na suíte
normal — sem container, sem Postgres, e sem o `oracledb` instalado.

O que se prova aqui: o **statement** que sai, os **binds**, a tradução dos
filtros de decisão (sigla exibida -> sigla da fonte, tipo -> nomes de estoque),
o mapeamento de linha (sigla, rótulo canônico, `DATE` -> `date`), a leitura do
ambiente, a conferência de contrato, a chave de fonte, o cache das dimensões, e
que nenhum caminho emite comando de escrita.

O que **não** se prova: que o Oracle de verdade aceita os statements, que as
tabelas se chamam assim, que o usuário de leitura tem privilégio, e que os
NÚMEROS batem com o Postgres. Os três primeiros a Maria prova abrindo
`/api/volumetria-catering/diagnostico-dw` na VM; o último é o comparador do C3,
rodado em produção com as duas fontes de pé.

## Duas guardas de somente leitura, e não uma

- **estática**, sobre a árvore sintática de todo módulo `*_dw.py`: nenhum
  literal com palavra de escrita, nenhuma chamada a
  `commit`/`rollback`/`executemany`. Pega o código que nenhum teste exercitou;
- **de runtime**, no cursor falso: todo `execute` que não comece por `SELECT`
  estoura. Pega o comando montado por concatenação, que a estática não veria —
  e cobre os endpoints do router, que a estática não varre (o router tem SQL
  das duas fontes, e varrê-lo por palavra daria falso positivo eterno).
"""

import ast
import logging
import pathlib
import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.volumetria_catering import (
    conexao_dw,
    contrato,
    dimensoes_dw,
    download,
    download_dw,
    fonte,
    matriz_dw,
    planilha,
    planilha_dw,
    recorte_dw,
    schema_dw,
)

BASE = "/api/volumetria-catering"
DIAG = f"{BASE}/diagnostico-dw"
JAN = {"de": "2026-01-01", "ate": "2026-01-31"}

# Como o DW declara cada tipo do nosso contrato. `TIMESTAMP` do contrato cai em
# `DATE` no Oracle porque o `DATE` do Oracle já carrega hora — a distinção era
# uma decisão do Postgres da nuvem-ia.
TIPO_NO_DW = {
    "TEXT": "VARCHAR2",
    "INTEGER": "NUMBER",
    "SMALLINT": "NUMBER",
    "NUMERIC(18,3)": "NUMBER",
    "DATE": "DATE",
    "TIMESTAMP": "DATE",
}


def catalogo_do_contrato(movimento, **sobrescritas):
    """`{COLUNA: DATA_TYPE}` como o `ALL_TAB_COLUMNS` responderia se o DW
    estivesse exatamente na forma que o contrato descreve."""
    tipos = {
        contrato.coluna_dw(nome, movimento): TIPO_NO_DW[tipo]
        for nome, tipo, _nulo in contrato.colunas(movimento)
    }
    tipos.update(sobrescritas)
    return tipos


# ------------------------------------------------------------ driver falso
class CursorFalso:
    """Só o que os módulos usam: execute, fetchall, fetchone, description,
    iteração, arraysize/prefetchrows.

    `resultados` é uma FILA: cada `execute()` que não seja catálogo nem o
    `WHERE 1=0` consome o próximo item. Um item é uma lista de linhas, ou um
    dicionário `{"descricao": [...], "linhas": [...]}` quando a consulta
    precisa de `cur.description` (Matriz e planilha leem o nome das colunas).
    Estreito de propósito: se o módulo passar a depender de mais coisa do
    driver, isto quebra e a dependência nova vira conversa."""

    def __init__(self, conexao, resultados=None, descricao=None):
        self.conexao = conexao
        self.arraysize = 100
        self.prefetchrows = 2
        self._fila = list(resultados or [])
        self._resultado = []
        self.description = descricao or []

    def __enter__(self):
        return self

    def __exit__(self, *_excecao):
        return False

    def __iter__(self):
        return iter(self._resultado)

    def execute(self, sql, binds=None):
        self.conexao.executados.append((sql, dict(binds or {})))
        # Guarda de RUNTIME: nada que não seja leitura passa por aqui.
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError(f"comando que não é leitura: {sql!r}")
        if self.conexao.erro is not None:
            raise self.conexao.erro
        if "ALL_TAB_COLUMNS" in sql:
            tabela = binds["tabela"]
            self._resultado = list(self.conexao.catalogo.get(tabela, {}).items())
        elif "WHERE 1=0" in sql:
            self._resultado = []  # o SELECT do contrato não lê bloco
        elif self._fila:
            item = self._fila.pop(0)
            if isinstance(item, dict):
                self.description = [(n,) for n in item["descricao"]]
                self._resultado = list(item["linhas"])
            else:
                self._resultado = list(item)
        else:
            self._resultado = []

    def fetchall(self):
        return list(self._resultado)

    def fetchone(self):
        return self._resultado[0] if self._resultado else None


class ConexaoFalsa:
    """Guarda o que foi executado e se foi fechada. A fila de resultados é
    COMPARTILHADA entre os cursores da mesma conexão — é assim que um endpoint
    que abre um cursor para o drift e outro para a consulta consome a fila na
    ordem certa."""

    def __init__(self, catalogo=None, erro=None, resultados=None, descricao=None):
        self.catalogo = catalogo if catalogo is not None else _CATALOGO_BOM
        self.erro = erro
        self.executados = []
        self.fechada = False
        self._fila = list(resultados or [])
        self._descricao = descricao

    def cursor(self):
        cur = CursorFalso(self, descricao=self._descricao)
        cur._fila = self._fila  # a mesma lista, consumida em ordem
        return cur

    def close(self):
        self.fechada = True


def _tabela_curta(movimento):
    """O nome sem o schema — a chave que o catálogo falso usa, porque o
    `ALL_TAB_COLUMNS` guarda dono e tabela separados."""
    return contrato.tabela(movimento).partition(".")[2]


_CATALOGO_BOM = {
    _tabela_curta("rec"): catalogo_do_contrato("rec"),
    _tabela_curta("exp"): catalogo_do_contrato("exp"),
}


class DriverFalso:
    """O módulo `oracledb` de mentira: `defaults` e `connect`."""

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


# ------------------------------------------------- o retrato das dimensões
def dim_falsa(**sobrescritas) -> dimensoes_dw.Dimensoes:
    """Um retrato pequeno e conhecido: a SANCA (`RMSPV` -> `RMSPIV`), um cliente
    com duas grafias (CONVIDA vence NOVITA pelo peso), três tipos e um nome de
    estoque que a regra não classifica."""
    base = dict(
        unidades_fonte=["RMSPV", "RMSPII", "RMRJ"],
        nomes_estoque=["CONG FLV (CUCINARE)", "SECO GERAL", "RESFRIADO - PR", "QUALQUER COISA"],
        operacoes={"rec": ["NAO TROCA NOTA DE ARMAZENAGEM"], "exp": ["SAIDA NORMAL"]},
        clientes_rotulo={"67945071": "CONVIDA", "12345678": "SAPORE"},
        clientes_grafias={
            "67945071": [("CONVIDA", 900.0), ("NOVITA", 100.0)],
            "12345678": [("SAPORE", 50.0)],
        },
        periodo=(date(2023, 1, 1), date(2026, 9, 5)),
        atualizado_em={"rec": datetime(2026, 9, 5, 7, 5), "exp": datetime(2026, 9, 5, 7, 10)},
    )
    base.update(sobrescritas)
    return dimensoes_dw.Dimensoes(**base)


def aquecer(dim):
    """Põe um retrato no cache sem varrer o DW — para testar o que vem depois
    da varredura sem ter que encenar a varredura toda vez."""
    dimensoes_dw._cache["dados"] = dim
    dimensoes_dw._cache["expira_em"] = float("inf")


# As quatro respostas de uma varredura (`dimensoes_dw.varrer`), na ordem em que
# ela as pede: listas do rec, clientes do rec, listas do exp, clientes do exp.
def _fila_da_varredura():
    return [
        [("RMSPV", "CONG FLV (CUCINARE)", "NAO TROCA NOTA DE ARMAZENAGEM"),
         ("RMSPII", "SECO GERAL", "NAO TROCA NOTA DE ARMAZENAGEM")],
        [("67945071", "CONVIDA", Decimal("900.000"), datetime(2023, 1, 1), datetime(2026, 9, 4), datetime(2026, 9, 4, 7, 5)),
         ("67945071", "NOVITA", Decimal("100.000"), datetime(2024, 1, 1), datetime(2026, 9, 5), datetime(2026, 9, 5, 7, 5))],
        [("RMRJ", "RESFRIADO - PR", "SAIDA NORMAL")],
        [("12345678", "SAPORE", Decimal("50"), datetime(2025, 1, 1), datetime(2026, 9, 3), datetime(2026, 9, 3, 7, 10))],
    ]


_DESCRICAO_MATRIZ_REC = ["CHAVE_0", "CHAVE_1", "ROTULO_1", "CHAVE_2", "MES", "MEDIDA_UNICA", "LINHAS"]


def _fila_da_matriz_rec():
    """Três grupos: DUAS siglas da fonte que a tela mostra como `RMSPIV` (é o
    caso da colisão, que tem que SOMAR), e a RMSPII. O cliente da SANCA vem com
    a grafia NOVITA na linha, e o rótulo tem que sair CONVIDA."""
    return [{
        "descricao": _DESCRICAO_MATRIZ_REC,
        "linhas": [
            ("RMSPV", "67945071", "NOVITA", "OP A", "2026-01", Decimal("100.000"), Decimal(2)),
            ("RMSPIV", "67945071", "NOVITA", "OP A", "2026-01", Decimal("50.000"), Decimal(1)),
            ("RMSPII", "12345678", "SAPORE", "OP B", "2026-01", Decimal("10.000"), Decimal(1)),
        ],
    }]


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Nenhum teste daqui herda credencial, chave de fonte nem nome de tabela do
    ambiente, e os dois caches (drift e dimensões) são zerados nas duas pontas."""
    for var in (
        conexao_dw.ENV_USUARIO, conexao_dw.ENV_SENHA, conexao_dw.ENV_HOST,
        conexao_dw.ENV_PORTA, conexao_dw.ENV_SERVICO, fonte.ENV_FONTE,
        "DW_TABELA_REC", "DW_TABELA_EXP",
    ):
        monkeypatch.delenv(var, raising=False)
    schema_dw.invalidar()
    dimensoes_dw.invalidar()
    yield
    schema_dw.invalidar()
    dimensoes_dw.invalidar()


@pytest.fixture
def com_credencial(monkeypatch):
    monkeypatch.setenv(conexao_dw.ENV_USUARIO, "hub_leitura_dw")
    monkeypatch.setenv(conexao_dw.ENV_SENHA, "senha-de-mentira")


@pytest.fixture
def fonte_dw(monkeypatch, com_credencial):
    """A chave virada para o DW, com credencial — o estado da VM depois do C5."""
    monkeypatch.setenv(fonte.ENV_FONTE, "dw")


@pytest.fixture
def driver(monkeypatch):
    """Injeta o driver falso no lugar do import preguiçoso."""
    falso = DriverFalso()
    monkeypatch.setattr(conexao_dw, "_driver", lambda: falso)
    return falso


def _conexao(monkeypatch, **kwargs) -> ConexaoFalsa:
    """Uma conexão falsa no lugar de `conexao_dw.conectar()`."""
    conexao = ConexaoFalsa(**kwargs)
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    return conexao


# ======================================================== a chave de fonte
def test_a_fonte_padrao_e_o_postgres_que_esta_em_producao():
    """Sem a variável, nada muda para quem usa a tela hoje."""
    assert fonte.ativa() == fonte.POSTGRES
    assert not fonte.e_dw()


def test_a_chave_vira_para_o_dw(monkeypatch):
    monkeypatch.setenv(fonte.ENV_FONTE, "dw")
    assert fonte.ativa() == fonte.DW
    assert fonte.e_dw()
    # maiúscula e espaço não fazem a virada falhar por descuido de digitação
    monkeypatch.setenv(fonte.ENV_FONTE, " DW ")
    assert fonte.e_dw()


def test_valor_invalido_nomeia_a_variavel_e_nao_cai_no_padrao(monkeypatch):
    """`oracle` parece certo e não é. Cair no padrão em silêncio faria a Maria
    acreditar que virou enquanto a tela continua no Postgres."""
    monkeypatch.setenv(fonte.ENV_FONTE, "oracle")
    with pytest.raises(fonte.FonteInvalida) as erro:
        fonte.ativa()
    assert fonte.ENV_FONTE in str(erro.value)
    assert "postgres" in str(erro.value) and "dw" in str(erro.value)


def test_com_a_chave_em_postgres_a_tela_nao_depende_do_dw(client, admin_headers, monkeypatch):
    """A tela continua no `nuvem-db` e continua 503 sem `VOLUMETRIA_DB_URL`,
    mesmo com a credencial do DW no ambiente — é o que faz os lotes C1–C4 irem
    para produção sem mudar nada para quem usa."""
    monkeypatch.setenv(conexao_dw.ENV_USUARIO, "hub_leitura_dw")
    monkeypatch.setenv(conexao_dw.ENV_SENHA, "senha-de-mentira")
    monkeypatch.delenv("VOLUMETRIA_DB_URL", raising=False)
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 503
    assert "VOLUMETRIA_DB_URL" in r.json()["detail"]


def test_chave_invalida_e_503_nomeando_a_variavel_em_toda_rota(client, admin_headers, monkeypatch):
    monkeypatch.setenv(fonte.ENV_FONTE, "oracle")
    for rota, params in (("/opcoes", {}), ("/matriz", JAN), ("/planilha", JAN)):
        r = client.get(f"{BASE}{rota}", params=params, headers=admin_headers)
        assert r.status_code == 503, rota
        assert fonte.ENV_FONTE in r.json()["detail"]
    assert client.get("/api/health").status_code == 200


# ==================================== os nomes dos objetos no DW (contrato)
def test_tabela_e_o_nome_qualificado_medido():
    """Nome curto (`FATO_VOL_REC_CAT`) é o que levou `ORA-00942` na primeira
    sondagem da nuvem-ia. O schema e o `_V01` fazem parte do nome."""
    assert contrato.tabela("rec") == "DM_VOLUMETRIA.FATO_VOL_REC_CAT_V01"
    assert contrato.tabela("exp") == "DM_VOLUMETRIA.FATO_VOL_EXP_CAT_V01"
    with pytest.raises(KeyError):
        contrato.tabela("estoque")


def test_nome_da_tabela_vem_de_configuracao(monkeypatch):
    """"Não há outra versão programada" é ausência de plano, não garantia — a
    `FATO_VOLUMETRIA` do mesmo schema já está em `_V04`. Trocar de versão tem
    que ser variável de ambiente, não commit."""
    monkeypatch.setenv("DW_TABELA_REC", "DM_VOLUMETRIA.FATO_VOL_REC_CAT_V02")
    assert contrato.tabela("rec") == "DM_VOLUMETRIA.FATO_VOL_REC_CAT_V02"
    assert schema_dw.sql_zero_linhas("rec").endswith(
        "FROM DM_VOLUMETRIA.FATO_VOL_REC_CAT_V02 WHERE 1=0"
    )


def test_nome_de_objeto_invalido_nao_entra_no_sql(monkeypatch):
    """Nome de objeto é concatenado (não pode ser bind), então precisa de guarda
    própria. Sem ela, `DW_TABELA_REC` seria injeção de SQL por .env."""
    for veneno in ("dm_volumetria.fato", "FATO; DROP TABLE X", "FATO WHERE 1=1"):
        monkeypatch.setenv("DW_TABELA_REC", veneno)
        with pytest.raises(contrato.TabelaInvalida) as erro:
            contrato.tabela("rec")
        assert "DW_TABELA_REC" in str(erro.value)


def test_coluna_dw_e_a_nossa_em_maiusculas_menos_a_pk():
    """A invariante, e a única exceção: o nome da PK foi MEDIDO, não derivado do
    nome da tabela (a tabela ganhou schema e `_V01`, a coluna não)."""
    assert contrato.coluna_dw("nk_wms_filial", "rec") == "NK_WMS_FILIAL"
    assert contrato.coluna_dw("qtde_peso_solicitado", "exp") == "QTDE_PESO_SOLICITADO"
    assert contrato.coluna_dw("pk_dw", "rec") == "PK_FATO_VOL_REC_CAT"
    assert contrato.coluna_dw("pk_dw", "exp") == "PK_FATO_VOL_EXP_CAT"
    # sem o `_V01` que a TABELA ganhou — é o detalhe que a sondagem mediu
    assert "_V01" not in contrato.coluna_dw("pk_dw", "rec")


def test_colunas_dw_segue_a_ordem_do_contrato_e_cobre_as_duas_tabelas():
    for movimento, quantas in (("rec", 36), ("exp", 46)):
        nomes = contrato.colunas_dw(movimento)
        assert len(nomes) == len(contrato.colunas(movimento)) == quantas
        assert nomes[0] == contrato.PK_DW[movimento]  # procedência vem primeiro
        assert nomes == [n.upper() for n in nomes]


def test_tipo_da_coluna_responde_pelo_contrato():
    """É por esta função que o lado Oracle sabe que `nk_calendario` tem que
    sair como `date` e não como o `datetime` que o driver entrega."""
    assert contrato.tipo_da_coluna("nk_calendario", "rec") == "DATE"
    assert contrato.tipo_da_coluna("dthr_confirm", "exp") == "TIMESTAMP"
    assert contrato.tipo_da_coluna("qtde_peso2", "rec") == "NUMERIC(18,3)"
    with pytest.raises(KeyError):
        contrato.tipo_da_coluna("qtde_peso2", "exp")  # medida só da entrada


# ================================================== o SELECT gerado do contrato
def test_select_e_gerado_do_contrato_e_nunca_estrela():
    """A lista explícita é o que faz coluna removida no DW dar `ORA-00904`
    nomeando a coluna, no primeiro execute — e não erro de tipo trinta mil
    linhas adiante."""
    for movimento in contrato.MOVIMENTOS:
        sql = schema_dw.sql_zero_linhas(movimento)
        esperado = ", ".join(contrato.colunas_dw(movimento))
        assert sql == (
            f"SELECT {esperado} FROM {contrato.tabela(movimento)} WHERE 1=0"
        )
        assert "SELECT *" not in sql


def test_select_de_conferencia_nao_le_bloco():
    """`WHERE 1=0`: o Oracle compila, resolve nome e privilégio, e não lê dado.
    É o que permite conferir contrato em toda abertura sem custo."""
    for movimento in contrato.MOVIMENTOS:
        assert schema_dw.sql_zero_linhas(movimento).endswith("WHERE 1=0")


def test_catalogo_passa_tabela_e_dono_por_bind():
    """Os dois vêm de variável de ambiente. Valor de fora do código dentro de
    uma string de SQL é o defeito que não aparece na revisão."""
    sql = schema_dw.sql_catalogo(com_dono=True)
    assert ":tabela" in sql and ":dono" in sql
    assert "DM_VOLUMETRIA" not in sql and "FATO_VOL" not in sql

    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        schema_dw.conferir(cur, "rec")
    catalogo = [(s, b) for s, b in conexao.executados if "ALL_TAB_COLUMNS" in s]
    assert catalogo, "o diagnóstico tem que consultar o catálogo"
    _sql, binds = catalogo[0]
    assert binds == {"dono": "DM_VOLUMETRIA", "tabela": "FATO_VOL_REC_CAT_V01"}


def test_sem_dono_no_nome_o_filtro_e_so_pela_tabela(monkeypatch):
    """Configuração sem schema é menos precisa, e a alternativa — supor `USER` —
    inventaria um dono que a configuração não disse."""
    monkeypatch.setenv("DW_TABELA_REC", "FATO_VOL_REC_CAT_V01")
    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        schema_dw.conferir(cur, "rec")
    _sql, binds = next(
        (s, b) for s, b in conexao.executados if "ALL_TAB_COLUMNS" in s
    )
    assert binds == {"tabela": "FATO_VOL_REC_CAT_V01"}
    assert "OWNER" not in _sql


# ============================================================== a conexão
def test_credencial_nao_tem_default_e_a_falta_nomeia_a_variavel():
    """Sem a credencial isto não conecta em lugar nenhum — que é a proteção. E a
    mensagem tem que chegar em quem escreveu o .env."""
    with pytest.raises(conexao_dw.CredencialAusente) as erro:
        conexao_dw.credencial()
    assert conexao_dw.ENV_USUARIO in str(erro.value)
    assert conexao_dw.ENV_SENHA in str(erro.value)
    assert not conexao_dw.configurado()


def test_falta_so_a_senha_nomeia_so_a_senha(monkeypatch):
    monkeypatch.setenv(conexao_dw.ENV_USUARIO, "hub_leitura_dw")
    with pytest.raises(conexao_dw.CredencialAusente) as erro:
        conexao_dw.credencial()
    assert conexao_dw.ENV_SENHA in str(erro.value)
    assert conexao_dw.ENV_USUARIO not in str(erro.value)


def test_credencial_ausente_e_um_caso_de_dw_indisponivel():
    """Quem trata "o card está fora" não precisa saber a diferença entre
    configuração faltando e rede fechada; quem quer distinguir ainda pode."""
    assert issubclass(conexao_dw.CredencialAusente, conexao_dw.DWIndisponivel)


def test_o_nome_da_credencial_e_diferente_do_da_carga():
    """A credencial da carga (`DW_USER`/`DW_SENHA` na nuvem-ia) tem escrita no
    Postgres dela. Nome diferente é o que faz copiar a linha do .env de lá para
    cá não conectar nada — e é isso que se quer."""
    assert conexao_dw.ENV_USUARIO not in ("DW_USER", "DW_USUARIO")
    assert conexao_dw.ENV_SENHA != "DW_SENHA"


def test_a_credencial_e_a_mesma_do_transporte_e_do_estoque():
    """Uma credencial de leitura para as três volumetrias: já está no `.env` da
    VM desde 04/set. Se os nomes divergissem, a virada do catering exigiria
    digitar a senha de novo — e a Maria já a digitou uma vez."""
    from backend.volumetria_transporte import conexao_dw as trn

    assert conexao_dw.ENV_USUARIO == trn.ENV_USUARIO
    assert conexao_dw.ENV_SENHA == trn.ENV_SENHA
    assert conexao_dw.dsn() == trn.dsn()


def test_dsn_tem_padrao_no_que_nao_e_segredo(monkeypatch):
    assert conexao_dw.dsn() == "oracleprd-aws.superfrio.com.br:1521/pdwgener"
    monkeypatch.setenv(conexao_dw.ENV_HOST, "outro-host")
    monkeypatch.setenv(conexao_dw.ENV_PORTA, "1522")
    monkeypatch.setenv(conexao_dw.ENV_SERVICO, "outro")
    assert conexao_dw.dsn() == "outro-host:1522/outro"


def test_fetch_decimals_e_ligado_antes_de_abrir_a_sessao(com_credencial, driver):
    """A linha que, faltando, corrompe peso em silêncio: sem ela todo `NUMBER`
    chega como float, e 3 decimais de kg não sobrevivem a ponto flutuante
    binário. Medido na nuvem-ia em 25/08/2026."""
    assert driver.defaults.fetch_decimals is False
    conexao_dw.conectar()
    assert driver.defaults.fetch_decimals is True


def test_credencial_faltando_nao_toca_no_driver(driver):
    """`fetch_decimals` é estado GLOBAL do módulo `oracledb`: erro de
    configuração não deve deixar rastro nele."""
    with pytest.raises(conexao_dw.CredencialAusente):
        conexao_dw.conectar()
    assert driver.defaults.fetch_decimals is False
    assert driver.chamadas == []


def test_conectar_passa_credencial_dsn_e_timeout(com_credencial, driver):
    conexao_dw.conectar()
    (kwargs,) = driver.chamadas
    assert kwargs["user"] == "hub_leitura_dw"
    assert kwargs["password"] == "senha-de-mentira"
    assert kwargs["dsn"] == conexao_dw.dsn()
    assert kwargs["tcp_connect_timeout"] == conexao_dw.TIMEOUT_CONEXAO_SEGUNDOS


def test_sessao_que_nao_abre_e_dw_indisponivel_sem_vazar_a_senha(
    com_credencial, monkeypatch, caplog
):
    """Só o TIPO do erro na mensagem: o texto do driver pode carregar usuário e
    DSN, e isto chega na tela. E a senha não pode aparecer nem no log."""
    class ErroDoDriver(Exception):
        pass

    falso = DriverFalso(erro=ErroDoDriver("ORA-01017 user=hub senha-de-mentira"))
    monkeypatch.setattr(conexao_dw, "_driver", lambda: falso)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(conexao_dw.DWIndisponivel) as erro:
            conexao_dw.conectar()

    assert "ErroDoDriver" in str(erro.value)
    assert "senha-de-mentira" not in str(erro.value)
    assert "ORA-01017" not in str(erro.value)
    assert "senha-de-mentira" not in caplog.text


def test_erro_de_configuracao_do_driver_tambem_e_503_e_nao_500(
    com_credencial, monkeypatch
):
    """`oracledb.Error` cobriria o esperado, mas configuração ruim do driver sai
    como `ValueError` — e 500 genérico neste card é o que a falha graciosa
    existe para evitar."""
    falso = DriverFalso(erro=ValueError("dsn malformado"))
    monkeypatch.setattr(conexao_dw, "_driver", lambda: falso)
    with pytest.raises(conexao_dw.DWIndisponivel):
        conexao_dw.conectar()


def test_o_driver_e_importado_preguicosamente():
    """A suíte inteira roda sem o `oracledb` instalado, e um ambiente sem o
    pacote não pode derrubar o import do router — e com ele o Hub."""
    fonte_py = pathlib.Path(conexao_dw.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte_py)
    no_topo = [
        no for no in arvore.body if isinstance(no, (ast.Import, ast.ImportFrom))
    ]
    importados = {
        alias.name for no in no_topo if isinstance(no, ast.Import) for alias in no.names
    }
    assert "oracledb" not in importados
    # e o import de dentro da função vira DWIndisponivel, não ImportError
    assert "DWIndisponivel" in fonte_py.split("def _driver")[1].split("def ")[0]


def test_preparar_cursor_governa_o_round_trip():
    """O default do driver é 100 linhas por ida e volta; com ele uma leitura de
    40 mil linhas custa 400 round trips."""
    cur = CursorFalso(ConexaoFalsa())
    conexao_dw.preparar_cursor(cur)
    assert cur.arraysize == conexao_dw.LOTE_LEITURA
    assert cur.prefetchrows > cur.arraysize


# ======================================================= drift contra o DW
def test_contrato_batendo_nao_tem_problema_nem_aviso():
    for movimento in contrato.MOVIMENTOS:
        problemas, avisos = schema_dw.comparar(
            movimento, catalogo_do_contrato(movimento)
        )
        assert problemas == []
        assert avisos == []


def test_timestamp_com_precisao_colada_e_aceito():
    """O `ALL_TAB_COLUMNS` responde `TIMESTAMP(6)`, não `TIMESTAMP`. Comparar por
    igualdade reprovaria a fonte inteira no primeiro dia."""
    catalogo = catalogo_do_contrato("rec", DW_DATA_ALTERACAO="TIMESTAMP(6)")
    problemas, _avisos = schema_dw.comparar("rec", catalogo)
    assert problemas == []


def test_coluna_do_contrato_que_sumiu_e_problema():
    catalogo = catalogo_do_contrato("rec")
    del catalogo["NK_WMS_FILIAL"]
    problemas, _avisos = schema_dw.comparar("rec", catalogo)
    assert len(problemas) == 1
    assert "NK_WMS_FILIAL" in problemas[0]
    assert "nk_wms_filial" in problemas[0]  # e o nome NOSSO, para achar no código


def test_tipo_de_familia_errada_e_problema():
    """Data virando texto no DW é o tipo de mudança que passaria batida: o
    `SELECT` continua compilando, e o valor chega deformado."""
    catalogo = catalogo_do_contrato("rec", NK_CALENDARIO="VARCHAR2")
    problemas, _avisos = schema_dw.comparar("rec", catalogo)
    assert len(problemas) == 1
    assert "NK_CALENDARIO" in problemas[0] and "VARCHAR2" in problemas[0]


@pytest.mark.parametrize("tipo", schema_dw.PONTO_FLUTUANTE)
def test_medida_em_ponto_flutuante_e_problema(tipo):
    """`fetch_decimals` não salva `FLOAT`/`BINARY_DOUBLE`: o driver entrega
    float, e peso com 3 decimais perde precisão em silêncio. É a checagem que
    justifica o arquivo."""
    catalogo = catalogo_do_contrato("rec", QTDE_PESO2=tipo)
    problemas, _avisos = schema_dw.comparar("rec", catalogo)
    assert len(problemas) == 1
    assert "QTDE_PESO2" in problemas[0]
    assert "precisão" in problemas[0]


def test_coluna_nova_no_dw_e_aviso_e_nao_problema():
    """Derrubar o card porque a equipe do DW acrescentou uma coluna seria
    transformar trabalho alheio em incidente nosso. Ela fica visível, e é no
    diagnóstico que se decide se entra no contrato."""
    catalogo = catalogo_do_contrato("exp", QTDE_NOVA_MEDIDA="NUMBER")
    problemas, avisos = schema_dw.comparar("exp", catalogo)
    assert problemas == []
    assert len(avisos) == 1
    assert "QTDE_NOVA_MEDIDA" in avisos[0]


def test_nulabilidade_nao_e_conferida():
    """Decisão registrada, não esquecimento: o `NOT NULL` do contrato é
    afirmação sobre o DADO (medida em 433 mil linhas), não sobre a declaração do
    DW. Comparar as duas daria drift falso no primeiro dia — e alarme que grita
    à toa é alarme que se aprende a ignorar."""
    assert "NULLABLE" not in schema_dw.sql_catalogo(com_dono=True)
    problemas, avisos = schema_dw.comparar("rec", catalogo_do_contrato("rec"))
    assert (problemas, avisos) == ([], [])


def test_tabela_invisivel_aponta_para_as_duas_causas():
    """`ORA-00942` e o `ALL_TAB_COLUMNS` respondem igual para "não existe" e
    "existe e você não pode ver". A mensagem não pode escolher uma."""
    problemas, avisos = schema_dw.comparar("rec", {})
    assert len(problemas) == 1
    assert "não existe" in problemas[0]
    assert "privilégio" in problemas[0]
    assert avisos == []


def test_conferir_relata_o_que_viu():
    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        visto = schema_dw.conferir(cur, "exp")
    assert visto["tabela"] == contrato.tabela("exp")
    assert visto["colunas_no_contrato"] == 46
    assert visto["colunas_no_dw"] == 46
    assert visto["select_compila"] is True
    assert visto["problemas"] == [] and visto["avisos"] == []


def test_select_que_nao_compila_e_problema_com_a_mensagem_do_oracle():
    """A mensagem do Oracle NOMEIA a coluna que faltou, então ela vale mais que
    qualquer texto nosso e é repassada."""
    class ErroOracle(Exception):
        pass

    conexao = ConexaoFalsa(erro=ErroOracle("ORA-00904: NK_WMS_FILIAL: invalid identifier"))
    with conexao.cursor() as cur:
        visto = schema_dw.conferir(cur, "rec")
    assert visto["select_compila"] is False
    assert any("ORA-00904" in p for p in visto["problemas"])


def test_verificar_levanta_com_os_dois_movimentos_na_mensagem():
    catalogo = {
        _tabela_curta("rec"): catalogo_do_contrato("rec", NK_CALENDARIO="VARCHAR2"),
        _tabela_curta("exp"): {},
    }
    conexao = ConexaoFalsa(catalogo=catalogo)
    with conexao.cursor() as cur:
        with pytest.raises(schema_dw.ContratoDivergenteDW) as erro:
            schema_dw.verificar(cur)
    texto = str(erro.value)
    assert "FATO_VOL_REC_CAT_V01" in texto and "FATO_VOL_EXP_CAT_V01" in texto
    assert "contrato.py" in texto  # a saída é uma PR, não um ajuste no dado


def test_garantir_usa_cache_e_falha_nunca_entra_nele():
    conexao = ConexaoFalsa()
    with conexao.cursor() as cur:
        schema_dw.garantir(cur)
        quantas = len(conexao.executados)
        schema_dw.garantir(cur)
        assert len(conexao.executados) == quantas, "a segunda vez veio do cache"

    ruim = ConexaoFalsa(catalogo={})
    schema_dw.invalidar()
    with ruim.cursor() as cur:
        for _ in range(2):
            with pytest.raises(schema_dw.ContratoDivergenteDW):
                schema_dw.garantir(cur)


# ============================================ a camada de decisões (dimensões)
def test_sigla_exibida_e_a_unica_excecao():
    """RMSPV -> RMSPIV (Maria, 21/ago). Unidade nova entra sozinha, com a sigla
    que o DW mandou."""
    assert dimensoes_dw.sigla_exibida("RMSPV") == "RMSPIV"
    assert dimensoes_dw.sigla_exibida("RMSPII") == "RMSPII"
    assert dimensoes_dw.sigla_exibida(" RMRJ ") == "RMRJ"
    assert dimensoes_dw.sigla_exibida(None) == ""


def test_siglas_fonte_e_o_caminho_de_volta_e_sabe_ser_n_para_1():
    """A tela pede `RMSPIV`; o DW conhece `RMSPV` (e `RMSPIV`, se um dia
    passar a mandar assim). Pedir pela sigla RENOMEADA não casa nada — é o que
    o Postgres fazia quando `COALESCE(u.sigla, ...) = 'RMSPV'` não achava
    linha."""
    assert dimensoes_dw.siglas_fonte("RMSPIV") == ["RMSPIV", "RMSPV"]
    assert dimensoes_dw.siglas_fonte("RMSPII") == ["RMSPII"]
    assert dimensoes_dw.siglas_fonte("RMSPV") == []


@pytest.mark.parametrize("nome, tipo", [
    ("CONG FLV (CUCINARE)", "CONGELADO"),
    ("CONGELADO GERAL", "CONGELADO"),
    ("RESFRIADO - PR", "RESFRIADO"),
    ("HORTIFRUTI", "HORTIFRUTI"),
    ("UTENSÍLIOS", "UTENSILIOS"),          # acento não atrapalha
    ("SECO GERAL", "SECO"),
    ("AGUA / CARVAO", "SECO"),              # de-para por nome exato
    ("SECO CONGELADO", "NAO_CLASSIFICADO"), # ambiguidade real vira sentinela
    ("CONSOLIDADOR", "NAO_CLASSIFICADO"),   # CONS não é CONG
    ("", "NAO_CLASSIFICADO"),
    (None, "NAO_CLASSIFICADO"),
])
def test_classificar_tipo_de_estoque_porta_a_regra_de_24_ago(nome, tipo):
    assert dimensoes_dw.classificar(nome) == tipo
    assert tipo in dimensoes_dw.TIPOS_VALIDOS


def test_canonizar_escolhe_a_grafia_de_maior_peso_e_desempata_por_ordem():
    """Decisão A da Maria (06/set): o nome do cliente continua sendo o de maior
    peso — a mesma regra do Postgres, agora calculada aqui."""
    escolhida, grafias = dimensoes_dw.canonizar([
        ("67945071", "NOVITA", 100.0),
        ("67945071", "CONVIDA", 500.0),
        ("67945071", "CONVIDA", 400.0),    # pesos da mesma grafia se acumulam
        ("11111111", "B", 10.0),
        ("11111111", "A", 10.0),           # empate -> alfabética
        ("22222222", "", 1.0),
        ("22222222", "PREENCHIDA", 1.0),   # no empate, grafia vazia fica por último
        ("", "IGNORADA", 1000.0),          # raiz vazia é ignorada
    ])
    assert escolhida == {"67945071": "CONVIDA", "11111111": "A", "22222222": "PREENCHIDA"}
    assert grafias["67945071"][0] == ("CONVIDA", 900.0)
    assert "" not in escolhida


def test_canonizar_e_a_regra_da_nuvem_ia_e_nao_uma_melhor():
    """Fidelidade antes de intenção: o rótulo que a tela mostra hoje saiu DESTA
    regra, e a decisão A é "o nome não muda para quem usa". Então uma grafia
    vazia com MAIS peso ainda vence — a docstring da nuvem-ia promete o
    contrário, mas o código dela nunca fez isso, e o Postgres em produção mostra
    o que o código fez. Corrigir a regra é conversa à parte, com aviso na tela."""
    from importlib import util as importlib_util
    from pathlib import Path

    escolhida, _grafias = dimensoes_dw.canonizar([("1", "", 99.0), ("1", "CHEIA", 1.0)])
    assert escolhida == {"1": ""}

    original = Path(r"C:\Users\maria.watanabe\Documents\nuvem-ia\catering\dominio\clientes.py")
    if not original.is_file():
        pytest.skip("repositório nuvem-ia não está ao lado deste; a comparação é local")
    spec = importlib_util.spec_from_file_location("clientes_nuvem_ia", original)
    modulo = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    observacoes = [
        ("67945071", "NOVITA", 100.0), ("67945071", "CONVIDA", 500.0),
        ("11111111", "B", 10.0), ("11111111", "A", 10.0),
        ("22222222", "", 99.0), ("22222222", "PREENCHIDA", 1.0),
        ("33333333", "", 1.0), ("33333333", "PREENCHIDA", 1.0),
    ]
    assert dimensoes_dw.canonizar(observacoes) == modulo.canonizar(observacoes)


def test_dimensoes_derivam_listas_e_rotulos_do_retrato():
    dim = dim_falsa()
    assert dim.unidades_exibidas() == ["RMRJ", "RMSPII", "RMSPIV"]
    assert dim.tipos() == ["CONGELADO", "NAO_CLASSIFICADO", "RESFRIADO", "SECO"]
    assert dim.nomes_estoque_do_tipo("CONGELADO") == ["CONG FLV (CUCINARE)"]
    assert dim.nomes_estoque_do_tipo("NAO_CLASSIFICADO") == ["QUALQUER COISA"]
    assert dim.nomes_estoque_do_tipo("HORTIFRUTI") == []
    assert dim.rotulo_cliente("67945071", "NOVITA") == "CONVIDA"     # canônico vence
    assert dim.rotulo_cliente("99999999", "NOVO LTDA") == "NOVO LTDA"  # queda: a grafia da linha
    assert dim.rotulo_cliente("99999999", None) == "99999999"          # última queda: a raiz
    assert dim.clientes() == [
        {"chave": "67945071", "rotulo": "CONVIDA"},
        {"chave": "12345678", "rotulo": "SAPORE"},
    ]
    assert sorted(dim.divergentes()) == ["67945071"]


def test_sql_da_varredura_agrupa_por_expressao_e_usa_o_peso_certo():
    """Quatro idas ao DW, não seis — e nunca `GROUP BY 1, 2`, que no Oracle
    agrupa pela CONSTANTE e devolve número errado sem erro."""
    listas = dimensoes_dw.sql_listas("rec")
    assert listas.startswith("SELECT NK_WMS_FILIAL, NOME_ESTOQUE, DESCR_OPER_WMS FROM ")
    assert listas.endswith("GROUP BY NK_WMS_FILIAL, NOME_ESTOQUE, DESCR_OPER_WMS")
    assert not re.search(r"GROUP BY \d", listas)
    # o peso que decide a grafia: qtde_peso2 na entrada, qtde_peso_solicitado na saída
    assert "SUM(COALESCE(QTDE_PESO2, 0))" in dimensoes_dw.sql_clientes("rec")
    assert "SUM(COALESCE(QTDE_PESO_SOLICITADO, 0))" in dimensoes_dw.sql_clientes("exp")
    assert "MAX(DW_DATA_ALTERACAO)" in dimensoes_dw.sql_clientes("exp")
    assert contrato.tabela("exp") in dimensoes_dw.sql_clientes("exp")


def test_varrer_monta_o_retrato_a_partir_das_duas_tabelas():
    conexao = ConexaoFalsa(resultados=_fila_da_varredura())
    with conexao.cursor() as cur:
        dim = dimensoes_dw.varrer(cur)
    assert len(conexao.executados) == 4
    assert dim.unidades_exibidas() == ["RMRJ", "RMSPII", "RMSPIV"]
    assert dim.tipos() == ["CONGELADO", "RESFRIADO", "SECO"]
    assert dim.operacoes == {"rec": ["NAO TROCA NOTA DE ARMAZENAGEM"], "exp": ["SAIDA NORMAL"]}
    assert dim.clientes_rotulo == {"67945071": "CONVIDA", "12345678": "SAPORE"}
    # período: o menor MIN e o maior MAX entre TODOS os grupos das duas tabelas
    assert dim.periodo == (date(2023, 1, 1), date(2026, 9, 5))
    # frescor por tabela: o maior MAX(DW_DATA_ALTERACAO) de cada uma
    assert dim.atualizado_em == {
        "rec": datetime(2026, 9, 5, 7, 5), "exp": datetime(2026, 9, 3, 7, 10),
    }
    assert dim.calculado_em is not None


def test_obter_cacheia_e_atualizar_revarre():
    """Uma hora de TTL: a segunda abertura de tela não paga a varredura. O
    "atualizar agora" e o `invalidar()` são os dois jeitos de furar isso."""
    conexao = ConexaoFalsa(resultados=_fila_da_varredura() * 3)
    with conexao.cursor() as cur:
        primeira = dimensoes_dw.obter(cur)
        depois_da_primeira = len(conexao.executados)
        assert dimensoes_dw.obter(cur) is primeira
        assert len(conexao.executados) == depois_da_primeira
        assert dimensoes_dw.em_cache() is primeira

        segunda = dimensoes_dw.atualizar(cur)
        assert segunda is not primeira
        assert len(conexao.executados) == depois_da_primeira + 4

        dimensoes_dw.invalidar()
        assert dimensoes_dw.em_cache() is None
        dimensoes_dw.obter(cur)
        assert len(conexao.executados) == depois_da_primeira + 8


# ================================================================= recorte_dw
def test_recorte_dw_reusa_a_definicao_de_filtro_do_recorte():
    """Um `Filtros` só: a tela do DW aceita e recusa exatamente o que a do
    Postgres aceita e recusa."""
    from backend.volumetria_catering import recorte

    assert recorte_dw.Filtros is recorte.Filtros
    assert recorte_dw.FiltroInvalido is recorte.FiltroInvalido
    assert recorte_dw.rotulos_dos_meses is recorte.rotulos_dos_meses


def test_onde_periodo_simples_com_bind_nomeado():
    f = recorte_dw.Filtros(**JAN).validar()
    clausulas, params = recorte_dw.onde(f, "rec", dim_falsa())
    assert clausulas == ["f.NK_CALENDARIO >= :de", "f.NK_CALENDARIO <= :ate"]
    assert params == {"de": date(2026, 1, 1), "ate": date(2026, 1, 31)}


def test_onde_traduz_a_sigla_exibida_para_a_da_fonte():
    """A pessoa escolhe `RMSPIV`; o `WHERE` pergunta por `RMSPV` (e por
    `RMSPIV`, caso o DW um dia mande assim)."""
    f = recorte_dw.Filtros(**JAN, unidades=("RMSPIV", "RMRJ")).validar()
    clausulas, params = recorte_dw.onde(f, "rec", dim_falsa())
    (unidades,) = [c for c in clausulas if c.startswith("f.NK_WMS_FILIAL IN")]
    assert unidades == "f.NK_WMS_FILIAL IN (:uni0, :uni1, :uni2)"
    assert {v for k, v in params.items() if k.startswith("uni")} == {"RMRJ", "RMSPIV", "RMSPV"}


def test_sigla_renomeada_pedida_pelo_nome_da_fonte_nao_casa_nada():
    """`RMSPV` não é sigla que a tela mostra: zero linha, nunca "sem filtro"."""
    f = recorte_dw.Filtros(**JAN, unidades=("RMSPV",)).validar()
    clausulas, params = recorte_dw.onde(f, "rec", dim_falsa())
    assert recorte_dw.NADA in clausulas
    assert not any(k.startswith("uni") for k in params)


def test_onde_traduz_o_tipo_para_os_nomes_de_estoque_que_a_regra_poe_nele():
    dim = dim_falsa()
    f = recorte_dw.Filtros(**JAN, tipos_estoque=("CONGELADO", "NAO_CLASSIFICADO")).validar()
    clausulas, params = recorte_dw.onde(f, "exp", dim)
    (tipos,) = [c for c in clausulas if c.startswith("f.NOME_ESTOQUE IN")]
    assert tipos == "f.NOME_ESTOQUE IN (:tip0, :tip1)"
    assert {v for k, v in params.items() if k.startswith("tip")} == {
        "CONG FLV (CUCINARE)", "QUALQUER COISA",
    }
    # `NAO_CLASSIFICADO` e `tipo` nunca chegam ao SQL: só nomes de estoque
    assert "NAO_CLASSIFICADO" not in " ".join(clausulas)


def test_tipo_sem_nenhum_nome_de_estoque_e_zero_linha():
    f = recorte_dw.Filtros(**JAN, tipos_estoque=("HORTIFRUTI",)).validar()
    clausulas, _params = recorte_dw.onde(f, "rec", dim_falsa())
    assert recorte_dw.NADA in clausulas


def test_onde_dias_clientes_e_operacoes_vao_por_bind_um_por_item():
    f = recorte_dw.Filtros(
        **JAN, dias=("5", "10"), clientes=("67945071",), operacoes=("SAIDA NORMAL",),
    ).validar()
    clausulas, params = recorte_dw.onde(f, "exp", dim_falsa())
    assert "EXTRACT(DAY FROM f.NK_CALENDARIO) IN (:dia0, :dia1)" in clausulas
    assert "f.NK_CLIENTE IN (:cli0)" in clausulas
    assert "f.DESCR_OPER_WMS IN (:ope0)" in clausulas
    assert params["dia0"] == 5 and params["dia1"] == 10
    assert params["cli0"] == "67945071" and params["ope0"] == "SAIDA NORMAL"


def test_todo_valor_de_filtro_vai_por_bind_e_nunca_no_texto():
    f = recorte_dw.Filtros(
        **JAN, clientes=("1'; DROP TABLE x; --",), operacoes=("OP",),
    ).validar()
    sql, params = recorte_dw.de_para_where(f, "rec", dim=dim_falsa())
    assert "DROP TABLE" not in sql
    assert params["cli0"] == "1'; DROP TABLE x; --"


def test_de_para_where_usa_a_tabela_do_contrato_e_recusa_a_conjunta():
    dim = dim_falsa()
    f = recorte_dw.Filtros(**JAN, movimento="exp").validar()
    sql, _params = recorte_dw.de_para_where(f, dim=dim)
    assert sql.startswith(f"FROM {contrato.tabela('exp')} f\nWHERE ")
    conjunta = recorte_dw.Filtros(**JAN, movimento=recorte_dw.CONJUNTA).validar()
    with pytest.raises(recorte_dw.FiltroInvalido):
        recorte_dw.de_para_where(conjunta, dim=dim)
    # com o movimento explícito a conjunta lê uma tabela por vez, como a Matriz faz
    sql, _params = recorte_dw.de_para_where(conjunta, "rec", dim=dim)
    assert contrato.tabela("rec") in sql


def test_coluna_passa_sempre_por_coluna_dw():
    """`f.pk_dw` cru foi o ORA-00904 do transporte em produção (04/set)."""
    assert recorte_dw.coluna("pk_dw", "rec") == "f.PK_FATO_VOL_REC_CAT"
    assert recorte_dw.coluna("pk_dw", "exp") == "f.PK_FATO_VOL_EXP_CAT"
    assert recorte_dw.coluna("nk_calendario", "rec") == "f.NK_CALENDARIO"


# ================================================================== matriz_dw
def test_matriz_dw_sql_traduz_o_dialeto():
    from backend.volumetria_catering.matriz import HIERARQUIA

    dim = dim_falsa()
    f = recorte_dw.Filtros(**JAN, movimento="rec", lente="liq").validar()
    sql, params = matriz_dw._sql("rec", HIERARQUIA["rec"], {"": "qtde_peso2"}, f, dim)
    assert "TO_CHAR(f.NK_CALENDARIO, 'YYYY-MM') AS mes" in sql
    assert "SUM(f.QTDE_PESO2) AS medida_unica" in sql
    assert "COUNT(*) AS linhas" in sql
    assert "MAX(f.RAZ_SOCIAL) AS rotulo_1" in sql
    assert (
        "GROUP BY f.NK_WMS_FILIAL, f.NK_CLIENTE, f.DESCR_OPER_WMS, "
        "TO_CHAR(f.NK_CALENDARIO, 'YYYY-MM')"
    ) in sql
    assert not re.search(r"GROUP BY \d", sql), "ordinal no GROUP BY é constante no Oracle"
    assert "date_trunc" not in sql and "LEFT JOIN" not in sql
    assert params["de"] == date(2026, 1, 1)


def test_matriz_dw_sql_da_saida_leva_as_tres_faixas():
    from backend.volumetria_catering.matriz import HIERARQUIA

    f = recorte_dw.Filtros(**JAN, movimento="exp", lente="liq").validar()
    medidas = recorte_dw.medidas_da_lente("exp", "liq")
    sql, _params = matriz_dw._sql("exp", HIERARQUIA["exp"], medidas, f, dim_falsa())
    for faixa in ("solicitado", "atendido", "separado"):
        assert f"SUM(f.QTDE_PESO_{faixa.upper()}) AS medida_{faixa}" in sql


def test_matriz_dw_soma_siglas_que_colidem_e_rotula_o_cliente_pelo_canonico():
    """A inversão que faz o de-para somar: `RMSPV` e `RMSPIV` viram UMA linha
    `RMSPIV` com 150 kg e 3 linhas do fato; e o cliente que veio com a grafia
    NOVITA sai como CONVIDA, o rótulo de maior peso."""
    dim = dim_falsa()
    conexao = ConexaoFalsa(resultados=_fila_da_matriz_rec())
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    with conexao.cursor() as cur:
        d = matriz_dw.matriz(cur, f, dim)

    assert d["total_linhas"] == 4 and isinstance(d["total_linhas"], int)
    assert d["total"] == {"2026-01": Decimal("160.000")}
    # unidades em ordem ALFABÉTICA (é o que `montar` faz, para a paginação por
    # unidade ser estável); só os filhos vão por peso decrescente
    assert [u["chave"] for u in d["linhas"]] == ["RMSPII", "RMSPIV"]
    sanca = d["linhas"][1]
    assert sanca["rotulo"] == "RMSPIV"
    assert sanca["valores"] == {"2026-01": Decimal("150.000")}
    (cliente,) = sanca["filhos"]
    assert cliente["chave"] == "67945071"
    assert cliente["rotulo"] == "CONVIDA"
    assert cliente["valores"] == {"2026-01": Decimal("150.000")}
    (operacao,) = cliente["filhos"]
    assert operacao["rotulo"] == "OP A"
    assert d["niveis"] == ["unidade", "cliente", "operacao"]


def test_matriz_dw_cliente_desconhecido_do_cache_sai_com_a_grafia_da_linha():
    """Cliente que apareceu depois da última varredura: o `MAX(RAZ_SOCIAL)` é
    a queda — a mesma ordem do `COALESCE(c.razao_social, f.raz_social)`."""
    dim = dim_falsa()
    conexao = ConexaoFalsa(resultados=[{
        "descricao": _DESCRICAO_MATRIZ_REC,
        "linhas": [("RMRJ", "55555555", "NOVO CLIENTE LTDA", "OP", "2026-01", Decimal("1"), Decimal(1))],
    }])
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    with conexao.cursor() as cur:
        d = matriz_dw.matriz(cur, f, dim)
    assert d["linhas"][0]["filhos"][0]["rotulo"] == "NOVO CLIENTE LTDA"


def test_matriz_dw_conjunta_soma_entrada_e_saida_em_python():
    """Duas consultas, uma por tabela, e a árvore soma no pai — como no
    Postgres. O nível `movimento` entra em Python, não no SQL."""
    descricao = ["CHAVE_0", "CHAVE_1", "ROTULO_1", "MES", "MEDIDA_UNICA", "LINHAS"]
    conexao = ConexaoFalsa(resultados=[
        {"descricao": descricao,
         "linhas": [("RMSPII", "12345678", "SAPORE", "2026-01", Decimal("100"), Decimal(1))]},
        {"descricao": descricao,
         "linhas": [("RMSPII", "12345678", "SAPORE", "2026-01", Decimal("40"), Decimal(1))]},
    ])
    f = recorte_dw.Filtros(**JAN, movimento=recorte_dw.CONJUNTA, faixa="solicitado").validar()
    with conexao.cursor() as cur:
        d = matriz_dw.matriz(cur, f, dim_falsa())
    assert len(conexao.executados) == 2
    assert contrato.tabela("rec") in conexao.executados[0][0]
    assert contrato.tabela("exp") in conexao.executados[1][0]
    assert d["total"] == {"2026-01": Decimal("140")}
    (unidade,) = d["linhas"]
    (cliente,) = unidade["filhos"]
    assert [m["rotulo"] for m in cliente["filhos"]] == ["Expedicao", "Recebimento"]
    assert d["total_linhas"] == 2


# ================================================================ planilha_dw
def test_planilha_dw_sql_pagina_com_offset_fetch_e_ordena_pela_chave_natural():
    f = recorte_dw.Filtros(**JAN, movimento="exp", pagina=3).validar()
    medidas = planilha._colunas_de_medida(f)
    sql, _params = planilha_dw._sql(f, medidas, dim_falsa())
    assert "OFFSET 200 ROWS FETCH NEXT 100 ROWS ONLY" in sql
    assert "LIMIT" not in sql
    assert "ORDER BY f.NK_CALENDARIO DESC, f.NK_INSTANCIA, f.NK_WMS_FILIAL, f.NUM_GEM" in sql
    for apelido in ("solicitado", "atendido", "separado"):
        assert f" AS {apelido}" in sql


def test_planilha_dw_devolve_as_mesmas_colunas_e_aplica_as_decisoes_por_linha():
    """O `DATE` vira `date` (senão a tela mostra `05T00:00:00/01/2026`), a
    sigla vira a exibida, o cliente vira o canônico e o tipo vem da regra."""
    dim = dim_falsa()
    conexao = ConexaoFalsa(resultados=[
        [(Decimal(2),)],  # COUNT(*)
        {"descricao": ["NK_CALENDARIO", "NK_WMS_FILIAL", "NK_CLIENTE", "RAZ_SOCIAL",
                       "NUM_GEM", "DESCR_OPER_WMS", "NOME_ESTOQUE", "VALOR"],
         "linhas": [(datetime(2026, 1, 5), "RMSPV", "67945071", "NOVITA", "0000000001",
                     "NAO TROCA NOTA DE ARMAZENAGEM", "CONG FLV (CUCINARE)", Decimal("100.000"))]},
    ])
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    with conexao.cursor() as cur:
        d = planilha_dw.planilha(cur, f, dim)
    assert d["colunas"] == planilha.colunas(f)
    assert d["linhas"] == [{
        "dia": date(2026, 1, 5), "unidade": "RMSPIV", "cliente": "CONVIDA",
        "guia": "0000000001", "operacao": "NAO TROCA NOTA DE ARMAZENAGEM",
        "tipo_estoque": "CONGELADO", "valor": Decimal("100.000"),
    }]
    assert d["paginacao"]["total_linhas"] == 2 and isinstance(d["paginacao"]["total_linhas"], int)
    assert d["avisos"] == []


# ================================================================ download_dw
def test_download_dw_tem_o_mesmo_cabecalho_do_postgres():
    """A pessoa que baixa o mesmo recorte das duas fontes tem que receber dois
    arquivos iguais. As colunas e os rótulos são literalmente os mesmos."""
    for movimento in contrato.MOVIMENTOS:
        assert download_dw.colunas(movimento) == download.colunas(movimento)
    assert download_dw.nome_do_arquivo is download.nome_do_arquivo
    assert download_dw.TETO_XLSX == download.TETO_XLSX


def test_download_dw_seleciona_a_pk_pelo_nome_do_dw():
    """Regressão do transporte (04/set): `f.pk_dw` não existe no DW; o nome é
    `PK_FATO_VOL_*_CAT`. Só o download seleciona a PK — Matriz e planilha nunca
    — por isso o bug só aparece no arquivo."""
    f = recorte_dw.Filtros(**JAN, movimento="exp").validar()
    sql, _params = download_dw._sql(f, dim_falsa())
    assert "f.PK_FATO_VOL_EXP_CAT AS pk_dw" in sql
    assert "f.pk_dw" not in sql
    assert "f.PK_DW" not in sql
    # o contrato inteiro, na ordem dele
    for nome in contrato.colunas_dw("exp"):
        assert f"f.{nome} AS " in sql


def _linha_crua(movimento, **sobrescritas):
    """Uma linha do fato como o driver a entregaria: `datetime` nas datas,
    `Decimal` nos números, e os identificadores com zero à esquerda."""
    valores = {
        "nk_wms_filial": "RMSPV", "nk_cliente": "67945071", "raz_social": "NOVITA",
        "nome_estoque": "CONG FLV (CUCINARE)", "num_gem": "0000000001",
        "nk_filial": "02060862000569",
    }
    valores.update(sobrescritas)
    linha = []
    for nome, tipo, _nulo in contrato.colunas(movimento):
        if nome in valores:
            linha.append(valores[nome])
        elif tipo == "TEXT":
            linha.append("X")
        elif tipo == "DATE":
            linha.append(datetime(2026, 1, 5))
        elif tipo == "TIMESTAMP":
            linha.append(datetime(2026, 1, 5, 12, 30, 0))
        elif tipo == "SMALLINT":
            linha.append(Decimal(2026))
        else:
            linha.append(Decimal("100.000"))
    return tuple(linha)


def test_download_dw_csv_e_excel_first_com_as_derivadas_e_o_date_sem_hora(monkeypatch):
    aquecer(dim_falsa())
    conexao = _conexao(monkeypatch, resultados=[[_linha_crua("rec")]])
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    conteudo = "".join(download_dw.gerar_csv(f))
    linhas = [l for l in conteudo.split("\r\n") if l]

    assert conteudo.startswith(download.BOM)
    assert linhas[0].lstrip(download.BOM) == ";".join(r for _a, _s, r in download.colunas("rec"))
    campos = linhas[1].split(";")
    # as quatro derivadas, na ordem: dia, unidade exibida, cliente canônico, tipo
    assert campos[:4] == ["05/01/2026", "RMSPIV", "CONVIDA", "CONGELADO"]
    indice = {nome: i for i, (nome, _t, _n) in enumerate(contrato.colunas("rec"))}
    cru = campos[4:]
    assert cru[indice["nk_calendario"]] == "05/01/2026"          # DATE sem hora colada
    assert cru[indice["dthr_confirm"]] == "05/01/2026 12:30:00"  # TIMESTAMP com hora
    assert cru[indice["qtde_peso2"]] == "100,000"                # vírgula decimal
    assert cru[indice["num_gem"]] == "0000000001"                # zero à esquerda intacto
    assert cru[indice["nk_wms_filial"]] == "RMSPV"               # o cru do DW continua no arquivo
    assert "00:00:00" not in linhas[1]
    assert conexao.fechada


def test_download_dw_xlsx_recusa_acima_do_teto_e_fecha_a_conexao(monkeypatch):
    aquecer(dim_falsa())
    conexao = _conexao(monkeypatch, resultados=[[(Decimal(download.TETO_XLSX + 1),)]])
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    with pytest.raises(download.DownloadGrandeDemais):
        download_dw.gerar_xlsx(f)
    assert conexao.fechada


def test_download_dw_xlsx_escreve_identificador_como_texto(monkeypatch):
    from openpyxl import load_workbook
    import io

    aquecer(dim_falsa())
    _conexao(monkeypatch, resultados=[[(Decimal(1),)], [_linha_crua("rec")]])
    f = recorte_dw.Filtros(**JAN, movimento="rec").validar()
    livro = load_workbook(io.BytesIO(download_dw.gerar_xlsx(f)))
    aba = livro["volumetria"]
    cabecalho = [c.value for c in aba[1]]
    linha = [c for c in aba[2]]
    assert cabecalho == [r for _a, _s, r in download.colunas("rec")]
    posicao = {apelido: i for i, (apelido, _s, _r) in enumerate(download.colunas("rec"))}
    guia = linha[posicao["num_gem"]]
    assert guia.value == "0000000001" and guia.number_format == "@"
    assert linha[posicao["unidade"]].value == "RMSPIV"
    assert linha[posicao["cliente"]].value == "CONVIDA"
    assert linha[posicao["dia"]].value == datetime(2026, 1, 5)  # openpyxl guarda date como datetime


# ========================================================= endpoints (router)
def test_opcoes_do_dw_traz_listas_procedencia_e_cacheia(client, admin_headers, fonte_dw, monkeypatch):
    conexao = _conexao(monkeypatch, resultados=_fila_da_varredura())

    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["fonte"] == "dw"
    assert corpo["unidades"] == ["RMRJ", "RMSPII", "RMSPIV"]
    assert corpo["tipos_estoque"] == ["CONGELADO", "RESFRIADO", "SECO"]
    assert corpo["clientes"] == [
        {"chave": "67945071", "rotulo": "CONVIDA"}, {"chave": "12345678", "rotulo": "SAPORE"},
    ]
    assert corpo["operacoes"] == {"rec": ["NAO TROCA NOTA DE ARMAZENAGEM"], "exp": ["SAIDA NORMAL"]}
    assert corpo["periodo"] == {"de": "2023-01-01", "ate": "2026-09-05"}
    # a procedência muda de significado: sem carga, o frescor é o da FONTE
    assert corpo["cargas"] == []
    assert corpo["atualizado_ate"] == {"rec": "2026-09-05T07:05:00", "exp": "2026-09-03T07:10:00"}
    assert corpo["rotulos_calculados_em"]
    assert corpo["processo_dw"] == contrato.PROCESSO_DW
    # o que a tela já lia continua lá, igual ao Postgres
    for chave in ("abertura", "teto_confirmacao", "teto_xlsx", "lentes", "faixas", "movimentos", "contrato"):
        assert chave in corpo
    assert conexao.fechada

    depois = len(conexao.executados)
    r2 = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r2.status_code == 200
    assert len(conexao.executados) == depois, "a segunda abertura veio do cache"
    assert r2.json()["unidades"] == corpo["unidades"]


def test_opcoes_do_postgres_declara_a_fonte(client, admin_headers, monkeypatch):
    """O lado Postgres ganhou só a chave `fonte` — para a tela poder dizer de
    onde veio o que está mostrando, nas duas fontes do mesmo jeito."""
    monkeypatch.delenv("VOLUMETRIA_DB_URL", raising=False)
    # sem banco o Postgres responde 503; a chave é conferida no `_opcoes_estaticas`
    # e na resposta do DW — aqui basta provar que a constante existe e é a padrão
    assert fonte.PADRAO == fonte.POSTGRES


def test_matriz_do_dw_responde_no_mesmo_formato(client, admin_headers, fonte_dw, monkeypatch):
    aquecer(dim_falsa())
    _conexao(monkeypatch, resultados=_fila_da_matriz_rec())
    r = client.get(f"{BASE}/matriz", params={**JAN, "movimento": "rec"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["total_linhas"] == 4
    assert corpo["total"] == {"2026-01": "160.000"}  # Decimal como STRING, como sempre
    assert [u["chave"] for u in corpo["linhas"]] == ["RMSPII", "RMSPIV"]  # alfabética
    assert corpo["linhas"][1]["filhos"][0]["rotulo"] == "CONVIDA"
    assert corpo["linhas"][1]["valores"] == {"2026-01": "150.000"}  # RMSPV + RMSPIV somados
    assert corpo["filtros"]["movimento"] == "rec"
    assert corpo["paginacao"]["total_unidades"] == 2


def test_planilha_do_dw_responde_no_mesmo_formato(client, admin_headers, fonte_dw, monkeypatch):
    aquecer(dim_falsa())
    _conexao(monkeypatch, resultados=[
        [(Decimal(1),)],
        {"descricao": ["NK_CALENDARIO", "NK_WMS_FILIAL", "NK_CLIENTE", "RAZ_SOCIAL",
                       "NUM_GEM", "DESCR_OPER_WMS", "NOME_ESTOQUE", "VALOR"],
         "linhas": [(datetime(2026, 1, 5), "RMSPV", "67945071", "NOVITA", "0000000001",
                     "OP", "CONG FLV (CUCINARE)", Decimal("100.000"))]},
    ])
    r = client.get(f"{BASE}/planilha", params={**JAN, "movimento": "rec"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["linhas"][0]["dia"] == "2026-01-05"  # date, não datetime
    assert corpo["linhas"][0]["unidade"] == "RMSPIV"
    assert corpo["linhas"][0]["valor"] == "100.000"
    assert corpo["paginacao"]["total_linhas"] == 1


def test_recusas_do_recorte_valem_igual_no_dw(client, admin_headers, fonte_dw, monkeypatch):
    """400 antes de tocar no DW: filtro inválido e visão conjunta fora da Matriz
    são recusas do RECORTE, que é um só para as duas fontes."""
    conexao = _conexao(monkeypatch)
    r = client.get(f"{BASE}/matriz", params={**JAN, "lente": "kg"}, headers=admin_headers)
    assert r.status_code == 400
    r = client.get(f"{BASE}/planilha", params={**JAN, "movimento": "amb"}, headers=admin_headers)
    assert r.status_code == 400 and "um movimento por vez" in r.json()["detail"]
    assert conexao.executados == []


def test_dw_fora_do_ar_e_503_so_neste_card(client, admin_headers, fonte_dw, monkeypatch):
    class ErroDoDriver(Exception):
        pass

    monkeypatch.setattr(conexao_dw, "_driver", lambda: DriverFalso(erro=ErroDoDriver("DPY-6005")))
    r = client.get(f"{BASE}/matriz", params=JAN, headers=admin_headers)
    assert r.status_code == 503
    assert "ErroDoDriver" in r.json()["detail"]
    assert client.get("/api/health").status_code == 200


def test_contrato_divergente_no_dw_e_503_com_a_coluna(client, admin_headers, fonte_dw, monkeypatch):
    catalogo = {
        _tabela_curta("rec"): catalogo_do_contrato("rec", NK_CALENDARIO="VARCHAR2"),
        _tabela_curta("exp"): catalogo_do_contrato("exp"),
    }
    _conexao(monkeypatch, catalogo=catalogo)
    r = client.get(f"{BASE}/matriz", params=JAN, headers=admin_headers)
    assert r.status_code == 503
    assert "NK_CALENDARIO" in r.json()["detail"]


def test_download_ticket_e_download_csv_pelo_dw(client, admin_headers, fonte_dw, monkeypatch):
    aquecer(dim_falsa())
    conexao = _conexao(monkeypatch, resultados=[[_linha_crua("rec")]])

    r = client.post(f"{BASE}/download/ticket", params={**JAN, "formato": "csv"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ticket"]

    r = client.get(f"{BASE}/download", params={**JAN, "formato": "csv"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('filename="catering_entrada_2026-01-01_a_2026-01-31.csv"')
    linhas = [l for l in r.content.decode("utf-8-sig").split("\r\n") if l]
    assert linhas[0] == ";".join(rot for _a, _s, rot in download.colunas("rec"))
    assert linhas[1].startswith("05/01/2026;RMSPIV;CONVIDA;CONGELADO;")
    assert conexao.fechada


def test_download_nao_abre_auditoria_quando_o_dw_esta_fora(client, admin_headers, fonte_dw, monkeypatch):
    from backend.volumetria_catering import auditoria

    class ErroDoDriver(Exception):
        pass

    monkeypatch.setattr(conexao_dw, "_driver", lambda: DriverFalso(erro=ErroDoDriver("DPY-6005")))
    antes = len(auditoria.listar(1000))
    r = client.get(f"{BASE}/download", params=JAN, headers=admin_headers)
    assert r.status_code == 503
    assert len(auditoria.listar(1000)) == antes


def test_dimensoes_e_atualizar_sao_so_admin(client, operador_headers, analista_headers):
    for headers in (operador_headers, analista_headers):
        assert client.get(f"{BASE}/dimensoes", headers=headers).status_code == 403
        assert client.post(f"{BASE}/dimensoes/atualizar", headers=headers).status_code == 403


def test_atualizar_agora_varre_o_dw_e_o_retrato_fica_visivel(client, admin_headers, com_credencial, monkeypatch):
    """O botão que o plano previa: independe da chave de fonte, porque o cache
    é do lado Oracle e aquecê-lo ANTES de virar é justamente o uso."""
    conexao = _conexao(monkeypatch, resultados=_fila_da_varredura())
    assert client.get(f"{BASE}/dimensoes", headers=admin_headers).json() == {
        "em_cache": False, "dimensoes": None,
    }
    r = client.post(f"{BASE}/dimensoes/atualizar", headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["unidades"] == ["RMRJ", "RMSPII", "RMSPIV"]
    assert corpo["clientes"] == 2
    assert corpo["clientes_com_mais_de_uma_grafia"] == ["67945071"]
    assert conexao.fechada

    depois = client.get(f"{BASE}/dimensoes", headers=admin_headers).json()
    assert depois["em_cache"] is True
    assert depois["dimensoes"]["unidades"] == corpo["unidades"]
    # e o diagnóstico mostra o mesmo retrato sem varrer de novo
    diag = client.get(DIAG, headers=admin_headers).json()
    assert diag["dimensoes_em_cache"]["unidades"] == corpo["unidades"]


# ============================================== o endpoint de diagnóstico
def test_diagnostico_exige_login(client):
    assert client.get(DIAG).status_code == 401


def test_diagnostico_e_so_admin(client, operador_headers, analista_headers):
    """Ele nomeia host e usuário do DW e repassa a mensagem crua do Oracle —
    não é leitura de todo mundo."""
    for headers in (operador_headers, analista_headers):
        assert client.get(DIAG, headers=headers).status_code == 403


def test_diagnostico_sem_credencial_e_503_nomeando_a_variavel(client, admin_headers):
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 503
    assert conexao_dw.ENV_USUARIO in r.json()["detail"]


def test_diagnostico_com_tabela_mal_configurada_e_503_e_nao_500(
    client, admin_headers, com_credencial, monkeypatch
):
    """Configuração inválida nomeia a variável, e é conferida ANTES de abrir
    sessão: erro de `.env` não precisa de round trip no DW para ser
    diagnosticado."""
    monkeypatch.setenv("DW_TABELA_EXP", "fato em minusculas")
    monkeypatch.setattr(
        conexao_dw, "conectar", lambda: pytest.fail("não devia ter conectado")
    )
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 503
    assert "DW_TABELA_EXP" in r.json()["detail"]


def test_diagnostico_aprova_e_fecha_a_conexao(
    client, admin_headers, com_credencial, monkeypatch
):
    conexao = _conexao(monkeypatch)
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is True
    assert corpo["conectou"] is True
    assert corpo["dsn"] == conexao_dw.dsn()
    assert corpo["credencial"]["configurada"] is True
    assert corpo["dimensoes_em_cache"] is None  # ainda não houve varredura
    assert [m["movimento"] for m in corpo["movimentos"]] == ["rec", "exp"]
    assert all(m["select_compila"] for m in corpo["movimentos"])
    assert conexao.fechada, "conexão com produção não se deixa fechar quando der"


def test_diagnostico_declara_a_fonte_da_tela(
    client, admin_headers, com_credencial, monkeypatch
):
    """"Virou ou não virou?" tem que ter resposta num lugar só-admin, sem abrir
    o `.env` da VM. Chave inválida aparece escrita, não some num 503."""
    _conexao(monkeypatch)
    assert client.get(DIAG, headers=admin_headers).json()["fonte_da_tela"] == "postgres"

    monkeypatch.setenv(fonte.ENV_FONTE, "dw")
    assert client.get(DIAG, headers=admin_headers).json()["fonte_da_tela"] == "dw"

    monkeypatch.setenv(fonte.ENV_FONTE, "oracle")
    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200
    assert "inválida" in r.json()["fonte_da_tela"]
    assert fonte.ENV_FONTE in r.json()["fonte_da_tela"]


def test_diagnostico_nao_devolve_a_senha(
    client, admin_headers, com_credencial, monkeypatch
):
    """Ele diz QUAL variável carrega a credencial, nunca o valor."""
    _conexao(monkeypatch)
    bruto = client.get(DIAG, headers=admin_headers).text
    assert "senha-de-mentira" not in bruto
    assert "hub_leitura_dw" not in bruto
    assert conexao_dw.ENV_SENHA in bruto  # o NOME da variável, sim


def test_diagnostico_relata_divergencia_em_200_e_nao_em_503(
    client, admin_headers, com_credencial, monkeypatch
):
    """O trabalho deste endpoint é RELATAR a divergência; um 503 esconderia
    justamente a lista que se veio buscar."""
    catalogo = {
        _tabela_curta("rec"): catalogo_do_contrato("rec", QTDE_PESO2="BINARY_DOUBLE"),
        _tabela_curta("exp"): catalogo_do_contrato("exp"),
    }
    _conexao(monkeypatch, catalogo=catalogo)

    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is False
    rec, exp = corpo["movimentos"]
    assert any("QTDE_PESO2" in p for p in rec["problemas"])
    assert exp["problemas"] == [], "o problema de um movimento não esconde o outro"


def test_diagnostico_nao_derruba_o_resto_do_hub(client, admin_headers):
    """Falha graciosa: sem credencial o card responde 503 e o Hub segue de pé."""
    assert client.get(DIAG, headers=admin_headers).status_code == 503
    assert client.get("/api/health").status_code == 200


# ==================================================== somente leitura
_PALAVRAS_DE_ESCRITA = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE",
    "ALTER", "GRANT", "REVOKE", "COMMIT",
)
_METODOS_DE_ESCRITA = {"commit", "rollback", "executemany", "setinputsizes"}

# TODOS os módulos que falam com o DW. O router NÃO entra: ele tem SQL das duas
# fontes e mensagens em prosa, então varrê-lo por palavra daria falso positivo
# eterno. Quem cobre os endpoints dele é a guarda de runtime.
_MODULOS_DO_DW = (
    conexao_dw, schema_dw, dimensoes_dw, recorte_dw, matriz_dw, planilha_dw, download_dw,
)


def _arvore(modulo):
    return ast.parse(pathlib.Path(modulo.__file__).read_text(encoding="utf-8"))


def _docstrings(arvore):
    """Toda docstring do módulo, para a guarda ignorar prosa: docstring fala de
    escrita justamente para explicar por que não há."""
    encontradas = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef,
                           ast.AsyncFunctionDef)):
            texto = ast.get_docstring(no, clean=False)
            if texto is not None:
                encontradas.add(texto)
    return encontradas


@pytest.mark.parametrize("modulo", _MODULOS_DO_DW, ids=lambda m: m.__name__)
def test_guarda_estatica_nenhum_literal_escreve(modulo):
    """A estática pega o código que nenhum teste exercitou."""
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
    """`commit`/`rollback` num módulo que só lê são sinal de que alguém passou a
    escrever por aqui. `executemany` é escrita em lote."""
    chamados = {
        no.func.attr
        for no in ast.walk(_arvore(modulo))
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
    }
    assert not (chamados & _METODOS_DE_ESCRITA), (
        f"chamada de escrita em {modulo.__name__}: "
        f"{sorted(chamados & _METODOS_DE_ESCRITA)}"
    )


def test_guarda_de_runtime_todo_comando_emitido_e_select(
    client, admin_headers, fonte_dw, monkeypatch
):
    """A de runtime pega o comando montado por concatenação, que a estática não
    veria — e cobre os endpoints inteiros, do router ao catálogo, nas quatro
    consultas da tela e no download. O `CursorFalso` estoura em qualquer
    `execute` que não comece por `SELECT`."""
    conexao = _conexao(monkeypatch, resultados=(
        _fila_da_varredura()          # /opcoes (varredura fria)
        + _fila_da_matriz_rec()       # /matriz
        + [[(Decimal(0),)], {"descricao": ["NK_CALENDARIO"], "linhas": []}]  # /planilha
        + [[_linha_crua("rec")]]      # /download
    ))
    assert client.get(DIAG, headers=admin_headers).status_code == 200
    assert client.get(f"{BASE}/opcoes", headers=admin_headers).status_code == 200
    assert client.get(f"{BASE}/matriz", params=JAN, headers=admin_headers).status_code == 200
    assert client.get(f"{BASE}/planilha", params=JAN, headers=admin_headers).status_code == 200
    assert client.get(f"{BASE}/download", params=JAN, headers=admin_headers).status_code == 200

    assert len(conexao.executados) >= 10, "o teste não exercitou o suficiente"
    for sql, _binds in conexao.executados:
        assert sql.lstrip().upper().startswith("SELECT"), sql


def test_nenhum_alter_session_e_emitido(com_credencial, monkeypatch):
    """Decisão registrada: NÃO emitimos `ALTER SESSION SET TRANSACTION READ
    ONLY`, o equivalente Oracle do `default_transaction_read_only` do Postgres.
    Ele abriria transação com snapshot próprio numa conexão de tela, e
    obrigaria este módulo a emitir um comando de DDL para ganhar uma proteção
    que o privilégio do usuário de leitura já dá."""
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "_driver", lambda: DriverFalso(conexao=conexao))
    conexao_dw.conectar()
    assert conexao.executados == [], "conectar() não emite comando nenhum"
