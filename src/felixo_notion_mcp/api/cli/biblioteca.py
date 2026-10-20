"""Comandos da CLI para a biblioteca: coletar, traduzir, gerar PDF, capas e importar.

Bordas finas: cada comando só lê argumentos e chama o serviço ou a integração
(``services.coleta``, ``services.traducao``, ``services.blog_hugo``,
``services.biblioteca``, ``integrations.pdf``, ``integrations.imagens``). Os que
precisam de ``markdown``/``pyyaml``/``pillow`` pedem o extra ``[biblioteca]``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from felixo_notion_mcp.integrations.notion_client import NotionClient

COMANDOS = (
    "coletar-artigos",
    "artigo-pdf",
    "traduzir",
    "gerar-capa",
    "ajustar-imagem",
    "blog-para-biblioteca",
    "importar-artigos",
)


def _progresso(feitos: int, total: int) -> None:
    if feitos % 25 == 0 or feitos == total:
        print(f"  {feitos}/{total}", file=sys.stderr, flush=True)


def registrar(sub: argparse._SubParsersAction) -> None:
    """Acrescenta os comandos da biblioteca ao parser principal."""

    coletar = sub.add_parser(
        "coletar-artigos",
        help="descobre os artigos de um site (feed, sitemap e links da página inicial)",
    )
    coletar.add_argument("site")
    coletar.add_argument("--sem-pagina-inicial", action="store_true")
    coletar.add_argument("--extrair", action="store_true", help="baixa e extrai cada artigo")

    pdf = sub.add_parser("artigo-pdf", help="gera o PDF de um Markdown com metadados (Edge/Chrome)")
    pdf.add_argument("artigo", type=Path)
    pdf.add_argument("saida", type=Path)
    pdf.add_argument("--url-original", required=True)
    pdf.add_argument("--autor", required=True)
    pdf.add_argument("--licenca", help='aviso opcional no rodapé, ex.: "MIT" ou "CC BY 4.0"')
    pdf.add_argument("--titular")
    pdf.add_argument("--reduzir-imagens", type=Path, metavar="PASTA_CACHE")
    pdf.add_argument("--largura-imagens", type=int, default=1400)
    pdf.add_argument("--qualidade-imagens", type=int, default=82)
    pdf.add_argument("--tempo-limite-s", type=int, default=300)

    traduzir = sub.add_parser("traduzir", help="traduz um Markdown pelo OpenRouter, código intacto")
    traduzir.add_argument("entrada", type=Path)
    traduzir.add_argument("saida", type=Path)
    traduzir.add_argument("--idioma", default="português do Brasil")
    traduzir.add_argument("--modelo", help="modelo do OpenRouter (padrão do provedor)")

    capa = sub.add_parser("gerar-capa", help="desenha uma capa 1500x600 original (PNG)")
    capa.add_argument("titulo")
    capa.add_argument("subtitulo")
    capa.add_argument("saida", type=Path)
    capa.add_argument("--estilo", default="claro")

    ajustar = sub.add_parser(
        "ajustar-imagem", help="reduz largura e peso de uma imagem (JPEG) até caber"
    )
    ajustar.add_argument("origem", type=Path)
    ajustar.add_argument("destino", type=Path)
    ajustar.add_argument("--limite-mb", type=float, help="tamanho máximo do arquivo")
    ajustar.add_argument("--largura", type=int, default=1400)

    blog = sub.add_parser(
        "blog-para-biblioteca", help="posts de um blog Hugo viram PDFs e rascunhos da biblioteca"
    )
    blog.add_argument("repo", type=Path)
    blog.add_argument("--base-url", required=True)
    blog.add_argument("--mapa", required=True, help="caminho ou nome de mapa embutido")
    blog.add_argument("--licenca", default="", help="aviso opcional no rodapé dos PDFs")
    blog.add_argument("--pdfs", type=Path, required=True)
    blog.add_argument("--rascunhos", type=Path, required=True)
    blog.add_argument("--paralelo", type=int, default=4)
    blog.add_argument("--limite", type=int)
    blog.add_argument("--reduzir-imagens", type=Path, metavar="PASTA_CACHE")
    blog.add_argument("--largura-imagens", type=int, default=1400)
    blog.add_argument("--qualidade-imagens", type=int, default=82)
    blog.add_argument("--limite-upload-mb", type=float, default=5)
    blog.add_argument("--tempo-limite-s", type=int, default=300)
    blog.add_argument("--so-rascunhos", action="store_true")

    importar = sub.add_parser(
        "importar-artigos",
        help="grava rascunhos (<chave>.json/.md) num database sem duplicar nem apagar",
    )
    importar.add_argument("pasta", type=Path)
    importar.add_argument("--database", required=True)
    importar.add_argument("--opcao-nova", action="append", default=[], metavar="COLUNA=VALOR")
    importar.add_argument("--opcoes-livres", action="append", default=[], metavar="COLUNA")
    importar.add_argument("--nao-completar", action="append", default=[], metavar="COLUNA=VALOR")
    importar.add_argument("--paralelo", type=int, default=1)
    importar.add_argument("--dry-run", action="store_true")


def executar(args: argparse.Namespace, *, client_factory: Callable[[], NotionClient]) -> Any:
    """Despacha um dos :data:`COMANDOS`."""

    comando = args.comando
    if comando == "coletar-artigos":
        from felixo_notion_mcp.services import coleta

        achado = coleta.descobrir_artigos(
            args.site, usar_pagina_inicial=not args.sem_pagina_inicial
        )
        artigos = [vars(item) for item in achado.artigos]
        if args.extrair:
            artigos = [vars(coleta.coletar_artigo(a["url"])) | {"palavras": 0} for a in artigos]
            for artigo in artigos:
                artigo["palavras"] = len(artigo["texto"].split())
        return {
            "site": achado.site,
            "fontes": achado.fontes,
            "total": len(artigos),
            "artigos": artigos,
        }

    if comando == "artigo-pdf":
        from felixo_notion_mcp.integrations import pdf

        saida = pdf.gerar_pdf(
            args.artigo.read_text(encoding="utf-8"),
            args.saida,
            url_original=args.url_original,
            autor=args.autor,
            licenca=args.licenca,
            titular=args.titular,
            cache_imagens=args.reduzir_imagens,
            largura_imagens=args.largura_imagens,
            qualidade_imagens=args.qualidade_imagens,
            tempo_limite_s=args.tempo_limite_s,
        )
        return {"pdf": str(saida), "bytes": saida.stat().st_size}

    if comando == "traduzir":
        from felixo_notion_mcp.integrations.openrouter import ProvedorOpenRouter
        from felixo_notion_mcp.services import traducao

        texto = traducao.traduzir_markdown(
            args.entrada.read_text(encoding="utf-8"),
            provedor=ProvedorOpenRouter(),
            idioma=args.idioma,
            modelo=args.modelo,
        )
        args.saida.write_text(texto, encoding="utf-8")
        return {"saida": str(args.saida), "caracteres": len(texto)}

    if comando == "gerar-capa":
        from felixo_notion_mcp.integrations import imagens

        saida = imagens.gerar_capa(args.titulo, args.subtitulo, args.saida, estilo=args.estilo)
        return {"capa": str(saida), "bytes": saida.stat().st_size}

    if comando == "ajustar-imagem":
        from felixo_notion_mcp.integrations import imagens

        if args.limite_mb:
            saida = imagens.caber_em(
                args.origem,
                args.destino,
                int(args.limite_mb * 1024 * 1024),
                largura_inicial=args.largura,
            )
        else:
            saida = imagens.reduzir(args.origem, args.destino, largura_max=args.largura)
        return {"imagem": str(saida), "bytes": saida.stat().st_size}

    if comando == "blog-para-biblioteca":
        from felixo_notion_mcp.services import blog_hugo, organizacao

        opcoes = blog_hugo.OpcoesLote(
            repo=args.repo,
            base_url=args.base_url,
            mapa=organizacao.carregar_mapa(args.mapa),
            licenca=args.licenca,
            pdfs=args.pdfs,
            rascunhos=args.rascunhos,
            paralelo=args.paralelo,
            limite=args.limite,
            reduzir_imagens=args.reduzir_imagens,
            largura_imagens=args.largura_imagens,
            qualidade_imagens=args.qualidade_imagens,
            limite_upload_mb=args.limite_upload_mb,
            tempo_limite_s=args.tempo_limite_s,
            so_rascunhos=args.so_rascunhos,
        )
        return blog_hugo.gerar_lote(opcoes, progresso=_progresso)

    if comando == "importar-artigos":
        from felixo_notion_mcp.services import biblioteca

        return biblioteca.importar_artigos(
            biblioteca.carregar_rascunhos(args.pasta),
            args.database,
            cliente=client_factory(),
            opcoes_novas=biblioteca.ler_opcoes_novas(args.opcao_nova),
            opcoes_livres=args.opcoes_livres,
            nao_completar=biblioteca.ler_pares(args.nao_completar, "--nao-completar"),
            paralelo=args.paralelo,
            dry_run=args.dry_run,
            progresso=_progresso,
        )

    raise ValueError(f"comando desconhecido: {comando}")
