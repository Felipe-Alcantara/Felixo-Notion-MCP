"""Contrato de linha de comando: o que a CLI aceitava antes continua sendo aceito.

``retrato_cli.json`` foi gravado a partir da CLI original (``notion-tasks-cli``), antes de
qualquer arquivo mudar de lugar. Se um destes testes falhar, alguma linha de comando que
funcionava deixou de ser aceita (ou passou a ter outro significado): isso é regressão, não
motivo para regravar o retrato.
"""

from __future__ import annotations

import json
from pathlib import Path

from felixo_notion_mcp.api.cli import notion_tasks, unificada
from felixo_notion_mcp.api.cli.retrato import retratar_parser
from felixo_notion_mcp.core import workspaces

RETRATO = json.loads((Path(__file__).parent / "retrato_cli.json").read_text(encoding="utf-8"))


def test_notion_tasks_aceita_todas_as_linhas_de_comando_de_antes():
    # Subcomando novo é funcionalidade, não regressão: só os que estão no retrato
    # precisam continuar idênticos, e as opções globais não podem mudar.
    atual = retratar_parser(notion_tasks.construir_parser())
    antes = RETRATO["notion_tasks"]
    assert {k: v for k, v in atual.items() if k != "subcomandos"} == {
        k: v for k, v in antes.items() if k != "subcomandos"
    }
    sumidos = sorted(set(antes["subcomandos"]) - set(atual["subcomandos"]))
    assert not sumidos, f"subcomandos que deixaram de existir: {sumidos}"
    for nome, retrato in antes["subcomandos"].items():
        _assert_compativel(nome, retrato, atual["subcomandos"][nome])


def _assert_compativel(nome: str, antes: dict, atual: dict) -> None:
    """Toda linha de comando antiga continua aceita e com o mesmo significado.

    Cada argumento do retrato tem de existir idêntico; argumento novo só passa se for
    flag opcional (posicional ou obrigatório novo quebraria comandos antigos).
    """

    assert {k: v for k, v in atual.items() if k != "argumentos"} == {
        k: v for k, v in antes.items() if k != "argumentos"
    }, f"'{nome}' mudou de estrutura"
    por_destino = {arg["destino"]: arg for arg in atual["argumentos"]}
    for arg in antes["argumentos"]:
        assert por_destino.get(arg["destino"]) == arg, f"'{nome}': {arg['destino']} mudou ou sumiu"
    antigos = {arg["destino"] for arg in antes["argumentos"]}
    for arg in atual["argumentos"]:
        if arg["destino"] not in antigos:
            assert arg["opcoes"] and not arg["obrigatorio"], (
                f"'{nome}': argumento novo {arg['destino']} precisa ser flag opcional"
            )


def test_fachada_aceita_exatamente_as_mesmas_linhas_de_comando():
    assert retratar_parser(unificada.construir_parser()) == RETRATO["unificada"]


def test_perfis_continuam_no_mesmo_caminho(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    relativo = workspaces.caminho_padrao().relative_to(tmp_path).as_posix()

    assert relativo == RETRATO["perfis"]["relativo"]
