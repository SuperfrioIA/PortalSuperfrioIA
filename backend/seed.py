"""Seed inicial da plataforma — orquestra o seed de cada módulo, numa transação só.

Idempotente: cada módulo insere apenas o que não existe. A ordem importa
(usuários referenciam apps via roles → portal primeiro).
"""
from backend.core.database import db, init_db
from backend.portal import seed as portal_seed
from backend.usuarios import seed as usuarios_seed


def seed_initial() -> None:
    with db() as session:
        portal_seed.seed(session)
        usuarios_seed.seed(session)
        # commit e close ficam a cargo do context manager db()


if __name__ == "__main__":
    # `python -m backend.seed` — usado no deploy pra (re)seedar um banco do zero
    # (ex.: Postgres novo no Lote 2). init_db é idempotente; roda migrations até
    # head antes de semear, então funciona mesmo standalone.
    init_db()
    seed_initial()
    print("[seed] concluído.")
