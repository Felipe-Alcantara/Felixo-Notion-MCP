#!/usr/bin/env python3
"""Grava artigos num database de biblioteca, sem duplicar, a partir de rascunhos.

Uso:
    python -I scripts/notion/importar_artigos_para_biblioteca.py <pasta_rascunhos>
        --database <id> [--perfil <alias>] [--opcao-nova "Coluna=valor" ...] [--dry-run]

Cada artigo é um par de arquivos na pasta:

- ``<chave>.json`` com ``titulo`` (vai para a coluna de título) e ``propriedades``
  (``{"Coluna": valor}``; lista para multi_select, número para number, ``AAAA-MM-DD``
  para date). ``URL da fonte`` é obrigatória: é ela que identifica o artigo;
- ``<chave>.md`` com o corpo da página em Markdown.

Opcionais no ``.json``: ``anexos`` (``{"coluna de arquivos": "caminho local"}``, enviado
só quando a coluna está vazia) e ``aparencia`` (``{"icone": ..., "capa": ...}``, pelo
comando ``aparencia``, que mantém ícone e capa que a página já tenha).

O script:

1. valida TODOS os rascunhos antes de escrever qualquer coisa: a coluna existe no
   schema real e aceita escrita, o valor de select, multi_select e status é uma opção
   que já existe (ou foi liberada com ``--opcao-nova``, para não criar opção por erro
   de digitação) e cada URL aparece uma vez só no lote;
2. cria a linha que ainda não existe (procurada pela ``URL da fonte``) com todas as
   propriedades e o corpo, numa chamada só;
3. completa a linha que já existe sem tirar nada dela: grava só as propriedades que
   estão vazias, acrescenta ao multi_select os valores que faltam e escreve o corpo
   apenas se a página estiver sem corpo. Rodar de novo não repete nada;
4. anexa os arquivos e aplica ícone e capa, sem duplicar nem sobrescrever;
5. imprime no fim um JSON com o que foi criado, completado e deixado como estava.

``--opcoes-livres COLUNA`` aceita qualquer valor naquela coluna (a opção nasce no Notion);
``--nao-completar "Coluna=valor"`` faz linhas existentes com esse valor não contarem como
o mesmo artigo (ex.: a linha de um livro cuja URL da fonte é o post que o anuncia);
``--paralelo N`` grava N artigos ao mesmo tempo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COLUNA_CHAVE = "URL da fonte"
TIPOS_COM_OPCOES = {"select", "multi_select", "status"}


class Erro(Exception):
    """Falha que interrompe o lote com mensagem legível."""


@dataclass(frozen=True)
class Artigo:
    chave: str
    titulo: str
    propriedades: dict[str, Any]
    corpo: str
    anexos: dict[str, str] = field(default_factory=dict)
    aparencia: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return str(self.propriedades.get(COLUNA_CHAVE, "")).strip()


# ---------------------------------------------------------------------------
# Parte sem rede (testada em tests/scripts/test_importar_artigos_para_biblioteca.py)
# ---------------------------------------------------------------------------


def vazio(valor: Any) -> bool:
    """Diz se uma propriedade lida do Notion está sem valor."""

    return valor is None or valor == "" or valor == [] or valor == {}


def carregar_rascunhos(pasta: Path) -> list[Artigo]:
    """Lê os pares ``<chave>.json`` + ``<chave>.md`` da pasta, em ordem de nome."""

    artigos: list[Artigo] = []
    for arquivo in sorted(pasta.glob("*.json")):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        corpo_arquivo = arquivo.with_suffix(".md")
        if not corpo_arquivo.is_file():
            raise Erro(f"{arquivo.name}: falta o corpo {corpo_arquivo.name}")
        titulo = str(dados.get("titulo", "")).strip()
        propriedades = dados.get("propriedades")
        if not titulo or not isinstance(propriedades, dict):
            raise Erro(f"{arquivo.name}: precisa de 'titulo' e de 'propriedades' (objeto)")
        artigos.append(
            Artigo(
                chave=arquivo.stem,
                titulo=titulo,
                propriedades=propriedades,
                corpo=corpo_arquivo.read_text(encoding="utf-8").strip(),
                anexos=dict(dados.get("anexos") or {}),
                aparencia={k: v for k, v in (dados.get("aparencia") or {}).items() if v},
            )
        )
    if not artigos:
        raise Erro(f"nenhum rascunho .json em {pasta}")
    return artigos


def ler_opcoes_novas(itens: Iterable[str]) -> dict[str, set[str]]:
    """Converte ``["Coluna=valor", ...]`` em ``{"Coluna": {"valor", ...}}``."""

    liberadas: dict[str, set[str]] = {}
    for item in itens:
        coluna, separador, valor = item.partition("=")
        if not separador or not coluna.strip() or not valor.strip():
            raise Erro(f"--opcao-nova espera 'Coluna=valor', recebeu {item!r}")
        liberadas.setdefault(coluna.strip(), set()).add(valor.strip())
    return liberadas


def _valores(valor: Any) -> list[str]:
    return [str(v) for v in valor] if isinstance(valor, list) else [str(valor)]


def validar(
    artigos: list[Artigo],
    colunas: Mapping[str, Mapping[str, Any]],
    opcoes_novas: Mapping[str, set[str]],
    opcoes_livres: Iterable[str] = (),
) -> list[str]:
    """Devolve a lista de problemas do lote; vazia quando dá para gravar."""

    livres = set(opcoes_livres)

    problemas: list[str] = []
    vistas: dict[str, str] = {}
    for artigo in artigos:
        if not artigo.url.startswith(("http://", "https://")):
            problemas.append(f"{artigo.chave}: '{COLUNA_CHAVE}' ausente ou não é URL")
        elif artigo.url in vistas:
            problemas.append(f"{artigo.chave}: mesma URL de {vistas[artigo.url]}")
        else:
            vistas[artigo.url] = artigo.chave
        if not artigo.corpo:
            problemas.append(f"{artigo.chave}: corpo vazio")
        for nome, valor in artigo.propriedades.items():
            coluna = colunas.get(nome)
            if coluna is None:
                problemas.append(f"{artigo.chave}: coluna inexistente {nome!r}")
                continue
            if not coluna.get("editavel", True) or coluna.get("titulo"):
                problemas.append(f"{artigo.chave}: coluna {nome!r} não aceita escrita aqui")
                continue
            tipo = coluna.get("tipo")
            if tipo == "multi_select" and not isinstance(valor, list):
                problemas.append(f"{artigo.chave}: {nome!r} é multi_select e pede uma lista")
                continue
            if tipo in TIPOS_COM_OPCOES and nome in livres:
                problemas += [
                    f"{artigo.chave}: {nome!r} tem vírgula em {item!r}"
                    for item in _valores(valor)
                    if "," in item
                ]
            elif tipo in TIPOS_COM_OPCOES:
                aceitas = set(coluna.get("opcoes") or []) | opcoes_novas.get(nome, set())
                for item in _valores(valor):
                    if "," in item:
                        problemas.append(f"{artigo.chave}: {nome!r} tem vírgula em {item!r}")
                    elif item not in aceitas:
                        problemas.append(
                            f"{artigo.chave}: {item!r} não é opção de {nome!r} "
                            "(libere com --opcao-nova se for intencional)"
                        )
            if tipo == "number" and not isinstance(valor, (int, float)):
                problemas.append(f"{artigo.chave}: {nome!r} é number e recebeu {valor!r}")
        for nome, caminho in artigo.anexos.items():
            coluna = colunas.get(nome)
            if coluna is None or coluna.get("tipo") != "files":
                problemas.append(f"{artigo.chave}: anexo em {nome!r}, que não é coluna de arquivos")
            elif not Path(caminho).is_file():
                problemas.append(f"{artigo.chave}: arquivo do anexo não existe: {caminho}")
        extras = set(artigo.aparencia) - {"icone", "capa"}
        if extras:
            problemas.append(
                f"{artigo.chave}: aparência só aceita icone e capa, veio {sorted(extras)}"
            )
    return problemas


def completar_existente(
    desejadas: Mapping[str, Any],
    atuais: Mapping[str, Any],
    tipos: Mapping[str, str],
) -> dict[str, Any]:
    """Propriedades a gravar numa linha que já existe, sem apagar nada dela.

    Coluna vazia recebe o valor do rascunho; multi_select preenchido recebe só os
    valores que faltam (o resultado é a união, na ordem atual + novos); qualquer outra
    coluna preenchida fica como está.
    """

    gravar: dict[str, Any] = {}
    for nome, valor in desejadas.items():
        atual = atuais.get(nome)
        if vazio(atual):
            gravar[nome] = valor
        elif tipos.get(nome) == "multi_select":
            faltando = [v for v in valor if v not in atual]
            if faltando:
                gravar[nome] = [*atual, *faltando]
    return gravar


def ler_filtros(itens: Iterable[str]) -> list[tuple[str, str]]:
    """Converte ``["Coluna=valor", ...]`` em pares, para ``--nao-completar``."""

    pares: list[tuple[str, str]] = []
    for item in itens:
        coluna, separador, valor = item.partition("=")
        if not separador or not coluna.strip() or not valor.strip():
            raise Erro(f"--nao-completar espera 'Coluna=valor', recebeu {item!r}")
        pares.append((coluna.strip(), valor.strip()))
    return pares


def indexar_por_url(
    linhas: Iterable[Mapping[str, Any]], nao_completar: Iterable[tuple[str, str]] = ()
) -> dict[str, Mapping[str, Any]]:
    """``URL da fonte -> linha``, sem as linhas que batem com algum filtro."""

    filtros = list(nao_completar)
    indice: dict[str, Mapping[str, Any]] = {}
    for linha in linhas:
        props = linha["propriedades"]
        url = str(props.get(COLUNA_CHAVE) or "").strip()
        if not url:
            continue
        if any(valor in _valores(props.get(coluna) or "") for coluna, valor in filtros):
            continue
        indice[url] = linha
    return indice


def argumentos_set(propriedades: Mapping[str, Any]) -> list[str]:
    """Traduz propriedades em ``--set "Coluna=valor"`` (listas viram CSV)."""

    argumentos: list[str] = []
    for nome, valor in propriedades.items():
        texto = ",".join(_valores(valor)) if isinstance(valor, list) else str(valor)
        argumentos += ["--set", f"{nome}={texto}"]
    return argumentos


# ---------------------------------------------------------------------------
# Parte que fala com o Notion (pela CLI notion-tasks)
# ---------------------------------------------------------------------------


#: ``src/`` deste checkout: quando existe, a CLI roda direto pelo interpretador atual.
SRC_DO_CHECKOUT = Path(__file__).resolve().parents[2] / "src"


def comando_cli(perfil: str | None, argumentos: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    """Linha de comando e ambiente para chamar a CLI sem passar por um shell.

    No checkout, a CLI roda como ``python -m felixo_notion_mcp.api.cli`` com o ``src/``
    no ``PYTHONPATH``. Isso evita o ``notion-tasks.cmd``: o ``cmd.exe`` não entende o
    ``\\"`` que o Python usa para aspas dentro de um argumento, e um título como
    ``Palestra "Ruby & GC"`` vira dois comandos no ``&`` — o primeiro gravou uma linha
    truncada no database errado. Fora do checkout, usa o executável instalado.
    """

    ambiente = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if (SRC_DO_CHECKOUT / "felixo_notion_mcp").is_dir():
        partes = (str(SRC_DO_CHECKOUT), ambiente.get("PYTHONPATH"))
        ambiente["PYTHONPATH"] = os.pathsep.join(p for p in partes if p)
        base = [sys.executable, "-m", "felixo_notion_mcp.api.cli"]
    else:
        instalado = shutil.which("notion-tasks") or "notion-tasks"
        if Path(instalado).suffix.lower() in (".cmd", ".bat"):
            raise Erro(
                "a CLI instalada é um .cmd: o cmd.exe quebra argumentos com aspas e '&'. "
                "Rode este script de dentro do checkout do Felixo-Notion-MCP."
            )
        base = [instalado]
    return [*base, "--json", *(["--perfil", perfil] if perfil else []), *argumentos], ambiente


def executar(perfil: str | None, *argumentos: str) -> dict[str, Any]:
    comando, ambiente = comando_cli(perfil, argumentos)
    resultado = subprocess.run(
        comando,
        check=False,
        capture_output=True,
        # A CLI responde JSON em UTF-8; sem isto, no Windows o pai leria em cp1252.
        encoding="utf-8",
        errors="replace",
        env=ambiente,
    )
    try:
        resposta = json.loads(resultado.stdout)
    except json.JSONDecodeError as erro:
        detalhe = resultado.stderr.strip() or resultado.stdout.strip()
        raise Erro(f"saída não JSON de '{argumentos[0]}': {detalhe[:800]}") from erro
    if resultado.returncode != 0 or not resposta.get("ok"):
        raise Erro(f"'{argumentos[0]}' falhou: {json.dumps(resposta, ensure_ascii=False)[:1500]}")
    return resposta


def _markdown_temporario(conteudo: str) -> str:
    arquivo = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False)
    with arquivo:
        arquivo.write(conteudo)
    return arquivo.name


def _processar(
    artigo: Artigo,
    existente: Mapping[str, Any] | None,
    *,
    database: str,
    perfil: str | None,
    tipos: Mapping[str, str],
    dry_run: bool,
) -> dict[str, Any]:
    """Cria ou completa uma linha, depois anexa arquivos e aplica ícone e capa."""

    if existente is None:
        item: dict[str, Any] = {"chave": artigo.chave, "acao": "criar", "titulo": artigo.titulo}
        anexos_pendentes = dict(artigo.anexos)
        if dry_run:
            return item | {"anexos": sorted(anexos_pendentes)}
        arquivo = _markdown_temporario(artigo.corpo)
        try:
            resposta = executar(
                perfil, "criar", artigo.titulo, "--database", database,
                *argumentos_set(artigo.propriedades), "--arquivo-md", arquivo,
            )
        finally:
            os.unlink(arquivo)
        page_id = str(resposta["dados"].get("id"))
        item["id"] = page_id
    else:
        page_id = str(existente["id"])
        atuais = existente["propriedades"]
        gravar = completar_existente(artigo.propriedades, atuais, tipos)
        corpo_atual = executar(perfil, "conteudo", page_id)["dados"].get("markdown", "")
        escrever_corpo = not str(corpo_atual).strip()
        anexos_pendentes = {c: v for c, v in artigo.anexos.items() if vazio(atuais.get(c))}
        mudou = bool(gravar or escrever_corpo or anexos_pendentes)
        item = {
            "chave": artigo.chave,
            "acao": "completar" if mudou else "sem_mudanca",
            "id": page_id,
            "propriedades": sorted(gravar),
            "corpo": "escrito" if escrever_corpo else "mantido (já tinha corpo)",
        }
        if dry_run:
            return item | {"anexos": sorted(anexos_pendentes)}
        if gravar:
            executar(perfil, "editar-linha", page_id, *argumentos_set(gravar))
        if escrever_corpo:
            arquivo = _markdown_temporario(artigo.corpo)
            try:
                executar(perfil, "escrever", page_id, "--arquivo-md", arquivo)
            finally:
                os.unlink(arquivo)

    for coluna, caminho in anexos_pendentes.items():
        executar(perfil, "anexar-arquivo", page_id, caminho, "--propriedade", coluna)
    item["anexos"] = sorted(anexos_pendentes)
    if artigo.aparencia:
        argumentos = []
        for campo in ("icone", "capa"):
            if artigo.aparencia.get(campo):
                argumentos += [f"--{campo}", artigo.aparencia[campo]]
        dados = executar(perfil, "aparencia", page_id, *argumentos)["dados"]
        item["aparencia"] = {"icone": dados.get("icone"), "capa": dados.get("capa")}
    return item


def importar(
    artigos: list[Artigo],
    database: str,
    perfil: str | None,
    opcoes_novas: Mapping[str, set[str]],
    dry_run: bool,
    *,
    opcoes_livres: Iterable[str] = (),
    nao_completar: Iterable[tuple[str, str]] = (),
    paralelo: int = 1,
) -> dict[str, Any]:
    schema = executar(perfil, "schema", database)["dados"]
    colunas = {c["nome"]: c for c in schema["colunas"]}
    problemas = validar(artigos, colunas, opcoes_novas, opcoes_livres)
    if problemas:
        lista = "".join(f"\n- {problema}" for problema in problemas)
        raise Erro(f"rascunhos inválidos, nada foi gravado:{lista}")
    tipos = {nome: str(c.get("tipo")) for nome, c in colunas.items()}
    linhas = executar(perfil, "linhas", "--completo", database)["dados"]["linhas"]
    por_url = indexar_por_url(linhas, nao_completar)

    trava = threading.Lock()
    feitos = {"n": 0}

    def rodar(artigo: Artigo) -> dict[str, Any]:
        try:
            item = _processar(
                artigo, por_url.get(artigo.url), database=database, perfil=perfil,
                tipos=tipos, dry_run=dry_run,
            )
        except Erro as erro:  # um artigo com problema não para o lote; rodar de novo completa
            item = {"chave": artigo.chave, "acao": "erro", "erro": str(erro)[:600]}
        with trava:
            feitos["n"] += 1
            if feitos["n"] % 25 == 0 or feitos["n"] == len(artigos):
                print(f"  {feitos['n']}/{len(artigos)}", file=sys.stderr, flush=True)
        return item

    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as executor:
        itens = list(executor.map(rodar, artigos))
    contagem: dict[str, int] = {}
    for item in itens:
        contagem[item["acao"]] = contagem.get(item["acao"], 0) + 1
    return {"database": database, "dry_run": dry_run, "contagem": contagem, "itens": itens}


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pasta", type=Path, help="pasta com os pares <chave>.json/.md")
    parser.add_argument("--database", required=True, help="ID ou link do database de destino")
    parser.add_argument("--perfil", help="perfil da CLI; sem ele, usa o perfil ativo")
    parser.add_argument(
        "--opcao-nova",
        action="append",
        default=[],
        metavar="COLUNA=VALOR",
        help="libera um valor de select/multi_select que ainda não é opção (o Notion cria)",
    )
    parser.add_argument(
        "--opcoes-livres",
        action="append",
        default=[],
        metavar="COLUNA",
        help="aceita qualquer valor nesta coluna select/multi_select (a opção nasce no Notion)",
    )
    parser.add_argument(
        "--nao-completar",
        action="append",
        default=[],
        metavar="COLUNA=VALOR",
        help="linha existente com este valor não conta como o mesmo artigo (cria outra)",
    )
    parser.add_argument("--paralelo", type=int, default=1, help="artigos gravados ao mesmo tempo")
    parser.add_argument("--dry-run", action="store_true", help="mostra o plano sem gravar")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Com ``python -I`` o PYTHONIOENCODING é ignorado; sem isto o log sai em cp1252 no Windows.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = construir_parser().parse_args(argv)
    try:
        artigos = carregar_rascunhos(args.pasta)
        log = importar(
            artigos,
            args.database,
            args.perfil,
            ler_opcoes_novas(args.opcao_nova),
            args.dry_run,
            opcoes_livres=args.opcoes_livres,
            nao_completar=ler_filtros(args.nao_completar),
            paralelo=args.paralelo,
        )
    except Erro as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1
    print(json.dumps(log, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
