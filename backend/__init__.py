"""Plataforma SuperFrio & Icestar — Modular Monolith.

Um app, um processo, um banco. Módulos:
- core/      infra compartilhada (banco, migrations Alembic, rate limit, helpers HTTP)
- auth/      senhas/JWT e o boundary de autenticação (futuro SSO Entra)
- usuarios/  contas, roles e vínculos de permissão
- portal/    catálogo de seções/apps + home

REGRA DE OURO: um módulo nunca lê a tabela/model de outro — só chama o
`service.py` do módulo dono. Routers podem orquestrar services de vários
módulos. Cobrar isso em code review (a fronteira é lógica, não do compilador).
"""
