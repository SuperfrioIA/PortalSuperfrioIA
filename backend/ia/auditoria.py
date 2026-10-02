"""Eventos `ia.*` na trilha de auditoria do Hub.

Finas camadas sobre `backend/auditoria/service.registrar`, para o resto do módulo
não repetir categoria, `app_slug` e as regras do que **não** entra na trilha
(arquitetura §16.3):

- **texto da pergunta**: nunca. Entram o **tamanho** e um **hash** do texto já
  mascarado;
- **linhas de dado**: nunca. Entram contagens;
- **chave do cliente**: nunca (DD-17);
- texto de erro de driver: nunca; só um `tipo`.

O conteúdo vive em `ia_mensagens` (retenção de 90 dias, DD-25); a trilha guarda o
**fato**. A trilha em si tem retenção própria, ainda não definida (D-9b).

Eventos de concessão recebem a `session` do chamador: o registro entra na mesma
transação da mudança, como nas mutações administrativas do Hub.
"""
import hashlib

from backend.auditoria import service as trilha
from backend.ia import config

CATEGORIA = "ia"


def _ev(acao, resultado, ator, ip, *, session=None, detalhes=None, alvo_tipo=None, alvo_id=None, alvo_rotulo=None):
    trilha.registrar(
        session, categoria=CATEGORIA, acao=acao, resultado=resultado, ator=ator, ator_ip=ip,
        app_slug=config.SLUG_APP, alvo_tipo=alvo_tipo, alvo_id=alvo_id, alvo_rotulo=alvo_rotulo,
        detalhes=detalhes,
    )


def hash_da_pergunta(texto_mascarado: str) -> str:
    return hashlib.sha256(texto_mascarado.encode("utf-8")).hexdigest()[:16]


def conversa_criada(user, ip, *, dominio, conversa_id):
    _ev("ia.conversa.criar", "ok", user, ip, detalhes={"dominio": dominio},
        alvo_tipo="conversa", alvo_id=conversa_id)


def pergunta(user, ip, *, dominio, conversa_id, texto_mascarado, mascarados):
    _ev("ia.pergunta", "ok", user, ip, alvo_tipo="conversa", alvo_id=conversa_id, detalhes={
        "dominio": dominio, "tamanho": len(texto_mascarado),
        "hash": hash_da_pergunta(texto_mascarado), "dados_pessoais_mascarados": sorted(set(mascarados)),
    })


def consulta(user, ip, *, dominio, conversa_id, registro: dict):
    _ev("ia.consulta", "ok" if registro["situacao"] == "ok" else "negado", user, ip,
        alvo_tipo="conversa", alvo_id=conversa_id, detalhes={
            "dominio": dominio, "capacidade": registro["capacidade"], "situacao": registro["situacao"],
            "motivo": registro.get("motivo"), "linhas": registro.get("linhas"),
            "duracao_ms": registro.get("duracao_ms"), "escopo_aplicado": registro.get("escopo_aplicado"),
            "chamadas_logicas": registro["chamadas_logicas"], "chamadas_servico": registro["chamadas_servico"],
            "paginas_lidas": registro["paginas_lidas"], "consultas_dw": registro["consultas_dw"],
            "limite_interno_atingido": bool(registro["limite_interno_atingido"]),
        })


def bloqueio(user, ip, *, dominio, motivo, conversa_id=None, **extra):
    _ev("ia.bloqueio", "negado", user, ip, alvo_tipo="conversa" if conversa_id else None,
        alvo_id=conversa_id, detalhes={"dominio": dominio, "motivo": motivo, **extra})


def erro(user, ip, *, dominio, tipo, conversa_id=None, status=None, tipo_api=None):
    """`tipo` é uma palavra (`dw_indisponivel`, `provedor_timeout`...), nunca o texto do erro.
    `status` (HTTP) e `tipo_api` (o `error.type` da API, palavra de conjunto fixo) só existem
    para falha do provedor: dizem se foi 400, 401, 404... sem a mensagem."""
    detalhes = {"dominio": dominio, "tipo": tipo}
    if status is not None:
        detalhes["status"] = status
    if tipo_api is not None:
        detalhes["tipo_api"] = tipo_api
    _ev("ia.erro", "erro", user, ip, alvo_tipo="conversa" if conversa_id else None,
        alvo_id=conversa_id, detalhes=detalhes)


def resposta(user, ip, *, dominio, conversa_id, estado, duracao_ms, provedor, operacoes, uso=None):
    """`operacoes` é o trabalho da pergunta INTEIRA (`ContextoDaPergunta.totais()`):
    cobre também o que `amostrar_valores` e `descrever` leram, que não são consulta.
    `uso` (provedor real): modelo, versão do prompt, rodadas, tokens, latência e custo
    estimado. Só números e nomes de configuração, nunca texto da pergunta ou da resposta."""
    detalhes = {"dominio": dominio, "estado": estado, "duracao_ms": duracao_ms, "provedor": provedor,
                "operacoes": operacoes}
    if uso:
        detalhes["uso"] = uso
    _ev("ia.resposta", "ok", user, ip, alvo_tipo="conversa", alvo_id=conversa_id, detalhes=detalhes)


def concessao(session, acao, ator, ip, *, dominio, concessao_id, usuario, detalhes=None):
    """`acao` ∈ pedida | aprovada | negada | revogada."""
    _ev(f"ia.concessao.{acao}", "ok", ator, ip, session=session, alvo_tipo="concessao",
        alvo_id=concessao_id, alvo_rotulo=usuario, detalhes={"dominio": dominio, "usuario": usuario, **(detalhes or {})})


def retencao(contagens: dict):
    _ev("ia.retencao.executada", "ok", None, None, detalhes=contagens)
