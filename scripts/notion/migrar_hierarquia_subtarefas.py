"""Migra ``Subtarefas``/``Tarefa principal`` do To Do List da HOME para um par de mão dupla.

Uso:
    python scripts/notion/migrar_hierarquia_subtarefas.py --simular --relatorio plano.md
    python scripts/notion/migrar_hierarquia_subtarefas.py --relatorio plano.md

Por quê (medido em 2026-10-21): as duas colunas são relações ``single_property`` do
próprio database, e o Notion espelha esse tipo **na mesma coluna** — gravar só
``A.Subtarefas = [B]`` fez ``B.Subtarefas`` trazer A na hora. Então toda ligação virava
A↔B (440 de 441 em Subtarefas, 904 de 904 em Tarefa principal) e as colunas não guardavam
quem é o pai. Hierarquia de verdade precisa de um par ``dual_property``, como
``Bloqueada por`` ↔ ``Bloqueia``.

O que faz, sem duplicar nada se rodar de novo:

1. renomeia as colunas atuais para ``Subtarefas (antiga)`` e ``Tarefa principal (antiga)``;
2. cria ``Subtarefas`` como relação de mão dupla do database com ele mesmo e dá o nome
   ``Tarefa principal`` à coluna espelho que o Notion cria;
3. como os dados antigos não guardam direção, usa a forma: numa **estrela**, o pai é a
   tarefa que liga várias outras que só ligam a ela (grau 1). Esses pares viram
   ``pai.Subtarefas += filho`` (o Notion preenche ``Tarefa principal`` do filho);
4. par isolado ou corrente (os dois lados com o mesmo papel) fica **ambíguo**: não é
   migrado e vai para o relatório, continuando visível nas colunas antigas.

``--simular`` só lê e mostra o plano. As colunas antigas ficam até a pessoa conferir.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATABASE_ID = "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
FILHOS = "Subtarefas"
PAI = "Tarefa principal"
ANTIGAS = ("Subtarefas (antiga)", "Tarefa principal (antiga)")
LIMITE_RELACAO = 100  # a API grava no máximo 100 páginas numa relação por requisição


# -- Parte sem rede --------------------------------------------------------------


@dataclass
class Plano:
    """``filhos``: pai -> filhos a ligar; ``ambiguos``: ``(a, b, motivo)`` não migrados."""

    filhos: dict[str, set[str]] = field(default_factory=dict)
    ambiguos: list[tuple[str, str, str]] = field(default_factory=list)


def pares(linhas: Mapping[str, Mapping[str, list[str]]], colunas: Iterable[str]) -> set[frozenset]:
    """Ligações distintas nas colunas antigas, sem a própria linha nem quem está fora."""

    encontrados: set[frozenset] = set()
    nomes = tuple(colunas)
    for pid, valores in linhas.items():
        for coluna in nomes:
            for alvo in valores.get(coluna) or []:
                if alvo != pid and alvo in linhas:
                    encontrados.add(frozenset((pid, alvo)))
    return encontrados


def planejar(ligacoes: set[frozenset]) -> Plano:
    """Direção pela forma: na estrela o pai é o de grau maior; o resto fica ambíguo."""

    grau: Counter[str] = Counter(no for par in ligacoes for no in par)
    plano = Plano()
    for par in sorted(ligacoes, key=sorted):
        a, b = sorted(par, key=lambda no: (-grau[no], no))
        if grau[a] >= 2 and grau[b] == 1:
            plano.filhos.setdefault(a, set()).add(b)
        elif grau[a] == 1 and grau[b] == 1:
            plano.ambiguos.append((a, b, "par isolado"))
        else:
            plano.ambiguos.append((a, b, "corrente ou dois polos"))
    return plano


def escritas(plano: Plano, atuais: Mapping[str, set[str]]) -> dict[str, list[str]]:
    """``pai -> lista completa`` a gravar em Subtarefas, só para quem ainda falta algo."""

    gravar: dict[str, list[str]] = {}
    for pai, filhos in plano.filhos.items():
        ja = set(atuais.get(pai) or set())
        if not filhos <= ja:
            gravar[pai] = sorted(ja | filhos)
    return gravar


# -- Notion ------------------------------------------------------------------------


def _cliente() -> Any:
    from felixo_notion_mcp.core import workspaces
    from felixo_notion_mcp.integrations.notion import criar_cliente

    workspaces.aplicar_perfil(None)  # o mesmo perfil ativo que a CLI usa
    return criar_cliente()


def _fonte(cli: Any) -> dict[str, Any]:
    """O schema pelo *data source*: o mesmo endpoint das escritas de schema.

    O ``GET /databases`` clássico demorou mais de 30 s para mostrar a coluna criada
    pelo data source (2026-10-21); ler pelo mesmo caminho evita esperar por ele.
    """

    return cli.get_data_source(cli.resolver_data_source(DATABASE_ID))


def _colunas(cli: Any) -> dict[str, dict[str, Any]]:
    from felixo_notion_mcp.domain.schema import descrever_database

    # O id do database (não o do data source) é o que diz se a relação é auto-referente.
    descricao = descrever_database({**_fonte(cli), "id": DATABASE_ID}).para_dict()
    return {coluna["nome"]: coluna for coluna in descricao["colunas"]}


def esperar(
    ler: Callable[[], dict[str, Any]],
    condicao: Callable[[dict[str, Any]], bool],
    etapa: str,
    *,
    tentativas: int = 30,
    intervalo: float = 2.0,
    dormir: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Relê o schema até ``condicao`` valer: a leitura logo depois de mudar vem atrasada.

    Medido na primeira aplicação (2026-10-21): renomeada a coluna, a releitura imediata
    ainda trazia o nome antigo, e o script pulou a criação do par.
    """

    for tentativa in range(tentativas):
        colunas = ler()
        if condicao(colunas):
            return colunas
        if tentativa < tentativas - 1:
            dormir(intervalo)
    raise SystemExit(
        f"O schema não mostrou '{etapa}' depois de {tentativas} leituras; rode de novo "
        "(o script continua de onde parou)."
    )


def _relacao(colunas: Mapping[str, Any], nome: str) -> dict[str, Any]:
    return (colunas.get(nome) or {}).get("relacao") or {}


def par_pronto(colunas: Mapping[str, Any]) -> bool:
    """``Subtarefas`` de mão dupla no próprio database, com a espelho ``Tarefa principal``."""

    relacao = _relacao(colunas, FILHOS)
    return bool(
        relacao.get("bidirecional")
        and relacao.get("auto_referente")
        and relacao.get("coluna_espelho") == PAI
    )


def preparar_schema(cli: Any, *, simular: bool) -> list[str]:
    """Renomeia as antigas e cria o par de mão dupla; devolve o que fez (ou faria)."""

    from felixo_notion_mcp.domain.properties import schema_propriedade
    from felixo_notion_mcp.services import schema as svc_schema

    def ler() -> dict[str, Any]:
        return _colunas(cli)

    acoes: list[str] = []
    colunas = ler()
    if par_pronto(colunas) and ANTIGAS[0] in colunas:
        return acoes
    for atual, antiga in zip((FILHOS, PAI), ANTIGAS, strict=True):
        if antiga in colunas:
            continue
        if atual not in colunas:
            raise SystemExit(f"Coluna {atual!r} não existe e {antiga!r} também não.")
        acoes.append(f"renomear coluna {atual!r} -> {antiga!r}")
        if not simular:
            svc_schema.renomear_coluna(DATABASE_ID, atual, antiga, cliente=cli)
            colunas = esperar(
                ler, lambda c, a=antiga, x=atual: a in c and x not in c, f"renomear {atual!r}"
            )
    # Simulando, as antigas ainda têm o nome atual: a Subtarefas que aparece é a velha.
    if FILHOS not in colunas or (simular and ANTIGAS[0] not in colunas):
        acoes.append(f"criar {FILHOS!r} (mão dupla no próprio database)")
        if simular:
            return [*acoes, f"renomear a coluna espelho criada pelo Notion -> {PAI!r}"]
        definicao = schema_propriedade("relacao", relacionar_com=DATABASE_ID)
        svc_schema.garantir_coluna(DATABASE_ID, FILHOS, definicao, cliente=cli)
        colunas = esperar(
            ler, lambda c: bool(_relacao(c, FILHOS).get("bidirecional")), f"criar {FILHOS!r}"
        )
    elif not _relacao(colunas, FILHOS).get("bidirecional"):
        raise SystemExit(f"Já existe uma {FILHOS!r} que não é de mão dupla; confira à mão.")
    espelho = _relacao(colunas, FILHOS).get("coluna_espelho")
    if espelho != PAI:
        acoes.append(f"renomear coluna espelho {espelho!r} -> {PAI!r}")
        if not simular:
            svc_schema.renomear_coluna(DATABASE_ID, str(espelho), PAI, cliente=cli)
            esperar(ler, par_pronto, f"renomear a espelho para {PAI!r}")
    return acoes


def _ids_completos(cli: Any, page_id: str, property_id: str) -> list[str]:
    return [
        str(item["relation"]["id"])
        for item in cli.ler_itens_de_propriedade(page_id, property_id)
        if isinstance(item, dict) and isinstance(item.get("relation"), dict)
    ]


def ler_linhas(
    cli: Any, colunas: tuple[str, ...]
) -> tuple[dict[str, dict[str, list[str]]], dict[str, str]]:
    """``id -> coluna -> ids ligados`` (listas completas, sem o corte de 25) e os títulos."""

    from felixo_notion_mcp.core.utils import chave_de_id
    from felixo_notion_mcp.services import conteudo

    ids_das_colunas = {nome: info.get("id") for nome, info in _fonte(cli)["properties"].items()}
    linhas: dict[str, dict[str, list[str]]] = {}
    titulos: dict[str, str] = {}
    for linha in conteudo.listar_linhas(DATABASE_ID, propriedades=True, cliente=cli):
        pid = chave_de_id(linha["id"])
        titulos[pid] = str(linha.get("titulo") or "(sem título)")
        valores: dict[str, list[str]] = {}
        for coluna in colunas:
            lista = linha["propriedades"].get(coluna) or []
            if len(lista) >= 25:  # o GET/query corta em 25: lê a propriedade inteira
                lista = _ids_completos(cli, linha["id"], ids_das_colunas[coluna])
            valores[coluna] = [chave_de_id(v) for v in lista]
        linhas[pid] = valores
    return linhas, titulos


def _link(page_id: str) -> str:
    return f"https://app.notion.com/p/{page_id}"


def relatorio(plano: Plano, titulos: Mapping[str, str], acoes: list[str]) -> str:
    """Markdown para a pessoa conferir: ações de schema, plano por pai e os ambíguos."""

    def item(pid: str) -> str:
        return f"[{titulos.get(pid, pid)}]({_link(pid)})"

    linhas = ["# Migração de Subtarefas / Tarefa principal", "", "## Schema", ""]
    linhas += [f"- {acao}" for acao in acoes] or ["- nada a mudar"]
    total = sum(len(f) for f in plano.filhos.values())
    linhas += ["", f"## Estrelas: {len(plano.filhos)} pais, {total} subtarefas", ""]
    for pai in sorted(plano.filhos, key=lambda p: titulos.get(p, p)):
        linhas.append(f"- {item(pai)}")
        linhas += [f"  - {item(f)}" for f in sorted(plano.filhos[pai], key=titulos.get)]
    linhas += ["", f"## Ambíguos (não migrados): {len(plano.ambiguos)}", ""]
    linhas += [f"- {motivo}: {item(a)} ↔ {item(b)}" for a, b, motivo in plano.ambiguos]
    return "\n".join(linhas) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--simular", action="store_true", help="só lê e mostra o plano")
    parser.add_argument("--relatorio", type=Path, help="grava o plano em Markdown")
    parser.add_argument("--paralelo", type=int, default=4)
    args = parser.parse_args()

    cli = _cliente()
    acoes = preparar_schema(cli, simular=args.simular)
    colunas = _colunas(cli)
    if not args.simular and not (par_pronto(colunas) and ANTIGAS[0] in colunas):
        raise SystemExit("O par novo não está pronto no schema; nada foi gravado nas linhas.")
    antigas = ANTIGAS if ANTIGAS[0] in colunas else (FILHOS, PAI)  # simulação: ainda sem renomear
    novas = (FILHOS,) if ANTIGAS[0] in colunas and FILHOS in colunas else ()
    linhas, titulos = ler_linhas(cli, antigas + novas)
    ligacoes = pares(linhas, antigas)
    if not args.simular and not ligacoes:
        raise SystemExit(
            "Nenhuma ligação nas colunas antigas (as linhas ainda vêm com o nome velho?); "
            "nada foi gravado, rode de novo."
        )
    plano = planejar(ligacoes)
    atuais = {}
    if novas:
        atuais = {pid: set(valores.get(FILHOS) or []) for pid, valores in linhas.items()}
    gravar = escritas(plano, atuais)
    grandes = [pai for pai, lista in gravar.items() if len(lista) > LIMITE_RELACAO]
    if grandes:
        raise SystemExit(f"Pais com mais de {LIMITE_RELACAO} subtarefas: {grandes}")

    if not args.simular:
        def ligar(item: tuple[str, list[str]]) -> None:
            pai, filhos = item
            cli.atualizar_pagina(pai, {FILHOS: {"relation": [{"id": f} for f in filhos]}})

        # Cada filho de estrela tem um pai só: escritas em pais diferentes não se cruzam.
        with ThreadPoolExecutor(max_workers=max(1, args.paralelo)) as executor:
            list(executor.map(ligar, gravar.items()))

    if args.relatorio:
        args.relatorio.write_text(relatorio(plano, titulos, acoes), encoding="utf-8")
    print(
        json.dumps(
            {
                "simulado": args.simular,
                "schema": acoes,
                "pares": len(ligacoes),
                "pais": len(plano.filhos),
                "subtarefas": sum(len(f) for f in plano.filhos.values()),
                "ambiguos": len(plano.ambiguos),
                "pais_a_gravar": len(gravar),
                "relatorio": str(args.relatorio) if args.relatorio else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
