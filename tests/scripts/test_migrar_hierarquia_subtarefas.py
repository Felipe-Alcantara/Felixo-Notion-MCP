"""Testes da parte sem rede da migração de Subtarefas/Tarefa principal para um par de mão dupla."""

from __future__ import annotations

from scripts.notion import migrar_hierarquia_subtarefas as mig

ANTIGAS = ("Subtarefas (antiga)", "Tarefa principal (antiga)")


def _linhas(ligacoes: dict[str, list[str]], coluna: str = ANTIGAS[0]) -> dict[str, dict]:
    """Linhas com as ligações já simétricas, como o Notion deixa as colunas antigas."""

    linhas: dict[str, dict] = {}
    for origem, alvos in ligacoes.items():
        for alvo in alvos:
            linhas.setdefault(origem, {}).setdefault(coluna, []).append(alvo)
            linhas.setdefault(alvo, {}).setdefault(coluna, []).append(origem)
    return linhas


def test_estrela_vira_pai_com_filhos_e_o_pai_e_o_de_mais_ligacoes():
    linhas = _linhas({"pai": ["f1", "f2", "f3"]})

    plano = mig.planejar(mig.pares(linhas, ANTIGAS))

    assert plano.filhos == {"pai": {"f1", "f2", "f3"}}
    assert plano.ambiguos == []


def test_par_isolado_e_corrente_ficam_ambiguos_com_o_motivo():
    linhas = _linhas({"a": ["b"], "x": ["y"], "y": ["z"], "z": ["w"]})

    plano = mig.planejar(mig.pares(linhas, ANTIGAS))

    motivos = {frozenset((a, b)): motivo for a, b, motivo in plano.ambiguos}
    assert motivos[frozenset(("a", "b"))] == "par isolado"
    assert motivos[frozenset(("y", "z"))] == "corrente ou dois polos"
    # x e w são pontas de grau 1 ligadas a nós de grau 2: estrela, direção pelo grau.
    assert plano.filhos == {"y": {"x"}, "z": {"w"}}


def test_pares_juntam_as_duas_colunas_e_ignoram_a_propria_linha_e_quem_esta_fora():
    linhas = _linhas({"a": ["b"]}, coluna=ANTIGAS[0])
    for pid, colunas in _linhas({"a": ["b", "fora"], "c": ["c"]}, coluna=ANTIGAS[1]).items():
        linhas.setdefault(pid, {}).update(colunas)
    linhas.pop("fora")  # ligação para uma linha que não está no database

    assert mig.pares(linhas, ANTIGAS) == {frozenset(("a", "b"))}


def test_escritas_somam_ao_que_ja_esta_e_pulam_quem_ja_esta_completo():
    plano = mig.Plano(filhos={"p": {"f1", "f2"}, "q": {"g1"}}, ambiguos=[])
    atuais = {"p": {"f1"}, "q": {"g1"}}

    assert mig.escritas(plano, atuais) == {"p": ["f1", "f2"]}


def test_esperar_rele_ate_o_schema_mostrar_a_mudanca():
    # Medido na aplicação: logo depois de renomear, a releitura ainda trazia o nome antigo.
    leituras = iter([{"Subtarefas": {}}, {"Subtarefas": {}}, {"Subtarefas (antiga)": {}}])
    pausas = []

    colunas = mig.esperar(
        lambda: next(leituras),
        lambda c: "Subtarefas (antiga)" in c,
        "renomear",
        dormir=pausas.append,
    )

    assert "Subtarefas (antiga)" in colunas
    assert len(pausas) == 2


def test_esperar_desiste_com_mensagem_quando_o_schema_nao_muda():
    import pytest

    with pytest.raises(SystemExit, match="criar o par"):
        mig.esperar(lambda: {}, lambda c: False, "criar o par", tentativas=3, dormir=lambda _: None)
