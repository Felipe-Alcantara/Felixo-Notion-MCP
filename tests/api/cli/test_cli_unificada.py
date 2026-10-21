"""Testes da entrada distribuída, sem rede, token ou instalação real."""

from __future__ import annotations

import hashlib
import io
import json
import re
import socket

import pytest

from felixo_notion_mcp.api.cli import atualizacao_nativa, unificada
from felixo_notion_mcp.core import config


def test_version_mostra_a_distribuicao_unica(capsys):
    """A entrada pública revela uma versão antes de exigir autenticação."""

    with pytest.raises(SystemExit) as exc_info:
        unificada.main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == "notion-automacoes 0.6.0.dev0"


def test_tasks_delega_sem_reescrever_os_subcomandos(monkeypatch):
    """A fachada preserva a sintaxe e a implementação madura de notion-tasks."""

    chamadas = []

    class Legacy:
        @staticmethod
        def main(argumentos):
            chamadas.append(argumentos)
            return 7

    monkeypatch.setattr(unificada, "importlib", unificada.importlib)
    monkeypatch.setattr("felixo_notion_mcp.api.cli.notion_tasks.main", Legacy.main)

    codigo = unificada.main(["--perfil", "pessoal", "--json", "tasks", "listar"])

    assert codigo == 7
    assert chamadas == [["--json", "--perfil", "pessoal", "listar"]]


def test_tasks_help_chega_ao_guia_legado(monkeypatch):
    """A forma documentada ``tasks --help`` mantém o guia completo da CLI."""

    chamadas = []
    monkeypatch.setattr(
        "felixo_notion_mcp.api.cli.notion_tasks.main",
        lambda argumentos: chamadas.append(argumentos) or 0,
    )

    assert unificada.main(["tasks", "--help"]) == 0
    assert chamadas == [["--help"]]


def test_auth_delega_para_perfis_com_flags_globais(monkeypatch):
    """O atalho auth continua usando o store persistente já existente."""

    chamadas = []
    monkeypatch.setattr(
        "felixo_notion_mcp.api.cli.notion_tasks.main",
        lambda argumentos: chamadas.append(argumentos) or 0,
    )

    assert unificada.main(["--json", "auth", "listar"]) == 0
    assert chamadas == [["--json", "perfis", "listar"]]


def test_doctor_funciona_sem_token_e_nao_exibe_credencial(monkeypatch, tmp_path, capsys):
    """Doctor deve ser útil no primeiro comando, antes de qualquer token."""

    # ``pasta_configuracao`` usa XDG no POSIX e APPDATA no Windows. Cobrir os
    # dois evita que o perfil real da máquina entre no diagnóstico durante a
    # suíte, independentemente do sistema operacional.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
    )

    codigo = unificada.main(["--json", "doctor"])
    saida = json.loads(capsys.readouterr().out)

    assert codigo == 0
    assert saida["ok"] is True
    assert saida["perfis"]["caminho"] == str(
        tmp_path / "notion-tasks" / ".notion-workspaces.json"
    )
    assert saida["perfis"]["quantidade"] == 0
    assert saida["perfis"]["ativo"] == ""
    assert any(
        item["nome"] == "Credencial" and item["estado"] == "aviso"
        for item in saida["checks"]
    )
    assert "NOTION_TOKEN" not in json.dumps(saida)


#: ``pip/pipx/uv`` instalando ou atualizando o nome ainda não publicado no PyPI. Quem registrasse o
#: nome ganharia execução de código em quem seguisse a receita.
INSTALA_PELO_NOME = re.compile(
    r"(?:pip3?|pipx|uv)\b[^\n]*\b(?:install|upgrade)\b[^\n]*felixo-notion-mcp"
)

#: Ambientes que o ``update`` distingue. ``executavel`` e ``prefixo`` simulam o caminho do Python;
#: ``no_path`` diz que ferramentas o ``shutil.which`` encontra. ``gerenciador`` é o rótulo esperado.
AMBIENTES = {
    "venv": {
        "executavel": "/home/u/projeto/.venv/bin/python3",
        "prefixo": "/home/u/projeto/.venv",
        "base_prefixo": "/usr",
        "virtual_env": "/home/u/projeto/.venv",
        "no_path": (),
        "gerenciador": "venv",
    },
    "pipx": {
        "executavel": "/home/u/.local/pipx/venvs/felixo-notion-mcp/bin/python",
        "prefixo": "/home/u/.local/pipx/venvs/felixo-notion-mcp",
        "no_path": (),
        "gerenciador": "pipx",
    },
    "uv-tool": {
        "executavel": "/home/u/.local/share/uv/tools/felixo-notion-mcp/bin/python",
        "prefixo": "/home/u/.local/share/uv/tools/felixo-notion-mcp",
        "no_path": (),
        "gerenciador": "uv",
    },
    "pipx-no-path": {
        "executavel": "/usr/bin/python3",
        "prefixo": "/usr",
        "no_path": ("pipx",),
        "gerenciador": "pipx",
    },
    "uv-no-path": {
        "executavel": "/usr/bin/python3",
        "prefixo": "/usr",
        "no_path": ("uv",),
        "gerenciador": "uv",
    },
    "pip-fallback": {
        "executavel": "/usr/bin/python3",
        "prefixo": "/usr",
        "no_path": (),
        "gerenciador": "pip",
    },
}


def _simular_ambiente(monkeypatch, *, ambiente, tmp_path, checkout):
    """Simula o Python (venv, pipx, uv...) e a raiz (checkout ou instalação), sem rede."""

    dados = AMBIENTES[ambiente]
    monkeypatch.setattr(unificada.sys, "executable", dados["executavel"])
    monkeypatch.setattr(unificada.sys, "prefix", dados["prefixo"])
    monkeypatch.setattr(unificada.sys, "base_prefix", dados.get("base_prefixo", dados["prefixo"]))
    if "virtual_env" in dados:
        monkeypatch.setenv("VIRTUAL_ENV", dados["virtual_env"])
    else:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr(
        unificada.shutil,
        "which",
        lambda nome: f"/usr/bin/{nome}" if nome in dados["no_path"] else None,
    )
    raiz = tmp_path / ("checkout" if checkout else "site-packages")
    raiz.mkdir()
    if checkout:
        (raiz / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(config, "REPO_RAIZ", raiz)
    return dados["gerenciador"]


def _proibir_execucao(monkeypatch):
    """O ``update`` só imprime: qualquer processo filho derruba o teste."""

    def executou(*args, **kwargs):
        raise AssertionError(f"update não pode executar nada: {args}")

    for nome in ("call", "run", "Popen", "check_call", "check_output"):
        monkeypatch.setattr(unificada.subprocess, nome, executou)


@pytest.mark.parametrize("subcomando", ["update", "atualizar"])
@pytest.mark.parametrize("checkout", [True, False], ids=["checkout", "fora-do-checkout"])
@pytest.mark.parametrize("ambiente", list(AMBIENTES))
def test_update_json_nunca_indica_instalar_o_nome_do_pypi(
    monkeypatch, tmp_path, capsys, ambiente, checkout, subcomando
):
    """Em qualquer ambiente, ``update --json`` não monta nem imprime pip/pipx/uv pelo nome."""

    gerenciador = _simular_ambiente(
        monkeypatch, ambiente=ambiente, tmp_path=tmp_path, checkout=checkout
    )
    _proibir_execucao(monkeypatch)

    codigo = unificada.main(["--json", subcomando])
    bruto = capsys.readouterr().out
    saida = json.loads(bruto)

    assert codigo == 0
    assert saida["executado"] is False
    assert saida["gerenciador"] == gerenciador
    assert saida["comando"] is None
    assert saida["distribuicao"] == "felixo-notion-mcp"
    assert INSTALA_PELO_NOME.search(bruto) is None
    assert "--upgrade" not in bruto
    assert isinstance(saida["instrucao"], str)


@pytest.mark.parametrize("ambiente", list(AMBIENTES))
def test_update_json_no_checkout_manda_git_pull_e_uv_sync(
    monkeypatch, tmp_path, capsys, ambiente
):
    _simular_ambiente(monkeypatch, ambiente=ambiente, tmp_path=tmp_path, checkout=True)

    assert unificada.main(["--json", "update"]) == 0
    instrucao = json.loads(capsys.readouterr().out)["instrucao"]

    assert "git pull" in instrucao
    assert "uv sync --all-extras" in instrucao
    assert 'pip install -e ".[app]"' in instrucao


@pytest.mark.parametrize("ambiente", list(AMBIENTES))
def test_update_json_fora_do_checkout_diz_que_a_distribuicao_nao_esta_publicada(
    monkeypatch, tmp_path, capsys, ambiente
):
    _simular_ambiente(monkeypatch, ambiente=ambiente, tmp_path=tmp_path, checkout=False)

    assert unificada.main(["--json", "update"]) == 0
    instrucao = json.loads(capsys.readouterr().out)["instrucao"]

    assert "ainda não está publicada no PyPI" in instrucao
    assert "checkout do código-fonte" in instrucao
    assert "uv sync --all-extras" in instrucao
    assert "git pull" not in instrucao


@pytest.mark.parametrize("checkout", [True, False], ids=["checkout", "fora-do-checkout"])
def test_update_texto_imprime_a_receita_e_nao_executa(monkeypatch, tmp_path, capsys, checkout):
    """Sem ``--json`` a saída humana mostra a receita e confirma que nada rodou."""

    _simular_ambiente(monkeypatch, ambiente="pipx", tmp_path=tmp_path, checkout=checkout)
    _proibir_execucao(monkeypatch)

    codigo = unificada.main(["update"])
    saida = capsys.readouterr().out

    assert codigo == 0
    assert "Versão atual:" in saida
    assert ("git pull" in saida) is checkout
    assert "uv sync --all-extras" in saida
    assert INSTALA_PELO_NOME.search(saida) is None
    assert "pipx upgrade" not in saida
    assert "Nenhum comando foi executado." in saida


def test_binario_verifica_update_antes_de_delegar(monkeypatch):
    """Um binário nativo verifica a Release antes de executar o comando."""

    chamadas = []
    auto_updates = []
    monkeypatch.setattr(unificada.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        unificada.atualizacao_nativa,
        "atualizar_automaticamente",
        lambda *args, **kwargs: auto_updates.append((args, kwargs))
        or {"ok": True, "status": "atualizado"},
    )
    monkeypatch.setattr(
        "felixo_notion_mcp.api.cli.notion_tasks.main",
        lambda argumentos: chamadas.append(argumentos) or 0,
    )

    assert unificada.main(["tasks", "listar"]) == 0
    assert auto_updates[0][0][0] == unificada.versao_distribuicao()
    assert auto_updates[0][1]["argumentos"] == ["tasks", "listar"]
    assert chamadas == [["listar"]]


def test_binario_sai_quando_troca_windows_foi_agendada(monkeypatch):
    """O processo pai não continua usando o executável bloqueado."""

    chamadas = []
    monkeypatch.setattr(unificada.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        unificada.atualizacao_nativa,
        "atualizar_automaticamente",
        lambda *args, **kwargs: {"ok": True, "status": "agendado"},
    )
    monkeypatch.setattr(
        "felixo_notion_mcp.api.cli.notion_tasks.main",
        lambda argumentos: chamadas.append(argumentos) or 0,
    )

    assert unificada.main(["tasks", "listar"]) == 0
    assert chamadas == []


def test_binario_relanca_comando_depois_de_troca_posix(monkeypatch):
    """Depois da troca em macOS/Linux o comando roda no executável novo."""

    chamadas = []
    relancamentos = []
    monkeypatch.setattr(unificada.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        unificada.atualizacao_nativa,
        "atualizar_automaticamente",
        lambda *args, **kwargs: {
            "ok": True,
            "status": "atualizado",
            "aplicado": True,
            "reiniciar": True,
            "executavel": "/opt/notion-automacoes",
        },
    )
    monkeypatch.setattr(
        unificada.atualizacao_nativa,
        "relancar_atualizado",
        lambda executavel, argumentos: relancamentos.append((executavel, argumentos)) or 3,
    )
    monkeypatch.setattr(
        "felixo_notion_mcp.api.cli.notion_tasks.main",
        lambda argumentos: chamadas.append(argumentos) or 0,
    )

    assert unificada.main(["tasks", "listar"]) == 3
    assert relancamentos == [("/opt/notion-automacoes", ["tasks", "listar"])]
    assert chamadas == []


def test_update_do_binario_oferece_dry_run(monkeypatch, capsys):
    """A consulta manual pode ser feita sem alterar o arquivo atual."""

    chamadas = []
    monkeypatch.setattr(unificada.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        unificada.atualizacao_nativa,
        "atualizar_nativo",
        lambda *args, **kwargs: chamadas.append((args, kwargs))
        or {"ok": True, "status": "disponivel", "aplicado": False},
    )

    assert unificada.main(["--json", "update", "--dry-run"]) == 0
    assert chamadas[0][1]["apenas_verificar"] is True
    assert json.loads(capsys.readouterr().out)["status"] == "disponivel"


class _RespostaFake(io.BytesIO):
    """Resposta mínima compatível com o context manager de ``urlopen``."""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def _resultado_real_do_update(tmp_path, *, sistema, versao_da_release="9.9.9", **opcoes):
    """Roda ``atualizar_nativo`` de verdade, com Release e rede falsas.

    O ``_imprimir`` recebe exatamente este dicionário; montá-lo à mão deixaria o teste
    descrever um formato que o código não produz.
    """

    alvo = atualizacao_nativa.obter_alvo("windows-x64" if sistema == "Windows" else "linux-x64")
    executavel = tmp_path / alvo.asset
    executavel.write_bytes(b"antigo")
    binario = b"novo"
    respostas = {
        "https://downloads.test/checksum": hashlib.sha256(binario).hexdigest().encode(),
        "https://downloads.test/binario": binario,
    }
    release = atualizacao_nativa.ReleaseNativa(
        tag=f"v{versao_da_release}",
        versao=versao_da_release,
        url=f"https://releases.test/v{versao_da_release}",
        assets={
            alvo.asset: "https://downloads.test/binario",
            alvo.checksum: "https://downloads.test/checksum",
        },
    )
    return atualizacao_nativa.atualizar_nativo(
        "0.0.1",
        executavel=executavel,
        alvo=alvo.identificador,
        release=release,
        sistema=sistema,
        opener=lambda requisicao, *, timeout: _RespostaFake(respostas[requisicao.full_url]),
        runner=lambda *_args, **_kwargs: None,
        **opcoes,
    )


@pytest.mark.parametrize(
    ("sistema", "opcoes", "versao_da_release", "esperado"),
    [
        ("Windows", {}, "9.9.9", ["Troca agendada", "9.9.9", ".previous"]),
        ("Linux", {}, "9.9.9", ["Atualizado de 0.0.1 para 9.9.9.", ".previous"]),
        ("Linux", {"apenas_verificar": True}, "9.9.9", ["9.9.9 está disponível", "--dry-run"]),
        ("Linux", {}, "0.0.1", ["já é igual ou mais nova"]),
    ],
    ids=["windows-agendado", "posix-atualizado", "dry-run", "ja-atualizado"],
)
def test_update_texto_do_binario_imprime_o_resultado_nativo(
    monkeypatch, tmp_path, capsys, sistema, opcoes, versao_da_release, esperado
):
    """Sem ``--json`` o resultado nativo sai em texto, inclusive a troca agendada do Windows.

    A troca agendada traz a chave ``comando`` (o helper que o Windows dispara), a mesma que
    a receita da instalação Python usa para se identificar: o ramo de texto lia
    ``versao_atual`` e levantava ``KeyError`` ao imprimir o resultado do Windows.
    """

    resultado = _resultado_real_do_update(
        tmp_path, sistema=sistema, versao_da_release=versao_da_release, **opcoes
    )
    monkeypatch.setattr(unificada.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        unificada.atualizacao_nativa, "atualizar_nativo", lambda *args, **kwargs: resultado
    )

    assert unificada.main(["update"]) == 0
    saida = capsys.readouterr().out

    assert not saida.lstrip().startswith("{"), "o texto humano não é o dump do JSON"
    for trecho in esperado:
        assert trecho in saida


def test_app_sem_extra_dá_instrução_de_instalação(monkeypatch, capsys):
    """Sem o extra opcional, app start falha com uma ação reparável."""

    real_import = unificada.importlib.import_module

    def importar(nome):
        if nome == "felixo_notion_mcp.api.launcher":
            raise ModuleNotFoundError("felixo_notion_mcp.api.launcher")
        return real_import(nome)

    monkeypatch.setattr(unificada.importlib, "import_module", importar)

    codigo = unificada.main(["app", "start"])

    assert codigo == 2
    saida = capsys.readouterr().out
    # O nome felixo-notion-mcp ainda não está publicado no PyPI: a mensagem aponta o extra e o
    # checkout, nunca um `pipx/pip install` da distribuição.
    assert "uv sync --all-extras" in saida
    assert "pip install -e" in saida
    assert ".[app]" in saida
    assert "pipx install" not in saida
    assert "felixo-notion-mcp[" not in saida


def test_mcp_isola_o_servidor_em_processo_separado(monkeypatch):
    """O pacote app não pode reutilizar o ``core`` já carregado pela CLI."""

    chamadas = []
    monkeypatch.setattr(
        unificada,
        "_importavel",
        lambda nome: nome == "felixo_notion_mcp.api.mcp.server",
    )
    monkeypatch.setattr(
        unificada.subprocess,
        "call",
        lambda comando: chamadas.append(comando) or 0,
    )

    assert unificada.main(["mcp", "start", "--transport", "streamable-http"]) == 0
    assert chamadas == [
        [
            unificada.sys.executable,
            "-m",
            "felixo_notion_mcp.api.mcp.server",
            "--transport",
            "streamable-http",
        ]
    ]
