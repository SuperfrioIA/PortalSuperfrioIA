import logging
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from backend.auditoria import service as auditoria_service
from backend.auth import entra as entra_module
from backend.auth.dependencies import get_current_user, get_current_user_optional
from backend.auth.provisioning import resolve_user as resolve_user_entra
from backend.auth.service import authenticate_user, create_access_token
from backend.core.database import db
from backend.core.limiter import limiter
from backend.usuarios import service as usuarios_service


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None

logger = logging.getLogger("backend.auth.router")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Cookie temporário que liga o início do SSO à volta (callback): guarda o
# `state` anti-CSRF entre os dois passos do redirecionamento.
_STATE_COOKIE = "sf_entra_state"


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form.username, form.password)
    if not user:
        auditoria_service.registrar(
            categoria="auth", acao="login.falha", resultado="negado",
            ator_ip=_ip(request),
            detalhes={"username_tentado": form.username.strip().lower()},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos",
        )
    auditoria_service.registrar(
        categoria="auth", acao="login.ok", resultado="ok", ator=user, ator_ip=_ip(request),
    )
    token = create_access_token(
        subject=user["username"],
        extra={
            "is_admin": bool(user["is_admin"]),
            "nome": user["nome"],
            "tv": user.get("token_version", 1),
        },
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "nome": user["nome"],
            "email": user["email"],
            "is_admin": bool(user["is_admin"]),
        },
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: dict | None = Depends(get_current_user_optional)):
    """Encerramento de sessão do lado do servidor — hoje só grava o evento.

    Best-effort: aceita token ausente ou já vencido (`get_current_user_optional`
    devolve `None` nesses casos) e sempre responde 204. O frontend chama isto
    ANTES de limpar o `localStorage`; não há nada para revogar no servidor além
    do rastro (o `token_version` já cobre revogação de sessão)."""
    if user:
        auditoria_service.registrar(
            categoria="auth", acao="logout", resultado="ok", ator=user, ator_ip=_ip(request),
        )


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "username": user["username"],
        "nome": user["nome"],
        "email": user["email"],
        "is_admin": bool(user["is_admin"]),
    }


@router.get("/me/permissoes")
def minhas_permissoes(user: dict | None = Depends(get_current_user_optional)) -> dict:
    """Tudo que o usuário logado pode fazer, num endpoint só.

    Substitui os `/<app>/pode-editar` escritos um por app: qualquer tela (inclusive
    os apps embutidos por iframe) pergunta aqui e checa
    `permissoes.includes("<app>:<acao>")`.

    Nunca devolve 401/403 — anônimo recebe listas vazias, do mesmo jeito que o
    `pode-editar` antigo fazia. Isso é proposital: os apps estáticos são servidos
    sem login (limitação conhecida, ver docs/PERMISSIONAMENTO_HOJE.md), então eles
    precisam conseguir perguntar antes de saber se há sessão.

    Admin recebe a lista expandida em vez de um sinalizador, para o frontend não
    precisar tratar admin como caso especial.
    """
    if not user:
        return {"autenticado": False, "is_admin": False, "permissoes": []}

    with db() as session:
        if user.get("is_admin"):
            permissoes = usuarios_service.todas_permissoes(session)
        else:
            permissoes = usuarios_service.permissoes_do_usuario(session, user["id"])

    return {
        "autenticado": True,
        "is_admin": bool(user["is_admin"]),
        "permissoes": sorted(permissoes),
    }


# --------------------------------------------------------------------------- #
# SSO — Microsoft Entra ID (Degrau 3 de docs/ROADMAP_EVOLUCAO.md). Tudo aqui
# fica DORMENTE enquanto `sso_enabled()` for falso (ENTRA_* vazios no
# ambiente): as rotas respondem 501 e o botão nem aparece no front. O login
# local segue intacto — inclusive como acesso de emergência do admin.
# --------------------------------------------------------------------------- #
@router.get("/config")
def sso_config() -> dict:
    """Diz ao front, ANTES do login, se o botão Microsoft deve aparecer."""
    return {"sso_enabled": entra_module.sso_enabled()}


def _require_sso() -> None:
    if not entra_module.sso_enabled():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Login com Microsoft (SSO Entra ID) não está habilitado.",
        )


def _voltar_para_login(motivo: str) -> RedirectResponse:
    """Recusa de SSO devolvida como REDIRECT, não como JSON de erro.

    Antes cada recusa era um `raise HTTPException(...)`, o que pintava uma tela
    branca de JSON no meio de uma navegação de topo. E o caso mais comum não era
    nem erro de verdade: bastava a pessoa apertar **Voltar** no navegador para o
    browser reexecutar esta URL com um `code` já usado e sem o cookie de state
    (400 em produção em 2026-08-21, com a sessão dela intacta).

    Agora o front recebe `/#sso_erro=<motivo>`, mostra a mensagem certa na tela
    de login — e quem já tinha sessão volta pro portal sem ver nada. O motivo
    também vai pro log do servidor, para uma recusa real não ficar silenciosa.
    """
    resp = RedirectResponse(
        f"/#sso_erro={motivo}", status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    resp.delete_cookie(_STATE_COOKIE)
    return resp


@router.get("/login/entra")
def login_entra():
    """Inicia o SSO: gera o `state` anti-CSRF e redireciona o usuário ao Microsoft."""
    _require_sso()
    state = secrets.token_urlsafe(32)
    url = entra_module.EntraAuthProvider().authorization_url(state)
    resp = RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    resp.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",  # sobrevive ao retorno (navegação top-level) vindo do Microsoft
        secure=os.environ.get("SUPERFRIO_ENV", "dev").lower() == "prod",
    )
    return resp


@router.get("/callback")
def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Volta do Microsoft: confere o `state`, troca o `code` pelos claims,
    resolve o usuário e emite o NOSSO JWT — daqui pra frente o sistema é
    idêntico ao login local.

    Nenhuma recusa aqui vira 4xx: todas voltam pro front por
    `_voltar_para_login()`, porque esta rota é sempre uma navegação de topo do
    navegador (ver a docstring de lá)."""
    _require_sso()
    if error:
        logger.warning("SSO: Microsoft recusou o login (%s)", error)
        auditoria_service.registrar(
            categoria="auth", acao="sso.recusado", resultado="negado", ator_ip=_ip(request),
            detalhes={"motivo": "microsoft"},
        )
        return _voltar_para_login("microsoft")

    expected = request.cookies.get(_STATE_COOKIE)
    if not (code and state and expected and secrets.compare_digest(state, expected)):
        # Quase sempre é o Voltar do navegador reexecutando o callback; pode ser
        # também cookie bloqueado ou um CSRF de verdade. O log distingue: sem
        # cookie e sem state = navegação repetida; state adulterado = suspeito.
        logger.warning(
            "SSO: callback sem state válido (code=%s, state=%s, cookie=%s)",
            bool(code), bool(state), bool(expected),
        )
        auditoria_service.registrar(
            categoria="auth", acao="sso.recusado", resultado="negado", ator_ip=_ip(request),
            detalhes={"motivo": "sessao"},
        )
        return _voltar_para_login("sessao")

    claims = entra_module.EntraAuthProvider().exchange_code(code)
    if claims is None:
        logger.warning("SSO: o Microsoft não validou a troca do code")
        auditoria_service.registrar(
            categoria="auth", acao="sso.recusado", resultado="negado", ator_ip=_ip(request),
            detalhes={"motivo": "microsoft"},
        )
        return _voltar_para_login("microsoft")

    with db() as session:
        user, motivo = resolve_user_entra(
            session,
            claims,
            entra_module.ENTRA_ALLOWED_GROUP_ID,
            auto_provision=entra_module.ENTRA_AUTO_PROVISION,
        )
        if user is None:
            logger.warning("SSO: acesso recusado (%s)", motivo)
            auditoria_service.registrar(
                session, categoria="auth", acao="sso.recusado", resultado="negado",
                ator_ip=_ip(request), detalhes={"motivo": motivo},
            )
            return _voltar_para_login(motivo)
        auditoria_service.registrar(
            session, categoria="auth", acao="sso.ok", resultado="ok",
            ator=user, ator_ip=_ip(request),
        )
        token = create_access_token(
            subject=user["username"],
            extra={
                "is_admin": bool(user["is_admin"]),
                "nome": user["nome"],
                "tv": user.get("token_version", 1),
            },
        )

    # Devolve a sessão ao front pelo FRAGMENTO da URL (#sso_token=...): fragmentos
    # não são enviados ao servidor nem caem em logs/histórico de proxy.
    redirect = RedirectResponse(
        f"/#sso_token={token}", status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )
    redirect.delete_cookie(_STATE_COOKIE)
    return redirect
