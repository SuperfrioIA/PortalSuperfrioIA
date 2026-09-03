"""O recorte: filtros, período e o `WHERE` — uma definição só, usada pela
Matriz, pela planilha e pelo download.

Adaptado de `backend/volumetria_catering/recorte.py` para Oracle: bind nomeado
`:x` (não `%(x)s` do psycopg), e sem `ANY(%(lista)s)` — o oracledb não aceita
lista Python como bind direto para `IN`, então toda lista vira uma clausula
`IN (:p0, :p1, ...)` com um bind por item (`_lista()`).

## Sem hierarquia de decisão (D2 não existe aqui)

O catering junta `cat_unidades`/`cat_clientes` para exibir sigla e razão social
canonizadas. Este módulo não tem essa camada (D2 do outro plano não foi feito,
e não é pré-requisito deste): a tela mostra `NK_WMS_FILIAL` e `RAZ_SOCIAL` como
o DW os entrega, sem JOIN nenhum. Se um dia o D2 existir, os dois módulos podem
passar a juntar a mesma tabela de rótulo — não antes.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from backend.volumetria_transporte import contrato

# Placa sentinela -> rótulo de tela. Único lugar: Matriz, planilha e download
# usam a mesma expressão SQL, então nunca divergem.
PLACA_ROTULO = (
    f"CASE WHEN f.placa = '{contrato.PLACA_SENTINELA}' "
    f"THEN '{contrato.PLACA_ROTULO_VAZIA}' ELSE f.placa END"
)


class FiltroInvalido(Exception):
    """Filtro que o contrato não admite. Erro do chamador, não do dado."""


_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIA_MAXIMO = 31


def data_do_recorte(valor, campo="data") -> date:
    bruto = str(valor)
    if not _DATA_ISO.match(bruto):
        raise FiltroInvalido(f"{campo} deve ser AAAA-MM-DD, veio {valor!r}")
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        raise FiltroInvalido(f"{campo}: {valor!r} não é uma data que existe") from None


def dias_do_filtro(valores) -> tuple:
    saida = set()
    for bruto in valores or ():
        try:
            dia = int(str(bruto).strip())
        except ValueError:
            raise FiltroInvalido(f"dia: {bruto!r} não é um número") from None
        if not 1 <= dia <= DIA_MAXIMO:
            raise FiltroInvalido(f"dia: {dia} está fora de 1..{DIA_MAXIMO}")
        saida.add(dia)
    return tuple(sorted(saida))


def proximo_mes(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def ultimo_dia_do_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def meses_do_periodo(de, ate):
    inicio = data_do_recorte(de, "de")
    fim = data_do_recorte(ate, "ate")
    atual = date(inicio.year, inicio.month, 1)
    saida = []
    while atual <= fim:
        saida.append(f"{atual.year:04d}-{atual.month:02d}")
        atual = proximo_mes(atual)
    return saida


def rotulos_dos_meses(de, ate):
    inicio = data_do_recorte(de, "de")
    fim = data_do_recorte(ate, "ate")
    saida = {}
    for mes in meses_do_periodo(de, ate):
        ano, numero = (int(parte) for parte in mes.split("-"))
        primeiro = date(ano, numero, 1)
        ultimo = ultimo_dia_do_mes(primeiro)
        borda_de = max(inicio, primeiro)
        borda_ate = min(fim, ultimo)
        saida[mes] = mes if (borda_de == primeiro and borda_ate == ultimo) else (
            f"{mes} ({borda_de.day:02d}-{borda_ate.day:02d})"
        )
    return saida


def rotulo_dos_dias(dias) -> str:
    dias = dias_do_filtro(dias)
    if not dias:
        return ""
    faixas, inicio, anterior = [], dias[0], dias[0]
    for dia in dias[1:] + (None,):
        if dia is not None and dia == anterior + 1:
            anterior = dia
            continue
        if inicio == anterior:
            faixas.append(f"{inicio:02d}")
        elif anterior == inicio + 1:
            faixas.append(f"{inicio:02d}, {anterior:02d}")
        else:
            faixas.append(f"{inicio:02d} a {anterior:02d}")
        inicio = anterior = dia
    return ", ".join(faixas)


def aviso_dos_dias(dias):
    if not dias:
        return None
    return (
        "Filtro de dia do mês ativo: o recorte leva apenas os dias "
        f"{rotulo_dos_dias(dias)} de cada mês, não o mês inteiro."
    )


# Filtros de múltipla seleção sobre colunas de texto — `(id do filtro, coluna)`.
FILTROS_CAIXAS = (
    ("unidades", "nk_wms_filial"),
    ("clientes", "nk_cliente"),
    ("tipos_estoque", "nome_estoque"),
    ("tipos_viagem", "tipo_viagem"),
    ("tipos_movimento", "tipo_movimento"),
    ("status_viagem", "status_viagem"),
    ("status_wms", "status_wms"),
    ("status_baixa", "status_baixa"),
)


@dataclass
class Filtros:
    de: str
    ate: str
    lente: str = "liq"
    unidades: tuple = ()
    clientes: tuple = ()
    tipos_estoque: tuple = ()
    tipos_viagem: tuple = ()
    tipos_movimento: tuple = ()
    status_viagem: tuple = ()
    status_wms: tuple = ()
    status_baixa: tuple = ()
    dias: tuple = ()
    pagina: int = 1

    def validar(self):
        if self.lente not in contrato.LENTES:
            raise FiltroInvalido(f"lente: {self.lente!r}")
        for nome in ("de", "ate"):
            data_do_recorte(getattr(self, nome), nome)
        if data_do_recorte(self.de, "de") > data_do_recorte(self.ate, "ate"):
            raise FiltroInvalido(f"período invertido: {self.de} > {self.ate}")
        self.dias = dias_do_filtro(self.dias)
        if self.pagina < 1:
            raise FiltroInvalido(f"pagina: {self.pagina}")
        return self

    def como_dict(self):
        base = {"de": self.de, "ate": self.ate, "lente": self.lente, "dias": list(self.dias)}
        for id_filtro, _coluna in FILTROS_CAIXAS:
            base[id_filtro] = list(getattr(self, id_filtro))
        return base


def _lista(coluna: str, valores, params: dict, prefixo: str) -> str:
    """`coluna IN (:p0, :p1, ...)`, com um bind numerado por valor — o
    oracledb não aceita lista Python como bind direto de `IN`.

    Limitação conhecida e não tratada: o Oracle recusa mais de 1000 elementos
    num `IN`. Nenhuma dimensão medida no T0 chega perto disso (a maior,
    unidade, tem 6) — se um filtro crescer muito, isto passa a exigir quebrar
    em `OR` de blocos de 1000."""
    nomes = []
    for i, valor in enumerate(valores):
        chave = f"{prefixo}{i}"
        params[chave] = valor
        nomes.append(f":{chave}")
    return f"{coluna} IN ({', '.join(nomes)})"


def onde(filtros: Filtros):
    """`(clausulas, params)` do recorte. **A única definição de filtro.**"""
    clausulas = ["f.nk_calendario >= :de", "f.nk_calendario <= :ate"]
    params = {
        "de": data_do_recorte(filtros.de, "de"),
        "ate": data_do_recorte(filtros.ate, "ate"),
    }
    if filtros.dias:
        clausulas.append(_lista("EXTRACT(DAY FROM f.nk_calendario)", filtros.dias, params, "dia"))
    for id_filtro, coluna in FILTROS_CAIXAS:
        valores = getattr(filtros, id_filtro)
        if valores:
            clausulas.append(_lista(f"f.{coluna}", valores, params, id_filtro[:3]))
    return clausulas, params


def de_para_where(filtros: Filtros):
    """`(sql_from_where, params)` — o pedaço comum das três consultas."""
    clausulas, params = onde(filtros)
    sql = f"FROM {contrato.tabela()} f\nWHERE {' AND '.join(clausulas)}"
    return sql, params


def medida(lente: str) -> str:
    if lente not in contrato.LENTES:
        raise FiltroInvalido(f"lente fora do contrato: {lente!r}")
    return contrato.LENTES[lente]["coluna"]
