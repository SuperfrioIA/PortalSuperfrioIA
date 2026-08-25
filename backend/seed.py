"""Seed inicial da plataforma — orquestra o seed de cada módulo, numa transação só.

Idempotente: cada módulo insere apenas o que não existe. A ordem importa
(usuários referenciam apps via roles → portal primeiro). O catálogo de filiais
não depende de ninguém e nada depende dele no boot.
"""
from backend.core.database import db, init_db
from backend.portal import seed as portal_seed
from backend.projetos_ia import seed as projetos_ia_seed
from backend.usuarios import seed as usuarios_seed


def seed_initial() -> None:
    with db() as session:
        apps_criados = portal_seed.seed(session)
        projetos_ia_seed.seed(session)
        # `apps_criados` existe para o grant inicial de `ver` de app que nasce
        # visível para todo mundo (ver `_VER_PARA_TODAS_AS_ROLES`).
        usuarios_seed.seed(session, apps_criados=apps_criados)
        # commit e close ficam a cargo do context manager db()


if __name__ == "__main__":
    # `python -m backend.seed` — usado no deploy pra (re)seedar um banco do zero
    # (ex.: Postgres novo no Lote 2). init_db é idempotente; roda migrations até
    # head antes de semear, então funciona mesmo standalone.
    init_db()
    seed_initial()
    print("[seed] concluído.")
