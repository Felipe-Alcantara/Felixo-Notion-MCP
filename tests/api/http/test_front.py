"""Testes de integração do front servido pelo Django.

Valida a fiação da rota raiz, os assets e os elementos essenciais do fluxo sem
depender de rede, token do Notion ou execução de JavaScript no navegador.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("django")

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "felixo_notion_mcp.api.http.config.settings")

# `front/` fica na raiz do checkout: tests/api/http/ -> tests/api -> tests -> raiz.
RAIZ = Path(__file__).resolve().parents[3]

import django  # noqa: E402
from django.contrib.staticfiles import finders  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402

django.setup()


def test_home_serve_template_do_front():
    resposta = Client(HTTP_HOST="localhost").get(reverse("home"))

    assert resposta.status_code == 200
    conteudo = resposta.content.decode()
    assert "Automações do Notion" in conteudo
    assert 'id="lista-tarefas"' in conteudo
    assert 'id="form-tarefa"' in conteudo
    assert 'role="dialog"' in conteudo
    assert 'aria-live="polite"' in conteudo


@pytest.mark.parametrize("asset", ["css/app.css", "js/app.js"])
def test_assets_do_front_sao_encontrados(asset):
    assert finders.find(asset) is not None


def test_css_preserva_elementos_ocultos():
    caminho = finders.find("css/app.css")

    assert caminho is not None
    assert "[hidden]" in open(caminho, encoding="utf-8").read()


def test_spa_usa_mock_somente_quando_variavel_explicitamente_ativa():
    client_js = RAIZ / "front" / "src" / "api" / "client.js"
    codigo = client_js.read_text(encoding="utf-8")

    assert "VITE_MOCK_API === 'true'" in codigo
    assert "fallbackToMock" not in codigo
    assert "Backend indisponivel ou contrato v2 ausente, usando mock" not in codigo


def test_spa_envia_filtros_de_propriedade_para_api():
    client_js = RAIZ / "front" / "src" / "api" / "client.js"
    codigo = client_js.read_text(encoding="utf-8")

    assert "qs.set('status', filtros.status)" in codigo
    assert "qs.set('duracao', filtros.duracao)" in codigo
    assert "qs.set('area', filtros.area)" in codigo


def test_spa_consulta_database_atual_e_exibe_link_para_notion():
    client_js = RAIZ / "front" / "src" / "api" / "client.js"
    painel = RAIZ / "front" / "src" / "components" / "tarefas" / "painel-tarefas.jsx"

    codigo_client = client_js.read_text(encoding="utf-8")
    codigo_painel = painel.read_text(encoding="utf-8")

    assert "request('/api/database-atual')" in codigo_client
    assert "Database ativa" in codigo_painel
    assert "Fonte:" in codigo_painel
    assert "Abrir no Notion" in codigo_painel


def test_home_serve_o_bundle_quando_nao_ha_front_na_raiz(monkeypatch, tmp_path):
    """Instalação (wheel): sem `front/package.json` na raiz, a SPA gerada é a entrada."""
    from felixo_notion_mcp.api.http.config import urls

    bundle = tmp_path / "index.html"
    bundle.write_text('<div id="root">SPA empacotada</div>', encoding="utf-8")
    monkeypatch.setattr(urls, "_BUNDLE_INDEX", bundle)
    monkeypatch.setattr(urls, "REPO_RAIZ", tmp_path)

    resposta = Client(HTTP_HOST="localhost").get(reverse("home"))

    assert resposta.status_code == 200
    assert "SPA empacotada" in resposta.content.decode()


def test_home_serve_o_template_no_checkout_mesmo_com_bundle(monkeypatch, tmp_path):
    """Checkout (há `front/package.json`): vale o front de desenvolvimento, não o bundle."""
    from felixo_notion_mcp.api.http.config import urls

    bundle = tmp_path / "index.html"
    bundle.write_text('<div id="root">SPA empacotada</div>', encoding="utf-8")
    monkeypatch.setattr(urls, "_BUNDLE_INDEX", bundle)
    monkeypatch.setattr(urls, "REPO_RAIZ", RAIZ)

    resposta = Client(HTTP_HOST="localhost").get(reverse("home"))

    assert resposta.status_code == 200
    assert "SPA empacotada" not in resposta.content.decode()
    assert 'id="lista-tarefas"' in resposta.content.decode()
