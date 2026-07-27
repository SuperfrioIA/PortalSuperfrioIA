"""Projetos IA: guarda de permissão + regras derivadas (fase atual, atraso,
status de rollout) — nada disso é gravado, tudo calculado na leitura."""
from datetime import date, timedelta

HOJE = date.today()


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _plano(fase0_fim: date):
    """7 janelas sequenciais; a fase 0 termina em `fase0_fim` (passado ou
    futuro, conforme o teste), a última (6 — Em suporte) fica aberta."""
    fase0_inicio = fase0_fim - timedelta(days=9)
    janelas = [{"previsto_inicio": _iso(fase0_inicio), "previsto_fim": _iso(fase0_fim)}]
    cursor = fase0_fim + timedelta(days=1)
    for _ in range(1, 6):
        fim = cursor + timedelta(days=9)
        janelas.append({"previsto_inicio": _iso(cursor), "previsto_fim": _iso(fim)})
        cursor = fim + timedelta(days=1)
    janelas.append({"previsto_inicio": _iso(cursor), "previsto_fim": None})
    return janelas


def _projeto(slug="proj-teste", **over):
    body = {
        "slug": slug,
        "nome": "Projeto Teste",
        "area": "CSC · Teste",
        "objetivo": "Testar o módulo.",
        "problema": "Sem automação.",
        "beneficio": "Menos retrabalho.",
        "publico": "Equipe de testes.",
        "acelerador": "Fulano de Tal",
        "plano": _plano(HOJE + timedelta(days=10)),
    }
    body.update(over)
    return body


def _criar_role_editor(client, admin_headers, slug="projetos-ia-editor"):
    r = client.post(
        "/api/admin/roles",
        json={"slug": slug, "nome": "Projetos IA - Editor", "permissoes": ["projetos-ia:editar"]},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    return slug


def _dar_roles(client, admin_headers, username, role_slugs):
    usuarios = client.get("/api/admin/usuarios", headers=admin_headers).json()
    user_id = next(u["id"] for u in usuarios if u["username"] == username)
    r = client.patch(f"/api/admin/usuarios/{user_id}", json={"roles": role_slugs}, headers=admin_headers)
    assert r.status_code == 200, r.text


# ---------- Guarda de permissão ----------

def test_listar_sem_login_401(client):
    assert client.get("/api/projetos-ia").status_code == 401


def test_criar_sem_permissao_403(client, operador_headers):
    r = client.post("/api/projetos-ia", json=_projeto("sem-permissao"), headers=operador_headers)
    assert r.status_code == 403


def test_ver_nao_exige_permissao_extra_so_login(client, operador_headers):
    # "ver" é o objetivo da tela: qualquer usuário logado lista/lê detalhe,
    # mesmo sem a permissão de editar.
    r = client.get("/api/projetos-ia", headers=operador_headers)
    assert r.status_code == 200


# ---------- CRUD de projeto + derivações ----------

def test_criar_com_permissao_e_ler_detalhe(client, admin_headers):
    r = client.post("/api/projetos-ia", json=_projeto("fluxo-completo"), headers=admin_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["fase_atual"] == 0
    assert body["atrasado_dias"] == 0
    assert len(body["fases"]) == 7
    assert body["rollout"] == []  # fase 0 ainda não chegou em implantação

    r2 = client.get("/api/projetos-ia/fluxo-completo", headers=admin_headers)
    assert r2.status_code == 200
    assert r2.json()["nome"] == "Projeto Teste"

    r3 = client.get("/api/projetos-ia", headers=admin_headers)
    item = next(p for p in r3.json() if p["slug"] == "fluxo-completo")
    # A lista precisa trazer `fases` (não só o detalhe) — é o que a visão
    # Cronograma do portfólio usa para desenhar as barras de cada projeto.
    assert len(item["fases"]) == 7
    assert "rollout" not in item  # bruto (com nome/status por filial) só no detalhe


def test_criar_slug_duplicado_409(client, admin_headers):
    client.post("/api/projetos-ia", json=_projeto("duplicado"), headers=admin_headers)
    r = client.post("/api/projetos-ia", json=_projeto("duplicado"), headers=admin_headers)
    assert r.status_code == 409


def test_criar_plano_com_numero_errado_de_fases_422(client, admin_headers):
    body = _projeto("plano-invalido")
    body["plano"] = body["plano"][:5]
    r = client.post("/api/projetos-ia", json=body, headers=admin_headers)
    assert r.status_code == 422


def test_detalhe_inexistente_404(client, admin_headers):
    r = client.get("/api/projetos-ia/nao-existe", headers=admin_headers)
    assert r.status_code == 404


def test_atualizar_projeto_patch_parcial(client, admin_headers):
    client.post("/api/projetos-ia", json=_projeto("patch-teste"), headers=admin_headers)
    r = client.patch(
        "/api/projetos-ia/patch-teste",
        json={"key_user": "Fulana da Silva", "proximo_marco_texto": "Apresentação à TI"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key_user"] == "Fulana da Silva"
    assert body["proximo_marco_texto"] == "Apresentação à TI"
    assert body["nome"] == "Projeto Teste"  # não tocado, PATCH é parcial


def test_atraso_derivado_sem_campo_manual(client, admin_headers):
    slug = "atrasado-teste"
    client.post(
        "/api/projetos-ia", json=_projeto(slug, plano=_plano(HOJE - timedelta(days=5))),
        headers=admin_headers,
    )
    r = client.get(f"/api/projetos-ia/{slug}", headers=admin_headers)
    body = r.json()
    assert body["fase_atual"] == 0
    assert body["atrasado_dias"] == 5


def test_fase_concluida_registra_quem_e_avanca_fase_atual(client, admin_headers):
    slug = "conclusao-teste"
    client.post("/api/projetos-ia", json=_projeto(slug), headers=admin_headers)
    r = client.patch(
        f"/api/projetos-ia/{slug}/fases/0",
        json={"concluido_em": _iso(HOJE), "observacao": "POC validada"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fase_atual"] == 1
    fase0 = next(f for f in body["fases"] if f["ordem"] == 0)
    assert fase0["concluido_em"] == _iso(HOJE)
    assert fase0["observacao"] == "POC validada"
    assert fase0["registrado_por"]  # nome do usuário logado, capturado automaticamente


def test_fase_reaberta_limpa_registrado_por(client, admin_headers):
    slug = "reabertura-teste"
    client.post("/api/projetos-ia", json=_projeto(slug), headers=admin_headers)
    client.patch(f"/api/projetos-ia/{slug}/fases/0", json={"concluido_em": _iso(HOJE)}, headers=admin_headers)
    r = client.patch(f"/api/projetos-ia/{slug}/fases/0", json={"concluido_em": None}, headers=admin_headers)
    fase0 = next(f for f in r.json()["fases"] if f["ordem"] == 0)
    assert fase0["concluido_em"] is None
    assert fase0["registrado_por"] is None


# ---------- Filiais (catálogo, admin) ----------

def test_filiais_admin_crud_e_bloqueio_para_nao_admin(client, admin_headers, operador_headers):
    r = client.post(
        "/api/admin/filiais", json={"nome": "CD Teste", "uf": "SP", "regiao": "Sudeste"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    filial_id = r.json()["id"]

    r2 = client.post(
        "/api/admin/filiais", json={"nome": "CD Bloqueado", "uf": "SP", "regiao": "Sudeste"},
        headers=operador_headers,
    )
    assert r2.status_code == 403

    r3 = client.patch(f"/api/admin/filiais/{filial_id}", json={"regiao": "Sul"}, headers=admin_headers)
    assert r3.status_code == 200
    assert r3.json()["regiao"] == "Sul"

    r4 = client.post(f"/api/admin/filiais/{filial_id}/toggle", headers=admin_headers)
    assert r4.status_code == 200
    assert r4.json()["ativo"] == 0


# ---------- Rollout (projeto × filial) ----------

def test_rollout_status_derivado_de_data_sem_campo_manual(client, admin_headers):
    slug = "rollout-teste"
    client.post(
        "/api/projetos-ia", json=_projeto(slug, plano=_plano(HOJE - timedelta(days=100))),
        headers=admin_headers,
    )
    for ordem in range(4):
        r = client.patch(
            f"/api/projetos-ia/{slug}/fases/{ordem}", json={"concluido_em": _iso(HOJE)}, headers=admin_headers
        )
    assert r.json()["fase_atual"] == 4  # Implantação — rollout já faz sentido

    filial = client.post(
        "/api/admin/filiais", json={"nome": "CD Rollout", "uf": "SP", "regiao": "Sudeste"},
        headers=admin_headers,
    ).json()

    r = client.post(f"/api/projetos-ia/{slug}/rollout", json={"filial_id": filial["id"]}, headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["rollout"][0]["status"] == "pendente"  # sem data
    assert r.json()["rollout_resumo"]["pendentes"] == 1

    r2 = client.patch(
        f"/api/projetos-ia/{slug}/rollout/{filial['id']}",
        json={"data": _iso(HOJE + timedelta(days=5))},
        headers=admin_headers,
    )
    assert r2.json()["rollout"][0]["status"] == "agendada"

    r3 = client.patch(
        f"/api/projetos-ia/{slug}/rollout/{filial['id']}",
        json={"data": _iso(HOJE - timedelta(days=1)), "publico_treinado": "Fiscal (3)"},
        headers=admin_headers,
    )
    assert r3.json()["rollout"][0]["status"] == "treinada"
    resumo = r3.json()["rollout_resumo"]
    assert resumo["treinadas"] == 1
    assert resumo["pct"] == 100

    r4 = client.patch(
        f"/api/projetos-ia/{slug}/rollout/{filial['id']}", json={"nao_se_aplica": True}, headers=admin_headers
    )
    assert r4.json()["rollout"][0]["status"] == "nao_se_aplica"
    assert r4.json()["rollout_resumo"]["previstas"] == 0  # exclui "não se aplica"

    r5 = client.delete(f"/api/projetos-ia/{slug}/rollout/{filial['id']}", headers=admin_headers)
    assert r5.status_code == 200
    assert r5.json()["rollout"] == []


def test_incluir_rollout_filial_duplicada_409(client, admin_headers):
    slug = "rollout-dup-teste"
    client.post(
        "/api/projetos-ia", json=_projeto(slug, plano=_plano(HOJE - timedelta(days=100))),
        headers=admin_headers,
    )
    for ordem in range(4):
        client.patch(f"/api/projetos-ia/{slug}/fases/{ordem}", json={"concluido_em": _iso(HOJE)}, headers=admin_headers)
    filial = client.post(
        "/api/admin/filiais", json={"nome": "CD Duplicado", "uf": "MG", "regiao": "Sudeste"},
        headers=admin_headers,
    ).json()
    client.post(f"/api/projetos-ia/{slug}/rollout", json={"filial_id": filial["id"]}, headers=admin_headers)
    r = client.post(f"/api/projetos-ia/{slug}/rollout", json={"filial_id": filial["id"]}, headers=admin_headers)
    assert r.status_code == 409


# ---------- Fluxo completo com role dedicada (não-admin) ----------

def test_editar_com_role_dedicada(client, admin_headers, operador_headers):
    _criar_role_editor(client, admin_headers)
    _dar_roles(client, admin_headers, "operador.armazem", ["armazem-full", "projetos-ia-editor"])
    r = client.post("/api/projetos-ia", json=_projeto("via-role"), headers=operador_headers)
    assert r.status_code == 201, r.text
