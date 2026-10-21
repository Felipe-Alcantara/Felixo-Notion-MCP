"""Regra pura: o que de um dia do **Registro diário** continua pendente no dia seguinte.

Recebe a árvore de blocos de um dia como ``ler_blocos(..., recursivo=True)`` a
devolve (filhos em ``_filhos``) e devolve só o que vai para o dia novo, na mesma
ordem e na mesma forma, para ser regravado bloco a bloco:

* os títulos das seções de tarefas (:data:`SECOES_DE_TAREFAS`) ficam sempre, mesmo
  sem nada embaixo, para o dia novo manter o modelo;
* tarefa (``to_do``) pendente vai **inteira**: passos já feitos e notas explicam
  onde ela parou;
* toggle (um assunto dentro do repositório) vai só com as tarefas pendentes, e
  some quando não sobra nenhuma;
* título de repositório (``heading_3``) só vai com alguma pendência embaixo;
* anotações e resumo da origem ficam nela: são daquele dia.

A árvore lida não é alterada.
"""

from __future__ import annotations

from typing import Any

#: Seções do modelo "Dia padrão" que guardam tarefas; as demais são do próprio dia.
SECOES_DE_TAREFAS = ("Tarefas de trabalho", "Projetos pessoais", "Dia a dia")

Bloco = dict[str, Any]


def texto_do_bloco(bloco: Bloco) -> str:
    """Texto visível de um bloco (``plain_text`` do *rich text*)."""

    corpo = bloco.get(str(bloco.get("type") or ""))
    itens = corpo.get("rich_text") if isinstance(corpo, dict) else None
    return "".join(str(i.get("plain_text", "")) for i in itens or [] if isinstance(i, dict))


def _filhos(bloco: Bloco) -> list[Bloco]:
    return [f for f in bloco.get("_filhos") or [] if isinstance(f, dict)]


def tarefa_pendente(bloco: Bloco) -> bool:
    """Uma tarefa (``to_do``) ainda está pendente?"""

    return not (bloco.get("to_do") or {}).get("checked")


def _pendente(bloco: Bloco) -> bool:
    """Tarefa pendente, ou toggle que ainda guarda uma."""

    tipo = bloco.get("type")
    if tipo == "to_do":
        return tarefa_pendente(bloco)
    if tipo == "toggle":
        return any(_pendente(f) for f in _filhos(bloco))
    return False


def _podar(bloco: Bloco) -> Bloco:
    """Toggle sem as tarefas concluídas; tarefa e outros blocos voltam como estão."""

    if bloco.get("type") != "toggle":
        return bloco
    return {
        **bloco,
        "_filhos": [
            _podar(f)
            for f in _filhos(bloco)
            if f.get("type") not in ("to_do", "toggle") or _pendente(f)
        ],
    }


def filtrar_pendencias(blocos: list[Bloco]) -> list[Bloco]:
    """Os blocos do dia que vão para o dia seguinte (regras no docstring do módulo)."""

    saida: list[Bloco] = []
    secao: str | None = None
    titulo: Bloco | None = None
    for bloco in blocos:
        tipo = bloco.get("type")
        if tipo == "heading_2":
            secao, titulo = texto_do_bloco(bloco).strip(), None
            if secao in SECOES_DE_TAREFAS:
                saida.append(bloco)
            continue
        if secao not in SECOES_DE_TAREFAS:
            continue
        if tipo == "heading_3":
            titulo = bloco
            continue
        if _pendente(bloco):
            if titulo is not None:
                saida.append(titulo)
                titulo = None
            saida.append(_podar(bloco))
    return saida


def titulos_das_tarefas(blocos: list[Bloco]) -> list[str]:
    """Texto de cada tarefa no nível de tarefa (solta ou dentro de toggle), sem os passos."""

    titulos: list[str] = []
    for bloco in blocos:
        if bloco.get("type") == "to_do":
            titulos.append(texto_do_bloco(bloco))
        elif bloco.get("type") == "toggle":
            titulos.extend(titulos_das_tarefas(_filhos(bloco)))
    return titulos
