"""Orquestrador do SuperfrioIA: uma pergunta, do login à resposta gravada.

Interface do módulo para a rota (`router.py`). Não conhece HTTP: levanta `Recusa`
com o status que a rota deve devolver.

## O caminho de uma pergunta

1. **portas** (`permissoes.exigir_acesso`): `<app_hub>:ver` e concessão vigente,
   revalidadas agora;
2. **políticas**: pergunta não vazia, até 1.000 caracteres, cota do dia;
3. **máscara** de CPF, CNPJ, e-mail e telefone — antes de gravar e de enviar (D-17);
4. o **provedor** roda o laço de ferramentas; o `executar` aplica passos, o teto de
   3 consultas lógicas e o limite interno de trabalho no banco (DD-16, DD-24);
5. os **blocos** exibidos (tiles, barras, tabela, fonte, avisos) são montados a
   partir do que as ferramentas devolveram, não do texto do modelo: a tela mostra
   o que a ferramenta entregou;
6. grava a mensagem, as consultas (`ia_consultas`) e os fatos da trilha (`ia.*`).

`EncerrarPergunta` (limite estourado, fonte fora do ar) termina a pergunta com um
texto **fixo**: o modelo não improvisa sobre um dado que não leu.
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, update

from backend.core.database import _now, db
from backend.ia import (
    auditoria, config, dominios, ferramentas, permissoes, prompt, provedor as modulo_provedor, verificador,
)
from backend.ia.models import IaConsulta, IaConversa, IaMensagem
from backend.ia.politicas import (
    ContextoDaPergunta, EncerrarPergunta, ErroDoProvedor, Recusa, mascarar, mencionou_a_base,
)

logger = logging.getLogger("backend.ia")

_FUSO = ZoneInfo("America/Sao_Paulo")
HISTORICO_PARA_O_MODELO = 6   # mensagens anteriores enviadas ao provedor
TITULO_MAXIMO = 60
ESCOPO = "integral (indicador sem alcance por usuário)"
ESTADO_NUMERO_NAO_VERIFICADO = "numero_nao_verificado"
MENSAGEM_NEUTRA = "Não consegui responder agora. Tente novamente em instantes."

_C, _M, _Q = IaConversa.__table__, IaMensagem.__table__, IaConsulta.__table__


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


# O que é de OPERAÇÃO (gasto com o provedor, números que o verificador reprovou) fica na
# mensagem gravada e na trilha, e não volta ao usuário comum: custo e região do contrato
# não são assunto da tela, e o texto reprovado não pode vazar de volta (T-44).
_SO_NO_SERVIDOR = ("uso", "numeros_reprovados")


def _meta_publica(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in _SO_NO_SERVIDOR}


def _inicio_do_dia_utc() -> str:
    """Meia-noite de São Paulo, em UTC, no formato dos timestamps do Hub: a cota
    é por dia do usuário, não por dia do servidor."""
    meia_noite = datetime.now(_FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def perguntas_hoje(session, usuario_id: int) -> int:
    return session.execute(
        select(func.count()).select_from(_M.join(_C, _C.c.id == _M.c.conversa_id))
        .where(_C.c.usuario_id == usuario_id, _M.c.papel == "usuario",
               _M.c.criado_em >= _inicio_do_dia_utc())
    ).scalar_one()


# ----------------------------------------------------------------- domínios
def listar_dominios(user: dict) -> list[dict]:
    """O que a tela mostra no seletor: cada domínio com o estado de acesso do usuário."""
    prov = modulo_provedor.obter(config.provedor_nome())
    with db() as session:
        usadas = perguntas_hoje(session, user["id"])
    saida = []
    for dom in dominios.carregar().values():
        estado = permissoes.estado_do_acesso(user, dom)
        saida.append({
            "slug": dom.slug, "nome": dom.nome, "area": dom.get("area"),
            "classificacao": dom.classificacao, "modo": dom["modo"],
            "fonte": (dom.get("fonte") or {}).get("rotulo"),
            "exemplos": dom["exemplos"]["responde"],
            "acesso": estado,
            "pode_administrar": permissoes.pode_administrar(user, dom),
            "limites": {"perguntas_por_dia": config.cota_diaria(), "perguntas_hoje": usadas,
                        "tamanho_da_pergunta": config.tamanho_maximo_da_pergunta(),
                        "consultas_por_pergunta": config.max_consultas_por_pergunta()},
            "provedor": {"nome": prov.nome, "rotulo": prov.rotulo},
        })
    return saida


# --------------------------------------------------------------- conversas
def _conversa_do_usuario(session, user: dict, conversa_id: int) -> dict:
    """Conversa de OUTRO usuário é 404, não 403: não confirma que ela existe."""
    row = session.execute(
        select(_C).where(_C.c.id == conversa_id, _C.c.usuario_id == user["id"])
    ).mappings().fetchone()
    if row is None:
        raise Recusa(404, "conversa_inexistente", "Conversa não encontrada.")
    return dict(row)


def listar_conversas(user: dict) -> list[dict]:
    with db() as session:
        rows = session.execute(
            select(_C).where(_C.c.usuario_id == user["id"]).order_by(_C.c.atualizado_em.desc(), _C.c.id.desc()).limit(50)
        ).mappings().all()
    saida = []
    for r in rows:
        dom = dominios.obter(r["dominio"])
        liberado = dom is not None and permissoes.estado_do_acesso(user, dom)["estado"] == "liberado"
        saida.append({
            "id": r["id"], "dominio": r["dominio"], "atualizado_em": r["atualizado_em"],
            # Acesso revogado: a conversa aparece, mas fechada (arquitetura §14.4).
            "titulo": r["titulo"] if liberado else "(acesso revogado)",
            "acesso_revogado": not liberado,
        })
    return saida


def obter_conversa(user: dict, conversa_id: int) -> dict:
    with db() as session:
        conversa = _conversa_do_usuario(session, user, conversa_id)
    dom = dominios.obter(conversa["dominio"])
    if dom is None or permissoes.estado_do_acesso(user, dom)["estado"] != "liberado":
        raise Recusa(403, "acesso_revogado", "O acesso a este domínio foi revogado: o conteúdo da conversa está fechado.")
    with db() as session:
        rows = session.execute(
            select(_M).where(_M.c.conversa_id == conversa_id).order_by(_M.c.id)
        ).mappings().all()
    return {
        "id": conversa["id"], "dominio": conversa["dominio"], "titulo": conversa["titulo"],
        "mensagens": [{
            "id": m["id"], "papel": m["papel"], "texto": m["texto"], "blocos": json.loads(m["blocos"]),
            "meta": _meta_publica(json.loads(m["meta"])), "feedback": m["feedback"], "criado_em": m["criado_em"],
        } for m in rows],
    }


def dar_feedback(user: dict, mensagem_id: int, valor: int) -> None:
    if valor not in (1, -1):
        raise Recusa(400, "feedback_invalido", "Use 1 (ajudou) ou -1 (não ajudou).")
    with db() as session:
        dono = session.execute(
            select(_C.c.usuario_id).join_from(_M, _C, _C.c.id == _M.c.conversa_id)
            .where(_M.c.id == mensagem_id, _M.c.papel == "ia")
        ).scalar_one_or_none()
        if dono != user["id"]:
            raise Recusa(404, "mensagem_inexistente", "Mensagem não encontrada.")
        session.execute(update(_M).where(_M.c.id == mensagem_id).values(feedback=valor))


# ----------------------------------------------------------------- perguntar
def _bloquear(user, ip, dominio, status, motivo, mensagem, conversa_id=None, **extra):
    auditoria.bloqueio(user, ip, dominio=dominio, motivo=motivo, conversa_id=conversa_id, **extra)
    raise Recusa(status, motivo, mensagem)


def _historico(session, conversa_id: int) -> list[dict]:
    rows = session.execute(
        select(_M.c.papel, _M.c.texto).where(_M.c.conversa_id == conversa_id)
        .order_by(_M.c.id.desc()).limit(HISTORICO_PARA_O_MODELO)
    ).all()
    return [{"papel": p, "texto": t} for p, t in reversed(rows)]


def _resposta_anterior_pediu_a_base(session, conversa_id: int) -> bool:
    """A última resposta da IA nesta conversa parou para perguntar a base da variação?"""
    meta = session.execute(
        select(_M.c.meta).where(_M.c.conversa_id == conversa_id, _M.c.papel == "ia")
        .order_by(_M.c.id.desc()).limit(1)
    ).scalar_one_or_none()
    try:
        return bool(meta and json.loads(meta).get("aguardando_base"))
    except ValueError:
        return False


_EM_ANDAMENTO: dict[int, int] = {}
_TRAVA_DE_ANDAMENTO = threading.Lock()


def perguntar(user: dict, *, dominio_slug: str, pergunta: str, conversa_id: int | None,
              ip: str | None, provedor=None) -> dict:
    """Uma pergunta. No máximo `IA_MAX_SIMULTANEAS` por usuário ao mesmo tempo (T-42): a
    cota diária conta e grava em transações separadas, e sem este limite uma rajada de
    requisições passaria dela e multiplicaria o gasto com o provedor. O limite é por processo
    (uma instância do Hub): é o que fecha a corrida, não um contador distribuído."""
    with _TRAVA_DE_ANDAMENTO:
        agora = _EM_ANDAMENTO.get(user["id"], 0)
        reservou = agora < config.max_simultaneas()
        if reservou:
            _EM_ANDAMENTO[user["id"]] = agora + 1
    if not reservou:
        _bloquear(user, ip, str(dominio_slug)[:60], 429, "simultaneas",
                  "Você já tem perguntas em andamento. Aguarde a resposta antes de enviar outra.", conversa_id)
    try:
        return _perguntar(user, dominio_slug=dominio_slug, pergunta=pergunta, conversa_id=conversa_id,
                          ip=ip, provedor=provedor)
    finally:
        with _TRAVA_DE_ANDAMENTO:
            restante = _EM_ANDAMENTO.get(user["id"], 1) - 1
            if restante > 0:
                _EM_ANDAMENTO[user["id"]] = restante
            else:
                _EM_ANDAMENTO.pop(user["id"], None)


def _perguntar(user: dict, *, dominio_slug: str, pergunta: str, conversa_id: int | None,
               ip: str | None, provedor=None) -> dict:
    inicio = time.perf_counter()
    dom = dominios.obter(dominio_slug)
    if dom is None:
        _bloquear(user, ip, str(dominio_slug)[:60], 404, "dominio_desconhecido", "Domínio não encontrado.")

    try:
        permissoes.exigir_acesso(user, dom)
    except Recusa as recusa:
        _bloquear(user, ip, dom.slug, recusa.status, recusa.motivo, recusa.mensagem, conversa_id)

    texto = (pergunta or "").strip()
    if not texto:
        _bloquear(user, ip, dom.slug, 400, "pergunta_vazia", "Escreva a sua pergunta.", conversa_id)
    if len(texto) > config.tamanho_maximo_da_pergunta():
        _bloquear(user, ip, dom.slug, 400, "tamanho",
                  f"A pergunta pode ter até {config.tamanho_maximo_da_pergunta()} caracteres.", conversa_id,
                  tamanho=len(texto))

    with db() as session:
        usadas = perguntas_hoje(session, user["id"])
    if usadas >= config.cota_diaria():
        _bloquear(user, ip, dom.slug, 429, "cota",
                  f"Limite diário atingido ({config.cota_diaria()} perguntas). Volta amanhã.", conversa_id)

    mascarado, achados = mascarar(texto)

    with db() as session:
        if conversa_id is not None:
            conversa = _conversa_do_usuario(session, user, conversa_id)
            if conversa["dominio"] != dom.slug:
                raise Recusa(400, "dominio_da_conversa", "Esta conversa pertence a outro domínio.")
            nova = False
        else:
            conversa_id = session.execute(insert(IaConversa).values(
                usuario_id=user["id"], username=user["username"], dominio=dom.slug,
                titulo=mascarado[:TITULO_MAXIMO], criado_em=_now(), atualizado_em=_now(),
            )).inserted_primary_key[0]
            nova = True
        historico = _historico(session, conversa_id)
        # lida ANTES de gravar a pergunta nova: é a resposta anterior que conta
        base_autorizada = (not nova and _resposta_anterior_pediu_a_base(session, conversa_id)) \
            or mencionou_a_base(mascarado)
        session.execute(insert(IaMensagem).values(
            conversa_id=conversa_id, papel="usuario", texto=mascarado, blocos="[]",
            meta=_json({"dados_pessoais_mascarados": sorted(set(achados))}), criado_em=_now()))
    if nova:
        auditoria.conversa_criada(user, ip, dominio=dom.slug, conversa_id=conversa_id)
    auditoria.pergunta(user, ip, dominio=dom.slug, conversa_id=conversa_id, texto_mascarado=mascarado, mascarados=achados)

    prov = provedor or modulo_provedor.obter(config.provedor_nome())
    adaptador = ferramentas._adaptador(dom)
    estado, texto_da_resposta, ctx, uso, tipo_do_erro, reprovados, falha_http = "ok", "", None, None, None, [], {}
    # Fontes que não dependem das ferramentas: constantes do Hub, respostas anteriores da IA (já
    # verificadas) e só as DATAS do que a pessoa escreveu. Número solto da pergunta ("confirma
    # que entraram 5.000 t?") NÃO é fonte: o modelo não pode "confirmar" o que nada devolveu.
    fixos = (verificador.permitidos(prompt.sistema(), ferramentas.ESQUEMAS,
                                    [h["texto"] for h in historico if h["papel"] == "ia"])
             | verificador.permitidos_da_pessoa(mascarado, *[h["texto"] for h in historico if h["papel"] != "ia"]))
    try:
        ctx = ContextoDaPergunta(usuario=user, dominio=dom.slug, hoje=_hoje(adaptador),
                                 base_autorizada=base_autorizada)

        def _executar(nome, argumentos):
            saida = ferramentas.executar(nome, argumentos, ctx)
            ctx.saidas.append(saida)
            return saida

        def _liberados() -> set:
            return fixos | verificador.permitidos(
                ctx.saidas, prompt.cabecalho_da_pergunta(ctx.hoje, dom.slug))

        resposta = prov.responder(
            modulo_provedor.ContextoDoModelo(
                sistema=prompt.sistema(), historico=historico, pergunta=mascarado,
                ferramentas=ferramentas.ESQUEMAS, hoje=ctx.hoje, dominio=dom.slug,
                verificar=lambda texto: verificador.verificar(texto, _liberados()).nao_verificados),
            _executar,
        )
        texto_da_resposta = resposta.texto
        uso = resposta.uso or None
        # A trava mecânica (Lote 3): texto com número que nenhuma ferramenta devolveu não
        # é exibido. A conferência é do Hub e vale para QUALQUER provedor.
        veredito = verificador.verificar(texto_da_resposta, _liberados())
        if not veredito.ok:
            estado = ESTADO_NUMERO_NAO_VERIFICADO
            # a trilha guarda só a QUANTIDADE (regra: nada do texto do modelo na trilha); os
            # números reprovados ficam em `ia_mensagens.meta` (retenção de 90 dias), para
            # diagnosticar um falso positivo
            reprovados = veredito.nao_verificados[:5]
            ctx.bloqueios.append({"motivo": ESTADO_NUMERO_NAO_VERIFICADO,
                                  "quantidade": len(veredito.nao_verificados)})
            texto_da_resposta = (
                "Não consegui validar os números da resposta, então não vou exibi-la."
                + (" Os dados da consulta estão abaixo." if ctx.resultados else "")
                + " Tente reformular a pergunta.")
    except EncerrarPergunta as fim:
        estado, texto_da_resposta = fim.motivo, fim.mensagem
        if ctx is None:
            ctx = ContextoDaPergunta(usuario=user, dominio=dom.slug, hoje=datetime.now(_FUSO).date())
    except ErroDoProvedor as falha:
        # só o TIPO (uma palavra) é registrado: nunca o texto do erro do SDK, que pode
        # trazer trecho da requisição
        logger.warning("ia: provedor falhou (%s)", falha.tipo)
        estado, tipo_do_erro, texto_da_resposta = "erro", f"provedor_{falha.tipo}", MENSAGEM_NEUTRA
        falha_http = {k: v for k, v in (("status", falha.status), ("tipo_api", falha.tipo_api)) if v is not None}
        ctx = ctx or ContextoDaPergunta(usuario=user, dominio=dom.slug, hoje=datetime.now(_FUSO).date())
    except Exception:
        logger.exception("ia: falha inesperada no provedor/ferramentas")
        estado, tipo_do_erro, texto_da_resposta = "erro", "provedor", MENSAGEM_NEUTRA
        ctx = ctx or ContextoDaPergunta(usuario=user, dominio=dom.slug, hoje=datetime.now(_FUSO).date())

    # o que o modelo gastou, também quando a pergunta terminou por limite ou por erro
    parcial = getattr(prov, "uso_da_pergunta", None)
    if uso is None and parcial is not None:
        uso = parcial.como_dict()

    blocos = [b for r in ctx.resultados for b in r["blocos"]]
    duracao_ms = int((time.perf_counter() - inicio) * 1000)
    meta = {"provedor": prov.nome, "rotulo_do_provedor": prov.rotulo, "estado": estado,
            "duracao_ms": duracao_ms, "dados_pessoais_mascarados": sorted(set(achados)),
            "operacoes": ctx.totais(),
            # só vale se a pessoa VIU a pergunta: com o texto retido ou a falha do provedor ela não
            # viu, e a próxima pergunta não pode herdar a autorização de `base` (DD-11)
            "aguardando_base": ctx.pediu_base and estado == "ok"}
    if uso:
        meta["uso"] = uso
    if reprovados:
        meta["numeros_reprovados"] = reprovados

    with db() as session:
        mensagem_id = session.execute(insert(IaMensagem).values(
            conversa_id=conversa_id, papel="ia", texto=texto_da_resposta, blocos=_json(blocos),
            meta=_json(meta), criado_em=_now())).inserted_primary_key[0]
        for registro in ctx.registros:
            session.execute(insert(IaConsulta).values(
                mensagem_id=mensagem_id, usuario_id=user["id"], dominio=dom.slug,
                capacidade=registro["capacidade"], parametros=_json(registro["parametros"]),
                escopo_aplicado=ESCOPO, situacao=registro["situacao"], motivo=registro.get("motivo"),
                linhas=registro.get("linhas"), duracao_ms=registro.get("duracao_ms"),
                chamadas_logicas=registro["chamadas_logicas"], chamadas_servico=registro["chamadas_servico"],
                paginas_lidas=registro["paginas_lidas"], consultas_dw=registro["consultas_dw"],
                limite_interno_atingido=registro["limite_interno_atingido"], criado_em=_now()))
        session.execute(update(_C).where(_C.c.id == conversa_id).values(atualizado_em=_now()))

    for registro in ctx.registros:
        auditoria.consulta(user, ip, dominio=dom.slug, conversa_id=conversa_id,
                           registro={**registro, "escopo_aplicado": ESCOPO})
    for b in ctx.bloqueios:
        auditoria.bloqueio(user, ip, dominio=dom.slug, conversa_id=conversa_id, **b)
    if estado in ("limite_consultas", "limite_interno", "passos"):
        auditoria.bloqueio(user, ip, dominio=dom.slug, conversa_id=conversa_id, motivo=estado)
    if estado == "indisponivel":
        auditoria.erro(user, ip, dominio=dom.slug, tipo="dw_indisponivel", conversa_id=conversa_id)
    if estado == "erro":
        auditoria.erro(user, ip, dominio=dom.slug, tipo=tipo_do_erro or "provedor", conversa_id=conversa_id,
                       **falha_http)
    auditoria.resposta(user, ip, dominio=dom.slug, conversa_id=conversa_id, estado=estado,
                       duracao_ms=duracao_ms, provedor=prov.nome, operacoes=ctx.totais(), uso=uso)

    return {
        "conversa_id": conversa_id,
        "estado": estado,
        "mensagem": {"id": mensagem_id, "papel": "ia", "texto": texto_da_resposta, "blocos": blocos,
                     "meta": _meta_publica(meta)},
        "pergunta": mascarado,   # o que foi gravado e enviado: a tela troca o que a pessoa digitou
        "dados_pessoais_mascarados": sorted(set(achados)),
        "perguntas_hoje": usadas + 1,
    }


def _hoje(adaptador):
    try:
        return adaptador.hoje()
    except Exception:  # fuso inválido etc.: a data não pode derrubar a pergunta
        return datetime.now(_FUSO).date()
