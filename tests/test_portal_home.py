"""/api/portal/home separando indicadores de sistemas (`apps.tipo_conteudo`).

O menu do portal tem dois grupos e a divisão é feita no backend, não no front —
então é aqui que ela precisa ser provada. Testes de mutação criam a própria
entidade e a fixture apaga no fim, para o seed voltar intacto.
"""
import pytest
from sqlalchemy import text

from backend.core.database import db


@pytest.fixture(autouse=True)
def _restore_db():
    """Remove apps/seções criados pelo teste (mesmo padrão de test_admin_crud)."""
    tabelas = ["secoes", "apps"]
    with db() as conn:
        antes = {t: set(conn.execute(text(f"SELECT id FROM {t}")).scalars()) for t in tabelas}
    yield
    with db() as conn:
        for t in ["apps", "secoes"]:
            atuais = set(conn.execute(text(f"SELECT id FROM {t}")).scalars())
            for novo in atuais - antes[t]:
                conn.execute(text(f"DELETE FROM {t} WHERE id = :id"), {"id": novo})


def _home(client, headers):
    r = client.get("/api/portal/home", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _slugs_das_secoes(home):
    return {a["slug"] for s in home["secoes"] for a in s["apps"]}


def _id_por_slug(client, headers, recurso, slug):
    r = client.get(f"/api/admin/{recurso}", headers=headers)
    return next(x["id"] for x in r.json() if x["slug"] == slug)


# ============ A divisão ============

def test_home_separa_indicadores_de_sistemas(client, admin_headers):
    home = _home(client, admin_headers)
    indicadores = {a["slug"] for a in home["indicadores"]}

    # Os dois painéis do seed nascem indicador (migration 0006 + seed)
    assert {"processos-abertos", "integracao-in-out"} <= indicadores
    # e por isso NÃO podem aparecer também na grade de sistemas
    assert not (indicadores & _slugs_das_secoes(home))


def test_contagem_da_secao_nao_conta_indicador(client, admin_headers):
    home = _home(client, admin_headers)
    armazem = next(s for s in home["secoes"] if s["slug"] == "armazem")
    slugs = {a["slug"] for a in armazem["apps"]}
    assert "processos-abertos" not in slugs
    assert "integracao-in-out" not in slugs
    # sobra pelo menos um sistema na seção (senão o teste acima seria vazio)
    assert slugs


def test_apps_do_menu_fixo_viraram_catalogo(client, admin_headers):
    """Governance TI e Mapa IA saíram da sidebar e entraram no catálogo."""
    home = _home(client, admin_headers)
    tecnologia = next(s for s in home["secoes"] if s["slug"] == "tecnologia")
    apps = {a["slug"]: a for a in tecnologia["apps"]}
    assert {"governanca-ti", "mapa-ia"} <= apps.keys()
    # Embutidos no portal (não abrem em nova aba)
    assert apps["governanca-ti"]["tipo_acesso"] == "iframe"
    assert apps["mapa-ia"]["tipo_acesso"] == "iframe"
    # E são sistema, não indicador
    assert "governanca-ti" not in {a["slug"] for a in home["indicadores"]}


def test_governance_ti_nasce_visivel_para_role_existente(client, admin_headers):
    """Era botão fixo, visível a qualquer pessoa logada: virar app não pode tirar
    o acesso de quem não é admin. O grant vai para todas as roles que existiam na
    criação do app — role criada DEPOIS não recebe nada, e é assim de propósito
    (senão o seed desfaria a matriz a cada boot). Por isso a asserção olha as
    roles do seed, não um total que outro teste pode ter mexido."""
    with db() as conn:
        com_grant = {
            slug
            for (slug,) in conn.execute(
                text(
                    "SELECT r.slug FROM roles r "
                    "JOIN role_apps ra ON ra.role_id = r.id "
                    "JOIN apps a ON a.id = ra.app_id "
                    "WHERE a.slug = 'governanca-ti'"
                )
            )
        }
    assert {"armazem-full", "backoffice-full", "faq-leitor"} <= com_grant


def test_seed_nao_devolve_grant_revogado(client, admin_headers):
    """O grant do Governance TI vale UMA vez, na criação do app.

    Se o seed reconcedesse a cada boot, um administrador que tirasse o Governance
    TI de uma role veria a permissão voltar no próximo deploy — e não teria como
    saber por quê. `test_seed_idempotente` não pega isso: lá o vínculo existe nas
    duas contagens, então some com ou sem o gating por `apps_criados`."""
    from backend.seed import seed_initial

    with db() as conn:
        role_id, app_id = conn.execute(
            text(
                "SELECT ra.role_id, ra.app_id FROM role_apps ra "
                "JOIN apps a ON a.id = ra.app_id "
                "JOIN roles r ON r.id = ra.role_id "
                "WHERE a.slug = 'governanca-ti' AND r.slug = 'faq-leitor'"
            )
        ).one()
        conn.execute(
            text("DELETE FROM role_apps WHERE role_id = :r AND app_id = :a"),
            {"r": role_id, "a": app_id},
        )
    try:
        seed_initial()  # o app já existe → não entra em `apps_criados`
        with db() as conn:
            voltou = conn.execute(
                text("SELECT COUNT(*) FROM role_apps WHERE role_id = :r AND app_id = :a"),
                {"r": role_id, "a": app_id},
            ).scalar_one()
        assert voltou == 0, "seed reconcedeu um `ver` que o administrador revogou"
    finally:
        # Idempotente de propósito: se a asserção acima falhar é porque o vínculo
        # VOLTOU, e um INSERT cego aqui estouraria IntegrityError por cima do
        # AssertionError — escondendo o motivo real da falha.
        with db() as conn:
            existe = conn.execute(
                text("SELECT COUNT(*) FROM role_apps WHERE role_id = :r AND app_id = :a"),
                {"r": role_id, "a": app_id},
            ).scalar_one()
            if not existe:
                conn.execute(
                    text("INSERT INTO role_apps (role_id, app_id) VALUES (:r, :a)"),
                    {"r": role_id, "a": app_id},
                )


def test_mapa_ia_sem_grant_nenhum(client, admin_headers):
    """Sem `ver` em role nenhuma → só admin enxerga o card."""
    with db() as conn:
        com_grant = conn.execute(
            text(
                "SELECT COUNT(*) FROM role_apps ra "
                "JOIN apps a ON a.id = ra.app_id WHERE a.slug = 'mapa-ia'"
            )
        ).scalar_one()
    assert com_grant == 0


# ============ Cadastro (admin) ============

def test_criar_app_indicador_aparece_no_grupo_certo(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json={
            "slug": "painel-de-teste",
            "nome": "Painel de teste",
            "secao_id": sid,
            "url": "/painel-de-teste/",
            "tipo_acesso": "iframe",
            "tipo_conteudo": "indicador",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["tipo_conteudo"] == "indicador"

    home = _home(client, admin_headers)
    assert "painel-de-teste" in {a["slug"] for a in home["indicadores"]}
    assert "painel-de-teste" not in _slugs_das_secoes(home)


def test_app_sem_tipo_conteudo_nasce_sistema(client, admin_headers):
    """Default da coluna: quem cadastra app comum não precisa pensar nisso."""
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json={
            "slug": "app-sem-conteudo",
            "nome": "App sem conteúdo declarado",
            "secao_id": sid,
            "url": "https://example.internal/x",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201
    assert r.json()["tipo_conteudo"] == "sistema"


def test_criar_app_tipo_conteudo_invalido(client, admin_headers):
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    r = client.post(
        "/api/admin/apps",
        json={
            "slug": "app-conteudo-ruim",
            "nome": "X",
            "secao_id": sid,
            "url": "https://example.internal/x",
            "tipo_conteudo": "kpi",
        },
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_patch_reclassifica_app(client, admin_headers):
    """Trocar o grupo do app é edição de cadastro, não deploy."""
    sid = _id_por_slug(client, admin_headers, "secoes", "armazem")
    criado = client.post(
        "/api/admin/apps",
        json={
            "slug": "app-vira-indicador",
            "nome": "Vira indicador",
            "secao_id": sid,
            "url": "https://example.internal/y",
        },
        headers=admin_headers,
    ).json()
    assert criado["tipo_conteudo"] == "sistema"

    r = client.patch(
        f"/api/admin/apps/{criado['id']}",
        json={"tipo_conteudo": "indicador"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["tipo_conteudo"] == "indicador"

    home = _home(client, admin_headers)
    assert "app-vira-indicador" in {a["slug"] for a in home["indicadores"]}


def test_patch_tipo_conteudo_invalido(client, admin_headers):
    app_id = _id_por_slug(client, admin_headers, "apps", "gerador-qrcode")
    r = client.patch(
        f"/api/admin/apps/{app_id}",
        json={"tipo_conteudo": "dashboard"},
        headers=admin_headers,
    )
    assert r.status_code == 400
