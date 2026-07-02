"""Seed do catálogo (seções e apps) — idempotente, insere só o que não existe."""
from sqlalchemy import insert, select, update

from backend.portal.models import App, Secao

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


def seed(session) -> None:
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
