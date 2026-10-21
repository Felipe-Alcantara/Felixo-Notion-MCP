"""Caso de uso: o **mapa do workspace** em JSON e num relatório HTML navegável.

Era o par ``examples/coletar_mapa.py`` + ``examples/gerar_arvore_html.py``, que o menu
rodava por ``subprocess``; fora do checkout (wheel, pipx, binário) a pasta ``examples/``
não existe e a opção quebrava. Agora é parte do pacote:

* :func:`coletar_mapa` — varre o que a integração enxerga, reconstrói a árvore
  (:func:`~felixo_notion_mcp.services.inventory.construir_inventario`) e conta as
  linhas de cada database (uma chamada por database, o trecho mais lento);
* :func:`gerar_html` — página única, sem dependência externa: resumo, duplicatas
  por nome, databases por tamanho, órfãos e a árvore expansível;
* :func:`gravar_mapa` — grava o JSON e/ou o HTML.

O mapa traz IDs e títulos reais do workspace: guarde-o em lugar privado.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from felixo_notion_mcp.core.exceptions import NotionSyncError
from felixo_notion_mcp.services.inventory import Inventario, construir_inventario

if TYPE_CHECKING:
    from felixo_notion_mcp.integrations.notion_client import NotionClient

Mapa = dict[str, Any]


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from felixo_notion_mcp.integrations.notion import criar_cliente

    return criar_cliente()


# -- Coleta -------------------------------------------------------------------


def _contar_linhas(cliente: NotionClient, database_ids: list[str]) -> dict[str, int]:
    """Linhas de cada database; sem permissão ou outra falha, ``-1`` e a coleta segue."""

    contagem: dict[str, int] = {}
    for database_id in database_ids:
        try:
            contagem[database_id] = len(cliente.consultar_database(database_id, buscar_todos=True))
        except NotionSyncError:
            contagem[database_id] = -1
    return contagem


def coletar_mapa(*, query: str | None = None, cliente: NotionClient | None = None) -> Mapa:
    """O mapa do workspace como dicionário serializável em JSON.

    Args:
        query: Filtro opcional da busca (``/search``); sem ele, tudo o que é visível.
        cliente: Cliente Notion opcional (injeção para testes).

    Returns:
        ``total_paginas``, ``total_databases``, ``itens`` (id, tipo, título, pai, url),
        ``linhas_por_database`` (``-1`` quando a contagem falhou), ``duplicatas``
        (título → IDs) e ``orfaos`` (IDs cujo pai não está visível).
    """

    cliente = cliente or _cliente_padrao()
    inventario = construir_inventario(cliente.buscar(query=query, buscar_todos=True))
    return montar_mapa(inventario, cliente=cliente)


def montar_mapa(inventario: Inventario, *, cliente: NotionClient) -> Mapa:
    """O mapa de um inventário já construído (conta as linhas de cada database).

    Para quem já fez a busca (ex.: o ``mapear`` da CLI, que também resume o
    inventário) e não quer varrer o workspace de novo.
    """

    database_ids = [i.id for i in inventario.itens.values() if i.tipo == "database"]
    return {
        "total_paginas": inventario.total_paginas,
        "total_databases": inventario.total_databases,
        "itens": [asdict(item) for item in inventario.itens.values()],
        "linhas_por_database": _contar_linhas(cliente, database_ids),
        "duplicatas": {
            titulo: [item.id for item in itens]
            for titulo, itens in inventario.duplicatas.items()
        },
        "orfaos": [item.id for item in inventario.orfaos],
    }


def gravar_mapa(
    mapa: Mapa, *, json_saida: Path | None = None, html: Path | None = None
) -> dict[str, str]:
    """Grava o mapa em JSON e/ou o relatório HTML; devolve os caminhos gravados."""

    gravados: dict[str, str] = {}
    if json_saida is not None:
        json_saida.write_text(json.dumps(mapa, ensure_ascii=False, indent=2), encoding="utf-8")
        gravados["json"] = str(json_saida)
    if html is not None:
        html.write_text(gerar_html(mapa), encoding="utf-8")
        gravados["html"] = str(html)
    return gravados


# -- Relatório HTML -----------------------------------------------------------


def _indexar(mapa: Mapa) -> tuple[dict[str, dict], dict[str, list[str]], list[str]]:
    """Devolve (itens por id, filhos por id-pai, ids raiz), em ordem alfabética."""

    itens = {item["id"]: item for item in mapa["itens"]}
    filhos: dict[str, list[str]] = {}
    raizes: list[str] = []
    for item in mapa["itens"]:
        pai = item.get("parent_id")
        if pai and pai in itens:
            filhos.setdefault(pai, []).append(item["id"])
        else:
            raizes.append(item["id"])

    def chave(item_id: str) -> str:
        return itens[item_id]["titulo"].lower()

    for lista in filhos.values():
        lista.sort(key=chave)
    raizes.sort(key=chave)
    return itens, filhos, raizes


def _render_no(
    item_id: str,
    itens: dict[str, dict],
    filhos: dict[str, list[str]],
    linhas_db: dict[str, int],
) -> str:
    item = itens[item_id]
    titulo = html_lib.escape(item["titulo"])
    is_db = item["tipo"] == "database"
    icone = "🗃️" if is_db else "📄"

    sufixo = ""
    if is_db:
        n = linhas_db.get(item_id, -1)
        if n >= 0:
            sufixo = f' <span class="badge">{n} linhas</span>'
        else:
            sufixo = ' <span class="badge sem">? linhas</span>'

    link = ""
    if item.get("url"):
        link = f' <a href="{html_lib.escape(item["url"])}" target="_blank" class="link">↗</a>'

    sub = filhos.get(item_id, [])
    rotulo = f"{icone} {titulo}{sufixo}{link}"
    if not sub:
        return f'<li class="leaf">{rotulo}</li>'

    filhos_html = "\n".join(_render_no(f, itens, filhos, linhas_db) for f in sub)
    return (
        f"<li><details><summary>{rotulo} "
        f'<span class="count">({len(sub)})</span></summary>\n'
        f"<ul>\n{filhos_html}\n</ul></details></li>"
    )


def _secao_duplicatas(mapa: Mapa) -> str:
    dups = mapa.get("duplicatas", {})
    if not dups:
        return "<p>Nenhuma duplicata por nome. 🎉</p>"
    linhas = [
        f"<li><b>{html_lib.escape(titulo)}</b> — {len(ids)} itens</li>"
        for titulo, ids in sorted(dups.items(), key=lambda kv: -len(kv[1]))
    ]
    return f"<ul>{''.join(linhas)}</ul>"


def _secao_ranking(mapa: Mapa, itens: dict[str, dict]) -> str:
    linhas_db = mapa.get("linhas_por_database", {})
    ranking = sorted(
        ((itens[i]["titulo"], n) for i, n in linhas_db.items() if i in itens),
        key=lambda t: -t[1],
    )
    if not ranking:
        return "<p>Sem databases.</p>"
    linhas = [
        f"<tr><td>{html_lib.escape(nome)}</td><td>{n if n >= 0 else '?'}</td></tr>"
        for nome, n in ranking
    ]
    return f"<table><tr><th>Database</th><th>Linhas</th></tr>{''.join(linhas)}</table>"


def _secao_orfaos(mapa: Mapa, itens: dict[str, dict]) -> str:
    orfaos = [i for i in mapa.get("orfaos", []) if i in itens]
    if not orfaos:
        return "<p>Nenhum órfão. 🎉</p>"
    linhas = [f"<li>{html_lib.escape(itens[i]['titulo'])}</li>" for i in orfaos]
    return f"<ul>{''.join(linhas)}</ul>"


def gerar_html(mapa: Mapa) -> str:
    """Relatório HTML autocontido do mapa (abra no navegador)."""

    itens, filhos, raizes = _indexar(mapa)
    linhas_db = mapa.get("linhas_por_database", {})
    arvore = "\n".join(_render_no(r, itens, filhos, linhas_db) for r in raizes)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mapa do Workspace Notion</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: system-ui, sans-serif; background:#1a1a1a; color:#e0e0e0;
         margin:0; padding:2rem; line-height:1.5; }}
  h1 {{ margin-top:0; }}
  .resumo {{ display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1.5rem; }}
  .card {{ background:#252525; border:1px solid #3a3a3a; border-radius:8px;
          padding:.75rem 1.25rem; }}
  .card b {{ font-size:1.5rem; display:block; color:#8a7fff; }}
  details {{ margin:.15rem 0; }}
  summary {{ cursor:pointer; padding:.1rem .25rem; border-radius:4px; }}
  summary:hover {{ background:#2d2d2d; }}
  ul {{ list-style:none; padding-left:1.25rem; border-left:1px solid #333;
       margin:.1rem 0; }}
  li.leaf {{ padding:.1rem .25rem; }}
  .badge {{ background:#2d4a2d; color:#9fe09f; border-radius:10px;
           padding:0 .5rem; font-size:.75rem; }}
  .badge.sem {{ background:#4a2d2d; color:#e09f9f; }}
  .count {{ color:#888; font-size:.8rem; }}
  .link {{ text-decoration:none; opacity:.6; }}
  .link:hover {{ opacity:1; }}
  section {{ background:#222; border:1px solid #333; border-radius:8px;
            padding:1rem 1.5rem; margin:1rem 0; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ text-align:left; padding:.3rem .6rem; border-bottom:1px solid #333; }}
  details.dest > summary {{ font-weight:bold; font-size:1.1rem; }}
</style>
</head>
<body>
<h1>🗺️ Mapa do Workspace Notion</h1>
<div class="resumo">
  <div class="card"><b>{mapa["total_paginas"]}</b> páginas</div>
  <div class="card"><b>{mapa["total_databases"]}</b> databases</div>
  <div class="card"><b>{len(mapa.get("duplicatas", {}))}</b> nomes duplicados</div>
  <div class="card"><b>{len(mapa.get("orfaos", []))}</b> órfãos</div>
</div>

<section><details class="dest" open><summary>📑 Duplicatas por nome</summary>
{_secao_duplicatas(mapa)}</details></section>

<section><details class="dest"><summary>📊 Databases por tamanho</summary>
{_secao_ranking(mapa, itens)}</details></section>

<section><details class="dest"><summary>🔗 Órfãos (parent não visível)</summary>
{_secao_orfaos(mapa, itens)}</details></section>

<h2>🌳 Árvore do workspace</h2>
<ul>
{arvore}
</ul>
</body>
</html>
"""
