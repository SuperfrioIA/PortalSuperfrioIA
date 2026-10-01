"""A Matriz: hierarquia nas linhas, mes nas colunas.

Porte de `catering/consulta/matriz.py` da nuvem-ia (main, 27/ago/2026). O que
ficou aqui e a parte que nao conhece banco: hierarquia, arvore, ordenacao,
avisos e paginacao. A consulta do DW esta em `matriz_dw.py`, que entrega as
linhas a `montar()`. Os testes provam que a soma da planilha bate com a Matriz
no mesmo recorte, que e a invariante que este modulo precisa manter.

## A regra que define o formato

**Coluna e do tempo. Medida que se repete vira LINHA.** As tres faixas da saida
como colunas deram 1.416 px de tabela e rolagem horizontal -- e o que sai do
campo de visao some.

## Hierarquia

    entrada:  unidade -> cliente -> operacao
    saida:    unidade -> cliente -> faixa -> operacao
    conjunta: unidade -> cliente -> movimento

`operacao` e o `descr_oper_wms` -- o tipo de movimento. A hierarquia e uma
TUPLA CONFIGURAVEL em `HIERARQUIA`.

## `faixa` nao e um GROUP BY

As tres faixas da saida (`solicitado`, `atendido`, `separado`) sao tres
COLUNAS DE MEDIDA diferentes. Entao o nivel `faixa` da arvore e um leque sobre
as medidas, feito em Python, e nao uma dimensao do SQL. **As tres faixas nao
somam entre si** -- e a tela tem que dizer isso.

## A coluna e o mes -- e as vezes NAO e o mes inteiro

Com 03/08 a 05/09 a coluna de agosto tem apenas os dias 03 a 31. A Matriz
**declara** as duas formas de parcialidade: o cabecalho traz a faixa de dias da
ponta (`rotulos_meses`) e o filtro de dia do mes entra como aviso.

## Tres matrizes: entrada, saida, e as duas juntas

A visao CONJUNTA (V3.7.2) roda as duas consultas e soma em Python -- nao num
`UNION`, porque as tabelas tem 36 e 46 colunas e contratos proprios. Na
conjunta a arvore fica MAIS CURTA: a operacao sai (listas diferentes nos dois
lados) e a faixa deixa de ser nivel para virar botao ("a expedicao entra
como"). O pai soma os dois filhos e se chama **movimentacao**.

A planilha e o download continuam pedindo um movimento por vez: a Matriz
**agrega** -- e por isso pode somar -- enquanto a planilha mostra linha crua.

## Injecao de SQL

Nome de coluna de medida e interpolado na string do SQL (em `matriz_dw.py`). Ele
NUNCA vem do usuario: sai de `contrato.LENTES` / `contrato.coluna_exp()`, e
`_medida()` confere contra o contrato antes de usar. Todo VALOR de filtro vai
como parametro.
"""

from backend.volumetria_catering import contrato, recorte
from backend.volumetria_catering.recorte import (  # reexportados: a API deste modulo nao muda
    FiltroInvalido,
    Filtros,
    meses_do_periodo,
    rotulos_dos_meses,
)

# Trocar o terceiro nivel e mudar aqui, e so aqui. Ver docstring.
FAIXA = "faixa"

# O nivel `movimento` da visao conjunta (V3.7.2). Como o `faixa`, ele NAO e uma
# coluna do fato -- ele diz de qual das duas consultas a linha veio.
MOVIMENTO = "movimento"
ROTULO_MOVIMENTO = {"rec": "Recebimento", "exp": "Expedicao"}
# Ordem FIXA, e nao ranking -- pelo mesmo motivo das faixas: ali e leitura.
ORDEM_MOVIMENTO = ("exp", "rec")

HIERARQUIA = {
    "rec": ("unidade", "cliente", "operacao"),
    "exp": ("unidade", "cliente", FAIXA, "operacao"),
    # A conjunta e a arvore MAIS CURTA das tres, e e isso que a torna possivel.
    recorte.CONJUNTA: ("unidade", "cliente", MOVIMENTO),
}

# Os dois niveis que nao saem do SQL. Ficam juntos porque todo lugar que pergunta
# "quais niveis vem da consulta" precisa excluir os dois.
FORA_DO_SQL = (FAIXA, MOVIMENTO)

# 12 unidades por pagina -- contrato do V3_PLANO. Hoje existem 6, entao a
# paginacao nao corta nada; existe para nao ser uma surpresa quando entrar a
# setima.
UNIDADES_POR_PAGINA = 12


# Reexportados do recorte: a Matriz, a planilha e o download tem que usar a
# MESMA definicao de medida e de filtro. Duas copias derivariam em silencio.
_medida = recorte.medida
_medidas_da_consulta = recorte.medidas_da_lente


def _medidas_da_conjunta(lente, faixa):
    """`{movimento: {"": coluna}}` para a visao conjunta, ou `{}`.

    As duas medidas saem com a MESMA chave (`""`): e isso que faz a arvore somar
    entrada e saida no no pai. A expedicao entra pela **faixa escolhida no
    botao**. Vazio quando a medida nao existe nos dois lados (pallet)."""
    saida = {}
    for movimento in recorte.movimentos_do_recorte(recorte.CONJUNTA):
        coluna = _medida(movimento, lente, faixa)
        if coluna is None:
            return {}
        saida[movimento] = {"": coluna}
    return saida


def _nova(chave, rotulo, nivel):
    return {"chave": chave, "rotulo": rotulo, "nivel": nivel,
            "valores": {}, "filhos": []}


def _acumular(no, mes, valor):
    if valor is None:
        return
    no["valores"][mes] = no["valores"].get(mes, 0) + valor


def _descer(pai, chave, rotulo, nivel):
    for filho in pai["filhos"]:
        if filho["chave"] == chave:
            return filho
    filho = _nova(chave, rotulo, nivel)
    pai["filhos"].append(filho)
    return filho


def _inserir(no, niveis, i_nivel, i_concreto, linha, valor):
    """Desce um caminho da arvore, criando o que falta e acumulando o mes.

    No nivel `faixa` a arvore **se abre em tres ramos**, e cada faixa leva os
    seus proprios filhos. Abaixo da faixa o valor que desce e o **daquele
    ramo**, nao o principal."""
    if i_nivel >= len(niveis):
        return
    nome = niveis[i_nivel]
    mes = linha["mes"]

    if nome == FAIXA:
        for faixa in contrato.FAIXAS:
            if faixa not in linha["medidas"]:
                continue
            filho = _descer(no, faixa, _rotulo_faixa(faixa), FAIXA)
            do_ramo = linha["medidas"][faixa]
            _acumular(filho, mes, do_ramo)
            _inserir(filho, niveis, i_nivel + 1, i_concreto, linha, do_ramo)
        return

    filho = _descer(no, linha["chaves"][i_concreto], linha["rotulos"][i_concreto], nome)
    _acumular(filho, mes, valor)
    _inserir(filho, niveis, i_nivel + 1, i_concreto + 1, linha, valor)


def _arvore(linhas, niveis, medidas, faixa_escolhida):
    """Monta a hierarquia. Todo no acumula o proprio total por mes.

    Acima do nivel `faixa` o valor exibido e o da **faixa escolhida no botao**
    -- as outras duas continuam visiveis, abertas dentro do cliente."""
    raiz = _nova(None, None, "raiz")
    for linha in linhas:
        principal = linha["medidas"].get(faixa_escolhida)
        _acumular(raiz, linha["mes"], principal)
        _inserir(raiz, niveis, 0, 0, linha, principal)
    return raiz


_rotulo_faixa = recorte.rotulo_faixa


def montar(cur, filtros: Filtros, consultar) -> dict:
    """Monta a Matriz a partir de quem sabe CONSULTAR um movimento.

    `consultar(cur, filtros, movimento, niveis, medidas)` devolve
    `(linhas, total_linhas)`: cada linha e `{"chaves", "rotulos", "mes",
    "medidas"}` -- um grupo do SQL por mes, ja com a chave e o rotulo de cada
    nivel concreto da hierarquia. E o unico ponto em que o dialeto do banco
    entra: hoje e o `consultar` do DW (`matriz_dw.py`). Tudo abaixo --
    hierarquia, arvore, ordenacao, avisos, paginacao -- nao conhece banco."""
    filtros.validar()
    movimento = filtros.movimento
    conjunta = movimento == recorte.CONJUNTA
    niveis = HIERARQUIA[movimento]
    medidas = (_medidas_da_conjunta(filtros.lente, filtros.faixa) if conjunta
               else _medidas_da_consulta(movimento, filtros.lente))
    meses = meses_do_periodo(filtros.de, filtros.ate)
    rotulos_meses = rotulos_dos_meses(filtros.de, filtros.ate)
    lente = contrato.LENTES[filtros.lente]

    avisos = []
    # Isto NAO cabe no cabecalho: o filtro de dia corta dentro de todas as
    # colunas, inclusive as do meio. Sem o aviso, "2026-05" parece maio.
    aviso_dia = recorte.aviso_dos_dias(filtros.dias)
    if aviso_dia:
        avisos.append(aviso_dia)
    if not medidas:
        # Pallet na saida. So aparece quando o caso ocorre.
        avisos.append(
            f"{lente['nome']} só existe na entrada. Em Entrada + saída o total "
            "seria apenas a entrada com o nome de movimentação — número certo "
            "com nome errado. Escolha Entrada para ver esta medida."
            if conjunta else
            f"{lente['nome']} só existe na entrada. Nenhuma das três faixas da "
            "expedição tem essa medida na fonte — a coluna fica vazia de "
            "propósito, não é falha de carga."
        )
        return _vazia(filtros, meses, rotulos_meses, lente, avisos)

    if conjunta:
        linhas, total_linhas = [], 0
        for concreto in recorte.movimentos_do_recorte(movimento):
            parte, quantas = consultar(
                cur, filtros, concreto, niveis, medidas[concreto])
            linhas.extend(parte)
            total_linhas += quantas
    else:
        linhas, total_linhas = consultar(
            cur, filtros, movimento, niveis, medidas)

    raiz = _arvore(linhas, niveis, medidas, filtros.faixa if FAIXA in niveis else "")

    unidades = raiz["filhos"]
    unidades.sort(key=lambda n: n["chave"] or "")
    total_unidades = len(unidades)
    inicio = (filtros.pagina - 1) * UNIDADES_POR_PAGINA
    pagina = unidades[inicio:inicio + UNIDADES_POR_PAGINA]
    _ordenar(pagina, meses)

    if FAIXA in niveis:
        avisos.append(
            "As três faixas não somam entre si: são três leituras do mesmo "
            "pedido em momentos diferentes."
        )
    if conjunta:
        avisos.append(
            "O total de cada linha é a movimentação: entrada e saída somadas, "
            "com a expedição entrando pela faixa escolhida no botão. Ele carrega "
            "as duas limitações declaradas em Fontes &amp; método, e elas apontam "
            "para lados opostos — a entrada não traz guia cancelada (a fonte só "
            "carrega guia confirmada) e a expedição traz, com peso apenas na "
            "faixa solicitado."
        )
        avisos.append(
            "Tipo de operação não abre nesta visão, e o filtro de operação não "
            "vale nela: as duas tabelas têm listas de operação diferentes, e "
            "filtrar por uma delas zeraria o outro movimento. Para abrir ou "
            "filtrar por operação, escolha Entrada ou Saída."
        )

    return {
        "filtros": _eco(filtros),
        "lente": {"chave": filtros.lente, "nome": lente["nome"],
                  "unidade": lente["unidade"]},
        "niveis": list(niveis),
        "meses": meses,
        "rotulos_meses": rotulos_meses,
        "linhas": pagina,
        "total": {m: raiz["valores"].get(m) for m in meses},
        # O recorte inteiro, nao a pagina: e o que a tela usa para avisar antes
        # de um download grande, e download nunca e de uma pagina so.
        "total_linhas": total_linhas,
        "paginacao": {
            "pagina": filtros.pagina,
            "por_pagina": UNIDADES_POR_PAGINA,
            "total_unidades": total_unidades,
            "paginas": max(1, -(-total_unidades // UNIDADES_POR_PAGINA)),
        },
        "avisos": avisos,
    }


def _ordenar(nos, meses):
    """Ordena por peso total decrescente, menos as faixas e os movimentos --
    que ficam na ordem do relatorio, porque ali e leitura e nao ranking."""
    for no in nos:
        if no["filhos"] and no["filhos"][0]["nivel"] == FAIXA:
            ordem = {f: i for i, f in enumerate(contrato.FAIXAS)}
            no["filhos"].sort(key=lambda n: ordem.get(n["chave"], 99))
        elif no["filhos"] and no["filhos"][0]["nivel"] == MOVIMENTO:
            ordem = {m: i for i, m in enumerate(ORDEM_MOVIMENTO)}
            no["filhos"].sort(key=lambda n: ordem.get(n["chave"], 99))
        else:
            no["filhos"].sort(
                key=lambda n: -sum(v for v in n["valores"].values() if v)
            )
        _ordenar(no["filhos"], meses)


def _eco(filtros):
    """Devolve o recorte aplicado. Delega para `Filtros.como_dict()`, que e o
    que a auditoria grava -- uma copia so."""
    return filtros.como_dict()


def _vazia(filtros, meses, rotulos_meses, lente, avisos):
    return {
        "filtros": _eco(filtros),
        "lente": {"chave": filtros.lente, "nome": lente["nome"],
                  "unidade": lente["unidade"]},
        "niveis": list(HIERARQUIA[filtros.movimento]),
        "meses": meses,
        "rotulos_meses": rotulos_meses,
        "linhas": [],
        "total": {m: None for m in meses},
        "total_linhas": 0,
        "paginacao": {"pagina": 1, "por_pagina": UNIDADES_POR_PAGINA,
                      "total_unidades": 0, "paginas": 1},
        "avisos": avisos,
    }
