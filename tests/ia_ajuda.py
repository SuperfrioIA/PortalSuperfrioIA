"""Auxiliares dos testes do SuperfrioIA: provedor roteirizado e atalhos de HTTP."""
import json

from backend.ia.provedor import RespostaDoModelo

DOMINIO = "volumetria-catering"


class Roteiro:
    """Provedor que executa EXATAMENTE as chamadas de ferramenta que o teste manda,
    na ordem, e devolve um texto fixo. Prova limites e recusas sem depender das
    heurísticas do provedor falso. Guarda tudo que viu, para o teste conferir o
    que seria enviado a um modelo de verdade."""

    nome = "roteirizado"
    rotulo = "provedor de teste"

    def __init__(self, passos, texto="resposta do roteiro"):
        self.passos = passos
        self.texto = texto
        self.contextos = []
        self.resultados = []

    def responder(self, contexto, executar):
        self.contextos.append(contexto)
        for nome, argumentos in self.passos:
            self.resultados.append(executar(nome, argumentos))
        return RespostaDoModelo(self.texto)

    def tudo_que_o_modelo_viu(self) -> str:
        """Pergunta, histórico e resultados de ferramenta, como um único texto."""
        vistos = [c.pergunta for c in self.contextos] + [h["texto"] for c in self.contextos for h in c.historico]
        return json.dumps({"textos": vistos, "resultados": self.resultados}, ensure_ascii=False, default=str)


def consulta(**parametros):
    """Atalho: uma chamada `consultar_indicador` com parâmetros de entrada em agosto."""
    base = {"de": "2026-08-01", "ate": "2026-08-31", "movimento": "rec"}
    return ("consultar_indicador", {"dominio": DOMINIO, "parametros": {**base, **parametros}})


def usar_roteiro(monkeypatch, roteiro):
    """Faz o serviço usar o `roteiro` no lugar do provedor configurado."""
    from backend.ia import provedor as modulo

    monkeypatch.setattr(modulo, "obter", lambda _nome: roteiro)
    return roteiro


def marco_da_trilha() -> int:
    """Último id da trilha agora. A trilha é append-only (nem os testes apagam):
    para isolar um teste, lê-se só o que nasceu depois deste marco."""
    from sqlalchemy import func, select

    from backend.auditoria.models import AuditoriaEvento
    from backend.core.database import db

    with db() as session:
        return session.execute(select(func.coalesce(func.max(AuditoriaEvento.id), 0))).scalar_one()


def eventos(desde: int, acao: str | None = None, app_slug: str | None = "superfrioia") -> list[dict]:
    """Eventos da trilha criados depois do marco, do mais antigo ao mais novo."""
    from sqlalchemy import select

    from backend.auditoria.models import AuditoriaEvento
    from backend.core.database import db

    consulta = select(AuditoriaEvento.__table__).where(AuditoriaEvento.id > desde).order_by(AuditoriaEvento.id)
    if acao:
        consulta = consulta.where(AuditoriaEvento.acao == acao)
    if app_slug:
        consulta = consulta.where(AuditoriaEvento.app_slug == app_slug)
    with db() as session:
        linhas = session.execute(consulta).mappings().all()
    return [{**dict(l), "detalhes": json.loads(l["detalhes"] or "{}")} for l in linhas]


def meta_gravada(mensagem_id: int) -> dict:
    """O `meta` COMPLETO da mensagem, como gravado. A resposta HTTP omite o que é de operação
    (`uso`, `numeros_reprovados`): quem confere gasto lê daqui ou da trilha."""
    from sqlalchemy import select

    from backend.core.database import db
    from backend.ia.models import IaMensagem

    with db() as session:
        return json.loads(session.execute(select(IaMensagem.meta).where(IaMensagem.id == mensagem_id)).scalar_one())


def registros_de_consulta() -> list[dict]:
    from sqlalchemy import select

    from backend.core.database import db
    from backend.ia.models import IaConsulta

    with db() as session:
        rows = session.execute(select(IaConsulta.__table__).order_by(IaConsulta.id)).mappings().all()
    return [dict(r) for r in rows]


def perguntar_http(client, usuario, texto, conversa_id=None, esperado=200):
    r = client.post("/api/ia/perguntas", headers=usuario["headers"],
                    json={"dominio": DOMINIO, "pergunta": texto, "conversa_id": conversa_id})
    assert r.status_code == esperado, r.text
    return r.json()
