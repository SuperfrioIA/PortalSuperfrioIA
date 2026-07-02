"""Auth — senhas (bcrypt), tokens (JWT) e o boundary de autenticação.

Não tem tabela própria: o usuário mora no módulo Usuários e é consultado via
`usuarios.service`. Quando vier SSO (Entra/AD, Degrau 3), este módulo é o
único ponto que muda.
"""
