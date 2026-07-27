from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from backend.auth.dependencies import get_current_user, get_current_user_optional
from backend.auth.service import authenticate_user, create_access_token
from backend.core.database import db
from backend.core.limiter import limiter
from backend.usuarios import service as usuarios_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos",
        )
    token = create_access_token(
        subject=user["username"],
        extra={
            "is_admin": bool(user["is_admin"]),
            "nome": user["nome"],
            "tv": user.get("token_version", 1),
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
        },
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "username": user["username"],
        "nome": user["nome"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
    }


@router.get("/me/permissoes")
def minhas_permissoes(user: dict | None = Depends(get_current_user_optional)) -> dict:
    """Tudo que o usuário logado pode fazer, num endpoint só.

    Substitui os `/<app>/pode-editar` escritos um por app: qualquer tela (inclusive
    os apps embutidos por iframe) pergunta aqui e checa
    `permissoes.includes("<app>:<acao>")`.

    Nunca devolve 401/403 — anônimo recebe listas vazias, do mesmo jeito que o
    `pode-editar` antigo fazia. Isso é proposital: os apps estáticos são servidos
    sem login (limitação conhecida, ver docs/PERMISSIONAMENTO_HOJE.md), então eles
    precisam conseguir perguntar antes de saber se há sessão.

    Admin recebe a lista expandida em vez de um sinalizador, para o frontend não
    precisar tratar admin como caso especial.
    """
    if not user:
        return {"autenticado": False, "is_admin": False, "permissoes": []}

    with db() as session:
        if user.get("is_admin"):
            permissoes = usuarios_service.todas_permissoes(session)
        else:
            permissoes = usuarios_service.permissoes_do_usuario(session, user["id"])

    return {
        "autenticado": True,
        "is_admin": bool(user["is_admin"]),
        "permissoes": sorted(permissoes),
    }
