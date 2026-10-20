"""Caso de uso: gravar artigos num database de biblioteca sem duplicar nem apagar.

Cada artigo traz título, propriedades em valores simples (texto, número, lista),
corpo em Markdown e, opcionalmente, anexos (``{coluna de arquivos: caminho}``) e
aparência (``{"icone", "capa"}``). A ``URL da fonte`` identifica o artigo:

- linha que ainda não existe é criada com propriedades e corpo;
- linha que já existe só ganha o que está vazio; multi_select recebe os valores que
  faltam; o corpo é escrito só se a página estiver sem corpo;
- anexos sobem só com a coluna vazia; ícone e capa que a página já tem são mantidos.

Antes de gravar, :func:`validar` confere tudo contra o schema real (coluna existe e
aceita escrita, opção de select existe ou foi liberada, URL única no lote). Rodar de
novo não repete nada. Não há HTTP aqui além do :class:`NotionClient` injetado.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from felixo_notion_mcp.domain import schema as dominio_schema
from felixo_notion_mcp.integrations.notion_client import NotionClient
from felixo_notion_mcp.services import anexos, aparencia, conteudo, propriedades

COLUNA_CHAVE = "URL da fonte"
TIPOS_COM_OPCOES = {"select", "multi_select", "status"}


@dataclass
class Artigo:
    chave: str
    titulo: str
    propriedades: dict[str, Any]
    corpo: str
    anexos: dict[str, str] = field(default_factory=dict)
    aparencia: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return str(self.propriedades.get(COLUNA_CHAVE, "")).strip()


# ---------------------------------------------------------------------------
# Regras puras
# ---------------------------------------------------------------------------


def vazio(valor: Any) -> bool:
    """Diz se uma propriedade lida do Notion está sem valor."""

    return valor is None or valor == "" or valor == [] or valor == {}


def carregar_rascunhos(pasta: Path) -> list[Artigo]:
    """Lê os pares ``<chave>.json`` + ``<chave>.md`` da pasta, em ordem de nome."""

    artigos: list[Artigo] = []
    for arquivo in sorted(Path(pasta).glob("*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        corpo_arquivo = arquivo.with_suffix(".md")
        if not corpo_arquivo.is_file():
            raise ValueError(f"{arquivo.name}: falta o corpo {corpo_arquivo.name}")
        titulo = str(dados.get("titulo", "")).strip()
        props = dados.get("propriedades")
        if not titulo or not isinstance(props, dict):
            raise ValueError(f"{arquivo.name}: precisa de 'titulo' e de 'propriedades' (objeto)")
        artigos.append(
            Artigo(
                chave=arquivo.stem,
                titulo=titulo,
                propriedades=props,
                corpo=corpo_arquivo.read_text(encoding="utf-8").strip(),
                anexos=dict(dados.get("anexos") or {}),
                aparencia={k: v for k, v in (dados.get("aparencia") or {}).items() if v},
            )
        )
    if not artigos:
        raise ValueError(f"nenhum rascunho .json em {pasta}")
    return artigos


def ler_pares(itens: Iterable[str], opcao: str) -> list[tuple[str, str]]:
    """Converte ``["Coluna=valor", ...]`` em pares ``(coluna, valor)``."""

    pares: list[tuple[str, str]] = []
    for item in itens:
        coluna, separador, valor = item.partition("=")
        if not separador or not coluna.strip() or not valor.strip():
            raise ValueError(f"{opcao} espera 'Coluna=valor', recebeu {item!r}")
        pares.append((coluna.strip(), valor.strip()))
    return pares


def ler_opcoes_novas(itens: Iterable[str]) -> dict[str, set[str]]:
    """Converte ``["Coluna=valor", ...]`` em ``{"Coluna": {"valor", ...}}``."""

    liberadas: dict[str, set[str]] = {}
    for coluna, valor in ler_pares(itens, "--opcao-nova"):
        liberadas.setdefault(coluna, set()).add(valor)
    return liberadas


def _valores(valor: Any) -> list[str]:
    return [str(v) for v in valor] if isinstance(valor, list) else [str(valor)]


def validar(
    artigos: list[Artigo],
    colunas: Mapping[str, Mapping[str, Any]],
    opcoes_novas: Mapping[str, set[str]] | None = None,
    opcoes_livres: Iterable[str] = (),
) -> list[str]:
    """Devolve a lista de problemas do lote; vazia quando dá para gravar."""

    opcoes_novas = opcoes_novas or {}
    livres = set(opcoes_livres)
    problemas: list[str] = []
    vistas: dict[str, str] = {}
    for artigo in artigos:
        if not artigo.url.startswith(("http://", "https://")):
            problemas.append(f"{artigo.chave}: '{COLUNA_CHAVE}' ausente ou não é URL")
        elif artigo.url in vistas:
            problemas.append(f"{artigo.chave}: mesma URL de {vistas[artigo.url]}")
        else:
            vistas[artigo.url] = artigo.chave
        if not artigo.corpo:
            problemas.append(f"{artigo.chave}: corpo vazio")
        for nome, valor in artigo.propriedades.items():
            coluna = colunas.get(nome)
            if coluna is None:
                problemas.append(f"{artigo.chave}: coluna inexistente {nome!r}")
                continue
            if not coluna.get("editavel", True) or coluna.get("titulo"):
                problemas.append(f"{artigo.chave}: coluna {nome!r} não aceita escrita aqui")
                continue
            tipo = coluna.get("tipo")
            if tipo == "multi_select" and not isinstance(valor, list):
                problemas.append(f"{artigo.chave}: {nome!r} é multi_select e pede uma lista")
                continue
            if tipo in TIPOS_COM_OPCOES:
                aceitas = set(coluna.get("opcoes") or []) | opcoes_novas.get(nome, set())
                for item in _valores(valor):
                    if "," in item:
                        problemas.append(f"{artigo.chave}: {nome!r} tem vírgula em {item!r}")
                    elif nome not in livres and item not in aceitas:
                        problemas.append(
                            f"{artigo.chave}: {item!r} não é opção de {nome!r} "
                            "(libere com --opcao-nova se for intencional)"
                        )
            if tipo == "number" and not isinstance(valor, (int, float)):
                problemas.append(f"{artigo.chave}: {nome!r} é number e recebeu {valor!r}")
        for nome, caminho in artigo.anexos.items():
            coluna = colunas.get(nome)
            if coluna is None or coluna.get("tipo") != "files":
                problemas.append(f"{artigo.chave}: anexo em {nome!r}, que não é coluna de arquivos")
            elif not Path(caminho).is_file():
                problemas.append(f"{artigo.chave}: arquivo do anexo não existe: {caminho}")
        extras = set(artigo.aparencia) - {"icone", "capa"}
        if extras:
            problemas.append(
                f"{artigo.chave}: aparência só aceita icone e capa, veio {sorted(extras)}"
            )
    return problemas


def completar_existente(
    desejadas: Mapping[str, Any],
    atuais: Mapping[str, Any],
    tipos: Mapping[str, str],
) -> dict[str, Any]:
    """Propriedades a gravar numa linha que já existe, sem apagar nada dela."""

    gravar: dict[str, Any] = {}
    for nome, valor in desejadas.items():
        atual = atuais.get(nome)
        if vazio(atual):
            gravar[nome] = valor
        elif tipos.get(nome) == "multi_select":
            faltando = [v for v in valor if v not in atual]
            if faltando:
                gravar[nome] = [*atual, *faltando]
    return gravar


def indexar_por_url(
    linhas: Iterable[Mapping[str, Any]], nao_completar: Iterable[tuple[str, str]] = ()
) -> dict[str, Mapping[str, Any]]:
    """``URL da fonte -> linha``, sem as linhas que batem com algum filtro."""

    filtros = list(nao_completar)
    indice: dict[str, Mapping[str, Any]] = {}
    for linha in linhas:
        props = linha["propriedades"]
        url = str(props.get(COLUNA_CHAVE) or "").strip()
        if not url:
            continue
        if any(valor in _valores(props.get(coluna) or "") for coluna, valor in filtros):
            continue
        indice[url] = linha
    return indice


def como_texto(valor: Any) -> str:
    """Valor simples do rascunho no texto que :mod:`propriedades` sabe converter."""

    return ",".join(_valores(valor)) if isinstance(valor, list) else str(valor)


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------


def _criar(artigo: Artigo, database: str, colunas: Mapping[str, Mapping[str, Any]],
           cliente: NotionClient) -> str:
    titulo = next(nome for nome, c in colunas.items() if c.get("titulo"))
    payload = {titulo: propriedades.valor_de_propriedade("title", artigo.titulo)}
    for nome, valor in artigo.propriedades.items():
        payload[nome] = propriedades.valor_de_propriedade(
            str(colunas[nome]["tipo"]), como_texto(valor)
        )
    pagina = cliente.criar_pagina(database, payload)
    page_id = str(pagina["id"])
    conteudo.escrever_conteudo(page_id, artigo.corpo, mesmo_com_database=True, cliente=cliente)
    return page_id


def _processar(artigo: Artigo, existente: Mapping[str, Any] | None, *, database: str,
               colunas: Mapping[str, Mapping[str, Any]], cliente: NotionClient,
               dry_run: bool) -> dict[str, Any]:
    tipos = {nome: str(c.get("tipo")) for nome, c in colunas.items()}
    if existente is None:
        item: dict[str, Any] = {"chave": artigo.chave, "acao": "criar", "titulo": artigo.titulo}
        pendentes = dict(artigo.anexos)
        if dry_run:
            return item | {"anexos": sorted(pendentes)}
        page_id = _criar(artigo, database, colunas, cliente)
        item["id"] = page_id
    else:
        page_id = str(existente["id"])
        atuais = existente["propriedades"]
        gravar = completar_existente(artigo.propriedades, atuais, tipos)
        escrever = not conteudo.ler_conteudo(page_id, cliente=cliente).strip()
        pendentes = {c: v for c, v in artigo.anexos.items() if vazio(atuais.get(c))}
        item = {
            "chave": artigo.chave,
            "acao": "completar" if (gravar or escrever or pendentes) else "sem_mudanca",
            "id": page_id,
            "propriedades": sorted(gravar),
            "corpo": "escrito" if escrever else "mantido (já tinha corpo)",
        }
        if dry_run:
            return item | {"anexos": sorted(pendentes)}
        if gravar:
            propriedades.editar_linha(
                page_id, {k: como_texto(v) for k, v in gravar.items()}, cliente=cliente
            )
        if escrever:
            conteudo.escrever_conteudo(
                page_id, artigo.corpo, mesmo_com_database=True, cliente=cliente
            )
    for coluna, caminho in pendentes.items():
        anexos.anexar_arquivo(page_id, caminho, propriedade=coluna, cliente=cliente)
    item["anexos"] = sorted(pendentes)
    if artigo.aparencia:
        dados = aparencia.definir_aparencia(
            page_id, icone=artigo.aparencia.get("icone"), capa=artigo.aparencia.get("capa"),
            cliente=cliente,
        )
        item["aparencia"] = {"icone": dados.get("icone"), "capa": dados.get("capa")}
    return item


def importar_artigos(
    artigos: list[Artigo],
    database: str,
    *,
    cliente: NotionClient,
    opcoes_novas: Mapping[str, set[str]] | None = None,
    opcoes_livres: Iterable[str] = (),
    nao_completar: Iterable[tuple[str, str]] = (),
    paralelo: int = 1,
    dry_run: bool = False,
    progresso: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Grava o lote; um artigo com erro não para os outros (rodar de novo completa)."""

    descricao = dominio_schema.descrever_database(cliente.get_database(database)).para_dict()
    colunas = {c["nome"]: c for c in descricao["colunas"]}
    problemas = validar(artigos, colunas, opcoes_novas, opcoes_livres)
    if problemas:
        lista = "".join(f"\n- {problema}" for problema in problemas)
        raise ValueError(f"rascunhos inválidos, nada foi gravado:{lista}")
    linhas = conteudo.listar_linhas(database, propriedades=True, cliente=cliente)
    por_url = indexar_por_url(linhas, nao_completar)

    trava = threading.Lock()
    feitos = {"n": 0}

    def rodar(artigo: Artigo) -> dict[str, Any]:
        try:
            item = _processar(artigo, por_url.get(artigo.url), database=database,
                              colunas=colunas, cliente=cliente, dry_run=dry_run)
        except Exception as erro:  # noqa: BLE001 — o motivo vai para o relatório
            item = {"chave": artigo.chave, "acao": "erro", "erro": str(erro)[:600]}
        with trava:
            feitos["n"] += 1
            if progresso:
                progresso(feitos["n"], len(artigos))
        return item

    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as executor:
        itens = list(executor.map(rodar, artigos))
    contagem: dict[str, int] = {}
    for item in itens:
        contagem[item["acao"]] = contagem.get(item["acao"], 0) + 1
    return {"database": database, "dry_run": dry_run, "contagem": contagem, "itens": itens}
