"""Testes do comando ``importar-tarefas`` na CLI."""

from __future__ import annotations

from pathlib import Path

from felixo_notion_mcp.api.cli import notion_tasks as cli
from felixo_notion_mcp.services import importacao_tarefas as svc


def _executar(args):
    return cli.executar(args, tasklist_factory=lambda: None, client_factory=lambda: object())


def test_importar_tarefas_repassa_pasta_filtro_e_opcoes(monkeypatch, tmp_path):
    chamadas = {}
    monkeypatch.setattr(
        svc, "carregar_lote", lambda pasta, so=None: chamadas.update(pasta=pasta, so=so) or ["r"]
    )
    monkeypatch.setattr(
        svc,
        "importar_tarefas",
        lambda rascunhos, db, **kw: chamadas.update(rascunhos=rascunhos, db=db, **kw)
        or {"dry_run": True},
    )

    codigo, saida = _executar(
        ["--json", "importar-tarefas", str(tmp_path),
         "--database", "https://app.notion.com/p/30296e2dcd394cf38bbd3fb2f53c0195",
         "--so", "a", "--so", "b", "--paralelo", "8", "--dry-run", "--conferir"]
    )

    assert codigo == 0, saida
    assert chamadas["pasta"] == Path(tmp_path) and chamadas["so"] == ["a", "b"]
    assert chamadas["db"] == "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
    assert (chamadas["paralelo"], chamadas["dry_run"], chamadas["conferir"]) == (8, True, True)


def test_lote_invalido_vira_erro_de_uso_com_a_lista(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "carregar_lote", lambda pasta, so=None: ["r"])

    def invalido(*_, **__):
        raise ValueError("rascunhos inválidos, nada foi gravado:\n- a: título vazio")

    monkeypatch.setattr(svc, "importar_tarefas", invalido)

    codigo, saida = _executar(["--json", "importar-tarefas", str(tmp_path), "--database", "db1"])

    assert codigo != 0
    assert "a: título vazio" in saida["erro"]["mensagem"]
