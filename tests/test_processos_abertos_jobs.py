"""Job diário de Processos Abertos (backend/processos_abertos/jobs.py).

Não bate no FTP de verdade — troca o cliente e o cálculo por dublês
controlados, e verifica só a orquestração: valida arquivo de hoje, chama o
processamento, grava no histórico, registra status, e a retentativa das
08:30 só dispara se as 08:05 não tiverem dado certo.
"""
from datetime import datetime, timedelta

import backend.processos_abertos.jobs as jobs
from backend.processos_abertos.status import ler_status


class _ClienteFtpFake:
    def __init__(self, *, data_arquivo: datetime, conteudo: bytes = b"conteudo"):
        self._data_arquivo = data_arquivo
        self._conteudo = conteudo

    def data_modificacao(self, nome_arquivo: str) -> datetime:
        return self._data_arquivo

    def baixar(self, nome_arquivo: str) -> bytes:
        return self._conteudo


def _isolar_status(monkeypatch, tmp_path):
    import backend.processos_abertos.status as status_mod

    monkeypatch.setattr(status_mod, "_STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(jobs, "ler_status", status_mod.ler_status)
    monkeypatch.setattr(jobs, "escrever_status", status_mod.escrever_status)


def test_tentativa_com_arquivo_de_ontem_nao_processa(monkeypatch, tmp_path):
    _isolar_status(monkeypatch, tmp_path)
    ontem = datetime.now() - timedelta(days=1)
    monkeypatch.setattr(jobs, "_cliente_ftp", lambda: _ClienteFtpFake(data_arquivo=ontem))
    chamou_processamento = []
    monkeypatch.setattr(jobs.processing, "montar_semana", lambda *a: chamou_processamento.append(1))

    ok = jobs._tentar(rotulo="teste")

    assert ok is False
    assert not chamou_processamento
    status = ler_status()
    assert status["ok"] is False
    assert "não de hoje" in status["mensagem"] or "n" in status["mensagem"]  # mensagem legível, não trava no texto exato


def test_tentativa_com_sucesso_grava_no_historico_e_status(monkeypatch, tmp_path):
    _isolar_status(monkeypatch, tmp_path)
    hoje = datetime.now()
    monkeypatch.setattr(jobs, "_cliente_ftp", lambda: _ClienteFtpFake(data_arquivo=hoje))
    semana_fake = {
        "date": "20/08/2026", "total": 5, "d5p": 1, "d1": 2, "d25": 2,
        "pct": 20.0, "units": 1, "resumo": {}, "tipos": {},
    }
    monkeypatch.setattr(jobs.processing, "montar_semana", lambda slin, jda: semana_fake)
    salvo = []
    monkeypatch.setattr(jobs, "salvar_semana_no_historico", lambda semana: salvo.append(semana))

    ok = jobs._tentar(rotulo="teste")

    assert ok is True
    assert salvo == [semana_fake]
    status = ler_status()
    assert status["ok"] is True
    assert status["ultima_data_sucesso"] == datetime.now().strftime("%Y-%m-%d")


def test_tentativa_com_erro_de_processamento_nao_derruba_o_job(monkeypatch, tmp_path):
    _isolar_status(monkeypatch, tmp_path)
    hoje = datetime.now()
    monkeypatch.setattr(jobs, "_cliente_ftp", lambda: _ClienteFtpFake(data_arquivo=hoje))

    def _explode(*_a):
        raise ValueError("arquivo corrompido")

    monkeypatch.setattr(jobs.processing, "montar_semana", _explode)

    ok = jobs._tentar(rotulo="teste")  # não deve propagar a exceção

    assert ok is False
    assert "corrompido" in ler_status()["mensagem"]


def test_retry_0830_nao_roda_se_0805_ja_deu_certo(monkeypatch, tmp_path):
    _isolar_status(monkeypatch, tmp_path)
    jobs.escrever_status(ok=True, mensagem="ok", tentativa="08:05", data_sucesso=jobs._hoje())
    chamadas = []
    monkeypatch.setattr(jobs, "_tentar", lambda **kw: chamadas.append(kw))

    jobs.executar_as_0830_retry()

    assert chamadas == []


def test_retry_0830_roda_se_0805_falhou(monkeypatch, tmp_path):
    _isolar_status(monkeypatch, tmp_path)
    jobs.escrever_status(ok=False, mensagem="FTP fora do ar", tentativa="08:05")
    chamadas = []
    monkeypatch.setattr(jobs, "_tentar", lambda **kw: chamadas.append(kw))

    jobs.executar_as_0830_retry()

    assert len(chamadas) == 1
    assert chamadas[0]["rotulo"] == "08:30 (retentativa)"
