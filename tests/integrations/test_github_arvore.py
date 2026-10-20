"""Testes da listagem da árvore e da leitura de arquivos de um repositório."""

from __future__ import annotations

import responses

from felixo_notion_mcp.integrations.github import GitHubClient


@responses.activate
def test_lista_so_arquivos_da_arvore_recursiva():
    responses.get(
        "https://api.github.com/repos/dono/blog/git/trees/HEAD",
        json={
            "tree": [{"path": "content", "type": "tree"}, {"path": "content/a.md", "type": "blob"}]
        },
    )
    assert GitHubClient(token="t").listar_arvore("dono/blog") == ["content/a.md"]
    assert "recursive=1" in responses.calls[0].request.url


@responses.activate
def test_le_arquivo_bruto_e_devolve_none_quando_nao_existe():
    responses.get("https://api.github.com/repos/dono/blog/contents/README.md", body="# Blog")
    responses.get("https://api.github.com/repos/dono/blog/contents/sumiu.md", status=404)
    cliente = GitHubClient(token="t")
    assert cliente.ler_arquivo("dono/blog", "/README.md") == "# Blog"
    assert cliente.ler_arquivo("dono/blog", "sumiu.md") is None
