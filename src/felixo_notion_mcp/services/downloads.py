"""Caso de uso: baixar arquivos da web com cache, retentativa e limite de tamanho.

Usado pela coleta de artigos, pela redução de imagens dos PDFs e por quem precisa
de uma cópia local de um recurso remoto. O cache é por URL (hash), então baixar de
novo a mesma coisa não vai à rede. Usa ``requests``, que traz os certificados do
``certifi`` — com ``urllib`` puro, o Python gerenciado pelo uv falha em algumas CDNs.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import requests

AGENTE = "Mozilla/5.0 (felixo-notion-mcp; leitura offline)"


class DownloadErro(RuntimeError):
    """O recurso não pôde ser baixado (rede, HTTP ou tamanho acima do limite)."""


@dataclass(frozen=True)
class Baixado:
    url: str
    caminho: Path
    tamanho: int
    tipo: str
    do_cache: bool


def nome_no_cache(url: str, extensao: str = "") -> str:
    """Nome estável do arquivo no cache para ``url`` (hash + extensão opcional)."""

    return hashlib.sha256(url.encode()).hexdigest()[:24] + extensao


def baixar(
    url: str,
    pasta: Path,
    *,
    nome: str | None = None,
    limite_bytes: int | None = None,
    tentativas: int = 3,
    timeout: float = 60,
    sessao: requests.Session | None = None,
) -> Baixado:
    """Baixa ``url`` para ``pasta`` (ou reaproveita a cópia que já está lá).

    Raises:
        DownloadErro: falha de rede/HTTP depois das tentativas, ou arquivo maior que
            ``limite_bytes`` (o download para no limite, sem guardar o pedaço).
    """

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / (nome or nome_no_cache(url))
    if destino.is_file() and destino.stat().st_size > 0:
        return Baixado(url, destino, destino.stat().st_size, "", True)

    cliente = sessao or requests
    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            with cliente.get(
                url, stream=True, timeout=timeout, headers={"User-Agent": AGENTE}
            ) as resposta:
                resposta.raise_for_status()
                parcial = destino.with_suffix(destino.suffix + ".parcial")
                total = 0
                with parcial.open("wb") as saida:
                    for pedaco in resposta.iter_content(64 * 1024):
                        total += len(pedaco)
                        if limite_bytes is not None and total > limite_bytes:
                            saida.close()
                            parcial.unlink(missing_ok=True)
                            raise DownloadErro(f"{url}: passa de {limite_bytes} bytes")
                        saida.write(pedaco)
                parcial.replace(destino)
                return Baixado(url, destino, total, resposta.headers.get("content-type", ""), False)
        except DownloadErro:
            raise
        except requests.RequestException as erro:
            ultimo = erro
            if tentativa < tentativas:
                time.sleep(min(2**tentativa, 10))
    raise DownloadErro(f"{url}: {ultimo}") from ultimo


def baixar_texto(url: str, *, timeout: float = 60, sessao: requests.Session | None = None) -> str:
    """Baixa uma página ou feed como texto (sem cache), decodificando como o servidor diz."""

    cliente = sessao or requests
    try:
        resposta = cliente.get(url, timeout=timeout, headers={"User-Agent": AGENTE})
        resposta.raise_for_status()
    except requests.RequestException as erro:
        raise DownloadErro(f"{url}: {erro}") from erro
    resposta.encoding = resposta.encoding or resposta.apparent_encoding
    return resposta.text
