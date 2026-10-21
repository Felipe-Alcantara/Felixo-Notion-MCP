"""Caso de uso: um lote de **rascunhos** vira tarefas num database, sem duplicar.

Era ``scripts/notion/criar_tarefas_de_rascunhos.py`` + ``verificar_…``: chamavam a
própria CLI por ``subprocess`` e tinham database, colunas, repositórios e cabeçalho
fixos. Aqui as colunas vêm do rascunho e são conferidas contra o schema real, e o
cabeçalho (agente, repositório, commit lido…) vem escrito no próprio ``.md``.

Formato da pasta:

* ``<chave>.json`` — ``chave`` (igual ao nome do arquivo), ``titulo``,
  ``propriedades`` (``coluna -> valor``; lista em multi_select e relação) e
  ``relacoes`` (``alvo``, ``coluna``, ``motivo``), em que ``alvo`` é ``chave:<x>``
  de outro rascunho ou o ID/link de uma tarefa existente;
* ``<chave>.md`` — o corpo, sem a seção "Tarefas relacionadas" (ela é gerada);
* ``lote.json`` (opcional) — ``propriedades`` comuns ao lote; as do rascunho vencem.

Etapas (:func:`importar_tarefas`); se algum item falha numa etapa, o lote para ali
com :class:`~felixo_notion_mcp.core.exceptions.LoteIncompletoError`, e rodar de novo
completa o que faltou:

1. valida tudo antes de escrever: schema, títulos únicos, chaves citadas e as
   tarefas existentes citadas, que precisam responder;
2. cria cada título que ainda não existe, com as propriedades numa requisição;
3. escreve o corpo de quem tem página vazia, trocando ``chave:x`` por links;
4. liga as relações (``relacionar``, idempotente) em rodadas sem página repetida;
5. acrescenta "Tarefas relacionadas" nas duas pontas, só com o que falta.

:func:`conferir_tarefas` relê tudo e aponta o que não ficou como o lote pede.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from felixo_notion_mcp.core.exceptions import LoteIncompletoError
from felixo_notion_mcp.core.utils import chave_de_id
from felixo_notion_mcp.domain import rascunhos_de_tarefas as dom
from felixo_notion_mcp.domain.readers import extrair_valores
from felixo_notion_mcp.domain.schema import descrever_database
from felixo_notion_mcp.services import conteudo, relacoes
from felixo_notion_mcp.services.propriedades import valor_de_propriedade

if TYPE_CHECKING:
    from felixo_notion_mcp.integrations.notion_client import NotionClient

ARQUIVO_LOTE = "lote.json"
_TIPOS_COM_OPCOES = ("select", "status", "multi_select")

T = TypeVar("T")
R = TypeVar("R")


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from felixo_notion_mcp.integrations.notion import criar_cliente

    return criar_cliente()


# -- Leitura da pasta --------------------------------------------------------------


def _ler_json(caminho: Path) -> dict[str, Any]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as erro:
        raise ValueError(f"{caminho.name}: JSON inválido ({erro})") from erro
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho.name}: o JSON deve ser um objeto")
    return dados


def _relacoes(caminho: Path, brutas: Any) -> list[dom.Relacao]:
    if not isinstance(brutas, list) or not all(isinstance(r, dict) for r in brutas):
        raise ValueError(f"{caminho.name}: 'relacoes' deve ser uma lista de objetos")
    return [
        dom.Relacao(
            alvo=str(r.get("alvo") or ""),
            coluna=str(r.get("coluna") or ""),
            motivo=str(r.get("motivo") or ""),
        )
        for r in brutas
    ]


def carregar_lote(pasta: Path, *, so: Iterable[str] | None = None) -> dom.Lote:
    """Lê os pares ``<chave>.json`` + ``<chave>.md`` da pasta (e o ``lote.json``).

    O ``lote.json`` (opcional) traz ``propriedades`` comuns e ``simetricas``: as
    relações de mão única do database que são simétricas (ver
    :func:`~felixo_notion_mcp.domain.rascunhos_de_tarefas.colunas_do_lote`).

    Args:
        pasta: A pasta do lote.
        so: Limita o lote a estas chaves (as citações a chaves de fora passam a
            ser apontadas pela validação).

    Raises:
        ValueError: Par incompleto, chave diferente do nome do arquivo ou pasta vazia.
    """

    comuns: dict[str, Any] = {}
    simetricas: list[str] = []
    caminho_lote = pasta / ARQUIVO_LOTE
    if caminho_lote.is_file():
        configuracao = _ler_json(caminho_lote)
        comuns = dict(configuracao.get("propriedades") or {})
        simetricas = configuracao.get("simetricas") or []
        if not isinstance(simetricas, list) or not all(isinstance(s, str) for s in simetricas):
            raise ValueError(f"{ARQUIVO_LOTE}: 'simetricas' deve ser uma lista de colunas")
    filtro = set(so or [])
    rascunhos: list[dom.Rascunho] = []
    for caminho in sorted(pasta.glob("*.json")):
        if caminho.name == ARQUIVO_LOTE:
            continue
        dados = _ler_json(caminho)
        chave = str(dados.get("chave") or "")
        if chave != caminho.stem:
            raise ValueError(f"{caminho.name}: 'chave' ({chave}) difere do nome do arquivo")
        if not str(dados.get("titulo") or "").strip():
            raise ValueError(f"{caminho.name}: falta 'titulo'")
        if filtro and chave not in filtro:
            continue
        caminho_md = caminho.with_suffix(".md")
        if not caminho_md.is_file():
            raise ValueError(f"{caminho.name}: falta o corpo {caminho_md.name}")
        rascunhos.append(
            dom.Rascunho(
                chave=chave,
                titulo=str(dados["titulo"]).strip(),
                propriedades={**comuns, **(dados.get("propriedades") or {})},
                corpo=caminho_md.read_text(encoding="utf-8-sig").strip(),
                relacoes=_relacoes(caminho, dados.get("relacoes") or []),
            )
        )
    if not rascunhos:
        raise ValueError(f"Nenhum rascunho em {pasta}")
    return dom.Lote(rascunhos=rascunhos, simetricas=frozenset(simetricas))


# -- Apoio -------------------------------------------------------------------------


def _em_paralelo(
    funcao: Callable[[T], R],
    itens: list[T],
    *,
    etapa: str,
    nome: Callable[[T], str],
    paralelo: int,
) -> list[R]:
    """Roda ``funcao`` em cada item; se algum falha, os outros terminam e a etapa para."""

    resultados: list[Any] = [None] * len(itens)
    falhas: list[str] = []

    def rodar(indice: int) -> None:
        try:
            resultados[indice] = funcao(itens[indice])
        except Exception as erro:  # noqa: BLE001 — o motivo vai inteiro para o relatório
            falhas.append(f"{nome(itens[indice])}: {erro}")

    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as executor:
        list(executor.map(rodar, range(len(itens))))
    if falhas:
        raise LoteIncompletoError(etapa, sorted(falhas))
    return resultados


def _colunas(cliente: NotionClient, database_id: str) -> dict[str, dict[str, Any]]:
    descricao = descrever_database(cliente.get_database(database_id)).para_dict()
    return {coluna["nome"]: coluna for coluna in descricao["colunas"]}


def _titulos_existentes(database_id: str, cliente: NotionClient) -> dict[str, str]:
    """``título -> ID`` das linhas que o database já tem."""

    return {
        str(linha["titulo"]).strip(): str(linha["id"])
        for linha in conteudo.listar_linhas(database_id, cliente=cliente)
        if linha.get("titulo") and linha.get("id")
    }


def _titulo_da_pagina(pagina: dict[str, Any]) -> str:
    for propriedade in (pagina.get("properties") or {}).values():
        if isinstance(propriedade, dict) and propriedade.get("type") == "title":
            return "".join(str(i.get("plain_text", "")) for i in propriedade.get("title") or [])
    return "(sem título)"


def _alvos_existentes(rascunhos: list[dom.Rascunho]) -> list[str]:
    return sorted(
        {
            str(dom.id_do_alvo(relacao.alvo))
            for r in rascunhos
            for relacao in r.relacoes
            if not relacao.alvo.strip().startswith("chave:")
        }
    )


def _titulos_das_citadas(
    rascunhos: list[dom.Rascunho], cliente: NotionClient, paralelo: int
) -> dict[str, str]:
    """``ID -> título`` das tarefas existentes citadas; todas precisam responder."""

    alvos = _alvos_existentes(rascunhos)
    try:
        titulos = _em_paralelo(
            lambda alvo: _titulo_da_pagina(cliente.obter_pagina(alvo)),
            alvos,
            etapa="ler tarefas existentes",
            nome=str,
            paralelo=paralelo,
        )
    except LoteIncompletoError as erro:
        lista = "".join(f"\n- {falha}" for falha in erro.falhas)
        raise ValueError(f"tarefas citadas que não respondem, nada foi gravado:{lista}") from erro
    return dict(zip(alvos, titulos, strict=True))


def _como_texto(valor: Any) -> str:
    return ",".join(str(v) for v in valor) if isinstance(valor, list) else str(valor)


# -- Etapas --------------------------------------------------------------------------


def _criar(
    r: dom.Rascunho,
    database_id: str,
    colunas: dict[str, dict[str, Any]],
    cliente: NotionClient,
) -> str:
    titulo = next(nome for nome, coluna in colunas.items() if coluna.get("titulo"))
    payload = {titulo: valor_de_propriedade("title", r.titulo)}
    for nome, valor in r.propriedades.items():
        payload[nome] = valor_de_propriedade(str(colunas[nome]["tipo"]), _como_texto(valor))
    return str(cliente.criar_pagina(database_id, payload)["id"])


def _escrever_corpo(
    r: dom.Rascunho,
    page_id: str,
    destinos: dict[str, tuple[str, str]],
    cliente: NotionClient,
) -> bool:
    """Escreve o corpo só em página vazia (corpo existente nunca é sobrescrito)."""

    if conteudo.ler_conteudo(page_id, cliente=cliente).strip():
        return False
    corpo, _ = dom.resolver_chaves(r.corpo, destinos)
    conteudo.escrever_conteudo(page_id, corpo + "\n", cliente=cliente)
    return True


def _acrescentar_secao(
    page_id: str,
    itens: list[dom.ItemRelacionado],
    titulos: dict[str, str],
    destinos: dict[str, tuple[str, str]],
    cliente: NotionClient,
) -> bool:
    markdown = conteudo.ler_conteudo(page_id, cliente=cliente)
    novo = dom.secao_a_acrescentar(markdown, itens, titulos, destinos)
    if novo is None:
        return False
    conteudo.escrever_conteudo(page_id, novo, cliente=cliente)
    return True


def _plano(
    rascunhos: list[dom.Rascunho],
    existentes: dict[str, str],
    colunas: dict[str, dict[str, Any]],
    database_id: str,
) -> dict[str, Any]:
    """O que o lote faria (``dry_run``): quem é criado, quantas ligações e os avisos."""

    tarefas = {
        r.chave: {
            "titulo": r.titulo,
            "acao": "existente" if r.titulo in existentes else "criar",
            **({"id": existentes[r.titulo]} if r.titulo in existentes else {}),
        }
        for r in rascunhos
    }
    provisorios = {r.chave: existentes.get(r.titulo) or f"novo:{r.chave}" for r in rascunhos}
    destinos = {r.chave: (provisorios[r.chave], r.titulo) for r in rascunhos}
    avisos = []
    for r in rascunhos:
        _, sem_destino = dom.resolver_chaves(r.corpo, destinos)
        if sem_destino:
            citadas = ", ".join(sorted(set(sem_destino)))
            avisos.append(f"{r.chave}: chaves citadas sem rascunho: {citadas}")
    return {
        "database": database_id,
        "dry_run": True,
        "tarefas": tarefas,
        "ligacoes": len(dom.resolver_arestas(rascunhos, provisorios, colunas)),
        "avisos": avisos,
    }


def importar_tarefas(
    lote: dom.Lote,
    database_id: str,
    *,
    paralelo: int = 4,
    dry_run: bool = False,
    conferir: bool = False,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Grava o lote no database (etapas no docstring do módulo).

    Args:
        lote: O lote, de :func:`carregar_lote`.
        database_id: Database de tarefas de destino.
        paralelo: Chamadas simultâneas por etapa.
        dry_run: Valida e mostra o plano, sem escrever.
        conferir: Ao fim, relê tudo (:func:`conferir_tarefas`) e devolve os problemas.
        cliente: Cliente Notion opcional (injeção para testes).

    Raises:
        ValueError: Lote inválido ou tarefa existente citada que não responde (nada
            é gravado).
        LoteIncompletoError: Uma etapa falhou em parte; rodar de novo completa.
    """

    cliente = cliente or _cliente_padrao()
    rascunhos = lote.rascunhos
    colunas, problemas = dom.colunas_do_lote(_colunas(cliente, database_id), lote.simetricas)
    problemas.extend(dom.validar_lote(rascunhos, colunas))
    if problemas:
        lista = "".join(f"\n- {problema}" for problema in problemas)
        raise ValueError(f"rascunhos inválidos, nada foi gravado:{lista}")
    existentes = _titulos_existentes(database_id, cliente)
    titulos = _titulos_das_citadas(rascunhos, cliente, paralelo)
    if dry_run:
        return _plano(rascunhos, existentes, colunas, database_id)

    novos = [r for r in rascunhos if r.titulo not in existentes]
    criados = _em_paralelo(
        lambda r: _criar(r, database_id, colunas, cliente),
        novos,
        etapa="criar linhas",
        nome=lambda r: r.chave,
        paralelo=paralelo,
    )
    ids = {r.chave: existentes[r.titulo] for r in rascunhos if r.titulo in existentes}
    ids.update({r.chave: page_id for r, page_id in zip(novos, criados, strict=True)})
    destinos = {r.chave: (ids[r.chave], r.titulo) for r in rascunhos}

    escritos = _em_paralelo(
        lambda r: _escrever_corpo(r, ids[r.chave], destinos, cliente),
        rascunhos,
        etapa="escrever corpos",
        nome=lambda r: r.chave,
        paralelo=paralelo,
    )

    arestas = dom.resolver_arestas(rascunhos, ids, colunas)
    for numero, rodada in enumerate(dom.rodadas_sem_pagina_repetida(arestas), start=1):
        _em_paralelo(
            lambda x: relacoes.relacionar(x.a, x.b, x.coluna, cliente=cliente),
            rodada,
            etapa=f"relações, rodada {numero}",
            nome=lambda x: f"{x.coluna}: {x.a} -> {x.b}",
            paralelo=paralelo,
        )

    titulos.update({ids[r.chave]: r.titulo for r in rascunhos})
    pares = list(dom.itens_por_pagina(arestas, colunas).items())
    secoes = _em_paralelo(
        lambda par: _acrescentar_secao(par[0], par[1], titulos, destinos, cliente),
        pares,
        etapa="seções de tarefas relacionadas",
        nome=lambda par: par[0],
        paralelo=paralelo,
    )

    criadas = {r.chave for r in novos}
    resultado: dict[str, Any] = {
        "database": database_id,
        "dry_run": False,
        "tarefas": {
            r.chave: {
                "id": ids[r.chave],
                "titulo": r.titulo,
                "url": dom.link(ids[r.chave]),
                "acao": "criada" if r.chave in criadas else "existente",
                "corpo": "escrito" if escrito else "mantido (já tinha corpo)",
            }
            for r, escrito in zip(rascunhos, escritos, strict=True)
        },
        "ligacoes": len(arestas),
        "secoes_atualizadas": sum(1 for mudou in secoes if mudou),
    }
    if conferir:
        resultado["problemas"] = conferir_tarefas(lote, database_id, cliente=cliente)
    return resultado


# -- Conferência -----------------------------------------------------------------------


def conferir_tarefas(
    lote: dom.Lote,
    database_id: str,
    *,
    cliente: NotionClient | None = None,
) -> list[str]:
    """Relê o que o lote gravou e aponta o que não ficou como ele pede.

    Confere, por tarefa (achada pelo título): valores de select/status/multi_select,
    corpo não vazio e sem ``chave:`` sobrando; cada ligação nas duas pontas (na de
    mão dupla, pela coluna espelho); e o link de cada ligação no corpo das duas.
    """

    cliente = cliente or _cliente_padrao()
    rascunhos = lote.rascunhos
    colunas, problemas = dom.colunas_do_lote(_colunas(cliente, database_id), lote.simetricas)
    existentes = _titulos_existentes(database_id, cliente)
    ids: dict[str, str] = {}
    for r in rascunhos:
        if r.titulo in existentes:
            ids[r.chave] = existentes[r.titulo]
        else:
            problemas.append(f"{r.chave}: tarefa não encontrada pelo título")
    rotulos = {chave_de_id(page_id): chave for chave, page_id in ids.items()}
    valores_lidos: dict[str, dict[str, Any]] = {}
    corpos_lidos: dict[str, str] = {}

    def valores(page_id: str) -> dict[str, Any]:
        if page_id not in valores_lidos:
            valores_lidos[page_id] = extrair_valores(cliente.obter_pagina(page_id))
        return valores_lidos[page_id]

    def corpo(page_id: str) -> str:
        if page_id not in corpos_lidos:
            corpos_lidos[page_id] = conteudo.ler_conteudo(page_id, cliente=cliente)
        return corpos_lidos[page_id]

    def rotulo(page_id: str) -> str:
        return rotulos.get(chave_de_id(page_id), page_id)

    def liga(page_id: str, coluna: str, outra: str) -> bool:
        ligados = valores(page_id).get(coluna) or []
        return chave_de_id(outra) in {chave_de_id(str(i)) for i in ligados}

    for r in rascunhos:
        if r.chave not in ids:
            continue
        atuais = valores(ids[r.chave])
        for nome, desejado in r.propriedades.items():
            if colunas.get(nome, {}).get("tipo") not in _TIPOS_COM_OPCOES:
                continue
            atual = atuais.get(nome)
            if isinstance(desejado, list):
                iguais = sorted(map(str, atual or [])) == sorted(map(str, desejado))
            else:
                iguais = atual == desejado
            if not iguais:
                problemas.append(f"{r.chave}: {nome}={atual!r}, esperado {desejado!r}")
        texto = corpo(ids[r.chave])
        if not texto.strip():
            problemas.append(f"{r.chave}: corpo vazio")
        _, sobras = dom.resolver_chaves(texto, {})
        if sobras:
            problemas.append(f"{r.chave}: sobrou citação de chave no corpo: {sorted(set(sobras))}")

    if len(ids) != len(rascunhos):
        return problemas
    arestas = dom.resolver_arestas(rascunhos, ids, colunas)
    for x in arestas:
        relacao = colunas[x.coluna].get("relacao") or {}
        volta = x.coluna
        if relacao.get("bidirecional"):
            volta = str(relacao.get("coluna_espelho") or x.coluna)
        if not liga(x.a, x.coluna, x.b):
            problemas.append(f"{rotulo(x.a)}: {x.coluna!r} não liga {x.b}")
        if not liga(x.b, volta, x.a):
            problemas.append(f"{rotulo(x.b)}: {volta!r} não liga {x.a}")
    for page_id, itens in dom.itens_por_pagina(arestas, colunas).items():
        citadas = chave_de_id(corpo(page_id))
        for item in itens:
            if chave_de_id(item.outra) not in citadas:
                problemas.append(f"{rotulo(page_id)}: corpo não cita {item.outra}")
    return problemas
