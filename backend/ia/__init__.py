"""SuperfrioIA — perguntas aos dados do Hub em linguagem natural (Lote 2).

Capacidade **nativa** do Hub, atrás da chave `IA_HABILITADO` (padrão desligada).
Desenho em `docs/ARQUITETURA_SUPERFRIOIA_MCP.md`; decisões em
`docs/DECISOES_SUPERFRIOIA.md`; plano em `docs/PLANO_LOTES_SUPERFRIOIA.md`.

Neste lote só existe o **modo A** (indicador pronto): a IA chama a função que a
tela já chama (`backend/volumetria_catering/service.py`), repete o número que
volta e nunca faz conta. O provedor é de teste: sem rede e sem chave.

Importar qualquer submódulo registra a chave no portal, para o card sumir quando
`IA_HABILITADO` está desligada (DD-27). O portal não conhece este módulo: ele só
oferece o gancho `registrar_chave_de_app`.
"""
from backend.ia import config
from backend.portal import service as _portal_service

_portal_service.registrar_chave_de_app(config.SLUG_APP, config.habilitado)
