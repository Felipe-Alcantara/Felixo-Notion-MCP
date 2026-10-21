"""Testes de ``services.mapa_workspace``: coletar o mapa e gerar o relatório HTML."""

from __future__ import annotations

import json

from felixo_notion_mcp.core.exceptions import NotionHTTPError
from felixo_notion_mcp.services import mapa_workspace as svc


def _pagina(item_id: str, titulo: str, pai: str | None = None) -> dict:
    parent = (
        {"type": "page_id", "page_id": pai} if pai else {"type": "workspace", "workspace": True}
    )
    return {
        "id": item_id,
        "object": "page",
        "parent": parent,
        "url": f"https://notion.so/{item_id}",
        "properties": {"Nome": {"type": "title", "title": [{"plain_text": titulo}]}},
    }


def _database(item_id: str, titulo: str, pai: str) -> dict:
    return {
        "id": item_id,
        "object": "database",
        "parent": {"type": "page_id", "page_id": pai},
        "title": [{"plain_text": titulo}],
    }


class ClienteMapa:
    def __init__(self, itens, linhas, falham=()):
        self.itens = itens
        self.linhas = linhas
        self.falham = set(falham)
        self.buscas = []

    def buscar(self, query=None, page_size=100, buscar_todos=False, filtro=None):
        self.buscas.append(query)
        return self.itens

    def consultar_database(self, database_id, buscar_todos=False):
        if database_id in self.falham:
            raise NotionHTTPError(403, '{"message":"sem acesso"}')
        return [{}] * self.linhas.get(database_id, 0)


def _cliente_padrao():
    return ClienteMapa(
        [
            _pagina("home", "HOME"),
            _database("tarefas", "Tarefas", "home"),
            _database("antigo", "Arquivo", "home"),
            _pagina("solta", "Notas", pai="pai-invisivel"),
            _pagina("dup1", "Rascunho", pai="home"),
            _pagina("dup2", "Rascunho", pai="home"),
        ],
        linhas={"tarefas": 3},
        falham={"antigo"},
    )


def test_coletar_conta_as_linhas_e_marca_menos_um_quando_a_contagem_falha():
    mapa = svc.coletar_mapa(cliente=_cliente_padrao())

    assert mapa["linhas_por_database"] == {"tarefas": 3, "antigo": -1}
    assert mapa["total_paginas"] == 4 and mapa["total_databases"] == 2


def test_coletar_aponta_duplicatas_e_orfaos_por_id():
    mapa = svc.coletar_mapa(cliente=_cliente_padrao())

    assert mapa["duplicatas"] == {"Rascunho": ["dup1", "dup2"]}
    assert mapa["orfaos"] == ["solta"]
    assert {item["id"] for item in mapa["itens"]} == {
        "home", "tarefas", "antigo", "solta", "dup1", "dup2",
    }
    json.dumps(mapa)  # o mapa é a "fonte da verdade" em JSON: tem de serializar


def test_coletar_repassa_o_filtro_de_busca():
    cliente = _cliente_padrao()

    svc.coletar_mapa(query="Projetos", cliente=cliente)

    assert cliente.buscas == ["Projetos"]


def test_html_mostra_resumo_arvore_e_contagem_de_linhas():
    pagina = svc.gerar_html(svc.coletar_mapa(cliente=_cliente_padrao()))

    assert pagina.startswith("<!DOCTYPE html>")
    assert '<span class="badge">3 linhas</span>' in pagina
    assert '<span class="badge sem">? linhas</span>' in pagina
    # Filhos da HOME ficam dentro do <details> dela, na árvore.
    inicio_home = pagina.index("HOME")
    assert pagina.index("Tarefas", inicio_home) < pagina.index("</details>", inicio_home)
    assert "<b>Rascunho</b> — 2 itens" in pagina


def test_html_escapa_titulos_vindos_do_workspace():
    mapa = svc.coletar_mapa(
        cliente=ClienteMapa([_pagina("x", "<script>alert(1)</script>")], linhas={})
    )

    pagina = svc.gerar_html(mapa)

    assert "<script>alert(1)</script>" not in pagina
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in pagina


def test_html_sem_duplicatas_nem_orfaos_diz_isso():
    mapa = svc.coletar_mapa(cliente=ClienteMapa([_pagina("x", "Única")], linhas={}))

    pagina = svc.gerar_html(mapa)

    assert "Nenhuma duplicata por nome." in pagina
    assert "Nenhum órfão." in pagina


def test_gravar_escreve_so_os_arquivos_pedidos(tmp_path):
    mapa = svc.coletar_mapa(cliente=_cliente_padrao())

    gravados = svc.gravar_mapa(mapa, html=tmp_path / "mapa.html")

    assert gravados == {"html": str(tmp_path / "mapa.html")}
    assert (tmp_path / "mapa.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert not (tmp_path / "mapa.json").exists()

    gravados = svc.gravar_mapa(mapa, json_saida=tmp_path / "mapa.json")

    relido = json.loads((tmp_path / "mapa.json").read_text(encoding="utf-8"))
    assert relido["linhas_por_database"] == {"tarefas": 3, "antigo": -1}
    assert gravados == {"json": str(tmp_path / "mapa.json")}
