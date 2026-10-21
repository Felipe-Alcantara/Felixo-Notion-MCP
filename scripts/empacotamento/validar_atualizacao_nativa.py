"""Valida, num sistema real, o auto-update e o rollback do binário nativo.

Roda o ciclo que uma pessoa faz com as Releases públicas, numa pasta descartável, com
perfis e cache isolados e o ``PATH`` do binário sem Python:

1. baixa o binário anterior e confere o SHA-256 publicado;
2. ``update --dry-run`` aponta a Release mais nova e não toca no arquivo;
3. um comando normal dispara o auto-update. No Windows a troca é do helper agendado, que
   relança o comando original sem console. ``auth adicionar`` serve de sentinela: grava o
   perfil na pasta isolada e prova que o relançamento rodou com os argumentos certos;
4. confere a troca, o backup ``.previous`` e o executável novo;
5. rollback manual (``.previous``) e rollback pela Release anterior;
6. o mesmo ciclo com outro processo do binário vivo (o caminho "arquivo em uso"), mais uma
   segunda atualização com o ``.previous`` ainda em uso, registrada como observação.

Só lê as Releases: não publica nada e não usa credencial. A saída é um relatório em
Markdown; o código de saída é 1 se algo obrigatório falhar.

    uv run python -m scripts.empacotamento.validar_atualizacao_nativa --saida relatorio.md
    uv run python -m scripts.empacotamento.validar_atualizacao_nativa \\
        --de-binario dist/native/notion-automacoes-linux-x64 --de-versao v0.4.9

Com ``--de-binario`` (um build deste checkout) o comando que dispara o auto-update **tem**
de concluir; com as Releases publicadas, que ainda não trazem a correção do relançamento,
essa falha é registrada como observação e não reprova o relatório.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from felixo_notion_mcp.api.cli import atualizacao_nativa as nativa
from scripts.empacotamento.build_native import sha256
from scripts.empacotamento.smoke_native import ambiente_isolado

VERSAO_PADRAO_DE = "v0.4.1"
TOKEN_FALSO = "ntn_token_falso_de_teste"
DATABASE_FALSO = "0" * 32
ARQUIVO_PERFIS = ".notion-workspaces.json"
TENTATIVAS_DE_REDE = 3
#: A consulta ao GitHub tem prazo de 15 s no updater e, em rede lenta, estoura.
PAUSA_ENTRE_TENTATIVAS = 3.0
#: O helper do Windows espera o pai sair, troca o arquivo e relança; no primeiro uso de um
#: executável novo o antivírus ainda o examina.
TEMPO_HELPER_WINDOWS = 90.0
TEMPO_RELANCAMENTO = 60.0
TEMPO_PROCESSO_ATIVO = 4.0
#: O processo em uso desiste sozinho depois disto; a troca precisa terminar antes.
VALIDADE_DO_PROCESSO_ATIVO = nativa.TEMPO_ESPERA_PROCESSO
WINDOWS = os.name == "nt"


@dataclass
class Relatorio:
    """Acumula o relatório em Markdown e conta as falhas obrigatórias."""

    linhas: list[str] = field(default_factory=list)
    falhas: int = 0

    def escrever(self, texto: str = "") -> None:
        print(texto, flush=True)
        self.linhas.append(texto)

    def titulo(self, nivel: int, texto: str) -> None:
        self.escrever()
        self.escrever(f"{'#' * nivel} {texto}")
        self.escrever()

    def conferir(
        self, descricao: str, ok: bool, detalhe: str = "", *, obrigatorio: bool = True
    ) -> bool:
        """Registra uma conferência; as obrigatórias que falham reprovam o relatório."""

        marca = "✓" if ok else ("✗" if obrigatorio else "⚠")
        if not ok and obrigatorio:
            self.falhas += 1
        self.escrever(f"- {marca} {descricao}" + (f" — {detalhe}" if detalhe else ""))
        return ok

    def observar(self, descricao: str, detalhe: str) -> None:
        self.escrever(f"- ℹ {descricao} — {detalhe}")


@dataclass(frozen=True)
class Execucao:
    """Resultado de um comando do binário."""

    codigo: int
    saida: str
    erro: str
    segundos: float

    @property
    def resumo(self) -> str:
        texto = (self.erro or self.saida).strip().replace("\n", " ⏎ ")
        return texto[:240] + ("…" if len(texto) > 240 else "")


@dataclass(frozen=True)
class Origem:
    """Binário anterior do ciclo e o que dele se sabe."""

    caminho: Path
    versao: str
    sha: str
    tag: str | None  # ``None`` num build local: não há Release anterior para baixar


def path_minimo() -> str:
    """``PATH`` de uma máquina sem Python: só as pastas do sistema."""

    if WINDOWS:
        raiz = os.environ.get("SystemRoot", r"C:\Windows")
        return os.pathsep.join([rf"{raiz}\System32", raiz])
    return os.pathsep.join(["/usr/bin", "/bin"])


def python_no_path() -> list[str]:
    """Pythons que o ``PATH`` mínimo ainda enxerga (os runners do macOS trazem o do sistema)."""

    achados = (shutil.which(nome, path=path_minimo()) for nome in ("python", "python3", "py"))
    return sorted({caminho for caminho in achados if caminho})


def ambiente_do_binario(base: Path, *, auto_update: bool) -> dict[str, str]:
    """Ambiente do binário: sem Python, com perfis e cache dentro de ``base``.

    ``auto_update=False`` mantém ``NOTION_AUTOMACOES_NO_UPDATE=1`` (comandos de conferência);
    ``True`` é o ambiente de quem usa de verdade e só dispara a troca com o cache limpo.
    """

    descartadas = {"VIRTUAL_ENV", "PYINSTALLER_RESET_ENVIRONMENT"}
    ambiente = {
        nome: valor
        for nome, valor in os.environ.items()
        if not nome.upper().startswith("PYTHON") and nome.upper() not in descartadas
    }
    ambiente["PATH"] = path_minimo()
    ambiente.update(ambiente_isolado(base))
    if auto_update:
        ambiente.pop("NOTION_AUTOMACOES_NO_UPDATE")
    return ambiente


def executar(
    executavel: Path, *argumentos: str, ambiente: Mapping[str, str], limite: float = 300.0
) -> Execucao:
    """Roda o binário e captura a saída como um agente ou script faria."""

    inicio = time.monotonic()
    resultado = subprocess.run(
        [str(executavel), *argumentos],
        capture_output=True,
        env=dict(ambiente),
        timeout=limite,
        check=False,
    )
    return Execucao(
        resultado.returncode,
        resultado.stdout.decode("utf-8", errors="replace"),
        resultado.stderr.decode("utf-8", errors="replace"),
        time.monotonic() - inicio,
    )


def _baixar(url: str, *, abrir: Callable[..., object] = urlopen) -> bytes:
    """Baixa uma URL pública do GitHub, repetindo em falha de rede."""

    ultimo: OSError | None = None
    for tentativa in range(1, TENTATIVAS_DE_REDE + 1):
        try:
            requisicao = Request(url, headers={"User-Agent": nativa.USER_AGENT})
            with abrir(requisicao, timeout=120) as resposta:  # type: ignore[attr-defined]
                return resposta.read()
        except OSError as exc:
            ultimo = exc
            time.sleep(PAUSA_ENTRE_TENTATIVAS * tentativa)
    raise RuntimeError(f"Não foi possível baixar {url}: {ultimo}")


def consultar_ultima_release() -> nativa.ReleaseNativa:
    """Release mais nova, com o token do ambiente quando existir.

    Só a consulta deste script é autenticada (a API anônima limita a 60 por hora e por IP, e os
    runners compartilham IPs). O token vai apenas para ``api.github.com``, a URL fixa do
    updater; o binário em teste continua anônimo, como o de quem o usa.
    """

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def abrir(requisicao: Request, *, timeout: float):
        if token and requisicao.host == "api.github.com":
            requisicao.add_header("Authorization", f"Bearer {token}")
        return urlopen(requisicao, timeout=timeout)

    return nativa.consultar_release(opener=abrir)


def baixar_release(tag: str, alvo: nativa.AlvoNativo, pasta: Path) -> tuple[Path, str]:
    """Baixa o asset do alvo e confere o SHA-256 publicado antes de usá-lo."""

    base = f"https://github.com/{nativa.REPOSITORIO_GITHUB}/releases/download/{tag}"
    dados = _baixar(f"{base}/{alvo.asset}")
    checksum = _baixar(f"{base}/{alvo.checksum}").decode("utf-8", errors="replace")
    digest = nativa.validar_sha256(dados, checksum)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / alvo.asset
    caminho.write_bytes(dados)
    return caminho, digest


def tornar_executavel(caminho: Path) -> None:
    if not WINDOWS:
        caminho.chmod(caminho.stat().st_mode | 0o111)


def substituir(executavel: Path, novo: Path) -> None:
    """Troca o executável por ``novo`` como a pessoa faz no rollback manual."""

    temporario = executavel.with_name(f"{executavel.name}.rollback")
    shutil.copyfile(novo, temporario)
    if executavel.exists():
        shutil.copymode(executavel, temporario)
    else:
        tornar_executavel(temporario)
    os.replace(temporario, executavel)


def esperar(condicao: Callable[[], bool], limite: float, intervalo: float = 0.5) -> bool:
    """Repete ``condicao`` até ela valer ou o prazo acabar (sempre testa ao menos uma vez)."""

    fim = time.monotonic() + limite
    while True:
        if condicao():
            return True
        if time.monotonic() >= fim:
            return False
        time.sleep(intervalo)


def perfis_gravados(base: Path) -> list[Path]:
    return list(base.rglob(ARQUIVO_PERFIS))


def status_do_cache(base: Path) -> str | None:
    """Resultado que o auto-update gravou no cache (``agendado``, ``atualizado``, ``erro``)."""

    for arquivo in base.rglob(nativa.ARQUIVO_CACHE):
        try:
            return str(json.loads(arquivo.read_text(encoding="utf-8")).get("status"))
        except (OSError, ValueError):
            return None
    return None


def limpar_estado_do_usuario(base: Path) -> None:
    """Deixa a pasta isolada como a de quem nunca rodou o binário (sem cache nem perfil)."""

    for nome in (nativa.ARQUIVO_CACHE, ARQUIVO_PERFIS):
        for arquivo in base.rglob(nome):
            arquivo.unlink(missing_ok=True)


def argumentos_do_processo_ativo(executavel: Path, pid: int) -> list[str]:
    """Argumentos que deixam o binário parado esperando ``pid``, sem rede e sem trocar nada."""

    ausente = executavel.parent / "inexistente"
    return [
        str(executavel), nativa.ARGUMENTO_APLICAR, str(pid),
        str(ausente / "novo"), str(ausente / "anterior"), str(executavel),
    ]


def iniciar_processo_ativo(
    executavel: Path, ambiente: Mapping[str, str]
) -> subprocess.Popen[bytes]:
    """Mantém outro processo do binário vivo, segurando o arquivo do executável.

    O ponto de entrada interno da troca agendada espera um PID terminar (até
    ``TEMPO_ESPERA_PROCESSO``) antes de tocar em qualquer arquivo. Apontado para o PID deste
    validador, que continua vivo, o processo fica parado sem usar rede; e, como o temporário
    que ele instalaria não existe, ao acordar só sai com erro, sem trocar nada.
    """

    return subprocess.Popen(
        argumentos_do_processo_ativo(executavel, os.getpid()),
        env=dict(ambiente),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def encerrar_processo_ativo(processo: subprocess.Popen[bytes] | None) -> None:
    if processo is None:
        return
    if processo.poll() is None:
        processo.kill()
    processo.wait(timeout=15)


def json_ou_vazio(texto: str) -> dict:
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


def consultar_plano(executavel: Path, ambiente: Mapping[str, str]) -> tuple[dict, Execucao]:
    """``update --dry-run``, repetido quando a rede falha: a consulta não altera nada."""

    for tentativa in range(1, TENTATIVAS_DE_REDE + 1):
        execucao = executar(executavel, "--json", "update", "--dry-run", ambiente=ambiente)
        dados = json_ou_vazio(execucao.saida)
        if dados.get("ok") is True or tentativa == TENTATIVAS_DE_REDE:
            return dados, execucao
        time.sleep(PAUSA_ENTRE_TENTATIVAS)
    raise AssertionError("inalcançável")


def sha_ou_none(caminho: Path) -> str | None:
    """SHA-256 do arquivo, ou ``None`` se ele sumiu ou está trancado pela troca em andamento."""

    try:
        return sha256(caminho)
    except OSError:
        return None


def troca_feita(executavel: Path, destino_sha: str) -> bool:
    return sha_ou_none(executavel) == destino_sha


def sobras_de_download(executavel: Path) -> list[Path]:
    """Temporários ``.download`` que o updater deixa ao lado do executável se a troca falha."""

    return sorted(executavel.parent.glob("*.download"))


def disparar_auto_update(
    executavel: Path, casa: Path, destino_sha: str
) -> tuple[Execucao, int]:
    """Um comando normal, com o auto-update ligado e o cache limpo.

    Se a rede falha, o binário ignora o erro, roda o comando na versão velha e grava
    ``erro`` no cache por 24 h. Nesse caso o estado do usuário é limpo e o disparo se repete.
    """

    for tentativa in range(1, TENTATIVAS_DE_REDE + 1):
        limpar_estado_do_usuario(casa)
        execucao = executar(
            executavel,
            "auth", "adicionar", "sonda", "--token", TOKEN_FALSO,
            "--database", DATABASE_FALSO, "--ativar",
            ambiente=ambiente_do_binario(casa, auto_update=True),
        )
        if status_do_cache(casa) != "erro" or tentativa == TENTATIVAS_DE_REDE:
            return execucao, tentativa
        time.sleep(PAUSA_ENTRE_TENTATIVAS)
    raise AssertionError("inalcançável")


def conferir_comando_original(
    rel: Relatorio, casa: Path, disparo: Execucao, *, exigir: bool
) -> None:
    """O comando que disparou o update tem de concluir no executável novo.

    No Windows quem o roda é o helper, sem console: a prova é o perfil gravado. Em macOS e
    Linux o próprio comando relança e devolve o código de saída.
    """

    if WINDOWS:
        concluiu = esperar(lambda: bool(perfis_gravados(casa)), TEMPO_RELANCAMENTO)
        detalhe = f"disparo com código {disparo.codigo}; helper relançou o comando"
    else:
        concluiu = disparo.codigo == 0 and bool(perfis_gravados(casa))
        detalhe = f"código {disparo.codigo} em {disparo.segundos:.1f}s; {disparo.resumo}"
    rel.conferir(
        "O comando original conclui no executável novo (o perfil `sonda` é gravado)",
        concluiu, detalhe if concluiu else f"não concluiu — {detalhe}", obrigatorio=exigir,
    )
    if not concluiu and not exigir:
        rel.observar(
            "Relançamento nas Releases publicadas",
            "o update foi aplicado, mas o comando que o disparou se perdeu; a correção do "
            "relançamento está no checkout, sem Release que a contenha",
        )


def conferir_troca(
    rel: Relatorio, executavel: Path, origem: Origem, destino_sha: str,
    disparo: Execucao, tentativas: int, ativo: subprocess.Popen[bytes] | None = None,
) -> None:
    """Confere o que o auto-update deixa no disco."""

    if tentativas > 1:
        rel.observar("Rede lenta", f"a consulta ao GitHub falhou e foi repetida ({tentativas}x)")
    if WINDOWS:
        rel.conferir(
            "O comando que dispara o update sai com código 0 e deixa a troca para o helper",
            disparo.codigo == 0, f"código {disparo.codigo} em {disparo.segundos:.1f}s",
        )
        trocou = esperar(
            lambda: troca_feita(executavel, destino_sha) and not sobras_de_download(executavel),
            TEMPO_HELPER_WINDOWS,
        )
    else:
        trocou = troca_feita(executavel, destino_sha) and not sobras_de_download(executavel)
    atual = (sha_ou_none(executavel) or "ausente")[:12]
    rel.conferir(
        "O executável passa a ser o da Release nova, sem `.download` sobrando", trocou, f"{atual}…"
    )
    if ativo is not None and trocou:
        rel.conferir(
            "O processo que estava em uso continua vivo depois da troca",
            ativo.poll() is None, f"pid {ativo.pid}",
        )
    anterior = nativa.caminho_backup(executavel)
    guardado = sha_ou_none(anterior)
    rel.conferir(
        "O `.previous` guarda exatamente o binário anterior",
        guardado == origem.sha, f"{(guardado or 'ausente')[:12]}…",
    )


def rollback_pelo_previous(
    rel: Relatorio, executavel: Path, origem: Origem, ambiente: Mapping[str, str]
) -> None:
    try:
        substituir(executavel, nativa.caminho_backup(executavel))
        versao = executar(executavel, "--version", ambiente=ambiente)
        rel.conferir(
            f"Rollback pelo `.previous` devolve {origem.versao}",
            origem.versao in versao.saida and sha_ou_none(executavel) == origem.sha,
            versao.saida.strip() or versao.resumo,
        )
    except OSError as exc:
        rel.conferir("Rollback pelo `.previous`", False, str(exc))


def rollback_pela_release(
    rel: Relatorio, executavel: Path, origem: Origem, alvo: nativa.AlvoNativo,
    base: Path, ambiente: Mapping[str, str],
) -> None:
    if not origem.tag:
        return
    try:
        baixado, _ = baixar_release(origem.tag, alvo, base / "rollback")
        substituir(executavel, baixado)
        versao = executar(executavel, "--version", ambiente=ambiente)
        rel.conferir(
            f"Rollback pela Release {origem.tag} (SHA-256 conferido) devolve {origem.versao}",
            origem.versao in versao.saida and sha_ou_none(executavel) == origem.sha,
            versao.saida.strip() or versao.resumo,
        )
    except (OSError, RuntimeError, nativa.AtualizacaoNativaError) as exc:
        rel.conferir(f"Rollback pela Release {origem.tag}", False, str(exc))


def observar_segunda_atualizacao(
    rel: Relatorio, executavel: Path, casa: Path, origem: Origem, destino_sha: str
) -> None:
    """Atualiza de novo com o ``.previous`` ainda em uso pelo processo vivo.

    No Windows um arquivo em uso não pode ser sobrescrito. O que importa é o executável
    continuar íntegro (a versão anterior ou a nova, nunca ausente ou corrompido).
    """

    disparo, _ = disparar_auto_update(executavel, casa, destino_sha)
    esperar(lambda: troca_feita(executavel, destino_sha), TEMPO_HELPER_WINDOWS if WINDOWS else 5.0)
    atual = sha_ou_none(executavel)
    rel.conferir(
        "Segunda atualização com o `.previous` em uso deixa o executável íntegro",
        atual in {origem.sha, destino_sha}, f"{(atual or 'ausente')[:12]}…",
    )
    resultado = "atualizou" if atual == destino_sha else "não atualizou (anterior preservado)"
    rel.observar(
        "Segunda atualização com o `.previous` em uso",
        f"{resultado}; o comando saiu com código {disparo.codigo}",
    )


def ciclo(
    rel: Relatorio, alvo: nativa.AlvoNativo, origem: Origem, destino_tag: str, destino_sha: str,
    *, com_processo_ativo: bool, exigir_relancamento: bool,
) -> None:
    """Um ciclo completo (update, conferências e dois rollbacks) numa pasta descartável."""

    with tempfile.TemporaryDirectory(prefix="validar-update-", ignore_cleanup_errors=True) as pasta:
        base = Path(pasta)
        executavel = base / "instalacao" / alvo.asset
        executavel.parent.mkdir()
        shutil.copyfile(origem.caminho, executavel)
        tornar_executavel(executavel)
        casa = base / "casa"
        quieto = ambiente_do_binario(casa, auto_update=False)
        versao_destino = nativa.normalizar_versao(destino_tag)
        ativo: subprocess.Popen[bytes] | None = None
        try:
            versao = executar(executavel, "--version", ambiente=quieto)
            rel.conferir(
                f"`--version` do binário anterior é {origem.versao}",
                origem.versao in versao.saida, versao.saida.strip() or versao.resumo,
            )
            plano, consulta = consultar_plano(executavel, quieto)
            rel.conferir(
                f"`update --dry-run` aponta {destino_tag} para {alvo.identificador} sem baixar",
                plano.get("status") == "disponivel"
                and plano.get("plano", {}).get("alvo") == alvo.identificador
                and plano.get("plano", {}).get("versao_disponivel") == versao_destino
                and sha_ou_none(executavel) == origem.sha,
                f"status {plano.get('status')!r} {consulta.resumo if not plano else ''}".strip(),
            )
            if com_processo_ativo:
                ativo = iniciar_processo_ativo(executavel, quieto)
                time.sleep(TEMPO_PROCESSO_ATIVO)
                if not rel.conferir(
                    "Outro processo do binário anterior está vivo, segurando o arquivo",
                    ativo.poll() is None, f"pid {ativo.pid}",
                ):
                    return

            disparo, tentativas = disparar_auto_update(executavel, casa, destino_sha)
            if ativo is not None:
                rel.conferir(
                    "O processo em uso seguia vivo quando o update foi disparado",
                    ativo.poll() is None,
                    f"pid {ativo.pid}; ele desiste sozinho em {VALIDADE_DO_PROCESSO_ATIVO:.0f}s "
                    "(rede lenta invalida este ciclo)",
                )
            conferir_troca(rel, executavel, origem, destino_sha, disparo, tentativas, ativo)
            conferir_comando_original(rel, casa, disparo, exigir=exigir_relancamento)
            nova = executar(executavel, "--version", ambiente=quieto)
            rel.conferir(
                f"`--version` depois do update é {versao_destino}",
                versao_destino in nova.saida, nova.saida.strip() or nova.resumo,
            )
            rollback_pelo_previous(rel, executavel, origem, quieto)
            rollback_pela_release(rel, executavel, origem, alvo, base, quieto)
            if ativo is not None:
                observar_segunda_atualizacao(rel, executavel, casa, origem, destino_sha)
        finally:
            encerrar_processo_ativo(ativo)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--de", dest="tag_de", default=VERSAO_PADRAO_DE, help="Release anterior")
    parser.add_argument("--de-binario", type=Path, help="usa este build local como anterior")
    parser.add_argument("--de-versao", help="versão do build local (vX.Y.Z)")
    parser.add_argument(
        "--ciclos", choices=("parado", "ativo", "ambos"), default="ambos",
        help="quais ciclos rodar: binário parado, com outro processo em uso, ou os dois",
    )
    parser.add_argument("--saida", type=Path, help="grava o relatório Markdown neste arquivo")
    return parser


def resolver_origem(args: argparse.Namespace, alvo: nativa.AlvoNativo, pasta: Path) -> Origem:
    if args.de_binario:
        if not args.de_versao:
            raise SystemExit("--de-binario exige --de-versao vX.Y.Z.")
        caminho = args.de_binario.resolve()
        return Origem(caminho, nativa.normalizar_versao(args.de_versao), sha256(caminho), None)
    caminho, digest = baixar_release(args.tag_de, alvo, pasta)
    return Origem(caminho, nativa.normalizar_versao(args.tag_de), digest, args.tag_de)


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    identificador = nativa.detectar_alvo()
    if identificador is None:
        print("Este sistema não tem binário nativo publicado.", file=sys.stderr)
        return 2
    alvo = nativa.obter_alvo(identificador)
    try:
        ultima = consultar_ultima_release()
    except nativa.AtualizacaoNativaError as exc:
        limite = " (limite de 60 consultas por hora e por IP; rode de novo mais tarde)"
        print(f"{exc}{limite if '403' in str(exc) else ''}", file=sys.stderr)
        return 3
    rel = Relatorio()

    with tempfile.TemporaryDirectory(prefix="validar-origem-", ignore_cleanup_errors=True) as pasta:
        origem = resolver_origem(args, alvo, Path(pasta))
        if nativa.chave_versao(origem.versao) >= nativa.chave_versao(ultima.versao):
            print(
                f"{origem.versao} não é anterior à Release mais nova ({ultima.tag}).",
                file=sys.stderr,
            )
            return 2
        _, destino_sha = baixar_release(ultima.tag, alvo, Path(pasta) / "destino")

        rel.titulo(2, f"Auto-update e rollback · {alvo.identificador}")
        rel.escrever(f"- **Sistema:** {platform.platform()} ({platform.machine()})")
        rel.escrever(f"- **Quando:** {datetime.now(UTC):%Y-%m-%d %H:%M} UTC")
        de = "build local" if not origem.tag else origem.tag
        rel.escrever(f"- **Atualização:** {origem.versao} ({de}) → {ultima.tag}")
        rel.escrever(f"- **Python no PATH do binário:** {', '.join(python_no_path()) or 'nenhum'}")
        rel.escrever("- **Assinatura:** nenhuma (as Releases publicadas não são assinadas)")
        exigir = args.de_binario is not None
        opcoes = {"exigir_relancamento": exigir}
        if args.ciclos in {"parado", "ambos"}:
            rel.titulo(3, "Ciclo com o binário parado")
            ciclo(rel, alvo, origem, ultima.tag, destino_sha, com_processo_ativo=False, **opcoes)
        if args.ciclos in {"ativo", "ambos"}:
            rel.titulo(3, "Ciclo com outro processo do binário em uso")
            ciclo(rel, alvo, origem, ultima.tag, destino_sha, com_processo_ativo=True, **opcoes)

    rel.escrever()
    veredito = "aprovado" if rel.falhas == 0 else f"reprovado ({rel.falhas} falha(s))"
    rel.escrever(f"**Resultado: {veredito}.**")
    if args.saida:
        args.saida.write_text("\n".join(rel.linhas) + "\n", encoding="utf-8")
    return 0 if rel.falhas == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
