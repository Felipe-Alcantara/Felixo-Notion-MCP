"""Testes do comando ``registro-diario`` (garantir e estimar) na CLI."""

from __future__ import annotations

from datetime import date

from felixo_notion_mcp.api.cli import notion_tasks as cli
from felixo_notion_mcp.integrations.github import CommitRemoto
from felixo_notion_mcp.services import registro_diario as svc


def _executar(args):
    return cli.executar(args, tasklist_factory=lambda: None, client_factory=lambda: object())


def test_garantir_aceita_data_no_formato_do_titulo(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        svc,
        "garantir_dia",
        lambda db, dia, **kw: chamadas.append((db, dia, kw["status"], kw["valores"]))
        or {"dia": dia.isoformat(), "page_id": "p", "criado": True},
    )

    codigo, saida = _executar(
        ["--json", "registro-diario", "garantir", "db1", "19-10-2026", "--set", "Banho=Sim"]
    )

    assert codigo == 0, saida
    assert chamadas == [("db1", date(2026, 10, 19), "Aberto", {"Banho": "Sim"})]


def test_estimar_sem_aplicar_so_mostra_e_pede_um_dia_a_mais_ao_github(monkeypatch):
    pedidos = []

    class GitHubFalso:
        def __init__(self, token=None):
            pass

        def buscar_commits(self, autor, desde, ate):
            pedidos.append((autor, desde, ate))
            return [
                CommitRemoto("dono/blog", "a", "2026-10-19T15:00:00-03:00", "feat"),
                CommitRemoto("dono/blog", "b", "2026-10-19T16:00:00-03:00", "feat"),
            ]

    monkeypatch.setattr(cli, "GitHubClient", GitHubFalso)
    monkeypatch.setattr(cli, "_token_github", lambda: None)
    monkeypatch.setattr(
        svc, "aplicar_estimativas", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )

    codigo, saida = _executar(
        ["--json", "registro-diario", "estimar", "db1", "--de", "2026-10-19",
         "--ate", "2026-10-19", "--autor", "eu"]
    )

    assert codigo == 0, saida
    # Véspera para o sono e um dia a mais porque a busca do GitHub filtra em UTC.
    assert pedidos == [("eu", "2026-10-18", "2026-10-20")]
    (estimativa,) = saida["dados"]["estimativas"]
    assert estimativa["propriedades"]["Projetos pessoais (h)"] == "1.5"
    assert saida["dados"]["aplicado"] is False


def test_estimar_recusa_intervalo_invertido():
    codigo, saida = _executar(
        ["--json", "registro-diario", "estimar", "db1", "--de", "2026-10-20",
         "--ate", "2026-10-16", "--autor", "eu"]
    )

    assert codigo != 0
    assert "--ate" in saida["erro"]["mensagem"]
