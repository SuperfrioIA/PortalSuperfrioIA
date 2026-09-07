"""O comparador: a mesma Matriz nas duas fontes, célula a célula.

Lote C3 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`, 06/set/2026).

## Por que ele existe

O D3 do plano original dizia: *"a defesa contra regressão silenciosa na tradução
do SQL é comparar os dois — mesma Matriz, mesmo recorte, mesmo total, no
Postgres e no Oracle. Se os números divergirem, é bug de tradução, e ele aparece
com nome e sobrenome."* E dizia também que essa oportunidade **morre quando o
`nuvem-db` for apagado**.

Com a chave de fonte (`fonte.py`), as duas fontes ficam vivas ao mesmo tempo em
produção — então a comparação deixa de ser um teste que a Maria roda uma vez na
janela e vira um endpoint só-admin que ela roda quantas vezes quiser, com dado
real, **antes** de virar a chave. É o portão do C5.

## O que se compara, e como

A Matriz é uma árvore (unidade › cliente › ... › mês). Este módulo a **achata**
em `{(caminho, mês): valor}`, onde o caminho é a tupla de CHAVES da raiz até o
nó — sigla exibida, raiz do CNPJ, operação, faixa, movimento —, mais a linha de
total (`__total__`). Duas árvores batem quando todo par (caminho, mês) existe
nas duas e tem o mesmo valor, e quando `total_linhas` é igual.

Chave, e não rótulo, porque a chave é o que identifica a linha nas duas fontes
(a raiz do CNPJ é a mesma; a razão social canonizada pode divergir). O rótulo é
comparado à parte e reportado à parte: número diferente é bug de SQL; rótulo
diferente é a camada de decisões dizendo outra coisa — problemas distintos, com
diagnósticos distintos.

## Comparação numérica estrita

`Decimal('150.000') == Decimal('150')` é verdadeiro no Python, e é isso que se
quer: a fonte pode formatar a escala diferente sem o número ter mudado. Mas
`None` (célula sem linha) e `0` são **diferentes**, de propósito: a tela mostra
`—` para um e `0` para o outro, e um grupo que existe numa fonte e não na outra
é exatamente o que se veio procurar.

## O que este módulo NÃO faz

Não conecta em banco nenhum e não sabe o que é Postgres ou Oracle: recebe dois
dicionários no formato de `matriz.matriz()` e devolve a diferença. Quem busca os
dois lados é o router. Puro, para ser testável sem fonte nenhuma.
"""

import time
from decimal import Decimal, InvalidOperation

TOTAL = "__total__"
_AUSENTE = object()


def _decimal(valor):
    """Número como `Decimal`, para a comparação ignorar escala e tipo (o
    Postgres devolve `int` para `SUM(integer)`; o Oracle, `Decimal`). Texto que
    não é número passa cru."""
    if valor is None or isinstance(valor, Decimal):
        return valor
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return valor


def _texto(valor):
    if valor is _AUSENTE:
        return "(ausente)"
    if valor is None:
        return None
    return str(valor)


def _caminho(tupla) -> str:
    return " › ".join(tupla)


def achatar(matriz: dict) -> tuple[dict, dict]:
    """`(valores, rotulos)` de uma Matriz no formato de `matriz.matriz()`.

    `valores[(caminho, mes)] = Decimal|None`; `rotulos[caminho] = rótulo`.
    O caminho é a tupla de chaves da raiz até o nó."""
    valores: dict = {}
    rotulos: dict = {}

    def descer(nos, prefixo):
        for no in nos or ():
            caminho = prefixo + (str(no.get("chave")),)
            rotulos[caminho] = no.get("rotulo")
            for mes, valor in (no.get("valores") or {}).items():
                valores[(caminho, mes)] = _decimal(valor)
            descer(no.get("filhos"), caminho)

    descer(matriz.get("linhas"), ())
    for mes, valor in (matriz.get("total") or {}).items():
        valores[((TOTAL,), mes)] = _decimal(valor)
    return valores, rotulos


def comparar_matriz(postgres: dict, dw: dict) -> dict:
    """A diferença entre duas Matrizes do MESMO recorte. Ver docstring do módulo
    para o que "bate" significa."""
    vp, rp = achatar(postgres)
    vd, rd = achatar(dw)

    diferencas = []
    for chave in sorted(set(vp) | set(vd), key=lambda k: (k[0], k[1])):
        a = vp.get(chave, _AUSENTE)
        b = vd.get(chave, _AUSENTE)
        if a is _AUSENTE or b is _AUSENTE or a != b:
            caminho, mes = chave
            diferencas.append({
                "caminho": _caminho(caminho), "mes": mes,
                "postgres": _texto(a), "dw": _texto(b),
            })

    rotulos_divergentes = [
        {"caminho": _caminho(c), "postgres": rp[c], "dw": rd[c]}
        for c in sorted(set(rp) & set(rd)) if rp[c] != rd[c]
    ]
    so_no_postgres = sorted(_caminho(c) for c in set(rp) - set(rd))
    so_no_dw = sorted(_caminho(c) for c in set(rd) - set(rp))

    total_linhas = {"postgres": postgres.get("total_linhas"), "dw": dw.get("total_linhas")}
    pag_pg, pag_dw = postgres.get("paginacao") or {}, dw.get("paginacao") or {}
    total_unidades = {
        "postgres": pag_pg.get("total_unidades"), "dw": pag_dw.get("total_unidades"),
    }

    bate = (
        not diferencas
        and total_linhas["postgres"] == total_linhas["dw"]
        and total_unidades["postgres"] == total_unidades["dw"]
    )
    return {
        "bate": bate,
        "celulas_comparadas": len(set(vp) | set(vd)),
        "diferencas": diferencas,
        "total_linhas": total_linhas,
        "total_unidades": total_unidades,
        # rótulo divergente NÃO derruba o `bate`: é a camada de decisões, não
        # o SQL — e é reportado para ser olhado, não para bloquear a virada
        "rotulos_divergentes": rotulos_divergentes,
        "caminhos_so_no_postgres": so_no_postgres,
        "caminhos_so_no_dw": so_no_dw,
        "avisos_iguais": (postgres.get("avisos") or []) == (dw.get("avisos") or []),
    }


def _listas(a, b) -> dict:
    a, b = set(a or ()), set(b or ())
    return {
        "bate": a == b,
        "so_no_postgres": sorted(a - b),
        "so_no_dw": sorted(b - a),
    }


def comparar_opcoes(postgres: dict, dw: dict) -> dict:
    """As listas do `/opcoes` nas duas fontes: unidades exibidas, clientes com
    rótulo, tipos, operações por movimento e o período disponível. É a prova da
    CAMADA DE DECISÕES (sigla, tipo, razão social canonizada), que a Matriz só
    prova indiretamente."""
    clientes_pg = {f"{c['chave']}={c['rotulo']}" for c in postgres.get("clientes") or ()}
    clientes_dw = {f"{c['chave']}={c['rotulo']}" for c in dw.get("clientes") or ()}
    operacoes = {
        m: _listas((postgres.get("operacoes") or {}).get(m), (dw.get("operacoes") or {}).get(m))
        for m in ("rec", "exp")
    }
    periodo = {"postgres": postgres.get("periodo"), "dw": dw.get("periodo")}
    periodo["bate"] = periodo["postgres"] == periodo["dw"]
    partes = {
        "unidades": _listas(postgres.get("unidades"), dw.get("unidades")),
        "clientes": _listas(clientes_pg, clientes_dw),
        "tipos_estoque": _listas(postgres.get("tipos_estoque"), dw.get("tipos_estoque")),
        "operacoes": operacoes,
        "periodo": periodo,
    }
    bate = all((
        partes["unidades"]["bate"], partes["clientes"]["bate"],
        partes["tipos_estoque"]["bate"], operacoes["rec"]["bate"],
        operacoes["exp"]["bate"], periodo["bate"],
    ))
    return {"bate": bate, **partes}


def cronometrar(funcao):
    """`(resultado, milissegundos)` — o número que o D0 pediu, medido em
    produção com a consulta de verdade."""
    inicio = time.perf_counter()
    resultado = funcao()
    return resultado, int((time.perf_counter() - inicio) * 1000)
