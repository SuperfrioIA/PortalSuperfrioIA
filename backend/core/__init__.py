"""Core — infra compartilhada da plataforma (banco, migrations, rate limit, helpers HTTP).

Não é um módulo de domínio: não tem tabelas nem regras de negócio próprias.
Todos os módulos podem importar do core; o core nunca importa de módulo de
domínio (exceção: env.py das migrations, que agrega os models pro Alembic).
"""
