"""Testes do verificador de links dos Markdown (``scripts.qualidade.verificar_links``)."""

import shutil
import subprocess

import pytest
from scripts.qualidade import verificar_links as vl
from scripts.qualidade.verificar_links import (
    ancoras_do_texto,
    deve_ignorar,
    listar_markdown,
    main,
    slug_do_titulo,
    verificar,
)


def _arquivo(raiz, nome, texto):
    caminho = raiz / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return nome


def _motivos(problemas):
    return [(p.arquivo, p.linha, p.motivo) for p in problemas]


def test_slug_do_titulo_mantem_a_marca_combinante_do_emoji():
    # O GitHub grava o U+FE0F no identificador: sem ele, o link do índice quebra.
    assert slug_do_titulo("⚠️ Limites atuais") == "️-limites-atuais"
    assert slug_do_titulo("📋 Índice") == "-índice"
    assert slug_do_titulo("O `uso` *comum*, 1.0!") == "o-uso-comum-10"


def test_titulo_repetido_ganha_sufixo_numerico():
    assert ancoras_do_texto("# A\n## A\n## A\n") == {"a", "a-1", "a-2"}


def test_titulo_dentro_de_bloco_de_codigo_nao_vira_ancora():
    assert ancoras_do_texto("```md\n# falso\n```\n# Real\n") == {"real"}


def test_link_valido_para_arquivo_e_ancora_nao_gera_problema(tmp_path):
    # A âncora do GitHub para "## ⚠️ Limites" é só o U+FE0F mais "-limites": o emoji em si sai.
    link = "[guia](docs/guia.md#️-limites) [topo](#inicio)\n# Inicio\n"
    _arquivo(tmp_path, "README.md", link)
    _arquivo(tmp_path, "docs/guia.md", "## ⚠️ Limites\n")

    assert verificar(tmp_path, ["README.md"]) == []


def test_arquivo_inexistente_e_apontado_com_a_linha(tmp_path):
    _arquivo(tmp_path, "README.md", "texto\n[some](docs/some.md)\n")

    assert _motivos(verificar(tmp_path, ["README.md"])) == [("README.md", 2, "arquivo inexistente")]


def test_ancora_sem_o_seletor_de_variacao_do_emoji_e_apontada(tmp_path):
    # Foi o defeito real do índice de INTEGRACOES.md: o link sem o U+FE0F não leva ao título.
    _arquivo(tmp_path, "README.md", "[guia](docs/guia.md#-limites)\n")
    _arquivo(tmp_path, "docs/guia.md", "## ⚠️ Limites\n")

    assert _motivos(verificar(tmp_path, ["README.md"])) == [
        ("README.md", 1, "âncora inexistente")
    ]


def test_ancora_do_proprio_arquivo_inexistente_e_apontada(tmp_path):
    _arquivo(tmp_path, "README.md", "# Um\n[ir](#dois)\n")

    assert _motivos(verificar(tmp_path, ["README.md"])) == [("README.md", 2, "âncora inexistente")]


def test_externos_codigo_e_cercas_nao_sao_conferidos(tmp_path):
    _arquivo(
        tmp_path,
        "README.md",
        "[site](https://exemplo.org/x) [mail](mailto:a@b.c) `[no código](nada.md)`\n"
        "```md\n[em bloco](nada.md)\n```\n",
    )

    assert verificar(tmp_path, ["README.md"]) == []


def test_imagem_inexistente_tambem_e_apontada(tmp_path):
    _arquivo(tmp_path, "README.md", "![logo](img/logo.png)\n")

    assert _motivos(verificar(tmp_path, ["README.md"])) == [("README.md", 1, "arquivo inexistente")]


def test_ancora_em_arquivo_que_nao_e_markdown_nao_e_conferida(tmp_path):
    _arquivo(tmp_path, "README.md", "[linha](src/codigo.py#L10)\n")
    _arquivo(tmp_path, "src/codigo.py", "x = 1\n")

    assert verificar(tmp_path, ["README.md"]) == []


def test_historico_e_skills_dos_agentes_ficam_fora_da_conferencia():
    assert deve_ignorar("docs/ia-archive/IA-ARCHIVE-2026-06.md")
    assert deve_ignorar(".agents/skills/x/SKILL.md")
    assert deve_ignorar(".claude/skills/x/SKILL.md")
    assert not deve_ignorar("docs/ARQUITETURA.md")


@pytest.mark.skipif(shutil.which("git") is None, reason="precisa do git")
def test_listar_markdown_usa_o_que_o_git_versiona(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _arquivo(tmp_path, "README.md", "# a\n")
    _arquivo(tmp_path, "docs/ia-archive/velho.md", "# velho\n")
    _arquivo(tmp_path, "docs/Padrão de qualidade.md", "# acento no nome\n")
    _arquivo(tmp_path, "solto.md", "# fora do git\n")
    versionados = ["README.md", "docs/ia-archive/velho.md", "docs/Padrão de qualidade.md"]
    subprocess.run(["git", "add", *versionados], cwd=tmp_path, check=True)

    # O git escaparia o nome com acento sem `-z`; o arquivo do histórico fica de fora.
    assert listar_markdown(tmp_path) == ["README.md", "docs/Padrão de qualidade.md"]


def test_main_lista_os_problemas_e_sai_com_1(tmp_path, monkeypatch, capsys):
    _arquivo(tmp_path, "README.md", "[some](nada.md)\n")
    monkeypatch.setattr(vl, "listar_markdown", lambda raiz: ["README.md"])

    assert main([str(tmp_path)]) == 1
    saida = capsys.readouterr().out
    assert "README.md:1: arquivo inexistente -> nada.md" in saida
    assert "1 problema(s) em 1 arquivo(s) .md" in saida


def test_main_sai_com_0_quando_esta_tudo_certo(tmp_path, monkeypatch, capsys):
    _arquivo(tmp_path, "README.md", "# ok\n[topo](#ok)\n")
    monkeypatch.setattr(vl, "listar_markdown", lambda raiz: ["README.md"])

    assert main([str(tmp_path)]) == 0
    assert "0 problema(s) em 1 arquivo(s) .md" in capsys.readouterr().out
