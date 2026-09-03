"""Vocabulário fechado de eventos de auditoria — infra, sem domínio.

Mesmo raciocínio de `backend/core/permissoes.py`: um evento gravado com
`categoria`/`acao` fora deste catálogo é erro de programação, não dado válido.
`validar()` levanta na hora de gravar, para o erro apontar pra quem chamou
`registrar()` errado — em vez de acumular lixo na trilha (que é append-only e
não tem como corrigir depois).

Categorias e ações da Fase 1 (docs/AUDITORIA_FUNCIONAL.md). Acrescentar um
módulo com mutação nova? Acrescenta a ação aqui — é o único lugar.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Evento:
    categoria: str
    acao: str
    descricao: str


_CATALOGO: dict[tuple[str, str], Evento] = {}


def _registrar(categoria: str, acao: str, descricao: str) -> None:
    chave = (categoria, acao)
    if chave in _CATALOGO:
        raise RuntimeError(f"evento {categoria}.{acao} já registrado no catálogo")
    _CATALOGO[chave] = Evento(categoria, acao, descricao)


_registrar("auth", "login.ok", "Login local bem-sucedido")
_registrar("auth", "login.falha", "Login local recusado (usuário ou senha inválidos)")
_registrar("auth", "login.bloqueado", "Login recusado por rate limit (5 tentativas/minuto)")
_registrar("auth", "sso.ok", "Login via Microsoft Entra ID bem-sucedido")
_registrar("auth", "sso.recusado", "Login via Microsoft Entra ID recusado")
_registrar("auth", "logout", "Encerramento de sessão")

_registrar("acesso", "app.abrir", "Abertura de um app pelo card do portal")
_registrar("acesso", "acesso.negado", "Rota exigiu permissão que o usuário não tem")

_registrar("admin", "usuario.criar", "Criação de usuário")
_registrar("admin", "usuario.atualizar", "Atualização de usuário")
_registrar("admin", "usuario.toggle", "Ativação/desativação de usuário")
_registrar("admin", "usuario.senha", "Reset de senha de usuário")
_registrar("admin", "role.criar", "Criação de role")
_registrar("admin", "role.atualizar", "Atualização de role (apps e/ou permissões)")
_registrar("admin", "role.toggle", "Ativação/desativação de role")
_registrar("admin", "app.criar", "Criação de app no catálogo")
_registrar("admin", "app.atualizar", "Atualização de app no catálogo")
_registrar("admin", "app.toggle", "Ativação/desativação de app")
_registrar("admin", "secao.criar", "Criação de seção")
_registrar("admin", "secao.atualizar", "Atualização de seção")
_registrar("admin", "secao.toggle", "Ativação/desativação de seção")
_registrar("admin", "filial.criar", "Criação de filial")
_registrar("admin", "filial.atualizar", "Atualização de filial")
_registrar("admin", "filial.toggle", "Ativação/desativação de filial")
_registrar("admin", "unidade.criar", "Criação de unidade de negócio")
_registrar("admin", "unidade.atualizar", "Atualização de unidade de negócio")
_registrar("admin", "unidade.toggle", "Ativação/desativação de unidade de negócio")

_registrar("projeto", "projeto.criar", "Criação de projeto IA")
_registrar("projeto", "projeto.atualizar", "Atualização de projeto IA")
_registrar("projeto", "projeto.fase", "Atualização de fase de projeto IA")
_registrar("projeto", "projeto.rollout.incluir", "Inclusão de filial no rollout de um projeto IA")
_registrar("projeto", "projeto.rollout.atualizar", "Atualização do rollout de uma filial")
_registrar("projeto", "projeto.rollout.remover", "Remoção de filial do rollout")

_registrar("acao", "processos-abertos.editar", "Envio de semana no histórico de Processos Abertos")
_registrar("acao", "integracao-in-out.editar", "Envio de base no painel Integração In/Out")

_registrar("auditoria", "auditoria.consultar", "Consulta à trilha de auditoria")
_registrar("auditoria", "auditoria.exportar", "Exportação da trilha de auditoria em CSV")


def validar(categoria: str, acao: str) -> None:
    if (categoria, acao) not in _CATALOGO:
        raise ValueError(
            f"evento de auditoria {categoria!r}.{acao!r} não existe no catálogo "
            f"(backend/auditoria/catalogo.py)"
        )


def listar() -> list[Evento]:
    return sorted(_CATALOGO.values(), key=lambda e: (e.categoria, e.acao))
