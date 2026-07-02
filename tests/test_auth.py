import jwt
import pytest
from sqlalchemy import text

from backend.auth.service import (
    authenticate_user,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.core.database import db


# ---------- unidade: hashing ----------

def test_hash_password_roundtrip():
    h = hash_password("segredo123")
    assert h != "segredo123"
    assert verify_password("segredo123", h)
    assert not verify_password("errado", h)


def test_verify_password_hash_invalido_nao_estoura():
    assert verify_password("qualquer", "isto-nao-e-bcrypt") is False


# ---------- unidade: token JWT ----------

def test_token_roundtrip():
    token = create_access_token("alguem", {"is_admin": True, "tv": 1})
    payload = decode_token(token)
    assert payload["sub"] == "alguem"
    assert payload["is_admin"] is True
    assert "exp" in payload and "iat" in payload


def test_token_assinatura_invalida_rejeitada():
    token = create_access_token("alguem", {"tv": 1})
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "outro-secret", algorithms=["HS256"])


# ---------- unidade: authenticate_user (boundary) ----------

def test_authenticate_user_ok():
    user = authenticate_user("admin", "admin123")
    assert user is not None
    assert user["username"] == "admin"
    assert user["is_admin"] == 1


def test_authenticate_user_senha_errada():
    assert authenticate_user("admin", "errada") is None


def test_authenticate_user_inexistente():
    assert authenticate_user("ninguem", "x") is None


def test_authenticate_user_inativo():
    with db() as conn:
        conn.execute(text("UPDATE usuarios SET ativo = 0 WHERE username = :u"), {"u": "operador.armazem"})
    try:
        assert authenticate_user("operador.armazem", "armazem123") is None
    finally:
        with db() as conn:
            conn.execute(text("UPDATE usuarios SET ativo = 1 WHERE username = :u"), {"u": "operador.armazem"})


# ---------- endpoint: login / me ----------

def test_login_ok(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["is_admin"] is True


def test_login_credenciais_invalidas(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "errada"})
    assert r.status_code == 401


def test_me_com_token(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_me_sem_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_token_invalido(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer lixo.invalido.xyz"})
    assert r.status_code == 401


def test_token_revogado_por_token_version(client, analista_headers):
    # Token válido vira inválido quando o token_version do usuário muda
    # (é o que o reset de senha faz: token_version + 1).
    assert client.get("/api/auth/me", headers=analista_headers).status_code == 200
    with db() as conn:
        conn.execute(
            text("UPDATE usuarios SET token_version = token_version + 1 WHERE username = :u"),
            {"u": "analista.bo"},
        )
    try:
        assert client.get("/api/auth/me", headers=analista_headers).status_code == 401
    finally:
        with db() as conn:
            conn.execute(
                text("UPDATE usuarios SET token_version = token_version - 1 WHERE username = :u"),
                {"u": "analista.bo"},
            )
