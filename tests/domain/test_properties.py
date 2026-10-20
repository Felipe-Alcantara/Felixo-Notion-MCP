from __future__ import annotations

from datetime import date, datetime

from felixo_notion_mcp.domain import properties as p


def test_title():
    assert p.title("Oi") == {"title": [{"text": {"content": "Oi"}}]}


def test_rich_text():
    assert p.rich_text("corpo") == {"rich_text": [{"text": {"content": "corpo"}}]}


def test_rich_text_fatia_texto_acima_de_2000():
    valor = "a" * 4500
    itens = p.rich_text(valor)["rich_text"]
    assert len(itens) == 3  # 2000 + 2000 + 500
    assert [len(i["text"]["content"]) for i in itens] == [2000, 2000, 500]
    assert "".join(i["text"]["content"] for i in itens) == valor


def test_title_fatia_texto_longo():
    itens = p.title("b" * 2001)["title"]
    assert [len(i["text"]["content"]) for i in itens] == [2000, 1]


def test_texto_vazio_gera_item_unico_vazio():
    assert p.title("") == {"title": [{"text": {"content": ""}}]}
    assert p.rich_text("") == {"rich_text": [{"text": {"content": ""}}]}


def test_emoji_conta_como_duas_unidades_utf16():
    # 1000 emojis fora do BMP = 2000 unidades UTF-16 → cabe em um item; +1 estoura.
    itens = p.rich_text("😀" * 1001)["rich_text"]
    assert len(itens) == 2


def test_email_phone_url_number_checkbox():
    assert p.email("a@b.com") == {"email": "a@b.com"}
    assert p.phone_number("+55 11") == {"phone_number": "+55 11"}
    assert p.url("https://x.y") == {"url": "https://x.y"}
    assert p.number(3) == {"number": 3}
    assert p.checkbox(True) == {"checkbox": True}


def test_select_status_multi_select():
    assert p.select("A") == {"select": {"name": "A"}}
    assert p.status("Concluído") == {"status": {"name": "Concluído"}}
    assert p.multi_select(["x", "y"]) == {"multi_select": [{"name": "x"}, {"name": "y"}]}


def test_relation():
    assert p.relation(["id-1", "id-2"]) == {"relation": [{"id": "id-1"}, {"id": "id-2"}]}
    assert p.relation([]) == {"relation": []}


def test_date_com_string():
    assert p.date("2026-06-24") == {"date": {"start": "2026-06-24"}}


def test_date_com_date_e_intervalo():
    resultado = p.date(date(2026, 6, 24), datetime(2026, 6, 25, 10, 0))
    assert resultado["date"]["start"] == "2026-06-24"
    assert resultado["date"]["end"].startswith("2026-06-25T10:00")


def test_arquivo_enviado_monta_files_com_upload():
    from felixo_notion_mcp.domain import properties as p

    valor = p.arquivo_enviado("upload42", "relatorio.docx")
    assert valor["files"][0]["type"] == "file_upload"
    assert valor["files"][0]["file_upload"]["id"] == "upload42"
    assert valor["files"][0]["name"] == "relatorio.docx"


def test_schema_propriedade_monta_fragmentos():
    from felixo_notion_mcp.domain import properties as p

    assert p.schema_propriedade("titulo") == {"title": {}}
    assert p.schema_propriedade("numero") == {"number": {}}
    assert p.schema_propriedade("Texto") == {"rich_text": {}}
    assert p.schema_propriedade("telefone") == {"phone_number": {}}


def test_schema_propriedade_select_com_opcoes_mantem_ordem():
    from felixo_notion_mcp.domain import properties as p

    assert p.schema_propriedade("select: Alta, Média ,Baixa,Alta") == {
        "select": {"options": [{"name": "Alta"}, {"name": "Média"}, {"name": "Baixa"}]}
    }
    assert p.schema_propriedade("multi_select:A,B") == {
        "multi_select": {"options": [{"name": "A"}, {"name": "B"}]}
    }


def test_schema_propriedade_soma_opcoes_do_tipo_e_da_lista():
    from felixo_notion_mcp.domain import properties as p

    assert p.schema_propriedade("select:A", opcoes=["B", "A"]) == {
        "select": {"options": [{"name": "A"}, {"name": "B"}]}
    }


def test_schema_propriedade_opcoes_em_tipo_errado_ou_vazias_levanta():
    import pytest

    from felixo_notion_mcp.domain import properties as p

    with pytest.raises(ValueError, match="Opções só se aplicam"):
        p.schema_propriedade("numero:1,2")
    with pytest.raises(ValueError, match="nenhuma foi informada"):
        p.schema_propriedade("select: , ")


def test_schema_propriedade_tipo_invalido_levanta():
    import pytest

    from felixo_notion_mcp.domain import properties as p

    with pytest.raises(ValueError, match="Tipos aceitos"):
        p.schema_propriedade("moeda")


def test_schema_propriedade_devolve_copia_independente():
    from felixo_notion_mcp.domain import properties as p

    a = p.schema_propriedade("select")
    a["select"]["options"] = [1]
    assert p.schema_propriedade("select") == {"select": {}}


def test_schema_propriedade_relacao_monta_dual_property():
    from felixo_notion_mcp.domain import properties as p

    assert p.schema_propriedade("relacao", relacionar_com=" db-alvo ") == {
        "relation": {"database_id": "db-alvo", "type": "dual_property", "dual_property": {}}
    }


def test_schema_propriedade_relacao_sem_alvo_levanta():
    import pytest

    from felixo_notion_mcp.domain import properties as p

    with pytest.raises(ValueError, match="relacionar_com"):
        p.schema_propriedade("relacao")


def test_schema_propriedade_alvo_em_tipo_nao_relacional_levanta():
    import pytest

    from felixo_notion_mcp.domain import properties as p

    with pytest.raises(ValueError, match="só se aplica ao tipo 'relacao'"):
        p.schema_propriedade("select", relacionar_com="db-alvo")
