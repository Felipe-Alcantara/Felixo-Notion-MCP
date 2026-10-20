"""Testes da parte sem navegador do gerador de PDF de artigos."""

from __future__ import annotations

import pytest
from scripts.notion import artigo_para_pdf as gerador

ARTIGO = """---
titulo_original: "Staying \\"Sharp\\""
titulo: "Mantendo o fio"
data: 2026-09-22
descricao: ""
---

Corpo **traduzido**.
"""


def test_le_metadados_e_corpo():
    artigo = gerador.ler_artigo(ARTIGO)
    assert artigo.titulo == "Mantendo o fio"
    assert artigo.titulo_original == 'Staying "Sharp"'
    assert artigo.data == "2026-09-22"
    assert artigo.descricao == ""
    assert artigo.corpo == "Corpo **traduzido**."


def test_sem_metadados_ou_sem_titulo_e_recusado():
    with pytest.raises(gerador.Erro, match="bloco de metadados"):
        gerador.ler_artigo("Só corpo.")
    with pytest.raises(gerador.Erro, match="titulo"):
        gerador.ler_artigo('---\ntitulo_original: "x"\ndata: 2026-01-01\n---\ncorpo')


def test_data_por_extenso():
    assert gerador.data_por_extenso("2026-03-05") == "5 de março de 2026"


def test_caminhos_relativos_viram_absolutos_e_os_demais_ficam():
    html = (
        '<img src="/assets/a.png"><a href="/post/">x</a>'
        '<img src="//cdn.exemplo/b.png"><img src="https://outro/c.png"><a href="#ancora">y</a>'
    )
    resultado = gerador.absolutizar(html, "https://rapha.land/")
    assert 'src="https://rapha.land/assets/a.png"' in resultado
    assert 'href="https://rapha.land/post/"' in resultado
    assert 'src="//cdn.exemplo/b.png"' in resultado
    assert 'src="https://outro/c.png"' in resultado
    assert 'href="#ancora"' in resultado


def test_video_vira_link_para_o_arquivo():
    html = '<p>a</p><video controls>\n<source src="https://x/v.webm">\nTexto</video><p>b</p>'
    resultado = gerador.trocar_videos(html)
    assert "<video" not in resultado
    assert '<a href="https://x/v.webm">' in resultado
    assert resultado.startswith("<p>a</p>") and resultado.endswith("<p>b</p>")


def test_pagina_traz_capa_e_licenca_mit_com_aviso_de_copyright():
    artigo = gerador.ler_artigo(ARTIGO)
    pagina = gerador.montar_html(
        artigo,
        "<p>corpo</p>",
        url_original="https://rapha.land/staying-sharp/",
        autor="Raphael Amorim",
        licenca="MIT",
        titular=None,
        fonte="repo@abc123",
    )
    assert "<h1>Mantendo o fio</h1>" in pagina
    assert "Título original: Staying &quot;Sharp&quot;" in pagina
    assert "22 de setembro de 2026" in pagina
    assert "Copyright (c) Raphael Amorim" in pagina
    assert "The above copyright notice and this permission notice" in pagina
    assert "repo@abc123" in pagina


def test_sem_licenca_nao_inventa_aviso():
    artigo = gerador.ler_artigo(ARTIGO)
    pagina = gerador.montar_html(
        artigo, "", url_original="https://x/", autor="A", licenca=None, titular=None, fonte=None
    )
    assert "MIT" not in pagina
    assert "Copyright" not in pagina


def test_navegador_explicito_tem_prioridade():
    assert gerador.achar_navegador("C:/meu/navegador.exe") == "C:/meu/navegador.exe"


def test_texto_sem_traducao_nao_fala_em_titulo_original_nem_em_traducao():
    artigo = gerador.Artigo(
        titulo="Rails Manifesto", titulo_original="Rails Manifesto", data="2006-04-11",
        descricao="", corpo="",
    )
    pagina = gerador.montar_html(
        artigo, "", url_original="https://akitaonrails.com/x/", autor="Fabio Akita",
        licenca="CC BY-NC-SA 4.0", titular=None, fonte=None,
    )
    assert "Título original" not in pagina
    assert "Tradução" not in pagina
    assert "Cópia para leitura offline" in pagina


def test_licenca_creative_commons_traz_atribuicao_e_link_da_licenca():
    artigo = gerador.ler_artigo(ARTIGO)
    pagina = gerador.montar_html(
        artigo, "", url_original="https://x/", autor="Fabio Akita",
        licenca="CC BY-NC-SA 4.0", titular=None, fonte=None,
    )
    assert "© Fabio Akita" in pagina
    assert "https://creativecommons.org/licenses/by-nc-sa/4.0/" in pagina
    assert "sem fins comerciais" in pagina
    assert "MIT" not in pagina


def test_reduzir_imagens_troca_url_por_copia_local_menor(tmp_path, monkeypatch):
    image = pytest.importorskip("PIL.Image")
    import io

    original = io.BytesIO()
    image.new("RGB", (3000, 1500), "red").save(original, "PNG")

    class Resposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    chamadas = []

    def abrir(pedido, timeout, context=None):
        chamadas.append(pedido.full_url)
        if "quebrada" in pedido.full_url:
            raise OSError("404")
        return Resposta(original.getvalue())

    monkeypatch.setattr("urllib.request.urlopen", abrir)
    html = '<img src="https://s3/foto.png"><img src="https://s3/foto.png"><img src="https://s3/quebrada.png">'
    resultado = gerador.reduzir_imagens(html, tmp_path, largura_max=1000)

    copias = list(tmp_path.glob("*.jpg"))
    assert len(copias) == 1
    with image.open(copias[0]) as reduzida:
        assert reduzida.size == (1000, 500)
    assert resultado.count(copias[0].resolve().as_uri()) == 2
    assert 'src="https://s3/quebrada.png"' in resultado
    assert chamadas.count("https://s3/foto.png") == 1  # o cache evita baixar de novo
