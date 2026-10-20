"""Testes da parte pura do script que transforma um blog Hugo em rascunhos da biblioteca."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

pytest.importorskip("yaml")  # o script declara pyyaml no cabeçalho PEP 723

from scripts.notion import blog_hugo_para_biblioteca as blog  # noqa: E402

MAPA = {
    "regras": [
        {"nome": "Vídeos", "tags": ["akitando"], "icone": "🎬", "capa": "capa-video"},
        {"nome": "IA", "tags": ["llms"], "icone": "🤖", "area": ["Programação"],
         "genres": ["Computer Scinece"], "capa": "capa-ia"},
        {"nome": "Negócios", "tags": ["negocios"], "icone": "💼", "area": ["Dinheiro"],
         "genres": ["Business and Economics"], "capa": "capa-negocios"},
    ],
    "padrao": {"icone": "📝", "area": ["Programação"], "genres": ["Computer Scinece"],
               "capa": "capa-padrao"},
}


def test_url_usa_slug_no_lugar_da_pasta_e_respeita_url_explicita():
    raiz = Path("content")
    pasta = raiz / "2026" / "07" / "19" / "pasta-antiga"
    assert blog.url_do_post({"slug": "novo-slug"}, pasta, raiz, "https://blog.dev/") == (
        "https://blog.dev/2026/07/19/novo-slug/"
    )
    assert blog.url_do_post({}, pasta, raiz, "https://blog.dev") == (
        "https://blog.dev/2026/07/19/pasta-antiga/"
    )
    assert blog.url_do_post({"url": "/sobre"}, pasta, raiz, "https://blog.dev") == (
        "https://blog.dev/sobre/"
    )


def test_data_vem_do_front_matter_ou_do_caminho():
    pasta = Path("content/2009/09/17/post")
    assert blog.data_do_post({"date": "2010-01-02T10:00:00-0300"}, pasta) == dt.date(2010, 1, 2)
    assert blog.data_do_post({"date": dt.datetime(2011, 3, 4, 5)}, pasta) == dt.date(2011, 3, 4)
    assert blog.data_do_post({}, pasta) == dt.date(2009, 9, 17)
    with pytest.raises(blog.Erro):
        blog.data_do_post({}, Path("content/sem-data"))


def test_tags_viram_o_nome_canonico_sem_repetir():
    taxonomia = {
        "tags": {"artificial_intelligence": {"pt": "inteligencia-artificial",
                                             "en": "artificial-intelligence",
                                             "aliases": ["ai", "ia"]}},
        "special_tags": {"off_topic": {"pt": "off-topic"}},
        "event_series": {"railsconf2008": {"aliases": ["railsconf2008"]}},
    }
    aliases = blog.carregar_aliases(taxonomia)
    assert blog.normalizar_tags(["IA", "ai", "artificial-intelligence", "Off_Topic", "nova"],
                                aliases) == ["inteligencia-artificial", "off-topic", "nova"]
    assert blog.normalizar_tags(["off_topic", "railsconf2008"], aliases) == [
        "off-topic", "railsconf2008",
    ]


def test_classificacao_usa_a_primeira_regra_para_icone_e_junta_area_e_genres():
    resultado = blog.classificar(["negocios", "llms", "akitando"], MAPA)
    assert resultado["icone"] == "🎬"
    assert resultado["capa"] == "capa-video"
    assert resultado["area"] == ["Programação", "Dinheiro"]
    assert resultado["genres"] == ["Computer Scinece", "Business and Economics"]
    padrao = blog.classificar(["desconhecida"], MAPA)
    assert padrao["icone"] == "📝"
    assert padrao["area"] == ["Programação"]
    assert padrao["capa"] == "capa-padrao"


def test_shortcodes_de_video_viram_link_e_os_demais_somem():
    corpo = 'Antes\n{{< youtube abcDEF12345 >}}\n{{< youtube id="xyz98765" >}}\n' \
            "{{< html >}}<b>ok</b>{{< /html >}}\n{{% outro %}}Depois"
    convertido, videos = blog.trocar_shortcodes(corpo)
    assert videos == ["abcDEF12345", "xyz98765"]
    assert "https://www.youtube.com/watch?v=abcDEF12345" in convertido
    assert "<b>ok</b>" in convertido
    assert "{{" not in convertido


def test_primeira_imagem_e_links_ignoram_imagens_na_lista_de_links():
    corpo = "[![alt](https://img.dev/a.png)](https://x.com/p)\ntexto [doc](https://doc.dev/)"
    assert blog.primeira_imagem(corpo) == "https://img.dev/a.png"
    assert blog.links_do_corpo(corpo) == ["https://x.com/p", "https://doc.dev/"]
    assert blog.primeira_imagem("sem imagem") is None


def test_nome_de_arquivo_tira_caracteres_proibidos():
    assert blog.nome_de_arquivo('A: "B" / C? <D>|*') == "A B  C D"
    assert blog.nome_de_arquivo("...") == "sem-titulo"


def test_posts_do_mesmo_dia_com_o_mesmo_titulo_ganham_arquivos_distintos(tmp_path: Path):
    def post(slug: str) -> blog.Post:
        return blog.Post(
            pasta=tmp_path, titulo="Visão do Passado", data=dt.date(2013, 5, 26), slug=slug,
            url=f"https://blog/{slug}/", descricao="", tags=[], corpo="",
        )

    a, b, c = post("visao"), post("visao--2"), post("outro")
    c.titulo = "Outro"
    blog.desambiguar([b, a, c])
    caminhos = {blog.caminho_pdf(tmp_path, p).name for p in (a, b, c)}
    assert caminhos == {
        "2013-05-26 Visão do Passado.pdf",
        "2013-05-26 Visão do Passado (2).pdf",
        "2013-05-26 Outro.pdf",
    }
