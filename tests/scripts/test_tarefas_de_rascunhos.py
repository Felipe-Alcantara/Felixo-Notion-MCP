"""Testes da parte sem rede dos scripts que gravam e conferem um lote de rascunhos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.notion import criar_tarefas_de_rascunhos as criador
from scripts.notion.verificar_tarefas_de_rascunhos import resumo_do_log

A = "3fa91f95-497e-8196-aaaa-f04cda9dc500"
B = "3fa91f95-497e-81fd-8197-d1742f01de67"
C = "3fa91f95-497e-8165-a222-ed0761792c95"
OPCOES = {
    "Etapa": {"Entrada", "Algum dia"},
    "Esforço": {"Dias", "Poucas horas"},
    "Prioridade": {"Baixa", "Média", "Alta"},
    "Tipo": {"Feature", "Pesquisa/Decisão"},
}


def rascunho(chave: str, **campos: object) -> criador.Rascunho:
    base: dict[str, object] = {
        "chave": chave,
        "anotacao": "Anotação",
        "titulo": f"Felixo AI Core/Canvas — tarefa {chave}",
        "etapa": "Entrada",
        "esforco": "Dias",
        "prioridade": "Média",
        "tipos": ["Feature"],
        "fontes": "",
        "repositorio": "Felixo-AI-Core",
        "corpo": "## Contexto\n\nTexto.",
    }
    base.update(campos)
    return criador.Rascunho(**base)  # type: ignore[arg-type]


def gravar_par(pasta: Path, dados: dict[str, object], corpo: str | None = "## Contexto") -> None:
    (pasta / f"{dados['chave']}.json").write_text(json.dumps(dados), encoding="utf-8")
    if corpo is not None:
        (pasta / f"{dados['chave']}.md").write_text(corpo, encoding="utf-8")


def test_carregar_rascunhos_aplica_os_padroes(tmp_path: Path) -> None:
    gravar_par(
        tmp_path,
        {
            "chave": "um",
            "anotacao": "Tokenização",
            "titulo": "  Felixo AI Core/Limites — mostrar o uso  ",
            "etapa": "Entrada",
            "esforco": "Dias",
            "prioridade": "Alta",
            "tipo": "Feature",
        },
    )

    (lido,) = criador.carregar_rascunhos(tmp_path, None)

    assert lido.titulo == "Felixo AI Core/Limites — mostrar o uso"
    assert lido.tipos == ["Feature"]
    assert lido.repositorio == "Felixo-AI-Core"
    assert lido.relacoes == []


def test_carregar_rascunhos_recusa_chave_diferente_do_arquivo(tmp_path: Path) -> None:
    dados = {campo: "x" for campo in criador.CAMPOS_OBRIGATORIOS}
    dados["chave"] = "outra"
    (tmp_path / "um.json").write_text(json.dumps(dados), encoding="utf-8")

    with pytest.raises(criador.Erro, match="difere do nome"):
        criador.carregar_rascunhos(tmp_path, None)


def test_carregar_rascunhos_exige_o_corpo(tmp_path: Path) -> None:
    dados: dict[str, object] = {campo: "x" for campo in criador.CAMPOS_OBRIGATORIOS}
    dados["chave"] = "um"
    gravar_par(tmp_path, dados, corpo=None)

    with pytest.raises(criador.Erro, match="falta o corpo"):
        criador.carregar_rascunhos(tmp_path, None)


def test_validar_aponta_cada_problema_antes_de_escrever() -> None:
    lote = [
        rascunho(
            "um",
            etapa="Hoje",
            tipos=["Feature", "Inventado"],
            corpo="## Contexto\n\n## Tarefas relacionadas",
            relacoes=[
                {"alvo": "chave:um", "coluna": "Subtarefas relacionadas", "motivo": "x"},
                {"alvo": "chave:nao-existe", "coluna": "Bloqueada por", "motivo": "x"},
                {"alvo": "nao-e-id", "coluna": "Tarefa principal", "motivo": ""},
            ],
        ),
        rascunho("dois", titulo="Felixo AI Core/Canvas — tarefa um", repositorio="Outro"),
    ]

    problemas = "\n".join(criador.validar(lote, OPCOES))

    for esperado in (
        "Etapa='Hoje' não é aceito",
        "Tipo='Inventado' não é aceito",
        "não deve trazer 'Tarefas relacionadas'",
        "relação consigo mesma",
        "chave inexistente chave:nao-existe",
        "coluna de relação 'Tarefa principal' não permitida",
        "sem motivo",
        "não é ID nem chave:",
        "dois: título repetido de um",
        "repositório 'Outro' desconhecido",
    ):
        assert esperado in problemas


def test_validar_aceita_lote_correto() -> None:
    lote = [
        rascunho(
            "um", relacoes=[{"alvo": A, "coluna": "Subtarefas relacionadas", "motivo": "x"}]
        ),
        rascunho(
            "dois", relacoes=[{"alvo": "chave:um", "coluna": "Bloqueada por", "motivo": "x"}]
        ),
    ]

    assert criador.validar(lote, OPCOES) == []


def test_resolver_chaves_troca_por_link_e_encurta_dentro_de_tabela() -> None:
    sem_prefixo = "Canvas — tocar áudio e vídeo no bloco de arquivo, com leitura em partes"
    destinos = {"midia": (A, f"Felixo AI Core/{sem_prefixo}")}
    markdown = (
        "Veja `chave:midia` e chave:midia.\n"
        "| `midia` | x |\n"
        "Falta `chave:sumiu`; `npm` fica."
    )

    texto, sem_destino = criador.resolver_chaves(markdown, destinos)

    prosa, tabela, resto = texto.split("\n")
    url = f"https://app.notion.com/p/{A.replace('-', '')}"
    assert prosa.count(f"[{sem_prefixo}]({url})") == 2
    assert f"[tocar áudio e vídeo no bloco de arquivo, com leitura em…]({url})" in tabela
    assert "`chave:sumiu`" in resto and "`npm`" in resto
    assert sem_destino == ["sumiu"]


def test_rotulo_curto_nao_deixa_parentese_aberto() -> None:
    titulo = (
        "Felixo AI Core/Canvas — tocar mídia no bloco "
        "(hoje o bloco só mostra markdown e texto puro)"
    )

    rotulo = criador.rotulo_curto(titulo)

    assert rotulo == "tocar mídia no bloco…"


def test_resolver_arestas_junta_a_simetrica_e_mantem_o_bloqueio() -> None:
    um = rascunho(
        "um",
        relacoes=[
            {"alvo": "chave:dois", "coluna": "Subtarefas relacionadas", "motivo": "irmãs"},
            {"alvo": C, "coluna": "Bloqueada por", "motivo": " depende "},
        ],
    )
    dois = rascunho(
        "dois", relacoes=[{"alvo": "chave:um", "coluna": "Subtarefas relacionadas", "motivo": "x"}]
    )

    arestas = criador.resolver_arestas([um, dois], {"um": A, "dois": B})

    assert arestas == [
        criador.Aresta(A, B, "Subtarefas relacionadas", "irmãs"),
        criador.Aresta(A, C, "Bloqueada por", "depende"),
    ]
    itens = criador.itens_por_pagina(arestas)
    assert (A, "Bloqueia", "depende") in itens[C]
    assert (C, "Bloqueada por", "depende") in itens[A]


def test_rodadas_nunca_tocam_a_mesma_pagina_duas_vezes() -> None:
    paginas = [f"p{i}" for i in range(6)]
    arestas = [
        criador.Aresta(a, b, "Subtarefas relacionadas", "m")
        for i, a in enumerate(paginas)
        for b in paginas[i + 1 :]
    ]

    rodadas = criador.rodadas_sem_pagina_repetida(arestas)

    assert sorted(map(id, (a for r in rodadas for a in r))) == sorted(map(id, arestas))
    for rodada in rodadas:
        pontas = [p for aresta in rodada for p in (aresta.a, aresta.b)]
        assert len(pontas) == len(set(pontas))


def test_cabecalho_marca_o_corpo_e_prefere_o_commit_do_rascunho() -> None:
    sessao = criador.Sessao(
        data="15/10/2026", inicio="14:26", fim="17:44", commits={"Felixo-AI-Core": "d5ce92e"}
    )

    da_sessao = criador.cabecalho(rascunho("um"), sessao)
    do_rascunho = criador.cabecalho(rascunho("um", commit="abc1234"), sessao)
    sem_commit = criador.cabecalho(rascunho("um", repositorio="Openia"), sessao)

    assert criador.MARCA_DO_CORPO in da_sessao
    assert "commit `d5ce92e`" in da_sessao and "15/10/2026 14:26" in da_sessao
    assert "commit `abc1234`" in do_rascunho
    assert "lido pelo GitHub" in sem_commit


def test_commits_da_linha_de_comando_confere_o_formato() -> None:
    assert criador.commits_da_linha_de_comando(["Openia=ed1e85c"]) == {"Openia": "ed1e85c"}
    with pytest.raises(criador.Erro, match="Repositório=commit"):
        criador.commits_da_linha_de_comando(["Openia"])
    with pytest.raises(criador.Erro, match="desconhecido"):
        criador.commits_da_linha_de_comando(["Outro=abc"])


def test_resumo_do_log_ignora_o_que_vem_depois_do_json(tmp_path: Path) -> None:
    resumo = {"tarefas": {"um": {"id": A, "titulo": "t", "url": "u"}}, "ligacoes": 1}
    log = tmp_path / "gravacao.txt"
    log.write_text(
        "[cria] um: " + A + "\n" + json.dumps(resumo, indent=2) + "\nsaida=0\n",
        encoding="utf-8-sig",
    )

    assert resumo_do_log(log) == resumo["tarefas"]
