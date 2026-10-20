"""Regras puras de aparência de página: ícone e capa.

O Notion aceita três formas de imagem em ``icon`` e ``cover``: emoji (só no ícone),
URL externa e arquivo enviado pela File Upload API. Este módulo só decide qual é
a forma de um valor informado pela borda e monta o objeto que a API espera — ler
o arquivo, subir e gravar fica em :mod:`felixo_notion_mcp.services.aparencia`.
"""

from __future__ import annotations

from typing import Any, Literal

TipoImagem = Literal["emoji", "externo", "arquivo"]

#: Extensões que a File Upload API aceita como imagem de ícone ou capa.
EXTENSOES_DE_IMAGEM = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def classificar(valor: str) -> TipoImagem:
    """Diz se ``valor`` é uma URL, um caminho de arquivo de imagem ou um emoji.

    Raises:
        ValueError: Se o valor estiver vazio ou não se encaixar em nenhuma forma.
    """

    texto = valor.strip()
    if not texto:
        raise ValueError("valor de imagem vazio")
    if texto.lower().startswith(("http://", "https://")):
        return "externo"
    if "://" in texto:
        raise ValueError(f"{texto!r}: o Notion só aceita imagem externa por http(s)")
    if texto.lower().endswith(EXTENSOES_DE_IMAGEM):
        return "arquivo"
    # Emoji é curto e não tem letra nem dígito ASCII; o resto é erro de digitação.
    if len(texto) <= 16 and not any(c.isascii() and c.isalnum() for c in texto):
        return "emoji"
    raise ValueError(
        f"{texto!r} não é emoji, URL http(s) nem arquivo de imagem "
        f"({', '.join(EXTENSOES_DE_IMAGEM)})"
    )


def emoji(valor: str) -> dict[str, Any]:
    return {"type": "emoji", "emoji": valor.strip()}


def externa(url: str) -> dict[str, Any]:
    return {"type": "external", "external": {"url": url.strip()}}


def enviada(upload_id: str) -> dict[str, Any]:
    return {"type": "file_upload", "file_upload": {"id": upload_id}}


def descrever(objeto: dict[str, Any] | None) -> str | None:
    """Resumo legível do ``icon``/``cover`` atual de uma página (``None`` se não tem)."""

    if not objeto:
        return None
    tipo = objeto.get("type")
    if tipo == "emoji":
        return str(objeto.get("emoji"))
    if tipo == "external":
        return str((objeto.get("external") or {}).get("url"))
    if tipo in ("file", "file_upload", "custom_emoji"):
        return f"({tipo})"
    return f"({tipo})"
