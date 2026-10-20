"""Testes da tradução: código intacto, prosa em pedaços, provedor injetado."""
# ruff: noqa: E501

from __future__ import annotations

from felixo_notion_mcp.services import traducao

MARKDOWN = "# Title\n\nFirst paragraph.\n\n```python\nprint('hi')  # keep\n```\n\nLast [link](https://x.dev)."


class ProvedorFalso:
    def __init__(self):
        self.prompts = []

    def completar(self, prompt, *, modelo=None):
        self.prompts.append(prompt)
        texto = prompt.split("---\n", 1)[1]
        return texto.replace("Title", "Título").replace("First paragraph.", "Primeiro parágrafo.").replace("Last", "Último")


def test_codigo_passa_intacto_e_so_a_prosa_vai_ao_provedor():
    provedor = ProvedorFalso()
    resultado = traducao.traduzir_markdown(MARKDOWN, provedor=provedor)
    assert "```python\nprint('hi')  # keep\n```" in resultado
    assert "# Título" in resultado and "Primeiro parágrafo." in resultado
    assert "Último [link](https://x.dev)." in resultado
    assert all("print('hi')" not in p for p in provedor.prompts)
    assert len(provedor.prompts) == 2


def test_prosa_longa_vira_varios_pedacos_sem_cortar_paragrafo():
    texto = "\n\n".join(f"Parágrafo {i} " + "x" * 50 for i in range(10))
    trechos = traducao.dividir(texto, limite=200)
    assert len(trechos) > 1
    assert all(not t.codigo for t in trechos)
    assert "\n\n".join(t.texto for t in trechos) == texto


def test_bloco_de_codigo_sem_fechamento_nao_vira_prosa():
    trechos = traducao.dividir("Texto\n\n~~~\ncodigo sem fim")
    assert trechos[-1].codigo and "codigo sem fim" in trechos[-1].texto
