"""Testes do despacho de ações do menu em terminais dedicados."""

from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from felixo_notion_mcp.api import launcher as start_app


def test_comando_acao_reabre_start_app_com_acao():
    comando = start_app._comando_acao("servidor")

    assert comando[0] == start_app._executavel_projeto()
    # Por `python -m`, nunca por caminho: o arquivo mora em `api/`, e rodá-lo como script
    # poria `api/http` e `api/mcp` na frente do `http` da stdlib e do SDK `mcp`.
    assert comando[1:3] == ["-m", "felixo_notion_mcp.api.launcher"]
    assert comando[3:] == ["--action", "servidor"]


def test_reexecuta_no_python_do_projeto_quando_venv_difere(monkeypatch):
    chamadas = []
    monkeypatch.setattr(start_app, "_executavel_projeto", lambda: "/tmp/projeto/.venv/bin/python")
    monkeypatch.setattr(start_app, "_interpretador_importa_o_pacote", lambda executavel: True)
    monkeypatch.setattr(start_app.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(
        start_app.os,
        "execv",
        lambda executavel, argv: chamadas.append((executavel, argv)),
    )

    start_app._reexecutar_no_python_do_projeto(["--action", "tudo"])

    # A produção normaliza o caminho via Path.absolute(), então o esperado
    # usa a mesma normalização para valer em POSIX e Windows.
    destino = str(start_app.Path("/tmp/projeto/.venv/bin/python").absolute())
    assert chamadas == [
        (
            destino,
            [
                destino,
                "-m",
                "felixo_notion_mcp.api.launcher",
                "--action",
                "tudo",
            ],
        )
    ]


def test_reexecutar_no_python_do_projeto_nao_faz_nada_quando_ja_esta_no_mesmo(monkeypatch):
    monkeypatch.setattr(start_app, "_executavel_projeto", lambda: "/usr/bin/python3")
    monkeypatch.setattr(start_app.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(
        start_app.os,
        "execv",
        lambda *_args: (_ for _ in ()).throw(AssertionError("não deveria reexecutar")),
    )

    start_app._reexecutar_no_python_do_projeto(["status"])


def test_terminal_linux_prefere_terminal_configurado(monkeypatch):
    monkeypatch.setenv("TERMINAL", "terminal-personalizado --nova-janela")
    monkeypatch.setattr(
        start_app.shutil,
        "which",
        lambda nome: f"/usr/bin/{nome}" if nome == "terminal-personalizado" else None,
    )

    comando = start_app._comando_terminal_linux(["python", "app.py"], "Minha ação")

    assert comando == [
        "/usr/bin/terminal-personalizado",
        "--nova-janela",
        "-e",
        "python",
        "app.py",
    ]


def test_terminal_linux_faz_fallback_para_konsole(monkeypatch):
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(
        start_app.shutil,
        "which",
        lambda nome: "/usr/bin/konsole" if nome == "konsole" else None,
    )

    comando = start_app._comando_terminal_linux(["python", "app.py"], "Status")

    assert comando == [
        "/usr/bin/konsole",
        "--separate",
        "-p",
        "tabtitle=Status",
        "-e",
        "python",
        "app.py",
    ]


def test_abrir_terminal_linux_inicia_processo_independente(monkeypatch):
    chamadas = []
    monkeypatch.setattr(start_app.sys, "platform", "linux")
    monkeypatch.setattr(
        start_app,
        "_comando_terminal_linux",
        lambda comando, titulo: ["terminal", "--", *comando],
    )
    monkeypatch.setattr(
        start_app.subprocess,
        "Popen",
        lambda comando, **kwargs: chamadas.append((comando, kwargs)),
    )

    abriu, mensagem = start_app._abrir_terminal_dedicado("status", "Status")

    assert abriu is True
    assert "Status" in mensagem
    comando, kwargs = chamadas[0]
    assert comando[:2] == ["terminal", "--"]
    assert comando[-2:] == ["--action", "status"]
    assert kwargs["cwd"] == start_app.RAIZ
    assert kwargs["start_new_session"] is True


def test_abrir_terminal_informa_quando_nao_ha_emulador(monkeypatch):
    monkeypatch.setattr(start_app.sys, "platform", "linux")
    monkeypatch.setattr(start_app, "_comando_terminal_linux", lambda comando, titulo: None)
    monkeypatch.setattr(
        start_app.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve abrir processo")),
    )

    abriu, mensagem = start_app._abrir_terminal_dedicado("status", "Status")

    assert abriu is False
    assert "Nenhum emulador de terminal" in mensagem


def test_abrir_terminal_windows_usa_novo_console(monkeypatch):
    chamadas = []
    monkeypatch.setattr(start_app.sys, "platform", "win32")
    monkeypatch.setattr(start_app.subprocess, "CREATE_NEW_CONSOLE", 1234, raising=False)
    monkeypatch.setattr(
        start_app.subprocess,
        "Popen",
        lambda comando, **kwargs: chamadas.append((comando, kwargs)),
    )

    abriu, _ = start_app._abrir_terminal_dedicado("configurar", "Configurar")

    assert abriu is True
    _, kwargs = chamadas[0]
    assert kwargs["creationflags"] == 1234
    assert "start_new_session" not in kwargs


def test_abrir_terminal_trata_falha_do_sistema(monkeypatch):
    monkeypatch.setattr(start_app.sys, "platform", "win32")

    def falhar(*args, **kwargs):
        raise OSError("terminal indisponível")

    monkeypatch.setattr(start_app.subprocess, "Popen", falhar)

    abriu, mensagem = start_app._abrir_terminal_dedicado("status", "Status")

    assert abriu is False
    assert "terminal indisponível" in mensagem


def test_menu_oferece_iniciar_tudo_como_primeira_opcao():
    acoes = start_app._acoes_menu()

    assert next(iter(acoes)) == "tudo"
    assert acoes["tudo"][1] is start_app.acao_iniciar_tudo


def test_categorias_cobrem_todas_as_acoes_sem_orfas():
    acoes = set(start_app._acoes_menu())
    nas_categorias: set[str] = set()
    for _titulo, chaves in start_app._categorias_menu():
        for chave in chaves:
            # Toda chave de categoria existe em _acoes_menu (sem typo/órfã).
            assert chave in acoes
            nas_categorias.add(chave)
    # 'status' fica fora das subtelas (atalho direto); o resto é coberto.
    assert nas_categorias | {"status"} == acoes


def test_comandos_de_qualidade_sao_o_gate_do_projeto():
    """O item "Qualidade" roda o gate de verdade: ``ruff check .`` e ``pytest -q``.

    Antes ele apontava para ``scripts/quality_check.py``, que não existe no monólito.
    """

    python = start_app._executavel_projeto()

    assert start_app._comandos_qualidade() == [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "pytest", "-q"],
    ]


def test_o_gate_de_qualidade_existe_e_roda_no_python_do_projeto():
    """Os comandos montados existem de fato: o Python, o ruff e o pytest respondem."""

    for comando in start_app._comandos_qualidade():
        assert Path(comando[0]).exists()
        ferramenta = comando[2]
        resposta = subprocess.run(
            [comando[0], "-m", ferramenta, "--version"],
            env={**os.environ, **UTF8_NO_FILHO},
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert resposta.returncode == 0, resposta.stderr


def test_acao_qualidade_roda_o_gate_na_raiz_do_checkout(monkeypatch):
    chamadas = []

    def rodar(comando, **kwargs):
        chamadas.append((comando, kwargs))
        return subprocess.CompletedProcess(comando, 0)

    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setattr(start_app.subprocess, "run", rodar)
    console = Console(file=io.StringIO(), force_terminal=False)

    start_app.acao_qualidade(console)

    assert [comando for comando, _ in chamadas] == start_app._comandos_qualidade()
    for comando, kwargs in chamadas:
        assert kwargs["cwd"] == start_app.RAIZ
        assert kwargs["check"] is False
        # Nenhum argumento que pareça um caminho pode apontar para um arquivo inexistente.
        for parte in comando:
            if os.sep in parte:
                assert Path(parte).exists(), parte


def test_acao_qualidade_mostra_o_resultado_de_cada_etapa(monkeypatch):
    codigos = iter([1, 0])
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setattr(
        start_app.subprocess,
        "run",
        lambda comando, **kwargs: subprocess.CompletedProcess(comando, next(codigos)),
    )
    saida = io.StringIO()
    console = Console(file=saida, force_terminal=False, width=300)

    start_app.acao_qualidade(console)

    texto = saida.getvalue()
    # O ruff falhou, mas o pytest roda mesmo assim e o resumo diz que o gate não passou.
    assert "ruff" in texto and "pytest" in texto
    assert "não passou" in texto


def test_acao_qualidade_fora_do_checkout_so_avisa(monkeypatch):
    chamadas = []
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", False)
    monkeypatch.setattr(
        start_app.subprocess, "run", lambda comando, **kwargs: chamadas.append(comando)
    )
    saida = io.StringIO()
    console = Console(file=saida, force_terminal=False, width=300)

    start_app.acao_qualidade(console)

    assert chamadas == []
    assert "checkout" in saida.getvalue()


def test_instala_extra_servidor_quando_necessario(monkeypatch):
    chamadas = []
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: True)
    monkeypatch.setattr(
        start_app.subprocess,
        "call",
        lambda comando, **kwargs: chamadas.append((comando, kwargs)) or 0,
    )
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._instalar_extra_servidor(console) is True
    comando, kwargs = chamadas[0]
    assert comando[-3:] == ["install", "-e", ".[app]"]
    assert kwargs["cwd"] == start_app.RAIZ


def test_database_compativel_exige_schema_completo():
    database = {
        "properties": {
            "Tarefa": {"type": "title"},
            "Etapa": {"type": "status"},
            "Prazo": {"type": "date"},
        }
    }

    assert start_app._database_compativel(database) is True
    del database["properties"]["Prazo"]
    assert start_app._database_compativel(database) is False


def test_garantir_database_sempre_pergunta_ao_subir(monkeypatch, tmp_path):
    # Mesmo com um database já salvo, "Iniciar tudo" pergunta (com o atual
    # pré-selecionado) — ele NÃO reusa em silêncio.
    import questionary

    capturado = {}

    class Pergunta:
        def ask(self):
            return "db-trocado"

    def fake_select(mensagem, choices, *args, **kwargs):
        capturado["default"] = kwargs.get("default")
        return Pergunta()

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\nNOTION_DATABASE_ID=db-atual\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "db-atual")
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Atual", "db-atual", True, []), ("Outro", "db-trocado", True, [])],
    )
    monkeypatch.setattr(questionary, "select", fake_select)
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._garantir_database_tarefas(console) is True
    # O atual entra pré-selecionado e a troca é gravada.
    assert capturado["default"] == "db-atual"
    assert start_app.os.environ[start_app.DATABASE_ENV] == "db-trocado"


def test_garantir_database_cancelar_mantem_o_atual_e_sobe(monkeypatch, tmp_path):
    # Ao subir, cancelar a escolha mantém o database já salvo e segue (True).
    import questionary

    class Pergunta:
        def ask(self):
            return None  # usuário escolheu "Manter o atual"

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\nNOTION_DATABASE_ID=db-atual\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "db-atual")
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Atual", "db-atual", True, []), ("Outro", "db-outro", True, [])],
    )
    monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: Pergunta())
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._garantir_database_tarefas(console) is True
    assert start_app.os.environ[start_app.DATABASE_ENV] == "db-atual"


def test_garantir_database_pergunta_e_salva_na_primeira_vez(monkeypatch, tmp_path):
    # Sem database salvo, "Iniciar tudo" pergunta (mesmo com um único
    # compatível) e grava a escolha no .env.
    import questionary

    class Pergunta:
        def ask(self):
            return "database-selecionado"

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    # setenv (em vez de delenv) faz o monkeypatch "adotar" a chave: a escrita
    # que a produção faz em os.environ é revertida no teardown, sem vazar para
    # outros testes (ex.: test_api_tarefas, que lê NOTION_DATABASE_ID).
    monkeypatch.setenv(start_app.DATABASE_ENV, "")
    monkeypatch.delenv(start_app.DATABASE_ENV, raising=False)
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Tarefas", "database-selecionado", True, [])],
    )
    monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: Pergunta())
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._garantir_database_tarefas(console) is True
    assert "NOTION_DATABASE_ID=database-selecionado" in env_file.read_text()
    assert start_app.os.environ[start_app.DATABASE_ENV] == "database-selecionado"


def test_garantir_database_pede_escolha_quando_ha_mais_de_um(monkeypatch, tmp_path):
    import questionary

    class Pergunta:
        def ask(self):
            return "db-2"

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    # setenv adota a chave para que a escrita da produção em os.environ seja
    # revertida no teardown (ver test_garantir_database_unico_salva_no_env).
    monkeypatch.setenv(start_app.DATABASE_ENV, "")
    monkeypatch.delenv(start_app.DATABASE_ENV, raising=False)
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Tarefas", "db-1", True, []), ("Tarefas (1)", "db-2", True, [])],
    )
    monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: Pergunta())
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._garantir_database_tarefas(console) is True
    assert start_app.os.environ[start_app.DATABASE_ENV] == "db-2"


def test_garantir_database_falha_sem_nenhum_compartilhado(monkeypatch, tmp_path):
    # Nenhum database compartilhado com a integração → não há o que escolher.
    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.delenv(start_app.DATABASE_ENV, raising=False)
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(start_app, "_buscar_databases", lambda token: [])
    saida = io.StringIO()
    console = Console(file=saida, force_terminal=False)

    assert start_app._garantir_database_tarefas(console) is False
    assert "Nenhum database compartilhado" in saida.getvalue()


def test_selecionar_database_pergunta_para_trocar_o_atual(monkeypatch, tmp_path):
    # Mesmo com um único database compatível, se já houver um selecionado a
    # opção "Configurar → Escolher database" deve perguntar (para poder trocar),
    # não reusar em silêncio. Marca o atual na lista de escolhas.
    import questionary

    capturado = {}

    class Pergunta:
        def ask(self):
            return "db-novo"

    def fake_select(mensagem, choices, *args, **kwargs):
        capturado["choices"] = choices
        return Pergunta()

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\nNOTION_DATABASE_ID=db-antigo\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "db-antigo")
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [
            ("Tarefas (atual)", "db-antigo", True, []),
            ("Tarefas nova", "db-novo", True, []),
        ],
    )
    monkeypatch.setattr(questionary, "select", fake_select)
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._selecionar_database_tarefas(console) is True
    assert start_app.os.environ[start_app.DATABASE_ENV] == "db-novo"
    assert "NOTION_DATABASE_ID=db-novo" in env_file.read_text()
    # O database atualmente em uso aparece marcado para o usuário se orientar.
    assert any("[atual]" in str(c.title) for c in capturado["choices"])


def test_selecionar_database_cancelado_mostra_titulo_real_do_atual(monkeypatch, tmp_path):
    import questionary

    class Pergunta:
        def ask(self):
            return None

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\nNOTION_DATABASE_ID=db-atual\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "db-atual")
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Tasks", "db-atual", True, [], ["Tasks"])],
    )
    monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: Pergunta())
    saida = io.StringIO()
    console = Console(file=saida, force_terminal=False)

    assert start_app._selecionar_database_tarefas(console, manter_atual_ao_cancelar=True) is True
    assert "Tasks (db-atual" in saida.getvalue()
    assert "Data source: Tasks" in saida.getvalue()
    assert "URL: https://app.notion.com/p/dbatual" in saida.getvalue()
    assert "Ex.:" not in saida.getvalue()


def test_selecionar_database_lista_todos_com_marca(monkeypatch, tmp_path):
    # Todos os databases aparecem (compatível ✓ e incompatível ⚠), não só os
    # que batem o schema.
    import questionary

    capturado = {}

    class Pergunta:
        def ask(self):
            return "db-ok"

    def fake_select(mensagem, choices, *args, **kwargs):
        capturado["titulos"] = [str(c.title) for c in choices]
        return Pergunta()

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "")
    monkeypatch.delenv(start_app.DATABASE_ENV, raising=False)
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [
            ("Tarefas", "db-ok", True, []),
            ("Budget", "db-x", False, ["Tarefa (espera title, tem ausente)"]),
        ],
    )
    monkeypatch.setattr(questionary, "select", fake_select)
    console = Console(file=io.StringIO(), force_terminal=False)

    assert start_app._selecionar_database_tarefas(console) is True
    assert any("✓" in t and "Tarefas" in t for t in capturado["titulos"])
    assert any("⚠" in t and "Budget" in t for t in capturado["titulos"])


def test_selecionar_database_incompativel_pede_confirmacao(monkeypatch, tmp_path):
    # Escolher um database sem o schema avisa as colunas que faltam e só grava
    # se a pessoa confirmar.
    import questionary

    class Selecao:
        def ask(self):
            return "db-incompat"

    class Confirma:
        def __init__(self, resposta):
            self.resposta = resposta

        def ask(self):
            return self.resposta

    env_file = tmp_path / ".env"
    env_file.write_text("NOTION_TOKEN=ntn_teste\n", encoding="utf-8")
    monkeypatch.setattr(start_app, "ENV_FILE", env_file)
    monkeypatch.setenv(start_app.DATABASE_ENV, "")
    monkeypatch.delenv(start_app.DATABASE_ENV, raising=False)
    monkeypatch.delenv(start_app.TOKEN_ENV, raising=False)
    monkeypatch.setattr(
        start_app,
        "_buscar_databases",
        lambda token: [("Budget", "db-incompat", False, ["Etapa (espera status, tem ausente)"])],
    )
    monkeypatch.setattr(questionary, "select", lambda *a, **k: Selecao())

    # 1) confirma=False → não grava
    monkeypatch.setattr(questionary, "confirm", lambda *a, **k: Confirma(False))
    saida = io.StringIO()
    console = Console(file=saida, force_terminal=False)
    assert start_app._selecionar_database_tarefas(console) is False
    assert "Etapa (espera status" in saida.getvalue()
    assert "NOTION_DATABASE_ID=db-incompat" not in env_file.read_text()

    # 2) confirma=True → grava mesmo incompatível
    monkeypatch.setattr(questionary, "confirm", lambda *a, **k: Confirma(True))
    console = Console(file=io.StringIO(), force_terminal=False)
    assert start_app._selecionar_database_tarefas(console) is True
    assert "NOTION_DATABASE_ID=db-incompat" in env_file.read_text()


def test_app_web_ativo_valida_health_do_projeto(monkeypatch):
    class Resposta:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"status": "ok", "service": "automacoes-notion"}'

    monkeypatch.setattr(start_app.urllib.request, "urlopen", lambda *args, **kwargs: Resposta())

    assert start_app._app_web_ativo() is True


def test_front_web_ativo_valida_html_do_vite(monkeypatch):
    class Resposta:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'<div id="root"></div><script type="module" src="/src/main.jsx"></script>'

    monkeypatch.setattr(start_app.urllib.request, "urlopen", lambda *args, **kwargs: Resposta())

    assert start_app._front_web_ativo() is True


def test_node_compativel_reflete_requisito_do_vite():
    assert start_app._node_compativel((20, 18, 1)) is False
    assert start_app._node_compativel((20, 19, 0)) is True
    assert start_app._node_compativel((22, 11, 0)) is False
    assert start_app._node_compativel((22, 12, 0)) is True
    assert start_app._node_compativel((25, 9, 0)) is True


def test_comando_front_usa_host_e_porta_padrao():
    runtime = start_app.FrontRuntime(
        node=start_app.Path("/usr/bin/node"),
        npm=start_app.Path("/usr/bin/npm"),
        versao="v22.12.0",
    )

    comando = start_app._comando_front(runtime)

    # str(Path) usa o separador da plataforma; compara com a mesma conversão.
    assert comando == [
        str(runtime.npm),
        "run",
        "dev",
        "--",
        "--host",
        start_app.FRONT_HOST,
        "--port",
        start_app.FRONT_PORT,
    ]


def test_abre_navegador_assim_que_health_responde(monkeypatch):
    estados = iter((False, True))
    aberturas = []
    monkeypatch.setattr(start_app, "_app_web_ativo", lambda: next(estados))
    monkeypatch.setattr(start_app, "_front_web_ativo", lambda: True)
    monkeypatch.setattr(start_app.time, "sleep", lambda intervalo: None)
    monkeypatch.setattr(
        start_app.webbrowser,
        "open",
        lambda url: aberturas.append(url) or True,
    )
    console = Console(file=io.StringIO(), force_terminal=False)

    start_app._abrir_navegador_quando_pronto(console, tentativas=2, intervalo=0)

    assert aberturas == [start_app.APP_URL]


def test_iniciar_tudo_usa_defaults_e_sobe_front_api(monkeypatch):
    chamadas = []
    agendamentos = []
    aguardados = []
    runtime = start_app.FrontRuntime(
        node=start_app.Path("/usr/bin/node"),
        npm=start_app.Path("/usr/bin/npm"),
        versao="v22.12.0",
    )

    class Processo:
        def poll(self):
            return None

    monkeypatch.setattr(start_app, "_django_disponivel", lambda: True)
    monkeypatch.setattr(start_app, "_token_configurado", lambda: (True, ".env local"))
    monkeypatch.setattr(start_app, "_garantir_database_tarefas", lambda console: True)
    monkeypatch.setattr(start_app, "_app_web_ativo", lambda: False)
    monkeypatch.setattr(start_app, "_front_web_ativo", lambda: False)
    monkeypatch.setattr(start_app, "_garantir_front_pronto", lambda console: runtime)
    monkeypatch.setattr(start_app, "_ambiente_servidor", lambda: {"DJANGO_DEBUG": "1"})
    monkeypatch.setattr(start_app, "_aplicar_migracoes", lambda console, ambiente: True)
    monkeypatch.setattr(
        start_app,
        "_agendar_abertura_navegador",
        lambda console: agendamentos.append(True),
    )
    monkeypatch.setattr(
        start_app,
        "_aguardar_processos",
        lambda console, processos: aguardados.extend(processos),
    )
    monkeypatch.setattr(
        start_app.subprocess,
        "Popen",
        lambda comando, **kwargs: chamadas.append((comando, kwargs)) or Processo(),
    )
    console = Console(file=io.StringIO(), force_terminal=False)

    start_app.acao_iniciar_tudo(console)

    assert agendamentos == [True]
    assert len(chamadas) == 2
    comando_api, kwargs_api = chamadas[0]
    comando_front, kwargs_front = chamadas[1]
    assert comando_api[-2:] == ["runserver", start_app.API_ENDERECO_PADRAO]
    assert kwargs_api["cwd"] == start_app.SERVIDOR
    assert kwargs_api["env"] == {"DJANGO_DEBUG": "1"}
    assert comando_front == start_app._comando_front(runtime)
    assert kwargs_front["cwd"] == start_app.FRONT
    assert len(aguardados) == 2


def test_iniciar_tudo_reabre_app_que_ja_esta_rodando(monkeypatch):
    aberturas = []
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: True)
    monkeypatch.setattr(start_app, "_token_configurado", lambda: (True, ".env local"))
    monkeypatch.setattr(start_app, "_garantir_database_tarefas", lambda console: True)
    monkeypatch.setattr(start_app, "_app_web_ativo", lambda: True)
    monkeypatch.setattr(start_app, "_front_web_ativo", lambda: True)
    monkeypatch.setattr(
        start_app,
        "_garantir_front_pronto",
        lambda console: start_app.FrontRuntime(
            node=start_app.Path("/usr/bin/node"),
            npm=start_app.Path("/usr/bin/npm"),
            versao="v22.12.0",
        ),
    )
    monkeypatch.setattr(
        start_app.webbrowser,
        "open",
        lambda url: aberturas.append(url) or True,
    )
    monkeypatch.setattr(
        start_app.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("não deve iniciar outro processo")
        ),
    )
    console = Console(file=io.StringIO(), force_terminal=False)

    start_app.acao_iniciar_tudo(console)

    assert aberturas == [start_app.APP_URL]


def test_main_rejeita_acao_desconhecida():
    try:
        start_app.main(["--action", "inexistente"])
    except SystemExit as exc:
        assert "Ação desconhecida" in str(exc)
    else:
        raise AssertionError("main deveria rejeitar uma ação inexistente")


# --------------------------------------------------------------------------- #
# Raiz, modo checkout e processos filhos (o launcher mora dentro do pacote)   #
# --------------------------------------------------------------------------- #
RAIZ_DO_CHECKOUT = Path(__file__).resolve().parents[2]


# O filho escreve UTF-8 e o pai decodifica UTF-8; sem isto, no Windows o pai usaria a
# codepage da localidade (cp1252) e a saída com acento derrubaria o teste.
UTF8_NO_FILHO = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def _ambiente_com_src() -> dict[str, str]:
    """Ambiente de um filho que só enxerga o pacote pelo `src/` (sem `pip install`)."""
    ambiente = {**os.environ, **UTF8_NO_FILHO}
    ambiente["PYTHONPATH"] = str(RAIZ_DO_CHECKOUT / "src")
    ambiente["DJANGO_DEBUG"] = "1"
    return ambiente


def test_raiz_do_launcher_e_a_unica_de_core_config():
    from felixo_notion_mcp.core import config

    assert start_app.RAIZ == config.REPO_RAIZ == RAIZ_DO_CHECKOUT
    assert start_app.ENV_FILE == config.ENV_FILE
    assert start_app.MODO_CHECKOUT is True


def test_caminhos_do_app_apontam_para_o_que_existe():
    assert start_app.MANAGE_PY.is_file()
    assert start_app.MCP_SERVER_PY.is_file()
    assert start_app.FRONT_BUNDLE_INDEX.parent == start_app.SERVIDOR / "static" / "frontend"
    assert (start_app.SERVIDOR / "templates" / "tarefas.html").is_file()
    assert (start_app.FRONT / "package.json").is_file()


def test_so_ha_checkout_com_pyproject_na_raiz(tmp_path):
    assert start_app._raiz_e_checkout(tmp_path) is False
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert start_app._raiz_e_checkout(tmp_path) is True


def test_fora_do_checkout_nao_reusa_venv_nem_pip_editavel(monkeypatch, tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(start_app, "RAIZ", tmp_path)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", False)

    assert start_app._executavel_projeto() == start_app.sys.executable
    # Fora do checkout não há o que instalar por aqui: nenhum comando, nunca a distribuição
    # por nome (o nome ainda não é do projeto no PyPI).
    assert start_app._comando_pip_projeto("app") is None


def test_no_checkout_reusa_o_venv_do_projeto_e_instala_editavel(monkeypatch, tmp_path):
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(start_app, "RAIZ", tmp_path)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)

    assert start_app._executavel_projeto() == str(venv / "python")
    assert start_app._comando_pip_projeto("app,dev")[-2:] == ["-e", ".[app,dev]"]


def test_no_checkout_o_comando_de_pip_e_a_instalacao_editavel_da_raiz(monkeypatch):
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)

    assert start_app._comando_pip_projeto("app") == [
        start_app.sys.executable,
        "-m",
        "pip",
        "install",
        "-e",
        ".[app]",
    ]


# --------------------------------------------------------------------------- #
# Cadeia de suprimentos: nada instala `felixo-notion-mcp` do PyPI por nome     #
# --------------------------------------------------------------------------- #
class _Resposta:
    """Dublê do que ``questionary.confirm(...)`` devolve: só o ``ask``."""

    def __init__(self, valor):
        self.valor = valor

    def ask(self):
        return self.valor


def _espiar_subprocessos(monkeypatch) -> list[list[str]]:
    """Registra todo comando que o launcher tentaria rodar, sem rodar nenhum."""

    comandos: list[list[str]] = []

    def registrar(comando, *args, **kwargs):
        comandos.append([comando] if isinstance(comando, str) else [str(p) for p in comando])
        return 0

    monkeypatch.setattr(start_app.subprocess, "call", registrar)
    monkeypatch.setattr(start_app.subprocess, "run", registrar)
    monkeypatch.setattr(start_app.subprocess, "Popen", registrar)
    return comandos


def _console_largo() -> tuple[Console, io.StringIO]:
    saida = io.StringIO()
    return Console(file=saida, force_terminal=False, width=400), saida


@pytest.mark.parametrize("acao", ["instalar", "iniciar_tudo", "servidor", "mcp"])
def test_fora_do_checkout_nenhuma_acao_instala_o_pacote_por_nome(monkeypatch, tmp_path, acao):
    """O nome ``felixo-notion-mcp`` não pertence ao projeto no PyPI até a etapa 4.

    Quem o registrasse ganharia execução de código em quem instalou a partir do código-fonte.
    Mesmo respondendo "sim" a toda pergunta, nada pode rodar ``pip install felixo-notion-mcp``;
    a pessoa recebe o caminho do checkout.
    """

    import questionary

    comandos = _espiar_subprocessos(monkeypatch)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", False)
    monkeypatch.setattr(start_app, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(start_app, "_front_empacotado", lambda: False)
    monkeypatch.setattr(start_app, "_resolver_runtime_front", lambda: None)
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: False)
    monkeypatch.setattr(start_app, "_mcp_disponivel", lambda: False)
    monkeypatch.setattr(questionary, "confirm", lambda *a, **k: _Resposta(True))
    monkeypatch.setattr(questionary, "text", lambda *a, **k: _Resposta(None))
    console, saida = _console_largo()

    getattr(start_app, f"acao_{acao}")(console)

    por_nome = [c for c in comandos if any("felixo-notion-mcp" in parte for parte in c)]
    assert por_nome == []
    assert not [c for c in comandos if "pip" in c and "install" in c]
    texto = saida.getvalue()
    assert "uv sync --all-extras" in texto
    assert 'pip install -e ".[' in texto
    assert "PyPI" in texto


def test_instalar_extra_servidor_fora_do_checkout_so_orienta(monkeypatch):
    comandos = _espiar_subprocessos(monkeypatch)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", False)
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: False)
    console, saida = _console_largo()

    assert start_app._instalar_extra_servidor(console) is False

    assert comandos == []
    assert "uv sync --all-extras" in saida.getvalue()


def test_iniciar_tudo_pergunta_antes_de_instalar_o_extra_app(monkeypatch):
    """Antes, ``acao_iniciar_tudo`` rodava o pip sem perguntar nada."""

    import questionary

    comandos = _espiar_subprocessos(monkeypatch)
    perguntas: list[str] = []
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: False)
    monkeypatch.setattr(
        questionary,
        "confirm",
        lambda mensagem, *a, **k: perguntas.append(mensagem) or _Resposta(False),
    )
    console, _ = _console_largo()

    start_app.acao_iniciar_tudo(console)

    assert len(perguntas) == 1
    assert comandos == []


def test_iniciar_tudo_instala_o_extra_editavel_so_depois_do_sim(monkeypatch):
    import questionary

    eventos: list[str] = []
    instalado = {"django": False}

    def registrar(comando, *args, **kwargs):
        eventos.append("pip:" + " ".join(str(p) for p in comando[-3:]))
        instalado["django"] = True
        return 0

    monkeypatch.setattr(start_app.subprocess, "call", registrar)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setattr(start_app, "_django_disponivel", lambda: instalado["django"])
    monkeypatch.setattr(start_app, "_token_configurado", lambda: (True, ".env local"))
    monkeypatch.setattr(start_app, "_garantir_database_tarefas", lambda console: False)
    monkeypatch.setattr(
        questionary,
        "confirm",
        lambda mensagem, *a, **k: eventos.append("pergunta") or _Resposta(True),
    )
    console, _ = _console_largo()

    start_app.acao_iniciar_tudo(console)

    assert eventos == ["pergunta", "pip:install -e .[app]"]


NOME_DA_DISTRIBUICAO = "felixo-notion-mcp"
#: O que, numa lista de argumentos, manda um gerenciador instalar ou atualizar.
VERBOS_DE_INSTALACAO = {"install", "upgrade", "--upgrade", "-U"}
#: O nome da distribuição como argumento (com extras ou versão: ``nome[app]``, ``nome==1``).
ARGUMENTO_COM_O_NOME = re.compile(r"felixo-notion-mcp(\[[^\]]*\])?([<>=!~@].*)?$")
#: Um texto que manda instalar ou atualizar o nome (``pip install nome``, ``pipx upgrade nome``).
TEXTO_QUE_INSTALA_O_NOME = re.compile(r"\b(?:install|upgrade)\b[^\n]*felixo-notion-mcp")


def _texto_estatico(no: ast.AST) -> str | None:
    """Texto de uma string ou f-string; a constante ``DISTRIBUICAO`` vale pelo nome."""

    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.Name) and no.id == "DISTRIBUICAO":
        return NOME_DA_DISTRIBUICAO
    if isinstance(no, ast.JoinedStr):
        partes = []
        for valor in no.values:
            alvo = valor.value if isinstance(valor, ast.FormattedValue) else valor
            partes.append(_texto_estatico(alvo) or "{}")
        return "".join(partes)
    return None


def _achados_de_instalacao_por_nome(codigo: str) -> list[tuple[int, str]]:
    """Linhas do código que mandam instalar ou atualizar ``felixo-notion-mcp`` por nome.

    Pega o que o nome literal esconde: o comando montado a partir da constante
    ``DISTRIBUICAO`` (``[sys.executable, "-m", "pip", "install", DISTRIBUICAO]``,
    ``["pipx", "upgrade", DISTRIBUICAO]``, ``["uv", "tool", "upgrade", DISTRIBUICAO]``) e a
    mensagem escrita por extenso, em string, f-string ou lista de argumentos.
    """

    achados: list[tuple[int, str]] = []
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, (ast.List, ast.Tuple)):
            argumentos = [_texto_estatico(item) for item in no.elts]
            if VERBOS_DE_INSTALACAO.intersection(argumentos) and any(
                item and ARGUMENTO_COM_O_NOME.match(item) for item in argumentos
            ):
                achados.append((no.lineno, "lista de argumentos que instala o nome"))
        elif isinstance(no, (ast.Constant, ast.JoinedStr)):
            texto = _texto_estatico(no)
            if texto and TEXTO_QUE_INSTALA_O_NOME.search(texto):
                achados.append((no.lineno, texto.strip().splitlines()[0]))
    return achados


def test_a_varredura_pega_o_comando_montado_pela_constante_e_o_texto_escrito_por_extenso():
    """Prova a própria guarda: o que ela deve achar e o que não deve."""

    ruins = [
        'DISTRIBUICAO = "felixo-notion-mcp"\nx = ["pipx", "upgrade", DISTRIBUICAO]',
        'x = ["uv", "tool", "upgrade", "felixo-notion-mcp"]',
        'x = [sys.executable, "-m", "pip", "install", "--upgrade", DISTRIBUICAO]',
        'x = (sys.executable, "-m", "pip", "install", "felixo-notion-mcp[app]")',
        'x = ["pip", "install", "felixo-notion-mcp==0.6.0"]',
        'x = "pipx upgrade felixo-notion-mcp"',
        'x = f"python -m pip install --upgrade {DISTRIBUICAO}"',
        'x = f"pip install {DISTRIBUICAO}[app]"',
    ]
    for codigo in ruins:
        assert _achados_de_instalacao_por_nome(codigo), codigo

    bons = [
        'x = ["git", "pull"]',
        'x = [sys.executable, "-m", "pip", "install", "-e", ".[app]"]',
        'x = importlib.metadata.version(DISTRIBUICAO)',
        'x = ["uv", "sync", "--all-extras"]',
        'x = f"pip install -e .[{extras}]"',
        'x = "A distribuição ainda não está publicada no PyPI."',
    ]
    for codigo in bons:
        assert _achados_de_instalacao_por_nome(codigo) == [], codigo


def test_nenhuma_mensagem_manda_instalar_a_distribuicao_pelo_nome():
    """Varre o código: nada instala nem atualiza ``felixo-notion-mcp`` pelo nome.

    Vale para o pacote (``src``) e para a porta de entrada (``start_app.py``), e olha
    três formas: o texto por extenso, o comando montado a partir de ``DISTRIBUICAO`` e o
    extra (``felixo-notion-mcp[app]``). A mensagem certa aponta o extra e o checkout, nunca
    um nome ainda não publicado: quem o registrasse no PyPI ganharia execução de código em
    quem seguisse a receita (``pip install``, ``pipx upgrade``, ``uv tool upgrade``).
    """

    por_linha = re.compile(r"""install\s+['"\\]*felixo-notion-mcp|felixo-notion-mcp\[""")
    achados = []
    arquivos = [*(RAIZ_DO_CHECKOUT / "src").rglob("*.py"), RAIZ_DO_CHECKOUT / "start_app.py"]
    for arquivo in arquivos:
        codigo = arquivo.read_text(encoding="utf-8")
        relativo = arquivo.relative_to(RAIZ_DO_CHECKOUT)
        for numero, linha in enumerate(codigo.splitlines(), 1):
            if por_linha.search(linha):
                achados.append(f"{relativo}:{numero}: {linha.strip()}")
        for numero, motivo in _achados_de_instalacao_por_nome(codigo):
            achados.append(f"{relativo}:{numero}: {motivo}")
    assert achados == []


def test_exporta_o_src_para_os_filhos_uma_vez_so(monkeypatch, tmp_path):
    src = tmp_path / "src"
    monkeypatch.setattr(start_app, "PASTA_DO_PACOTE", src)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setenv("PYTHONPATH", "/outro/lugar")

    start_app._exportar_pacote_para_filhos()
    start_app._exportar_pacote_para_filhos()

    assert os.environ["PYTHONPATH"] == os.pathsep.join([str(src), "/outro/lugar"])


def test_nao_exporta_o_site_packages_nem_fora_do_checkout(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(start_app, "PASTA_DO_PACOTE", tmp_path / "site-packages")
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    start_app._exportar_pacote_para_filhos()
    assert "PYTHONPATH" not in os.environ

    monkeypatch.setattr(start_app, "PASTA_DO_PACOTE", tmp_path / "src")
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", False)
    start_app._exportar_pacote_para_filhos()
    assert "PYTHONPATH" not in os.environ


def test_launcher_abre_por_python_m_sem_esconder_a_stdlib():
    """É assim que o menu se reabre; por caminho, `api/http` taparia o `http` da stdlib."""
    resultado = subprocess.run(
        [sys.executable, "-m", start_app.MODULO_LAUNCHER, "--help"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=_ambiente_com_src(),
        cwd=RAIZ_DO_CHECKOUT,
        timeout=60,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "notion-automacoes-app" in resultado.stdout


def test_cli_abre_pelo_modulo_que_o_menu_usa():
    resultado = subprocess.run(
        [sys.executable, "-m", start_app.MODULO_CLI, "--help"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=_ambiente_com_src(),
        cwd=RAIZ_DO_CHECKOUT,
        timeout=60,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "listar" in resultado.stdout


def test_servidor_mcp_abre_pelo_caminho_que_o_menu_usa():
    resultado = subprocess.run(
        [sys.executable, str(start_app.MCP_SERVER_PY), "--help"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=_ambiente_com_src(),
        cwd=start_app.SERVIDOR,
        timeout=60,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "--transport" in resultado.stdout


def test_manage_py_roda_pelo_caminho_que_o_menu_usa(tmp_path):
    pytest.importorskip("django")
    ambiente = _ambiente_com_src()
    ambiente["OPERATIONAL_DB_PATH"] = str(tmp_path / "operacional.sqlite3")
    resultado = subprocess.run(
        [sys.executable, str(start_app.MANAGE_PY), "check"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=ambiente,
        cwd=start_app.SERVIDOR,
        timeout=60,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr


# --------------------------------------------------------------------------- #
# O launcher abre sem nenhuma dependência instalada (Instalar/Setup precisa dele) #
# --------------------------------------------------------------------------- #
TERCEIROS = ("requests", "docx", "django", "mcp", "rich", "questionary", "openpyxl")


def test_launcher_e_config_abrem_sem_nenhuma_dependencia_de_terceiros():
    """Num venv recém-criado só existe a stdlib: o menu tem de abrir para oferecer o Setup."""
    codigo = (
        "import sys\n"
        f"for nome in {TERCEIROS!r}:\n"
        "    sys.modules[nome] = None\n"
        "import felixo_notion_mcp.core.config\n"
        "import felixo_notion_mcp.api.launcher as launcher\n"
        "launcher.main(['--help'])\n"
        "assert not launcher._pacote_instalado()\n"
        "print('faltando:', ','.join(launcher._dependencias_faltando()))\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=_ambiente_com_src(),
        cwd=RAIZ_DO_CHECKOUT,
        timeout=60,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "notion-automacoes-app" in resultado.stdout
    assert "faltando: python-docx,requests,mcp" in resultado.stdout


def test_pacote_instalado_e_falso_quando_falta_uma_dependencia(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", None)

    assert start_app._pacote_instalado() is False
    assert "requests" in start_app._dependencias_faltando()


def test_pacote_instalado_e_verdadeiro_com_todas_as_dependencias(monkeypatch):
    monkeypatch.setattr(start_app.importlib.util, "find_spec", lambda nome: object())

    assert start_app._pacote_instalado() is True
    assert start_app._dependencias_faltando() == []


def test_dependencias_do_launcher_sao_as_do_pyproject():
    """Se o pyproject ganhar ou perder uma dependência de runtime, o launcher acompanha."""
    import tomllib

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    pyproject = tomllib.loads((RAIZ_DO_CHECKOUT / "pyproject.toml").read_text(encoding="utf-8"))
    do_pyproject = {
        canonicalize_name(Requirement(texto).name) for texto in pyproject["project"]["dependencies"]
    }

    assert {canonicalize_name(nome) for nome in start_app._DEPENDENCIAS_DE_RUNTIME} == do_pyproject


def test_mapear_orienta_instalar_setup_quando_faltam_dependencias(monkeypatch):
    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: ["requests"])
    monkeypatch.setattr(
        start_app.subprocess,
        "call",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve rodar nada")),
    )
    saida = io.StringIO()

    start_app.acao_mapear(Console(file=saida, force_terminal=False, width=200))

    assert "Instalar / Setup" in saida.getvalue()
    assert "requests" in saida.getvalue()


def test_mapear_usa_o_servico_do_pacote_e_grava_na_pasta_atual(monkeypatch, tmp_path):
    # Antes rodava examples/*.py por subprocess: fora do checkout essa pasta não existe.
    from felixo_notion_mcp.services import mapa_workspace

    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: [])
    monkeypatch.setattr(start_app, "_token_configurado", lambda: (True, "ambiente"))
    monkeypatch.setenv("NOTION_TOKEN", "ntn_teste")
    monkeypatch.setattr(
        start_app.subprocess,
        "call",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deve rodar script")),
    )
    mapa = {
        "total_paginas": 1, "total_databases": 0, "linhas_por_database": {},
        "duplicatas": {}, "orfaos": [],
        "itens": [{"id": "p1", "tipo": "page", "titulo": "HOME", "parent_tipo": "workspace",
                   "parent_id": None, "url": None}],
    }
    monkeypatch.setattr(mapa_workspace, "coletar_mapa", lambda **kw: mapa)
    monkeypatch.chdir(tmp_path)
    saida = io.StringIO()

    start_app.acao_mapear(Console(file=saida, force_terminal=False, width=300))

    assert json.loads((tmp_path / "mapa.json").read_text(encoding="utf-8")) == mapa
    assert "HOME" in (tmp_path / "mapa.html").read_text(encoding="utf-8")
    assert str(tmp_path / "mapa.html") in saida.getvalue()


def test_rodar_avisa_quando_faltam_dependencias(monkeypatch):
    import questionary

    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: ["requests"])
    monkeypatch.setattr(start_app, "_token_configurado", lambda: (True, ".env local"))
    monkeypatch.setattr(
        questionary, "select", lambda *args, **kwargs: type("P", (), {"ask": lambda self: None})()
    )
    saida = io.StringIO()

    start_app.acao_rodar(Console(file=saida, force_terminal=False, width=200))

    assert "Instalar / Setup" in saida.getvalue()
    assert "requests" in saida.getvalue()


def test_status_mostra_o_pacote_sem_dependencias_como_nao_instalado(monkeypatch):
    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: ["requests"])
    monkeypatch.setattr(start_app, "_resolver_runtime_front", lambda: None)
    saida = io.StringIO()

    start_app.acao_status(Console(file=saida, force_terminal=False, width=200))

    assert "não instalado" in saida.getvalue()
    assert "Instalar/Setup" in saida.getvalue()


def test_status_mostra_a_versao_quando_o_pacote_esta_pronto(monkeypatch):
    import felixo_notion_mcp

    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: [])
    monkeypatch.setattr(start_app, "_resolver_runtime_front", lambda: None)
    saida = io.StringIO()

    start_app.acao_status(Console(file=saida, force_terminal=False, width=200))

    assert f"v{felixo_notion_mcp.__version__}" in saida.getvalue()


def test_status_mostra_de_onde_o_pacote_vem(monkeypatch):
    """Substitui o ``check-dev.py`` do hub: o Status diz se o código é o do checkout."""

    from felixo_notion_mcp.core.origem import origem_do_pacote

    monkeypatch.setattr(start_app, "_dependencias_faltando", lambda: [])
    monkeypatch.setattr(start_app, "_resolver_runtime_front", lambda: None)
    saida = io.StringIO()

    start_app.acao_status(Console(file=saida, force_terminal=False, width=400))

    texto = saida.getvalue()
    assert "Origem do pacote" in texto
    assert str(origem_do_pacote().pasta) in texto
    assert "checkout editável" in texto


# --------------------------------------------------------------------------- #
# Só reexecuta no .venv do projeto se ele consegue importar o pacote           #
# --------------------------------------------------------------------------- #
def test_nao_reexecuta_em_venv_que_nao_importa_o_pacote(monkeypatch):
    sondados = []
    chamadas = []
    monkeypatch.setattr(start_app, "_VENVS_RECUSADOS", set())
    monkeypatch.setattr(start_app, "_executavel_projeto", lambda: "/tmp/projeto/.venv/bin/python")
    monkeypatch.setattr(start_app.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(
        start_app,
        "_interpretador_importa_o_pacote",
        lambda executavel: sondados.append(executavel) or False,
    )
    monkeypatch.setattr(start_app.os, "execv", lambda *args: chamadas.append(args))

    start_app._reexecutar_no_python_do_projeto(["--action", "tudo"])

    assert sondados == [str(start_app.Path("/tmp/projeto/.venv/bin/python").absolute())]
    assert chamadas == []


def test_sonda_aceita_o_python_que_importa_o_pacote(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(RAIZ_DO_CHECKOUT / "src"))

    assert start_app._interpretador_importa_o_pacote(sys.executable) is True


def test_sonda_recusa_python_que_nao_existe(tmp_path):
    assert start_app._interpretador_importa_o_pacote(str(tmp_path / "nao-existe")) is False


def test_sonda_recusa_python_que_nao_acha_o_modulo(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(RAIZ_DO_CHECKOUT / "src"))
    monkeypatch.setattr(start_app, "MODULO_LAUNCHER", "felixo_notion_mcp.api.nao_existe")

    assert start_app._interpretador_importa_o_pacote(sys.executable) is False


def test_venv_recusado_pela_sonda_deixa_de_ser_o_python_do_projeto(monkeypatch, tmp_path):
    """Terminais dedicados e pip usam `_executavel_projeto`: não podem voltar ao .venv recusado."""
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(start_app, "RAIZ", tmp_path)
    monkeypatch.setattr(start_app, "MODO_CHECKOUT", True)
    monkeypatch.setattr(start_app, "_VENVS_RECUSADOS", set())
    monkeypatch.setattr(start_app, "_interpretador_importa_o_pacote", lambda executavel: False)
    monkeypatch.setattr(start_app.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(start_app.os, "execv", lambda *args: pytest.fail("não deve reexecutar"))
    assert start_app._executavel_projeto() == str(venv / "python")

    start_app._reexecutar_no_python_do_projeto([])

    assert start_app._executavel_projeto() == "/usr/bin/python3"
    assert start_app._comando_acao("status")[0] == "/usr/bin/python3"
