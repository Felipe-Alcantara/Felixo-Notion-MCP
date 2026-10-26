"""Confere os links relativos dos Markdown versionados: o arquivo de destino e a âncora.

O Guia Mínimo de Qualidade pede "links internos válidos" antes de dar uma entrega por pronta.
Este script faz essa conferência de forma repetível, em vez de abrir os arquivos um a um: lê os
`.md` que o git versiona, acha cada `[texto](caminho#âncora)` e confere se o arquivo existe e se
a âncora é de um título do arquivo de destino. Links `http(s)`, `mailto:` e o conteúdo de blocos
e trechos de código são ignorados.

Fora da conferência ficam `docs/ia-archive/` (histórico preservado como foi escrito, com caminhos
de repositórios que não existem mais) e as skills dos agentes em `.agents/` e `.claude/`.

A âncora segue a regra do GitHub: minúsculas, pontuação removida, espaços viram hífen. Marcas
combinantes, como o U+FE0F que acompanha vários emojis, **permanecem**, por isso `## ⚠️ Limites`
vira `#️-limites` (com o U+FE0F antes do hífen), e título repetido ganha o sufixo `-1`, `-2`.

Uso: `python -m scripts.qualidade.verificar_links [raiz]`. Sai com 1 se houver problema.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

PREFIXOS_IGNORADOS = ("docs/ia-archive/", ".agents/", ".claude/")
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODIGO_EM_LINHA = re.compile(r"`[^`\n]*`")
_TITULO = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_CERCA = re.compile(r"^\s*(```|~~~)")
_EXTERNO = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


@dataclass(frozen=True)
class Problema:
    """Um link que não leva a lugar nenhum."""

    arquivo: str
    linha: int
    alvo: str
    motivo: str

    def __str__(self) -> str:
        return f"{self.arquivo}:{self.linha}: {self.motivo} -> {self.alvo}"


def slug_do_titulo(titulo: str) -> str:
    """Âncora que o GitHub gera para o texto de um título (sem o sufixo de repetição)."""

    texto = re.sub(r"[`*_]", "", titulo).strip().lower()
    mantidos = (
        c
        for c in texto
        if c.isalnum() or c in "-_ \t" or unicodedata.category(c).startswith("M")
    )
    return re.sub(r"\s", "-", "".join(mantidos))


def ancoras_do_texto(texto: str) -> set[str]:
    """Âncoras dos títulos de um Markdown, fora de blocos de código, com o sufixo de repetição."""

    vistas: dict[str, int] = {}
    ancoras: set[str] = set()
    em_cerca = False
    for linha in texto.splitlines():
        if _CERCA.match(linha):
            em_cerca = not em_cerca
            continue
        achado = None if em_cerca else _TITULO.match(linha)
        if achado is None:
            continue
        base = slug_do_titulo(achado.group(1))
        repeticao = vistas.get(base, 0)
        vistas[base] = repeticao + 1
        ancoras.add(base if repeticao == 0 else f"{base}-{repeticao}")
    return ancoras


def deve_ignorar(caminho_relativo: str) -> bool:
    """Diz se o arquivo está fora da conferência (histórico e skills dos agentes)."""

    return caminho_relativo.startswith(PREFIXOS_IGNORADOS)


def listar_markdown(raiz: Path) -> list[str]:
    """Os `.md` versionados, como caminhos relativos com `/` (a lista do `git ls-files`)."""

    saida = subprocess.run(
        # `-z`: sem ele o git escapa nomes com acento ("Padr\303\243o.md") e o caminho não abre.
        ["git", "ls-files", "-z", "*.md"],
        cwd=raiz,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return [nome for nome in saida.split("\0") if nome and not deve_ignorar(nome)]


def _links_do_arquivo(texto: str) -> list[tuple[int, str]]:
    """Cada link `(linha, alvo)` fora de blocos e trechos de código."""

    achados: list[tuple[int, str]] = []
    em_cerca = False
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if _CERCA.match(linha):
            em_cerca = not em_cerca
            continue
        if em_cerca:
            continue
        sem_codigo = _CODIGO_EM_LINHA.sub("", linha)
        achados += [(numero, alvo) for alvo in _LINK.findall(sem_codigo)]
    return achados


def verificar(raiz: Path, arquivos: list[str] | None = None) -> list[Problema]:
    """Confere os links dos `arquivos` (padrão: os Markdown versionados) a partir de `raiz`."""

    raiz = raiz.resolve()
    ancoras_por_arquivo: dict[Path, set[str]] = {}
    problemas: list[Problema] = []
    for relativo in listar_markdown(raiz) if arquivos is None else arquivos:
        origem = raiz / PurePosixPath(relativo)
        for numero, alvo in _links_do_arquivo(origem.read_text(encoding="utf-8")):
            if _EXTERNO.match(alvo):
                continue
            caminho, _, fragmento = alvo.partition("#")
            destino = origem if not caminho else (origem.parent / unquote(caminho)).resolve()
            if not destino.exists():
                problemas.append(Problema(relativo, numero, alvo, "arquivo inexistente"))
                continue
            if not fragmento or destino.suffix != ".md" or not destino.is_file():
                continue
            ancoras = ancoras_por_arquivo.setdefault(
                destino, ancoras_do_texto(destino.read_text(encoding="utf-8"))
            )
            if unicodedata.normalize("NFC", unquote(fragmento).lower()) not in ancoras:
                problemas.append(Problema(relativo, numero, alvo, "âncora inexistente"))
    return problemas


def main(argv: list[str] | None = None) -> int:
    """Confere os links e lista os problemas; sai com 1 se houver algum."""

    parser = argparse.ArgumentParser(
        description="Confere os links relativos dos Markdown versionados."
    )
    parser.add_argument("raiz", nargs="?", default=".", help="raiz do repositório (padrão: .)")
    args = parser.parse_args(argv)

    # Os alvos têm emoji e acento; o console do Windows (cp1252) não os imprimiria.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raiz = Path(args.raiz)
    arquivos = listar_markdown(raiz.resolve())
    problemas = verificar(raiz, arquivos)
    for problema in problemas:
        print(problema)
    print(f"{len(problemas)} problema(s) em {len(arquivos)} arquivo(s) .md")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
