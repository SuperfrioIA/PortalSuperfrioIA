from sqlalchemy import insert, select, update

from backend.auth import hash_password
from backend.database import App, Role, Secao, Usuario, db, init_db, role_apps, usuario_roles

SECOES = [
    {
        "slug": "armazem",
        "nome": "Armazém",
        "nome_es": "Almacén",
        "descricao": "Operações de armazém, integrações WMS e inventário.",
        "descricao_es": "Operaciones de almacén, integraciones WMS e inventario.",
        "icone": "warehouse",
        "ordem": 1,
    },
    {
        "slug": "backoffice",
        "nome": "Backoffice",
        "nome_es": "Backoffice",
        "descricao": "Processos administrativos, financeiro e suporte interno.",
        "descricao_es": "Procesos administrativos, finanzas y soporte interno.",
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
        "nome_es": "FAQ BlueYonder",
        "descricao": "Perguntas frequentes e procedimentos do WMS BlueYonder.",
        "descricao_es": "Preguntas frecuentes y procedimientos del WMS BlueYonder.",
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
        "nome_es": "FAQ Slin",
        "descricao": "Base de conhecimento do sistema Slin.",
        "descricao_es": "Base de conocimiento del sistema Slin.",
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
        "nome_es": "Conciliación de Inventario",
        "descricao": "Comparação WMS x Protheus e tratativas de divergência.",
        "descricao_es": "Comparación WMS x Protheus y tratamiento de divergencias.",
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
        "nome_es": "Consultas Finanzas",
        "descricao": "Canal de dúvidas e tratativas com o financeiro.",
        "descricao_es": "Canal de consultas y tratativas con finanzas.",
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
        "nome_es": "Compras 2.0",
        "descricao": "Fluxo renovado de solicitação e aprovação de compras.",
        "descricao_es": "Flujo renovado de solicitud y aprobación de compras.",
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
        "nome_es": "ConciliaFAT",
        "descricao": "Conciliação automatizada de notas fiscais de transporte.",
        "descricao_es": "Conciliación automatizada de facturas de transporte.",
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
        "nome_es": "Control de Recepción",
        "descricao": "Acompanhamento de recebimentos e pendências.",
        "descricao_es": "Seguimiento de recepciones y pendientes.",
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
    """Seed idempotente — insere só o que não existe (equivalente ao INSERT OR IGNORE)."""
    with db() as session:
        for s in SECOES:
            existe = session.execute(
                select(Secao.id).where(Secao.slug == s["slug"])
            ).scalar_one_or_none()
            if existe is None:
                session.execute(
                    insert(Secao).values(
                        slug=s["slug"], nome=s["nome"], nome_es=s["nome_es"],
                        descricao=s["descricao"], descricao_es=s["descricao_es"],
                        icone=s["icone"], ordem=s["ordem"],
                    )
                )
            # Backfill ES em bancos já seedados (não sobrescreve edição do admin)
            session.execute(
                update(Secao)
                .where(Secao.slug == s["slug"], Secao.nome_es.is_(None))
                .values(nome_es=s["nome_es"], descricao_es=s["descricao_es"])
            )

        secao_id = {
            slug: id_ for id_, slug in session.execute(select(Secao.id, Secao.slug))
        }

        for a in APPS:
            existe = session.execute(
                select(App.id).where(App.slug == a["slug"])
            ).scalar_one_or_none()
            if existe is None:
                session.execute(
                    insert(App).values(
                        slug=a["slug"], nome=a["nome"], nome_es=a["nome_es"],
                        descricao=a["descricao"], descricao_es=a["descricao_es"],
                        icone=a["icone"], secao_id=secao_id[a["secao"]],
                        url=a["url"], tipo_acesso=a["tipo_acesso"],
                        badge=a["badge"], ordem=a["ordem"],
                    )
                )
            # Backfill ES em bancos já seedados (não sobrescreve edição do admin)
            session.execute(
                update(App)
                .where(App.slug == a["slug"], App.nome_es.is_(None))
                .values(nome_es=a["nome_es"], descricao_es=a["descricao_es"])
            )

        app_id = {
            slug: id_ for id_, slug in session.execute(select(App.id, App.slug))
        }

        for r in ROLES:
            role_id = session.execute(
                select(Role.id).where(Role.slug == r["slug"])
            ).scalar_one_or_none()
            if role_id is None:
                role_id = session.execute(
                    insert(Role).values(slug=r["slug"], nome=r["nome"], descricao=r["descricao"])
                ).inserted_primary_key[0]
            for app_slug in r["apps"]:
                vinculo = session.execute(
                    select(role_apps.c.role_id).where(
                        role_apps.c.role_id == role_id,
                        role_apps.c.app_id == app_id[app_slug],
                    )
                ).fetchone()
                if vinculo is None:
                    session.execute(
                        insert(role_apps).values(role_id=role_id, app_id=app_id[app_slug])
                    )

        role_id_map = {
            slug: id_ for id_, slug in session.execute(select(Role.id, Role.slug))
        }

        for u in USUARIOS:
            user_id = session.execute(
                select(Usuario.id).where(Usuario.username == u["username"])
            ).scalar_one_or_none()
            if user_id is None:
                user_id = session.execute(
                    insert(Usuario).values(
                        username=u["username"], nome=u["nome"], email=u["email"],
                        password_hash=hash_password(u["senha"]),
                        auth_source="local", is_admin=u["is_admin"],
                    )
                ).inserted_primary_key[0]

            for role_slug in u["roles"]:
                vinculo = session.execute(
                    select(usuario_roles.c.usuario_id).where(
                        usuario_roles.c.usuario_id == user_id,
                        usuario_roles.c.role_id == role_id_map[role_slug],
                    )
                ).fetchone()
                if vinculo is None:
                    session.execute(
                        insert(usuario_roles).values(
                            usuario_id=user_id, role_id=role_id_map[role_slug]
                        )
                    )
        # commit e close ficam a cargo do context manager db()


if __name__ == "__main__":
    # `python -m backend.seed` — usado no deploy pra (re)seedar um banco do zero
    # (ex.: Postgres novo no Lote 2). init_db é idempotente; roda migrations até
    # head antes de semear, então funciona mesmo standalone.
    init_db()
    seed_initial()
    print("[seed] concluído.")
