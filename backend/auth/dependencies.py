"""Depends de FastAPI usados pelos routers de todos os módulos."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.auth.service import decode_token
from backend.core import permissoes as catalogo
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


def usuario_pode(user: dict | None, permissao_slug: str) -> bool:
    """Checagem informativa, sem levantar 401/403.

    Serve para o frontend decidir se mostra um botão. Visitante anônimo devolve
    False em vez de erro. É aqui — e só aqui — que mora o bypass de admin, para
    nenhum módulo precisar reimplementar `if is_admin`.
    """
    if not user:
        return False
    if user.get("is_admin"):
        return True
    with db() as session:
        return usuarios_service.tem_permissao(session, user["id"], permissao_slug)


def require_permissao(permissao_slug: str):
    """Guarda de rota por permissão da matriz (`<app>:<acao>`).

    O slug é validado **agora**, no import do router que chama esta função: se
    não existir no catálogo, a aplicação não sobe. É o que substituiu o antigo
    `ROLE_EDITOR = "processos-abertos-editor"`, em que errar a string virava um
    403 silencioso em produção.
    """
    permissao = catalogo.obter(permissao_slug)  # KeyError explícito no boot

    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if not usuario_pode(user, permissao_slug):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Requer a permissão '{permissao.nome}' em {permissao.modulo} "
                    f"({permissao_slug}). Peça a um administrador para incluí-la em "
                    "alguma das suas roles."
                ),
            )
        return user

    _dep.__name__ = f"require_{permissao_slug.replace(':', '_').replace('-', '_')}"
    return _dep
