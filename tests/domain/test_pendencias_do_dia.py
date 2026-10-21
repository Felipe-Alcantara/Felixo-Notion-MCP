"""Testes de ``domain.pendencias_do_dia``: o que de um dia continua no seguinte."""

from __future__ import annotations

import copy
from typing import Any

from felixo_notion_mcp.domain import pendencias_do_dia as pend


def _rico(texto: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": texto}, "plain_text": texto}]


def _bloco(tipo: str, texto: str, *filhos: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Bloco como ``ler_blocos(recursivo=True)`` devolve (filhos em ``_filhos``)."""

    return {"type": tipo, tipo: {"rich_text": _rico(texto), **extra}, "_filhos": list(filhos)}


def _h2(texto: str) -> dict[str, Any]:
    return _bloco("heading_2", texto)


def _h3(texto: str) -> dict[str, Any]:
    return _bloco("heading_3", texto)


def _toggle(texto: str, *filhos: dict[str, Any]) -> dict[str, Any]:
    return _bloco("toggle", texto, *filhos)


def _tarefa(texto: str, *filhos: dict[str, Any], feita: bool = False) -> dict[str, Any]:
    return _bloco("to_do", texto, *filhos, checked=feita)


def _item(texto: str) -> dict[str, Any]:
    return _bloco("bulleted_list_item", texto)


def _textos(blocos: list[dict[str, Any]]) -> list[str]:
    return [pend.texto_do_bloco(b) for b in blocos]


def test_tarefa_concluida_fica_no_dia_de_origem():
    blocos = [
        _h2("Tarefas de trabalho"),
        _h3("Repo"),
        _tarefa("Feita", feita=True),
        _tarefa("Aberta"),
    ]

    assert _textos(pend.filtrar_pendencias(blocos)) == ["Tarefas de trabalho", "Repo", "Aberta"]


def test_tarefa_pendente_vai_inteira_com_passos_feitos_e_notas():
    tarefa = _tarefa(
        "Moeda por país",
        _tarefa("Ler o código", _item("Feito: decide pelo IP"), feita=True),
        _tarefa("Testar no painel", _item("Não feito: sem acesso")),
        _item("Dependência: painel da Stripe"),
    )

    (_, levada) = pend.filtrar_pendencias([_h2("Tarefas de trabalho"), tarefa])

    assert levada == tarefa


def test_toggle_perde_as_concluidas_e_some_quando_nao_sobra_pendencia():
    blocos = [
        _h2("Tarefas de trabalho"),
        _h3("MeuEcoo"),
        _toggle("Afiliados", _tarefa("Regra conferida", feita=True), _tarefa("Testar em produção")),
        _toggle("Cobrança", _tarefa("Tudo feito", feita=True)),
    ]

    resultado = pend.filtrar_pendencias(blocos)

    assert _textos(resultado) == ["Tarefas de trabalho", "MeuEcoo", "Afiliados"]
    assert _textos(resultado[2]["_filhos"]) == ["Testar em produção"]


def test_titulo_de_repositorio_so_entra_com_pendencia_embaixo():
    blocos = [
        _h2("Projetos pessoais"),
        _h3("Tudo concluído"),
        _tarefa("Feita", feita=True),
        _h3("Com pendência"),
        _tarefa("Aberta"),
    ]

    assert _textos(pend.filtrar_pendencias(blocos)) == [
        "Projetos pessoais",
        "Com pendência",
        "Aberta",
    ]


def test_secoes_de_tarefas_ficam_mesmo_vazias_e_anotacoes_e_resumo_nao_vao():
    blocos = [
        _h2("Tarefas de trabalho"),
        _h2("Projetos pessoais"),
        _h2("Dia a dia"),
        _h3("MEI"),
        _tarefa("Mandar o DAS"),
        _h2("Anotações do dia"),
        _item("Fontes: horários de ontem"),
        _tarefa("Lembrete solto nas anotações"),
        _h2("Resumo do dia"),
        _item("Concluído: tudo"),
    ]

    assert _textos(pend.filtrar_pendencias(blocos)) == [
        "Tarefas de trabalho",
        "Projetos pessoais",
        "Dia a dia",
        "MEI",
        "Mandar o DAS",
    ]


def test_filtrar_nao_altera_a_arvore_lida():
    blocos = [
        _h2("Tarefas de trabalho"),
        _toggle("Grupo", _tarefa("Feita", feita=True), _tarefa("Aberta")),
    ]
    antes = copy.deepcopy(blocos)

    pend.filtrar_pendencias(blocos)

    assert blocos == antes


def test_titulos_das_tarefas_contam_so_o_nivel_de_tarefa():
    blocos = [
        _h2("Tarefas de trabalho"),
        _toggle("Grupo", _tarefa("Dentro do toggle", _tarefa("Passo"))),
        _tarefa("Solta", _tarefa("Outro passo")),
    ]

    assert pend.titulos_das_tarefas(blocos) == ["Dentro do toggle", "Solta"]
