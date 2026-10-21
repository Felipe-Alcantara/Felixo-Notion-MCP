"""Testes de ``services.registro_diario``: estimar, aplicar sem sobrescrever e garantir o dia."""

from __future__ import annotations

from datetime import date

import pytest

from felixo_notion_mcp.integrations.github import CommitRemoto
from felixo_notion_mcp.services import registro_diario as svc


def _commit(quando: str, repo: str = "Felipe-Alcantara/Felixo-Notion-MCP") -> CommitRemoto:
    return CommitRemoto(repositorio=repo, sha="abc1234", quando=quando, mensagem="feat: x")


def test_estimar_combina_relatorio_e_commits_por_area_e_calcula_sono():
    relatorios = {
        date(2026, 10, 16): ["Meu Blog — 20:28–22:53 (2h 25)"],
        date(2026, 10, 17): [
            "Meu Blog — 11:22–11:28 (6 min)",
            "MEM (MeuEcoo-Midia) — 12:44–14:20 (1h 36)",
        ],
    }

    (dia,) = svc.estimar_dias(
        [date(2026, 10, 17)], commits=[], relatorios=relatorios, trabalho=["MeuEcoo"]
    )

    assert dia.trabalho_h == 1.6
    assert dia.pessoal_h == 0.1
    assert dia.acordei == "10:20"
    assert dia.sono_h == 10.9
    assert dia.produtividade == "Baixa"
    assert dia.propriedades()["Projetos pessoais"] == "Sim"


def test_estimar_so_com_commits_e_madrugada_sem_hora_de_acordar():
    commits = [_commit(f"2026-10-20T{h}:00-03:00") for h in ("00", "01", "02", "03")]
    commits.append(_commit("2026-10-20T10:48:00-03:00", repo="AndreGustavoms/crm-solar-prototipo"))

    (dia,) = svc.estimar_dias(
        [date(2026, 10, 20)], commits=commits, relatorios={}, trabalho=["crm-solar"]
    )

    assert dia.pessoal_h == 3.5
    assert dia.trabalho_h == 0.5
    assert dia.acordei is None
    assert "Acordei às" not in dia.propriedades()
    assert any("madrugada" in c for c in dia.criterios)


def test_area_de_trabalho_ignora_espacos_e_hifens():
    relatorios = {date(2026, 10, 16): ["Meu Ecoo Midia — 16:40–16:47 (7 min)"]}

    (dia,) = svc.estimar_dias(
        [date(2026, 10, 16)], commits=[], relatorios=relatorios, trabalho=["MeuEcoo"]
    )

    assert dia.trabalho_h == 0.1
    assert dia.pessoal_h is None


def test_dia_sem_rastro_nao_inventa_nada():
    (dia,) = svc.estimar_dias([date(2026, 10, 18)], commits=[], relatorios={}, trabalho=[])

    assert dia.propriedades() == {}


class ClienteFalso:
    def __init__(self, linhas=None):
        self.linhas = linhas or {}
        self.criadas = []
        self.patches = []

    def resolver_data_source(self, database_id):
        return "ds"

    def consultar_data_source(self, fonte, filtro=None, buscar_todos=False, page_size=100):
        iso = filtro["date"]["equals"]
        return [self.linhas[iso]] if iso in self.linhas else []

    def criar_pagina_em_fonte(self, fonte, propriedades):
        self.criadas.append(propriedades)
        return {"id": "nova"}


def test_aplicar_preserva_o_que_a_pessoa_informou(monkeypatch):
    linha = {
        "id": "p20",
        "properties": {
            "Acordei às": {"type": "rich_text", "rich_text": [{"plain_text": "08:20"}]},
            "Trabalho (h)": {"type": "number", "number": None},
        },
    }
    cliente = ClienteFalso({"2026-10-20": linha})
    gravado = {}
    monkeypatch.setattr(
        "felixo_notion_mcp.services.propriedades.editar_linha",
        lambda page_id, valores, cliente=None: gravado.update({page_id: valores}),
    )
    estimativa = svc.Estimativa(
        dia=date(2026, 10, 20), trabalho_h=0.5, pessoal_h=None, acordei="07:00",
        sono_h=None, produtividade="Baixa",
    )

    (acao,) = svc.aplicar_estimativas("db", [estimativa], cliente=cliente)

    assert gravado == {"p20": {"Trabalho (h)": "0.5", "Produtividade": "Baixa"}}
    assert acao["mantidas"] == ["Acordei às"]


def test_aplicar_em_dia_sem_linha_nao_cria():
    estimativa = svc.Estimativa(
        dia=date(2026, 10, 18), trabalho_h=1.0, pessoal_h=None, acordei=None,
        sono_h=None, produtividade="Baixa",
    )

    (acao,) = svc.aplicar_estimativas("db", [estimativa], cliente=ClienteFalso())

    assert acao == {"dia": "2026-10-18", "acao": "sem_linha"}


def test_garantir_dia_nao_duplica(monkeypatch):
    cliente = ClienteFalso({"2026-10-16": {"id": "existente", "properties": {}}})

    resultado = svc.garantir_dia("db", date(2026, 10, 16), cliente=cliente)

    assert resultado == {"dia": "2026-10-16", "page_id": "existente", "criado": False}
    assert cliente.criadas == []


def test_garantir_dia_cria_com_titulo_data_status_e_corpo(monkeypatch):
    cliente = ClienteFalso()
    chamadas = []
    monkeypatch.setattr(
        "felixo_notion_mcp.services.propriedades.editar_linha",
        lambda page_id, valores, cliente=None: chamadas.append(("props", valores)),
    )
    monkeypatch.setattr(
        "felixo_notion_mcp.services.conteudo.escrever_conteudo",
        lambda page_id, md, cliente=None: chamadas.append(("corpo", md)),
    )

    resultado = svc.garantir_dia(
        "db", date(2026, 10, 20), conteudo="## Tarefas de trabalho", cliente=cliente
    )

    assert resultado["criado"] is True
    titulo = cliente.criadas[0]["Dia"]["title"][0]["text"]["content"]
    assert titulo == "20-10-2026"
    assert cliente.criadas[0]["Data"] == {"date": {"start": "2026-10-20"}}
    # Propriedades antes do corpo.
    assert chamadas == [("props", {"Status do dia": "Aberto"}), ("corpo", "## Tarefas de trabalho")]


def test_garantir_dia_sem_corpo_usa_o_modelo_dia_padrao(monkeypatch):
    corpos = []
    monkeypatch.setattr(
        "felixo_notion_mcp.services.propriedades.editar_linha", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "felixo_notion_mcp.services.conteudo.escrever_conteudo",
        lambda page_id, md, cliente=None: corpos.append(md),
    )

    svc.garantir_dia("db", date(2026, 10, 21), cliente=ClienteFalso())

    assert corpos == [svc.CORPO_DIA_PADRAO]
    assert "## Tarefas de trabalho" in corpos[0] and "## Resumo do dia" in corpos[0]


# -- levar_pendencias ----------------------------------------------------------


def _rico(texto):
    return {"rich_text": [{"type": "text", "text": {"content": texto}, "plain_text": texto}]}


def _lido(tipo, texto, *filhos, **extra):
    return {"type": tipo, tipo: {**_rico(texto), **extra}, "_filhos": list(filhos)}


def _dia_lido():
    """Corpo de um dia como a leitura recursiva devolve."""

    return [
        _lido("heading_2", "Tarefas de trabalho"),
        _lido("heading_3", "Repo"),
        _lido("to_do", "Feita", checked=True),
        _lido(
            "to_do",
            "Aberta",
            _lido("to_do", "Passo feito", checked=True),
            _lido("to_do", "Passo aberto", checked=False),
            checked=False,
        ),
        _lido("heading_2", "Anotações do dia"),
        _lido("bulleted_list_item", "Fontes: de ontem"),
    ]


class ClienteDias:
    """Linhas do Registro diário por data ISO e o corpo de cada página."""

    def __init__(self, linhas=None, corpos=None):
        self.linhas = {
            iso: {"id": pid, "properties": {"Data": {"type": "date", "date": {"start": iso}}}}
            for iso, pid in (linhas or {}).items()
        }
        self.corpos = corpos or {}
        self.criadas = []
        self.lidas = []
        self.arquivadas = []

    def resolver_data_source(self, database_id):
        return "ds"

    def consultar_data_source(self, fonte, filtro=None, buscar_todos=False, page_size=100):
        condicao = filtro["date"]
        if "equals" in condicao:
            iso = condicao["equals"]
            return [self.linhas[iso]] if iso in self.linhas else []
        return [linha for iso, linha in self.linhas.items() if iso < condicao["before"]]

    def criar_pagina_em_fonte(self, fonte, propriedades):
        self.criadas.append(propriedades)
        return {"id": "nova"}

    def ler_blocos(self, block_id, buscar_todos=False, recursivo=False):
        self.lidas.append(block_id)
        return self.corpos.get(block_id, [])

    def arquivar_pagina(self, page_id):
        self.arquivadas.append(page_id)
        return {"id": page_id, "in_trash": True}


def _registrar_escritas(monkeypatch, chamadas, *, falhar_na_copia=False):
    from felixo_notion_mcp.core.exceptions import NotionSyncError
    from felixo_notion_mcp.services.copia_corpo import ResultadoCopia

    def copiar(blocos, destino_id, cliente=None):
        if falhar_na_copia:
            raise NotionSyncError("falha simulada")
        titulos = [b[b["type"]]["rich_text"][0]["plain_text"] for b in blocos]
        chamadas.append(("blocos", destino_id, titulos))
        return ResultadoCopia(origem="", destino=destino_id, blocos_de_topo=len(blocos))

    monkeypatch.setattr(
        "felixo_notion_mcp.services.propriedades.editar_linha",
        lambda page_id, valores, cliente=None: chamadas.append(("props", valores)),
    )
    monkeypatch.setattr("felixo_notion_mcp.services.copia_corpo.copiar_blocos", copiar)
    monkeypatch.setattr(
        "felixo_notion_mcp.services.conteudo.escrever_conteudo",
        lambda page_id, md, cliente=None: chamadas.append(("corpo", md)),
    )


def test_levar_pendencias_cria_o_dia_com_o_que_ficou_aberto_no_dia_anterior(monkeypatch):
    cliente = ClienteDias(
        {"2026-10-17": "p17", "2026-10-20": "p20"}, corpos={"p20": _dia_lido()}
    )
    chamadas = []
    _registrar_escritas(monkeypatch, chamadas)

    resultado = svc.levar_pendencias(
        "db", date(2026, 10, 21), valores={"Banho": "Não"}, cliente=cliente
    )

    assert resultado["criado"] is True
    assert resultado["origem"] == "p20"  # o último dia antes, não o primeiro
    assert resultado["tarefas_levadas"] == ["Aberta"]
    assert cliente.criadas[0]["Dia"]["title"][0]["text"]["content"] == "21-10-2026"
    # Propriedades, depois as pendências bloco a bloco, depois anotações e resumo.
    assert chamadas == [
        ("props", {"Status do dia": "Aberto", "Banho": "Não"}),
        ("blocos", "nova", ["Tarefas de trabalho", "Repo", "Aberta"]),
        ("corpo", svc.FECHO_DIA_PADRAO),
    ]


def test_levar_pendencias_usa_a_origem_informada_e_o_fecho_dado(monkeypatch):
    cliente = ClienteDias({"2026-10-20": "p20"}, corpos={"outra": _dia_lido()})
    chamadas = []
    _registrar_escritas(monkeypatch, chamadas)

    resultado = svc.levar_pendencias(
        "db", date(2026, 10, 21), origem_id="outra", fecho="## Anotações do dia\n\n- x",
        cliente=cliente,
    )

    assert resultado["origem"] == "outra"
    assert cliente.lidas == ["outra"]
    assert chamadas[-1] == ("corpo", "## Anotações do dia\n\n- x")


def test_levar_pendencias_nao_mexe_em_dia_que_ja_existe(monkeypatch):
    cliente = ClienteDias({"2026-10-20": "p20", "2026-10-21": "p21"}, corpos={"p20": _dia_lido()})
    chamadas = []
    _registrar_escritas(monkeypatch, chamadas)

    resultado = svc.levar_pendencias("db", date(2026, 10, 21), cliente=cliente)

    assert resultado == {"dia": "2026-10-21", "page_id": "p21", "criado": False}
    assert cliente.criadas == [] and chamadas == []


def test_levar_pendencias_dry_run_mostra_a_previa_sem_escrever(monkeypatch):
    cliente = ClienteDias({"2026-10-20": "p20"}, corpos={"p20": _dia_lido()})
    chamadas = []
    _registrar_escritas(monkeypatch, chamadas)

    resultado = svc.levar_pendencias("db", date(2026, 10, 21), dry_run=True, cliente=cliente)

    assert resultado["dry_run"] is True and resultado["criado"] is False
    assert "Aberta" in resultado["previa"] and "Passo feito" in resultado["previa"]
    assert "Feita" not in resultado["previa"].replace("Passo feito", "")
    assert "## Resumo do dia" in resultado["previa"]
    assert cliente.criadas == [] and chamadas == []


def test_levar_pendencias_sem_dia_anterior_pede_a_origem(monkeypatch):
    cliente = ClienteDias({"2026-10-22": "p22"})
    _registrar_escritas(monkeypatch, [])

    with pytest.raises(ValueError, match="origem"):
        svc.levar_pendencias("db", date(2026, 10, 21), cliente=cliente)
    assert cliente.criadas == []


def test_levar_pendencias_recusa_origem_fora_do_modelo(monkeypatch):
    cliente = ClienteDias(
        {"2026-10-20": "p20"}, corpos={"p20": [_lido("paragraph", "texto solto")]}
    )
    _registrar_escritas(monkeypatch, [])

    with pytest.raises(ValueError, match="Tarefas de trabalho"):
        svc.levar_pendencias("db", date(2026, 10, 21), cliente=cliente)
    assert cliente.criadas == []


def test_levar_pendencias_manda_a_linha_nova_para_a_lixeira_se_a_copia_falha(monkeypatch):
    from felixo_notion_mcp.core.exceptions import NotionSyncError

    cliente = ClienteDias({"2026-10-20": "p20"}, corpos={"p20": _dia_lido()})
    _registrar_escritas(monkeypatch, [], falhar_na_copia=True)

    with pytest.raises(NotionSyncError):
        svc.levar_pendencias("db", date(2026, 10, 21), cliente=cliente)
    # Sem a linha pela metade, repetir o comando cria o dia de novo.
    assert cliente.arquivadas == ["nova"]
