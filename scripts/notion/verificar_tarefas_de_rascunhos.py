#!/usr/bin/env python3
"""Relê no Notion o que o criar_tarefas_de_rascunhos.py gravou e confere tudo.

Uso:
    python -I scripts/notion/verificar_tarefas_de_rascunhos.py <pasta_rascunhos>
        <log_da_gravacao> [<outro_log> ...] [--paralelo 8]

Cada log é a saída de uma execução do ``criar_tarefas_de_rascunhos.py`` (o JSON do
fim dá a chave e o ID de cada tarefa); vários logs conferem vários lotes de uma vez.

Confere, por tarefa criada: propriedades (Etapa, Esforço, Prioridade, Tipo, Origem,
Repositório, URL de referência, Projeto, Áreas da vida), corpo (cabeçalho, seções,
nenhum `chave:` sobrando) e cada relação nos DOIS lados — inclusive nas tarefas
existentes, que também precisam do link na seção "Tarefas relacionadas".
Sai com 1 se achar problema.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

# O GET /pages devolve no máximo 25 referências por relação (has_more fica de fora).
LIMITE_RELACAO_LIDA = 25
CHAVE_CITADA = re.compile(r"chave:[a-z0-9]+(?:-[a-z0-9]+)+")


def carregar_criador(caminho: Path) -> ModuleType:
    # Por caminho, não por import: com ``python -I`` a pasta do script não entra no sys.path.
    spec = importlib.util.spec_from_file_location("criador", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["criador"] = modulo  # os dataclasses do módulo procuram por ele aqui
    spec.loader.exec_module(modulo)
    return modulo


def resumo_do_log(log: Path) -> dict[str, dict[str, str]]:
    texto = log.read_text(encoding="utf-8-sig")
    inicio = texto.rfind('\n{\n  "tarefas"')
    # raw_decode para no fim do objeto: o que vier depois (ex.: "saida=0") não atrapalha.
    resumo, _ = json.JSONDecoder().raw_decode(texto[inicio + 1 :])
    return resumo["tarefas"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pasta", type=Path)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--perfil", default="felipe")
    parser.add_argument("--paralelo", type=int, default=8)
    args = parser.parse_args()

    criador = carregar_criador(Path(__file__).with_name("criar_tarefas_de_rascunhos.py"))
    criador.TRABALHADORES = args.paralelo
    resumo: dict[str, dict[str, str]] = {}
    for log in args.logs:
        resumo.update(resumo_do_log(log))
    rascunhos = {r.chave: r for r in criador.carregar_rascunhos(args.pasta, set(resumo))}
    ids = {chave: dados["id"] for chave, dados in resumo.items()}
    arestas = criador.resolver_arestas(list(rascunhos.values()), ids)

    paginas_alvo = set(ids.values()) | {a.a for a in arestas} | {a.b for a in arestas}
    cache: dict[str, dict] = {}
    criador.em_paralelo(
        lambda pid: criador.ler_pagina(args.perfil, pid, cache), sorted(paginas_alvo), "reler"
    )

    def props(pid: str) -> dict:
        return cache[pid].get("propriedades") or {}

    def md(pid: str) -> str:
        return cache[pid].get("markdown") or ""

    problemas: list[str] = []
    for chave, r in rascunhos.items():
        pid = ids[chave]
        p = props(pid)
        repositorio = criador.REPOSITORIOS[r.repositorio]
        esperado = {
            "Etapa": r.etapa,
            "Esforço": r.esforco,
            "Prioridade": r.prioridade,
            "Origem": criador.ORIGEM,
            "Repositório": r.repositorio,
            "URL de referência": repositorio["url"],
            "Tarefa": r.titulo,
        }
        for coluna, valor in esperado.items():
            if p.get(coluna) != valor:
                problemas.append(f"{chave}: {coluna}={p.get(coluna)!r}, esperado {valor!r}")
        if sorted(p.get("Tipo") or []) != sorted(r.tipos):
            problemas.append(f"{chave}: Tipo={p.get('Tipo')}, esperado {r.tipos}")
        if repositorio["projeto"]:
            if p.get("Projeto") != [repositorio["projeto"]]:
                problemas.append(f"{chave}: Projeto={p.get('Projeto')}")
        else:
            print(f"[info] {chave}: Projeto={p.get('Projeto')} ({r.repositorio} sem projeto)")
        if p.get("Áreas da vida") != [criador.AREA_PRODUTOS]:
            problemas.append(f"{chave}: Áreas da vida={p.get('Áreas da vida')}")
        corpo = md(pid)
        secoes = ("## Contexto", "## O que a investigação mediu", "## Critério de aceite")
        for trecho in (criador.MARCA_DO_CORPO, *secoes):
            if trecho not in corpo:
                problemas.append(f"{chave}: corpo sem '{trecho}'")
        # Só a referência de chave que o gravador troca por link (`chave:<slug>`);
        # a palavra "chave:" solta no texto ("nem chave:") não é sobra.
        sobras = sorted(set(CHAVE_CITADA.findall(corpo)))
        if sobras:
            problemas.append(f"{chave}: sobrou referência de chave no corpo: {sobras}")

    inconclusivas: list[str] = []

    def contem(x: str, coluna: str, y: str) -> bool | None:
        """``y`` está na relação ``coluna`` de ``x``? ``None`` quando não dá para saber.

        O GET /pages corta a relação em 25 referências: numa lista desse tamanho,
        a ausência de ``y`` não prova nada.
        """
        lista = props(x).get(coluna) or []
        if y in lista:
            return True
        return None if len(lista) >= LIMITE_RELACAO_LIDA else False

    for aresta in arestas:
        if aresta.coluna == "Subtarefas relacionadas":
            for x, y in ((aresta.a, aresta.b), (aresta.b, aresta.a)):
                achou = contem(x, "Subtarefas relacionadas", y)
                if achou is False:
                    problemas.append(f"relação simétrica faltando: {x} -/-> {y}")
                elif achou is None:
                    inconclusivas.append(
                        f"Subtarefas relacionadas de {x} (lista cortada em 25) -> {y}"
                    )
        else:
            achou = contem(aresta.a, "Bloqueada por", aresta.b)
            if achou is False:
                problemas.append(f"'Bloqueada por' faltando: {aresta.a} -/-> {aresta.b}")
            elif achou is None:
                inconclusivas.append(
                    f"Bloqueada por de {aresta.a} (lista cortada em 25) -> {aresta.b}"
                )
            # "Bloqueia" é o espelho automático da relação dupla: só se confere quando a
            # lista veio inteira.
            if contem(aresta.b, "Bloqueia", aresta.a) is False:
                problemas.append(f"'Bloqueia' (espelho) faltando: {aresta.b} -/-> {aresta.a}")
        for x, y in ((aresta.a, aresta.b), (aresta.b, aresta.a)):
            if criador.sem_hifens(y) not in md(x):
                problemas.append(f"link no corpo faltando: {x} não cita {y}")

    print(
        f"tarefas conferidas: {len(rascunhos)} · páginas relidas: {len(paginas_alvo)} · "
        f"ligações: {len(arestas)}"
    )
    print(f"problemas: {len(problemas)}")
    for problema in problemas:
        print("-", problema)
    if inconclusivas:
        print(f"não conferíveis pela leitura cortada em 25: {len(inconclusivas)}")
        for item in inconclusivas:
            print("  ~", item)
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
