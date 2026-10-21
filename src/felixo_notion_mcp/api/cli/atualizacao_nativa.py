"""Atualização segura dos executáveis nativos publicados em Releases.

O módulo fica na borda da distribuição porque conhece o GitHub e o processo
do executável. A parte que decide se um artefato é válido permanece pura e
testável, sem depender de um binário PyInstaller ou de uma chamada ao Notion.

O contrato de uma Release nativa é deliberadamente pequeno:

* a tag é um SemVer estável, por exemplo ``v0.4.0``;
* cada alvo possui um asset com nome fixo e um asset irmão ``.sha256``;
* somente o asset correspondente ao sistema atual é baixado;
* a troca preserva a versão anterior em ``.previous``.

O empacotamento e a assinatura continuam sendo responsabilidades do workflow
de release. Este módulo não baixa nem executa código quando o processo não é
um binário nativo.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORIO_GITHUB = "Felipe-Alcantara/notion-tasks-cli"
URL_RELEASES = f"https://api.github.com/repos/{REPOSITORIO_GITHUB}/releases"
URL_LATEST = f"{URL_RELEASES}/latest"
USER_AGENT = "notion-automacoes-native-updater/1"
TEMPO_LIMITE_REDE = 15
TEMPO_ESPERA_PROCESSO = 120
MAXIMO_DOWNLOAD = 250 * 1024 * 1024
INTERVALO_ESPERA_PROCESSO = 0.1
TTL_CACHE_VERIFICACAO = 24 * 60 * 60
# No Windows o mtime do arquivo pode ficar à frente de time.time() (granularidades diferentes).
TOLERANCIA_RELOGIO_CACHE = 2.0

ARGUMENTO_APLICAR = "--__aplicar-atualizacao-nativa"
ARQUIVO_CACHE = "verificacao-atualizacao.json"
# Faz o bootloader do executável novo extrair o próprio conteúdo em vez de
# herdar a pasta temporária do processo antigo (PyInstaller >= 6.10).
VARIAVEL_RESET_PYINSTALLER = "PYINSTALLER_RESET_ENVIRONMENT"


class AtualizacaoNativaError(RuntimeError):
    """Erro legível ao consultar, validar ou substituir um binário nativo."""


@dataclass(frozen=True)
class AlvoNativo:
    """Identidade e nomes de assets de um alvo suportado."""

    identificador: str
    sistema: str
    arquitetura: str
    asset: str

    @property
    def checksum(self) -> str:
        """Nome do asset que contém o SHA-256 do binário."""

        return f"{self.asset}.sha256"


ALVOS_NATIVOS: dict[str, AlvoNativo] = {
    "windows-x64": AlvoNativo(
        "windows-x64", "Windows", "x64", "notion-automacoes-windows-x64.exe"
    ),
    "macos-x64": AlvoNativo(
        "macos-x64", "macOS", "Intel", "notion-automacoes-macos-x64"
    ),
    "macos-arm64": AlvoNativo(
        "macos-arm64", "macOS", "Apple Silicon", "notion-automacoes-macos-arm64"
    ),
    "linux-x64": AlvoNativo(
        "linux-x64", "Linux", "x64", "notion-automacoes-linux-x64"
    ),
}


@dataclass(frozen=True)
class ReleaseNativa:
    """Metadados estáveis de uma Release do GitHub."""

    tag: str
    versao: str
    url: str
    assets: Mapping[str, str]


@dataclass(frozen=True)
class PlanoAtualizacao:
    """Plano validado para baixar um único asset nativo."""

    versao_atual: str
    versao_disponivel: str
    alvo: AlvoNativo
    release: ReleaseNativa
    url_binario: str
    url_checksum: str


@dataclass(frozen=True)
class Planejamento:
    """Resultado da consulta antes de qualquer escrita no disco."""

    status: str
    mensagem: str
    alvo: AlvoNativo | None = None
    release: ReleaseNativa | None = None
    plano: PlanoAtualizacao | None = None


_VERSAO_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")


def normalizar_versao(valor: str) -> str:
    """Converte ``v1.2.3`` e ``1.2.3`` para ``1.2.3``.

    Releases prévias não entram no canal automático: a validação rejeita
    sufixos como ``-rc1`` para não instalar uma versão de teste em produção.
    """

    if not isinstance(valor, str):
        raise AtualizacaoNativaError("A versão da Release não é texto.")
    correspondencia = _VERSAO_RE.fullmatch(valor.strip())
    if not correspondencia:
        raise AtualizacaoNativaError(
            f"Versão inválida: {valor!r}; use uma tag SemVer estável (vX.Y.Z)."
        )
    major, minor, patch = (int(parte) for parte in correspondencia.groups())
    return f"{major}.{minor}.{patch}"


def chave_versao(valor: str) -> tuple[int, int, int]:
    """Retorna a chave comparável de uma versão estável."""

    normalizada = normalizar_versao(valor)
    return tuple(int(parte) for parte in normalizada.split("."))  # type: ignore[return-value]


def detectar_alvo(
    sistema: str | None = None,
    arquitetura: str | None = None,
) -> str | None:
    """Detecta um dos quatro alvos distribuídos, sem inferir outro binário."""

    sistema_atual = (sistema or platform.system()).strip().lower()
    arquitetura_atual = (arquitetura or platform.machine()).strip().lower()

    aliases_x64 = {"amd64", "x86_64", "x64"}
    aliases_arm64 = {"arm64", "aarch64"}
    if sistema_atual in {"windows", "win32", "mingw", "msys"}:
        return "windows-x64" if arquitetura_atual in aliases_x64 else None
    if sistema_atual in {"darwin", "macos", "mac os", "osx"}:
        if arquitetura_atual in aliases_arm64:
            return "macos-arm64"
        if arquitetura_atual in aliases_x64:
            return "macos-x64"
        return None
    if sistema_atual == "linux" and arquitetura_atual in aliases_x64:
        return "linux-x64"
    return None


def obter_alvo(identificador: str) -> AlvoNativo:
    """Busca um alvo pelo identificador documentado."""

    try:
        return ALVOS_NATIVOS[identificador]
    except KeyError as exc:
        aceitos = ", ".join(ALVOS_NATIVOS)
        raise AtualizacaoNativaError(
            f"Alvo nativo não suportado: {identificador!r}. Aceitos: {aceitos}."
        ) from exc


def _abrir_url(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float = TEMPO_LIMITE_REDE,
) -> bytes:
    """Lê uma URL com cabeçalhos previsíveis e limite de tamanho."""

    requisicao = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        resposta = opener(requisicao, timeout=timeout)
        with resposta:
            dados = resposta.read(MAXIMO_DOWNLOAD + 1)
    except Exception as exc:  # noqa: BLE001 - fronteira de rede
        raise AtualizacaoNativaError(
            f"Não foi possível baixar o recurso da Release: {url} ({exc})."
        ) from exc
    if len(dados) > MAXIMO_DOWNLOAD:
        raise AtualizacaoNativaError(
            f"Download recusado por exceder {MAXIMO_DOWNLOAD} bytes: {url}."
        )
    return dados


def _url_release(tag: str | None) -> str:
    if tag is None:
        return URL_LATEST
    return f"{URL_RELEASES}/tags/{quote(tag, safe='')}"


def consultar_release(
    tag: str | None = None,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = TEMPO_LIMITE_REDE,
) -> ReleaseNativa:
    """Consulta uma Release estável e normaliza seus assets."""

    corpo = _abrir_url(_url_release(tag), opener=opener, timeout=timeout)
    try:
        payload = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AtualizacaoNativaError("A resposta da Release não é JSON válido.") from exc
    if not isinstance(payload, dict):
        raise AtualizacaoNativaError("A resposta da Release não é um objeto JSON.")
    if payload.get("draft") or payload.get("prerelease"):
        raise AtualizacaoNativaError("A Release encontrada é rascunho ou prévia.")

    tag_name = payload.get("tag_name")
    versao = normalizar_versao(tag_name)
    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, list):
        raise AtualizacaoNativaError("A Release não contém a lista de assets.")

    assets: dict[str, str] = {}
    for item in assets_payload:
        if not isinstance(item, dict):
            continue
        nome = item.get("name")
        url = item.get("browser_download_url")
        if isinstance(nome, str) and isinstance(url, str) and nome not in assets:
            assets[nome] = url
    url = payload.get("html_url")
    if not isinstance(url, str):
        url = f"https://github.com/{REPOSITORIO_GITHUB}/releases/tag/{tag_name}"
    return ReleaseNativa(tag=str(tag_name), versao=versao, url=url, assets=assets)


def planejar_atualizacao(
    versao_atual: str,
    *,
    alvo: str | None = None,
    release: ReleaseNativa | None = None,
    tag: str | None = None,
    permitir_retrocesso: bool = False,
    opener: Callable[..., Any] = urlopen,
    timeout: float = TEMPO_LIMITE_REDE,
) -> Planejamento:
    """Monta o plano sem tocar no executável nem no diretório de instalação."""

    atual = normalizar_versao(versao_atual)
    identificador = alvo or detectar_alvo()
    if identificador is None:
        return Planejamento(
            "alvo_nao_suportado",
            "A arquitetura deste sistema não possui binário nativo publicado.",
        )
    alvo_info = obter_alvo(identificador)
    release_info = release or consultar_release(tag, opener=opener, timeout=timeout)
    versao_release = chave_versao(release_info.versao)
    versao_atual_chave = chave_versao(atual)
    if versao_release == versao_atual_chave or (
        versao_release < versao_atual_chave and not permitir_retrocesso
    ):
        return Planejamento(
            "atualizado",
            f"A versão {atual} já é igual ou mais nova que {release_info.versao}.",
            alvo=alvo_info,
            release=release_info,
        )

    url_binario = release_info.assets.get(alvo_info.asset)
    url_checksum = release_info.assets.get(alvo_info.checksum)
    if not url_binario or not url_checksum:
        return Planejamento(
            "asset_indisponivel",
            (
                f"A Release {release_info.tag} não publicou o par de assets "
                f"{alvo_info.asset} e {alvo_info.checksum}."
            ),
            alvo=alvo_info,
            release=release_info,
        )
    return Planejamento(
        "disponivel",
        f"A versão {release_info.versao} está disponível para {identificador}.",
        alvo=alvo_info,
        release=release_info,
        plano=PlanoAtualizacao(
            atual,
            release_info.versao,
            alvo_info,
            release_info,
            url_binario,
            url_checksum,
        ),
    )


def extrair_sha256(texto: str) -> str:
    """Extrai o primeiro SHA-256 hexadecimal de um asset de checksum."""

    correspondencia = _SHA256_RE.search(texto)
    if not correspondencia:
        raise AtualizacaoNativaError("O asset de checksum não contém SHA-256 válido.")
    return correspondencia.group(1).lower()


def validar_sha256(dados: bytes, checksum: str) -> str:
    """Confere o conteúdo baixado e retorna seu digest normalizado."""

    esperado = extrair_sha256(checksum)
    recebido = hashlib.sha256(dados).hexdigest()
    if recebido != esperado:
        raise AtualizacaoNativaError(
            f"Checksum SHA-256 divergente: esperado {esperado}, recebido {recebido}."
        )
    return recebido


def baixar_e_validar(
    plano: PlanoAtualizacao,
    destino: Path,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = TEMPO_LIMITE_REDE,
) -> dict[str, Any]:
    """Baixa o binário e só o deixa no destino depois de validar o checksum."""

    destino = Path(destino)
    existia = destino.exists()
    try:
        checksum_bytes = _abrir_url(
            plano.url_checksum, opener=opener, timeout=timeout
        )
        checksum = checksum_bytes.decode("utf-8", errors="replace")
        dados = _abrir_url(plano.url_binario, opener=opener, timeout=timeout)
        digest = validar_sha256(dados, checksum)
        destino.write_bytes(dados)
    except Exception:
        if not existia:
            destino.unlink(missing_ok=True)
        raise
    return {"bytes": len(dados), "sha256": digest, "arquivo": str(destino)}


def caminho_backup(executavel: Path | str) -> Path:
    """Retorna o backup local da última versão instalada."""

    return Path(f"{Path(executavel)}.previous")


def trocar_arquivo(
    executavel: Path | str,
    temporario: Path | str,
    *,
    backup: Path | str | None = None,
) -> Path:
    """Troca atomicamente o executável e restaura o anterior se algo falhar."""

    atual = Path(executavel)
    novo = Path(temporario)
    anterior = Path(backup) if backup is not None else caminho_backup(atual)
    if not novo.is_file():
        raise AtualizacaoNativaError(f"Binário temporário não encontrado: {novo}.")

    modo: int | None = None
    if atual.exists():
        modo = stat.S_IMODE(atual.stat().st_mode)
    try:
        if modo is not None:
            os.chmod(novo, modo)
        if atual.exists():
            os.replace(atual, anterior)
        os.replace(novo, atual)
    except OSError as exc:
        if anterior.exists() and not atual.exists():
            try:
                os.replace(anterior, atual)
            except OSError:
                pass
        raise AtualizacaoNativaError(
            f"Não foi possível trocar o executável {atual}: {exc}."
        ) from exc
    return anterior


def _processo_vivo(pid: int) -> bool:
    if os.name == "nt":
        try:
            import ctypes

            processo = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not processo:
                return False
            codigo = ctypes.c_ulong()
            consultado = ctypes.windll.kernel32.GetExitCodeProcess(
                processo, ctypes.byref(codigo)
            )
            ctypes.windll.kernel32.CloseHandle(processo)
            return bool(consultado and codigo.value == 259)
        except (AttributeError, OSError):
            # Ambientes Windows restritos podem não expor a API; o fallback
            # mantém a cobertura em runtimes alternativos.
            pass
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _aguardar_processamento(pid: int, timeout: float = TEMPO_ESPERA_PROCESSO) -> None:
    """Espera o processo pai liberar o executável no Windows."""

    limite = time.monotonic() + timeout
    while _processo_vivo(pid):
        if time.monotonic() >= limite:
            raise AtualizacaoNativaError(
                f"O processo {pid} não liberou o executável dentro do prazo."
            )
        time.sleep(INTERVALO_ESPERA_PROCESSO)


def agendar_troca_windows(
    executavel: Path | str,
    temporario: Path | str,
    *,
    backup: Path | str | None = None,
    argumentos: Sequence[str] = (),
    runner: Callable[..., Any] = subprocess.Popen,
) -> list[str]:
    """Agenda a troca em um processo filho iniciado pelo próprio executável."""

    atual = Path(executavel).resolve()
    novo = Path(temporario).resolve()
    anterior = Path(backup or caminho_backup(atual)).resolve()
    comando = [
        str(atual),
        ARGUMENTO_APLICAR,
        str(os.getpid()),
        str(novo),
        str(anterior),
        str(atual),
        "--",
        *argumentos,
    ]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        runner(comando, close_fds=True, creationflags=flags)
    except OSError as exc:
        raise AtualizacaoNativaError(
            f"Não foi possível agendar a troca do executável no Windows: {exc}."
        ) from exc
    return comando


def ambiente_de_instancia_nova() -> dict[str, str]:
    """Ambiente para iniciar o executável novo como uma instância independente.

    Quem o lança (o processo antigo, ou o helper do Windows) é, ele mesmo, um onefile do
    PyInstaller. Sem ``PYINSTALLER_RESET_ENVIRONMENT`` o filho herda a pasta de extração do
    pai (``_PYI_APPLICATION_HOME_DIR``) e passa a depender dela: ela some quando o pai sai.
    """

    ambiente = dict(os.environ)
    ambiente[VARIAVEL_RESET_PYINSTALLER] = "1"
    return ambiente


def executar_troca_agendada(
    argumentos: Sequence[str],
    *,
    waiter: Callable[[int], None] = _aguardar_processamento,
    runner: Callable[..., Any] = subprocess.Popen,
) -> int:
    """Executa a etapa interna da troca e relança os argumentos originais.

    O relançamento é uma instância independente: o helper sai logo em seguida, e o comando
    original, se herdasse a pasta de extração dele, morreria junto (medido no Windows).
    """

    if len(argumentos) < 4:
        raise AtualizacaoNativaError("Argumentos incompletos para a troca agendada.")
    try:
        pid = int(argumentos[0])
    except ValueError as exc:
        raise AtualizacaoNativaError("PID inválido na troca agendada.") from exc
    temporario = Path(argumentos[1])
    anterior = Path(argumentos[2])
    executavel = Path(argumentos[3])
    try:
        separador = list(argumentos).index("--", 4)
    except ValueError:
        originais: list[str] = []
    else:
        originais = list(argumentos[separador + 1 :])

    waiter(pid)
    trocar_arquivo(executavel, temporario, backup=anterior)
    if originais:
        try:
            runner(
                [str(executavel), *originais],
                close_fds=True,
                env=ambiente_de_instancia_nova(),
            )
        except OSError as exc:
            raise AtualizacaoNativaError(
                f"Binário atualizado, mas não foi possível relançá-lo: {exc}."
            ) from exc
    return 0


def relancar_atualizado(
    executavel: Path | str,
    argumentos: Sequence[str],
    *,
    runner: Callable[..., Any] = subprocess.call,
) -> int:
    """Continua o comando original no executável recém-instalado.

    Em macOS e Linux a troca acontece com o processo antigo ainda vivo. O
    executável onefile lê módulos do próprio arquivo sob demanda; depois da
    troca, um import tardio leria o arquivo novo com os offsets do antigo e
    falharia com ``Error -3 while decompressing data``. Por isso o comando
    roda num processo novo e o antigo só repassa o código de saída.
    """

    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.flush()
        except (AttributeError, OSError, ValueError):
            pass
    try:
        return int(runner([str(executavel), *argumentos], env=ambiente_de_instancia_nova()))
    except OSError as exc:
        raise AtualizacaoNativaError(
            f"Binário atualizado, mas não foi possível relançá-lo: {exc}."
        ) from exc


def _serializar_planejamento(resultado: Planejamento) -> dict[str, Any]:
    dados: dict[str, Any] = {
        "ok": resultado.status not in {"asset_indisponivel", "alvo_nao_suportado"},
        "status": resultado.status,
        "mensagem": resultado.mensagem,
    }
    if resultado.alvo is not None:
        dados["alvo"] = asdict(resultado.alvo)
    if resultado.release is not None:
        dados["release"] = {
            "tag": resultado.release.tag,
            "versao": resultado.release.versao,
            "url": resultado.release.url,
            "assets": dict(resultado.release.assets),
        }
    if resultado.plano is not None:
        dados["plano"] = {
            "versao_atual": resultado.plano.versao_atual,
            "versao_disponivel": resultado.plano.versao_disponivel,
            "alvo": resultado.plano.alvo.identificador,
            "url_binario": resultado.plano.url_binario,
            "url_checksum": resultado.plano.url_checksum,
            "release": resultado.plano.release.url,
        }
    return dados


def atualizar_nativo(
    versao_atual: str,
    *,
    executavel: Path | str | None = None,
    alvo: str | None = None,
    tag: str | None = None,
    permitir_retrocesso: bool = False,
    apenas_verificar: bool = False,
    argumentos: Sequence[str] = (),
    sistema: str | None = None,
    release: ReleaseNativa | None = None,
    opener: Callable[..., Any] = urlopen,
    runner: Callable[..., Any] = subprocess.Popen,
    timeout: float = TEMPO_LIMITE_REDE,
) -> dict[str, Any]:
    """Consulta, baixa e instala uma Release nativa validada.

    ``permitir_retrocesso`` existe para o fluxo manual de rollback no futuro;
    o canal automático nunca faz downgrade. A versão antiga fica em
    ``<executável>.previous`` como recuperação local imediata.
    """

    atual = normalizar_versao(versao_atual)
    planejamento = planejar_atualizacao(
        atual,
        alvo=alvo,
        release=release,
        tag=tag,
        permitir_retrocesso=permitir_retrocesso,
        opener=opener,
        timeout=timeout,
    )
    dados = _serializar_planejamento(planejamento)
    if planejamento.status != "disponivel":
        return dados
    assert planejamento.plano is not None
    if (
        not permitir_retrocesso
        and chave_versao(planejamento.plano.versao_disponivel) <= chave_versao(atual)
    ):
        dados["status"] = "atualizado"
        dados["mensagem"] = "A atualização não faria downgrade da instalação atual."
        return dados
    if apenas_verificar:
        dados["status"] = "disponivel"
        dados["aplicado"] = False
        return dados

    caminho = Path(executavel or sys.executable).resolve()
    if not caminho.is_file():
        raise AtualizacaoNativaError(f"Executável atual não encontrado: {caminho}.")
    temporario: Path | None = None
    try:
        fd, nome = tempfile.mkstemp(
            prefix=f".{caminho.stem}-update-",
            suffix=".download",
            dir=caminho.parent,
        )
        os.close(fd)
        temporario = Path(nome)
        baixar_e_validar(
            planejamento.plano,
            temporario,
            opener=opener,
            timeout=timeout,
        )
        if (sistema or platform.system()).lower() == "windows":
            comando = agendar_troca_windows(
                caminho,
                temporario,
                argumentos=argumentos,
                runner=runner,
            )
            dados.update(
                {
                    "status": "agendado",
                    "aplicado": False,
                    "comando": comando,
                    "backup": str(caminho_backup(caminho)),
                }
            )
            temporario = None
            return dados
        backup = trocar_arquivo(caminho, temporario)
        temporario = None
        dados.update(
            {
                "status": "atualizado",
                "aplicado": True,
                "backup": str(backup),
                "executavel": str(caminho),
                "mensagem": (
                    f"Atualizado de {atual} para "
                    f"{planejamento.plano.versao_disponivel}."
                ),
            }
        )
        return dados
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


def caminho_cache() -> Path:
    """Retorna o caminho de cache sem misturar credenciais ou configurações."""

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "notion-automacoes" / ARQUIVO_CACHE
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "notion-automacoes" / ARQUIVO_CACHE
    return Path.home() / ".cache" / "notion-automacoes" / ARQUIVO_CACHE


def _cache_fresco(caminho: Path, agora: float | None = None) -> bool:
    """Diz se o cache vale; tolera mtime levemente adiantado (granularidade do Windows)."""

    try:
        momento = time.time() if agora is None else agora
        idade = momento - caminho.stat().st_mtime
    except OSError:
        return False
    return -TOLERANCIA_RELOGIO_CACHE <= idade < TTL_CACHE_VERIFICACAO


def _gravar_cache(caminho: Path, status: str) -> None:
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            json.dumps({"verificado_em": time.time(), "status": status}),
            encoding="utf-8",
        )
    except OSError:
        # O cache é apenas uma otimização; disco somente leitura não bloqueia
        # a execução da CLI nem transforma atualização opcional em erro.
        pass


def atualizar_automaticamente(
    versao_atual: str,
    *,
    executavel: Path | str | None = None,
    argumentos: Sequence[str] = (),
    cache: Path | str | None = None,
    forcar: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Tenta a atualização automática sem quebrar o comando principal."""

    caminho_cache_atual = Path(cache) if cache is not None else caminho_cache()
    if not forcar and _cache_fresco(caminho_cache_atual):
        return {
            "ok": True,
            "status": "verificacao_em_cache",
            "mensagem": "A Release já foi consultada nas últimas 24 horas.",
        }
    try:
        dados = atualizar_nativo(
            versao_atual,
            executavel=executavel,
            argumentos=argumentos,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 - atualização é opcional
        _gravar_cache(caminho_cache_atual, "erro")
        return {
            "ok": False,
            "status": "erro_ignorado",
            "mensagem": f"Atualização automática ignorada: {exc}",
        }
    _gravar_cache(caminho_cache_atual, str(dados.get("status", "desconhecido")))
    # Troca aplicada em processo vivo (macOS/Linux) exige continuar o comando
    # no executável novo; no Windows o helper agendado já relança.
    dados["reiniciar"] = bool(dados.get("aplicado"))
    return dados
