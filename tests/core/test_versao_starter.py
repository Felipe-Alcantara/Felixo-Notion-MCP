"""A versão exposta pelo módulo é a mesma do pacote que o PyPI publica."""

from __future__ import annotations

import tomllib
from pathlib import Path

import felixo_notion_mcp

RAIZ = Path(__file__).resolve().parents[2]


def test_versao_do_modulo_e_a_do_pyproject():
    """Os consumidores declaram a faixa pela versão do pacote e conferem a
    instalada por ``felixo_notion_mcp.__version__``; subir só uma das duas faz a
    conferência mentir sobre quais APIs estão disponíveis."""

    dados = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert felixo_notion_mcp.__version__ == dados["project"]["version"]
