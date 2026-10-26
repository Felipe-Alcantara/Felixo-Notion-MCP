"""Testes do servidor MCP (``felixo_notion_mcp.api.mcp.server``).

Cada ferramenta e testada com o Notion mockado via ``responses`` — sem token
nem rede real.  A ``TaskList`` e injetada diretamente, seguindo o mesmo padrao
de DI dos testes de ``services.tarefas``.

Tambem verifica que as anotacoes MCP (``read_only_hint``, ``open_world_hint``;
no fio, ``readOnlyHint`` e ``openWorldHint``) estao corretas, garantindo que o
Felixo-AI-Core receba os sinais certos sobre quais ferramentas requerem
confirmacao.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest import mock

import pytest
import responses
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from felixo_notion_mcp import NotionClient, NotionConfigurationError, TaskList
from felixo_notion_mcp.api.mcp.server import (
    _criar_tasklist,
    _resolver_transporte,
    _tarefa_dict,
    append_content,
    clone_database,
    conclude_task,
    create_database,
    create_task,
    delete_block,
    edit_block,
    import_spreadsheet,
    list_database_rows,
    list_tasks,
    main,
    mcp,
    move_database,
    move_page,
    move_status,
    read_page_content,
    search,
    update_github_inventory,
    update_project_page,
    upload_file,
)
from felixo_notion_mcp.core.constants import NOTION_BASE_URL

TOKEN = "ntn_test_token"
DB = "db_mcp_test"


def _tasklist() -> TaskList:
    return TaskList(NotionClient(token=TOKEN), DB)


def _pagina(id_: str, nome: str, status: str | None = None, prazo: str | None = None):
    props: dict = {"Tarefa": {"type": "title", "title": [{"plain_text": nome}]}}
    if status is not None:
        props["Etapa"] = {"type": "status", "status": {"name": status}}
    if prazo is not None:
        props["Prazo"] = {"type": "date", "date": {"start": prazo}}
    return {"id": id_, "url": f"https://notion.so/{id_}", "properties": props}


def _schema_tarefas():
    """Schema mínimo que a criação real consulta antes do POST."""

    return {
        "properties": {
            "Tarefa": {"type": "title", "title": {}},
            "Etapa": {"type": "status", "status": {"options": []}},
            "Prazo": {"type": "date", "date": {}},
        }
    }


# ---------------------------------------------------------------------------
# Anotacoes MCP
# ---------------------------------------------------------------------------


class TestAnotacoesMCP:
    """Verifica que as ferramentas declaram as anotacoes certas."""

    def _tools(self):
        return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    def test_list_tasks_e_read_only(self):
        ann = self._tools()["notion.list_tasks"].annotations
        assert ann.read_only_hint is True
        assert ann.destructive_hint is False
        assert ann.open_world_hint is True

    def test_create_task_e_write(self):
        ann = self._tools()["notion.create_task"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is False
        assert ann.open_world_hint is True

    def test_move_status_e_write(self):
        ann = self._tools()["notion.move_status"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is True
        assert ann.open_world_hint is True

    def test_conclude_task_e_write(self):
        ann = self._tools()["notion.conclude_task"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is True
        assert ann.open_world_hint is True

    def test_update_project_page_e_write(self):
        ann = self._tools()["notion.update_project_page"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is True
        assert ann.open_world_hint is True

    def test_search_e_read_only(self):
        ann = self._tools()["notion.search"].annotations
        assert ann.read_only_hint is True
        assert ann.destructive_hint is False

    def test_read_page_content_e_read_only(self):
        ann = self._tools()["notion.read_page_content"].annotations
        assert ann.read_only_hint is True
        assert ann.destructive_hint is False

    def test_list_database_rows_e_read_only(self):
        ann = self._tools()["notion.list_database_rows"].annotations
        assert ann.read_only_hint is True
        assert ann.destructive_hint is False

    def test_append_content_e_write(self):
        ann = self._tools()["notion.append_content"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is False

    def test_edit_block_e_write(self):
        ann = self._tools()["notion.edit_block"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False
        assert ann.idempotent_hint is True

    def test_delete_block_e_destrutivo(self):
        ann = self._tools()["notion.delete_block"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is True
        assert ann.open_world_hint is True

    def test_clone_database_e_write_nao_destrutivo(self):
        ann = self._tools()["notion.clone_database"].annotations
        assert ann.read_only_hint is False
        assert ann.destructive_hint is False

    def test_superficie_publica_tem_namespace_notion(self):
        assert set(self._tools()) == {
            "notion.list_tasks",
            "notion.create_task",
            "notion.move_status",
            "notion.conclude_task",
            "notion.update_project_page",
            "notion.update_github_inventory",
            "notion.search",
            "notion.read_page_content",
            "notion.append_content",
            "notion.edit_block",
            "notion.delete_block",
            "notion.list_database_rows",
            "notion.clone_database",
            "notion.create_database",
            "notion.import_spreadsheet",
            "notion.upload_file",
            "notion.move_page",
            "notion.move_database",
            "notion.set_page_appearance",
            "notion.discover_articles",
            "notion.extract_article",
            "notion.translate_markdown",
            "notion.article_to_pdf",
            "notion.generate_cover",
            "notion.import_articles",
            "notion.sort_view",
            "notion.ensure_daily_log_day",
            "notion.carry_over_daily_log",
            "notion.estimate_daily_log",
            "notion.import_tasks",
        }

    def test_novas_ferramentas_de_escrita_nao_sao_destrutivas(self):
        tools = self._tools()
        for nome in (
            "notion.create_database",
            "notion.import_spreadsheet",
            "notion.upload_file",
            "notion.move_page",
            "notion.move_database",
        ):
            ann = tools[nome].annotations
            assert ann.read_only_hint is False, nome
            assert ann.destructive_hint is False, nome
        # mover e re-parent: repetir preserva o mesmo efeito
        assert tools["notion.move_page"].annotations.idempotent_hint is True
        assert tools["notion.move_database"].annotations.idempotent_hint is True


# ---------------------------------------------------------------------------
# Serializacao
# ---------------------------------------------------------------------------


class TestSerializacao:
    """Verifica o helper ``_tarefa_dict``."""

    def test_tarefa_para_dict_campos_corretos(self):
        from felixo_notion_mcp import Tarefa

        t = Tarefa(
            id="abc",
            nome="Teste",
            status="Inbox",
            prazo="2026-07-01",
            url="https://notion.so/abc",
            bruto={},
        )
        d = _tarefa_dict(t)
        assert d == {
            "id": "abc",
            "nome": "Teste",
            "status": "Inbox",
            "prazo": "2026-07-01",
            "url": "https://notion.so/abc",
        }

    def test_tarefa_para_dict_sem_bruto(self):
        from felixo_notion_mcp import Tarefa

        t = Tarefa(id="x", nome="N", status=None, prazo=None, url="u", bruto={"segredo": 42})
        d = _tarefa_dict(t)
        assert "bruto" not in d
        assert "segredo" not in d


# ---------------------------------------------------------------------------
# _criar_tasklist
# ---------------------------------------------------------------------------


class TestCriarTasklist:
    """Verifica que ``_criar_tasklist`` exige as variaveis de ambiente."""

    def test_erro_sem_token(self):
        ambiente = {"NOTION_TOKEN": "", "NOTION_DATABASE_ID": "db"}
        with (
            mock.patch.dict(os.environ, ambiente, clear=False),
            pytest.raises(NotionConfigurationError, match="NOTION_TOKEN"),
        ):
            _criar_tasklist()

    def test_erro_sem_database_id(self):
        ambiente = {"NOTION_TOKEN": "ntn_x", "NOTION_DATABASE_ID": ""}
        with (
            mock.patch.dict(os.environ, ambiente, clear=False),
            pytest.raises(NotionConfigurationError, match="NOTION_DATABASE_ID"),
        ):
            _criar_tasklist()

    def test_cria_tasklist_com_env_ok(self):
        ambiente = {"NOTION_TOKEN": TOKEN, "NOTION_DATABASE_ID": DB}
        with mock.patch.dict(os.environ, ambiente, clear=False):
            tl = _criar_tasklist()
            assert tl is not None


# ---------------------------------------------------------------------------
# Validacao da borda MCP
# ---------------------------------------------------------------------------


class TestValidacao:
    """Entradas invalidas falham antes de tocar no Notion."""

    def test_create_task_exige_nome(self):
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_tasklist") as criar_tasklist,
            pytest.raises(ValueError, match="nome"),
        ):
            create_task(nome="   ")
        criar_tasklist.assert_not_called()

    def test_move_status_exige_task_id(self):
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_tasklist") as criar_tasklist,
            pytest.raises(ValueError, match="task_id"),
        ):
            move_status(task_id="", status="Fazendo")
        criar_tasklist.assert_not_called()

    def test_move_status_exige_status(self):
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_tasklist") as criar_tasklist,
            pytest.raises(ValueError, match="status"),
        ):
            move_status(task_id="t1", status=" ")
        criar_tasklist.assert_not_called()

    def test_erro_de_configuracao_e_sanitizado_na_ferramenta(self):
        erro = NotionConfigurationError("token-interno-nao-deve-vazar")
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_tasklist", side_effect=erro),
            pytest.raises(RuntimeError, match="nao configurado") as exc_info,
        ):
            list_tasks()
        assert "token-interno" not in str(exc_info.value)

    def test_update_project_page_rejeita_contagem_negativa(self):
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_notion_client") as criar_cliente,
            pytest.raises(ValueError, match="estrelas"),
        ):
            update_project_page(
                page_id="projeto-1",
                nome_completo="felipe/projeto",
                estrelas=-1,
            )
        criar_cliente.assert_not_called()


# ---------------------------------------------------------------------------
# Ferramentas MCP (funcoes puras, Notion mockado)
# ---------------------------------------------------------------------------


class TestListTasks:
    """Testes da ferramenta ``list_tasks``."""

    @responses.activate
    def test_lista_todas_as_tarefas(self):
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/databases/{DB}/query",
            json={
                "results": [_pagina("t1", "A", "Inbox"), _pagina("t2", "B", "Fazendo")],
                "has_more": False,
            },
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = list_tasks()
        assert len(resultado) == 2
        assert resultado[0]["nome"] == "A"
        assert resultado[1]["nome"] == "B"

    @responses.activate
    def test_filtra_por_status(self):
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/databases/{DB}/query",
            json={"results": [_pagina("t1", "A", "Inbox")], "has_more": False},
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = list_tasks(status="Inbox")
        corpo = json.loads(responses.calls[0].request.body)
        assert corpo["filter"]["status"]["equals"] == "Inbox"
        assert len(resultado) == 1

    @responses.activate
    def test_lista_vazia(self):
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/databases/{DB}/query",
            json={"results": [], "has_more": False},
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = list_tasks()
        assert resultado == []


class TestCreateTask:
    """Testes da ferramenta ``create_task``."""

    @responses.activate
    def test_cria_tarefa_simples(self):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/{DB}",
            json=_schema_tarefas(),
            status=200,
        )
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/pages",
            json=_pagina("novo", "Estudar IA", "Inbox"),
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = create_task(nome="Estudar IA")
        assert resultado["id"] == "novo"
        assert resultado["nome"] == "Estudar IA"

    @responses.activate
    def test_cria_tarefa_com_status_e_prazo(self):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/{DB}",
            json=_schema_tarefas(),
            status=200,
        )
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/pages",
            json=_pagina("t2", "Revisar PR", "Fazendo", "2026-07-01"),
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = create_task(nome="Revisar PR", status="Fazendo", prazo="2026-07-01")
        assert resultado["status"] == "Fazendo"
        assert resultado["prazo"] == "2026-07-01"


class TestMoveStatus:
    """Testes da ferramenta ``move_status``."""

    @responses.activate
    def test_move_status_com_sucesso(self):
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/pages/t1",
            json=_pagina("t1", "A", "Fazendo"),
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = move_status(task_id="t1", status="Fazendo")
        assert resultado["status"] == "Fazendo"


class TestConcludeTask:
    """Testes da ferramenta ``conclude_task``."""

    @responses.activate
    def test_conclui_tarefa_com_sucesso(self):
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/pages/t1",
            json=_pagina("t1", "A", "Concluída"),
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_tasklist", return_value=_tasklist()
        ):
            resultado = conclude_task(task_id="t1", status_concluido="Concluída")
        assert resultado["status"] == "Concluída"


class TestUpdateProjectPage:
    """Testes da ferramenta ``update_project_page``."""

    @responses.activate
    def test_atualiza_pagina_com_metadados_normalizados(self):
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/pages/projeto-1",
            json={
                "id": "projeto-1",
                "url": "https://notion.so/projeto-1",
                "properties": {},
            },
            status=200,
        )
        with mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_notion_client",
            return_value=NotionClient(token=TOKEN),
        ):
            resultado = update_project_page(
                page_id="projeto-1",
                nome_completo="felipe/projeto",
                descricao="Estado atual",
                linguagem="Python",
                topicos=["notion", " mcp "],
                estrelas=4,
                forks=1,
            )

        corpo = json.loads(responses.calls[0].request.body)
        propriedades = corpo["properties"]
        assert propriedades["Nome"]["title"][0]["text"]["content"] == "felipe/projeto"
        assert propriedades["Descrição"]["rich_text"][0]["text"]["content"] == "Estado atual"
        assert propriedades["Tópicos"]["multi_select"] == [
            {"name": "notion"},
            {"name": "mcp"},
        ]
        assert resultado == {
            "id": "projeto-1",
            "url": "https://notion.so/projeto-1",
        }


class TestUpdateGithubInventory:
    """Testes da ferramenta de atualização do inventário GitHub."""

    def test_repassa_flags_para_o_servico(self):
        from felixo_notion_mcp.services.inventario_github import ResumoInventario

        resumo = ResumoInventario(repos_encontrados=2, paginas_puladas=1)
        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=object()
            ),
            mock.patch(
                "felixo_notion_mcp.services.inventario_github.atualizar_repos", return_value=resumo
            ) as atualizar,
        ):
            resultado = update_github_inventory(
                contas=[" https://github.com/felipe "],
                database_id="db-github",
                sem_readme=True,
                sem_arquivados=True,
                apenas_mudancas=True,
            )

        assert resultado["repos_encontrados"] == 2
        assert resultado["paginas_puladas"] == 1
        _, kwargs = atualizar.call_args
        assert atualizar.call_args.args[:2] == (["https://github.com/felipe"], "db-github")
        assert kwargs["sincronizar_readme"] is False
        assert kwargs["ignorar_arquivados"] is True
        assert kwargs["apenas_mudancas"] is True


# ---------------------------------------------------------------------------
# Servidor MCP: metadata
# ---------------------------------------------------------------------------


class TestMetadataServidor:
    """Verifica propriedades do servidor MCP."""

    def test_nome_do_servidor(self):
        assert mcp.name == "notion"

    def test_instructions_menciona_confirmacao(self):
        assert "confirmacao" in mcp.instructions.lower()


# ---------------------------------------------------------------------------
# Erros pelo SDK: o que o modelo le
# ---------------------------------------------------------------------------


class TestErrosPeloSDK:
    """O SDK so entrega ao modelo a mensagem de ``ToolError``; queda vira texto generico."""

    def test_falha_prevista_chega_com_a_mensagem_sanitizada(self):
        erro = NotionConfigurationError("token-interno-nao-deve-vazar")
        with (
            mock.patch("felixo_notion_mcp.api.mcp.server._criar_tasklist", side_effect=erro),
            pytest.raises(ToolError, match="nao configurado") as exc_info,
        ):
            asyncio.run(mcp.call_tool("notion.list_tasks", {}))
        assert not isinstance(exc_info.value, UnexpectedToolError)
        assert "token-interno" not in str(exc_info.value)

    def test_entrada_invalida_chega_com_o_motivo(self):
        with pytest.raises(ToolError, match="'page_id' e obrigatorio") as exc_info:
            asyncio.run(mcp.call_tool("notion.read_page_content", {"page_id": " "}))
        assert not isinstance(exc_info.value, UnexpectedToolError)

    def test_erro_inesperado_nao_vaza_detalhe_interno(self):
        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_tasklist",
                side_effect=KeyError("segredo-interno"),
            ),
            pytest.raises(UnexpectedToolError) as exc_info,
        ):
            asyncio.run(mcp.call_tool("notion.list_tasks", {}))
        assert "segredo-interno" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# CLI / transportes
# ---------------------------------------------------------------------------


class TestCLI:
    """Verifica o transporte efetivamente passado ao SDK MCP."""

    def test_transporte_padrao_e_stdio(self):
        assert _resolver_transporte([]) == "stdio"

    def test_transporte_http_e_resolvido(self):
        assert _resolver_transporte(["--transport", "streamable-http"]) == "streamable-http"

    def test_transporte_invalido_falha(self):
        with pytest.raises(SystemExit):
            _resolver_transporte(["--transport", "websocket"])

    def test_main_repassa_transporte_ao_sdk(self):
        with mock.patch.object(mcp, "run") as run:
            main(["--transport", "streamable-http"])
        run.assert_called_once_with(transport="streamable-http")


# ---------------------------------------------------------------------------
# Ferramentas de conteudo (Notion mockado)
# ---------------------------------------------------------------------------


class TestConteudo:
    """Verifica as ferramentas de conteudo, incluindo o fluxo destrutivo."""

    def _patch_cliente(self):
        return mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_notion_client",
            return_value=NotionClient(token=TOKEN),
        )

    @responses.activate
    def test_read_page_content_devolve_markdown(self):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/page1/children",
            json={
                "results": [
                    {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "oi"}]}}
                ],
                "has_more": False,
            },
            status=200,
        )
        with self._patch_cliente():
            resultado = read_page_content(page_id="page1")
        assert resultado == {
            "id": "page1",
            "tipo": "pagina",
            "propriedades": {},
            "markdown": "oi",
        }

    @responses.activate
    def test_append_content_conta_blocos(self):
        # A escrita lê a página antes, para recusar texto solto embaixo de uma
        # database. Lista vazia = é documento, pode escrever.
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/page1/children",
            json={"results": [], "has_more": False},
            status=200,
        )
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/blocks/page1/children",
            json={"results": []},
            status=200,
        )
        with self._patch_cliente():
            resultado = append_content(page_id="page1", markdown="a\nb")
        assert resultado == {"id": "page1", "blocos_anexados": 2}

    @responses.activate
    def test_edit_block_atualiza(self):
        # A edicao le o bloco antes (conferir_atual): so assim o tipo atual e conferido.
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/b1",
            json={"id": "b1", "type": "heading_2", "heading_2": {"rich_text": []}},
            status=200,
        )
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/blocks/b1",
            json={"id": "b1"},
            status=200,
        )
        with self._patch_cliente():
            resultado = edit_block(block_id="b1", markdown="## Novo")
        assert resultado == {"id": "b1", "editado": True}
        assert "heading_2" in json.loads(responses.calls[-1].request.body)

    @responses.activate
    def test_edit_block_em_titulo_que_comeca_com_numero_grava_o_numero(self):
        # "5. texto" era lido como item de lista numerada e recusado num heading_3.
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/b1",
            json={"id": "b1", "type": "heading_3", "heading_3": {"rich_text": []}},
            status=200,
        )
        responses.add(
            responses.PATCH, f"{NOTION_BASE_URL}/blocks/b1", json={"id": "b1"}, status=200
        )
        with self._patch_cliente():
            resultado = edit_block(block_id="b1", markdown="5. Desligar a atualização")
        assert resultado == {"id": "b1", "editado": True}
        corpo = json.loads(responses.calls[-1].request.body)
        assert list(corpo) == ["heading_3"]
        assert corpo["heading_3"]["rich_text"][0]["text"]["content"] == "5. Desligar a atualização"

    @staticmethod
    def _codigo_enviado() -> str:
        """Texto do bloco de codigo que o ultimo PATCH mandou para o Notion."""

        corpo = json.loads(responses.calls[-1].request.body)
        return "".join(item["text"]["content"] for item in corpo["code"]["rich_text"])

    @staticmethod
    def _mockar_bloco_de_codigo() -> None:
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/b1",
            json={"id": "b1", "type": "code", "code": {"rich_text": [], "language": "python"}},
            status=200,
        )
        responses.add(
            responses.PATCH, f"{NOTION_BASE_URL}/blocks/b1", json={"id": "b1"}, status=200
        )

    @responses.activate
    def test_edit_block_de_codigo_preserva_o_recuo_inicial(self):
        # O strip() da borda tirava o recuo da primeira linha: o corpo de um metodo
        # chegava ao Notion deslocado e a resposta ainda dizia editado=True.
        self._mockar_bloco_de_codigo()
        with self._patch_cliente():
            resultado = edit_block(block_id="b1", markdown="    return valor\n\nfim")
        assert resultado == {"id": "b1", "editado": True}
        assert self._codigo_enviado() == "    return valor\n\nfim"

    @responses.activate
    def test_edit_block_de_codigo_converte_crlf_em_lf(self):
        # Sem normalizar, o CRLF de um cliente Windows deixava '\r' dentro do codigo.
        self._mockar_bloco_de_codigo()
        with self._patch_cliente():
            edit_block(block_id="b1", markdown="    x = 1\r\ny = 2\r\n")
        assert self._codigo_enviado() == "    x = 1\ny = 2"

    @responses.activate
    def test_append_content_nao_aninha_lista_recuada_por_igual(self):
        # Com strip() so a primeira linha perdia o recuo: "b" virava filho de "a".
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/page1/children",
            json={"results": [], "has_more": False},
            status=200,
        )
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/blocks/page1/children",
            json={"results": []},
            status=200,
        )
        with self._patch_cliente():
            resultado = append_content(page_id="page1", markdown="  - a\n  - b")
        filhos = json.loads(responses.calls[-1].request.body)["children"]
        assert [bloco["type"] for bloco in filhos] == ["bulleted_list_item"] * 2
        assert resultado == {"id": "page1", "blocos_anexados": 2}

    @pytest.mark.parametrize("ferramenta", [append_content, edit_block])
    def test_markdown_so_com_espacos_continua_sendo_recusado(self, ferramenta):
        argumentos = {"page_id" if ferramenta is append_content else "block_id": "x"}
        with self._patch_cliente(), pytest.raises(ValueError, match="markdown"):
            ferramenta(markdown="  \n\t ", **argumentos)

    @responses.activate
    def test_delete_block_arquiva(self):
        responses.add(
            responses.DELETE,
            f"{NOTION_BASE_URL}/blocks/b1",
            json={"id": "b1", "archived": True},
            status=200,
        )
        with self._patch_cliente():
            resultado = delete_block(block_id="b1")
        assert resultado == {"id": "b1", "apagado": True}
        assert responses.calls[0].request.method == "DELETE"

    def test_append_content_rejeita_pagina_vazia(self):
        with self._patch_cliente(), pytest.raises(ValueError, match="page_id"):
            append_content(page_id="   ", markdown="oi")

    @responses.activate
    def test_search_normaliza_itens(self):
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/search",
            json={
                "results": [
                    {
                        "object": "page",
                        "id": "p1",
                        "url": "https://notion.so/p1",
                        "properties": {
                            "Name": {"type": "title", "title": [{"plain_text": "Nota"}]}
                        },
                    }
                ],
                "has_more": False,
            },
            status=200,
        )
        with self._patch_cliente():
            itens = search(query="x")
        assert itens == [
            {"id": "p1", "tipo": "page", "titulo": "Nota", "url": "https://notion.so/p1"}
        ]


# ---------------------------------------------------------------------------
# Data sources (databases do modelo novo)
# ---------------------------------------------------------------------------


class TestDataSources:
    """Verifica a leitura de linhas de database e o aviso de database."""

    def _patch_cliente(self):
        return mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_notion_client",
            return_value=NotionClient(token=TOKEN),
        )

    @responses.activate
    def test_list_database_rows_resolve_fontes(self):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"data_sources": [{"id": "ds1", "name": "Principal"}]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/data_sources/ds1/query",
            json={
                "results": [
                    {
                        "id": "r1",
                        "url": "https://notion.so/r1",
                        "properties": {
                            "Name": {"type": "title", "title": [{"plain_text": "Linha 1"}]}
                        },
                    }
                ],
                "has_more": False,
            },
            status=200,
        )
        with self._patch_cliente():
            resultado = list_database_rows(database_id="db1")
        assert resultado["id"] == "db1"
        assert resultado["linhas"][0]["titulo"] == "Linha 1"

    @responses.activate
    def test_read_page_content_avisa_quando_e_database(self):
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/blocks/db1/children",
            json={"results": [], "has_more": False},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"data_sources": [{"id": "ds1", "name": "Principal"}]},
            status=200,
        )
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/data_sources/ds1/query",
            json={
                "results": [
                    {
                        "id": "r1",
                        "url": "https://notion.so/r1",
                        "properties": {
                            "Name": {"type": "title", "title": [{"plain_text": "Linha 1"}]}
                        },
                    }
                ],
                "has_more": False,
            },
            status=200,
        )
        with self._patch_cliente():
            resultado = read_page_content(page_id="db1")
        assert resultado["tipo"] == "database"
        assert resultado["linhas"][0]["id"] == "r1"

    @responses.activate
    def test_clone_database_cria_e_aplica_schema(self):
        # origem: GET database -> 1 fonte; GET data source -> schema
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db1",
            json={"data_sources": [{"id": "ds_origem", "name": "Origem"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/data_sources/ds_origem",
            json={
                "properties": {
                    "Tarefa": {"type": "title", "title": {}},
                    "Etapa": {"type": "status", "status": {"options": [{"name": "Entrada"}]}},
                },
                "parent": {"type": "page_id", "page_id": "pagina_pai"},
            },
            status=200,
        )
        # cria database -> clone; GET clone -> 1 fonte; PATCH schema
        responses.add(
            responses.POST,
            f"{NOTION_BASE_URL}/databases",
            json={"id": "db_clone"},
            status=200,
        )
        responses.add(
            responses.GET,
            f"{NOTION_BASE_URL}/databases/db_clone",
            json={"data_sources": [{"id": "ds_clone", "name": "Origem (cópia)"}]},
            status=200,
        )
        responses.add(
            responses.PATCH,
            f"{NOTION_BASE_URL}/data_sources/ds_clone",
            json={"properties": {"Etapa": {"type": "status"}}},
            status=200,
        )
        with self._patch_cliente():
            resultado = clone_database(database_id="db1")
        assert resultado["id"] == "db_clone"
        assert resultado["data_source_id"] == "ds_clone"
        assert resultado["titulo"] == "Origem (cópia)"
        assert resultado["linhas_copiadas"] == 0


# ---------------------------------------------------------------------------
# Novas ferramentas: create_database / import_spreadsheet / upload_file / move
# ---------------------------------------------------------------------------


class _ClienteNovasFerramentas:
    """Double do NotionClient para as ferramentas de construcao/movimentacao."""

    def __init__(self):
        self.chamadas: list[tuple[str, object]] = []

    def criar_database(self, pagina_id, titulo, propriedades, **kwargs):
        self.chamadas.append(("criar_database", (pagina_id, titulo, propriedades, kwargs)))
        return {"id": "db_novo", "url": "https://notion.so/db_novo"}

    def mover_pagina(self, page_id, novo_pai_id, *, tipo_pai="page_id"):
        self.chamadas.append(("mover_pagina", (page_id, novo_pai_id, tipo_pai)))
        return {"id": page_id}

    def mover_database(self, database_id, novo_pai_id):
        self.chamadas.append(("mover_database", (database_id, novo_pai_id)))
        return {"id": database_id}

    def enviar_arquivo(self, conteudo, nome, content_type):
        self.chamadas.append(("enviar_arquivo", (nome, content_type)))
        return "upload-1"

    def obter_pagina(self, page_id):
        return {"properties": {}}

    def atualizar_pagina(self, page_id, props):
        self.chamadas.append(("atualizar_pagina", (page_id, props)))
        return {"id": page_id}

    def consultar_database(self, database_id, page_size=1, filtro=None):
        return []

    def criar_pagina(self, database_id, props):
        self.chamadas.append(("criar_pagina", (database_id, props)))
        return {"id": "linha-1"}


class TestNovasFerramentas:
    def _patch(self, cliente):
        return mock.patch(
            "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=cliente
        )

    def test_create_database_monta_schema_e_titulo_automatico(self):
        cliente = _ClienteNovasFerramentas()
        with self._patch(cliente):
            resultado = create_database(
                pagina_id="pag1",
                titulo="Cadastro",
                propriedades={"Seguidores": "numero"},
                prefixo_id="DVIP",
            )
        assert resultado["id"] == "db_novo"
        _, (pagina, titulo, schema, kwargs) = cliente.chamadas[0]
        assert schema["Seguidores"] == {"number": {}}
        assert schema["Nome"] == {"title": {}}
        assert kwargs["prefixo_id"] == "DVIP"

    def test_create_database_tipo_invalido_vira_value_error(self):
        with self._patch(_ClienteNovasFerramentas()):
            with pytest.raises(ValueError):
                create_database(pagina_id="pag1", titulo="X", propriedades={"Valor": "moeda"})

    def test_import_spreadsheet_csv(self, tmp_path):
        planilha = tmp_path / "contas.csv"
        planilha.write_text("Nome,Seguidores\nConta A,1.614\n", encoding="utf-8")
        cliente = _ClienteNovasFerramentas()
        with self._patch(cliente):
            resultado = import_spreadsheet(
                database_id="db1",
                caminho=str(planilha),
                tipos={"Seguidores": "numero"},
            )
        assert resultado["criados"] == 1
        props = [c for c in cliente.chamadas if c[0] == "criar_pagina"][0][1][1]
        assert props["Seguidores"] == {"number": 1614}

    def test_upload_file_anexa_na_propriedade(self, tmp_path):
        arquivo = tmp_path / "rel.docx"
        arquivo.write_bytes(b"x")
        cliente = _ClienteNovasFerramentas()
        with self._patch(cliente):
            resultado = upload_file(page_id="pag1", caminho=str(arquivo))
        assert resultado["upload_id"] == "upload-1"
        atualizacao = [c for c in cliente.chamadas if c[0] == "atualizar_pagina"][0]
        assert "Arquivos e mídia" in atualizacao[1][1]

    def test_move_page_e_move_database(self):
        cliente = _ClienteNovasFerramentas()
        with self._patch(cliente):
            pagina = move_page(page_id="pag1", novo_pai_id="pai2")
            db = move_database(database_id="db1", novo_pai_id="pai2")
        assert pagina == {"id": "pag1", "novo_pai": "pai2", "tipo_pai": "page_id"}
        assert db == {"id": "db1", "novo_pai": "pai2"}
        assert ("mover_pagina", ("pag1", "pai2", "page_id")) in cliente.chamadas
        assert ("mover_database", ("db1", "pai2")) in cliente.chamadas


class TestRegistroDiario:
    """``carry_over_daily_log`` cria o dia com as pendências do anterior."""

    def test_repassa_dia_origem_colunas_fecho_e_dry_run_ao_servico(self):
        from datetime import date

        from felixo_notion_mcp.api.mcp.server import carry_over_daily_log

        cliente = object()
        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=cliente
            ),
            mock.patch(
                "felixo_notion_mcp.services.registro_diario.levar_pendencias",
                return_value={"criado": False, "dry_run": True},
            ) as levar,
        ):
            resultado = carry_over_daily_log(
                database_id="db1",
                data="2026-10-21",
                origem_id="p20",
                valores={"Banho": "Não"},
                fecho="## Anotações do dia",
                dry_run=True,
            )

        assert resultado == {"criado": False, "dry_run": True}
        levar.assert_called_once_with(
            "db1",
            date(2026, 10, 21),
            origem_id="p20",
            status="Aberto",
            valores={"Banho": "Não"},
            fecho="## Anotações do dia",
            dry_run=True,
            cliente=cliente,
        )

    def test_sem_dia_anterior_vira_erro_de_entrada_com_o_caminho(self):
        from felixo_notion_mcp.api.mcp.server import carry_over_daily_log

        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=object()
            ),
            mock.patch(
                "felixo_notion_mcp.services.registro_diario.levar_pendencias",
                side_effect=ValueError("Nenhum dia antes: informe a origem das pendências."),
            ),
            pytest.raises(ToolError, match="informe a origem"),
        ):
            carry_over_daily_log(database_id="db1", data="2026-10-21")

    def test_e_escrita_que_cria_sem_destruir(self):
        ferramenta = {t.name: t for t in asyncio.run(mcp.list_tools())}[
            "notion.carry_over_daily_log"
        ]
        assert ferramenta.annotations.read_only_hint is False
        assert ferramenta.annotations.destructive_hint is False


class TestImportarTarefas:
    """``import_tasks`` lê a pasta do lote e chama o serviço de importação."""

    def test_repassa_pasta_database_e_opcoes(self, tmp_path):
        from pathlib import Path

        from felixo_notion_mcp.api.mcp.server import import_tasks

        cliente = object()
        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=cliente
            ),
            mock.patch(
                "felixo_notion_mcp.services.importacao_tarefas.carregar_lote",
                return_value=["r"],
            ) as carregar,
            mock.patch(
                "felixo_notion_mcp.services.importacao_tarefas.importar_tarefas",
                return_value={"dry_run": True},
            ) as importar,
        ):
            resultado = import_tasks(
                pasta=str(tmp_path), database_id="db1", so=["a"], dry_run=True
            )

        assert resultado == {"dry_run": True}
        carregar.assert_called_once_with(Path(tmp_path), so=["a"])
        importar.assert_called_once_with(
            ["r"], "db1", paralelo=4, dry_run=True, conferir=False, cliente=cliente
        )

    def test_lote_invalido_vira_erro_de_entrada(self, tmp_path):
        from felixo_notion_mcp.api.mcp.server import import_tasks

        with (
            mock.patch(
                "felixo_notion_mcp.api.mcp.server._criar_notion_client", return_value=object()
            ),
            mock.patch(
                "felixo_notion_mcp.services.importacao_tarefas.carregar_lote",
                side_effect=ValueError("Nenhum rascunho em x"),
            ),
            pytest.raises(ToolError, match="Nenhum rascunho"),
        ):
            import_tasks(pasta=str(tmp_path), database_id="db1")
