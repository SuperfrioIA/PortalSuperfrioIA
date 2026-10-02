"""Permissões do módulo Volumetria de Catering.

`ver` não aparece aqui: é implícita para todo app cadastrado e mora em
`role_apps` (ver `backend/core/permissoes.py`). É ela que libera a consulta —
Matriz, planilha e opções de filtro exigem login + `ver` do app.

`exportar`: baixar o recorte em CSV/xlsx. Na tela antiga (V3, porta 8003) o
download era liberado para qualquer pessoa logada; aqui ele passa a ser uma
célula da matriz de acesso, que foi um dos motivos de trazer a tela para o Hub.

`administrar` (SuperfrioIA, DD-13): aprovar e revogar a **concessão de IA** deste
domínio. Alcance fechado, documentado em `docs/DECISOES_SUPERFRIOIA.md`:

- **autoriza**, só para o domínio `volumetria-catering` no SuperfrioIA: ver a fila
  de pedidos, aprovar ou negar com motivo, definir a validade, ver as concessões
  (vigentes, vencidas, revogadas) e revogar;
- **não autoriza**: dar ou tirar o `ver` do app, exportar, ler conversas de
  outros usuários, alterar o contrato do domínio, cotas ou a chave
  `IA_HABILITADO`, nem aprovar concessão de qualquer outro domínio.

A concessão sozinha também não libera consulta: o usuário precisa ter `ver`.
Quem a recebe é configurado na matriz de acesso, numa role própria — não por seed.

**Atenção ao montar a role do aprovador:** a fila de pedidos vive na tela do SuperfrioIA, e
toda rota de `/api/ia` exige `superfrioia:ver` (a visibilidade do card). Então a role
"Aprovador IA — Volumetria de Catering" precisa de **`superfrioia:ver` + `administrar`**;
só `administrar` devolve 403 na fila. Ela NÃO precisa de `volumetria-catering:ver`.
"""
from backend.core.permissoes import registrar_modulo

APP_SLUG = "volumetria-catering"

PERMISSOES = registrar_modulo(
    APP_SLUG,
    nome="Volumetria de Catering",
    acoes={
        "exportar": (
            "Baixar o recorte da volumetria de catering em CSV ou xlsx — a linha "
            "inteira do DW, no recorte dos filtros da tela. Consultar a Matriz e a "
            "planilha exige só o acesso ao app."
        ),
        "administrar": (
            "Aprovar, negar e revogar pedidos de acesso do SuperfrioIA a este "
            "domínio (a concessão de IA). Não dá nem tira o acesso ao app, não "
            "exporta e não altera o contrato do domínio."
        ),
    },
)

EXPORTAR = f"{APP_SLUG}:exportar"
ADMINISTRAR = f"{APP_SLUG}:administrar"
