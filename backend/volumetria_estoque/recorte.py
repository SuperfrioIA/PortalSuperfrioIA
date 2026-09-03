"""O recorte: filtros, período e o `WHERE` — uma definição só, usada pela
Matriz, pela planilha e pelo download.

Cópia de `backend/volumetria_transporte/recorte.py`, com uma diferença real:
o filtro de **câmara** precisa admitir "sem câmara" como opção — a coluna
aceita nulo de verdade (T0), e `IN (:x, :y)` nunca casa com `NULL` em SQL
nenhum. Por isso `_lista()` não serve para esse filtro sozinho; `onde()` trata
câmara à parte (`_filtro_camara`).
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from backend.volumetria_estoque import contrato

CAMARA_CHAVE_VAZIA = "__SEM_CAMARA__"  # valor que o filtro de tela usa para "sem câmara"


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
        "Filtro de dia do mês ativo: no estoque isto seleciona A FOTO DAQUELE "
        f"DIA em cada mês (dias {rotulo_dos_dias(dias)}), não uma soma — é "
        "posição, não movimento."
    )


FILTROS_CAIXAS = (
    ("unidades", "nk_wms_filial"),
    ("clientes", "nk_cliente"),
    ("status_lote", "status_lote"),
)


@dataclass
class Filtros:
    de: str
    ate: str
    lente: str = "liq"
    unidades: tuple = ()
    clientes: tuple = ()
    camaras: tuple = ()
    status_lote: tuple = ()
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
        return {
            "de": self.de, "ate": self.ate, "lente": self.lente, "dias": list(self.dias),
            "unidades": list(self.unidades), "clientes": list(self.clientes),
            "camaras": list(self.camaras), "status_lote": list(self.status_lote),
        }


def _lista(coluna: str, valores, params: dict, prefixo: str) -> str:
    """`coluna IN (:p0, :p1, ...)`. Mesma limitação do transporte: sem
    quebra em blocos acima de 1000 itens (nenhuma dimensão medida chega perto)."""
    nomes = []
    for i, valor in enumerate(valores):
        chave = f"{prefixo}{i}"
        params[chave] = valor
        nomes.append(f":{chave}")
    return f"{coluna} IN ({', '.join(nomes)})"


def _filtro_camara(camaras, params: dict) -> str | None:
    """`camara` aceita nulo de verdade — `IN (...)` nunca casa com `NULL`,
    então "sem câmara" (`CAMARA_CHAVE_VAZIA`) vira `OR f.camara IS NULL`."""
    if not camaras:
        return None
    reais = [c for c in camaras if c != CAMARA_CHAVE_VAZIA]
    quer_vazia = CAMARA_CHAVE_VAZIA in camaras
    partes = []
    if reais:
        partes.append(_lista("f.camara", reais, params, "cam"))
    if quer_vazia:
        partes.append("f.camara IS NULL")
    return "(" + " OR ".join(partes) + ")"


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
    camara_clausula = _filtro_camara(filtros.camaras, params)
    if camara_clausula:
        clausulas.append(camara_clausula)
    return clausulas, params


def de_para_where(filtros: Filtros):
    clausulas, params = onde(filtros)
    sql = f"FROM {contrato.tabela()} f\nWHERE {' AND '.join(clausulas)}"
    return sql, params


def medida(lente: str) -> str:
    if lente not in contrato.LENTES:
        raise FiltroInvalido(f"lente fora do contrato: {lente!r}")
    return contrato.LENTES[lente]["coluna"]
