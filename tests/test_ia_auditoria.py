"""SuperfrioIA — eventos `ia.*` na trilha: o fato, nunca o conteúdo (arquitetura §16)."""
import json

from ia_ajuda import DOMINIO, eventos, marco_da_trilha, perguntar_http

from backend.auditoria import catalogo

PERGUNTA = "Quanto de peso líquido entrou em agosto de 2026?"


def test_os_eventos_ia_estao_no_catalogo_com_descricao():
    acoes = {e.acao for e in catalogo.listar() if e.categoria == "ia"}
    assert acoes == {
        "ia.conversa.criar", "ia.pergunta", "ia.consulta", "ia.resposta", "ia.bloqueio", "ia.erro",
        "ia.concessao.pedida", "ia.concessao.aprovada", "ia.concessao.negada", "ia.concessao.revogada",
        "ia.retencao.executada",
    }
    assert all(e.descricao for e in catalogo.listar() if e.categoria == "ia")


def test_uma_pergunta_gera_conversa_pergunta_consulta_e_resposta_na_ordem(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, PERGUNTA)
    ev = eventos(marco)
    assert [e["acao"] for e in ev] == ["ia.conversa.criar", "ia.pergunta", "ia.consulta", "ia.resposta"]
    assert {e["app_slug"] for e in ev} == {"superfrioia"}
    assert {e["ator_username"] for e in ev} == {usuario_ia["username"]}
    assert {e["categoria"] for e in ev} == {"ia"}


def test_os_eventos_de_uma_pergunta_compartilham_o_correlacao_id_do_request(client, usuario_ia):
    """P6: o mesmo id liga o log técnico do request aos eventos `ia.*`."""
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, PERGUNTA)
    ids = {e["correlacao_id"] for e in eventos(marco)}
    assert len(ids) == 1 and None not in ids


def test_a_trilha_guarda_hash_e_tamanho_nunca_o_texto(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, PERGUNTA)
    pergunta = eventos(marco, "ia.pergunta")[0]["detalhes"]
    assert pergunta["tamanho"] == len(PERGUNTA) and len(pergunta["hash"]) == 16
    todos = json.dumps([e["detalhes"] for e in eventos(marco)], ensure_ascii=False)
    assert "peso líquido" not in todos and "agosto" not in todos       # nada do texto, nem em pedaço


def test_a_consulta_audita_o_trabalho_feito_e_o_escopo(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, "Qual unidade mais recebeu em agosto?")
    d = eventos(marco, "ia.consulta")[0]["detalhes"]
    assert d["escopo_aplicado"] == "integral (indicador sem alcance por usuário)"
    assert d["situacao"] == "ok" and d["capacidade"] == "matriz"
    assert d["chamadas_logicas"] == 1 and d["chamadas_servico"] == 2 and d["paginas_lidas"] == 1
    assert d["limite_interno_atingido"] is False and d["linhas"] > 0
    assert set(d) >= {"dominio", "duracao_ms", "consultas_dw"}
    assert "unidades" not in d and "clientes" not in d                  # nem filtro nem linha de dado


def test_a_resposta_audita_estado_duracao_e_provedor_sem_o_texto(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, PERGUNTA)
    d = eventos(marco, "ia.resposta")[0]["detalhes"]
    assert d["estado"] == "ok" and d["provedor"] == "falso" and d["duracao_ms"] >= 0
    assert "texto" not in d


def test_a_resposta_audita_o_trabalho_da_pergunta_inteira_inclusive_o_que_nao_e_consulta(
    client, usuario_ia, ia_dw, monkeypatch
):
    """Operações efetivas (DD-24): `descrever`/`amostrar_valores` leem as opções no DW
    mas não são consulta; o total da pergunta tem que mostrar tudo."""
    from ia_ajuda import Roteiro, consulta, registros_de_consulta, usar_roteiro
    banco = ia_dw()
    usar_roteiro(monkeypatch, Roteiro([
        ("amostrar_valores", {"dominio": DOMINIO, "dimensao": "unidade", "termo": ""}), consulta(), consulta()]))
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, PERGUNTA)
    total = eventos(marco, "ia.resposta")[0]["detalhes"]["operacoes"]
    assert total["chamadas_servico"] == len(banco.conexoes) == 3          # opções + 2 leituras
    assert total["consultas_logicas"] == 2 and total["passos"] == 3 and total["paginas_lidas"] == 2
    # e a soma das linhas de ia_consultas bate com o mesmo número: nada ficou sem dono
    assert sum(c["chamadas_servico"] for c in registros_de_consulta()) == 3


def test_pergunta_com_dado_pessoal_audita_so_o_tipo_mascarado(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, "Quanto entrou em agosto? meu cpf é 123.456.789-09")
    d = eventos(marco, "ia.pergunta")[0]["detalhes"]
    assert d["dados_pessoais_mascarados"] == ["CPF"]
    assert "123.456.789-09" not in json.dumps(eventos(marco), ensure_ascii=False)


def test_pergunta_recusada_pela_politica_vira_bloqueio_e_nao_pergunta(client, usuario_ia):
    marco = marco_da_trilha()
    perguntar_http(client, usuario_ia, "x" * 1001, esperado=400)
    assert [e["acao"] for e in eventos(marco)] == ["ia.bloqueio"]
    assert eventos(marco)[0]["detalhes"]["motivo"] == "tamanho"


# ============================================================== concessões
def test_ciclo_da_concessao_audita_pedida_aprovada_e_revogada_com_quem_e_por_que(
    client, ia_ligada, criar_usuario_ia, admin_headers
):
    u = criar_usuario_ia("ciclo")
    marco = marco_da_trilha()
    pid = client.post("/api/ia/concessoes/pedidos", headers=u["headers"],
                      json={"dominio": DOMINIO, "motivo": "relatório mensal"}).json()["id"]
    client.post(f"/api/ia/administracao/concessoes/{pid}/aprovar", headers=admin_headers,
                json={"motivo": "ok", "validade_dias": 90})
    client.post(f"/api/ia/administracao/concessoes/{pid}/revogar", headers=admin_headers, json={"motivo": "saiu do time"})

    pedida, aprovada, revogada = (eventos(marco, a)[0] for a in
                                  ("ia.concessao.pedida", "ia.concessao.aprovada", "ia.concessao.revogada"))
    assert pedida["detalhes"] == {"dominio": DOMINIO, "usuario": u["username"], "motivo": "relatório mensal"}
    assert pedida["ator_username"] == u["username"]
    d = aprovada["detalhes"]
    assert (d["aprovador"], d["usuario"], d["dominio"], d["motivo"], d["validade_dias"], d["autoaprovacao"]) == \
        ("admin", u["username"], DOMINIO, "ok", 90, False)
    assert d["validade_ate"]
    assert revogada["detalhes"]["motivo"] == "saiu do time" and revogada["ator_username"] == "admin"
    assert {e["alvo_tipo"] for e in (pedida, aprovada, revogada)} == {"concessao"}
    assert {e["alvo_id"] for e in (pedida, aprovada, revogada)} == {str(pid)}


def test_negada_audita_o_motivo_e_a_autoaprovacao_vem_marcada(client, ia_ligada, criar_usuario_ia, admin_headers):
    u = criar_usuario_ia("negada")
    marco = marco_da_trilha()
    pid = client.post("/api/ia/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": "x"}).json()["id"]
    client.post(f"/api/ia/administracao/concessoes/{pid}/negar", headers=admin_headers, json={"motivo": "fora do escopo"})
    assert eventos(marco, "ia.concessao.negada")[0]["detalhes"]["motivo"] == "fora do escopo"

    marco = marco_da_trilha()
    meu = client.post("/api/ia/concessoes/pedidos", headers=admin_headers, json={"dominio": DOMINIO, "motivo": "PoC"}).json()["id"]
    client.post(f"/api/ia/administracao/concessoes/{meu}/aprovar", headers=admin_headers, json={})
    assert eventos(marco, "ia.concessao.aprovada")[0]["detalhes"]["autoaprovacao"] is True


def test_decisao_e_evento_sao_atomicos_a_decisao_recusada_nao_deixa_evento(client, ia_ligada, criar_usuario_ia, admin_headers):
    u = criar_usuario_ia("atomico")
    pid = client.post("/api/ia/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": "x"}).json()["id"]
    marco = marco_da_trilha()
    r = client.post(f"/api/ia/administracao/concessoes/{pid}/aprovar", headers=admin_headers, json={"validade_dias": 9999})
    assert r.status_code == 400
    assert eventos(marco, "ia.concessao.aprovada") == []


def test_acesso_negado_a_rota_de_administracao_e_auditado_como_acesso_negado(client, ia_ligada, criar_usuario_ia):
    u = criar_usuario_ia("curioso")
    marco = marco_da_trilha()
    r = client.get("/api/ia/administracao/concessoes", headers=u["headers"], params={"dominio": DOMINIO})
    assert r.status_code == 403
    ev = eventos(marco, "acesso.negado")
    assert ev and ev[0]["detalhes"]["exigia"] == "volumetria-catering:administrar"


def test_a_retencao_audita_so_contagens(client):
    from backend.ia import retencao
    marco = marco_da_trilha()
    retencao.executar()
    d = eventos(marco, "ia.retencao.executada")[0]["detalhes"]
    assert set(d) == {"mensagens", "conversas", "consultas", "prazo_mensagens_dias", "prazo_consultas_dias"}
    assert (d["prazo_mensagens_dias"], d["prazo_consultas_dias"]) == (90, 180)
