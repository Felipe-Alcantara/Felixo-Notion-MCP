"""Testes do download com cache, limite de tamanho e retentativa."""

from __future__ import annotations

import pytest
import responses

from felixo_notion_mcp.services import downloads


@responses.activate
def test_baixa_uma_vez_e_depois_usa_o_cache(tmp_path):
    responses.get("https://x.dev/a.png", body=b"123", content_type="image/png")
    primeiro = downloads.baixar("https://x.dev/a.png", tmp_path)
    segundo = downloads.baixar("https://x.dev/a.png", tmp_path)
    assert primeiro.caminho.read_bytes() == b"123"
    assert not primeiro.do_cache and segundo.do_cache
    assert len(responses.calls) == 1


@responses.activate
def test_para_no_limite_sem_guardar_o_pedaco(tmp_path):
    responses.get("https://x.dev/grande", body=b"x" * 1000)
    with pytest.raises(downloads.DownloadErro, match="passa de 100 bytes"):
        downloads.baixar("https://x.dev/grande", tmp_path, limite_bytes=100)
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_tenta_de_novo_e_desiste_com_erro_legivel(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads.time, "sleep", lambda _s: None)
    responses.get("https://x.dev/falha", status=503)
    responses.get("https://x.dev/falha", status=503)
    responses.get("https://x.dev/falha", body=b"ok")
    assert downloads.baixar("https://x.dev/falha", tmp_path).caminho.read_bytes() == b"ok"
    responses.get("https://x.dev/sempre", status=404)
    with pytest.raises(downloads.DownloadErro):
        downloads.baixar("https://x.dev/sempre", tmp_path, tentativas=2)
