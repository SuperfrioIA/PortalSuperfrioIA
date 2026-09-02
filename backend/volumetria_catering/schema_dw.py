"""Verificação de drift contra o DW: o contrato conferido na própria fonte.

Lote D1 de `docs/PLANO_VOLUMETRIA_DW_DIRETO.md`.

## Por que este arquivo é MENOR que o `schema.py`

O `schema.py` existe para uma dívida de coordenação: o schema das `cat_*` é
governado pelas migrations da nuvem-ia, este repositório tem uma CÓPIA do
contrato, e a regra "toda mudança de schema são duas PRs coordenadas" é promessa
sem trava. Lendo o DW direto, essa dívida **deixa de existir** — não há mais
cópia intermediária divergindo de nada. Sobra a pergunta que continua valendo: *o
DW ainda tem a forma que este contrato descreve?*

## Duas conferências, que respondem coisas diferentes

1. **O `SELECT` gerado do contrato, com `WHERE 1=0`.** É a prova definitiva, e é
   quase de graça: o Oracle compila o statement, resolve cada nome de coluna e
   confere privilégio sem ler um bloco de dado. Coluna que sumiu dá `ORA-00904`
   nomeando a coluna; tabela que sumiu (ou sem GRANT) dá `ORA-00942`. Como é o
   MESMO texto que as consultas de verdade usam, ela prova o que vai acontecer,
   não uma aproximação;
2. **o `ALL_TAB_COLUMNS`.** Responde o que o item 1 não vê: o **tipo** de cada
   coluna, e a coluna **nova** que o DW ganhou e o nosso `SELECT` não leva.

Nenhuma das duas substitui a outra. A primeira não vê tipo; a segunda não prova
privilégio (o `ALL_TAB_COLUMNS` só lista objeto que a sessão pode ver, então
GRANT faltando aparece igual a tabela inexistente — a mesma armadilha do
`information_schema`).

## O que se confere de tipo, e o que NÃO se confere

Confere-se a **família**, não o tipo exato, porque o contrato nasceu descrevendo
um Postgres e não este Oracle:

| contrato | família aceita no DW | por quê |
|---|---|---|
| `TEXT` | `VARCHAR2`, `CHAR`, `NVARCHAR2`, `NCHAR`, `CLOB` | qualquer uma chega como `str` |
| `INTEGER`, `SMALLINT`, `NUMERIC(18,3)` | `NUMBER` | com `fetch_decimals`, `NUMBER` chega como `Decimal` |
| `DATE`, `TIMESTAMP` | `DATE`, `TIMESTAMP(n)` | o `DATE` do Oracle já carrega hora; a distinção era do Postgres |

A precisão declarada (`NUMBER(18,3)` × `NUMBER`) **não** é conferida: o DW
declara as medidas como `NUMBER` sem escala, e é o `fetch_decimals` — não a
declaração — que garante que o valor chega íntegro. Mas `FLOAT`,
`BINARY_FLOAT` e `BINARY_DOUBLE` **são** reprovados numa coluna nossa de
medida, e essa é a checagem que vale o arquivo: nesses tipos o driver entrega
`float` mesmo com `fetch_decimals` ligado, e peso com 3 decimais perderia
precisão em silêncio.

**Nulabilidade não é conferida, de propósito.** O `NOT NULL` do nosso contrato é
uma afirmação sobre o DADO, medida em 433 mil linhas na nuvem-ia — não sobre a
declaração do DW. O DW pode declarar tudo nulável e estar correto; comparar as
duas coisas produziria drift falso no primeiro dia e ensinaria a ignorar o
alarme. A afirmação sobre o dado tem outra trava, no lugar certo: a sondagem de
preenchimento da carga, que já mediu (e já pegou `sk_cliente`, 1 linha em
232.089).

## Falha e aviso não são a mesma coisa

- **problema** (levanta `ContratoDivergenteDW`): tabela invisível, coluna do
  contrato que não existe, tipo de família errada. O `SELECT` já não funciona ou
  o número chega deformado — servir dado assim é pior que não servir;
- **aviso** (só informa): coluna nova no DW. Ela não quebra nada nosso, e
  derrubar o card porque a equipe do DW acrescentou uma coluna seria transformar
  trabalho alheio em incidente nosso. Fica visível no diagnóstico, que é onde se
  decide se ela deve entrar no contrato.

## Quando roda

`garantir(cur)` confere se a última verificação boa tem mais de
`INTERVALO_REVERIFICACAO` segundos. Falha nunca fica em cache — o próximo
request confere de novo. No D1 só o endpoint de diagnóstico chama
`verificar()`; é o D3 que põe `garantir()` na frente das consultas.
"""

import logging
import time

from backend.volumetria_catering import contrato

logger = logging.getLogger(__name__)

INTERVALO_REVERIFICACAO = 600  # segundos

# Tipo do contrato -> famílias aceitas no `ALL_TAB_COLUMNS.DATA_TYPE`.
# `TIMESTAMP` aparece com a precisão colada (`TIMESTAMP(6)`), então a comparação
# é por prefixo — ver `_familia_ok`.
_FAMILIA_TEXTO = ("VARCHAR2", "VARCHAR", "CHAR", "NVARCHAR2", "NCHAR", "CLOB", "NCLOB")
_FAMILIA_NUMERO = ("NUMBER",)
_FAMILIA_DATA = ("DATE", "TIMESTAMP")

_FAMILIAS = {
    "TEXT": _FAMILIA_TEXTO,
    "INTEGER": _FAMILIA_NUMERO,
    "SMALLINT": _FAMILIA_NUMERO,
    "NUMERIC(18,3)": _FAMILIA_NUMERO,
    "DATE": _FAMILIA_DATA,
    "TIMESTAMP": _FAMILIA_DATA,
}

# Tipos que o driver entrega como `float` mesmo com `fetch_decimals` ligado. Numa
# coluna de medida isso é perda de precisão silenciosa, e é a razão de a
# conferência de tipo existir.
PONTO_FLUTUANTE = ("FLOAT", "BINARY_FLOAT", "BINARY_DOUBLE")


class ContratoDivergenteDW(Exception):
    """O DW não tem a forma que este contrato descreve.

    A mensagem lista cada divergência com tabela e coluna. Não se ajusta o dado
    para caber: a saída é uma PR atualizando o contrato — depois de olhar o
    porquê."""

    def __init__(self, problemas):
        self.problemas = list(problemas)
        super().__init__(
            "contrato da volumetria divergente do DW — "
            f"{len(self.problemas)} problema(s): " + "; ".join(self.problemas)
            + ". Atualize backend/volumetria_catering/contrato.py (e confirme a "
            "mudança com quem mantém o DW antes)."
        )


def _partes_do_nome(movimento: str) -> tuple[str | None, str]:
    """`(dono, tabela)` a partir do nome qualificado.

    O `ALL_TAB_COLUMNS` guarda dono e tabela em colunas separadas. Sem dono no
    nome (só possível pela variável de ambiente), filtra-se apenas pela tabela:
    é menos preciso, e a alternativa — supor `USER` — inventaria um dono que a
    configuração não disse."""
    nome = contrato.tabela(movimento)
    dono, _, tabela = nome.partition(".")
    return (dono, tabela) if tabela else (None, dono)


def sql_zero_linhas(movimento: str) -> str:
    """O `SELECT` do contrato que não lê bloco nenhum.

    Mesmo texto de coluna que as consultas de verdade usam — é o que faz esta
    conferência provar o statement, e não um parecido com ele."""
    colunas = ", ".join(contrato.colunas_dw(movimento))
    return f"SELECT {colunas} FROM {contrato.tabela(movimento)} WHERE 1=0"


def sql_catalogo(com_dono: bool) -> str:
    """A consulta ao catálogo. Nome de tabela e dono vão por BIND — eles vêm de
    variável de ambiente, e valor de fora do código dentro de uma string de SQL
    é o defeito que não aparece na revisão."""
    onde = "TABLE_NAME = :tabela"
    if com_dono:
        onde = "OWNER = :dono AND " + onde
    return (
        "SELECT COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS "
        f"WHERE {onde} ORDER BY COLUMN_ID"
    )


def _familia_ok(tipo_contrato: str, tipo_dw: str) -> bool:
    """Se o tipo do DW pertence à família que o contrato aceita.

    Por prefixo porque o `ALL_TAB_COLUMNS` cola a precisão no nome
    (`TIMESTAMP(6)`), e porque `VARCHAR2` sem tamanho não existe lá."""
    return tipo_dw.upper().startswith(_FAMILIAS[tipo_contrato])


def comparar(movimento: str, tipos_reais: dict) -> tuple[list[str], list[str]]:
    """`(problemas, avisos)` de um movimento. Pura, para ser testável sem DW.

    `tipos_reais` é `{COLUNA: DATA_TYPE}` como o catálogo respondeu."""
    tabela = contrato.tabela(movimento)
    if not tipos_reais:
        # O `ALL_TAB_COLUMNS` só lista objeto que a sessão pode ver: GRANT
        # faltando no usuário de leitura aparece igual a tabela inexistente. A
        # mensagem tem que apontar para as duas — e nomear quem resolve, porque
        # o GRANT não é nosso.
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
    for nossa, tipo, _nulo in contrato.colunas(movimento):
        coluna = contrato.coluna_dw(nossa, movimento)
        esperadas.add(coluna)
        tipo_dw = tipos_reais.get(coluna)
        if tipo_dw is None:
            problemas.append(
                f"{tabela}.{coluna}: coluna do contrato não existe no DW "
                f"(nosso nome: {nossa})"
            )
            continue
        if tipo_dw.upper().startswith(PONTO_FLUTUANTE) and tipo == "NUMERIC(18,3)":
            problemas.append(
                f"{tabela}.{coluna}: o DW declara {tipo_dw}, que chega como float "
                "mesmo com fetch_decimals — peso com 3 decimais perderia precisão "
                "em silêncio"
            )
        elif not _familia_ok(tipo, tipo_dw):
            problemas.append(
                f"{tabela}.{coluna}: contrato diz {tipo}, o DW tem {tipo_dw}"
            )

    # Aviso, não problema: coluna nova no DW não quebra nada nosso.
    avisos = [
        f"{tabela}.{coluna}: coluna existe no DW e não está no contrato "
        f"(tipo {tipos_reais[coluna]}) — o SELECT deste módulo não a leva"
        for coluna in sorted(set(tipos_reais) - esperadas)
    ]
    return problemas, avisos


def _tipos_do_catalogo(cur, movimento: str) -> dict:
    """`{COLUNA: DATA_TYPE}` do catálogo, para um movimento."""
    dono, tabela = _partes_do_nome(movimento)
    binds = {"tabela": tabela}
    if dono is not None:
        binds["dono"] = dono
    cur.execute(sql_catalogo(dono is not None), binds)
    return {str(coluna): str(tipo) for coluna, tipo in cur.fetchall()}


def conferir(cur, movimento: str) -> dict:
    """Confere um movimento e devolve o que foi visto, sem levantar.

    Devolver em vez de levantar é o que o diagnóstico precisa: ele quer mostrar
    os DOIS movimentos, e o primeiro falhar não pode esconder o segundo. Quem
    quer a versão que interrompe usa `verificar()`."""
    resultado = {
        "movimento": movimento,
        "tabela": contrato.tabela(movimento),
        "colunas_no_contrato": len(contrato.colunas_dw(movimento)),
        "select_compila": False,
        "colunas_no_dw": 0,
        "problemas": [],
        "avisos": [],
    }

    # 1) o statement de verdade, sem ler bloco. Falha aqui é `ORA-00904`/
    # `ORA-00942`, e a mensagem do Oracle NOMEIA o que faltou — então ela vale
    # mais que qualquer texto nosso e é repassada. Ela não carrega credencial:
    # é nome de coluna e de tabela, que já estão no contrato.
    try:
        cur.execute(sql_zero_linhas(movimento))
        cur.fetchall()
        resultado["select_compila"] = True
    except Exception as erro:
        resultado["problemas"].append(
            f"{resultado['tabela']}: o SELECT gerado do contrato não compilou no "
            f"DW — {type(erro).__name__}: {erro}"
        )

    # 2) o catálogo: tipo e coluna nova, que o item 1 não vê.
    try:
        tipos = _tipos_do_catalogo(cur, movimento)
    except Exception as erro:
        resultado["problemas"].append(
            f"{resultado['tabela']}: o ALL_TAB_COLUMNS não respondeu — "
            f"{type(erro).__name__}: {erro}"
        )
        return resultado

    resultado["colunas_no_dw"] = len(tipos)
    problemas, avisos = comparar(movimento, tipos)
    resultado["problemas"].extend(problemas)
    resultado["avisos"] = avisos
    return resultado


def verificar(cur) -> list[str]:
    """Confere os dois movimentos agora, sem cache. Levanta
    `ContratoDivergenteDW` se houver problema; devolve os avisos."""
    problemas: list[str] = []
    avisos: list[str] = []
    for movimento in contrato.MOVIMENTOS:
        visto = conferir(cur, movimento)
        problemas.extend(visto["problemas"])
        avisos.extend(visto["avisos"])
    if problemas:
        raise ContratoDivergenteDW(problemas)
    for aviso in avisos:
        # Aviso vai para o log e não para a resposta: ele não muda o que a tela
        # mostra, mas é o rastro de quando o DW mudou.
        logger.warning("volumetria/DW: %s", aviso)
    return avisos


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
    """Esquece a última verificação boa. Para testes e para quem quiser refazer
    a conferência no meio de uma sessão."""
    global _verificado_em
    _verificado_em = None
