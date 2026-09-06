"""Download do recorte lido do DW Oracle: CSV em streaming e xlsx sob teto.

Lote C2 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

## O mesmo arquivo, com outra fonte

Cabeçalho, ordem de colunas, formato Excel-first (`;`, BOM, vírgula decimal,
`DD/MM/AAAA`), o zero à esquerda protegido no xlsx, o teto de 150 mil linhas e
o nome do arquivo são os de `download.py`, reaproveitados — não copiados. A
pessoa que baixa o mesmo recorte das duas fontes tem que receber dois arquivos
iguais, e é assim que o C3 vai conferir isso.

## O que muda

- sem cursor nomeado (o oracledb não tem esse conceito): `preparar_cursor()`
  (`arraysize`/`prefetchrows`) já faz o driver entregar em blocos, e iterar
  `for linha in cur` nunca segura o resultado inteiro na memória. O gerador
  continua **dono da própria conexão**, pelo mesmo motivo do Postgres: o corpo
  roda depois de a resposta HTTP começar;
- as quatro colunas DERIVADAS (dia, unidade exibida, cliente canonizado, tipo de
  estoque) não saem de `LEFT JOIN`: saem das colunas cruas da própria linha,
  resolvidas em Python pelo retrato de `dimensoes_dw` — um lookup por linha;
- toda coluna que o contrato declara `DATE` sai como `date`, e não como o
  `datetime` com hora zero que o Oracle entrega — senão o CSV ganharia um
  `00:00:00` que o Postgres nunca escreveu, e os dois arquivos deixariam de bater;
- `pk_dw` é selecionado por `contrato.coluna_dw()`, que devolve
  `PK_FATO_VOL_*_CAT`. Selecionar `f.pk_dw` cru foi o `ORA-00904` que o
  transporte levou em produção em 04/set — e só no download, porque a Matriz e
  a planilha nunca selecionam a PK.
"""

import csv
import io
import logging

from backend.volumetria_catering import auditoria, conexao_dw, contrato, dimensoes_dw, recorte_dw
from backend.volumetria_catering.download import (
    BLOCO,
    BOM,
    DERIVADAS,
    TETO_CONFIRMACAO,
    TETO_XLSX,
    DownloadGrandeDemais,
    _para_csv,
    colunas,
    nome_do_arquivo,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BLOCO", "BOM", "DERIVADAS", "TETO_CONFIRMACAO", "TETO_XLSX",
    "DownloadGrandeDemais", "colunas", "nome_do_arquivo", "contar",
    "gerar_csv", "gerar_xlsx",
]


def _sql(filtros, dim):
    """Só as colunas do CONTRATO saem do SQL, cruas e na ordem dele. As
    derivadas são montadas em Python a partir delas."""
    movimento = filtros.movimento
    de_para_where, params = recorte_dw.de_para_where(filtros, dim=dim)
    selecoes = [
        f"{recorte_dw.coluna(nome, movimento)} AS {nome}"
        for nome, _tipo, _nulo in contrato.colunas(movimento)
    ]
    ordem = f"{recorte_dw.coluna('nk_calendario', movimento)}, " + ", ".join(
        recorte_dw.coluna(c, movimento) for c in contrato.CHAVE_NATURAL
    )
    return "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        f"ORDER BY {ordem}",
    )), params


def contar(cur, filtros, dim) -> int:
    de_para_where, params = recorte_dw.de_para_where(filtros, dim=dim)
    cur.execute(f"SELECT COUNT(*) {de_para_where}", params)
    return int(cur.fetchone()[0])


def _normalizadores(movimento):
    """Por coluna do contrato: a função que traz o valor do driver para o tipo
    que o contrato declara. Hoje só `DATE` precisa (datetime -> date)."""
    return [
        dimensoes_dw.como_date if tipo == "DATE" else None
        for _nome, tipo, _nulo in contrato.colunas(movimento)
    ]


def _linha_do_arquivo(bruta, indice, normalizadores, dim):
    """Da linha crua do DW para a linha do arquivo: derivadas primeiro (na
    ordem de `DERIVADAS`), depois o contrato inteiro, na ordem dele."""
    crua = [
        (norm(valor) if norm else valor) for valor, norm in zip(bruta, normalizadores)
    ]
    derivadas = [
        crua[indice["nk_calendario"]],
        dimensoes_dw.sigla_exibida(crua[indice["nk_wms_filial"]]),
        dim.rotulo_cliente(crua[indice["nk_cliente"]], crua[indice["raz_social"]]),
        dimensoes_dw.classificar(crua[indice["nome_estoque"]]),
    ]
    return derivadas + crua


def _preparar(filtros):
    """O que toda escrita de arquivo precisa antes da primeira linha."""
    movimento = filtros.movimento
    indice = {nome: i for i, (nome, _t, _n) in enumerate(contrato.colunas(movimento))}
    return colunas(movimento), indice, _normalizadores(movimento)


def gerar_csv(filtros, registro=None):
    """Gera o CSV linha a linha. **Dono da própria conexão** — ver docstring.

    `registro` é o id da auditoria: fechado com a contagem real de linhas, ou
    marcado como falha se o stream morrer no meio."""
    tampao = io.StringIO()
    escritor = csv.writer(tampao, delimiter=";", lineterminator="\r\n")

    def despejar():
        conteudo = tampao.getvalue()
        tampao.seek(0)
        tampao.truncate(0)
        return conteudo

    nomes, indice, normalizadores = _preparar(filtros)
    enviadas = 0
    conn = None
    try:
        conn = conexao_dw.conectar()
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            dim = dimensoes_dw.obter(cur)
            sql, params = _sql(filtros, dim)
            cur.execute(sql, params)
            escritor.writerow([rotulo for _a, _s, rotulo in nomes])
            yield BOM + despejar()
            for bruta in cur:
                linha = _linha_do_arquivo(bruta, indice, normalizadores, dim)
                escritor.writerow([_para_csv(v) for v in linha])
                enviadas += 1
                if enviadas % BLOCO == 0:
                    yield despejar()
            resto = despejar()
            if resto:
                yield resto
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("volumetria/DW: download csv concluído: %d linha(s)", enviadas)
    except GeneratorExit:
        # O cliente fechou a aba no meio: o Starlette descarta o gerador e isto
        # NÃO é `Exception`. "Interrompido" é o que a trilha precisa dizer.
        if registro is not None:
            auditoria.falhar(registro, f"interrompido pelo cliente apos {enviadas} linha(s)")
        raise
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()


def gerar_xlsx(filtros, registro=None) -> bytes:
    """xlsx com identificador como TEXTO. Recusa acima do teto — não streama."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    nomes, indice, normalizadores = _preparar(filtros)
    conn = None
    try:
        conn = conexao_dw.conectar()
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            dim = dimensoes_dw.obter(cur)
            total = contar(cur, filtros, dim)
            if total > TETO_XLSX:
                raise DownloadGrandeDemais(
                    f"{total:,} linhas passam do teto de {TETO_XLSX:,} do xlsx. "
                    "Baixe em CSV, que sai em streaming sem teto."
                    .replace(",", ".")
                )

            livro = Workbook(write_only=True)
            aba = livro.create_sheet("volumetria")
            aba.append([rotulo for _a, _s, rotulo in nomes])

            # as colunas que TÊM que sair como texto, para o zero à esquerda
            # sobreviver. A lista sai do contrato, não da memória de ninguém.
            como_texto = {
                i for i, (apelido, _s, _r) in enumerate(nomes)
                if apelido in contrato.IDENTIFICADORES_TEXTO
            }

            enviadas = 0
            sql, params = _sql(filtros, dim)
            cur.execute(sql, params)
            for bruta in cur:
                linha = _linha_do_arquivo(bruta, indice, normalizadores, dim)
                celulas = []
                for i, valor in enumerate(linha):
                    if i in como_texto:
                        celula = WriteOnlyCell(aba, value="" if valor is None else str(valor))
                        celula.number_format = "@"
                        celulas.append(celula)
                    else:
                        celulas.append(valor)
                aba.append(celulas)
                enviadas += 1

        fluxo = io.BytesIO()
        livro.save(fluxo)
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("volumetria/DW: download xlsx concluído: %d linha(s)", enviadas)
        return fluxo.getvalue()
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()
