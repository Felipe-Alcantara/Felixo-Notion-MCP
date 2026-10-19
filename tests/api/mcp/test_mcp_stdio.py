"""Contrato do servidor MCP no fio: handshake real por ``stdio``.

Os outros testes do servidor chamam as funções Python direto; este sobe o
processo como um cliente externo sobe (o Felixo-AI-Core, um agente de
programação) e conversa em JSON-RPC cru, sem passar pelo SDK do lado do
cliente. Assim ele vale igual para qualquer versão do SDK ``mcp`` instalada e
pega o que uma troca de versão quebraria sem aviso: a negociação do protocolo
com clientes da era do ``initialize``, as instruções enviadas ao modelo, a
lista de ferramentas e as anotações em camelCase que o host lê para decidir o
que pede confirmação.

Nada fala com o Notion: além de ``initialize`` e ``tools/list``, a única
chamada de ferramenta tem entrada inválida e é recusada antes de qualquer
requisição.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest

import felixo_notion_mcp

# Versão de protocolo da era do ``initialize`` que os clientes de 2025 ainda
# propõem. O servidor tem de aceitá-la e responder com a mesma.
PROTOCOLO_DO_CLIENTE = "2025-06-18"

# Subir o interpretador e importar o pacote passa de 10 s em máquina lenta.
TEMPO_MAXIMO_POR_RESPOSTA = 90

FERRAMENTAS_ESPERADAS = {
    "notion.list_tasks",
    "notion.create_task",
    "notion.move_status",
    "notion.conclude_task",
    "notion.update_project_page",
    "notion.update_github_inventory",
    "notion.search",
    "notion.read_page_content",
    "notion.list_database_rows",
    "notion.clone_database",
    "notion.append_content",
    "notion.edit_block",
    "notion.delete_block",
    "notion.create_database",
    "notion.import_spreadsheet",
    "notion.upload_file",
    "notion.move_page",
    "notion.move_database",
}


class _ServidorStdio:
    """Processo do servidor MCP com leitura de respostas por linha e prazo."""

    def __init__(self) -> None:
        env = dict(os.environ)
        env.pop("NOTION_TOKEN", None)
        env.pop("NOTION_DATABASE_ID", None)
        # O processo filho importa o pacote da mesma pasta que este teste importou,
        # mesmo onde o modo editável não funciona (caminho com acento no Windows).
        raiz_do_pacote = str(Path(felixo_notion_mcp.__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(
            parte for parte in (raiz_do_pacote, env.get("PYTHONPATH", "")) if parte
        )
        # O log do servidor vai para um arquivo: um pipe que ninguém esvazia enche
        # e trava o processo filho no meio da conversa.
        self._log = tempfile.TemporaryFile()
        self._processo = subprocess.Popen(
            [sys.executable, "-m", "felixo_notion_mcp.api.mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            env=env,
        )
        self._linhas: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._ler_stdout, daemon=True).start()

    def _ler_stdout(self) -> None:
        assert self._processo.stdout is not None
        for linha in self._processo.stdout:
            self._linhas.put(linha)

    def enviar(self, mensagem: dict[str, Any]) -> None:
        assert self._processo.stdin is not None
        self._processo.stdin.write((json.dumps(mensagem) + "\n").encode("utf-8"))
        self._processo.stdin.flush()

    def resposta(self, id_: int) -> dict[str, Any]:
        """Devolve a resposta ao pedido ``id_``, pulando notificações do servidor."""

        while True:
            try:
                linha = self._linhas.get(timeout=TEMPO_MAXIMO_POR_RESPOSTA)
            except queue.Empty:
                pytest.fail(f"o servidor não respondeu ao pedido {id_}:\n{self._fim_do_log()}")
            mensagem = json.loads(linha.decode("utf-8"))
            if mensagem.get("id") == id_:
                return mensagem

    def _fim_do_log(self) -> str:
        self._log.seek(0)
        return self._log.read().decode("utf-8", errors="replace")[-2000:]

    def encerrar(self) -> int:
        assert self._processo.stdin is not None
        self._processo.stdin.close()
        try:
            return self._processo.wait(timeout=TEMPO_MAXIMO_POR_RESPOSTA)
        except subprocess.TimeoutExpired:
            self._processo.kill()
            self._processo.wait()
            pytest.fail(f"o servidor não encerrou depois que o stdin fechou:\n{self._fim_do_log()}")
        finally:
            self._log.close()


@pytest.fixture(scope="module")
def conversa() -> dict[str, Any]:
    """Faz o handshake e lista as ferramentas uma vez para todos os testes."""

    servidor = _ServidorStdio()
    try:
        servidor.enviar(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOLO_DO_CLIENTE,
                    "capabilities": {},
                    "clientInfo": {"name": "teste-de-contrato", "version": "0"},
                },
            }
        )
        inicializacao = servidor.resposta(1)
        servidor.enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
        servidor.enviar({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        ferramentas = servidor.resposta(2)
        servidor.enviar(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "notion.read_page_content", "arguments": {"page_id": " "}},
            }
        )
        chamada_invalida = servidor.resposta(3)
    finally:
        codigo_de_saida = servidor.encerrar()
    return {
        "inicializacao": inicializacao,
        "ferramentas": ferramentas,
        "chamada_invalida": chamada_invalida,
        "codigo_de_saida": codigo_de_saida,
    }


def _ferramentas(conversa: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in conversa["ferramentas"]["result"]["tools"]}


def test_negocia_o_protocolo_proposto_pelo_cliente(conversa):
    resultado = conversa["inicializacao"]["result"]
    assert resultado["protocolVersion"] == PROTOCOLO_DO_CLIENTE


def test_se_identifica_com_o_nome_e_a_versao_do_pacote(conversa):
    info = conversa["inicializacao"]["result"]["serverInfo"]
    assert info["name"] == "notion"
    assert info["version"] == felixo_notion_mcp.__version__


def test_envia_as_instrucoes_de_confirmacao_ao_cliente(conversa):
    instrucoes = conversa["inicializacao"]["result"]["instructions"]
    assert "REGRA DO LINK" in instrucoes
    assert "confirmacao" in instrucoes


def test_lista_todas_as_ferramentas(conversa):
    assert set(_ferramentas(conversa)) == FERRAMENTAS_ESPERADAS


def test_anotacoes_seguem_o_formato_do_protocolo(conversa):
    ferramentas = _ferramentas(conversa)
    assert ferramentas["notion.list_tasks"]["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "openWorldHint": True,
    }
    assert ferramentas["notion.delete_block"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }


def test_esquemas_de_entrada_sao_objetos(conversa):
    for nome, ferramenta in _ferramentas(conversa).items():
        assert ferramenta["inputSchema"]["type"] == "object", nome


def test_erro_da_ferramenta_volta_como_resultado_e_nao_como_erro_de_protocolo(conversa):
    # O modelo precisa ler o motivo da recusa; um erro JSON-RPC derrubaria a chamada.
    resposta = conversa["chamada_invalida"]
    assert "error" not in resposta
    assert resposta["result"]["isError"] is True
    assert "'page_id' e obrigatorio" in resposta["result"]["content"][0]["text"]


def test_encerra_limpo_quando_o_cliente_fecha_o_stdin(conversa):
    assert conversa["codigo_de_saida"] == 0
