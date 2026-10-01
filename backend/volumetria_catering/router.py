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

Credencial do DW ausente, DW fora do ar ou contrato divergente do schema viram
**503 com a causa** — e nada mais no Hub sente. O startup não toca aqui.

## Comportamentos da V3 preservados

- **Decimal vira string no JSON** (`_json`): peso e valor não passam pelo float
  do JavaScript. Valor cru na API; formatação é trabalho da tela;
- filtro inválido é **400**, não 500 (`_filtros`);
- `pagina` **não entra** no download;
- `entrada + saída` é **só da Matriz**: planilha e download recusam com 400;
- a tela mostra a **procedência**: até quando o DW atualizou cada tabela
  (`MAX(DW_DATA_ALTERACAO)`).

## Uma fonte só: o DW Oracle

O módulo lê o DW direto (`conexao_dw.py`), sem cópia intermediária. Até o lote C6
do plano (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`) existiu também o `nuvem-db`,
escolhido por uma chave de fonte; a virada foi em 07/set/2026 e o C6 apagou o
lado Postgres, a chave e o comparador.
"""

import logging
from contextlib import contextmanager
from decimal import Decimal

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
    conexao_dw,
    contrato,
    dimensoes_dw,
    download,
    download_dw,
    matriz_dw,
    planilha_dw,
    recorte,
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


def _erro_do_oracle(erro: BaseException) -> bool:
    """Se a exceção veio do driver do Oracle — sem importar o `oracledb` aqui
    (o import é preguiçoso de propósito, ver `conexao_dw._driver`). Erro de
    rede no meio de uma consulta é `oracledb.Error`, e neste card ele tem que
    virar 503, não 500."""
    return type(erro).__module__.split(".")[0] == "oracledb"


@contextmanager
def _cursor():
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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    return {"de": abertura_de.isoformat(), "ate": hoje.isoformat()}


def _opcoes_dw() -> dict:
    """O `/opcoes` lido do DW: as listas vêm do retrato em cache
    (`dimensoes_dw.obter`, TTL de 1 h), e a procedência é o
    `MAX(DW_DATA_ALTERACAO)` da própria fonte — "de quando são os rótulos" é a
    hora da varredura."""
    try:
        contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    with _cursor() as cur:
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


@router.get("/opcoes")
def opcoes(_: dict = Depends(require_ver)):
    """O que existe para filtrar — lido do dado, não de lista fixa.

    Unidade nova, cliente novo ou operação nova aparecem no filtro sozinhos.
    Traz também a procedência (o frescor do DW), o período que existe no dado,
    a abertura da tela e os tetos do download — do Python, para não existir uma
    segunda cópia deles no JavaScript."""
    return _opcoes_dw()


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
    """A Matriz do recorte, lida do DW."""
    filtros = _filtros(de, ate, movimento, lente, faixa, pagina,
                       unidade, cliente, tipo_estoque, operacao, dia)
    with _cursor() as cur:
        resultado = matriz_dw.matriz(cur, filtros, dimensoes_dw.obter(cur))
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
        resultado = planilha_dw.planilha(cur, filtros, dimensoes_dw.obter(cur))
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

    nome = download_dw.nome_do_arquivo(filtros, formato)
    cabecalhos = {"Content-Disposition": f'attachment; filename="{nome}"'}

    if formato == "csv":
        # o gerador é dono da conexão: o corpo dele roda DEPOIS de a resposta
        # começar, quando um `with` daqui já teria fechado tudo
        return StreamingResponse(
            download_dw.gerar_csv(filtros, registro),
            media_type="text/csv; charset=utf-8",
            headers=cabecalhos,
        )

    try:
        conteudo = download_dw.gerar_xlsx(filtros, registro)
    except download.DownloadGrandeDemais as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    except Exception as erro:
        # DW caiu no meio do xlsx: a auditoria já marcou `erro`; aqui é só o
        # status HTTP honesto (o CSV, em streaming, não tem mais como avisar)
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
@router.get("/diagnostico-dw")
def api_diagnostico_dw(_: dict = Depends(require_admin)):
    """Conectei no DW, vi as duas tabelas, o contrato bate?

    É o aceite do lote C1 de `docs/PLANO_VOLUMETRIA_DW_DIRETO.md`: a IA não
    conecta no DW, então a única prova possível é a Maria abrir isto na VM.
    Nada da tela passa por aqui.

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
    1 h. É o botão para não depender do TTL depois de uma mudança no DW."""
    with _cursor() as cur:
        dim = dimensoes_dw.atualizar(cur)
    logger.info("volumetria/DW: dimensões atualizadas por admin — %s", dim.como_dict())
    return dim.como_dict()
