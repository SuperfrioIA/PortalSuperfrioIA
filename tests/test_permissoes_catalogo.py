"""Catálogo de permissões, matriz de acesso e o efeito de `roles.ativo`.

Complementa `test_permissoes.py` (que cobre require_admin e o filtro da home) e
`test_processos_abertos.py` (que cobre a permissão de escrita ponta a ponta).

Cada teste cria as próprias roles/usuários com slug dedicado: o banco é
compartilhado pela sessão inteira.
"""
import pytest
from sqlalchemy import select, text

from backend.auth.dependencies import require_permissao
from backend.core import permissoes as catalogo
from backend.core.database import db
from backend.usuarios.models import role_permissoes


# ============ Catálogo em código ============

def test_catalogo_tem_a_permissao_do_processos_abertos():
    assert catalogo.existe("processos-abertos:editar")
    p = catalogo.obter("processos-abertos:editar")
    assert p.app_slug == "processos-abertos"
    assert p.acao == "editar"
    assert p.modulo == "Processos Abertos"
    assert p.descricao  # a tela mostra isso — não pode ser vazio


def test_catalogo_sem_slug_duplicado():
    slugs = [p.slug for p in catalogo.listar()]
    assert len(slugs) == len(set(slugs))


def test_toda_permissao_tem_acao_do_vocabulario():
    for p in catalogo.listar():
        assert p.acao in catalogo.ACOES_MODULO
        assert p.slug == f"{p.app_slug}:{p.acao}"


def test_todo_modulo_esta_no_agregador():
    """`backend/permissoes.py` precisa importar todo módulo que declara permissão,
    senão a matriz da tela nasce incompleta em ambientes que não importam o router."""
    import backend.permissoes as agregador

    declarados = {m.__name__.rsplit(".", 2)[-2] for m in agregador._MODULOS}
    usados = {p.app_slug.replace("-", "_") for p in catalogo.listar()}
    assert usados <= declarados, f"módulo fora do agregador: {usados - declarados}"


# ============ Falha explícita: permissão inexistente ou mal catalogada ============

def test_require_permissao_com_slug_inexistente_estoura_na_definicao():
    """O ponto central da mudança: slug errado derruba o boot (é aqui que o router
    chamaria require_permissao), em vez de virar 403 silencioso em produção."""
    with pytest.raises(KeyError) as exc:
        require_permissao("processos-abertos:aprovar")
    assert "não existe no catálogo" in str(exc.value)


def test_registrar_acao_fora_do_vocabulario_estoura():
    with pytest.raises(ValueError, match="não existe no vocabulário"):
        catalogo.registrar_modulo("app-de-teste", nome="X", acoes={"aprovar": "..."})
    assert not catalogo.existe("app-de-teste:aprovar")


def test_registrar_ver_estoura_porque_ver_e_implicita():
    with pytest.raises(ValueError, match="implícita"):
        catalogo.registrar_modulo("outro-app-teste", nome="X", acoes={"ver": "..."})


def test_acao_invalida_no_meio_nao_registra_as_validas():
    """Registro é atômico: nada de catálogo meio populado."""
    with pytest.raises(ValueError):
        catalogo.registrar_modulo(
            "app-parcial", nome="X", acoes={"editar": "ok", "aprovar": "inválida"}
        )
    assert not catalogo.existe("app-parcial:editar")


def test_modulo_duplicado_estoura():
    with pytest.raises(RuntimeError, match="já registrou"):
        catalogo.registrar_modulo(
            "processos-abertos", nome="Cópia", acoes={"exportar": "..."}
        )


def test_api_recusa_permissao_fora_do_catalogo(client, admin_headers):
    r = client.post(
        "/api/admin/roles",
        json={"slug": "role-perm-ruim", "nome": "X", "permissoes": ["nao-existe:editar"]},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert "inexistente" in r.json()["detail"]


# ============ roles.ativo corta acesso nas DUAS metades da matriz ============

def _cria_usuario_com_role(client, admin_headers, *, username, role_slug, apps, permissoes):
    r = client.post(
        "/api/admin/roles",
        json={"slug": role_slug, "nome": role_slug, "apps": apps, "permissoes": permissoes},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    role_id = r.json()["id"]
    r = client.post(
        "/api/admin/usuarios",
        json={"username": username, "senha": "senha-de-teste-123", "roles": [role_slug]},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/auth/login", data={"username": username, "password": "senha-de-teste-123"}
        ).json()["access_token"]
    }
    return role_id, headers


def test_role_inativa_nao_libera_apps(client, admin_headers):
    """O bug que existia: `app_ids_permitidos` ignorava `roles.ativo`, então
    desativar a role deixava a pessoa vendo os apps do mesmo jeito."""
    role_id, headers = _cria_usuario_com_role(
        client, admin_headers,
        username="teste.inativa.apps", role_slug="role-teste-inativa-apps",
        apps=["faq-slin"], permissoes=[],
    )

    apps = [a["slug"] for s in client.get("/api/portal/home", headers=headers).json()["secoes"]
            for a in s["apps"]]
    assert apps == ["faq-slin"]

    assert client.post(f"/api/admin/roles/{role_id}/toggle", headers=admin_headers).status_code == 200

    secoes = client.get("/api/portal/home", headers=headers).json()["secoes"]
    assert secoes == [], "role desativada continuou liberando app"


def test_role_inativa_nao_concede_permissao(client, admin_headers):
    role_id, headers = _cria_usuario_com_role(
        client, admin_headers,
        username="teste.inativa.perm", role_slug="role-teste-inativa-perm",
        apps=[], permissoes=["processos-abertos:editar"],
    )

    assert client.get("/api/auth/me/permissoes", headers=headers).json()["permissoes"] == [
        "processos-abertos:editar"
    ]

    client.post(f"/api/admin/roles/{role_id}/toggle", headers=admin_headers)

    assert client.get("/api/auth/me/permissoes", headers=headers).json()["permissoes"] == []
    r = client.post(
        "/api/processos-abertos/historico",
        json={"date": "01/02/2026", "total": 1, "d5p": 1, "d1": 0, "d25": 0, "pct": 1.0, "units": 1},
        headers=headers,
    )
    assert r.status_code == 403


# ============ Endpoint global de permissões ============

def test_minhas_permissoes_anonimo_nao_falha(client):
    r = client.get("/api/auth/me/permissoes")
    assert r.status_code == 200
    assert r.json() == {"autenticado": False, "is_admin": False, "permissoes": []}


def test_minhas_permissoes_usuario_comum(client, operador_headers):
    body = client.get("/api/auth/me/permissoes", headers=operador_headers).json()
    assert body["autenticado"] is True
    assert body["is_admin"] is False
    # armazem-full concede a coluna `ver` dos 3 apps do Armazém
    assert "faq-slin:ver" in body["permissoes"]
    assert "conciliafat:ver" not in body["permissoes"]


def test_minhas_permissoes_admin_recebe_lista_expandida(client, admin_headers):
    body = client.get("/api/auth/me/permissoes", headers=admin_headers).json()
    assert body["is_admin"] is True
    # admin não recebe um sinalizador: recebe tudo, pra o front usar includes()
    assert "processos-abertos:editar" in body["permissoes"]
    assert "faq-slin:ver" in body["permissoes"]


# ============ Matriz ============

def test_matriz_exige_admin(client, operador_headers):
    assert client.get("/api/admin/matriz").status_code == 401
    assert client.get("/api/admin/matriz", headers=operador_headers).status_code == 403


def test_matriz_tem_colunas_e_linhas(client, admin_headers):
    m = client.get("/api/admin/matriz", headers=admin_headers).json()

    assert [a["slug"] for a in m["acoes"]] == ["ver", "editar", "exportar", "administrar"]

    apps = {a["slug"]: a for s in m["secoes"] for a in s["apps"]}
    # todo app tem `ver`; só quem declarou tem as demais
    assert apps["faq-slin"]["acoes"] == ["ver"]
    assert apps["processos-abertos"]["acoes"] == ["ver", "editar"]
    assert m["descricoes"]["processos-abertos:editar"]


def test_matriz_sem_permissao_orfa(client, admin_headers):
    """Permissão declarada em código cujo app não está cadastrado neste ambiente.
    Não é erro (o cadastro é por ambiente), mas a tela precisa avisar."""
    m = client.get("/api/admin/matriz", headers=admin_headers).json()
    assert m["orfas"] == [], f"catálogo aponta para app inexistente: {m['orfas']}"


def test_nenhum_grant_orfao_no_banco():
    """Linha de `role_permissoes` apontando para permissão que saiu do catálogo.
    Como o slug é texto sem FK, este teste é a rede de proteção."""
    with db() as session:
        slugs = set(session.execute(select(role_permissoes.c.permissao_slug)).scalars())
    orfas = {s for s in slugs if not catalogo.existe(s)}
    assert not orfas, f"grants apontando pra permissão inexistente: {orfas}"


# ============ Migration 0002 ============

def test_backfill_da_migration_cobre_a_role_antiga(tmp_path):
    """Ambientes que já tinham a role `processos-abertos-editor` criada na mão (o
    mecanismo antigo, em que o slug da role era a permissão) recebem o grant
    equivalente ao subir a 0002 — ninguém perde acesso na virada.
    """
    import sqlite3

    from alembic import command

    from backend.core.database import _alembic_config

    caminho = tmp_path / "backfill.db"
    url = f"sqlite:///{caminho.as_posix()}"
    cfg = _alembic_config(url)

    command.upgrade(cfg, "0001")  # estado anterior a esta mudança
    conn = sqlite3.connect(caminho)
    conn.execute(
        "INSERT INTO roles (slug, nome, ativo) VALUES ('processos-abertos-editor', 'Editores', 1)"
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(caminho)
    try:
        grants = conn.execute(
            "SELECT permissao_slug FROM role_permissoes rp "
            "JOIN roles r ON r.id = rp.role_id WHERE r.slug = 'processos-abertos-editor'"
        ).fetchall()
    finally:
        conn.close()
    assert grants == [("processos-abertos:editar",)]


def test_migration_0002_sobe_e_desce(tmp_path):
    from alembic import command

    from backend.core.database import _alembic_config

    url = f"sqlite:///{(tmp_path / 'updown.db').as_posix()}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")


def test_role_criada_pela_api_grava_em_role_permissoes(client, admin_headers):
    r = client.post(
        "/api/admin/roles",
        json={
            "slug": "role-teste-grava-perm",
            "nome": "Grava",
            "permissoes": ["processos-abertos:editar"],
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["permissoes"] == ["processos-abertos:editar"]

    with db() as session:
        linhas = session.execute(
            text(
                "SELECT permissao_slug FROM role_permissoes rp "
                "JOIN roles r ON r.id = rp.role_id WHERE r.slug = :s"
            ),
            {"s": "role-teste-grava-perm"},
        ).scalars().all()
    assert linhas == ["processos-abertos:editar"]


def test_patch_role_troca_permissoes(client, admin_headers):
    rid = client.post(
        "/api/admin/roles",
        json={"slug": "role-teste-patch-perm", "nome": "P", "permissoes": ["processos-abertos:editar"]},
        headers=admin_headers,
    ).json()["id"]

    r = client.patch(
        f"/api/admin/roles/{rid}", json={"permissoes": []}, headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json()["permissoes"] == []
