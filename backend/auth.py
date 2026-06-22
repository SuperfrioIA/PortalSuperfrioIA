import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.database import db

_DEFAULT_SECRET = "dev-secret-change-me"
JWT_SECRET = os.environ.get("SUPERFRIO_JWT_SECRET", _DEFAULT_SECRET)
JWT_ALG = "HS256"
JWT_EXP_HOURS = 3

if JWT_SECRET == _DEFAULT_SECRET:
    if os.environ.get("SUPERFRIO_ENV", "dev").lower() == "prod":
        raise RuntimeError(
            "SUPERFRIO_JWT_SECRET não configurado em produção. "
            "Defina uma string aleatória forte (ex: openssl rand -hex 32)."
        )
    import sys
    print(
        "[WARN] SUPERFRIO_JWT_SECRET usando default 'dev-secret-change-me'. "
        "OK para dev; em produção defina SUPERFRIO_ENV=prod para forçar.",
        file=sys.stderr,
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXP_HOURS)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])


def authenticate_user(username: str, password: str) -> dict | None:
    """
    Boundary de autenticação. Hoje valida contra SQLite local.
    Quando vier integração AD/LDAP, este é o único ponto que muda:
    branch por `auth_source` ou bind LDAP direto antes do fallback local.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE username = ? AND ativo = 1",
            (username,),
        ).fetchone()

    if not row:
        return None

    if row["auth_source"] == "local":
        if not row["password_hash"] or not verify_password(password, row["password_hash"]):
            return None
        return dict(row)

    # auth_source == 'ad' → placeholder, ainda não implementado
    return None


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

    with db() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE username = ? AND ativo = 1",
            (username,),
        ).fetchone()

    if not row:
        raise creds_exc
    if row["token_version"] != tv_token:
        raise creds_exc
    return dict(row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores",
        )
    return user
