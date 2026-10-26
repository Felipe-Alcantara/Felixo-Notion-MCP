"""Testes das rotas REST de tarefas, ponta a ponta pela borda HTTP.

Usa o test client do Django (sem rede) com o Notion mockado por ``responses``,
exercitando o caminho real: view → service → ``TaskList`` → ``NotionClient``.
Pulado se o Django não estiver instalado (extras de servidor ausentes).
"""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("django")

import responses  # noqa: E402

from felixo_notion_mcp.core.constants import NOTION_BASE_URL  # noqa: E402

DB = "db_tarefas"


@pytest.fixture(scope="module", autouse=True)
def _django():
    # Config mínima para subir o Django sem segredo real nem rede.
    os.environ.setdefault("DJANGO_DEBUG", "1")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "felixo_notion_mcp.api.http.config.settings")
    import django

    django.setup()


@pytest.fixture(autouse=True)
def _notion_env(monkeypatch):
    # Fixa token/database deste módulo a cada teste. Usa setenv (não
    # setdefault) para não herdar valores que outro teste possa ter deixado
    # em os.environ — as rotas montam o NotionClient a partir do ambiente.
    monkeypatch.setenv("NOTION_TOKEN", "ntn_test_token")
    monkeypatch.setenv("NOTION_DATABASE_ID", DB)


@pytest.fixture
def client():
    from django.test import Client

    return Client(HTTP_HOST="localhost")


def _pagina(id_, nome, status=None, prazo=None, duracao=None, areas=None):
    props = {"Tarefa": {"type": "title", "title": [{"plain_text": nome}]}}
    if status is not None:
        props["Etapa"] = {"type": "status", "status": {"name": status}}
    if prazo is not None:
        props["Prazo"] = {"type": "date", "date": {"start": prazo}}
    if duracao is not None:
        props["Esforço"] = {"type": "status", "status": {"name": duracao}}
    if areas is not None:
        props["Áreas da vida"] = {
            "type": "relation",
            "relation": [{"id": area_id} for area_id in areas],
        }
    return {"id": id_, "url": f"https://notion.so/{id_}", "properties": props}


@responses.activate
def test_get_tarefas_lista(client):
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/{DB}/query",
        json={"results": [_pagina("t1", "A", "Entrada")], "has_more": False},
        status=200,
    )
    resp = client.get("/api/tarefas")
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["tarefas"][0]["nome"] == "A"
    assert "bruto" not in corpo["tarefas"][0]


@responses.activate
def test_get_database_atual_retorna_contexto(client):
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DB}",
        json={
            "url": f"https://notion.so/{DB}",
            "title": [{"plain_text": "Tarefas — HOME (pessoal)"}],
            "properties": {},
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DB}",
        json={"data_sources": [{"id": "ds1", "name": "Tarefas — HOME (pessoal)"}]},
        status=200,
    )

    resp = client.get("/api/database-atual")

    assert resp.status_code == 200
    assert resp.json() == {
        "id": DB,
        "titulo": "Tarefas — HOME (pessoal)",
        "url": f"https://notion.so/{DB}",
        "data_sources": ["Tarefas — HOME (pessoal)"],
    }


@responses.activate
def test_get_tarefas_filtra_por_status(client):
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/{DB}/query",
        json={"results": [], "has_more": False},
        status=200,
    )
    client.get("/api/tarefas", {"status": "Entrada"})
    corpo = json.loads(responses.calls[0].request.body)
    assert corpo["filter"] == {"property": "Etapa", "status": {"equals": "Entrada"}}


@responses.activate
def test_get_tarefas_filtra_por_status_duracao_e_area(client):
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/{DB}/query",
        json={"results": [], "has_more": False},
        status=200,
    )
    client.get("/api/tarefas", {"status": "Entrada", "duracao": "Dias", "area": "a1"})
    corpo = json.loads(responses.calls[0].request.body)
    assert corpo["filter"] == {
        "and": [
            {"property": "Etapa", "status": {"equals": "Entrada"}},
            {"property": "Esforço", "status": {"equals": "Dias"}},
            {"property": "Áreas da vida", "relation": {"contains": "a1"}},
        ]
    }


@responses.activate
def test_post_tarefa_cria(client):
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/pages",
        json=_pagina("novo", "Nova", "Entrada", duracao="Dias", areas=["a1"]),
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DB}",
        json={
            "properties": {
                "Tarefa": {"type": "title", "title": {}},
                "Etapa": {"type": "status", "status": {}},
                "Esforço": {"type": "status", "status": {}},
                "Áreas da vida": {
                    "type": "relation",
                    "relation": {"database_id": "db_areas"},
                }
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db_areas/query",
        json={
            "results": [
                {
                    "id": "a1",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Estudos"}]}
                    },
                }
            ],
            "has_more": False,
        },
        status=200,
    )
    resp = client.post(
        "/api/tarefas",
        data=json.dumps(
            {
                "nome": "Nova",
                "status": "Entrada",
                "duracao": "Dias",
                "areas": ["a1"],
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 201
    corpo = resp.json()
    assert corpo["id"] == "novo"
    assert corpo["duracao"] == "Dias"
    assert corpo["areas"] == ["a1"]
    assert corpo["areas_nomes"] == ["Estudos"]

    request_call = next(
        call
        for call in responses.calls
        if call.request.method == "POST" and call.request.url == f"{NOTION_BASE_URL}/pages"
    )
    request = json.loads(request_call.request.body)
    assert request["properties"]["Esforço"]["status"]["name"] == "Dias"
    assert request["properties"]["Áreas da vida"]["relation"] == [{"id": "a1"}]


def test_post_tarefa_sem_nome_e_400(client):
    resp = client.post(
        "/api/tarefas",
        data=json.dumps({"status": "Entrada"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["erro"]["codigo"] == "validacao"


@responses.activate
def test_patch_tarefa_move_status(client):
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/t1",
        json=_pagina("t1", "A", "Assim que possível"),
        status=200,
    )
    resp = client.patch(
        "/api/tarefas/t1",
        data=json.dumps({"status": "Assim que possível"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "Assim que possível"


@responses.activate
def test_patch_tarefa_edita_campos_amplos(client):
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/t1",
        json=_pagina("t1", "Renomeada", "Assim que possível", duracao="Poucas horas", areas=["a1"]),
        status=200,
    )
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DB}",
        json={
            "properties": {
                "Áreas da vida": {
                    "type": "relation",
                    "relation": {"database_id": "db_areas"},
                }
            }
        },
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db_areas/query",
        json={
            "results": [
                {
                    "id": "a1",
                    "properties": {
                        "Name": {"type": "title", "title": [{"plain_text": "Estudos"}]}
                    },
                }
            ],
            "has_more": False,
        },
        status=200,
    )
    resp = client.patch(
        "/api/tarefas/t1",
        data=json.dumps(
            {
                "nome": "Renomeada",
                "status": "Assim que possível",
                "duracao": "Poucas horas",
                "areas": ["a1"],
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["nome"] == "Renomeada"
    assert corpo["duracao"] == "Poucas horas"
    assert corpo["areas"] == ["a1"]
    assert corpo["areas_nomes"] == ["Estudos"]

    request = json.loads(responses.calls[0].request.body)
    assert request["properties"]["Tarefa"]["title"][0]["text"]["content"] == "Renomeada"
    assert request["properties"]["Esforço"]["status"]["name"] == "Poucas horas"
    assert request["properties"]["Áreas da vida"]["relation"] == [{"id": "a1"}]


def test_patch_tarefa_sem_campos_e_400(client):
    resp = client.patch(
        "/api/tarefas/t1",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["erro"]["codigo"] == "validacao"


def test_patch_tarefa_areas_invalidas_e_400(client):
    resp = client.patch(
        "/api/tarefas/t1",
        data=json.dumps({"areas": "a1"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["erro"]["codigo"] == "validacao"


@responses.activate
def test_patch_tarefa_inexistente_e_404(client):
    responses.add(
        responses.PATCH,
        f"{NOTION_BASE_URL}/pages/inexistente",
        json={"message": "Could not find page"},
        status=404,
    )
    resp = client.patch(
        "/api/tarefas/inexistente",
        data=json.dumps({"status": "Concluída"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
    assert resp.json()["erro"]["codigo"] == "nao_encontrado"


@responses.activate
def test_falha_do_notion_vira_502(client):
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/{DB}/query",
        json={"message": "erro interno"},
        status=500,
    )
    resp = client.get("/api/tarefas")
    assert resp.status_code == 502
    assert resp.json()["erro"]["codigo"] == "erro_upstream"


def test_configuracao_ausente_orienta_iniciar_tudo(client, monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    from felixo_notion_mcp.api.http.rest import views

    def falhar(*args, **kwargs):
        raise ImproperlyConfigured("detalhe interno")

    monkeypatch.setattr(views.svc, "listar_tarefas", falhar)

    resp = client.get("/api/tarefas")

    assert resp.status_code == 500
    assert resp.json()["erro"]["codigo"] == "erro_interno"
    assert "Iniciar tudo" in resp.json()["erro"]["mensagem"]
    assert "detalhe interno" not in resp.content.decode()


def test_token_ausente_na_fabrica_do_cliente_orienta_iniciar_tudo(client, monkeypatch):
    # A fábrica `integrations.notion.criar_cliente` (a que os services usam) levanta a
    # `ImproperlyConfigured` da biblioteca, que não é a do Django: a view precisa tratar
    # as duas do mesmo jeito, ou a ausência do token viraria "Erro interno inesperado".
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    # Um `.env` real na raiz do checkout devolveria o token ao ambiente.
    monkeypatch.setattr("felixo_notion_mcp.core.config.carregar_env_file", lambda *_a, **_k: None)

    resp = client.get("/api/tarefas")

    assert resp.status_code == 500
    assert resp.json()["erro"]["codigo"] == "erro_interno"
    assert "Iniciar tudo" in resp.json()["erro"]["mensagem"]
    assert "NOTION_TOKEN" not in resp.content.decode()


def test_metodo_nao_permitido_e_405(client):
    resp = client.delete("/api/tarefas/t1")
    assert resp.status_code == 405


@responses.activate
def test_get_opcoes_lista_status_duracao_areas(client):
    responses.add(
        responses.GET,
        f"{NOTION_BASE_URL}/databases/{DB}",
        json={
            "properties": {
                "Etapa": {
                    "type": "status",
                    "status": {"options": [{"name": "Entrada"}, {"name": "Concluída"}]},
                },
                "Esforço": {
                    "type": "status",
                    "status": {"options": [{"name": "Minutos"}, {"name": "Dias"}]},
                },
                "Áreas da vida": {
                    "type": "relation",
                    "relation": {"database_id": "db_areas"},
                },
            },
        },
        status=200,
    )
    responses.add(
        responses.POST,
        f"{NOTION_BASE_URL}/databases/db_areas/query",
        json={
            "results": [
                {
                    "id": "a1",
                    "properties": {
                        "Tarefa": {
                            "type": "title",
                            "title": [{"plain_text": "Estudos"}],
                        }
                    },
                }
            ],
            "has_more": False,
        },
        status=200,
    )
    resp = client.get("/api/opcoes")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": ["Entrada", "Concluída"],
        "duracao": ["Minutos", "Dias"],
        "areas": [{"id": "a1", "nome": "Estudos"}],
    }


def test_post_atualizar_github_repassa_flags(client, monkeypatch):
    from felixo_notion_mcp.services.inventario_github import ResumoInventario

    chamadas = {}

    def atualizar_repos(*args, **kwargs):
        chamadas["args"] = args
        chamadas["kwargs"] = kwargs
        return ResumoInventario(repos_encontrados=1, paginas_puladas=1)

    monkeypatch.setattr("felixo_notion_mcp.integrations.notion.criar_cliente", lambda: object())
    monkeypatch.setattr(
        "felixo_notion_mcp.services.inventario_github.atualizar_repos", atualizar_repos
    )

    resp = client.post(
        "/api/github/atualizar",
        data=json.dumps(
            {
                "contas": "felipe, https://github.com/outra",
                "database": "db-github",
                "sem_readme": True,
                "sem_arquivados": True,
                "apenas_mudancas": True,
            }
        ),
        content_type="application/json",
    )

    assert resp.status_code == 200
    assert resp.json()["repos_encontrados"] == 1
    assert resp.json()["paginas_puladas"] == 1
    assert chamadas["args"][:2] == (["felipe", "https://github.com/outra"], "db-github")
    assert chamadas["kwargs"]["sincronizar_readme"] is False
    assert chamadas["kwargs"]["ignorar_arquivados"] is True
    assert chamadas["kwargs"]["apenas_mudancas"] is True


# --- CSRF no servidor local --------------------------------------------------------------
# O servidor não usa cookie de sessão, então o CSRF do Django não tem o que proteger. A defesa
# é exigir ``application/json``: uma página de outro site só consegue disparar, sem preflight,
# um POST "simples" (texto, formulário ou sem corpo), e o servidor não responde ao preflight.

_ROTAS_QUE_ESCREVEM = [
    ("post", "/api/tarefas"),
    ("patch", "/api/tarefas/t1"),
    ("post", "/api/github/atualizar"),
]


@responses.activate
@pytest.mark.parametrize(("metodo", "caminho"), _ROTAS_QUE_ESCREVEM)
@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x", ""],
)
def test_rota_que_escreve_recusa_corpo_que_nao_e_json_antes_de_falar_com_o_notion(
    client, metodo, caminho, content_type
):
    resp = getattr(client, metodo)(
        caminho, data='{"nome": "feito de outro site"}', content_type=content_type
    )

    assert resp.status_code == 400
    assert resp.json()["erro"]["codigo"] == "validacao"
    assert "application/json" in resp.json()["erro"]["mensagem"]
    assert len(responses.calls) == 0


def test_corpo_json_aceita_charset_no_content_type():
    from django.test import RequestFactory

    from felixo_notion_mcp.api.http.rest.views import _corpo_json

    requisicao = RequestFactory().post(
        "/api/tarefas", data='{"nome": "ok"}', content_type="application/json; charset=utf-8"
    )

    assert _corpo_json(requisicao) == {"nome": "ok"}


# --- DNS rebinding no servidor local -----------------------------------------------------
# O menu sobe o app com DJANGO_DEBUG=1; o padrão de hosts não pode virar "*" nesse modo, ou um
# domínio do atacante apontado para 127.0.0.1 passa a falar com a API como se fosse da mesma
# origem (e o preflight de CORS não entra, porque não é uma requisição entre origens).


@responses.activate
def test_host_de_outro_dominio_e_recusado_antes_de_qualquer_rota():
    from django.test import Client

    resp = Client(HTTP_HOST="atacante.exemplo.org").get("/api/health")

    assert resp.status_code == 400
    assert len(responses.calls) == 0
