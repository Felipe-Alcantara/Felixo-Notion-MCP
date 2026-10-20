"""Caso de uso: organizar itens da biblioteca por tags e regras de categoria.

- :func:`carregar_aliases` lê uma taxonomia (grupos ``tags``, ``special_tags`` e
  ``event_series``, cada item com ``pt``, ``en`` e ``aliases``) e devolve
  ``apelido -> nome canônico``;
- :func:`normalizar_tags` troca cada tag pelo nome canônico, sem repetir;
- :func:`classificar` aplica um mapa de regras: a primeira que casar dá ícone e capa;
  Área e Genres juntam todas as que casarem (formato em ``services/mapas/*.json``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PASTA_MAPAS = Path(__file__).with_name("mapas")


def carregar_mapa(nome_ou_caminho: str | Path) -> dict[str, Any]:
    """Mapa de regras por caminho ou pelo nome de um mapa embutido (ex.: ``akitaonrails``)."""

    caminho = Path(nome_ou_caminho)
    if not caminho.is_file():
        caminho = PASTA_MAPAS / f"{nome_ou_caminho}.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_aliases(taxonomia: dict[str, Any]) -> dict[str, str]:
    """``alias -> nome canônico em português`` a partir da taxonomia do blog."""

    aliases: dict[str, str] = {}
    for grupo in ("tags", "special_tags", "event_series"):
        for chave, item in (taxonomia.get(grupo) or {}).items():
            canonico = str(item.get("pt") or chave).strip()
            for nome in [chave, canonico, item.get("en"), *(item.get("aliases") or [])]:
                if nome:
                    aliases[str(nome).strip().lower()] = canonico
    return aliases


def normalizar_tags(tags: Iterable[Any], aliases: dict[str, str]) -> list[str]:
    vistas: list[str] = []
    for tag in tags:
        nome = aliases.get(str(tag).strip().lower(), str(tag).strip().lower())
        nome = nome.replace(",", " ").strip()
        if nome and nome not in vistas:
            vistas.append(nome)
    return vistas


def classificar(tags: list[str], mapa: dict[str, Any]) -> dict[str, Any]:
    """Aplica as regras do mapa: ícone/capa da primeira que casar; Área/Genres de todas."""

    casadas = [r for r in mapa["regras"] if set(r.get("tags", [])) & set(tags)]
    padrao = mapa["padrao"]
    primeira = next((r for r in casadas if r.get("icone")), padrao)
    areas: list[str] = []
    generos: list[str] = []
    for regra in casadas or [padrao]:
        areas += [a for a in regra.get("area", []) if a not in areas]
        generos += [g for g in regra.get("genres", []) if g not in generos]
    return {
        "icone": primeira.get("icone", padrao["icone"]),
        "capa": primeira.get("capa", padrao["capa"]),
        "area": areas or padrao["area"],
        "genres": generos or padrao["genres"],
        "categoria": primeira.get("nome", "padrão"),
    }
