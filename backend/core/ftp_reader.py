"""Cliente FTP/FTPS somente leitura — padrão genérico pra jobs que buscam
arquivo em servidor externo (Pentaho, parceiros, etc.).

Deliberadamente enxuto: só sabe checar a data de modificação de um arquivo e
baixar o conteúdo dele. Não existe (nem por engano) um método de escrever,
apagar, renomear ou navegar livremente pelo servidor — a pasta é fixada na
criação do cliente e nunca muda. Se o método não existe no código, não tem
como o job fazer isso, mesmo usando uma credencial com permissão de sobra.

Conecta com FTP explícito sobre TLS (`AUTH TLS`, mesma opção usada no
FileZilla) e cai pra FTP puro só se o servidor não suportar TLS — replica o
comportamento de "Usar FTP explícito sobre TLS, se disponível".
"""
from __future__ import annotations

import ftplib
import io
import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("backend.core.ftp_reader")


class FtpReadError(RuntimeError):
    """Falha ao conectar, autenticar ou ler do FTP."""


@dataclass
class FtpReadOnlyClient:
    host: str
    user: str
    password: str
    diretorio: str
    port: int = 21
    timeout: int = 30

    def _conectar(self) -> ftplib.FTP:
        try:
            ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=self.timeout)
            ftp.connect(self.host, self.port)
            ftp.auth()
            seguro = True
        except ftplib.all_errors:
            logger.warning("servidor %s não aceitou AUTH TLS — caindo para FTP sem criptografia", self.host)
            ftp = ftplib.FTP(timeout=self.timeout)
            ftp.connect(self.host, self.port)
            seguro = False

        try:
            ftp.login(self.user, self.password)
            if seguro:
                ftp.prot_p()  # criptografa também o canal de dados, não só o de login
            ftp.cwd(self.diretorio)
        except (OSError, ftplib.all_errors) as exc:
            _fechar(ftp)
            raise FtpReadError(f"falha ao autenticar/entrar em '{self.diretorio}' em {self.host}: {exc}") from exc
        return ftp

    def data_modificacao(self, nome_arquivo: str) -> datetime:
        """Data/hora de última modificação do arquivo (fuso do servidor), via MDTM."""
        ftp = self._conectar()
        try:
            resposta = ftp.sendcmd(f"MDTM {nome_arquivo}")
        except ftplib.all_errors as exc:
            raise FtpReadError(f"não consegui ler a data de '{nome_arquivo}' em '{self.diretorio}': {exc}") from exc
        finally:
            _fechar(ftp)
        # resposta no formato "213 AAAAMMDDhhmmss"
        timestamp = resposta.split()[-1]
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S")

    def baixar(self, nome_arquivo: str) -> bytes:
        """Conteúdo do arquivo, em memória. Nunca grava nada no servidor remoto."""
        ftp = self._conectar()
        buffer = io.BytesIO()
        try:
            ftp.retrbinary(f"RETR {nome_arquivo}", buffer.write)
        except ftplib.all_errors as exc:
            raise FtpReadError(f"falha ao baixar '{nome_arquivo}' de '{self.diretorio}': {exc}") from exc
        finally:
            _fechar(ftp)
        return buffer.getvalue()


def _fechar(ftp: ftplib.FTP) -> None:
    try:
        ftp.quit()
    except ftplib.all_errors:
        ftp.close()
