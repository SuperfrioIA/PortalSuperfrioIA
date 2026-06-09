from fastapi import APIRouter, Depends

from backend.auth import get_current_user
from backend.database import get_conn

router = APIRouter(prefix="/api/portal", tags=["portal"])


def _apps_permitidos(user: dict) -> list[dict]:
    """Retorna lista de apps que o usuário pode ver, com a seção embutida."""
    conn = get_conn()
    try:
        if user.get("is_admin"):
            rows = conn.execute(
                """SELECT a.*, s.slug AS secao_slug, s.nome AS secao_nome,
                          s.nome_es AS secao_nome_es,
                          s.icone AS secao_icone, s.ordem AS secao_ordem
                   FROM apps a
                   JOIN secoes s ON s.id = a.secao_id
                   WHERE a.ativo = 1 AND s.ativo = 1
                   ORDER BY s.ordem, a.ordem, a.nome"""
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT a.*, s.slug AS secao_slug, s.nome AS secao_nome,
                                   s.nome_es AS secao_nome_es,
                                   s.icone AS secao_icone, s.ordem AS secao_ordem
                   FROM apps a
                   JOIN secoes s ON s.id = a.secao_id
                   JOIN role_apps ra ON ra.app_id = a.id
                   JOIN usuario_roles ur ON ur.role_id = ra.role_id
                   WHERE ur.usuario_id = ?
                     AND a.ativo = 1 AND s.ativo = 1
                   ORDER BY s.ordem, a.ordem, a.nome""",
                (user["id"],),
            ).fetchall()
    finally:
        conn.close()
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
