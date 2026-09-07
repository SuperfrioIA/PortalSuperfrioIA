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
- **auditoria**: só admin — diz quem baixou o que;
- **diagnóstico do DW** (`/diagnostico-dw`): só admin — expõe o host do DW e
  repassa a mensagem crua do Oracle. Credencial nenhuma: ele diz o NOME das
  variáveis e se estão preenchidas, nunca os valores.

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

## Duas fontes ao mesmo tempo, escolhidas por uma chave

Desde o lote C1 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`, 06/set)
este arquivo fala com dois bancos: o `nuvem-db` (`conexao.py`) e o DW Oracle
(`conexao_dw.py`). Quem decide qual deles serve a tela é a chave
`VOLUMETRIA_CATERING_FONTE` (`fonte.py`), com padrão `postgres` — então nenhum
destes lotes muda o que a tela mostra até a Maria virar a chave no `.env` da VM.
Não é indecisão: é o que permite comparar as duas fontes em produção, com dado
real, antes de virar — e voltar em segundos se precisar. O C6 apaga o lado
Postgres e a chave.
"""

import logging
from contextlib import contextmanager
from decimal import Decimal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from backend.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_permissao,
    usuario_pode,
)
from backend.core.database import db
from backend.usuarios import service as usuarios_service
from backend.volumetria_catering import (
    auditoria,
    comparador,
    conexao,
    conexao_dw,
    contrato,
    dimensoes_dw,
    download,
    download_dw,
    fonte,
    matriz,
    matriz_dw,
    planilha,
    planilha_dw,
    recorte,
    schema,
    schema_dw,
    ticket as ticket_mod,
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


# ------------------------------------------------------------ a fonte ativa
def _usar_dw() -> bool:
    """A chave, lida a cada request. Valor inválido é 503 NOMEANDO a variável:
    cair no padrão em silêncio faria a Maria acreditar que virou."""
    try:
        return fonte.e_dw()
    except fonte.FonteInvalida as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))


def _erro_do_oracle(erro: BaseException) -> bool:
    """Se a exceção veio do driver do Oracle — sem importar o `oracledb` aqui
    (o import é preguiçoso de propósito, ver `conexao_dw._driver`). Erro de
    rede no meio de uma consulta é `oracledb.Error`, e neste card ele tem que
    virar 503, não 500."""
    return type(erro).__module__.split(".")[0] == "oracledb"


@contextmanager
def _cursor():
    """Cursor somente leitura na fonte ATIVA, com o contrato conferido.

    Indisponibilidade e drift viram 503 aqui — um lugar só, para as duas
    fontes. Quem chama não sabe (nem precisa saber) qual banco respondeu."""
    if _usar_dw():
        with _cursor_dw() as cur:
            yield cur
        return
    with _cursor_postgres() as cur:
        yield cur


@contextmanager
def _cursor_postgres():
    """O `nuvem-db`, via `conexao.py`. Morre no C6."""
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


@contextmanager
def _cursor_dw():
    """O DW Oracle, via `conexao_dw.py`. Mesmo desenho do transporte e do
    estoque: `preparar_cursor` antes de tudo, drift conferido a cada 10 min."""
    try:
        conn = conexao_dw.conectar()
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    try:
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            try:
                schema_dw.garantir(cur)
            except schema_dw.ContratoDivergenteDW as erro:
                logger.error("volumetria/DW: %s", erro)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)
                )
            yield cur
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    except Exception as erro:
        if not _erro_do_oracle(erro):
            raise
        logger.error("volumetria/DW: o DW falhou no meio da consulta: %s", type(erro).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"o DW falhou durante a consulta ({type(erro).__name__}). A "
                "volumetria de catering lê o DW direto; o resto do Hub continua "
                "funcionando."
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
def _opcoes_estaticas() -> dict:
    """A parte do `/opcoes` que não vem do dado: tetos, lentes, faixas e os
    movimentos da TELA. Uma cópia só, servida pelas duas fontes."""
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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    return {"de": abertura_de.isoformat(), "ate": hoje.isoformat()}


def _opcoes_dw() -> dict:
    """O `/opcoes` lido do DW: as listas vêm do retrato em cache
    (`dimensoes_dw.obter`, TTL de 1 h), e a procedência muda de significado —
    não existe carga, então "de quando é o dado" é o `MAX(DW_DATA_ALTERACAO)`
    da própria fonte, e "de quando são os rótulos" é a hora da varredura."""
    try:
        contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    # `_cursor_dw()` e não `_cursor()`: esta função é chamada também pelo
    # comparador, que quer o lado DW independentemente da chave.
    with _cursor_dw() as cur:
        dim = dimensoes_dw.obter(cur)

    # "Hoje" pelo relógio do processo no fuso de exibição — o DW é fonte de
    # dado, não de hora (mesma decisão do transporte e do estoque).
    hoje = dimensoes_dw.hoje_no_fuso()
    primeiro, ultimo = dim.periodo
    return {
        "fonte": fonte.DW,
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
        # Não há carga: a procedência é a da fonte. `cargas` fica vazia para a
        # tela antiga (que ainda lê essa chave) não quebrar até o C4 trocar o
        # que ela mostra.
        "cargas": [],
        "atualizado_ate": {
            m: (v.isoformat() if v else None) for m, v in dim.atualizado_em.items()
        },
        "rotulos_calculados_em": dim.calculado_em.isoformat(),
        "processo_dw": contrato.PROCESSO_DW,
        "contrato": contrato.ORIGEM,
    }


def _opcoes_postgres() -> dict:
    """O `/opcoes` lido do `nuvem-db`: cinco varreduras mais a procedência em
    `cat_cargas`. `_cursor_postgres()` explícito, pelo mesmo motivo do lado DW:
    o comparador chama os dois lados independentemente da chave. Morre no C6."""
    # Configuração inválida é 503 nomeando a variável, não 500 genérico: a
    # mensagem do `contrato.py` existe para chegar em quem escreveu o .env.
    try:
        fuso = contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    with _cursor_postgres() as cur:
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

    return {
        "fonte": fonte.POSTGRES,
        "unidades": unidades,
        "clientes": clientes,
        "operacoes": operacoes,
        "tipos_estoque": tipos,
        "periodo": {"de": periodo[0], "ate": periodo[1]},
        "abertura": _abertura(hoje),
        **_opcoes_estaticas(),
        "cargas": cargas,
        "contrato": contrato.ORIGEM,
    }


@router.get("/opcoes")
def opcoes(_: dict = Depends(require_ver)):
    """O que existe para filtrar — lido do dado, não de lista fixa.

    Unidade nova, cliente novo ou operação nova aparecem no filtro sozinhos.
    Traz também a procedência (última carga, ou o frescor do DW), o período que
    existe no dado, a abertura da tela e os tetos do download — do Python, para
    não existir uma segunda cópia deles no JavaScript. Da fonte ativa."""
    return _opcoes_dw() if _usar_dw() else _opcoes_postgres()


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
    """A Matriz do recorte — da fonte ativa. O formato da resposta é o mesmo
    nas duas, e é isso que o comparador confere."""
    filtros = _filtros(de, ate, movimento, lente, faixa, pagina,
                       unidade, cliente, tipo_estoque, operacao, dia)
    usar_dw = _usar_dw()
    with _cursor() as cur:
        if usar_dw:
            resultado = matriz_dw.matriz(cur, filtros, dimensoes_dw.obter(cur))
        else:
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
    usar_dw = _usar_dw()
    with _cursor() as cur:
        if usar_dw:
            resultado = planilha_dw.planilha(cur, filtros, dimensoes_dw.obter(cur))
        else:
            resultado = planilha.planilha(cur, filtros)
    return _json(resultado)


# ------------------------------------------------------------------ download
_SEM_EXPORTAR = (
    f"Requer a permissão de exportar da Volumetria de Catering ({EXPORTAR}). "
    "Consultar a Matriz e a planilha na tela não exige. Peça a um administrador "
    "para incluí-la em alguma das suas roles."
)


def _itens_do_recorte(request: Request):
    """Os parâmetros que o ticket assina: a query string menos o próprio ticket."""
    return [(k, v) for k, v in request.query_params.multi_items() if k != "ticket"]


def _usuario_do_ticket(ticket: str, request: Request) -> dict:
    """Quem pediu o download, provado pelo ticket em vez do header.

    A parte criptográfica é do `ticket.py`; aqui vem o que exige banco: o
    usuário ainda existe, o `token_version` dele não mudou (logout, troca de
    senha e revogação matam o ticket antes do minuto acabar) e a permissão
    `exportar` **continua** valendo — conferida agora, não só na emissão.
    """
    try:
        payload = ticket_mod.abrir(ticket, _itens_do_recorte(request))
    except ticket_mod.TicketInvalido as erro:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(erro)) from None

    with db() as session:
        user = usuarios_service.por_username(session, payload["sub"])
    if not user or user["token_version"] != payload.get("tver"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "a sessão que pediu este download não vale mais. Entre no portal "
                "de novo e clique em baixar."
            ),
        )
    if not usuario_pode(user, EXPORTAR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SEM_EXPORTAR)
    return user


def _quem_baixa(request: Request, ticket: str | None, user_bearer: dict | None) -> dict:
    """Duas portas para o mesmo download, e a mesma permissão nas duas.

    - **ticket**: o caminho da tela. Navegação não carrega `Authorization`, e é
      a navegação que faz o navegador salvar o arquivo (ver `ticket.py`);
    - **Bearer**: o caminho de quem chama a API direto — script, `curl`, teste.

    O Bearer continua valendo de propósito: sem ele, testar o download exigiria
    emitir ticket, e a API perderia um uso legítimo por causa de uma limitação
    do navegador.
    """
    if ticket:
        return _usuario_do_ticket(ticket, request)
    if not user_bearer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not usuario_pode(user_bearer, EXPORTAR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SEM_EXPORTAR)
    return user_bearer


@router.post("/download/ticket")
def api_download_ticket(
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
    """Autoriza UM download deste recorte, por um minuto.

    Existe porque o download navega e navegação não carrega header — o porquê
    inteiro está em `ticket.py`. A tela pede o ticket com o Bearer, e é **aqui**
    que os erros aparecem de forma legível: filtro inválido, visão conjunta e
    banco fora do ar viram JSON num `fetch`, e não uma página de JSON cru
    depois de o navegador ter começado a baixar.
    """
    if formato not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail=f"formato: {formato!r}")
    filtros = _filtros(de, ate, movimento, lente, faixa, 1,
                       unidade, cliente, tipo_estoque, operacao, dia)
    _um_movimento_por_vez(filtros, "O download")

    # Banco alcançável e contrato íntegro antes de a tela navegar: é o que faz o
    # 503 chegar como mensagem na tela em vez de página de erro do navegador.
    with _cursor():
        pass

    return {
        "ticket": ticket_mod.emitir(user, _itens_do_recorte(request)),
        "valido_por_segundos": ticket_mod.VALIDO_POR_SEGUNDOS,
    }


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
    ticket: str | None = Query(
        default=None,
        description="ticket de /download/ticket; alternativa ao header Authorization",
    ),
    user_bearer: dict | None = Depends(get_current_user_optional),
):
    """O recorte inteiro, em CSV (streaming) ou xlsx (sob teto).

    **Sempre no recorte dos filtros da tela**: os mesmos parâmetros da Matriz e
    da planilha, e a auditoria registra exatamente qual recorte saiu. `pagina`
    não entra de propósito — download de uma página só não é download do
    recorte.

    Autentica por **ticket** (a tela) ou por **Bearer** (API direta), com a
    mesma exigência de `exportar` nas duas portas — ver `_quem_baixa`.
    """
    user = _quem_baixa(request, ticket, user_bearer)
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

    # O gerador do arquivo é da fonte ativa. Os dois módulos têm a MESMA
    # superfície (`gerar_csv`, `gerar_xlsx`, `nome_do_arquivo`,
    # `DownloadGrandeDemais`), e o arquivo que sai tem que ser igual.
    gerador = download_dw if _usar_dw() else download

    nome = gerador.nome_do_arquivo(filtros, formato)
    cabecalhos = {"Content-Disposition": f'attachment; filename="{nome}"'}

    if formato == "csv":
        # o gerador é dono da conexão: o corpo dele roda DEPOIS de a resposta
        # começar, quando um `with` daqui já teria fechado tudo
        return StreamingResponse(
            gerador.gerar_csv(filtros, registro),
            media_type="text/csv; charset=utf-8",
            headers=cabecalhos,
        )

    try:
        conteudo = gerador.gerar_xlsx(filtros, registro)
    except download.DownloadGrandeDemais as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None
    except (conexao.VolumetriaIndisponivel, conexao_dw.DWIndisponivel) as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    except psycopg.OperationalError as erro:
        # banco caiu no meio do xlsx: a auditoria já marcou `erro`; aqui é só
        # o status HTTP honesto (o CSV, em streaming, não tem mais como avisar)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"o banco da volumetria falhou durante o download ({type(erro).__name__}).",
        )
    except Exception as erro:
        if not _erro_do_oracle(erro):
            raise
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"o DW falhou durante o download ({type(erro).__name__}).",
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


# --------------------------------------------------------- diagnóstico do DW
def _fonte_declarada() -> str:
    """A fonte que a tela usa agora, para o diagnóstico dizer. Valor inválido
    vira texto, não 503: o diagnóstico existe para RELATAR, e uma chave escrita
    errada é justamente o que se quer ver escrito aqui."""
    try:
        return fonte.ativa()
    except fonte.FonteInvalida as erro:
        return f"inválida — {erro}"


@router.get("/diagnostico-dw")
def api_diagnostico_dw(_: dict = Depends(require_admin)):
    """Conectei no DW, vi as duas tabelas, o contrato bate? E qual fonte a tela
    está usando agora?

    É o aceite do lote C1 de `docs/PLANO_VOLUMETRIA_DW_DIRETO.md`: a IA não
    conecta no DW, então a única prova possível é a Maria abrir isto na VM.
    Nada da tela passa por aqui — os endpoints de consulta seguem a chave
    `VOLUMETRIA_CATERING_FONTE`, que este endpoint apenas relata.

    **Não lê dado.** As duas conferências são o `SELECT` do contrato com
    `WHERE 1=0` (compila e resolve privilégio sem ler bloco) e o
    `ALL_TAB_COLUMNS`. Custo de catálogo, não de varredura.

    **Divergência de contrato não é 503 aqui**, ao contrário do `_cursor()`: o
    trabalho deste endpoint é RELATAR a divergência, e um 503 esconderia
    justamente a lista que se veio buscar. 503 fica para o que impede o
    diagnóstico de existir — credencial ausente e sessão que não abre.

    **Só admin**, por dois motivos: ele nomeia host e usuário do DW (não a
    senha, nunca), e repassa a mensagem crua do Oracle, que é o que faz o
    diagnóstico valer e não é leitura de todo mundo.
    """
    em_cache = dimensoes_dw.em_cache()
    resposta = {
        "fonte_da_tela": _fonte_declarada(),
        "dsn": conexao_dw.dsn(),
        "credencial": {
            "usuario": conexao_dw.ENV_USUARIO,
            "senha": conexao_dw.ENV_SENHA,
            "configurada": conexao_dw.configurado(),
        },
        "contrato": contrato.ORIGEM,
        # O retrato das dimensões que está servindo a tela agora, sem tocar no
        # DW para isso. `None` = ainda não houve varredura neste processo.
        "dimensoes_em_cache": em_cache.como_dict() if em_cache else None,
        "conectou": False,
        "movimentos": [],
        "ok": False,
    }

    # Nome de objeto inválido é 503 NOMEANDO a variável, não 500 genérico — e
    # conferido ANTES de abrir sessão: erro de `.env` não precisa de round trip
    # no DW para ser diagnosticado.
    try:
        for movimento in contrato.MOVIMENTOS:
            contrato.tabela(movimento)
    except contrato.TabelaInvalida as erro:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)
        ) from None

    try:
        conn = conexao_dw.conectar()
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)
        ) from None

    try:
        resposta["conectou"] = True
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            # `conferir` e não `verificar`: o primeiro movimento com problema
            # não pode esconder o segundo. Quem abre isto quer os dois.
            resposta["movimentos"] = [
                schema_dw.conferir(cur, movimento) for movimento in contrato.MOVIMENTOS
            ]
    finally:
        conn.close()

    resposta["ok"] = not any(m["problemas"] for m in resposta["movimentos"])
    if not resposta["ok"]:
        logger.error(
            "volumetria/DW: diagnóstico reprovou — %s",
            "; ".join(p for m in resposta["movimentos"] for p in m["problemas"]),
        )
    return resposta


# ------------------------------------------------- as dimensões (só admin)
@router.get("/dimensoes")
def api_dimensoes(_: dict = Depends(require_admin)):
    """O retrato das dimensões em cache — sigla, tipos, clientes canonizados,
    período, frescor — SEM tocar no DW. Vazio se ainda não houve varredura
    neste processo. Só admin: nomeia cliente."""
    dim = dimensoes_dw.em_cache()
    return {"em_cache": dim is not None, "dimensoes": dim.como_dict() if dim else None}


@router.post("/dimensoes/atualizar")
def api_dimensoes_atualizar(_: dict = Depends(require_admin)):
    """"Atualizar agora": varre o DW e substitui o cache, sem esperar o TTL de
    1 h. É o botão que o plano previa para não depender de job para testar —
    e o que a Maria aperta no dia da virada depois de conferir o diagnóstico.

    Lê o DW independentemente da chave de fonte: o cache é do lado Oracle, e
    aquecê-lo ANTES de virar a chave é justamente o uso."""
    with _cursor_dw() as cur:
        dim = dimensoes_dw.atualizar(cur)
    logger.info("volumetria/DW: dimensões atualizadas por admin — %s", dim.como_dict())
    return dim.como_dict()


# --------------------------------------------- o comparador (só admin, C3)
def _lado(nome: str, buscar) -> dict:
    """Roda `buscar()` numa fonte e devolve `{fonte, ok, ms, resultado, erro}`.

    Erro de UMA fonte não derruba o endpoint: o trabalho dele é RELATAR —
    inclusive "o Postgres não respondeu e o DW sim", que é informação. Só o
    503 do `_cursor_*` é capturado; bug de código continua sendo 500, porque
    esconder isso atrás de "não bateu" seria pior que o bug."""
    try:
        resultado, ms = comparador.cronometrar(buscar)
    except HTTPException as erro:
        return {"fonte": nome, "ok": False, "ms": None, "resultado": None, "erro": erro.detail}
    return {"fonte": nome, "ok": True, "ms": ms, "resultado": resultado, "erro": None}


def _matriz_postgres(filtros):
    with _cursor_postgres() as cur:
        return matriz.matriz(cur, filtros)


def _matriz_dw(filtros):
    with _cursor_dw() as cur:
        return matriz_dw.matriz(cur, filtros, dimensoes_dw.obter(cur))


@router.get("/comparar/matriz")
def api_comparar_matriz(
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
    _: dict = Depends(require_admin),
):
    """A MESMA Matriz nas duas fontes, lado a lado, célula a célula — o portão
    da virada (C3 de `docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

    Lê o Postgres E o DW **independentemente da chave de fonte**: é para ser
    rodado em produção, com dado real, antes de virar a chave — e depois, se
    um número parecer estranho, enquanto o `nuvem-db` estiver de pé. Devolve
    as duas Matrizes inteiras (para olhar), o tempo de cada uma (o número que o
    D0 pediu, agora medido com a consulta de verdade) e a comparação de
    `comparador.py`. Número diferente é bug de tradução do SQL; rótulo
    diferente é a camada de decisões — e os dois saem separados.

    Só admin: é diagnóstico, dobra o custo de uma consulta, e nomeia cliente.
    """
    filtros = _filtros(de, ate, movimento, lente, faixa, pagina,
                       unidade, cliente, tipo_estoque, operacao, dia)
    postgres = _lado(fonte.POSTGRES, lambda: _matriz_postgres(filtros))
    dw = _lado(fonte.DW, lambda: _matriz_dw(filtros))
    comparacao = None
    if postgres["ok"] and dw["ok"]:
        comparacao = comparador.comparar_matriz(postgres["resultado"], dw["resultado"])
        logger.info(
            "volumetria/comparador: matriz %s — bate=%s, %d diferença(s), "
            "postgres %s ms, dw %s ms",
            filtros.como_dict(), comparacao["bate"], len(comparacao["diferencas"]),
            postgres["ms"], dw["ms"],
        )
    return _json({
        "filtros": filtros.como_dict(),
        "fonte_da_tela": _fonte_declarada(),
        "postgres": postgres,
        "dw": dw,
        "comparacao": comparacao,
    })


@router.get("/comparar/opcoes")
def api_comparar_opcoes(_: dict = Depends(require_admin)):
    """O `/opcoes` nas duas fontes: unidades exibidas, clientes com rótulo,
    tipos, operações e período. É a prova direta da CAMADA DE DECISÕES (sigla,
    tipo, razão social canonizada), que a Matriz só prova por tabela. Custa a
    varredura completa nas duas fontes — só admin, e só quando se quer saber."""
    postgres = _lado(fonte.POSTGRES, _opcoes_postgres)
    dw = _lado(fonte.DW, _opcoes_dw)
    comparacao = None
    if postgres["ok"] and dw["ok"]:
        comparacao = comparador.comparar_opcoes(postgres["resultado"], dw["resultado"])
        logger.info(
            "volumetria/comparador: opcoes — bate=%s, postgres %s ms, dw %s ms",
            comparacao["bate"], postgres["ms"], dw["ms"],
        )
    return _json({
        "fonte_da_tela": _fonte_declarada(),
        "postgres": postgres,
        "dw": dw,
        "comparacao": comparacao,
    })
