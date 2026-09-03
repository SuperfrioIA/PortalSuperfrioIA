"""Registro e leitura da trilha de auditoria.

## `registrar()` — dentro ou fora da transação de negócio

Recebe a `session` do chamador quando existe uma (mutação administrativa,
dentro de `with db() as session:`): o INSERT entra na mesma transação, e se
`registrar()` falhar (categoria/ação fora do catálogo, detalhes com chave
proibida), a mutação inteira não commita. É a garantia de atomicidade da
Fase 1 — nenhuma alteração administrativa "silenciosa".

Sem `session` (login, logout, SSO, `app.abrir`, `acesso.negado`): não existe
uma transação de negócio para participar, e essas rotas não podem travar por
causa da auditoria. Abre a própria sessão e nunca deixa uma exceção subir —
só `logger.error`.

## `detalhes` nunca carrega segredo

`_sanear_detalhes` recusa (levanta, não mascara) qualquer chave — em
qualquer profundidade do dicionário — que bata na lista de proibidas. Um
diff de PATCH nunca inclui `password_hash` (o select público de usuários já
não devolve essa coluna), e o evento de reset de senha não recebe a senha
nova como argumento — a proteção aqui é a segunda camada, não a única.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from sqlalchemy import func, insert, select

from backend.auditoria import catalogo
from backend.auditoria.models import AuditoriaEvento
from backend.core.correlacao import correlacao_id as correlacao_id_atual
from backend.core.database import _now, db

logger = logging.getLogger("backend.auditoria")

RESULTADOS = ("ok", "negado", "erro")

_TETO_DETALHES_BYTES = 4096
_PROIBIDOS = {
    "senha", "password", "password_hash", "token", "code", "state",
    "client_secret", "access_token", "refresh_token", "authorization",
}


def _chave_proibida(valor: Any) -> str | None:
    if isinstance(valor, dict):
        for chave, sub in valor.items():
            if str(chave).lower() in _PROIBIDOS:
                return str(chave)
            achado = _chave_proibida(sub)
            if achado:
                return achado
    elif isinstance(valor, (list, tuple)):
        for item in valor:
            achado = _chave_proibida(item)
            if achado:
                return achado
    return None


def _sanear_detalhes(detalhes: dict | None) -> str:
    dados = detalhes or {}
    achado = _chave_proibida(dados)
    if achado:
        raise ValueError(
            f"detalhes de auditoria não podem conter a chave {achado!r} "
            "(segredo/credencial não é dado de auditoria)"
        )
    bruto = json.dumps(dados, ensure_ascii=False, default=str)
    if len(bruto.encode("utf-8")) > _TETO_DETALHES_BYTES:
        bruto = json.dumps(
            {"_truncado": True, "motivo": f"detalhes acima de {_TETO_DETALHES_BYTES} bytes"},
            ensure_ascii=False,
        )
    return bruto


def registrar(
    session=None,
    *,
    categoria: str,
    acao: str,
    resultado: str,
    ator: dict | None = None,
    ator_ip: str | None = None,
    app_slug: str | None = None,
    alvo_tipo: str | None = None,
    alvo_id: int | str | None = None,
    alvo_rotulo: str | None = None,
    detalhes: dict | None = None,
) -> None:
    """Grava um evento. Ver o módulo para a regra de atomicidade."""
    catalogo.validar(categoria, acao)
    if resultado not in RESULTADOS:
        raise ValueError(f"resultado de auditoria inválido: {resultado!r} (use {RESULTADOS})")

    valores = dict(
        ocorrido_em=_now(),
        correlacao_id=correlacao_id_atual(),
        ator_usuario_id=(ator or {}).get("id"),
        ator_username=(ator or {}).get("username"),
        ator_ip=ator_ip,
        app_slug=app_slug,
        categoria=categoria,
        acao=acao,
        alvo_tipo=alvo_tipo,
        alvo_id=str(alvo_id) if alvo_id is not None else None,
        alvo_rotulo=alvo_rotulo,
        resultado=resultado,
        detalhes=_sanear_detalhes(detalhes),
    )

    if session is not None:
        session.execute(insert(AuditoriaEvento).values(**valores))
        return

    try:
        with db() as propria:
            propria.execute(insert(AuditoriaEvento).values(**valores))
    except Exception:
        logger.error("falha ao gravar evento %s.%s", categoria, acao, exc_info=True)


def diff(antes: dict, campos: dict) -> dict:
    """Só os campos de `campos` cujo valor realmente muda, como
    `{campo: {"de": ..., "para": ...}}` — usado nos eventos `*.atualizar` para
    o detalhe carregar o antes/depois, não o registro inteiro."""
    mudou = {}
    for campo, novo in campos.items():
        velho = antes.get(campo)
        if velho != novo:
            mudou[campo] = {"de": velho, "para": novo}
    return mudou


def diff_listas(antes: list, depois: list) -> dict:
    """Para campos tipo lista (apps de uma role, roles de um usuário):
    `{"adicionados": [...], "removidos": [...]}` em vez da lista inteira nos
    dois lados — é o que a auditoria de concessão precisa responder."""
    antes_s, depois_s = set(antes), set(depois)
    return {
        "adicionados": sorted(depois_s - antes_s),
        "removidos": sorted(antes_s - depois_s),
    }


def _aplicar_filtros(
    stmt,
    *,
    de: str | None,
    ate: str | None,
    ator_username: str | None,
    app_slug: str | None,
    categoria: str | None,
    acao: str | None,
    resultado: str | None,
):
    if de:
        stmt = stmt.where(AuditoriaEvento.ocorrido_em >= f"{de} 00:00:00")
    if ate:
        stmt = stmt.where(AuditoriaEvento.ocorrido_em <= f"{ate} 23:59:59")
    if ator_username:
        stmt = stmt.where(AuditoriaEvento.ator_username == ator_username)
    if app_slug:
        stmt = stmt.where(AuditoriaEvento.app_slug == app_slug)
    if categoria:
        stmt = stmt.where(AuditoriaEvento.categoria == categoria)
    if acao:
        stmt = stmt.where(AuditoriaEvento.acao == acao)
    if resultado:
        stmt = stmt.where(AuditoriaEvento.resultado == resultado)
    return stmt


def listar(
    session,
    *,
    de: str | None = None,
    ate: str | None = None,
    ator_username: str | None = None,
    app_slug: str | None = None,
    categoria: str | None = None,
    acao: str | None = None,
    resultado: str | None = None,
    pagina: int = 1,
    por_pagina: int = 50,
) -> dict:
    """Página de eventos, mais recente primeiro, com o total do filtro aplicado."""
    pagina = max(1, pagina)
    por_pagina = min(max(1, por_pagina), 200)

    filtros = dict(
        de=de, ate=ate, ator_username=ator_username, app_slug=app_slug,
        categoria=categoria, acao=acao, resultado=resultado,
    )
    base = _aplicar_filtros(select(AuditoriaEvento.__table__), **filtros)
    total = session.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    linhas = session.execute(
        base.order_by(AuditoriaEvento.id.desc())
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    ).mappings().fetchall()

    itens = []
    for linha in linhas:
        item = dict(linha)
        item["detalhes"] = json.loads(item["detalhes"] or "{}")
        itens.append(item)

    return {"itens": itens, "total": total, "pagina": pagina, "por_pagina": por_pagina}


_CABECALHO_CSV = (
    "ocorrido_em", "ator_username", "ator_ip", "app_slug", "categoria", "acao",
    "alvo_tipo", "alvo_id", "alvo_rotulo", "resultado", "detalhes",
)

BOM = "﻿"


def exportar_csv(
    *,
    de: str | None = None,
    ate: str | None = None,
    ator_username: str | None = None,
    app_slug: str | None = None,
    categoria: str | None = None,
    acao: str | None = None,
    resultado: str | None = None,
) -> Iterator[bytes]:
    """Todas as linhas do filtro, em CSV Excel-first (BOM, `;`). Gerador dono
    da própria sessão: o corpo roda depois de a resposta HTTP começar, quando
    um `with` do chamador já teria fechado (mesmo padrão de
    `volumetria_catering/download.py`)."""
    import csv
    import io

    filtros = dict(
        de=de, ate=ate, ator_username=ator_username, app_slug=app_slug,
        categoria=categoria, acao=acao, resultado=resultado,
    )
    with db() as session:
        base = _aplicar_filtros(select(AuditoriaEvento.__table__), **filtros)
        linhas = session.execute(base.order_by(AuditoriaEvento.id.asc())).mappings().fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(_CABECALHO_CSV)
    yield (BOM + buffer.getvalue()).encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)

    for linha in linhas:
        writer.writerow([linha[campo] for campo in _CABECALHO_CSV])
        yield buffer.getvalue().encode("utf-8")
        buffer.seek(0)
        buffer.truncate(0)
