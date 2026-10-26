"""Testes do caso de uso de clonagem de databases (``services.clonagem``).

A clonagem encadeia várias chamadas (criar database, ler/atualizar data source,
copiar linhas). Em vez de mockar todo o HTTP, injeta-se um cliente falso que
grava as chamadas — assim os testes afirmam o comportamento difícil descoberto
em uso: auto-relação reapontada para o clone, relação externa preservada,
opções de ``status`` recriadas, e cópia de linhas ignorando campos automáticos.
"""

from __future__ import annotations

import pytest

from felixo_notion_mcp.services import clonagem as svc

ORIGEM_DB = "db_origem"
ORIGEM_FONTE = "fonte_origem"
CLONE_DB = "db_clone"
CLONE_FONTE = "fonte_clone"
AREAS_FONTE = "fonte_areas"
PAGINA_PAI = "pagina_pai"

# Schema da origem cobrindo os casos: title, status, select, auto-relação
# (aponta para a própria fonte), relação externa (Áreas) e campo automático.
SCHEMA_ORIGEM = {
    "Tarefa": {"type": "title", "title": {}},
    "Esforço": {
        "type": "status",
        "status": {"options": [{"name": "Dias"}, {"name": "Minutos"}]},
    },
    "Prioridade": {"type": "select", "select": {"options": [{"name": "Alta"}]}},
    "Subtarefas": {
        "type": "relation",
        "relation": {"data_source_id": ORIGEM_FONTE, "single_property": {}},
    },
    "Áreas da vida": {
        "type": "relation",
        "relation": {"data_source_id": AREAS_FONTE, "single_property": {}},
    },
    "Criado em": {"type": "created_time", "created_time": {}},
}


class FakeClient:
    """Cliente falso que grava as chamadas relevantes da clonagem."""

    def __init__(self, linhas: list[dict] | None = None) -> None:
        self.linhas = linhas or []
        self.schema_aplicado: dict | None = None
        self.paginas_criadas: list[dict] = []
        self.titulo_criado: str | None = None
        self.pagina_destino: str | None = None

    def listar_data_sources(self, database_id):
        if database_id == ORIGEM_DB:
            return [{"id": ORIGEM_FONTE, "name": "Tarefas"}]
        if database_id == CLONE_DB:
            return [{"id": CLONE_FONTE, "name": "Tarefas (cópia)"}]
        return []

    def get_data_source(self, data_source_id):
        if data_source_id == ORIGEM_FONTE:
            return {
                "properties": SCHEMA_ORIGEM,
                "parent": {"type": "page_id", "page_id": PAGINA_PAI},
            }
        return {"properties": {}}

    def criar_database(self, pagina_id, titulo, propriedades):
        self.pagina_destino = pagina_id
        self.titulo_criado = titulo
        return {"id": CLONE_DB}

    def atualizar_data_source(self, data_source_id, *, propriedades):
        self.schema_aplicado = propriedades
        return {"properties": propriedades}

    def consultar_data_source(self, data_source_id, page_size=100, buscar_todos=False, filtro=None):
        return self.linhas if data_source_id == ORIGEM_FONTE else []

    def criar_pagina_em_fonte(self, data_source_id, propriedades):
        self.paginas_criadas.append({"fonte": data_source_id, "props": propriedades})
        return {"id": f"nova_{len(self.paginas_criadas)}"}


def test_clona_schema_sem_title_e_com_titulo_padrao():
    cli = FakeClient()
    resultado = svc.clonar_database(ORIGEM_DB, cliente=cli)

    assert resultado["id"] == CLONE_DB
    assert resultado["data_source_id"] == CLONE_FONTE
    assert cli.titulo_criado == "Tarefas (cópia)"
    # title não é recriado (o database já nasce com ele).
    assert "Tarefa" not in cli.schema_aplicado
    # demais propriedades entram.
    assert set(cli.schema_aplicado) == {
        "Esforço",
        "Prioridade",
        "Subtarefas",
        "Áreas da vida",
        "Criado em",
    }


def test_status_recria_opcoes():
    cli = FakeClient()
    svc.clonar_database(ORIGEM_DB, cliente=cli)
    esforco = cli.schema_aplicado["Esforço"]
    assert esforco == {"status": {"options": [{"name": "Dias"}, {"name": "Minutos"}]}}


def test_auto_relacao_aponta_para_o_clone():
    cli = FakeClient()
    svc.clonar_database(ORIGEM_DB, cliente=cli)
    # 'Subtarefas' apontava para a própria fonte de origem -> deve apontar para
    # a fonte do clone, não de volta para a origem.
    rel = cli.schema_aplicado["Subtarefas"]["relation"]
    assert rel["data_source_id"] == CLONE_FONTE


def test_relacao_externa_e_preservada():
    cli = FakeClient()
    svc.clonar_database(ORIGEM_DB, cliente=cli)
    # 'Áreas da vida' aponta para outro database -> preserva o mesmo alvo.
    rel = cli.schema_aplicado["Áreas da vida"]["relation"]
    assert rel["data_source_id"] == AREAS_FONTE


def test_relacoes_como_texto_viram_rich_text():
    cli = FakeClient()
    svc.clonar_database(ORIGEM_DB, relacoes="texto", cliente=cli)
    assert cli.schema_aplicado["Subtarefas"] == {"rich_text": {}}
    assert cli.schema_aplicado["Áreas da vida"] == {"rich_text": {}}


def test_relacoes_invalido_levanta():
    with pytest.raises(ValueError):
        svc.clonar_database(ORIGEM_DB, relacoes="qualquer", cliente=FakeClient())


def test_sem_linhas_nao_copia():
    cli = FakeClient(linhas=[{"properties": {}}])
    resultado = svc.clonar_database(ORIGEM_DB, cliente=cli)
    assert resultado["linhas_copiadas"] == 0
    assert cli.paginas_criadas == []


def test_com_linhas_copia_valores_e_ignora_automaticos():
    linha = {
        "properties": {
            "Tarefa": {"type": "title", "title": [{"plain_text": "Fazer X"}]},
            "Esforço": {"type": "status", "status": {"name": "Dias"}},
            "Áreas da vida": {"type": "relation", "relation": [{"id": "area1"}]},
            "Criado em": {"type": "created_time", "created_time": "2026-01-01"},
        }
    }
    cli = FakeClient(linhas=[linha])
    resultado = svc.clonar_database(ORIGEM_DB, com_linhas=True, cliente=cli)

    assert resultado["linhas_copiadas"] == 1
    props = cli.paginas_criadas[0]["props"]
    # title e status copiam; relação externa é preservada.
    assert props["Tarefa"] == {"title": [{"type": "text", "text": {"content": "Fazer X"}}]}
    assert props["Esforço"] == {"status": {"name": "Dias"}}
    assert props["Áreas da vida"] == {"relation": [{"id": "area1"}]}
    # campo automático não é copiado.
    assert "Criado em" not in props


def test_com_linhas_texto_ignora_relacao():
    linha = {
        "properties": {
            "Tarefa": {"type": "title", "title": [{"plain_text": "Y"}]},
            "Áreas da vida": {"type": "relation", "relation": [{"id": "area1"}]},
        }
    }
    cli = FakeClient(linhas=[linha])
    svc.clonar_database(ORIGEM_DB, com_linhas=True, relacoes="texto", cliente=cli)
    props = cli.paginas_criadas[0]["props"]
    assert "Áreas da vida" not in props
    assert "Tarefa" in props


def test_titulo_e_pagina_destino_customizados():
    cli = FakeClient()
    svc.clonar_database(
        ORIGEM_DB, titulo="Meu Clone", pagina_destino="outra_pagina", cliente=cli
    )
    assert cli.titulo_criado == "Meu Clone"
    assert cli.pagina_destino == "outra_pagina"


def test_pagina_destino_padrao_e_a_pai_da_origem():
    cli = FakeClient()
    svc.clonar_database(ORIGEM_DB, cliente=cli)
    assert cli.pagina_destino == PAGINA_PAI


def test_origem_sem_data_source_levanta():
    class SemFonte(FakeClient):
        def listar_data_sources(self, database_id):
            return []

    with pytest.raises(ValueError, match="sem data source"):
        svc.clonar_database(ORIGEM_DB, cliente=SemFonte())


def test_origem_com_multiplas_fontes_levanta():
    class MultiFonte(FakeClient):
        def listar_data_sources(self, database_id):
            return [{"id": "a"}, {"id": "b"}]

    with pytest.raises(ValueError, match="múltiplos data sources"):
        svc.clonar_database(ORIGEM_DB, cliente=MultiFonte())


def test_com_linhas_copia_a_relacao_inteira_quando_a_consulta_a_corta_em_25():
    """Medido na API real: a consulta devolve 25 de 30 ligações com ``has_more``, e a cópia
    levava só as 25."""

    areas = [f"area{i:02d}" for i in range(30)]
    linha = {
        "id": "linha1",
        "properties": {
            "Tarefa": {"type": "title", "title": [{"plain_text": "Fazer X"}]},
            "Áreas da vida": {
                "id": "%3AAr",
                "type": "relation",
                "relation": [{"id": a} for a in areas[:25]],
                "has_more": True,
            },
        },
    }

    class ClienteComRelacaoLonga(FakeClient):
        lidos: list[tuple[str, str]] = []

        def ler_itens_de_propriedade(self, page_id, property_id):
            self.lidos.append((page_id, property_id))
            return [
                {"object": "property_item", "type": "relation", "relation": {"id": a}}
                for a in areas
            ]

    cli = ClienteComRelacaoLonga(linhas=[linha])
    svc.clonar_database(ORIGEM_DB, com_linhas=True, cliente=cli)

    assert cli.lidos == [("linha1", "%3AAr")]
    assert cli.paginas_criadas[0]["props"]["Áreas da vida"] == {
        "relation": [{"id": a} for a in areas]
    }


def test_relacao_ate_25_na_clonagem_nao_faz_leitura_extra():
    linha = {
        "id": "linha1",
        "properties": {
            "Tarefa": {"type": "title", "title": [{"plain_text": "Y"}]},
            "Áreas da vida": {"id": "%3AAr", "type": "relation", "relation": [{"id": "a1"}]},
        },
    }
    cli = FakeClient(linhas=[linha])  # sem ler_itens_de_propriedade: chamar levantaria erro

    svc.clonar_database(ORIGEM_DB, com_linhas=True, cliente=cli)

    assert cli.paginas_criadas[0]["props"]["Áreas da vida"] == {"relation": [{"id": "a1"}]}
