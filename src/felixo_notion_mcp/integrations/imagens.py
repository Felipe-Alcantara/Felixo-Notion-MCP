"""Integração com o Pillow: reduzir, comprimir até caber e gerar capas originais.

- :func:`reduzir` limita a largura e grava JPEG (fotos de câmera viram cópias leves);
- :func:`caber_em` reduz qualidade e largura até o arquivo caber num limite de bytes
  (ex.: 5 MiB do upload do Notion no plano gratuito);
- :func:`gerar_capa` desenha uma capa 1500x600 só com tipografia e formas abstratas,
  para páginas sem imagem própria.

O Pillow vem do extra opcional ``[biblioteca]``; ele é importado só quando usado.
"""

from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path

LARGURA_CAPA, ALTURA_CAPA = 1500, 600

#: Paletas por estilo: fundo (início, fim), cor do texto, cores das formas.
ESTILOS: dict[str, tuple[tuple[str, str], str, tuple[str, ...]]] = {
    "claro": (("#f6fbff", "#f3e9ff"), "#23324a", ("#7fd1c9", "#a7c7f2", "#c9a7f2", "#f2c4d8")),
    "noite": (("#1d2a55", "#05070f"), "#e8eeff", ("#e8f0ff",)),
    "tecnico": (("#0f3b66", "#0b2a4a"), "#ffffff", ("#9fd3ff",)),
    "terminal": (("#050a07", "#0b1510"), "#7dffb0", ("#33ff88",)),
    "epico": (("#4a1414", "#1a0606"), "#fbe7c0", ("#f4c86a",)),
    "audio": (("#3b1f6b", "#b0458f"), "#ffffff", ("#ffffff",)),
    "quente": (("#f08a4b", "#f7d58a"), "#3a1f0e", ("#fff4dc",)),
    "papel": (("#f7f3ea", "#efe8d8"), "#1f1f1f", ("#2b2b2b",)),
}


def _pil():
    from PIL import Image, ImageDraw, ImageFont  # extra opcional [biblioteca]

    return Image, ImageDraw, ImageFont


def reduzir(origem: Path, destino: Path, *, largura_max: int = 1400, qualidade: int = 82) -> Path:
    """Grava ``destino`` em JPEG com no máximo ``largura_max`` px de largura."""

    image, _, _ = _pil()
    with image.open(origem) as imagem:
        imagem = imagem.convert("RGB")
        if imagem.width > largura_max:
            imagem = imagem.resize((largura_max, round(imagem.height * largura_max / imagem.width)))
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        imagem.save(destino, "JPEG", quality=qualidade, optimize=True)
    return Path(destino)


def caber_em(
    origem: Path, destino: Path, limite_bytes: int, *, largura_inicial: int = 1600
) -> Path:
    """Reduz qualidade e depois largura até ``destino`` ter no máximo ``limite_bytes``.

    Raises:
        ValueError: se nem com 320 px e qualidade 40 couber.
    """

    largura = largura_inicial
    while largura >= 320:
        for qualidade in (85, 75, 65, 55, 40):
            reduzir(origem, destino, largura_max=largura, qualidade=qualidade)
            if Path(destino).stat().st_size <= limite_bytes:
                return Path(destino)
        largura = int(largura * 0.75)
    raise ValueError(f"{origem}: não coube em {limite_bytes} bytes nem reduzida ao mínimo")


def _fonte(tamanho: int, negrito: bool = False):
    _, _, image_font = _pil()
    nomes = (
        ["georgiab.ttf", "arialbd.ttf", "DejaVuSerif-Bold.ttf"]
        if negrito
        else ["georgia.ttf", "arial.ttf", "DejaVuSerif.ttf"]
    )
    for nome in nomes:
        try:
            return image_font.truetype(nome, tamanho)
        except OSError:
            continue
    return image_font.load_default(tamanho)


def _quebrar(texto: str, fonte, largura: int, desenho) -> list[str]:
    linhas: list[str] = []
    atual = ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if desenho.textlength(tentativa, font=fonte) <= largura or not atual:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    return [*linhas, atual] if atual else linhas


def gerar_capa(
    titulo: str, subtitulo: str, destino: Path, *, estilo: str = "claro", semente: str | None = None
) -> Path:
    """Desenha uma capa original (tipografia + formas abstratas) e grava em PNG."""

    image, image_draw, _ = _pil()
    (inicio, fim), cor_texto, cores = ESTILOS.get(estilo, ESTILOS["claro"])
    r = random.Random(int(hashlib.sha256((semente or titulo).encode()).hexdigest()[:12], 16))
    capa = image.new("RGB", (LARGURA_CAPA, ALTURA_CAPA), inicio)
    desenho = image_draw.Draw(capa, "RGBA")

    a, b = (
        image.new("RGB", (1, 1), inicio).getpixel((0, 0)),
        image.new("RGB", (1, 1), fim).getpixel((0, 0)),
    )
    for x in range(LARGURA_CAPA):
        t = x / LARGURA_CAPA
        desenho.line(
            [(x, 0), (x, ALTURA_CAPA)],
            fill=tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)),
        )
    for _ in range(18):
        cx, cy, raio = r.uniform(700, 1500), r.uniform(-50, 650), r.uniform(30, 140)
        lados = r.choice([4, 5, 6])
        pontos = [
            (
                cx + raio * math.cos(6.283 * i / lados + r.random()),
                cy + raio * math.sin(6.283 * i / lados + r.random()),
            )
            for i in range(lados)
        ]
        cor = image.new("RGB", (1, 1), r.choice(cores)).getpixel((0, 0))
        desenho.polygon(pontos, fill=(*cor, r.randint(50, 140)))

    fonte_titulo = _fonte(68 if len(titulo) < 30 else 54 if len(titulo) < 55 else 44, negrito=True)
    linhas = _quebrar(titulo, fonte_titulo, 640, desenho)[:4]
    altura_linha = fonte_titulo.size + 10
    y = (ALTURA_CAPA - altura_linha * len(linhas) - 60) // 2
    desenho.rectangle([90, y - 30, 180, y - 25], fill=cor_texto)
    for linha in linhas:
        desenho.text((90, y), linha, font=fonte_titulo, fill=cor_texto)
        y += altura_linha
    desenho.text((90, y + 16), subtitulo, font=_fonte(26), fill=cor_texto)
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    capa.save(destino, "PNG", optimize=True)
    return Path(destino)
