"""Histórico compartilhado do dashboard "Processos Abertos".

O dashboard (frontend/processos-abertos/, Receita 1 do CONTRIBUTING.md) roda
inteiro no navegador. Este router existe só pra centralizar as semanas
processadas num arquivo compartilhado — sem banco, sem ORM, sem migration —
em vez de cada upload ficar preso ao localStorage de quem processou.

Leitura é pública (mesmo nível de acesso que os arquivos estáticos do app,
que já são abertos sem login). Escrita exige a role `processos-abertos-editor`
(ou ser admin) — ver o app na home é uma permissão, atualizar os dados é outra.
"""
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth.dependencies import get_current_user, get_current_user_optional
from backend.core.database import DB_PATH, db
from backend.usuarios import service as usuarios_service

router = APIRouter(prefix="/api/processos-abertos", tags=["processos-abertos"])

_DATA_PATH: Path = DB_PATH.parent / "processos_abertos_extra.json"
_lock = threading.Lock()

ROLE_EDITOR = "processos-abertos-editor"


def _pode_editar(user: dict) -> bool:
    if user.get("is_admin"):
        return True
    with db() as session:
        return usuarios_service.tem_role(session, user["id"], ROLE_EDITOR)


def require_editor(user: dict = Depends(get_current_user)) -> dict:
    if not _pode_editar(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requer a role '{ROLE_EDITOR}' (ou ser admin) pra atualizar Processos Abertos",
        )
    return user


class Semana(BaseModel):
    date: str
    total: int
    d5p: int
    d1: int
    d25: int
    pct: float
    units: int
    resumo: dict[str, Any] = {}
    tipos: dict[str, Any] = {}


def _ler() -> list[dict]:
    if not _DATA_PATH.exists():
        return []
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _escrever(semanas: list[dict]) -> None:
    _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(semanas, f, ensure_ascii=False)
    tmp.replace(_DATA_PATH)


@router.get("/historico")
def listar_historico() -> list[dict]:
    return _ler()


@router.get("/pode-editar")
def pode_editar(user: dict | None = Depends(get_current_user_optional)) -> dict:
    """Pra o frontend decidir se mostra o botão 'Atualizar dados' — nunca falha
    com 401/403, quem não está logado ou não tem a role só recebe False."""
    return {"pode_editar": bool(user) and _pode_editar(user)}


@router.post("/historico")
def salvar_semana(semana: Semana, _: dict = Depends(require_editor)) -> list[dict]:
    """Upsert por `date`: mesma semana reprocessada substitui a anterior."""
    with _lock:
        semanas = _ler()
        payload = semana.model_dump()
        idx = next((i for i, s in enumerate(semanas) if s.get("date") == payload["date"]), None)
        if idx is not None:
            semanas[idx] = payload
        else:
            semanas.append(payload)
        _escrever(semanas)
    return semanas
