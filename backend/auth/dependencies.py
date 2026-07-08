"""Depends de FastAPI usados pelos routers de todos os módulos."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.auth.service import decode_token
from backend.core.database import db
from backend.usuarios import service as usuarios_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        tv_token = payload.get("tv")
        if not username or tv_token is None:
            raise creds_exc
    except jwt.PyJWTError:
        raise creds_exc

    with db() as session:
        user = usuarios_service.por_username(session, username)

    if not user:
        raise creds_exc
    if user["token_version"] != tv_token:
        raise creds_exc
    return user


def get_current_user_optional(token: str | None = Depends(oauth2_scheme_optional)) -> dict | None:
    """Como get_current_user, mas devolve None em vez de 401/403 — pra endpoints
    que precisam saber quem é o visitante sem exigir login (ex.: decidir se
    mostra um botão que só quem tem permissão pode usar)."""
    if not token:
        return None
    try:
        return get_current_user(token)
    except HTTPException:
        return None


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores",
        )
    return user
