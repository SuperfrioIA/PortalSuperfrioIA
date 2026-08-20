"""Status da integração automática via FTP (backend/processos_abertos/status.py)."""
from backend.processos_abertos.status import escrever_status, ler_status


def test_status_vazio_antes_da_primeira_execucao(tmp_path, monkeypatch):
    import backend.processos_abertos.status as status_mod

    monkeypatch.setattr(status_mod, "_STATUS_PATH", tmp_path / "status.json")
    assert ler_status() == {}


def test_escrever_e_ler_status_sucesso(tmp_path, monkeypatch):
    import backend.processos_abertos.status as status_mod

    monkeypatch.setattr(status_mod, "_STATUS_PATH", tmp_path / "status.json")

    escrever_status(ok=True, mensagem="semana 20/08/2026 atualizada", tentativa="08:05", data_sucesso="2026-08-20")
    status = ler_status()

    assert status["ok"] is True
    assert status["ultima_data_sucesso"] == "2026-08-20"
    assert status["tentativa"] == "08:05"


def test_falha_nao_apaga_ultima_data_de_sucesso(tmp_path, monkeypatch):
    import backend.processos_abertos.status as status_mod

    monkeypatch.setattr(status_mod, "_STATUS_PATH", tmp_path / "status.json")

    escrever_status(ok=True, mensagem="ok", tentativa="08:05", data_sucesso="2026-08-19")
    escrever_status(ok=False, mensagem="FTP fora do ar", tentativa="08:30 (retentativa)")
    status = ler_status()

    assert status["ok"] is False
    assert status["ultima_data_sucesso"] == "2026-08-19"
