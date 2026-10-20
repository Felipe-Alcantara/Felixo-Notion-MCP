"""Testes de ``services.views``: ordenar uma view e conferir por releitura."""

from __future__ import annotations

import pytest

from felixo_notion_mcp.services import views as svc


class ClienteFalso:
    def __init__(self, views, *, ignora_patch=False):
        self.views = {v["id"]: dict(v) for v in views}
        self.ignora_patch = ignora_patch
        self.patches = []

    def listar_views(self, database_id):
        return list(self.views)

    def obter_view(self, view_id):
        return dict(self.views[view_id])

    def atualizar_view(self, view_id, alteracoes):
        self.patches.append((view_id, alteracoes))
        if not self.ignora_patch:
            self.views[view_id].update(alteracoes)
        return self.views[view_id]


def test_ordena_a_primeira_view_de_tabela_e_renomeia():
    cliente = ClienteFalso(
        [
            {"id": "cal", "type": "calendar", "name": "Calendário", "sorts": None},
            {"id": "tab", "type": "table", "name": "Default view", "sorts": None},
        ]
    )

    resultado = svc.ordenar_view("db", "Data", "decrescente", nome="Tabela", cliente=cliente)

    assert cliente.patches == [
        ("tab", {"sorts": [{"property": "Data", "direction": "descending"}], "name": "Tabela"})
    ]
    assert resultado.aplicado is True
    assert resultado.nome == "Tabela"
    assert resultado.sorts == [{"property": "Data", "direction": "descending"}]


def test_patch_que_nao_pega_nao_e_dado_como_aplicado():
    cliente = ClienteFalso(
        [{"id": "tab", "type": "table", "name": "Default view", "sorts": None}],
        ignora_patch=True,
    )

    resultado = svc.ordenar_view("db", "Data", cliente=cliente)

    assert resultado.aplicado is False
    assert resultado.sorts == []


def test_sem_view_do_tipo_levanta_antes_de_escrever():
    cliente = ClienteFalso([{"id": "cal", "type": "calendar", "name": "C", "sorts": None}])

    with pytest.raises(svc.ViewNaoEncontradaError):
        svc.ordenar_view("db", "Data", cliente=cliente)
    assert cliente.patches == []


def test_direcao_invalida_levanta_antes_de_escrever():
    cliente = ClienteFalso([{"id": "tab", "type": "table", "name": "T", "sorts": None}])

    with pytest.raises(ValueError, match="Direção"):
        svc.ordenar_view("db", "Data", "lateral", cliente=cliente)
    assert cliente.patches == []
