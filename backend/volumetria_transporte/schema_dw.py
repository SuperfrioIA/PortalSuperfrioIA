"""Verificação de drift contra o DW: o contrato conferido na própria fonte.

Adaptado de `backend/volumetria_catering/schema_dw.py` (D1) para **uma
tabela só** — o transporte não tem o par rec/exp do catering, então não há
`movimento` para iterar. O resto do desenho é o mesmo, e a docstring longa
sobre POR QUE cada conferência existe está lá; aqui só o que muda.

## As duas conferências (resumo — ver o original para o raciocínio completo)

1. `SELECT` do contrato com `WHERE 1=0`: prova nome de coluna e privilégio,
   sem ler bloco;
2. `ALL_TAB_COLUMNS`: prova tipo (família) e aponta coluna nova que o nosso
   `SELECT` não leva.

Nulabilidade **não é conferida** — mesma decisão do catering: o `NOT NULL` do
`contrato.py` é o que a medição observou no DADO, não a declaração do Oracle
(que aqui, medido em 04/set, é quase toda `NULLABLE`).
"""

import logging
import time

from backend.volumetria_transporte import contrato

logger = logging.getLogger(__name__)

INTERVALO_REVERIFICACAO = 600  # segundos

_FAMILIA_TEXTO = ("VARCHAR2", "VARCHAR", "CHAR", "NVARCHAR2", "NCHAR", "CLOB", "NCLOB")
_FAMILIA_NUMERO = ("NUMBER",)
_FAMILIA_DATA = ("DATE", "TIMESTAMP")

_FAMILIAS = {
    "TEXT": _FAMILIA_TEXTO,
    "INTEGER": _FAMILIA_NUMERO,
    "NUMERIC": _FAMILIA_NUMERO,
    "DATE": _FAMILIA_DATA,
    "TIMESTAMP": _FAMILIA_DATA,
}

PONTO_FLUTUANTE = ("FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE")


class ContratoDivergenteDW(Exception):
    """O DW não tem a forma que este contrato descreve."""

    def __init__(self, problemas):
        self.problemas = list(problemas)
        super().__init__(
            "contrato da volumetria de transporte divergente do DW — "
            f"{len(self.problemas)} problema(s): " + "; ".join(self.problemas)
            + ". Atualize backend/volumetria_transporte/contrato.py (e confirme "
            "a mudança com quem mantém o DW antes)."
        )


def _partes_do_nome() -> tuple[str | None, str]:
    nome = contrato.tabela()
    dono, _, tabela = nome.partition(".")
    return (dono, tabela) if tabela else (None, dono)


def sql_zero_linhas() -> str:
    colunas = ", ".join(contrato.colunas_dw())
    return f"SELECT {colunas} FROM {contrato.tabela()} WHERE 1=0"


def sql_catalogo(com_dono: bool) -> str:
    onde = "TABLE_NAME = :tabela"
    if com_dono:
        onde = "OWNER = :dono AND " + onde
    return f"SELECT COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS WHERE {onde} ORDER BY COLUMN_ID"


def _familia_ok(tipo_contrato: str, tipo_dw: str) -> bool:
    return tipo_dw.upper().startswith(_FAMILIAS[tipo_contrato])


def comparar(tipos_reais: dict) -> tuple[list[str], list[str]]:
    """`(problemas, avisos)`. Pura, testável sem DW."""
    tabela = contrato.tabela()
    if not tipos_reais:
        return (
            [
                f"{tabela}: tabela não existe no DW ou o usuário de leitura não "
                "tem privilégio de SELECT nela — o ALL_TAB_COLUMNS responde igual "
                "nos dois casos, e a segunda hipótese se resolve com quem mantém "
                "o DW"
            ],
            [],
        )

    problemas: list[str] = []
    esperadas: set[str] = set()
    for nossa, tipo, _nulo in contrato.COLUNAS_SELECT:
        coluna = contrato.coluna_dw(nossa)
        esperadas.add(coluna)
        tipo_dw = tipos_reais.get(coluna)
        if tipo_dw is None:
            problemas.append(
                f"{tabela}.{coluna}: coluna do contrato não existe no DW "
                f"(nosso nome: {nossa})"
            )
            continue
        if tipo_dw.upper().startswith(PONTO_FLUTUANTE) and tipo == "NUMERIC":
            problemas.append(
                f"{tabela}.{coluna}: o DW declara {tipo_dw}, que chega como float "
                "mesmo com fetch_decimals — peso/valor perderia precisão em silêncio"
            )
        elif not _familia_ok(tipo, tipo_dw):
            problemas.append(f"{tabela}.{coluna}: contrato diz {tipo}, o DW tem {tipo_dw}")

    avisos = [
        f"{tabela}.{coluna}: coluna existe no DW e não está no contrato "
        f"(tipo {tipos_reais[coluna]}) — o SELECT deste módulo não a leva"
        for coluna in sorted(set(tipos_reais) - esperadas)
    ]
    return problemas, avisos


def _tipos_do_catalogo(cur) -> dict:
    dono, tabela = _partes_do_nome()
    binds = {"tabela": tabela}
    if dono is not None:
        binds["dono"] = dono
    cur.execute(sql_catalogo(dono is not None), binds)
    return {str(coluna): str(tipo) for coluna, tipo in cur.fetchall()}


def conferir(cur) -> dict:
    """Confere a tabela e devolve o que foi visto, sem levantar."""
    resultado = {
        "tabela": contrato.tabela(),
        "colunas_no_contrato": len(contrato.colunas_dw()),
        "select_compila": False,
        "colunas_no_dw": 0,
        "problemas": [],
        "avisos": [],
    }
    try:
        cur.execute(sql_zero_linhas())
        cur.fetchall()
        resultado["select_compila"] = True
    except Exception as erro:
        resultado["problemas"].append(
            f"{resultado['tabela']}: o SELECT gerado do contrato não compilou no "
            f"DW — {type(erro).__name__}: {erro}"
        )

    try:
        tipos = _tipos_do_catalogo(cur)
    except Exception as erro:
        resultado["problemas"].append(
            f"{resultado['tabela']}: o ALL_TAB_COLUMNS não respondeu — "
            f"{type(erro).__name__}: {erro}"
        )
        return resultado

    resultado["colunas_no_dw"] = len(tipos)
    problemas, avisos = comparar(tipos)
    resultado["problemas"].extend(problemas)
    resultado["avisos"] = avisos
    return resultado


def verificar(cur) -> list[str]:
    """Confere agora, sem cache. Levanta `ContratoDivergenteDW` se houver
    problema; devolve os avisos."""
    visto = conferir(cur)
    if visto["problemas"]:
        raise ContratoDivergenteDW(visto["problemas"])
    for aviso in visto["avisos"]:
        logger.warning("volumetria-transporte/DW: %s", aviso)
    return visto["avisos"]


_verificado_em: float | None = None


def garantir(cur) -> None:
    global _verificado_em
    agora = time.monotonic()
    if _verificado_em is not None and agora - _verificado_em < INTERVALO_REVERIFICACAO:
        return
    verificar(cur)
    _verificado_em = agora


def invalidar() -> None:
    global _verificado_em
    _verificado_em = None
