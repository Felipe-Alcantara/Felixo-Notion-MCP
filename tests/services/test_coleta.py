"""Testes da descoberta de artigos (rede simulada por um dicionário)."""
# ruff: noqa: E501 — HTML e XML de exemplo ficam numa linha, como chegam da web

from __future__ import annotations

from felixo_notion_mcp.services import coleta, downloads


def baixador(paginas):
    def baixar(url):
        if url not in paginas:
            raise downloads.DownloadErro(url)
        return paginas[url]

    return baixar


def test_junta_feed_sitemap_e_pagina_inicial_sem_repetir():
    paginas = {
        "https://blog.dev/feed.xml": "<rss><channel><item><title>A</title><link>https://blog.dev/a/</link></item></channel></rss>",
        "https://blog.dev/sitemap.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://blog.dev/a/</loc></url><url><loc>https://blog.dev/b/</loc></url></urlset>',
        "https://blog.dev/": '<a href="/c/">c</a><a href="/a/">a</a>',
    }
    achado = coleta.descobrir_artigos("https://blog.dev", baixar=baixador(paginas))
    assert [a.url for a in achado.artigos] == [
        "https://blog.dev/a/",
        "https://blog.dev/b/",
        "https://blog.dev/c/",
    ]
    assert achado.fontes == ["feed:feed.xml", "sitemap", "pagina-inicial"]


def test_site_sem_feed_nem_sitemap_usa_a_pagina_inicial():
    achado = coleta.descobrir_artigos(
        "https://blog.dev/", baixar=baixador({"https://blog.dev/": '<a href="/x/">x</a>'})
    )
    assert [a.url for a in achado.artigos] == ["https://blog.dev/x/"]
    assert achado.fontes == ["pagina-inicial"]


class GitHubFalso:
    def __init__(self):
        self.lidos = []

    def listar_arvore(self, repo, ref="HEAD"):
        return ["content/2026/a/index.md", "content/2026/a/index.en.md", "README.md"]

    def ler_arquivo(self, repo, caminho, ref=None):
        self.lidos.append(caminho)
        return f"conteúdo de {caminho}"


def test_baixa_so_a_pasta_pedida_e_nao_repete(tmp_path):
    cliente = GitHubFalso()
    gravados = coleta.baixar_pasta_do_repositorio(cliente, "dono/blog", "content/", tmp_path)
    assert [g.relative_to(tmp_path).as_posix() for g in gravados] == [
        "content/2026/a/index.md",
        "content/2026/a/index.en.md",
    ]
    assert (tmp_path / "content/2026/a/index.md").read_text(encoding="utf-8").startswith("conteúdo")
    coleta.baixar_pasta_do_repositorio(cliente, "dono/blog", "content/", tmp_path)
    assert len(cliente.lidos) == 2
