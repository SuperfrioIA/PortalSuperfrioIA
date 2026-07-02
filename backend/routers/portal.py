from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend.auth import get_current_user
from backend.database import App, Secao, db, role_apps, usuario_roles

router = APIRouter(prefix="/api/portal", tags=["portal"])


def _apps_permitidos(user: dict) -> list[dict]:
    """Retorna lista de apps que o usuário pode ver, com a seção embutida."""
    cols = (
        *App.__table__.c,
        Secao.slug.label("secao_slug"),
        Secao.nome.label("secao_nome"),
        Secao.nome_es.label("secao_nome_es"),
        Secao.icone.label("secao_icone"),
        Secao.ordem.label("secao_ordem"),
    )
    with db() as session:
        if user.get("is_admin"):
            stmt = (
                select(*cols)
                .join_from(App, Secao, Secao.id == App.secao_id)
                .where(App.ativo == 1, Secao.ativo == 1)
                .order_by(Secao.ordem, App.ordem, App.nome)
            )
        else:
            stmt = (
                select(*cols)
                .distinct()
                .join_from(App, Secao, Secao.id == App.secao_id)
                .join(role_apps, role_apps.c.app_id == App.id)
                .join(usuario_roles, usuario_roles.c.role_id == role_apps.c.role_id)
                .where(
                    usuario_roles.c.usuario_id == user["id"],
                    App.ativo == 1,
                    Secao.ativo == 1,
                )
                .order_by(Secao.ordem, App.ordem, App.nome)
            )
        rows = session.execute(stmt).mappings().fetchall()
    return [dict(r) for r in rows]


@router.get("/home")
def home(user: dict = Depends(get_current_user)):
    """Estrutura pronta pro frontend: lista de seções com seus apps."""
    apps = _apps_permitidos(user)

    secoes: dict[str, dict] = {}
    for a in apps:
        slug = a["secao_slug"]
        if slug not in secoes:
            secoes[slug] = {
                "slug": slug,
                "nome": a["secao_nome"],
                "nome_es": a["secao_nome_es"],
                "icone": a["secao_icone"],
                "ordem": a["secao_ordem"],
                "apps": [],
            }
        secoes[slug]["apps"].append({
            "slug": a["slug"],
            "nome": a["nome"],
            "nome_es": a["nome_es"],
            "descricao": a["descricao"],
            "descricao_es": a["descricao_es"],
            "icone": a["icone"],
            "url": a["url"],
            "tipo_acesso": a["tipo_acesso"],
            "badge": a["badge"],
        })

    return {
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "is_admin": bool(user["is_admin"]),
        },
        "secoes": sorted(secoes.values(), key=lambda s: s["ordem"]),
    }
