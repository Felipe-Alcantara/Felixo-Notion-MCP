"""Edição de propriedades (colunas) de uma linha genérica de database.

Ao trabalhar numa página que é linha de um database, o recomendado é começar
pelas **propriedades** (as colunas: status, datas, seleções, relações…) e só
depois preencher o **conteúdo** (os blocos do corpo da página). Este módulo
cobre a parte de propriedades, que faltava na CLI: os comandos de `tarefa`
editam só o modelo de tarefas, e os de bloco mexem no conteúdo — para uma linha
qualquer não havia caminho, forçando o uso direto da API.

O fluxo é simples: lê a página (a resposta já traz o ``type`` de cada coluna),
converte os valores informados para o formato da API do Notion e faz um único
PATCH com todas as mudanças.
"""

from __future__ import annotations

from typing import Any

from felixo_notion_mcp import NotionClient
from felixo_notion_mcp.domain import properties as prop

# Tipos calculados/gerenciados pelo Notion: não aceitam escrita via API.
_SOMENTE_LEITURA = frozenset(
    {
        "formula",
        "rollup",
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "unique_id",
        "button",
    }
)


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` a partir da configuração do servidor.

    Import tardio de propósito: evita acoplar a camada de casos de uso ao Django
    no import — a config só é tocada quando nenhum cliente é injetado.
    """

    from felixo_notion_mcp.integrations.notion import criar_cliente

    return criar_cliente()


def _numero(texto: str) -> float | int:
    """Converte texto em ``int`` quando inteiro, senão ``float``."""

    try:
        return int(texto)
    except ValueError:
        return float(texto)


def _lista(texto: str) -> list[str]:
    """Divide um texto CSV em itens não vazios."""

    return [parte.strip() for parte in texto.split(",") if parte.strip()]


def _para_valor(tipo: str, texto: str) -> dict[str, Any]:
    """Converte ``texto`` no payload de propriedade do ``tipo`` informado.

    Um texto vazio limpa a propriedade quando o tipo permite. Levanta
    ``ValueError`` para tipos ainda não suportados ou valores inválidos.
    """

    texto = texto.strip()
    vazio = texto == ""

    if tipo == "title":
        return {"title": []} if vazio else prop.title(texto)
    if tipo == "rich_text":
        return {"rich_text": []} if vazio else prop.rich_text(texto)
    if tipo == "number":
        if vazio:
            return {"number": None}
        try:
            return prop.number(_numero(texto))
        except ValueError as exc:
            raise ValueError(f"'{texto}' não é um número válido.") from exc
    if tipo == "checkbox":
        return prop.checkbox(texto.casefold() in {"true", "1", "sim", "yes", "x", "✓"})
    if tipo == "select":
        return {"select": None} if vazio else prop.select(texto)
    if tipo == "status":
        if vazio:
            raise ValueError("Uma propriedade 'status' não pode ficar vazia.")
        return prop.status(texto)
    if tipo == "multi_select":
        return prop.multi_select(_lista(texto))
    if tipo == "relation":
        return prop.relation(_lista(texto))
    if tipo == "people":
        return {"people": [{"id": id_} for id_ in _lista(texto)]}
    if tipo == "date":
        if vazio:
            return {"date": None}
        # Aceita intervalo no formato "inicio..fim".
        inicio, _, fim = texto.partition("..")
        return prop.date(inicio.strip(), fim.strip() or None)
    if tipo == "email":
        return {"email": texto or None}
    if tipo == "phone_number":
        return {"phone_number": texto or None}
    if tipo == "url":
        return {"url": texto or None}

    raise ValueError(f"Tipo '{tipo}' ainda não é suportado por editar-linha.")


# Colunas de texto às quais dá para *acrescentar* (append) preservando o atual.
_TIPOS_TEXTO = frozenset({"title", "rich_text"})


def valor_de_propriedade(tipo: str, texto: str) -> dict[str, Any]:
    """Versão pública de :func:`_para_valor`: texto -> payload da coluna do ``tipo``.

    Usada por quem monta propriedades fora de :func:`editar_linha`, como a criação
    de linhas em :mod:`felixo_notion_mcp.services.biblioteca`.
    """

    return _para_valor(tipo, texto)


def _item_gravavel(item: dict[str, Any]) -> dict[str, Any]:
    """Reduz um item de rich_text (como vem da API) à forma gravável.

    Preserva o conteúdo, o link e as anotações (negrito, itálico…), descartando
    campos só-leitura como ``plain_text``/``href``. Itens não-texto (mention,
    equation) são reenviados sem os campos de topo só-leitura.
    """

    tipo = item.get("type", "text")
    if tipo != "text":
        return {k: v for k, v in item.items() if k in ("type", tipo, "annotations")}
    origem = item.get("text", {}) or {}
    texto: dict[str, Any] = {"content": origem.get("content", item.get("plain_text", ""))}
    if origem.get("link"):
        texto["link"] = origem["link"]
    gravavel: dict[str, Any] = {"type": "text", "text": texto}
    if item.get("annotations"):
        gravavel["annotations"] = item["annotations"]
    return gravavel


def _itens_texto(tipo: str, texto: str) -> list[dict[str, Any]]:
    """Itens de rich_text/title para o texto do append, **sem** aparar espaços.

    Diferente do ``--set``, o append preserva o texto exato (incluindo quebras
    de linha usadas como separador). Texto vazio não acrescenta nada.
    """

    if texto == "":
        return []
    builder = prop.title if tipo == "title" else prop.rich_text
    return builder(texto)[tipo]


def _coluna(props: dict[str, Any], nome: str) -> str:
    """Valida que ``nome`` existe e não é só-leitura; devolve o ``type`` da coluna."""

    if nome not in props:
        disponiveis = ", ".join(sorted(props)) or "(nenhuma)"
        raise ValueError(
            f"Propriedade '{nome}' não existe nesta linha. Disponíveis: {disponiveis}"
        )
    tipo = props[nome].get("type", "")
    if tipo in _SOMENTE_LEITURA:
        raise ValueError(
            f"Propriedade '{nome}' é do tipo '{tipo}', calculada pelo Notion, "
            "e não pode ser editada."
        )
    return tipo


def editar_linha(
    page_id: str,
    valores: dict[str, str] | None = None,
    acrescentos: dict[str, str] | None = None,
    *,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Edita propriedades de uma linha de database em um único PATCH.

    Args:
        page_id: ID da página (linha) a editar.
        valores: Mapa ``{coluna: valor}`` a **substituir**. O valor é texto; o
            formato certo é inferido do ``type`` real da coluna.
        acrescentos: Mapa ``{coluna: texto}`` a **acrescentar** ao final, só para
            colunas de texto (``title``/``rich_text``). Preserva o conteúdo atual
            (os itens rich_text originais) e o texto novo é fatiado em ≤2000.
        cliente: Cliente opcional; injete um double em testes.

    Returns:
        ``{"id": page_id, "atualizadas": {coluna: descrição, ...}}``.

    Raises:
        ValueError: nada informado, mesma coluna em ``valores`` e ``acrescentos``,
            coluna inexistente, tipo só-leitura/insuportado, append em coluna que
            não é de texto, ou valor inválido — sempre com mensagem acionável.
    """

    valores = valores or {}
    acrescentos = acrescentos or {}
    if not valores and not acrescentos:
        raise ValueError(
            'Informe ao menos uma propriedade (ex.: --set "Status=Feito" '
            'ou --append "Resumo=... texto ...").'
        )
    conflito = set(valores) & set(acrescentos)
    if conflito:
        raise ValueError(
            f"Coluna(s) em --set e --append ao mesmo tempo: {', '.join(sorted(conflito))}. "
            "Use um ou outro por coluna."
        )

    cliente = cliente or _cliente_padrao()
    props = cliente.obter_pagina(page_id).get("properties", {})

    payload: dict[str, dict[str, Any]] = {}
    atualizadas: dict[str, str] = {}

    for nome, texto in valores.items():
        tipo = _coluna(props, nome)
        payload[nome] = _para_valor(tipo, texto)
        atualizadas[nome] = tipo

    for nome, texto in acrescentos.items():
        tipo = _coluna(props, nome)
        if tipo not in _TIPOS_TEXTO:
            raise ValueError(
                f"--append só vale para colunas de texto (title/rich_text); "
                f"'{nome}' é do tipo '{tipo}'. Use --set para substituir."
            )
        originais = [_item_gravavel(i) for i in props[nome].get(tipo, [])]
        payload[nome] = {tipo: originais + _itens_texto(tipo, texto)}
        atualizadas[nome] = f"{tipo} (append)"

    cliente.atualizar_pagina(page_id, payload)
    return {"id": page_id, "atualizadas": atualizadas}
