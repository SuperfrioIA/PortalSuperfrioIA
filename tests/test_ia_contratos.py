"""SuperfrioIA — o contrato do domínio (YAML) validado no boot contra o código real.

Contrato inconsistente derruba a subida com uma mensagem que nomeia o erro (mesmo
padrão de `registrar_modulo`). Cada teste quebra UMA coisa e confere que a mensagem
diz qual.
"""
import copy
import pathlib
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.ia import dominios
from backend.ia.dominios import ContratoInvalido

ORIGINAL = pathlib.Path(dominios.PASTA) / "volumetria-catering.yaml"


@pytest.fixture
def contrato():
    """O YAML real, como dicionário, para cada teste quebrar uma coisa."""
    return yaml.safe_load(ORIGINAL.read_text(encoding="utf-8"))


def validar(dados):
    return dominios.validar(copy.deepcopy(dados), "volumetria-catering.yaml", "volumetria-catering")


# ===================================================================== o real
def test_o_contrato_real_valida_e_carrega():
    d = dominios.carregar(forcar=True)["volumetria-catering"]
    assert d.nome == "Volumetria de Catering" and d["modo"] == "A"
    assert d.permissao_de_aprovacao == "volumetria-catering:administrar"
    assert d.app_hub == "volumetria-catering" and d.classificacao == "interno-agregado"


def test_as_decisoes_do_contrato_estao_no_yaml(contrato):
    r = contrato["regras"]
    assert r["faixa_padrao"] == "atendido" and r["faixa_padrao_dizer"] == "atendido pelo estoque"   # DD-15
    assert "embarque" in r["faixa_padrao_nao_e"]
    assert r["top_n"] == {"padrao": 10, "teto": 20}                                                  # DD-28
    assert contrato["limites"]["consultas_por_pergunta"] == 3                                        # DD-16
    assert "embarque" not in contrato["sinonimos"]["saida"]                                          # DD-15
    assert contrato["responsavel"]["validacao_negocio"]["situacao"] == "pendente"                    # DD-19
    assert "ranking_de_cliente_entre_unidades" in contrato["nao_atendidas"]                          # DD-21
    assert contrato["escopo_usuario"]["tipo"] == "nenhum" and contrato["escopo_usuario"]["justificativa"]


# ====================================================== quebras de estrutura
@pytest.mark.parametrize("campo", ["nome", "adaptador", "app_hub", "classificacao", "modo", "responsavel",
                                   "escopo_usuario", "metricas", "capacidades", "nao_atendidas", "exemplos"])
def test_campo_obrigatorio_ausente_e_nomeado(contrato, campo):
    del contrato[campo]
    with pytest.raises(ContratoInvalido, match=f"campo obrigatório ausente: '{campo}'"):
        validar(contrato)


def test_dominio_diferente_do_nome_do_arquivo(contrato):
    contrato["dominio"] = "outro-nome"
    with pytest.raises(ContratoInvalido, match="diverge do nome do arquivo"):
        validar(contrato)


def test_modo_que_nao_existe_neste_lote(contrato):
    contrato["modo"] = "B"
    with pytest.raises(ContratoInvalido, match="modo 'B' não existe neste lote"):
        validar(contrato)


def test_escopo_sem_justificativa(contrato):
    del contrato["escopo_usuario"]["justificativa"]
    with pytest.raises(ContratoInvalido, match="escopo_usuario precisa de 'tipo' e 'justificativa'"):
        validar(contrato)


def test_permissao_de_aprovacao_que_nao_existe_no_catalogo(contrato):
    contrato["responsavel"]["acesso"] = "volumetria-catering:aprovar"
    with pytest.raises(ContratoInvalido, match="não existe no catálogo de permissões"):
        validar(contrato)


def test_adaptador_que_nao_existe(contrato):
    contrato["adaptador"] = "conciliador"
    with pytest.raises(ContratoInvalido, match="adaptador 'conciliador' não existe"):
        validar(contrato)


def test_adaptador_com_caminho_nao_passa(contrato):
    contrato["adaptador"] = "../../etc/passwd"
    with pytest.raises(ContratoInvalido, match="adaptador inválido"):
        validar(contrato)


def test_capacidades_com_nome_repetido(contrato):
    contrato["capacidades"].append(dict(contrato["capacidades"][0]))
    with pytest.raises(ContratoInvalido, match="'nome' único"):
        validar(contrato)


def test_limite_de_consultas_invalido(contrato):
    contrato["limites"]["consultas_por_pergunta"] = 0
    with pytest.raises(ContratoInvalido, match="inteiro positivo"):
        validar(contrato)


# ================================================== quebras contra o código real
def test_metrica_que_o_modulo_nao_tem(contrato):
    contrato["metricas"]["margem"] = {"nome": "Margem", "exibicao": "R$"}
    with pytest.raises(ContratoInvalido, match="metricas .* diverge das lentes do módulo"):
        validar(contrato)


def test_metrica_que_falta(contrato):
    del contrato["metricas"]["pal"]
    with pytest.raises(ContratoInvalido, match="diverge das lentes do módulo"):
        validar(contrato)


def test_unidade_da_metrica_diferente_da_do_modulo(contrato):
    contrato["metricas"]["liq"]["exibicao"] = "kg"
    with pytest.raises(ContratoInvalido, match="metrica 'liq': exibicao 'kg' diverge de 't'"):
        validar(contrato)


def test_nome_da_metrica_diferente_do_modulo(contrato):
    contrato["metricas"]["val"]["nome"] = "Faturamento"
    with pytest.raises(ContratoInvalido, match="metrica 'val': nome 'Faturamento' diverge de 'Valor'"):
        validar(contrato)


def test_pallet_que_deixa_de_ser_so_entrada(contrato):
    del contrato["metricas"]["pal"]["so_entrada"]
    with pytest.raises(ContratoInvalido, match="so_entrada diverge do módulo"):
        validar(contrato)


def test_faixa_que_nao_existe(contrato):
    contrato["faixas"]["embarcado"] = "Embarcado"
    with pytest.raises(ContratoInvalido, match="faixas .* diverge"):
        validar(contrato)


def test_faixa_padrao_desconhecida(contrato):
    contrato["regras"]["faixa_padrao"] = "embarcado"
    with pytest.raises(ContratoInvalido, match="regras.faixa_padrao 'embarcado' não é uma faixa"):
        validar(contrato)


def test_filtro_que_a_matriz_nao_oferece(contrato):
    contrato["regras"]["filtros_permitidos"].append("dia_da_semana")
    with pytest.raises(ContratoInvalido, match=r"filtros_permitidos tem campo que Filtros não tem: \['dia_da_semana'\]"):
        validar(contrato)


def test_movimento_que_o_modulo_nao_tem(contrato):
    contrato["regras"]["movimentos"].append("estoque")
    with pytest.raises(ContratoInvalido, match="regras.movimentos"):
        validar(contrato)


def test_detalhe_que_o_adaptador_nao_implementa(contrato):
    contrato["regras"]["detalhes_permitidos"].append("operacao")
    with pytest.raises(ContratoInvalido, match="detalhes_permitidos fora de"):
        validar(contrato)


@pytest.mark.parametrize("top", [{"padrao": 30, "teto": 30}, {"padrao": 0, "teto": 5}, {"padrao": 10, "teto": 5}, {}])
def test_top_n_acima_do_teto_do_produto_ou_incoerente(contrato, top):
    contrato["regras"]["top_n"] = top
    with pytest.raises(ContratoInvalido, match="regras.top_n precisa ter"):
        validar(contrato)


def test_funcao_que_nao_existe_no_servico(contrato):
    contrato["capacidades"][0]["funcao"] = "service.matriz_secreta"
    with pytest.raises(ContratoInvalido, match="a função 'service.matriz_secreta' não existe no serviço"):
        validar(contrato)


def test_funcao_fora_do_servico(contrato):
    contrato["capacidades"][0]["funcao"] = "router.api_matriz"
    with pytest.raises(ContratoInvalido, match="não existe no serviço"):
        validar(contrato)


def test_fonte_apontando_para_outro_modulo(contrato):
    contrato["fonte"]["modulo"] = "backend.volumetria_catering.router"
    with pytest.raises(ContratoInvalido, match="fonte.modulo diverge do serviço"):
        validar(contrato)


def test_app_hub_diferente_do_do_adaptador(contrato):
    contrato["app_hub"] = "volumetria-estoque"
    with pytest.raises(ContratoInvalido, match="app_hub 'volumetria-estoque' diverge"):
        validar(contrato)


# ====================================================== a pasta e o boot
def test_yaml_ilegivel_derruba_com_o_nome_do_arquivo(tmp_path, monkeypatch):
    (tmp_path / "quebrado.yaml").write_text("dominio: [sem fechar", encoding="utf-8")
    monkeypatch.setattr(dominios, "PASTA", tmp_path)
    with pytest.raises(ContratoInvalido, match="quebrado.yaml: YAML ilegível"):
        dominios.carregar(forcar=True)
    dominios.limpar_cache()


def test_yaml_quebrado_na_pasta_derruba_o_carregamento(tmp_path, monkeypatch, contrato):
    contrato["metricas"]["liq"]["exibicao"] = "kg"
    (tmp_path / "volumetria-catering.yaml").write_text(yaml.safe_dump(contrato, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(dominios, "PASTA", tmp_path)
    with pytest.raises(ContratoInvalido, match="volumetria-catering.yaml.*exibicao 'kg'"):
        dominios.carregar(forcar=True)
    dominios.limpar_cache()


def test_contrato_valido_numa_pasta_nova_carrega(tmp_path, monkeypatch):
    shutil.copy(ORIGINAL, tmp_path / "volumetria-catering.yaml")
    monkeypatch.setattr(dominios, "PASTA", tmp_path)
    assert list(dominios.carregar(forcar=True)) == ["volumetria-catering"]
    dominios.limpar_cache()


def test_contrato_invalido_derruba_o_boot_do_hub(monkeypatch):
    """O `lifespan` valida os contratos ANTES de migrations, seed e agendador, mesmo
    com `IA_HABILITADO` desligada: falha no deploy, não na primeira pergunta."""
    from backend import main

    def contrato_quebrado():
        raise ContratoInvalido("contrato volumetria-catering.yaml: metrica 'liq': exibicao 'kg' diverge de 't'")

    monkeypatch.setattr(main.ia_dominios, "carregar", contrato_quebrado)
    monkeypatch.setenv("IA_HABILITADO", "false")
    with pytest.raises(ContratoInvalido, match="metrica 'liq'"):
        with TestClient(main.app):
            pass


def test_o_boot_normal_valida_o_contrato_com_a_chave_desligada(monkeypatch):
    from backend import main
    chamadas = []
    original = main.ia_dominios.carregar
    monkeypatch.setattr(main.ia_dominios, "carregar", lambda *a, **k: (chamadas.append(1), original(*a, **k))[1])
    monkeypatch.setenv("IA_HABILITADO", "false")
    with TestClient(main.app):
        pass
    assert chamadas == [1]


def test_o_contrato_e_codigo_versionado_na_pasta_do_pacote():
    """O YAML mora em `backend/` (COPY do Dockerfile): chega à imagem no rebuild."""
    assert ORIGINAL.parent.parent.name == "ia" and ORIGINAL.parent.parent.parent.name == "backend"
