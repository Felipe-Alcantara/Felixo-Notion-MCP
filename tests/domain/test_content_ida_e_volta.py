"""Ida e volta Notion -> Markdown -> Notion de trechos com marcador (``*``, ``_``, ``~``, ``\\``).

A 0.4.1 casa a ênfase pelo algoritmo do CommonMark, e isso deixou de fora a ida e volta de
três famílias (medido num diferencial sintético de semente fixa):

* **A**: trecho formatado que começa ou termina com o próprio marcador (tachado de ``~``,
  itálico de ``*x``);
* **P**: marcador solto em texto sem formatação (``a*b e c*d``, ``__init__.py``);
* **B**: trechos seguidos de formatações diferentes (``~~a~~~~b~~``: quatro ``~`` não são
  marcador; ``**a**`` e ``*b*`` colados).

A leitura escapa com barra o que a releitura tomaria por marcador (só quando precisa, para
``snake_case_name`` e ``2 * 3 * 4`` continuarem como estão), junta tachado e itálico de
trechos vizinhos sob um marcador só e usa ``_`` no itálico colado em outra ênfase. A escrita
trata a barra do CommonMark: pontuação escapada vira texto.

**Limite do formato** (``test_cadeia_de_tres_trechos_entre_letras_...``): três trechos seguidos
de negrito e itálico, com letra colada dos dois lados, não têm leitura única em Markdown. O
``_`` não pode abrir nem fechar junto de letra e o ``**`` entre letras abre e fecha ao mesmo
tempo, então a releitura erra o trecho do meio.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from felixo_notion_mcp.domain.content import blocos_para_markdown, markdown_para_blocos

URL = "https://x.dev/p"


def _item(texto: str, link: str | None = None, **anotacoes: bool) -> dict[str, Any]:
    item: dict[str, Any] = {"type": "text", "text": {"content": texto}, "plain_text": texto}
    if link:
        item["text"]["link"] = {"url": link}
    if anotacoes:
        item["annotations"] = dict(anotacoes)
    return item


def _paragrafo(*itens: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "paragraph": {"rich_text": list(itens)}}


def _forma(itens: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    """Caractere a caractere, com o que o Markdown representa. Espaço não carrega formatação."""

    texto = "".join(i["text"]["content"] for i in itens)
    inicio, fim = len(texto) - len(texto.lstrip()), len(texto.rstrip())
    saida: list[tuple[str, Any]] = []
    posicao = 0
    for item in itens:
        anot = item.get("annotations") or {}
        formato = (
            bool(anot.get("code")),
            bool(anot.get("bold")),
            bool(anot.get("italic")),
            bool(anot.get("strikethrough")),
            (item["text"].get("link") or {}).get("url"),
        )
        for caractere in item["text"]["content"]:
            if inicio <= posicao < fim:
                saida.append((caractere, None if caractere.isspace() else formato))
            posicao += 1
    return saida


def _ida_e_volta(*itens: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    markdown = blocos_para_markdown([_paragrafo(*itens)])
    blocos = markdown_para_blocos(markdown)
    assert [b["type"] for b in blocos] == ["paragraph"], (markdown, blocos)
    return markdown, blocos[0]["paragraph"]["rich_text"]


def _volta_igual(*itens: dict[str, Any]) -> str:
    markdown, volta = _ida_e_volta(*itens)
    assert _forma(volta) == _forma(list(itens)), markdown
    return markdown


def _markdown(*itens: dict[str, Any]) -> str:
    return blocos_para_markdown([_paragrafo(*itens)])


# -- A: o conteúdo do trecho formatado começa ou termina com o próprio marcador --------------


@pytest.mark.parametrize(
    "anotacoes",
    [
        {"bold": True},
        {"italic": True},
        {"strikethrough": True},
        {"bold": True, "italic": True},
        {"bold": True, "strikethrough": True},
    ],
)
@pytest.mark.parametrize(
    "conteudo",
    ["*x", "x*", "*x*", "_x", "x_", "~x", "x~", "~~x", "x~~", "**x", "x**", "a*b", "a_b", "a~~b"],
)
def test_trecho_formatado_com_marcador_na_borda_volta_igual(anotacoes, conteudo):
    _volta_igual(_item("antes "), _item(conteudo, **anotacoes), _item(" depois"))


# -- P: marcador solto em texto sem formatação ----------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "a*b e c*d",
        "a_b e c_d",
        "__init__.py",
        "use _x_ ou *y* literal",
        "x ~~não é tachado~~ y",
        "*começa com marcador",
        "termina com marcador*",
        "a ** b ** c",
    ],
)
def test_marcador_solto_em_texto_simples_volta_igual(texto):
    _volta_igual(_item("Veja: " + texto))


@pytest.mark.parametrize(
    "texto",
    [
        "snake_case_name",
        "2 * 3 * 4",
        "FELIXO_UPDATE_PRERELEASE e FELIXO_DISABLE_AUTO_UPDATE",
        "~/.config",
        "x**2",
        "Nota*",
    ],
)
def test_so_escapa_quando_precisa(texto):
    """``snake_case``, ``2 * 3``, ``~/x`` e um marcador único na linha ficam sem barra."""

    assert _volta_igual(_item(texto)) == texto


def test_marcador_que_precisa_de_escape_sai_com_barra():
    assert _markdown(_item("a*b e c*d")) == r"a\*b e c\*d"
    assert _markdown(_item("__init__.py")) == r"\_\_init\_\_.py"


# -- a própria barra --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "C:\\_backup\\*.log",
        "dois \\\\ barras",
        "barra\\*estrela",
        "barra no fim\\",
        "\\)",
    ],
)
def test_barra_no_texto_volta_igual(texto):
    _volta_igual(_item("Veja: " + texto))


def test_barra_no_fim_de_trecho_formatado_nao_escapa_o_marcador_de_fechamento():
    _volta_igual(_item("a"), _item("b\\", bold=True), _item("c"))


def test_barra_antes_de_letra_continua_literal_e_sem_escape():
    assert _volta_igual(_item(r"C:\Users\Felipe")) == r"C:\Users\Felipe"


# -- B: trechos seguidos de formatações diferentes -----------------------------------------------


@pytest.mark.parametrize(
    ("primeiro", "segundo"),
    [
        ({"strikethrough": True}, {"strikethrough": True, "bold": True}),
        ({"strikethrough": True, "bold": True}, {"strikethrough": True}),
        ({"strikethrough": True, "italic": True}, {"strikethrough": True, "bold": True}),
        ({"strikethrough": True, "bold": True, "italic": True}, {"strikethrough": True}),
    ],
)
@pytest.mark.parametrize(("a", "b"), [("aa", "bb"), ("aa ", "bb"), ("a", " b")])
def test_dois_trechos_tachados_colados_voltam_iguais(primeiro, segundo, a, b):
    _volta_igual(_item("x" + a, **primeiro), _item(b, **segundo), _item("y"))


def test_tachado_separado_por_texto_simples_nao_vira_um_so():
    markdown = _volta_igual(
        _item("a", strikethrough=True), _item(" e "), _item("b", strikethrough=True)
    )
    assert markdown == "~~a~~ e ~~b~~"


def test_tachado_de_dois_trechos_seguidos_fica_sob_um_marcador_so():
    markdown = _volta_igual(
        _item("a", strikethrough=True), _item("b", strikethrough=True, bold=True)
    )

    assert markdown == "~~a**b**~~"


@pytest.mark.parametrize(
    ("primeiro", "segundo"),
    [
        ({"bold": True}, {"italic": True}),
        ({"italic": True}, {"bold": True}),
        ({"bold": True}, {"bold": True, "italic": True}),
        ({"italic": True}, {"bold": True, "italic": True}),
    ],
)
@pytest.mark.parametrize("em_volta", [("", ""), ("x", "y"), ("x ", " y")])
def test_negrito_e_italico_colados_voltam_iguais(primeiro, segundo, em_volta):
    antes, depois = em_volta
    _volta_igual(
        _item(antes + "p"), _item("a", **primeiro), _item("b", **segundo), _item("c" + depois)
    )


def test_italico_colado_em_negrito_usa_sublinhado_quando_pode():
    # "**a***b*" e as corridas de 4 ou 5 "*" de três trechos seguidos se leem pela regra do 3.
    assert _volta_igual(_item("a", bold=True), _item("b", italic=True)) == "**a**_b_"


def test_italico_junto_de_letra_continua_com_asterisco():
    # "_" não pode fechar logo antes de uma letra: "*b*c" e não "_b_c".
    assert _volta_igual(_item("a", bold=True), _item("b", italic=True), _item("c")) == "**a***b*c"


def test_italico_isolado_e_negrito_italico_de_um_trecho_nao_mudam():
    assert _volta_igual(_item("a "), _item("b", italic=True), _item(" c")) == "a *b* c"
    bold_italic = _item("b", bold=True, italic=True)
    assert _volta_igual(_item("a "), bold_italic, _item(" c")) == "a ***b*** c"


def test_italico_de_trechos_seguidos_fica_sob_um_marcador_so():
    markdown = _volta_igual(_item("a", italic=True), _item("b", bold=True, italic=True))

    assert markdown == "_a**b**_"


def test_tres_trechos_seguidos_de_negrito_e_italico_voltam_iguais():
    _volta_igual(
        _item("ab", bold=True, italic=True),
        _item("ab", italic=True),
        _item("ab", bold=True, italic=True),
    )


@pytest.mark.xfail(
    strict=True,
    reason="limite do formato: sem espaço entre letras, '**' e '_' não têm leitura única",
)
def test_cadeia_de_tres_trechos_entre_letras_e_limite_do_formato():
    _volta_igual(
        _item("xp"),
        _item("ab", bold=True),
        _item("ab", italic=True),
        _item("ab", bold=True, italic=True),
        _item("q"),
    )


# -- a escrita trata a barra do CommonMark -----------------------------------------------------


def _itens_de(markdown: str) -> list[dict[str, Any]]:
    return markdown_para_blocos(markdown)[0]["paragraph"]["rich_text"]


def test_barra_antes_de_pontuacao_vira_o_caractere():
    [item] = _itens_de(r"a\*b\_c\~d \\ e\!")

    assert item["text"]["content"] == "a*b_c~d \\ e!"
    assert "annotations" not in item


def test_barra_antes_de_letra_ou_no_fim_fica_como_esta():
    [item] = _itens_de("C:\\Users\\Felipe\\")

    assert item["text"]["content"] == "C:\\Users\\Felipe\\"


def test_asterisco_escapado_nao_fecha_a_enfase():
    itens = _itens_de(r"*a\* b*")

    formas = [(i["text"]["content"], (i.get("annotations") or {}).get("italic")) for i in itens]
    assert formas == [("a* b", True)]


def test_barra_nao_vale_dentro_de_codigo_inline():
    [item] = _itens_de(r"`a\*b`")

    assert item["text"]["content"] == r"a\*b"
    assert item["annotations"]["code"] is True


def test_barra_vale_dentro_do_rotulo_de_um_link():
    [item] = _itens_de(r"[a\_b\_c](https://x.dev/p)")

    assert item["text"]["content"] == "a_b_c"
    assert item["text"]["link"] == {"url": URL}


# -- o par escapado, para quem não relê (busca e exportação) ------------------------------------


def test_sem_escapar_devolve_o_markdown_de_antes():
    bloco = _paragrafo(_item("a*b e c*d"), _item(" forte", bold=True), _item("b", italic=True))

    assert blocos_para_markdown([bloco], escapar=False) == "a*b e c*d **forte***b*"
    assert blocos_para_markdown([bloco]) == r"a\*b e c\*d **forte**_b_"


def test_o_escape_vale_tambem_nos_filhos_e_nas_celulas():
    pai = {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [_item("pai")]},
        "_filhos": [_paragrafo(_item("a*b e c*d"))],
    }
    tabela = {
        "type": "table",
        "table": {"table_width": 1, "children": []},
        "_filhos": [{"type": "table_row", "table_row": {"cells": [[_item("a*b e c*d")]]}}],
    }

    assert r"a\*b e c\*d" in blocos_para_markdown([pai])
    assert r"a\*b e c\*d" in blocos_para_markdown([tabela])
    assert r"\*" not in blocos_para_markdown([pai, tabela], escapar=False)


# -- diferencial de semente fixa ------------------------------------------------------------------

_LETRAS = "abcdeéíoçxyz"
_PEDACOS_FIXOS = [" ", " ", "0", "7", "日", "本", ".", ",", "-", "/", "(", ")", ":", "\\"]


def _trecho(rng: random.Random) -> str:
    pecas: list[str] = []
    for _ in range(rng.randint(1, 4)):
        sorteio = rng.random()
        if sorteio < 0.45:
            pecas.append("".join(rng.choice(_LETRAS) for _ in range(rng.randint(1, 5))))
        elif sorteio < 0.7:
            pecas.append(rng.choice(_PEDACOS_FIXOS))
        else:
            pecas.append(rng.choice("*_~") * rng.choice([1, 1, 1, 2, 2, 3]))
    return "".join(pecas)


def _paragrafo_sintetico(rng: random.Random) -> list[dict[str, Any]]:
    itens: list[dict[str, Any]] = []
    for _ in range(rng.randint(1, 5)):
        anotacoes: dict[str, bool] = {}
        if rng.random() < 0.6:
            for nome in ("bold", "italic", "strikethrough"):
                if rng.random() < 0.4:
                    anotacoes[nome] = True
        itens.append(_item(_trecho(rng), **anotacoes))
    return itens


def _tem_tres_trechos_formatados_seguidos(itens: list[dict[str, Any]]) -> bool:
    """O limite do formato: três trechos seguidos com alguma ênfase (ver o docstring do módulo)."""

    enfase = [bool(i.get("annotations")) for i in itens if i["text"]["content"]]
    return any(all(enfase[k : k + 3]) for k in range(len(enfase) - 2))


def test_diferencial_sintetico_de_semente_fixa_volta_igual():
    """Só o limite do formato (três trechos formatados seguidos) pode falhar, e pouco.

    Antes desta correção, o mesmo gerador falhava em 13% dos parágrafos.
    """

    rng = random.Random(2026)
    falhas: list[tuple[str, list[dict[str, Any]]]] = []
    gerados = 0
    while gerados < 3000:
        itens = _paragrafo_sintetico(rng)
        texto = "".join(i["text"]["content"] for i in itens).strip()
        # O parágrafo começa por letra: "- ", "# " e "1. " no começo são prefixo de bloco.
        if not texto[:1].isalpha():
            continue
        gerados += 1
        markdown = blocos_para_markdown([_paragrafo(*itens)])
        blocos = markdown_para_blocos(markdown)
        if len(blocos) != 1 or _forma(blocos[0]["paragraph"]["rich_text"]) != _forma(itens):
            falhas.append((markdown, itens))

    fora_do_limite = [
        md for md, itens in falhas if not _tem_tres_trechos_formatados_seguidos(itens)
    ]
    assert fora_do_limite[:5] == []
    assert len(falhas) <= 5, [md for md, _ in falhas]
