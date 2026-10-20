"""Caso de uso: definir o ícone e a capa de uma página sem apagar o que já existe.

Cada valor pode ser um emoji (só ícone), uma URL externa ou um arquivo de imagem
local, que é enviado pela File Upload API. Por padrão, ícone ou capa que a página já
tem são mantidos — quem já escolheu uma imagem à mão não perde a escolha; use
``substituir=True`` para trocar.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from felixo_notion_mcp.domain import aparencia
from felixo_notion_mcp.integrations.notion_client import NotionClient
from felixo_notion_mcp.services.anexos import descobrir_content_type

#: Limite de upload por arquivo no plano gratuito do Notion.
LIMITE_UPLOAD = 5 * 1024 * 1024


def _objeto(
    valor: str, *, cliente: NotionClient, campo: str, limite_bytes: int = LIMITE_UPLOAD
) -> dict[str, Any]:
    tipo = aparencia.classificar(valor)
    if tipo == "emoji":
        if campo == "capa":
            raise ValueError("A capa não aceita emoji: use uma URL ou um arquivo de imagem.")
        return aparencia.emoji(valor)
    if tipo == "externo":
        return aparencia.externa(valor)
    arquivo = Path(valor.strip())
    if not arquivo.is_file():
        raise ValueError(f"Arquivo de imagem não encontrado: {arquivo}")
    if arquivo.stat().st_size > limite_bytes:
        # Imagem acima do limite do upload: sobe uma cópia comprimida até caber.
        from felixo_notion_mcp.integrations import imagens

        with tempfile.TemporaryDirectory() as pasta:
            menor = imagens.caber_em(arquivo, Path(pasta) / f"{arquivo.stem}.jpg", limite_bytes)
            upload_id = cliente.enviar_arquivo(menor.read_bytes(), menor.name, "image/jpeg")
        return aparencia.enviada(upload_id)
    upload_id = cliente.enviar_arquivo(
        arquivo.read_bytes(), arquivo.name, descobrir_content_type(arquivo.name)
    )
    return aparencia.enviada(upload_id)


def definir_aparencia(
    page_id: str,
    *,
    icone: str | None = None,
    capa: str | None = None,
    substituir: bool = False,
    cliente: NotionClient,
) -> dict[str, Any]:
    """Grava ícone e/ou capa de uma página, preservando o que já existe.

    Args:
        page_id: ID da página (ou linha de database).
        icone: Emoji, URL ``http(s)`` ou caminho de imagem local; ``None`` não mexe.
        capa: URL ``http(s)`` ou caminho de imagem local; ``None`` não mexe.
        substituir: Troca ícone/capa mesmo que a página já tenha.
        cliente: Cliente Notion injetado.

    Returns:
        Para ``icone`` e ``capa``: ``"gravado"``, ``"mantido"`` (já existia e
        ``substituir`` é falso) ou ``None`` (não foi pedido), mais o valor anterior.

    Raises:
        ValueError: Se nada for pedido, se o valor for inválido (inclusive emoji na
            capa) ou se o arquivo local não existir.
    """

    if icone is None and capa is None:
        raise ValueError("Informe --icone, --capa ou os dois.")
    # Valida os dois antes de qualquer rede: erro de digitação não deve subir arquivo.
    for valor, campo in ((icone, "icone"), (capa, "capa")):
        if valor is not None:
            tipo = aparencia.classificar(valor)
            if campo == "capa" and tipo == "emoji":
                raise ValueError("A capa não aceita emoji: use uma URL ou um arquivo de imagem.")

    pagina = cliente.obter_pagina(page_id)
    atual = {"icone": pagina.get("icon"), "capa": pagina.get("cover")}
    pedidos = {"icone": icone, "capa": capa}
    resultado: dict[str, Any] = {"page_id": page_id}
    gravar: dict[str, dict[str, Any]] = {}
    for campo, valor in pedidos.items():
        resultado[f"{campo}_anterior"] = aparencia.descrever(atual[campo])
        if valor is None:
            resultado[campo] = None
        elif atual[campo] and not substituir:
            resultado[campo] = "mantido"
        else:
            gravar[campo] = _objeto(valor, cliente=cliente, campo=campo)
            resultado[campo] = "gravado"
    if gravar:
        cliente.atualizar_aparencia(page_id, icone=gravar.get("icone"), capa=gravar.get("capa"))
    return resultado
