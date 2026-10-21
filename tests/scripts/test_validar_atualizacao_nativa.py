"""O validador do auto-update só serve se o próprio validador for confiável.

O ciclo de verdade roda em runners reais (workflow ``validar-atualizacao-nativa``). Aqui ficam
as peças que decidem se o resultado vale: isolamento do ambiente, conferência do SHA-256,
repetição quando a rede falha e o critério do relançamento do comando original.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.empacotamento import validar_atualizacao_nativa as validar

from felixo_notion_mcp.api.cli import atualizacao_nativa as nativa


def test_ambiente_do_binario_nao_enxerga_python_nem_a_conta_de_quem_roda(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONHOME", "/qualquer")
    monkeypatch.setenv("PYTHONPATH", "/qualquer")
    monkeypatch.setenv("VIRTUAL_ENV", "/qualquer")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "conta-real"))

    ambiente = validar.ambiente_do_binario(tmp_path / "casa", auto_update=False)

    for nome in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYINSTALLER_RESET_ENVIRONMENT"):
        assert nome not in ambiente
    assert ambiente["PATH"] == validar.path_minimo()
    assert Path(ambiente["HOME"]) == tmp_path / "casa"
    assert ambiente["NOTION_AUTOMACOES_NO_UPDATE"] == "1"


def test_auto_update_ligado_so_remove_a_trava_do_update(tmp_path):
    ambiente = validar.ambiente_do_binario(tmp_path / "casa", auto_update=True)

    assert "NOTION_AUTOMACOES_NO_UPDATE" not in ambiente
    assert Path(ambiente["LOCALAPPDATA"]).is_relative_to(tmp_path / "casa")


def test_python_no_path_lista_so_o_que_o_path_minimo_enxerga(monkeypatch):
    consultados = []

    def falso_which(nome, path=None):
        consultados.append(path)
        return "/usr/bin/python3" if nome == "python3" else None

    monkeypatch.setattr(validar.shutil, "which", falso_which)

    assert validar.python_no_path() == ["/usr/bin/python3"]
    assert set(consultados) == {validar.path_minimo()}


def test_baixar_release_grava_o_binario_quando_o_sha256_confere(monkeypatch, tmp_path):
    binario = b"binario de teste"
    alvo = nativa.obter_alvo("linux-x64")
    respostas = {
        alvo.asset: binario,
        alvo.checksum: f"{hashlib.sha256(binario).hexdigest()}  {alvo.asset}\n".encode(),
    }
    monkeypatch.setattr(validar, "_baixar", lambda url: respostas[url.rsplit("/", 1)[1]])

    caminho, digest = validar.baixar_release("v0.4.1", alvo, tmp_path)

    assert caminho.read_bytes() == binario
    assert digest == hashlib.sha256(binario).hexdigest()


def test_baixar_release_recusa_binario_com_sha256_diferente(monkeypatch, tmp_path):
    alvo = nativa.obter_alvo("linux-x64")
    respostas = {alvo.asset: b"adulterado", alvo.checksum: ("0" * 64).encode()}
    monkeypatch.setattr(validar, "_baixar", lambda url: respostas[url.rsplit("/", 1)[1]])

    with pytest.raises(nativa.AtualizacaoNativaError, match="divergente"):
        validar.baixar_release("v0.4.1", alvo, tmp_path)

    assert not (tmp_path / alvo.asset).exists()


def test_baixar_repete_em_falha_de_rede_e_depois_desiste(monkeypatch):
    tentativas = []

    def abrir(requisicao, *, timeout):
        tentativas.append(requisicao.full_url)
        raise OSError("rede fora")

    monkeypatch.setattr(validar.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="rede fora"):
        validar._baixar("https://releases.test/asset", abrir=abrir)

    assert len(tentativas) == validar.TENTATIVAS_DE_REDE


def test_status_do_cache_e_a_limpeza_do_estado_do_usuario(tmp_path):
    cache = tmp_path / "AppData" / "Local" / "notion-automacoes" / nativa.ARQUIVO_CACHE
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"verificado_em": 1, "status": "erro"}), encoding="utf-8")
    perfil = tmp_path / "AppData" / "Roaming" / "notion-tasks" / validar.ARQUIVO_PERFIS
    perfil.parent.mkdir(parents=True)
    perfil.write_text("{}", encoding="utf-8")

    assert validar.status_do_cache(tmp_path) == "erro"
    assert validar.perfis_gravados(tmp_path) == [perfil]

    validar.limpar_estado_do_usuario(tmp_path)

    assert validar.status_do_cache(tmp_path) is None
    assert validar.perfis_gravados(tmp_path) == []


def _execucao(codigo: int = 0) -> validar.Execucao:
    return validar.Execucao(codigo, "", "", 0.1)


def test_disparo_repete_com_o_estado_limpo_quando_a_rede_falha(monkeypatch, tmp_path):
    """Erro de rede é ignorado pelo binário e cacheado por 24 h: sem limpar, nada se repete."""

    estados = iter(["erro", "erro", "atualizado"])
    disparos = []
    limpezas = []
    monkeypatch.setattr(validar.time, "sleep", lambda _: None)
    monkeypatch.setattr(validar, "status_do_cache", lambda casa: next(estados))
    monkeypatch.setattr(validar, "limpar_estado_do_usuario", lambda casa: limpezas.append(casa))
    monkeypatch.setattr(
        validar, "executar", lambda *args, **kwargs: disparos.append(args) or _execucao()
    )

    _, tentativas = validar.disparar_auto_update(tmp_path / "bin", tmp_path, "sha")

    assert tentativas == 3
    assert len(disparos) == len(limpezas) == 3
    assert disparos[0][1:3] == ("auth", "adicionar")


def test_disparo_nao_repete_quando_a_primeira_tentativa_funciona(monkeypatch, tmp_path):
    monkeypatch.setattr(validar, "status_do_cache", lambda casa: "agendado")
    monkeypatch.setattr(validar, "limpar_estado_do_usuario", lambda casa: None)
    chamadas = []
    monkeypatch.setattr(
        validar, "executar", lambda *args, **kwargs: chamadas.append(args) or _execucao()
    )

    _, tentativas = validar.disparar_auto_update(tmp_path / "bin", tmp_path, "sha")

    assert (tentativas, len(chamadas)) == (1, 1)


@pytest.fixture
def relatorio_posix(monkeypatch):
    monkeypatch.setattr(validar, "WINDOWS", False)
    return validar.Relatorio()


def test_comando_original_concluido_passa(relatorio_posix, tmp_path):
    perfil = tmp_path / "config" / validar.ARQUIVO_PERFIS
    perfil.parent.mkdir()
    perfil.write_text("{}", encoding="utf-8")

    validar.conferir_comando_original(relatorio_posix, tmp_path, _execucao(0), exigir=True)

    assert relatorio_posix.falhas == 0
    assert relatorio_posix.linhas[0].startswith("- ✓")


def test_comando_perdido_reprova_quando_o_build_deveria_ter_a_correcao(relatorio_posix, tmp_path):
    validar.conferir_comando_original(relatorio_posix, tmp_path, _execucao(2), exigir=True)

    assert relatorio_posix.falhas == 1
    assert relatorio_posix.linhas[0].startswith("- ✗")


def test_comando_perdido_nas_releases_publicadas_vira_aviso_e_observacao(relatorio_posix, tmp_path):
    validar.conferir_comando_original(relatorio_posix, tmp_path, _execucao(2), exigir=False)

    assert relatorio_posix.falhas == 0
    assert relatorio_posix.linhas[0].startswith("- ⚠")
    assert relatorio_posix.linhas[1].startswith("- ℹ")


def test_no_windows_o_comando_original_so_vale_com_o_perfil_gravado(monkeypatch, tmp_path):
    """O disparo sai com 0 antes de a troca acontecer: o código de saída não prova nada."""

    monkeypatch.setattr(validar, "WINDOWS", True)
    monkeypatch.setattr(validar, "TEMPO_RELANCAMENTO", 0.0)
    relatorio = validar.Relatorio()

    validar.conferir_comando_original(relatorio, tmp_path, _execucao(0), exigir=True)

    assert relatorio.falhas == 1


def test_processo_em_uso_espera_o_pid_do_validador(tmp_path):
    executavel = tmp_path / "na"

    argumentos = validar.argumentos_do_processo_ativo(executavel, 4242)

    assert argumentos[:3] == [str(executavel), nativa.ARGUMENTO_APLICAR, "4242"]
    assert argumentos[-1] == str(executavel)


def test_processo_em_uso_nao_troca_nada_quando_acorda(tmp_path):
    """Ele só existe para segurar o arquivo: expirando ou sendo liberado, não instala nada."""

    executavel = tmp_path / "na"
    executavel.write_bytes(b"antigo")
    argumentos_da_troca = validar.argumentos_do_processo_ativo(executavel, 1)[2:]

    with pytest.raises(nativa.AtualizacaoNativaError, match="temporário"):
        nativa.executar_troca_agendada(
            argumentos_da_troca,
            waiter=lambda pid: None,
            runner=lambda *a, **k: pytest.fail("não relança nada"),
        )

    assert executavel.read_bytes() == b"antigo"
    assert list(tmp_path.iterdir()) == [executavel]


def test_resolver_origem_de_build_local_exige_a_versao(tmp_path):
    args = validar.construir_parser().parse_args(["--de-binario", str(tmp_path / "na")])

    with pytest.raises(SystemExit, match="--de-versao"):
        validar.resolver_origem(args, nativa.obter_alvo("linux-x64"), tmp_path)


def test_resolver_origem_de_build_local_nao_baixa_nada(monkeypatch, tmp_path):
    binario = tmp_path / "na"
    binario.write_bytes(b"build local")
    monkeypatch.setattr(validar, "baixar_release", lambda *a, **k: pytest.fail("sem rede"))
    args = validar.construir_parser().parse_args(
        ["--de-binario", str(binario), "--de-versao", "v0.4.9"]
    )

    origem = validar.resolver_origem(args, nativa.obter_alvo("linux-x64"), tmp_path)

    assert (origem.versao, origem.tag) == ("0.4.9", None)
    assert origem.sha == hashlib.sha256(b"build local").hexdigest()
