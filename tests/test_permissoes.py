"""Permissões: require_admin (401/403/200) e filtro de apps por role."""


# ---------- require_admin ----------

def test_admin_endpoint_exige_token(client):
    assert client.get("/api/admin/usuarios").status_code == 401


def test_admin_endpoint_nega_nao_admin(client, operador_headers):
    assert client.get("/api/admin/usuarios", headers=operador_headers).status_code == 403


def test_admin_endpoint_aceita_admin(client, admin_headers):
    r = client.get("/api/admin/usuarios", headers=admin_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- /portal/home: visibilidade por role ----------

def test_portal_home_admin_ve_tudo(client, admin_headers):
    r = client.get("/api/portal/home", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    secoes = body["secoes"]
    assert {s["slug"] for s in secoes} == {"armazem", "backoffice", "inovacao", "tecnologia"}
    # `secoes` traz só os apps de sistema; os indicadores vêm em lista à parte.
    # 7 exemplos + gerador-qrcode, projetos-ia, governanca-ti e mapa-ia
    assert sum(len(s["apps"]) for s in secoes) == 11
    # processos-abertos e integracao-in-out
    assert len(body["indicadores"]) == 2


def test_portal_home_operador_so_armazem(client, operador_headers):
    """Governance TI entra aqui de carona: ao virar app do catálogo, ele nasceu
    liberado para TODAS as roles, porque antes era um botão fixo que todo mundo
    logado via (ver `_VER_PARA_TODAS_AS_ROLES` em backend/usuarios/seed.py)."""
    secoes = client.get("/api/portal/home", headers=operador_headers).json()["secoes"]
    assert {s["slug"] for s in secoes} == {"armazem", "tecnologia"}
    apps = {a["slug"] for s in secoes for a in s["apps"]}
    assert apps == {"faq-blueyonder", "faq-slin", "conciliacao-estoque", "governanca-ti"}


def test_portal_home_analista_backoffice_e_faqs(client, analista_headers):
    secoes = {s["slug"]: s for s in client.get("/api/portal/home", headers=analista_headers).json()["secoes"]}
    assert set(secoes) == {"armazem", "backoffice", "tecnologia"}
    # Pela role faq-leitor enxerga só os 2 FAQs do armazém, não a conciliação.
    assert {a["slug"] for a in secoes["armazem"]["apps"]} == {"faq-blueyonder", "faq-slin"}
    assert len(secoes["backoffice"]["apps"]) == 4
    # Mapa IA não foi liberado para role nenhuma: só admin vê.
    assert {a["slug"] for a in secoes["tecnologia"]["apps"]} == {"governanca-ti"}


def test_portal_home_nao_admin_nao_ve_mapa_ia(client, operador_headers):
    apps = {
        a["slug"]
        for s in client.get("/api/portal/home", headers=operador_headers).json()["secoes"]
        for a in s["apps"]
    }
    assert "mapa-ia" not in apps
