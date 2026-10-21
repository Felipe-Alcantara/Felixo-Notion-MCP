"""O que o ``pyproject.toml`` declara precisa bater com o código que a suíte testa.

A distribuição é uma só (``felixo-notion-mcp``): biblioteca, CLI, servidor MCP e app moram
no mesmo pacote. Estes testes prendem o contrato de instalação: o nome, a versão que a CLI
mostra quando o pacote não está instalado e os executáveis, que precisam apontar para
funções que existem.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from felixo_notion_mcp.api.cli import unificada, versao

RAIZ = Path(__file__).resolve().parents[3]

#: Executáveis da CLI: o principal, o apelido permanente e o de transição.
EXECUTAVEIS_DA_CLI = {
    "felixo-notion-mcp": "felixo_notion_mcp.api.cli.unificada:main",
    "notion-tasks": "felixo_notion_mcp.api.cli.notion_tasks:main",
    "notion-automacoes": "felixo_notion_mcp.api.cli.unificada:main",
}

#: Apelidos de transição do app: o launcher (menu) e o servidor MCP.
EXECUTAVEIS_DO_APP = {
    "notion-automacoes-app": "felixo_notion_mcp.api.launcher:main",
    "notion-automacoes-mcp": "felixo_notion_mcp.api.mcp.server:main",
}


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    return tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))


def test_raiz_e_a_do_repositorio():
    """Se a profundidade do arquivo mudar, a raiz deixa de achar o ``pyproject.toml``."""

    assert (RAIZ / "pyproject.toml").is_file()
    assert (RAIZ / "src" / "felixo_notion_mcp").is_dir()


def test_versao_fonte_e_a_do_pyproject(pyproject):
    """``--version`` cai em ``VERSAO_FONTE`` quando o pacote não está instalado."""

    assert versao.VERSAO_FONTE == pyproject["project"]["version"]


def test_distribuicao_unica_com_o_nome_novo(pyproject):
    assert pyproject["project"]["name"] == "felixo-notion-mcp"
    assert unificada.DISTRIBUICAO == pyproject["project"]["name"]


def test_nao_depende_de_distribuicoes_irmas(pyproject):
    """A biblioteca e o app moram aqui; depender deles seria instalar o código duas vezes."""

    projeto = pyproject["project"]
    declaradas = list(projeto["dependencies"])
    for extra in projeto.get("optional-dependencies", {}).values():
        declaradas.extend(extra)
    nomes = {canonicalize_name(Requirement(texto).name) for texto in declaradas}

    assert not nomes & {"notion-starter", "notion-workspace-app", "notion-automacoes"}


@pytest.mark.parametrize(("executavel", "destino"), sorted(EXECUTAVEIS_DA_CLI.items()))
def test_executavel_da_cli_aponta_para_uma_funcao_que_existe(pyproject, executavel, destino):
    scripts = pyproject["project"]["scripts"]
    assert scripts[executavel] == destino

    modulo, _, funcao = destino.partition(":")
    assert callable(getattr(importlib.import_module(modulo), funcao))


@pytest.mark.parametrize(("executavel", "destino"), sorted(EXECUTAVEIS_DO_APP.items()))
def test_executavel_do_app_aponta_para_uma_funcao_que_existe(pyproject, executavel, destino):
    scripts = pyproject["project"]["scripts"]
    assert scripts[executavel] == destino

    modulo, _, funcao = destino.partition(":")
    assert callable(getattr(importlib.import_module(modulo), funcao))


def test_executaveis_de_transicao_declarados(pyproject):
    scripts = pyproject["project"]["scripts"]
    assert {
        "felixo-notion-mcp",
        "notion-tasks",
        "notion-automacoes",
        "notion-automacoes-app",
        "notion-automacoes-mcp",
    } <= set(scripts)
    assert pyproject["project"]["name"] == "felixo-notion-mcp"


def test_python_minimo_e_o_mesmo_do_pyproject():
    """A versão mínima que a CLI e o menu conferem é a que o pacote declara."""

    from felixo_notion_mcp.core.constants import PYTHON_MINIMO

    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">={}.{}".format(*PYTHON_MINIMO)
    assert f"Programming Language :: Python :: {PYTHON_MINIMO[0]}.{PYTHON_MINIMO[1] - 1}" not in (
        pyproject["project"]["classifiers"]
    )
