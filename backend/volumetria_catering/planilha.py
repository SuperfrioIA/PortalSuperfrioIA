"""A planilha aberta: as colunas que a tela mostra e a paginacao.

A consulta em si mora em `planilha_dw.py` (DW Oracle). Aqui ficou o que e
definicao e nao e de banco nenhum: quais colunas, com que rotulo, quantas linhas
por pagina.

## Mesmo recorte da Matriz, por construcao

A planilha usa o `FROM`/`WHERE` de `recorte_dw.de_para_where()`, o mesmo da
Matriz. Nao e disciplina, e estrutura: nao existe um segundo lugar onde o filtro
possa divergir. O teste mede isso: somando todas as paginas da planilha, o total
tem que dar **exatamente** o que a Matriz agrega no mesmo recorte.

## Estreita na tela, completa no arquivo

A tela mostra dia, unidade, cliente, guia, operacao, tipo de estoque e a
**lente escolhida** (na saida, as tres faixas dela). O **download** leva a
linha inteira (`download.py`).

## `guia` aparece aqui, e nao na Matriz

O contrato tira a guia da Matriz porque contagem distinta nao soma por linha.
Na planilha ela e coluna de uma linha, nao agregado -- entao entra.
"""

from backend.volumetria_catering import contrato, recorte

LINHAS_POR_PAGINA = 100

# As colunas de contexto da tela, na ordem. `(apelido, rotulo)`.
CONTEXTO = (
    ("dia", "Dia"),
    ("unidade", "Unidade"),
    ("cliente", "Cliente"),
    ("guia", "Guia"),
    ("operacao", "Operação"),
    ("tipo_estoque", "Tipo de estoque"),
)


def _colunas_de_medida(filtros):
    """`[(apelido, coluna, rotulo)]` da lente escolhida.

    Vazio quando a lente nao existe no movimento (pallet na expedicao) -- a
    planilha continua mostrando o contexto, so sem coluna de numero."""
    medidas = recorte.medidas_da_lente(filtros.movimento, filtros.lente)
    nome = contrato.LENTES[filtros.lente]["nome"]
    if not medidas:
        return []
    if list(medidas) == [""]:
        return [("valor", medidas[""], nome)]
    return [
        (faixa, coluna, f"{nome} — {recorte.rotulo_faixa(faixa)}")
        for faixa, coluna in medidas.items()
    ]


def colunas(filtros):
    """As colunas da planilha, na ordem, com rotulo de tela."""
    return [
        {"chave": apelido, "rotulo": rotulo}
        for apelido, rotulo in CONTEXTO
    ] + [
        {"chave": apelido, "rotulo": rotulo}
        for apelido, _coluna, rotulo in _colunas_de_medida(filtros)
    ]
