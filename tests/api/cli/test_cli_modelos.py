"""``modelos listar|preencher``: borda sobre ``notion_starter.services.modelos``.

A regra (quem é modelo vazio, idempotência, validação das colunas) é testada
no ``notion-starter``. Aqui: argumentos, envelope, erros traduzidos e a recusa
amigável quando o starter instalado ainda não tem o serviço.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from felixo_notion_mcp.api.cli import notion_tasks as cli

DATABASE = "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
FONTE = "38e91f95-497e-818b-ab08-ff19918d6c7c"

precisa_do_servico = pytest.mark.skipif(
    importlib.util.find_spec("felixo_notion_mcp.services.modelos") is None,
    reason="notion-starter instalado ainda sem services.modelos",
)


class ClienteModelos:
    def __init__(self, *, fontes: int = 1) -> None:
        self.fontes = fontes
        self.nomes = {"m1": "New page", "m2": "Resenha"}
        self.corpos: dict[str, list[dict[str, Any]]] = {
            "m1": [], "m2": [{"id": "x", "type": "paragraph", "paragraph": {"rich_text": []}}],
        }
        self.patches: list[str] = []

    def resolver_data_source(self, database_id: str) -> str:
        from felixo_notion_mcp.core.exceptions import FonteDeDadosIndefinidaError

        if self.fontes != 1:
            raise FonteDeDadosIndefinidaError(database_id, [("ds-a", "A"), ("ds-b", "B")])
        return FONTE

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        return {"properties": {"Nome": {"type": "title"}, "Etapa": {"type": "select"}}}

    def listar_modelos(self, data_source_id: str) -> list[dict[str, Any]]:
        return [{"id": m, "name": n, "is_default": m == "m2"} for m, n in self.nomes.items()]

    def ler_blocos(self, block_id: str, buscar_todos: bool = False, recursivo: bool = False):
        return list(self.corpos.get(block_id, []))

    def atualizar_pagina(self, page_id: str, propriedades: dict[str, Any]) -> dict[str, Any]:
        self.patches.append(page_id)
        return {"id": page_id}

    def anexar_blocos(self, block_id: str, blocos: list[dict[str, Any]], **_: Any):
        criados = [{"id": f"{block_id}-n{i}", **b} for i, b in enumerate(blocos)]
        self.corpos.setdefault(block_id, []).extend(criados)
        return {"results": criados}


def _executar(args: list[str], cliente: Any) -> tuple[int, Any]:
    return cli.executar(args, tasklist_factory=lambda: None, client_factory=lambda: cliente)


def _manifesto(pasta: Path, itens: list[dict[str, Any]]) -> str:
    (pasta / "ideia.md").write_text("# Ideia\n\n- por quê", encoding="utf-8")
    caminho = pasta / "modelos.json"
    caminho.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
    return str(caminho)


@precisa_do_servico
def test_listar_mostra_modelos_e_o_limite_da_api():
    codigo, saida = _executar(["--json", "modelos", "listar", DATABASE], ClienteModelos())

    assert codigo == 0, saida
    dados = saida["dados"]
    assert dados["total"] == 2
    assert dados["modelos"][1] == {"id": "m2", "nome": "Resenha", "padrao": True}
    assert "não cria modelo" in dados["aviso"]
    # Exemplos de outros comandos já vazaram para dentro deste resultado.
    assert set(dados) == {"database_id", "total", "modelos", "aviso"}


@precisa_do_servico
def test_preencher_usa_o_vazio_e_pula_o_existente(tmp_path):
    cliente = ClienteModelos()
    manifesto = _manifesto(tmp_path, [
        {"nome": "Resenha", "arquivo": "ideia.md"},
        {"nome": "💡 Ideia rápida", "arquivo": "ideia.md", "propriedades": {"Etapa": "Ideia"}},
        {"nome": "Sobra", "arquivo": "ideia.md"},
    ])

    codigo, saida = _executar(
        ["--json", "modelos", "preencher", DATABASE, "--manifesto", manifesto], cliente
    )

    assert codigo == 0, saida
    acoes = [(a["nome"], a["acao"]) for a in saida["dados"]["acoes"]]
    assert acoes == [
        ("Resenha", "ja_existia"),
        ("💡 Ideia rápida", "preenchido"),
        ("Sobra", "sem_modelo_vazio"),
    ]
    assert saida["dados"]["faltam_modelos_vazios"] == 1
    assert cliente.patches == ["m1"]


@precisa_do_servico
def test_manifesto_invalido_vira_validacao_com_os_problemas(tmp_path):
    manifesto = _manifesto(tmp_path, [{"nome": "A", "arquivo": "nao-existe.md"}])

    codigo, saida = _executar(
        ["--json", "modelos", "preencher", DATABASE, "--manifesto", manifesto], ClienteModelos()
    )

    assert codigo == 2
    assert saida["erro"]["codigo"] == "validacao"
    assert "arquivo não encontrado" in saida["erro"]["detalhes"]["problemas"][0]


@precisa_do_servico
def test_varias_fontes_pede_fonte(tmp_path):
    codigo, saida = _executar(
        ["--json", "modelos", "listar", DATABASE], ClienteModelos(fontes=2)
    )

    assert codigo == 2
    assert saida["erro"]["proximo_passo"].endswith("--fonte ds-a")


@precisa_do_servico
def test_dry_run_humano_marca_simulacao(tmp_path):
    cliente = ClienteModelos()
    manifesto = _manifesto(tmp_path, [{"nome": "Nova", "arquivo": "ideia.md"}])

    codigo, saida = _executar(
        ["modelos", "preencher", DATABASE, "--manifesto", manifesto, "--dry-run"], cliente
    )

    assert codigo == 0
    assert saida == "[simulação] preenchido: Nova"
    assert cliente.patches == []


def test_starter_sem_o_servico_recusa_com_configuracao(monkeypatch):
    original = importlib.import_module

    def sem_servico(nome: str, *args: Any, **kwargs: Any):
        if nome == "felixo_notion_mcp.services.modelos":
            raise ImportError(nome)
        return original(nome, *args, **kwargs)

    monkeypatch.setattr(cli.importlib, "import_module", sem_servico)

    codigo, saida = _executar(["--json", "modelos", "listar", DATABASE], ClienteModelos())

    assert codigo == 2
    assert saida["erro"]["codigo"] == "configuracao"
