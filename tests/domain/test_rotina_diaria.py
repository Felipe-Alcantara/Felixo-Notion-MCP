"""Testes das regras puras de estimativa da rotina diária."""

from __future__ import annotations

from datetime import date, datetime

from felixo_notion_mcp.domain import rotina_diaria as r


def _dt(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


def test_horas_nao_contam_duas_vezes_a_sobreposicao():
    blocos = [
        r.Intervalo(_dt("2026-10-16T11:26"), _dt("2026-10-16T16:32")),
        r.Intervalo(_dt("2026-10-16T14:00"), _dt("2026-10-16T15:00")),
        r.Intervalo(_dt("2026-10-16T16:40"), _dt("2026-10-16T16:47")),
    ]
    assert r.horas(blocos) == 5.2


def test_sessoes_de_commits_quebram_em_pausa_longa_e_somam_aquecimento():
    horarios = [_dt(f"2026-10-19T{h}") for h in ("15:00", "16:08", "17:00", "20:01", "20:30")]

    sessoes = r.sessoes_de_commits(horarios)

    assert [(s.inicio.strftime("%H:%M"), s.fim.strftime("%H:%M")) for s in sessoes] == [
        ("14:30", "17:00"),
        ("19:31", "20:30"),
    ]
    assert r.horas(sessoes) == 3.5


def test_intervalos_de_texto_respeitam_data_e_meia_noite():
    texto = "Meu Blog — 16/10 20:28–22:53 (2h 25) e 17/10 11:22–11:28; MEM 23:50-00:10"

    blocos = r.intervalos_de_texto(texto, date(2026, 10, 17))

    assert blocos[0] == r.Intervalo(_dt("2026-10-16T20:28"), _dt("2026-10-16T22:53"))
    assert blocos[1] == r.Intervalo(_dt("2026-10-17T11:22"), _dt("2026-10-17T11:28"))
    assert blocos[2] == r.Intervalo(_dt("2026-10-17T23:50"), _dt("2026-10-18T00:10"))


def test_acordar_e_sono_estimados_e_implausivel_vira_none():
    assert r.estimar_acordar(_dt("2026-10-17T11:22")) == "10:20"
    assert r.estimar_acordar(None) is None
    assert r.estimar_acordar(_dt("2026-10-20T00:29")) is None  # madrugada: noite estendida

    acordou = _dt("2026-10-17T10:20")
    assert r.estimar_sono(_dt("2026-10-16T22:53"), acordou) == 10.9
    # Véspera sem registro à noite: 16 h de "sono" não é sono, é falta de dado.
    assert r.estimar_sono(_dt("2026-10-15T17:32"), _dt("2026-10-16T10:00")) is None
    assert r.estimar_sono(None, acordou) is None


def test_produtividade_por_faixa_de_horas():
    assert r.classificar_produtividade(13.4) == "Alta"
    assert r.classificar_produtividade(7) == "Alta"
    assert r.classificar_produtividade(3.5) == "Média"
    assert r.classificar_produtividade(1.7) == "Baixa"
    assert r.classificar_produtividade(0) is None
    assert r.classificar_produtividade(None) is None


def test_titulo_do_dia():
    assert r.titulo_do_dia(date(2026, 10, 20)) == "20-10-2026"
