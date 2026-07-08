"""Histórico compartilhado de Processos Abertos — arquivo JSON, sem banco."""


def _semana(date="01/01/2026", total=10):
    return {
        "date": date,
        "total": total,
        "d5p": 1,
        "d1": 2,
        "d25": 3,
        "pct": 10.0,
        "units": 1,
        "resumo": {"RMSPII": {"total": total, "d1": 2, "d2": 0, "d3": 0, "d4": 0, "d5": 0, "d5p": 1}},
        "tipos": {},
    }


def test_historico_vazio_por_padrao(client):
    r = client.get("/api/processos-abertos/historico")
    assert r.status_code == 200
    assert r.json() == []


def test_post_sem_login_401(client):
    r = client.post("/api/processos-abertos/historico", json=_semana())
    assert r.status_code == 401


def test_post_autenticado_persiste_e_aparece_no_get(client, admin_headers):
    r = client.post(
        "/api/processos-abertos/historico", json=_semana(date="05/01/2026"), headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert any(s["date"] == "05/01/2026" for s in r.json())

    r2 = client.get("/api/processos-abertos/historico")
    assert any(s["date"] == "05/01/2026" for s in r2.json())


def test_post_mesma_data_substitui_em_vez_de_duplicar(client, admin_headers):
    client.post(
        "/api/processos-abertos/historico",
        json=_semana(date="12/01/2026", total=100),
        headers=admin_headers,
    )
    r = client.post(
        "/api/processos-abertos/historico",
        json=_semana(date="12/01/2026", total=200),
        headers=admin_headers,
    )
    semanas = [s for s in r.json() if s["date"] == "12/01/2026"]
    assert len(semanas) == 1
    assert semanas[0]["total"] == 200
