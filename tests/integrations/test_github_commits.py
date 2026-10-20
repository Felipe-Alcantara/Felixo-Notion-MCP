"""Testes da busca de commits por autor e período (``GET /search/commits``)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import responses

from felixo_notion_mcp.integrations.github import CommitRemoto, GitHubClient


def _item(sha: str, quando: str, repo: str = "dono/blog") -> dict:
    return {
        "sha": sha,
        "repository": {"full_name": repo},
        "commit": {"committer": {"date": quando}, "message": "feat: algo\n\ncorpo longo"},
    }


@responses.activate
def test_busca_monta_a_consulta_e_reduz_cada_commit():
    responses.get(
        "https://api.github.com/search/commits",
        json={"items": [_item("abcdef123", "2026-10-15T22:06:31.000-03:00")]},
    )

    commits = GitHubClient(token="t").buscar_commits("Felipe-Alcantara", "2026-10-15", "2026-10-21")

    assert commits == [
        CommitRemoto(
            repositorio="dono/blog",
            sha="abcdef1",
            quando="2026-10-15T22:06:31.000-03:00",
            mensagem="feat: algo",
        )
    ]
    consulta = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert consulta["q"] == ["author:Felipe-Alcantara committer-date:2026-10-15..2026-10-21"]


@responses.activate
def test_busca_pagina_ate_vir_pagina_incompleta():
    cheia = {"items": [_item(f"{n:07d}", "2026-10-19T15:00:00-03:00") for n in range(100)]}
    responses.get("https://api.github.com/search/commits", json=cheia)
    responses.get(
        "https://api.github.com/search/commits",
        json={"items": [_item("fim0000", "2026-10-19T16:00:00-03:00")]},
    )

    commits = GitHubClient(token="t").buscar_commits("x", "2026-10-19", "2026-10-19")

    assert len(commits) == 101
    assert len(responses.calls) == 2
