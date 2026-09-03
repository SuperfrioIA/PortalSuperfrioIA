"""Rotas do Portal: home (/api/portal) e administração do catálogo (/api/admin).

Princípios (herdados do CRUD original):
- Toggle ativo/inativo em vez de DELETE (auditável).
- PATCH é parcial: só atualiza o que vier no body.
- Slug é stable: nunca é editado depois de criado.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, insert, select, update

from backend.auditoria import service as auditoria_service
from backend.auth.dependencies import get_current_user, require_admin
from backend.core.database import _now, db
from backend.core.http import apply_update, ensure_slug, row_or_404, unique_or_409
from backend.portal import service
from backend.portal.models import App, Secao
from backend.usuarios import service as usuarios_service


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None

router = APIRouter(prefix="/api/portal", tags=["portal"])
router_admin = APIRouter(prefix="/api/admin", tags=["admin"])


# ============ Sistemas (timeline de apps adicionados ao portal) ============

@router.get("/sistemas")
def sistemas(user: dict = Depends(get_current_user)):
    """Lista de apps ativos ordenada por data de criação — base da timeline pública."""
    with db() as session:
        if user.get("is_admin"):
            apps = service.apps_ativos_com_secao(session)
        else:
            permitidos = usuarios_service.app_ids_permitidos(session, user["id"])
            apps = service.apps_ativos_com_secao(session, app_ids=permitidos)
    return sorted(
        [
            {
                "slug": a["slug"],
                "nome": a["nome"],
                "descricao": a["descricao"],
                "icone": a["icone"],
                "secao": a["secao_nome"],
                "secao_slug": a["secao_slug"],
                "badge": a["badge"],
                "criado_em": a["criado_em"],
            }
            for a in apps
        ],
        key=lambda x: x["criado_em"] or "",
    )


# ============ Home ============

def _app_publico(a: dict) -> dict:
    """Só o que a home precisa — nada de id, ativo ou datas."""
    return {
        "slug": a["slug"],
        "nome": a["nome"],
        "nome_es": a["nome_es"],
        "descricao": a["descricao"],
        "descricao_es": a["descricao_es"],
        "icone": a["icone"],
        "url": a["url"],
        "tipo_acesso": a["tipo_acesso"],
        "badge": a["badge"],
    }


@router.get("/home")
def home(user: dict = Depends(get_current_user)):
    """Estrutura pronta pro frontend, já separada nos dois grupos do menu.

    `indicadores` é lista chata (os painéis de acompanhamento não são agrupados
    por seção — são poucos e o menu os mostra direto); `secoes` traz apenas os
    apps de sistema, então a contagem de cada seção é a de sistemas, não a de
    tudo. Quem decide a classificação é `apps.tipo_conteudo`, no cadastro.

    A divisão vive aqui e não no frontend de propósito: é a mesma regra para a
    home, para o menu e para qualquer consumidor futuro da API.
    """
    with db() as session:
        if user.get("is_admin"):
            apps = service.apps_ativos_com_secao(session)
        else:
            permitidos = usuarios_service.app_ids_permitidos(session, user["id"])
            apps = service.apps_ativos_com_secao(session, app_ids=permitidos)

    indicadores: list[dict] = []
    secoes: dict[str, dict] = {}
    for a in apps:
        if a["tipo_conteudo"] == "indicador":
            indicadores.append(a)
            continue
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
        secoes[slug]["apps"].append(_app_publico(a))

    # `apps` vem ordenado por seção; a lista chata de indicadores precisa da
    # própria ordem, senão o menu ficaria agrupado por seção sem dizer isso.
    indicadores.sort(key=lambda a: (a["ordem"], a["nome"]))

    return {
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "is_admin": bool(user["is_admin"]),
        },
        "indicadores": [_app_publico(a) for a in indicadores],
        "secoes": sorted(secoes.values(), key=lambda s: s["ordem"]),
    }


@router.post("/abrir/{slug}")
def abrir(slug: str, request: Request, user: dict = Depends(get_current_user)):
    """Chamado pelo card do portal ao clicar num app — é o evento `app.abrir`
    da auditoria (docs/AUDITORIA_FUNCIONAL.md). O frontend segue para a URL
    independente da resposta (fire-and-forget); mesmo assim a permissão é
    conferida de verdade aqui, não só confiada ao front.

    `ver` não passa por `require_permissao` (é a coluna implícita da matriz,
    resolvida por `app_ids_permitidos`) — por isso a checagem é direta, em vez
    de um `Depends` compartilhado com as demais ações.
    """
    with db() as session:
        row = session.execute(
            select(App.__table__.c).where(App.slug == slug, App.ativo == 1)
        ).mappings().fetchone()
        if not row:
            raise HTTPException(404, f"app '{slug}' não encontrado")
        if not user.get("is_admin"):
            permitidos = usuarios_service.app_ids_permitidos(session, user["id"])
            if row["id"] not in permitidos:
                # Sessão própria (não a do endpoint): a HTTPException abaixo
                # reverteria o INSERT se ele estivesse na mesma transação.
                auditoria_service.registrar(
                    categoria="acesso", acao="acesso.negado", resultado="negado",
                    ator=user, ator_ip=_ip(request), app_slug=slug,
                    detalhes={"rota": request.url.path, "exigia": "ver"},
                )
                raise HTTPException(403, f"Você não tem acesso ao app '{slug}'")
        auditoria_service.registrar(
            session, categoria="acesso", acao="app.abrir", resultado="ok",
            ator=user, ator_ip=_ip(request), app_slug=slug,
        )
        return {"url": row["url"]}


# ============ Seções (admin) ============

class SecaoCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: int = 0


class SecaoUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    ordem: Optional[int] = None


@router_admin.get("/secoes")
def listar_secoes(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            select(*Secao.__table__.c, func.count(App.id).label("apps_count"))
            .join_from(Secao, App, App.secao_id == Secao.id, isouter=True)
            .group_by(Secao.id)
            .order_by(Secao.ordem, Secao.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router_admin.post("/secoes", status_code=201)
def criar_secao(body: SecaoCreate, request: Request, admin: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    with db() as session:
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(Secao).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, ordem=body.ordem,
                )
            )
        secao_id = cur.inserted_primary_key[0]
        auditoria_service.registrar(
            session, categoria="admin", acao="secao.criar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="secao", alvo_id=secao_id, alvo_rotulo=body.slug,
            detalhes=body.model_dump(),
        )
        return row_or_404(session, Secao, secao_id, "secoes")


@router_admin.patch("/secoes/{secao_id}")
def atualizar_secao(
    secao_id: int, body: SecaoUpdate, request: Request, admin: dict = Depends(require_admin)
):
    with db() as session:
        atual = row_or_404(session, Secao, secao_id, "secoes")
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return atual
        apply_update(session, Secao, secao_id, fields)
        auditoria_service.registrar(
            session, categoria="admin", acao="secao.atualizar", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="secao", alvo_id=secao_id, alvo_rotulo=atual["slug"],
            detalhes=auditoria_service.diff(atual, fields),
        )
        return row_or_404(session, Secao, secao_id, "secoes")


@router_admin.post("/secoes/{secao_id}/toggle")
def toggle_secao(secao_id: int, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, Secao, secao_id, "secoes")
        novo = 0 if row["ativo"] else 1
        session.execute(update(Secao).where(Secao.id == secao_id).values(ativo=novo))
        auditoria_service.registrar(
            session, categoria="admin", acao="secao.toggle", resultado="ok",
            ator=admin, ator_ip=_ip(request),
            alvo_tipo="secao", alvo_id=secao_id, alvo_rotulo=row["slug"],
            detalhes={"ativo": {"de": bool(row["ativo"]), "para": bool(novo)}},
        )
        return row_or_404(session, Secao, secao_id, "secoes")


# ============ Apps (admin) ============

class AppCreate(BaseModel):
    slug: str
    nome: str
    nome_es: Optional[str] = None
    secao_id: int
    url: str
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    tipo_acesso: str = "url"
    tipo_conteudo: str = "sistema"
    badge: Optional[str] = None
    ordem: int = 0


class AppUpdate(BaseModel):
    nome: Optional[str] = None
    nome_es: Optional[str] = None
    descricao: Optional[str] = None
    descricao_es: Optional[str] = None
    icone: Optional[str] = None
    secao_id: Optional[int] = None
    url: Optional[str] = None
    tipo_acesso: Optional[str] = None
    tipo_conteudo: Optional[str] = None
    badge: Optional[str] = None
    ordem: Optional[int] = None


def _check_tipo_acesso(tipo: Optional[str]) -> None:
    # "interno" = tela nativa do próprio SPA do portal (ex.: Projetos IA), sem
    # iframe nem nova aba — o front reconhece esse tipo em `openApp()`.
    if tipo is not None and tipo not in ("url", "iframe", "interno"):
        raise HTTPException(400, "tipo_acesso deve ser 'url', 'iframe' ou 'interno'")


def _check_tipo_conteudo(tipo: Optional[str]) -> None:
    # O QUE o app é, não como abre. Separa os dois grupos do menu do portal:
    # 'indicador' = painel de acompanhamento, 'sistema' = aplicação/ferramenta.
    if tipo is not None and tipo not in ("indicador", "sistema"):
        raise HTTPException(400, "tipo_conteudo deve ser 'indicador' ou 'sistema'")


def _check_url(url: Optional[str]) -> None:
    if url is None:
        return
    if not url.startswith(("http://", "https://", "/")):
        raise HTTPException(
            400, "url deve começar com http://, https:// ou / (caminho relativo do próprio portal)"
        )


def _normalizar_url_interna(url: Optional[str], tipo_acesso: Optional[str]) -> Optional[str]:
    """Garante a barra no fim de app embutido que aponta pra uma pasta do portal.

    Sem a barra, o StaticFiles responde um redirect pra versão com barra — e o
    navegador se recusa a emoldurar o destino, porque atrás do ALB aquele redirect
    saía como `http://` e batia no `frame-src` do CSP. Foi o que derrubou o
    mapa-estatistico em 21/08/2026. O `--forwarded-allow-ips` do Dockerfile
    conserta o esquema; isto evita o redirect inútil e o cadastro que convida ao
    erro de novo.

    Só toca em `iframe`: em `url` a barra é indiferente e em `interno` o campo é
    só um identificador de tela do SPA, não um caminho.
    """
    if tipo_acesso != "iframe" or not url:
        return url
    if not url.startswith("/") or url.endswith("/"):
        return url
    if "?" in url or "#" in url:  # tem query/fragmento: não é caminho de pasta
        return url
    if "." in url.rsplit("/", 1)[-1]:  # aponta pra um arquivo, não pra pasta
        return url
    return url + "/"


_APP_COM_SECAO = (
    select(
        *App.__table__.c,
        Secao.slug.label("secao_slug"),
        Secao.nome.label("secao_nome"),
    )
    .join_from(App, Secao, Secao.id == App.secao_id)
)


def _select_app(session, app_id: int) -> dict:
    row = session.execute(
        _APP_COM_SECAO.where(App.id == app_id)
    ).mappings().fetchone()
    if not row:
        raise HTTPException(404, f"app {app_id} não encontrado")
    return dict(row)


@router_admin.get("/apps")
def listar_apps(_: dict = Depends(require_admin)):
    with db() as session:
        rows = session.execute(
            _APP_COM_SECAO.order_by(Secao.ordem, App.ordem, App.nome)
        ).mappings().fetchall()
    return [dict(r) for r in rows]


@router_admin.post("/apps", status_code=201)
def criar_app(body: AppCreate, request: Request, admin: dict = Depends(require_admin)):
    ensure_slug(body.slug)
    _check_tipo_acesso(body.tipo_acesso)
    _check_tipo_conteudo(body.tipo_conteudo)
    _check_url(body.url)
    url = _normalizar_url_interna(body.url, body.tipo_acesso)
    with db() as session:
        row_or_404(session, Secao, body.secao_id, "secoes")
        with unique_or_409("slug", body.slug):
            cur = session.execute(
                insert(App).values(
                    slug=body.slug, nome=body.nome, nome_es=body.nome_es,
                    descricao=body.descricao, descricao_es=body.descricao_es,
                    icone=body.icone, secao_id=body.secao_id, url=url,
                    tipo_acesso=body.tipo_acesso, tipo_conteudo=body.tipo_conteudo,
                    badge=body.badge, ordem=body.ordem,
                )
            )
        app_id = cur.inserted_primary_key[0]
        auditoria_service.registrar(
            session, categoria="admin", acao="app.criar", resultado="ok",
            ator=admin, ator_ip=_ip(request), app_slug=body.slug,
            alvo_tipo="app", alvo_id=app_id, alvo_rotulo=body.slug,
            detalhes=body.model_dump(),
        )
        return _select_app(session, app_id)


@router_admin.patch("/apps/{app_id}")
def atualizar_app(app_id: int, body: AppUpdate, request: Request, admin: dict = Depends(require_admin)):
    _check_tipo_acesso(body.tipo_acesso)
    _check_tipo_conteudo(body.tipo_conteudo)
    _check_url(body.url)
    with db() as session:
        atual = row_or_404(session, App, app_id, "apps")
        if body.secao_id is not None:
            row_or_404(session, Secao, body.secao_id, "secoes")
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            return _select_app(session, app_id)
        if "url" in fields:
            # tipo_acesso pode não vir no PATCH — vale o que já está gravado.
            fields["url"] = _normalizar_url_interna(
                fields["url"], fields.get("tipo_acesso") or atual["tipo_acesso"]
            )
        apply_update(session, App, app_id, fields, touch_updated=True)
        auditoria_service.registrar(
            session, categoria="admin", acao="app.atualizar", resultado="ok",
            ator=admin, ator_ip=_ip(request), app_slug=atual["slug"],
            alvo_tipo="app", alvo_id=app_id, alvo_rotulo=atual["slug"],
            detalhes=auditoria_service.diff(atual, fields),
        )
        return _select_app(session, app_id)


@router_admin.post("/apps/{app_id}/toggle")
def toggle_app(app_id: int, request: Request, admin: dict = Depends(require_admin)):
    with db() as session:
        row = row_or_404(session, App, app_id, "apps")
        novo = 0 if row["ativo"] else 1
        session.execute(
            update(App).where(App.id == app_id).values(ativo=novo, atualizado_em=_now())
        )
        auditoria_service.registrar(
            session, categoria="admin", acao="app.toggle", resultado="ok",
            ator=admin, ator_ip=_ip(request), app_slug=row["slug"],
            alvo_tipo="app", alvo_id=app_id, alvo_rotulo=row["slug"],
            detalhes={"ativo": {"de": bool(row["ativo"]), "para": bool(novo)}},
        )
        return _select_app(session, app_id)
