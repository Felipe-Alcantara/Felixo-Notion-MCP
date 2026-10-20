"""Testes da leitura de feeds/sitemaps e da extração de artigos (HTML sintético)."""
# ruff: noqa: E501 — HTML e XML de exemplo ficam numa linha, como chegam da web

from __future__ import annotations

from felixo_notion_mcp.integrations import web

RSS = """<rss><channel>
<item><title>Primeiro</title><link>https://blog.dev/primeiro/</link><pubDate>2026-01-02</pubDate></item>
<item><title>Segundo</title><link>https://blog.dev/segundo/</link></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom</title><link rel="alternate" href="https://blog.dev/atom/"/>
<published>2026-03-04</published></entry></feed>"""

SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://blog.dev/a/</loc></url><url><loc>https://blog.dev/b/</loc></url></urlset>"""

PAGINA = """<html><head><title>Título do post</title>
<meta property="article:published_time" content="2026-05-06"></head>
<body><nav><a href="/menu">Menu</a></nav>
<article><h1>Título do post</h1><p>Primeiro parágrafo.</p>
<h2>Seção</h2><ul><li>item</li></ul>
<p>Veja <a href="https://outro.dev/x">fora</a> e <a href="/interno">dentro</a>.</p>
<img src="/img/a.png"><script>lixo()</script></article>
<footer>rodapé</footer></body></html>"""


def test_le_rss_e_atom():
    assert [i.url for i in web.ler_feed(RSS)] == [
        "https://blog.dev/primeiro/",
        "https://blog.dev/segundo/",
    ]
    [atom] = web.ler_feed(ATOM)
    assert (atom.titulo, atom.url, atom.data) == ("Atom", "https://blog.dev/atom/", "2026-03-04")


def test_le_sitemap():
    paginas, filhos = web.ler_sitemap(SITEMAP)
    assert paginas == ["https://blog.dev/a/", "https://blog.dev/b/"]
    assert filhos == []


def test_extrai_so_o_miolo_do_artigo():
    artigo = web.extrair_artigo(PAGINA, "https://blog.dev/post/")
    assert artigo.titulo == "Título do post"
    assert artigo.data == "2026-05-06"
    assert "Primeiro parágrafo." in artigo.texto and "## Seção" in artigo.texto
    assert (
        "Menu" not in artigo.texto and "rodapé" not in artigo.texto and "lixo" not in artigo.texto
    )
    assert artigo.links == ["https://outro.dev/x"]
    assert artigo.imagens == ["https://blog.dev/img/a.png"]


def test_links_internos_ignora_arquivos_e_outros_dominios():
    html = '<a href="/p/um/">1</a><a href="/estilo.css">c</a><a href="https://x.dev/y">y</a><a href="/">h</a>'
    assert web.links_internos(html, "https://blog.dev/") == ["https://blog.dev/p/um/"]
