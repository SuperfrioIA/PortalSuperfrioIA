"""SuperfrioIA — segurança: contrato, chave do cliente, dado pessoal e perímetro de código.

O que o modelo pode pedir é só o que o contrato descreve; o que ele recebe nunca
inclui a chave do cliente (DD-17); e só o adaptador fala com o módulo dono do dado.
"""
import ast
import json
import pathlib

import pytest
from ia_ajuda import (
    DOMINIO, Roteiro, consulta, eventos, marco_da_trilha, perguntar_http,
    registros_de_consulta, usar_roteiro,
)
from sqlalchemy import select

from backend.core.database import db
from backend.ia import politicas
from backend.ia.models import IaConsulta, IaConversa, IaMensagem
from backend.volumetria_catering import service

CHAVES = ["67945071", "67945072", "12345678", "55555555"]   # raízes de CNPJ dos clientes do DW falso
RAIZ_IA = pathlib.Path(__file__).resolve().parent.parent / "backend" / "ia"


# ====================================================== parâmetro fora do contrato
INVALIDOS = [
    ("campo desconhecido", dict(intruso="x")),
    ("sql solto", dict(sql="SELECT * FROM dual")),
    ("tabela", dict(tabela="FATO_VOL_REC_CAT_V01")),
    ("pagina (não é do modelo)", dict(pagina=2)),
    ("lente", dict(lente="kg")),
    ("movimento", dict(movimento="estoque")),
    ("faixa", dict(faixa="entregue")),
    ("dias não numéricos", dict(dias=["a"])),
    ("dia booleano", dict(dias=[True])),
    ("limite acima do teto", dict(detalhe="unidade", limite=21)),
    ("limite zero", dict(detalhe="unidade", limite=0)),
    ("detalhe inexistente", dict(detalhe="operacao")),
    ("operações na conjunta", dict(movimento="amb", operacoes=["OP A"])),
    ("período invertido", dict(de="2026-09-01", ate="2026-01-01")),
    ("data que não existe", dict(de="2026-02-30", ate="2026-03-01")),
    ("cliente por identificador", dict(clientes=["12345678"])),
    ("cliente por CNPJ formatado", dict(clientes=["12.345.678/0001-90"])),
    ("lista que é texto", dict(unidades="CPS")),
    ("detalhe cliente sem unidade", dict(detalhe="cliente")),
    ("detalhe cliente com duas unidades", dict(detalhe="cliente", unidades=["CPS", "MAQ"])),
    ("detalhe faixa na entrada", dict(detalhe="faixa", unidades=["CPS"], clientes=["SAPORE"])),
    ("derivação desconhecida", dict(derivacao={"tipo": "media"})),
    ("derivação com os dois meses iguais", dict(derivacao={"tipo": "variacao_percentual", "mes_base": "2026-08", "mes_atual": "2026-08"})),
    ("derivação com detalhe", dict(detalhe="unidade", derivacao={"tipo": "variacao_percentual", "mes_base": "2026-07", "mes_atual": "2026-08"})),
    ("período de 5 anos", dict(de="2021-01-01", ate="2026-08-31")),
]


@pytest.mark.parametrize("nome, parametros", INVALIDOS, ids=[n for n, _ in INVALIDOS])
def test_parametro_fora_do_contrato_e_recusado_antes_da_matriz(client, usuario_ia, ia_dw, monkeypatch, nome, parametros):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(**parametros)]))
    monkeypatch.setattr(service, "matriz", lambda *_a, **_k: pytest.fail("a Matriz não podia ser chamada"))
    perguntar_http(client, usuario_ia, "x")
    assert "erro" in roteiro.resultados[0], nome
    assert banco.consultas == []                    # nenhuma agregação chegou ao DW
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in banco.executados)


def test_valor_de_filtro_com_sql_vira_nao_encontrado_nunca_chega_ao_dw(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([
        consulta(unidades=["CPS'; DROP TABLE x;--"]),
        consulta(clientes=["' OR 1=1 --"]),
        consulta(tipos_estoque=["SECO' UNION SELECT"]),
    ]))
    perguntar_http(client, usuario_ia, "x")
    assert [r["erro"] for r in roteiro.resultados] == ["nao_encontrado"] * 3
    assert banco.consultas == []
    texto = json.dumps(banco.executados, default=str)
    assert "DROP" not in texto and "OR 1=1" not in texto


def test_so_o_dominio_da_conversa_existe_para_as_ferramentas(client, usuario_ia, monkeypatch):
    marco = marco_da_trilha()
    roteiro = usar_roteiro(monkeypatch, Roteiro([
        ("descrever", {"dominio": "conciliador-de-estoque"}),
        ("amostrar_valores", {"dominio": "outro", "dimensao": "unidade", "termo": ""}),
        ("consultar_indicador", {"dominio": "outro", "parametros": {"movimento": "rec"}}),
    ]))
    perguntar_http(client, usuario_ia, "x")
    assert [r["erro"] for r in roteiro.resultados] == ["dominio_fora_da_conversa"] * 3
    assert registros_de_consulta() == []                       # nem virou consulta
    motivos = [e["detalhes"]["motivo"] for e in eventos(marco, "ia.bloqueio")]
    assert motivos == ["dominio_fora_da_conversa"] * 3          # recusa pedida pelo modelo é auditada


def test_ferramenta_inexistente_e_recusada_e_auditada(client, usuario_ia, monkeypatch):
    marco = marco_da_trilha()
    roteiro = usar_roteiro(monkeypatch, Roteiro([("executar_sql", {"sql": "DELETE FROM x"}), ("../../etc", {})]))
    perguntar_http(client, usuario_ia, "x")
    assert [r["erro"] for r in roteiro.resultados] == ["ferramenta_desconhecida"] * 2
    assert [e["detalhes"]["motivo"] for e in eventos(marco, "ia.bloqueio")] == ["ferramenta_desconhecida"] * 2


def test_dominio_desconhecido_na_rota_e_404_auditado(client, usuario_ia):
    marco = marco_da_trilha()
    r = client.post("/api/ia/perguntas", headers=usuario_ia["headers"], json={"dominio": "nao-existe", "pergunta": "x"})
    assert r.status_code == 404
    assert [e["detalhes"]["motivo"] for e in eventos(marco, "ia.bloqueio")] == ["dominio_desconhecido"]


def test_conversa_nao_troca_de_dominio(client, usuario_ia):
    cid = perguntar_http(client, usuario_ia, "Quanto entrou em agosto?")["conversa_id"]
    r = client.post("/api/ia/perguntas", headers=usuario_ia["headers"],
                    json={"dominio": "nao-existe", "pergunta": "x", "conversa_id": cid})
    assert r.status_code == 404


# ============================================= sem concessão / sem ver: auditado
def test_sem_concessao_e_negado_e_auditado(client, ia_ligada, ia_dw, criar_usuario_ia):
    ia_dw()
    u = criar_usuario_ia("sem-concessao")
    marco = marco_da_trilha()
    r = perguntar_http(client, u, "Quanto entrou em agosto?", esperado=403)
    assert r["detail"] == "Você não tem acesso a este domínio."      # neutra: não diz qual porta falhou
    assert [(e["acao"], e["detalhes"]["motivo"], e["ator_username"]) for e in eventos(marco, "ia.bloqueio")] == \
        [("ia.bloqueio", "sem_concessao", u["username"])]


def test_concessao_sem_ver_do_sistema_e_negada_com_a_mesma_mensagem(client, ia_ligada, criar_usuario_ia, admin_headers):
    u = criar_usuario_ia("sem-ver", ver_sistema=False)
    pedido = client.post("/api/ia/concessoes/pedidos", headers=u["headers"], json={"dominio": DOMINIO, "motivo": "x"})
    assert pedido.status_code == 403
    r = perguntar_http(client, u, "Quanto entrou em agosto?", esperado=403)
    assert r["detail"] == "Você não tem acesso a este domínio."


def test_sem_login_e_401(client, ia_ligada):
    for rota in ("/api/ia/dominios", "/api/ia/conversas", "/api/ia/concessoes/minhas"):
        assert client.get(rota).status_code == 401
    assert client.post("/api/ia/perguntas", json={"dominio": DOMINIO, "pergunta": "x"}).status_code == 401


# ==================================================== a chave do cliente (DD-17)
def test_a_chave_do_cliente_nunca_sai_do_hub(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([
        consulta(clientes=["SAPORE"]),
        consulta(detalhe="cliente", unidades=["CPS"]),
        ("amostrar_valores", {"dominio": DOMINIO, "dimensao": "cliente", "termo": ""}),
    ]))
    marco = marco_da_trilha()
    r = perguntar_http(client, usuario_ia, "Quanto o cliente SAPORE recebeu?")

    # (prova de que o teste não é vazio) a chave CHEGOU ao DW, como filtro
    binds = [b for _sql, b in banco.consultas]
    assert any(b.get("cli0") == "12345678" for b in binds)

    # ...e não aparece em nenhum lugar por onde o dado de IA passa
    onde = {
        "o que o modelo viu": roteiro.tudo_que_o_modelo_viu(),
        "resposta da API": json.dumps(r, ensure_ascii=False),
        "trilha de auditoria": json.dumps([e["detalhes"] for e in eventos(marco)], ensure_ascii=False),
    }
    with db() as session:
        onde["ia_mensagens"] = json.dumps([dict(m) for m in session.execute(select(IaMensagem.__table__)).mappings()], default=str)
        onde["ia_consultas"] = json.dumps([dict(m) for m in session.execute(select(IaConsulta.__table__)).mappings()], default=str)
        onde["ia_conversas"] = json.dumps([dict(m) for m in session.execute(select(IaConversa.__table__)).mappings()], default=str)
    for lugar, conteudo in onde.items():
        for chave in CHAVES:
            assert chave not in conteudo, f"a chave {chave} apareceu em: {lugar}"


def test_o_eco_dos_filtros_e_os_nos_da_matriz_trazem_rotulos_e_nao_chaves(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(detalhe="cliente", unidades=["CPS"], clientes=["SAPORE"])]))
    perguntar_http(client, usuario_ia, "x")
    visto = roteiro.resultados[0]
    assert "clientes: SAPORE" in visto["recorte"]
    assert [i["rotulo"] for i in visto["itens"]] == ["SAPORE"]
    assert all("chave" not in i for i in visto["itens"])


def test_nome_ambiguo_devolve_candidatos_por_rotulo_e_nao_escolhe(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(clientes=["convida"])]))
    perguntar_http(client, usuario_ia, "x")
    erro = roteiro.resultados[0]
    assert erro["erro"] == "ambiguo" and erro["candidatos"] == ["CONVIDA BRASIL", "CONVIDA SUL"]
    assert banco.consultas == []                                 # não chutou: nada foi consultado


def test_nome_exato_resolve_mesmo_com_acento_e_caixa_diferentes(client, usuario_ia, ia_dw, monkeypatch):
    banco = ia_dw()
    roteiro = usar_roteiro(monkeypatch, Roteiro([consulta(clientes=["convida   brasil"]), consulta(clientes=["Sápore"])]))
    perguntar_http(client, usuario_ia, "x")
    assert "erro" not in roteiro.resultados[0] and "erro" not in roteiro.resultados[1]
    assert [b["cli0"] for _s, b in banco.consultas] == ["67945071", "12345678"]


def test_amostrar_valores_so_devolve_rotulos(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([("amostrar_valores", {"dominio": DOMINIO, "dimensao": "cliente", "termo": "con"})]))
    perguntar_http(client, usuario_ia, "x")
    achado = roteiro.resultados[0]
    assert achado["valores"] == ["CONVIDA BRASIL", "CONVIDA SUL"]
    assert not any(c in json.dumps(achado) for c in CHAVES)


# ================================================================ dado pessoal
@pytest.mark.parametrize("entrada, tipo, sobra", [
    ("meu CPF é 123.456.789-09", "CPF", "123.456.789-09"),
    ("cpf 12345678909", "CPF", "12345678909"),
    ("CNPJ 12.345.678/0001-90", "CNPJ", "12.345.678/0001-90"),
    ("cnpj 12345678000190", "CNPJ", "12345678000190"),
    ("raiz do cnpj: 12345678", "CNPJ", "12345678"),
    ("escreva para ana.silva+x@superfrio.com.br", "EMAIL", "ana.silva+x@superfrio.com.br"),
    ("ligue (11) 91234-5678", "TELEFONE", "91234-5678"),
    ("ligue +55 11 91234-5678", "TELEFONE", "91234-5678"),
])
def test_dado_pessoal_e_mascarado(entrada, tipo, sobra):
    texto, achados = politicas.mascarar(entrada)
    assert f"[{tipo}]" in texto and sobra not in texto and tipo in achados


@pytest.mark.parametrize("pergunta", [
    "Quanto entrou em agosto de 2026?", "Variação entre 2026-07 e 2026-08", "Volumes de 01/08/2026 a 31/08/2026",
    "Quanto pesou 1.234.567,8 kg?", "pallets 12345",
])
def test_pergunta_normal_nao_e_mascarada(pergunta):
    assert politicas.mascarar(pergunta) == (pergunta, [])


def test_o_que_o_provedor_recebe_e_o_que_fica_gravado_ja_vai_mascarado(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([]))
    marco = marco_da_trilha()
    pergunta = "Quanto entrou em agosto? CPF 123.456.789-09, ana@empresa.com, CNPJ 12.345.678/0001-90"
    r = perguntar_http(client, usuario_ia, pergunta)
    assert sorted(r["dados_pessoais_mascarados"]) == ["CNPJ", "CPF", "EMAIL"]
    enviado = roteiro.contextos[0].pergunta
    assert enviado == "Quanto entrou em agosto? CPF [CPF], [EMAIL], CNPJ [CNPJ]"
    with db() as session:
        gravado = " ".join(session.execute(select(IaMensagem.texto)).scalars())
    trilha = json.dumps([e["detalhes"] for e in eventos(marco)], ensure_ascii=False)
    for segredo in ("123.456.789-09", "ana@empresa.com", "12.345.678/0001-90"):
        assert segredo not in gravado and segredo not in trilha and segredo not in json.dumps(r)


def test_o_historico_enviado_ao_provedor_tambem_e_o_mascarado(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([]))
    primeira = perguntar_http(client, usuario_ia, "Meu e-mail é ana@empresa.com. Quanto entrou?")
    perguntar_http(client, usuario_ia, "E em setembro?", conversa_id=primeira["conversa_id"])
    historico = " ".join(h["texto"] for h in roteiro.contextos[1].historico)
    assert "ana@empresa.com" not in historico and "[EMAIL]" in historico


# ======================================================== falha do provedor
def test_excecao_do_provedor_vira_mensagem_neutra_sem_vazar_detalhe(client, usuario_ia, monkeypatch):
    class Quebrado:
        nome, rotulo = "quebrado", "provedor de teste"

        def responder(self, *_a, **_k):
            raise RuntimeError("segredo-interno ORA-12345 traceback")

    marco = marco_da_trilha()
    usar_roteiro(monkeypatch, Quebrado())
    r = perguntar_http(client, usuario_ia, "x")
    assert r["estado"] == "erro" and "segredo-interno" not in json.dumps(r) and "ORA-12345" not in json.dumps(r)
    assert [e["detalhes"]["tipo"] for e in eventos(marco, "ia.erro")] == ["provedor"]


# =========================================================== perímetro de código
def _imports(arquivo: pathlib.Path) -> set[str]:
    achados = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            achados.update(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            achados.add(no.module)
            achados.update(f"{no.module}.{a.name}" for a in no.names)
    return achados


def _arquivos_da_ia():
    return sorted(p for p in RAIZ_IA.rglob("*.py"))


def test_so_o_adaptador_fala_com_o_modulo_dono_do_dado():
    for arquivo in _arquivos_da_ia():
        if arquivo.name == "volumetria_catering.py" and arquivo.parent.name == "adaptadores":
            continue
        indevidos = {i for i in _imports(arquivo) if i.startswith("backend.volumetria")}
        assert not indevidos, f"{arquivo.relative_to(RAIZ_IA)} importa o módulo dono do dado: {indevidos}"


def test_o_adaptador_so_usa_contrato_recorte_e_service():
    permitidos = {"backend.volumetria_catering", "backend.volumetria_catering.contrato",
                  "backend.volumetria_catering.recorte", "backend.volumetria_catering.service"}
    usados = {i for i in _imports(RAIZ_IA / "adaptadores" / "volumetria_catering.py") if i.startswith("backend.volumetria")}
    assert usados <= permitidos, usados - permitidos
    assert "backend.volumetria_catering.service" in usados


def test_backend_ia_nao_importa_driver_conexao_nem_abre_cursor():
    proibidos = ("oracledb", "psycopg", "psycopg2", "sqlite3", "backend.volumetria_catering.conexao_dw",
                 "backend.volumetria_catering.schema_dw", "backend.volumetria_catering.matriz_dw")
    for arquivo in _arquivos_da_ia():
        achados = _imports(arquivo)
        assert not [i for i in achados if i.split(".")[0] in ("oracledb", "psycopg", "psycopg2", "sqlite3")], arquivo
        assert not [i for i in achados if i in proibidos], arquivo
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        chamadas = {n.func.attr for n in ast.walk(arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "cursor" not in chamadas, f"{arquivo.name} abre cursor"


def test_nenhum_arquivo_da_ia_tem_sql_de_escrita_no_dw():
    """O que a IA grava é no banco do Hub (tabelas ia_*), por SQLAlchemy; não há
    literal de comando de escrita em texto SQL."""
    import re
    padrao = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE|TRUNCATE)\b", re.I)
    for arquivo in _arquivos_da_ia():
        if arquivo.suffix == ".py":
            achados = [c.value for c in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8")))
                       if isinstance(c, ast.Constant) and isinstance(c.value, str) and padrao.search(c.value)]
            assert not achados, f"{arquivo.name}: {achados}"


def test_o_contrato_nao_expoe_funcao_nem_arquivo_ao_modelo(client, usuario_ia, monkeypatch):
    roteiro = usar_roteiro(monkeypatch, Roteiro([("descrever", {"dominio": DOMINIO}), ("listar_capacidades", {})]))
    perguntar_http(client, usuario_ia, "x")
    visto = json.dumps(roteiro.resultados, ensure_ascii=False)
    for interno in ("service.matriz", "backend/", "FATO_VOL", "DM_VOLUMETRIA", "DW_LEITURA", "Maria Eduarda",
                    "catering_to_dw", "responsavel", "funcao"):
        assert interno not in visto, interno
