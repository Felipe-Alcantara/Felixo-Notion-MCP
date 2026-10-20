# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown>=3.5", "pyyaml>=6", "pillow>=10"]
# ///
"""Transforma os posts de um blog Hugo em PDFs e em rascunhos para a biblioteca do Notion.

Uso:
    uv run --script scripts/notion/blog_hugo_para_biblioteca.py <repo_hugo>
        --base-url https://blog.exemplo --mapa scripts/notion/mapas/<blog>.json
        --licenca "CC BY-NC-SA 4.0" --pdfs <pasta_pdfs> --rascunhos <pasta_rascunhos>
        [--paralelo 4] [--limite N] [--so-rascunhos]

Para cada post no idioma padrão (``content/**/index.md``, sem ``draft: true``):

1. lê título, data, slug, descrição, tags e a versão traduzida (``index.<lang>.md``);
2. normaliza as tags pela taxonomia do blog (aliases viram o nome canônico) e aplica o
   mapa: a primeira regra que casar dá ícone e capa reserva; Área e Genres juntam todas;
3. troca shortcodes do Hugo (``{{< youtube >}}`` vira link; ``{{< html >}}`` vira o
   HTML de dentro) e gera o PDF com ``artigo_para_pdf.gerar_pdf`` — em paralelo,
   pulando o PDF que já existe, então dá para interromper e retomar;
4. escreve ``<chave>.json`` (título, propriedades, anexos e aparência) e ``<chave>.md``
   (corpo da página no Notion), no formato de ``importar_artigos_para_biblioteca.py``.

A capa é a primeira imagem do post; sem imagem, a miniatura do primeiro vídeo do
YouTube; sem nenhum dos dois, a capa reserva da regra. Nada aqui fala com o Notion.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # rodando como script (uv run --script): o módulo irmão está no sys.path
    import artigo_para_pdf as gerador_pdf
except ImportError:  # importado como pacote (testes)
    from scripts.notion import artigo_para_pdf as gerador_pdf

LIMITE_UPLOAD = 20 * 1024 * 1024
MESES = gerador_pdf.MESES


class Erro(Exception):
    """Falha que interrompe a geração com mensagem legível."""


@dataclass
class Post:
    pasta: Path
    titulo: str
    data: dt.date
    slug: str
    url: str
    descricao: str
    tags: list[str]
    corpo: str
    url_traducao: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def chave(self) -> str:
        return f"{self.data.isoformat()}-{self.slug}"[:120]


# ---------------------------------------------------------------------------
# Parte pura (testada em tests/scripts/test_blog_hugo_para_biblioteca.py)
# ---------------------------------------------------------------------------


def separar_front_matter(texto: str) -> tuple[dict[str, Any], str]:
    import yaml

    casado = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", texto, re.DOTALL)
    if not casado:
        return {}, texto
    dados = yaml.safe_load(casado.group(1)) or {}
    return (dados if isinstance(dados, dict) else {}), casado.group(2)


def data_do_post(front: dict[str, Any], pasta: Path) -> dt.date:
    valor = front.get("date")
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    if isinstance(valor, str) and re.match(r"\d{4}-\d{2}-\d{2}", valor):
        return dt.date.fromisoformat(valor[:10])
    partes = [p for p in pasta.parts if p.isdigit()]
    if len(partes) >= 3:
        return dt.date(int(partes[-3]), int(partes[-2]), int(partes[-1]))
    raise Erro(f"{pasta}: sem data no front matter nem no caminho")


def url_do_post(front: dict[str, Any], pasta: Path, raiz_conteudo: Path, base_url: str) -> str:
    """URL publicada: ``url`` explícita, ou o caminho da pasta com o slug no fim."""

    base = base_url.rstrip("/")
    if front.get("url"):
        return base + "/" + str(front["url"]).strip("/") + "/"
    relativo = pasta.relative_to(raiz_conteudo).parts
    ultimo = str(front.get("slug") or relativo[-1])
    return base + "/" + "/".join([*relativo[:-1], ultimo]) + "/"


def carregar_aliases(taxonomia: dict[str, Any]) -> dict[str, str]:
    """``alias -> nome canônico em português`` a partir da taxonomia do blog."""

    aliases: dict[str, str] = {}
    for grupo in ("tags", "special_tags", "event_series"):
        for chave, item in (taxonomia.get(grupo) or {}).items():
            canonico = str(item.get("pt") or chave).strip()
            for nome in [chave, canonico, item.get("en"), *(item.get("aliases") or [])]:
                if nome:
                    aliases[str(nome).strip().lower()] = canonico
    return aliases


def normalizar_tags(tags: Iterable[Any], aliases: dict[str, str]) -> list[str]:
    vistas: list[str] = []
    for tag in tags:
        nome = aliases.get(str(tag).strip().lower(), str(tag).strip().lower())
        nome = nome.replace(",", " ").strip()
        if nome and nome not in vistas:
            vistas.append(nome)
    return vistas


def classificar(tags: list[str], mapa: dict[str, Any]) -> dict[str, Any]:
    """Aplica as regras do mapa: ícone/capa da primeira que casar; Área/Genres de todas."""

    casadas = [r for r in mapa["regras"] if set(r.get("tags", [])) & set(tags)]
    padrao = mapa["padrao"]
    primeira = next((r for r in casadas if r.get("icone")), padrao)
    areas: list[str] = []
    generos: list[str] = []
    for regra in casadas or [padrao]:
        areas += [a for a in regra.get("area", []) if a not in areas]
        generos += [g for g in regra.get("genres", []) if g not in generos]
    return {
        "icone": primeira.get("icone", padrao["icone"]),
        "capa": primeira.get("capa", padrao["capa"]),
        "area": areas or padrao["area"],
        "genres": generos or padrao["genres"],
        "categoria": primeira.get("nome", "padrão"),
    }


def trocar_shortcodes(corpo: str) -> tuple[str, list[str]]:
    """Converte shortcodes do Hugo em Markdown/HTML; devolve também os IDs de vídeo."""

    videos: list[str] = []

    def youtube(casado: re.Match[str]) -> str:
        args = casado.group(1)
        achado = re.search(r'id="?([\w-]{6,})"?', args) or re.search(r"([\w-]{6,})", args)
        if not achado:
            return ""
        videos.append(achado.group(1))
        return f"\n\n[▶ Vídeo no YouTube](https://www.youtube.com/watch?v={achado.group(1)})\n\n"

    corpo = re.sub(r"\{\{[<%]\s*youtube\s+([^>%]*?)\s*[>%]\}\}", youtube, corpo)
    corpo = re.sub(r"\{\{[<%]\s*/?\s*html\s*[>%]\}\}", "", corpo)
    corpo = re.sub(r"\{\{[<%].*?[>%]\}\}", "", corpo)
    return corpo, videos


def primeira_imagem(corpo: str) -> str | None:
    achado = re.search(r'!\[[^\]]*\]\((https?://[^)\s]+)', corpo) or re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+)', corpo
    )
    return achado.group(1) if achado else None


def links_do_corpo(corpo: str) -> list[str]:
    vistos: list[str] = []
    for url in re.findall(r"\]\((https?://[^)\s]+)\)", corpo) + re.findall(
        r'href=["\'](https?://[^"\']+)', corpo
    ):
        if url not in vistos and not re.search(r"\.(png|jpe?g|gif|webp)(\?|$)", url, re.I):
            vistos.append(url)
    return vistos


def nome_de_arquivo(texto: str, limite: int = 90) -> str:
    limpo = re.sub(r'[\\/:*?"<>|\r\n\t]', "", texto).strip().rstrip(".")
    return limpo[:limite].rstrip() or "sem-titulo"


def data_por_extenso(data: dt.date) -> str:
    return f"{data.day} de {MESES[data.month - 1]} de {data.year}"


def corpo_notion(post: Post, *, autor: str, licenca: str, palavras: int, minutos: int,
                 videos: list[str], links: list[str]) -> str:
    linhas = [
        "## Sobre o artigo",
        "",
        f"- **Autor:** {autor}",
        f"- **Publicado em:** {data_por_extenso(post.data)}",
        f"- **Original:** [{post.url}]({post.url})",
    ]
    if post.url_traducao:
        traducao = post.url_traducao
        linhas.append(f"- **Versão em inglês (do autor):** [{traducao}]({traducao})")
    linhas.append(f"- **Tamanho:** cerca de {palavras} palavras (≈{minutos} min de leitura)")
    if post.tags:
        linhas.append("- **Tags do autor:** " + ", ".join(post.tags))
    if post.descricao:
        linhas += ["", "## Descrição do autor", "", post.descricao.strip()]
    if videos:
        linhas += ["", "## Vídeo", ""] + [
            f"- [youtube.com/watch?v={v}](https://www.youtube.com/watch?v={v})" for v in videos
        ]
    if links:
        linhas += ["", "## Links citados no artigo", ""]
        linhas += [f"- [{url[:90]}]({url})" for url in links]
    linhas += [
        "",
        "---",
        "",
        f"*O texto completo está no PDF anexado na coluna Local do arquivo PDF no PC. "
        f"Texto de {autor}, publicado sob a licença {licenca}; cópia para leitura offline, "
        f"sem fins comerciais.*",
        "",
    ]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Leitura do repositório, PDFs e rascunhos
# ---------------------------------------------------------------------------


def ler_posts(repo: Path, base_url: str, aliases: dict[str, str]) -> list[Post]:
    raiz = repo / "content"
    posts: list[Post] = []
    for arquivo in sorted(raiz.rglob("index.md")):
        front, corpo = separar_front_matter(arquivo.read_text(encoding="utf-8", errors="replace"))
        if front.get("draft") is True or not front.get("title"):
            continue
        pasta = arquivo.parent
        traducoes = sorted(p for p in pasta.glob("index.*.md"))
        url_traducao = None
        if traducoes:
            texto_t = traducoes[0].read_text(encoding="utf-8", errors="replace")
            front_t, _ = separar_front_matter(texto_t)
            lang = traducoes[0].name.split(".")[1]
            url_t = url_do_post(front_t, pasta, raiz, base_url)
            url_traducao = url_t.replace(base_url.rstrip("/"), base_url.rstrip("/") + f"/{lang}", 1)
        posts.append(
            Post(
                pasta=pasta,
                titulo=str(front["title"]).strip(),
                data=data_do_post(front, pasta),
                slug=str(front.get("slug") or pasta.name),
                url=url_do_post(front, pasta, raiz, base_url),
                descricao=str(front.get("description") or "").strip(),
                tags=normalizar_tags(front.get("tags") or [], aliases),
                corpo=corpo,
                url_traducao=url_traducao,
            )
        )
    return posts


def contar_paginas(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf.read_bytes()))


def caminho_pdf(pasta: Path, post: Post) -> Path:
    nome = f"{post.data.isoformat()} {nome_de_arquivo(post.titulo)}.pdf"
    return pasta / str(post.data.year) / nome


def gerar_um(post: Post, args: argparse.Namespace, autor: str) -> dict[str, Any]:
    saida = caminho_pdf(args.pdfs, post)
    corpo, videos = trocar_shortcodes(post.corpo)
    post.extras["videos"] = videos
    post.extras["corpo_limpo"] = corpo
    if not args.so_rascunhos and not (saida.is_file() and saida.stat().st_size > 0):
        texto = (
            "---\n"
            f'titulo_original: "{post.titulo.replace(chr(34), chr(92) + chr(34))}"\n'
            f'titulo: "{post.titulo.replace(chr(34), chr(92) + chr(34))}"\n'
            f"data: {post.data.isoformat()}\n"
            'descricao: ""\n'
            "---\n\n" + corpo
        )
        gerador_pdf.gerar_pdf(
            texto, saida, url_original=post.url, autor=autor, licenca=args.licenca,
            espera_ms=args.espera_ms, tempo_limite_s=args.tempo_limite_s,
            cache_imagens=args.reduzir_imagens,
        )
    return {"post": post, "pdf": saida if saida.is_file() else None}


def escrever_rascunho(post: Post, pdf: Path | None, args: argparse.Namespace,
                      mapa: dict[str, Any]) -> dict[str, Any]:
    autor = mapa.get("autor", "")
    corpo = post.extras.get("corpo_limpo", post.corpo)
    videos = post.extras.get("videos", [])
    palavras = len(re.findall(r"\w+", re.sub(r"```.*?```", "", corpo, flags=re.S)))
    minutos = max(1, math.ceil(palavras / 220))
    cat = classificar(post.tags, mapa)
    capa = primeira_imagem(corpo) or (
        f"https://img.youtube.com/vi/{videos[0]}/hqdefault.jpg" if videos else cat["capa"]
    )
    props: dict[str, Any] = dict(mapa.get("colunas_fixas", {}))
    props.update({
        "Genres": cat["genres"],
        "Área": cat["area"],
        "Tags": post.tags,
        "Data de adição": dt.date.today().isoformat(),
        "Duração": f"≈{minutos} min de leitura",
        "URL da fonte": post.url,
    })
    anexos: dict[str, str] = {}
    aviso = None
    if pdf is not None:
        props["Total Pages"] = contar_paginas(pdf)
        props["Caminho do arquivo (local)"] = str(pdf)
        if pdf.stat().st_size <= LIMITE_UPLOAD:
            anexos["Local do arquivo PDF no PC"] = str(pdf)
        else:
            aviso = f"PDF com {pdf.stat().st_size // 1024 // 1024} MB passa do limite de upload"
    dados = {
        "titulo": post.titulo,
        "propriedades": {k: v for k, v in props.items() if v not in (None, "", [])},
        "anexos": anexos,
        "aparencia": {"icone": cat["icone"], "capa": capa},
        "categoria": cat["categoria"],
    }
    if aviso:
        dados["aviso"] = aviso
    (args.rascunhos / f"{post.chave}.json").write_text(
        json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.rascunhos / f"{post.chave}.md").write_text(
        corpo_notion(post, autor=autor, licenca=args.licenca, palavras=palavras, minutos=minutos,
                     videos=videos, links=links_do_corpo(corpo)),
        encoding="utf-8",
    )
    return dados


def main(argv: list[str] | None = None) -> int:
    import yaml

    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("repo", type=Path, help="checkout do blog Hugo")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--mapa", type=Path, required=True)
    parser.add_argument("--licenca", required=True, help='ex.: "CC BY-NC-SA 4.0"')
    parser.add_argument("--pdfs", type=Path, required=True)
    parser.add_argument("--rascunhos", type=Path, required=True)
    parser.add_argument("--paralelo", type=int, default=4)
    parser.add_argument("--limite", type=int, help="processa só os N posts mais recentes")
    parser.add_argument("--espera-ms", type=int, default=12000)
    parser.add_argument(
        "--reduzir-imagens", type=Path, metavar="PASTA_CACHE",
        help="baixa as imagens para esta pasta, reduz a 1400 px e usa as cópias no PDF",
    )
    parser.add_argument(
        "--tempo-limite-s", type=int, default=300,
        help="tempo máximo do navegador por PDF (posts com muitas fotos grandes)",
    )
    parser.add_argument(
        "--so-rascunhos", action="store_true", help="não gera PDF (usa os que existem)"
    )
    args = parser.parse_args(argv)

    mapa = json.loads(args.mapa.read_text(encoding="utf-8"))
    taxonomia_arquivo = args.repo / mapa.get("taxonomia", "")
    taxonomia = {}
    if taxonomia_arquivo.is_file():
        taxonomia = yaml.safe_load(taxonomia_arquivo.read_text(encoding="utf-8"))
    aliases = carregar_aliases(taxonomia or {})
    posts = sorted(ler_posts(args.repo, args.base_url, aliases), key=lambda p: p.data, reverse=True)
    if args.limite:
        posts = posts[: args.limite]
    args.rascunhos.mkdir(parents=True, exist_ok=True)
    print(f"{len(posts)} posts", file=sys.stderr)

    trava = threading.Lock()
    feitos = {"n": 0}
    falhas: list[str] = []

    def processar(post: Post) -> dict[str, Any] | None:
        try:
            resultado = gerar_um(post, args, mapa.get("autor", ""))
            dados = escrever_rascunho(post, resultado["pdf"], args, mapa)
        except Exception as erro:  # noqa: BLE001 — um post ruim não para o lote
            with trava:
                falhas.append(f"{post.url}: {erro}")
            return None
        with trava:
            feitos["n"] += 1
            if feitos["n"] % 25 == 0:
                print(f"  {feitos['n']}/{len(posts)}", file=sys.stderr, flush=True)
        return dados

    with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as executor:
        resultados = [r for r in executor.map(processar, posts) if r]

    resumo = {
        "posts": len(posts),
        "rascunhos": len(resultados),
        "sem_pdf": sum(1 for r in resultados if "Total Pages" not in r["propriedades"]),
        "pdf_grande_demais": [r["titulo"] for r in resultados if r.get("aviso")],
        "categorias": {},
        "tags_distintas": len({t for r in resultados for t in r["propriedades"].get("Tags", [])}),
        "falhas": falhas,
    }
    for r in resultados:
        resumo["categorias"][r["categoria"]] = resumo["categorias"].get(r["categoria"], 0) + 1
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
