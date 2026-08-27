"""Endpoints de consulta da volumetria de catering.

Porte dos endpoints de consulta de `catering/app.py` da nuvem-ia (main,
27/ago/2026) para dentro do Hub. O que NÃO veio: login/logout/sessão (o Hub já
resolve), administração de usuários (`cat_usuarios` aposenta no H4), páginas
HTML (a tela é o H2, em `frontend/volumetria-catering/`) e `/health` (o do Hub
não depende deste banco, de propósito).

## Guardas

- **consulta** (`/opcoes`, `/matriz`, `/planilha`): login + `ver` do app
  (`volumetria-catering:ver`, a coluna Ver da matriz de acesso). Diferente dos
  painéis estáticos do Hub, aqui o dado é de negócio (cliente, peso, valor) e
  não sai sem identidade;
- **download**: `volumetria-catering:exportar` — a célula da matriz que foi um
  dos motivos de trazer a tela para o Hub (na V3 qualquer logado baixava);
- **auditoria**: só admin — diz quem baixou o que.

Admin passa por cima de tudo (regra do `usuario_pode`); nada de `if is_admin`.

## Falha graciosa, só neste card

`VOLUMETRIA_DB_URL` ausente, banco fora do ar ou contrato divergente do schema
viram **503 com a causa** — e nada mais no Hub sente. O startup não toca aqui.

## Comportamentos da V3 preservados

- **Decimal vira string no JSON** (`_json`): peso e valor não passam pelo float
  do JavaScript. Valor cru na API; formatação é trabalho da tela;
- filtro inválido é **400**, não 500 (`_filtros`);
- `pagina` **não entra** no download;
- `entrada + saída` é **só da Matriz**: planilha e download recusam com 400;
- a tela mostra a **procedência** (última carga) lendo `cat_cargas`.
"""

import logging
from contextlib import contextmanager
from decimal import Decimal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.auth.dependencies import (
    get_current_user,
    require_admin,
    require_permissao,
    usuario_pode,
)
from backend.volumetria_catering import (
    auditoria,
    conexao,
    contrato,
    download,
    matriz,
    planilha,
    recorte,
    schema,
)
from backend.volumetria_catering.permissoes import APP_SLUG, EXPORTAR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/volumetria-catering", tags=["volumetria-catering"])

VER = f"{APP_SLUG}:ver"


def require_ver(user: dict = Depends(get_current_user)) -> dict:
    """Login + a coluna Ver do app. `ver` não mora no catálogo de ações (é
    implícita, em `role_apps`), então não passa por `require_permissao` — mas
    `usuario_pode` resolve `<app>:ver` e aplica o bypass de admin."""
    if not usuario_pode(user, VER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Requer acesso ao app Volumetria de Catering (coluna Ver da matriz "
                f"de acesso, {VER}). Peça a um administrador para incluí-lo em "
                "alguma das suas roles."
            ),
        )
    return user


# ------------------------------------------------------------ banco externo
@contextmanager
def _cursor():
    """Cursor somente leitura no banco da nuvem-ia, com o contrato conferido.

    Indisponibilidade e drift viram 503 aqui — um lugar só."""
    try:
        conn = conexao.conectar()
    except conexao.VolumetriaIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    try:
        with conn.cursor() as cur:
            try:
                schema.garantir(cur)
            except schema.ContratoDivergente as erro:
                logger.error("volumetria: %s", erro)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)
                )
            yield cur
    except psycopg.OperationalError as erro:
        logger.error("volumetria: banco falhou no meio da consulta: %s", type(erro).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "o banco da volumetria de catering falhou durante a consulta "
                f"({type(erro).__name__}). O resto do Hub continua funcionando."
            ),
        )
    finally:
        conn.close()


def _filtros(de, ate, movimento, lente, faixa, pagina,
             unidade, cliente, tipo_estoque, operacao, dia=()):
    """Monta e valida o recorte. Um lugar só para os três endpoints.

    Filtro inválido é **400**, não 500. `dia` entra como texto de propósito:
    com `int` o FastAPI recusaria antes com 422 e o recorte passaria a ter duas
    linguagens de erro. `recorte.dias_do_filtro()` converte e recusa em 400."""
    filtros = recorte.Filtros(
        de=de, ate=ate, movimento=movimento, lente=lente, faixa=faixa,
        pagina=pagina, unidades=tuple(unidade), clientes=tuple(cliente),
        tipos_estoque=tuple(tipo_estoque), operacoes=tuple(operacao),
        dias=tuple(dia),
    )
    try:
        return filtros.validar()
    except recorte.FiltroInvalido as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None


def _um_movimento_por_vez(filtros, o_que):
    """Recusa `Entrada + saída` onde a visão conjunta não se aplica.

    A Matriz AGREGA e pode somar os dois movimentos. A planilha mostra linha
    crua e o download leva a linha inteira — as tabelas têm 36 e 46 colunas.
    **400 e não 500**, e a mensagem diz o que fazer."""
    if filtros.movimento != recorte.CONJUNTA:
        return
    raise HTTPException(
        status_code=400,
        detail=(
            f"{o_que} responde por um movimento por vez: as duas tabelas do DW "
            "têm colunas diferentes (36 e 46), então não existe linha crua "
            "'entrada + saída'. Escolha Entrada ou Saída. A visão conjunta "
            "existe na Matriz, que agrega."
        ),
    )


def _json(valor):
    """Decimal -> string; o resto passa. A tela formata."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


def _ip(request: Request):
    """IP do cliente, ou `None` — não se inventa `"desconhecido"` na auditoria.
    Atrás do ALB o uvicorn já traduz o X-Forwarded-For (ver Dockerfile)."""
    return request.client.host if request.client else None


# ------------------------------------------------------------------ opções
@router.get("/opcoes")
def opcoes(_: dict = Depends(require_ver)):
    """O que existe para filtrar — lido do dado, não de lista fixa.

    Unidade nova, cliente novo ou operação nova aparecem no filtro sozinhos.
    Traz também a procedência (últimas cargas), o período que existe no dado, a
    abertura da tela e os tetos do download — do Python, para não existir uma
    segunda cópia deles no JavaScript."""
    # Configuração inválida é 503 nomeando a variável, não 500 genérico: a
    # mensagem do `contrato.py` existe para chegar em quem escreveu o .env.
    try:
        fuso = contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    with _cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT COALESCE(u.sigla, f.nk_wms_filial)
            FROM (SELECT nk_wms_filial FROM cat_fato_recebimento
                  UNION SELECT nk_wms_filial FROM cat_fato_expedicao) f
            LEFT JOIN cat_unidades u ON u.sigla_fonte = f.nk_wms_filial
            ORDER BY 1
            """
        )
        unidades = [linha[0] for linha in cur.fetchall()]

        cur.execute(
            """
            SELECT f.nk_cliente, COALESCE(c.razao_social, f.nk_cliente)
            FROM (SELECT DISTINCT nk_cliente FROM cat_fato_recebimento
                  UNION SELECT DISTINCT nk_cliente FROM cat_fato_expedicao) f
            LEFT JOIN cat_clientes c ON c.raiz_cnpj = f.nk_cliente
            ORDER BY 2
            """
        )
        clientes = [{"chave": k, "rotulo": r} for k, r in cur.fetchall()]

        cur.execute(
            """
            SELECT DISTINCT descr_oper_wms, movimento FROM (
                SELECT descr_oper_wms, 'rec' AS movimento FROM cat_fato_recebimento
                UNION SELECT descr_oper_wms, 'exp' FROM cat_fato_expedicao
            ) t ORDER BY 1
            """
        )
        operacoes = {"rec": [], "exp": []}
        for nome, movimento in cur.fetchall():
            operacoes[movimento].append(nome)

        cur.execute("SELECT DISTINCT tipo FROM cat_tipos_estoque ORDER BY 1")
        tipos = [linha[0] for linha in cur.fetchall()]

        # O período que EXISTE no dado: a dica de alcance ("o dado vai de X a
        # Y"), para quem não sabe que 2023 está no banco poder filtrar para trás.
        cur.execute(
            """
            SELECT to_char(min(nk_calendario), 'YYYY-MM-DD'),
                   to_char(max(nk_calendario), 'YYYY-MM-DD')
            FROM (SELECT nk_calendario FROM cat_fato_recebimento
                  UNION ALL SELECT nk_calendario FROM cat_fato_expedicao) t
            """
        )
        periodo = cur.fetchone()

        # "Hoje" vem do POSTGRES, no fuso de exibição, e não do relógio do
        # processo: o container roda em UTC, e as 21h de Brasília já são o dia
        # seguinte lá. O fuso entra por BIND, nunca concatenado.
        cur.execute("SELECT (now() AT TIME ZONE %s)::date", (fuso,))
        hoje = cur.fetchone()[0]

        # Procedência: de quando é o dado que a tela está mostrando. O Hub
        # enxerga se a carga falhou sem ser quem a roda.
        cur.execute(
            """
            SELECT tabela_origem, fonte,
                   to_char(terminada_em AT TIME ZONE %s, 'DD/MM/YYYY HH24:MI'),
                   linhas_lidas
            FROM cat_cargas WHERE status = 'ok'
            ORDER BY id DESC LIMIT 2
            """,
            (fuso,),
        )
        cargas = [
            {"tabela": t, "fonte": f, "quando": q, "linhas": n}
            for t, f, q, n in cur.fetchall()
        ]

    # A abertura da tela: janeiro do ano corrente até hoje (configurável). A
    # única trava é a da inversão, para uma abertura pinada no futuro não abrir
    # a tela com "período invertido".
    try:
        abertura_de = min(contrato.abertura_de(hoje), hoje)
    except contrato.AberturaInvalida as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    return {
        "unidades": unidades,
        "clientes": clientes,
        "operacoes": operacoes,
        "tipos_estoque": tipos,
        "periodo": {"de": periodo[0], "ate": periodo[1]},
        "abertura": {"de": abertura_de.isoformat(), "ate": hoje.isoformat()},
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
        "cargas": cargas,
        "contrato": contrato.ORIGEM,
    }


# ------------------------------------------------------------------ consulta
@router.get("/matriz")
def api_matriz(
    de: str = Query(..., description="primeiro dia, AAAA-MM-DD"),
    ate: str = Query(..., description="último dia, AAAA-MM-DD (inclusivo)"),
    movimento: str = Query("rec"),
    lente: str = Query("liq"),
    faixa: str = Query("solicitado"),
    pagina: int = Query(1, ge=1),
    unidade: list[str] = Query(default=[]),
    cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]),
    operacao: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[], description="dia do MÊS, 1..31"),
    _: dict = Depends(require_ver),
):
    """A Matriz do recorte."""
    filtros = _filtros(de, ate, movimento, lente, faixa, pagina,
                       unidade, cliente, tipo_estoque, operacao, dia)
    with _cursor() as cur:
        resultado = matriz.matriz(cur, filtros)
    return _json(resultado)


@router.get("/planilha")
def api_planilha(
    de: str = Query(..., description="primeiro dia, AAAA-MM-DD"),
    ate: str = Query(..., description="último dia, AAAA-MM-DD (inclusivo)"),
    movimento: str = Query("rec"),
    lente: str = Query("liq"),
    faixa: str = Query("solicitado"),
    pagina: int = Query(1, ge=1),
    unidade: list[str] = Query(default=[]),
    cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]),
    operacao: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[], description="dia do MÊS, 1..31"),
    _: dict = Depends(require_ver),
):
    """Linhas cruas do recorte, 100 por página, paginadas no servidor."""
    filtros = _filtros(de, ate, movimento, lente, faixa, pagina,
                       unidade, cliente, tipo_estoque, operacao, dia)
    _um_movimento_por_vez(filtros, "A planilha")
    with _cursor() as cur:
        resultado = planilha.planilha(cur, filtros)
    return _json(resultado)


# ------------------------------------------------------------------ download
@router.get("/download")
def api_download(
    request: Request,
    de: str = Query(..., description="primeiro dia, AAAA-MM-DD"),
    ate: str = Query(..., description="último dia, AAAA-MM-DD (inclusivo)"),
    formato: str = Query("csv"),
    movimento: str = Query("rec"),
    lente: str = Query("liq"),
    faixa: str = Query("solicitado"),
    unidade: list[str] = Query(default=[]),
    cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]),
    operacao: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[], description="dia do MÊS, 1..31"),
    user: dict = Depends(require_permissao(EXPORTAR)),
):
    """O recorte inteiro, em CSV (streaming) ou xlsx (sob teto).

    **Sempre no recorte dos filtros da tela**: os mesmos parâmetros da Matriz e
    da planilha, e a auditoria registra exatamente qual recorte saiu. `pagina`
    não entra de propósito — download de uma página só não é download do
    recorte.
    """
    if formato not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail=f"formato: {formato!r}")
    filtros = _filtros(de, ate, movimento, lente, faixa, 1,
                       unidade, cliente, tipo_estoque, operacao, dia)
    # ANTES de abrir a auditoria: registro de download que não saiu é ruído na
    # trilha, e ela é usada para responder quem baixou o que.
    _um_movimento_por_vez(filtros, "O download")

    # Banco alcançável e contrato íntegro ANTES de a resposta começar: depois
    # que o stream abre, um erro não vira mais HTTP — vira só linha de auditoria
    # com status 'erro'. Conferir agora é o que deixa o 503 chegar à tela.
    with _cursor():
        pass

    registro = auditoria.abrir(
        recorte=filtros.como_dict(), formato=formato,
        ip=_ip(request), usuario=user.get("username"),
    )

    nome = download.nome_do_arquivo(filtros, formato)
    cabecalhos = {"Content-Disposition": f'attachment; filename="{nome}"'}

    if formato == "csv":
        # o gerador é dono da conexão: o corpo dele roda DEPOIS de a resposta
        # começar, quando um `with` daqui já teria fechado tudo
        return StreamingResponse(
            download.gerar_csv(filtros, registro),
            media_type="text/csv; charset=utf-8",
            headers=cabecalhos,
        )

    try:
        conteudo = download.gerar_xlsx(filtros, registro)
    except download.DownloadGrandeDemais as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None
    except conexao.VolumetriaIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    except psycopg.OperationalError as erro:
        # banco caiu no meio do xlsx: a auditoria já marcou `erro`; aqui é só
        # o status HTTP honesto (o CSV, em streaming, não tem mais como avisar)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"o banco da volumetria falhou durante o download ({type(erro).__name__}).",
        )
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=cabecalhos,
    )


# ----------------------------------------------------------------- auditoria
@router.get("/auditoria")
def api_auditoria(
    limite: int = Query(100, ge=1, le=1000),
    _: dict = Depends(require_admin),
):
    """As últimas tentativas de download, do banco do Hub. Restrita a admin: a
    tabela diz quem baixou o que, e isso não é leitura de todo mundo."""
    return auditoria.listar(limite)
