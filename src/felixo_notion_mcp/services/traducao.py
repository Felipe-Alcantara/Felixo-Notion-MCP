"""Caso de uso: traduzir um texto em Markdown preservando código e estrutura.

O texto é dividido em trechos: blocos de código (``` e ~~~) passam intactos; a prosa
é agrupada em pedaços de até ``limite`` caracteres (sem cortar parágrafos) e enviada
ao provedor de IA (:class:`~felixo_notion_mcp.integrations.openrouter.ProvedorIA`),
com instruções para manter links, imagens, HTML e Markdown exatamente onde estão.
O provedor é injetado — este módulo não conhece OpenRouter nem chave de API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from felixo_notion_mcp.integrations.openrouter import ProvedorIA

PROMPT = """Traduza o texto em Markdown abaixo para {idioma}.
Regras: traduza tudo, sem resumir, sem comentar e sem acrescentar nada; mantenha o tom
do autor; preserve exatamente a estrutura Markdown e o HTML (títulos, listas, tabelas,
citações, ênfase); não altere URLs, destinos de links, caminhos de imagem, código inline
nem nomes de produtos; traduza o texto visível dos links e o texto alternativo das imagens.
Responda só com o texto traduzido.

---
{texto}"""

_CERCA = re.compile(r"^(```|~~~)")


@dataclass(frozen=True)
class Trecho:
    texto: str
    codigo: bool


def dividir(markdown: str, limite: int = 6000) -> list[Trecho]:
    """Separa blocos de código da prosa e agrupa a prosa em pedaços de até ``limite``."""

    trechos: list[Trecho] = []
    prosa: list[str] = []
    codigo: list[str] | None = None
    cerca = ""

    def fechar_prosa() -> None:
        pedaco: list[str] = []
        tamanho = 0
        for paragrafo in "\n".join(prosa).split("\n\n"):
            if pedaco and tamanho + len(paragrafo) > limite:
                trechos.append(Trecho("\n\n".join(pedaco), False))
                pedaco, tamanho = [], 0
            pedaco.append(paragrafo)
            tamanho += len(paragrafo) + 2
        if pedaco and "".join(pedaco).strip():
            trechos.append(Trecho("\n\n".join(pedaco), False))
        prosa.clear()

    for linha in markdown.split("\n"):
        marca = _CERCA.match(linha.strip())
        if codigo is None and marca:
            fechar_prosa()
            codigo, cerca = [linha], marca.group(1)
        elif codigo is not None:
            codigo.append(linha)
            if linha.strip().startswith(cerca) and len(codigo) > 1:
                trechos.append(Trecho("\n".join(codigo), True))
                codigo = None
        else:
            prosa.append(linha)
    if codigo is not None:
        trechos.append(Trecho("\n".join(codigo), True))
    fechar_prosa()
    return trechos


def traduzir_markdown(
    markdown: str,
    *,
    provedor: ProvedorIA,
    idioma: str = "português do Brasil",
    modelo: str | None = None,
    limite: int = 6000,
) -> str:
    """Traduz a prosa de ``markdown`` e devolve o texto remontado, código intacto."""

    partes = []
    for trecho in dividir(markdown, limite):
        if trecho.codigo:
            partes.append(trecho.texto)
        else:
            prompt = PROMPT.format(idioma=idioma, texto=trecho.texto)
            partes.append(provedor.completar(prompt, modelo=modelo).strip())
    return "\n\n".join(partes).strip() + "\n"
