"""Regras puras para **estimar a rotina de um dia** a partir de rastros de trabalho.

Usado pelo Registro diário: quando a pessoa não anotou as horas, o dia pode ser
estimado pelos horários de commit e pelos blocos ``HH:MM–HH:MM`` que os relatórios
diários já registram. Tudo aqui é determinístico e sem rede.

Critérios (combinados com a pessoa em 2026-10-20):

* **horas por área** — união dos intervalos, sem contar duas vezes a sobreposição
  de agentes em paralelo;
* **sessões de commits** — intervalo maior que ``pausa_maxima`` (2 h) abre sessão
  nova, e cada sessão começa ``aquecimento`` (30 min) antes do primeiro commit;
* **acordei às** — primeira atividade do dia menos ``antecedencia`` (1 h),
  arredondada para 10 min; atividade antes das 05:00 é a noite anterior se
  estendendo, e aí não há estimativa;
* **sono** — da última atividade da véspera mais ``deitar_apos`` (30 min) até
  acordar, só quando o resultado é plausível (até ``maximo``, 14 h);
* **produtividade** — 7 h ou mais = Alta, de 3 a 7 h = Média, menos de 3 h = Baixa.

Quando não há dado (ou o dado é implausível), a função devolve ``None``: o
Registro diário deixa o campo vazio em vez de inventar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

PAUSA_MAXIMA = timedelta(hours=2)
AQUECIMENTO = timedelta(minutes=30)
ANTECEDENCIA_ACORDAR = timedelta(hours=1)
DEITAR_APOS = timedelta(minutes=30)
SONO_MAXIMO = timedelta(hours=14)
#: Atividade antes deste horário continua a noite anterior: não indica a hora de acordar.
FIM_DA_MADRUGADA = time(5, 0)

#: ``HH:MM–HH:MM``, com data ``DD/MM`` opcional antes do primeiro horário.
_INTERVALO = re.compile(
    r"(?:(?P<dia>\d{1,2})/(?P<mes>\d{1,2})\s+)?"
    r"(?P<ini>\d{1,2}:\d{2})\s*[–—-]\s*(?P<fim>\d{1,2}:\d{2})"
)


@dataclass(frozen=True, order=True)
class Intervalo:
    """Um bloco de atividade, com início e fim absolutos."""

    inicio: datetime
    fim: datetime

    @property
    def duracao(self) -> timedelta:
        return self.fim - self.inicio


def unir_intervalos(intervalos: list[Intervalo]) -> list[Intervalo]:
    """Funde intervalos que se tocam ou se sobrepõem, em ordem cronológica."""

    unidos: list[Intervalo] = []
    for atual in sorted(intervalos):
        if unidos and atual.inicio <= unidos[-1].fim:
            ultimo = unidos[-1]
            unidos[-1] = Intervalo(ultimo.inicio, max(ultimo.fim, atual.fim))
        else:
            unidos.append(atual)
    return unidos


def horas(intervalos: list[Intervalo]) -> float:
    """Total de horas da união dos intervalos, com uma casa decimal."""

    total = sum((i.duracao for i in unir_intervalos(intervalos)), timedelta())
    return round(total.total_seconds() / 3600, 1)


def sessoes_de_commits(
    horarios: list[datetime],
    *,
    pausa_maxima: timedelta = PAUSA_MAXIMA,
    aquecimento: timedelta = AQUECIMENTO,
) -> list[Intervalo]:
    """Agrupa horários de commit em sessões de trabalho."""

    sessoes: list[Intervalo] = []
    inicio: datetime | None = None
    anterior: datetime | None = None
    for momento in sorted(horarios):
        if anterior is None or momento - anterior > pausa_maxima:
            if inicio is not None and anterior is not None:
                sessoes.append(Intervalo(inicio - aquecimento, anterior))
            inicio = momento
        anterior = momento
    if inicio is not None and anterior is not None:
        sessoes.append(Intervalo(inicio - aquecimento, anterior))
    return sessoes


def intervalos_de_texto(texto: str, dia: date) -> list[Intervalo]:
    """Extrai blocos ``HH:MM–HH:MM`` de um texto de relatório.

    Um bloco com ``DD/MM`` antes do horário pertence àquela data (no ano de
    ``dia``); sem data, pertence a ``dia``. Um fim menor que o início atravessa
    a meia-noite.
    """

    blocos: list[Intervalo] = []
    for achado in _INTERVALO.finditer(texto):
        base = dia
        if achado["dia"] and achado["mes"]:
            try:
                base = date(dia.year, int(achado["mes"]), int(achado["dia"]))
            except ValueError:
                continue
        try:
            inicio = datetime.combine(base, _hora(achado["ini"]))
            fim = datetime.combine(base, _hora(achado["fim"]))
        except ValueError:
            continue
        if fim < inicio:
            fim += timedelta(days=1)
        blocos.append(Intervalo(inicio, fim))
    return blocos


def estimar_acordar(
    primeira_atividade: datetime | None,
    *,
    antecedencia: timedelta = ANTECEDENCIA_ACORDAR,
    fim_da_madrugada: time = FIM_DA_MADRUGADA,
) -> str | None:
    """``HH:MM`` estimado para acordar, arredondado para 10 min.

    ``None`` sem atividade, ou quando a primeira atividade é de madrugada (a
    noite anterior se estendendo: commits à 01:00 não dizem quando a pessoa acordou).
    """

    if primeira_atividade is None or primeira_atividade.time() < fim_da_madrugada:
        return None
    momento = primeira_atividade - antecedencia
    minutos = round((momento.hour * 60 + momento.minute) / 10) * 10
    minutos %= 24 * 60
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def estimar_sono(
    ultima_atividade_vespera: datetime | None,
    acordou: datetime | None,
    *,
    deitar_apos: timedelta = DEITAR_APOS,
    maximo: timedelta = SONO_MAXIMO,
) -> float | None:
    """Horas de sono estimadas, ou ``None`` quando faltam dados ou é implausível."""

    if ultima_atividade_vespera is None or acordou is None:
        return None
    sono = acordou - (ultima_atividade_vespera + deitar_apos)
    if sono <= timedelta() or sono > maximo:
        return None
    return round(sono.total_seconds() / 3600, 1)


def classificar_produtividade(horas_no_dia: float | None) -> str | None:
    """``Alta`` (≥ 7 h), ``Média`` (3–7 h), ``Baixa`` (< 3 h) ou ``None`` sem horas."""

    if horas_no_dia is None or horas_no_dia <= 0:
        return None
    if horas_no_dia >= 7:
        return "Alta"
    if horas_no_dia >= 3:
        return "Média"
    return "Baixa"


def titulo_do_dia(dia: date) -> str:
    """Título da linha no Registro diário: ``DD-MM-AAAA``."""

    return dia.strftime("%d-%m-%Y")


def _hora(texto: str) -> time:
    horas_, minutos = texto.split(":")
    return time(int(horas_), int(minutos))
