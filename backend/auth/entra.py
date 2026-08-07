"""
Provedor SSO: Microsoft Entra ID — fluxo OIDC (Authorization Code), o backend
conduz o redirecionamento (Degrau 3 de `docs/ROADMAP_EVOLUCAO.md`).

Em resumo:
  1. o front manda o usuário para `authorization_url()` (a tela do Microsoft);
  2. o Microsoft autentica e volta para a rota de callback com um `code`;
  3. `exchange_code()` troca o code pelos tokens e devolve os CLAIMS do
     id_token já validados pelo MSAL (assinatura, emissor/tenant e
     audiência/client id) — ou `None` se o Microsoft recusou;
  4. a rota resolve/cria o usuário pelo e-mail (`backend/auth/provisioning.py`)
     e emite o NOSSO JWT de sempre. Daqui pra frente nada muda: RBAC, `/me` e
     o resto do sistema seguem idênticos ao login local.

Fica DORMENTE até os `ENTRA_*` abaixo estarem todos preenchidos (ver
`sso_enabled()`) — enquanto isso, `/api/auth/login/entra` e `/api/auth/callback`
devolvem 501 e o botão nem aparece no front. O `msal` é importado de forma
preguiçosa (dentro do método) para o módulo poder ser importado mesmo com o
SSO desligado, sem exigir a biblioteca instalada em quem só usa login local.
"""
import os

ENTRA_TENANT_ID = os.environ.get("ENTRA_TENANT_ID", "").strip()
ENTRA_CLIENT_ID = os.environ.get("ENTRA_CLIENT_ID", "").strip()
ENTRA_CLIENT_SECRET = os.environ.get("ENTRA_CLIENT_SECRET", "").strip()
ENTRA_REDIRECT_URI = os.environ.get("ENTRA_REDIRECT_URI", "").strip()

# Grupo do Entra que pode logar (opcional). Vazio = libera todo o tenant
# (o registro do app já restringe a "somente locatário único").
ENTRA_ALLOWED_GROUP_ID = os.environ.get("ENTRA_ALLOWED_GROUP_ID", "").strip()

_AUTHORITY = "https://login.microsoftonline.com/{tenant}"

# Escopo OIDC mínimo, sem tocar no Microsoft Graph. openid/profile/offline_access
# são RESERVADOS: o MSAL os adiciona sozinho e ERRA se vierem aqui — pedimos só
# 'email' (o claim que `provisioning.py` usa pra achar/criar o usuário).
_SCOPES = ["email"]


def sso_enabled() -> bool:
    """Liga só quando os 4 segredos do Entra estão preenchidos no ambiente."""
    return all((ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_REDIRECT_URI))


class EntraAuthProvider:
    def _client(self):
        import msal

        return msal.ConfidentialClientApplication(
            client_id=ENTRA_CLIENT_ID,
            authority=_AUTHORITY.format(tenant=ENTRA_TENANT_ID),
            client_credential=ENTRA_CLIENT_SECRET,
        )

    def authorization_url(self, state: str) -> str:
        """URL do Microsoft para onde mandamos o usuário autenticar (carrega o `state` anti-CSRF)."""
        return self._client().get_authorization_request_url(
            _SCOPES,
            state=state,
            redirect_uri=ENTRA_REDIRECT_URI,
        )

    def exchange_code(self, code: str) -> dict | None:
        """Troca o `code` da volta pelos tokens e devolve os claims do id_token
        já validados pelo MSAL — ou `None` se o Microsoft recusou ou o token não veio."""
        result = self._client().acquire_token_by_authorization_code(
            code,
            scopes=_SCOPES,
            redirect_uri=ENTRA_REDIRECT_URI,
        )
        if not result or "error" in result:
            return None
        return result.get("id_token_claims") or None
