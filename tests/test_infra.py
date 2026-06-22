"""Infra: idempotência do seed, migrations e headers de segurança.

Cobre comportamentos que blindam deploy/retomada:
- seed roda 2x sem duplicar e sem sobrescrever edição do admin (backfill ES);
- _ensure_column / init_db são idempotentes (ALTER só quando falta coluna);
- middleware injeta os headers de segurança + CSP em toda resposta.
Cada teste restaura o que mexe; o de migração usa tabela temporária própria.
"""
from backend.database import _ensure_column, db, init_db
from backend.seed import seed_initial


# ============ Idempotência do seed ============

def _counts():
    tabelas = ["secoes", "apps", "roles", "usuarios", "role_apps", "usuario_roles"]
    with db() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in tabelas}


def test_seed_idempotente():
    antes = _counts()
    seed_initial()  # INSERT OR IGNORE em tudo → não pode duplicar
    assert _counts() == antes


def test_seed_backfill_es_preenche_nulo():
    with db() as conn:
        conn.execute("UPDATE secoes SET nome_es = NULL WHERE slug = 'armazem'")
    seed_initial()
    with db() as conn:
        val = conn.execute("SELECT nome_es FROM secoes WHERE slug = 'armazem'").fetchone()["nome_es"]
    assert val == "Almacén"


def test_seed_backfill_es_nao_sobrescreve_edicao():
    with db() as conn:
        conn.execute("UPDATE secoes SET nome_es = 'EDITADO' WHERE slug = 'armazem'")
    try:
        seed_initial()
        with db() as conn:
            val = conn.execute("SELECT nome_es FROM secoes WHERE slug = 'armazem'").fetchone()["nome_es"]
        assert val == "EDITADO"  # backfill só toca quando nome_es IS NULL
    finally:
        with db() as conn:
            conn.execute("UPDATE secoes SET nome_es = 'Almacén' WHERE slug = 'armazem'")


# ============ Migrations ============

def test_ensure_column_adiciona_e_idempotente():
    with db() as conn:
        conn.execute("DROP TABLE IF EXISTS _mig_test")
        conn.execute("CREATE TABLE _mig_test (id INTEGER)")
        try:
            _ensure_column(conn, "_mig_test", "extra", "extra TEXT")
            cols = [r[1] for r in conn.execute("PRAGMA table_info(_mig_test)")]
            assert "extra" in cols
            # 2ª chamada não estoura nem duplica a coluna
            _ensure_column(conn, "_mig_test", "extra", "extra TEXT")
            cols = [r[1] for r in conn.execute("PRAGMA table_info(_mig_test)")]
            assert cols.count("extra") == 1
        finally:
            conn.execute("DROP TABLE IF EXISTS _mig_test")


def test_init_db_idempotente_com_colunas_de_migracao():
    init_db()  # roda de novo (já rodou no setup da sessão) — não pode estourar
    with db() as conn:
        usuarios = {r[1] for r in conn.execute("PRAGMA table_info(usuarios)")}
        secoes = {r[1] for r in conn.execute("PRAGMA table_info(secoes)")}
        apps = {r[1] for r in conn.execute("PRAGMA table_info(apps)")}
    assert "token_version" in usuarios
    assert {"nome_es", "descricao_es"} <= secoes
    assert {"nome_es", "descricao_es"} <= apps


# ============ Headers de segurança / CSP ============

def test_security_headers_presentes(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_csp_restritiva(client):
    csp = client.get("/api/health").headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp
