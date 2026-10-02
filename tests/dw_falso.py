"""DW de mentira para os testes do SuperfrioIA (Lote 2).

Nenhum teste conecta no DW: o DW é produção, e a política é que a IA não conecta
nele. Este módulo troca `conexao_dw.conectar` por uma conexão falsa que:

- responde o catálogo do contrato (a conferência de drift passa);
- **guarda todo comando executado** e recusa tudo que não seja `SELECT` (guarda de
  runtime, a mesma de `test_volumetria_catering_dw.py`);
- devolve linhas geradas a partir dos **apelidos do próprio SELECT**
  (`chave_0`, `rotulo_1`, `mes`, `medida_*`, `linhas`), **aplicando os filtros** que
  chegam nos binds (período, unidade, cliente, operação). Assim "maiores clientes
  da unidade X" é testado de verdade, não só o formato.

O dado é determinístico e simples de somar de cabeça. Para cada
(unidade `u`, cliente `c`, operação `o`, mês `m`, medida `k`), em **toneladas**:

    t = (u+1)*100 + (c+1)*10 + (o+1) + m + 1000*k

O valor chega ao Hub em kg (`t * 1000`), como o DW devolve. `soma_t()` é o oráculo
independente: soma por laço, sem usar nenhuma função do Hub.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from backend.volumetria_catering import conexao_dw, contrato, dimensoes_dw, schema_dw

UNIDADES_BASE = ["CPS", "MAQ", "RMSPV", "RMSPIV", "RMSPII", "RMRJ"]  # RMSPV e RMSPIV colidem
CLIENTES = [
    ("67945071", "CONVIDA BRASIL"),
    ("67945072", "CONVIDA SUL"),
    ("12345678", "SAPORE"),
    ("55555555", "NOVO CLIENTE LTDA"),
]
OPERACOES = ["OP A", "OP B"]
HOJE = date(2026, 9, 6)
ATUALIZADO = {"rec": datetime(2026, 9, 5, 7, 5), "exp": datetime(2026, 9, 3, 7, 10)}

_TIPO_NO_DW = {"TEXT": "VARCHAR2", "INTEGER": "NUMBER", "SMALLINT": "NUMBER",
               "NUMERIC(18,3)": "NUMBER", "DATE": "DATE", "TIMESTAMP": "DATE"}


def unidades_da_fonte(n: int = 6) -> list[str]:
    return (UNIDADES_BASE + [f"U{i:02d}" for i in range(len(UNIDADES_BASE), n)])[:n]


def exibida(fonte: str) -> str:
    return "RMSPIV" if fonte == "RMSPV" else fonte


def unidades_exibidas(n: int = 6) -> list[str]:
    return sorted({exibida(u) for u in unidades_da_fonte(n)})


# ------------------------------------------------------------------ o oráculo
def mes_indice(mes: str) -> int:
    ano, numero = (int(p) for p in mes.split("-"))
    return (ano - 2026) * 12 + numero - 1


def valor_t(u: int, c: int, o: int, m: int, k: int = 0) -> int:
    return (u + 1) * 100 + (c + 1) * 10 + (o + 1) + m + 1000 * k


def soma_t(meses, *, n_unidades=6, unidades=None, clientes=None, operacoes=None, k=0) -> int:
    """Soma, por laço, das toneladas do recorte. Independente do Hub."""
    total = 0
    for u, fonte in enumerate(unidades_da_fonte(n_unidades)):
        if unidades is not None and exibida(fonte) not in unidades:
            continue
        for c, (chave, rotulo) in enumerate(CLIENTES):
            if clientes is not None and rotulo not in clientes:
                continue
            for o, operacao in enumerate(OPERACOES):
                if operacoes is not None and operacao not in operacoes:
                    continue
                total += sum(valor_t(u, c, o, mes_indice(m), k) for m in meses)
    return total


def pt_br(valor: int | Decimal, casas: int = 1) -> str:
    """`1234.5` -> `1.234,5`, escrito de novo aqui para o teste não depender do Hub."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


# ------------------------------------------------------------------ dimensões
def dim_ia(n_unidades: int = 6) -> dimensoes_dw.Dimensoes:
    return dimensoes_dw.Dimensoes(
        unidades_fonte=unidades_da_fonte(n_unidades),
        nomes_estoque=["CONG FLV (CUCINARE)", "SECO GERAL", "RESFRIADO - PR", "QUALQUER COISA"],
        operacoes={"rec": list(OPERACOES), "exp": list(OPERACOES)},
        clientes_rotulo={chave: rotulo for chave, rotulo in CLIENTES},
        clientes_grafias={chave: [(rotulo, 100.0)] for chave, rotulo in CLIENTES},
        periodo=(date(2023, 1, 1), date(2026, 9, 5)),
        atualizado_em=dict(ATUALIZADO),
    )


# --------------------------------------------------------------------- o DW
def _catalogo_do_contrato(movimento):
    return {contrato.coluna_dw(nome, movimento): _TIPO_NO_DW[tipo]
            for nome, tipo, _nulo in contrato.colunas(movimento)}


def _tabela_curta(movimento):
    return contrato.tabela(movimento).partition(".")[2]


def _meses(de: date, ate: date) -> list[str]:
    saida, ano, mes = [], de.year, de.month
    while (ano, mes) <= (ate.year, ate.month):
        saida.append(f"{ano}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return saida


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self.arraysize = 100
        self.prefetchrows = 2
        self.description = []
        self._resultado = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, binds=None):
        binds = dict(binds or {})
        self.conexao.banco.executados.append((sql, binds))
        if not sql.lstrip().upper().startswith("SELECT"):
            raise AssertionError(f"comando que não é leitura: {sql!r}")
        if "ALL_TAB_COLUMNS" in sql:
            self._resultado = list(self.conexao.banco.catalogo.get(binds["tabela"], {}).items())
        elif "WHERE 1=0" in sql:
            self._resultado = []
        else:
            erro = self.conexao.banco.erro_na_consulta
            if erro is not None:
                raise erro
            self.conexao.banco.consultas.append((sql, binds))
            self._gerar(sql, binds)

    def _gerar(self, sql, binds):
        primeira = sql.split("\n", 1)[0]
        aliases = re.findall(r"\bAS (\w+)", primeira)
        banco = self.conexao.banco
        fontes = [v for k, v in binds.items() if k.startswith("uni")]
        chaves = [v for k, v in binds.items() if k.startswith("cli")]
        ops_filtradas = [v for k, v in binds.items() if k.startswith("ope")]
        com_operacao = "chave_2" in aliases

        # A faixa de cada medida sai da expressão `SUM(f.QTDE_PESO_ATENDIDO) AS medida_unica`:
        # é assim que a conjunta escolhe a faixa, e o fake não precisa saber o filtro.
        faixas = ["solicitado", "atendido", "separado"]
        k_da_medida = {}
        for expressao, alias in re.findall(r"SUM\((.*?)\) AS (medida_\w+)", primeira):
            achada = next((i for i, f in enumerate(faixas) if f.upper() in expressao.upper()), 0)
            k_da_medida[alias] = achada

        def monta(fonte, chave, grafia, operacao, mes, valores_por_medida):
            registro = []
            for alias in aliases:
                if alias == "chave_0":
                    registro.append(fonte)
                elif alias == "chave_1":
                    registro.append(chave)
                elif alias == "rotulo_1":
                    registro.append(grafia)
                elif alias == "chave_2":
                    registro.append(operacao)
                elif alias == "mes":
                    registro.append(mes)
                elif alias == "linhas":
                    registro.append(Decimal(1))
                else:
                    registro.append(Decimal(valores_por_medida[alias] * 1000))
            return tuple(registro)

        linhas = []
        for u, fonte in enumerate(unidades_da_fonte(banco.n_unidades)):
            if fontes and fonte not in fontes:
                continue
            for c, (chave, grafia) in enumerate(CLIENTES):
                if chaves and chave not in chaves:
                    continue
                operacoes = [(o, op) for o, op in enumerate(OPERACOES) if not ops_filtradas or op in ops_filtradas]
                for mes in _meses(binds["de"], binds["ate"]):
                    m = mes_indice(mes)
                    if com_operacao:  # uma linha por operação
                        for o, op in operacoes:
                            valores = {a: valor_t(u, c, o, m, k) for a, k in k_da_medida.items()}
                            linhas.append(monta(fonte, chave, grafia, op, mes, valores))
                    elif operacoes:   # o SELECT não traz a operação: o SUM junta todas
                        valores = {a: sum(valor_t(u, c, o, m, k) for o, _ in operacoes)
                                   for a, k in k_da_medida.items()}
                        linhas.append(monta(fonte, chave, grafia, None, mes, valores))
        self.description = [(a.upper(),) for a in aliases]
        self._resultado = linhas

    def fetchall(self):
        return list(self._resultado)

    def fetchone(self):
        return self._resultado[0] if self._resultado else None


class ConexaoFalsa:
    def __init__(self, banco):
        self.banco = banco
        self.fechada = False

    def cursor(self):
        return CursorFalso(self)

    def close(self):
        self.fechada = True


class Banco:
    """O estado do DW de mentira numa execução de teste."""

    def __init__(self, n_unidades=6, erro_na_consulta=None, catalogo=None):
        self.n_unidades = n_unidades
        self.erro_na_consulta = erro_na_consulta
        self.catalogo = {_tabela_curta(m): c for m, c in
                         (catalogo or {m: _catalogo_do_contrato(m) for m in contrato.MOVIMENTOS}).items()}
        self.conexoes: list[ConexaoFalsa] = []
        self.executados: list[tuple] = []   # todos os comandos
        self.consultas: list[tuple] = []    # só as agregações da Matriz

    def conectar(self):
        conexao = ConexaoFalsa(self)
        self.conexoes.append(conexao)
        return conexao


def instalar(monkeypatch, *, n_unidades=6, erro_na_consulta=None, hoje=HOJE, catalogo=None) -> Banco:
    """Liga o DW de mentira e fixa a data de 'hoje'. Zera os caches nas duas pontas
    é responsabilidade do fixture que chama (veja `conftest.py`)."""
    banco = Banco(n_unidades=n_unidades, erro_na_consulta=erro_na_consulta, catalogo=catalogo)
    schema_dw.invalidar()
    dimensoes_dw.invalidar()
    dimensoes_dw._cache["dados"] = dim_ia(n_unidades)
    dimensoes_dw._cache["expira_em"] = float("inf")
    monkeypatch.setattr(conexao_dw, "conectar", banco.conectar)
    monkeypatch.setattr(dimensoes_dw, "hoje_no_fuso", lambda: hoje)
    return banco
