# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown>=3.5", "pillow>=10"]
# ///
"""Gera o PDF de um artigo em Markdown (uma tradução, por exemplo) para a biblioteca.

Uso:
    uv run --script scripts/notion/artigo_para_pdf.py <artigo.md> <saida.pdf>
        --url-original <url> --autor "Nome" [--base-url https://site/]
        [--licenca MIT --titular "Nome"] [--fonte "repo@commit"] [--navegador <exe>]

O Markdown começa com um bloco de metadados entre ``---``, com ``titulo``,
``titulo_original``, ``data`` (AAAA-MM-DD) e ``descricao`` (opcional). O PDF sai com:

- capa curta: título traduzido, título original, autor, data de publicação e link do
  original;
- o corpo, com caminhos relativos de imagem trocados pelo endereço absoluto (o
  navegador baixa a imagem na hora de imprimir) e vídeos trocados por um link, porque
  vídeo não aparece em PDF;
- no fim, a nota de tradução e, quando ``--licenca MIT``, o aviso de copyright e o
  texto da licença, que a MIT exige em toda cópia.

O PDF é impresso por um navegador Chromium em modo headless (Edge ou Chrome), sem
cabeçalho nem rodapé do navegador. Nada aqui fala com o Notion; para anexar o arquivo
numa linha, use ``importar_artigos_para_biblioteca.py`` (campo ``anexos``).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

TEXTO_MIT = """Permission is hereby granted, free of charge, to any person obtaining a copy of \
this software and associated documentation files (the "Software"), to deal in the Software \
without restriction, including without limitation the rights to use, copy, modify, merge, \
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to \
whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or \
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING \
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND \
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, \
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, \
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."""

CANDIDATOS_NAVEGADOR = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)
NOMES_NAVEGADOR = ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome")

CSS = """
@page { size: A4; margin: 22mm 20mm 22mm 20mm; }
html { font-size: 11pt; }
body { font-family: "EB Garamond", Georgia, "Times New Roman", serif; line-height: 1.55;
       color: #1b1b1b; max-width: 100%; margin: 0; }
header.capa { border-bottom: 1px solid #ccc; margin-bottom: 1.6em; padding-bottom: 1em; }
header.capa h1 { font-size: 2em; line-height: 1.2; margin: 0 0 .25em; }
header.capa .original { font-style: italic; color: #555; margin: 0 0 .8em; }
header.capa dl { display: grid; grid-template-columns: max-content 1fr; gap: .15em 1em;
                 margin: 0; font-size: .92em; }
header.capa dt { color: #666; } header.capa dd { margin: 0; word-break: break-all; }
h2, h3, h4 { line-height: 1.25; page-break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #1a4f8a; text-decoration: none; word-break: break-word; }
img, svg, video, iframe { max-width: 100%; height: auto; page-break-inside: avoid; }
figure { margin: 1em 0; page-break-inside: avoid; } figcaption { font-size: .88em; color: #555; }
pre { background: #f5f5f3; border: 1px solid #e2e2de; padding: .7em .9em; font-size: .82em;
      white-space: pre-wrap; word-break: break-word; page-break-inside: auto; }
code { font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: .9em; }
pre code { font-size: 1em; }
table { border-collapse: collapse; width: 100%; font-size: .88em; margin: 1em 0; }
th, td { border: 1px solid #ddd; padding: .3em .5em; text-align: left; vertical-align: top; }
blockquote { margin: 1em 0; padding-left: 1em; border-left: 3px solid #ccc; color: #444; }
.video-link { border: 1px dashed #bbb; padding: .5em .8em; font-size: .92em; }
footer.licenca { margin-top: 2.5em; border-top: 1px solid #ccc; padding-top: 1em;
                 font-size: .82em; color: #444; page-break-inside: avoid; }
footer.licenca pre { font-family: inherit; background: none; border: none; padding: 0;
                     font-size: .95em; white-space: pre-wrap; }
"""


class Erro(Exception):
    """Falha que interrompe a geração com mensagem legível."""


@dataclass(frozen=True)
class Artigo:
    titulo: str
    titulo_original: str
    data: str
    descricao: str
    corpo: str


# ---------------------------------------------------------------------------
# Parte sem navegador e sem a biblioteca markdown (testada)
# ---------------------------------------------------------------------------


def ler_artigo(texto: str) -> Artigo:
    """Separa o bloco de metadados ``---`` do corpo em Markdown."""

    casado = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", texto, re.DOTALL)
    if not casado:
        raise Erro("o artigo precisa começar com um bloco de metadados entre '---'")
    metadados: dict[str, str] = {}
    for linha in casado.group(1).splitlines():
        chave, separador, valor = linha.partition(":")
        if separador:
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] == '"':
                valor = valor[1:-1].replace('\\"', '"')
            metadados[chave.strip()] = valor
    faltando = [c for c in ("titulo", "titulo_original", "data") if not metadados.get(c)]
    if faltando:
        raise Erro(f"metadados obrigatórios ausentes: {', '.join(faltando)}")
    return Artigo(
        titulo=metadados["titulo"],
        titulo_original=metadados["titulo_original"],
        data=metadados["data"],
        descricao=metadados.get("descricao", ""),
        corpo=casado.group(2).strip(),
    )


def data_por_extenso(iso: str) -> str:
    ano, mes, dia = iso[:10].split("-")
    return f"{int(dia)} de {MESES[int(mes) - 1]} de {ano}"


def absolutizar(html_corpo: str, base_url: str) -> str:
    """Troca ``src``/``href``/``poster`` que começam em ``/`` pelo endereço absoluto."""

    raiz = base_url.rstrip("/")
    return re.sub(
        r'\b(src|href|poster)=(["\'])/(?!/)',
        lambda m: f"{m.group(1)}={m.group(2)}{raiz}/",
        html_corpo,
    )


def reduzir_imagens(html_corpo: str, cache: Path, largura_max: int = 1400) -> str:
    """Troca imagens remotas por cópias locais reduzidas (JPEG, até ``largura_max`` px).

    Fotos originais de câmera (10+ MB cada) travam o navegador na impressão e geram PDFs
    grandes demais para o upload do Notion. Cada URL é baixada uma vez para ``cache``;
    se baixar ou converter falhar, a imagem original continua no HTML.
    """

    import hashlib
    import urllib.request

    from PIL import Image  # dependência declarada no cabeçalho do script (PEP 723)

    cache.mkdir(parents=True, exist_ok=True)

    def local(casado: re.Match[str]) -> str:
        url = html.unescape(casado.group(2))
        destino = cache / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".jpg")
        if not destino.is_file():
            try:
                pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(pedido, timeout=90) as resposta:
                    bruto = cache / (destino.stem + ".orig")
                    bruto.write_bytes(resposta.read())
                with Image.open(bruto) as imagem:
                    imagem = imagem.convert("RGB")
                    if imagem.width > largura_max:
                        altura = round(imagem.height * largura_max / imagem.width)
                        imagem = imagem.resize((largura_max, altura))
                    imagem.save(destino, "JPEG", quality=82, optimize=True)
                bruto.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001 — sem a cópia, fica a imagem original
                return casado.group(0)
        return f"{casado.group(1)}{destino.resolve().as_uri()}{casado.group(3)}"

    padrao = r"(<img\b[^>]*?\bsrc=[\"'])(https?://[^\"']+)([\"'])"
    return re.sub(padrao, local, html_corpo)


def trocar_videos(html_corpo: str) -> str:
    """Vídeo não aparece em PDF: cada ``<video>`` vira um link para o arquivo."""

    def substituir(casado: re.Match[str]) -> str:
        bloco = casado.group(0)
        fonte = re.search(r'\bsrc=["\']([^"\']+)["\']', bloco)
        if not fonte:
            return '<p class="video-link">[Vídeo disponível no artigo original]</p>'
        endereco = html.escape(fonte.group(1), quote=True)
        return (
            f'<p class="video-link">[Vídeo no artigo original: '
            f'<a href="{endereco}">{endereco}</a>]</p>'
        )

    return re.sub(r"<video\b.*?</video>", substituir, html_corpo, flags=re.DOTALL | re.I)


def montar_html(
    artigo: Artigo,
    corpo_html: str,
    *,
    url_original: str,
    autor: str,
    licenca: str | None,
    titular: str | None,
    fonte: str | None,
) -> str:
    """Página completa: capa, corpo e rodapé com a nota de origem e a licença.

    Quando ``titulo_original`` é igual a ``titulo``, o texto não foi traduzido: a capa
    não repete o título e o rodapé fala em cópia, não em tradução.
    """

    e = html.escape
    linhas_fonte = f"<dt>Fonte</dt><dd>{e(fonte)}</dd>" if fonte else ""
    aviso_licenca = ""
    if licenca and licenca.upper() == "MIT":
        dono = e(titular or autor)
        aviso_licenca = (
            f"<p><strong>Copyright © {dono}.</strong> Texto original publicado sob a "
            f"licença MIT, reproduzida abaixo como ela exige em toda cópia.</p>"
            f"<pre>MIT License\n\nCopyright (c) {dono}\n\n{e(TEXTO_MIT)}</pre>"
        )
    elif licenca and licenca.upper().startswith("CC "):
        codigo = licenca.upper().removeprefix("CC ").split()[0].lower()
        versao = (licenca.split()[-1] if licenca.split()[-1][0].isdigit() else "4.0")
        url_licenca = f"https://creativecommons.org/licenses/{codigo}/{versao}/"
        aviso_licenca = (
            f"<p><strong>© {e(titular or autor)}.</strong> Texto publicado sob a licença "
            f"<a href=\"{url_licenca}\">Creative Commons {e(licenca.removeprefix('CC '))}</a>. "
            f"Esta cópia mantém a autoria e a mesma licença e serve só para leitura offline, sem "
            f"fins comerciais. A única adaptação é de formato: vídeos e elementos interativos "
            f"viraram links.</p>"
        )
    elif licenca:
        aviso_licenca = f"<p>Texto original publicado sob a licença {e(licenca)}.</p>"
    traduzido = artigo.titulo_original.strip() != artigo.titulo.strip()
    linha_original = (
        f'<p class="original">Título original: {e(artigo.titulo_original)}</p>' if traduzido else ""
    )
    if traduzido:
        nota = (
            "Tradução para o português feita para leitura offline. O texto original está em "
            f'<a href="{e(url_original, quote=True)}">{e(url_original)}</a>.'
        )
    else:
        nota = (
            "Cópia para leitura offline. O texto original está em "
            f'<a href="{e(url_original, quote=True)}">{e(url_original)}</a>.'
        )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{e(artigo.titulo)} — {e(autor)}</title>
<style>{CSS}</style></head>
<body>
<header class="capa">
<h1>{e(artigo.titulo)}</h1>
{linha_original}
<dl>
<dt>Autor</dt><dd>{e(autor)}</dd>
<dt>Publicado em</dt><dd>{data_por_extenso(artigo.data)}</dd>
<dt>Original</dt><dd><a href="{e(url_original, quote=True)}">{e(url_original)}</a></dd>
{linhas_fonte}
</dl>
</header>
<main>
{corpo_html}
</main>
<footer class="licenca">
<p>{nota}</p>
{aviso_licenca}
</footer>
</body></html>
"""


def achar_navegador(explicito: str | None) -> str:
    if explicito:
        return explicito
    for candidato in CANDIDATOS_NAVEGADOR:
        if Path(candidato).is_file():
            return candidato
    for nome in NOMES_NAVEGADOR:
        achado = shutil.which(nome)
        if achado:
            return achado
    raise Erro("nenhum navegador Chromium (Edge ou Chrome) encontrado; use --navegador")


# ---------------------------------------------------------------------------
# Conversão e impressão
# ---------------------------------------------------------------------------


def markdown_para_html(corpo: str) -> str:
    import markdown  # dependência declarada no cabeçalho do script (PEP 723)

    return markdown.markdown(
        corpo,
        extensions=["fenced_code", "tables", "footnotes", "md_in_html", "attr_list", "sane_lists"],
        output_format="html",
    )


def imprimir_pdf(
    navegador: str, pagina_html: Path, saida: Path, espera_ms: int, tempo_limite_s: int = 300
) -> None:
    with tempfile.TemporaryDirectory() as perfil:
        comando = [
            navegador,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={perfil}",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--virtual-time-budget={espera_ms}",
            f"--print-to-pdf={saida}",
            pagina_html.resolve().as_uri(),
        ]
        resultado = subprocess.run(
            comando, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=tempo_limite_s,
        )
    if not saida.is_file() or saida.stat().st_size == 0:
        raise Erro(f"o navegador não gerou o PDF: {resultado.stderr.strip()[-800:]}")


def gerar_pdf(
    texto: str,
    saida: Path,
    *,
    url_original: str,
    autor: str,
    licenca: str | None = None,
    titular: str | None = None,
    fonte: str | None = None,
    base_url: str | None = None,
    navegador: str | None = None,
    espera_ms: int = 8000,
    manter_html: bool = False,
    tempo_limite_s: int = 300,
    cache_imagens: Path | None = None,
) -> Path:
    """Gera o PDF de um Markdown com bloco de metadados; usado pelo CLI e por lotes."""

    artigo = ler_artigo(texto)
    partes = re.match(r"(https?://[^/]+)", url_original)
    raiz = base_url or (partes.group(1) if partes else "")
    corpo_html = trocar_videos(absolutizar(markdown_para_html(artigo.corpo), raiz))
    if cache_imagens is not None:
        corpo_html = reduzir_imagens(corpo_html, cache_imagens)
    pagina = montar_html(
        artigo,
        corpo_html,
        url_original=url_original,
        autor=autor,
        licenca=licenca,
        titular=titular,
        fonte=fonte,
    )
    saida.parent.mkdir(parents=True, exist_ok=True)
    arquivo_html = saida.with_suffix(".html")
    arquivo_html.write_text(pagina, encoding="utf-8")
    try:
        imprimir_pdf(achar_navegador(navegador), arquivo_html, saida, espera_ms, tempo_limite_s)
    finally:
        if not manter_html:
            os.unlink(arquivo_html)
    return saida


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("artigo", type=Path, help="Markdown com bloco de metadados")
    parser.add_argument("saida", type=Path, help="caminho do PDF")
    parser.add_argument("--url-original", required=True)
    parser.add_argument("--autor", required=True)
    parser.add_argument("--base-url", help="raiz para caminhos relativos (padrão: a do original)")
    parser.add_argument("--licenca", help="ex.: MIT (inclui aviso e texto da licença)")
    parser.add_argument("--titular", help="titular do copyright (padrão: o autor)")
    parser.add_argument("--fonte", help="de onde veio o texto, ex.: repositório@commit")
    parser.add_argument("--navegador", help="executável do Edge/Chrome")
    parser.add_argument("--espera-ms", type=int, default=8000, help="tempo para carregar imagens")
    parser.add_argument("--manter-html", action="store_true", help="grava o HTML ao lado do PDF")
    args = parser.parse_args(argv)
    try:
        gerar_pdf(
            args.artigo.read_text(encoding="utf-8"),
            args.saida,
            url_original=args.url_original,
            autor=args.autor,
            licenca=args.licenca,
            titular=args.titular,
            fonte=args.fonte,
            base_url=args.base_url,
            navegador=args.navegador,
            espera_ms=args.espera_ms,
            manter_html=args.manter_html,
        )
    except Erro as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    print(args.saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
