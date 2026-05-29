from backend.auth import hash_password
from backend.database import get_conn

SECOES = [
    {
        "slug": "armazem",
        "nome": "Armazém",
        "descricao": "Operações de armazém, integrações WMS e inventário.",
        "icone": "warehouse",
        "ordem": 1,
    },
    {
        "slug": "backoffice",
        "nome": "Backoffice",
        "descricao": "Processos administrativos, financeiro e suporte interno.",
        "icone": "briefcase",
        "ordem": 2,
    },
]

APPS = [
    # Armazém
    {
        "secao": "armazem",
        "slug": "faq-blueyonder",
        "nome": "FAQ BlueYonder",
        "descricao": "Perguntas frequentes e procedimentos do WMS BlueYonder.",
        "icone": "book",
        "url": "https://example.internal/faq-blueyonder",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 1,
    },
    {
        "secao": "armazem",
        "slug": "faq-slin",
        "nome": "FAQ Slin",
        "descricao": "Base de conhecimento do sistema Slin.",
        "icone": "book",
        "url": "https://example.internal/faq-slin",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 2,
    },
    {
        "secao": "armazem",
        "slug": "conciliacao-estoque",
        "nome": "Conciliação de Estoque",
        "descricao": "Comparação WMS x Protheus e tratativas de divergência.",
        "icone": "scale",
        "url": "https://example.internal/conciliacao-estoque",
        "tipo_acesso": "url",
        "badge": "NEW",
        "ordem": 3,
    },
    # Backoffice
    {
        "secao": "backoffice",
        "slug": "duvidas-financeiro",
        "nome": "Dúvidas Financeiro",
        "descricao": "Canal de dúvidas e tratativas com o financeiro.",
        "icone": "chat",
        "url": "https://example.internal/duvidas-financeiro",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 1,
    },
    {
        "secao": "backoffice",
        "slug": "compras-2-0",
        "nome": "Compras 2.0",
        "descricao": "Fluxo renovado de solicitação e aprovação de compras.",
        "icone": "cart",
        "url": "https://example.internal/compras-2-0",
        "tipo_acesso": "url",
        "badge": "BETA",
        "ordem": 2,
    },
    {
        "secao": "backoffice",
        "slug": "conciliafat",
        "nome": "ConciliaFAT",
        "descricao": "Conciliação automatizada de notas fiscais de transporte.",
        "icone": "document",
        "url": "https://example.internal/conciliafat",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 3,
    },
    {
        "secao": "backoffice",
        "slug": "controle-recebimento",
        "nome": "Controle de Recebimento",
        "descricao": "Acompanhamento de recebimentos e pendências.",
        "icone": "truck",
        "url": "https://example.internal/controle-recebimento",
        "tipo_acesso": "url",
        "badge": None,
        "ordem": 4,
    },
]

ROLES = [
    {
        "slug": "armazem-full",
        "nome": "Armazém — Acesso completo",
        "descricao": "Acesso a todos os apps da seção Armazém.",
        "apps": ["faq-blueyonder", "faq-slin", "conciliacao-estoque"],
    },
    {
        "slug": "backoffice-full",
        "nome": "Backoffice — Acesso completo",
        "descricao": "Acesso a todos os apps da seção Backoffice.",
        "apps": ["duvidas-financeiro", "compras-2-0", "conciliafat", "controle-recebimento"],
    },
    {
        "slug": "faq-leitor",
        "nome": "FAQ — Somente leitura",
        "descricao": "Acesso restrito aos FAQs (BlueYonder e Slin).",
        "apps": ["faq-blueyonder", "faq-slin"],
    },
]

USUARIOS = [
    {
        "username": "admin",
        "nome": "Administrador",
        "email": "admin@superfrio.com.br",
        "senha": "admin123",
        "is_admin": 1,
        "roles": [],
    },
    {
        "username": "operador.armazem",
        "nome": "Operador Armazém",
        "email": "armazem@superfrio.com.br",
        "senha": "armazem123",
        "is_admin": 0,
        "roles": ["armazem-full"],
    },
    {
        "username": "analista.bo",
        "nome": "Analista Backoffice",
        "email": "bo@superfrio.com.br",
        "senha": "backoffice123",
        "is_admin": 0,
        "roles": ["backoffice-full", "faq-leitor"],
    },
]


def seed_initial() -> None:
    """Seed idempotente — INSERT OR IGNORE em todas as tabelas."""
    conn = get_conn()
    try:
        for s in SECOES:
            conn.execute(
                """INSERT OR IGNORE INTO secoes (slug, nome, descricao, icone, ordem)
                   VALUES (?, ?, ?, ?, ?)""",
                (s["slug"], s["nome"], s["descricao"], s["icone"], s["ordem"]),
            )

        secao_id = {
            row["slug"]: row["id"]
            for row in conn.execute("SELECT id, slug FROM secoes").fetchall()
        }

        for a in APPS:
            conn.execute(
                """INSERT OR IGNORE INTO apps
                   (slug, nome, descricao, icone, secao_id, url, tipo_acesso, badge, ordem)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    a["slug"], a["nome"], a["descricao"], a["icone"],
                    secao_id[a["secao"]], a["url"], a["tipo_acesso"],
                    a["badge"], a["ordem"],
                ),
            )

        app_id = {
            row["slug"]: row["id"]
            for row in conn.execute("SELECT id, slug FROM apps").fetchall()
        }

        for r in ROLES:
            conn.execute(
                """INSERT OR IGNORE INTO roles (slug, nome, descricao)
                   VALUES (?, ?, ?)""",
                (r["slug"], r["nome"], r["descricao"]),
            )
            role_id = conn.execute(
                "SELECT id FROM roles WHERE slug = ?", (r["slug"],)
            ).fetchone()["id"]
            for app_slug in r["apps"]:
                conn.execute(
                    "INSERT OR IGNORE INTO role_apps (role_id, app_id) VALUES (?, ?)",
                    (role_id, app_id[app_slug]),
                )

        role_id_map = {
            row["slug"]: row["id"]
            for row in conn.execute("SELECT id, slug FROM roles").fetchall()
        }

        for u in USUARIOS:
            existing = conn.execute(
                "SELECT id FROM usuarios WHERE username = ?", (u["username"],)
            ).fetchone()
            if existing:
                user_id = existing["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO usuarios
                       (username, nome, email, password_hash, auth_source, is_admin)
                       VALUES (?, ?, ?, ?, 'local', ?)""",
                    (
                        u["username"], u["nome"], u["email"],
                        hash_password(u["senha"]), u["is_admin"],
                    ),
                )
                user_id = cursor.lastrowid

            for role_slug in u["roles"]:
                conn.execute(
                    "INSERT OR IGNORE INTO usuario_roles (usuario_id, role_id) VALUES (?, ?)",
                    (user_id, role_id_map[role_slug]),
                )

        conn.commit()
    finally:
        conn.close()
