"""Caso de uso: descobrir e baixar os artigos de um site para a biblioteca.

:func:`descobrir_artigos` tenta, nesta ordem, o feed (``/feed.xml``, ``/rss.xml``,
``/atom.xml``, ``/index.xml``, ``/feed``), o ``/sitemap.xml`` e, por fim, os links
internos da página inicial — a mesma sequência usada à mão no rapha.land. Junta as
fontes sem repetir URL. :func:`coletar_artigo` baixa uma página e extrai o artigo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from felixo_notion_mcp.integrations import web
from felixo_notion_mcp.services import downloads

CAMINHOS_DE_FEED = ("feed.xml", "rss.xml", "atom.xml", "index.xml", "feed", "rss")

BaixarTexto = Callable[[str], str]


@dataclass
class Descoberta:
    site: str
    artigos: list[web.ItemDeFeed] = field(default_factory=list)
    fontes: list[str] = field(default_factory=list)


def _tentar(baixar: BaixarTexto, url: str) -> str | None:
    try:
        return baixar(url)
    except downloads.DownloadErro:
        return None


def descobrir_artigos(
    site: str,
    *,
    usar_pagina_inicial: bool = True,
    baixar: BaixarTexto = downloads.baixar_texto,
) -> Descoberta:
    """Lista os artigos do site combinando feed, sitemap e (opcional) página inicial."""

    base = site.rstrip("/") + "/"
    descoberta = Descoberta(site=base)
    vistos: dict[str, web.ItemDeFeed] = {}

    for caminho in CAMINHOS_DE_FEED:
        xml = _tentar(baixar, urljoin(base, caminho))
        if not xml:
            continue
        try:
            itens = web.ler_feed(xml)
        except Exception:  # noqa: BLE001 — não era XML de feed; tenta o próximo
            continue
        if itens:
            descoberta.fontes.append(f"feed:{caminho}")
            for item in itens:
                vistos.setdefault(item.url.rstrip("/") + "/", item)
            break

    xml = _tentar(baixar, urljoin(base, "sitemap.xml"))
    if xml:
        try:
            paginas, filhos = web.ler_sitemap(xml)
            for filho in filhos:
                sub = _tentar(baixar, filho)
                if sub:
                    paginas += web.ler_sitemap(sub)[0]
            novas = [
                p
                for p in paginas
                if p.rstrip("/") + "/" not in vistos and p.rstrip("/") + "/" != base
            ]
            if novas:
                descoberta.fontes.append("sitemap")
            for pagina in novas:
                vistos.setdefault(pagina.rstrip("/") + "/", web.ItemDeFeed("", pagina, ""))
        except Exception:  # noqa: BLE001 — sitemap inválido não derruba a descoberta
            pass

    if usar_pagina_inicial:
        html = _tentar(baixar, base)
        if html:
            novos = [
                link
                for link in web.links_internos(html, base)
                if link.rstrip("/") + "/" not in vistos
            ]
            if novos:
                descoberta.fontes.append("pagina-inicial")
            for link in novos:
                vistos.setdefault(link.rstrip("/") + "/", web.ItemDeFeed("", link, ""))

    descoberta.artigos = list(vistos.values())
    return descoberta


def coletar_artigo(url: str, *, baixar: BaixarTexto = downloads.baixar_texto) -> web.ArtigoExtraido:
    """Baixa a página e extrai título, data, texto, links e imagens."""

    return web.extrair_artigo(baixar(url), url)


def baixar_pasta_do_repositorio(
    cliente: Any, repo: str, prefixo: str, destino: Path, *, ref: str = "HEAD"
) -> list[Path]:
    """Copia os arquivos de ``repo`` sob ``prefixo`` (ex.: ``content/``) para ``destino``.

    Serve para ler um blog Hugo/Jekyll sem clonar o repositório. ``cliente`` é um
    :class:`~felixo_notion_mcp.integrations.github.GitHubClient`. Arquivos que já existem
    em ``destino`` não são baixados de novo.
    """

    gravados: list[Path] = []
    for caminho in cliente.listar_arvore(repo, ref):
        if not caminho.startswith(prefixo.lstrip("/")):
            continue
        local = Path(destino) / caminho
        if not local.is_file():
            texto = cliente.ler_arquivo(repo, caminho, None if ref == "HEAD" else ref)
            if texto is None:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(texto, encoding="utf-8")
        gravados.append(local)
    return gravados
