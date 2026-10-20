"""Integração com a web aberta: feeds, sitemaps e extração do texto de um artigo.

Só interpreta HTML/XML já baixado (a rede fica em :mod:`services.downloads`), com a
biblioteca padrão: ``xml.etree`` para RSS/Atom/sitemap e ``html.parser`` para páginas.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ATOM = "{http://www.w3.org/2005/Atom}"
SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass
class ItemDeFeed:
    titulo: str
    url: str
    data: str
    resumo: str = ""


@dataclass
class ArtigoExtraido:
    url: str
    titulo: str
    data: str
    texto: str
    links: list[str] = field(default_factory=list)
    imagens: list[str] = field(default_factory=list)

    @property
    def palavras(self) -> int:
        return len(re.findall(r"\w+", self.texto))


def ler_feed(xml: str) -> list[ItemDeFeed]:
    """Itens de um feed RSS 2.0 ou Atom, na ordem do feed."""

    raiz = ET.fromstring(xml)
    itens: list[ItemDeFeed] = []
    for item in raiz.iter("item"):
        itens.append(
            ItemDeFeed(
                titulo=(item.findtext("title") or "").strip(),
                url=(item.findtext("link") or "").strip(),
                data=(item.findtext("pubDate") or "").strip(),
                resumo=(item.findtext("description") or "").strip(),
            )
        )
    for entrada in raiz.iter(f"{ATOM}entry"):
        link = entrada.find(f"{ATOM}link[@rel='alternate']") or entrada.find(f"{ATOM}link")
        itens.append(
            ItemDeFeed(
                titulo=(entrada.findtext(f"{ATOM}title") or "").strip(),
                url=(link.get("href") if link is not None else "") or "",
                data=(
                    entrada.findtext(f"{ATOM}published") or entrada.findtext(f"{ATOM}updated") or ""
                ),
                resumo=(entrada.findtext(f"{ATOM}summary") or "").strip(),
            )
        )
    return [i for i in itens if i.url]


def ler_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """``(urls de páginas, urls de sub-sitemaps)`` de um sitemap ou índice de sitemaps."""

    raiz = ET.fromstring(xml)
    paginas = [e.text.strip() for e in raiz.iter(f"{SITEMAP}url/{SITEMAP}loc") if e.text]
    paginas += [e.findtext(f"{SITEMAP}loc", "").strip() for e in raiz.iter(f"{SITEMAP}url")]
    filhos = [e.findtext(f"{SITEMAP}loc", "").strip() for e in raiz.iter(f"{SITEMAP}sitemap")]
    return list(dict.fromkeys(p for p in paginas if p)), [f for f in filhos if f]


class _Extrator(HTMLParser):
    """Texto do miolo do artigo: ``<article>``/``<main>`` quando houver, senão o ``<body>``."""

    BLOCOS = {"p", "li", "h1", "h2", "h3", "h4", "pre", "blockquote", "br", "tr", "figcaption"}
    IGNORAR = {"script", "style", "nav", "header", "footer", "aside", "noscript", "form"}

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.titulo = ""
        self.data = ""
        self.partes: dict[str, list[str]] = {"article": [], "main": [], "body": []}
        self.links: list[str] = []
        self.imagens: list[str] = []
        self._pilha: list[str] = []
        self._ignorando = 0
        self._no_titulo = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.IGNORAR:
            self._ignorando += 1
        if tag in ("article", "main", "body"):
            self._pilha.append(tag)
        if tag == "title" and not self.titulo:
            self._no_titulo = True
        if tag == "meta" and a.get("property") in ("article:published_time", "og:published_time"):
            self.data = a.get("content", "")
        if tag == "time" and a.get("datetime") and not self.data:
            self.data = a["datetime"]
        if self._ignorando:
            return
        if tag == "a" and a.get("href"):
            self.links.append(urljoin(self.base, a["href"]))
        if tag == "img" and (a.get("src") or a.get("data-src")):
            self.imagens.append(urljoin(self.base, a.get("src") or a["data-src"]))
        if tag in self.BLOCOS:
            self._escrever("\n")
        if tag in ("h2", "h3", "h4"):
            self._escrever("## ")
        if tag == "li":
            self._escrever("- ")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1
        if tag in ("article", "main", "body") and tag in self._pilha:
            self._pilha.remove(tag)
        if tag == "title":
            self._no_titulo = False

    def handle_data(self, dados):
        if self._no_titulo:
            self.titulo += dados
        elif not self._ignorando:
            self._escrever(dados)

    def _escrever(self, texto: str) -> None:
        for zona in set(self._pilha):
            self.partes[zona].append(texto)


def extrair_artigo(html: str, url: str) -> ArtigoExtraido:
    """Título, data, texto, links externos e imagens de uma página de artigo."""

    extrator = _Extrator(url)
    extrator.feed(html)
    bruto = next(("".join(p) for z in ("article", "main", "body") if (p := extrator.partes[z])), "")
    texto = re.sub(r"[ \t]+\n", "\n", re.sub(r"\n\s*\n+", "\n\n", bruto)).strip()
    dominio = urlparse(url).netloc
    externos = [link for link in extrator.links if urlparse(link).netloc not in ("", dominio)]
    return ArtigoExtraido(
        url=url,
        titulo=re.sub(r"\s+", " ", extrator.titulo).strip(),
        data=extrator.data,
        texto=texto,
        links=list(dict.fromkeys(externos)),
        imagens=list(dict.fromkeys(extrator.imagens)),
    )


def links_internos(html: str, url: str) -> list[str]:
    """Links do mesmo domínio que parecem artigos (caminho com pelo menos um segmento)."""

    extrator = _Extrator(url)
    extrator.feed(html)
    dominio = urlparse(url).netloc
    candidatos = []
    for link in extrator.links:
        partes = urlparse(link)
        if partes.netloc == dominio and partes.path.strip("/") and not partes.fragment:
            if not re.search(r"\.(css|js|png|jpe?g|gif|svg|xml|ico|pdf)$", partes.path, re.I):
                candidatos.append(f"{partes.scheme}://{partes.netloc}{partes.path}")
    return list(dict.fromkeys(candidatos))
