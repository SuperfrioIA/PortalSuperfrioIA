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
    secoes = r.json()["secoes"]
    assert {s["slug"] for s in secoes} == {"armazem", "backoffice"}
    total_apps = sum(len(s["apps"]) for s in secoes)
    assert total_apps == 7


def test_portal_home_operador_so_armazem(client, operador_headers):
    secoes = client.get("/api/portal/home", headers=operador_headers).json()["secoes"]
    assert {s["slug"] for s in secoes} == {"armazem"}
    apps = {a["slug"] for s in secoes for a in s["apps"]}
    assert apps == {"faq-blueyonder", "faq-slin", "conciliacao-estoque"}


def test_portal_home_analista_backoffice_e_faqs(client, analista_headers):
    secoes = {s["slug"]: s for s in client.get("/api/portal/home", headers=analista_headers).json()["secoes"]}
    assert set(secoes) == {"armazem", "backoffice"}
    # Pela role faq-leitor enxerga só os 2 FAQs do armazém, não a conciliação.
    assert {a["slug"] for a in secoes["armazem"]["apps"]} == {"faq-blueyonder", "faq-slin"}
    assert len(secoes["backoffice"]["apps"]) == 4
