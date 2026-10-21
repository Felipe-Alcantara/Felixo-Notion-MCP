"""Testes de ``domain.rascunhos_de_tarefas``: o lote de rascunhos antes e depois de gravar."""

from __future__ import annotations

from felixo_notion_mcp.domain import rascunhos_de_tarefas as dom

A = "3fa91f95-497e-8196-aaaa-f04cda9dc500"
B = "3fa91f95-497e-81fd-8197-d1742f01de67"
C = "3fa91f95-497e-8165-a222-ed0761792c95"

COLUNAS = {
    "Tarefa": {"nome": "Tarefa", "tipo": "title", "editavel": True, "titulo": True},
    "Etapa": {"nome": "Etapa", "tipo": "status", "editavel": True, "opcoes": ["Entrada"]},
    "Tipo": {"nome": "Tipo", "tipo": "multi_select", "editavel": True, "opcoes": ["Feature"]},
    "Subtarefas relacionadas": {
        "nome": "Subtarefas relacionadas", "tipo": "relation", "editavel": True,
        "relacao": {"database_id": "db", "bidirecional": False, "coluna_espelho": None,
                    "auto_referente": True},
    },
    "Bloqueada por": {
        "nome": "Bloqueada por", "tipo": "relation", "editavel": True,
        "relacao": {"database_id": "db", "bidirecional": True, "coluna_espelho": "Bloqueia",
                    "auto_referente": True},
    },
    "Projeto": {
        "nome": "Projeto", "tipo": "relation", "editavel": True,
        "relacao": {"database_id": "outro", "bidirecional": True,
                    "coluna_espelho": "Tarefas", "auto_referente": False},
    },
}


def rascunho(chave: str, **campos: object) -> dom.Rascunho:
    base: dict[str, object] = {
        "chave": chave,
        "titulo": f"Felixo AI Core/Canvas — tarefa {chave}",
        "propriedades": {"Etapa": "Entrada", "Tipo": ["Feature"]},
        "corpo": "## Contexto\n\nTexto.",
        "relacoes": [],
    }
    base.update(campos)
    return dom.Rascunho(**base)  # type: ignore[arg-type]


def rel(alvo: str, coluna: str = "Subtarefas relacionadas", motivo: str = "porque sim"):
    return dom.Relacao(alvo=alvo, coluna=coluna, motivo=motivo)


# -- validar_lote ----------------------------------------------------------------


def test_validar_aceita_lote_correto():
    lote = [
        rascunho("a", relacoes=[rel("chave:b"), rel(A, "Bloqueada por")]),
        rascunho("b"),
    ]

    assert dom.validar_lote(lote, COLUNAS) == []


def test_validar_aponta_cada_problema_antes_de_escrever():
    lote = [
        rascunho("a", propriedades={"Etapa": "Feito"}),
        rascunho("b", titulo="Felixo AI Core/Canvas — tarefa a"),
        rascunho("c", corpo="## Contexto\n\n## Tarefas relacionadas\n\n- x"),
        rascunho("d", corpo="  "),
        rascunho("e", relacoes=[rel("chave:nao-existe"), rel("chave:e")]),
        rascunho("f", relacoes=[rel("texto solto"), rel(A, motivo=" ")]),
        rascunho("g", relacoes=[rel(A, "Projeto"), rel(A, "Etapa"), rel(A, "Sumida")]),
        rascunho("Com Espaço"),
    ]

    problemas = " | ".join(dom.validar_lote(lote, COLUNAS))

    assert "a: 'Feito' não é opção de 'Etapa'" in problemas
    assert "b: título repetido de a" in problemas
    assert "c: o corpo não deve trazer 'Tarefas relacionadas'" in problemas
    assert "d: corpo vazio" in problemas
    assert "e: relação para chave inexistente chave:nao-existe" in problemas
    assert "e: relação consigo mesma" in problemas
    assert "f: alvo 'texto solto' não é ID nem chave:" in problemas
    assert "f: relação com " in problemas and "sem motivo" in problemas
    assert "g: 'Projeto' liga a outro database" in problemas
    assert "g: 'Etapa' não é coluna de relação" in problemas
    assert "g: coluna de relação inexistente 'Sumida'" in problemas
    assert "Com Espaço: chave só com minúsculas, números e hífen" in problemas


def test_validar_aceita_alvo_como_link_ou_sem_hifens():
    lote = [
        rascunho("a", relacoes=[rel(A.replace("-", "")),
                                rel(f"https://app.notion.com/p/Tarefa-{B.replace('-', '')}")]),
    ]

    assert dom.validar_lote(lote, COLUNAS) == []


# -- corpo e links ---------------------------------------------------------------


def test_resolver_chaves_troca_por_link_e_encurta_dentro_de_tabela():
    destinos = {"b": (B, "Felixo AI Core/Canvas — Aba de pedidos de escrita no painel lateral")}
    texto = (
        "Ver `chave:b` e `b` e chave:b; `x` fica.\n"
        "| `b` | coluna |\n"
        "Sem destino: `chave:sumida`."
    )

    resultado, sem_destino = dom.resolver_chaves(texto, destinos)

    link_b = f"https://app.notion.com/p/{B.replace('-', '')}"
    primeira, tabela, _ = resultado.split("\n")
    assert primeira.count(f"]({link_b})") == 3
    assert "[Felixo AI Core/Canvas — Aba de pedidos de escrita no painel lateral]" in primeira
    assert "`x` fica" in primeira
    assert tabela.startswith(f"| [Aba de pedidos de escrita no painel lateral]({link_b})")
    assert sem_destino == ["sumida"]


def test_rotulo_curto_corta_na_palavra_sem_parentese_aberto():
    titulo = "Projeto/Área — Uma descrição bem longa que passa do limite (com parêntese aberto)"

    rotulo = dom.rotulo_curto(titulo)

    assert rotulo.endswith("…")
    assert rotulo.count("(") == rotulo.count(")")
    assert len(rotulo) <= dom.LIMITE_ROTULO_TABELA + 1


# -- relações --------------------------------------------------------------------


def test_resolver_arestas_junta_a_simetrica_e_mantem_a_de_mao_dupla():
    lote = [
        rascunho("a", relacoes=[rel("chave:b"), rel("chave:b", "Bloqueada por", "b antes")]),
        rascunho("b", relacoes=[rel("chave:a")]),
    ]

    arestas = dom.resolver_arestas(lote, {"a": A, "b": B}, COLUNAS)

    assert len(arestas) == 2
    assert dom.Aresta(A, B, "Bloqueada por", "b antes") in arestas
    assert sum(1 for x in arestas if x.coluna == "Subtarefas relacionadas") == 1


def test_rodadas_nunca_tocam_a_mesma_pagina_duas_vezes():
    arestas = [
        dom.Aresta(A, B, "Subtarefas relacionadas", "1"),
        dom.Aresta(A, C, "Subtarefas relacionadas", "2"),
        dom.Aresta(B, C, "Subtarefas relacionadas", "3"),
    ]

    rodadas = dom.rodadas_sem_pagina_repetida(arestas)

    assert sorted(len(r) for r in rodadas) == [1, 1, 1]
    for rodada in rodadas:
        paginas = [p for x in rodada for p in (x.a, x.b)]
        assert len(paginas) == len(set(paginas))


def test_itens_por_pagina_usa_a_coluna_espelho_do_schema_como_rotulo():
    arestas = [
        dom.Aresta(A, B, "Bloqueada por", "B entrega a API"),
        dom.Aresta(A, C, "Subtarefas relacionadas", "mesmo tema"),
    ]

    itens = dom.itens_por_pagina(arestas, COLUNAS)

    assert dom.ItemRelacionado(B, "Bloqueada por", "B entrega a API") in itens[A]
    assert itens[B] == [dom.ItemRelacionado(A, "Bloqueia", "B entrega a API")]
    assert itens[C] == [dom.ItemRelacionado(A, "", "mesmo tema")]


def test_secao_acrescenta_so_os_links_que_faltam_e_o_titulo_uma_vez():
    itens = [
        dom.ItemRelacionado(B, "Bloqueada por", "B entrega a API"),
        dom.ItemRelacionado(C, "", "ver `chave:c`"),
    ]
    titulos = {B: "Tarefa B", C: "Tarefa C"}
    destinos = {"c": (C, "Tarefa C")}

    nova = dom.secao_a_acrescentar("## Contexto\n\nTexto.", itens, titulos, destinos)

    link_b = f"https://app.notion.com/p/{B.replace('-', '')}"
    assert nova.startswith("## Tarefas relacionadas\n\n")
    assert f"- **Bloqueada por:** [Tarefa B]({link_b}) — B entrega a API" in nova
    assert "`chave:c`" not in nova
    # Rodar de novo, com a seção já escrita, não repete nada.
    escrito = "## Contexto\n\n" + nova
    assert dom.secao_a_acrescentar(escrito, itens, titulos, destinos) is None
    # Ligação nova depois: entra sob a seção existente, sem repetir o título.
    outra = dom.ItemRelacionado(A, "", "nova")
    acrescimo = dom.secao_a_acrescentar(escrito, [*itens, outra], {**titulos, A: "A"}, destinos)
    assert acrescimo.startswith("- [A](")
