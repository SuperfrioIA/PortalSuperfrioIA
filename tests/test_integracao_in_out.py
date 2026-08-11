"""Base compartilhada de Integração In/Out — arquivo JSON, sem banco.

O que estes testes cobrem além do óbvio: a gravação é **por (ano, mês)**, não
por data de upload. É a regra que faz o relatório do mês corrente atualizar só o
mês corrente, e que faz subir o mesmo arquivo duas vezes não dobrar número
nenhum.
"""
import pytest

from backend.integracao_in_out import router as modulo


@pytest.fixture(autouse=True)
def _base_limpa():
    """Cada teste começa sem base — o JSON mora no tmp do SUPERFRIO_DB_PATH."""
    if modulo._DATA_PATH.exists():
        modulo._DATA_PATH.unlink()
    yield


def _vetor(integrado, total):
    """[int_pedidos, tot_pedidos, int_linhas, tot_linhas, int_ondas, tot_ondas]"""
    return [integrado, total, integrado * 10, total * 10, 0, 0]


def _envio(
    ano="2026",
    meses=("07",),
    unidade="BSB",
    cliente="UNILEVER",
    integrado=7,
    total=8,
    arquivo="rpt_jda.xlsx",
):
    por_mes = {m: _vetor(integrado, total) for m in meses}
    return {
        "arquivo": arquivo,
        "linhas": 10,
        "anos": {
            ano: {
                "agg": {"IN": {unidade: dict(por_mes)}, "OUT": {}},
                "cli": {"IN": {cliente: dict(por_mes)}, "OUT": {}},
                "climap": {cliente: unidade},
            }
        },
    }


def _agg_in(corpo, ano="2026"):
    return corpo["anos"][ano]["agg"]["IN"]


# ── leitura ──────────────────────────────────────────────────────────────────


def test_base_vazia_por_padrao(client):
    r = client.get("/api/integracao-in-out/base")
    assert r.status_code == 200
    assert r.json() == {"anos": {}, "atualizado_em": None, "arquivo": None}


def test_get_base_nao_expoe_log_de_auditoria(client, admin_headers):
    client.post("/api/integracao-in-out/base", json=_envio(), headers=admin_headers)
    corpo = client.get("/api/integracao-in-out/base").json()
    assert "uploads" not in corpo, "o log tem nome de usuário e a leitura é pública"


# ── guardas ──────────────────────────────────────────────────────────────────


def test_post_sem_login_401(client):
    assert client.post("/api/integracao-in-out/base", json=_envio()).status_code == 401


def test_post_logado_sem_permissao_403(client, analista_headers):
    r = client.post("/api/integracao-in-out/base", json=_envio(), headers=analista_headers)
    assert r.status_code == 403


def test_uploads_exige_permissao(client, analista_headers):
    assert client.get("/api/integracao-in-out/uploads").status_code == 401
    assert client.get("/api/integracao-in-out/uploads", headers=analista_headers).status_code == 403


def test_post_com_permissao_concedida_pela_matriz(client, admin_headers, operador_headers):
    r0 = client.post(
        "/api/admin/roles",
        json={
            "slug": "integracao-in-out-editor",
            "nome": "Integração In/Out - Editor",
            "permissoes": ["integracao-in-out:editar"],
        },
        headers=admin_headers,
    )
    assert r0.status_code == 201, r0.text
    usuarios = client.get("/api/admin/usuarios", headers=admin_headers).json()
    operador_id = next(u["id"] for u in usuarios if u["username"] == "operador.armazem")
    r1 = client.patch(
        f"/api/admin/usuarios/{operador_id}",
        json={"roles": ["armazem-full", "integracao-in-out-editor"]},
        headers=admin_headers,
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post("/api/integracao-in-out/base", json=_envio(), headers=operador_headers)
    assert r2.status_code == 200, r2.text
    assert _agg_in(r2.json())["BSB"]["07"] == _vetor(7, 8)


# ── gravação por (ano, mês) ──────────────────────────────────────────────────


def test_post_grava_e_aparece_no_get(client, admin_headers):
    r = client.post("/api/integracao-in-out/base", json=_envio(), headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["atualizado_em"]

    corpo = client.get("/api/integracao-in-out/base").json()
    assert _agg_in(corpo)["BSB"]["07"] == _vetor(7, 8)
    assert corpo["anos"]["2026"]["cli"]["IN"]["UNILEVER"]["07"] == _vetor(7, 8)
    assert corpo["anos"]["2026"]["climap"] == {"UNILEVER": "BSB"}
    assert corpo["arquivo"] == "rpt_jda.xlsx"


def test_mesmo_arquivo_duas_vezes_substitui_em_vez_de_somar(client, admin_headers):
    client.post("/api/integracao-in-out/base", json=_envio(), headers=admin_headers)
    r = client.post("/api/integracao-in-out/base", json=_envio(), headers=admin_headers)
    assert _agg_in(r.json())["BSB"]["07"] == _vetor(7, 8)


def test_mes_novo_nao_apaga_os_meses_anteriores(client, admin_headers):
    client.post(
        "/api/integracao-in-out/base",
        json=_envio(meses=("01", "02", "03")),
        headers=admin_headers,
    )
    r = client.post(
        "/api/integracao-in-out/base",
        json=_envio(meses=("04",), integrado=1, total=2),
        headers=admin_headers,
    )
    meses = _agg_in(r.json())["BSB"]
    assert sorted(meses) == ["01", "02", "03", "04"]
    assert meses["01"] == _vetor(7, 8)
    assert meses["04"] == _vetor(1, 2)


def test_mes_reenviado_com_numero_novo_vale_o_novo(client, admin_headers):
    client.post("/api/integracao-in-out/base", json=_envio(), headers=admin_headers)
    r = client.post(
        "/api/integracao-in-out/base",
        json=_envio(integrado=20, total=30),
        headers=admin_headers,
    )
    assert _agg_in(r.json())["BSB"]["07"] == _vetor(20, 30)


def test_unidade_que_sumiu_do_mes_sai_do_mes(client, admin_headers):
    client.post(
        "/api/integracao-in-out/base",
        json=_envio(meses=("06", "07"), unidade="ITA"),
        headers=admin_headers,
    )
    # Julho volta só com BSB: ITA continua em junho, some de julho.
    r = client.post(
        "/api/integracao-in-out/base", json=_envio(meses=("07",)), headers=admin_headers
    )
    unidades = _agg_in(r.json())
    assert sorted(unidades["ITA"]) == ["06"]
    assert sorted(unidades["BSB"]) == ["07"]


def test_ano_novo_nao_apaga_o_ano_anterior(client, admin_headers):
    client.post("/api/integracao-in-out/base", json=_envio(ano="2026"), headers=admin_headers)
    r = client.post(
        "/api/integracao-in-out/base",
        json=_envio(ano="2027", meses=("01",)),
        headers=admin_headers,
    )
    corpo = r.json()
    assert sorted(corpo["anos"]) == ["2026", "2027"]
    assert _agg_in(corpo, "2026")["BSB"]["07"] == _vetor(7, 8)
    assert _agg_in(corpo, "2027")["BSB"]["01"] == _vetor(7, 8)


# ── validação de entrada ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mutacao",
    [
        pytest.param(lambda e: e["anos"].update({"20xx": e["anos"].pop("2026")}), id="ano-invalido"),
        pytest.param(
            lambda e: e["anos"]["2026"]["agg"]["IN"]["BSB"].update({"13": _vetor(1, 1)}),
            id="mes-13",
        ),
        pytest.param(
            lambda e: e["anos"]["2026"]["agg"]["IN"]["BSB"].update({"07": [1, 2, 3]}),
            id="vetor-curto",
        ),
        pytest.param(
            lambda e: e["anos"]["2026"]["agg"]["IN"]["BSB"].update({"07": _vetor(-1, 5)}),
            id="contagem-negativa",
        ),
        pytest.param(
            lambda e: e["anos"]["2026"]["agg"].update({"AMBOS": {}}), id="direcao-invalida"
        ),
        pytest.param(lambda e: e.update({"anos": {}}), id="sem-ano"),
    ],
)
def test_payload_invalido_422(client, admin_headers, mutacao):
    envio = _envio()
    mutacao(envio)
    r = client.post("/api/integracao-in-out/base", json=envio, headers=admin_headers)
    assert r.status_code == 422, r.text


def test_ano_sem_nenhum_mes_422(client, admin_headers):
    envio = _envio()
    envio["anos"]["2026"]["agg"] = {"IN": {}, "OUT": {}}
    envio["anos"]["2026"]["cli"] = {"IN": {}, "OUT": {}}
    r = client.post("/api/integracao-in-out/base", json=envio, headers=admin_headers)
    assert r.status_code == 422, r.text


# ── auditoria ────────────────────────────────────────────────────────────────


def test_uploads_registra_quem_subiu_o_que(client, admin_headers):
    client.post(
        "/api/integracao-in-out/base",
        json=_envio(meses=("06", "07"), arquivo="rpt_junho_julho.xlsx"),
        headers=admin_headers,
    )
    log = client.get("/api/integracao-in-out/uploads", headers=admin_headers).json()
    assert len(log) == 1
    assert log[0]["por"] == "admin"
    assert log[0]["arquivo"] == "rpt_junho_julho.xlsx"
    assert log[0]["meses"] == {"2026": ["06", "07"]}
    assert log[0]["totais"]["2026"]["IN"] == [14, 16]


def test_uploads_mais_recente_primeiro(client, admin_headers):
    client.post(
        "/api/integracao-in-out/base", json=_envio(arquivo="primeiro.xlsx"), headers=admin_headers
    )
    client.post(
        "/api/integracao-in-out/base", json=_envio(arquivo="segundo.xlsx"), headers=admin_headers
    )
    log = client.get("/api/integracao-in-out/uploads", headers=admin_headers).json()
    assert [u["arquivo"] for u in log] == ["segundo.xlsx", "primeiro.xlsx"]
