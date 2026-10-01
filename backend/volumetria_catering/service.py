"""Serviço da volumetria de catering: a Matriz e as opções, sem HTTP.

Extraído do `router.py` no Lote 1 do SuperfrioIA (`docs/PLANO_LOTES_SUPERFRIOIA.md`).
Quem chama uma **função** — a rota, hoje; o adaptador da IA, depois — chama esta
camada, e recebe exatamente o que a tela recebe. Nada aqui é regra nova: abrir o
cursor, conferir o contrato do DW e montar o `Filtros` já existiam no router; o
cálculo continua em `matriz.py`/`matriz_dw.py`/`recorte.py`/`contrato.py`/
`dimensoes_dw.py`, que este lote **não tocou** (é isso que garante que não existe
uma segunda fórmula).

## O que o serviço não conhece

- **FastAPI e HTTP.** Falha vira exceção de domínio: `VolumetriaIndisponivel`
  (DW fora, credencial ausente, contrato divergente, configuração inválida) e
  `recorte.FiltroInvalido` (filtro que o contrato não admite). Traduzir para 503 e
  400, com a mensagem que já existia, é trabalho da rota;
- **permissão.** Quem pode chamar é decisão de quem chama (`volumetria-catering:ver`
  na rota; concessão + `ver` na IA);
- **JSON.** `matriz()` devolve `Decimal`; a rota converte para texto, para peso e
  valor não passarem pelo `float`.

## O que não muda de lugar na ordem

Conectar -> `preparar_cursor` -> `schema_dw.garantir` -> consultar. A ordem decide
em que momento um DW fora do ar ou um contrato divergente aparece, e portanto
quando o 503 sai; ela é a mesma de antes e os testes de equivalência a cobrem.

O cache de dimensões é o de `dimensoes_dw.obter` (por processo, TTL de 1 h). Este
módulo não cria cache.
"""

import logging
from contextlib import contextmanager
from dataclasses import fields

from backend.volumetria_catering import (
    conexao_dw,
    contrato,
    dimensoes_dw,
    download,
    matriz_dw,
    recorte,
    schema_dw,
)

logger = logging.getLogger(__name__)

# Campos de `Filtros` que são listas. O serviço aceita qualquer sequência e guarda
# tupla, que é o que `Filtros` e o SQL esperam.
_LISTAS = ("unidades", "clientes", "tipos_estoque", "operacoes", "dias")
_CAMPOS_DO_FILTRO = frozenset(f.name for f in fields(recorte.Filtros))


class VolumetriaIndisponivel(Exception):
    """A volumetria não consegue responder agora: DW fora do ar, credencial
    ausente, contrato divergente do schema, ou configuração inválida (fuso,
    abertura). A mensagem é a que a rota devolve no 503 — nomeia a causa."""


def erro_do_oracle(erro: BaseException) -> bool:
    """Se a exceção veio do driver do Oracle — sem importar o `oracledb` aqui
    (o import é preguiçoso de propósito, ver `conexao_dw._driver`). Erro de
    rede no meio de uma consulta é `oracledb.Error`, e neste card ele tem que
    virar indisponibilidade, não erro 500."""
    return type(erro).__module__.split(".")[0] == "oracledb"


@contextmanager
def cursor():
    """O DW Oracle, via `conexao_dw.py`. Mesmo desenho do transporte e do
    estoque: `preparar_cursor` antes de tudo, drift conferido a cada 10 min.

    Levanta `VolumetriaIndisponivel` no lugar do que antes era 503."""
    try:
        conn = conexao_dw.conectar()
    except conexao_dw.DWIndisponivel as erro:
        raise VolumetriaIndisponivel(str(erro)) from None
    try:
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            try:
                schema_dw.garantir(cur)
            except schema_dw.ContratoDivergenteDW as erro:
                logger.error("volumetria/DW: %s", erro)
                raise VolumetriaIndisponivel(str(erro)) from None
            yield cur
    except conexao_dw.DWIndisponivel as erro:
        raise VolumetriaIndisponivel(str(erro)) from None
    except Exception as erro:
        if not erro_do_oracle(erro):
            raise
        logger.error("volumetria/DW: o DW falhou no meio da consulta: %s", type(erro).__name__)
        raise VolumetriaIndisponivel(
            f"o DW falhou durante a consulta ({type(erro).__name__}). A "
            "volumetria de catering lê o DW direto; o resto do Hub continua "
            "funcionando."
        ) from None
    finally:
        conn.close()


def filtros_de(**campos) -> recorte.Filtros:
    """Monta e valida o recorte. Um lugar só para a rota e para a IA.

    Os campos são os de `recorte.Filtros` (`de`, `ate`, `movimento`, `lente`,
    `faixa`, `unidades`, `clientes`, `tipos_estoque`, `operacoes`, `dias`,
    `pagina`); `de` e `ate` são obrigatórios e o resto tem o **mesmo padrão da
    rota** (entrada, peso líquido, `solicitado`, página 1) — o padrão da IA para
    a faixa é decisão do adaptador, não daqui.

    Levanta `recorte.FiltroInvalido` para campo desconhecido, lista que não é
    lista ou valor que o contrato não admite (`Filtros.validar()`)."""
    desconhecidos = sorted(set(campos) - _CAMPOS_DO_FILTRO)
    if desconhecidos:
        raise recorte.FiltroInvalido(f"campo fora do contrato: {', '.join(desconhecidos)}")
    for nome in _LISTAS:
        if nome not in campos:
            continue
        # Uma string é sequência, e `tuple("RMSP")` viraria quatro unidades.
        if isinstance(campos[nome], (str, bytes)):
            raise recorte.FiltroInvalido(f"{nome}: deve ser uma lista, veio {campos[nome]!r}")
        campos[nome] = tuple(campos[nome])
    try:
        filtros = recorte.Filtros(**campos)
    except TypeError:  # `de`/`ate` ausentes
        raise recorte.FiltroInvalido("de e ate são obrigatórios") from None
    return filtros.validar()


def matriz(filtros: recorte.Filtros) -> dict:
    """A Matriz do recorte, lida do DW. É a função que a tela chama.

    Devolve o `dict` de `matriz.montar()` como ele é, com `Decimal`. `filtros`
    deve ter passado por `filtros_de` (ou `validar()`)."""
    with cursor() as cur:
        return matriz_dw.matriz(cur, filtros, dimensoes_dw.obter(cur))


# ------------------------------------------------------------------ opções
def _opcoes_estaticas() -> dict:
    """A parte do `/opcoes` que não vem do dado: tetos, lentes, faixas e os
    movimentos da TELA."""
    return {
        "teto_confirmacao": download.TETO_CONFIRMACAO,
        "teto_xlsx": download.TETO_XLSX,
        "lentes": [
            {"chave": c, "nome": d["nome"], "unidade": d["unidade"],
             "so_entrada": d["exp"] is None}
            for c, d in contrato.LENTES.items()
        ],
        "faixas": [
            {"chave": f, "rotulo": recorte.rotulo_faixa(f)} for f in contrato.FAIXAS
        ],
        # Os movimentos da TELA, e não os do dado: o terceiro é "as duas
        # juntas", que não é tabela nem tipo de linha.
        "movimentos": [
            {"chave": "rec", "rotulo": "Entrada", "so_matriz": False},
            {"chave": "exp", "rotulo": "Saída", "so_matriz": False},
            {"chave": recorte.CONJUNTA, "rotulo": "Entrada + saída", "so_matriz": True},
        ],
    }


def _abertura(hoje):
    """A abertura da tela: janeiro do ano corrente até hoje (configurável). A
    única trava é a da inversão, para uma abertura pinada no futuro não abrir
    a tela com "período invertido"."""
    try:
        abertura_de = min(contrato.abertura_de(hoje), hoje)
    except contrato.AberturaInvalida as erro:
        raise VolumetriaIndisponivel(str(erro)) from None
    return {"de": abertura_de.isoformat(), "ate": hoje.isoformat()}


def opcoes() -> dict:
    """O que existe para filtrar — lido do dado, não de lista fixa.

    As listas vêm do retrato em cache (`dimensoes_dw.obter`, TTL de 1 h), e a
    procedência é o `MAX(DW_DATA_ALTERACAO)` da própria fonte — "de quando são
    os rótulos" é a hora da varredura. Unidade nova, cliente novo ou operação
    nova aparecem no filtro sozinhos. Traz também o período que existe no dado,
    a abertura da tela e os tetos do download — do Python, para não existir uma
    segunda cópia deles no JavaScript.

    Já é JSON puro (datas em texto, sem `Decimal`)."""
    try:
        contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise VolumetriaIndisponivel(str(erro)) from None

    with cursor() as cur:
        dim = dimensoes_dw.obter(cur)

    # "Hoje" pelo relógio do processo no fuso de exibição — o DW é fonte de
    # dado, não de hora (mesma decisão do transporte e do estoque).
    hoje = dimensoes_dw.hoje_no_fuso()
    primeiro, ultimo = dim.periodo
    return {
        "unidades": dim.unidades_exibidas(),
        "clientes": dim.clientes(),
        "operacoes": dim.operacoes,
        "tipos_estoque": dim.tipos(),
        "periodo": {
            "de": primeiro.isoformat() if primeiro else None,
            "ate": ultimo.isoformat() if ultimo else None,
        },
        "abertura": _abertura(hoje),
        **_opcoes_estaticas(),
        "atualizado_ate": {
            m: (v.isoformat() if v else None) for m, v in dim.atualizado_em.items()
        },
        "rotulos_calculados_em": dim.calculado_em.isoformat(),
        "processo_dw": contrato.PROCESSO_DW,
        "contrato": contrato.ORIGEM,
    }
