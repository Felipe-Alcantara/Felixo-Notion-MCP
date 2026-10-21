"""Ler o schema real de um database antes de escrever nele.

Sem isto, descobrir o nome exato de uma coluna, os valores aceitos por um
select ou se uma relação é de mão única exigia chamar a API do Notion na mão —
que é exatamente o passo que se pula quando se está com pressa, e o erro só
aparece depois, gravado.
"""

from __future__ import annotations

from felixo_notion_mcp import descrever_database


def _database() -> dict:
    return {
        "id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
        "title": [{"plain_text": "Tarefas — "}, {"plain_text": "HOME"}],
        "properties": {
            "Prioridade": {
                "type": "select",
                "select": {"options": [{"name": "Baixa"}, {"name": "Alta"}]},
            },
            "Tarefa": {"type": "title"},
            "Subtarefas relacionadas": {
                "type": "relation",
                "relation": {
                    "database_id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
                    "type": "single_property",
                    "single_property": {},
                },
            },
            "Projeto": {
                "type": "relation",
                "relation": {
                    "database_id": "38e91f95-497e-818b-ab08-ff19918d6c7c",
                    "type": "dual_property",
                    "dual_property": {"synced_property_name": "Tarefas"},
                },
            },
            "Finalização": {"type": "last_edited_time"},
            "Etapa": {
                "type": "status",
                "status": {"options": [{"name": "Entrada"}, {"name": "Concluída"}]},
            },
        },
    }


def test_titulo_vem_concatenado_do_rich_text():
    assert descrever_database(_database()).titulo == "Tarefas — HOME"


def test_database_sem_titulo_nao_devolve_string_vazia():
    assert descrever_database({"id": "x", "properties": {}}).titulo == "(sem título)"


def test_coluna_de_titulo_vem_primeiro_e_o_resto_em_ordem_alfabetica():
    """Ordem estável: a mesma entrada sai sempre igual, e o título lidera."""

    nomes = [coluna.nome for coluna in descrever_database(_database()).colunas]

    assert nomes[0] == "Tarefa"
    assert nomes[1:] == [
        "Etapa",
        "Finalização",
        "Prioridade",
        "Projeto",
        "Subtarefas relacionadas",
    ]


def test_opcoes_de_select_e_status_sao_expostas():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}

    assert colunas["Prioridade"].opcoes == ("Baixa", "Alta")
    assert colunas["Etapa"].opcoes == ("Entrada", "Concluída")


def test_tipo_calculado_pelo_notion_e_marcado_como_nao_editavel():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}

    assert colunas["Finalização"].editavel is False
    assert colunas["Tarefa"].editavel is True
    assert "Finalização" not in {c.nome for c in descrever_database(_database()).editaveis}


def test_relacao_de_mao_unica_e_identificada_e_avisada():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}
    relacao = colunas["Subtarefas relacionadas"].relacao

    assert relacao is not None
    assert relacao.bidirecional is False
    assert relacao.auto_referente is True
    assert "single_property" in (relacao.aviso or "")


def test_aviso_da_auto_referente_de_mao_unica_diz_que_ela_e_simetrica():
    # Medido em 2026-10-21: gravar só A.Subtarefas = [B] fez B.Subtarefas trazer A.
    from felixo_notion_mcp.domain.schema import Relacao

    aviso = Relacao(database_id="db", bidirecional=False, auto_referente=True).aviso or ""

    assert "single_property" in aviso
    assert "mesma coluna" in aviso and "hierarquia" in aviso and "mão dupla" in aviso


def test_aviso_da_mao_unica_para_outro_database_diz_que_nao_ha_volta():
    from felixo_notion_mcp.domain.schema import Relacao

    aviso = Relacao(database_id="outro", bidirecional=False, auto_referente=False).aviso or ""

    assert "single_property" in aviso and "não há coluna de volta" in aviso


def test_relacao_bidirecional_nao_gera_aviso():
    colunas = {c.nome: c for c in descrever_database(_database()).colunas}
    relacao = colunas["Projeto"].relacao

    assert relacao is not None
    assert relacao.bidirecional is True
    assert relacao.coluna_espelho == "Tarefas"
    assert relacao.auto_referente is False
    assert relacao.aviso is None


def test_avisos_do_database_listam_so_o_que_exige_acao():
    avisos = descrever_database(_database()).avisos

    assert len(avisos) == 1
    assert avisos[0].startswith("Subtarefas relacionadas:")


def test_auto_referencia_ignora_hifens_do_id():
    """A API aceita o ID com e sem hífen; comparar cru daria falso negativo."""

    database = {
        "id": "30296e2dcd394cf38bbd3fb2f53c0195",
        "properties": {
            "Sub": {
                "type": "relation",
                "relation": {
                    "database_id": "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195",
                    "type": "single_property",
                },
            }
        },
    }

    relacao = descrever_database(database).colunas[0].relacao

    assert relacao is not None and relacao.auto_referente is True


def test_para_dict_serializa_opcoes_relacao_e_avisos():
    dados = descrever_database(_database()).para_dict()
    por_nome = {coluna["nome"]: coluna for coluna in dados["colunas"]}

    assert por_nome["Prioridade"]["opcoes"] == ["Baixa", "Alta"]
    assert por_nome["Projeto"]["relacao"]["bidirecional"] is True
    assert "opcoes" not in por_nome["Tarefa"]
    assert len(dados["avisos"]) == 1


# -- problemas_de_valores ------------------------------------------------------

COLUNAS_VALORES = {
    "Nome": {"nome": "Nome", "tipo": "title", "editavel": True, "titulo": True},
    "Etapa": {"nome": "Etapa", "tipo": "status", "editavel": True, "opcoes": ["Entrada"]},
    "Tipo": {"nome": "Tipo", "tipo": "multi_select", "editavel": True, "opcoes": ["Feature"]},
    "Horas": {"nome": "Horas", "tipo": "number", "editavel": True},
    "ID": {"nome": "ID", "tipo": "unique_id", "editavel": False},
    "Notas": {"nome": "Notas", "tipo": "rich_text", "editavel": True},
}


def test_problemas_de_valores_aceita_valores_do_schema():
    from felixo_notion_mcp.domain.schema import problemas_de_valores

    valores = {"Etapa": "Entrada", "Tipo": ["Feature"], "Horas": 2, "Notas": "x"}

    assert problemas_de_valores(valores, COLUNAS_VALORES) == []


def test_problemas_de_valores_aponta_cada_valor_que_a_api_recusaria():
    from felixo_notion_mcp.domain.schema import problemas_de_valores

    problemas = " | ".join(
        problemas_de_valores(
            {
                "Etapa": "Feito",
                "Tipo": "Feature",
                "Horas": "duas",
                "ID": "X-1",
                "Nome": "título por aqui não",
                "Sumida": "x",
            },
            COLUNAS_VALORES,
        )
    )

    assert "'Feito' não é opção de 'Etapa'" in problemas
    assert "'Tipo' é multi_select e pede uma lista" in problemas
    assert "'Horas' é number" in problemas
    assert "'ID' não aceita escrita" in problemas
    assert "'Nome' não aceita escrita" in problemas
    assert "coluna inexistente 'Sumida'" in problemas


def test_problemas_de_valores_libera_opcoes_extras_e_colunas_livres_mas_nao_virgula():
    from felixo_notion_mcp.domain.schema import problemas_de_valores

    assert problemas_de_valores(
        {"Etapa": "Nova"}, COLUNAS_VALORES, opcoes_extras={"Etapa": {"Nova"}}
    ) == []
    assert problemas_de_valores({"Tipo": ["Qualquer"]}, COLUNAS_VALORES, livres=["Tipo"]) == []
    assert any(
        "vírgula" in p
        for p in problemas_de_valores({"Tipo": ["A, B"]}, COLUNAS_VALORES, livres=["Tipo"])
    )
    (problema,) = problemas_de_valores({"Etapa": "X"}, COLUNAS_VALORES, dica_opcao=" (dica)")
    assert problema.endswith(" (dica)")
