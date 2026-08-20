"""Testes do cálculo de Processos Abertos (backend/processos_abertos/processing.py).

Cobre a fidelidade da porta pra Python de `frontend/processos-abertos/app.js`
(processFiles()): de-para de unidade, de-para de categoria, filtro de "em
aberto", bucket de dias e as particularidades documentadas (LPN sempre
"> 5 dias", Recebimento/Expedição somando JDA + SLIN).
"""
import io
from datetime import datetime

from openpyxl import Workbook

from backend.processos_abertos import processing


def _workbook_bytes(abas: dict) -> bytes:
    """`abas` é {nome_da_aba: [[cabecalho...], [linha1...], ...]}, na ordem
    em que devem aparecer no arquivo (a leitura do SLIN é por posição)."""
    wb = Workbook()
    wb.remove(wb.active)
    for nome, linhas in abas.items():
        ws = wb.create_sheet(nome)
        for linha in linhas:
            ws.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _slin_minimo(*, portaria=None, recebimento=None, expedicao=None, lpn=None) -> bytes:
    cabecalho_evento = ["nome_und", "operacao", "dthr_chegada", "status_portaria"]
    cabecalho_lpn = ["nome_und"]
    return _workbook_bytes({
        "Portaria": [cabecalho_evento] + (portaria or []),
        "Recebimento": [["nome_und", "dthr_chegada"]] + (recebimento or []),
        "Expedicao": [["nome_und", "dthr_chegada"]] + (expedicao or []),
        "LPN": [cabecalho_lpn] + (lpn or []),
    })


def _jda_minimo(linhas=None) -> bytes:
    cabecalho = ["Unidade", "Sub Grupo", "Qtd Total", "1D", "2D", "3D", "4D", "5D", "> 5D"]
    return _workbook_bytes({"Sheet0": [cabecalho] + (linhas or [])})


REF = datetime(2026, 8, 20)


def test_arquivo_slin_sem_4_abas_da_erro_claro():
    ruim = _workbook_bytes({"Portaria": [["nome_und"]]})
    jda = _jda_minimo()
    try:
        processing.montar_semana(ruim, jda)
        assert False, "devia ter levantado ProcessamentoError"
    except processing.ProcessamentoError as exc:
        assert "4 abas" in str(exc)


def test_arquivo_jda_sem_sheet0_da_erro_claro():
    slin = _slin_minimo(recebimento=[["MAQ", REF]])
    ruim = _workbook_bytes({"OutraAba": [["Unidade"]]})
    try:
        processing.montar_semana(slin, ruim)
        assert False, "devia ter levantado ProcessamentoError"
    except processing.ProcessamentoError as exc:
        assert "Sheet0" in str(exc)


def test_de_para_unidade_aplica_alias():
    # "MAIRINQUE" (nome cru do SLIN) deve virar "MAQ" (sigla oficial) tanto no
    # JDA quanto no SLIN.
    slin = _slin_minimo(
        recebimento=[["MAIRINQUE", REF]],
        portaria=[["MAIRINQUE", "Descarga", REF, "Aberto"]],
    )
    jda = _jda_minimo([["MAIRINQUE", "01 - Recebimento em aberto", 5, 5, 0, 0, 0, 0, 0]])

    semana = processing.montar_semana(slin, jda)

    assert "MAQ" in semana["resumo"]
    assert "MAIRINQUE" not in semana["resumo"]


def test_de_para_categoria_operacao_slin():
    slin = _slin_minimo(
        recebimento=[["RMRJ", REF]],
        portaria=[["RMRJ", "Cross Docking", REF, "Aberto"]],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    assert "04 - Portaria em aberto - Cross Docking" in semana["tipos"]
    assert semana["tipos"]["04 - Portaria em aberto - Cross Docking"]["total"] == 1


def test_filtro_concluido_exclui_linha():
    slin = _slin_minimo(
        recebimento=[["RMRJ", REF]],
        portaria=[
            ["RMRJ", "Descarga", REF, "Concluído"],
            ["RMRJ", "Descarga", REF, "Aberto"],
        ],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    # 1 da linha de Recebimento (usada tb como referência de data) + 1 da
    # Portaria "Aberto" — a "Concluído" não deve entrar.
    assert semana["resumo"]["RMRJ"]["total"] == 2


def test_bucket_de_dias_calculado_a_partir_da_data():
    # Recebimento usa a maior data como referência: 20/08. Uma linha de
    # Portaria de 17/08 fica a 3 dias -> cai em d3.
    slin = _slin_minimo(
        recebimento=[["RMRJ", REF]],
        portaria=[["RMRJ", "Descarga", datetime(2026, 8, 17), "Aberto"]],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    assert semana["resumo"]["RMRJ"]["d3"] == 1
    # +1 da própria linha de Recebimento usada como referência de data (dias=0)
    assert semana["resumo"]["RMRJ"]["total"] == 2


def test_data_como_texto_tambem_e_parseada():
    # Simula um arquivo onde a coluna de data veio como texto formatado
    # (equivalente ao {raw:false} do lado JS), não como tipo data do Excel.
    slin = _slin_minimo(
        recebimento=[["RMRJ", "20/08/2026 08:00:00"]],
        portaria=[["RMRJ", "Descarga", "18/08/2026 10:00:00", "Aberto"]],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    assert semana["date"] == "20/08/2026"
    assert semana["resumo"]["RMRJ"]["d2"] == 1


def test_lpn_sempre_conta_como_mais_de_5_dias():
    slin = _slin_minimo(
        recebimento=[["RMRJ", REF]],
        lpn=[["RMRJ"], ["RMRJ"], ["CWBII"]],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    assert semana["tipos"]["06 - LPN Armazém"]["total"] == 3
    assert semana["tipos"]["06 - LPN Armazém"]["d5p"] == 3
    assert semana["resumo"]["RMRJ"]["d5p"] == 2
    assert semana["resumo"]["CWBII"]["d5p"] == 1


def test_recebimento_soma_jda_e_slin_na_mesma_categoria():
    # JDA já traz 1 unidade em "01 - Recebimento em aberto"; o SLIN contribui
    # mais 1 pela aba Recebimento — os dois devem se SOMAR, não substituir.
    slin = _slin_minimo(recebimento=[["RMRJ", REF]])
    jda = _jda_minimo([["RMRJ", "01 - Recebimento em aberto", 1, 1, 0, 0, 0, 0, 0]])

    semana = processing.montar_semana(slin, jda)

    # 1 do JDA (Qtd Total) + 1 do SLIN (a própria linha usada como refDate)
    assert semana["tipos"]["01 - Recebimento em aberto"]["total"] == 2


def test_totais_gerais_e_percentual():
    slin = _slin_minimo(
        recebimento=[["RMRJ", REF]],
        portaria=[
            ["RMRJ", "Descarga", REF, "Aberto"],  # dias=0 -> só soma total
            ["RMRJ", "Descarga", datetime(2026, 8, 13), "Aberto"],  # 7 dias -> d5p
        ],
    )
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    # total = 1 (linha de Recebimento, dias=0) + 1 (Portaria dias=0) + 1 (Portaria 7 dias)
    assert semana["total"] == 3
    assert semana["d5p"] == 1
    assert semana["units"] == 1
    assert semana["pct"] == round(1 / 3 * 100, 1)


def test_semana_vazia_nao_quebra_e_pct_fica_zero():
    slin = _slin_minimo()
    jda = _jda_minimo()

    semana = processing.montar_semana(slin, jda)

    assert semana["total"] == 0
    assert semana["pct"] == 0.0
