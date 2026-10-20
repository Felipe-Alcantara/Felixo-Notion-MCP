"""Testes do caso de uso que define ícone e capa sem apagar o que já existe."""

from __future__ import annotations

import pytest

from felixo_notion_mcp.services.aparencia import definir_aparencia


class ClienteFake:
    def __init__(self, pagina=None):
        self._pagina = pagina or {"icon": None, "cover": None}
        self.uploads = []
        self.aparencias = []
        self.leituras = 0

    def obter_pagina(self, page_id):
        self.leituras += 1
        return self._pagina

    def enviar_arquivo(self, conteudo, nome, content_type):
        self.uploads.append((nome, content_type, len(conteudo)))
        return f"upload-{len(self.uploads)}"

    def atualizar_aparencia(self, page_id, *, icone=None, capa=None):
        self.aparencias.append((page_id, icone, capa))
        return {"id": page_id}


def test_grava_emoji_e_capa_externa_numa_pagina_sem_nada():
    cliente = ClienteFake()
    resultado = definir_aparencia("p1", icone="📘", capa="https://x/c.jpg", cliente=cliente)
    capa = {"type": "external", "external": {"url": "https://x/c.jpg"}}
    assert cliente.aparencias == [("p1", {"type": "emoji", "emoji": "📘"}, capa)]
    assert resultado["icone"] == resultado["capa"] == "gravado"


def test_arquivo_local_sobe_pela_file_upload_api(tmp_path):
    imagem = tmp_path / "capa.png"
    imagem.write_bytes(b"\x89PNG")
    cliente = ClienteFake()
    definir_aparencia("p1", capa=str(imagem), cliente=cliente)
    assert cliente.uploads == [("capa.png", "image/png", 4)]
    enviada = {"type": "file_upload", "file_upload": {"id": "upload-1"}}
    assert cliente.aparencias == [("p1", None, enviada)]


def test_mantem_icone_e_capa_que_ja_existem():
    pagina = {
        "icon": {"type": "emoji", "emoji": "🎧"},
        "cover": {"type": "external", "external": {"url": "https://antiga"}},
    }
    cliente = ClienteFake(pagina)
    resultado = definir_aparencia("p1", icone="📘", capa="https://nova", cliente=cliente)
    assert cliente.aparencias == []
    assert resultado["icone"] == resultado["capa"] == "mantido"
    assert resultado["icone_anterior"] == "🎧"
    assert resultado["capa_anterior"] == "https://antiga"


def test_mantem_so_o_que_existe_e_grava_o_que_falta():
    cliente = ClienteFake({"icon": {"type": "emoji", "emoji": "🎧"}, "cover": None})
    resultado = definir_aparencia("p1", icone="📘", capa="https://nova", cliente=cliente)
    capa = {"type": "external", "external": {"url": "https://nova"}}
    assert cliente.aparencias == [("p1", None, capa)]
    assert (resultado["icone"], resultado["capa"]) == ("mantido", "gravado")


def test_substituir_troca_o_que_ja_existe():
    cliente = ClienteFake({"icon": {"type": "emoji", "emoji": "🎧"}, "cover": None})
    definir_aparencia("p1", icone="📘", substituir=True, cliente=cliente)
    assert cliente.aparencias == [("p1", {"type": "emoji", "emoji": "📘"}, None)]


def test_capa_com_emoji_e_recusada_antes_de_qualquer_requisicao():
    cliente = ClienteFake()
    with pytest.raises(ValueError, match="capa não aceita emoji"):
        definir_aparencia("p1", icone="https://x/i.png", capa="📘", cliente=cliente)
    assert cliente.leituras == 0
    assert cliente.uploads == []


def test_arquivo_inexistente_e_pedido_vazio_sao_recusados(tmp_path):
    with pytest.raises(ValueError, match="não encontrado"):
        definir_aparencia("p1", capa=str(tmp_path / "nao-existe.png"), cliente=ClienteFake())
    with pytest.raises(ValueError, match="Informe"):
        definir_aparencia("p1", cliente=ClienteFake())


def test_imagem_acima_do_limite_sobe_comprimida(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    import random

    from felixo_notion_mcp.services import aparencia as servico

    foto = tmp_path / "capa.png"
    r = random.Random(2)
    imagem = pil.new("RGB", (1200, 800))
    pixels = [(r.randrange(256), r.randrange(256), r.randrange(256)) for _ in range(1200 * 800)]
    imagem.putdata(pixels)
    imagem.save(foto)
    assert foto.stat().st_size > 200_000
    cliente = ClienteFake()
    objeto = servico._objeto(str(foto), cliente=cliente, campo="capa", limite_bytes=200_000)
    nome, tipo, tamanho = cliente.uploads[0]
    assert (nome, tipo) == ("capa.jpg", "image/jpeg")
    assert tamanho <= 200_000
    assert objeto["type"] == "file_upload"
