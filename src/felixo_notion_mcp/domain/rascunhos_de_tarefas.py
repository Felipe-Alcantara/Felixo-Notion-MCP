"""Regra pura: um lote de **rascunhos de tarefas** antes e depois de virar linhas.

Era a parte sem rede de ``scripts/notion/criar_tarefas_de_rascunhos.py``, sem o que
era deste workspace (database, colunas, repositórios e cabeçalho fixos): as colunas
vêm de ``propriedades`` e são conferidas contra o schema real, e quem é simétrico ou
espelho numa relação também vem do schema.

* :func:`validar_lote` — tudo o que impediria a gravação, antes de escrever;
* :func:`resolver_chaves` — `` `chave:x` ``, `` `x` `` e ``chave:x`` viram links;
* :func:`resolver_arestas` e :func:`rodadas_sem_pagina_repetida` — as ligações,
  sem duplicar a simétrica e sem duas escritas na mesma página ao mesmo tempo;
* :func:`itens_por_pagina` e :func:`secao_a_acrescentar` — a seção
  "Tarefas relacionadas", com link e motivo, só com o que falta.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from felixo_notion_mcp.core.exceptions import IdNotionInvalidoError
from felixo_notion_mcp.core.utils import chave_de_id, normalizar_id
from felixo_notion_mcp.domain.schema import problemas_de_valores

SECAO_RELACIONADAS = "## Tarefas relacionadas"
LIMITE_ROTULO_TABELA = 60
CHAVE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CITACAO = re.compile(
    r"`chave:([a-z0-9][a-z0-9-]*)`|`([a-z0-9][a-z0-9-]*)`|(?<![\w/`-])chave:([a-z0-9][a-z0-9-]*)"
)

Colunas = Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class Relacao:
    """Ligação pedida num rascunho: ``alvo`` é ``chave:<x>`` do lote ou ID/link."""

    alvo: str
    coluna: str
    motivo: str


@dataclass
class Rascunho:
    """Uma tarefa do lote: o ``<chave>.json`` com o corpo do ``<chave>.md``."""

    chave: str
    titulo: str
    propriedades: dict[str, Any]
    corpo: str
    relacoes: list[Relacao] = field(default_factory=list)


@dataclass(frozen=True)
class Aresta:
    """Ligação já resolvida para IDs: ``a`` é a dona da coluna."""

    a: str
    b: str
    coluna: str
    motivo: str


@dataclass(frozen=True)
class ItemRelacionado:
    """Uma linha da seção "Tarefas relacionadas" de uma página."""

    outra: str
    rotulo: str
    motivo: str


def link(page_id: str) -> str:
    """Link clicável de uma página do Notion."""

    return f"https://app.notion.com/p/{chave_de_id(page_id)}"


def id_do_alvo(alvo: str) -> str | None:
    """ID canônico de um alvo dado como UUID (com ou sem hífens) ou link; senão ``None``."""

    try:
        canonico = normalizar_id(alvo.strip())
    except IdNotionInvalidoError:
        return None
    return canonico if _UUID.match(canonico) else None


def _relacao_da_coluna(colunas: Colunas, nome: str) -> Mapping[str, Any]:
    return (colunas.get(nome) or {}).get("relacao") or {}


def validar_lote(rascunhos: list[Rascunho], colunas: Colunas) -> list[str]:
    """Tudo o que impede gravar o lote; vazia quando dá para escrever.

    Args:
        rascunhos: O lote inteiro (as citações ``chave:`` são conferidas entre eles).
        colunas: ``nome -> coluna`` na forma de ``DescricaoDatabase.para_dict``.
    """

    chaves = {r.chave for r in rascunhos}
    vistos: dict[str, str] = {}
    problemas: list[str] = []
    for r in rascunhos:
        if not CHAVE.match(r.chave):
            problemas.append(
                f"{r.chave}: chave só com minúsculas, números e hífen "
                "(é ela que vira link em 'chave:')"
            )
        titulo = r.titulo.strip()
        if not titulo:
            problemas.append(f"{r.chave}: título vazio")
        elif titulo in vistos:
            problemas.append(f"{r.chave}: título repetido de {vistos[titulo]}")
        else:
            vistos[titulo] = r.chave
        if not r.corpo.strip():
            problemas.append(f"{r.chave}: corpo vazio")
        elif SECAO_RELACIONADAS in r.corpo:
            problemas.append(
                f"{r.chave}: o corpo não deve trazer 'Tarefas relacionadas' "
                "(ela é gerada a partir de relacoes)"
            )
        do_rascunho = problemas_de_valores(r.propriedades, colunas)
        for relacao in r.relacoes:
            do_rascunho.extend(_problemas_da_relacao(r, relacao, colunas, chaves))
        problemas.extend(f"{r.chave}: {p}" for p in do_rascunho)
    return problemas


def _problemas_da_relacao(
    r: Rascunho, relacao: Relacao, colunas: Colunas, chaves: set[str]
) -> list[str]:
    problemas: list[str] = []
    coluna = colunas.get(relacao.coluna)
    if coluna is None:
        problemas.append(f"coluna de relação inexistente {relacao.coluna!r}")
    elif coluna.get("tipo") != "relation":
        problemas.append(f"{relacao.coluna!r} não é coluna de relação")
    elif not _relacao_da_coluna(colunas, relacao.coluna).get("auto_referente"):
        problemas.append(
            f"{relacao.coluna!r} liga a outro database; ponha os IDs em propriedades"
        )
    if not relacao.motivo.strip():
        problemas.append(f"relação com {relacao.alvo} sem motivo")
    alvo = relacao.alvo.strip()
    if alvo.startswith("chave:"):
        if alvo[6:] not in chaves:
            problemas.append(f"relação para chave inexistente {alvo}")
        elif alvo[6:] == r.chave:
            problemas.append("relação consigo mesma")
    elif id_do_alvo(alvo) is None:
        problemas.append(f"alvo {alvo!r} não é ID nem chave:")
    return problemas


# -- Corpo -----------------------------------------------------------------------


def rotulo_curto(titulo: str) -> str:
    """Rótulo para célula de tabela: o trecho depois do travessão, cortado na palavra."""

    texto = titulo.split(" — ", 1)[-1]
    if len(texto) <= LIMITE_ROTULO_TABELA:
        return texto
    corte = texto[:LIMITE_ROTULO_TABELA].rsplit(" ", 1)[0].rstrip(",;:")
    if corte.count("(") > corte.count(")"):
        # Não deixar parêntese aberto dentro do texto do link.
        corte = corte[: corte.rfind("(")].rstrip(" ,;:")
    return f"{corte}…"


def _rotulo_de_link(texto: str) -> str:
    return texto.replace("`", "").replace("[", "(").replace("]", ")")


def resolver_chaves(
    markdown: str, destinos: Mapping[str, tuple[str, str]]
) -> tuple[str, list[str]]:
    """Troca `` `chave:x` ``, `` `x` `` e ``chave:x`` do lote por links clicáveis.

    ``destinos`` é ``chave -> (page_id, título)``. Dentro de linha de tabela o rótulo é
    curto (:func:`rotulo_curto`); fora, é o título. Devolve o texto e as chaves
    citadas com ``chave:`` que não têm destino (`` `x` `` sem destino é só código).
    """

    sem_destino: list[str] = []
    linhas: list[str] = []
    for linha in markdown.split("\n"):
        em_tabela = linha.lstrip().startswith("|")

        def trocar(m: re.Match[str], em_tabela: bool = em_tabela) -> str:
            chave = m.group(1) or m.group(2) or m.group(3)
            if chave not in destinos:
                if m.group(1) or m.group(3):
                    sem_destino.append(chave)
                return m.group(0)
            page_id, titulo = destinos[chave]
            rotulo = rotulo_curto(titulo) if em_tabela else titulo
            return f"[{_rotulo_de_link(rotulo)}]({link(page_id)})"

        linhas.append(_CITACAO.sub(trocar, linha))
    return "\n".join(linhas), sem_destino


# -- Relações --------------------------------------------------------------------


def resolver_arestas(
    rascunhos: list[Rascunho], ids: Mapping[str, str], colunas: Colunas
) -> list[Aresta]:
    """As ligações do lote em IDs, sem repetir a simétrica (A↔B pedida dos dois lados).

    Simétrica é a relação auto-referente de mão única: :func:`relacionar` grava as duas
    pontas na mesma coluna. Na de mão dupla (coluna espelho), a direção importa.
    """

    arestas: dict[tuple[str, ...], Aresta] = {}
    for r in rascunhos:
        for relacao in r.relacoes:
            alvo = relacao.alvo.strip()
            b = ids[alvo[6:]] if alvo.startswith("chave:") else str(id_do_alvo(alvo))
            a = ids[r.chave]
            simetrica = not _relacao_da_coluna(colunas, relacao.coluna).get("bidirecional")
            chave: tuple[str, ...] = (
                (relacao.coluna, *sorted((a, b))) if simetrica else (relacao.coluna, a, b)
            )
            arestas.setdefault(chave, Aresta(a, b, relacao.coluna, relacao.motivo.strip()))
    return list(arestas.values())


def rodadas_sem_pagina_repetida(arestas: list[Aresta]) -> list[list[Aresta]]:
    """Agrupa as ligações em rodadas em que nenhuma página aparece duas vezes.

    ``relacionar`` lê a lista de relações de uma ponta e a regrava inteira; duas
    ligações tocando a mesma página ao mesmo tempo poderiam apagar uma à outra.
    """

    rodadas: list[tuple[set[str], list[Aresta]]] = []
    for aresta in arestas:
        for paginas, lista in rodadas:
            if aresta.a not in paginas and aresta.b not in paginas:
                paginas.update((aresta.a, aresta.b))
                lista.append(aresta)
                break
        else:
            rodadas.append(({aresta.a, aresta.b}, [aresta]))
    return [lista for _, lista in rodadas]


def itens_por_pagina(arestas: list[Aresta], colunas: Colunas) -> dict[str, list[ItemRelacionado]]:
    """Para cada página, o que citar na seção: a outra ponta, o rótulo e o motivo.

    Na relação de mão dupla, cada lado usa o nome da sua coluna ("Bloqueada por" de
    um lado, a espelho "Bloqueia" do outro); na simétrica, sem rótulo.
    """

    itens: dict[str, list[ItemRelacionado]] = {}
    for aresta in arestas:
        relacao = _relacao_da_coluna(colunas, aresta.coluna)
        if relacao.get("bidirecional"):
            de_a, de_b = aresta.coluna, str(relacao.get("coluna_espelho") or aresta.coluna)
        else:
            de_a = de_b = ""
        itens.setdefault(aresta.a, []).append(ItemRelacionado(aresta.b, de_a, aresta.motivo))
        itens.setdefault(aresta.b, []).append(ItemRelacionado(aresta.a, de_b, aresta.motivo))
    return itens


def _ultima_secao(markdown: str) -> str:
    secoes = [linha for linha in markdown.splitlines() if linha.startswith("## ")]
    return secoes[-1] if secoes else ""


def secao_a_acrescentar(
    markdown_atual: str,
    itens: list[ItemRelacionado],
    titulos: Mapping[str, str],
    destinos: Mapping[str, tuple[str, str]],
) -> str | None:
    """O Markdown a acrescentar no fim da página, ou ``None`` se todos os links já estão.

    Só entram os itens cuja página ainda não é citada no corpo; o título
    "## Tarefas relacionadas" só entra se a última seção ainda não for ela.
    """

    corpo = chave_de_id(markdown_atual)
    faltando = [item for item in itens if chave_de_id(item.outra) not in corpo]
    if not faltando:
        return None
    linhas: list[str] = []
    if "Tarefas relacionadas" not in _ultima_secao(markdown_atual):
        linhas.append(SECAO_RELACIONADAS)
    for item in faltando:
        prefixo = f"**{item.rotulo}:** " if item.rotulo else ""
        titulo = _rotulo_de_link(titulos.get(item.outra) or "(sem título)")
        motivo, _ = resolver_chaves(item.motivo, destinos)
        linhas.append(f"- {prefixo}[{titulo}]({link(item.outra)}) — {motivo}")
    return "\n\n".join(linhas) + "\n"
