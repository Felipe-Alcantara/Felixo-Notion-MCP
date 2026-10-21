"""Borda da CLI distribuída do ecossistema Automações do Notion.

Este módulo só interpreta o comando de alto nível e delega as regras existentes
para a CLI de tarefas, o launcher do app e o servidor MCP. O comportamento de
domínio fica em ``domain/`` e ``services/``.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from felixo_notion_mcp.api.cli import atualizacao_nativa
from felixo_notion_mcp.api.cli.versao import VERSAO_FONTE, ler_versao_embutida
from felixo_notion_mcp.core import config
from felixo_notion_mcp.core.constants import PYTHON_MINIMO
from felixo_notion_mcp.core.instalacao import (
    instrucao_de_atualizacao,
    instrucao_de_instalacao,
    raiz_e_checkout,
)
from felixo_notion_mcp.core.origem import origem_do_pacote

DISTRIBUICAO = "felixo-notion-mcp"
PORTAS_APP = (8000, 5173)


def versao_distribuicao() -> str:
    """Retorna a versão instalada, com fallback útil durante o desenvolvimento."""

    versao_nativa = ler_versao_embutida()
    if versao_nativa:
        return versao_nativa
    try:
        return importlib.metadata.version(DISTRIBUICAO)
    except importlib.metadata.PackageNotFoundError:
        return VERSAO_FONTE


def construir_parser() -> argparse.ArgumentParser:
    """Monta o parser enxuto da entrada distribuída."""

    parser = argparse.ArgumentParser(
        prog="notion-automacoes",
        description=(
            "CLI única para tarefas, perfis, app local e servidor MCP do Notion. "
            "Use 'tasks --help' para os comandos completos de operação."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {versao_distribuicao()}",
        help="mostra a versão instalada",
    )
    parser.add_argument("--json", action="store_true", help="emite JSON quando aplicável")
    parser.add_argument(
        "--perfil",
        help="alias do workspace salvo; vale para tasks, app e mcp",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    tasks = sub.add_parser(
        "tasks",
        aliases=("tarefas",),
        add_help=False,
        help="opera tarefas, páginas e databases (preserva o comando notion-tasks)",
        description="Delegação para todos os subcomandos existentes de notion-tasks.",
    )
    tasks.add_argument(
        "--help",
        action="store_true",
        dest="ajuda",
        help="mostra o guia completo de notion-tasks",
    )
    tasks.add_argument("argumentos", nargs=argparse.REMAINDER)

    auth = sub.add_parser(
        "auth",
        aliases=("perfis",),
        add_help=False,
        help="gerencia perfis persistentes de workspace",
        description="Atalho para 'notion-tasks perfis'.",
    )
    auth.add_argument(
        "--help",
        action="store_true",
        dest="ajuda",
        help="mostra a ajuda de notion-tasks perfis",
    )
    auth.add_argument("argumentos", nargs=argparse.REMAINDER)

    app = sub.add_parser("app", help="controla o app local com SPA e API")
    app_sub = app.add_subparsers(dest="acao_app", required=True)
    app_sub.add_parser("start", help="inicia API e SPA empacotada")

    mcp = sub.add_parser("mcp", help="controla o servidor MCP")
    mcp_sub = mcp.add_subparsers(dest="acao_mcp", required=True)
    mcp_start = mcp_sub.add_parser("start", help="inicia o servidor MCP")
    mcp_start.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="transporte MCP (padrão: stdio)",
    )

    sub.add_parser(
        "doctor",
        help="verifica Python, dependências, perfis, rede e componentes opcionais",
    )
    update = sub.add_parser(
        "update",
        aliases=("atualizar",),
        help="atualiza o binário nativo ou mostra como atualizar o pacote Python",
    )
    update.add_argument(
        "--dry-run",
        action="store_true",
        help="consulta a Release e mostra o plano sem baixar nem substituir",
    )
    return parser


def _aplicar_perfil(alias: str | None) -> None:
    """Aplica o perfil escolhido sem duplicar a regra existente de autenticação."""

    if not alias:
        return
    from felixo_notion_mcp.core.workspaces import aplicar_perfil

    aplicar_perfil(alias)


def _argumentos_legacy(
    args: argparse.Namespace,
    comando: Sequence[str] = (),
) -> list[str]:
    """Prepara argumentos para ``notion-tasks``, mantendo sua ordem pública."""

    prefixo: list[str] = []
    if args.json:
        prefixo.append("--json")
    if args.perfil:
        prefixo.extend(("--perfil", args.perfil))
    argumentos = [*comando, *args.argumentos]
    if getattr(args, "ajuda", False):
        argumentos.append("--help")
    if not argumentos:
        argumentos = ["--help"]
    return [*prefixo, *argumentos]


def _delegar_tasks(args: argparse.Namespace) -> int:
    """Executa o parser legado e devolve seu código de saída."""

    from felixo_notion_mcp.api.cli import notion_tasks

    return int(notion_tasks.main(_argumentos_legacy(args)))


def _delegar_auth(args: argparse.Namespace) -> int:
    """Executa o gerenciamento de perfis através da implementação existente."""

    from felixo_notion_mcp.api.cli import notion_tasks

    return int(notion_tasks.main(_argumentos_legacy(args, ("perfis",))))


def _importavel(nome: str) -> bool:
    """Testa a presença de um módulo sem importá-lo nem executar efeitos colaterais."""

    try:
        return importlib.util.find_spec(nome) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _status(nome: str, estado: str, detalhe: str, *, opcional: bool = False) -> dict[str, Any]:
    """Cria uma checagem serializável do diagnóstico."""

    return {"nome": nome, "estado": estado, "detalhe": detalhe, "opcional": opcional}


def _porta_disponivel(porta: int) -> bool:
    """Indica se não há processo aceitando conexões TCP na porta local."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", porta)) != 0


def _checar_perfis() -> dict[str, Any]:
    """Lê o store do usuário sem expor ou carregar tokens para a saída."""

    from felixo_notion_mcp.core import workspaces

    caminho = workspaces.pasta_configuracao() / workspaces.ARQUIVO_NOME
    try:
        store = workspaces.carregar_store(caminho)
    except workspaces.WorkspaceConfigError as exc:
        return {
            "check": _status("Perfis", "erro", str(exc)),
            "caminho": str(caminho),
            "quantidade": 0,
            "ativo": "",
        }
    detalhe = f"{len(store.perfis)} perfil(is)"
    if store.ativo:
        detalhe += f" · ativo: {store.ativo}"
    else:
        detalhe += " · nenhum ativo"
    return {
        "check": _status("Perfis", "ok", detalhe),
        "caminho": str(caminho),
        "quantidade": len(store.perfis),
        "ativo": store.ativo or "",
    }


def _checar_origem_do_pacote() -> dict[str, Any]:
    """Diz a versão e de onde o pacote vem (checkout editável, instalação ou binário).

    Substitui o ``check-dev.py``: se você edita o código e nada muda, é aqui que se vê
    que o Python está lendo outra cópia.
    """

    origem = origem_do_pacote()
    if origem is None:
        return _status(
            DISTRIBUICAO,
            "erro",
            "pacote não encontrado; reinstale a distribuição",
        )
    return _status(DISTRIBUICAO, "ok", f"{versao_distribuicao()} · {origem.descricao()}")


def diagnosticar() -> dict[str, Any]:
    """Executa diagnóstico seguro, sem exigir token e sem chamar a API do Notion."""

    checks: list[dict[str, Any]] = []
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = sys.version_info >= PYTHON_MINIMO
    minimo = ".".join(map(str, PYTHON_MINIMO))
    checks.append(
        _status(
            "Python",
            "ok" if python_ok else "erro",
            f"{py}{'' if python_ok else f' · requer {minimo}+'}",
        )
    )

    checks.append(_checar_origem_do_pacote())

    perfis = _checar_perfis()
    checks.append(perfis["check"])
    token = bool(os.environ.get("NOTION_TOKEN", "").strip())
    checks.append(
        _status(
            "Credencial",
            "ok" if token or perfis["quantidade"] else "aviso",
            "token disponível no ambiente"
            if token
            else "nenhum token carregado (pode configurar depois)",
        )
    )

    try:
        with socket.create_connection(("api.notion.com", 443), timeout=2):
            rede_estado, rede_detalhe = "ok", "api.notion.com:443 acessível"
    except OSError as exc:
        rede_estado, rede_detalhe = "aviso", f"API não acessível agora ({type(exc).__name__})"
    checks.append(_status("Rede do Notion", rede_estado, rede_detalhe))

    app_ok = _importavel("felixo_notion_mcp.api.launcher") and _importavel(
        "felixo_notion_mcp.api.mcp.server"
    )
    checks.append(
        _status(
            "App local",
            "ok" if app_ok else "aviso",
            "launcher e servidor MCP importáveis"
            if app_ok
            else "extra app ausente; no checkout: uv sync --all-extras",
            opcional=True,
        )
    )
    django_ok = _importavel("django")
    mcp_ok = _importavel("mcp")
    checks.append(
        _status(
            "Django",
            "ok" if django_ok else "aviso",
            "instalado" if django_ok else "extra app não instalado",
            opcional=True,
        )
    )
    checks.append(
        _status(
            "SDK MCP",
            "ok" if mcp_ok else "aviso",
            "instalado" if mcp_ok else "extra app não instalado",
            opcional=True,
        )
    )

    for porta in PORTAS_APP:
        livre = _porta_disponivel(porta)
        checks.append(
            _status(
                f"Porta {porta}",
                "ok" if livre else "aviso",
                "livre" if livre else "ocupada por outro processo",
                opcional=True,
            )
        )

    return {
        "ok": not any(item["estado"] == "erro" for item in checks),
        "versao": versao_distribuicao(),
        "checks": checks,
        "perfis": {key: value for key, value in perfis.items() if key != "check"},
    }


def _gerenciador_atualizacao() -> tuple[str, str]:
    """Resolve o gerenciador provável do ambiente e o motivo; só descreve, não monta comando.

    O rótulo é informativo. Nenhum ramo monta ``pip``/``pipx``/``uv`` com o nome da
    distribuição: ``felixo-notion-mcp`` ainda não é do projeto no PyPI, e um comando que o
    instalasse ou atualizasse por nome daria a quem registrasse o nome a execução de código
    em quem o seguisse. Quando a distribuição for publicada (etapa 4), é aqui que o comando
    por gerenciador volta.
    """

    caminho_python = str(Path(sys.executable).resolve()).lower()
    prefixo = str(Path(sys.prefix).resolve()).lower()
    if os.environ.get("VIRTUAL_ENV") or sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return "venv", "ambiente virtual ativo"
    if "pipx" in caminho_python or "pipx" in prefixo:
        return "pipx", "instalação gerenciada pelo pipx"
    if "uv" in caminho_python or "uv" in prefixo:
        return "uv", "instalação gerenciada pelo uv"
    if shutil.which("pipx"):
        return "pipx", "pipx disponível no PATH"
    if shutil.which("uv"):
        return "uv", "uv disponível no PATH"
    return "pip", "fallback do Python atual"


def preparar_atualizacao() -> dict[str, Any]:
    """Informa como atualizar sem executar instalação ou alterar o ambiente.

    Enquanto a distribuição não está no PyPI, não há comando de atualização por nome: o
    ``comando`` é ``None`` e a ``instrucao`` traz a receita do checkout (atualizar o
    repositório e sincronizar o ambiente) ou, fora dele, como instalar a partir do
    código-fonte. ``executado`` é sempre ``False``.
    """

    gerenciador, motivo = _gerenciador_atualizacao()
    return {
        "distribuicao": DISTRIBUICAO,
        "versao_atual": versao_distribuicao(),
        "gerenciador": gerenciador,
        "comando": None,
        "instrucao": instrucao_de_atualizacao(em_checkout=raiz_e_checkout(config.REPO_RAIZ)),
        "motivo": motivo,
        "executado": False,
    }


def _eh_binario_nativo() -> bool:
    """Indica se a entrada está rodando dentro de um executável PyInstaller."""

    return bool(getattr(sys, "frozen", False))


def _deve_verificar_automaticamente(
    args: argparse.Namespace,
    argumentos: Sequence[str],
) -> bool:
    """Evita rede em ajuda, doctor, update e quando o usuário opta por não atualizar."""

    if not _eh_binario_nativo():
        return False
    if args.comando in {"doctor", "update", "atualizar"}:
        return False
    if any(item in {"--help", "-h"} for item in argumentos):
        return False
    return not any(
        os.environ.get(nome, "").strip().lower() in {"1", "true", "sim", "yes"}
        for nome in (
            "NOTION_AUTOMACOES_NO_UPDATE",
            "NOTION_AUTOMACOES_SEM_AUTO_UPDATE",
        )
    )


def _verificar_auto_update(
    args: argparse.Namespace,
    argumentos: Sequence[str],
) -> dict[str, Any] | None:
    """Consulta/aplica uma Release sem poluir a saída do comando principal."""

    if not _deve_verificar_automaticamente(args, argumentos):
        return None
    return atualizacao_nativa.atualizar_automaticamente(
        versao_distribuicao(),
        executavel=sys.executable,
        argumentos=argumentos,
    )


def _iniciar_app(args: argparse.Namespace) -> int:
    """Inicia o launcher empacotado, que detecta a SPA sem Node/npm."""

    _aplicar_perfil(args.perfil)
    try:
        modulo = importlib.import_module("felixo_notion_mcp.api.launcher")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"O app local não está instalado (extra app). {instrucao_de_instalacao('app')}"
        ) from exc
    resultado = modulo.main(["--action", "tudo"])
    return int(resultado) if isinstance(resultado, int) else 0


def _iniciar_mcp(args: argparse.Namespace) -> int:
    """Inicia o servidor MCP empacotado sem passar pelo menu interativo."""

    _aplicar_perfil(args.perfil)
    if not _importavel("felixo_notion_mcp.api.mcp.server"):
        raise RuntimeError(
            f"O servidor MCP não está instalado (extra app). {instrucao_de_instalacao('app')}"
        )
    # Processo separado, como sempre foi: o servidor MCP é dono do stdin/stdout (transporte
    # stdio) e herda o ambiente com o perfil já aplicado. Isolar dois pacotes ``core``
    # homônimos (CLI e app) era outro motivo, que o pacote único tornou obsoleto.
    return int(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "felixo_notion_mcp.api.mcp.server",
                "--transport",
                args.transport,
            ]
        )
    )


def _imprimir(dados: Any, *, json_saida: bool) -> None:
    """Imprime um resultado humano ou JSON determinístico."""

    if json_saida:
        print(json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(dados, dict) and "checks" in dados:
        print(f"notion-automacoes {dados['versao']}")
        for item in dados["checks"]:
            simbolo = {"ok": "✓", "aviso": "⚠", "erro": "✗"}.get(item["estado"], "•")
            print(f"{simbolo} {item['nome']}: {item['detalhe']}")
        return
    if isinstance(dados, dict) and "comando" in dados:
        print(f"Versão atual: {dados['versao_atual']}")
        print(f"Atualização ({dados['motivo']}):")
        print(dados["instrucao"])
        print("Nenhum comando foi executado.")
        return
    if dados is not None:
        print(json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada público da distribuição única."""

    argumentos = list(sys.argv[1:] if argv is None else argv)
    if argumentos and argumentos[0] == atualizacao_nativa.ARGUMENTO_APLICAR:
        try:
            return atualizacao_nativa.executar_troca_agendada(argumentos[1:])
        except Exception as exc:  # noqa: BLE001 - helper é fronteira do executável
            print(f"Falha na atualização nativa agendada: {exc}", file=sys.stderr)
            return 2

    parser = construir_parser()
    args = parser.parse_args(argumentos)
    try:
        resultado_auto = _verificar_auto_update(args, argumentos)
        if resultado_auto and resultado_auto.get("status") == "agendado":
            return 0
        if resultado_auto and resultado_auto.get("reiniciar"):
            return atualizacao_nativa.relancar_atualizado(
                resultado_auto.get("executavel") or sys.executable,
                argumentos,
            )
        if args.comando in {"tasks", "tarefas"}:
            return _delegar_tasks(args)
        if args.comando in {"auth", "perfis"}:
            return _delegar_auth(args)
        if args.comando == "doctor":
            dados = diagnosticar()
            _imprimir(dados, json_saida=args.json)
            return 0 if dados["ok"] else 1
        if args.comando in {"update", "atualizar"}:
            if _eh_binario_nativo():
                dados = atualizacao_nativa.atualizar_nativo(
                    versao_distribuicao(),
                    executavel=sys.executable,
                    argumentos=argumentos,
                    apenas_verificar=args.dry_run,
                )
                _imprimir(dados, json_saida=args.json)
                return 0 if dados.get("ok", True) else 2
            _imprimir(preparar_atualizacao(), json_saida=args.json)
            return 0
        if args.comando == "app" and args.acao_app == "start":
            return _iniciar_app(args)
        if args.comando == "mcp" and args.acao_mcp == "start":
            return _iniciar_mcp(args)
        parser.error("Comando incompleto.")
    except Exception as exc:  # noqa: BLE001 - fronteira pública com erro legível
        dados = {"ok": False, "erro": {"mensagem": str(exc)}}
        _imprimir(dados, json_saida=getattr(args, "json", False))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
