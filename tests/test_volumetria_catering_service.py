"""Volumetria de catering — o serviço (`service.py`), Lote 1 do SuperfrioIA.

O lote extraiu do `router.py` a abertura do cursor, a conferência de contrato do
DW e a montagem do `Filtros`, para a IA chamar uma **função** em vez de uma rota.
A promessa é "mesmo comportamento", e este arquivo a prova de quatro jeitos:

- **equivalência**: para o mesmo recorte e o mesmo DW falso, a rota e
  `service.matriz()` devolvem a mesma resposta **e emitem os mesmos comandos**;
- **erros**: DW fora, credencial ausente, contrato divergente e erro do driver no
  meio da consulta são `VolumetriaIndisponivel` no serviço e 503 com a **mesma
  mensagem** na rota; filtro inválido é `FiltroInvalido` e 400 com a mesma
  mensagem;
- **ordem**: conectar -> conferir o contrato -> consultar, e a conexão sempre
  fechada;
- **pureza**: `service.py` e tudo que ele importa dentro do pacote não conhecem
  FastAPI.

Nenhum teste daqui conecta no DW: o cursor é de mentira (e estoura em qualquer
comando que não seja `SELECT`, como a guarda de runtime de
`test_volumetria_catering_dw.py`). Os arquivos `*_dw.py` e o `matriz.py` não são
tocados pelo lote; a prova de que não foram é o `git diff`, não um teste.
"""

import ast
import json
import pathlib
import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from backend.volumetria_catering import (
    conexao_dw,
    contrato,
    dimensoes_dw,
    recorte,
    schema_dw,
    service,
)

BASE = "/api/volumetria-catering"
PERIODO = {"de": "2026-01-01", "ate": "2026-02-28"}
PACOTE = "backend.volumetria_catering"
RAIZ_DO_PACOTE = pathlib.Path(__file__).resolve().parent.parent / "backend" / "volumetria_catering"

TIPO_NO_DW = {
    "TEXT": "VARCHAR2", "INTEGER": "NUMBER", "SMALLINT": "NUMBER",
    "NUMERIC(18,3)": "NUMBER", "DATE": "DATE", "TIMESTAMP": "DATE",
}


# ------------------------------------------------------------ o DW de mentira
def _catalogo_do_contrato(movimento, **sobrescritas):
    tipos = {
        contrato.coluna_dw(nome, movimento): TIPO_NO_DW[tipo]
        for nome, tipo, _nulo in contrato.colunas(movimento)
    }
    tipos.update(sobrescritas)
    return tipos


def _tabela_curta(movimento):
    return contrato.tabela(movimento).partition(".")[2]


def _catalogo_bom():
    return {m: _catalogo_do_contrato(m) for m in contrato.MOVIMENTOS}


_UNIDADES_DA_FONTE = ["RMSPV", "RMSPIV", "RMSPII", "RMRJ"]  # RMSPV e RMSPIV colidem na exibida
_CLIENTES = [("67945071", "NOVITA"), ("12345678", "SAPORE"), ("55555555", "NOVO CLIENTE LTDA")]
_OPERACOES = ["OP A", "OP B"]
_MESES = ["2026-01", "2026-02"]


def _linhas_do_fato(sql, n_unidades):
    """As linhas que o DW devolveria, montadas a partir dos **apelidos do
    próprio SELECT** (`chave_0`, `rotulo_1`, `mes`, `medida_*`, `linhas`). Sem
    estado: a mesma consulta devolve sempre o mesmo, que é o que deixa a rota e
    o serviço serem comparados sobre o mesmo dado. Não avalia o `WHERE`."""
    aliases = re.findall(r"\bAS (\w+)", sql.split("\n", 1)[0])
    unidades = (_UNIDADES_DA_FONTE
                + [f"U{i:02d}" for i in range(len(_UNIDADES_DA_FONTE), n_unidades)])[:n_unidades]
    operacoes = _OPERACOES if "chave_2" in aliases else [None]
    medidas = [a for a in aliases if a.startswith("medida_")]
    linhas = []
    for ui, unidade in enumerate(unidades):
        for ci, (chave, grafia) in enumerate(_CLIENTES):
            for oi, operacao in enumerate(operacoes):
                for mi, mes in enumerate(_MESES):
                    base = 100 * (ui + 1) + 10 * (ci + 1) + 3 * oi + mi
                    registro = []
                    for alias in aliases:
                        if alias == "chave_0":
                            registro.append(unidade)
                        elif alias == "chave_1":
                            registro.append(chave)
                        elif alias == "rotulo_1":
                            registro.append(grafia)
                        elif alias == "chave_2":
                            registro.append(operacao)
                        elif alias == "mes":
                            registro.append(mes)
                        elif alias == "linhas":
                            registro.append(Decimal(1))
                        else:  # medida_*: um valor por medida, distinto entre as faixas
                            registro.append(Decimal(f"{base + 7 * medidas.index(alias)}.500"))
                    linhas.append(tuple(registro))
    return aliases, linhas


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self.arraysize = 100
        self.prefetchrows = 2
        self.description = []
        self._resultado = []

    def __enter__(self):
        return self

    def __exit__(self, *_excecao):
        return False

    def execute(self, sql, binds=None):
        self.conexao.executados.append((sql, dict(binds or {})))
        if not sql.lstrip().upper().startswith("SELECT"):  # guarda de runtime
            raise AssertionError(f"comando que não é leitura: {sql!r}")
        if "ALL_TAB_COLUMNS" in sql:
            tabela = binds["tabela"]
            self._resultado = list(self.conexao.catalogo.get(tabela, {}).items())
        elif "WHERE 1=0" in sql:
            self._resultado = []
        else:
            # a consulta da Matriz: só ela falha, depois de a conferência do
            # contrato passar — o `garantir` converte qualquer falha DELE em
            # "contrato divergente", e esse é outro caminho (já testado acima)
            if self.conexao.erro_na_consulta is not None:
                raise self.conexao.erro_na_consulta
            aliases, linhas = _linhas_do_fato(sql, self.conexao.n_unidades)
            self.description = [(a.upper(),) for a in aliases]
            self._resultado = linhas

    def fetchall(self):
        return list(self._resultado)

    def fetchone(self):
        return self._resultado[0] if self._resultado else None


class ConexaoFalsa:
    def __init__(self, catalogo=None, erro_na_consulta=None, n_unidades=4):
        self.catalogo = {_tabela_curta(m): c for m, c in (catalogo or _catalogo_bom()).items()}
        self.erro_na_consulta = erro_na_consulta
        self.n_unidades = n_unidades
        self.executados = []
        self.fechada = False

    def cursor(self):
        return CursorFalso(self)

    def close(self):
        self.fechada = True


def _dim_falsa():
    return dimensoes_dw.Dimensoes(
        unidades_fonte=["RMSPV", "RMSPII", "RMRJ"],
        nomes_estoque=["CONG FLV (CUCINARE)", "SECO GERAL", "RESFRIADO - PR", "QUALQUER COISA"],
        operacoes={"rec": ["OP A", "OP B"], "exp": ["OP A", "OP B"]},
        clientes_rotulo={"67945071": "CONVIDA", "12345678": "SAPORE"},
        clientes_grafias={"67945071": [("CONVIDA", 900.0), ("NOVITA", 100.0)],
                          "12345678": [("SAPORE", 50.0)]},
        periodo=(date(2023, 1, 1), date(2026, 9, 5)),
        atualizado_em={"rec": datetime(2026, 9, 5, 7, 5), "exp": datetime(2026, 9, 5, 7, 10)},
    )


def _aquecer():
    dimensoes_dw._cache["dados"] = _dim_falsa()
    dimensoes_dw._cache["expira_em"] = float("inf")


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Nenhum teste daqui herda credencial do ambiente, e os caches (drift do
    contrato e dimensões) são zerados nas duas pontas."""
    for var in (conexao_dw.ENV_USUARIO, conexao_dw.ENV_SENHA, conexao_dw.ENV_HOST,
                conexao_dw.ENV_PORTA, conexao_dw.ENV_SERVICO, "DW_TABELA_REC", "DW_TABELA_EXP"):
        monkeypatch.delenv(var, raising=False)
    schema_dw.invalidar()
    dimensoes_dw.invalidar()
    yield
    schema_dw.invalidar()
    dimensoes_dw.invalidar()


def _conectar_em(monkeypatch, **kwargs):
    """Uma conexão falsa nova no lugar de `conexao_dw.conectar()`. O cache de
    drift é zerado: cada chamada confere o contrato, para as duas sequências de
    comandos serem comparáveis."""
    schema_dw.invalidar()
    conexao = ConexaoFalsa(**kwargs)
    monkeypatch.setattr(conexao_dw, "conectar", lambda: conexao)
    return conexao


def _como_json(valor):
    """O que a rota faz com o `Decimal`: vira texto, para não passar por `float`."""
    return json.loads(json.dumps(valor, default=str))


# ===================================================== equivalência rota x serviço
# (nome do caso, campos do serviço). A rota recebe os mesmos campos pelos nomes
# da query string (`unidade`, `cliente`, ...).
CASOS = {
    "entrada": dict(movimento="rec", lente="liq"),
    "saida-solicitado": dict(movimento="exp", lente="liq", faixa="solicitado"),
    "saida-atendido": dict(movimento="exp", lente="liq", faixa="atendido"),
    "saida-separado-volume": dict(movimento="exp", lente="vol", faixa="separado"),
    "conjunta": dict(movimento="amb", lente="liq", faixa="atendido"),
    "unidade-e-cliente": dict(movimento="rec", unidades=["RMSPIV"], clientes=["67945071"]),
    "dias-do-mes": dict(movimento="rec", dias=["3", "1", "2"]),
    "operacao": dict(movimento="rec", operacoes=["OP A"]),
    "tipo-de-estoque-e-valor": dict(movimento="rec", lente="val", tipos_estoque=["SECO"]),
    "pallet-na-saida": dict(movimento="exp", lente="pal"),
}
_NOME_NA_ROTA = {"unidades": "unidade", "clientes": "cliente", "tipos_estoque": "tipo_estoque",
                 "operacoes": "operacao", "dias": "dia"}


def _params_da_rota(campos):
    params = dict(PERIODO)
    for nome, valor in campos.items():
        params[_NOME_NA_ROTA.get(nome, nome)] = valor
    return params


@pytest.mark.parametrize("caso", list(CASOS), ids=list(CASOS))
def test_matriz_da_rota_e_do_servico_sao_a_mesma_resposta(caso, client, admin_headers, monkeypatch):
    """Mesmo recorte, mesmo DW: a resposta é igual **e os comandos emitidos
    também** — inclusive a conferência de contrato que vem antes da consulta."""
    campos = CASOS[caso]
    _aquecer()

    na_rota = _conectar_em(monkeypatch)
    r = client.get(f"{BASE}/matriz", params=_params_da_rota(campos), headers=admin_headers)
    assert r.status_code == 200, r.text

    no_servico = _conectar_em(monkeypatch)
    direto = service.matriz(service.filtros_de(**PERIODO, **campos))

    assert r.json() == _como_json(direto)
    assert na_rota.executados == no_servico.executados
    assert na_rota.fechada and no_servico.fechada


def test_os_casos_cobrem_o_que_a_matriz_tem_de_diferente(client, admin_headers, monkeypatch):
    """Guarda do próprio teste: se os casos virassem todos iguais, a equivalência
    provaria pouco. Entrada, saída, conjunta e pallet na saída têm árvores e
    avisos diferentes."""
    _aquecer()
    niveis, avisos = {}, {}
    for caso in ("entrada", "saida-atendido", "conjunta", "pallet-na-saida"):
        _conectar_em(monkeypatch)
        d = service.matriz(service.filtros_de(**PERIODO, **CASOS[caso]))
        niveis[caso] = d["niveis"]
        avisos[caso] = d["avisos"]
    assert niveis["entrada"] == ["unidade", "cliente", "operacao"]
    assert niveis["saida-atendido"] == ["unidade", "cliente", "faixa", "operacao"]
    assert niveis["conjunta"] == ["unidade", "cliente", "movimento"]
    assert any("só existe na entrada" in a for a in avisos["pallet-na-saida"])
    assert any("não somam entre si" in a for a in avisos["saida-atendido"])


def test_siglas_que_colidem_somam_pelo_servico_como_pela_tela(monkeypatch):
    """`RMSPV` e `RMSPIV` da fonte viram uma linha só (`RMSPIV`): é a decisão da
    tela, e o serviço a entrega sem ninguém precisar refazê-la."""
    _aquecer()
    _conectar_em(monkeypatch)
    d = service.matriz(service.filtros_de(**PERIODO, movimento="rec"))
    assert [u["chave"] for u in d["linhas"]] == ["RMRJ", "RMSPII", "RMSPIV"]


def test_mais_de_12_unidades_paginam_e_o_total_e_do_recorte_inteiro(client, admin_headers, monkeypatch):
    """14 unidades: página 1 com 12, página 2 com 2. O `total` é o do recorte
    inteiro nas duas, e a rota devolve o mesmo que o serviço em cada página.
    É o que o ranking da IA vai precisar percorrer (DD-20)."""
    _aquecer()
    por_pagina = {}
    for pagina in (1, 2):
        na_rota = _conectar_em(monkeypatch, n_unidades=14)
        r = client.get(f"{BASE}/matriz", params={**PERIODO, "pagina": pagina}, headers=admin_headers)
        assert r.status_code == 200, r.text
        _conectar_em(monkeypatch, n_unidades=14)
        direto = service.matriz(service.filtros_de(**PERIODO, pagina=pagina))
        assert r.json() == _como_json(direto)
        por_pagina[pagina] = direto
        assert na_rota.fechada

    # 14 siglas da fonte, mas RMSPV e RMSPIV colidem: 13 exibidas
    assert por_pagina[1]["paginacao"]["total_unidades"] == 13
    assert por_pagina[1]["paginacao"]["paginas"] == 2
    assert len(por_pagina[1]["linhas"]) == 12 and len(por_pagina[2]["linhas"]) == 1
    assert por_pagina[1]["total"] == por_pagina[2]["total"]
    visitadas = [u["chave"] for p in (1, 2) for u in por_pagina[p]["linhas"]]
    assert visitadas == sorted(visitadas) and len(set(visitadas)) == 13


def test_opcoes_da_rota_e_do_servico_sao_a_mesma_resposta(client, admin_headers, monkeypatch):
    _aquecer()
    _conectar_em(monkeypatch)
    r = client.get(f"{BASE}/opcoes", headers=admin_headers)
    assert r.status_code == 200, r.text
    _conectar_em(monkeypatch)
    direto = service.opcoes()
    assert r.json() == direto  # já é JSON puro: sem Decimal, datas em texto
    for chave in ("unidades", "clientes", "operacoes", "tipos_estoque", "periodo", "abertura",
                  "atualizado_ate", "rotulos_calculados_em", "lentes", "faixas", "movimentos"):
        assert chave in direto
    assert "fonte" not in direto and "cargas" not in direto  # saíram no C6


# ================================================================= filtros_de
def test_filtros_de_tem_o_mesmo_padrao_da_rota():
    """O padrão da IA para a faixa (`atendido`, DD-15) é do adaptador. Aqui vale
    o da rota, para o serviço não mudar o que a tela vê."""
    f = service.filtros_de(**PERIODO)
    assert (f.movimento, f.lente, f.faixa, f.pagina) == ("rec", "liq", "solicitado", 1)
    assert f.unidades == f.clientes == f.tipos_estoque == f.operacoes == f.dias == ()


def test_filtros_de_guarda_tupla_e_normaliza_os_dias():
    f = service.filtros_de(**PERIODO, unidades=["A", "B"], clientes=("1",), dias=["03", "1", "1"])
    assert f.unidades == ("A", "B") and f.clientes == ("1",)
    assert f.dias == (1, 3)


def test_filtros_de_recusa_o_que_o_contrato_nao_admite():
    invalidos = [
        dict(**PERIODO, lente="kg"),
        dict(**PERIODO, movimento="estoque"),
        dict(**PERIODO, faixa="embarcado"),
        dict(de="2026-03-01", ate="2026-01-01"),
        dict(de="2026-02-30", ate="2026-03-01"),
        dict(**PERIODO, dias=["32"]),
        dict(**PERIODO, pagina=0),
        dict(**PERIODO, movimento="amb", operacoes=["OP A"]),
        dict(**PERIODO, cliente_chave="67945071"),   # campo fora do contrato
        dict(**PERIODO, unidades="RMSPIV"),          # string não é lista
        dict(de="2026-01-01"),                       # falta `ate`
    ]
    for campos in invalidos:
        with pytest.raises(recorte.FiltroInvalido):
            service.filtros_de(**campos)


def test_filtro_invalido_e_400_na_rota_com_a_mesma_mensagem_do_servico(client, admin_headers, monkeypatch):
    conexao = _conectar_em(monkeypatch)
    casos = [
        (dict(lente="kg"), dict(lente="kg")),
        (dict(de="2026-03-01", ate="2026-01-01"), dict(de="2026-03-01", ate="2026-01-01")),
        (dict(movimento="amb", operacoes=["OP A"]), dict(movimento="amb", operacao=["OP A"])),
        (dict(dias=["32"]), dict(dia=["32"])),
    ]
    for no_servico, na_rota in casos:
        with pytest.raises(recorte.FiltroInvalido) as erro:
            service.filtros_de(**{**PERIODO, **no_servico})
        r = client.get(f"{BASE}/matriz", params={**PERIODO, **na_rota}, headers=admin_headers)
        assert r.status_code == 400
        assert r.json()["detail"] == str(erro.value)
    assert conexao.executados == [], "400 sai antes de tocar no DW"


# ===================================================== indisponibilidade -> 503
def _indisponivel(chamada):
    with pytest.raises(service.VolumetriaIndisponivel) as erro:
        chamada()
    return str(erro.value)


def test_sem_credencial_e_indisponivel_no_servico_e_503_na_rota(client, admin_headers):
    filtros = service.filtros_de(**PERIODO)
    mensagem = _indisponivel(lambda: service.matriz(filtros))
    assert conexao_dw.ENV_USUARIO in mensagem
    assert _indisponivel(service.opcoes) == mensagem
    for rota in ("/matriz", "/opcoes"):
        r = client.get(f"{BASE}{rota}", params=PERIODO if rota == "/matriz" else {}, headers=admin_headers)
        assert r.status_code == 503
        assert r.json()["detail"] == mensagem


def test_contrato_divergente_e_indisponivel_com_a_coluna_e_503_com_a_mesma_mensagem(
    client, admin_headers, monkeypatch
):
    catalogo = _catalogo_bom()
    catalogo["rec"] = _catalogo_do_contrato("rec", NK_CALENDARIO="VARCHAR2")
    filtros = service.filtros_de(**PERIODO)

    conexao = _conectar_em(monkeypatch, catalogo=catalogo)
    mensagem = _indisponivel(lambda: service.matriz(filtros))
    assert "NK_CALENDARIO" in mensagem
    assert conexao.fechada

    _conectar_em(monkeypatch, catalogo=catalogo)
    r = client.get(f"{BASE}/matriz", params=PERIODO, headers=admin_headers)
    assert r.status_code == 503 and r.json()["detail"] == mensagem


def test_erro_do_driver_no_meio_da_consulta_e_indisponivel_e_503(client, admin_headers, monkeypatch):
    """Erro de rede é `oracledb.Error`: neste card ele vira indisponibilidade,
    não 500. O módulo do erro é o que o serviço olha (sem importar o driver)."""
    erro_do_driver = type("DatabaseError", (Exception,), {"__module__": "oracledb"})("DPY-4011")
    filtros = service.filtros_de(**PERIODO)

    conexao = _conectar_em(monkeypatch, erro_na_consulta=erro_do_driver)
    mensagem = _indisponivel(lambda: service.matriz(filtros))
    assert "DatabaseError" in mensagem and "o resto do Hub continua funcionando" in mensagem
    assert conexao.fechada

    _conectar_em(monkeypatch, erro_na_consulta=erro_do_driver)
    r = client.get(f"{BASE}/matriz", params=PERIODO, headers=admin_headers)
    assert r.status_code == 503 and r.json()["detail"] == mensagem


def test_erro_que_nao_e_do_driver_nao_vira_indisponivel(monkeypatch):
    """Bug nosso continua sendo bug: só o erro do Oracle é "DW fora"."""
    conexao = _conectar_em(monkeypatch, erro_na_consulta=RuntimeError("defeito de programação"))
    with pytest.raises(RuntimeError):
        service.matriz(service.filtros_de(**PERIODO))
    assert conexao.fechada


def test_erro_do_oracle_olha_o_modulo_do_erro():
    assert service.erro_do_oracle(type("E", (Exception,), {"__module__": "oracledb.exceptions"})())
    assert not service.erro_do_oracle(ValueError())


# ======================================================================== ordem
def test_conecta_confere_o_contrato_e_so_depois_consulta(monkeypatch):
    """A ordem decide quando o 503 sai. Conferência do contrato (catálogo e
    `WHERE 1=0`) antes de qualquer consulta da Matriz, conexão fechada no fim."""
    _aquecer()
    conexao = _conectar_em(monkeypatch)
    service.matriz(service.filtros_de(**PERIODO, movimento="rec"))
    comandos = [sql for sql, _ in conexao.executados]
    primeira_da_matriz = next(i for i, sql in enumerate(comandos) if "GROUP BY" in sql)
    conferencias = [i for i, sql in enumerate(comandos) if "ALL_TAB_COLUMNS" in sql or "WHERE 1=0" in sql]
    assert conferencias and max(conferencias) < primeira_da_matriz
    assert conexao.fechada


def test_o_servico_nao_cria_cache_a_segunda_chamada_reusa_o_das_dimensoes(monkeypatch):
    """O cache é o de `dimensoes_dw.obter` (por processo, TTL de 1 h). Com o
    retrato aquecido, nenhuma consulta de dimensão é emitida."""
    _aquecer()
    conexao = _conectar_em(monkeypatch)
    service.opcoes()
    assert not any("DISTINCT" in sql.upper() for sql, _ in conexao.executados)


# ====================================================================== pureza
def _modulos_importados(arquivo):
    achados = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            achados.update(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            achados.add(no.module)
            if no.module == PACOTE:  # `from backend.volumetria_catering import a, b`
                achados.update(f"{PACOTE}.{a.name}" for a in no.names)
    return achados


def _fecho_dos_imports(arquivo_inicial):
    """Todo módulo que `service.py` alcança importando — dentro do pacote da
    volumetria, seguindo os arquivos; fora dele, só o nome."""
    pendentes, vistos = [arquivo_inicial], set()
    while pendentes:
        arquivo = pendentes.pop()
        for modulo in _modulos_importados(arquivo):
            if modulo in vistos:
                continue
            vistos.add(modulo)
            if modulo.startswith(f"{PACOTE}."):
                filho = RAIZ_DO_PACOTE / (modulo.removeprefix(f"{PACOTE}.") + ".py")
                if filho.exists():
                    pendentes.append(filho)
    return vistos


def test_o_servico_nao_conhece_fastapi_nem_nada_que_o_importe():
    """O adaptador da IA vai importar `service`. Se alguma coisa no caminho
    puxasse FastAPI, a IA passaria a depender do servidor web, e a camada de
    serviço deixaria de ser uma função."""
    fecho = _fecho_dos_imports(RAIZ_DO_PACOTE / "service.py")

    # a prova não é vazia: o fecho enxerga o cálculo que o serviço usa
    for esperado in ("matriz_dw", "matriz", "recorte", "contrato", "dimensoes_dw", "conexao_dw"):
        assert f"{PACOTE}.{esperado}" in fecho, esperado

    proibidos = [m for m in fecho if m.split(".")[0] in ("fastapi", "starlette")]
    assert proibidos == []
    assert f"{PACOTE}.router" not in fecho
    assert not any(m.startswith("backend.auth") for m in fecho)


def test_o_servico_nao_emite_nem_importa_nada_de_escrita():
    """Complemento da guarda de `test_volumetria_catering_dw.py`, que varre os
    `*_dw.py`: o serviço não tem SQL, e tem que continuar sem ter."""
    arvore = ast.parse((RAIZ_DO_PACOTE / "service.py").read_text(encoding="utf-8"))
    chamadas = {no.func.attr for no in ast.walk(arvore)
                if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)}
    assert not chamadas & {"commit", "rollback", "executemany", "execute"}
