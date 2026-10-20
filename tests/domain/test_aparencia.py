"""Testes das regras puras de ícone e capa de página."""

from __future__ import annotations

import pytest

from felixo_notion_mcp.domain import aparencia


@pytest.mark.parametrize(
    ("valor", "tipo"),
    [
        ("📚", "emoji"),
        ("🧑‍💻", "emoji"),
        (" https://exemplo.dev/capa.jpg ", "externo"),
        ("HTTP://exemplo.dev/i.png", "externo"),
        ("C:/capas/livro.PNG", "arquivo"),
        ("capa.webp", "arquivo"),
        ("icone.svg", "arquivo"),
    ],
)
def test_classifica_emoji_url_e_arquivo(valor, tipo):
    assert aparencia.classificar(valor) == tipo


@pytest.mark.parametrize("valor", ["", "   ", "livro", "capa.pdf", "ftp://x/y.png"])
def test_recusa_o_que_nao_e_imagem(valor):
    with pytest.raises(ValueError):
        aparencia.classificar(valor)


def test_monta_os_objetos_da_api():
    assert aparencia.emoji(" 📘 ") == {"type": "emoji", "emoji": "📘"}
    assert aparencia.externa("https://x/c.jpg") == {
        "type": "external",
        "external": {"url": "https://x/c.jpg"},
    }
    assert aparencia.enviada("up-1") == {"type": "file_upload", "file_upload": {"id": "up-1"}}


def test_descreve_o_que_a_pagina_ja_tem():
    assert aparencia.descrever(None) is None
    assert aparencia.descrever({"type": "emoji", "emoji": "📘"}) == "📘"
    assert aparencia.descrever({"type": "external", "external": {"url": "https://x"}}) == "https://x"
    assert aparencia.descrever({"type": "file", "file": {"url": "https://s3"}}) == "(file)"
