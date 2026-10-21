"""Testes de ``services.importacao_tarefas``: rascunhos viram tarefas sem duplicar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from felixo_notion_mcp.core.exceptions import LoteIncompletoError, NotionHTTPError
from felixo_notion_mcp.domain.rascunhos_de_tarefas import Rascunho, Relacao
from felixo_notion_mcp.services import importacao_tarefas as svc

DB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EXISTENTE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def _rel(tipo: str, espelho: str | None = None) -> dict:
    corpo = {"database_id": DB, "type": tipo, tipo: {}}
    if espelho:
        corpo[tipo] = {"synced_property_name": espelho}
    return {"type": "relation", "relation": corpo}


DATABASE = {
    "id": DB,
    "title": [{"plain_text": "Tarefas"}],
    "properties": {
        "Tarefa": {"type": "title", "title": {}},
        "Etapa": {
            "type": "status", "status": {"options": [{"name": "Entrada"}, {"name": "Feito"}]},
        },
        "Tipo": {"type": "multi_select", "multi_select": {"options": [{"name": "Feature"}]}},
        "Subtarefas relacionadas": _rel("single_property"),
        "Bloqueada por": _rel("dual_property", "Bloqueia"),
        "Bloqueia": _rel("dual_property", "Bloqueada por"),
    },
}


class Workspace:
    """Database de tarefas em memória: cliente Notion e serviços que o importador usa."""

    def __init__(self, existentes: dict[str, tuple[str, str]] | None = None) -> None:
        self.paginas: dict[str, dict] = {}
        self.criacoes: list[str] = []
        self.escritas: list[str] = []
        self.ligacoes: list[tuple[str, str, str]] = []
        self.falhar_criacao: set[str] = set()
        for page_id, (titulo, corpo) in (existentes or {}).items():
            self.paginas[page_id] = {"titulo": titulo, "props": {}, "corpo": corpo}

    # -- cliente -----------------------------------------------------------------

    def get_database(self, database_id):
        assert database_id == DB
        return DATABASE

    def criar_pagina(self, database_id, propriedades):
        titulo = propriedades["Tarefa"]["title"][0]["text"]["content"]
        if titulo in self.falhar_criacao:
            raise NotionHTTPError(500, '{"message":"falha simulada"}')
        page_id = f"00000000-0000-4000-8000-{len(self.paginas) + 1:012d}"
        props = {}
        for nome, valor in propriedades.items():
            if "status" in valor:
                props[nome] = valor["status"]["name"]
            elif "multi_select" in valor:
                props[nome] = [o["name"] for o in valor["multi_select"]]
        self.paginas[page_id] = {"titulo": titulo, "props": props, "corpo": ""}
        self.criacoes.append(titulo)
        return {"id": page_id}

    def obter_pagina(self, page_id):
        if page_id not in self.paginas:
            raise NotionHTTPError(404, '{"message":"não encontrada"}')
        pagina = self.paginas[page_id]
        props = {"Tarefa": {"type": "title", "title": [{"plain_text": pagina["titulo"]}]}}
        for nome, valor in pagina["props"].items():
            if nome == "Etapa":
                props[nome] = {"type": "status", "status": {"name": valor}}
            elif nome == "Tipo":
                props[nome] = {"type": "multi_select", "multi_select": [{"name": v} for v in valor]}
            else:
                props[nome] = {"type": "relation", "relation": [{"id": v} for v in valor]}
        return {"id": page_id, "properties": props}

    # -- serviços ----------------------------------------------------------------

    def listar_linhas(self, database_id, propriedades=False, cliente=None):
        return [{"id": pid, "titulo": p["titulo"], "url": ""} for pid, p in self.paginas.items()]

    def ler_conteudo(self, page_id, cliente=None):
        return self.paginas[page_id]["corpo"]

    def escrever_conteudo(self, page_id, markdown, cliente=None, **_):
        atual = self.paginas[page_id]["corpo"]
        self.paginas[page_id]["corpo"] = f"{atual}\n\n{markdown}" if atual else markdown
        self.escritas.append(page_id)

    def relacionar(self, page_a, page_b, coluna, cliente=None, **_):
        self.ligacoes.append((page_a, page_b, coluna))
        espelho = {"Bloqueada por": "Bloqueia", "Bloqueia": "Bloqueada por"}.get(coluna, coluna)
        for pid, col, outra in ((page_a, coluna, page_b), (page_b, espelho, page_a)):
            lista = self.paginas[pid]["props"].setdefault(col, [])
            if outra not in lista:
                lista.append(outra)
        return {}

    def titulo(self, titulo):
        return next(pid for pid, p in self.paginas.items() if p["titulo"] == titulo)


@pytest.fixture
def ws(monkeypatch):
    workspace = Workspace({EXISTENTE: ("Tarefa antiga", "## Contexto\n\nJá existia.")})
    for nome in ("listar_linhas", "ler_conteudo", "escrever_conteudo"):
        monkeypatch.setattr(f"felixo_notion_mcp.services.conteudo.{nome}", getattr(workspace, nome))
    monkeypatch.setattr("felixo_notion_mcp.services.relacoes.relacionar", workspace.relacionar)
    return workspace


def _lote() -> list[Rascunho]:
    return [
        Rascunho(
            chave="a",
            titulo="Projeto — Tarefa A",
            propriedades={"Etapa": "Entrada", "Tipo": ["Feature"]},
            corpo="## Contexto\n\nDepende de `chave:b`.",
            relacoes=[Relacao("chave:b", "Subtarefas relacionadas", "mesmo tema")],
        ),
        Rascunho(
            chave="b",
            titulo="Projeto — Tarefa B",
            propriedades={"Etapa": "Entrada"},
            corpo="## Contexto\n\nTexto de B.",
            relacoes=[Relacao(EXISTENTE, "Bloqueada por", "a antiga entrega a base")],
        ),
    ]


def test_importa_o_lote_com_corpo_ligacoes_e_secao_nas_duas_pontas(ws):
    resultado = svc.importar_tarefas(_lote(), DB, cliente=ws)

    a, b = ws.titulo("Projeto — Tarefa A"), ws.titulo("Projeto — Tarefa B")
    assert {c: t["acao"] for c, t in resultado["tarefas"].items()} == {"a": "criada", "b": "criada"}
    assert ws.paginas[a]["props"]["Etapa"] == "Entrada"
    # `chave:b` vira link para a tarefa B, que só tem ID depois de criada.
    assert f"[Projeto — Tarefa B](https://app.notion.com/p/{b.replace('-', '')})" in (
        ws.paginas[a]["corpo"]
    )
    assert sorted(ws.ligacoes) == sorted(
        [(a, b, "Subtarefas relacionadas"), (b, EXISTENTE, "Bloqueada por")]
    )
    # A tarefa que já existia também ganha a seção, com o rótulo da coluna espelho.
    assert "## Tarefas relacionadas" in ws.paginas[EXISTENTE]["corpo"]
    assert "**Bloqueia:** [Projeto — Tarefa B]" in ws.paginas[EXISTENTE]["corpo"]
    assert "**Bloqueada por:** [Tarefa antiga]" in ws.paginas[b]["corpo"]
    assert resultado["ligacoes"] == 2


def test_rodar_de_novo_nao_cria_nem_escreve_de_novo(ws):
    svc.importar_tarefas(_lote(), DB, cliente=ws)
    criacoes, escritas = list(ws.criacoes), list(ws.escritas)

    resultado = svc.importar_tarefas(_lote(), DB, cliente=ws)

    assert ws.criacoes == criacoes and ws.escritas == escritas
    assert {t["acao"] for t in resultado["tarefas"].values()} == {"existente"}


def test_lote_invalido_nao_escreve_nada(ws):
    lote = _lote()
    lote[0].propriedades["Etapa"] = "Inventada"

    with pytest.raises(ValueError, match="'Inventada' não é opção de 'Etapa'"):
        svc.importar_tarefas(lote, DB, cliente=ws)
    assert ws.criacoes == []


def test_tarefa_existente_citada_que_nao_responde_para_antes_de_escrever(ws):
    lote = _lote()
    sumida = "99999999-9999-4999-8999-999999999999"
    lote[1].relacoes = [Relacao(sumida, "Bloqueada por", "x")]

    with pytest.raises(ValueError, match=sumida):
        svc.importar_tarefas(lote, DB, cliente=ws)
    assert ws.criacoes == []


def test_dry_run_mostra_o_plano_e_as_chaves_sem_destino_sem_escrever(ws):
    lote = _lote()
    lote[1].corpo += "\n\nVer `chave:sumida`."
    ws.paginas["ja-existe"] = {"titulo": "Projeto — Tarefa A", "props": {}, "corpo": "x"}

    resultado = svc.importar_tarefas(lote, DB, dry_run=True, cliente=ws)

    assert {c: t["acao"] for c, t in resultado["tarefas"].items()} == {
        "a": "existente", "b": "criar",
    }
    assert resultado["avisos"] == ["b: chaves citadas sem rascunho: sumida"]
    assert ws.criacoes == [] and ws.escritas == [] and ws.ligacoes == []


def test_falha_ao_criar_para_o_lote_e_rodar_de_novo_completa(ws):
    ws.falhar_criacao = {"Projeto — Tarefa B"}

    with pytest.raises(LoteIncompletoError) as erro:
        svc.importar_tarefas(_lote(), DB, cliente=ws)

    assert erro.value.etapa == "criar linhas"
    assert ws.criacoes == ["Projeto — Tarefa A"] and ws.escritas == []
    ws.falhar_criacao = set()
    svc.importar_tarefas(_lote(), DB, cliente=ws)
    assert ws.criacoes == ["Projeto — Tarefa A", "Projeto — Tarefa B"]


def test_conferir_aponta_o_que_nao_ficou_gravado(ws):
    resultado = svc.importar_tarefas(_lote(), DB, conferir=True, cliente=ws)
    assert resultado["problemas"] == []

    a, b = ws.titulo("Projeto — Tarefa A"), ws.titulo("Projeto — Tarefa B")
    ws.paginas[a]["props"]["Etapa"] = "Feito"
    ws.paginas[b]["props"]["Bloqueada por"] = []
    ws.paginas[b]["props"]["Subtarefas relacionadas"] = []  # a volta da simétrica a→b
    ws.paginas[EXISTENTE]["corpo"] = "## Contexto"

    problemas = " | ".join(svc.conferir_tarefas(_lote(), DB, cliente=ws))

    assert "a: Etapa='Feito', esperado 'Entrada'" in problemas
    assert f"b: 'Bloqueada por' não liga {EXISTENTE}" in problemas
    assert f"b: 'Subtarefas relacionadas' não liga {a}" in problemas
    assert f"{EXISTENTE}: corpo não cita {b}" in problemas


# -- carregar_lote ---------------------------------------------------------------


def _par(pasta: Path, chave: str, dados: dict, corpo: str | None = "## Contexto\n\nx") -> None:
    (pasta / f"{chave}.json").write_text(json.dumps({"chave": chave, **dados}), encoding="utf-8")
    if corpo is not None:
        (pasta / f"{chave}.md").write_text(corpo, encoding="utf-8")


def test_carregar_lote_junta_as_colunas_comuns_e_o_rascunho_vence(tmp_path):
    (tmp_path / "lote.json").write_text(
        json.dumps({"propriedades": {"Etapa": "Entrada", "Tipo": ["Feature"]}}), encoding="utf-8"
    )
    _par(tmp_path, "a", {"titulo": " A ", "propriedades": {"Etapa": "Feito"},
                         "relacoes": [{"alvo": "chave:b", "coluna": "Bloqueia", "motivo": "m"}]})
    _par(tmp_path, "b", {"titulo": "B"})

    a, b = svc.carregar_lote(tmp_path)

    assert (a.chave, a.titulo) == ("a", "A")
    assert a.propriedades == {"Etapa": "Feito", "Tipo": ["Feature"]}
    assert a.relacoes == [Relacao("chave:b", "Bloqueia", "m")]
    assert b.propriedades == {"Etapa": "Entrada", "Tipo": ["Feature"]}


def test_carregar_lote_filtra_por_chave(tmp_path):
    _par(tmp_path, "a", {"titulo": "A"})
    _par(tmp_path, "b", {"titulo": "B"})

    assert [r.chave for r in svc.carregar_lote(tmp_path, so=["b"])] == ["b"]


@pytest.mark.parametrize(
    ("dados", "corpo", "mensagem"),
    [
        ({"chave": "outra", "titulo": "A"}, "x", "difere do nome do arquivo"),
        ({"titulo": "A"}, None, "falta o corpo a.md"),
        ({"titulo": ""}, "x", "falta 'titulo'"),
    ],
)
def test_carregar_lote_recusa_par_incompleto(tmp_path, dados, corpo, mensagem):
    _par(tmp_path, "a", dados, corpo)

    with pytest.raises(ValueError, match=mensagem):
        svc.carregar_lote(tmp_path)


def test_carregar_lote_vazio_recusa(tmp_path):
    with pytest.raises(ValueError, match="Nenhum rascunho"):
        svc.carregar_lote(tmp_path)
