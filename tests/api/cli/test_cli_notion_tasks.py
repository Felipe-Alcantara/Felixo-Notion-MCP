"""Testes da CLI para IA.

A CLI é testada por injeção de doubles de ``TaskList``/``NotionClient``: sem
token, sem rede e sem tocar no Notion real.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from felixo_notion_mcp import Tarefa
from felixo_notion_mcp.api.cli import notion_tasks as cli


class FakeTaskList:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, object]] = []

    def listar(self, status=None, duracao=None, areas=None):
        self.chamadas.append(("listar", (status, duracao, areas)))
        return [
            Tarefa(
                id="t1",
                nome="Estudar",
                status=status or "Entrada",
                prazo="2026-07-01",
                duracao=duracao or "Dias",
                areas=areas or ["a1"],
                areas_nomes=["Estudos"],
                url="https://notion.so/t1",
            )
        ]

    def criar(self, nome, status=None, prazo=None, duracao=None, areas=None):
        self.chamadas.append(("criar", (nome, status, prazo, duracao, areas)))
        return Tarefa(
            id="novo",
            nome=nome,
            status=status,
            prazo=prazo,
            duracao=duracao,
            areas=areas or [],
            url="https://notion.so/novo",
        )

    def editar(self, task_id, *, nome=None, status=None, prazo=None, duracao=None, areas=None):
        self.chamadas.append(("editar", (task_id, nome, status, prazo, duracao, areas)))
        return Tarefa(
            id=task_id,
            nome=nome or "Editada",
            status=status,
            prazo=prazo,
            duracao=duracao,
            areas=areas or [],
            url=f"https://notion.so/{task_id}",
        )

    def atualizar_status(self, task_id, status):
        self.chamadas.append(("atualizar_status", (task_id, status)))
        return Tarefa(id=task_id, nome="Movida", status=status, url=f"https://notion.so/{task_id}")

    def concluir(self, task_id, status_concluido):
        self.chamadas.append(("concluir", (task_id, status_concluido)))
        return Tarefa(
            id=task_id,
            nome="Concluída",
            status=status_concluido,
            url=f"https://notion.so/{task_id}",
        )

    def opcoes(self):
        self.chamadas.append(("opcoes", None))
        return {
            "status": ["Entrada", "Assim que possível", "Concluída"],
            "duracao": ["Dias"],
            "areas": [{"id": "a1", "nome": "Estudos"}],
        }


class FakeTaskListLote:
    """TaskList mínimo para verificar criação de várias linhas."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, object]] = []

    def criar(self, nome, status=None, prazo=None, duracao=None, areas=None):
        indice = len([chamada for chamada in self.chamadas if chamada[0] == "criar"]) + 1
        self.chamadas.append(("criar", (nome, status, prazo, duracao, areas)))
        return Tarefa(
            id=f"novo-{indice}",
            nome=nome,
            status=status,
            prazo=prazo,
            duracao=duracao,
            areas=areas or [],
            url=f"https://notion.so/novo-{indice}",
        )


class FakeClient:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, object]] = []
        self.database = {
            "id": "db1",
            "url": "https://notion.so/db1",
            "title": [{"plain_text": "Tarefas"}],
            "properties": {
                "Nome": {"type": "title", "title": {}},
                "Status": {
                    "type": "status",
                    "status": {
                        "options": [
                            {"id": "old-status", "name": "00. Inbox", "color": "default"},
                            {"id": "done-status", "name": "06. Feito", "color": "green"},
                        ],
                        "groups": [
                            {
                                "name": "In progress",
                                "option_ids": ["old-status"],
                            },
                            {
                                "name": "Complete",
                                "option_ids": ["done-status"],
                            },
                        ],
                    },
                },
                "Duração": {
                    "type": "status",
                    "status": {
                        "options": [
                            {"id": "fast", "name": "Mais rápido possível", "color": "red"},
                            {"id": "days", "name": "Dias", "color": "yellow"},
                        ],
                        "groups": [{"name": "To-do", "option_ids": ["fast", "days"]}],
                    },
                },
                "Áreas-da-Vida": {
                    "type": "relation",
                    "relation": {"database_id": "areas-db"},
                },
            },
        }
        self.areas_database = {
            "id": "areas-db",
            "title": [{"plain_text": "Áreas-da-Vida"}],
            "properties": {"Name": {"type": "title", "title": {}}},
        }
        self.paginas = [
            {
                "id": "t1",
                "properties": {
                    "Status": {"type": "status", "status": {"name": "00. Inbox"}},
                    "Duração": {
                        "type": "status",
                        "status": {"name": "Mais rápido possível"},
                    },
                },
            }
        ]
        self.areas = [
            {
                "id": "a1",
                "properties": {"Name": {"type": "title", "title": [{"plain_text": "Money"}]}},
            }
        ]

    def buscar(self, query=None, page_size=100, buscar_todos=False, filtro=None):
        if filtro == {"property": "object", "value": "database"}:
            return [
                {
                    "id": "db1",
                    "object": "database",
                    "title": [{"plain_text": "Tarefas"}],
                    "url": "https://notion.so/db1",
                }
            ]
        return [
            {
                "id": "p1",
                "object": "page",
                "parent": {"type": "workspace", "workspace": True},
                "properties": {"Nome": {"type": "title", "title": [{"plain_text": "Home"}]}},
            },
            {
                "id": "db1",
                "object": "database",
                "parent": {"type": "page_id", "page_id": "p1"},
                "title": [{"plain_text": "Tarefas"}],
            },
        ]

    def get_database(self, database_id):
        if database_id == "areas-db":
            return self.areas_database
        return self.database

    def listar_data_sources(self, database_id):
        self.chamadas.append(("listar_data_sources", database_id))
        return [{"id": "ds1", "name": "Tarefas"}]

    def consultar_database(self, database_id, buscar_todos=False):
        return self.areas if database_id == "areas-db" else self.paginas

    def atualizar_database(self, database_id, *, titulo=None, propriedades=None):
        self.chamadas.append(("atualizar_database", (database_id, titulo, propriedades)))
        if database_id == "areas-db":
            alvo = self.areas_database
        else:
            alvo = self.database
        if titulo:
            alvo["title"] = [{"plain_text": titulo}]
        for nome, mudanca in (propriedades or {}).items():
            if "name" in mudanca and nome in alvo["properties"]:
                alvo["properties"][mudanca["name"]] = alvo["properties"].pop(nome)
            elif nome in alvo["properties"] and "status" in mudanca:
                atuais = {op["name"]: op for op in alvo["properties"][nome]["status"]["options"]}
                novas = []
                for op in mudanca["status"]["options"]:
                    if "id" in op:
                        novas.extend(item for item in atuais.values() if item.get("id") == op["id"])
                    else:
                        novas.append(
                            {
                                "id": op["name"].casefold().replace(" ", "-"),
                                "name": op["name"],
                                "color": op.get("color", "default"),
                            }
                        )
                alvo["properties"][nome]["status"]["options"] = novas
        return alvo

    def obter_pagina(self, page_id):
        self.chamadas.append(("obter_pagina", page_id))
        return {
            "id": page_id,
            "properties": {
                "Nome": {"type": "title", "title": []},
                "Status": {"type": "status", "status": {"name": "Inbox"}},
                "Prazo": {"type": "date", "date": None},
                "Tags": {"type": "multi_select", "multi_select": []},
                "Peso": {"type": "number", "number": None},
                "Fórmula": {"type": "formula", "formula": {}},
            },
        }

    def atualizar_pagina(self, page_id, propriedades):
        self.chamadas.append(("atualizar_pagina", (page_id, propriedades)))
        return {"id": page_id, "properties": propriedades}

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler_blocos", block_id))
        return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "oi"}]}}]

    def anexar_blocos(self, block_id, blocos):
        self.chamadas.append(("anexar_blocos", (block_id, blocos)))
        return {"results": blocos}

    def atualizar_bloco(self, block_id, conteudo):
        self.chamadas.append(("atualizar_bloco", (block_id, conteudo)))
        return {"id": block_id}

    def excluir_bloco(self, block_id):
        self.chamadas.append(("excluir_bloco", block_id))
        return {"id": block_id, "archived": True}

    def restaurar_bloco(self, block_id):
        self.chamadas.append(("restaurar_bloco", block_id))
        return {"id": block_id, "in_trash": False}

    def obter_bloco(self, block_id):
        self.chamadas.append(("obter_bloco", block_id))
        if block_id.startswith("sub"):
            return {
                "id": block_id,
                "type": "child_page",
                "child_page": {"title": "Sandbox inteira"},
                "has_children": True,
            }
        return {
            "id": block_id,
            "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": f"texto de {block_id}"}]},
            "has_children": False,
        }

    def criar_subpagina(self, pagina_pai_id, titulo, *, blocos=None):
        self.chamadas.append(("criar_subpagina", (pagina_pai_id, titulo)))
        return {"id": f"sub-{titulo}", "url": f"https://notion.so/sub-{titulo}"}

    def consultar_data_source(self, data_source_id, page_size=100, buscar_todos=False, filtro=None):
        self.chamadas.append(("consultar_data_source", data_source_id))
        return []


class FakeCloneClient(FakeClient):
    """Cliente que sustenta o fluxo de ``clonar-database`` ponta a ponta."""

    def listar_data_sources(self, database_id):
        nome = "Origem" if database_id == "db1" else "Origem (cópia)"
        fonte = "f_origem" if database_id == "db1" else "f_clone"
        return [{"id": fonte, "name": nome}]

    def get_data_source(self, data_source_id):
        if data_source_id == "f_origem":
            return {
                "properties": {
                    "Tarefa": {"type": "title", "title": {}},
                    "Esforço": {"type": "status", "status": {"options": [{"name": "Dias"}]}},
                },
                "parent": {"type": "page_id", "page_id": "pagina_pai"},
            }
        return {"properties": {}}

    def criar_database(self, pagina_id, titulo, propriedades):
        self.chamadas.append(("criar_database", (pagina_id, titulo)))
        return {"id": "db_clone"}

    def atualizar_data_source(self, data_source_id, *, propriedades):
        self.chamadas.append(("atualizar_data_source", data_source_id))
        return {"properties": propriedades}

    def criar_pagina_em_fonte(self, data_source_id, propriedades):
        self.chamadas.append(("criar_pagina_em_fonte", data_source_id))
        return {"id": "nova"}


class FakeDatabaseClient(FakeClient):
    """Cliente onde o ID consultado é um database (blocos vazios, com linhas)."""

    def obter_pagina(self, page_id):
        # Como na API real: GET /pages/<database_id> responde 404.
        from felixo_notion_mcp import NotionHTTPError

        raise NotionHTTPError(404, "não é uma página")

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        return []

    def listar_data_sources(self, database_id):
        return [{"id": "ds1", "name": "Principal"}]

    def consultar_data_source(self, data_source_id, page_size=100, buscar_todos=False, filtro=None):
        return [
            {
                "id": "r1",
                "url": "https://notion.so/r1",
                "properties": {"Name": {"type": "title", "title": [{"plain_text": "Linha 1"}]}},
            }
        ]


class FakeExemploClient(FakeClient):
    """Cliente com linhas e páginas completas para o comando ``exemplo``."""

    _linhas = [
        {
            "id": "r1",
            "url": "https://notion.so/r1",
            "properties": {"Nome": {"type": "title", "title": [{"plain_text": "Primeira linha"}]}},
        },
        {
            "id": "r2",
            "url": "https://notion.so/r2",
            "properties": {"Nome": {"type": "title", "title": [{"plain_text": "Segunda linha"}]}},
        },
        {
            "id": "r3",
            "url": "https://notion.so/r3",
            "properties": {"Nome": {"type": "title", "title": [{"plain_text": "Terceira linha"}]}},
        },
    ]

    def listar_data_sources(self, database_id):
        self.chamadas.append(("listar_data_sources", database_id))
        return [{"id": "ds1", "name": "Tarefas"}]

    def consultar_data_source(self, data_source_id, page_size=100, buscar_todos=False, filtro=None):
        self.chamadas.append(("consultar_data_source", data_source_id))
        return self._linhas

    def obter_pagina(self, page_id):
        self.chamadas.append(("obter_pagina", page_id))
        linha = next(linha for linha in self._linhas if linha["id"] == page_id)
        titulo = linha["properties"]["Nome"]["title"][0]["plain_text"]
        return {
            "id": page_id,
            "properties": {
                "Nome": {
                    "type": "title",
                    "title": [{"plain_text": titulo}],
                },
                "Status": {"type": "status", "status": {"name": "Entrada"}},
            },
        }

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler_blocos", block_id))
        return [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": f"Corpo de {block_id}"}]},
            }
        ]


def _executar(args, fake: FakeTaskList | None = None, client=None):
    tasklist = fake or FakeTaskList()
    notion_client = client or FakeClient()
    return cli.executar(
        args,
        tasklist_factory=lambda: tasklist,
        client_factory=lambda: notion_client,
    )


def test_listar_json_emite_envelope_estavel():
    codigo, saida = _executar(
        ["--json", "listar", "--status", "Entrada", "--duracao", "Dias", "--area", "a1"]
    )
    assert codigo == 0
    assert saida["ok"] is True
    assert saida["dados"][0]["id"] == "t1"
    assert "bruto" not in saida["dados"][0]


def test_listar_delega_filtros_para_services():
    fake = FakeTaskList()
    codigo, _ = _executar(
        ["--json", "listar", "--status", "Entrada", "--duracao", "Dias", "--area", "a1,a2"],
        fake,
    )

    assert codigo == 0
    assert fake.chamadas == [("listar", ("Entrada", "Dias", ["a1", "a2"]))]


def test_criar_delega_campos_amplos_para_services():
    fake = FakeTaskList()
    codigo, saida = _executar(
        [
            "--json",
            "criar",
            "Nova tarefa",
            "--status",
            "Entrada",
            "--duracao",
            "Dias",
            "--area",
            "a1,a2",
        ],
        fake,
    )
    assert codigo == 0
    # Agora valida status antes de criar, então espera chamada a listar_opcoes também
    assert fake.chamadas[0] == ("opcoes", None)
    assert fake.chamadas[1] == ("criar", ("Nova tarefa", "Entrada", None, "Dias", ["a1", "a2"]))
    assert saida["dados"]["areas"] == ["a1", "a2"]


def test_editar_exige_ao_menos_um_campo():
    codigo, saida = _executar(["--json", "editar", "t1"])
    assert codigo == 2
    assert saida == {
        "ok": False,
        "erro": {
            "codigo": "validacao",
            "mensagem": "Informe ao menos um campo para editar.",
            "proximo_passo": None,
            "http_status": None,
            "notion_code": None,
            "detalhes": {},
        },
    }


def test_mover_e_concluir_delegam_para_tasklist():
    fake = FakeTaskList()
    codigo_mover, _ = _executar(["mover", "t1", "Assim que possível"], fake)
    codigo_concluir, _ = _executar(["concluir", "t1", "Concluída"], fake)
    assert codigo_mover == 0
    assert codigo_concluir == 0
    # Agora valida status antes de mover/concluir
    assert fake.chamadas[0] == ("opcoes", None)
    assert fake.chamadas[1] == ("atualizar_status", ("t1", "Assim que possível"))
    assert fake.chamadas[2] == ("opcoes", None)
    assert fake.chamadas[3] == ("concluir", ("t1", "Concluída"))


def test_ler_busca_tarefa_por_id():
    codigo, saida = _executar(["--json", "ler", "t1"])
    assert codigo == 0
    assert saida["dados"]["nome"] == "Estudar"


def test_ler_retorna_erro_quando_nao_encontra():
    codigo, saida = _executar(["--json", "ler", "inexistente"])
    assert codigo == 2
    assert saida["erro"]["mensagem"].startswith("Tarefa não encontrada")
    # Mesmo código do 404 do Notion, e o caminho para uma linha de outro database.
    assert saida["erro"]["codigo"] == "nao_encontrado"
    assert saida["erro"]["proximo_passo"] == "notion-tasks conteudo inexistente"


UUID_TAREFA = "3e691f95-497e-816b-b57e-e8ae6be6d500"


class FakeTaskListUUID(FakeTaskList):
    """Tarefa com ID real (UUID com hífens), como a API devolve."""

    def listar(self, status=None, duracao=None, areas=None):
        tarefa = super().listar(status, duracao, areas)[0]
        tarefa.id = UUID_TAREFA
        return [tarefa]


def test_ler_aceita_o_id_sem_hifens_do_campo_url():
    """A forma sem hífens é a que aparece no 'url' da própria resposta."""

    codigo, saida = _executar(
        ["--json", "ler", UUID_TAREFA.replace("-", "")], fake=FakeTaskListUUID()
    )
    assert codigo == 0
    assert saida["dados"]["id"] == UUID_TAREFA


def test_ler_aceita_id_em_maiusculas_e_link_do_notion():
    for entrada in (
        UUID_TAREFA.upper(),
        f"https://app.notion.com/p/Estudar-{UUID_TAREFA.replace('-', '')}",
        f"https://www.notion.so/meu-espaco/Estudar-{UUID_TAREFA.replace('-', '')}?pvs=4",
    ):
        codigo, saida = _executar(["--json", "ler", entrada], fake=FakeTaskListUUID())
        assert codigo == 0, entrada
        assert saida["dados"]["id"] == UUID_TAREFA


def test_blocos_com_link_chama_a_api_com_o_id_canonico():
    """Antes o link ia cru para a API: HTTP 400 'Invalid request URL'."""

    client = FakeClient()
    link = f"https://app.notion.com/p/Pagina-{UUID_TAREFA.replace('-', '')}"
    codigo, _ = _executar(["--json", "blocos", link], client=client)
    assert codigo == 0
    assert ("ler_blocos", UUID_TAREFA) in client.chamadas


def test_link_de_database_ignora_o_id_da_view():
    client = FakeDatabaseClient()
    view = "0" * 31 + "1"
    link = f"https://www.notion.so/{UUID_TAREFA.replace('-', '')}?v={view}"
    codigo, saida = _executar(["--json", "linhas", link], client=client)
    assert codigo == 0
    assert saida["dados"]["id"] == UUID_TAREFA


def test_editar_bloco_com_link_usa_a_ancora_do_bloco():
    client = FakeClient()
    client.obter_bloco = lambda block_id: {
        "id": block_id,
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "a"}}]},
    }
    bloco = "1" * 32
    link = f"https://www.notion.so/Pagina-{UUID_TAREFA.replace('-', '')}#{bloco}"
    codigo, _ = _executar(["--json", "editar-bloco", link, "novo texto"], client=client)
    assert codigo == 0
    alvos = [c[1][0] for c in client.chamadas if c[0] == "atualizar_bloco"]
    assert alvos == ["11111111-1111-1111-1111-111111111111"]


def test_link_sem_id_e_recusado_antes_da_api():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "conteudo", "https://www.notion.so/meu-espaco/sem-id"], client=client
    )
    assert codigo == 2
    assert saida["erro"]["codigo"] == "id_invalido"
    assert client.chamadas == []


def test_opcoes_retorna_json_dos_seletores():
    codigo, saida = _executar(["--json", "opcoes"])
    assert codigo == 0
    assert saida["dados"]["status"] == ["Entrada", "Assim que possível", "Concluída"]


def test_databases_lista_databases_visiveis():
    codigo, saida = _executar(["--json", "databases"])
    assert codigo == 0
    assert saida["dados"] == [{"id": "db1", "titulo": "Tarefas", "url": "https://notion.so/db1"}]


def test_mapear_resume_workspace():
    codigo, saida = _executar(["--json", "mapear"])
    assert codigo == 0
    assert saida["dados"]["total_itens"] == 2
    assert saida["dados"]["total_paginas"] == 1
    assert saida["dados"]["total_databases"] == 1


def test_mapear_com_html_e_saida_grava_o_mapa_completo(tmp_path: Path):
    codigo, saida = _executar(
        ["--json", "mapear", "--saida", str(tmp_path / "mapa.json"),
         "--html", str(tmp_path / "mapa.html")]
    )

    assert codigo == 0, saida
    assert saida["dados"]["arquivos"] == {
        "json": str(tmp_path / "mapa.json"),
        "html": str(tmp_path / "mapa.html"),
    }
    mapa = json.loads((tmp_path / "mapa.json").read_text(encoding="utf-8"))
    assert mapa["linhas_por_database"] == {"db1": 1}
    assert "Tarefas" in (tmp_path / "mapa.html").read_text(encoding="utf-8")
    assert saida["dados"]["total_itens"] == 2  # o resumo de sempre continua na resposta


def test_escolher_database_sem_perfil_grava_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    salvar_database_env = cli._salvar_database_env
    with (
        mock.patch.object(cli, "RAIZ", tmp_path),
        mock.patch.object(cli.perfis_workspace, "ARQUIVO_PADRAO", tmp_path / "perfis.json"),
        mock.patch.object(
            cli,
            "_salvar_database_env",
            wraps=lambda db_id: salvar_database_env(db_id, env_file),
        ),
    ):
        codigo, saida = _executar(["--json", "escolher-database", "db_novo"])
    assert codigo == 0
    assert env_file.read_text(encoding="utf-8") == "NOTION_DATABASE_ID=db_novo\n"
    assert saida["dados"]["database_id"] == "db_novo"
    assert saida["dados"]["perfil"] == ""


def test_escolher_database_grava_no_perfil_ativo(tmp_path: Path, monkeypatch):
    """Com perfil ativo, o database vai para o perfil — quem vence a resolução.

    Gravando só no ``.env``, ``perfis mostrar`` continuava com database vazio e o
    comando seguinte falhava com "NOTION_DATABASE_ID não configurado" logo depois
    de um ``escolher-database`` que respondeu sucesso.
    """

    arquivo = tmp_path / "perfis.json"
    monkeypatch.delenv("NOTION_PROFILE", raising=False)
    cli.perfis_workspace.adicionar_perfil(
        alias="relatorios",
        token="ntn_" + "a" * 20,
        ativar=True,
        caminho=arquivo,
    )
    with mock.patch.object(cli.perfis_workspace, "ARQUIVO_PADRAO", arquivo):
        codigo, saida = _executar(["--json", "escolher-database", "db_novo"])
        perfil = cli.perfis_workspace.resolver_perfil("relatorios", arquivo)

    assert codigo == 0
    assert saida["dados"]["perfil"] == "relatorios"
    assert saida["dados"]["salvo_em"] == str(arquivo)
    assert perfil is not None and perfil.database_id == "db_novo"
    assert not (tmp_path / ".env").exists()


def test_perfil_global_aplica_workspace_antes_do_comando():
    with mock.patch.object(cli.perfis_workspace, "aplicar_perfil") as aplicar:
        codigo, saida = _executar(["--json", "--perfil", "cliente", "databases"])

    assert codigo == 0
    assert saida["dados"][0]["id"] == "db1"
    aplicar.assert_called_once_with("cliente")


def test_perfis_adicionar_retorna_token_mascarado(tmp_path: Path):
    arquivo = tmp_path / "perfis.json"
    token = "ntn_" + "a" * 20
    with mock.patch.object(cli.perfis_workspace, "ARQUIVO_PADRAO", arquivo):
        codigo, saida = _executar(
            [
                "--json",
                "perfis",
                "adicionar",
                "cliente",
                "--token",
                token,
                "--database",
                "db-cliente",
                "--nome",
                "Cliente",
                "--ativar",
            ]
        )

    assert codigo == 0
    assert saida["dados"]["perfil"]["alias"] == "cliente"
    assert saida["dados"]["perfil"]["token"] == "ntn_aa...aaaa"
    assert token not in json.dumps(saida, ensure_ascii=False)


def test_perfis_remover_exige_confirmacao(tmp_path: Path):
    arquivo = tmp_path / "perfis.json"
    cli.perfis_workspace.adicionar_perfil(
        alias="cliente",
        token="ntn_" + "a" * 20,
        caminho=arquivo,
    )
    with mock.patch.object(cli.perfis_workspace, "ARQUIVO_PADRAO", arquivo):
        codigo, saida = _executar(["--json", "perfis", "remover", "cliente"])

    assert codigo == 2
    assert "--sim" in saida["erro"]["mensagem"]


def test_normalizar_nomes_dry_run_nao_escreve_no_notion(monkeypatch):
    monkeypatch.setenv("NOTION_DATABASE_ID", "db1")
    client = FakeClient()

    codigo, saida = _executar(["--json", "normalizar-nomes", "--dry-run"], client=client)

    assert codigo == 0
    assert saida["dados"]["aplicado"] is False
    assert saida["dados"]["paginas_alteradas"] == 1
    assert saida["dados"]["opcoes_adicionadas"]["status"] == [
        {"de": "00. Inbox", "para": "Entrada"},
        {"de": "06. Feito", "para": "Concluída"},
    ]
    assert client.chamadas == []


def test_normalizar_nomes_aplica_migracao_na_fonte(monkeypatch):
    monkeypatch.setenv("NOTION_DATABASE_ID", "db1")
    client = FakeClient()

    codigo, saida = _executar(["--json", "normalizar-nomes"], client=client)

    assert codigo == 0
    assert saida["dados"]["aplicado"] is True
    assert ("atualizar_pagina", ("t1", mock.ANY)) in client.chamadas
    assert any(chamada[0] == "atualizar_database" for chamada in client.chamadas)
    assert "Etapa" in client.database["properties"]
    assert "Tarefa" in client.database["properties"]
    assert "Área" in client.areas_database["properties"]


def test_main_imprime_json(capsys):
    with mock.patch.object(cli, "executar", return_value=(0, {"ok": True, "dados": []})):
        codigo = cli.main(["--json", "listar"])
    assert codigo == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "dados": []}


# -- Conteúdo (blocos) -----------------------------------------------------


def test_conteudo_le_pagina_como_markdown():
    client = FakeClient()
    codigo, saida = _executar(["--json", "conteudo", "page1"], client=client)
    assert codigo == 0
    assert saida["dados"]["markdown"] == "oi"
    assert ("ler_blocos", "page1") in client.chamadas


def test_escrever_anexa_blocos():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "linha um\nlinha dois"], client=client
    )
    assert codigo == 0
    assert saida["dados"]["blocos_anexados"] == 2
    assert any(c[0] == "anexar_blocos" for c in client.chamadas)


class FakeClientComIds(FakeClient):
    """Anexar como a API: devolve IDs e, com posição, também os irmãos seguintes.

    Medido na API real (2022-06-28): com ``position``, ``results`` traz os
    blocos novos seguidos de todos os irmãos que vêm depois deles.
    """

    def __init__(self) -> None:
        super().__init__()
        self._sequencia = 0

    def anexar_blocos(self, block_id, blocos, *, apos_bloco_id=None, no_inicio=False):
        self.chamadas.append(("anexar_blocos", (block_id, apos_bloco_id, no_inicio)))
        novos = []
        for bloco in blocos:
            self._sequencia += 1
            novos.append({"id": f"novo-{self._sequencia}", **bloco})
        irmaos = [{"id": "irmao-1", "type": "paragraph", "paragraph": {"rich_text": []}}]
        return {"results": novos + (irmaos if apos_bloco_id or no_inicio else [])}


def test_escrever_devolve_os_ids_criados_e_a_posicao():
    client = FakeClientComIds()
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "# Título\n\ntexto"], client=client
    )

    assert codigo == 0
    dados = saida["dados"]
    assert dados["posicao"] == {"tipo": "fim"}
    assert dados["blocos_criados"] == [
        {"id": "novo-1", "tipo": "heading_1"},
        {"id": "novo-2", "tipo": "paragraph"},
    ]


def test_escrever_apos_insere_depois_do_bloco_e_ignora_os_irmaos_devolvidos():
    """Antes o agente reordenava (apagar e recriar) o que era só uma inserção."""

    client = FakeClientComIds()
    ancora = "2" * 32
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "linha nova", "--apos", ancora], client=client
    )

    assert codigo == 0
    esperado = "22222222-2222-2222-2222-222222222222"
    assert ("anexar_blocos", ("page1", esperado, False)) in client.chamadas
    dados = saida["dados"]
    assert dados["posicao"] == {"tipo": "apos_bloco", "bloco_id": esperado}
    # O irmão seguinte que a API devolve junto não é um bloco criado.
    assert dados["blocos_criados"] == [{"id": "novo-1", "tipo": "paragraph"}]
    assert not any(c[0] == "excluir_bloco" for c in client.chamadas)


def test_escrever_inicio_insere_no_comeco():
    client = FakeClientComIds()
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "primeiro", "--inicio"], client=client
    )

    assert codigo == 0
    assert ("anexar_blocos", ("page1", None, True)) in client.chamadas
    assert saida["dados"]["posicao"] == {"tipo": "inicio"}


def test_escrever_posicao_com_substituir_e_recusada_sem_tocar_na_pagina():
    client = FakeClientComIds()
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "x", "--inicio", "--substituir"], client=client
    )

    assert codigo == 2
    assert "--substituir" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_escrever_apos_e_inicio_juntos_sao_recusados():
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "x", "--inicio", "--apos", "b1"],
        client=FakeClientComIds(),
    )

    assert codigo == 2
    assert saida["erro"]["codigo"] == "uso_invalido"


def test_criar_com_conteudo_devolve_os_ids_criados():
    codigo, saida = _executar(
        ["--json", "criar", "Nova", "--conteudo", "## Contexto"], client=FakeClientComIds()
    )

    assert codigo == 0
    assert saida["dados"]["blocos_criados"] == [{"id": "novo-1", "tipo": "heading_2"}]


def test_criar_com_conteudo_que_falha_mantem_o_id_e_diz_que_nada_ficou():
    """A linha existe; o corpo foi desfeito — o conselho é escrever, não recriar."""

    from felixo_notion_mcp import NotionHTTPError

    class ClienteQueRecusaAnexar(FakeClient):
        def anexar_blocos(self, block_id, blocos, **posicao):
            raise NotionHTTPError(400, '{"code": "validation_error", "message": "ruim"}')

    codigo, saida = _executar(
        ["--json", "criar", "Nova", "--conteudo", "texto"], client=ClienteQueRecusaAnexar()
    )

    assert codigo == 2
    erro = saida["erro"]
    assert erro["codigo"] == "criacao_incompleta"
    assert erro["detalhes"]["id"] == "novo"
    assert erro["detalhes"]["causa"] == "escrita_parcial"
    assert "não crie" in erro["mensagem"]
    assert erro["proximo_passo"] == "notion-tasks escrever novo \"<markdown>\""


MARKDOWN_COM_SHELL = "# Nota\n\nCusto `$HOME` e \"aspas\" 'simples' — ok"


def _stdin(monkeypatch, texto: str) -> None:
    import io

    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO(texto.encode("utf-8"))))


def _textos_anexados(client) -> list[str]:
    anexados = [c[1][1] for c in client.chamadas if c[0] == "anexar_blocos"]
    return [
        "".join(item["text"]["content"] for item in bloco[bloco["type"]]["rich_text"])
        for lote in anexados
        for bloco in lote
    ]


def test_escrever_hifen_le_o_markdown_do_stdin(monkeypatch):
    """Antes, 'escrever <id> -' gravava um '-' literal na página."""

    _stdin(monkeypatch, MARKDOWN_COM_SHELL)
    client = FakeClient()
    codigo, saida = _executar(["--json", "escrever", "page1", "-"], client=client)

    assert codigo == 0
    assert saida["dados"]["blocos_anexados"] == 2
    assert _textos_anexados(client) == ["Nota", "Custo $HOME e \"aspas\" 'simples' — ok"]


def test_escrever_arquivo_md(tmp_path):
    nota = tmp_path / "nota.md"
    nota.write_text(MARKDOWN_COM_SHELL, encoding="utf-8")
    client = FakeClient()
    codigo, _ = _executar(
        ["--json", "escrever", "page1", "--arquivo-md", str(nota)], client=client
    )
    assert codigo == 0
    assert _textos_anexados(client)[0] == "Nota"


def test_escrever_recusa_conteudo_e_arquivo_md_juntos(tmp_path):
    nota = tmp_path / "nota.md"
    nota.write_text("x", encoding="utf-8")
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "texto", "--arquivo-md", str(nota)], client=client
    )
    assert codigo == 2
    assert "--arquivo-md" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_hifen_sem_stdin_redirecionado_nao_trava(monkeypatch):
    class Terminal:
        def isatty(self):
            return True

    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    client = FakeClient()
    codigo, saida = _executar(["--json", "escrever", "page1", "-"], client=client)
    assert codigo == 2
    assert "stdin" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_arquivo_md_inexistente_vira_erro_de_uso(tmp_path):
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "--arquivo-md", str(tmp_path / "nao-existe.md")]
    )
    assert codigo == 2
    assert "nao-existe.md" in saida["erro"]["mensagem"]


def test_criar_e_criar_subpagina_aceitam_conteudo_do_stdin(monkeypatch):
    _stdin(monkeypatch, "## Contexto")
    client = FakeClient()
    codigo, _ = _executar(["--json", "criar", "Nova", "--conteudo", "-"], client=client)
    assert codigo == 0
    assert _textos_anexados(client) == ["Contexto"]

    nota = "# README"
    _stdin(monkeypatch, nota)
    blocos_enviados = []

    class ClienteSubpagina(FakeClient):
        def criar_subpagina(self, pagina_pai_id, titulo, *, blocos=None):
            blocos_enviados.append(blocos)
            return super().criar_subpagina(pagina_pai_id, titulo, blocos=blocos)

    codigo, _ = _executar(
        ["--json", "criar-subpagina", "pai", "README", "--conteudo", "-"],
        client=ClienteSubpagina(),
    )
    assert codigo == 0
    assert blocos_enviados[0][0]["type"] == "heading_1"


def _estrutura_anexada(client) -> list[tuple[str, int]]:
    """(tipo, quantidade de filhos) de cada bloco de topo enviado ao Notion."""

    anexados = [c[1][1] for c in client.chamadas if c[0] == "anexar_blocos"]
    return [
        (bloco["type"], len(bloco[bloco["type"]].get("children") or []))
        for lote in anexados
        for bloco in lote
    ]


def test_escrever_lista_recuada_por_igual_nao_vira_lista_aninhada(monkeypatch):
    """O strip() do texto inteiro tirava o recuo só da PRIMEIRA linha: dois itens
    irmãos ('  - a' e '  - b') viravam 'b' filho de 'a'."""

    _stdin(monkeypatch, "  - a\n  - b\n")
    client = FakeClient()
    codigo, saida = _executar(["--json", "escrever", "page1", "-"], client=client)

    assert codigo == 0, saida
    assert _estrutura_anexada(client) == [("bulleted_list_item", 0), ("bulleted_list_item", 0)]


def test_criar_conteudo_recuado_por_igual_mantem_os_itens_irmaos(tmp_path):
    nota = tmp_path / "nota.md"
    nota.write_text("  - a\n  - b\n", encoding="utf-8")
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "criar", "Nova", "--arquivo-md", str(nota)], client=client
    )

    assert codigo == 0, saida
    assert _estrutura_anexada(client) == [("bulleted_list_item", 0), ("bulleted_list_item", 0)]


def test_escrever_so_com_espacos_continua_obrigatorio(monkeypatch):
    _stdin(monkeypatch, " \n\n")
    client = FakeClient()
    codigo, saida = _executar(["--json", "escrever", "page1", "-"], client=client)

    assert codigo == 2
    assert "obrigatório" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_editar_linha_atualiza_propriedades_por_tipo():
    client = FakeClient()
    codigo, saida = _executar(
        [
            "--json",
            "editar-linha",
            "page1",
            "--set",
            "Status=Feito",
            "--set",
            "Tags=urgente,casa",
            "--set",
            "Peso=3",
        ],
        client=client,
    )
    assert codigo == 0
    assert saida["dados"]["atualizadas"] == {
        "Status": "status",
        "Tags": "multi_select",
        "Peso": "number",
    }
    enviados = [c[1][1] for c in client.chamadas if c[0] == "atualizar_pagina"][0]
    assert enviados["Status"] == {"status": {"name": "Feito"}}
    assert enviados["Tags"] == {"multi_select": [{"name": "urgente"}, {"name": "casa"}]}
    assert enviados["Peso"] == {"number": 3}


def test_editar_linha_propriedade_inexistente_erra():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "editar-linha", "page1", "--set", "Inexistente=x"], client=client
    )
    assert codigo == 2
    assert not saida["ok"]
    assert "Inexistente" in saida["erro"]["mensagem"]
    assert not any(c[0] == "atualizar_pagina" for c in client.chamadas)


def test_editar_linha_tipo_somente_leitura_erra():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "editar-linha", "page1", "--set", "Fórmula=x"], client=client
    )
    assert codigo == 2
    assert "formula" in saida["erro"]["mensagem"]


def test_editar_linha_sem_set_erra():
    client = FakeClient()
    codigo, saida = _executar(["--json", "editar-linha", "page1"], client=client)
    assert codigo == 2
    assert not saida["ok"]


def test_editar_linha_lote_reutiliza_cliente_e_continua_depois_de_erro(
    tmp_path: Path, capsys
):
    arquivo = tmp_path / "edicoes.json"
    arquivo.write_text(
        json.dumps(
            [
                {"page_id": "p1", "propriedades": {"Status": "Feito"}},
                {"page_id": "ruim", "propriedades": {"Status": "Feito"}},
                {"page_id": "p2", "propriedades": {"Peso": 3}},
            ]
        ),
        encoding="utf-8",
    )
    cliente = FakeClient()
    obter_pagina = cliente.obter_pagina

    def obter_pagina_com_falha(page_id):
        if page_id == "ruim":
            raise ValueError("falha da linha de teste")
        return obter_pagina(page_id)

    cliente.obter_pagina = obter_pagina_com_falha
    chamadas_factory = 0

    def criar_cliente():
        nonlocal chamadas_factory
        chamadas_factory += 1
        return cliente

    codigo, saida = cli.executar(
        [
            "--json",
            "editar-linha",
            "--arquivo",
            str(arquivo),
            "--progresso-a-cada",
            "2",
        ],
        client_factory=criar_cliente,
    )

    assert codigo == 0
    dados = saida["dados"]
    assert dados["total"] == 3
    assert dados["processados"] == 3
    assert dados["sucessos"] == 2
    assert dados["erros"] == 1
    assert dados["pendentes"] == 0
    assert dados["resultados"][1]["page_id"] == "ruim"
    assert dados["resultados"][1]["estado"] == "erro"
    assert "falha da linha de teste" in dados["resultados"][1]["erro"]["mensagem"]
    # O item de lote usa o mesmo vocabulário de códigos do envelope de topo.
    assert dados["resultados"][1]["erro"]["codigo"] == "validacao"
    assert chamadas_factory == 1
    assert [chamada[1][0] for chamada in cliente.chamadas if chamada[0] == "atualizar_pagina"] == [
        "p1",
        "p2",
    ]
    progresso = capsys.readouterr().err
    assert "[lote] 2/3" in progresso
    assert "[lote] 3/3" in progresso


def test_criar_lote_reutiliza_tasklist_e_marca_criacao_parcial_como_pendente(
    tmp_path: Path, capsys
):
    arquivo = tmp_path / "novas.json"
    arquivo.write_text(
        json.dumps(
            [
                {"nome": "Primeira", "propriedades": {"Status": "Feito"}},
                {"nome": "Parcial", "propriedades": {"Status": "Feito"}},
                {"nome": "Sem propriedades"},
            ]
        ),
        encoding="utf-8",
    )
    tasklist = FakeTaskListLote()
    cliente = FakeClient()
    obter_pagina = cliente.obter_pagina

    def obter_pagina_com_falha(page_id):
        if page_id == "novo-2":
            raise ValueError("não foi possível aplicar as propriedades")
        return obter_pagina(page_id)

    cliente.obter_pagina = obter_pagina_com_falha
    chamadas_tasklist = 0
    chamadas_cliente = 0

    def criar_tasklist():
        nonlocal chamadas_tasklist
        chamadas_tasklist += 1
        return tasklist

    def criar_cliente():
        nonlocal chamadas_cliente
        chamadas_cliente += 1
        return cliente

    codigo, saida = cli.executar(
        [
            "--json",
            "criar",
            "--arquivo",
            str(arquivo),
            "--progresso-a-cada",
            "2",
        ],
        tasklist_factory=criar_tasklist,
        client_factory=criar_cliente,
    )

    assert codigo == 0
    dados = saida["dados"]
    assert dados["total"] == 3
    assert dados["sucessos"] == 2
    assert dados["erros"] == 0
    assert dados["pendentes"] == 1
    assert dados["resultados"][1]["estado"] == "pendente"
    assert dados["resultados"][1]["page_id"] == "novo-2"
    assert "não foi possível aplicar" in dados["resultados"][1]["erro"]["mensagem"]
    assert chamadas_tasklist == 1
    assert chamadas_cliente == 1
    assert len([chamada for chamada in tasklist.chamadas if chamada[0] == "criar"]) == 3
    assert "[lote] 3/3" in capsys.readouterr().err


def test_editar_linha_lote_aceita_csv_com_append(tmp_path: Path):
    arquivo = tmp_path / "edicoes.csv"
    arquivo.write_text(
        "page_id,Status,append:Nome\np1,Feito,nota nova\n",
        encoding="utf-8",
    )
    cliente = FakeClient()

    codigo, saida = cli.executar(
        ["--json", "editar-linha", "--arquivo", str(arquivo)],
        client_factory=lambda: cliente,
    )

    assert codigo == 0
    assert saida["dados"]["sucessos"] == 1
    enviados = [chamada[1][1] for chamada in cliente.chamadas if chamada[0] == "atualizar_pagina"]
    assert enviados[0]["Status"] == {"status": {"name": "Feito"}}
    assert enviados[0]["Nome"]["title"][0]["text"]["content"] == "nota nova"


def _texto(conteudo, **anotacoes):
    return {
        "type": "text",
        "text": {"content": conteudo, "link": None},
        "plain_text": conteudo,
        "annotations": {
            "bold": False,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": False,
            "color": "default",
            **anotacoes,
        },
    }


class FakeEdicaoClient(FakeClient):
    """Bloco atual lido por GET e resposta do PATCH como a API devolve."""

    def __init__(self, atual: dict) -> None:
        super().__init__()
        self.atual = {"id": "b1", **atual}

    def obter_bloco(self, block_id):
        self.chamadas.append(("obter_bloco", block_id))
        return self.atual

    def atualizar_bloco(self, block_id, conteudo):
        self.chamadas.append(("atualizar_bloco", (block_id, conteudo)))
        tipo = next(iter(conteudo))
        return {
            "id": block_id,
            "type": tipo,
            tipo: {**self.atual.get(tipo, {}), **conteudo[tipo]},
            "last_edited_time": "2026-09-25T23:50:00.000Z",
        }

    def patches(self):
        return [c[1][1] for c in self.chamadas if c[0] == "atualizar_bloco"]


def _heading(*itens):
    return {"type": "heading_3", "heading_3": {"rich_text": list(itens), "color": "default"}}


def test_editar_bloco_atualiza_e_confirma_o_que_gravou():
    client = FakeEdicaoClient({"type": "paragraph", "paragraph": {"rich_text": [_texto("a")]}})
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "novo **texto**"], client=client)
    assert codigo == 0
    dados = saida["dados"]
    assert dados["editado"] is True
    assert dados["tipo"] == "paragraph"
    assert dados["markdown"] == "novo **texto**"
    assert dados["editado_em"] == "2026-09-25T23:50:00.000Z"


def test_editar_bloco_com_varias_linhas_recusa_sem_gravar_nada():
    """Antes gravava só a primeira linha e respondia editado=true."""

    client = FakeEdicaoClient({"type": "paragraph", "paragraph": {"rich_text": [_texto("a")]}})
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "linha 1\n\nlinha 2 importante"], client=client
    )
    assert codigo == 2
    erro = saida["erro"]
    assert erro["codigo"] == "edicao_multibloco"
    assert erro["detalhes"]["quantidade"] == 2
    # A dica cita comandos que existem na CLI, não a API Python.
    assert "--apos b1" in erro["mensagem"]
    assert client.patches() == []


def test_editar_bloco_de_codigo_aceita_varias_linhas():
    client = FakeEdicaoClient({"type": "code", "code": {"rich_text": [_texto("x")]}})
    codigo, _ = _executar(
        ["--json", "editar-bloco", "b1", "def f():\n    return 1"], client=client
    )
    assert codigo == 0
    enviado = client.patches()[0]["code"]["rich_text"]
    assert "".join(item["text"]["content"] for item in enviado) == "def f():\n    return 1"


def _codigo_enviado(client) -> str:
    enviado = client.patches()[0]["code"]["rich_text"]
    return "".join(item["text"]["content"] for item in enviado)


def _bloco_de_codigo() -> dict:
    return {"type": "code", "code": {"rich_text": [_texto("x")], "language": "python"}}


def test_editar_bloco_de_codigo_preserva_o_recuo_vindo_do_stdin(monkeypatch):
    """A borda fazia strip() do texto inteiro: o corpo de um método perdia o recuo
    da primeira linha e a resposta ainda dizia editado=true."""

    _stdin(monkeypatch, "    return valor\n\nfim\n")
    client = FakeEdicaoClient(_bloco_de_codigo())
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "-"], client=client)

    assert codigo == 0, saida
    assert _codigo_enviado(client) == "    return valor\n\nfim"


def test_editar_bloco_de_codigo_preserva_o_recuo_vindo_do_arquivo_md(tmp_path):
    arquivo = tmp_path / "trecho.py"
    arquivo.write_text("    indentado primeiro\nsegunda\n", encoding="utf-8")
    client = FakeEdicaoClient(_bloco_de_codigo())
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "--arquivo-md", str(arquivo)], client=client
    )

    assert codigo == 0, saida
    assert _codigo_enviado(client) == "    indentado primeiro\nsegunda"


def test_editar_bloco_de_codigo_do_stdin_com_crlf_nao_grava_retorno_de_carro(monkeypatch):
    """O stdin é lido em bytes; sem normalizar, o CRLF do Windows deixava '\\r' no código
    (o arquivo, lido em modo texto, já chegava com '\\n')."""

    _stdin(monkeypatch, "    x = 1\r\ny = 2\r\n")
    client = FakeEdicaoClient(_bloco_de_codigo())
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "-"], client=client)

    assert codigo == 0, saida
    assert _codigo_enviado(client) == "    x = 1\ny = 2"


def test_editar_bloco_so_com_espacos_continua_pedindo_conteudo(monkeypatch):
    _stdin(monkeypatch, "  \n\t\n")
    client = FakeEdicaoClient(_bloco_de_codigo())
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "-"], client=client)

    assert codigo == 2
    assert "Informe o conteúdo novo" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_editar_bloco_texto_puro_mantem_o_tipo_atual():
    """Texto sem prefixo num heading virava paragraph e a API respondia 400."""

    client = FakeEdicaoClient(_heading(_texto("[20:12] Agente")))
    codigo, _ = _executar(["--json", "editar-bloco", "b1", "[20:15] Agente X"], client=client)
    assert codigo == 0
    assert list(client.patches()[0]) == ["heading_3"]


def test_editar_bloco_titulo_que_comeca_com_numero_grava_o_numero():
    """Medido: "5. texto" num título era lido como item de lista numerada e recusado, e a
    dica do erro mandava repetir justamente o texto que falhou."""

    client = FakeEdicaoClient(_heading(_texto("antigo")))
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "5. Desligar a atualização automática"], client=client
    )
    assert codigo == 0, saida
    payload = client.patches()[0]
    assert list(payload) == ["heading_3"]
    assert payload["heading_3"]["rich_text"][0]["text"]["content"] == (
        "5. Desligar a atualização automática"
    )


def test_editar_bloco_prefixo_de_outro_tipo_e_recusado():
    client = FakeEdicaoClient(_heading(_texto("t")))
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "# Outro"], client=client)
    assert codigo == 2
    assert saida["erro"]["codigo"] == "troca_de_tipo"
    assert client.patches() == []


def test_editar_bloco_recusa_perder_sublinhado_e_cor_e_ensina_o_trocar():
    client = FakeEdicaoClient(_heading(_texto("[20:12] ", underline=True, color="red")))
    codigo, saida = _executar(["--json", "editar-bloco", "b1", "[20:15]"], client=client)
    assert codigo == 2
    erro = saida["erro"]
    assert erro["codigo"] == "perda_de_formatacao"
    assert "--trocar" in erro["mensagem"]
    assert "--aceitar-perda-de-formatacao" in erro["mensagem"]
    assert client.patches() == []

    codigo, _ = _executar(
        ["--json", "editar-bloco", "b1", "[20:15]", "--aceitar-perda-de-formatacao"],
        client=client,
    )
    assert codigo == 0
    assert len(client.patches()) == 1


def test_editar_bloco_trocar_preserva_formatacao_e_mencao():
    mencao = {
        "type": "mention",
        "mention": {"type": "page", "page": {"id": "pg-x"}},
        "plain_text": "Página X",
        "href": "https://www.notion.so/pgx",
        "annotations": _texto("")["annotations"],
    }
    client = FakeEdicaoClient(
        _heading(_texto("[20:12] ", underline=True, color="red"), mencao, _texto(" fim", bold=True))
    )
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "--trocar", "20:12", "--por", "20:15"], client=client
    )

    assert codigo == 0
    enviado = client.patches()[0]["heading_3"]["rich_text"]
    assert enviado[0]["text"]["content"] == "[20:15] "
    assert enviado[0]["annotations"]["underline"] is True
    assert enviado[0]["annotations"]["color"] == "red"
    assert enviado[1]["type"] == "mention"
    assert enviado[1]["mention"]["page"]["id"] == "pg-x"
    assert enviado[2]["annotations"]["bold"] is True
    assert saida["dados"]["ocorrencias"] == 1
    assert saida["dados"]["tipo"] == "heading_3"


def test_editar_bloco_trocar_ambiguo_sugere_todas():
    client = FakeEdicaoClient(_heading(_texto("a e a")))
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "--trocar", "a", "--por", "b"], client=client
    )
    assert codigo == 2
    assert saida["erro"]["codigo"] == "trecho_ambiguo"
    assert "--todas" in saida["erro"]["mensagem"]

    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "--trocar", "a", "--por", "b", "--todas"],
        client=client,
    )
    assert codigo == 0
    assert saida["dados"]["ocorrencias"] == 2


def test_editar_bloco_lote_json_reusa_o_cliente_e_continua_depois_de_erro(tmp_path, capsys):
    arquivo = tmp_path / "edicoes.json"
    arquivo.write_text(
        json.dumps(
            {
                "itens": [
                    {"block_id": "b1", "conteudo": "título novo"},
                    {"block_id": "b2", "conteudo": "linha 1\n\nlinha 2"},
                    {"block_id": "b3", "trocar": "velho", "por": "novo"},
                    {"conteudo": "sem id"},
                ]
            }
        ),
        encoding="utf-8",
    )
    client = FakeEdicaoClient(_heading(_texto("texto velho")))
    fabricas = 0

    def fabrica():
        nonlocal fabricas
        fabricas += 1
        return client

    codigo, saida = cli.executar(
        ["--json", "editar-bloco", "--arquivo", str(arquivo), "--progresso-a-cada", "2"],
        client_factory=fabrica,
    )

    assert codigo == 0
    dados = saida["dados"]
    assert dados["modo"] == "lote"
    assert dados["comando"] == "editar-bloco"
    assert (dados["total"], dados["sucessos"], dados["erros"]) == (4, 2, 2)
    assert [r["estado"] for r in dados["resultados"]] == ["sucesso", "erro", "sucesso", "erro"]
    assert dados["resultados"][1]["erro"]["codigo"] == "edicao_multibloco"
    assert dados["resultados"][2]["dados"]["ocorrencias"] == 1
    assert fabricas == 1
    assert [c[1][0] for c in client.chamadas if c[0] == "atualizar_bloco"] == ["b1", "b3"]
    assert "[lote] 2/4" in capsys.readouterr().err


def test_editar_bloco_lote_csv(tmp_path):
    arquivo = tmp_path / "edicoes.csv"
    arquivo.write_text(
        "block_id,conteudo,trocar,por,todas\n"
        "b1,texto novo,,,\n"
        "b2,,x,y,sim\n",
        encoding="utf-8",
    )
    client = FakeEdicaoClient(_heading(_texto("x e x")))
    codigo, saida = _executar(["--json", "editar-bloco", "--arquivo", str(arquivo)], client=client)

    assert codigo == 0
    assert saida["dados"]["sucessos"] == 2
    assert saida["dados"]["resultados"][1]["dados"]["ocorrencias"] == 2


def test_editar_bloco_lote_nao_mistura_com_edicao_individual(tmp_path):
    arquivo = tmp_path / "edicoes.json"
    arquivo.write_text('[{"block_id": "b1", "conteudo": "x"}]', encoding="utf-8")
    client = FakeEdicaoClient(_heading(_texto("a")))
    codigo, saida = _executar(
        ["--json", "editar-bloco", "b1", "--arquivo", str(arquivo)], client=client
    )
    assert codigo == 2
    assert "--arquivo" in saida["erro"]["mensagem"]
    assert client.chamadas == []


def test_editar_bloco_combinacoes_invalidas_sao_recusadas_antes_da_api():
    for argumentos in (
        ["editar-bloco", "b1", "texto", "--trocar", "a", "--por", "b"],
        ["editar-bloco", "b1", "--trocar", "a"],
        ["editar-bloco", "b1", "--por", "b"],
        ["editar-bloco", "b1", "texto", "--todas"],
        ["editar-bloco", "b1"],
    ):
        client = FakeEdicaoClient(_heading(_texto("a")))
        codigo, saida = _executar(["--json", *argumentos], client=client)
        assert codigo == 2, argumentos
        assert client.chamadas == [], argumentos


def test_apagar_bloco_sem_sim_nao_apaga():
    client = FakeClient()
    codigo, saida = _executar(["--json", "apagar-bloco", "b1"], client=client)
    assert codigo == 2
    assert saida["ok"] is False
    assert not any(c[0] == "excluir_bloco" for c in client.chamadas)


def test_apagar_bloco_com_sim_apaga():
    client = FakeClient()
    codigo, saida = _executar(["--json", "apagar-bloco", "b1", "--sim"], client=client)
    assert codigo == 0
    assert saida["dados"]["apagado"] is True
    assert ("excluir_bloco", "b1") in client.chamadas


def test_apagar_bloco_diz_o_que_apagou_e_como_desfazer():
    """A resposta era igual para um parágrafo e para uma página inteira."""

    codigo, saida = _executar(["--json", "apagar-bloco", "b1", "--sim"], client=FakeClient())
    assert codigo == 0
    dados = saida["dados"]
    assert dados["id"] == "b1"
    assert dados["tipo"] == "paragraph"
    assert dados["resumo"] == "texto de b1"
    assert dados["tem_filhos"] is False
    assert dados["desfazer"] == "notion-tasks restaurar-bloco b1"


def test_apagar_bloco_de_subpagina_sem_forcar_nao_apaga():
    """Medido: apagar o ID de uma subpágina mandou 11 subpáginas e 2 databases à lixeira."""

    client = FakeClient()
    codigo, saida = _executar(["--json", "apagar-bloco", "sub1", "--sim"], client=client)

    assert codigo == 2
    erro = saida["erro"]
    assert erro["codigo"] == "exclusao_arriscada"
    assert erro["detalhes"] == {"tipo": "child_page", "titulo": "Sandbox inteira"}
    assert "--forcar-tipos-arriscados" in erro["mensagem"]
    assert not any(c[0] == "excluir_bloco" for c in client.chamadas)


def test_apagar_bloco_de_subpagina_com_forcar_apaga():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "apagar-bloco", "sub1", "--sim", "--forcar-tipos-arriscados"], client=client
    )
    assert codigo == 0
    assert saida["dados"]["tipo"] == "child_page"
    assert saida["dados"]["resumo"] == "Sandbox inteira"
    assert ("excluir_bloco", "sub1") in client.chamadas
    # Medido: PATCH /blocks não restaura página (HTTP 400 "Updating a page via the
    # blocks endpoint unsupported"); não se sugere um desfazer que falha.
    assert "desfazer" not in saida["dados"]
    assert saida["dados"]["desfazer_manual"]["ids"] == ["sub1"]
    assert "Lixeira" in saida["dados"]["desfazer_manual"]["como"]


def test_limpar_apagar_tudo_separa_o_desfazer_de_blocos_e_de_paginas():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "sub9", "type": "child_page", "child_page": {"title": "X"}},
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}},
    ]
    codigo, saida = _executar(
        ["--json", "limpar", "page1", "--sim", "--apagar-tudo"], client=client
    )
    assert codigo == 0
    dados = saida["dados"]
    assert dados["blocos_apagados"] == 2
    assert dados["desfazer"] == "notion-tasks restaurar-bloco b1"
    assert dados["desfazer_manual"]["ids"] == ["sub9"]


def test_apagar_varios_blocos_continua_depois_de_um_erro():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "apagar-bloco", "b1", "sub1", "b3", "b1", "--sim"], client=client
    )

    assert codigo == 0
    dados = saida["dados"]
    assert dados["modo"] == "lote"
    assert dados["comando"] == "apagar-bloco"
    # O ID repetido é processado uma vez só.
    assert dados["total"] == 3
    assert dados["sucessos"] == 2
    assert dados["erros"] == 1
    assert [r["block_id"] for r in dados["resultados"]] == ["b1", "sub1", "b3"]
    assert dados["resultados"][1]["erro"]["codigo"] == "exclusao_arriscada"
    assert dados["desfazer"] == "notion-tasks restaurar-bloco b1 b3"
    assert [c[1] for c in client.chamadas if c[0] == "excluir_bloco"] == ["b1", "b3"]


def test_blocos_lista_ids_para_editar_ou_apagar():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "b1", "type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "T"}]}},
        {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "corpo"}]}},
    ]
    codigo, saida = _executar(["--json", "blocos", "page1"], client=client)
    assert codigo == 0
    ids = [b["id"] for b in saida["dados"]["blocos"]]
    assert ids == ["b1", "b2"]
    assert saida["dados"]["blocos"][0]["preview"] == "# T"


def _paragrafo(bloco_id, texto, **extras):
    return {
        "id": bloco_id,
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": texto}]},
        **extras,
    }


class FakeArvoreClient(FakeClient):
    """Página com um item de lista que tem filho, e blocos com carimbos da API."""

    ARVORE = {
        "page1": [
            _paragrafo(
                "b1",
                "Relatório " + "x" * 150,
                created_time="2026-09-25T23:36:00.000Z",
                last_edited_time="2026-09-25T23:40:00.000Z",
                created_by={"object": "user", "id": "u1"},
                last_edited_by={"object": "user", "id": "u2"},
                has_children=False,
                in_trash=False,
            ),
            {
                "id": "b2",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "pai"}]},
                "has_children": True,
            },
        ],
        "b2": [
            {
                "id": "b3",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"plain_text": "filho com Trilha"}]},
            }
        ],
    }

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler_blocos", block_id))
        return [dict(bloco) for bloco in self.ARVORE.get(block_id, [])]

    def obter_bloco(self, block_id):
        self.chamadas.append(("obter_bloco", block_id))
        if block_id == "b2":
            return {
                **self.ARVORE["page1"][1],
                "parent": {"type": "page_id", "page_id": "page1"},
                "last_edited_time": "2026-09-25T23:41:00.000Z",
            }
        return {
            "id": block_id,
            "type": "child_page",
            "child_page": {"title": "Subpágina"},
            "has_children": True,
            "parent": {"type": "page_id", "page_id": "page1"},
        }


def test_blocos_sem_flags_mantem_o_formato_de_sempre():
    codigo, saida = _executar(["--json", "blocos", "page1"], client=FakeArvoreClient())
    assert codigo == 0
    assert set(saida["dados"]["blocos"][0]) == {"id", "tipo", "preview"}


def test_blocos_metadados_traz_os_carimbos_que_a_api_ja_devolve():
    codigo, saida = _executar(
        ["--json", "blocos", "page1", "--metadados"], client=FakeArvoreClient()
    )
    assert codigo == 0
    primeiro = saida["dados"]["blocos"][0]
    assert primeiro["criado_em"] == "2026-09-25T23:36:00.000Z"
    assert primeiro["editado_em"] == "2026-09-25T23:40:00.000Z"
    assert primeiro["criado_por"] == "u1"
    assert primeiro["editado_por"] == "u2"
    assert primeiro["tem_filhos"] is False
    assert primeiro["na_lixeira"] is False
    assert saida["dados"]["blocos"][1]["tem_filhos"] is True


def test_blocos_completo_traz_o_texto_inteiro_alem_do_preview():
    codigo, saida = _executar(
        ["--json", "blocos", "page1", "--completo"], client=FakeArvoreClient()
    )
    assert codigo == 0
    primeiro = saida["dados"]["blocos"][0]
    assert len(primeiro["preview"]) == 100
    assert primeiro["markdown"] == "Relatório " + "x" * 150


def test_blocos_recursivo_lista_os_filhos_com_nivel_e_pai():
    codigo, saida = _executar(
        ["--json", "blocos", "page1", "--recursivo"], client=FakeArvoreClient()
    )
    assert codigo == 0
    blocos = saida["dados"]["blocos"]
    assert [(b["id"], b["nivel"], b["pai_id"]) for b in blocos] == [
        ("b1", 0, "page1"),
        ("b2", 0, "page1"),
        ("b3", 1, "b2"),
    ]


def test_blocos_contendo_acha_o_id_pelo_texto():
    codigo, saida = _executar(
        ["--json", "blocos", "page1", "--recursivo", "--contendo", "trilha"],
        client=FakeArvoreClient(),
    )
    assert codigo == 0
    assert [b["id"] for b in saida["dados"]["blocos"]] == ["b3"]


def test_blocos_recursivo_indenta_a_saida_humana():
    codigo, saida = _executar(["blocos", "page1", "--recursivo"], client=FakeArvoreClient())
    assert codigo == 0
    assert "  - filho com Trilha" in saida


def test_ler_bloco_devolve_o_markdown_com_os_filhos_e_o_pai():
    client = FakeArvoreClient()
    codigo, saida = _executar(["--json", "ler-bloco", "b2"], client=client)
    assert codigo == 0
    dados = saida["dados"]
    assert dados["tipo"] == "bulleted_list_item"
    assert dados["markdown"] == "- pai\n  - filho com Trilha"
    assert dados["pai"] == {"tipo": "page_id", "id": "page1"}
    assert dados["editado_em"] == "2026-09-25T23:41:00.000Z"
    assert ("obter_bloco", "b2") in client.chamadas


def test_ler_bloco_de_subpagina_aponta_para_conteudo():
    codigo, saida = _executar(["--json", "ler-bloco", "sub1"], client=FakeArvoreClient())
    assert codigo == 0
    assert saida["dados"]["tipo"] == "child_page"
    assert "conteudo sub1" in saida["dados"]["aviso"]


def test_escrever_substituir_limpa_antes():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "velho", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "lixo"}]}}
    ]
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "novo", "--substituir"], client=client
    )
    assert codigo == 0
    assert saida["dados"]["substituiu"] is True
    assert ("excluir_bloco", "velho") in client.chamadas
    assert any(c[0] == "anexar_blocos" for c in client.chamadas)


def test_limpar_sem_sim_nao_apaga():
    client = FakeClient()
    codigo, saida = _executar(["--json", "limpar", "page1"], client=client)
    assert codigo == 2
    assert saida["ok"] is False
    assert not any(c[0] == "excluir_bloco" for c in client.chamadas)


def test_limpar_com_sim_apaga_o_corpo():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}},
        {"id": "b2", "type": "paragraph", "paragraph": {"rich_text": []}},
    ]
    codigo, saida = _executar(["--json", "limpar", "page1", "--sim"], client=client)
    assert codigo == 0
    assert saida["dados"]["blocos_apagados"] == 2
    assert ("excluir_bloco", "b1") in client.chamadas
    assert ("excluir_bloco", "b2") in client.chamadas


def test_limpar_devolve_os_ids_apagados_e_como_desfazer():
    """Sem os IDs não há como restaurar: a API restaura pelo ID do bloco."""

    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}},
        {"id": "b2", "type": "heading_2", "heading_2": {"rich_text": []}},
    ]
    codigo, saida = _executar(["--json", "limpar", "page1", "--sim"], client=client)

    assert codigo == 0
    dados = saida["dados"]
    # A contagem continua int (contrato antigo); os IDs vêm numa chave nova.
    assert dados["blocos_apagados"] == 2
    assert dados["blocos_apagados_ids"] == [
        {"id": "b1", "tipo": "paragraph"},
        {"id": "b2", "tipo": "heading_2"},
    ]
    assert dados["desfazer"] == "notion-tasks restaurar-bloco b1 b2"


def test_limpar_diz_por_que_preservou_cada_bloco():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "t1", "type": "callout", "callout": {"rich_text": []}},
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}},
    ]
    codigo, saida = _executar(["--json", "limpar", "page1", "--sim"], client=client)

    assert codigo == 0
    preservado = saida["dados"]["blocos_preservados"][0]
    assert preservado["id"] == "t1"
    assert preservado["tipo"] == "callout"
    assert "duplicado" in preservado["motivo"]
    assert ("excluir_bloco", "t1") not in client.chamadas


def test_escrever_substituir_devolve_os_ids_apagados():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "velho", "type": "paragraph", "paragraph": {"rich_text": []}}
    ]
    codigo, saida = _executar(
        ["--json", "escrever", "page1", "novo", "--substituir"], client=client
    )

    assert codigo == 0
    assert saida["dados"]["blocos_apagados"] == 1
    assert saida["dados"]["blocos_apagados_ids"] == [{"id": "velho", "tipo": "paragraph"}]


def test_limpar_que_para_no_meio_diz_o_que_apagou_e_como_desfazer():
    """Erro persistente no 2º DELETE: antes, traceback sem dizer o que já foi apagado."""

    from felixo_notion_mcp import NotionHTTPError

    class ClienteQueFalhaNoSegundo(FakeClient):
        def ler_blocos(self, *args, **kwargs):
            return [
                {"id": f"b{n}", "type": "paragraph", "paragraph": {"rich_text": []}}
                for n in (1, 2, 3)
            ]

        def excluir_bloco(self, block_id):
            if block_id == "b2":
                raise NotionHTTPError(409, '{"code": "conflict_error", "message": "x"}')
            return super().excluir_bloco(block_id)

    codigo, saida = _executar(
        ["--json", "limpar", "page1", "--sim"], client=ClienteQueFalhaNoSegundo()
    )

    assert codigo == 1
    erro = saida["erro"]
    assert erro["codigo"] == "limpeza_incompleta"
    assert erro["http_status"] == 409
    assert erro["detalhes"]["blocos_apagados_ids"] == [{"id": "b1", "tipo": "paragraph"}]
    assert erro["detalhes"]["pendentes"] == [
        {"id": "b2", "tipo": "paragraph"},
        {"id": "b3", "tipo": "paragraph"},
    ]
    assert erro["proximo_passo"] == "notion-tasks restaurar-bloco b1"


def test_restaurar_bloco_tira_da_lixeira_varios_ids():
    client = FakeClient()
    codigo, saida = _executar(
        ["--json", "restaurar-bloco", "b1", "b2"], client=client
    )

    assert codigo == 0
    assert saida["dados"]["restaurados"] == ["b1", "b2"]
    assert saida["dados"]["falhas"] == []
    assert "fim" in saida["dados"]["aviso"].lower()
    assert ("restaurar_bloco", "b1") in client.chamadas
    assert ("restaurar_bloco", "b2") in client.chamadas


def test_restaurar_bloco_que_falha_em_todos_sai_com_erro():
    from felixo_notion_mcp import NotionHTTPError

    class ClienteSemLixeira(FakeClient):
        def restaurar_bloco(self, block_id):
            raise NotionHTTPError(404, "não encontrado")

    codigo, saida = _executar(
        ["--json", "restaurar-bloco", "b1"], client=ClienteSemLixeira()
    )

    assert codigo == 1
    assert saida["ok"] is False
    assert "b1" in saida["erro"]["mensagem"]


def test_buscar_normaliza_itens():
    client = FakeClient()
    codigo, saida = _executar(["--json", "buscar", "x"], client=client)
    assert codigo == 0
    ids = {item["id"] for item in saida["dados"]}
    assert ids == {"p1", "db1"}


def test_database_atual_traz_titulo_real():
    client = FakeClient()
    with mock.patch.dict(cli.os.environ, {"NOTION_DATABASE_ID": "db1"}, clear=False):
        codigo, saida = _executar(["--json", "database-atual"], client=client)

    assert codigo == 0
    assert saida["dados"] == {
        "database_id": "db1",
        "titulo": "Tarefas",
        "url": "https://notion.so/db1",
        "data_sources": ["Tarefas"],
    }


def test_conteudo_de_database_avisa_e_traz_linhas():
    codigo, saida = _executar(
        ["--json", "conteudo", "db1"], client=FakeDatabaseClient()
    )
    assert codigo == 0
    dados = saida["dados"]
    assert dados["tipo"] == "database"
    assert "database" in dados["aviso"].lower()
    assert dados["linhas"][0]["titulo"] == "Linha 1"


def test_conteudo_de_pagina_sem_corpo_nao_inventa_linhas():
    client = FakeClient()
    # ler_blocos do FakeClient devolve um parágrafo; força vazio aqui.
    client.ler_blocos = lambda *a, **k: []
    codigo, saida = _executar(["--json", "conteudo", "page1"], client=client)
    assert codigo == 0
    # Página = propriedades + corpo: mesmo sem corpo, as propriedades
    # preenchidas vêm no resultado (e vêm primeiro).
    assert saida["dados"] == {
        "id": "page1",
        "tipo": "pagina",
        "propriedades": {"Status": "Inbox"},
        "markdown": "",
    }


class FakeLinhaClient(FakeClient):
    def obter_pagina(self, page_id):
        pagina = super().obter_pagina(page_id)
        pagina.update(
            parent={"type": "database_id", "database_id": "db9"},
            url="https://www.notion.so/linha-page1",
            created_time="2026-09-20T10:00:00.000Z",
            last_edited_time="2026-09-25T23:00:00.000Z",
        )
        return pagina


def test_conteudo_diz_o_database_da_linha_e_quando_mudou():
    """Sem o pai, o agente não sabia em qual database rodar 'schema'."""

    codigo, saida = _executar(["--json", "conteudo", "page1"], client=FakeLinhaClient())
    assert codigo == 0
    dados = saida["dados"]
    assert dados["pai"] == {"tipo": "database_id", "id": "db9"}
    assert dados["url"] == "https://www.notion.so/linha-page1"
    assert dados["editado_em"] == "2026-09-25T23:00:00.000Z"

    codigo, texto = _executar(["conteudo", "page1"], client=FakeLinhaClient())
    assert codigo == 0
    assert texto.splitlines()[0] == "Linha do database db9 (schema: 'schema db9')"
    assert "Editada em: 2026-09-25T23:00:00.000Z" in texto


def test_conteudo_traz_propriedades_antes_do_corpo():
    codigo, saida = _executar(["conteudo", "page1"])
    assert codigo == 0
    assert saida.index("Propriedades") < saida.index("Corpo")
    assert "Status: Inbox" in saida


def test_exemplo_devolve_amostra_completa_do_database_atual():
    client = FakeExemploClient()
    with mock.patch.dict(cli.os.environ, {"NOTION_DATABASE_ID": "db1"}, clear=False):
        codigo, saida = _executar(["--json", "exemplo", "--n", "2"], client=client)

    assert codigo == 0
    dados = saida["dados"]
    assert dados["database_id"] == "db1"
    assert dados["quantidade_solicitada"] == 2
    assert dados["quantidade_retornada"] == 2
    assert dados["total_linhas"] == 3
    assert [exemplo["id"] for exemplo in dados["exemplos"]] == ["r1", "r2"]
    assert dados["exemplos"][0]["titulo"] == "Primeira linha"
    assert dados["exemplos"][0]["propriedades"] == {
        "Nome": "Primeira linha",
        "Status": "Entrada",
    }
    assert dados["exemplos"][0]["markdown"] == "Corpo de r1"
    assert ("obter_pagina", "r1") in client.chamadas
    assert ("ler_blocos", "r1") in client.chamadas


def test_exemplo_rejeita_quantidade_fora_do_intervalo():
    codigo, saida = _executar(["--json", "exemplo", "--n", "5"])

    assert codigo == 2
    assert saida["ok"] is False
    assert saida["erro"]["codigo"] == "validacao"
    assert saida["erro"]["mensagem"] == "'--n' deve estar entre 2 e 4."


def test_linhas_lista_linhas_do_database():
    codigo, saida = _executar(["--json", "linhas", "db1"], client=FakeDatabaseClient())
    assert codigo == 0
    assert saida["dados"]["linhas"][0]["id"] == "r1"
    assert "propriedades" not in saida["dados"]["linhas"][0]


def test_linhas_completo_traz_propriedades_normalizadas():
    codigo, saida = _executar(
        ["--json", "linhas", "db1", "--completo"], client=FakeDatabaseClient()
    )
    assert codigo == 0
    assert saida["dados"]["linhas"][0]["propriedades"] == {"Name": "Linha 1"}


def test_guia_lista_todos_os_comandos():
    codigo, saida = _executar(["--json", "guia"])
    assert codigo == 0
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    # Cobre tarefas, conteúdo e o próprio guia — reflete o parser.
    assert {"listar", "conteudo", "exemplo", "linhas", "apagar-bloco", "guia"} <= comandos
    # Cada comando traz ao menos um exemplo.
    assert all(c["exemplos"] for c in saida["dados"]["comandos"])


def test_guia_documenta_lote_de_criar_e_editar_linha():
    codigo, saida = _executar(["--json", "guia"])
    assert codigo == 0
    exemplos = {item["comando"]: item["exemplos"] for item in saida["dados"]["comandos"]}
    assert any("--arquivo" in exemplo for exemplo in exemplos["criar"])
    assert any("--arquivo" in exemplo for exemplo in exemplos["editar-linha"])


def test_guia_recomenda_propriedades_antes_do_conteudo():
    codigo, saida = _executar(["--json", "guia"])
    assert codigo == 0
    fluxo = " ".join(saida["dados"]["fluxo_recomendado"]).lower()
    assert "editar-linha" in fluxo and "escrever" in fluxo
    # A ordem recomendada: propriedades (editar-linha) antes do conteúdo (escrever).
    assert fluxo.index("editar-linha") < fluxo.index("escrever")
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    assert "editar-linha" in comandos


def test_guia_humano_mostra_fluxo_recomendado():
    codigo, saida = _executar(["guia"])
    assert codigo == 0
    assert "editar-linha" in saida and "propriedades" in saida.lower()


def test_guia_humano_tem_dica_de_uso():
    codigo, saida = _executar(["guia"])
    assert codigo == 0
    assert "--json" in saida


def test_guia_inclui_clonar_database():
    codigo, saida = _executar(["--json", "guia"])
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    assert "clonar-database" in comandos


def test_clonar_database_cria_clone_e_aplica_schema():
    codigo, saida = _executar(["--json", "clonar-database", "db1"], client=FakeCloneClient())
    assert codigo == 0
    dados = saida["dados"]
    assert dados["id"] == "db_clone"
    assert dados["titulo"] == "Origem (cópia)"
    assert dados["linhas_copiadas"] == 0


def test_clonar_database_com_titulo_e_com_linhas():
    cli_fake = FakeCloneClient()
    codigo, saida = _executar(
        ["--json", "clonar-database", "db1", "--titulo", "Clone X", "--com-linhas"],
        client=cli_fake,
    )
    assert codigo == 0
    assert saida["dados"]["titulo"] == "Clone X"
    assert ("criar_database", ("pagina_pai", "Clone X")) in cli_fake.chamadas


def test_clonar_database_humano_resume():
    codigo, saida = _executar(["clonar-database", "db1"], client=FakeCloneClient())
    assert codigo == 0
    assert "Clone criado" in saida


class FakeEstruturaClient(FakeClient):
    """Cliente que sustenta o fluxo de estrutura de projeto (subpáginas/databases)."""

    def __init__(self) -> None:
        super().__init__()
        self.blocos_por_pagina: dict[str, list[dict]] = {}

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        self.chamadas.append(("ler_blocos", block_id))
        return self.blocos_por_pagina.get(block_id, [])

    def criar_database(self, pagina_id, titulo, propriedades, **kwargs):
        self.chamadas.append(("criar_database", (pagina_id, titulo)))
        return {"id": f"db-{titulo}"}


def test_guia_inclui_comandos_de_estrutura():
    codigo, saida = _executar(["--json", "guia"])
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    assert {
        "criar-subpagina",
        "inspecionar-estrutura",
        "clonar-estrutura",
        "montar-estrutura-projeto",
    } <= comandos


def test_criar_subpagina_cria_pagina_filha():
    cliente = FakeEstruturaClient()
    codigo, saida = _executar(
        ["--json", "criar-subpagina", "pagina_pai", "Estado atual"], client=cliente
    )
    assert codigo == 0
    assert saida["dados"]["titulo"] == "Estado atual"
    assert ("criar_subpagina", ("pagina_pai", "Estado atual")) in cliente.chamadas


def test_inspecionar_estrutura_le_arvore_recursiva():
    cliente = FakeEstruturaClient()
    cliente.blocos_por_pagina["raiz"] = [
        {"id": "p1", "type": "child_page", "child_page": {"title": "README"}}
    ]
    cliente.blocos_por_pagina["p1"] = []

    codigo, saida = _executar(["--json", "inspecionar-estrutura", "raiz"], client=cliente)

    assert codigo == 0
    filhos = saida["dados"]["filhos"]
    assert filhos[0]["titulo"] == "README"


def test_clonar_estrutura_recria_subpaginas_no_destino():
    cliente = FakeEstruturaClient()
    cliente.blocos_por_pagina["ref"] = [
        {"id": "p1", "type": "child_page", "child_page": {"title": "Estado atual"}}
    ]

    codigo, saida = _executar(
        ["--json", "clonar-estrutura", "ref", "destino"], client=cliente
    )

    assert codigo == 0
    assert saida["dados"]["subpaginas_criadas"] == ["Estado atual"]
    assert ("criar_subpagina", ("destino", "Estado atual")) in cliente.chamadas


def test_montar_estrutura_projeto_cria_padrao_completo():
    cliente = FakeEstruturaClient()

    codigo, saida = _executar(
        ["--json", "montar-estrutura-projeto", "pagina"], client=cliente
    )

    assert codigo == 0
    assert len(saida["dados"]["subpaginas_criadas"]) == 4
    assert len(saida["dados"]["databases_criados"]) == 2


class FakeReordenacaoClient(FakeClient):
    """Cliente que sustenta o fluxo de ``reordenar-bloco``."""

    def __init__(self, blocos: list[dict]) -> None:
        super().__init__()
        self._blocos = blocos

    def ler_blocos(self, block_id, page_size=100, buscar_todos=False, recursivo=False):
        return self._blocos

    def excluir_bloco(self, block_id):
        self.chamadas.append(("excluir_bloco", block_id))
        return {"id": block_id, "archived": True}

    def anexar_blocos(self, block_id, blocos, *, apos_bloco_id=None):
        self.chamadas.append(("anexar_blocos", (block_id, apos_bloco_id)))
        return {"results": [{"id": "novo-id", **blocos[0]}]}


def test_reordenar_bloco_move_paragrafo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bloco = {"id": "p1", "type": "paragraph", "paragraph": {"rich_text": []}}
    cliente = FakeReordenacaoClient([bloco])

    codigo, saida = _executar(
        ["--json", "reordenar-bloco", "pagina", "p1", "--apos", "p2"], client=cliente
    )

    assert codigo == 0
    assert saida["dados"]["bloco_id_novo"] == "novo-id"
    assert ("excluir_bloco", "p1") in cliente.chamadas


def test_reordenar_bloco_rejeita_child_page_sem_forcar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bloco = {"id": "cp1", "type": "child_page", "child_page": {"title": "Estado atual"}}
    cliente = FakeReordenacaoClient([bloco])

    codigo, saida = _executar(
        ["--json", "reordenar-bloco", "pagina", "cp1", "--inicio"], client=cliente
    )

    assert codigo != 0
    assert not any(c[0] == "excluir_bloco" for c in cliente.chamadas)


def test_reordenar_bloco_rejeita_child_database_mesmo_com_forcar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bloco = {"id": "db1", "type": "child_database", "child_database": {"title": "Docs"}}
    cliente = FakeReordenacaoClient([bloco])

    codigo, saida = _executar(
        [
            "--json",
            "reordenar-bloco",
            "pagina",
            "db1",
            "--inicio",
            "--forcar-tipos-arriscados",
        ],
        client=cliente,
    )

    assert codigo != 0
    assert not any(c[0] == "excluir_bloco" for c in cliente.chamadas)


def test_reordenar_bloco_nao_grava_backup_no_diretorio_corrente(tmp_path, monkeypatch):
    """O backup (texto do workspace) caía em ./.notion-backups e ia parar no git."""

    monkeypatch.chdir(tmp_path)
    cliente = FakeReordenacaoClient([{"id": "p1", "type": "paragraph", "paragraph": {}}])

    codigo, saida = _executar(
        ["--json", "reordenar-bloco", "pagina", "p1", "--apos", "p2"], client=cliente
    )

    assert codigo == 0
    assert not (tmp_path / ".notion-backups").exists()
    assert Path(saida["dados"]["backup_path"]).is_absolute()


def test_reordenar_bloco_dir_backup_escolhe_a_pasta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pasta = tmp_path / "meus-backups"
    cliente = FakeReordenacaoClient([{"id": "p1", "type": "paragraph", "paragraph": {}}])

    codigo, saida = _executar(
        [
            "--json",
            "reordenar-bloco",
            "pagina",
            "p1",
            "--apos",
            "p2",
            "--dir-backup",
            str(pasta),
        ],
        client=cliente,
    )

    assert codigo == 0
    backup = Path(saida["dados"]["backup_path"])
    assert backup.parent == pasta.resolve()
    assert json.loads(backup.read_text(encoding="utf-8"))["id"] == "p1"


def test_reordenar_bloco_exige_exatamente_um_alvo():
    cliente = FakeReordenacaoClient([{"id": "p1", "type": "paragraph", "paragraph": {}}])
    codigo, saida = _executar(["--json", "reordenar-bloco", "pagina", "p1"], client=cliente)
    assert codigo != 0


# -- atualizar-github ------------------------------------------------------


class _ResumoFake:
    repos_encontrados = 3
    paginas_criadas = 1
    paginas_atualizadas = 2
    paginas_puladas = 0
    readmes_escritos = 1
    readmes_atualizados = 1
    erros: list[str] = []


def test_atualizar_github_passa_contas_e_database(monkeypatch):
    capturado = {}

    def fake_atualizar(contas, database_id, **kwargs):
        capturado["contas"] = contas
        capturado["database_id"] = database_id
        capturado["sincronizar_readme"] = kwargs["sincronizar_readme"]
        return _ResumoFake()

    monkeypatch.setattr(cli.svc_inventario, "atualizar_repos", fake_atualizar)
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: object())

    codigo, saida = _executar(
        ["--json", "atualizar-github", "--contas", "conta-a,conta-b", "--database", "db1"]
    )
    assert codigo == 0
    assert capturado["contas"] == ["conta-a", "conta-b"]
    assert capturado["database_id"] == "db1"
    assert capturado["sincronizar_readme"] is True
    assert saida["dados"]["paginas_atualizadas"] == 2


def test_atualizar_github_sem_readme(monkeypatch):
    capturado = {}
    monkeypatch.setattr(
        cli.svc_inventario,
        "atualizar_repos",
        lambda c, d, **k: capturado.update(k) or _ResumoFake(),
    )
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: object())
    codigo, _ = _executar(
        ["--json", "atualizar-github", "--contas", "x", "--database", "db1", "--sem-readme"]
    )
    assert codigo == 0
    assert capturado["sincronizar_readme"] is False
    # Sem a flag, arquivados entram normalmente.
    assert capturado["ignorar_arquivados"] is False


def test_atualizar_github_sem_arquivados(monkeypatch):
    capturado = {}
    monkeypatch.setattr(
        cli.svc_inventario,
        "atualizar_repos",
        lambda c, d, **k: capturado.update(k) or _ResumoFake(),
    )
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: object())
    codigo, _ = _executar(
        ["--json", "atualizar-github", "--contas", "x", "--database", "db1", "--sem-arquivados"]
    )
    assert codigo == 0
    assert capturado["ignorar_arquivados"] is True


def test_atualizar_github_apenas_mudancas(monkeypatch):
    capturado = {}
    monkeypatch.setattr(
        cli.svc_inventario,
        "atualizar_repos",
        lambda c, d, **k: capturado.update(k) or _ResumoFake(),
    )
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: object())
    codigo, _ = _executar(
        ["--json", "atualizar-github", "--contas", "x", "--database", "db1", "--apenas-mudancas"]
    )
    assert codigo == 0
    assert capturado["apenas_mudancas"] is True


def test_atualizar_github_exige_contas(monkeypatch):
    monkeypatch.delenv("GITHUB_CONTAS", raising=False)
    codigo, saida = _executar(["--json", "atualizar-github", "--database", "db1"])
    assert codigo == 2
    assert saida["ok"] is False


def test_atualizar_github_humano_resume(monkeypatch):
    monkeypatch.setattr(cli.svc_inventario, "atualizar_repos", lambda c, d, **k: _ResumoFake())
    monkeypatch.setattr(cli, "GitHubClient", lambda *a, **k: object())
    codigo, saida = _executar(["atualizar-github", "--contas", "x", "--database", "db1"])
    assert codigo == 0
    assert "Repos: 3" in saida


# -- exportar-docx ---------------------------------------------------------


def test_exportar_docx_passa_periodo_database_e_saida(monkeypatch, tmp_path: Path):
    capturado = {}

    def fake_exportar(**kwargs):
        capturado.update(kwargs)
        return {
            "database_id": kwargs["database_id"],
            "periodo": {"de": kwargs["data_inicio"], "ate": kwargs["data_fim"]},
            "campo_data": kwargs["campo_data"],
            "saida": str(kwargs["saida"]),
            "total": 1,
            "arquivos": [],
        }

    monkeypatch.setattr(cli.svc_relatorios_docx, "exportar_relatorios_docx", fake_exportar)

    codigo, saida = _executar(
        [
            "--json",
            "exportar-docx",
            "--database",
            "db-relatorios",
            "--de",
            "2026-07-01",
            "--ate",
            "2026-07-06",
            "--saida",
            str(tmp_path),
        ]
    )

    assert codigo == 0
    assert saida["dados"]["total"] == 1
    assert capturado["database_id"] == "db-relatorios"
    assert capturado["data_inicio"] == "2026-07-01"
    assert capturado["data_fim"] == "2026-07-06"
    assert capturado["campo_data"] == "Data"


def test_exportar_docx_usa_env_especifico_antes_do_database_padrao(monkeypatch, tmp_path: Path):
    capturado = {}
    monkeypatch.setenv("NOTION_REPORTS_DATABASE_ID", "db-relatorios")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db-tarefas")
    monkeypatch.setattr(
        cli.svc_relatorios_docx,
        "exportar_relatorios_docx",
        lambda **kwargs: capturado.update(kwargs)
        or {
            "database_id": kwargs["database_id"],
            "periodo": {"de": kwargs["data_inicio"], "ate": kwargs["data_fim"]},
            "saida": str(kwargs["saida"]),
            "total": 0,
            "arquivos": [],
        },
    )

    codigo, _ = _executar(
        [
            "--json",
            "exportar-docx",
            "--de",
            "2026-07-01",
            "--ate",
            "2026-07-06",
            "--saida",
            str(tmp_path),
        ]
    )

    assert codigo == 0
    assert capturado["database_id"] == "db-relatorios"


def test_exportar_docx_humano_resume(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cli.svc_relatorios_docx,
        "exportar_relatorios_docx",
        lambda **kwargs: {
            "database_id": "db1",
            "periodo": {"de": "2026-07-01", "ate": "2026-07-06"},
            "saida": str(tmp_path),
            "total": 2,
            "arquivos": [],
        },
    )

    codigo, saida = _executar(
        [
            "exportar-docx",
            "--database",
            "db1",
            "--de",
            "2026-07-01",
            "--ate",
            "2026-07-06",
            "--saida",
            str(tmp_path),
        ]
    )

    assert codigo == 0
    assert "DOCX exportados: 2" in saida


# -- criar-database / importar-planilha / anexar-arquivo / mover ------------


class FakeNovosClient:
    def __init__(self):
        self.chamadas: list[tuple[str, object]] = []
        self.pagina = {"properties": {}}

    def criar_database(self, pagina_id, titulo, propriedades, **kwargs):
        self.chamadas.append(("criar_database", (pagina_id, titulo, propriedades, kwargs)))
        return {"id": "db_novo", "url": "https://notion.so/db_novo"}

    def mover_pagina(self, page_id, novo_pai_id, *, tipo_pai="page_id"):
        self.chamadas.append(("mover_pagina", (page_id, novo_pai_id, tipo_pai)))
        return {"id": page_id}

    def mover_database(self, database_id, novo_pai_id):
        self.chamadas.append(("mover_database", (database_id, novo_pai_id)))
        return {"id": database_id}

    def renomear_database(self, database_id, novo_titulo):
        self.chamadas.append(("renomear_database", (database_id, novo_titulo)))
        return {"id": database_id}

    def enviar_arquivo(self, conteudo, nome, content_type):
        self.chamadas.append(("enviar_arquivo", (nome, content_type)))
        return "upload-1"

    def obter_pagina(self, page_id):
        return self.pagina

    def atualizar_pagina(self, page_id, props):
        self.chamadas.append(("atualizar_pagina", (page_id, props)))
        return {"id": page_id}

    def consultar_database(self, database_id, page_size=1, filtro=None):
        return []

    def criar_pagina(self, database_id, props):
        self.chamadas.append(("criar_pagina", (database_id, props)))
        return {"id": "linha-nova"}


def test_criar_database_monta_schema_e_atalhos():
    fake = FakeNovosClient()
    codigo, saida = _executar(
        [
            "--json",
            "criar-database",
            "pag1",
            "Cadastro",
            "--prop",
            "Seguidores=numero",
            "--prop",
            "Plataforma=select",
            "--prefixo-id",
            "DVIP",
            "--inline",
        ],
        client=fake,
    )
    assert codigo == 0
    assert saida["dados"]["id"] == "db_novo"
    nome, (pagina, titulo, props, kwargs) = fake.chamadas[0]
    assert props["Seguidores"] == {"number": {}}
    assert props["Nome"] == {"title": {}}  # título automático
    assert kwargs["prefixo_id"] == "DVIP"
    assert kwargs["is_inline"] is True


def test_criar_database_tipo_invalido_da_erro_de_uso():
    codigo, saida = _executar(
        ["--json", "criar-database", "pag1", "X", "--prop", "Valor=moeda"],
        client=FakeNovosClient(),
    )
    assert codigo == 2
    assert "Tipos aceitos" in str(saida["erro"])


def test_importar_planilha_csv_upsert(tmp_path):
    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome,Seguidores\nConta A,1.614\n", encoding="utf-8")
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha), "--tipo", "Seguidores=numero"],
        client=fake,
    )
    assert codigo == 0
    assert saida["dados"]["criados"] == 1
    props = [c for c in fake.chamadas if c[0] == "criar_pagina"][0][1][1]
    assert props["Seguidores"] == {"number": 1614}


def test_importar_planilha_dry_run_nao_grava_nada(tmp_path):
    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome,Seguidores\nConta A,1.614\n", encoding="utf-8")
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha), "--dry-run"], client=fake
    )
    assert codigo == 0
    assert saida["dados"]["simulado"] is True
    assert saida["dados"]["criados"] == 1
    assert saida["dados"]["conflitos"] == []
    assert not any(c[0] in ("criar_pagina", "atualizar_pagina") for c in fake.chamadas)


def test_importar_planilha_chave_identifica_o_registro_pela_coluna(tmp_path):
    """Sem chave, a Origem é a posição da linha: reordenar a planilha trocava registros."""

    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome,Email\nAna,ana@x.com\n", encoding="utf-8")
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha), "--chave", "Email"], client=fake
    )
    assert codigo == 0
    props = [c for c in fake.chamadas if c[0] == "criar_pagina"][0][1][1]
    origem = "".join(item["text"]["content"] for item in props["Origem"]["rich_text"])
    assert origem.endswith("#Email=ana@x.com")


def test_importar_planilha_chave_inexistente_nao_grava(tmp_path):
    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome\nAna\n", encoding="utf-8")
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha), "--chave", "Email"], client=fake
    )
    assert codigo == 2
    assert "Email" in saida["erro"]["mensagem"]
    assert not any(c[0] == "criar_pagina" for c in fake.chamadas)


def test_importar_planilha_relata_motivo_das_falhas(tmp_path):
    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome,Seguidores\nConta A,1.614\n", encoding="utf-8")

    class FakeQueRejeita(FakeNovosClient):
        def criar_pagina(self, database_id, props):
            raise RuntimeError("Nome is not a property that exists")

    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha)],
        client=FakeQueRejeita(),
    )
    assert codigo == 0
    assert saida["dados"]["erros"] == 1
    assert saida["dados"]["falhas"] == [
        "Conta A (contas.csv:2): Nome is not a property that exists"
    ]


def test_importar_planilha_aceita_resultado_de_starter_anterior(tmp_path, monkeypatch):
    planilha = tmp_path / "contas.csv"
    planilha.write_text("Nome\nConta A\n", encoding="utf-8")

    class ResultadoLegado:
        criados = 1
        atualizados = 0
        erros = 0
        itens_processados = 1

    monkeypatch.setattr(cli.svc_ingestao, "ingerir", lambda *args, **kwargs: ResultadoLegado())

    codigo, saida = _executar(
        ["--json", "importar-planilha", "db1", str(planilha)],
        client=FakeNovosClient(),
    )

    assert codigo == 0
    assert saida["dados"]["falhas"] == []


def test_anexar_arquivo_sobe_e_grava_propriedade(tmp_path):
    arquivo = tmp_path / "rel.docx"
    arquivo.write_bytes(b"x")
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "anexar-arquivo", "pag1", str(arquivo)], client=fake
    )
    assert codigo == 0
    assert saida["dados"]["upload_id"] == "upload-1"
    atualizacao = [c for c in fake.chamadas if c[0] == "atualizar_pagina"][0]
    assert "Arquivos e mídia" in atualizacao[1][1]


def test_mover_database_reparenteia():
    fake = FakeNovosClient()
    codigo, saida = _executar(["--json", "mover-database", "db1", "pai2"], client=fake)
    assert codigo == 0
    assert ("mover_database", ("db1", "pai2")) in fake.chamadas


def test_renomear_database_troca_titulo():
    fake = FakeNovosClient()
    codigo, saida = _executar(
        ["--json", "renomear-database", "db1", "banco de ideias"], client=fake
    )
    assert codigo == 0
    assert ("renomear_database", ("db1", "banco de ideias")) in fake.chamadas
    assert saida["dados"]["titulo"] == "banco de ideias"


def test_renomear_database_titulo_vazio_falha():
    fake = FakeNovosClient()
    codigo, _ = _executar(["--json", "renomear-database", "db1", "   "], client=fake)
    assert codigo != 0
    assert not any(c[0] == "renomear_database" for c in fake.chamadas)


def test_guia_inclui_comandos_novos():
    codigo, saida = _executar(["--json", "guia"])
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    assert {
        "criar-database",
        "importar-planilha",
        "anexar-arquivo",
        "mover-pagina",
        "mover-database",
        "renomear-database",
    } <= comandos


class FakeSchemaClient(FakeClient):
    """Cliente que sustenta o fluxo de ``garantir-coluna``."""

    def __init__(self, propriedades: dict, *, com_data_source: bool = True) -> None:
        super().__init__()
        self._propriedades = dict(propriedades)
        self._com_data_source = com_data_source

    def listar_data_sources(self, database_id):
        self.chamadas.append(("listar_data_sources", database_id))
        return [{"id": "ds1"}] if self._com_data_source else []

    def get_data_source(self, data_source_id):
        return {"properties": self._propriedades}

    def atualizar_data_source(self, data_source_id, *, propriedades):
        self.chamadas.append(("atualizar_data_source", (data_source_id, propriedades)))
        self._propriedades.update(propriedades)

    def get_database(self, database_id):
        return {"properties": self._propriedades}

    def atualizar_database(self, database_id, *, propriedades):
        self.chamadas.append(("atualizar_database", (database_id, propriedades)))
        self._propriedades.update(propriedades)


def test_guia_inclui_garantir_coluna():
    codigo, saida = _executar(["--json", "guia"])
    comandos = {c["comando"] for c in saida["dados"]["comandos"]}
    assert "garantir-coluna" in comandos


def test_garantir_coluna_adiciona_select():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})

    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Idioma", "select"], client=cliente
    )

    assert codigo == 0
    assert saida["dados"]["criada"] is True
    assert ("atualizar_data_source", ("ds1", {"Idioma": {"select": {}}})) in cliente.chamadas


def test_garantir_coluna_texto_e_numero():
    cliente_texto = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Resumo", "texto"], client=cliente_texto
    )
    assert codigo == 0
    assert (
        "atualizar_data_source",
        ("ds1", {"Resumo": {"rich_text": {}}}),
    ) in cliente_texto.chamadas

    cliente_numero = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Peso", "numero"], client=cliente_numero
    )
    assert codigo == 0
    assert (
        "atualizar_data_source",
        ("ds1", {"Peso": {"number": {}}}),
    ) in cliente_numero.chamadas


def test_garantir_coluna_nao_mexe_quando_ja_existe():
    cliente = FakeSchemaClient(
        {"Nome": {"type": "title", "title": {}}, "Idioma": {"type": "select", "select": {}}}
    )

    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Idioma", "select"], client=cliente
    )

    assert codigo == 0
    assert saida["dados"]["criada"] is False
    assert not any(c[0] == "atualizar_data_source" for c in cliente.chamadas)


def test_garantir_coluna_relacao_usa_data_source_do_alvo():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})

    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Projeto", "relacao", "--relacionar-com", "db-alvo"],
        client=cliente,
    )

    assert codigo == 0
    assert saida["dados"]["criada"] is True
    assert (
        "atualizar_data_source",
        (
            "ds1",
            {
                "Projeto": {
                    "relation": {
                        "type": "dual_property",
                        "dual_property": {},
                        "data_source_id": "ds1",
                    }
                }
            },
        ),
    ) in cliente.chamadas


def test_garantir_coluna_relacao_sem_data_source_usa_database_id():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}}, com_data_source=False)

    codigo, _ = _executar(
        ["--json", "garantir-coluna", "db1", "Projeto", "relacao", "--relacionar-com", "db-alvo"],
        client=cliente,
    )

    assert codigo == 0
    assert (
        "atualizar_database",
        (
            "db1",
            {
                "Projeto": {
                    "relation": {
                        "database_id": "db-alvo",
                        "type": "dual_property",
                        "dual_property": {},
                    }
                }
            },
        ),
    ) in cliente.chamadas


def test_garantir_coluna_relacao_sem_alvo_falha():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, _ = _executar(
        ["--json", "garantir-coluna", "db1", "Projeto", "relacao"], client=cliente
    )
    assert codigo != 0


def test_garantir_coluna_alvo_em_tipo_nao_relacional_falha():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, _ = _executar(
        ["--json", "garantir-coluna", "db1", "Idioma", "select", "--relacionar-com", "db-alvo"],
        client=cliente,
    )
    assert codigo != 0


def test_garantir_coluna_tipo_invalido():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Idioma", "tipo-que-nao-existe"], client=cliente
    )
    assert codigo != 0


# -- Mensagem de erro do Notion --------------------------------------------
#
# Todo erro que não fosse 404 virava "Falha ao falar com o Notion." e o corpo do
# 400 — o único lugar que nomeia a propriedade recusada — era descartado.


class ClienteQueRecusa(FakeClient):
    """Cliente que responde como a API real quando a propriedade está errada."""

    def __init__(self, status: int, corpo: str) -> None:
        super().__init__()
        self._status = status
        self._corpo = corpo

    def buscar(self, **kwargs):
        from felixo_notion_mcp import NotionHTTPError

        raise NotionHTTPError(self._status, self._corpo)


def test_erro_400_do_notion_chega_com_a_mensagem_da_api():
    corpo = (
        '{"object": "error", "status": 400, "code": "validation_error", '
        '"message": "Etapa is expected to be select."}'
    )
    codigo, saida = _executar(
        ["--json", "buscar", "x"], client=ClienteQueRecusa(400, corpo)
    )
    assert codigo == 1
    mensagem = saida["erro"]["mensagem"]
    assert "HTTP 400" in mensagem
    assert "Etapa is expected to be select." in mensagem
    assert "validation_error" in mensagem


def test_erro_404_continua_com_a_mensagem_curta():
    codigo, saida = _executar(
        ["--json", "buscar", "x"], client=ClienteQueRecusa(404, "não encontrado")
    )
    assert codigo == 1
    assert saida["erro"]["mensagem"] == "Recurso não encontrado."


def test_erro_sem_json_no_corpo_devolve_o_texto_cru():
    codigo, saida = _executar(
        ["--json", "buscar", "x"], client=ClienteQueRecusa(502, "<html>bad gateway</html>")
    )
    assert codigo == 1
    assert "bad gateway" in saida["erro"]["mensagem"]


def test_coluna_inexistente_vira_erro_de_uso_com_caminho():
    """Schema errado não pode virar traceback: é erro de uso, com exit 2."""

    from felixo_notion_mcp import NotionSchemaError

    class TaskListSemAreas(FakeTaskList):
        def listar(self, *args, **kwargs):
            raise NotionSchemaError(faltando=["Áreas da vida"])

    codigo, saida = _executar(["--json", "listar", "--area", "a1"], fake=TaskListSemAreas())
    assert codigo == 2
    mensagem = saida["erro"]["mensagem"]
    assert "Áreas da vida" in mensagem
    assert "schema <database_id>" in mensagem


def test_erro_404_nomeia_o_perfil_ativo(tmp_path: Path):
    """REGRA 8 em código: "ID válido devolvendo 404 quase nunca é permissão —
    é o perfil salvo apontando pra outro workspace, e ele vence o
    NOTION_TOKEN em silêncio" deixou de ser só uma frase de prosa que o
    agente lembrava (ou não) de seguir. Confirmar a suspeita custava outra
    chamada (`perfis listar`); agora o nome do perfil já vem junto do 404.
    """
    arquivo = tmp_path / "perfis.json"
    cli.perfis_workspace.adicionar_perfil(
        alias="relatorios", token="ntn_" + "a" * 20, ativar=True, caminho=arquivo
    )
    with mock.patch.object(cli.perfis_workspace, "ARQUIVO_PADRAO", arquivo):
        codigo, saida = _executar(
            ["--json", "buscar", "x"], client=ClienteQueRecusa(404, "não encontrado")
        )

    assert codigo == 1
    mensagem = saida["erro"]["mensagem"]
    assert mensagem.startswith("Recurso não encontrado.")
    assert "'relatorios'" in mensagem
    assert "perfis listar" in mensagem


def test_erro_404_traz_codigo_status_e_code_do_notion():
    """O agente decide pelo código, não pelo texto em português."""

    corpo = '{"object": "error", "status": 404, "code": "object_not_found", "message": "x"}'
    codigo, saida = _executar(["--json", "buscar", "x"], client=ClienteQueRecusa(404, corpo))

    assert codigo == 1
    erro = saida["erro"]
    assert erro["codigo"] == "nao_encontrado"
    assert erro["http_status"] == 404
    assert erro["notion_code"] == "object_not_found"
    assert erro["proximo_passo"] == "notion-tasks perfis listar"


def test_argumento_invalido_com_json_vira_envelope():
    """Antes o argparse imprimia o uso no stderr e saía sem JSON."""

    codigo, saida = _executar(["--json", "reordenar-bloco"])

    assert codigo == 2
    assert saida["ok"] is False
    assert saida["erro"]["codigo"] == "uso_invalido"
    assert "bloco_id" in saida["erro"]["mensagem"]


def test_argumento_invalido_sem_json_mantem_o_argparse():
    import pytest

    with pytest.raises(SystemExit) as saida:
        _executar(["reordenar-bloco"])
    assert saida.value.code == 2


def test_excecao_inesperada_vira_erro_interno_sem_quebrar_o_json(capsys):
    class ClienteQueQuebra(FakeClient):
        def buscar(self, *args, **kwargs):
            raise KeyError("campo_inesperado")

    codigo, saida = _executar(["--json", "buscar", "x"], client=ClienteQueQuebra())

    assert codigo == 1
    assert saida["erro"]["codigo"] == "erro_interno"
    assert saida["erro"]["detalhes"] == {"tipo": "KeyError"}
    # O diagnóstico não se perde: o traceback vai para o stderr.
    assert "KeyError" in capsys.readouterr().err


def test_escrita_parcial_vira_envelope_json_com_o_que_ficou():
    """EscritaParcialError (RuntimeError) escapava do executar como traceback."""

    from felixo_notion_mcp import NotionHTTPError

    class ClienteQueRecusaAnexar(FakeClient):
        def anexar_blocos(self, block_id, blocos, **posicao):
            raise NotionHTTPError(
                400,
                '{"object": "error", "status": 400, "code": "validation_error", '
                '"message": "body failed validation"}',
            )

    codigo, saida = _executar(
        ["--json", "escrever", "page1", "texto novo", "--substituir"],
        client=ClienteQueRecusaAnexar(),
    )

    assert codigo == 1
    erro = saida["erro"]
    assert erro["codigo"] == "escrita_parcial"
    assert erro["http_status"] == 400
    assert erro["notion_code"] == "validation_error"
    assert erro["detalhes"]["substituicao"] is True
    assert erro["detalhes"]["blocos_criados"] == []
    assert "body failed validation" in erro["mensagem"]


def test_escrita_salva_pelo_notion_nao_parece_recusa():
    """503 com a escrita salva: o texto "Notion recusou" levava a repetir e duplicar."""

    from felixo_notion_mcp.core.exceptions import NotionEscritaSalvaError

    corpo = (
        '{"object": "error", "status": 503, "code": "service_unavailable", '
        '"message": "The change was saved", "additional_data": '
        '{"committed_resource_id": "sub-nova", "retry_guidance": "Do not repeat the write."}}'
    )

    class ClienteSalvaSemResponder(FakeClient):
        def criar_subpagina(self, pagina_pai_id, titulo, *, blocos=None):
            raise NotionEscritaSalvaError(503, corpo)

    codigo, saida = _executar(
        ["--json", "criar-subpagina", "pai", "Nova"], client=ClienteSalvaSemResponder()
    )

    assert codigo == 1
    erro = saida["erro"]
    assert erro["codigo"] == "escrita_salva"
    assert not erro["mensagem"].startswith("Notion recusou")
    assert "NÃO repita" in erro["mensagem"]
    assert erro["detalhes"]["recurso_id"] == "sub-nova"


def test_escrita_abaixo_de_database_mantem_a_lista_no_topo_e_em_detalhes():
    client = FakeClient()
    client.ler_blocos = lambda *a, **k: [
        {"id": "db9", "type": "child_database", "child_database": {"title": "Tarefas"}}
    ]
    codigo, saida = _executar(["--json", "escrever", "page1", "texto"], client=client)

    assert codigo == 2
    assert saida["erro"]["codigo"] == "escrita_abaixo_de_database"
    esperado = [{"id": "db9", "titulo": "Tarefas"}]
    assert saida["databases_dentro"] == esperado
    assert saida["erro"]["detalhes"]["databases_dentro"] == esperado
    assert saida["erro"]["proximo_passo"] == "notion-tasks linhas db9"


def test_erro_404_sem_perfil_ativo_mantem_a_mensagem_curta():
    """Sem perfil configurado (autouse `perfis_isolados` garante isso por
    padrão), a mensagem antiga continua exatamente igual — nada de sufixo
    vazio nem pontuação sobrando.
    """
    codigo, saida = _executar(
        ["--json", "buscar", "x"], client=ClienteQueRecusa(404, "não encontrado")
    )
    assert codigo == 1
    assert saida["erro"]["mensagem"] == "Recurso não encontrado."


class ClienteRelatorioDiario(FakeClient):
    """Database de relatórios diários em memória — título, Data e Resumo."""

    def __init__(self, paginas: list[dict] | None = None) -> None:
        super().__init__()
        self.paginas_relatorio = paginas or []
        self.criadas: list[tuple[str, dict]] = []
        self._sequencia = 0

    def get_database(self, database_id):
        return {
            "properties": {
                "Relatório": {"type": "title"},
                "Data": {"type": "date"},
                "Resumo": {"type": "rich_text"},
                "O que fiz": {"type": "rich_text"},
                "Status": {"type": "status", "status": {"options": [], "groups": []}},
                "Área": {"type": "select", "select": {"options": []}},
            }
        }

    def consultar_database(self, database_id, buscar_todos=False, **kwargs):
        return self.paginas_relatorio

    def criar_pagina(self, database_id, propriedades):
        self._sequencia += 1
        page_id = f"relatorio-{self._sequencia}"
        self.criadas.append((page_id, propriedades))
        return {"id": page_id, "url": f"https://notion.so/{page_id}"}

    def atualizar_pagina(self, page_id, propriedades):
        return {"id": page_id}


def test_relatorio_do_dia_exige_corpo_a_menos_que_permitido():
    codigo, saida = _executar(
        ["--json", "relatorio-do-dia", "--database", "db1", "--resumo", "oi"]
    )
    assert codigo == 2
    assert "--corpo está vazio" in saida["erro"]["mensagem"]
    assert "--permitir-corpo-vazio" in saida["erro"]["mensagem"]


def test_relatorio_do_dia_escreve_corpo_e_resumo_curto(monkeypatch):
    chamadas_escrita: list[tuple[str, str]] = []

    def falso_escrever(page_id, markdown, *, substituir=False, cliente=None):
        chamadas_escrita.append((page_id, markdown))
        return markdown.count("\n") + 1

    monkeypatch.setattr(cli.svc_relatorios, "escrever_conteudo", falso_escrever)

    cliente = ClienteRelatorioDiario()
    codigo, saida = _executar(
        [
            "--json",
            "relatorio-do-dia",
            "--database",
            "db1",
            "--data",
            "2026-09-09",
            "--resumo",
            "Corrigi o bug do relatório indo pra propriedade em vez do corpo.",
            "--corpo",
            "# Relato completo\n\nParágrafo bem mais longo do que caberia numa coluna.",
        ],
        client=cliente,
    )

    assert codigo == 0
    assert saida["dados"]["acao"] == "criada"
    assert "avisos" not in saida["dados"]
    assert len(chamadas_escrita) == 1
    assert chamadas_escrita[0][1].startswith("# Relato completo")
    (page_id, propriedades) = cliente.criadas[0]
    assert "Resumo" in propriedades
    # O relato longo foi para o corpo (via escrever_conteudo), não duplicado
    # na propriedade.
    assert "Parágrafo bem mais longo" not in json.dumps(propriedades)


def test_relatorio_do_dia_avisa_quando_propriedade_vira_relato(monkeypatch):
    monkeypatch.setattr(
        cli.svc_relatorios, "escrever_conteudo", lambda *a, **k: 1
    )
    texto_grande = "x" * 500

    codigo, saida = _executar(
        [
            "--json",
            "relatorio-do-dia",
            "--database",
            "db1",
            "--o-que-fiz",
            texto_grande,
            "--corpo",
            "corpo normal",
        ],
        client=ClienteRelatorioDiario(),
    )

    assert codigo == 0
    avisos = saida["dados"]["avisos"]
    assert len(avisos) == 1
    assert "--o-que-fiz" in avisos[0]
    assert "500 caracteres" in avisos[0]


def test_relatorio_do_dia_permite_corpo_vazio_quando_pedido(monkeypatch):
    monkeypatch.setattr(
        cli.svc_relatorios, "escrever_conteudo", lambda *a, **k: 0
    )
    codigo, saida = _executar(
        [
            "--json",
            "relatorio-do-dia",
            "--database",
            "db1",
            "--resumo",
            "Nada a registrar hoje.",
            "--permitir-corpo-vazio",
        ],
        client=ClienteRelatorioDiario(),
    )
    assert codigo == 0
    assert saida["dados"]["blocos_escritos"] == 0


def test_abrir_a_cli_nao_carrega_python_docx():
    """python-docx + lxml eram ~20-29% da abertura de TODO comando.

    O notion-starter passou a importar o docx só dentro de ``renderizar_docx``;
    este teste guarda a borda: importar a CLI (o que todo comando faz) não pode
    trazer o docx de volta. Roda num processo novo, porque a suíte já pode ter
    carregado o módulo.
    """

    import os
    import subprocess
    import sys

    # ``tests/api/cli/<este arquivo>``: a raiz do repositório está três pastas acima.
    raiz = Path(__file__).resolve().parents[3]
    # O processo novo não herda o ``pythonpath`` do pytest; ``src`` entra pelo ambiente.
    ambiente = {
        **os.environ,
        "PYTHONPATH": str(raiz / "src"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    codigo = (
        "import sys; import felixo_notion_mcp.api.cli.notion_tasks; "
        "carregados = [m for m in ('docx', 'lxml') if m in sys.modules]; "
        "print(','.join(carregados))"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=True,
    )
    assert resultado.stdout.strip() == ""


def test_exportar_docx_continua_carregando_o_servico_real():
    assert cli.svc_relatorios_docx.__name__ == "felixo_notion_mcp.services.relatorios_docx"
    assert callable(cli.svc_relatorios_docx.exportar_relatorios_docx)


class FakeAparenciaClient:
    def __init__(self, pagina=None):
        self.pagina = pagina or {"icon": None, "cover": None}
        self.chamadas = []

    def obter_pagina(self, page_id):
        return self.pagina

    def atualizar_aparencia(self, page_id, *, icone=None, capa=None):
        self.chamadas.append((page_id, icone, capa))
        return {"id": page_id}


def test_aparencia_grava_icone_e_capa():
    fake = FakeAparenciaClient()
    codigo, saida = _executar(
        ["--json", "aparencia", "p1", "--icone", "📘", "--capa", "https://x/capa.jpg"],
        client=fake,
    )
    assert codigo == 0
    assert fake.chamadas == [
        (
            "p1",
            {"type": "emoji", "emoji": "📘"},
            {"type": "external", "external": {"url": "https://x/capa.jpg"}},
        )
    ]
    assert saida["dados"]["icone"] == saida["dados"]["capa"] == "gravado"


def test_aparencia_mantem_o_que_existe_sem_substituir():
    fake = FakeAparenciaClient({"icon": {"type": "emoji", "emoji": "🎧"}, "cover": None})
    codigo, saida = _executar(["--json", "aparencia", "p1", "--icone", "📘"], client=fake)
    assert codigo == 0
    assert fake.chamadas == []
    assert saida["dados"]["icone"] == "mantido"


def test_aparencia_capa_com_emoji_e_erro_de_uso():
    codigo, saida = _executar(
        ["--json", "aparencia", "p1", "--capa", "📘"], client=FakeAparenciaClient()
    )
    assert codigo != 0
    assert saida["ok"] is False


def test_garantir_coluna_multi_select_ja_nasce_com_as_opcoes():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Tags", "multi_select",
         "--opcoes", "rails,llms", "--opcoes", "llms,linux"],
        client=cliente,
    )
    assert codigo == 0
    assert saida["dados"]["criada"] is True
    opcoes = {"options": [{"name": "rails"}, {"name": "llms"}, {"name": "linux"}]}
    esperado = ("atualizar_data_source", ("ds1", {"Tags": {"multi_select": opcoes}}))
    assert esperado in cliente.chamadas


def test_garantir_coluna_recusa_opcoes_em_tipo_sem_opcoes():
    cliente = FakeSchemaClient({"Nome": {"type": "title", "title": {}}})
    codigo, saida = _executar(
        ["--json", "garantir-coluna", "db1", "Resumo", "texto", "--opcoes", "a"], client=cliente
    )
    assert codigo != 0
    assert "--opcoes" in saida["erro"]["mensagem"]
