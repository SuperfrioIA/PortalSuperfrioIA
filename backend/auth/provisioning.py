"""
Provisionamento de usuário a partir dos claims do Entra ID (Degrau 3 do roadmap).

Política (revisada em 2026-08-21, depois do primeiro teste com gente real):
  - quem entra pode ser restringido por grupo do Entra (opcional, via
    `ENTRA_ALLOWED_GROUP_ID` em `backend/auth/entra.py`) — sem grupo
    configurado, libera todo o tenant (o app já é single-tenant no registro);
  - **cadastro prévio é obrigatório por padrão**: e-mail sem cadastro no Hub é
    recusado (`RECUSA_SEM_CADASTRO`) e nada é gravado. `ENTRA_AUTO_PROVISION=1`
    religa a criação na hora (JIT), sem nenhuma role, com o admin concedendo
    acesso depois na tela de Administração que já existe;
  - **cadastro desativado é recusa, nunca recriação.** A busca inclui inativos
    de propósito: com o `apenas_ativos=True` do default, um usuário desativado
    ficava invisível aqui e o código concluía "usuário novo", tentando inserir
    de novo e estourando o UNIQUE de `username` — 500 em produção em
    2026-08-21. Além da tela quebrada, o bloqueio dependia da constraint do
    banco em vez da nossa regra: com um `username` diferente (e-mail alterado
    no Entra, por exemplo) o acesso voltaria sozinho num segundo cadastro.

Só orquestra: a leitura/escrita na tabela de usuários é sempre via
`backend.usuarios.service` (regra de ouro do CONTRIBUTING.md — este módulo
não é o dono da tabela `usuarios`).
"""
from backend.usuarios import service as usuarios_service

# Ordem de preferência pra achar o e-mail nos claims. Nem todo tenant emite
# `email`; `preferred_username`/`upn` são os fallbacks usuais do Entra.
_EMAIL_CLAIMS = ("email", "preferred_username", "upn")

# Resultado de `resolve_user`. São strings, não exceções, porque nenhum desses
# casos é erro de programa: são recusas previstas, e cada uma vira uma mensagem
# própria na tela de login (o front lê o código em `#sso_erro=`).
OK = "ok"
RECUSA_SEM_EMAIL = "sem_email"
RECUSA_FORA_DO_GRUPO = "fora_do_grupo"
RECUSA_SEM_CADASTRO = "sem_cadastro"
RECUSA_DESATIVADO = "desativado"


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


def resolve_user(
    session, claims: dict, allowed_group_id: str, auto_provision: bool = False
) -> tuple[dict | None, str]:
    """Resolve o usuário a partir dos claims do Entra.

    Devolve `(usuario, OK)` quando pode entrar e `(None, RECUSA_*)` quando não —
    o motivo existe para a rota mostrar à pessoa o que fazer ("peça acesso ao
    administrador" é diferente de "seu acesso foi desativado").
    """
    email = email_from_claims(claims)
    if email is None:
        return None, RECUSA_SEM_EMAIL
    if not is_group_allowed(claims, allowed_group_id):
        return None, RECUSA_FORA_DO_GRUPO

    # apenas_ativos=False de propósito — ver a docstring do módulo.
    user = usuarios_service.por_email(session, email, apenas_ativos=False)
    if user is not None:
        if not user["ativo"]:
            return None, RECUSA_DESATIVADO
        return user, OK

    if not auto_provision:
        return None, RECUSA_SEM_CADASTRO

    novo = usuarios_service.provisionar_usuario_ad(session, email, claims.get("name"))
    # `None` aqui só acontece na corrida de dois primeiros logins simultâneos em
    # que o cadastro vencedor ainda não commitou — a pessoa tenta de novo e entra.
    return (novo, OK) if novo is not None else (None, RECUSA_SEM_CADASTRO)
