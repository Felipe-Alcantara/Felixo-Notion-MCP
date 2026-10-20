"""Caso de uso: operar o database **Registro diário** (uma linha por dia).

Três operações, usadas na criação e no preenchimento de 16 a 20/10/2026:

* :func:`garantir_dia` — cria a linha de um dia **só se ela não existir** (nunca
  duplica), com ``Dia`` = ``DD-MM-AAAA``, ``Data``, ``Status do dia`` e o corpo;
* :func:`estimar_dias` — estima horas por área, hora de acordar, sono e
  produtividade a partir de commits do GitHub e dos blocos ``HH:MM–HH:MM`` dos
  relatórios diários (regras em :mod:`felixo_notion_mcp.domain.rotina_diaria`);
* :func:`aplicar_estimativas` — grava as estimativas **só nos campos vazios**
  (a não ser que ``sobrescrever``), para não apagar o que a pessoa informou.

``Banho`` nunca é estimado: nenhum rastro de trabalho diz isso.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from felixo_notion_mcp.domain import rotina_diaria as rotina

if TYPE_CHECKING:
    from felixo_notion_mcp.integrations.github import CommitRemoto, GitHubClient
    from felixo_notion_mcp.integrations.notion_client import NotionClient

COLUNA_DIA = "Dia"
COLUNA_DATA = "Data"
COLUNA_STATUS = "Status do dia"
COLUNA_ACORDEI = "Acordei às"
COLUNA_SONO = "Sono (h)"
COLUNA_TRABALHO = "Trabalho (h)"
COLUNA_PRODUTIVIDADE = "Produtividade"
COLUNA_PESSOAIS = "Projetos pessoais"
COLUNA_PESSOAIS_H = "Projetos pessoais (h)"

#: Corpo do modelo nativo "Dia padrão" (o mesmo gravado no database). Usado por
#: :func:`garantir_dia` quando nenhum corpo é informado.
CORPO_DIA_PADRAO = """## Tarefas de trabalho

- [ ] **Tarefa** — Próxima
  - [ ] Próximo passo
  - [ ] Pendência
  - Dependência: nenhuma

## Projetos pessoais

- [ ] **Tarefa** — Próxima
  - [ ] Próximo passo
  - Dependência: nenhuma

## Dia a dia

- [ ] **Tarefa** — Próxima
  - [ ] Próximo passo
  - Dependência: nenhuma

## Anotações do dia

-

## Resumo do dia

- Concluído:
- Pendente:
- Próximo passo principal:
"""

#: Coluna dos relatórios diários com os blocos ``Projeto — HH:MM–HH:MM``.
COLUNA_RELATORIO_TEXTO = "O que fiz"


def _cliente_padrao() -> NotionClient:
    """Resolve o :class:`NotionClient` da configuração do consumidor (import tardio)."""

    from felixo_notion_mcp.integrations.notion import criar_cliente

    return criar_cliente()


# -- Estimativa (sem rede) ---------------------------------------------------


@dataclass(frozen=True)
class Estimativa:
    """O que dá para afirmar sobre um dia a partir dos rastros de trabalho."""

    dia: date
    trabalho_h: float | None
    pessoal_h: float | None
    acordei: str | None
    sono_h: float | None
    produtividade: str | None
    criterios: list[str] = field(default_factory=list)

    def propriedades(self) -> dict[str, str]:
        """Colunas do Registro diário com valor estimado (vazias ficam de fora)."""

        valores: dict[str, Any] = {
            COLUNA_TRABALHO: self.trabalho_h,
            COLUNA_PESSOAIS_H: self.pessoal_h,
            COLUNA_PESSOAIS: "Sim" if self.pessoal_h else None,
            COLUNA_ACORDEI: self.acordei,
            COLUNA_SONO: self.sono_h,
            COLUNA_PRODUTIVIDADE: self.produtividade,
        }
        return {coluna: str(valor) for coluna, valor in valores.items() if valor is not None}

    def para_dict(self) -> dict[str, Any]:
        dados = asdict(self)
        dados["dia"] = self.dia.isoformat()
        dados["propriedades"] = self.propriedades()
        return dados


def _compacto(texto: str) -> str:
    """Sem caixa, espaço, hífen nem sublinhado: "Meu Ecoo Midia" casa com "MeuEcoo-Midia"."""

    return re.sub(r"[\s\-_]+", "", texto.casefold())


def _eh_trabalho(nome: str, trabalho: list[str]) -> bool:
    nome_compacto = _compacto(nome)
    return any(_compacto(termo) in nome_compacto for termo in trabalho if termo.strip())


def _atividades(
    commits: list[CommitRemoto],
    relatorios: dict[date, list[str]],
    trabalho: list[str],
) -> dict[date, dict[str, list[rotina.Intervalo]]]:
    """Intervalos por dia e por área (``trabalho``/``pessoal``)."""

    por_dia: dict[date, dict[str, list[rotina.Intervalo]]] = defaultdict(
        lambda: {"trabalho": [], "pessoal": []}
    )
    for dia_relatorio, linhas in relatorios.items():
        for linha in linhas:
            projeto = linha.split(" — ", 1)[0]
            area = "trabalho" if _eh_trabalho(projeto, trabalho) else "pessoal"
            for bloco in rotina.intervalos_de_texto(linha, dia_relatorio):
                por_dia[bloco.inicio.date()][area].append(bloco)

    horarios: dict[tuple[date, str], list[datetime]] = defaultdict(list)
    for commit in commits:
        try:
            # O horário fica no fuso do próprio commit, que é o da pessoa.
            momento = datetime.fromisoformat(commit.quando).replace(tzinfo=None)
        except ValueError:
            continue
        area = "trabalho" if _eh_trabalho(commit.repositorio, trabalho) else "pessoal"
        horarios[(momento.date(), area)].append(momento)
    for (dia, area), momentos in horarios.items():
        por_dia[dia][area].extend(rotina.sessoes_de_commits(momentos))
    return por_dia


def estimar_dias(
    dias: list[date],
    *,
    commits: list[CommitRemoto],
    relatorios: dict[date, list[str]],
    trabalho: list[str],
) -> list[Estimativa]:
    """Estima cada dia de ``dias``.

    Para o sono, ``commits`` e ``relatorios`` devem incluir também a véspera do
    primeiro dia. ``trabalho`` são trechos de nome (repositório ou projeto do
    relatório) que contam como trabalho; o resto conta como projeto pessoal.
    """

    atividades = _atividades(commits, relatorios, trabalho)
    estimativas: list[Estimativa] = []
    for dia in dias:
        areas = atividades.get(dia, {"trabalho": [], "pessoal": []})
        trabalho_h = rotina.horas(areas["trabalho"]) or None
        pessoal_h = rotina.horas(areas["pessoal"]) or None
        todos = areas["trabalho"] + areas["pessoal"]
        primeira = min((i.inicio for i in todos), default=None)
        # Sessão que começa na véspera (o aquecimento de um commit à 00:00) também é
        # a noite se estendendo, não a hora de acordar.
        acordei = (
            None
            if primeira is not None and primeira.date() < dia
            else rotina.estimar_acordar(primeira)
        )

        vespera = atividades.get(dia - timedelta(days=1), {"trabalho": [], "pessoal": []})
        ultima_vespera = max(
            (i.fim for i in vespera["trabalho"] + vespera["pessoal"]), default=None
        )
        acordou = (
            datetime.combine(dia, datetime.strptime(acordei, "%H:%M").time())
            if acordei
            else None
        )
        sono = rotina.estimar_sono(ultima_vespera, acordou)
        total = round((trabalho_h or 0) + (pessoal_h or 0), 1)

        criterios = [
            "horas: união dos blocos dos relatórios e das sessões de commits por área",
        ]
        if primeira is not None and acordei is None:
            criterios.append("sem hora de acordar: primeira atividade de madrugada")
        if acordei and sono is None:
            criterios.append("sem sono: véspera sem registro ou intervalo implausível")
        estimativas.append(
            Estimativa(
                dia=dia,
                trabalho_h=trabalho_h,
                pessoal_h=pessoal_h,
                acordei=acordei,
                sono_h=sono,
                produtividade=rotina.classificar_produtividade(total),
                criterios=criterios,
            )
        )
    return estimativas


# -- Notion -------------------------------------------------------------------


def _texto(propriedade: dict[str, Any]) -> str:
    itens = propriedade.get(propriedade.get("type", ""), [])
    if not isinstance(itens, list):
        return ""
    return "".join(str(i.get("plain_text", "")) for i in itens if isinstance(i, dict))


def _vazia(propriedade: dict[str, Any] | None) -> bool:
    if not propriedade:
        return True
    valor = propriedade.get(propriedade.get("type", ""))
    return valor in (None, [], "")


def _linha_do_dia(cliente: NotionClient, data_source_id: str, dia: date) -> dict[str, Any] | None:
    linhas = cliente.consultar_data_source(
        data_source_id,
        filtro={"property": COLUNA_DATA, "date": {"equals": dia.isoformat()}},
    )
    return linhas[0] if linhas else None


def ler_relatorios(
    database_id: str,
    desde: date,
    ate: date,
    *,
    coluna_texto: str = COLUNA_RELATORIO_TEXTO,
    cliente: NotionClient | None = None,
) -> dict[date, list[str]]:
    """Linhas de ``coluna_texto`` dos relatórios diários entre ``desde`` e ``ate``.

    Cada linha do texto (separadas por quebra de linha ou ``" | "``) é um bloco
    ``Projeto — HH:MM–HH:MM …``.
    """

    cliente = cliente or _cliente_padrao()
    fonte = cliente.resolver_data_source(database_id)
    linhas = cliente.consultar_data_source(
        fonte,
        buscar_todos=True,
        filtro={
            "and": [
                {"property": COLUNA_DATA, "date": {"on_or_after": desde.isoformat()}},
                {"property": COLUNA_DATA, "date": {"on_or_before": ate.isoformat()}},
            ]
        },
    )
    relatorios: dict[date, list[str]] = defaultdict(list)
    for linha in linhas:
        props = linha.get("properties", {})
        inicio = ((props.get(COLUNA_DATA) or {}).get("date") or {}).get("start")
        if not inicio:
            continue
        texto = _texto(props.get(coluna_texto) or {})
        partes = [p.strip() for bloco in texto.split("\n") for p in bloco.split(" | ")]
        relatorios[date.fromisoformat(inicio[:10])].extend(p for p in partes if p)
    return dict(relatorios)


def garantir_dia(
    database_id: str,
    dia: date,
    *,
    status: str = "Aberto",
    valores: dict[str, str] | None = None,
    conteudo: str | None = None,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Cria a linha do dia se ela não existir; se existir, não mexe em nada.

    Ordem da escrita, como pede a regra do database: propriedades e depois corpo.
    Sem ``conteudo``, o corpo é o do modelo :data:`CORPO_DIA_PADRAO` (a API não
    aplica o modelo nativo junto com propriedades e corpo numa só criação).
    """

    from felixo_notion_mcp.services import conteudo as svc_conteudo
    from felixo_notion_mcp.services import propriedades as svc_propriedades

    cliente = cliente or _cliente_padrao()
    fonte = cliente.resolver_data_source(database_id)
    existente = _linha_do_dia(cliente, fonte, dia)
    if existente is not None:
        return {"dia": dia.isoformat(), "page_id": existente.get("id"), "criado": False}

    pagina = cliente.criar_pagina_em_fonte(
        fonte,
        {
            COLUNA_DIA: {"title": [{"text": {"content": rotina.titulo_do_dia(dia)}}]},
            COLUNA_DATA: {"date": {"start": dia.isoformat()}},
        },
    )
    page_id = str(pagina["id"])
    svc_propriedades.editar_linha(
        page_id, {COLUNA_STATUS: status, **(valores or {})}, cliente=cliente
    )
    corpo = conteudo if conteudo and conteudo.strip() else CORPO_DIA_PADRAO
    svc_conteudo.escrever_conteudo(page_id, corpo, cliente=cliente)
    return {"dia": dia.isoformat(), "page_id": page_id, "criado": True}


def aplicar_estimativas(
    database_id: str,
    estimativas: list[Estimativa],
    *,
    sobrescrever: bool = False,
    dry_run: bool = False,
    cliente: NotionClient | None = None,
) -> list[dict[str, Any]]:
    """Grava as estimativas nas linhas existentes, só nos campos vazios.

    Dia sem linha não é criado aqui (use :func:`garantir_dia`): a ação volta
    como ``sem_linha``.
    """

    from felixo_notion_mcp.services import propriedades as svc_propriedades

    cliente = cliente or _cliente_padrao()
    fonte = cliente.resolver_data_source(database_id)
    acoes: list[dict[str, Any]] = []
    for estimativa in estimativas:
        linha = _linha_do_dia(cliente, fonte, estimativa.dia)
        if linha is None:
            acoes.append({"dia": estimativa.dia.isoformat(), "acao": "sem_linha"})
            continue
        atuais = linha.get("properties", {})
        gravar = {
            coluna: valor
            for coluna, valor in estimativa.propriedades().items()
            if sobrescrever or _vazia(atuais.get(coluna))
        }
        mantidas = sorted(set(estimativa.propriedades()) - set(gravar))
        if gravar and not dry_run:
            svc_propriedades.editar_linha(str(linha["id"]), gravar, cliente=cliente)
        acoes.append(
            {
                "dia": estimativa.dia.isoformat(),
                "page_id": linha.get("id"),
                "acao": "preenchido" if gravar else "nada_a_fazer",
                "gravadas": gravar,
                "mantidas": mantidas,
            }
        )
    return acoes


def estimar_periodo(
    database_id: str,
    desde: date,
    ate: date,
    *,
    autor: str,
    github: GitHubClient,
    relatorios_id: str | None = None,
    trabalho: list[str] | None = None,
    aplicar: bool = False,
    sobrescrever: bool = False,
    cliente: NotionClient | None = None,
) -> dict[str, Any]:
    """Estima os dias de ``desde`` a ``ate`` e, com ``aplicar``, grava nos campos vazios.

    Busca os commits da véspera (para o sono) até um dia **depois** de ``ate``,
    porque a busca do GitHub filtra a data em UTC: um commit às 22:00 de Brasília
    já é do dia seguinte lá. O agrupamento por dia usa o fuso do próprio commit.

    Raises:
        ValueError: Se ``ate`` for antes de ``desde`` ou ``autor`` vier vazio.
    """

    if ate < desde:
        raise ValueError("--ate não pode ser antes de --de.")
    if not autor.strip():
        raise ValueError("Informe o login do GitHub em 'autor'.")
    cliente = cliente or _cliente_padrao()
    vespera = desde - timedelta(days=1)
    commits = github.buscar_commits(
        autor, vespera.isoformat(), (ate + timedelta(days=1)).isoformat()
    )
    relatorios = (
        ler_relatorios(relatorios_id, vespera, ate, cliente=cliente) if relatorios_id else {}
    )
    dias = [desde + timedelta(days=n) for n in range((ate - desde).days + 1)]
    estimativas = estimar_dias(
        dias, commits=commits, relatorios=relatorios, trabalho=trabalho or []
    )
    resultado: dict[str, Any] = {
        "commits": len(commits),
        "dias_com_relatorio": sorted(d.isoformat() for d in relatorios),
        "estimativas": [e.para_dict() for e in estimativas],
        "aplicado": aplicar,
    }
    if aplicar:
        resultado["acoes"] = aplicar_estimativas(
            database_id, estimativas, sobrescrever=sobrescrever, cliente=cliente
        )
    return resultado
