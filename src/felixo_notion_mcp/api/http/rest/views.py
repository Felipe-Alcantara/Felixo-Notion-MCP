"""Views da borda HTTP — finas: parse, validação e delegação a ``services``.

Sem regra de negócio aqui (isso vive em ``services``) nem formato cru do Notion
(isso é de ``domain`` e ``integrations``). O contrato das rotas segue ``docs/CONTRATOS.md``:

    GET   /api/tarefas[?status=<nome>&duracao=<nome>&area=<id>] lista (filtros opcionais)
    POST  /api/tarefas                    cria  {nome, status?, prazo?, duracao?, areas?}  -> 201
    PATCH /api/tarefas/<id>               edita {nome?, status?, prazo?, duracao?, areas?} -> 200
    GET   /api/opcoes                     valores para seletores                          -> 200
    GET   /api/database-atual             contexto da database ativa                      -> 200

Saída em JSON. Erros mapeados: 400 (entrada inválida), 404 (tarefa inexistente),
502 (falha na API do Notion), 500 (servidor sem token/database configurado).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured as DjangoImproperlyConfigured
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from felixo_notion_mcp import NotionAPIError, NotionConfigurationError, NotionHTTPError
from felixo_notion_mcp.api.http.rest.serializers import tarefa_para_dict
from felixo_notion_mcp.integrations.github import GitHubClient
from felixo_notion_mcp.integrations.notion import ImproperlyConfigured
from felixo_notion_mcp.services import tarefas as svc


def health(_request: HttpRequest) -> JsonResponse:
    """Sinaliza que o servidor está de pé. Não toca no Notion."""

    return JsonResponse({"status": "ok", "service": "automacoes-notion"})


def _erro(codigo: str, mensagem: str, status: int) -> JsonResponse:
    """Monta o envelope de erro padrão (``docs/CONTRATOS.md`` §3)."""

    return JsonResponse({"erro": {"codigo": codigo, "mensagem": mensagem}}, status=status)


def _corpo_json(request: HttpRequest) -> dict[str, Any]:
    """Lê o corpo da requisição como objeto JSON (``ValueError`` se inválido).

    Exige ``Content-Type: application/json``. As rotas são ``csrf_exempt`` porque não há cookie
    de sessão para o CSRF do Django proteger; a defesa é esta: uma página de outro site só
    dispara sem preflight um POST "simples" (texto, formulário ou sem corpo), e o servidor não
    responde ao preflight que o JSON exige.
    """

    if request.content_type != "application/json":
        raise ValueError("o Content-Type deve ser application/json")
    dados = json.loads(request.body.decode("utf-8") or "{}")
    if not isinstance(dados, dict):
        raise ValueError("o corpo deve ser um objeto JSON")
    return dados


def _lista_de_strings(valor: Any, campo: str) -> list[str] | None:
    """Valida listas opcionais de IDs recebidas pelo JSON público."""

    if valor is None:
        return None
    if not isinstance(valor, list) or not all(isinstance(item, str) for item in valor):
        raise ValueError(f"'{campo}' deve ser uma lista de strings")
    return valor


def _lista_csv_ou_lista(valor: Any, campo: str) -> list[str] | None:
    """Aceita lista de strings ou CSV em uma string."""

    if valor is None:
        return None
    if isinstance(valor, str):
        itens = [item.strip() for item in valor.split(",") if item.strip()]
        return itens or None
    return _lista_de_strings(valor, campo)


def _bool_opcional(dados: dict[str, Any], campo: str, *, default: bool = False) -> bool:
    """Valida booleanos opcionais do JSON público."""

    if campo not in dados or dados[campo] is None:
        return default
    if not isinstance(dados[campo], bool):
        raise ValueError(f"'{campo}' deve ser booleano")
    return dados[campo]


def _resumo_inventario_dict(resumo: Any) -> dict[str, Any]:
    """Serializa o resumo de inventário GitHub para a API pública."""

    return {
        "repos_encontrados": resumo.repos_encontrados,
        "paginas_criadas": resumo.paginas_criadas,
        "paginas_atualizadas": resumo.paginas_atualizadas,
        "paginas_puladas": resumo.paginas_puladas,
        "readmes_escritos": resumo.readmes_escritos,
        "readmes_atualizados": resumo.readmes_atualizados,
        "erros": resumo.erros,
    }


def _lista_query(request: HttpRequest, campo: str) -> list[str] | None:
    """Lê parâmetros repetidos ou CSV da query string."""

    valores: list[str] = []
    for bruto in request.GET.getlist(campo):
        valores.extend(item.strip() for item in bruto.split(",") if item.strip())
    return valores or None


def _texto_opcional(dados: dict[str, Any], campo: str) -> str | None:
    """Normaliza um campo textual opcional, preservando ausência real."""

    if campo not in dados or dados[campo] is None:
        return None
    if not isinstance(dados[campo], str):
        raise ValueError(f"'{campo}' deve ser uma string")
    return dados[campo].strip() or None


def _responder(acao: Callable[[], JsonResponse]) -> JsonResponse:
    """Executa um caso de uso e mapeia exceções para o envelope de erro do contrato.

    Mensagens são genéricas de propósito: nunca vazam token, ID interno ou caminho
    local (guarda-corpo de ``docs/CONTRATOS.md`` §3).
    """

    try:
        return acao()
    except (json.JSONDecodeError, ValueError) as exc:
        return _erro("validacao", f"Requisição inválida: {exc}", 400)
    except NotionHTTPError as exc:
        if exc.status_code == 404:
            return _erro("nao_encontrado", "Tarefa não encontrada.", 404)
        return _erro("erro_upstream", "Falha ao falar com o Notion.", 502)
    except NotionAPIError:
        return _erro("erro_upstream", "Falha ao falar com o Notion.", 502)
    # Duas classes de "configuração ausente": a do Django (settings, testes) e a da
    # biblioteca (`integrations.notion`, que não depende do Django). A fábrica do cliente
    # levanta a da biblioteca; as duas viram o mesmo 500 que o front já sabe mostrar.
    except (NotionConfigurationError, ImproperlyConfigured, DjangoImproperlyConfigured):
        return _erro(
            "erro_interno",
            "Notion ainda não configurado. Execute “Iniciar tudo” novamente.",
            500,
        )
    except Exception:  # noqa: BLE001 - contrato: qualquer outra falha vira 500 erro_interno
        return _erro("erro_interno", "Erro interno inesperado.", 500)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def tarefas(request: HttpRequest) -> JsonResponse:
    """Lista (``GET``) ou cria (``POST``) tarefas."""

    if request.method == "GET":

        def _listar() -> JsonResponse:
            itens = svc.listar_tarefas(
                status=request.GET.get("status") or None,
                duracao=request.GET.get("duracao") or None,
                areas=_lista_query(request, "area"),
            )
            return JsonResponse({"tarefas": [tarefa_para_dict(t) for t in itens]})

        return _responder(_listar)

    def _criar() -> JsonResponse:
        dados = _corpo_json(request)
        nome = _texto_opcional(dados, "nome") or ""
        if not nome:
            raise ValueError("'nome' é obrigatório")
        tarefa = svc.criar_tarefa(
            nome,
            status=_texto_opcional(dados, "status"),
            prazo=_texto_opcional(dados, "prazo"),
            duracao=_texto_opcional(dados, "duracao"),
            areas=_lista_de_strings(dados.get("areas"), "areas"),
        )
        return JsonResponse(tarefa_para_dict(tarefa), status=201)

    return _responder(_criar)


@csrf_exempt
@require_http_methods(["PATCH"])
def tarefa_detalhe(request: HttpRequest, task_id: str) -> JsonResponse:
    """Edita uma tarefa existente (``PATCH`` amplo, retrocompatível com status)."""

    def _editar() -> JsonResponse:
        dados = _corpo_json(request)
        campos_permitidos = {"nome", "status", "prazo", "duracao", "areas"}
        if not any(campo in dados for campo in campos_permitidos):
            raise ValueError("ao menos um campo deve ser informado")

        tarefa = svc.editar_tarefa(
            task_id,
            nome=_texto_opcional(dados, "nome"),
            status=_texto_opcional(dados, "status"),
            prazo=_texto_opcional(dados, "prazo"),
            duracao=_texto_opcional(dados, "duracao"),
            areas=_lista_de_strings(dados.get("areas"), "areas"),
        )
        return JsonResponse(tarefa_para_dict(tarefa))

    return _responder(_editar)


@require_http_methods(["GET"])
def opcoes(_request: HttpRequest) -> JsonResponse:
    """Devolve opções de status, duração e áreas para seletores."""

    def _listar_opcoes() -> JsonResponse:
        return JsonResponse(svc.listar_opcoes())

    return _responder(_listar_opcoes)


@require_http_methods(["GET"])
def database_atual(_request: HttpRequest) -> JsonResponse:
    """Devolve a database de tarefas ativa, com título e URL do Notion."""

    def _obter() -> JsonResponse:
        return JsonResponse(svc.obter_database_atual())

    return _responder(_obter)


@require_http_methods(["GET"])
def databases(request: HttpRequest) -> JsonResponse:
    """Lista os databases visíveis à integração (modo exploração, read-only)."""

    from felixo_notion_mcp.services import exploracao

    def _listar() -> JsonResponse:
        query = request.GET.get("query") or None
        itens = exploracao.listar_databases(query)
        return JsonResponse({"databases": itens})

    return _responder(_listar)


@require_http_methods(["GET"])
def database_detalhe(request: HttpRequest, database_id: str) -> JsonResponse:
    """Descreve um database genérico: colunas + linhas como texto (read-only)."""

    from felixo_notion_mcp.services import exploracao

    def _descrever() -> JsonResponse:
        if not database_id.strip():
            raise ValueError("database_id é obrigatório")
        return JsonResponse(exploracao.descrever_database(database_id.strip()))

    return _responder(_descrever)


@csrf_exempt
@require_http_methods(["POST"])
def atualizar_github(request: HttpRequest) -> JsonResponse:
    """Re-sincroniza o inventário GitHub com as mesmas flags do CLI."""

    from felixo_notion_mcp.integrations.notion import criar_cliente
    from felixo_notion_mcp.services import inventario_github

    def _atualizar() -> JsonResponse:
        dados = _corpo_json(request)
        contas = _lista_csv_ou_lista(dados.get("contas"), "contas")
        if not contas:
            contas = _lista_csv_ou_lista(os.environ.get("GITHUB_CONTAS", ""), "contas")
        if not contas:
            raise ValueError("'contas' é obrigatório")

        database_id = _texto_opcional(dados, "database") or os.environ.get(
            "NOTION_DATABASE_ID", ""
        ).strip()
        if not database_id:
            raise ValueError("'database' é obrigatório")

        resumo = inventario_github.atualizar_repos(
            contas,
            database_id,
            github_client=GitHubClient(),
            notion_client=criar_cliente(),
            sincronizar_readme=not _bool_opcional(dados, "sem_readme"),
            ignorar_arquivados=_bool_opcional(dados, "sem_arquivados"),
            apenas_mudancas=_bool_opcional(dados, "apenas_mudancas"),
        )
        return JsonResponse(_resumo_inventario_dict(resumo))

    return _responder(_atualizar)
