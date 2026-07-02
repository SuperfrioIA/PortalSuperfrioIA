import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.core.database import db
from backend.usuarios import service as usuarios_service

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
    Boundary de autenticação. Hoje valida senha local (via módulo Usuários).
    Quando vier integração AD/LDAP, este é o único ponto que muda:
    branch por `auth_source` ou bind LDAP direto antes do fallback local.
    """
    with db() as session:
        user = usuarios_service.por_username(session, username)

    if not user:
        return None

    if user["auth_source"] == "local":
        if not user["password_hash"] or not verify_password(password, user["password_hash"]):
            return None
        return user

    # auth_source == 'ad' → placeholder, ainda não implementado
    return None
