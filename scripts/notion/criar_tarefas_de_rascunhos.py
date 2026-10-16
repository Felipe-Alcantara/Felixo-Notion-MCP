#!/usr/bin/env python3
"""Grava no database de tarefas, sem duplicar, um lote de rascunhos investigados.

Uso:
    python -I scripts/notion/criar_tarefas_de_rascunhos.py <pasta_rascunhos>
        [--perfil felipe] [--data 15/10/2026] [--inicio 14:26]
        [--commit Felixo-AI-Core=d5ce92e ...] [--modelo "Claude Code"]
        [--dry-run] [--so <chave> ...] [--paralelo 6]

Cada tarefa é um par de arquivos na pasta:

- ``<chave>.json`` com ``chave`` (igual ao nome do arquivo), ``anotacao`` (apelido da
  anotação que originou a tarefa), ``titulo``, ``etapa``, ``esforco``, ``prioridade``,
  ``tipo`` (texto ou lista) e, opcionais, ``fontes``, ``repositorio`` (padrão
  ``Felixo-AI-Core``), ``commit`` e ``relacoes`` — lista de
  ``{"alvo", "coluna", "motivo"}``, em que ``alvo`` é o ID de uma tarefa existente ou
  ``chave:<chave>`` de outro rascunho do lote e ``coluna`` é "Subtarefas relacionadas"
  (simétrica) ou "Bloqueada por" (o Notion espelha em "Bloqueia");
- ``<chave>.md`` com o corpo, começando em ``## Contexto``, sem a seção "Tarefas
  relacionadas" (o script a gera a partir de ``relacoes``).

O script:

1. valida TODOS os rascunhos antes de escrever qualquer coisa: valores aceitos
   pelo schema real do database, títulos únicos, chaves de relação que existem
   e IDs de tarefas existentes que respondem;
2. cria cada título que ainda não existe, com as propriedades (título já
   existente é pulado e reaproveitado);
3. escreve o corpo de cada tarefa criada por este lote — cabeçalho padrão mais o
   Markdown do rascunho — trocando as citações de chave (`chave:x`, `x`) por
   links clicáveis para as tarefas, que nesse ponto já têm ID. Corpo já escrito
   (marcado pelo cabeçalho) não é escrito de novo;
4. liga as relações com ``notion-tasks relacionar`` (idempotente: confere a
   outra ponta e grava só o que falta);
5. acrescenta a seção "Tarefas relacionadas", com link e motivo, no corpo das
   tarefas novas E das existentes ligadas a elas — só os itens cujo link ainda
   não está no corpo, então rodar de novo não repete nada.

``Projeto`` não é passado à mão: a CLI resolve a linha canônica a partir da
``URL de referência`` do repositório (services/preflight.py).

A conferência do que foi gravado é do ``verificar_tarefas_de_rascunhos.py``, que lê
o log desta execução (o JSON do fim da saída).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")

DATABASE_ID = "30296e2d-cd39-4cf3-8bbd-3fb2f53c0195"
AREA_PRODUTOS = "1fe91f95-497e-8123-92b5-e7afa33f97e1"
ORIGEM = "Projetos"
AGENTE = "Escritor de tasks"
MARCA_DO_CORPO = f"Agente: {AGENTE} · Repositório"

# ``projeto``: a linha do database GITHUB que o preflight da CLI põe em "Projeto" a partir
# da URL. Vazio quando o repositório não tem linha lá (as tarefas antigas do Audiofy também
# não têm Projeto); o verificador só confere o Projeto de quem tem.
REPOSITORIOS: dict[str, dict[str, str]] = {
    "Felixo-AI-Core": {
        "url": "https://github.com/Felipe-Alcantara/Felixo-AI-Core",
        "prefixo": "Felixo AI Core/",
        "projeto": "38e91f95-497e-81d9-8770-fd20886c9232",
    },
    "Felixo-Notion-MCP": {
        "url": "https://github.com/Felipe-Alcantara/Felixo-Notion-MCP",
        "prefixo": "Felixo Notion MCP/",
        "projeto": "38e91f95-497e-8165-a222-d9a5c1bf6467",
    },
    "Openia": {
        "url": "https://github.com/Felipe-Alcantara/Openia",
        "prefixo": "Openia/",
        "projeto": "38e91f95-497e-819d-b312-df58f3aac3b7",
    },
    "Audiofy-Content-AI": {
        "url": "https://github.com/Felipe-Alcantara/Audiofy-Content-AI",
        "prefixo": "Audiofy Content AI/",
        "projeto": "",
    },
    "SoundScraper-soundcloud_track_scraper_downloader": {
        "url": (
            "https://github.com/Felipe-Alcantara/"
            "SoundScraper-soundcloud_track_scraper_downloader"
        ),
        "prefixo": "SoundScraper/",
        "projeto": "38e91f95-497e-81e9-9196-d21d5dbd50d0",
    },
}
COLUNAS_RELACAO = ("Subtarefas relacionadas", "Bloqueada por")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CAMPOS_OBRIGATORIOS = ("chave", "anotacao", "titulo", "etapa", "esforco", "prioridade", "tipo")
LIMITE_ROTULO_TABELA = 60


@dataclass
class Rascunho:
    chave: str
    anotacao: str
    titulo: str
    etapa: str
    esforco: str
    prioridade: str
    tipos: list[str]
    fontes: str
    repositorio: str
    corpo: str
    relacoes: list[dict[str, str]] = field(default_factory=list)
    commit: str = ""


@dataclass(frozen=True)
class Sessao:
    """O que vai no cabeçalho de toda tarefa do lote: quando e com o que ela foi aberta."""

    data: str
    inicio: str
    fim: str
    modelo: str = "Claude Code"
    # Commit lido de cada repositório; o ``commit`` do rascunho, quando houver, vence.
    commits: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Aresta:
    """Uma ligação já resolvida para IDs: ``a`` é a dona da coluna."""

    a: str
    b: str
    coluna: str
    motivo: str


class Erro(RuntimeError):
    """Falha que interrompe o lote com mensagem legível."""


TRABALHADORES = 6
_trava_cache = threading.Lock()


def em_paralelo(funcao: Callable[[T], R], itens: Iterable[T], etapa: str) -> list[R]:
    """Roda ``funcao`` em cada item com TRABALHADORES threads (cada chamada é um processo
    ``notion-tasks``). Falhas não param os outros itens: são juntadas e levantadas no fim
    da etapa — o lote é idempotente, então rodar de novo completa o que faltou."""

    lista = list(itens)
    resultados: list[Any] = [None] * len(lista)
    falhas: list[str] = []

    def rodar(indice: int) -> None:
        try:
            resultados[indice] = funcao(lista[indice])
        except Exception as erro:  # noqa: BLE001 — a mensagem vai inteira para o relatório
            falhas.append(f"{etapa} #{indice}: {erro}")

    with ThreadPoolExecutor(max_workers=TRABALHADORES) as executor:
        list(executor.map(rodar, range(len(lista))))
    if falhas:
        raise Erro(f"{len(falhas)} falha(s) na etapa '{etapa}':\n- " + "\n- ".join(falhas))
    return resultados


def executar(perfil: str, *argumentos: str) -> dict[str, Any]:
    resultado = subprocess.run(
        ["notion-tasks", "--json", "--perfil", perfil, *argumentos],
        check=False,
        capture_output=True,
        # A CLI responde JSON em UTF-8; sem isto, no Windows o pai leria em cp1252.
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    try:
        resposta = json.loads(resultado.stdout)
    except json.JSONDecodeError as erro:
        detalhe = resultado.stderr.strip() or resultado.stdout.strip()
        raise Erro(f"Saída não JSON de '{argumentos[0]}': {detalhe[:800]}") from erro
    if resultado.returncode != 0 or not resposta.get("ok"):
        raise Erro(
            f"'{' '.join(argumentos[:2])}' falhou: "
            f"{json.dumps(resposta, ensure_ascii=False)[:1500]}"
        )
    return resposta


def com_markdown_temporario(conteudo: str) -> str:
    arquivo = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False)
    with arquivo:
        arquivo.write(conteudo)
    return arquivo.name


def escrever_markdown(perfil: str, page_id: str, markdown: str) -> None:
    arquivo = com_markdown_temporario(markdown)
    try:
        executar(perfil, "escrever", page_id, "--arquivo-md", arquivo)
    finally:
        os.unlink(arquivo)


def sem_hifens(page_id: str) -> str:
    return page_id.replace("-", "")


def link(page_id: str) -> str:
    return f"https://app.notion.com/p/{sem_hifens(page_id)}"


# --------------------------------------------------------------------------- leitura


def carregar_rascunhos(pasta: Path, so: set[str] | None) -> list[Rascunho]:
    rascunhos: list[Rascunho] = []
    for caminho_json in sorted(pasta.glob("*.json")):
        dados = json.loads(caminho_json.read_text(encoding="utf-8-sig"))
        faltando = [campo for campo in CAMPOS_OBRIGATORIOS if not dados.get(campo)]
        if faltando:
            raise Erro(f"{caminho_json.name}: faltam os campos {faltando}")
        if dados["chave"] != caminho_json.stem:
            raise Erro(f"{caminho_json.name}: 'chave' ({dados['chave']}) difere do nome do arquivo")
        if so and dados["chave"] not in so:
            continue
        caminho_md = caminho_json.with_suffix(".md")
        if not caminho_md.exists():
            raise Erro(f"{caminho_json.name}: falta o corpo {caminho_md.name}")
        tipos = dados["tipo"] if isinstance(dados["tipo"], list) else [dados["tipo"]]
        rascunhos.append(
            Rascunho(
                chave=dados["chave"],
                anotacao=dados["anotacao"],
                titulo=dados["titulo"].strip(),
                etapa=dados["etapa"],
                esforco=dados["esforco"],
                prioridade=dados["prioridade"],
                tipos=[str(t).strip() for t in tipos],
                fontes=dados.get("fontes", "").strip(),
                repositorio=dados.get("repositorio") or "Felixo-AI-Core",
                corpo=caminho_md.read_text(encoding="utf-8-sig").strip(),
                relacoes=list(dados.get("relacoes") or []),
                commit=str(dados.get("commit") or "").strip(),
            )
        )
    if not rascunhos:
        raise Erro(f"Nenhum rascunho em {pasta}")
    return rascunhos


def opcoes_do_schema(perfil: str) -> dict[str, set[str]]:
    resposta = executar(perfil, "schema", DATABASE_ID)
    dados = resposta.get("dados", resposta)
    return {
        coluna["nome"]: set(coluna.get("opcoes") or [])
        for coluna in dados.get("colunas", [])
        if coluna.get("opcoes")
    }


def titulos_existentes(perfil: str) -> dict[str, str]:
    dados = executar(perfil, "linhas", DATABASE_ID).get("dados", {})
    encontrados: dict[str, str] = {}
    for linha in dados.get("linhas", []):
        titulo, identificador = linha.get("titulo"), linha.get("id")
        if isinstance(titulo, str) and isinstance(identificador, str):
            encontrados[titulo.strip()] = identificador
    return encontrados


def validar(rascunhos: list[Rascunho], opcoes: dict[str, set[str]]) -> list[str]:
    problemas: list[str] = []
    chaves = {r.chave for r in rascunhos}
    vistos: dict[str, str] = {}
    regras = (("Etapa", "etapa"), ("Esforço", "esforco"), ("Prioridade", "prioridade"))
    for r in rascunhos:
        if r.titulo in vistos:
            problemas.append(f"{r.chave}: título repetido de {vistos[r.titulo]}")
        vistos[r.titulo] = r.chave
        for coluna, atributo in regras:
            valor = getattr(r, atributo)
            if valor not in opcoes.get(coluna, set()):
                problemas.append(f"{r.chave}: {coluna}='{valor}' não é aceito")
        for tipo in r.tipos:
            if tipo not in opcoes.get("Tipo", set()):
                problemas.append(f"{r.chave}: Tipo='{tipo}' não é aceito")
        if r.repositorio not in REPOSITORIOS:
            problemas.append(f"{r.chave}: repositório '{r.repositorio}' desconhecido")
        if "## Tarefas relacionadas" in r.corpo:
            problemas.append(f"{r.chave}: o corpo não deve trazer 'Tarefas relacionadas'")
        for relacao in r.relacoes:
            alvo, coluna = relacao.get("alvo", ""), relacao.get("coluna", "")
            if coluna not in COLUNAS_RELACAO:
                problemas.append(f"{r.chave}: coluna de relação '{coluna}' não permitida")
            if not relacao.get("motivo"):
                problemas.append(f"{r.chave}: relação com {alvo} sem motivo")
            if alvo.startswith("chave:"):
                if alvo[6:] not in chaves:
                    problemas.append(f"{r.chave}: relação para chave inexistente {alvo}")
                elif alvo[6:] == r.chave:
                    problemas.append(f"{r.chave}: relação consigo mesma")
            elif not UUID.match(alvo):
                problemas.append(f"{r.chave}: alvo '{alvo}' não é ID nem chave:")
    return problemas


# --------------------------------------------------------------------------- corpo


def sem_prefixo(titulo: str) -> str:
    for repo in REPOSITORIOS.values():
        if titulo.startswith(repo["prefixo"]):
            return titulo[len(repo["prefixo"]):]
    return titulo


def rotulo_curto(titulo: str) -> str:
    """Rótulo para célula de tabela: o trecho depois do travessão, cortado na palavra."""

    texto = sem_prefixo(titulo).split(" — ", 1)[-1]
    if len(texto) <= LIMITE_ROTULO_TABELA:
        return texto
    corte = texto[:LIMITE_ROTULO_TABELA].rsplit(" ", 1)[0].rstrip(",;:")
    if corte.count("(") > corte.count(")"):
        # Não deixar parêntese aberto dentro do texto do link.
        corte = corte[: corte.rfind("(")].rstrip(" ,;:")
    return f"{corte}…"


def resolver_chaves(markdown: str, destinos: dict[str, tuple[str, str]]) -> tuple[str, list[str]]:
    """Troca `chave:x`, `x` e chave:x (de rascunhos conhecidos) por links clicáveis.

    Dentro de linha de tabela o rótulo é curto; fora, é o título sem o prefixo do
    projeto. Devolve o texto e as chaves citadas que ficaram sem destino.
    """

    padrao = re.compile(
        r"`chave:([a-z0-9][a-z0-9-]*)`|`([a-z0-9][a-z0-9-]*)`|(?<![\w/`-])chave:([a-z0-9][a-z0-9-]*)"
    )
    sem_destino: list[str] = []
    linhas: list[str] = []
    for linha in markdown.split("\n"):
        em_tabela = linha.lstrip().startswith("|")

        def trocar(m: re.Match[str], em_tabela: bool = em_tabela) -> str:
            chave = m.group(1) or m.group(2) or m.group(3)
            if chave not in destinos:
                if m.group(1) or m.group(3):
                    sem_destino.append(chave)
                return m.group(0)
            page_id, titulo = destinos[chave]
            rotulo = rotulo_curto(titulo) if em_tabela else sem_prefixo(titulo)
            rotulo = rotulo.replace("`", "").replace("[", "(").replace("]", ")")
            return f"[{rotulo}]({link(page_id)})"

        linhas.append(padrao.sub(trocar, linha))
    return "\n".join(linhas), sem_destino


def cabecalho(r: Rascunho, sessao: Sessao) -> str:
    repo = REPOSITORIOS[r.repositorio]
    commit = r.commit or sessao.commits.get(r.repositorio, "")
    lido = f"lido em `main`, commit `{commit}`" if commit else "lido pelo GitHub"
    return "\n\n".join(
        [
            "---",
            f"### [{sessao.inicio}–{sessao.fim}] Agente: {AGENTE} · Repositório: {r.repositorio}",
            f"- **Agente:** {AGENTE} ({sessao.modelo})",
            f"- **Repositório / diretório:** {r.repositorio} — `{repo['url']}` ({lido})",
            f"- **Task:** aberta a partir das anotações que o Felipe enviou em {sessao.data} "
            f"ao canvas (anotação \"{r.anotacao}\")",
            f"- **Início:** {sessao.data} {sessao.inicio} · **Fim:** {sessao.data} {sessao.fim} · "
            "**Duração:** registro de abertura",
            "- **Trilha:** registro de tarefa (somente leitura: código, histórico do git, "
            "`--help` das CLIs e pesquisa na web; o trabalho descrito não foi executado)",
            "- **Commits:** nenhum",
            "- **Deploy:** não se aplica à abertura",
            f"- **Fontes e referências:** {r.fontes or 'ver Evidência de origem'}",
            "---",
        ]
    )


def corpo_completo(
    r: Rascunho, destinos: dict[str, tuple[str, str]], sessao: Sessao
) -> tuple[str, list[str]]:
    return resolver_chaves(cabecalho(r, sessao) + "\n\n" + r.corpo + "\n", destinos)


# --------------------------------------------------------------------------- escrita


def argumentos_criar(r: Rascunho, dry_run: bool) -> list[str]:
    argumentos = [
        "criar",
        r.titulo,
        "--status",
        r.etapa,
        "--duracao",
        r.esforco,
        "--area",
        AREA_PRODUTOS,
        "--set",
        f"Prioridade={r.prioridade}",
        "--set",
        f"Tipo={','.join(r.tipos)}",
        "--set",
        f"Origem={ORIGEM}",
        "--set",
        f"Repositório={r.repositorio}",
        "--set",
        f"URL de referência={REPOSITORIOS[r.repositorio]['url']}",
    ]
    if dry_run:
        argumentos.append("--dry-run")
    return argumentos


def garantir_tarefa(
    perfil: str, r: Rascunho, existentes: dict[str, str], dry_run: bool
) -> str | None:
    if r.titulo in existentes:
        print(f"[pula] {r.chave}: já existe ({existentes[r.titulo]})")
        return existentes[r.titulo]
    resposta = executar(perfil, *argumentos_criar(r, dry_run))
    dados = resposta.get("dados", {})
    if dry_run:
        preflight = dados.get("preflight", {})
        projeto = (preflight.get("projeto") or {}).get("id")
        print(f"[plano] {r.chave}: projeto={projeto} avisos={preflight.get('avisos')}")
        return None
    page_id = dados.get("id")
    if not isinstance(page_id, str):
        raise Erro(f"{r.chave}: a criação não devolveu id: {resposta}")
    existentes[r.titulo] = page_id
    print(f"[cria] {r.chave}: {page_id}")
    return page_id


def garantir_corpo(
    perfil: str,
    r: Rascunho,
    page_id: str,
    destinos: dict[str, tuple[str, str]],
    sessao: Sessao,
    cache: dict[str, dict[str, Any]],
) -> None:
    markdown_atual = ler_pagina(perfil, page_id, cache).get("markdown") or ""
    if MARCA_DO_CORPO in markdown_atual:
        print(f"[corpo] {r.chave}: já escrito")
        return
    corpo, _ = corpo_completo(r, destinos, sessao)
    escrever_markdown(perfil, page_id, corpo)
    esquecer_pagina(page_id, cache)
    print(f"[corpo] {r.chave}: escrito ({len(corpo)} caracteres)")


def resolver_arestas(rascunhos: list[Rascunho], ids: dict[str, str]) -> list[Aresta]:
    """Converte ``chave:`` em ID e tira duplicatas (a simétrica vale nos dois sentidos)."""

    arestas: dict[tuple[str, ...], Aresta] = {}
    for r in rascunhos:
        for relacao in r.relacoes:
            alvo = relacao["alvo"]
            b = ids[alvo[6:]] if alvo.startswith("chave:") else alvo
            a = ids[r.chave]
            coluna = relacao["coluna"]
            if coluna == "Subtarefas relacionadas":
                chave_aresta: tuple[str, ...] = (coluna, *sorted((a, b)))
            else:
                chave_aresta = (coluna, a, b)
            arestas.setdefault(chave_aresta, Aresta(a, b, coluna, relacao["motivo"].strip()))
    return list(arestas.values())


def itens_por_pagina(arestas: list[Aresta]) -> dict[str, list[tuple[str, str, str]]]:
    """Para cada página, a lista de (outra_ponta, rótulo, motivo) a citar no corpo."""

    itens: dict[str, list[tuple[str, str, str]]] = {}
    for aresta in arestas:
        if aresta.coluna == "Bloqueada por":
            itens.setdefault(aresta.a, []).append((aresta.b, "Bloqueada por", aresta.motivo))
            itens.setdefault(aresta.b, []).append((aresta.a, "Bloqueia", aresta.motivo))
        else:
            itens.setdefault(aresta.a, []).append((aresta.b, "", aresta.motivo))
            itens.setdefault(aresta.b, []).append((aresta.a, "", aresta.motivo))
    return itens


def ler_pagina(perfil: str, page_id: str, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    with _trava_cache:
        if page_id in cache:
            return cache[page_id]
    dados = executar(perfil, "conteudo", page_id).get("dados", {})
    with _trava_cache:
        cache[page_id] = dados
    return dados


def esquecer_pagina(page_id: str, cache: dict[str, dict[str, Any]]) -> None:
    with _trava_cache:
        cache.pop(page_id, None)


def rodadas_sem_pagina_repetida(arestas: list[Aresta]) -> list[list[Aresta]]:
    """Agrupa as ligações em rodadas em que nenhuma página aparece duas vezes.

    ``relacionar`` lê a lista de relações de uma ponta e a regrava inteira; duas
    ligações tocando a mesma página ao mesmo tempo poderiam apagar uma à outra.
    """

    rodadas: list[tuple[set[str], list[Aresta]]] = []
    for aresta in arestas:
        for paginas, lista in rodadas:
            if aresta.a not in paginas and aresta.b not in paginas:
                paginas.update((aresta.a, aresta.b))
                lista.append(aresta)
                break
        else:
            rodadas.append(({aresta.a, aresta.b}, [aresta]))
    return [lista for _, lista in rodadas]


def titulo_da_pagina(pagina: dict[str, Any]) -> str:
    propriedades = pagina.get("propriedades") or {}
    return str(propriedades.get("Tarefa") or pagina.get("titulo") or "(sem título)")


def ultima_secao(markdown: str) -> str:
    secoes = [linha for linha in markdown.splitlines() if linha.startswith("## ")]
    return secoes[-1] if secoes else ""


def acrescentar_secoes(
    perfil: str,
    itens: dict[str, list[tuple[str, str, str]]],
    cache: dict[str, dict[str, Any]],
    destinos: dict[str, tuple[str, str]],
) -> None:
    def uma_pagina(entrada: tuple[str, list[tuple[str, str, str]]]) -> None:
        page_id, lista = entrada
        esquecer_pagina(page_id, cache)  # reler: o corpo pode ter mudado nesta execução
        markdown = ler_pagina(perfil, page_id, cache).get("markdown") or ""
        faltando = [item for item in lista if sem_hifens(item[0]) not in markdown]
        if not faltando:
            print(f"[secao] {page_id}: links já presentes")
            return
        linhas: list[str] = []
        if "Tarefas relacionadas" not in ultima_secao(markdown):
            linhas.append("## Tarefas relacionadas")
        for outra, rotulo, motivo in faltando:
            titulo = titulo_da_pagina(ler_pagina(perfil, outra, cache))
            prefixo = f"**{rotulo}:** " if rotulo else ""
            motivo_resolvido, _ = resolver_chaves(motivo, destinos)
            linhas.append(f"- {prefixo}[{titulo}]({link(outra)}) — {motivo_resolvido}")
        escrever_markdown(perfil, page_id, "\n\n".join(linhas) + "\n")
        esquecer_pagina(page_id, cache)
        print(f"[secao] {page_id}: +{len(faltando)} link(s)")

    em_paralelo(uma_pagina, itens.items(), "seções de tarefas relacionadas")


# --------------------------------------------------------------------------- principal


def commits_da_linha_de_comando(valores: list[str]) -> dict[str, str]:
    """``["Felixo-AI-Core=d5ce92e"]`` → ``{"Felixo-AI-Core": "d5ce92e"}``, conferindo o nome."""

    commits: dict[str, str] = {}
    for valor in valores:
        repositorio, separador, commit = valor.partition("=")
        if not separador or not commit.strip():
            raise Erro(f"--commit '{valor}': use Repositório=commit")
        if repositorio not in REPOSITORIOS:
            raise Erro(f"--commit '{valor}': repositório desconhecido ({', '.join(REPOSITORIOS)})")
        commits[repositorio] = commit.strip()
    return commits


def main() -> int:
    # Com ``python -I`` o PYTHONIOENCODING é ignorado; sem isto o log sai em cp1252 no Windows.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    agora = dt.datetime.now()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--perfil", default="felipe")
    parser.add_argument(
        "--data", default=agora.strftime("%d/%m/%Y"), help="data das anotações (DD/MM/AAAA)"
    )
    parser.add_argument(
        "--inicio", default=agora.strftime("%H:%M"), help="hora em que a sessão começou"
    )
    parser.add_argument(
        "--commit",
        action="append",
        default=[],
        metavar="REPOSITORIO=COMMIT",
        help="commit lido de cada repositório, para o cabeçalho (repetível)",
    )
    parser.add_argument("--modelo", default="Claude Code", help="quem escreveu, no cabeçalho")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--so", nargs="*", help="limita o lote a estas chaves")
    parser.add_argument("--paralelo", type=int, default=TRABALHADORES, help="chamadas simultâneas")
    args = parser.parse_args()
    globals()["TRABALHADORES"] = max(1, args.paralelo)
    commits = commits_da_linha_de_comando(args.commit)

    rascunhos = carregar_rascunhos(args.pasta, set(args.so) if args.so else None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futuro_schema = executor.submit(opcoes_do_schema, args.perfil)
        futuro_titulos = executor.submit(titulos_existentes, args.perfil)
        problemas = validar(rascunhos, futuro_schema.result())
        existentes = futuro_titulos.result()
    if problemas:
        raise Erro("Rascunhos inválidos — nada foi escrito:\n- " + "\n- ".join(problemas))
    cache: dict[str, dict[str, Any]] = {}
    # Toda tarefa existente citada precisa responder antes da primeira escrita.
    alvos_existentes = sorted(
        {
            rel["alvo"]
            for r in rascunhos
            for rel in r.relacoes
            if not rel["alvo"].startswith("chave:")
        }
    )
    em_paralelo(
        lambda alvo: ler_pagina(args.perfil, alvo, cache),
        alvos_existentes,
        "ler tarefas existentes",
    )
    print(f"[ok] {len(alvos_existentes)} tarefa(s) existente(s) citada(s) respondem")

    sessao = Sessao(
        data=args.data,
        inicio=args.inicio,
        fim=dt.datetime.now().strftime("%H:%M"),
        modelo=args.modelo,
        commits=commits,
    )

    if args.dry_run:
        falsos = {r.chave: ("00000000-0000-0000-0000-000000000000", r.titulo) for r in rascunhos}
        em_paralelo(
            lambda r: garantir_tarefa(args.perfil, r, existentes, dry_run=True),
            rascunhos,
            "preflight",
        )
        for r in rascunhos:
            _, sem_destino = corpo_completo(r, falsos, sessao)
            if sem_destino:
                print(f"[aviso] {r.chave}: chaves citadas sem rascunho: {sorted(set(sem_destino))}")
        print(f"[dry-run] {len(rascunhos)} rascunho(s) válidos; nada foi escrito.")
        return 0

    criados = em_paralelo(
        lambda r: garantir_tarefa(args.perfil, r, existentes, dry_run=False),
        rascunhos,
        "criar linhas",
    )
    ids = {r.chave: page_id for r, page_id in zip(rascunhos, criados, strict=True) if page_id}
    destinos = {r.chave: (ids[r.chave], r.titulo) for r in rascunhos}
    em_paralelo(
        lambda r: garantir_corpo(args.perfil, r, ids[r.chave], destinos, sessao, cache),
        rascunhos,
        "escrever corpos",
    )

    arestas = resolver_arestas(rascunhos, ids)
    # Reexecução barata: ligação já gravada nos dois lados não chama o relacionar de novo.
    paginas = sorted({a.a for a in arestas} | {a.b for a in arestas})
    for pid in paginas:
        esquecer_pagina(pid, cache)
    em_paralelo(
        lambda pid: ler_pagina(args.perfil, pid, cache), paginas, "reler pontas das ligações"
    )

    def ja_ligada(aresta: Aresta) -> bool:
        pa = cache[aresta.a].get("propriedades") or {}
        pb = cache[aresta.b].get("propriedades") or {}
        if aresta.coluna == "Subtarefas relacionadas":
            return aresta.b in (pa.get(aresta.coluna) or []) and aresta.a in (
                pb.get(aresta.coluna) or []
            )
        return aresta.b in (pa.get("Bloqueada por") or []) and aresta.a in (
            pb.get("Bloqueia") or []
        )

    pendentes = [aresta for aresta in arestas if not ja_ligada(aresta)]
    rodadas = rodadas_sem_pagina_repetida(pendentes)
    print(
        f"[relaciona] {len(arestas)} ligação(ões); {len(arestas) - len(pendentes)} já gravada(s); "
        f"{len(pendentes)} em {len(rodadas)} rodada(s) sem página repetida"
    )

    def ligar(aresta: Aresta) -> None:
        executar(args.perfil, "relacionar", aresta.a, aresta.b, "--coluna", aresta.coluna)
        print(f"[relaciona] {aresta.coluna}: {aresta.a} -> {aresta.b}")

    for numero, rodada in enumerate(rodadas, start=1):
        em_paralelo(ligar, rodada, f"relações, rodada {numero}")
    acrescentar_secoes(args.perfil, itens_por_pagina(arestas), cache, destinos)

    resumo = {
        r.chave: {"id": ids[r.chave], "titulo": r.titulo, "url": link(ids[r.chave])}
        for r in rascunhos
    }
    print(json.dumps({"tarefas": resumo, "ligacoes": len(arestas)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Erro as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        raise SystemExit(1) from erro
