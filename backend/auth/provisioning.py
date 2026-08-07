"""
Provisionamento de usuário a partir dos claims do Entra ID (Degrau 3 do roadmap).

Política:
  - quem entra pode ser restringido por grupo do Entra (opcional, via
    `ENTRA_ALLOWED_GROUP_ID` em `backend/auth/entra.py`) — sem grupo
    configurado, libera todo o tenant (o app já é single-tenant no registro);
  - usuário novo é criado na hora (JIT) sem nenhuma role — o admin concede
    acesso depois, na tela de Administração que já existe;
  - usuário já cadastrado com o mesmo e-mail (local ou de um login SSO
    anterior) é reaproveitado, mantendo as roles que já tinha.

Só orquestra: a leitura/escrita na tabela de usuários é sempre via
`backend.usuarios.service` (regra de ouro do CONTRIBUTING.md — este módulo
não é o dono da tabela `usuarios`).
"""
from backend.usuarios import service as usuarios_service

# Ordem de preferência pra achar o e-mail nos claims. Nem todo tenant emite
# `email`; `preferred_username`/`upn` são os fallbacks usuais do Entra.
_EMAIL_CLAIMS = ("email", "preferred_username", "upn")


def email_from_claims(claims: dict) -> str | None:
    """Extrai o e-mail/UPN dos claims, normalizado (minúsculas/sem espaços). None se não houver."""
    for key in _EMAIL_CLAIMS:
        value = claims.get(key)
        if value:
            return str(value).strip().lower()
    return None


def is_group_allowed(claims: dict, allowed_group_id: str) -> bool:
    """Sem grupo exigido (`allowed_group_id` vazio) → libera todos. Com grupo
    exigido → o id precisa estar no claim `groups` do token."""
    if not allowed_group_id:
        return True
    return allowed_group_id in (claims.get("groups") or [])


def resolve_user(session, claims: dict, allowed_group_id: str) -> dict | None:
    """Resolve o usuário a partir dos claims — `None` quando o acesso não é
    permitido (a rota traduz para 403). Cria na hora (JIT) se passar as regras."""
    email = email_from_claims(claims)
    if email is None or not is_group_allowed(claims, allowed_group_id):
        return None

    user = usuarios_service.por_email(session, email)
    if user is not None:
        return user
    return usuarios_service.provisionar_usuario_ad(session, email, claims.get("name"))
