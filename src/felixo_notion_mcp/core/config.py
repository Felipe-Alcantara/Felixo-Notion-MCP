"""Configuração central do servidor — lida inteiramente do ambiente.

Nenhum segredo mora no repositório: o token do Notion, a ``SECRET_KEY`` do Django
e as demais opções vêm de variáveis de ambiente (ou de um ``.env`` local, ignorado
pelo git). Esta camada não conhece HTTP nem o Django — é só leitura de configuração,
para que ``config/settings.py`` e ``integrations/`` consumam um objeto estável.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _raiz_do_repositorio() -> Path:
    """Raiz de onde o ``.env`` e o banco local são lidos e gravados.

    A conta vale para quem usa a raiz (a CLI, o launcher, o servidor MCP e o Django): ninguém
    a repete. Há três casos, e o ``__file__`` de ``core/config.py`` é o ponto de partida:

    - **Binário nativo (PyInstaller):** a própria ``_MEIPASS``, a pasta privada de extração.
      O arquivo mora em ``<_MEIPASS>/felixo_notion_mcp/core``, e ``parents[3]`` sairia dela
      para a pasta que a contém (no Linux, a temporária do sistema, gravável por qualquer
      usuário local): um ``.env`` plantado ali seria carregado a cada execução.
    - **Checkout:** a raiz do repositório. Em ``src/felixo_notion_mcp/core/config.py``,
      ``parents[0]`` é ``core``, ``[1]`` é ``felixo_notion_mcp``, ``[2]`` é ``src`` e ``[3]``
      é a raiz. Só vale se ela tem o ``pyproject.toml`` do projeto.
    - **Instalação (wheel, pipx):** não há repositório. A raiz é ``parents[2]``, a pasta que
      contém o pacote ``felixo_notion_mcp`` (``site-packages``), o mesmo ponto onde a CLI e o
      app antigos guardavam o ``.env`` e o banco. ``parents[3]`` seria ``<venv>/lib/pythonX.Y``.
      Sem ``_MEIPASS`` num binário congelado, cai neste mesmo ponto.
    """

    if getattr(sys, "frozen", False):
        pasta_privada = getattr(sys, "_MEIPASS", None)
        if pasta_privada:
            return Path(pasta_privada)
        return Path(__file__).resolve().parents[2]
    arquivo = Path(__file__).resolve()
    if (arquivo.parents[3] / "pyproject.toml").is_file():
        return arquivo.parents[3]
    return arquivo.parents[2]


#: Raiz do checkout; numa instalação, a pasta que contém o pacote (``site-packages``); no
#: binário nativo, a pasta privada de extração.
REPO_RAIZ = _raiz_do_repositorio()

#: ``.env`` local opcional, no mesmo padrão usado por ``start_app.py``.
ENV_FILE = REPO_RAIZ / ".env"

# Nomes das variáveis de ambiente que o servidor lê.
ENV_SECRET_KEY = "DJANGO_SECRET_KEY"
ENV_DEBUG = "DJANGO_DEBUG"
ENV_ALLOWED_HOSTS = "DJANGO_ALLOWED_HOSTS"
ENV_NOTION_TOKEN = "NOTION_TOKEN"
ENV_NOTION_DATABASE_ID = "NOTION_DATABASE_ID"
ENV_DB_PATH = "OPERATIONAL_DB_PATH"

#: Hosts aceitos quando ``DJANGO_ALLOWED_HOSTS`` não está definida, com ou sem debug: só a
#: máquina local. ``["*"]`` em debug deixava um site qualquer falar com a API por DNS rebinding.
HOSTS_LOCAIS = ("localhost", "127.0.0.1", "[::1]")

#: SECRET_KEY de desenvolvimento — só usada quando ``DEBUG`` e nenhuma foi definida.
#: Nunca deve ser usada em produção; ``settings.py`` exige a real quando ``DEBUG`` é off.
SECRET_KEY_DEV = "dev-inseguro-troque-em-producao"  # noqa: S105 - placeholder, não é segredo real


def carregar_env_file(caminho: Path | None = None) -> None:
    """Carrega pares ``CHAVE=valor`` de um ``.env`` para ``os.environ``.

    Não sobrescreve variáveis já definidas no ambiente (o ambiente real vence o
    arquivo) e ignora linhas vazias e comentários. Sem dependência externa, no mesmo
    espírito do leitor de ``.env`` de ``start_app.py``.

    Args:
        caminho: O ``.env`` a ler. Sem ele vale o ``ENV_FILE`` da raiz, lido na hora da
            chamada (e não na definição da função), para que a suíte consiga apontá-lo
            para um checkout temporário em vez do ``.env`` real de quem a executa.
    """

    if caminho is None:
        caminho = ENV_FILE
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave, valor = chave.strip(), valor.strip()
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def _bool_env(nome: str, padrao: bool = False) -> bool:
    """Lê uma variável de ambiente como booleano (1/true/yes/on)."""

    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "yes", "on", "sim")


def _lista_env(nome: str) -> list[str]:
    """Lê uma variável separada por vírgulas como lista (sem itens vazios)."""

    valor = os.environ.get(nome, "")
    return [item.strip() for item in valor.split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    """Configuração resolvida do servidor, sem expor segredos em ``repr``."""

    secret_key: str
    debug: bool
    allowed_hosts: list[str]
    notion_token: str | None
    notion_database_id: str | None
    database_path: Path

    def __repr__(self) -> str:  # nunca vazar o token/secret em log
        token = "definido" if self.notion_token else "ausente"
        return (
            f"Config(debug={self.debug}, allowed_hosts={self.allowed_hosts}, "
            f"notion_token={token}, notion_database_id="
            f"{'definido' if self.notion_database_id else 'ausente'}, "
            f"database_path={self.database_path})"
        )


def carregar_config(carregar_dotenv: bool = True) -> Config:
    """Resolve a configuração a partir do ambiente (e do ``.env`` local, se houver).

    Args:
        carregar_dotenv: Quando ``True`` (padrão), popula o ``os.environ`` a partir
            do ``.env`` antes de ler — sem sobrescrever o que já está no ambiente.

    Returns:
        Um :class:`Config` imutável.
    """

    if carregar_dotenv:
        carregar_env_file()

    debug = _bool_env(ENV_DEBUG, padrao=False)
    secret_key = os.environ.get(ENV_SECRET_KEY, "").strip()
    if not secret_key:
        # Em dev seguimos com uma chave previsível; em produção, settings exige a real.
        secret_key = SECRET_KEY_DEV

    allowed_hosts = _lista_env(ENV_ALLOWED_HOSTS) or list(HOSTS_LOCAIS)

    db_path = os.environ.get(ENV_DB_PATH, "").strip()
    database_path = Path(db_path) if db_path else (REPO_RAIZ / "operacional.sqlite3")

    notion_token = os.environ.get(ENV_NOTION_TOKEN, "").strip() or None
    notion_database_id = os.environ.get(ENV_NOTION_DATABASE_ID, "").strip() or None

    return Config(
        secret_key=secret_key,
        debug=debug,
        allowed_hosts=allowed_hosts,
        notion_token=notion_token,
        notion_database_id=notion_database_id,
        database_path=database_path,
    )
