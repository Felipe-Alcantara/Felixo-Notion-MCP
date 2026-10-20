"""Caso de uso: configurar a **ordenação** (e o nome) de uma view de database.

Usa a Views API oficial (``/views``, versão ``2026-03-11``, lançada em
2026-03-19). Medido em 2026-10-20: um database criado pela API nasce com uma
view ``table`` chamada ``"Default view"`` e ``sorts: null``.

A escrita é confirmada por releitura: o PATCH pode responder 200 e a view não
mudar (já aconteceu com o ``parent`` de páginas), então o resultado só é
``aplicado`` se a view relida tiver a ordenação pedida.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from felixo_notion_mcp.core.exceptions import NotionSyncError

if TYPE_CHECKING:
    from felixo_notion_mcp.integrations.notion_client import NotionClient

#: Direções aceitas, com os apelidos em português que a CLI recebe.
DIRECOES = {
    "asc": "ascending",
    "ascending": "ascending",
    "crescente": "ascending",
    "desc": "descending",
    "descending": "descending",
    "decrescente": "descending",
}


class ViewNaoEncontradaError(NotionSyncError, ValueError):
    """O database não tem a view pedida (ou nenhuma view do tipo esperado)."""


@dataclass(frozen=True)
class ResultadoOrdenacao:
    """O que :func:`ordenar_view` fez, já conferido por releitura."""

    database_id: str
    view_id: str
    nome: str
    tipo: str
    sorts: list[dict[str, str]]
    aplicado: bool

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from felixo_notion_mcp.integrations.notion import criar_cliente

    return criar_cliente()


def normalizar_direcao(direcao: str) -> str:
    """Traduz ``desc``/``decrescente``/… para o valor da API."""

    valor = DIRECOES.get(direcao.strip().casefold())
    if valor is None:
        raise ValueError(
            f"Direção '{direcao}' inválida. Use: {', '.join(sorted(DIRECOES))}."
        )
    return valor


def _escolher_view(
    cliente: NotionClient, database_id: str, view_id: str | None, tipo: str
) -> dict[str, Any]:
    """A view pedida, ou a primeira do tipo ``tipo`` do database."""

    if view_id:
        return cliente.obter_view(view_id)
    for candidato in cliente.listar_views(database_id):
        view = cliente.obter_view(candidato)
        if view.get("type") == tipo:
            return view
    raise ViewNaoEncontradaError(
        f"O database {database_id} não tem view do tipo '{tipo}'. "
        "Passe --view <view_id> para escolher outra."
    )


def ordenar_view(
    database_id: str,
    propriedade: str,
    direcao: str = "descending",
    *,
    view_id: str | None = None,
    tipo: str = "table",
    nome: str | None = None,
    cliente: NotionClient | None = None,
) -> ResultadoOrdenacao:
    """Ordena uma view por uma propriedade, substituindo a ordenação anterior.

    Args:
        database_id: Database dono da view.
        propriedade: Nome (ou ID) da propriedade usada na ordenação.
        direcao: ``descending``/``desc``/``decrescente`` ou o equivalente crescente.
        view_id: View exata; sem ela, vale a primeira view do ``tipo``.
        tipo: Tipo de view procurado quando ``view_id`` não é informado.
        nome: Novo nome da view, quando informado.
        cliente: Cliente do Notion (injetável em testes).

    Raises:
        ViewNaoEncontradaError: Se não houver view para ordenar.
        ValueError: Se a direção for inválida.
    """

    cliente = cliente or _cliente_padrao()
    sorts = [{"property": propriedade.strip(), "direction": normalizar_direcao(direcao)}]
    view = _escolher_view(cliente, database_id, view_id, tipo)
    alteracoes: dict[str, Any] = {"sorts": sorts}
    if nome and nome.strip():
        alteracoes["name"] = nome.strip()
    cliente.atualizar_view(str(view["id"]), alteracoes)

    relida = cliente.obter_view(str(view["id"]))
    sorts_relidos = [
        {"property": str(s.get("property", "")), "direction": str(s.get("direction", ""))}
        for s in relida.get("sorts") or []
        if isinstance(s, dict)
    ]
    return ResultadoOrdenacao(
        database_id=database_id,
        view_id=str(relida.get("id") or view["id"]),
        nome=str(relida.get("name") or ""),
        tipo=str(relida.get("type") or ""),
        sorts=sorts_relidos,
        aplicado=_mesma_ordenacao(sorts_relidos, sorts),
    )


def _mesma_ordenacao(relidos: list[dict[str, str]], pedidos: list[dict[str, str]]) -> bool:
    """Compara a ordenação relida com a pedida.

    A API pode devolver a propriedade pelo ID em vez do nome; nesse caso basta
    a direção e a quantidade baterem — a propriedade em si já foi validada pelo
    PATCH, que recusa nome inexistente.
    """

    if len(relidos) != len(pedidos):
        return False
    return all(r["direction"] == p["direction"] for r, p in zip(relidos, pedidos, strict=True))
