"""Garante que o cliente FTP (backend/core/ftp_reader.py) continua só-leitura.

Não testa contra um FTP de verdade (não é o objetivo aqui) — testa a
superfície pública da classe: se algum dia alguém adicionar um método de
escrever/apagar/renomear, este teste quebra e chama atenção pra revisão.
"""
from backend.core.ftp_reader import FtpReadOnlyClient

_METODOS_PUBLICOS_PERMITIDOS = {"data_modificacao", "baixar"}


def test_cliente_ftp_so_expoe_metodos_de_leitura():
    metodos_publicos = {
        nome
        for nome in dir(FtpReadOnlyClient)
        if not nome.startswith("_") and callable(getattr(FtpReadOnlyClient, nome))
    }
    assert metodos_publicos == _METODOS_PUBLICOS_PERMITIDOS


def test_cliente_ftp_nao_tem_metodos_de_escrita_por_nome():
    proibidos = {"deletar", "apagar", "remover", "delete", "upload", "enviar", "renomear", "escrever", "storbinary"}
    metodos = {nome.lower() for nome in dir(FtpReadOnlyClient)}
    assert not (proibidos & metodos)
