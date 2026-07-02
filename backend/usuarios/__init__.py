"""Usuários — contas, roles e vínculos de permissão (quem vê o quê).

Dono das tabelas `usuarios`, `roles`, `usuario_roles` e `role_apps` (o grant
role→app pertence ao domínio de permissões; `apps` em si é do Portal).
Outros módulos acessam usuários/permissões SÓ via `backend.usuarios.service`.
"""
