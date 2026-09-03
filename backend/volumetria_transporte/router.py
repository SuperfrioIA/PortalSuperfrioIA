"""Endpoints de consulta da volumetria de transporte de catering.

Padrão de `backend/volumetria_catering/router.py`, adaptado: uma tabela só
(sem `movimento`, sem visão conjunta, sem faixa), e a fonte é o DW Oracle
direto — não há "banco fora do ar por enquanto ainda serve Postgres" como no
catering hoje (ele troca isso no D3; este módulo já nasce lendo o DW).

## Guardas

- **consulta** (`/opcoes`, `/matriz`, `/planilha`): login + `ver`
  (`volumetria-transporte:ver`);
- **download**: `volumetria-transporte:exportar`;
- **auditoria**, **diagnóstico**: só admin.

## Falha graciosa

DW fora do ar, credencial ausente ou contrato divergente viram 503 com a
causa — só este card. O startup do Hub não depende disto.
"""

import logging
import threading
import time
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
from backend.volumetria_transporte import (
    auditoria,
    conexao_dw,
    contrato,
    download,
    matriz,
    planilha,
    recorte,
    schema_dw,
    ticket as ticket_mod,
)
from backend.volumetria_transporte.permissoes import APP_SLUG, EXPORTAR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/volumetria-transporte", tags=["volumetria-transporte"])

VER = f"{APP_SLUG}:ver"


def require_ver(user: dict = Depends(get_current_user)) -> dict:
    if not usuario_pode(user, VER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Requer acesso ao app Volumetria de Transporte (coluna Ver da "
                f"matriz de acesso, {VER}). Peça a um administrador para incluí-lo "
                "em alguma das suas roles."
            ),
        )
    return user


@contextmanager
def _cursor():
    """Cursor somente leitura no DW, com o contrato conferido. Indisponibilidade
    e drift viram 503 aqui — um lugar só."""
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
                logger.error("volumetria-transporte: %s", erro)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)
                )
            yield cur
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    finally:
        conn.close()


def _filtros(de, ate, lente, pagina, unidade, cliente, tipo_estoque,
             tipo_viagem, tipo_movimento, status_viagem, status_wms, status_baixa, dia=()):
    filtros = recorte.Filtros(
        de=de, ate=ate, lente=lente, pagina=pagina,
        unidades=tuple(unidade), clientes=tuple(cliente),
        tipos_estoque=tuple(tipo_estoque), tipos_viagem=tuple(tipo_viagem),
        tipos_movimento=tuple(tipo_movimento), status_viagem=tuple(status_viagem),
        status_wms=tuple(status_wms), status_baixa=tuple(status_baixa), dias=tuple(dia),
    )
    try:
        return filtros.validar()
    except recorte.FiltroInvalido as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None


def _json(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_json(v) for v in valor]
    return valor


def _ip(request: Request):
    return request.client.host if request.client else None


# ------------------------------------------------------------------ opções

# `/opcoes` varre a tabela inteira sem filtro de data (precisa saber todo
# cliente/unidade que já existiu, não só do recorte aberto na tela) — medido
# em 03/set/2026: ~9,4s por chamada, 9 SELECT DISTINCT/MIN/MAX contra uma
# tabela granular (linha por movimento). Combinado com a Duda no mesmo dia:
# cliente/unidade novo é raro (~1x/6 meses); só o "atualizado até" muda todo
# dia, e mesmo assim 1h de atraso é aceitável. TTL alto de propósito.
_CACHE_OPCOES_TTL_SEGUNDOS = 60 * 60
_cache_opcoes_lock = threading.Lock()
_cache_opcoes: dict = {"expira_em": 0.0, "dados": None}


def _opcoes_do_dw() -> dict:
    """Varredura pesada do `/opcoes`, com cache de processo (ver TTL acima)."""
    agora = time.monotonic()
    with _cache_opcoes_lock:
        if _cache_opcoes["dados"] is not None and agora < _cache_opcoes["expira_em"]:
            return _cache_opcoes["dados"]

    with _cursor() as cur:
        listas = {}
        for chave, coluna in (
            ("unidades", "nk_wms_filial"),
            ("tipos_estoque", "nome_estoque"),
            ("tipos_viagem", "tipo_viagem"),
            ("tipos_movimento", "tipo_movimento"),
            ("status_viagem", "status_viagem"),
            ("status_wms", "status_wms"),
            ("status_baixa", "status_baixa"),
        ):
            cur.execute(f"SELECT DISTINCT {coluna} FROM {contrato.tabela()} ORDER BY 1")
            listas[chave] = [linha[0] for linha in cur.fetchall()]

        cur.execute(
            f"SELECT DISTINCT nk_cliente, raz_social FROM {contrato.tabela()} ORDER BY 2"
        )
        clientes = [{"chave": k, "rotulo": r} for k, r in cur.fetchall()]

        cur.execute(
            f"SELECT MIN(nk_calendario), MAX(nk_calendario), MAX(dw_data_alteracao) "
            f"FROM {contrato.tabela()}"
        )
        de_min, ate_max, alterado_em = cur.fetchone()

    dados = {
        "listas": listas,
        "clientes": clientes,
        "de_min": de_min,
        "ate_max": ate_max,
        "alterado_em": alterado_em,
    }
    with _cache_opcoes_lock:
        _cache_opcoes["dados"] = dados
        _cache_opcoes["expira_em"] = agora + _CACHE_OPCOES_TTL_SEGUNDOS
    return dados


@router.get("/opcoes")
def opcoes(_: dict = Depends(require_ver)):
    """O que existe para filtrar, lido do dado — e não de lista fixa."""
    try:
        fuso = contrato.fuso_exibicao()
    except contrato.FusoInvalido as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    from datetime import datetime
    from zoneinfo import ZoneInfo
    hoje = datetime.now(ZoneInfo(fuso)).date()

    dados = _opcoes_do_dw()
    listas = dados["listas"]
    clientes = dados["clientes"]
    de_min, ate_max, alterado_em = dados["de_min"], dados["ate_max"], dados["alterado_em"]

    try:
        abertura_de = min(contrato.abertura_de(hoje), hoje)
    except contrato.AberturaInvalida as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))

    return {
        **listas,
        "clientes": clientes,
        "periodo": {
            "de": de_min.isoformat() if de_min else None,
            "ate": ate_max.isoformat() if ate_max else None,
        },
        "abertura": {"de": abertura_de.isoformat(), "ate": hoje.isoformat()},
        "atualizado_ate": alterado_em.isoformat() if alterado_em else None,
        "teto_confirmacao": download.TETO_CONFIRMACAO,
        "teto_xlsx": download.TETO_XLSX,
        "lentes": [
            {"chave": c, "nome": d["nome"], "unidade": d["unidade"]}
            for c, d in contrato.LENTES.items()
        ],
        "hierarquia": list(contrato.HIERARQUIA),
        "contrato": contrato.ORIGEM,
    }


# ------------------------------------------------------------------ consulta
@router.get("/matriz")
def api_matriz(
    de: str = Query(..., description="primeiro dia, AAAA-MM-DD"),
    ate: str = Query(..., description="último dia, AAAA-MM-DD (inclusivo)"),
    lente: str = Query("liq"),
    pagina: int = Query(1, ge=1),
    unidade: list[str] = Query(default=[]),
    cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]),
    tipo_viagem: list[str] = Query(default=[]),
    tipo_movimento: list[str] = Query(default=[]),
    status_viagem: list[str] = Query(default=[]),
    status_wms: list[str] = Query(default=[]),
    status_baixa: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[], description="dia do MÊS, 1..31"),
    _: dict = Depends(require_ver),
):
    filtros = _filtros(de, ate, lente, pagina, unidade, cliente, tipo_estoque,
                       tipo_viagem, tipo_movimento, status_viagem, status_wms, status_baixa, dia)
    with _cursor() as cur:
        resultado = matriz.consultar(cur, filtros)
    return _json(resultado)


@router.get("/planilha")
def api_planilha(
    de: str = Query(...),
    ate: str = Query(...),
    lente: str = Query("liq"),
    pagina: int = Query(1, ge=1),
    unidade: list[str] = Query(default=[]),
    cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]),
    tipo_viagem: list[str] = Query(default=[]),
    tipo_movimento: list[str] = Query(default=[]),
    status_viagem: list[str] = Query(default=[]),
    status_wms: list[str] = Query(default=[]),
    status_baixa: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[]),
    _: dict = Depends(require_ver),
):
    filtros = _filtros(de, ate, lente, pagina, unidade, cliente, tipo_estoque,
                       tipo_viagem, tipo_movimento, status_viagem, status_wms, status_baixa, dia)
    with _cursor() as cur:
        resultado = planilha.consultar(cur, filtros)
    return _json(resultado)


# ------------------------------------------------------------------ download
_SEM_EXPORTAR = (
    f"Requer a permissão de exportar da Volumetria de Transporte ({EXPORTAR}). "
    "Consultar a Matriz e a planilha na tela não exige. Peça a um administrador "
    "para incluí-la em alguma das suas roles."
)


def _itens_do_recorte(request: Request):
    return [(k, v) for k, v in request.query_params.multi_items() if k != "ticket"]


def _usuario_do_ticket(ticket: str, request: Request) -> dict:
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
    de: str = Query(...), ate: str = Query(...), formato: str = Query("csv"),
    lente: str = Query("liq"),
    unidade: list[str] = Query(default=[]), cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]), tipo_viagem: list[str] = Query(default=[]),
    tipo_movimento: list[str] = Query(default=[]), status_viagem: list[str] = Query(default=[]),
    status_wms: list[str] = Query(default=[]), status_baixa: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[]),
    user: dict = Depends(require_permissao(EXPORTAR)),
):
    """Autoriza UM download deste recorte, por um minuto — ver `ticket.py`."""
    if formato not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail=f"formato: {formato!r}")
    # Só para validar o recorte (400 antes de emitir ticket) — o resultado
    # não é usado aqui; quem consome o recorte de verdade é `/download`.
    _filtros(de, ate, lente, 1, unidade, cliente, tipo_estoque,
             tipo_viagem, tipo_movimento, status_viagem, status_wms, status_baixa, dia)
    with _cursor():
        pass
    return {
        "ticket": ticket_mod.emitir(user, _itens_do_recorte(request)),
        "valido_por_segundos": ticket_mod.VALIDO_POR_SEGUNDOS,
    }


@router.get("/download")
def api_download(
    request: Request,
    de: str = Query(...), ate: str = Query(...), formato: str = Query("csv"),
    lente: str = Query("liq"),
    unidade: list[str] = Query(default=[]), cliente: list[str] = Query(default=[]),
    tipo_estoque: list[str] = Query(default=[]), tipo_viagem: list[str] = Query(default=[]),
    tipo_movimento: list[str] = Query(default=[]), status_viagem: list[str] = Query(default=[]),
    status_wms: list[str] = Query(default=[]), status_baixa: list[str] = Query(default=[]),
    dia: list[str] = Query(default=[]),
    ticket: str | None = Query(default=None),
    user_bearer: dict | None = Depends(get_current_user_optional),
):
    """O recorte inteiro, em CSV (streaming) ou xlsx (sob teto)."""
    user = _quem_baixa(request, ticket, user_bearer)
    if formato not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail=f"formato: {formato!r}")
    filtros = _filtros(de, ate, lente, 1, unidade, cliente, tipo_estoque,
                       tipo_viagem, tipo_movimento, status_viagem, status_wms, status_baixa, dia)

    with _cursor():
        pass

    registro = auditoria.abrir(
        recorte=filtros.como_dict(), formato=formato,
        ip=_ip(request), usuario=user.get("username"),
    )

    nome = download.nome_do_arquivo(filtros, formato)
    cabecalhos = {"Content-Disposition": f'attachment; filename="{nome}"'}

    if formato == "csv":
        return StreamingResponse(
            download.gerar_csv(filtros, registro),
            media_type="text/csv; charset=utf-8",
            headers=cabecalhos,
        )

    try:
        conteudo = download.gerar_xlsx(filtros, registro)
    except download.DownloadGrandeDemais as erro:
        raise HTTPException(status_code=400, detail=str(erro)) from None
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro))
    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=cabecalhos,
    )


# ----------------------------------------------------------------- auditoria
@router.get("/auditoria")
def api_auditoria(limite: int = Query(100, ge=1, le=1000), _: dict = Depends(require_admin)):
    return auditoria.listar(limite)


# --------------------------------------------------------- diagnóstico do DW
@router.get("/diagnostico-dw")
def api_diagnostico_dw(_: dict = Depends(require_admin)):
    """Conectei no DW, vi a tabela, o contrato bate? Padrão de
    `volumetria_catering`, ver lá para o porquê de cada decisão. Só admin."""
    resposta = {
        "dsn": conexao_dw.dsn(),
        "credencial": {
            "usuario": conexao_dw.ENV_USUARIO,
            "senha": conexao_dw.ENV_SENHA,
            "configurada": conexao_dw.configurado(),
        },
        "contrato": contrato.ORIGEM,
        "conectou": False,
        "resultado": None,
        "ok": False,
    }

    try:
        contrato.tabela()
    except contrato.TabelaInvalida as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)) from None

    try:
        conn = conexao_dw.conectar()
    except conexao_dw.DWIndisponivel as erro:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(erro)) from None

    try:
        resposta["conectou"] = True
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            resposta["resultado"] = schema_dw.conferir(cur)
    finally:
        conn.close()

    resposta["ok"] = not resposta["resultado"]["problemas"]
    if not resposta["ok"]:
        logger.error(
            "volumetria-transporte/DW: diagnóstico reprovou — %s",
            "; ".join(resposta["resultado"]["problemas"]),
        )
    return resposta
