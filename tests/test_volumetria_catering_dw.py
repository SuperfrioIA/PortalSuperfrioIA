"""Volumetria de catering — a conexão com o DW Oracle (lote D1).

## O limite desta suíte, dito antes de qualquer coisa

**Nenhum teste daqui conecta no DW.** O DW é produção, e a política é que a IA
não conecta nele. Tudo roda contra `DriverFalso`/`ConexaoFalsa`, de mentira, com
a mesma superfície estreita que `conexao_dw.py` e `schema_dw.py` usam. É o mesmo
padrão de `nuvem-ia/tests/test_catering_oracle.py`, e por isso este arquivo roda
na suíte normal — sem container, sem Postgres, e sem o `oracledb` instalado.

O que se prova aqui: o **statement** que sai, os **binds**, a leitura do
ambiente, a conferência de contrato, e que nenhum caminho emite comando de
escrita.

O que **não** se prova: que as tabelas do DW se chamam assim, que o usuário de
leitura tem privilégio, e que o tipo real das colunas é o esperado. Essas três
só a Maria prova, abrindo `/api/volumetria-catering/diagnostico-dw` na VM depois
de escrever a credencial no `.env` — e é esse o aceite do D1.

## Duas guardas de somente leitura, e não uma

- **estática**, sobre a árvore sintática de `conexao_dw.py` e `schema_dw.py`:
  nenhum literal com palavra de escrita, nenhuma chamada a
  `commit`/`rollback`/`executemany`. Pega o código que nenhum teste exercitou;
- **de runtime**, no cursor falso: todo `execute` que não comece por `SELECT`
  estoura. Pega o comando montado por concatenação, que a estática não veria —
  e cobre também o endpoint do router, que a estática não varre (o router tem
  SQL das duas fontes, e varrê-lo por palavra daria falso positivo eterno).
"""

import ast
import logging
import pathlib
import re

import pytest

from backend.volumetria_catering import conexao_dw, contrato, schema_dw

BASE = "/api/volumetria-catering"
DIAG = f"{BASE}/diagnostico-dw"

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
    """Só o que os dois módulos usam: execute, fetchall, arraysize/prefetchrows.

    Estreito de propósito: se o módulo passar a depender de mais coisa do
    driver, isto quebra e a dependência nova vira conversa."""

    def __init__(self, conexao):
        self.conexao = conexao
        self.arraysize = 100
        self.prefetchrows = 2
        self._resultado = []

    def __enter__(self):
        return self

    def __exit__(self, *_excecao):
        return False

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
        else:
            self._resultado = []  # o SELECT do contrato é `WHERE 1=0`

    def fetchall(self):
        return list(self._resultado)


class ConexaoFalsa:
    """Guarda o que foi executado e se foi fechada."""

    def __init__(self, catalogo=None, erro=None):
        self.catalogo = catalogo if catalogo is not None else _CATALOGO_BOM
        self.erro = erro
        self.executados = []
        self.fechada = False

    def cursor(self):
        return CursorFalso(self)

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


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Nenhum teste daqui herda credencial nem nome de tabela do ambiente, e o
    cache do drift é zerado nas duas pontas."""
    for var in (
        conexao_dw.ENV_USUARIO, conexao_dw.ENV_SENHA, conexao_dw.ENV_HOST,
        conexao_dw.ENV_PORTA, conexao_dw.ENV_SERVICO,
        "DW_TABELA_REC", "DW_TABELA_EXP",
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
    """Injeta o driver falso no lugar do import preguiçoso."""
    falso = DriverFalso()
    monkeypatch.setattr(conexao_dw, "_driver", lambda: falso)
    return falso


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
    fonte = pathlib.Path(conexao_dw.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    no_topo = [
        no for no in arvore.body if isinstance(no, (ast.Import, ast.ImportFrom))
    ]
    importados = {
        alias.name for no in no_topo if isinstance(no, ast.Import) for alias in no.names
    }
    assert "oracledb" not in importados
    # e o import de dentro da função vira DWIndisponivel, não ImportError
    assert "DWIndisponivel" in fonte.split("def _driver")[1].split("def ")[0]


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
    # o catálogo não informa nulabilidade, e `comparar` aprova ainda assim
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
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)

    r = client.get(DIAG, headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is True
    assert corpo["conectou"] is True
    assert corpo["dsn"] == conexao_dw.dsn()
    assert corpo["credencial"]["configurada"] is True
    assert [m["movimento"] for m in corpo["movimentos"]] == ["rec", "exp"]
    assert all(m["select_compila"] for m in corpo["movimentos"])
    assert conexao.fechada, "conexão com produção não se deixa fechar quando der"


def test_diagnostico_nao_devolve_a_senha(
    client, admin_headers, com_credencial, monkeypatch
):
    """Ele diz QUAL variável carrega a credencial, nunca o valor."""
    monkeypatch.setattr(conexao_dw, "conectar", lambda: ConexaoFalsa())
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
    monkeypatch.setattr(conexao_dw, "conectar", lambda: ConexaoFalsa(catalogo=catalogo))

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


def test_a_tela_nao_passou_a_depender_do_dw(client, admin_headers, monkeypatch):
    """O D1 não muda nada da tela: `/opcoes` continua no `nuvem-db` e continua
    503 sem `VOLUMETRIA_DB_URL`, mesmo com a credencial do DW no ambiente."""
    monkeypatch.setenv(conexao_dw.ENV_USUARIO, "hub_leitura_dw")
    monkeypatch.setenv(conexao_dw.ENV_SENHA, "senha-de-mentira")
    monkeypatch.delenv("VOLUMETRIA_DB_URL", raising=False)
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 503
    assert "VOLUMETRIA_DB_URL" in r.json()["detail"]


# ==================================================== somente leitura
_PALAVRAS_DE_ESCRITA = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE", "DROP", "CREATE",
    "ALTER", "GRANT", "REVOKE", "COMMIT",
)
_METODOS_DE_ESCRITA = {"commit", "rollback", "executemany", "setinputsizes"}

# Os módulos que falam com o DW. O router NÃO entra: ele tem SQL das duas fontes
# e mensagens em prosa, então varrê-lo por palavra daria falso positivo eterno.
# Quem cobre o endpoint dele é a guarda de runtime.
_MODULOS_DO_DW = (conexao_dw, schema_dw)


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
    client, admin_headers, com_credencial, monkeypatch
):
    """A de runtime pega o comando montado por concatenação, que a estática não
    veria — e cobre o endpoint inteiro, do router ao catálogo. O `CursorFalso`
    estoura em qualquer `execute` que não comece por `SELECT`."""
    conexao = ConexaoFalsa()
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    assert client.get(DIAG, headers=admin_headers).status_code == 200

    assert conexao.executados, "o teste não exercitou nada"
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
