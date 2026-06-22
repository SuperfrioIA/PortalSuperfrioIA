"""Lockout: auto-bloqueio do admin + rate limit de força bruta no login."""
from backend.database import db
from backend.limiter import limiter


def _admin_id() -> int:
    with db() as conn:
        return conn.execute("SELECT id FROM usuarios WHERE username = 'admin'").fetchone()["id"]


# ---------- auto-lockout do admin ----------

def test_admin_nao_desativa_propria_conta(client, admin_headers):
    r = client.post(f"/api/admin/usuarios/{_admin_id()}/toggle", headers=admin_headers)
    assert r.status_code == 400


def test_admin_nao_remove_proprio_is_admin(client, admin_headers):
    r = client.patch(
        f"/api/admin/usuarios/{_admin_id()}",
        json={"is_admin": False},
        headers=admin_headers,
    )
    assert r.status_code == 400


# ---------- rate limit do login (5/minute → 429 na 6ª) ----------

def test_login_rate_limit_429(client):
    limiter.enabled = True
    limiter.reset()
    try:
        statuses = [
            client.post(
                "/api/auth/login", data={"username": "admin", "password": "errada"}
            ).status_code
            for _ in range(6)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
