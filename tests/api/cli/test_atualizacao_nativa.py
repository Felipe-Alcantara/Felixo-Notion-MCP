"""Testes offline do contrato de atualização de binários nativos."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from pathlib import Path

import pytest

from felixo_notion_mcp.api.cli import atualizacao_nativa as updater


class RespostaFake(io.BytesIO):
    """Resposta mínima compatível com o context manager de ``urlopen``."""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def fazer_opener(respostas: dict[str, bytes]):
    chamadas: list[str] = []

    def opener(requisicao, *, timeout):
        del timeout
        chamadas.append(requisicao.full_url)
        return RespostaFake(respostas[requisicao.full_url])

    opener.chamadas = chamadas
    return opener


def release_fake(
    *,
    versao: str = "0.4.0",
    alvo: str = "linux-x64",
    binario: str = "https://downloads.test/binario",
    checksum: str = "https://downloads.test/checksum",
) -> updater.ReleaseNativa:
    info = updater.obter_alvo(alvo)
    return updater.ReleaseNativa(
        tag=f"v{versao}",
        versao=versao,
        url="https://github.com/Felipe-Alcantara/notion-tasks-cli/releases/tag/v0.4.0",
        assets={info.asset: binario, info.checksum: checksum},
    )


@pytest.mark.parametrize(
    ("sistema", "arquitetura", "esperado"),
    [
        ("Windows", "AMD64", "windows-x64"),
        ("Darwin", "x86_64", "macos-x64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Linux", "x86_64", "linux-x64"),
    ],
)
def test_detecta_a_matriz_nativa(sistema, arquitetura, esperado):
    assert updater.detectar_alvo(sistema, arquitetura) == esperado


def test_recusa_alvo_fora_da_matriz():
    assert updater.detectar_alvo("Linux", "aarch64") is None
    assert updater.detectar_alvo("FreeBSD", "x86_64") is None


def test_consulta_release_filtra_metadados_e_preserva_urls():
    payload = {
        "tag_name": "v0.4.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/example/release",
        "assets": [
            {
                "name": "notion-automacoes-linux-x64",
                "browser_download_url": "https://downloads.test/linux",
            },
            {
                "name": "notion-automacoes-linux-x64.sha256",
                "browser_download_url": "https://downloads.test/linux.sha256",
            },
            {"name": "notas.txt", "browser_download_url": "https://downloads.test/notas"},
        ],
    }
    opener = fazer_opener({updater.URL_LATEST: json.dumps(payload).encode()})

    release = updater.consultar_release(opener=opener)

    assert release.versao == "0.4.0"
    assert release.assets["notion-automacoes-linux-x64"] == "https://downloads.test/linux"
    assert opener.chamadas == [updater.URL_LATEST]


def test_consulta_release_rejeita_pre_release():
    payload = {"tag_name": "v0.4.0-rc1", "draft": False, "prerelease": True, "assets": []}
    opener = fazer_opener({updater.URL_LATEST: json.dumps(payload).encode()})

    with pytest.raises(updater.AtualizacaoNativaError, match="rascunho"):
        updater.consultar_release(opener=opener)


def test_planejamento_distingue_atualizado_disponivel_e_asset_ausente():
    release = release_fake()

    atual = updater.planejar_atualizacao("0.4.0", alvo="linux-x64", release=release)
    disponivel = updater.planejar_atualizacao("0.3.0", alvo="linux-x64", release=release)
    sem_asset = updater.planejar_atualizacao(
        "0.3.0",
        alvo="windows-x64",
        release=release,
    )

    assert atual.status == "atualizado"
    assert disponivel.status == "disponivel"
    assert disponivel.plano is not None
    assert sem_asset.status == "asset_indisponivel"


def test_rollback_exige_permissao_explicita():
    release = release_fake(versao="0.2.0")

    bloqueado = updater.planejar_atualizacao("0.3.0", alvo="linux-x64", release=release)
    permitido = updater.planejar_atualizacao(
        "0.3.0",
        alvo="linux-x64",
        release=release,
        permitir_retrocesso=True,
    )

    assert bloqueado.status == "atualizado"
    assert permitido.status == "disponivel"


def test_baixa_e_confere_sha256_sem_apagar_destino_preexistente(tmp_path):
    binario = b"executavel novo"
    checksum = hashlib.sha256(binario).hexdigest()
    release = release_fake()
    plano = updater.planejar_atualizacao("0.3.0", alvo="linux-x64", release=release).plano
    assert plano is not None
    respostas = {
        plano.url_checksum: f"{checksum}  {plano.alvo.asset}\n".encode(),
        plano.url_binario: binario,
    }
    destino = tmp_path / "download"
    opener = fazer_opener(respostas)

    resultado = updater.baixar_e_validar(plano, destino, opener=opener)

    assert resultado["sha256"] == checksum
    assert destino.read_bytes() == binario
    assert opener.chamadas == [plano.url_checksum, plano.url_binario]

    destino.write_bytes(b"versao preservada")
    respostas[plano.url_checksum] = ("0" * 64).encode()
    with pytest.raises(updater.AtualizacaoNativaError, match="divergente"):
        updater.baixar_e_validar(plano, destino, opener=fazer_opener(respostas))
    assert destino.read_bytes() == b"versao preservada"


def test_troca_atomica_preserva_backup_e_permissoes(tmp_path):
    executavel = tmp_path / "notion-automacoes"
    temporario = tmp_path / "download"
    executavel.write_bytes(b"versao anterior")
    temporario.write_bytes(b"versao nova")
    os.chmod(executavel, 0o744)

    backup = updater.trocar_arquivo(executavel, temporario)

    assert executavel.read_bytes() == b"versao nova"
    assert backup.read_bytes() == b"versao anterior"
    if os.name != "nt":
        assert executavel.stat().st_mode & 0o777 == 0o744
    assert not temporario.exists()


def _acesso_negado(winerror: int | None) -> PermissionError:
    erro = PermissionError(13, "Acesso negado")
    if winerror is not None:
        erro.winerror = winerror
    return erro


def test_troca_repete_enquanto_o_windows_nega_o_acesso_por_instantes(tmp_path, monkeypatch):
    """Renomear o executável em uso falha de vez em quando com WinError 32 e passa logo depois.

    Medido no Windows em 21/10/2026: o helper tentava uma vez, restaurava o original e saía
    sem avisar, e o update se perdia (o cache de 24 h impedia nova tentativa no dia).
    """

    executavel = tmp_path / "notion-automacoes.exe"
    novo = tmp_path / "download.exe"
    executavel.write_bytes(b"antigo")
    novo.write_bytes(b"novo")
    negados = {"restam": 3}
    substituir = os.replace

    def replace_ocupado(origem, destino):
        if Path(origem) == executavel and negados["restam"]:
            negados["restam"] -= 1
            raise _acesso_negado(32)
        return substituir(origem, destino)

    monkeypatch.setattr(updater.os, "replace", replace_ocupado)
    monkeypatch.setattr(updater.time, "sleep", lambda _: None)

    backup = updater.trocar_arquivo(executavel, novo)

    assert negados["restam"] == 0
    assert executavel.read_bytes() == b"novo"
    assert backup.read_bytes() == b"antigo"


def test_troca_desiste_no_prazo_e_devolve_o_executavel_intacto(tmp_path, monkeypatch):
    executavel = tmp_path / "notion-automacoes.exe"
    novo = tmp_path / "download.exe"
    executavel.write_bytes(b"antigo")
    novo.write_bytes(b"novo")
    substituir = os.replace

    def replace_sempre_ocupado(origem, destino):
        if Path(origem) == executavel:
            raise _acesso_negado(32)
        return substituir(origem, destino)

    monkeypatch.setattr(updater.os, "replace", replace_sempre_ocupado)
    monkeypatch.setattr(updater.time, "sleep", lambda _: None)
    monkeypatch.setattr(updater, "TEMPO_REPETICAO_TROCA", 0.0)

    with pytest.raises(updater.AtualizacaoNativaError, match="Não foi possível trocar"):
        updater.trocar_arquivo(executavel, novo)

    assert executavel.read_bytes() == b"antigo"
    assert not updater.caminho_backup(executavel).exists()


def test_permissao_negada_de_verdade_nao_e_repetida(tmp_path, monkeypatch):
    """Fora do Windows (sem ``winerror``) ou com outro código, insistir só atrasa o erro."""

    executavel = tmp_path / "notion-automacoes"
    novo = tmp_path / "download"
    executavel.write_bytes(b"antigo")
    novo.write_bytes(b"novo")
    tentativas = []

    def replace_negado(origem, destino):
        tentativas.append(origem)
        raise _acesso_negado(None)

    monkeypatch.setattr(updater.os, "replace", replace_negado)
    monkeypatch.setattr(
        updater.time, "sleep", lambda _: pytest.fail("não deve esperar para repetir")
    )

    with pytest.raises(updater.AtualizacaoNativaError):
        updater.trocar_arquivo(executavel, novo)

    assert len(tentativas) == 1


def test_agendamento_windows_nao_tenta_substituir_processo_em_uso(tmp_path):
    executavel = tmp_path / "notion-automacoes.exe"
    temporario = tmp_path / "download.exe"
    chamadas = []

    comando = updater.agendar_troca_windows(
        executavel,
        temporario,
        argumentos=["tasks", "listar"],
        runner=lambda *args, **kwargs: chamadas.append((args, kwargs)),
    )

    assert comando[:2] == [str(executavel.resolve()), updater.ARGUMENTO_APLICAR]
    assert comando[-2:] == ["tasks", "listar"]
    assert chamadas[0][0][0] == comando


def test_troca_agendada_espera_pai_troca_e_relanca(tmp_path):
    executavel = tmp_path / "notion-automacoes.exe"
    temporario = tmp_path / "download.exe"
    backup = tmp_path / "notion-automacoes.exe.previous"
    executavel.write_bytes(b"antigo")
    temporario.write_bytes(b"novo")
    relancamentos = []

    codigo = updater.executar_troca_agendada(
        [
            "123",
            str(temporario),
            str(backup),
            str(executavel),
            "--",
            "tasks",
            "listar",
        ],
        waiter=lambda pid: relancamentos.append(("esperou", pid)),
        runner=lambda comando, **kwargs: relancamentos.append(("relancou", comando, kwargs)),
    )

    assert codigo == 0
    assert executavel.read_bytes() == b"novo"
    assert backup.read_bytes() == b"antigo"
    assert relancamentos[0] == ("esperou", 123)
    assert relancamentos[1][0] == "relancou"


def test_troca_agendada_relanca_o_executavel_novo_como_instancia_independente(
    tmp_path, monkeypatch
):
    """O helper é um processo PyInstaller: o executável novo, filho dele, herdaria a pasta de
    extração do helper (``_PYI_APPLICATION_HOME_DIR``) e morreria quando o helper saísse.

    Medido no Windows em 21/10/2026: o comando original era relançado, vivia 0,8 s e se perdia
    sem erro. ``PYINSTALLER_RESET_ENVIRONMENT=1`` manda o bootloader extrair uma pasta própria.
    """

    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI123")
    executavel = tmp_path / "notion-automacoes.exe"
    temporario = tmp_path / "download.exe"
    executavel.write_bytes(b"antigo")
    temporario.write_bytes(b"novo")
    relancamentos = []

    updater.executar_troca_agendada(
        ["123", str(temporario), str(tmp_path / "x.previous"), str(executavel), "--", "tasks"],
        waiter=lambda pid: None,
        runner=lambda comando, **kwargs: relancamentos.append((comando, kwargs)),
    )

    (comando, kwargs), = relancamentos
    assert comando == [str(executavel), "tasks"]
    assert kwargs["env"][updater.VARIAVEL_RESET_PYINSTALLER] == "1"
    assert os.environ.get(updater.VARIAVEL_RESET_PYINSTALLER) is None


def test_atualizar_nativo_dry_run_nao_baixa_nem_toca_no_executavel(tmp_path):
    executavel = tmp_path / "notion-automacoes"
    executavel.write_bytes(b"antigo")
    release = release_fake()
    def opener(*_args, **_kwargs):
        pytest.fail("dry-run não deve baixar assets")

    resultado = updater.atualizar_nativo(
        "0.3.0",
        executavel=executavel,
        alvo="linux-x64",
        release=release,
        apenas_verificar=True,
        opener=opener,
    )

    assert resultado["status"] == "disponivel"
    assert resultado["aplicado"] is False
    assert executavel.read_bytes() == b"antigo"


def test_atualizar_nativo_linux_baixa_valida_e_troca(tmp_path):
    executavel = tmp_path / "notion-automacoes"
    executavel.write_bytes(b"antigo")
    binario = b"novo"
    release = release_fake()
    plano = updater.planejar_atualizacao("0.3.0", alvo="linux-x64", release=release).plano
    assert plano is not None
    opener = fazer_opener(
        {
            plano.url_checksum: hashlib.sha256(binario).hexdigest().encode(),
            plano.url_binario: binario,
        }
    )

    resultado = updater.atualizar_nativo(
        "0.3.0",
        executavel=executavel,
        alvo="linux-x64",
        release=release,
        sistema="Linux",
        opener=opener,
    )

    assert resultado["status"] == "atualizado"
    assert resultado["aplicado"] is True
    assert resultado["mensagem"] == "Atualizado de 0.3.0 para 0.4.0."
    assert resultado["executavel"] == str(executavel.resolve())
    assert executavel.read_bytes() == binario
    assert Path(resultado["backup"]).read_bytes() == b"antigo"


def test_auto_update_aplicado_pede_reinicio_do_comando(tmp_path):
    """Troca em processo vivo não pode continuar importando do arquivo antigo."""

    executavel = tmp_path / "notion-automacoes"
    executavel.write_bytes(b"antigo")
    binario = b"novo"
    release = release_fake()
    plano = updater.planejar_atualizacao("0.3.0", alvo="linux-x64", release=release).plano
    assert plano is not None
    opener = fazer_opener(
        {
            plano.url_checksum: hashlib.sha256(binario).hexdigest().encode(),
            plano.url_binario: binario,
        }
    )

    resultado = updater.atualizar_automaticamente(
        "0.3.0",
        executavel=executavel,
        cache=tmp_path / "cache.json",
        alvo="linux-x64",
        release=release,
        sistema="Linux",
        opener=opener,
    )

    assert resultado["reiniciar"] is True
    assert resultado["executavel"] == str(executavel.resolve())


def test_auto_update_sem_troca_nao_pede_reinicio(tmp_path):
    resultado = updater.atualizar_automaticamente(
        "0.4.0",
        cache=tmp_path / "cache.json",
        alvo="linux-x64",
        release=release_fake(versao="0.4.0"),
    )

    assert resultado["status"] == "atualizado"
    assert resultado["reiniciar"] is False


def test_relanca_executavel_novo_com_ambiente_pyinstaller_limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/tmp/antigo")
    chamadas = []

    codigo = updater.relancar_atualizado(
        tmp_path / "notion-automacoes",
        ["tasks", "listar"],
        runner=lambda comando, **kwargs: chamadas.append((comando, kwargs)) or 7,
    )

    assert codigo == 7
    comando, kwargs = chamadas[0]
    assert comando == [str(tmp_path / "notion-automacoes"), "tasks", "listar"]
    assert kwargs["env"][updater.VARIAVEL_RESET_PYINSTALLER] == "1"
    assert os.environ.get(updater.VARIAVEL_RESET_PYINSTALLER) is None


def test_relancamento_que_falha_vira_erro_legivel(tmp_path):
    def runner(*_args, **_kwargs):
        raise FileNotFoundError("sumiu")

    with pytest.raises(updater.AtualizacaoNativaError, match="não foi possível relançá-lo"):
        updater.relancar_atualizado(tmp_path / "x", [], runner=runner)


def test_auto_update_respeita_cache(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{}", encoding="utf-8")
    agora = time.time()
    os.utime(cache, (agora - 1, agora - 1))
    resultado = updater.atualizar_automaticamente(
        "0.3.0",
        cache=cache,
        opener=lambda *_args, **_kwargs: pytest.fail("cache deveria evitar a rede"),
    )

    assert resultado["status"] == "verificacao_em_cache"


@pytest.mark.parametrize(
    ("deslocamento", "esperado"),
    [
        (-0.5, True),  # mtime 0,5 s no futuro: relógio de arquivo adiantado (Windows)
        (-3600.0, False),  # mtime 1 h no futuro: não é cache confiável
        (1.0, True),  # 1 s no passado
        (updater.TTL_CACHE_VERIFICACAO + 1, False),  # mais velho que o TTL
    ],
)
def test_cache_fresco_tolera_relogio_de_arquivo_adiantado(tmp_path, deslocamento, esperado):
    cache = tmp_path / "cache.json"
    cache.write_text("{}", encoding="utf-8")
    agora = 1_800_000_000.0
    os.utime(cache, (agora - deslocamento, agora - deslocamento))

    assert updater._cache_fresco(cache, agora=agora) is esperado
