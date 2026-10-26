"""Hosts que o servidor HTTP local aceita (``ALLOWED_HOSTS``).

O menu sobe o app com ``DJANGO_DEBUG=1``. Com ``["*"]`` nesse modo, uma página de outro site
conseguia, por *DNS rebinding*, falar com o servidor como se fosse da mesma origem. O padrão
é só a máquina local, com ou sem debug; ``DJANGO_ALLOWED_HOSTS`` continua mandando.
"""

import pytest

from felixo_notion_mcp.core.config import carregar_config

HOSTS_LOCAIS = ["localhost", "127.0.0.1", "[::1]"]


@pytest.fixture(autouse=True)
def _sem_hosts_no_ambiente(monkeypatch):
    monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)


@pytest.mark.parametrize("debug", ["1", "0"])
def test_padrao_aceita_so_a_maquina_local_com_ou_sem_debug(monkeypatch, debug):
    monkeypatch.setenv("DJANGO_DEBUG", debug)

    assert carregar_config(carregar_dotenv=False).allowed_hosts == HOSTS_LOCAIS


def test_variavel_de_ambiente_vence_o_padrao(monkeypatch):
    monkeypatch.setenv("DJANGO_DEBUG", "1")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "app.exemplo.org, outro.exemplo.org")

    assert carregar_config(carregar_dotenv=False).allowed_hosts == [
        "app.exemplo.org",
        "outro.exemplo.org",
    ]
