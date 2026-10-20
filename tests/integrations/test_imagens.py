"""Testes da redução, compressão até caber e geração de capas (Pillow)."""

from __future__ import annotations

import pytest

pil = pytest.importorskip("PIL.Image")

from felixo_notion_mcp.integrations import imagens  # noqa: E402


@pytest.fixture
def foto(tmp_path):
    import random

    caminho = tmp_path / "foto.png"
    imagem = pil.new("RGB", (3000, 2000))
    r = random.Random(1)
    imagem.putdata(
        [(r.randrange(256), r.randrange(256), r.randrange(256)) for _ in range(3000 * 2000)]
    )
    imagem.save(caminho)
    return caminho


def test_reduzir_limita_a_largura_e_mantem_a_proporcao(foto, tmp_path):
    saida = imagens.reduzir(foto, tmp_path / "r.jpg", largura_max=1000)
    with pil.open(saida) as reduzida:
        assert reduzida.size == (1000, 667)


def test_caber_em_respeita_o_limite_de_bytes(foto, tmp_path):
    saida = imagens.caber_em(foto, tmp_path / "c.jpg", 300_000)
    assert saida.stat().st_size <= 300_000


def test_gerar_capa_tem_o_tamanho_de_capa_e_e_deterministica(tmp_path):
    a = imagens.gerar_capa(
        "Um título bem comprido para quebrar em linhas", "Autor", tmp_path / "a.png"
    )
    b = imagens.gerar_capa(
        "Um título bem comprido para quebrar em linhas", "Autor", tmp_path / "b.png"
    )
    with pil.open(a) as capa:
        assert capa.size == (1500, 600)
    assert a.read_bytes() == b.read_bytes()
