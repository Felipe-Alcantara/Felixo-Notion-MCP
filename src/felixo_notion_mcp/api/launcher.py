"""Menu de entrada do Automações do Notion — a porta de entrada única do projeto.

Rode ``notion-automacoes-app`` (ou ``python start_app.py``, no checkout) para abrir
um menu interativo onde você instala as dependências, configura o token do Notion,
vê o estado do ambiente e roda os exemplos. Não é preciso decorar comando nenhum.

Segue o contrato de menu de entrada do Felixo System Design: menu interativo,
colorido e descritivo, com no mínimo Iniciar/Rodar, Instalar/Setup, Configurar
e Status/Sair. Cross-platform (Windows, Linux, macOS), sem segredo no script —
o token continua em variável de ambiente / ``.env`` ignorado pelo git.

Este módulo mora dentro do pacote: os processos filhos que ele dispara abrem o próprio
launcher e a CLI por ``python -m``. Rodar o arquivo por caminho colocaria a pasta ``api/``
no começo do ``sys.path``, e as subpastas ``http`` e ``mcp`` esconderiam o ``http`` da
biblioteca padrão e o SDK ``mcp``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import NamedTuple

from felixo_notion_mcp.core.config import ENV_FILE, REPO_RAIZ
from felixo_notion_mcp.core.instalacao import instrucao_de_instalacao, raiz_e_checkout
from felixo_notion_mcp.core.origem import origem_do_pacote

#: O mesmo predicado do ``update`` da CLI (``core.instalacao``); o nome antigo fica para os
#: testes e para quem já o chamava.
_raiz_e_checkout = raiz_e_checkout


#: Raiz do checkout. É a mesma de ``core.config`` (que também decide a raiz do binário
#: nativo, sempre dentro de ``_MEIPASS``); o launcher não repete essa conta.
RAIZ = REPO_RAIZ
#: Sem o ``pyproject.toml`` na raiz (wheel, pipx, binário) é instalação: não há ``.venv``
#: do projeto, ``front/`` nem ``pip install -e`` a fazer.
MODO_CHECKOUT = _raiz_e_checkout(RAIZ)
#: Pasta que contém o pacote ``felixo_notion_mcp`` (``src/`` no checkout).
PASTA_DO_PACOTE = Path(__file__).resolve().parents[2]
#: Borda HTTP: ``manage.py``, ``templates``, ``static`` (e o bundle da SPA em ``static/frontend``).
SERVIDOR = Path(__file__).resolve().parent / "http"
MANAGE_PY = SERVIDOR / "manage.py"
MCP_SERVER_PY = Path(__file__).resolve().parent / "mcp" / "server.py"
#: Módulo deste launcher, para reabri-lo por ``python -m`` (nunca por caminho).
MODULO_LAUNCHER = "felixo_notion_mcp.api.launcher"
MODULO_CLI = "felixo_notion_mcp.api.cli"
ENV_EXEMPLO = RAIZ / ".env.example"
EXEMPLOS = RAIZ / "examples"
FRONT = RAIZ / "front"
FRONT_NODE_MODULES = FRONT / "node_modules"
FRONT_BUNDLE_INDEX = SERVIDOR / "static" / "frontend" / "index.html"
TOKEN_ENV = "NOTION_TOKEN"
DATABASE_ENV = "NOTION_DATABASE_ID"
TOKEN_PREFIXO = "ntn_"
APP_ENDERECO_PADRAO = "127.0.0.1:8000"
API_ENDERECO_PADRAO = APP_ENDERECO_PADRAO
API_URL = f"http://{API_ENDERECO_PADRAO}/"
API_HEALTH_URL = f"{API_URL}api/health"
FRONT_HOST = "127.0.0.1"
FRONT_PORT = "5173"
FRONT_ENDERECO_PADRAO = f"{FRONT_HOST}:{FRONT_PORT}"
FRONT_EMPACOTADO = FRONT_BUNDLE_INDEX.exists() and not (FRONT / "package.json").exists()
FRONT_URL = API_URL if FRONT_EMPACOTADO else f"http://{FRONT_ENDERECO_PADRAO}/"
APP_URL = API_URL if FRONT_EMPACOTADO else FRONT_URL
APP_HEALTH_URL = API_HEALTH_URL
NODE_VERSAO_MINIMA = "20.19+ ou 22.12+"
SCHEMA_TAREFAS = {
    "Tarefa": "title",
    "Etapa": "status",
    "Prazo": "date",
}

# As deps de TUI são do próprio menu; o passo de Instalar/Setup garante que
# existem. Antes disso, caímos num fallback em texto puro para nunca quebrar.
_DEPS_TUI = ("questionary", "rich")


class FrontRuntime(NamedTuple):
    """Runtime Node/npm escolhido para executar a SPA React."""

    node: Path
    npm: Path
    versao: str


#: Pythons de ``.venv`` que a sonda recusou (não importam o pacote); ``_executavel_projeto``
#: os pula.
_VENVS_RECUSADOS: set[str] = set()


def _executavel_projeto() -> str:
    """Retorna o Python do ambiente local do projeto quando ele existir.

    O `start_app.py` é frequentemente invocado com o Python do sistema, mas o
    repositório já costuma ter um `.venv` preparado. Reusar esse interpretador
    evita tentar instalar dependências num ambiente externamente gerenciado.
    Fora de um checkout (instalação, binário nativo) não existe `.venv` do projeto:
    vale o Python que está rodando.
    """

    if not MODO_CHECKOUT:
        return sys.executable
    candidatos = (
        RAIZ / ".venv" / "bin" / "python",
        RAIZ / ".venv" / "Scripts" / "python.exe",
        RAIZ / "venv" / "bin" / "python",
        RAIZ / "venv" / "Scripts" / "python.exe",
    )
    for candidato in candidatos:
        if candidato.exists() and str(candidato) not in _VENVS_RECUSADOS:
            return str(candidato)
    return sys.executable


def _exportar_pacote_para_filhos() -> None:
    """No checkout, faz os processos filhos acharem o mesmo ``src/`` que este launcher usa.

    Quem abre o launcher com ``src`` só no ``sys.path`` (sem ``pip install -e``) deixaria
    o ``manage.py``, o MCP e a CLI sem o pacote. Fora do checkout nada a fazer: a pasta do
    pacote seria o ``site-packages``, e jogá-lo no ``PYTHONPATH`` de outro Python misturaria
    versões de bibliotecas.
    """

    if not MODO_CHECKOUT or PASTA_DO_PACOTE.name != "src":
        return
    pasta = str(PASTA_DO_PACOTE)
    atuais = [parte for parte in os.environ.get("PYTHONPATH", "").split(os.pathsep) if parte]
    if pasta not in atuais:
        os.environ["PYTHONPATH"] = os.pathsep.join([pasta, *atuais])


def _interpretador_importa_o_pacote(executavel: str) -> bool:
    """Confere, com o ambiente que o ``execv`` vai herdar, se ``executavel`` abre o launcher.

    É a sonda barata (``python -c "import ..."``, sem dependência de terceiros) que impede o
    menu de trocar para um ``.venv`` recém-criado, sem o pacote nem ``src/`` no ``PYTHONPATH``:
    o ``python -m`` falharia com ``No module named felixo_notion_mcp`` antes de qualquer menu.
    """

    try:
        resultado = subprocess.run(
            [executavel, "-c", f"import {MODULO_LAUNCHER}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return resultado.returncode == 0


def _reexecutar_no_python_do_projeto(argumentos: list[str]) -> None:
    """Relança o launcher (``python -m``) no Python do projeto quando ele difere do atual.

    Só troca de interpretador se o do projeto consegue importar o pacote; senão fica neste, que
    já está rodando o launcher, e o menu oferece Instalar/Setup.
    """

    destino = Path(_executavel_projeto()).absolute()
    atual = Path(sys.executable).absolute()
    if destino == atual:
        return
    if not _interpretador_importa_o_pacote(str(destino)):
        _VENVS_RECUSADOS.add(str(destino))
        print(
            f"Aviso: {destino} não importa {MODULO_LAUNCHER} (falta instalar o pacote ali); "
            f"seguindo com {atual}.",
            file=sys.stderr,
        )
        return
    os.execv(str(destino), [str(destino), "-m", MODULO_LAUNCHER, *argumentos])


# --------------------------------------------------------------------------- #
# Terminais dedicados                                                        #
# --------------------------------------------------------------------------- #
def _comando_acao(chave: str) -> list[str]:
    """Monta o comando que executa uma única ação fora do menu principal."""

    return [_executavel_projeto(), "-m", MODULO_LAUNCHER, "--action", chave]


def _comando_terminal_linux(
    comando: list[str],
    titulo: str,
) -> list[str] | None:
    """Escolhe um emulador de terminal Linux disponível."""

    terminal_configurado = os.environ.get("TERMINAL", "").strip()
    if terminal_configurado:
        partes = shlex.split(terminal_configurado)
        executavel = shutil.which(partes[0])
        if executavel:
            return [executavel, *partes[1:], "-e", *comando]

    candidatos = (
        ("konsole", lambda exe: [exe, "--separate", "-p", f"tabtitle={titulo}", "-e", *comando]),
        ("gnome-terminal", lambda exe: [exe, f"--title={titulo}", "--", *comando]),
        ("kgx", lambda exe: [exe, "--title", titulo, "--", *comando]),
        (
            "xfce4-terminal",
            lambda exe: [exe, f"--title={titulo}", f"--command={shlex.join(comando)}"],
        ),
        ("mate-terminal", lambda exe: [exe, f"--title={titulo}", "--", *comando]),
        ("kitty", lambda exe: [exe, "--title", titulo, *comando]),
        ("alacritty", lambda exe: [exe, "--title", titulo, "-e", *comando]),
        (
            "wezterm",
            lambda exe: [
                exe,
                "start",
                "--always-new-process",
                "--cwd",
                str(RAIZ),
                "--",
                *comando,
            ],
        ),
        ("foot", lambda exe: [exe, f"--title={titulo}", "--", *comando]),
        ("xterm", lambda exe: [exe, "-T", titulo, "-e", *comando]),
        ("x-terminal-emulator", lambda exe: [exe, "-T", titulo, "-e", *comando]),
    )
    for nome, montar in candidatos:
        executavel = shutil.which(nome)
        if executavel:
            return montar(executavel)
    return None


def _abrir_terminal_dedicado(chave: str, titulo: str) -> tuple[bool, str]:
    """Abre uma ação em outro terminal, sem bloquear o menu atual."""

    comando = _comando_acao(chave)
    kwargs: dict[str, object] = {
        "cwd": RAIZ,
        "start_new_session": True,
    }

    try:
        if sys.platform == "win32":
            kwargs.pop("start_new_session")
            kwargs["creationflags"] = getattr(
                subprocess,
                "CREATE_NEW_CONSOLE",
                0x00000010,
            )
            subprocess.Popen(comando, **kwargs)
        elif sys.platform == "darwin":
            # O Terminal.app abre um shell novo, que não herda o PYTHONPATH deste processo.
            caminho_python = os.environ.get("PYTHONPATH", "")
            prefixo_env = f"PYTHONPATH={shlex.quote(caminho_python)} " if caminho_python else ""
            comando_shell = f"cd {shlex.quote(str(RAIZ))} && {prefixo_env}{shlex.join(comando)}"
            comando_apple = comando_shell.replace("\\", "\\\\").replace('"', '\\"')
            script = f'tell application "Terminal" to do script "{comando_apple}"'
            subprocess.Popen(["osascript", "-e", script], **kwargs)
        else:
            comando_terminal = _comando_terminal_linux(comando, titulo)
            if comando_terminal is None:
                return (
                    False,
                    "Nenhum emulador de terminal compatível foi encontrado. "
                    "Configure a variável TERMINAL ou instale Konsole, GNOME Terminal, "
                    "Kitty, Alacritty, XTerm ou equivalente.",
                )
            subprocess.Popen(comando_terminal, **kwargs)
    except OSError as exc:
        return False, f"Não foi possível abrir o terminal dedicado: {exc}"

    return True, f"Terminal dedicado aberto para: {titulo}"


# --------------------------------------------------------------------------- #
# Bootstrap das dependências de TUI                                           #
# --------------------------------------------------------------------------- #
def _tui_disponivel() -> bool:
    """Indica se as bibliotecas do menu interativo estão instaladas."""

    try:
        import questionary  # noqa: F401
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def _front_empacotado() -> bool:
    """Indica se o app instalado tem a SPA dentro do pacote Python."""

    return FRONT_BUNDLE_INDEX.exists() and not (FRONT / "package.json").exists()


def _instalar_deps_tui() -> bool:
    """Tenta instalar as dependências de TUI do menu. Retorna sucesso."""

    print(f"Instalando dependências do menu ({', '.join(_DEPS_TUI)})...")
    executavel = _executavel_projeto()
    codigo = subprocess.call([executavel, "-m", "pip", "install", *_DEPS_TUI])
    if codigo != 0:
        print(
            "Não consegui instalar as dependências do menu. "
            "Instale manualmente com:\n"
            f"  {executavel} -m pip install {' '.join(_DEPS_TUI)}"
        )
        return False
    return True


# --------------------------------------------------------------------------- #
# Estado real do ambiente                                                     #
# --------------------------------------------------------------------------- #
def _comando_pip_projeto(extras: str) -> list[str] | None:
    """Comando ``pip install`` do próprio projeto com os extras pedidos, ou ``None``.

    Só existe no checkout, onde é a instalação editável da raiz (``-e ".[app,dev]"``). Fora
    dele não há raiz para instalar e o comando é ``None``: nada aqui instala a distribuição
    por nome, porque ``felixo-notion-mcp`` ainda não é do projeto no PyPI (a publicação é de
    uma etapa posterior) e quem registrasse o nome ganharia execução de código em quem
    seguisse a instalação automática.
    """

    if not MODO_CHECKOUT:
        return None
    return [sys.executable, "-m", "pip", "install", "-e", f".[{extras}]"]


def _texto_comando(comando: list[str]) -> str:
    """Comando pronto para uma mensagem do rich: os colchetes dos extras não viram estilo."""

    from rich.markup import escape

    return escape(shlex.join(comando))


def _como_instalar(extras: str) -> str:
    """Como instalar os extras, pronto para o rich: o comando no checkout, a orientação fora."""

    from rich.markup import escape

    comando = _comando_pip_projeto(extras)
    if comando is None:
        return escape(instrucao_de_instalacao(extras))
    return _texto_comando(comando)


def _comando_de_instalacao_confirmado(
    console, pergunta: str, extras: str = "app"
) -> list[str] | None:
    """Pergunta antes de instalar os extras; devolve o comando a rodar só se a pessoa disser sim.

    Nada é instalado sem esta pergunta. Fora do checkout não há comando nem o que perguntar
    (ver ``_comando_pip_projeto``): mostra como instalar e devolve ``None``. Recusando, mostra
    o comando para rodar quando quiser e também devolve ``None``.
    """

    import questionary

    comando = _comando_pip_projeto(extras)
    if comando is None:
        console.print(f"[yellow]•[/yellow] Nada será instalado por aqui. {_como_instalar(extras)}")
        return None
    if questionary.confirm(pergunta).ask():
        return comando
    console.print(f"[dim]Instale quando quiser:\n  {_como_instalar(extras)}[/dim]")
    return None


#: Dependências de runtime do ``pyproject.toml`` (distribuição -> módulo que se importa). O
#: ``typing_extensions`` (só no Python 3.10) entra em ``_dependencias_faltando``.
_DEPENDENCIAS_DE_RUNTIME = {
    "python-docx": "docx",
    "requests": "requests",
    "mcp": "mcp",
}


def _dependencias_faltando() -> list[str]:
    """Distribuições de runtime do projeto que o Python atual não consegue importar."""

    dependencias = dict(_DEPENDENCIAS_DE_RUNTIME)
    if sys.version_info < (3, 11):
        dependencias["typing_extensions"] = "typing_extensions"
    return [
        distribuicao
        for distribuicao, modulo in dependencias.items()
        if importlib.util.find_spec(modulo) is None
    ]


def _pacote_instalado() -> bool:
    """Indica se o ``felixo_notion_mcp`` está pronto para uso: suas dependências importam.

    O pacote em si sempre importa (é este launcher que está rodando, e ``import
    felixo_notion_mcp`` só usa a stdlib); o que falta num ambiente novo são o ``requests``
    e as demais dependências de runtime, que os exemplos, o mapa e o servidor precisam.
    """

    return not _dependencias_faltando()


def _django_disponivel() -> bool:
    """Indica se o Django (extra ``app``) está instalado."""

    try:
        import django  # noqa: F401
    except ImportError:
        return False
    return True


def _mcp_disponivel() -> bool:
    """Indica se o SDK MCP está instalado."""

    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


def _parse_versao_node(texto: str) -> tuple[int, int, int] | None:
    """Converte ``v22.12.0`` em tupla comparável."""

    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", texto.strip())
    if not match:
        return None
    return tuple(int(parte) for parte in match.groups())


def _node_compativel(versao: tuple[int, int, int] | None) -> bool:
    """Valida a versão exigida pelo Vite atual."""

    if versao is None:
        return False
    major, minor, _patch = versao
    if major == 20:
        return minor >= 19
    if major == 22:
        return minor >= 12
    return major > 22


def _versao_node(executavel: Path) -> str | None:
    """Lê a versão de um executável ``node`` sem poluir a saída do menu."""

    try:
        resultado = subprocess.run(
            [str(executavel), "--version"],
            check=False,
            capture_output=True,
            text=True,
            # Erro localizado do node pode ter byte fora da codepage; nunca derruba o menu.
            errors="replace",
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if resultado.returncode != 0:
        return None
    return resultado.stdout.strip()


def _candidatos_node() -> list[Path]:
    """Lista runtimes Node conhecidos, preferindo PATH e depois instalações NVM."""

    candidatos: list[Path] = []
    do_path = shutil.which("node")
    if do_path:
        candidatos.append(Path(do_path))

    nvm_versions = Path.home() / ".nvm" / "versions" / "node"
    if nvm_versions.exists():
        candidatos.extend(sorted(nvm_versions.glob("v*/bin/node"), reverse=True))

    vistos: set[Path] = set()
    unicos = []
    for candidato in candidatos:
        resolvido = candidato.resolve()
        if resolvido not in vistos:
            vistos.add(resolvido)
            unicos.append(resolvido)
    return unicos


def _resolver_runtime_front() -> FrontRuntime | None:
    """Escolhe um Node compatível e o npm correspondente para rodar o Vite."""

    for node in _candidatos_node():
        versao_texto = _versao_node(node)
        if not _node_compativel(_parse_versao_node(versao_texto or "")):
            continue

        npm_nome = "npm.cmd" if sys.platform == "win32" else "npm"
        npm = node.parent / npm_nome
        if not npm.exists():
            encontrado = shutil.which("npm")
            if not encontrado:
                continue
            npm = Path(encontrado).resolve()
        return FrontRuntime(node=node, npm=npm, versao=versao_texto or "desconhecida")
    return None


def _ambiente_front(runtime: FrontRuntime) -> dict[str, str]:
    """Monta o ambiente do Vite forçando o Node compatível no início do PATH."""

    ambiente = dict(os.environ)
    caminho_node = str(runtime.node.parent)
    path_atual = ambiente.get("PATH", "")
    ambiente["PATH"] = caminho_node + (os.pathsep + path_atual if path_atual else "")
    return ambiente


def _front_deps_instaladas() -> bool:
    """Confere se as dependências npm do front já foram instaladas."""

    return FRONT_NODE_MODULES.exists()


def _instalar_deps_front(console, runtime: FrontRuntime) -> bool:
    """Instala as dependências da SPA React."""

    if not (FRONT / "package.json").exists():
        console.print("[red]✗[/red] Pasta front/ sem package.json. Não dá para subir a SPA.")
        return False

    console.print(
        f"Instalando dependências do front React com Node {runtime.versao} "
        f"([bold]{runtime.npm.name} install[/bold])..."
    )
    codigo = subprocess.call(
        [str(runtime.npm), "install"],
        cwd=FRONT,
        env=_ambiente_front(runtime),
    )
    if codigo == 0:
        console.print("[green]✓[/green] Dependências do front instaladas.")
        return True

    console.print(
        "[red]✗[/red] Não consegui instalar as dependências do front. "
        "Confira sua conexão e rode novamente o menu."
    )
    return False


def _garantir_front_pronto(console) -> FrontRuntime | None:
    """Garante Node/npm compatíveis e dependências instaladas para a SPA."""

    if _front_empacotado():
        return None

    runtime = _resolver_runtime_front()
    if runtime is None:
        console.print(
            "[red]✗[/red] Não encontrei Node compatível para o front React. "
            f"O Vite usado pelo projeto exige Node {NODE_VERSAO_MINIMA}."
        )
        console.print(
            "[dim]Dica: se você usa nvm, selecione uma versão recente e rode o menu de novo.[/dim]"
        )
        return None

    if not _front_deps_instaladas() and not _instalar_deps_front(console, runtime):
        return None
    return runtime


def _ler_valor_env_file(nome: str) -> str | None:
    """Lê uma variável do arquivo ``.env`` local, se existir."""

    if not ENV_FILE.exists():
        return None
    for linha in ENV_FILE.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha.startswith(f"{nome}="):
            return linha.split("=", 1)[1].strip()
    return None


def _ler_token_env_file() -> str | None:
    """Lê ``NOTION_TOKEN`` do arquivo ``.env`` local, se existir."""

    return _ler_valor_env_file(TOKEN_ENV)


def _valor_configurado(nome: str) -> str | None:
    """Resolve uma configuração do ambiente ou do ``.env``, ignorando placeholders."""

    valor = os.environ.get(nome, "").strip() or (_ler_valor_env_file(nome) or "").strip()
    if not valor or "xxx" in valor.lower():
        return None
    return valor


def _token_configurado() -> tuple[bool, str]:
    """Resolve a origem do token sem expor o valor.

    Returns:
        ``(configurado, origem)`` — origem é uma descrição legível, nunca o token.
    """

    do_ambiente = os.environ.get(TOKEN_ENV, "").strip()
    if do_ambiente:
        valido = do_ambiente.startswith(TOKEN_PREFIXO)
        return valido, f"variável de ambiente {TOKEN_ENV}" + (
            "" if valido else " (prefixo inesperado)"
        )

    do_arquivo = _ler_token_env_file()
    if do_arquivo and do_arquivo != f"{TOKEN_PREFIXO}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx":
        valido = do_arquivo.startswith(TOKEN_PREFIXO)
        return valido, ".env local" + ("" if valido else " (prefixo inesperado)")

    return False, "não configurado"


# --------------------------------------------------------------------------- #
# Ações do menu                                                               #
# --------------------------------------------------------------------------- #
def acao_instalar(console) -> None:
    """Instala/Setup: dependências Python, front React e cria o ``.env``."""

    console.rule("[bold]Instalar / Setup")
    if _front_empacotado():
        console.print(
            "[green]✓[/green] Esta é uma instalação empacotada: Python, Django, MCP e "
            "a SPA já estão incluídos. Configure o workspace pelo comando "
            "[bold]notion-automacoes auth[/bold]."
        )
        return
    comando_pip = _comando_pip_projeto("app,dev")
    if comando_pip is None:
        console.print(
            "[yellow]•[/yellow] O Instalar/Setup só instala dentro de um checkout do código-fonte. "
            f"{_como_instalar('app,dev')}"
        )
        return
    console.print(
        f"Instalando o pacote com os extras de app e dev ({_texto_comando(comando_pip)})..."
    )
    codigo = subprocess.call(comando_pip, cwd=RAIZ)
    if codigo == 0:
        console.print("[green]✓[/green] Pacote e dependências de app e dev instalados.")
    else:
        console.print(
            "[red]✗[/red] Falha ao instalar. Verifique sua conexão e o pip e "
            "tente de novo por aqui."
        )

    if not ENV_FILE.exists() and ENV_EXEMPLO.exists():
        ENV_FILE.write_text(ENV_EXEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
        console.print(
            "[green]✓[/green] Criado [bold].env[/bold] a partir de .env.example — "
            "edite-o (Configurar) e coloque seu token."
        )
    elif ENV_FILE.exists():
        console.print("[yellow]•[/yellow] .env já existe — mantido como está.")

    runtime = _resolver_runtime_front()
    if runtime is None:
        console.print(
            "[yellow]•[/yellow] Front React não preparado: Node compatível não encontrado "
            f"(requer {NODE_VERSAO_MINIMA})."
        )
    elif not _front_deps_instaladas():
        _instalar_deps_front(console, runtime)
    else:
        console.print(
            f"[green]✓[/green] Front React já preparado (Node {runtime.versao}, "
            "node_modules presente)."
        )


def acao_configurar(console) -> None:
    """Configurar: submenu para apontar o token e o database (sem editar à mão)."""

    import questionary

    console.rule("[bold]Configurar")
    escolha = questionary.select(
        "O que você quer configurar?",
        choices=[
            questionary.Choice("🔑  Token do Notion — credencial da integração", value="token"),
            questionary.Choice(
                "🗂️  Database de tarefas — qual database alimenta a lista", value="database"
            ),
            questionary.Choice("← Voltar", value=None),
        ],
    ).ask()
    if escolha == "token":
        _configurar_token(console)
    elif escolha == "database":
        _selecionar_database_tarefas(console)


def _configurar_token(console) -> None:
    """Orienta como apontar o token do Notion (sem editar à mão)."""

    import questionary
    from rich.panel import Panel

    console.rule("[bold]Configurar token")
    configurado, origem = _token_configurado()
    console.print(f"Token atual: [bold]{origem}[/bold].")
    console.print(
        "O token nunca é gravado neste script. Ele vive na variável de ambiente "
        f"[bold]{TOKEN_ENV}[/bold] ou no arquivo [bold].env[/bold] (ignorado pelo git).\n"
    )

    console.print(
        Panel(
            "[bold]1.[/bold] Acesse [cyan]https://www.notion.so/my-integrations[/cyan] "
            "e clique em [bold]New integration[/bold].\n"
            "[bold]2.[/bold] Dê um nome, escolha o workspace e salve. Em "
            "[bold]Configuration[/bold], copie o [bold]Internal Integration Secret[/bold] "
            f"(começa com [bold]{TOKEN_PREFIXO}[/bold]) — é o token que você vai colar aqui.\n"
            "[bold]3.[/bold] Abra no Notion a página ou o database que quer usar, clique no "
            "menu [bold]•••[/bold] (canto superior direito) → [bold]Conexões[/bold] / "
            "[bold]Connections[/bold] e selecione a integração que você acabou de criar.\n"
            "   [dim]Sem este passo o token é válido, mas não enxerga nada — o Notion só "
            "expõe à integração o que foi explicitamente compartilhado com ela.[/dim]\n"
            "[bold]4.[/bold] Volte aqui e cole o token abaixo. Depois, em "
            "[bold]Status[/bold], confira se ele foi reconhecido.",
            title="[bold]Como obter o token do Notion (passo a passo)",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    if not questionary.confirm("Já tem o token em mãos para colar agora?").ask():
        console.print(
            "[dim]Sem problema. Siga os passos acima e volte em "
            "[bold]Configurar[/bold] quando tiver o token.[/dim]"
        )
        return

    if not ENV_FILE.exists() and ENV_EXEMPLO.exists():
        if questionary.confirm("Criar um .env a partir do .env.example agora?").ask():
            ENV_FILE.write_text(ENV_EXEMPLO.read_text(encoding="utf-8"), encoding="utf-8")
            console.print("[green]✓[/green] .env criado.")

    novo = questionary.password(
        f"Cole um token do Notion para gravar no .env (começa com '{TOKEN_PREFIXO}'), "
        "ou deixe em branco para não alterar:"
    ).ask()
    if novo:
        novo = novo.strip()
        if not novo.startswith(TOKEN_PREFIXO):
            console.print(
                f"[yellow]Aviso:[/yellow] o token não começa com '{TOKEN_PREFIXO}'. "
                "Gravando assim mesmo — confira se está correto."
            )
        _gravar_token_env_file(novo)
        console.print(
            "[green]✓[/green] Token gravado em .env. "
            "Ele não aparece nos logs nem no histórico do git."
        )
    else:
        console.print("[dim]Token inalterado.[/dim]")
        console.print(
            f"Dica: você também pode exportar no shell — "
            f"[bold]export {TOKEN_ENV}={TOKEN_PREFIXO}...[/bold]"
        )


def _gravar_valor_env_file(nome: str, valor: str) -> None:
    """Grava/atualiza uma configuração no ``.env`` preservando o resto."""

    linhas: list[str] = []
    achou = False
    if ENV_FILE.exists():
        linhas = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(f"{nome}="):
            linhas[i] = f"{nome}={valor}"
            achou = True
            break
    if not achou:
        linhas.append(f"{nome}={valor}")
    ENV_FILE.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _gravar_token_env_file(token: str) -> None:
    """Grava/atualiza ``NOTION_TOKEN`` no ``.env`` preservando o resto."""

    _gravar_valor_env_file(TOKEN_ENV, token)


def _titulo_database(item: dict) -> str:
    """Extrai um título curto de um database retornado pelo ``/search``."""

    titulo = "".join(parte.get("plain_text", "") for parte in item.get("title", []))
    return titulo.strip() or "(sem título)"


def _colunas_faltantes(item: dict) -> list[str]:
    """Colunas do schema de tarefas que o database não atende, já descritas.

    Lista vazia significa que o database é compatível.
    """

    propriedades = {nome: info.get("type") for nome, info in item.get("properties", {}).items()}
    faltantes = []
    for nome, tipo in SCHEMA_TAREFAS.items():
        atual = propriedades.get(nome)
        if atual != tipo:
            faltantes.append(f"{nome} (espera {tipo}, tem {atual or 'ausente'})")
    return faltantes


def _database_compativel(item: dict) -> bool:
    """Verifica o schema mínimo usado pelo front de tarefas."""

    return not _colunas_faltantes(item)


def _nomes_data_sources_terminal(fontes: list[dict]) -> list[str]:
    """Extrai nomes das fontes de dados para orientar a escolha no terminal."""

    nomes = []
    for fonte in fontes:
        nome = str(fonte.get("name") or "").strip()
        if nome:
            nomes.append(nome)
    return nomes


def _partes_database(item: tuple) -> tuple[str, str, bool, list[str], list[str]]:
    """Aceita registros antigos de teste e registros novos com data sources."""

    titulo, db_id, compativel, faltantes, *resto = item
    fontes = resto[0] if resto else []
    return titulo, db_id, compativel, faltantes, fontes


def _buscar_databases(token: str) -> list[tuple[str, str, bool, list[str], list[str]]]:
    """Lista TODOS os databases acessíveis à integração, ordenados.

    Cada item é ``(titulo, db_id, compativel, faltantes, data_sources)``.
    Compatíveis (que atendem ao schema de tarefas) vêm primeiro; dentro de cada
    grupo, em ordem alfabética. Mostrar todos — não só os compatíveis — deixa a
    pessoa escolher livremente um database mesmo que precise ajustar as colunas
    depois.
    """

    from felixo_notion_mcp import NotionClient

    cliente = NotionClient(token=token)
    itens = cliente.buscar(
        buscar_todos=True,
        filtro={"property": "object", "value": "database"},
    )
    databases = []
    for item in itens:
        db_id = item.get("id")
        if not db_id:
            continue
        faltantes = _colunas_faltantes(item)
        fontes = []
        if not faltantes:
            fontes = _nomes_data_sources_terminal(cliente.listar_data_sources(db_id))
        databases.append((_titulo_database(item), db_id, not faltantes, faltantes, fontes))
    # Compatíveis primeiro (not compativel == False ordena antes), depois título.
    return sorted(databases, key=lambda d: (not d[2], d[0].casefold()))


def _rotulo_database_terminal(titulo: str, database_id: str) -> str:
    """Monta um rótulo curto e confiável para mensagens do terminal."""

    return f"{titulo} ({database_id[:8]}…)"


def _url_database_terminal(database_id: str) -> str:
    """Monta a URL canônica do database no Notion a partir do ID."""

    return f"https://app.notion.com/p/{database_id.replace('-', '')}"


def _garantir_database_tarefas(console) -> bool:
    """Pergunta qual database de tarefas usar antes de subir o site.

    Usado pelo "Iniciar tudo" — **sempre** pergunta, com o database atual já
    pré-selecionado (basta dar Enter para manter). Se a pessoa cancelar e já
    houver um database salvo, mantém esse e segue subindo o site; só barra
    quando ainda não há nenhum configurado.
    """

    return _selecionar_database_tarefas(console, manter_atual_ao_cancelar=True)


def _selecionar_database_tarefas(console, *, manter_atual_ao_cancelar: bool = False) -> bool:
    """Busca, escolhe e persiste o database de tarefas no ``.env``.

    Sempre re-consulta o Notion e regrava ``NOTION_DATABASE_ID``, com o database
    atual pré-selecionado na lista. É o caminho usado tanto ao subir o site
    ("Iniciar tudo") quanto pelo menu Configurar.

    ``manter_atual_ao_cancelar``: quando ``True`` (fluxo de subir), cancelar a
    escolha mantém o database já salvo e retorna sucesso, desde que exista um.
    Quando ``False`` (menu Configurar), cancelar apenas não altera nada.
    """

    import questionary

    token = _valor_configurado(TOKEN_ENV)
    if not token or not token.startswith(TOKEN_PREFIXO):
        console.print(
            "[yellow]•[/yellow] Configure primeiro o token do Notion pela opção "
            "[bold]Configurar[/bold]."
        )
        return False

    atual = _valor_configurado(DATABASE_ENV)

    console.print("Procurando databases compartilhados com a integração...")
    try:
        databases = _buscar_databases(token)
    except Exception as exc:  # noqa: BLE001 - fronteira externa com mensagem segura
        console.print(
            "[red]✗[/red] Não consegui consultar os databases do Notion. "
            f"Verifique a integração e tente novamente ({type(exc).__name__})."
        )
        # Falha de rede ao subir não deve travar quem já tem um database salvo.
        return bool(atual) if manter_atual_ao_cancelar else False

    if not databases:
        colunas = ", ".join(f"{nome} ({tipo})" for nome, tipo in SCHEMA_TAREFAS.items())
        console.print(
            "[red]✗[/red] Nenhum database compartilhado com a integração foi encontrado. "
            f"Compartilhe um database (idealmente com: [bold]{colunas}[/bold]) e tente de novo."
        )
        return False

    compativeis = sum(1 for item in databases if _partes_database(item)[2])
    console.print(
        f"[dim]{len(databases)} databases acessíveis · {compativeis} já compatíveis "
        "(✓). Os demais (⚠) podem ser usados, mas pedem ajuste de colunas.[/dim]"
    )
    if compativeis:
        console.print("[dim]Compatíveis detectados (título pela API + ID + URL):[/dim]")
        for item in databases:
            titulo, db_id, ok, _, fontes = _partes_database(item)
            if not ok:
                continue
            atual_label = " [atual]" if db_id == atual else ""
            console.print(f"  • [bold]{titulo}[/bold]{atual_label}")
            console.print(f"    ID: {db_id}")
            if fontes:
                console.print(f"    Data source: {', '.join(fontes)}")
            console.print(f"    URL: {_url_database_terminal(db_id)}")

    # Mapa para descrever o database escolhido (título + colunas que faltam).
    por_id = {
        db_id: (titulo, faltantes)
        for titulo, db_id, _, faltantes, _ in map(_partes_database, databases)
    }
    escolha_atual = next(
        (db_id for _, db_id, _, _, _ in map(_partes_database, databases) if db_id == atual),
        None,
    )
    escolhas = [
        questionary.Choice(
            f"{'✓' if ok else '⚠'} {titulo} · {db_id}"
            + ("  [atual]" if db_id == atual else ""),
            value=db_id,
        )
        for titulo, db_id, ok, _, _ in map(_partes_database, databases)
    ]
    rotulo_cancelar = "Manter o atual" if (manter_atual_ao_cancelar and atual) else "Cancelar"
    escolhas.append(questionary.Choice(rotulo_cancelar, value=None))
    database_id = questionary.select(
        "Qual database real do Notion deve alimentar a lista de tarefas?",
        choices=escolhas,
        default=escolha_atual,
    ).ask()
    if not database_id:
        if manter_atual_ao_cancelar and atual:
            titulo_atual = por_id.get(atual, ("database atual", []))[0]
            console.print(
                f"[dim]Mantendo o database atual: "
                f"{_rotulo_database_terminal(titulo_atual, atual)}.[/dim]"
            )
            os.environ.setdefault(DATABASE_ENV, atual)
            return True
        console.print("[dim]Configuração cancelada.[/dim]")
        return False

    titulo_escolhido, faltantes = por_id[database_id]
    if faltantes:
        console.print(
            f"[yellow]⚠[/yellow] [bold]{titulo_escolhido}[/bold] não tem o schema de "
            "tarefas. O site pode falhar ao ler/criar tarefas até você ajustar:"
        )
        for falta in faltantes:
            console.print(f"   • {falta}")
        if not questionary.confirm("Usar este database mesmo assim?", default=False).ask():
            if manter_atual_ao_cancelar and atual:
                titulo_atual = por_id.get(atual, ("database atual", []))[0]
                console.print(
                    f"[dim]Mantendo o database atual: "
                    f"{_rotulo_database_terminal(titulo_atual, atual)}.[/dim]"
                )
                os.environ.setdefault(DATABASE_ENV, atual)
                return True
            console.print("[dim]Configuração cancelada.[/dim]")
            return False

    _gravar_valor_env_file(DATABASE_ENV, database_id)
    os.environ[DATABASE_ENV] = database_id
    console.print(
        "[green]✓[/green] Database de tarefas salvo no .env: "
        f"[bold]{_rotulo_database_terminal(titulo_escolhido, database_id)}[/bold]. "
        "Essa escolha será reutilizada nas próximas execuções."
    )
    return True


def acao_rodar(console) -> None:
    """Iniciar / Rodar: submenu com os exemplos executáveis da biblioteca."""

    import questionary

    console.rule("[bold]Iniciar / Rodar")

    if not _pacote_instalado():
        console.print(
            "[yellow]•[/yellow] Faltam dependências do felixo_notion_mcp "
            f"({', '.join(_dependencias_faltando())}). "
            "Use [bold]Instalar / Setup[/bold] primeiro "
            "(o menu não obriga, mas os exemplos vão falhar sem elas)."
        )
    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. Os exemplos chamam a API do Notion "
            "e vão falhar sem um token válido — ajuste em [bold]Configurar[/bold]."
        )

    escolha = questionary.select(
        "O que você quer rodar?",
        choices=[
            questionary.Choice(
                "export_rows.py — cria uma página por linha de exemplo num database",
                value="export_rows",
            ),
            questionary.Choice(
                "check_schema.py — valida o schema de um database contra o esperado",
                value="check_schema",
            ),
            questionary.Choice(
                "sync_from_csv.py — valida o schema e cria uma página por linha de um CSV",
                value="sync_from_csv",
            ),
            questionary.Choice(
                "gerenciar_tarefas.py — lista, cria e conclui tarefas via TaskList",
                value="gerenciar_tarefas",
            ),
            questionary.Choice("Voltar", value=None),
        ],
    ).ask()

    if not escolha:
        return

    database_id = questionary.text(
        "ID do database do Notion (deixe em branco para cancelar):"
    ).ask()
    if not database_id:
        console.print("[dim]Cancelado.[/dim]")
        return

    args = [database_id.strip()]
    if escolha == "sync_from_csv":
        caminho_csv = questionary.text(
            "Caminho do arquivo CSV (deixe em branco para cancelar):"
        ).ask()
        if not caminho_csv:
            console.print("[dim]Cancelado.[/dim]")
            return
        args.append(caminho_csv.strip())

    script = EXEMPLOS / f"{escolha}.py"
    console.print(f"Executando [bold]{script.name}[/bold]...\n")
    ambiente = dict(os.environ)
    token_arquivo = _ler_token_env_file()
    if token_arquivo and not ambiente.get(TOKEN_ENV):
        ambiente[TOKEN_ENV] = token_arquivo  # passa o token do .env só ao subprocesso
    codigo = subprocess.call([sys.executable, str(script), *args], cwd=RAIZ, env=ambiente)
    if codigo == 0:
        console.print("\n[green]✓[/green] Exemplo concluído.")
    else:
        console.print(
            f"\n[red]✗[/red] O exemplo terminou com código {codigo}. "
            "Confira o token, o ID do database e a mensagem acima."
        )


def _instalar_extra_servidor(console) -> bool:
    """Instala o extra Django e confirma que ele ficou importável."""

    comando = _comando_pip_projeto("app")
    if comando is None:
        console.print(f"[yellow]•[/yellow] Nada será instalado por aqui. {_como_instalar('app')}")
        return False

    console.print("Instalando os componentes do servidor web...")
    codigo = subprocess.call(comando, cwd=RAIZ)
    if codigo == 0 and _django_disponivel():
        console.print("[green]✓[/green] Componentes do servidor instalados.")
        return True

    console.print(
        "[red]✗[/red] Não consegui instalar o Django. Instale manualmente:\n"
        f"  {_texto_comando(comando)}"
    )
    return False


def _ambiente_servidor() -> dict[str, str]:
    """Monta o ambiente local do Django sem expor o token."""

    ambiente = dict(os.environ)
    ambiente.setdefault("DJANGO_DEBUG", "1")
    token_arquivo = _ler_token_env_file()
    if token_arquivo and not ambiente.get(TOKEN_ENV):
        ambiente[TOKEN_ENV] = token_arquivo
    return ambiente


def _aplicar_migracoes(console, ambiente: dict[str, str]) -> bool:
    """Aplica as migrações operacionais antes de iniciar o app."""

    console.print("Aplicando migrações do estado operacional (SQLite)...")
    codigo = subprocess.call(
        [sys.executable, str(MANAGE_PY), "migrate", "--noinput"],
        cwd=SERVIDOR,
        env=ambiente,
    )
    if codigo == 0:
        return True
    console.print(f"[red]✗[/red] Falha ao migrar (código {codigo}).")
    return False


def _app_web_ativo(url: str = APP_HEALTH_URL) -> bool:
    """Confirma que a API Django responde como este projeto."""

    try:
        with urllib.request.urlopen(url, timeout=0.5) as resposta:  # noqa: S310 - URL local fixa
            corpo = json.loads(resposta.read().decode("utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError, urllib.error.URLError):
        return False
    return (
        isinstance(corpo, dict)
        and corpo.get("status") == "ok"
        and corpo.get("service") == "automacoes-notion"
    )


def _front_web_ativo(url: str = FRONT_URL) -> bool:
    """Confirma que a SPA React/Vite ou empacotada está respondendo."""

    try:
        with urllib.request.urlopen(url, timeout=0.5) as resposta:  # noqa: S310 - URL local fixa
            html = resposta.read().decode("utf-8", errors="replace")
    except (OSError, UnicodeError, urllib.error.URLError):
        return False
    return resposta.status == 200 and 'id="root"' in html and (
        "/src/main.jsx" in html or "/static/frontend/assets/" in html
    )


def _abrir_navegador_quando_pronto(
    console,
    *,
    tentativas: int = 40,
    intervalo: float = 0.25,
) -> None:
    """Espera API + SPA responderem e abre o front React no navegador padrão."""

    for _ in range(tentativas):
        if _app_web_ativo() and _front_web_ativo():
            if webbrowser.open(APP_URL):
                console.print(f"[green]✓[/green] Navegador aberto em [bold]{APP_URL}[/bold].")
            else:
                console.print(
                    "[yellow]•[/yellow] O navegador não abriu automaticamente. "
                    f"Acesse [bold]{APP_URL}[/bold]."
                )
            return
        time.sleep(intervalo)

    console.print(
        "[yellow]•[/yellow] A API ou o front demorou para responder. "
        f"Quando estiver pronto, acesse [bold]{APP_URL}[/bold]."
    )


def _agendar_abertura_navegador(console) -> None:
    """Inicia em background a espera pelo servidor e a abertura do navegador."""

    threading.Thread(
        target=_abrir_navegador_quando_pronto,
        args=(console,),
        daemon=True,
        name="abrir-navegador-notion",
    ).start()


def _comando_front(runtime: FrontRuntime) -> list[str]:
    """Comando padrão para subir a SPA React com proxy para a API Django."""

    return [
        str(runtime.npm),
        "run",
        "dev",
        "--",
        "--host",
        FRONT_HOST,
        "--port",
        FRONT_PORT,
    ]


def _encerrar_processos(processos: list[subprocess.Popen]) -> None:
    """Encerra processos filhos iniciados pelo menu."""

    for processo in processos:
        if processo.poll() is None:
            processo.terminate()
    for processo in processos:
        if processo.poll() is None:
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()


def _aguardar_processos(console, processos: list[subprocess.Popen]) -> None:
    """Mantém o terminal vivo enquanto API/front rodam."""

    try:
        while processos and all(processo.poll() is None for processo in processos):
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.print("\n[dim]Encerrando aplicação local...[/dim]")
        _encerrar_processos(processos)
        return

    for processo in processos:
        codigo = processo.poll()
        if codigo not in (None, 0):
            console.print(
                f"[red]✗[/red] Um processo da aplicação terminou com código {codigo}. "
                "Confira a saída acima para entender o motivo."
            )
            _encerrar_processos(processos)
            return


def acao_iniciar_tudo(console) -> None:
    """Inicia API e SPA, usando bundle embutido quando instalado pelo pip."""

    console.rule("[bold]Iniciar tudo")

    if not _django_disponivel():
        console.print("[yellow]•[/yellow] O Django (extra app) não está instalado.")
        if _comando_de_instalacao_confirmado(
            console, "Instalar o extra app agora?"
        ) is None or not _instalar_extra_servidor(console):
            return

    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. O app abre normalmente, mas as tarefas "
            "do Notion só carregam depois de configurar o token."
        )

    if not _garantir_database_tarefas(console):
        return

    runtime = None
    if not _front_empacotado():
        runtime = _garantir_front_pronto(console)
        if runtime is None:
            return

    api_ativa = _app_web_ativo()
    front_ativo = _front_web_ativo()
    if api_ativa and front_ativo:
        console.print("[green]✓[/green] API e front React já estão rodando.")
        if not webbrowser.open(APP_URL):
            console.print(f"Acesse [bold]{APP_URL}[/bold] no navegador.")
        return

    ambiente = _ambiente_servidor()
    if not api_ativa and not _aplicar_migracoes(console, ambiente):
        return

    if _front_empacotado():
        console.print(
            f"Subindo API em [bold]{API_URL}[/bold] com a SPA empacotada. "
            "O navegador abrirá automaticamente."
        )
    else:
        console.print(
            f"Subindo API em [bold]{API_URL}[/bold] e front React em "
            f"[bold]{APP_URL}[/bold]. O navegador abrirá automaticamente."
        )
    _agendar_abertura_navegador(console)

    processos: list[subprocess.Popen] = []
    try:
        if api_ativa:
            console.print(f"[green]✓[/green] API já ativa em [bold]{API_URL}[/bold].")
        else:
            processos.append(
                subprocess.Popen(
                    [sys.executable, str(MANAGE_PY), "runserver", API_ENDERECO_PADRAO],
                    cwd=SERVIDOR,
                    env=ambiente,
                )
            )

        if _front_empacotado():
            console.print(
                f"[green]✓[/green] SPA empacotada será servida pelo Django em "
                f"[bold]{APP_URL}[/bold]."
            )
        elif front_ativo:
            console.print(f"[green]✓[/green] Front React já ativo em [bold]{APP_URL}[/bold].")
        else:
            assert runtime is not None
            processos.append(
                subprocess.Popen(
                    _comando_front(runtime),
                    cwd=FRONT,
                    env=_ambiente_front(runtime),
                )
            )

        _aguardar_processos(console, processos)
    except OSError as exc:
        _encerrar_processos(processos)
        console.print(f"[red]✗[/red] Não consegui iniciar a aplicação local: {exc}")
    except KeyboardInterrupt:
        console.print("\n[dim]Aplicação encerrada.[/dim]")
        _encerrar_processos(processos)


def acao_servidor(console) -> None:
    """Subir API: aplica as migrações e sobe o servidor Django local."""

    import questionary

    console.rule("[bold]Subir API Django")

    if not _django_disponivel():
        console.print("[yellow]•[/yellow] O Django (extra app) não está instalado.")
        if _comando_de_instalacao_confirmado(
            console, "Instalar o extra app agora?"
        ) is None or not _instalar_extra_servidor(console):
            console.print("[dim]Sem o Django a API não sobe.[/dim]")
            return

    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. A API sobe, mas as rotas que falam "
            "com o Notion vão falhar até o token ser configurado em [bold]Configurar[/bold]."
        )

    endereco = questionary.text(
        "Endereço do servidor (host:porta):", default="127.0.0.1:8000"
    ).ask()
    if not endereco:
        console.print("[dim]Cancelado.[/dim]")
        return
    endereco = endereco.strip()

    ambiente = _ambiente_servidor()
    if not _aplicar_migracoes(console, ambiente):
        return

    console.print(
        f"Subindo a API em [bold]http://{endereco}/[/bold] — health em "
        "[bold]/api/health[/bold]. Pressione [bold]Ctrl+C[/bold] para encerrar este processo."
    )
    try:
        subprocess.call(
            [sys.executable, str(MANAGE_PY), "runserver", endereco], cwd=SERVIDOR, env=ambiente
        )
    except KeyboardInterrupt:
        console.print("\n[dim]API encerrada.[/dim]")


def acao_mcp(console) -> None:
    """Subir o servidor MCP para o Felixo-AI-Core."""

    import questionary

    console.rule("[bold]Subir servidor MCP")

    if not _mcp_disponivel():
        console.print("[yellow]•[/yellow] O SDK MCP não está instalado.")
        # O SDK MCP é dependência do pacote; reinstalar o projeto o traz de volta.
        comando_pip = _comando_de_instalacao_confirmado(console, "Instalar o SDK MCP agora?")
        if comando_pip is None:
            console.print("[dim]Sem o SDK MCP o servidor não sobe.[/dim]")
            return
        codigo = subprocess.call(comando_pip, cwd=RAIZ)
        if codigo != 0 or not _mcp_disponivel():
            console.print(
                "[red]✗[/red] Não consegui instalar o MCP. Instale manualmente:\n"
                f"  {_texto_comando(comando_pip)}"
            )
            return

    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. As ferramentas MCP que falam "
            "com o Notion vão falhar até o token ser configurado em [bold]Configurar[/bold]."
        )

    database_id = os.environ.get(DATABASE_ENV, "").strip() or _ler_valor_env_file(DATABASE_ENV)
    if not database_id:
        console.print(
            f"[yellow]•[/yellow] {DATABASE_ENV} não configurado. As ferramentas MCP "
            "vão falhar até o database de tarefas ser definido no ambiente ou no .env."
        )

    modo = questionary.select(
        "Modo de transporte:",
        choices=[
            questionary.Choice(
                "stdio (padrão — o Felixo-AI-Core spawna assim)",
                value="stdio",
            ),
            questionary.Choice(
                "Streamable HTTP (debug local — endpoint /mcp)",
                value="streamable-http",
            ),
        ],
    ).ask()
    if not modo:
        console.print("[dim]Cancelado.[/dim]")
        return

    ambiente = dict(os.environ)
    token_arquivo = _ler_token_env_file()
    if token_arquivo and not ambiente.get(TOKEN_ENV):
        ambiente[TOKEN_ENV] = token_arquivo

    args = [sys.executable, str(MCP_SERVER_PY)]
    if modo == "streamable-http":
        args.extend(["--transport", "streamable-http"])
        console.print(
            "Subindo servidor MCP em [bold]http://127.0.0.1:8000/mcp[/bold] — "
            "Pressione [bold]Ctrl+C[/bold] para encerrar este servidor."
        )
    else:
        console.print(
            "Subindo servidor MCP em modo stdio — "
            "Pressione [bold]Ctrl+C[/bold] para encerrar este servidor."
        )

    try:
        subprocess.call(args, cwd=SERVIDOR, env=ambiente)
    except KeyboardInterrupt:
        console.print("\n[dim]Servidor MCP encerrado.[/dim]")


def acao_cli(console) -> None:
    """Mostra a ajuda da CLI para IA."""

    console.rule("[bold]CLI para IA")
    console.print(
        "A CLI usa os mesmos services da API/MCP e pode emitir JSON estável para "
        "scripts ou IAs locais.\n"
    )
    subprocess.run([sys.executable, "-m", MODULO_CLI, "--help"], cwd=RAIZ, check=False)
    console.print(
        "\n[dim]Exemplo JSON:[/dim]\n"
        f"  {sys.executable} -m {MODULO_CLI} --json listar\n"
        f'  {sys.executable} -m {MODULO_CLI} --json criar "Nova tarefa" --status "Entrada"\n'
        f'  {sys.executable} -m {MODULO_CLI} --json buscar "nota"\n'
        f"  {sys.executable} -m {MODULO_CLI} --json conteudo <page_id>"
    )


def acao_atualizar_github(console) -> None:
    """Re-sincroniza o database GITHUB: repos novos, propriedades e README mudado."""

    console.rule("[bold]Atualizar inventário GitHub")

    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. A atualização chama a API do Notion "
            "e vai falhar sem um token válido — ajuste em [bold]Configurar[/bold]."
        )
        return

    ambiente = dict(os.environ)
    token_arquivo = _ler_token_env_file()
    if token_arquivo and not ambiente.get("NOTION_TOKEN"):
        ambiente["NOTION_TOKEN"] = token_arquivo

    contas = ambiente.get("GITHUB_CONTAS", "").strip()
    if not contas:
        import questionary

        contas = (
            questionary.text(
                "Contas do GitHub a sincronizar (separadas por vírgula):"
            ).ask()
            or ""
        ).strip()
    if not contas:
        console.print(
            "[yellow]•[/yellow] Nenhuma conta informada. Defina [bold]GITHUB_CONTAS[/bold] "
            "no .env ou informe ao rodar."
        )
        return

    if not ambiente.get("GITHUB_TOKEN"):
        console.print(
            "[dim]Dica: defina GITHUB_TOKEN para incluir repositórios privados da sua "
            "própria conta.[/dim]\n"
        )

    console.print(
        f"Atualizando os repositórios de [bold]{contas}[/bold] no database GITHUB "
        "(NOTION_DATABASE_ID).\n"
    )
    subprocess.run(
        [sys.executable, "-m", MODULO_CLI, "atualizar-github", "--contas", contas],
        cwd=RAIZ,
        env=ambiente,
        check=False,
    )


def acao_mapear(console) -> None:
    """Mapear workspace: coleta o mapa e gera o relatório HTML navegável."""

    console.rule("[bold]Mapear workspace")

    if not _pacote_instalado():
        console.print(
            "[yellow]•[/yellow] Faltam dependências do felixo_notion_mcp "
            f"({', '.join(_dependencias_faltando())}). "
            "Use [bold]Instalar / Setup[/bold] primeiro."
        )
        return
    configurado, origem = _token_configurado()
    if not configurado:
        console.print(
            f"[yellow]•[/yellow] Token {origem}. O mapeamento chama a API do Notion "
            "e vai falhar sem um token válido — ajuste em [bold]Configurar[/bold]."
        )
        return

    from felixo_notion_mcp import NotionClient
    from felixo_notion_mcp.core.exceptions import NotionSyncError
    from felixo_notion_mcp.services import mapa_workspace

    token = os.environ.get(TOKEN_ENV, "").strip() or _ler_token_env_file()
    # Na pasta atual: instalado, a "raiz" é o site-packages, lugar errado para o relatório.
    pasta = Path.cwd()
    console.print("Coletando o mapa do workspace (pode levar ~1 min)...")
    try:
        mapa = mapa_workspace.coletar_mapa(cliente=NotionClient(token=token))
        gravados = mapa_workspace.gravar_mapa(
            mapa, json_saida=pasta / "mapa.json", html=pasta / "mapa.html"
        )
    except (NotionSyncError, OSError) as erro:
        console.print(f"[red]✗[/red] Falha ao mapear o workspace: {erro}")
        return
    console.print(
        f"[green]✓[/green] Pronto: [bold]{gravados['json']}[/bold] e "
        f"[bold]{gravados['html']}[/bold]. Abra o HTML no navegador."
    )


def _comandos_qualidade() -> list[list[str]]:
    """Os comandos do gate local de Python, na ordem, com o Python do projeto.

    É o gate do ``CONTRIBUTING.md``: ``ruff check .`` e ``pytest -q``, rodados na raiz do
    checkout. O ``lint`` e o ``build`` do ``front/`` rodam com ``npm`` dentro dele.
    """

    python = _executavel_projeto()
    return [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "pytest", "-q"],
    ]


def acao_qualidade(console) -> None:
    """Roda o gate local de qualidade do Python (``ruff`` e ``pytest``) na raiz do checkout."""

    console.rule("[bold]Qualidade")
    if not MODO_CHECKOUT:
        console.print(
            "[yellow]•[/yellow] O gate de qualidade só existe num checkout do código-fonte "
            "(precisa de pyproject.toml, tests/ e das ferramentas de dev). Nesta instalação "
            "não há o que rodar."
        )
        return
    console.print(
        "Executando o gate local: ruff check . e pytest -q.\n"
        "[dim]Se alguma ferramenta faltar, rode Instalar/Setup (instala o extra dev). Para o "
        "front, rode npm run lint e npm run build dentro de front/.[/dim]\n"
    )
    falhas = 0
    for comando in _comandos_qualidade():
        console.print(f"[dim]$ {_texto_comando(comando)}[/dim]")
        if subprocess.run(comando, cwd=RAIZ, check=False).returncode != 0:
            falhas += 1
    if falhas:
        console.print(f"[red]✗[/red] O gate não passou ({falhas} de 2 etapas falharam).")
    else:
        console.print("[green]✓[/green] O gate passou: ruff e pytest sem falhas.")


def acao_status(console) -> None:
    """Status: mostra o estado real do ambiente, sem expor segredo."""

    from rich.markup import escape
    from rich.table import Table

    console.rule("[bold]Status")
    tabela = Table(show_header=True, header_style="bold")
    tabela.add_column("Item")
    tabela.add_column("Estado")

    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 10)
    tabela.add_row("Python", f"[green]{py}[/green]" if py_ok else f"[red]{py} (requer 3.10+)[/red]")

    if _pacote_instalado():
        import felixo_notion_mcp

        tabela.add_row(
            "Pacote felixo_notion_mcp",
            f"[green]instalado[/green] (v{getattr(felixo_notion_mcp, '__version__', '?')})",
        )
    else:
        tabela.add_row(
            "Pacote felixo_notion_mcp",
            f"[yellow]não instalado[/yellow] (faltam {', '.join(_dependencias_faltando())}; "
            "use Instalar/Setup)",
        )

    origem = origem_do_pacote()
    tabela.add_row(
        "Origem do pacote",
        escape(origem.descricao()) if origem else "[yellow]não encontrada[/yellow]",
    )
    tabela.add_row(
        "Deps do menu (rich/questionary)",
        "[green]ok[/green]" if _tui_disponivel() else "[yellow]faltando[/yellow]",
    )
    tabela.add_row(
        "Django (API)",
        "[green]ok[/green]" if _django_disponivel() else "[yellow]faltando[/yellow]",
    )
    if _front_empacotado():
        tabela.add_row("Front", "[green]SPA empacotada no wheel[/green]")
        tabela.add_row("Node do front", "[green]não necessário[/green]")
        tabela.add_row("Deps do front", "[green]embutidas no pacote[/green]")
    else:
        runtime = _resolver_runtime_front()
        if runtime is None:
            tabela.add_row(
                "Node do front",
                f"[yellow]não encontrado/compatível[/yellow] (requer {NODE_VERSAO_MINIMA})",
            )
            tabela.add_row("Deps do front", "[yellow]indisponíveis sem Node compatível[/yellow]")
        else:
            tabela.add_row("Node do front", f"[green]{runtime.versao}[/green]")
            tabela.add_row(
                "Deps do front",
                "[green]ok[/green]" if _front_deps_instaladas() else "[yellow]faltando[/yellow]",
            )
    tabela.add_row(
        "Arquivo .env",
        "[green]existe[/green]" if ENV_FILE.exists() else "[yellow]ausente[/yellow]",
    )
    configurado, origem = _token_configurado()
    tabela.add_row(
        f"Token ({TOKEN_ENV})",
        f"[green]{origem}[/green]" if configurado else f"[yellow]{origem}[/yellow]",
    )
    database = _valor_configurado(DATABASE_ENV)
    tabela.add_row(
        f"Database ({DATABASE_ENV})",
        f"[green]configurado ({database[:8]}…)[/green]"
        if database
        else "[yellow]não configurado[/yellow]",
    )

    console.print(tabela)


def _acoes_menu():
    """Retorna as ações disponíveis e seus rótulos públicos."""

    return {
        "tudo": (
            "🚀  Iniciar tudo — abre SPA React + API no navegador",
            acao_iniciar_tudo,
        ),
        "rodar": ("▶  Iniciar / Rodar — executa um exemplo da biblioteca", acao_rodar),
        "servidor": ("🌐  Subir API Django — health e rotas REST locais", acao_servidor),
        "mcp": ("🔗  Subir servidor MCP — ponte para o Felixo-AI-Core", acao_mcp),
        "cli": ("⌘  CLI para IA — mostra comandos e saída JSON", acao_cli),
        "github": (
            "🐙  Atualizar inventário GitHub — sincroniza repos e README",
            acao_atualizar_github,
        ),
        "mapear": ("🗺  Mapear workspace — gera mapa.json e mapa.html navegável", acao_mapear),
        "qualidade": ("✅  Qualidade — roda Ruff e Pytest (só no checkout)", acao_qualidade),
        "instalar": ("⬇  Instalar / Setup — instala deps e cria o .env", acao_instalar),
        "configurar": ("⚙  Configurar — aponta o token do Notion", acao_configurar),
        "status": ("ℹ  Status — mostra o estado real do ambiente", acao_status),
    }


def _categorias_menu() -> list[tuple[str, list[str]]]:
    """Agrupa as ações em poucas categorias, para um menu enxuto por subtelas.

    Cada categoria lista as chaves de ``_acoes_menu()`` que pertencem a ela. O
    menu mostra primeiro as categorias (pouca informação de uma vez) e só então
    as ações de dentro — mais intuitivo que despejar tudo numa tela só. ``status``
    fica como atalho direto (ação única comum), fora das subtelas.
    """

    return [
        ("🚀  Usar o app — abrir e rodar", ["tudo", "rodar"]),
        ("🤖  Para IA e integrações — CLI, GitHub, MCP, mapa", ["cli", "github", "mcp", "mapear"]),
        (
            "⚙  Configurar e instalar — token, deps, API, qualidade",
            ["configurar", "instalar", "servidor", "qualidade"],
        ),
    ]


def _executar_acao_dedicada(chave: str) -> None:
    """Executa uma ação no processo filho e mantém o terminal legível ao final."""

    from rich.console import Console

    acoes = _acoes_menu()
    console = Console()
    texto, acao = acoes[chave]
    console.print(f"[bold cyan]{texto}[/bold cyan]\n")

    try:
        acao(console)
    except KeyboardInterrupt:
        console.print("\n[dim]Ação interrompida.[/dim]")
    except Exception as exc:  # noqa: BLE001 - mostra erro amigável no terminal dedicado
        console.print(f"\n[red]Erro:[/red] {exc}")
    finally:
        if sys.stdin.isatty():
            try:
                input("\nPressione Enter para fechar este terminal...")
            except (EOFError, KeyboardInterrupt):
                pass


# --------------------------------------------------------------------------- #
# Loop do menu                                                                #
# --------------------------------------------------------------------------- #
def _disparar_acao(console, chave: str) -> None:
    """Abre uma ação num terminal dedicado e reporta o resultado."""

    acoes = _acoes_menu()
    abriu, mensagem = _abrir_terminal_dedicado(chave, acoes[chave][0])
    estilo = "green" if abriu else "red"
    simbolo = "✓" if abriu else "✗"
    console.print(f"[{estilo}]{simbolo}[/{estilo}] {mensagem}")
    if abriu:
        console.print("[dim]O menu continua disponível para iniciar outras ações.[/dim]")
    console.print()


def _submenu_categoria(console, titulo: str, chaves: list[str]) -> None:
    """Mostra as ações de uma categoria e dispara a escolhida."""

    import questionary

    acoes = _acoes_menu()
    while True:
        escolha = questionary.select(
            titulo,
            choices=[
                *(questionary.Choice(acoes[chave][0], value=chave) for chave in chaves),
                questionary.Choice("← Voltar", value=None),
            ],
        ).ask()
        if not escolha:
            return
        _disparar_acao(console, escolha)


def _menu_loop() -> None:
    """Desenha o menu interativo (categorias → ações) até a pessoa sair."""

    import questionary
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(
        Panel.fit(
            "[bold cyan]Automações do Notion[/bold cyan]\n"
            "Aplicação local para operar Notion, GitHub, IA e MCP.\n"
            "[dim]Escolha uma categoria; cada uma abre suas opções.[/dim]",
            border_style="cyan",
        )
    )

    categorias = _categorias_menu()

    while True:
        escolha = questionary.select(
            "O que você quer fazer?",
            choices=[
                *(questionary.Choice(titulo, value=i) for i, (titulo, _) in enumerate(categorias)),
                questionary.Choice("ℹ  Status — estado do ambiente", value="status"),
                questionary.Choice("⏿  Sair", value="sair"),
            ],
        ).ask()

        if escolha in (None, "sair"):
            console.print("[dim]Até mais![/dim]")
            return
        if escolha == "status":
            _disparar_acao(console, "status")
            continue

        titulo, chaves = categorias[escolha]
        _submenu_categoria(console, titulo, chaves)


def main(argv: list[str] | None = None) -> None:
    """Ponto de entrada: garante a TUI e abre o menu (ou um fallback claro)."""

    argumentos = sys.argv[1:] if argv is None else argv
    if argumentos in (["--help"], ["-h"]):
        print(
            "Uso: notion-automacoes-app [--action {tudo,rodar,servidor,mcp,cli,"
            "github,mapear,qualidade,instalar,configurar,status}]\n"
            "Sem argumentos, abre o menu interativo."
        )
        return
    acao_solicitada: str | None = None
    if argumentos:
        if len(argumentos) != 2 or argumentos[0] != "--action":
            opcoes = ", ".join(_acoes_menu())
            raise SystemExit(f"Uso: notion-automacoes-app [--action {{{opcoes}}}]")
        acao_solicitada = argumentos[1]
        if acao_solicitada not in _acoes_menu():
            opcoes = ", ".join(_acoes_menu())
            raise SystemExit(f"Ação desconhecida: {acao_solicitada}. Opções: {opcoes}")

    _exportar_pacote_para_filhos()
    _reexecutar_no_python_do_projeto(argumentos)

    if not _tui_disponivel():
        print(
            "O menu interativo precisa de 'questionary' e 'rich'.\n"
            "Posso instalá-los agora neste ambiente Python."
        )
        resposta = input("Instalar agora? [S/n] ").strip().lower()
        if resposta in ("", "s", "sim", "y", "yes"):
            if not _instalar_deps_tui() or not _tui_disponivel():
                raise SystemExit(1)
        else:
            print(
                "Sem as dependências do menu não dá para abrir a TUI. "
                f"Instale quando quiser:\n  {sys.executable} -m pip install "
                f"{' '.join(_DEPS_TUI)}"
            )
            raise SystemExit(1)

    if acao_solicitada:
        _executar_acao_dedicada(acao_solicitada)
        return

    try:
        _menu_loop()
    except KeyboardInterrupt:
        print("\nAté mais!")


if __name__ == "__main__":
    main()
