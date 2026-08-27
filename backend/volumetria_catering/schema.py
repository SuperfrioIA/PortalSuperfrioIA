"""Verificação de drift: o contrato copiado contra as colunas reais do banco.

## O problema que isto resolve

O schema das `cat_*` é governado pelas migrations da nuvem-ia; este repositório
tem uma CÓPIA do contrato (`contrato.py`). A regra é "toda mudança de schema
são duas PRs coordenadas" — mas regra sem trava é promessa. A trava é esta:
antes de servir dado, o módulo compara o contrato com `information_schema` e
**falha nomeando tabela, coluna e o que divergiu**. Drift detectado na hora,
não trinta mil linhas de download depois.

## O que é conferido

- nas duas tabelas de fato: toda coluna do contrato existe, com o tipo e a
  nulabilidade declarados; e **não existe coluna a mais** além das de infra da
  própria nuvem-ia (`id`, `carga_id`) — coluna nova lá sem contrato aqui é
  exatamente o drift que o download deixaria de levar;
- nas dimensões e no registro de carga: só a EXISTÊNCIA das colunas que as
  consultas usam (`recorte.JUNCOES` e a procedência de `opcoes`).

## Quando roda

`garantir(cur)` é chamado por todo endpoint antes da consulta, mas só vai ao
`information_schema` se a última verificação boa tiver mais de
`INTERVALO_REVERIFICACAO` segundos — uma consulta barata a cada 10 min por
processo, e uma migration na nuvem-ia é percebida em até 10 min sem reiniciar
o Hub. Falha nunca fica em cache: o próximo request confere de novo.
"""

import time

from backend.volumetria_catering import contrato

INTERVALO_REVERIFICACAO = 600  # segundos

TABELA_FATO = {"rec": "cat_fato_recebimento", "exp": "cat_fato_expedicao"}

# Colunas que a nuvem-ia tem nos fatos e que NÃO fazem parte do contrato do DW:
# a chave da linha e a FK para a rodada de carga. Não são drift.
INFRA_DO_FATO = frozenset({"id", "carga_id"})

# O que as consultas deste módulo leem fora dos fatos. Só existência.
COLUNAS_DE_APOIO = {
    "cat_unidades": ("sigla_fonte", "sigla"),
    "cat_clientes": ("raiz_cnpj", "razao_social"),
    "cat_tipos_estoque": ("nome_estoque", "tipo"),
    "cat_cargas": ("id", "tabela_origem", "fonte", "terminada_em", "linhas_lidas", "status"),
}

# Tipo do contrato -> `data_type` do information_schema.
_TIPO_CATALOGO = {
    "INTEGER": "integer",
    "SMALLINT": "smallint",
    "TEXT": "text",
    "DATE": "date",
    "TIMESTAMP": "timestamp without time zone",
    "NUMERIC(18,3)": "numeric",
}


class ContratoDivergente(Exception):
    """O banco não tem a forma que o contrato copiado descreve.

    A mensagem lista cada divergência com tabela e coluna. É erro de
    coordenação entre repositórios, e a saída é uma PR aqui (atualizar a cópia)
    — nunca um ajuste no dado."""

    def __init__(self, problemas):
        self.problemas = list(problemas)
        super().__init__(
            "contrato da volumetria divergente do banco da nuvem-ia — "
            f"{len(self.problemas)} problema(s): " + "; ".join(self.problemas)
            + f". Cópia local: {contrato.ORIGEM}. Atualize backend/volumetria_catering/"
            "contrato.py junto com a migration correspondente na nuvem-ia."
        )


def _colunas_reais(cur) -> dict:
    """`{tabela: {coluna: (data_type, nulavel, precisao, escala)}}` das tabelas
    que interessam. Uma ida só ao catálogo."""
    tabelas = tuple(TABELA_FATO.values()) + tuple(COLUNAS_DE_APOIO)
    cur.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable = 'YES',
               numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = ANY(%(tabelas)s)
        """,
        {"tabelas": list(tabelas)},
    )
    reais: dict = {}
    for tabela, coluna, tipo, nulavel, precisao, escala in cur.fetchall():
        reais.setdefault(tabela, {})[coluna] = (tipo, nulavel, precisao, escala)
    return reais


def comparar(reais: dict) -> list[str]:
    """Compara o contrato com o retrato do catálogo. Pura, para ser testável sem
    banco. Devolve a lista de divergências (vazia = tudo certo)."""
    problemas: list[str] = []

    for movimento, tabela in TABELA_FATO.items():
        colunas_reais = reais.get(tabela)
        if not colunas_reais:
            # `information_schema.columns` só lista colunas em que o role tem
            # privilégio: GRANT faltando no `hub_leitura` aparece igual a
            # tabela inexistente. A mensagem tem que apontar para as duas.
            problemas.append(
                f"{tabela}: tabela não existe ou o role da conexão não tem SELECT nela"
            )
            continue
        esperadas = {nome: (tipo, nulavel) for nome, tipo, nulavel in contrato.colunas(movimento)}
        for nome, (tipo, nulavel) in esperadas.items():
            real = colunas_reais.get(nome)
            if real is None:
                problemas.append(f"{tabela}.{nome}: coluna do contrato não existe no banco")
                continue
            tipo_real, nulavel_real, precisao, escala = real
            if tipo_real != _TIPO_CATALOGO[tipo]:
                problemas.append(
                    f"{tabela}.{nome}: tipo esperado {tipo}, banco tem {tipo_real}"
                )
            elif tipo == "NUMERIC(18,3)" and (precisao, escala) != (18, 3):
                problemas.append(
                    f"{tabela}.{nome}: esperado NUMERIC(18,3), banco tem "
                    f"NUMERIC({precisao},{escala})"
                )
            if nulavel_real != nulavel:
                problemas.append(
                    f"{tabela}.{nome}: contrato diz {'nulável' if nulavel else 'NOT NULL'}, "
                    f"banco diz {'nulável' if nulavel_real else 'NOT NULL'}"
                )
        extras = sorted(set(colunas_reais) - set(esperadas) - INFRA_DO_FATO)
        for nome in extras:
            problemas.append(
                f"{tabela}.{nome}: coluna existe no banco e não está no contrato copiado"
            )

    for tabela, colunas in COLUNAS_DE_APOIO.items():
        colunas_reais = reais.get(tabela)
        if not colunas_reais:
            # `information_schema.columns` só lista colunas em que o role tem
            # privilégio: GRANT faltando no `hub_leitura` aparece igual a
            # tabela inexistente. A mensagem tem que apontar para as duas.
            problemas.append(
                f"{tabela}: tabela não existe ou o role da conexão não tem SELECT nela"
            )
            continue
        for nome in colunas:
            if nome not in colunas_reais:
                problemas.append(f"{tabela}.{nome}: coluna usada pela consulta não existe")

    return problemas


def verificar(cur) -> None:
    """Confere agora, sem cache. Levanta `ContratoDivergente`."""
    problemas = comparar(_colunas_reais(cur))
    if problemas:
        raise ContratoDivergente(problemas)


_verificado_em: float | None = None


def garantir(cur) -> None:
    """Confere se a última verificação boa venceu (ou nunca houve). Falha não
    entra no cache — o request seguinte confere de novo."""
    global _verificado_em
    agora = time.monotonic()
    if _verificado_em is not None and agora - _verificado_em < INTERVALO_REVERIFICACAO:
        return
    verificar(cur)
    _verificado_em = agora


def invalidar() -> None:
    """Esquece a última verificação boa. Para testes e para quem mexer no schema
    de teste no meio de uma sessão."""
    global _verificado_em
    _verificado_em = None
