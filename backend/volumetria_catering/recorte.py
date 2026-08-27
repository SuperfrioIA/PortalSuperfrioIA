"""O recorte: filtros, periodo e o `WHERE` -- **uma definicao so**.

Porte de `catering/consulta/recorte.py` da nuvem-ia (main, 27/ago/2026). A unica
mudanca e o import do contrato; a logica e a mesma, de proposito -- a tela do Hub
e a tela antiga precisam responder sobre o MESMO conjunto de linhas enquanto
convivem (H2 -> H4).

## Por que este modulo existe

A Matriz (V3.2), a planilha e o download (V3.3) tem que responder sobre
**exatamente o mesmo conjunto de linhas**. Se cada uma montasse o seu proprio
`WHERE`, o dia em que um filtro mudasse de comportamento numa e nao na outra a
tela passaria a mostrar uma coisa e a baixar outra -- e ninguem descobriria por
um bom tempo, porque os dois numeros parecem plausiveis sozinhos.

Entao o recorte e definido aqui e usado pelas tres. O aceite do V3.3 fixa isso
por medicao: somando as paginas da planilha tem que dar o total da Matriz.

## Sem FK, entao LEFT JOIN com queda para a fonte

As dimensoes nao tem FK vindo do fato, de proposito (V3.0). Isso obriga
`LEFT JOIN` + `COALESCE`: unidade, cliente ou nome de estoque que ainda nao
entrou na dimensao **nao pode fazer a linha desaparecer**. Desaparecer em
silencio e o pior desfecho -- o numero fica menor e ninguem ve.

## Duas coisas diferentes com a palavra "dia"

O recorte tem **periodo** e **filtro de dia do mes**, e eles nao se substituem:

  - `de`/`ate` sao **datas** (`AAAA-MM-DD`), inclusivas nas duas pontas;
  - `dias` e a **multi-selecao 01..31**, que recorta DENTRO de todo mes do
    periodo -- pegar jan a ago e tirar os dias 1, 2 e 3 exclui esses dias nos
    oito meses. E a semantica do slicer "Dia" do Power BI. E dia **do mes**,
    nao dia da semana.

A consequencia que a tela tem que declarar: com qualquer dos dois ativo, a
coluna "2026-08" deixa de ser o mes de agosto. Por isso `rotulos_dos_meses()` e
`rotulo_dos_dias()` moram aqui, do lado da definicao do recorte, e nao no
navegador.

## Injecao de SQL

Todo VALOR de filtro vai como parametro nomeado. Os unicos identificadores
interpolados sao nomes de coluna que saem do `contrato.py` e passam por
conferencia contra ele -- nunca do usuario. `dias` chega como texto da URL e sai
daqui como **lista de inteiros**, o que fecha a porta por construcao.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date

from backend.volumetria_catering import contrato

TABELA = {"rec": "cat_fato_recebimento", "exp": "cat_fato_expedicao"}

# O terceiro movimento da TELA (V3.7.2). Ele NAO entra em `contrato.MOVIMENTOS`,
# e a separacao e o ponto: aquele e o conjunto do DADO. "Entrada + saida" nao e
# uma terceira tabela nem um terceiro tipo de linha: e um jeito de LER as duas.
CONJUNTA = "amb"
MOVIMENTOS_DA_TELA = ("rec", "exp", CONJUNTA)


def movimentos_do_recorte(movimento):
    """As tabelas que o recorte precisa ler. Uma, ou as duas."""
    if movimento == CONJUNTA:
        return ("rec", "exp")
    return (movimento,)

# As tres dimensoes de decisao, juntadas na leitura. Ver docstring.
JUNCOES = (
    "LEFT JOIN cat_unidades u ON u.sigla_fonte = f.nk_wms_filial\n"
    "LEFT JOIN cat_clientes c ON c.raiz_cnpj = f.nk_cliente\n"
    "LEFT JOIN cat_tipos_estoque t ON t.nome_estoque = f.nome_estoque"
)

# Expressoes reusadas por Matriz, planilha e download -- para o rotulo da tela
# e o do arquivo nunca divergirem.
SIGLA = "COALESCE(u.sigla, f.nk_wms_filial)"
CLIENTE_ROTULO = "COALESCE(c.razao_social, f.raz_social)"
TIPO_ESTOQUE = "COALESCE(t.tipo, 'NAO_CLASSIFICADO')"


class FiltroInvalido(Exception):
    """Filtro que o contrato nao admite. Erro do chamador, nao do dado."""


@dataclass
class Filtros:
    """O recorte da tela.

    `de`/`ate` sao **datas** (`AAAA-MM-DD`), inclusivas nas duas pontas.
    `dias` e a multi-selecao de dia do mes (01..31); vazio significa todos."""

    de: str
    ate: str
    movimento: str = "rec"
    lente: str = "liq"
    faixa: str = "solicitado"
    unidades: tuple = ()
    clientes: tuple = ()
    tipos_estoque: tuple = ()
    operacoes: tuple = ()
    dias: tuple = ()
    pagina: int = 1

    def validar(self):
        if self.movimento not in MOVIMENTOS_DA_TELA:
            raise FiltroInvalido(f"movimento: {self.movimento!r}")
        if self.lente not in contrato.LENTES:
            raise FiltroInvalido(f"lente: {self.lente!r}")
        if self.faixa not in contrato.FAIXAS:
            raise FiltroInvalido(f"faixa: {self.faixa!r}")
        for nome in ("de", "ate"):
            data_do_recorte(getattr(self, nome), nome)
        if data_do_recorte(self.de, "de") > data_do_recorte(self.ate, "ate"):
            raise FiltroInvalido(f"periodo invertido: {self.de} > {self.ate}")
        # Normaliza AQUI, e nao no SQL: o eco da tela, o registro da auditoria e
        # o `WHERE` tem que falar do MESMO conjunto.
        self.dias = dias_do_filtro(self.dias)
        if self.pagina < 1:
            raise FiltroInvalido(f"pagina: {self.pagina}")
        # Operacao (`descr_oper_wms`) e uma lista POR MOVIMENTO, e as duas nao
        # coincidem. Na visao conjunta, filtrar por uma operacao que so existe
        # na entrada ZERARIA a linha de Expedicao -- sem erro, sem aviso.
        if self.movimento == CONJUNTA and self.operacoes:
            raise FiltroInvalido(
                "filtro de operacao nao vale em Entrada + saida: as duas "
                "tabelas tem listas de operacao diferentes, e filtrar por uma "
                "delas zeraria o outro movimento em silencio. Escolha Entrada "
                "ou Saida para filtrar por operacao."
            )
        return self

    def como_dict(self):
        """O recorte aplicado, para a tela ecoar e para a auditoria registrar."""
        return {
            "de": self.de, "ate": self.ate, "movimento": self.movimento,
            "lente": self.lente, "faixa": self.faixa,
            "unidades": list(self.unidades), "clientes": list(self.clientes),
            "tipos_estoque": list(self.tipos_estoque),
            "operacoes": list(self.operacoes),
            "dias": list(self.dias),
        }


_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def data_do_recorte(valor, campo="data") -> date:
    """`AAAA-MM-DD` -> `date`, estrito.

    A conferencia do formato vem ANTES do `fromisoformat` de proposito: o
    `fromisoformat` do Python 3.11+ aceita `20260105` e outras variantes ISO.
    `2026-02-30` cai no segundo teste, que e o do calendario."""
    bruto = str(valor)
    if not _DATA_ISO.match(bruto):
        raise FiltroInvalido(f"{campo} deve ser AAAA-MM-DD, veio {valor!r}")
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        raise FiltroInvalido(f"{campo}: {valor!r} nao e uma data que existe") from None


DIA_MAXIMO = 31


def dias_do_filtro(valores) -> tuple:
    """Os dias do mes selecionados, como inteiros unicos e ordenados.

    Dia 29, 30 e 31 sao aceitos sem olhar o mes -- num mes que nao tem dia 31 a
    selecao simplesmente nao casa com linha nenhuma."""
    saida = set()
    for bruto in valores or ():
        try:
            dia = int(str(bruto).strip())
        except ValueError:
            raise FiltroInvalido(f"dia: {bruto!r} nao e um numero") from None
        if not 1 <= dia <= DIA_MAXIMO:
            raise FiltroInvalido(f"dia: {dia} esta fora de 1..{DIA_MAXIMO}")
        saida.add(dia)
    return tuple(sorted(saida))


def proximo_mes(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def ultimo_dia_do_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def meses_do_periodo(de, ate):
    """Todos os meses do recorte, inclusive os sem dado.

    Mes vazio tem que virar coluna vazia, nao coluna ausente: se a coluna
    desaparece, as outras deslizam e a comparacao entre linhas passa a mentir."""
    inicio = data_do_recorte(de, "de")
    fim = data_do_recorte(ate, "ate")
    atual = date(inicio.year, inicio.month, 1)
    saida = []
    while atual <= fim:
        saida.append(f"{atual.year:04d}-{atual.month:02d}")
        atual = proximo_mes(atual)
    return saida


def rotulos_dos_meses(de, ate):
    """`{mes: rotulo}` das colunas, declarando as pontas PARCIAIS.

    Com periodo de 03/08 a 05/09 a coluna de agosto tem os dias 03 a 31 e a de
    setembro os dias 01 a 05. O cabecalho diz isso (`2026-08 (03-31)`). Mes
    inteiro sai sem parenteses: anotar o obvio treina a pessoa a ignorar a
    anotacao."""
    inicio = data_do_recorte(de, "de")
    fim = data_do_recorte(ate, "ate")
    saida = {}
    for mes in meses_do_periodo(de, ate):
        ano, numero = (int(parte) for parte in mes.split("-"))
        primeiro = date(ano, numero, 1)
        ultimo = ultimo_dia_do_mes(primeiro)
        borda_de = max(inicio, primeiro)
        borda_ate = min(fim, ultimo)
        if borda_de == primeiro and borda_ate == ultimo:
            saida[mes] = mes
        else:
            saida[mes] = f"{mes} ({borda_de.day:02d}-{borda_ate.day:02d})"
    return saida


def rotulo_dos_dias(dias) -> str:
    """Os dias selecionados em faixas: `04 a 31`, `01, 03 a 05, 09`."""
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
    """O aviso do filtro de dia do mes, ou `None` quando ele nao esta ativo.

    Mora aqui porque a Matriz e a planilha tem que dizer a MESMA coisa sobre o
    mesmo recorte."""
    if not dias:
        return None
    return (
        "Filtro de dia do mês ativo: o recorte leva apenas os dias "
        f"{rotulo_dos_dias(dias)} de cada mês, não o mês inteiro."
    )


def onde(filtros: Filtros):
    """`(clausulas, params)` do recorte. **A unica definicao de filtro.**"""
    # Intervalo FECHADO nas duas pontas: `nk_calendario` e DATE (meia-noite
    # sempre), entao `<= ate` e exato -- e "03/08 a 05/09" inclui o dia 05.
    clausulas = ["f.nk_calendario >= %(de)s", "f.nk_calendario <= %(ate)s"]
    params = {
        "de": data_do_recorte(filtros.de, "de"),
        "ate": data_do_recorte(filtros.ate, "ate"),
    }
    # Dia do mes: recorta DENTRO de cada mes do periodo. Nao usa indice (e
    # expressao sobre a coluna) e nao faz falta -- quem estreita e o intervalo
    # de datas acima, que usa o indice da 0019.
    if filtros.dias:
        clausulas.append("EXTRACT(DAY FROM f.nk_calendario) = ANY(%(dias)s)")
        params["dias"] = list(filtros.dias)
    if filtros.unidades:
        clausulas.append(f"{SIGLA} = ANY(%(unidades)s)")
        params["unidades"] = list(filtros.unidades)
    if filtros.clientes:
        clausulas.append("f.nk_cliente = ANY(%(clientes)s)")
        params["clientes"] = list(filtros.clientes)
    if filtros.tipos_estoque:
        clausulas.append(f"{TIPO_ESTOQUE} = ANY(%(tipos)s)")
        params["tipos"] = list(filtros.tipos_estoque)
    if filtros.operacoes:
        clausulas.append("f.descr_oper_wms = ANY(%(operacoes)s)")
        params["operacoes"] = list(filtros.operacoes)
    return clausulas, params


def de_para_where(filtros: Filtros, movimento=None):
    """`(sql_from_where, params)` -- o pedaco comum das tres consultas.

    O `movimento` explicito existe para a visao conjunta (V3.7.2), que roda UMA
    consulta por tabela e soma depois, em Python.

    Sem ele, `movimento=amb` **levanta** em vez de escolher uma tabela por conta
    propria: escolher em silencio daria um numero que parece certo e e a metade.
    A planilha e o download chamam esta funcao SEM o argumento -- entao a trava
    aqui e o que garante que eles nunca passem a responder so pelo recebimento
    sem ninguem notar."""
    escolhido = movimento or filtros.movimento
    if escolhido == CONJUNTA:
        raise FiltroInvalido(
            "recorte de dois movimentos: esta consulta le uma tabela por vez"
        )
    clausulas, params = onde(filtros)
    sql = (
        f"FROM {TABELA[escolhido]} f\n"
        f"{JUNCOES}\n"
        f"WHERE {' AND '.join(clausulas)}"
    )
    return sql, params


def medida(movimento, lente, faixa):
    """Nome da coluna de medida, conferido contra o contrato.

    `None` quando a medida nao existe nesse lado -- o caso do pallet, que so
    existe na entrada. Nao e defeito: e a fonte, e a tela declara."""
    if movimento == "rec":
        coluna = contrato.LENTES[lente]["rec"]
    else:
        coluna = contrato.coluna_exp(lente, faixa)
    if coluna is None:
        return None
    validas = {nome for nome, _t, _n in contrato.colunas(movimento)}
    if coluna not in validas:
        raise FiltroInvalido(f"medida fora do contrato: {coluna!r}")
    return coluna


def medidas_da_lente(movimento, lente):
    """As colunas de medida de uma lente. Na saida, as TRES faixas.

    Dicionario vazio quando a lente nao existe naquele movimento (pallet na
    expedicao)."""
    if movimento == "rec":
        coluna = medida("rec", lente, "solicitado")
        return {} if coluna is None else {"": coluna}
    saida = {}
    for faixa in contrato.FAIXAS:
        coluna = medida("exp", lente, faixa)
        if coluna is not None:
            saida[faixa] = coluna
    return saida


ROTULO_FAIXA = {
    "solicitado": "Solicitado pelo cliente",
    "atendido": "Atendido pelo estoque",
    "separado": "Separado fisicamente",
}


def rotulo_faixa(faixa):
    return ROTULO_FAIXA[faixa]
