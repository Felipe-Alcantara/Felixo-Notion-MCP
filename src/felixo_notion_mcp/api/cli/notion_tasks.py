"""CLI para IA operar tarefas do Notion via services compartilhados.

Esta borda valida entradas, escolhe formato de saída e delega a regra para os
services compartilhados com API/MCP. Não monta payload cru do Notion.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import re
import sys
import time
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn

from felixo_notion_mcp import (
    NotionAPIError,
    NotionClient,
    NotionHTTPError,  # noqa: F401 - exposto como cli.NotionHTTPError
    TaskList,
    blocos_para_markdown,
    construir_inventario,
)
from felixo_notion_mcp.api.cli.erros import (
    CODIGOS_ERRO,
    SAIDA_FALHA,
    SAIDA_USO,
    CLIError,
    ErroClassificado,
    classificar_erro,
    dados_desfazer,
)
from felixo_notion_mcp.core import workspaces as perfis_workspace
from felixo_notion_mcp.core.config import REPO_RAIZ, carregar_env_file
from felixo_notion_mcp.core.exceptions import (
    EdicaoMultiblocoError,
    EscritaParcialError,
    ExclusaoArriscadaError,
    IdNotionInvalidoError,
    PerdaDeFormatacaoError,
    TrechoAmbiguoError,
)
from felixo_notion_mcp.core.utils import chave_de_id, normalizar_id
from felixo_notion_mcp.domain import properties as starter_properties
from felixo_notion_mcp.domain import schema as starter_schema
from felixo_notion_mcp.integrations.github import GitHubClient
from felixo_notion_mcp.services import anexos as svc_anexos
from felixo_notion_mcp.services import aparencia as svc_aparencia
from felixo_notion_mcp.services import clonagem as svc_clonagem
from felixo_notion_mcp.services import conteudo as svc_conteudo
from felixo_notion_mcp.services import estrutura_projeto as svc_estrutura
from felixo_notion_mcp.services import (
    historico_repositorios as svc_historico,
)
from felixo_notion_mcp.services import ingestao as svc_ingestao
from felixo_notion_mcp.services import inventario_github as svc_inventario
from felixo_notion_mcp.services import normalizacao as svc_normalizacao
from felixo_notion_mcp.services import preflight as svc_preflight
from felixo_notion_mcp.services import propriedades as svc_propriedades
from felixo_notion_mcp.services import relacoes as svc_relacoes
from felixo_notion_mcp.services import (
    relatorios_diarios as svc_relatorios,
)
from felixo_notion_mcp.services import relatorios_docx as svc_relatorios_docx
from felixo_notion_mcp.services import reordenacao as svc_reordenacao
from felixo_notion_mcp.services import schema as svc_schema
from felixo_notion_mcp.services import tarefas as svc

#: Raiz do checkout: onde mora o ``.env`` (a mesma que ``core.config`` usa para lê-lo).
RAIZ = REPO_RAIZ

carregar_env_file()

TaskListFactory = Callable[[], TaskList]
ClientFactory = Callable[[], NotionClient]


def _criar_client() -> NotionClient:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise CLIError("NOTION_TOKEN não configurado.")
    return NotionClient(token=token)


def _criar_tasklist() -> TaskList:
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not database_id:
        raise CLIError("NOTION_DATABASE_ID não configurado.")
    return TaskList(_criar_client(), database_id)


def _normalizar_texto(valor: str | None) -> str | None:
    if valor is None:
        return None
    return valor.strip() or None


def _texto_obrigatorio(valor: str | None, campo: str) -> str:
    normalizado = _normalizar_texto(valor)
    if not normalizado:
        raise CLIError(f"O campo '{campo}' é obrigatório.")
    return normalizado


def _id_notion(valor: str | None, campo: str, *, bloco: bool = False) -> str:
    """ID do Notion vindo de quem opera: UUID com ou sem hífens, ou um link.

    Devolve o UUID canônico (``8-4-4-4-12``, minúsculo) pela regra da
    biblioteca (:func:`felixo_notion_mcp.core.utils.normalizar_id`): a forma sem
    hífens é a que aparece no ``url`` das respostas, e comparar a forma crua
    dizia "não encontrado" para um ID certo. Num link, vale o ID do caminho
    (``?v=`` de view é ignorado; ``?p=`` de painel vence) e, com ``bloco``, a
    âncora ``#<id>`` do bloco.

    Um link sem ID é recusado aqui (``IdNotionInvalidoError``), antes de a API
    responder "Invalid request URL". Texto que não é UUID nem link segue como
    veio, para a própria API responder.
    """

    texto = _texto_obrigatorio(valor, campo)
    try:
        return normalizar_id(texto, preferir_ancora=bloco)
    except IdNotionInvalidoError:
        if "://" in texto:
            raise
        return texto


def _id_opcional(valor: str | None, campo: str, *, bloco: bool = False) -> str | None:
    """Como :func:`_id_notion`, para flags opcionais (``None`` quando ausente)."""

    if _normalizar_texto(valor) is None:
        return None
    return _id_notion(valor, campo, bloco=bloco)


#: Próximo passo mostrado quando um serviço do próprio pacote não pode ser importado.
PROXIMO_PASSO_INSTALACAO_QUEBRADA = (
    "Rode 'felixo-notion-mcp doctor' para ver de onde o pacote é importado e reinstale-o "
    "(no checkout: uv sync --locked --all-extras)."
)


def _servico_do_starter(nome: str, *, comando: str) -> ModuleType:
    """Importa ``felixo_notion_mcp.services.<nome>`` só quando o comando roda.

    Os comandos de organização do workspace (``mover-pagina`` verificado,
    ``modelos``, ``copiar-corpo``, ``inventario``…) carregam o serviço sob
    demanda. A função vem do tempo em que esses serviços podiam faltar no
    ``notion-starter`` publicado; no pacote único eles sempre estão presentes,
    então um ``ImportError`` aqui significa instalação incompleta ou quebrada, e
    só o comando que precisa do serviço recusa, com uma mensagem que diz isso.
    As chamadas são simplificadas na etapa 2.
    """

    try:
        return importlib.import_module(f"felixo_notion_mcp.services.{nome}")
    except ImportError as exc:
        raise CLIError(
            f"'{comando}' precisa do serviço felixo_notion_mcp.services.{nome}, que não "
            "pôde ser importado. No pacote único isso indica uma instalação incompleta "
            "ou quebrada, não uma dependência desatualizada.",
            codigo="configuracao",
            proximo_passo=PROXIMO_PASSO_INSTALACAO_QUEBRADA,
        ) from exc


def _markdown_da_entrada(
    valor: str | None, arquivo_md: str | None, *, campo: str
) -> str | None:
    """Markdown do argumento, do stdin (``-``) ou de ``--arquivo-md``, sem retoque.

    Passar Markdown no argv esbarra no limite de 128 KiB por argumento do
    Linux (e de ~32 mil caracteres no Windows) e na citação do shell; o stdin
    e o arquivo não. É leitura de E/S de borda: o serviço continua recebendo
    ``str``. Lê em UTF-8 (com BOM tolerado) independentemente do console.

    O texto segue para o serviço como veio, sem ``strip()``: o recuo da
    primeira linha é conteúdo (o código de um bloco de código, o nível de uma
    lista recuada por igual), e cortá-lo mudava o que era gravado. A
    biblioteca já ignora as linhas em branco e os espaços nas pontas de uma
    linha de Markdown. Só texto inteiro em branco conta como ausente
    (``None``). As quebras de linha chegam como ``\\n`` nas três fontes, como
    na leitura do arquivo em modo texto.

    Raises:
        CLIError: As duas fontes juntas, ``-`` sem nada redirecionado (em vez
            de ficar esperando o teclado) ou arquivo ilegível.
    """

    bruto = _ler_markdown(valor, arquivo_md, campo=campo)
    if bruto is None or not bruto.strip():
        return None
    return bruto.replace("\r\n", "\n").replace("\r", "\n")


def _ler_markdown(valor: str | None, arquivo_md: str | None, *, campo: str) -> str | None:
    """Lê a fonte escolhida em :func:`_markdown_da_entrada`, sem normalizar."""

    texto = _normalizar_texto(valor)
    caminho = _normalizar_texto(arquivo_md)
    if caminho is not None:
        if texto is not None:
            raise CLIError(f"Use {campo} OU --arquivo-md, não os dois.")
        arquivo = Path(caminho).expanduser()
        try:
            return arquivo.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as erro:
            raise CLIError(f"Não foi possível ler o Markdown de '{arquivo}': {erro}") from erro
    if texto != "-":
        return valor
    entrada = sys.stdin
    if entrada is None or entrada.isatty():
        raise CLIError(
            f"{campo} '-' lê o Markdown do stdin, mas nada foi redirecionado: use "
            "'< nota.md', um pipe ou --arquivo-md <arquivo>."
        )
    bruto = entrada.buffer.read() if hasattr(entrada, "buffer") else entrada.read()
    if isinstance(bruto, bytes):
        try:
            return bruto.decode("utf-8-sig")
        except UnicodeError as erro:
            raise CLIError(f"O stdin não está em UTF-8: {erro}") from erro
    return bruto


def _argumento_arquivo_md(args: argparse.Namespace) -> str | None:
    """Lê ``--arquivo-md`` sem transformar atributos automáticos de ``Mock`` em caminho."""

    valor = getattr(args, "arquivo_md", None)
    return valor if isinstance(valor, str) else None


def _lista_csv(valores: Sequence[str] | None) -> list[str] | None:
    if not valores:
        return None
    itens: list[str] = []
    for valor in valores:
        itens.extend(item.strip() for item in valor.split(",") if item.strip())
    return itens


def _database_id_tasklist(tasklist: Any) -> str | None:
    """Obtém o database do ``TaskList`` sem exigir esse detalhe aos doubles."""

    for atributo in ("_database_id", "database_id"):
        valor = getattr(tasklist, atributo, None)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def _cliente_tasklist(tasklist: Any, client_factory: ClientFactory) -> NotionClient:
    """Reutiliza o cliente interno do ``TaskList`` quando ele existe."""

    cliente = getattr(tasklist, "_client", None)
    if cliente is not None:
        return cliente
    return client_factory()


def _preflight_necessario(
    valores: Mapping[str, str], *, estrito: bool, dry_run: bool = False
) -> bool:
    """Decide quando vale abrir a leitura adicional do contrato de projeto."""

    if estrito or dry_run:
        return True
    nomes = {str(chave).casefold() for chave in valores}
    return bool(
        nomes
        & {
            svc_preflight.COLUNA_PROJETO.casefold(),
            svc_preflight.COLUNA_URL_REFERENCIA.casefold(),
        }
    )


def _preflight_dict(resultado: svc_preflight.ResultadoPreflight) -> dict[str, Any]:
    """Mantém o retorno do preflight estável e serializável."""

    return resultado.para_dict()


def _aplicar_relacao_preflight(
    page_id: str,
    resultado: svc_preflight.ResultadoPreflight,
    *,
    cliente: NotionClient,
) -> dict[str, Any] | None:
    """Corrige a relation planejada e confirma o estado final por releitura."""

    if resultado.projeto is None or resultado.coluna_relacao is None:
        return None
    coluna = resultado.coluna_relacao
    for antigo in resultado.remover_relacoes:
        svc_relacoes.relacionar(
            page_id,
            antigo,
            coluna,
            desfazer=True,
            cliente=cliente,
        )
    relacao = svc_relacoes.relacionar(
        page_id,
        resultado.projeto.id,
        coluna,
        cliente=cliente,
    )
    pagina = cliente.obter_pagina(page_id)
    propriedades = pagina.get("properties") or {}
    ids = svc_preflight.ids_relacao(propriedades.get(coluna))
    esperado = chave_de_id(resultado.projeto.id)
    if not any(chave_de_id(item) == esperado for item in ids):
        raise ValueError(
            f"A relation '{coluna}' não confirmou o projeto {resultado.projeto.id} "
            f"na linha {page_id}; releia a linha antes de tentar outra criação."
        )
    return relacao


def _tarefa_dict(tarefa: Any) -> dict[str, Any]:
    return {
        "id": tarefa.id,
        "nome": tarefa.nome,
        "status": tarefa.status,
        "prazo": tarefa.prazo,
        "duracao": tarefa.duracao,
        "areas": tarefa.areas,
        "areas_nomes": tarefa.areas_nomes,
        "url": tarefa.url,
    }


def _database_titulo(item: dict[str, Any]) -> str:
    partes = item.get("title", [])
    titulo = "".join(parte.get("plain_text", "") for parte in partes).strip()
    return titulo or "(sem título)"


def _database_dict(item: dict[str, Any]) -> dict[str, Any]:
    return {"id": item.get("id", ""), "titulo": _database_titulo(item), "url": item.get("url")}


def _nomes_data_sources(fontes: list[dict[str, Any]]) -> list[str]:
    nomes = []
    for fonte in fontes:
        nome = str(fonte.get("name") or "").strip()
        if nome:
            nomes.append(nome)
    return nomes


def _envelope(sucesso: bool, dados: Any = None, erro: str | None = None) -> dict[str, Any]:
    if sucesso:
        return {"ok": True, "dados": dados}
    return _envelope_erro(
        ErroClassificado(
            codigo="validacao", mensagem=erro or "Erro desconhecido.", saida=SAIDA_USO
        )
    )


def _envelope_erro(erro: ErroClassificado) -> dict[str, Any]:
    """``{"ok": false, "erro": {codigo, mensagem, proximo_passo, http_status,
    notion_code, detalhes}}`` — sempre as mesmas chaves, para decidir por código."""

    envelope: dict[str, Any] = {"ok": False, "erro": erro.para_dict()}
    if erro.codigo == "escrita_abaixo_de_database":
        # Compatibilidade: a lista também morava no topo do envelope.
        envelope["databases_dentro"] = erro.detalhes.get("databases_dentro", [])
    return envelope


def _texto_erro(erro: ErroClassificado) -> str:
    """Saída humana de um erro: a mensagem e, quando houver, o próximo passo."""

    texto = f"Erro: {erro.mensagem}"
    if erro.proximo_passo:
        texto += f"\nPróximo passo: {erro.proximo_passo}"
    return texto


def _json(dados: Any) -> str:
    # Usar safe_json_dumps para prevenir erros de surrogate inválidos
    from felixo_notion_mcp.core.utils import safe_json_dumps
    return safe_json_dumps(dados, ensure_ascii=False, indent=2, sort_keys=True)


def _linhas_tabela(registros: Iterable[dict[str, Any]], colunas: Sequence[str]) -> list[str]:
    linhas = list(registros)
    if not linhas:
        return ["Nenhum item encontrado."]
    larguras = {
        coluna: max(len(coluna), *(len(str(item.get(coluna) or "")) for item in linhas))
        for coluna in colunas
    }
    cabecalho = "  ".join(coluna.ljust(larguras[coluna]) for coluna in colunas)
    separador = "  ".join("-" * larguras[coluna] for coluna in colunas)
    corpo = [
        "  ".join(str(item.get(coluna) or "").ljust(larguras[coluna]) for coluna in colunas)
        for item in linhas
    ]
    return [cabecalho, separador, *corpo]


def _formatar_guia(dados: dict[str, Any]) -> str:
    """Renderiza o guia de comandos em texto legível."""

    linhas = [dados["ferramenta"], dados["dica"], ""]
    for passo in dados.get("fluxo_recomendado", []):
        linhas.append(f">> {passo}")
    linhas.append("")
    for item in dados["comandos"]:
        linhas.append(f"{item['comando']:18} {item['descricao']}")
        for exemplo in item["exemplos"]:
            linhas.append(f"    {exemplo}")
    return "\n".join(linhas)


def _formatar_lote(dados: dict[str, Any]) -> str:
    """Resume um lote sem esconder a situação de nenhuma linha."""

    linhas = [
        f"Lote: {dados['total']} | sucessos: {dados['sucessos']} | "
        f"erros: {dados['erros']} | pendentes: {dados['pendentes']}"
    ]
    for item in dados["resultados"]:
        referencia = (
            item.get("page_id")
            or item.get("block_id")
            or item.get("nome")
            or f"linha {item['indice']}"
        )
        estado = item["estado"].upper()
        mensagem = (item.get("erro") or {}).get("mensagem")
        sufixo = f": {mensagem}" if mensagem else ""
        linhas.append(f"{estado:<9} {item['indice']} ({referencia}){sufixo}")
    return "\n".join(linhas)


def _contexto_da_pagina(dados: Mapping[str, Any]) -> str:
    """Onde a página mora, a URL e quando mudou — só o que a leitura trouxe."""

    linhas: list[str] = []
    pai = dados.get("pai") or {}
    tipo = pai.get("tipo")
    pai_id = pai.get("database_id") or pai.get("id")
    if tipo in ("database_id", "data_source_id") and pai_id:
        linhas.append(f"Linha do database {pai_id} (schema: 'schema {pai_id}')")
    elif tipo == "page_id" and pai_id:
        linhas.append(f"Subpágina de {pai_id}")
    elif tipo == "block_id" and pai_id:
        linhas.append(f"Dentro do bloco {pai_id}")
    elif tipo == "workspace":
        linhas.append("Página na raiz do workspace")
    if dados.get("url"):
        linhas.append(f"URL: {dados['url']}")
    if dados.get("editado_em"):
        linhas.append(f"Editada em: {dados['editado_em']}")
    return "\n".join(linhas)


def _formatar_humano(comando: str, dados: Any) -> str:
    if isinstance(dados, dict) and dados.get("modo") == "lote":
        return _formatar_lote(dados)
    if comando == "guia":
        return _formatar_guia(dados)
    if comando in {"listar", "ler", "criar", "editar", "mover", "concluir"}:
        tarefas = dados if isinstance(dados, list) else [dados]
        return "\n".join(
            _linhas_tabela(
                tarefas,
                ("id", "nome", "status", "duracao", "areas_nomes", "prazo", "url"),
            )
        )
    if comando == "opcoes":
        return _json(dados)
    if comando == "databases":
        return "\n".join(_linhas_tabela(dados, ("id", "titulo", "url")))
    if comando == "buscar":
        return "\n".join(_linhas_tabela(dados, ("id", "tipo", "titulo", "url")))
    if comando == "conteudo":
        if dados.get("tipo") == "database":
            cabecalho = dados["aviso"]
            tabela = "\n".join(_linhas_tabela(dados["linhas"], ("id", "titulo", "url")))
            return f"{cabecalho}\n\n{tabela}"
        # Página = propriedades + corpo: as propriedades vêm PRIMEIRO, porque
        # há páginas com mais informação nas colunas do que no corpo. Antes
        # delas, onde a página mora (numa linha, o database para 'schema').
        partes: list[str] = []
        contexto = _contexto_da_pagina(dados)
        if contexto:
            partes.append(contexto)
        propriedades = dados.get("propriedades") or {}
        if propriedades:
            linhas_props = "\n".join(
                f"- {nome}: {valor}"
                for nome, valor in propriedades.items()
                if valor not in (None, "", [])
            )
            if linhas_props:
                partes.append(f"## Propriedades\n{linhas_props}")
        if dados["markdown"]:
            rotulo = "## Corpo\n" if partes else ""
            partes.append(f"{rotulo}{dados['markdown']}")
        return "\n\n".join(partes) or "(página sem propriedades nem conteúdo)"
    if comando == "exemplo":
        exemplos = dados.get("exemplos", [])
        if not exemplos:
            return "Nenhum exemplo encontrado no database configurado."
        blocos = []
        for indice, exemplo in enumerate(exemplos, start=1):
            titulo = exemplo.get("titulo") or "(sem título)"
            identificador = exemplo.get("id", "")
            url = exemplo.get("url") or ""
            cabecalho = f"### Exemplo {indice}: {titulo} ({identificador})"
            if url:
                cabecalho += f"\nURL: {url}"
            blocos.append(f"{cabecalho}\n{_formatar_humano('conteudo', exemplo)}")
        return "\n\n".join(blocos)
    if comando == "linhas":
        return "\n".join(_linhas_tabela(dados["linhas"], ("id", "titulo", "url")))
    if comando == "blocos":
        # Com --recursivo, o recuo do preview mostra o aninhamento.
        registros = [
            {**bloco, "preview": "  " * int(bloco.get("nivel") or 0) + bloco["preview"]}
            for bloco in dados["blocos"]
        ]
        return "\n".join(_linhas_tabela(registros, ("id", "tipo", "preview")))
    if comando == "ler-bloco":
        cabecalho = f"Bloco {dados['id']} ({dados['tipo']}) — editado em {dados['editado_em']}"
        aviso = f"\n{dados['aviso']}" if dados.get("aviso") else ""
        return f"{cabecalho}{aviso}\n\n{dados['markdown']}"
    if comando == "clonar-database":
        return (
            f"Clone criado: {dados['titulo']} ({dados['id']})\n"
            f"Propriedades: {len(dados['propriedades'])} | "
            f"linhas copiadas: {dados['linhas_copiadas']}"
        )
    if comando == "relacionar" and "resultados" in dados:
        linhas = [
            f"Pares: {dados['total']} | sucessos: {dados['sucessos']} | "
            f"erros: {dados['erros']}"
        ]
        for item in dados["resultados"]:
            par = f"{item['page_a']} ↔ {item['page_b']}"
            if item["ok"]:
                acao = item["resultado"].get("acao", "concluído")
                linhas.append(f"OK   {par}: {acao}")
            else:
                linhas.append(f"ERRO {par}: {item['erro']['mensagem']}")
        return "\n".join(linhas)
    if comando == "criar-subpagina":
        return f"Subpágina criada: {dados['titulo']} ({dados['id']})\nURL: {dados['url']}"
    if comando == "inspecionar-estrutura":
        return _json(dados)
    if comando == "clonar-estrutura":
        return (
            f"Subpáginas criadas: {len(dados['subpaginas_criadas'])} | "
            f"databases clonados: {len(dados['databases_clonados'])} | "
            f"ignorados: {len(dados['ignorados'])}"
        )
    if comando == "montar-estrutura-projeto":
        return (
            f"Subpáginas criadas: {', '.join(dados['subpaginas_criadas'])}\n"
            f"Databases criados: {', '.join(dados['databases_criados'])}"
        )
    if comando == "reordenar-bloco":
        aviso = " (ID mudou!)" if dados["id_mudou"] else ""
        return (
            f"Bloco {dados['bloco_id_antigo']} ({dados['tipo']}) reordenado -> "
            f"{dados['bloco_id_novo']}{aviso}\nBackup: {dados['backup_path']}"
        )
    if comando == "renomear-database":
        return f"Database {dados['id']} renomeado para '{dados['titulo']}'."
    if comando == "aparencia":
        partes = [
            f"{rotulo}: {dados[campo]}"
            for campo, rotulo in (("icone", "Ícone"), ("capa", "Capa"))
            if dados[campo]
        ]
        return f"Página {dados['page_id']} — " + "; ".join(partes) + "."
    if comando == "garantir-coluna":
        acao = "criada" if dados["criada"] else "já existia"
        return f"Coluna '{dados['coluna']}' ({dados['tipo']}) {acao} em {dados['database_id']}."
    if comando == "renomear-coluna":
        return (
            f"Coluna '{dados['coluna_antiga']}' renomeada para "
            f"'{dados['coluna_nova']}' em {dados['database_id']}."
        )
    if comando == "database-atual":
        if not dados["database_id"]:
            return "Database atual: (não configurado)"
        fontes = ", ".join(dados.get("data_sources") or []) or "(sem data source acessível)"
        return (
            f"Database atual: {dados['titulo']} ({dados['database_id']})\n"
            f"Data source: {fontes}\n"
            f"URL: {dados['url'] or '(sem URL)'}"
        )
    if comando == "normalizar-nomes":
        return _json(dados)
    if comando == "mapear":
        return (
            f"Itens: {dados['total_itens']} | páginas: {dados['total_paginas']} | "
            f"databases: {dados['total_databases']} | raízes: {dados['total_raizes']} | "
            f"duplicatas: {dados['total_duplicatas']} | órfãos: {dados['total_orfaos']}"
        )
    if comando == "atualizar-github":
        return (
            f"Repos: {dados['repos_encontrados']} | criados: {dados['paginas_criadas']} | "
            f"atualizados: {dados['paginas_atualizadas']} | "
            f"pulados: {dados['paginas_puladas']} | "
            f"READMEs novos: {dados['readmes_escritos']} | "
            f"READMEs atualizados: {dados['readmes_atualizados']} | "
            f"erros: {len(dados['erros'])}"
        )
    if comando == "exportar-docx":
        return (
            f"DOCX exportados: {dados['total']} | periodo: "
            f"{dados['periodo']['de']} a {dados['periodo']['ate']} | saida: {dados['saida']}"
        )
    if comando == "inventario":
        return (
            f"Inventário: {dados['total']} itens ({dados['paginas']} páginas, "
            f"{dados['databases']} databases) em {dados['segundos']} s → {dados['saida']}"
        )
    if comando == "baixar-corpos":
        linha = (
            f"Baixados: {dados['baixados']} | já existiam: {dados['pulados']} | "
            f"adiados: {dados['adiados']} | falhas: {len(dados['falhas'])} → {dados['destino']}"
        )
        return "\n".join([linha, *[f"- {pid}: {erro}" for pid, erro in dados["falhas"].items()]])
    if comando == "buscar-conteudo":
        linhas = [f"{dados['total_paginas']} página(s) com '{dados['expressao']}'"]
        for o in dados["ocorrencias"]:
            caminho = f"{o['caminho']} / " if o["caminho"] else ""
            linhas.append(f"\n{o['total']}x  {caminho}{o['titulo']}  ({o['criado_em'] or '?'})")
            linhas += [f"    … {trecho} …" for trecho in o["trechos"]]
        return "\n".join(linhas)
    if comando == "modelos":
        if "modelos" in dados:
            linhas = [
                f"{m['id']}  {m['nome'] or '(sem nome)'}" + ("  [padrão]" if m["padrao"] else "")
                for m in dados["modelos"]
            ]
            return "\n".join([*linhas, dados["aviso"]]) if linhas else dados["aviso"]
        prefixo = "[simulação] " if dados["dry_run"] else ""
        linhas = [f"{prefixo}{a['acao']}: {a['nome']}" for a in dados["acoes"]]
        if dados["faltam_modelos_vazios"]:
            linhas.append(
                f"Faltam {dados['faltam_modelos_vazios']} modelo(s) em branco. {dados['aviso']}"
            )
        return "\n".join(linhas)
    if comando == "copiar-corpo":
        if dados["pulado"]:
            return "Destino já tinha conteúdo: nada foi copiado (--so-se-vazio)."
        verbo = "Seriam copiados" if dados["dry_run"] else "Copiados"
        tipos = ", ".join(f"{tipo}: {n}" for tipo, n in dados["por_tipo"].items())
        linhas = [f"{verbo} {dados['blocos_total']} blocos ({tipos or 'nenhum'})."]
        linhas += [f"- ignorado {b['tipo']} ({b['id']}): {b['motivo']}" for b in dados["ignorados"]]
        if dados["conferencia"] is not None:
            linhas.append(
                "Conferência: " + ("confere" if dados["conferencia"]["confere"] else "DIVERGE")
            )
        return "\n".join(linhas)
    if comando == "mover-pagina":
        linhas = [dados["aviso"]]
        linhas += [
            f"+ coluna nova no destino: {c['nome']} ({c['tipo']})"
            for c in dados.get("colunas_acrescentadas_no_destino", [])
        ]
        linhas += [
            f"- valor perdido: {c['nome']} — {c['motivo']}"
            for c in dados.get("valores_perdidos", [])
        ]
        return "\n".join(linhas)
    if comando == "perfis":
        if "perfis" in dados:
            registros = dados["perfis"]
            if not registros:
                return "Nenhum perfil configurado."
            return "\n".join(
                _linhas_tabela(
                    registros,
                    ("alias", "ativo", "nome", "database_id", "token", "descricao"),
                )
            )
        return _json(dados)
    return _json(dados)


def _salvar_database_env(database_id: str, env_file: Path = RAIZ / ".env") -> None:
    linhas: list[str] = []
    if env_file.exists():
        linhas = env_file.read_text(encoding="utf-8").splitlines()
    chave = "NOTION_DATABASE_ID"
    nova_linha = f"{chave}={database_id}"
    atualizado = False
    for indice, linha in enumerate(linhas):
        if linha.startswith(f"{chave}="):
            linhas[indice] = nova_linha
            atualizado = True
            break
    if not atualizado:
        linhas.append(nova_linha)
    env_file.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")
    os.environ[chave] = database_id


def cmd_listar(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    tarefas = svc.listar_tarefas(
        status=_normalizar_texto(args.status),
        duracao=_normalizar_texto(args.duracao),
        areas=_lista_csv(args.area),
        tasklist=tasklist_factory(),
    )
    return [_tarefa_dict(tarefa) for tarefa in tarefas]


def cmd_ler(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    task_id = _id_notion(args.task_id, "task_id")
    procurado = chave_de_id(task_id)
    tarefas = svc.listar_tarefas(tasklist=tasklist_factory())
    for tarefa in tarefas:
        if chave_de_id(tarefa.id) == procurado:
            return _tarefa_dict(tarefa)
    raise CLIError(
        "Tarefa não encontrada no database padrão (NOTION_DATABASE_ID). Se o ID é de "
        "uma linha de outro database ou de uma página solta, leia com 'conteudo <id>'.",
        codigo="nao_encontrado",
        proximo_passo=f"notion-tasks conteudo {task_id}",
    )


def _tasklist_do_database(database_id: str, client_factory: ClientFactory) -> TaskListFactory:
    """``TaskList`` de um database escolhido na chamada (``criar --database``)."""

    return lambda: TaskList(client_factory(), database_id)


def cmd_criar(
    args: argparse.Namespace,
    *,
    tasklist_factory: TaskListFactory,
    client_factory: ClientFactory = _criar_client,
) -> Any:
    """Cria uma linha nova no database atual ou no de ``--database``.

    O ``TaskList`` descobre a coluna de título e só aplica os atalhos de tarefa
    (status, prazo, duração e área) quando as respectivas colunas existem.
    ``--set`` completa quaisquer outras propriedades depois da criação.
    ``--database`` troca só o destino desta chamada (o padrão do perfil não
    muda), valendo também para ``--arquivo`` e ``--dry-run``.

    Quando ``--status`` é usado, valida o valor contra as opções do modelo de
    tarefas antes de enviar, evitando ``Invalid status option`` da API.
    """
    database_bruto = getattr(args, "database", None)
    database = (
        _id_opcional(database_bruto, "--database") if isinstance(database_bruto, str) else None
    )
    if database:
        tasklist_factory = _tasklist_do_database(database, client_factory)

    arquivo = _argumento_arquivo_lote(args)
    estrito = getattr(args, "strict", False) is True
    dry_run = getattr(args, "dry_run", False) is True
    if arquivo:
        conflitos = {
            "nome": getattr(args, "nome", None),
            "--status": getattr(args, "status", None),
            "--prazo": getattr(args, "prazo", None),
            "--duracao": getattr(args, "duracao", None),
            "--area": getattr(args, "area", None),
            "--set": getattr(args, "set", None),
            "--conteudo": getattr(args, "conteudo", None),
            "--arquivo-md": _argumento_arquivo_md(args),
        }
        presentes = [nome for nome, valor in conflitos.items() if _argumento_presente(valor)]
        if presentes:
            raise CLIError(
                "Não misture --arquivo com os argumentos de uma criação individual: "
                + ", ".join(presentes)
            )
        return _cmd_criar_lote(
            arquivo,
            tasklist_factory=tasklist_factory,
            client_factory=client_factory,
            progresso_a_cada=getattr(args, "progresso_a_cada", 10),
            estrito=estrito,
            dry_run=dry_run,
        )

    nome = _texto_obrigatorio(args.nome, "nome")
    tasklist = tasklist_factory()

    # Validar status contra opções disponíveis (se fornecido)
    status = _normalizar_texto(args.status)
    if status:
        opcoes = svc.listar_opcoes(tasklist=tasklist)
        status_validos = opcoes.get("status", [])
        if status not in status_validos:
            raise CLIError(
                f"Status '{status}' inválido. Opções disponíveis: {', '.join(status_validos)}"
            )

    extras = _pares_chave_valor(getattr(args, "set", None), "--set")
    conteudo = _markdown_da_entrada(
        getattr(args, "conteudo", None), _argumento_arquivo_md(args), campo="--conteudo"
    )
    cliente: NotionClient | None = None
    preflight: svc_preflight.ResultadoPreflight | None = None
    if _preflight_necessario(extras, estrito=estrito, dry_run=dry_run):
        cliente = _cliente_tasklist(tasklist, client_factory)
        preflight = svc_preflight.preflight_criar(
            nome,
            extras,
            cliente=cliente,
            database_id=_database_id_tasklist(tasklist),
            estrito=estrito,
        )
        extras = preflight.valores

    if dry_run:
        dados_dry_run: dict[str, Any] = {
            "nome": nome,
            "database_id": _database_id_tasklist(tasklist),
            "dry_run": True,
            "escrever": False,
            "propriedades_planejadas": dict(extras),
            "conteudo_planejado": bool(conteudo),
        }
        if preflight is not None:
            dados_dry_run["preflight"] = _preflight_dict(preflight)
        return dados_dry_run

    tarefa = svc.criar_tarefa(
        nome,
        status=status,
        prazo=_normalizar_texto(args.prazo),
        duracao=_normalizar_texto(args.duracao),
        areas=_lista_csv(args.area),
        tasklist=tasklist,
    )
    dados = _tarefa_dict(tarefa)
    if database:
        dados["database_id"] = database

    # A partir daqui a linha JÁ EXISTE. Qualquer falha abaixo é reportada com o
    # id junto, para quem chamou poder completar a linha em vez de criar outra —
    # um script que estoura aqui sem saber o id deixa órfã no database.
    page_id = dados.get("id", "")
    if not extras and not conteudo and preflight is None:
        return dados

    try:
        if extras:
            cliente = cliente or client_factory()
            dados["propriedades"] = svc_propriedades.editar_linha(
                page_id, extras, cliente=cliente
            )["atualizadas"]
        if preflight is not None:
            dados["preflight"] = _preflight_dict(preflight)
            if preflight.projeto is not None:
                cliente = cliente or client_factory()
                dados["relacao_projeto"] = _aplicar_relacao_preflight(
                    page_id, preflight, cliente=cliente
                )
        if conteudo:
            cliente = cliente or client_factory()
            escrita = svc_conteudo.escrever_conteudo(
                page_id,
                conteudo,
                # A linha acabou de nascer vazia: não há database dentro dela.
                mesmo_com_database=True,
                cliente=cliente,
            )
            dados["blocos_anexados"] = escrita.anexados
            dados["blocos_criados"] = _blocos_criados(escrita)
    except Exception as erro:  # noqa: BLE001 - o id precisa sobreviver ao erro
        raise _erro_ao_completar_criacao(page_id, erro) from erro
    return dados


def _erro_ao_completar_criacao(page_id: str, erro: Exception) -> CLIError:
    """A linha JÁ existe: o erro leva o id e o conselho certo para completá-la.

    Depois de uma escrita parcial, "use 'escrever'" só é seguro quando nada do
    corpo ficou na página; se algo pode ter ficado, é preciso conferir antes.
    """

    classificado = classificar_erro(erro)
    motivo = str(erro) if classificado.codigo == "erro_interno" else classificado.mensagem
    proximo = f"notion-tasks editar-linha {page_id} --set \"Coluna=valor\""
    if isinstance(erro, EscritaParcialError):
        if erro.criados or erro.lote_incerto:
            conselho = (
                f"Parte do corpo pode ter ficado na página: confira com 'blocos {page_id}' "
                "antes de escrever de novo — não crie a linha de novo."
            )
            proximo = f"notion-tasks blocos {page_id}"
        else:
            conselho = (
                f"O corpo não ficou na página (os blocos novos foram desfeitos): escreva-o "
                f"com 'escrever {page_id}' — não crie a linha de novo."
            )
            proximo = f'notion-tasks escrever {page_id} "<markdown>"'
    else:
        conselho = f"Use 'editar-linha {page_id}' / 'escrever {page_id}' — não crie de novo."
    return CLIError(
        f"Tarefa criada (id {page_id}), mas falhou ao completá-la: {motivo} {conselho}",
        codigo="criacao_incompleta",
        proximo_passo=proximo,
        detalhes={"id": page_id, "causa": classificado.codigo, **classificado.detalhes},
    )


def cmd_editar(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    """Edita uma tarefa existente.

    IMPORTANTE: Valida status contra opções disponíveis no database para evitar
    erro "Invalid status option" da API do Notion.

    Problema conhecido: CLI falhava com status inválido que não existe no schema.
    Solução: Validar status contra opções do database antes de enviar.
    """
    campos = {
        "nome": _normalizar_texto(args.nome),
        "status": _normalizar_texto(args.status),
        "prazo": _normalizar_texto(args.prazo),
        "duracao": _normalizar_texto(args.duracao),
        "areas": _lista_csv(args.area),
    }

    if all(valor is None for valor in campos.values()):
        raise CLIError("Informe ao menos um campo para editar.")

    # Validar status contra opções disponíveis (se fornecido)
    status = campos["status"]
    if status:
        opcoes = svc.listar_opcoes(tasklist=tasklist_factory())
        status_validos = opcoes.get("status", [])
        if status not in status_validos:
            raise CLIError(
                f"Status '{status}' inválido. Opções disponíveis: {', '.join(status_validos)}"
            )

    tarefa = svc.editar_tarefa(
        _id_notion(args.task_id, "task_id"),
        **campos,
        tasklist=tasklist_factory(),
    )
    return _tarefa_dict(tarefa)


def cmd_mover(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    """Move tarefa para outro status.

    IMPORTANTE: Valida status contra opções disponíveis no database para evitar
    erro "Invalid status option" da API do Notion.

    Problema conhecido: CLI falhava com status inválido que não existe no schema.
    Solução: Validar status contra opções do database antes de enviar.
    """
    status = _texto_obrigatorio(args.status, "status")

    # Validar status contra opções disponíveis
    opcoes = svc.listar_opcoes(tasklist=tasklist_factory())
    status_validos = opcoes.get("status", [])
    if status not in status_validos:
        raise CLIError(
            f"Status '{status}' inválido. Opções disponíveis: {', '.join(status_validos)}"
        )

    tarefa = svc.mover_status(
        _id_notion(args.task_id, "task_id"),
        status,
        tasklist=tasklist_factory(),
    )
    return _tarefa_dict(tarefa)


def cmd_concluir(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    """Conclui tarefa com o status informado.

    IMPORTANTE: Valida status contra opções disponíveis no database para evitar
    erro "Invalid status option" da API do Notion.

    Problema conhecido: CLI falhava com status inválido que não existe no schema.
    Solução: Validar status contra opções do database antes de enviar.
    """
    status = _texto_obrigatorio(args.status, "status")

    # Validar status contra opções disponíveis
    opcoes = svc.listar_opcoes(tasklist=tasklist_factory())
    status_validos = opcoes.get("status", [])
    if status not in status_validos:
        raise CLIError(
            f"Status '{status}' inválido. Opções disponíveis: {', '.join(status_validos)}"
        )

    tarefa = svc.concluir_tarefa(
        _id_notion(args.task_id, "task_id"),
        status,
        tasklist=tasklist_factory(),
    )
    return _tarefa_dict(tarefa)


def cmd_opcoes(args: argparse.Namespace, *, tasklist_factory: TaskListFactory) -> Any:
    return svc.listar_opcoes(tasklist=tasklist_factory())


def cmd_databases(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    itens = client_factory().buscar(
        query=_normalizar_texto(args.query),
        buscar_todos=True,
        filtro={"property": "object", "value": "database"},
    )
    return [_database_dict(item) for item in itens]


def cmd_database_atual(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not database_id:
        return {"database_id": "", "titulo": "", "url": "", "data_sources": []}
    cliente = client_factory()
    database = cliente.get_database(database_id)
    fontes = cliente.listar_data_sources(database_id)
    return {
        "database_id": database_id,
        "titulo": _database_titulo(database),
        "url": database.get("url"),
        "data_sources": _nomes_data_sources(fontes),
    }


def cmd_escolher_database(args: argparse.Namespace) -> Any:
    """Define o database padrão, gravando onde a próxima execução vai ler.

    Com perfil ativo, grava **no perfil** — que é quem vence na resolução de
    credenciais. Gravar só no ``.env`` deixava o perfil sem ``database_id``, e o
    comando seguinte falhava com "NOTION_DATABASE_ID não configurado" mesmo
    depois de um "escolher-database" que respondeu sucesso.
    """

    database_id = _id_notion(args.database_id, "database_id")
    perfil = perfis_workspace.resolver_perfil(getattr(args, "perfil", None))
    if perfil is not None:
        atualizado = perfis_workspace.definir_database(database_id, perfil.alias)
        return {
            "database_id": database_id,
            "salvo_em": str(perfis_workspace.caminho_em_uso()),
            "perfil": atualizado.alias,
        }
    _salvar_database_env(database_id)
    return {"database_id": database_id, "salvo_em": str(RAIZ / ".env"), "perfil": ""}


def cmd_normalizar_nomes(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not database_id:
        raise CLIError("NOTION_DATABASE_ID não configurado.")
    return svc_normalizacao.normalizar_nomes(
        database_id,
        aplicar=not args.dry_run,
        cliente=client_factory(),
    )


def cmd_mapear(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    itens = client_factory().buscar(
        query=_normalizar_texto(args.query),
        page_size=args.page_size,
        buscar_todos=True,
    )
    inventario = construir_inventario(itens)
    duplicatas = [
        {"titulo": titulo, "ids": [item.id for item in grupo]}
        for titulo, grupo in inventario.duplicatas.items()
    ]
    return {
        "total_itens": len(inventario.itens),
        "total_paginas": inventario.total_paginas,
        "total_databases": inventario.total_databases,
        "total_raizes": len(inventario.raizes),
        "total_duplicatas": len(inventario.duplicatas),
        "total_orfaos": len(inventario.orfaos),
        "duplicatas": duplicatas[: args.limite_duplicatas],
    }


def cmd_conteudo(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    page_id = _id_notion(args.page_id, "page_id")
    cliente = client_factory()
    resultado = svc_conteudo.ler_pagina_ou_database(page_id, cliente=cliente)
    if resultado["tipo"] == "database":
        # Borda acrescenta o aviso voltado ao usuário da CLI.
        resultado["aviso"] = (
            "Isto é um database: o conteúdo são as linhas, não blocos. "
            "Use 'linhas' para listá-las (já incluídas em 'linhas' abaixo)."
        )
        return resultado

    # Página comum: pode ainda assim ser a CASA de uma database. Quem lê precisa
    # descobrir isso agora, na leitura, e não depois de escrever no lugar errado.
    dentro = svc_conteudo.databases_da_pagina(page_id, cliente=cliente)
    if dentro:
        resultado["databases_dentro"] = [
            {"id": database_id, "titulo": titulo or "(sem título)"}
            for database_id, titulo in dentro
        ]
        listagem = "; ".join(
            f"{titulo or '(sem título)'} ({database_id})" for database_id, titulo in dentro
        )
        resultado["aviso"] = (
            f"ATENÇÃO: esta página CONTÉM database(s) — {listagem}. "
            "O conteúdo de verdade são as LINHAS delas, não o corpo desta página. "
            "Use 'linhas <database_id>' para listar e trabalhe na linha certa. "
            "'escrever' aqui é recusado por padrão, porque criaria um bloco solto "
            "abaixo da tabela."
        )
    return resultado


def cmd_exemplo(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Devolve uma amostra de linhas do database atual com leitura completa.

    A listagem mantém a ordem devolvida pelo Notion, que funciona como uma
    amostra determinística. Cada linha é relida como página para incluir as
    propriedades preenchidas e o corpo em Markdown numa única execução da CLI.
    """

    quantidade = args.n
    if not 2 <= quantidade <= 4:
        raise CLIError("'--n' deve estar entre 2 e 4.")

    database_id = _texto_obrigatorio(
        os.environ.get("NOTION_DATABASE_ID"), "NOTION_DATABASE_ID"
    )
    cliente = client_factory()
    linhas = svc_conteudo.listar_linhas(database_id, cliente=cliente)
    exemplos = []
    for linha in linhas[:quantidade]:
        page_id = _texto_obrigatorio(linha.get("id"), "id da linha")
        conteudo = svc_conteudo.ler_pagina_ou_database(page_id, cliente=cliente)
        conteudo["titulo"] = linha.get("titulo", "")
        conteudo["url"] = linha.get("url", "")
        exemplos.append(conteudo)

    return {
        "database_id": database_id,
        "quantidade_solicitada": quantidade,
        "quantidade_retornada": len(exemplos),
        "total_linhas": len(linhas),
        "exemplos": exemplos,
    }


def cmd_linhas(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    linhas = svc_conteudo.listar_linhas(
        database_id,
        propriedades=getattr(args, "completo", False),
        cliente=client_factory(),
    )
    return {"id": database_id, "linhas": linhas}


def _pares_chave_valor(itens: Sequence[str] | None, flag: str) -> dict[str, str]:
    """Converte ``["Nome=valor", ...]`` num mapa ``{Nome: valor}``.

    Divide no primeiro ``=`` para o valor poder conter ``=``. O nome não pode
    ficar vazio. ``flag`` é citada na mensagem de erro (ex.: ``--set``).
    """

    pares: dict[str, str] = {}
    for item in itens or []:
        nome, sep, valor = item.partition("=")
        nome = nome.strip()
        if not sep or not nome:
            raise CLIError(f'Use o formato "Nome=valor" em {flag} (recebido: {item!r}).')
        pares[nome] = valor
    return pares


def _argumento_presente(valor: Any) -> bool:
    """Indica se um argumento real foi informado, sem confiar em ``Mock``."""

    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, os.PathLike):
        convertido = os.fspath(valor)
        return bool(convertido) if isinstance(convertido, str) else bool(convertido)
    if isinstance(valor, Sequence) and not isinstance(valor, (str, bytes, bytearray)):
        return bool(valor)
    return False


def _argumento_arquivo_lote(args: argparse.Namespace) -> str | None:
    """Lê ``--arquivo`` sem transformar atributos automáticos de ``Mock`` em caminho."""

    valor = getattr(args, "arquivo", None)
    if isinstance(valor, str):
        return _normalizar_texto(valor)
    if isinstance(valor, os.PathLike):
        convertido = os.fspath(valor)
        if isinstance(convertido, bytes):
            convertido = os.fsdecode(convertido)
        return _normalizar_texto(convertido)
    return None


def _valor_texto_lote(valor: Any, *, nome: str, indice: int) -> str:
    """Converte valor JSON/CSV para a sintaxe textual já usada por ``--set``."""

    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (list, tuple)):
        return ",".join(
            _valor_texto_lote(item, nome=nome, indice=indice) for item in valor
        )
    if isinstance(valor, Mapping):
        raise CLIError(
            f"Linha {indice}: o valor da propriedade '{nome}' deve ser texto, "
            "número, booleano ou lista — objeto aninhado não é aceito."
        )
    return str(valor)


def _pares_lote(valor: Any, *, campo: str, indice: int) -> dict[str, str]:
    """Normaliza um mapa/lista de propriedades pelo mesmo parser de ``--set``."""

    if valor is None:
        return {}
    if isinstance(valor, Mapping):
        itens = [
            f"{nome}={_valor_texto_lote(conteudo, nome=str(nome), indice=indice)}"
            for nome, conteudo in valor.items()
        ]
    elif isinstance(valor, str):
        itens = [valor]
    elif isinstance(valor, Sequence) and not isinstance(valor, (bytes, bytearray)):
        itens = []
        for item in valor:
            if not isinstance(item, str):
                raise CLIError(
                    f"Linha {indice}: '{campo}' em formato de lista deve conter "
                    "itens no formato Nome=valor."
                )
            itens.append(item)
    else:
        raise CLIError(
            f"Linha {indice}: '{campo}' deve ser um objeto de propriedades ou "
            "uma lista de itens Nome=valor."
        )
    return _pares_chave_valor(itens, f"{campo} da linha {indice}")


def _campo_lote(item: Mapping[str, Any], nomes: Sequence[str]) -> Any:
    """Obtém o primeiro campo presente, aceitando aliases de entrada."""

    for nome in nomes:
        if nome in item:
            return item[nome]
    return None


def _pares_campo_lote(
    item: Mapping[str, Any], nomes: Sequence[str], *, campo: str, indice: int
) -> dict[str, str]:
    """Lê um campo de propriedades e recusa aliases duplicados ambíguos."""

    presentes = [nome for nome in nomes if nome in item]
    if len(presentes) > 1:
        nomes_texto = ", ".join(presentes)
        raise CLIError(f"Linha {indice}: use apenas um entre {nomes_texto}.")
    return _pares_lote(item[presentes[0]], campo=campo, indice=indice) if presentes else {}


def _texto_campo_lote(valor: Any, *, campo: str, indice: int) -> str | None:
    """Valida texto usado como ID ou título de uma entrada de lote."""

    if valor is None:
        return None
    if not isinstance(valor, str):
        raise CLIError(f"Linha {indice}: '{campo}' deve ser texto.")
    return _normalizar_texto(valor)


def _normalizar_entrada_lote(
    item: Any, indice: int, *, criar: bool
) -> dict[str, Any]:
    """Valida uma entrada JSON/CSV e devolve dados prontos para o caso de uso."""

    if not isinstance(item, Mapping):
        raise CLIError(f"Linha {indice}: cada item do lote deve ser um objeto.")
    if item.get("__erro_lote__"):
        raise CLIError(f"Linha {indice}: {item['__erro_lote__']}")

    page_id = _texto_campo_lote(
        _campo_lote(item, ("page_id", "id")), campo="page_id", indice=indice
    )
    nome = _texto_campo_lote(
        _campo_lote(item, ("nome", "titulo")), campo="nome", indice=indice
    )
    if criar:
        nome = _texto_obrigatorio(nome, f"nome da linha {indice}")
    else:
        page_id = _id_notion(page_id, f"page_id da linha {indice}")

    return {
        "page_id": page_id,
        "nome": nome,
        "valores": _pares_campo_lote(
            item, ("propriedades", "set"), campo="propriedades", indice=indice
        ),
        "acrescentos": _pares_campo_lote(
            item, ("append", "acrescentos"), campo="append", indice=indice
        ),
    }


def _ler_csv_lote(caminho: Path) -> list[dict[str, Any]]:
    """Lê CSV com ``page_id``/``nome`` e demais colunas como propriedades."""

    try:
        with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
            leitor = csv.DictReader(arquivo)
            campos = leitor.fieldnames or []
            nomes = [campo.strip() if isinstance(campo, str) else "" for campo in campos]
            if not nomes or any(not nome for nome in nomes):
                raise CLIError("O cabeçalho do CSV de lote não pode ser vazio.")
            if len({nome.casefold() for nome in nomes}) != len(nomes):
                raise CLIError("O cabeçalho do CSV de lote não pode repetir colunas.")

            entradas: list[dict[str, Any]] = []
            for _linha_numero, linha in enumerate(leitor, start=2):
                entrada: dict[str, Any] = {}
                propriedades: dict[str, str] = {}
                acrescentos: dict[str, str] = {}
                erros: list[str] = []
                for campo, valor in linha.items():
                    if campo is None:
                        if valor:
                            erros.append("há valores depois da última coluna")
                        continue
                    nome = str(campo).strip()
                    texto = "" if valor is None else valor
                    chave = nome.casefold()
                    if chave in {"page_id", "id"}:
                        entrada["page_id"] = texto
                    elif chave in {"nome", "titulo"}:
                        entrada["nome"] = texto
                    elif chave.startswith("append:"):
                        coluna = nome.split(":", 1)[1].strip()
                        if coluna:
                            acrescentos[coluna] = texto
                        else:
                            erros.append("a coluna append: precisa informar o nome da propriedade")
                    else:
                        propriedades[nome] = texto
                if propriedades:
                    entrada["propriedades"] = propriedades
                if acrescentos:
                    entrada["append"] = acrescentos
                if erros:
                    entrada["__erro_lote__"] = "; ".join(erros)
                entradas.append(entrada)
            if not entradas:
                raise CLIError(f"O CSV de lote '{caminho}' não contém nenhuma linha.")
            return entradas
    except OSError as erro:
        raise CLIError(f"Não foi possível ler o CSV de lote '{caminho}': {erro}") from erro
    except UnicodeError as erro:
        raise CLIError(f"Não foi possível ler o CSV de lote '{caminho}': {erro}") from erro
    except csv.Error as erro:
        raise CLIError(f"CSV de lote inválido '{caminho}': {erro}") from erro


def _ler_arquivo_lote(caminho_texto: str) -> tuple[Path, list[Any]]:
    """Lê uma lista de entradas JSON ou CSV uma única vez."""

    caminho = Path(caminho_texto).expanduser()
    if not caminho.is_file():
        raise CLIError(f"Arquivo de lote não encontrado: {caminho}")
    if caminho.suffix.casefold() == ".csv":
        return caminho, _ler_csv_lote(caminho)

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except UnicodeError as erro:
        raise CLIError(f"Não foi possível ler o arquivo de lote '{caminho}': {erro}") from erro
    except json.JSONDecodeError as erro:
        raise CLIError(f"JSON de lote inválido '{caminho}': {erro.msg}") from erro
    except OSError as erro:
        raise CLIError(f"Não foi possível ler o arquivo de lote '{caminho}': {erro}") from erro

    if isinstance(dados, Mapping):
        for chave in ("linhas", "itens"):
            if chave in dados:
                dados = dados[chave]
                break
    if not isinstance(dados, list) or not dados:
        raise CLIError(
            f"O arquivo de lote '{caminho}' deve conter uma lista não vazia "
            "(ou um objeto com a chave 'linhas')."
        )
    return caminho, dados


def _referencia_entrada_lote(item: Any, *, criar: bool) -> dict[str, str]:
    """Extrai referência segura para o relatório quando a entrada falha."""

    if not isinstance(item, Mapping):
        return {}
    if criar:
        valor = _campo_lote(item, ("nome", "titulo"))
        return {"nome": valor.strip()} if isinstance(valor, str) and valor.strip() else {}
    valor = _campo_lote(item, ("page_id", "id"))
    return {"page_id": valor.strip()} if isinstance(valor, str) and valor.strip() else {}


def _erro_lote(erro: Exception) -> dict[str, Any]:
    """O ``erro`` de um item de lote: mesma classificação da CLI unitária."""

    classificado = classificar_erro(erro)
    return {
        "codigo": classificado.codigo,
        "mensagem": classificado.mensagem.strip() or type(erro).__name__,
    }


def _resultado_lote(
    indice: int,
    estado: str,
    *,
    page_id: str | None = None,
    block_id: str | None = None,
    nome: str | None = None,
    dados: Any = None,
    erro: Exception | None = None,
) -> dict[str, Any]:
    """Cria o registro estável de uma linha (ou bloco) processada."""

    resultado: dict[str, Any] = {
        "indice": indice,
        "estado": estado,
        "ok": estado == "sucesso",
    }
    if page_id is not None:
        resultado["page_id"] = page_id
    if block_id is not None:
        resultado["block_id"] = block_id
    if nome is not None:
        resultado["nome"] = nome
    if dados is not None:
        resultado["dados"] = dados
    if erro is not None:
        resultado["erro"] = _erro_lote(erro)
    return resultado


def _resumo_lote(
    comando: str, caminho: Path | None, resultados: list[dict[str, Any]]
) -> dict[str, Any]:
    """Monta o resumo final do lote (``arquivo`` é ``None`` quando os itens vêm do argv)."""

    return {
        "modo": "lote",
        "comando": comando,
        "arquivo": str(caminho) if caminho is not None else None,
        "total": len(resultados),
        "processados": len(resultados),
        "sucessos": sum(item["estado"] == "sucesso" for item in resultados),
        "erros": sum(item["estado"] == "erro" for item in resultados),
        "pendentes": sum(item["estado"] == "pendente" for item in resultados),
        "planejados": sum(item["estado"] == "planejado" for item in resultados),
        "bloqueados": sum(item["estado"] == "bloqueado" for item in resultados),
        "resultados": resultados,
    }


def _emitir_progresso_lote(
    indice: int,
    total: int,
    resultados: Sequence[dict[str, Any]],
    progresso_a_cada: int,
) -> None:
    """Emite progresso em stderr, preservando JSON válido em stdout."""

    if indice % progresso_a_cada and indice != total:
        return
    sucessos = sum(item["estado"] == "sucesso" for item in resultados)
    erros = sum(item["estado"] == "erro" for item in resultados)
    pendentes = sum(item["estado"] == "pendente" for item in resultados)
    bloqueados = sum(item["estado"] == "bloqueado" for item in resultados)
    print(
        f"[lote] {indice}/{total} | sucessos: {sucessos} | "
        f"erros: {erros} | pendentes: {pendentes} | bloqueados: {bloqueados}",
        file=sys.stderr,
    )


def _progresso_lote(valor: Any) -> int:
    """Valida o intervalo de progresso informado pelo usuário."""

    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise CLIError("'--progresso-a-cada' deve ser um inteiro maior que zero.")
    return valor


def _planejar_edicoes_lote(
    entradas: Sequence[Any],
    *,
    cliente: NotionClient,
    estrito: bool,
) -> tuple[
    dict[int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]],
    dict[int, tuple[dict[str, str], Exception]],
]:
    """Executa todos os preflights antes de um lote estrito ou simulado."""

    planos: dict[
        int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]
    ] = {}
    falhas: dict[int, tuple[dict[str, str], Exception]] = {}
    for indice, item in enumerate(entradas, start=1):
        referencia = _referencia_entrada_lote(item, criar=False)
        try:
            entrada = _normalizar_entrada_lote(item, indice, criar=False)
            preflight = svc_preflight.preflight_editar(
                entrada["page_id"],
                entrada["valores"],
                entrada["acrescentos"],
                cliente=cliente,
                estrito=estrito,
            )
            planos[indice] = (entrada, preflight, preflight.valores)
        except Exception as erro:  # noqa: BLE001 - o lote acumula falhas para não escrever parcialmente
            falhas[indice] = (referencia, erro)
    return planos, falhas


def _cmd_editar_linha_lote(
    caminho_texto: str,
    *,
    client_factory: ClientFactory,
    progresso_a_cada: Any,
    estrito: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Edita várias linhas mantendo o cliente dentro da mesma execução."""

    caminho, entradas = _ler_arquivo_lote(caminho_texto)
    intervalo = _progresso_lote(progresso_a_cada)
    resultados: list[dict[str, Any]] = []
    cliente: NotionClient | None = None
    planos: dict[
        int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]
    ] = {}

    if estrito or dry_run:
        cliente = client_factory()
        planos, falhas = _planejar_edicoes_lote(
            entradas, cliente=cliente, estrito=estrito
        )
        if dry_run or falhas:
            for indice, _item in enumerate(entradas, start=1):
                if indice in falhas:
                    referencia, erro = falhas[indice]
                    resultado = _resultado_lote(indice, "erro", erro=erro, **referencia)
                else:
                    entrada, preflight, valores = planos[indice]
                    if dry_run:
                        dados = {
                            "id": entrada["page_id"],
                            "dry_run": True,
                            "escrever": False,
                            "propriedades_planejadas": dict(valores),
                            "acrescimos_planejados": dict(entrada["acrescentos"]),
                            "preflight": _preflight_dict(preflight),
                        }
                        estado = "planejado"
                    else:
                        dados = {"preflight": _preflight_dict(preflight)}
                        erro_bloqueio = CLIError(
                            "Lote não escrito: --strict encontrou uma entrada inválida "
                            "e bloqueou todas as alterações para evitar escrita parcial."
                        )
                        estado = "bloqueado"
                        resultado = _resultado_lote(
                            indice,
                            estado,
                            page_id=entrada["page_id"],
                            dados=dados,
                            erro=erro_bloqueio,
                        )
                        resultados.append(resultado)
                        _emitir_progresso_lote(
                            indice, len(entradas), resultados, intervalo
                        )
                        continue
                    resultado = _resultado_lote(
                        indice,
                        estado,
                        page_id=entrada["page_id"],
                        dados=dados,
                    )
                resultados.append(resultado)
                _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)
            return _resumo_lote("editar-linha", caminho, resultados)

    for indice, item in enumerate(entradas, start=1):
        referencia = _referencia_entrada_lote(item, criar=False)
        try:
            if indice in planos:
                entrada, preflight, valores = planos[indice]
            else:
                entrada = _normalizar_entrada_lote(item, indice, criar=False)
                preflight = None
                valores = entrada["valores"]
            if cliente is None:
                cliente = client_factory()
            if preflight is None and _preflight_necessario(
                valores, estrito=estrito, dry_run=dry_run
            ):
                preflight = svc_preflight.preflight_editar(
                    entrada["page_id"],
                    valores,
                    entrada["acrescentos"],
                    cliente=cliente,
                    estrito=estrito,
                )
                valores = preflight.valores
            if dry_run:
                dados = {
                    "id": entrada["page_id"],
                    "dry_run": True,
                    "escrever": False,
                    "propriedades_planejadas": dict(valores),
                    "acrescimos_planejados": dict(entrada["acrescentos"]),
                }
                if preflight is not None:
                    dados["preflight"] = _preflight_dict(preflight)
                estado = "planejado"
            else:
                dados = svc_propriedades.editar_linha(
                    entrada["page_id"],
                    valores,
                    entrada["acrescentos"],
                    cliente=cliente,
                )
                if preflight is not None:
                    dados["preflight"] = _preflight_dict(preflight)
                    if preflight.projeto is not None:
                        dados["relacao_projeto"] = _aplicar_relacao_preflight(
                            entrada["page_id"], preflight, cliente=cliente
                        )
                estado = "sucesso"
            resultado = _resultado_lote(
                indice,
                estado,
                page_id=entrada["page_id"],
                dados=dados,
            )
        except Exception as erro:  # noqa: BLE001 - o lote continua nas demais linhas
            resultado = _resultado_lote(indice, "erro", erro=erro, **referencia)
        resultados.append(resultado)
        _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)

    return _resumo_lote("editar-linha", caminho, resultados)


def _planejar_criacoes_lote(
    entradas: Sequence[Any],
    *,
    tasklist: Any,
    cliente: NotionClient,
    estrito: bool,
) -> tuple[
    dict[int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]],
    dict[int, tuple[dict[str, str], Exception]],
]:
    """Executa todos os preflights de criação antes de um lote protegido."""

    planos: dict[
        int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]
    ] = {}
    falhas: dict[int, tuple[dict[str, str], Exception]] = {}
    for indice, item in enumerate(entradas, start=1):
        referencia = _referencia_entrada_lote(item, criar=True)
        try:
            entrada = _normalizar_entrada_lote(item, indice, criar=True)
            preflight = svc_preflight.preflight_criar(
                entrada["nome"],
                entrada["valores"],
                cliente=cliente,
                database_id=_database_id_tasklist(tasklist),
                estrito=estrito,
            )
            planos[indice] = (entrada, preflight, preflight.valores)
        except Exception as erro:  # noqa: BLE001 - o lote acumula falhas para não escrever parcialmente
            falhas[indice] = (referencia, erro)
    return planos, falhas


def _cmd_criar_lote(
    caminho_texto: str,
    *,
    tasklist_factory: TaskListFactory,
    client_factory: ClientFactory,
    progresso_a_cada: Any,
    estrito: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cria várias linhas e completa as propriedades com um cliente reutilizado."""

    caminho, entradas = _ler_arquivo_lote(caminho_texto)
    intervalo = _progresso_lote(progresso_a_cada)
    resultados: list[dict[str, Any]] = []
    tasklist: TaskList | None = None
    cliente: NotionClient | None = None
    planos: dict[
        int, tuple[dict[str, Any], svc_preflight.ResultadoPreflight, dict[str, str]]
    ] = {}

    if estrito or dry_run:
        tasklist = tasklist_factory()
        cliente = _cliente_tasklist(tasklist, client_factory)
        planos, falhas = _planejar_criacoes_lote(
            entradas, tasklist=tasklist, cliente=cliente, estrito=estrito
        )
        if dry_run or falhas:
            for indice, _item in enumerate(entradas, start=1):
                if indice in falhas:
                    referencia, erro = falhas[indice]
                    resultado = _resultado_lote(indice, "erro", erro=erro, **referencia)
                else:
                    entrada, preflight, valores = planos[indice]
                    if dry_run:
                        dados = {
                            "nome": entrada["nome"],
                            "dry_run": True,
                            "escrever": False,
                            "propriedades_planejadas": dict(valores),
                            "preflight": _preflight_dict(preflight),
                        }
                        estado = "planejado"
                    else:
                        dados = {"preflight": _preflight_dict(preflight)}
                        erro_bloqueio = CLIError(
                            "Lote não escrito: --strict encontrou uma entrada inválida "
                            "e bloqueou todas as criações para evitar escrita parcial."
                        )
                        estado = "bloqueado"
                        resultado = _resultado_lote(
                            indice,
                            estado,
                            nome=entrada["nome"],
                            dados=dados,
                            erro=erro_bloqueio,
                        )
                        resultados.append(resultado)
                        _emitir_progresso_lote(
                            indice, len(entradas), resultados, intervalo
                        )
                        continue
                    resultado = _resultado_lote(
                        indice,
                        estado,
                        nome=entrada["nome"],
                        dados=dados,
                    )
                resultados.append(resultado)
                _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)
            return _resumo_lote("criar", caminho, resultados)

    for indice, item in enumerate(entradas, start=1):
        referencia = _referencia_entrada_lote(item, criar=True)
        dados_criados: dict[str, Any] | None = None
        try:
            if indice in planos:
                entrada, preflight, valores = planos[indice]
            else:
                entrada = _normalizar_entrada_lote(item, indice, criar=True)
                preflight = None
                valores = entrada["valores"]
            if tasklist is None:
                tasklist = tasklist_factory()
            if preflight is None and _preflight_necessario(
                valores, estrito=estrito, dry_run=dry_run
            ):
                if cliente is None:
                    cliente = _cliente_tasklist(tasklist, client_factory)
                preflight = svc_preflight.preflight_criar(
                    entrada["nome"],
                    valores,
                    cliente=cliente,
                    database_id=_database_id_tasklist(tasklist),
                    estrito=estrito,
                )
                valores = preflight.valores
            if dry_run:
                dados_planejados: dict[str, Any] = {
                    "nome": entrada["nome"],
                    "dry_run": True,
                    "escrever": False,
                    "propriedades_planejadas": dict(valores),
                }
                if preflight is not None:
                    dados_planejados["preflight"] = _preflight_dict(preflight)
                resultado = _resultado_lote(
                    indice,
                    "planejado",
                    nome=entrada["nome"],
                    dados=dados_planejados,
                )
                resultados.append(resultado)
                _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)
                continue
            tarefa = svc.criar_tarefa(entrada["nome"], tasklist=tasklist)
            dados_criados = _tarefa_dict(tarefa)
            page_id = _texto_obrigatorio(dados_criados.get("id"), f"id criado na linha {indice}")
            if valores or entrada["acrescentos"]:
                if cliente is None:
                    cliente = _cliente_tasklist(tasklist, client_factory)
                dados_criados["propriedades"] = svc_propriedades.editar_linha(
                    page_id,
                    valores,
                    entrada["acrescentos"],
                    cliente=cliente,
                )["atualizadas"]
            if preflight is not None:
                dados_criados["preflight"] = _preflight_dict(preflight)
                if preflight.projeto is not None:
                    dados_criados["relacao_projeto"] = _aplicar_relacao_preflight(
                        page_id, preflight, cliente=cliente or client_factory()
                    )
            resultado = _resultado_lote(
                indice,
                "sucesso",
                page_id=page_id,
                nome=entrada["nome"],
                dados=dados_criados,
            )
        except Exception as erro:  # noqa: BLE001 - uma linha não interrompe o lote
            if dados_criados is not None and dados_criados.get("id"):
                resultado = _resultado_lote(
                    indice,
                    "pendente",
                    page_id=str(dados_criados["id"]),
                    nome=str(dados_criados.get("nome") or referencia.get("nome") or ""),
                    dados=dados_criados,
                    erro=erro,
                )
            else:
                resultado = _resultado_lote(indice, "erro", erro=erro, **referencia)
        resultados.append(resultado)
        _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)

    return _resumo_lote("criar", caminho, resultados)


def cmd_editar_linha(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    estrito = getattr(args, "strict", False) is True
    dry_run = getattr(args, "dry_run", False) is True
    arquivo = _argumento_arquivo_lote(args)
    if arquivo:
        conflitos = {
            "page_id": getattr(args, "page_id", None),
            "--set": getattr(args, "set", None),
            "--append": getattr(args, "append", None),
        }
        presentes = [nome for nome, valor in conflitos.items() if _argumento_presente(valor)]
        if presentes:
            raise CLIError(
                "Não misture --arquivo com os argumentos de uma edição individual: "
                + ", ".join(presentes)
            )
        return _cmd_editar_linha_lote(
            arquivo,
            client_factory=client_factory,
            progresso_a_cada=getattr(args, "progresso_a_cada", 10),
            estrito=estrito,
            dry_run=dry_run,
        )

    page_id = _id_notion(args.page_id, "page_id")
    valores = _pares_chave_valor(args.set, "--set")
    acrescentos = _pares_chave_valor(args.append, "--append")
    cliente = client_factory()
    preflight: svc_preflight.ResultadoPreflight | None = None
    if _preflight_necessario(valores, estrito=estrito, dry_run=dry_run):
        preflight = svc_preflight.preflight_editar(
            page_id,
            valores,
            acrescentos,
            cliente=cliente,
            estrito=estrito,
        )
        valores = preflight.valores

    if dry_run:
        dados_dry_run: dict[str, Any] = {
            "id": page_id,
            "dry_run": True,
            "escrever": False,
            "propriedades_planejadas": dict(valores),
            "acrescimos_planejados": dict(acrescentos),
        }
        if preflight is not None:
            dados_dry_run["preflight"] = _preflight_dict(preflight)
        return dados_dry_run

    dados = svc_propriedades.editar_linha(
        page_id, valores, acrescentos, cliente=cliente
    )
    if preflight is not None:
        dados["preflight"] = _preflight_dict(preflight)
        if preflight.projeto is not None:
            dados["relacao_projeto"] = _aplicar_relacao_preflight(
                page_id, preflight, cliente=cliente
            )
    return dados


def cmd_blocos(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    page_id = _id_notion(args.page_id, "page_id")
    blocos = svc_conteudo.listar_blocos(
        page_id,
        metadados=getattr(args, "metadados", False) is True,
        completo=getattr(args, "completo", False) is True,
        recursivo=getattr(args, "recursivo", False) is True,
        contendo=_normalizar_texto(getattr(args, "contendo", None)),
        cliente=client_factory(),
    )
    return {"id": page_id, "blocos": blocos}


def cmd_ler_bloco(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Lê UM bloco pelo ID: Markdown inteiro, tipo, pai e carimbos."""

    block_id = _id_notion(args.block_id, "block_id", bloco=True)
    lido: dict[str, Any] = dict(svc_conteudo.ler_bloco(block_id, cliente=client_factory()))
    # Subpágina e database não descem (o conteúdo deles é outra página/linhas):
    # a borda aponta o comando que lê o que está dentro.
    if lido["tipo"] == "child_page":
        lido["aviso"] = f"É uma subpágina: leia o conteúdo com 'conteudo {lido['id']}'."
    elif lido["tipo"] == "child_database":
        lido["aviso"] = f"É um database: liste as linhas com 'linhas {lido['id']}'."
    return lido


def cmd_escrever(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    page_id = _id_notion(args.page_id, "page_id")
    conteudo = _markdown_da_entrada(args.conteudo, _argumento_arquivo_md(args), campo="conteudo")
    if conteudo is None:
        raise CLIError(
            "O campo 'conteudo (texto, '-' para o stdin ou --arquivo-md)' é obrigatório."
        )
    apagar_tudo = getattr(args, "apagar_tudo", False)
    if apagar_tudo and not args.substituir:
        raise CLIError("--apagar-tudo só faz sentido junto de --substituir.")
    apos = _id_opcional(getattr(args, "apos", None), "--apos", bloco=True)
    inicio = getattr(args, "inicio", False) is True
    if (apos or inicio) and args.substituir:
        raise CLIError(
            "--apos/--inicio não combinam com --substituir: substituir troca o corpo "
            "inteiro e poderia apagar a própria âncora. Para inserir num ponto, rode "
            "sem --substituir."
        )
    resultado = svc_conteudo.escrever_conteudo(
        page_id,
        conteudo,
        substituir=args.substituir,
        apagar_nao_recriaveis=apagar_tudo,
        mesmo_com_database=getattr(args, "mesmo_com_database", False),
        apos_bloco_id=apos,
        inicio=inicio,
        cliente=client_factory(),
    )
    saida: dict[str, Any] = {
        "id": page_id,
        "blocos_anexados": resultado.anexados,
        "substituiu": args.substituir,
        "posicao": _posicao_escrita(apos, inicio),
        "blocos_criados": _blocos_criados(resultado),
    }
    if resultado.limpeza is not None:
        # Dizer o que foi mantido é o ponto: quem substituiu precisa saber que a
        # imagem/subpágina continua na página e o texto novo entrou depois dela.
        saida.update(_dados_limpeza(resultado.limpeza))
        if resultado.preservados:
            saida["aviso"] = (
                "Preservados blocos que não se recriam a partir de Markdown "
                f"({', '.join(resultado.limpeza.tipos_preservados)}); o conteúdo novo "
                "entrou depois deles (o motivo de cada um está em blocos_preservados). "
                "Use --apagar-tudo para apagá-los também."
            )
    return saida


def _posicao_escrita(apos: str | None, inicio: bool) -> dict[str, str]:
    """Onde o conteúdo novo entrou: ``fim`` (padrão), ``inicio`` ou após um bloco."""

    if apos:
        return {"tipo": "apos_bloco", "bloco_id": apos}
    return {"tipo": "inicio" if inicio else "fim"}


def _blocos_criados(resultado: svc_conteudo.ResultadoEscrita) -> list[dict[str, str]]:
    """IDs dos blocos de topo criados, na ordem (filhos exigem 'blocos --recursivo')."""

    return [{"id": bloco.id, "tipo": bloco.tipo} for bloco in resultado.criados]


def _dados_limpeza(limpeza: svc_conteudo.ResultadoLimpeza) -> dict[str, Any]:
    """O que ``limpar`` e ``escrever --substituir`` apagaram e mantiveram.

    ``blocos_apagados`` continua sendo a contagem (contrato antigo); os IDs
    vêm em ``blocos_apagados_ids``, porque é com eles que a API restaura —
    ``desfazer`` traz o comando pronto.
    """

    dados: dict[str, Any] = {
        "blocos_apagados": limpeza.apagados,
        "blocos_apagados_ids": [
            {"id": bloco_id, "tipo": tipo} for bloco_id, tipo in limpeza.apagados_ids
        ],
        "blocos_preservados": [
            {"id": bloco_id, "tipo": tipo, "motivo": limpeza.motivos.get(bloco_id, "")}
            for bloco_id, tipo in limpeza.preservados
        ],
    }
    dados.update(dados_desfazer(limpeza.apagados_ids))
    return dados


def cmd_limpar(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    page_id = _id_notion(args.page_id, "page_id")
    # Operação destrutiva: exige confirmação explícita, nunca apaga "no susto".
    if not args.sim:
        raise CLIError(
            "Limpar apaga TODO o corpo da página (destrutivo). "
            "Repita com --sim para confirmar."
        )
    resultado = svc_conteudo.limpar_conteudo(
        page_id,
        incluir_nao_recriaveis=getattr(args, "apagar_tudo", False),
        cliente=client_factory(),
    )
    saida: dict[str, Any] = {"id": page_id, **_dados_limpeza(resultado)}
    if resultado.preservados:
        saida["aviso"] = (
            "Preservados blocos que não se recriam a partir de Markdown "
            f"({', '.join(resultado.tipos_preservados)}); o motivo de cada um está em "
            "blocos_preservados. Use --apagar-tudo para apagá-los também."
        )
    return saida


def cmd_restaurar_bloco(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Tira blocos da lixeira pelo ID — o desfazer de ``limpar``/``apagar-bloco``.

    Aceita vários IDs (o normal é desfazer um ``limpar`` inteiro, cujo
    ``desfazer`` já traz o comando). Um ID que falhar não interrompe os demais;
    se nenhum voltar, é erro.
    """

    ids = [_id_notion(valor, "block_id", bloco=True) for valor in args.block_ids]
    resultado = svc_conteudo.restaurar_blocos(ids, cliente=client_factory())
    falhas = [{"id": bloco_id, "motivo": motivo} for bloco_id, motivo in resultado.falhas]
    if falhas and not resultado.restaurados:
        raise CLIError(
            "Nenhum bloco foi restaurado: "
            + "; ".join(f"{item['id']}: {item['motivo']}" for item in falhas),
            codigo="restauracao_falhou",
            saida=SAIDA_FALHA,
            detalhes={"falhas": falhas},
        )
    return {
        "restaurados": resultado.restaurados,
        "falhas": falhas,
        "aviso": (
            "Os blocos restaurados voltam no FIM da página, com o mesmo ID e os "
            "filhos (a API não os devolve à posição original); use 'reordenar-bloco' "
            "para reposicioná-los."
        ),
    }


def cmd_editar_bloco(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Edita UM bloco: reescreve por Markdown ou troca um trecho (``--trocar``).

    A reescrita sempre confere o bloco atual (``conferir_atual``): texto sem
    prefixo mantém o tipo (um heading continua heading), prefixo de outro tipo
    e várias linhas são recusados, e o que o Markdown não representa (menção,
    sublinhado, cor…) só é descartado com ``--aceitar-perda-de-formatacao``.
    """

    trocar = getattr(args, "trocar", None)
    por = getattr(args, "por", None)
    todas = getattr(args, "todas", False) is True
    aceitar_perda = getattr(args, "aceitar_perda_de_formatacao", False) is True
    # Sem strip: num bloco de código o texto inteiro é o código, recuo incluído.
    conteudo = _markdown_da_entrada(
        getattr(args, "conteudo", None), _argumento_arquivo_md(args), campo="conteudo"
    )
    arquivo = _argumento_arquivo_lote(args)
    if arquivo:
        conflitos = {
            "block_id": getattr(args, "block_id", None),
            "conteudo": conteudo,
            "--trocar": trocar,
            "--por": por,
        }
        presentes = [nome for nome, valor in conflitos.items() if valor is not None]
        presentes += ["--todas"] if todas else []
        presentes += ["--aceitar-perda-de-formatacao"] if aceitar_perda else []
        if presentes:
            raise CLIError(
                "Não misture --arquivo com os argumentos de uma edição individual: "
                + ", ".join(presentes)
            )
        return _cmd_editar_bloco_lote(
            arquivo,
            client_factory=client_factory,
            progresso_a_cada=getattr(args, "progresso_a_cada", 10),
        )

    block_id = _id_notion(args.block_id, "block_id", bloco=True)
    _validar_modo_edicao(conteudo, trocar, por, todas=todas, aceitar_perda=aceitar_perda)
    return _executar_edicao(
        block_id,
        conteudo=conteudo,
        trocar=trocar,
        por=por,
        todas=todas,
        aceitar_perda=aceitar_perda,
        cliente=client_factory(),
    )


def _executar_edicao(
    block_id: str,
    *,
    conteudo: str | None,
    trocar: str | None,
    por: str | None,
    todas: bool,
    aceitar_perda: bool,
    cliente: NotionClient,
) -> dict[str, Any]:
    """Uma edição já validada: troca de trecho ou reescrita por Markdown."""

    if trocar is not None:
        return _trocar_trecho(block_id, trocar, por or "", todas=todas, cliente=cliente)
    return _editar_por_markdown(
        block_id, conteudo or "", aceitar_perda=aceitar_perda, cliente=cliente
    )


#: Valores aceitos como verdadeiro/falso nas colunas booleanas de um lote.
_VERDADEIROS = frozenset({"true", "sim", "s", "1", "yes", "y"})
_FALSOS = frozenset({"", "false", "nao", "não", "n", "0", "no"})


def _booleano_lote(valor: Any, *, campo: str, indice: int) -> bool:
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    texto = str(valor).strip().casefold()
    if texto in _VERDADEIROS:
        return True
    if texto in _FALSOS:
        return False
    raise CLIError(f"Item {indice}: '{campo}' deve ser verdadeiro ou falso (recebido: {valor!r}).")


def _texto_lote(valor: Any, *, campo: str, indice: int) -> str | None:
    """Texto opcional de um item de lote; célula vazia do CSV conta como ausente."""

    if valor is None:
        return None
    if not isinstance(valor, str):
        raise CLIError(f"Item {indice}: '{campo}' deve ser texto.")
    return valor if valor.strip() else None


def _ler_arquivo_edicoes(caminho_texto: str) -> tuple[Path, list[Any]]:
    """JSON como nos demais lotes; CSV com as colunas block_id, conteudo, trocar, por…"""

    caminho = Path(caminho_texto).expanduser()
    if caminho.suffix.casefold() != ".csv":
        return _ler_arquivo_lote(caminho_texto)
    if not caminho.is_file():
        raise CLIError(f"Arquivo de lote não encontrado: {caminho}")
    try:
        with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
            linhas = [
                {str(chave).strip(): valor for chave, valor in linha.items() if chave is not None}
                for linha in csv.DictReader(arquivo)
            ]
    except (OSError, UnicodeError, csv.Error) as erro:
        raise CLIError(f"Não foi possível ler o CSV de lote '{caminho}': {erro}") from erro
    if not linhas:
        raise CLIError(f"O CSV de lote '{caminho}' não contém nenhuma linha.")
    return caminho, linhas


def _cmd_editar_bloco_lote(
    caminho_texto: str, *, client_factory: ClientFactory, progresso_a_cada: Any
) -> dict[str, Any]:
    """Várias edições de bloco num processo: um cliente, um resultado por item.

    Cada item é ``{"block_id", "conteudo"}`` ou ``{"block_id", "trocar", "por",
    "todas"}`` (``aceitar_perda_de_formatacao`` opcional). Um item com erro não
    interrompe os demais.
    """

    intervalo = _progresso_lote(progresso_a_cada)
    caminho, entradas = _ler_arquivo_edicoes(caminho_texto)
    cliente = client_factory()
    resultados: list[dict[str, Any]] = []
    for indice, item in enumerate(entradas, start=1):
        referencia: str | None = None
        try:
            if not isinstance(item, Mapping):
                raise CLIError(
                    f"Item {indice}: use um objeto com block_id e conteudo (ou trocar/por)."
                )
            campos = {str(chave).strip().casefold(): valor for chave, valor in item.items()}
            bruto = _texto_lote(
                campos.get("block_id", campos.get("id")), campo="block_id", indice=indice
            )
            referencia = bruto
            block_id = _id_notion(bruto, f"block_id do item {indice}", bloco=True)
            referencia = block_id
            trocar = _texto_lote(campos.get("trocar"), campo="trocar", indice=indice)
            por_bruto = campos.get("por")
            if trocar is None:
                por = _texto_lote(por_bruto, campo="por", indice=indice)
            else:
                # Com --trocar, "por" vazio é válido: apaga o trecho.
                por = None if por_bruto is None else str(por_bruto)
            conteudo = _texto_lote(campos.get("conteudo"), campo="conteudo", indice=indice)
            todas = _booleano_lote(campos.get("todas"), campo="todas", indice=indice)
            aceitar = _booleano_lote(
                campos.get("aceitar_perda_de_formatacao"),
                campo="aceitar_perda_de_formatacao",
                indice=indice,
            )
            _validar_modo_edicao(conteudo, trocar, por, todas=todas, aceitar_perda=aceitar)
            dados = _executar_edicao(
                block_id,
                conteudo=conteudo,
                trocar=trocar,
                por=por,
                todas=todas,
                aceitar_perda=aceitar,
                cliente=cliente,
            )
        except Exception as erro:  # noqa: BLE001 - o lote relata cada item sem parar
            resultados.append(_resultado_lote(indice, "erro", block_id=referencia, erro=erro))
        else:
            resultados.append(
                _resultado_lote(indice, "sucesso", block_id=block_id, dados=dados)
            )
        _emitir_progresso_lote(indice, len(entradas), resultados, intervalo)
    return _resumo_lote("editar-bloco", caminho, resultados)


def _validar_modo_edicao(
    conteudo: str | None,
    trocar: str | None,
    por: str | None,
    *,
    todas: bool,
    aceitar_perda: bool,
) -> None:
    """Recusa, antes de qualquer chamada, combinações de flags sem sentido."""

    if trocar is not None:
        if conteudo is not None:
            raise CLIError(
                "Use o conteúdo novo OU --trocar/--por, não os dois: --trocar muda só um "
                "trecho e mantém o resto do bloco."
            )
        if por is None:
            raise CLIError('--trocar exige --por "<texto novo>" (use --por "" para apagar).')
        if not trocar:
            raise CLIError("--trocar não pode ser vazio.")
        if aceitar_perda:
            raise CLIError(
                "--aceitar-perda-de-formatacao não se aplica a --trocar: a troca de "
                "trecho já preserva a formatação."
            )
        return
    if por is not None or todas:
        raise CLIError("--por e --todas só valem junto de --trocar.")
    if conteudo is None:
        raise CLIError(
            "Informe o conteúdo novo do bloco (uma linha de Markdown) ou use "
            '--trocar "<trecho>" --por "<novo>".'
        )


def _editar_por_markdown(
    block_id: str, conteudo: str, *, aceitar_perda: bool, cliente: NotionClient
) -> dict[str, Any]:
    try:
        resposta = svc_conteudo.editar_bloco(
            block_id,
            conteudo,
            conferir_atual=True,
            aceitar_perda_de_formatacao=aceitar_perda,
            cliente=cliente,
        )
    except EdicaoMultiblocoError as erro:
        raise CLIError(
            f"editar-bloco edita UM bloco, mas o Markdown gerou {erro.quantidade} blocos; "
            "nada foi alterado. Mande uma linha só; para o resto, edite este bloco com a "
            "primeira linha e insira as demais logo depois dele com "
            f"'escrever <pagina_id> \"<markdown>\" --apos {block_id}'.",
            codigo="edicao_multibloco",
            proximo_passo=f'notion-tasks escrever <pagina_id> "<markdown>" --apos {block_id}',
            detalhes={"quantidade": erro.quantidade},
        ) from erro
    except PerdaDeFormatacaoError as erro:
        raise CLIError(
            f"Reescrever o bloco {block_id} por Markdown perderia: "
            f"{'; '.join(erro.perdas)}. Nada foi alterado. Para mudar só um trecho "
            f"mantendo o resto: 'editar-bloco {block_id} --trocar \"<antigo>\" --por "
            "\"<novo>\"'; para reescrever mesmo assim, repita com "
            "--aceitar-perda-de-formatacao.",
            codigo="perda_de_formatacao",
            proximo_passo=(
                f'notion-tasks editar-bloco {block_id} --trocar "<antigo>" --por "<novo>"'
            ),
            detalhes={"perdas": list(erro.perdas)},
        ) from erro
    return _resumo_bloco_editado(block_id, resposta)


def _resumo_bloco_editado(block_id: str, resposta: Any) -> dict[str, Any]:
    """Confirma o que foi gravado a partir da resposta do PATCH (sem outra chamada).

    ``editado_em`` vem arredondado ao minuto (observado); a confirmação de
    verdade é o ``markdown`` devolvido.
    """

    lido = resposta if isinstance(resposta, dict) and resposta.get("type") else {}
    return {
        "id": block_id,
        "editado": True,
        "tipo": str(lido.get("type") or ""),
        "markdown": blocos_para_markdown([lido]) if lido else "",
        "editado_em": str(lido.get("last_edited_time") or ""),
    }


def _trocar_trecho(
    block_id: str, trocar: str, por: str, *, todas: bool, cliente: NotionClient
) -> dict[str, Any]:
    try:
        resultado = svc_conteudo.trocar_trecho(
            block_id, trocar, por, todas=todas, cliente=cliente
        )
    except TrechoAmbiguoError as erro:
        raise CLIError(
            f"O trecho '{trocar}' aparece {erro.ocorrencias} vezes no bloco {block_id}; "
            "repita com --todas para trocar todas, ou use um trecho mais longo.",
            codigo="trecho_ambiguo",
            detalhes={"ocorrencias": erro.ocorrencias},
        ) from erro
    return {
        "id": resultado.id,
        "editado": True,
        "tipo": resultado.tipo,
        "ocorrencias": resultado.ocorrencias,
        "markdown": resultado.markdown,
        "editado_em": resultado.editado_em,
    }


def cmd_apagar_bloco(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Manda um ou mais blocos para a lixeira, conferindo cada alvo antes.

    Cada bloco é lido antes do DELETE (``apagar_bloco_verificado``): subpágina
    e database — que levam tudo o que está dentro — exigem
    ``--forcar-tipos-arriscados``, e a saída diz o que foi apagado e como
    desfazer. Com vários IDs, o envelope é o de lote: um erro não interrompe
    os demais.
    """

    ids = _ids_unicos(args.block_ids)
    # Operação destrutiva: exige confirmação explícita, nunca apaga "no susto".
    if not args.sim:
        raise CLIError(
            "Apagar é destrutivo. Repita com --sim para confirmar a exclusão do bloco."
        )
    forcar = getattr(args, "forcar_tipos_arriscados", False) is True
    cliente = client_factory()
    if len(ids) == 1:
        return _apagar_um_bloco(ids[0], forcar=forcar, cliente=cliente)

    resultados: list[dict[str, Any]] = []
    apagados: list[tuple[str, str]] = []
    for indice, block_id in enumerate(ids, start=1):
        try:
            dados = _apagar_um_bloco(block_id, forcar=forcar, cliente=cliente)
        except Exception as erro:  # noqa: BLE001 - o lote relata cada ID sem parar
            resultados.append(_resultado_lote(indice, "erro", block_id=block_id, erro=erro))
            continue
        apagados.append((dados["id"], dados["tipo"]))
        resultados.append(_resultado_lote(indice, "sucesso", block_id=block_id, dados=dados))
    resumo = _resumo_lote("apagar-bloco", None, resultados)
    resumo.update(dados_desfazer(apagados))
    return resumo


def _ids_unicos(valores: Sequence[str]) -> list[str]:
    """IDs de bloco normalizados, na ordem, sem repetir o mesmo bloco."""

    vistos: set[str] = set()
    ids: list[str] = []
    for valor in valores:
        block_id = _id_notion(valor, "block_id", bloco=True)
        if chave_de_id(block_id) not in vistos:
            vistos.add(chave_de_id(block_id))
            ids.append(block_id)
    return ids


def _apagar_um_bloco(block_id: str, *, forcar: bool, cliente: NotionClient) -> dict[str, Any]:
    try:
        apagado = svc_conteudo.apagar_bloco_verificado(
            block_id, forcar_tipos_arriscados=forcar, cliente=cliente
        )
    except ExclusaoArriscadaError as erro:
        alvo = "a subpágina" if erro.tipo == "child_page" else "o database"
        raise CLIError(
            f"O bloco {block_id} é {alvo} '{erro.titulo or '(sem título)'}': apagá-lo manda "
            "para a lixeira tudo o que está dentro. Nada foi apagado. Se é isso mesmo, "
            "repita com --forcar-tipos-arriscados.",
            codigo="exclusao_arriscada",
            detalhes={"tipo": erro.tipo, "titulo": erro.titulo},
        ) from erro
    return {
        "id": apagado.id,
        "apagado": True,
        "tipo": apagado.tipo,
        "resumo": apagado.resumo,
        "tem_filhos": apagado.tem_filhos,
        **dados_desfazer([(apagado.id, apagado.tipo)]),
    }


def _texto_par_relacao(valor: Any, origem: str) -> str:
    """Valida um ID vindo de ``--par`` ou de um arquivo JSON."""

    if not isinstance(valor, str):
        raise CLIError(f"{origem} deve conter IDs como texto.")
    return _id_notion(valor, origem)


def _par_relacao(valor: Any, origem: str) -> tuple[str, str]:
    """Converte ``page_a:page_b`` em um par validado."""

    if not isinstance(valor, str):
        raise CLIError(f"Use o formato \"page_a:page_b\" em {origem}.")
    page_a, separador, page_b = valor.partition(":")
    if not separador:
        raise CLIError(f"Use o formato \"page_a:page_b\" em {origem} (recebido: {valor!r}).")
    return (
        _texto_par_relacao(page_a, f"{origem} (page_a)"),
        _texto_par_relacao(page_b, f"{origem} (page_b)"),
    )


def _par_relacao_do_json(valor: Any, indice: int) -> tuple[str, str]:
    """Lê um item de ``--arquivo`` em formato objeto, lista ou ``a:b``."""

    origem = f"--arquivo item {indice}"
    if isinstance(valor, str):
        return _par_relacao(valor, origem)
    if isinstance(valor, (list, tuple)):
        if len(valor) != 2:
            raise CLIError(f"{origem} deve ser uma lista com exatamente dois IDs.")
        return (
            _texto_par_relacao(valor[0], f"{origem} (page_a)"),
            _texto_par_relacao(valor[1], f"{origem} (page_b)"),
        )
    if isinstance(valor, dict):
        if "page_a" not in valor or "page_b" not in valor:
            raise CLIError(f"{origem} deve ter as chaves 'page_a' e 'page_b'.")
        return (
            _texto_par_relacao(valor["page_a"], f"{origem}.page_a"),
            _texto_par_relacao(valor["page_b"], f"{origem}.page_b"),
        )
    raise CLIError(
        f"{origem} deve ser \"a:b\", uma lista de dois IDs "
        "ou um objeto com page_a/page_b."
    )


def _pares_relacao_do_arquivo(caminho: str) -> list[tuple[str, str]]:
    """Carrega e valida a lista de pares de um arquivo JSON."""

    arquivo = Path(_texto_obrigatorio(caminho, "arquivo"))
    try:
        conteudo = arquivo.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CLIError(f"Não foi possível ler o arquivo de pares '{arquivo}': {exc}") from exc
    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError as exc:
        raise CLIError(
            f"JSON inválido no arquivo de pares '{arquivo}' "
            f"(linha {exc.lineno}, coluna {exc.colno})."
        ) from exc

    if isinstance(dados, dict) and "pares" in dados:
        dados = dados["pares"]
    elif isinstance(dados, dict) and {"page_a", "page_b"}.issubset(dados):
        dados = [dados]
    if not isinstance(dados, list):
        raise CLIError(
            "O arquivo de pares deve conter uma lista JSON "
            "ou um objeto com a chave 'pares'."
        )
    if not dados:
        raise CLIError("O arquivo de pares não contém nenhum par.")
    return [_par_relacao_do_json(valor, indice) for indice, valor in enumerate(dados, start=1)]


def _obter_pares_relacao(args: argparse.Namespace) -> tuple[list[tuple[str, str]], bool]:
    """Resolve o par legado ou as entradas de lote do comando ``relacionar``."""

    page_a = getattr(args, "page_a", None)
    page_b = getattr(args, "page_b", None)
    pares = getattr(args, "par", None) or []
    arquivo = getattr(args, "arquivo", None)
    tem_posicionais = page_a is not None or page_b is not None
    tem_lote = bool(pares) or bool(arquivo)

    if tem_posicionais:
        if page_a is None or page_b is None:
            raise CLIError("Informe page_a e page_b juntos.")
        if tem_lote:
            raise CLIError("Não misture page_a/page_b com --par ou --arquivo.")
        return [
            (
                _id_notion(page_a, "page_a"),
                _id_notion(page_b, "page_b"),
            )
        ], False
    if pares and arquivo:
        raise CLIError("Use --par ou --arquivo, não os dois ao mesmo tempo.")
    if pares:
        return [
            _par_relacao(valor, f"--par #{indice}")
            for indice, valor in enumerate(pares, 1)
        ], True
    if arquivo:
        return _pares_relacao_do_arquivo(arquivo), True
    raise CLIError(
        "Informe page_a e page_b, repita --par \"page_a:page_b\" ou use --arquivo <pares.json>."
    )


def cmd_schema(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Descreve o schema real de um database: colunas, tipos, opções e relações.

    É o comando que responde à pergunta que antecede **toda** escrita num
    database que você não conhece — qual o nome exato da coluna, quais valores
    o select aceita, o que é calculado pelo Notion e não aceita PATCH, e quais
    relações são de mão única (precisam ser gravadas nos dois lados).

    Sem ele o caminho era chamar a API do Notion na mão, que é justamente o
    passo que se pula com pressa — e o erro aparece depois, já gravado.
    """

    database_id = _id_notion(args.database_id, "database_id")
    descricao = starter_schema.descrever_database(
        client_factory().get_database(database_id)
    )
    dados = descricao.para_dict()
    if args.editaveis:
        editaveis = {coluna.nome for coluna in descricao.editaveis}
        dados["colunas"] = [c for c in dados["colunas"] if c["nome"] in editaveis]
    return dados


def cmd_relacionar(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Liga uma ou várias linhas numa coluna de relação, **nos dois sentidos**.

    Uma relação ``single_property`` do Notion parece bidirecional na interface
    (ligar pela tela mostra as duas páginas se enxergando), mas pela API só o
    lado escrito é gravado. Este comando resolve isso: descobre a configuração
    da coluna e, quando ela é de mão única, escreve as duas pontas.

    A forma posicional antiga continua aceitando um par. Para lotes, ``--par``
    pode ser repetido ou ``--arquivo`` pode apontar para um JSON com uma lista
    de objetos ``{"page_a": "...", "page_b": "..."}``.
    """

    coluna = _texto_obrigatorio(args.coluna, "coluna")
    pares, lote = _obter_pares_relacao(args)
    cliente = client_factory()

    if not lote:
        origem, destino = pares[0]
        if chave_de_id(origem) == chave_de_id(destino):
            raise CLIError("page_a e page_b são a mesma página — nada a relacionar.")
        return svc_relacoes.relacionar(
            origem,
            destino,
            coluna,
            desfazer=args.desfazer,
            cliente=cliente,
        )

    resultados: list[dict[str, Any]] = []
    for indice, (origem, destino) in enumerate(pares, start=1):
        item: dict[str, Any] = {
            "indice": indice,
            "page_a": origem,
            "page_b": destino,
        }
        if chave_de_id(origem) == chave_de_id(destino):
            item.update(
                ok=False,
                erro={
                    "codigo": "validacao",
                    "mensagem": "page_a e page_b são a mesma página — nada a relacionar.",
                },
            )
            resultados.append(item)
            continue
        try:
            resultado = svc_relacoes.relacionar(
                origem,
                destino,
                coluna,
                desfazer=args.desfazer,
                cliente=cliente,
            )
        except (CLIError, ValueError, NotionAPIError) as exc:
            item.update(ok=False, erro=_erro_lote(exc))
        else:
            item.update(ok=True, resultado=resultado)
        resultados.append(item)

    erros = sum(1 for item in resultados if not item["ok"])
    return {
        "coluna": coluna,
        "desfazer": args.desfazer,
        "total": len(resultados),
        "sucessos": len(resultados) - erros,
        "erros": erros,
        "resultados": resultados,
    }


def cmd_relatorios_do_git(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Reconstrói relatórios diários a partir do histórico de vários repositórios.

    Um dia de trabalho quase nunca cabe num repositório só: mexe-se na
    biblioteca, no CLI que a consome e no app que a expõe. Este comando lê todos
    de uma vez, agrupa por data e escreve **um relatório por dia**, com hora e
    duração por projeto — nunca só a data.

    É idempotente pela data: dia que já tem relatório é **complementado** (o
    corpo novo entra abaixo do que já estava), nunca sobrescrito. As
    propriedades de um relatório existente ficam intactas, porque costumam
    descrever, em prosa, o mesmo dia com mais contexto do que qualquer log.
    """

    database_id = _id_notion(args.database, "--database")
    repositorios = [
        svc_historico.Repositorio.de_par(nome, caminho)
        for nome, caminho in _pares_chave_valor(args.repo, "--repo").items()
    ]
    # Varredura: listar repositório à mão só acha o que já se lembra, e o dia de
    # trabalho esquecido, por definição, não está nessa lista.
    #
    # A deduplicação é pelo CAMINHO RESOLVIDO, nunca pelo nome: o objetivo de
    # `--repo` é justamente dar um nome de produto diferente do nome da pasta,
    # então comparar nomes deixa o mesmo repositório entrar duas vezes e o dia
    # sai com a mesma lista de commits repetida sob dois títulos.
    ja_incluidos = {Path(r.caminho).resolve() for r in repositorios}
    for raiz in args.descobrir or []:
        for encontrado in svc_historico.descobrir_repositorios(raiz):
            caminho = Path(encontrado.caminho).resolve()
            if caminho not in ja_incluidos:
                ja_incluidos.add(caminho)
                repositorios.append(encontrado)
    if not repositorios:
        raise CLIError(
            "Informe ao menos um repositório: "
            '--repo "Nome do projeto=/caminho/do/repo" ou --descobrir /pasta/raiz.'
        )

    dias = svc_historico.consolidar_dias(
        repositorios,
        desde=_normalizar_texto(args.desde) or "",
        ate=_normalizar_texto(args.ate) or "",
        autor=_normalizar_texto(args.autor) or "",
        com_estatisticas=not args.sem_estatisticas,
    )

    previa = [
        {
            "data": dia.data,
            "commits": dia.total_commits,
            "projetos": list(dia.repositorios),
            "resumo": dia.resumo(),
        }
        for dia in dias
    ]

    if args.dry_run:
        return {
            "dry_run": True,
            "dias": len(dias),
            "commits": sum(dia.total_commits for dia in dias),
            "previa": previa,
        }

    area = _normalizar_texto(args.area)
    relatorios = []
    for dia in dias:
        propriedades: dict[str, Any] = {
            "Resumo": starter_properties.rich_text(dia.resumo()),
            "O que fiz": starter_properties.rich_text(dia.o_que_fiz()),
        }
        if area:
            propriedades["Área"] = starter_properties.select(area)
        if args.status:
            propriedades["Status"] = starter_properties.status(args.status)
        relatorios.append(
            svc_relatorios.RelatorioDiario(
                data=dia.data,
                corpo_markdown=svc_historico.corpo_markdown(dia),
                propriedades=propriedades,
            )
        )

    resultado = svc_relatorios.publicar_relatorios(
        database_id, relatorios, cliente=client_factory()
    )
    return {
        "dias": len(resultado.relatorios),
        "criadas": resultado.criadas,
        "complementadas": resultado.complementadas,
        "paginas": [
            {"data": r.data, "acao": r.acao, "id": r.page_id, "blocos": r.blocos_escritos}
            for r in resultado.relatorios
        ],
    }


#: Acima disto, uma coluna de resumo parou de ser resumo. Não é um limite
#: rígido do Notion — é o ponto em que vale avisar em vez de deixar passar
#: quieto. Medido em 09/09/2026: mais de um agente (este incluído) despejou o
#: relato do dia inteiro na coluna "O que fiz" (até 7 mil caracteres numa
#: linha só) e deixou o corpo da página vazio — exatamente o que este comando
#: existe para não deixar acontecer de novo.
_LIMIAR_PROPRIEDADE_CURTA = 400

#: (nome da flag exibido no aviso, nome da coluna no Notion, atributo em ``args``)
_COLUNAS_RESUMO_RELATORIO = (
    ("--resumo", "Resumo", "resumo"),
    ("--o-que-fiz", "O que fiz", "o_que_fiz"),
    ("--bloqueios", "Bloqueios", "bloqueios"),
    ("--proximos-passos", "Próximos passos", "proximos_passos"),
)


def cmd_relatorio_do_dia(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Cria ou complementa a linha do dia em uma database de Relatórios diários.

    Existe para fechar, em código, o que a instrução em prosa ("preencha as
    colunas E o corpo") deixava ambíguo na prática: ``--corpo`` é o único
    lugar para o relato completo, em Markdown; as colunas (``--resumo``,
    ``--o-que-fiz``, ``--bloqueios``, ``--proximos-passos``) são sempre um
    resumo curto. O comando não impede um resumo comprido — algumas colunas
    legitimamente precisam de mais espaço —, mas avisa quando uma passa de
    ``_LIMIAR_PROPRIEDADE_CURTA`` caracteres, porque essa é a marca de que o
    relato foi parar no lugar errado.

    Idempotente pela data, via
    :func:`felixo_notion_mcp.services.relatorios_diarios.publicar_relatorios`: dia
    que já existe é complementado (o corpo novo entra depois do que já
    estava), nunca sobrescrito; as propriedades de um dia existente ficam como
    estão, porque costumam descrever o trabalho de outro projeto no mesmo dia.
    """

    database_id = _id_notion(args.database, "--database")
    data = _normalizar_texto(args.data) or date.today().isoformat()
    corpo = (
        _markdown_da_entrada(args.corpo, _argumento_arquivo_md(args), campo="--corpo") or ""
    )

    if not corpo and not args.permitir_corpo_vazio:
        raise CLIError(
            "--corpo está vazio. O relato completo do dia vai no corpo da página, "
            "nunca numa propriedade — se não há mesmo nada a registrar hoje além "
            "das colunas, use --permitir-corpo-vazio."
        )

    avisos: list[str] = []
    propriedades: dict[str, Any] = {}
    for flag, coluna, atributo in _COLUNAS_RESUMO_RELATORIO:
        texto = _normalizar_texto(getattr(args, atributo))
        if texto is None:
            continue
        if len(texto) > _LIMIAR_PROPRIEDADE_CURTA:
            avisos.append(
                f"{flag} tem {len(texto)} caracteres — isso parece relato, não "
                f"resumo. Considere mover o texto para --corpo e deixar {flag} "
                "só com o essencial escaneável."
            )
        propriedades[coluna] = starter_properties.rich_text(texto)
    if args.status:
        propriedades["Status"] = starter_properties.status(args.status)
    if args.area:
        propriedades["Área"] = starter_properties.select(args.area)

    relatorio = svc_relatorios.RelatorioDiario(
        data=data, corpo_markdown=corpo, propriedades=propriedades
    )
    resultado = svc_relatorios.publicar_relatorios(
        database_id, [relatorio], cliente=client_factory()
    )
    r = resultado.relatorios[0]
    saida: dict[str, Any] = {
        "data": r.data,
        "id": r.page_id,
        "acao": r.acao,
        "blocos_escritos": r.blocos_escritos,
        "url": r.url,
    }
    if avisos:
        saida["avisos"] = avisos
    return saida


def cmd_buscar(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    return svc_conteudo.buscar(_normalizar_texto(args.query), cliente=client_factory())


def cmd_clonar_database(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    return svc_clonagem.clonar_database(
        database_id,
        titulo=_normalizar_texto(args.titulo) or None,
        pagina_destino=_id_opcional(args.pagina, "--pagina"),
        com_linhas=args.com_linhas,
        relacoes=args.relacoes,
        cliente=client_factory(),
    )


def cmd_criar_subpagina(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    pagina_pai_id = _id_notion(args.pagina_pai_id, "pagina_pai_id")
    titulo = _texto_obrigatorio(args.titulo, "titulo")
    criada = svc_estrutura.criar_subpagina(
        pagina_pai_id,
        titulo,
        markdown=_markdown_da_entrada(
            args.conteudo, _argumento_arquivo_md(args), campo="--conteudo"
        ),
        cliente=client_factory(),
    )
    return {"id": criada.get("id"), "url": criada.get("url"), "titulo": titulo}


def cmd_inspecionar_estrutura(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    pagina_id = _id_notion(args.pagina_id, "pagina_id")
    arvore = svc_estrutura.inspecionar_estrutura(
        pagina_id,
        profundidade=args.profundidade,
        cliente=client_factory(),
    )
    return arvore.para_dict()


def cmd_clonar_estrutura(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    referencia_id = _id_notion(args.pagina_referencia_id, "pagina_referencia_id")
    destino_id = _id_notion(args.pagina_destino_id, "pagina_destino_id")
    resumo = svc_estrutura.clonar_estrutura_projeto(
        referencia_id,
        destino_id,
        cliente=client_factory(),
    )
    return {
        "subpaginas_criadas": resumo.subpaginas_criadas,
        "databases_clonados": resumo.databases_clonados,
        "ignorados": resumo.ignorados,
    }


def cmd_copiar_corpo(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Copia o corpo de uma página para o fim de outra, bloco a bloco.

    A regra (lista branca de tipos, remoção de ``null``, aninhamento em etapas,
    desfazer em falha) vive em ``felixo_notion_mcp.services.copia_corpo``.
    """

    origem = _id_notion(args.origem_id, "origem_id")
    destino = _id_notion(args.destino_id, "destino_id")
    copia = _servico_do_starter("copia_corpo", comando="copiar-corpo")
    resultado = copia.copiar_corpo(
        origem,
        destino,
        so_se_vazio=getattr(args, "so_se_vazio", False) is True,
        mesmo_com_database=getattr(args, "mesmo_com_database", False) is True,
        dry_run=getattr(args, "dry_run", False) is True,
        conferir=getattr(args, "conferir", False) is True,
        cliente=client_factory(),
    )
    return resultado.para_dict()


AVISO_MODELOS = (
    "A API do Notion lista e preenche modelos, mas não cria modelo nem escolhe o padrão: "
    "crie modelos em branco pela interface (Novo modelo, sem digitar nada) e defina o "
    "padrão por lá."
)


def _fonte_indefinida(erro: Any, comando: str) -> CLIError:
    """``FonteDeDadosIndefinidaError`` vira recusa com as fontes e o ``--fonte`` pronto."""

    primeira = erro.fontes[0][0] if erro.fontes else "<data_source_id>"
    return CLIError(
        str(erro),
        codigo="validacao",
        proximo_passo=f"{comando} --fonte {primeira}",
        detalhes={
            "database_id": erro.database_id,
            "data_sources": [{"id": fid, "nome": nome} for fid, nome in erro.fontes],
        },
    )


def cmd_modelos(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """``modelos listar|preencher``: modelos nativos (templates) de um database.

    A regra (vazio = "New page" sem corpo, idempotência, validação das colunas
    antes de escrever) vive em ``felixo_notion_mcp.services.modelos``.
    """

    servico = _servico_do_starter("modelos", comando="modelos")
    from felixo_notion_mcp.core.exceptions import FonteDeDadosIndefinidaError

    database_id = _id_notion(args.database_id, "database_id")
    fonte = _id_opcional(getattr(args, "fonte", None), "--fonte")
    comando = f"notion-tasks modelos {args.acao_modelos} {database_id}"
    try:
        if args.acao_modelos == "listar":
            modelos = servico.listar_modelos(
                database_id, data_source_id=fonte, cliente=client_factory()
            )
            return {
                "database_id": database_id,
                "total": len(modelos),
                "inventario": [
        "notion-tasks --json inventario --saida inventario.json",
        "notion-tasks --json inventario --saida databases.json --filtro database",
    ],
    "baixar-corpos": [
        "notion-tasks --json baixar-corpos inventario.json --destino corpos/ "
        '--ignorar-caminho "Arquivo" --priorizar "artigo|post|pauta"',
        "notion-tasks --json baixar-corpos inventario.json --destino corpos/ "
        "--somente-database <database_id> --limite 200",
    ],
    "buscar-conteudo": [
        'notion-tasks --json buscar-conteudo corpos/ "publica[cç][aã]o|artigo"',
        'notion-tasks --json buscar-conteudo corpos/ "\\bTODO\\b" --diferenciar-caixa '
        "--limite 20",
    ],
    "modelos": [m.para_dict() for m in modelos],
                "aviso": AVISO_MODELOS,
            }
        itens = servico.carregar_manifesto(Path(_texto_obrigatorio(args.manifesto, "--manifesto")))
        resultado = servico.preencher_modelos(
            database_id,
            itens,
            data_source_id=fonte,
            dry_run=getattr(args, "dry_run", False) is True,
            cliente=client_factory(),
        )
    except servico.ManifestoInvalidoError as erro:
        raise CLIError(
            str(erro), codigo="validacao", detalhes={"problemas": list(erro.problemas)}
        ) from erro
    except FonteDeDadosIndefinidaError as erro:
        raise _fonte_indefinida(erro, comando) from erro
    dados = {"database_id": database_id, **resultado.para_dict(), "aviso": AVISO_MODELOS}
    return dados


def cmd_inventario(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Grava o inventário plano do workspace (datas, caminho, colunas) em JSON."""

    servico = _servico_do_starter("inventario_workspace", comando="inventario")
    saida = Path(_texto_obrigatorio(args.saida, "--saida"))
    inicio = time.monotonic()
    registros = servico.varrer_workspace(
        filtro=getattr(args, "filtro", None), cliente=client_factory()
    )
    servico.salvar_inventario(registros, saida)
    return {
        "saida": str(saida.resolve()),
        **servico.resumir(registros),
        "segundos": round(time.monotonic() - inicio, 1),
        "proximo_passo": f"notion-tasks baixar-corpos {saida} --destino <pasta>",
    }


def _progresso_stderr(rotulo: str, a_cada: int) -> Callable[[int, int], None]:
    """Mostra ``feitas/total`` no stderr a cada ``a_cada`` itens (stdout fica JSON)."""

    def mostrar(feitas: int, total: int) -> None:
        if a_cada > 0 and (feitas % a_cada == 0 or feitas == total):
            print(f"[{rotulo}] {feitas}/{total}", file=sys.stderr, flush=True)

    return mostrar


def cmd_baixar_corpos(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Baixa o Markdown das páginas do inventário, retomável e priorizado."""

    inventario = _servico_do_starter("inventario_workspace", comando="baixar-corpos")
    corpos = _servico_do_starter("corpos", comando="baixar-corpos")
    registros = inventario.carregar_inventario(
        Path(_texto_obrigatorio(args.inventario, "inventario"))
    )
    priorizar = None
    if _normalizar_texto(getattr(args, "priorizar", None)):
        try:
            priorizar = re.compile(args.priorizar, re.IGNORECASE)
        except re.error as exc:
            raise CLIError(f"--priorizar não é uma expressão regular válida: {exc}") from exc
    somente = [_id_notion(d, "--somente-database") for d in args.somente_database or []]
    ignorar = [_id_notion(d, "--ignorar-database") for d in args.ignorar_database or []]
    paginas = corpos.selecionar_paginas(
        registros,
        ignorar_caminhos=args.ignorar_caminho or [],
        ignorar_databases=ignorar,
        somente_databases=somente or None,
        incluir_arquivados=getattr(args, "incluir_arquivados", False) is True,
    )
    paginas = corpos.ordenar_por_prioridade(paginas, priorizar=priorizar)
    resultado = corpos.baixar_corpos(
        paginas,
        Path(_texto_obrigatorio(args.destino, "--destino")),
        trabalhadores=args.trabalhadores,
        limite=args.limite,
        ao_progredir=_progresso_stderr("baixar-corpos", args.progresso_a_cada),
        cliente=client_factory(),
    )
    dados = resultado.para_dict()
    if resultado.adiados or resultado.falhas:
        dados["proximo_passo"] = "rode o mesmo comando de novo: o que já baixou é pulado"
    dados["proximo_passo_busca"] = (
        f'notion-tasks buscar-conteudo {resultado.destino} "<expressão>"'
    )
    return dados


def cmd_buscar_conteudo(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Procura uma expressão regular no texto completo baixado por ``baixar-corpos``."""

    busca = _servico_do_starter("busca_conteudo", comando="buscar-conteudo")
    ocorrencias = busca.buscar_no_conteudo(
        Path(_texto_obrigatorio(args.pasta, "pasta")),
        args.expressao,
        ignorar_acentos=not getattr(args, "com_acentos", False),
        ignorar_caixa=not getattr(args, "diferenciar_caixa", False),
        contexto=args.contexto,
        max_trechos=args.max_trechos,
        limite=args.limite,
    )
    return {
        "pasta": args.pasta,
        "expressao": args.expressao,
        "total_paginas": len(ocorrencias),
        "ocorrencias": [o.para_dict() for o in ocorrencias],
    }


def cmd_montar_estrutura_projeto(
    args: argparse.Namespace, *, client_factory: ClientFactory
) -> Any:
    pagina_id = _id_notion(args.pagina_id, "pagina_id")
    resumo = svc_estrutura.montar_estrutura_projeto(pagina_id, cliente=client_factory())
    return {
        "subpaginas_criadas": resumo.subpaginas_criadas,
        "databases_criados": resumo.databases_criados,
    }


def cmd_reordenar_bloco(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    pagina_id = _id_notion(args.pagina_id, "pagina_id")
    bloco_id = _id_notion(args.bloco_id, "bloco_id", bloco=True)

    apos = _id_opcional(args.apos, "--apos", bloco=True)
    if bool(apos) == bool(args.inicio):
        raise CLIError("Informe exatamente um entre --apos <bloco_id> e --inicio.")

    resultado = svc_reordenacao.reordenar_bloco(
        pagina_id,
        bloco_id,
        apos_bloco_id=apos,
        inicio=args.inicio,
        # Sem --dir-backup a biblioteca usa a pasta de estado do usuário (nunca
        # o diretório corrente, que pode ser um repositório git).
        diretorio_backup=_normalizar_texto(getattr(args, "dir_backup", None)),
        cliente=client_factory(),
    )

    return {
        "bloco_id_antigo": resultado.bloco_id_antigo,
        "bloco_id_novo": resultado.bloco_id_novo,
        "tipo": resultado.tipo,
        "backup_path": resultado.backup_path,
        "id_mudou": resultado.id_mudou,
    }


def cmd_garantir_coluna(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    nome_coluna = _texto_obrigatorio(args.nome_coluna, "nome_coluna")
    definicao = starter_properties.schema_propriedade(
        args.tipo,
        relacionar_com=_id_opcional(getattr(args, "relacionar_com", None), "--relacionar-com"),
    )
    opcoes = _lista_csv(getattr(args, "opcoes", None)) or []
    if opcoes:
        tipo_api = next(iter(definicao))
        if tipo_api not in ("select", "multi_select"):
            raise CLIError("--opcoes só vale para colunas select e multi_select.")
        # Criar as opções junto com a coluna evita a corrida de gravações paralelas
        # criando a mesma opção ao mesmo tempo.
        definicao = {tipo_api: {"options": [{"name": nome} for nome in dict.fromkeys(opcoes)]}}

    criada = svc_schema.garantir_coluna(
        database_id, nome_coluna, definicao, cliente=client_factory()
    )
    return {"database_id": database_id, "coluna": nome_coluna, "tipo": args.tipo, "criada": criada}


def cmd_renomear_coluna(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    nome_atual = _texto_obrigatorio(args.nome_atual, "nome_atual")
    novo_nome = _texto_obrigatorio(args.novo_nome, "novo_nome")

    svc_schema.renomear_coluna(database_id, nome_atual, novo_nome, cliente=client_factory())
    return {"database_id": database_id, "coluna_antiga": nome_atual, "coluna_nova": novo_nome}


def cmd_remover_coluna(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Remove uma coluna do schema (destrutivo: os valores somem de todas as linhas)."""

    database_id = _id_notion(args.database_id, "database_id")
    coluna = _texto_obrigatorio(args.coluna, "coluna")
    if not getattr(args, "sim", False):
        raise CLIError(
            f"remover-coluna apaga a coluna '{coluna}' e os valores dela em TODAS as linhas "
            "do database. Confira com 'schema' e repita com --sim.",
            proximo_passo=f'notion-tasks remover-coluna {database_id} "{coluna}" --sim',
        )
    schema_starter = _servico_do_starter("schema", comando="remover-coluna")
    remover = getattr(schema_starter, "remover_coluna", None)
    if remover is None:
        raise CLIError(
            "'remover-coluna' precisa de felixo_notion_mcp.services.schema.remover_coluna, "
            "que não foi encontrada. No pacote único isso indica uma instalação "
            "incompleta ou quebrada.",
            codigo="configuracao",
            proximo_passo=PROXIMO_PASSO_INSTALACAO_QUEBRADA,
        )
    return remover(database_id, coluna, cliente=client_factory())


def _resumo_inventario_dict(resumo: Any) -> dict[str, Any]:
    return {
        "repos_encontrados": resumo.repos_encontrados,
        "paginas_criadas": resumo.paginas_criadas,
        "paginas_atualizadas": resumo.paginas_atualizadas,
        "paginas_puladas": resumo.paginas_puladas,
        "readmes_escritos": resumo.readmes_escritos,
        "readmes_atualizados": resumo.readmes_atualizados,
        "erros": resumo.erros,
    }


def cmd_atualizar_github(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Re-sincroniza o database GITHUB: repos novos, propriedades e README mudado."""

    contas = _lista_csv(args.contas) or _lista_csv([os.environ.get("GITHUB_CONTAS", "")])
    if not contas:
        raise CLIError(
            "Informe as contas com --contas (CSV) ou defina GITHUB_CONTAS no ambiente."
        )
    database_id = _id_opcional(args.database, "--database") or os.environ.get(
        "NOTION_DATABASE_ID", ""
    ).strip()
    if not database_id:
        raise CLIError("Informe o database com --database ou defina NOTION_DATABASE_ID.")

    resumo = svc_inventario.atualizar_repos(
        contas,
        database_id,
        github_client=GitHubClient(),
        notion_client=client_factory(),
        sincronizar_readme=not args.sem_readme,
        ignorar_arquivados=args.sem_arquivados,
        apenas_mudancas=args.apenas_mudancas,
    )
    return _resumo_inventario_dict(resumo)


def cmd_exportar_docx(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_opcional(args.database, "--database") or os.environ.get(
        "NOTION_REPORTS_DATABASE_ID", ""
    ).strip()
    if not database_id:
        database_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not database_id:
        raise CLIError(
            "Informe --database ou configure NOTION_REPORTS_DATABASE_ID/NOTION_DATABASE_ID."
        )
    return svc_relatorios_docx.exportar_relatorios_docx(
        database_id=database_id,
        data_inicio=_texto_obrigatorio(args.de, "de"),
        data_fim=_texto_obrigatorio(args.ate, "ate"),
        saida=_texto_obrigatorio(args.saida, "saida"),
        campo_data=_texto_obrigatorio(args.campo_data, "campo_data"),
        cliente=client_factory(),
    )


def cmd_criar_database(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    pagina_id = _id_notion(args.pagina_id, "pagina_id")
    titulo = _texto_obrigatorio(args.titulo, "titulo")
    tipos = _pares_chave_valor(args.prop, "--prop")

    propriedades: dict[str, dict[str, object]] = {}
    for nome, tipo in tipos.items():
        propriedades[nome] = starter_properties.schema_propriedade(tipo)
    if not any("title" in fragmento for fragmento in propriedades.values()):
        propriedades["Nome"] = starter_properties.schema_propriedade("titulo")

    resultado = client_factory().criar_database(
        pagina_id,
        titulo,
        propriedades,
        is_inline=args.inline,
        icone=_normalizar_texto(args.icone),
        descricao=_normalizar_texto(args.descricao),
        prefixo_id=_normalizar_texto(args.prefixo_id),
    )
    return {
        "id": resultado.get("id", ""),
        "titulo": titulo,
        "url": resultado.get("url"),
        "propriedades": sorted(propriedades),
    }


def cmd_importar_planilha(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    caminho = _texto_obrigatorio(args.caminho, "caminho")
    fonte = svc_ingestao.FontePlanilha(
        caminho,
        aba=_normalizar_texto(args.aba),
        coluna_titulo=_normalizar_texto(args.coluna_titulo),
        tipos=_pares_chave_valor(args.tipo, "--tipo"),
        renomear=_pares_chave_valor(args.renomear, "--renomear"),
        chave=_normalizar_texto(getattr(args, "chave", None)),
    )
    resultado = svc_ingestao.ingerir(
        fonte,
        client=client_factory(),
        database_id=database_id,
        simular=getattr(args, "dry_run", False) is True,
    )
    return {
        "database_id": database_id,
        "arquivo": caminho,
        "criados": resultado.criados,
        "atualizados": resultado.atualizados,
        "erros": resultado.erros,
        "itens_processados": resultado.itens_processados,
        # Herança do tempo em que a CLI e o ``notion-starter`` tinham versões separadas:
        # a borda aceitava um resultado sem estes campos. No pacote único eles sempre
        # existem; os ``getattr`` saem junto com a simplificação da etapa 2.
        "falhas": getattr(resultado, "falhas", []),
        "conflitos": getattr(resultado, "conflitos", []),
        "simulado": getattr(resultado, "simulado", False),
    }


def cmd_anexar_arquivo(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    return svc_anexos.anexar_arquivo(
        _id_notion(args.page_id, "page_id"),
        _texto_obrigatorio(args.caminho, "caminho"),
        propriedade=_normalizar_texto(args.propriedade) or "Arquivos e mídia",
        substituir=args.substituir,
        cliente=client_factory(),
    )


def cmd_aparencia(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    return svc_aparencia.definir_aparencia(
        _id_notion(args.page_id, "page_id"),
        icone=_normalizar_texto(args.icone),
        capa=_normalizar_texto(args.capa),
        substituir=args.substituir,
        cliente=client_factory(),
    )


def cmd_mover_pagina(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    """Move uma página prevendo antes o que muda nas colunas, e confere o pai.

    A regra (previsão, recusa de perda, endpoint ``/move`` e releitura) vive em
    ``felixo_notion_mcp.services.movimentacao``; aqui só se traduzem as recusas
    para o envelope, com o comando para aceitar a perda ou escolher a fonte.
    """

    page_id = _id_notion(args.page_id, "page_id")
    destino = _id_notion(args.novo_pai_id, "novo_pai_id")
    movimentacao = _servico_do_starter("movimentacao", comando="mover-pagina")
    from felixo_notion_mcp.core.exceptions import FonteDeDadosIndefinidaError

    dry_run = getattr(args, "dry_run", False) is True
    try:
        resultado = movimentacao.mover_pagina(
            page_id,
            destino,
            tipo_pai=args.tipo_pai,
            dry_run=dry_run,
            aceitar_perdas=getattr(args, "aceitar_perdas", False) is True,
            cliente=client_factory(),
        )
    except movimentacao.MovimentoComPerdasError as erro:
        raise CLIError(
            str(erro),
            codigo="validacao",
            proximo_passo=f"notion-tasks mover-pagina {page_id} {destino} "
            f"--tipo-pai {args.tipo_pai} --aceitar-perdas",
            detalhes=erro.previsao.para_dict(),
        ) from erro
    except FonteDeDadosIndefinidaError as erro:
        primeira = erro.fontes[0][0] if erro.fontes else "<data_source_id>"
        raise CLIError(
            str(erro),
            codigo="validacao",
            proximo_passo=f"notion-tasks mover-pagina {page_id} {primeira} "
            "--tipo-pai data_source_id",
            detalhes={
                "database_id": erro.database_id,
                "data_sources": [{"id": fid, "nome": nome} for fid, nome in erro.fontes],
            },
        ) from erro

    dados = resultado.para_dict()
    criadas = [c["nome"] for c in dados["colunas_acrescentadas_no_destino"]]
    if dry_run:
        aviso = "Simulação: nada foi movido."
    elif criadas:
        aviso = (
            f"Movimento conferido. O Notion criou no destino as colunas {', '.join(criadas)}; "
            "se não as quiser lá, remova-as do schema do destino."
        )
    else:
        aviso = "Movimento conferido: o pai relido é o destino pedido."
    return {"id": page_id, "novo_pai": destino, "dry_run": dry_run, **dados, "aviso": aviso}


def cmd_mover_database(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    destino = _id_notion(args.novo_pai_id, "novo_pai_id")
    client_factory().mover_database(database_id, destino)
    return {"id": database_id, "novo_pai": destino}


def cmd_renomear_database(args: argparse.Namespace, *, client_factory: ClientFactory) -> Any:
    database_id = _id_notion(args.database_id, "database_id")
    novo_titulo = _texto_obrigatorio(args.novo_titulo, "novo_titulo")
    client_factory().renomear_database(database_id, novo_titulo)
    return {"id": database_id, "titulo": novo_titulo}


def cmd_perfis(args: argparse.Namespace) -> Any:
    acao = args.acao_perfil
    if acao == "listar":
        return perfis_workspace.carregar_store().publico()
    if acao == "adicionar":
        perfil = perfis_workspace.adicionar_perfil(
            alias=args.alias,
            token=args.token,
            database_id=_id_opcional(args.database, "--database"),
            nome=_normalizar_texto(args.nome),
            descricao=_normalizar_texto(args.descricao),
            ativar=args.ativar,
            sobrescrever=args.sobrescrever,
        )
        ativo = perfis_workspace.carregar_store().ativo == perfil.alias
        return {
            "acao": "adicionado",
            "perfil": perfil.publico(ativo=ativo),
            "arquivo": str(perfis_workspace.ARQUIVO_PADRAO),
        }
    if acao == "usar":
        perfil = perfis_workspace.selecionar_perfil(args.alias)
        perfis_workspace.aplicar_perfil(perfil.alias)
        return {
            "acao": "selecionado",
            "perfil": perfil.publico(ativo=True),
            "ambiente": {
                "NOTION_PROFILE": perfil.alias,
                "NOTION_TOKEN": "definido",
                "NOTION_DATABASE_ID": "definido" if perfil.database_id else "ausente",
            },
        }
    if acao == "mostrar":
        perfil = perfis_workspace.resolver_perfil(args.alias)
        if perfil is None:
            raise CLIError("Nenhum perfil ativo. Use 'perfis listar' ou 'perfis usar <alias>'.")
        store = perfis_workspace.carregar_store()
        return perfil.publico(ativo=perfil.alias == store.ativo)
    if acao == "remover":
        perfil = perfis_workspace.remover_perfil(args.alias, confirmar=args.sim)
        return {"acao": "removido", "perfil": perfil.publico(ativo=False)}
    raise CLIError(f"Ação de perfis desconhecida: {acao}")


#: Exemplos de uso por comando, mostrados pelo ``guia``. Texto curto e copiável.
EXEMPLOS_GUIA: dict[str, list[str]] = {
    "listar": ['notion-tasks --json listar --status "Entrada"'],
    "ler": ["notion-tasks --json ler <task_id>"],
    "criar": [
        'notion-tasks --json criar "Nova tarefa" --status "Entrada" --duracao "Dias"',
        'notion-tasks --json criar "Nova tarefa" --status "Entrada" '
        '--set "Prioridade=Alta" --conteudo $\'## Contexto\\n\\nDetalhes...\'',
        'notion-tasks --json criar "Projeto/contexto — descrição" '
        '--set "URL de referência=https://github.com/owner/repo/tree/main" --strict',
        'notion-tasks --json criar --arquivo novas-linhas.json --strict --dry-run',
        "notion-tasks --json criar --arquivo novas-linhas.json --progresso-a-cada 25",
        'notion-tasks --json criar "Ideia de artigo" --database <database_id> '
        '--set "Etapa=Ideia" --conteudo "## Rascunho"',
    ],
    "editar": ['notion-tasks --json editar <task_id> --status "Concluída"'],
    "mover": ['notion-tasks --json mover <task_id> "Concluída"'],
    "concluir": ['notion-tasks --json concluir <task_id> "Concluída"'],
    "opcoes": ["notion-tasks --json opcoes"],
    "databases": ["notion-tasks --json databases"],
    "database-atual": ["notion-tasks --json database-atual"],
    "escolher-database": ["notion-tasks --json escolher-database <database_id>"],
    "normalizar-nomes": ["notion-tasks --json normalizar-nomes --dry-run"],
    "mapear": ["notion-tasks --json mapear"],
    "buscar": ['notion-tasks --json buscar "nota de reunião"'],
    "conteudo": ["notion-tasks --json conteudo <page_id>"],
    "exemplo": ["notion-tasks --json exemplo --n 3"],
    "linhas": [
        "notion-tasks --json linhas <database_id>",
        "notion-tasks --json linhas <database_id> --completo",
    ],
    "editar-linha": [
        'notion-tasks --json editar-linha <page_id> --set "Status=Feito"',
        'notion-tasks --json editar-linha <page_id> --set "Prazo=2026-07-10" '
        '--set "Tags=urgente,casa"',
        'notion-tasks --json editar-linha <page_id> --append '
        '"Resumo=\\n\\nNova observação ao final"',
        'notion-tasks --json editar-linha <page_id> '
        '--set "URL de referência=https://github.com/owner/repo" --strict',
        "notion-tasks --json editar-linha --arquivo atualizacoes.json --strict --dry-run",
        "notion-tasks --json editar-linha --arquivo atualizacoes.json "
        "--progresso-a-cada 25",
    ],
    "blocos": [
        "notion-tasks --json blocos <page_id>",
        "notion-tasks --json blocos <page_id> --metadados --completo",
        'notion-tasks --json blocos <page_id> --recursivo --contendo "trecho lido"',
    ],
    "ler-bloco": ["notion-tasks --json ler-bloco <block_id>"],
    "escrever": [
        "notion-tasks --json escrever <page_id> $'# Título\\n\\nTexto'",
        "notion-tasks --json escrever <page_id> $'- item inserido' --apos <block_id>",
        "notion-tasks --json escrever <page_id> $'> Aviso no topo' --inicio",
        "notion-tasks --json escrever <page_id> - < nota.md  # Markdown pelo stdin",
        "notion-tasks --json escrever <page_id> --arquivo-md nota.md --substituir",
        "notion-tasks --json escrever <page_id> $'# Só isto' --substituir",
        "notion-tasks --json escrever <page_id> $'# Zera mesmo' --substituir --apagar-tudo",
        "# página que contém database: trabalhe nas LINHAS, não escreva solto nela",
        "notion-tasks --json linhas <database_id>",
    ],
    "editar-bloco": [
        'notion-tasks --json editar-bloco <block_id> "Texto novo do parágrafo"',
        'notion-tasks --json editar-bloco <block_id> --trocar "20:12" --por "20:15"',
        'notion-tasks --json editar-bloco <block_id> --trocar "v1" --por "v2" --todas',
        "notion-tasks --json editar-bloco --arquivo edicoes.json --progresso-a-cada 25",
    ],
    "apagar-bloco": [
        "notion-tasks --json apagar-bloco <block_id> --sim",
        "notion-tasks --json apagar-bloco <id1> <id2> <id3> --sim",
        "notion-tasks --json apagar-bloco <child_page_id> --sim --forcar-tipos-arriscados",
    ],
    "limpar": [
        "notion-tasks --json limpar <page_id> --sim",
        "notion-tasks --json limpar <page_id> --sim --apagar-tudo",
    ],
    "restaurar-bloco": [
        "notion-tasks --json restaurar-bloco <block_id>",
        "notion-tasks --json restaurar-bloco <id1> <id2> <id3>  # o 'desfazer' do limpar",
    ],
    "relatorios-do-git": [
        'notion-tasks --json relatorios-do-git --database <id> --dry-run '
        '--descobrir ~/Programacao/Github/Repositorios',
        'notion-tasks --json relatorios-do-git --database <id> --dry-run '
        '--repo "Felixo AI Core=/caminho/Felixo-AI-Core"',
        'notion-tasks --json relatorios-do-git --database <id> --desde 2026-08-01 '
        '--repo "App=/caminho/app" --repo "Lib=/caminho/lib" --area Trabalho',
    ],
    "relatorio-do-dia": [
        'notion-tasks --json relatorio-do-dia --database <id> '
        '--resumo "Corrigi o bug X e entreguei a feature Y" '
        "--arquivo-md relato-do-dia.md",
        'notion-tasks --json relatorio-do-dia --database <id> --data 2026-09-08 '
        '--resumo "..." --o-que-fiz "..." --bloqueios "..." --proximos-passos "..." '
        "--status Concluído --corpo - < relato.md",
    ],
    "schema": [
        "notion-tasks --json schema <database_id>",
        "notion-tasks --json schema <database_id> --editaveis",
    ],
    "relacionar": [
        'notion-tasks --json relacionar <page_a> <page_b> --coluna "Subtarefas relacionadas"',
        'notion-tasks --json relacionar <page_a> <page_b> --coluna "Depende de" --desfazer',
        'notion-tasks --json relacionar --coluna "Subtarefas relacionadas" '
        '--par a1:b1 --par a2:b2',
        'notion-tasks --json relacionar --coluna "Subtarefas relacionadas" '
        '--arquivo pares.json',
    ],
    "clonar-database": [
        "notion-tasks --json clonar-database <database_id>",
        'notion-tasks --json clonar-database <database_id> --titulo "Cópia" --com-linhas',
    ],
    "criar-subpagina": [
        'notion-tasks --json criar-subpagina <pagina_pai_id> "Estado atual"',
        'notion-tasks --json criar-subpagina <pagina_pai_id> "README" --conteudo "# Título"',
    ],
    "inspecionar-estrutura": [
        "notion-tasks --json inspecionar-estrutura <pagina_id>",
        "notion-tasks --json inspecionar-estrutura <pagina_id> --profundidade 1",
    ],
    "modelos": [
        "notion-tasks --json modelos listar <database_id>",
        "notion-tasks --json modelos preencher <database_id> --manifesto modelos.json "
        "--dry-run",
        "notion-tasks --json modelos preencher <database_id> --manifesto modelos.json "
        "--fonte <data_source_id>",
    ],
    "copiar-corpo": [
        "notion-tasks --json copiar-corpo <pagina_origem_id> <pagina_destino_id> --dry-run",
        "notion-tasks --json copiar-corpo <pagina_origem_id> <pagina_destino_id> "
        "--so-se-vazio --conferir",
    ],
    "clonar-estrutura": [
        "notion-tasks --json clonar-estrutura <pagina_referencia_id> <pagina_destino_id>",
    ],
    "montar-estrutura-projeto": [
        "notion-tasks --json montar-estrutura-projeto <pagina_id>",
    ],
    "reordenar-bloco": [
        "notion-tasks --json reordenar-bloco <pagina_id> <bloco_id> --apos <outro_bloco_id>",
        "notion-tasks --json reordenar-bloco <pagina_id> <bloco_id> --inicio",
        "notion-tasks --json reordenar-bloco <pagina_id> <bloco_id> --inicio "
        "--dir-backup ~/notion-backups",
    ],
    "garantir-coluna": [
        "notion-tasks --json garantir-coluna <database_id> Idioma select",
        "notion-tasks --json garantir-coluna <database_id> Observações texto",
        "notion-tasks --json garantir-coluna <database_id> Projeto relacao "
        "--relacionar-com <database_alvo_id>",
    ],
    "remover-coluna": [
        'notion-tasks --json remover-coluna <database_id> "Tema/Pilar" --sim',
    ],
    "renomear-coluna": [
        'notion-tasks --json renomear-coluna <database_id> "Related to X (Y)" "Bloqueia"',
    ],
    "atualizar-github": [
        "notion-tasks --json atualizar-github --contas conta-um,conta-dois",
        "notion-tasks --json atualizar-github --database <database_id> --sem-readme",
        "notion-tasks --json atualizar-github --contas conta-um --sem-arquivados",
        "notion-tasks --json atualizar-github --contas https://github.com/conta-um "
        "--apenas-mudancas",
    ],
    "exportar-docx": [
        "notion-tasks --json exportar-docx --de 2026-07-01 --ate 2026-07-06 --saida ./exports",
        "notion-tasks --json exportar-docx --database <database_id> --campo-data Data "
        "--de 2026-07-01 --ate 2026-07-06 --saida ./exports",
    ],
    "criar-database": [
        'notion-tasks --json criar-database <pagina_id> "Cadastro" '
        '--prop "Seguidores=numero" --prop "Plataforma=select" '
        '--prefixo-id DVIP --icone 📇 --descricao "Contas do projeto"',
    ],
    "importar-planilha": [
        "notion-tasks --json importar-planilha <database_id> contas.xlsx "
        '--aba Contas --tipo "Seguidores=numero" --tipo "Criada em=data"',
        "notion-tasks --json importar-planilha <database_id> contas.csv "
        '--renomear "Email=E-mail de acesso"',
        "notion-tasks --json importar-planilha <database_id> contas.csv --chave Email "
        "--dry-run",
    ],
    "aparencia": [
        "notion-tasks --json aparencia <page_id> --icone 📚 --capa https://exemplo.dev/capa.jpg",
        "notion-tasks --json aparencia <page_id> --icone icone.png --capa capa.png --substituir",
    ],
    "anexar-arquivo": [
        "notion-tasks --json anexar-arquivo <page_id> relatorio.docx",
        'notion-tasks --json anexar-arquivo <page_id> foto.png --propriedade "Anexos" '
        "--substituir",
    ],
    "mover-pagina": [
        "notion-tasks --json mover-pagina <page_id> <nova_pagina_pai_id>",
        "notion-tasks --json mover-pagina <page_id> <database_id> --tipo-pai database_id "
        "--dry-run",
        "notion-tasks --json mover-pagina <page_id> <database_id> --tipo-pai database_id "
        "--aceitar-perdas",
        "notion-tasks --json mover-pagina <page_id> <data_source_id> "
        "--tipo-pai data_source_id",
    ],
    "renomear-database": [
        'notion-tasks --json renomear-database <database_id> "Novo título"',
    ],
    "mover-database": [
        "notion-tasks --json mover-database <database_id> <nova_pagina_pai_id>",
    ],
    "perfis": [
        "notion-tasks --json perfis adicionar trabalho --token ntn_... "
        "--database <db_id> --ativar",
        "notion-tasks --json perfis listar",
        "notion-tasks --perfil trabalho --json listar",
    ],
    "guia": ["notion-tasks --json guia"],
}


def cmd_guia(args: argparse.Namespace) -> Any:
    """Auto-documenta a CLI: todos os comandos, o que fazem e um exemplo.

    Pensado para uma IA descobrir como operar a ferramenta sem tatear: é a
    primeira chamada a fazer. Reflete o próprio parser, então nunca desatualiza.
    """

    parser = construir_parser()
    subparsers = next(
        acao for acao in parser._subparsers._group_actions if hasattr(acao, "choices")
    )
    # O texto de ajuda de cada subcomando fica em ``_choices_actions`` (o ``help``
    # passado em ``add_parser``); lê de lá para o guia refletir o parser.
    ajudas = {acao.dest: (acao.help or "") for acao in subparsers._choices_actions}
    comandos = []
    for nome in subparsers.choices:
        comandos.append(
            {
                "comando": nome,
                "descricao": ajudas.get(nome, ""),
                "exemplos": EXEMPLOS_GUIA.get(nome, [f"notion-tasks {nome} --help"]),
            }
        )
    return {
        "ferramenta": "cli notion (mesmos services da API e do MCP)",
        "dica": (
            "Use estes comandos em vez de chamar a API do Notion na mão. "
            "Acrescente --json para saída estável: {ok: true, dados} ou {ok: false, "
            "erro: {codigo, mensagem, proximo_passo, http_status, notion_code, "
            "detalhes}}. Decida pelo 'codigo', não pelo texto. Sufixo '--help' "
            "em qualquer comando mostra os argumentos."
        ),
        "erros": {
            "codigos": list(CODIGOS_ERRO),
            "saida": {
                "0": "sucesso",
                "1": "falha da API, da rede, no meio de uma escrita ou interna",
                "2": "uso inválido ou recusa antes de escrever (nada mudou)",
            },
            "notas": [
                "escrita_salva: o Notion GRAVOU e não respondeu a tempo — NÃO repita; "
                "releia com 'blocos'/'conteudo' (detalhes.filhos_criados).",
                "escrita_parcial / limpeza_incompleta / reordenacao_incompleta: a "
                "escrita começou e parou; 'detalhes' diz o que foi gravado, apagado "
                "ou ficou pendente, e 'proximo_passo' diz como conferir ou desfazer.",
                "nao_encontrado: com perfil ativo, confira 'perfis listar' antes de "
                "suspeitar de compartilhamento.",
            ],
        },
        "fluxo_recomendado": [
            "REGRA DO LINK: ao receber um link ou ID do Notion, LEIA e entenda "
            "do que se trata ANTES de qualquer mudança ('conteudo <id>'; se for "
            "database, 'linhas <id>'). Se o alvo é um database, o trabalho é nas "
            "LINHAS: localize a linha certa e atualize-a — NUNCA ignore o "
            "database criando blocos soltos abaixo dele.",
            "REGRA DE LEITURA: propriedades e corpo são partes da MESMA página. "
            "Toda página deve começar a ser lida pelas propriedades (as colunas) "
            "e só depois pelo corpo — há páginas com mais informação nas "
            "propriedades do que no corpo. 'conteudo <page_id>' já devolve as "
            "duas partes, propriedades primeiro.",
            "REGRA: ao trabalhar numa página que é linha de um database, edite "
            "PRIMEIRO as propriedades (as colunas) e SÓ DEPOIS o conteúdo (o corpo).",
            "1. Propriedades (colunas: status, datas, seleções, relações…) → "
            "'editar-linha <page_id> --set \"Nome=valor\"'.",
            "Para muitas linhas, use 'criar --arquivo' ou 'editar-linha --arquivo': "
            "uma chamada processa o lote e relata cada entrada sem interromper as demais.",
            "2. Conteúdo (o corpo da nota, em blocos) → 'escrever <page_id> <markdown>'.",
            "Não pare no conteúdo esquecendo as propriedades: uma linha de database "
            "só fica completa quando as colunas também são preenchidas.",
            "ATENÇÃO: 'escrever' ANEXA ao final (não substitui). Repetir empilha "
            "conteúdo. Para TROCAR o corpo, use 'escrever ... --substituir'. Para "
            "INSERIR num ponto, 'escrever ... --apos <block_id>' ou '--inicio' (não "
            "use 'reordenar-bloco' para isso: ele apaga e recria).",
            "Para corrigir/reescrever uma página: veja os blocos com ID em "
            "'blocos <page_id>' ('--contendo \"trecho\"' acha o bloco pelo texto; "
            "'ler-bloco <id>' lê um só), então 'editar-bloco' por ID ('--trocar/--por' "
            "muda só um trecho sem perder cor, sublinhado nem menções) ou "
            "'apagar-bloco', ou 'escrever --substituir' para trocar o corpo. Tudo o "
            "que apaga devolve os IDs e o comando 'restaurar-bloco' em 'desfazer'.",
        ],
        "comandos": comandos,
    }


class _ErroDeArgumento(Exception):
    """Argumento inválido, levantado no lugar do ``sys.exit`` do argparse."""

    def __init__(self, parser: argparse.ArgumentParser, mensagem: str) -> None:
        super().__init__(mensagem)
        self.parser = parser
        self.mensagem = mensagem


class _ParserCLI(argparse.ArgumentParser):
    """``ArgumentParser`` cujo erro de uso pode virar envelope JSON.

    O ``error`` padrão imprime o uso no stderr e encerra o processo; a própria
    documentação do método diz que, ao sobrescrevê-lo, ele deve encerrar ou
    levantar uma exceção. Aqui levanta, e ``executar`` decide: com ``--json``,
    envelope ``uso_invalido``; sem, o mesmo texto e código 2 de sempre. Os
    subcomandos herdam a classe (``add_subparsers`` usa ``type(self)``).
    """

    def error(self, message: str) -> NoReturn:
        raise _ErroDeArgumento(self, message)


def construir_parser() -> argparse.ArgumentParser:
    parser = _ParserCLI(
        prog="notion-tasks",
        description="CLI para IA operar tarefas do Notion via services.",
    )
    parser.add_argument("--json", action="store_true", help="emite envelope JSON estável")
    parser.add_argument(
        "--perfil",
        help="alias de workspace salvo em 'perfis'; vence o perfil ativo nesta execução",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    listar = sub.add_parser("listar", help="lista tarefas")
    listar.add_argument("--status")
    listar.add_argument("--duracao")
    listar.add_argument("--area", action="append", help="ID de área; aceita CSV e repetição")

    ler = sub.add_parser("ler", help="lê uma tarefa pelo ID")
    ler.add_argument("task_id")

    criar = sub.add_parser(
        "criar",
        help="cria uma linha no database atual — ou em QUALQUER database com "
        "--database <id> (tarefas ou schema genérico)",
    )
    criar.add_argument("nome", nargs="?")
    criar.add_argument(
        "--database",
        metavar="DATABASE_ID",
        help="database de destino só desta chamada (ID ou link); sem ele, usa o "
        "database do perfil/NOTION_DATABASE_ID",
    )
    criar.add_argument("--status")
    criar.add_argument("--prazo")
    criar.add_argument("--duracao")
    criar.add_argument("--area", action="append", help="ID de área; aceita CSV e repetição")
    criar.add_argument(
        "--set",
        action="append",
        metavar="NOME=VALOR",
        help="preenche QUALQUER outra coluna já na criação (mesma sintaxe de "
        'editar-linha). Ex.: --set "Prioridade=Alta" --set "Projeto=<id1>,<id2>". '
        "Uma URL em 'URL de referência' resolve Projeto; --strict valida URL, "
        "relação e o título antes da escrita. Evita o vaivém criar → editar-linha",
    )
    criar.add_argument(
        "--conteudo",
        help="Markdown do corpo da linha, escrito logo após as propriedades — "
        "fecha criar + editar-linha + escrever numa chamada só; '-' lê do stdin",
    )
    criar.add_argument(
        "--arquivo-md",
        dest="arquivo_md",
        metavar="ARQUIVO",
        help="lê o Markdown do corpo deste arquivo (não confundir com --arquivo, o lote)",
    )
    criar.add_argument(
        "--arquivo",
        metavar="ARQUIVO",
        help="cria várias linhas a partir de JSON/CSV; JSON usa itens com nome e propriedades",
    )
    criar.add_argument(
        "--strict",
        action="store_true",
        help="bloqueia URL/Projeto/título inconsistentes antes de qualquer escrita",
    )
    criar.add_argument(
        "--dry-run",
        action="store_true",
        help="executa o preflight e mostra o plano sem criar nem editar no Notion",
    )
    criar.add_argument(
        "--progresso-a-cada",
        type=int,
        default=10,
        metavar="N",
        help="no modo --arquivo, informa progresso a cada N linhas (padrão: 10)",
    )

    editar = sub.add_parser("editar", help="edita uma tarefa")
    editar.add_argument("task_id")
    editar.add_argument("--nome")
    editar.add_argument("--status")
    editar.add_argument("--prazo")
    editar.add_argument("--duracao")
    editar.add_argument("--area", action="append", help="ID de área; aceita CSV e repetição")

    mover = sub.add_parser("mover", help="move tarefa para outro status")
    mover.add_argument("task_id")
    mover.add_argument("status")

    concluir = sub.add_parser("concluir", help="conclui tarefa com o status informado")
    concluir.add_argument("task_id")
    concluir.add_argument("status")

    sub.add_parser("opcoes", help="lista opções de status, duração e áreas")

    databases = sub.add_parser("databases", help="lista databases visíveis")
    databases.add_argument("--query")

    database_atual = sub.add_parser("database-atual", help="mostra o database configurado")
    database_atual.set_defaults(alias_comando="database-atual")

    escolher = sub.add_parser(
        "escolher-database",
        help="define o database padrão (grava no perfil ativo; sem perfil, no .env)",
    )
    escolher.add_argument("database_id")

    normalizar_nomes = sub.add_parser(
        "normalizar-nomes",
        help="renomeia propriedades e opções no Notion para nomes intuitivos",
    )
    normalizar_nomes.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra o plano sem escrever no Notion",
    )

    mapear = sub.add_parser("mapear", help="resume o inventário do workspace")
    mapear.add_argument("--query")
    mapear.add_argument("--page-size", type=int, default=100)
    mapear.add_argument("--limite-duplicatas", type=int, default=10)

    conteudo = sub.add_parser(
        "conteudo",
        help="lê uma página: propriedades, corpo em Markdown e, quando a API traz, "
        "'pai' {tipo, id} (numa linha de database, o database para 'schema'), 'url', "
        "'criado_em' e 'editado_em'; num database, as linhas",
    )
    conteudo.add_argument("page_id")

    exemplo = sub.add_parser(
        "exemplo",
        help="devolve 2 a 4 linhas do database padrão com propriedades e corpo completos",
    )
    exemplo.add_argument(
        "--n",
        type=int,
        default=3,
        metavar="N",
        help="quantidade de exemplos (entre 2 e 4; padrão: 3)",
    )

    linhas = sub.add_parser("linhas", help="lista as linhas de um database (resolve data sources)")
    linhas.add_argument("database_id")
    linhas.add_argument(
        "--completo",
        action="store_true",
        help="cada linha ganha 'propriedades' com todas as colunas já reduzidas "
        "a nome -> valor simples — evita 'conteudo'/'obter_pagina' linha a linha "
        "para analisar um database inteiro. Sem a flag, devolve só id/titulo/url",
    )

    editar_linha = sub.add_parser(
        "editar-linha",
        help="edita propriedades (colunas) de uma linha de database — faça ISTO "
        "antes de escrever o conteúdo",
    )
    editar_linha.add_argument("page_id", nargs="?")
    editar_linha.add_argument(
        "--set",
        action="append",
        metavar="NOME=VALOR",
        help='substitui o valor de uma coluna; repita para várias. Ex.: --set '
        '"Status=Feito" --set "Prazo=2026-07-10". Listas (multi_select/relation) '
        "aceitam CSV; texto vazio limpa a coluna. Uma URL em 'URL de referência' "
        "resolve Projeto; use --strict para exigir o padrão antes do PATCH.",
    )
    editar_linha.add_argument(
        "--append",
        action="append",
        metavar="NOME=TEXTO",
        help='acrescenta texto ao FINAL de uma coluna de texto (title/rich_text), '
        'preservando o conteúdo atual. Ex.: --append "Resumo=\\n\\nMais uma nota". '
        "Texto longo é fatiado automaticamente no limite de 2000.",
    )
    editar_linha.add_argument(
        "--arquivo",
        metavar="ARQUIVO",
        help="edita várias linhas a partir de JSON/CSV; JSON usa page_id e propriedades",
    )
    editar_linha.add_argument(
        "--strict",
        action="store_true",
        help="bloqueia URL/Projeto/título inconsistentes antes de qualquer escrita",
    )
    editar_linha.add_argument(
        "--dry-run",
        action="store_true",
        help="executa o preflight e mostra o plano sem editar no Notion",
    )
    editar_linha.add_argument(
        "--progresso-a-cada",
        type=int,
        default=10,
        metavar="N",
        help="no modo --arquivo, informa progresso a cada N linhas (padrão: 10)",
    )

    blocos = sub.add_parser(
        "blocos",
        help="lista os blocos de topo de uma página COM o ID de cada um — use "
        "antes de 'editar-bloco'/'apagar-bloco', que precisam do block_id. Sem "
        "flags, só {id, tipo, preview}",
    )
    blocos.add_argument("page_id")
    blocos.add_argument(
        "--metadados",
        action="store_true",
        help="acrescenta tem_filhos, criado_em, editado_em, criado_por, editado_por "
        "(IDs de usuário) e na_lixeira — já vêm na mesma resposta, sem chamada extra. "
        "Observado no workspace real: os horários chegam arredondados ao minuto (a "
        "documentação não fala em precisão) — para a ordem, use a posição na lista",
    )
    blocos.add_argument(
        "--completo",
        action="store_true",
        help="acrescenta 'markdown' com o texto INTEIRO de cada bloco (o preview é "
        "cortado em 100 caracteres)",
    )
    blocos.add_argument(
        "--recursivo",
        action="store_true",
        help="desce nos blocos com filhos (itens recuados, toggles, colunas) e lista "
        "os descendentes logo depois do pai, com 'nivel' (0 = topo) e 'pai_id'. Um "
        "GET por bloco com filhos, em sequência; nunca entra em subpágina nem database",
    )
    blocos.add_argument(
        "--contendo",
        metavar="TRECHO",
        help="só os blocos cujo texto contém o trecho (sem diferenciar maiúsculas) — "
        "para achar o ID de um bloco pelo que se leu em 'conteudo'",
    )

    ler_bloco = sub.add_parser(
        "ler-bloco",
        help="lê UM bloco pelo ID (aceita link com #bloco): Markdown inteiro (com os "
        "filhos, exceto de subpágina/database), tipo, pai {tipo, id}, tem_filhos, "
        "carimbos e na_lixeira. Use para conferir um bloco antes de 'editar-bloco' "
        "ou quando só se tem o ID de um bloco aninhado",
    )
    ler_bloco.add_argument("block_id")

    escrever = sub.add_parser(
        "escrever",
        help="ANEXA conteúdo (Markdown) ao final de uma página (não substitui); "
        "--apos <bloco>/--inicio insere noutro ponto; --substituir troca o corpo. "
        "Valida os limites da API antes de escrever. A saída traz 'blocos_criados' "
        "(ID e tipo de cada bloco de TOPO; filhos como itens recuados e linhas de "
        "tabela exigem 'blocos --recursivo'; lista vazia = a API não informou) e "
        "'posicao'. Se for linha de database, defina antes as propriedades com "
        "'editar-linha'",
    )
    escrever.add_argument("page_id")
    escrever.add_argument(
        "conteudo",
        nargs="?",
        help="texto em Markdown a anexar; '-' lê do stdin (escrever <id> - < nota.md)",
    )
    escrever.add_argument(
        "--arquivo-md",
        dest="arquivo_md",
        metavar="ARQUIVO",
        help="lê o Markdown deste arquivo (UTF-8) — sem limite de tamanho do argv nem "
        "escaping de shell",
    )
    posicao_escrita = escrever.add_mutually_exclusive_group()
    posicao_escrita.add_argument(
        "--apos",
        metavar="BLOCO_ID",
        help="INSERE logo depois deste bloco em vez de no fim (filho direto da página; "
        "pegue o ID em 'blocos'; aceita link com #bloco). Conteúdo com mais de 100 "
        "blocos sai encadeado na ordem. É o caminho para inserir — 'reordenar-bloco' "
        "é só para mover o que já existe",
    )
    posicao_escrita.add_argument(
        "--inicio", action="store_true", help="INSERE no começo da página em vez de no fim"
    )
    escrever.add_argument(
        "--substituir",
        action="store_true",
        help="troca o corpo pelo conteúdo novo (evita ir empilhando blocos ao "
        "corrigir/reescrever). Seguro por ordem: valida o Markdown contra os limites "
        "da API, ESCREVE o novo e só então apaga o antigo — se a escrita falhar, nada "
        "do antigo é apagado. Só é apagado o que o Markdown recria do mesmo tipo "
        "(parágrafo, títulos, listas, to-do, citação, código, divisória); toggle, "
        "callout, equação, imagem, arquivo, embed, subpágina, child_database e blocos "
        "que contêm algo assim são PRESERVADOS (com o motivo) e o texto novo entra "
        "depois deles. A saída traz os IDs apagados e o comando para desfazer",
    )
    escrever.add_argument(
        "--mesmo-com-database",
        dest="mesmo_com_database",
        action="store_true",
        help="permite escrever numa página que CONTÉM uma database. Por padrão "
        "isso é recusado: o texto viraria um bloco solto abaixo da tabela, onde "
        "não vira linha nem aparece em view nenhuma. Se o alvo é uma database, o "
        "trabalho é nas LINHAS ('linhas' → 'editar-linha'/'escrever <linha_id>')",
    )
    escrever.add_argument(
        "--apagar-tudo",
        dest="apagar_tudo",
        action="store_true",
        help="com --substituir, apaga TAMBÉM os blocos preservados (toggle, callout, "
        "equação, imagem, arquivo, embed, subpágina, child_database…). Perigoso: a "
        "URL de arquivo do Notion expira e apagar um child_database leva o database "
        "inteiro",
    )

    editar_bloco = sub.add_parser(
        "editar-bloco",
        help="edita UM bloco (pegue o block_id em 'blocos'): reescreve o texto por "
        "Markdown ou troca só um trecho com --trocar/--por. Confere o bloco antes: "
        "texto sem prefixo mantém o tipo atual (heading continua heading); prefixo de "
        "outro tipo, várias linhas e perda de menção/sublinhado/cor são recusados sem "
        "gravar nada. A saída confirma tipo, markdown e editado_em",
    )
    editar_bloco.add_argument("block_id", nargs="?")
    editar_bloco.add_argument(
        "conteudo",
        nargs="?",
        help="o novo texto do bloco: UMA linha de Markdown (várias linhas são "
        "recusadas; num bloco de código, o texto inteiro é o código, com o recuo da "
        "primeira linha preservado); '-' lê do stdin",
    )
    editar_bloco.add_argument(
        "--arquivo-md",
        dest="arquivo_md",
        metavar="ARQUIVO",
        help="lê o novo texto deste arquivo (útil para um bloco de código grande)",
    )
    editar_bloco.add_argument(
        "--trocar",
        metavar="TRECHO",
        help="troca só este trecho, mantendo cor, sublinhado, links e menções do resto",
    )
    editar_bloco.add_argument(
        "--por", metavar="TEXTO", help='texto que entra no lugar de --trocar ("" apaga)'
    )
    editar_bloco.add_argument(
        "--todas",
        action="store_true",
        help="com --trocar, troca todas as ocorrências (sem isso, exige exatamente uma)",
    )
    editar_bloco.add_argument(
        "--aceitar-perda-de-formatacao",
        dest="aceitar_perda_de_formatacao",
        action="store_true",
        help="reescreve por Markdown mesmo que menção, equação, sublinhado ou cor se "
        "percam (prefira --trocar)",
    )
    editar_bloco.add_argument(
        "--arquivo",
        metavar="ARQUIVO",
        help="várias edições num processo, a partir de JSON (lista, ou objeto com "
        "'itens'/'linhas') ou CSV: cada item é {block_id, conteudo} ou {block_id, "
        "trocar, por, todas}. Envelope de lote; um erro não para os demais",
    )
    editar_bloco.add_argument(
        "--progresso-a-cada",
        type=int,
        default=10,
        metavar="N",
        help="no modo --arquivo, informa progresso a cada N itens no stderr (padrão: 10)",
    )

    apagar_bloco = sub.add_parser(
        "apagar-bloco",
        help="manda um ou mais blocos para a lixeira — destrutivo (pegue o block_id em "
        "'blocos'). Lê cada bloco antes: subpágina e database (que levam tudo o que "
        "está dentro) exigem --forcar-tipos-arriscados. A saída diz o tipo, um resumo "
        "e, em 'desfazer', o comando 'restaurar-bloco' pronto. Com vários IDs, "
        "envelope de lote (um erro não para os demais)",
    )
    apagar_bloco.add_argument(
        "block_ids", nargs="+", metavar="block_id", help="um ou mais IDs de bloco"
    )
    apagar_bloco.add_argument("--sim", action="store_true", help="confirma a exclusão")
    apagar_bloco.add_argument(
        "--forcar-tipos-arriscados",
        action="store_true",
        help="permite apagar subpágina (child_page) ou database (child_database), com "
        "tudo o que está dentro — é o caso de arquivar uma página inteira",
    )

    limpar = sub.add_parser(
        "limpar",
        help="apaga de uma vez o corpo recriável de uma página — destrutivo; use para "
        "reiniciar uma página bagunçada antes de reescrever. Preserva (com o motivo) "
        "o que o Markdown não recria. A saída traz os IDs apagados e, em 'desfazer', "
        "o comando 'restaurar-bloco' pronto",
    )
    limpar.add_argument("page_id")
    limpar.add_argument("--sim", action="store_true", help="confirma a limpeza")
    limpar.add_argument(
        "--apagar-tudo",
        dest="apagar_tudo",
        action="store_true",
        help="apaga TAMBÉM toggle, callout, equação, imagem, arquivo, embed, "
        "subpágina e child_database — que por padrão são preservados por não se "
        "recriarem a partir de Markdown",
    )

    restaurar_bloco = sub.add_parser(
        "restaurar-bloco",
        help="tira da lixeira blocos apagados por 'limpar', 'escrever --substituir' "
        "ou 'apagar-bloco', pelo ID (a saída deles traz os IDs e o comando pronto em "
        "'desfazer'). O bloco volta no FIM da página, com o mesmo ID e os filhos. "
        "Subpágina e database NÃO voltam por aqui (a API recusa): use a Lixeira do Notion",
    )
    restaurar_bloco.add_argument(
        "block_ids", nargs="+", metavar="block_id", help="um ou mais IDs de bloco"
    )

    esquema = sub.add_parser(
        "schema",
        help="descreve as colunas de um database: tipo, opções válidas, o que é "
        "calculado pelo Notion e como cada relação está configurada. LEIA ISTO "
        "antes de escrever num database que você não conhece",
    )
    esquema.add_argument("database_id")
    esquema.add_argument(
        "--editaveis",
        action="store_true",
        help="mostra só as colunas que aceitam escrita",
    )

    relacionar = sub.add_parser(
        "relacionar",
        help="liga uma ou várias linhas por uma coluna de relação NOS DOIS SENTIDOS — "
        "relação single_property do Notion não espelha sozinha pela API",
    )
    relacionar.add_argument("page_a", nargs="?", help="primeira página (forma legada de um par)")
    relacionar.add_argument("page_b", nargs="?", help="segunda página (forma legada de um par)")
    relacionar.add_argument(
        "--coluna", required=True, help='nome da coluna de relação (ex.: "Subtarefas relacionadas")'
    )
    entradas_relacao = relacionar.add_mutually_exclusive_group()
    entradas_relacao.add_argument(
        "--par",
        action="append",
        help='par no formato "page_a:page_b"; repita para ligar vários pares',
    )
    entradas_relacao.add_argument(
        "--arquivo",
        help=(
            "arquivo JSON com uma lista de pares; cada item pode ser objeto, "
            "lista de dois IDs ou 'a:b'"
        ),
    )
    relacionar.add_argument(
        "--desfazer", action="store_true", help="remove a ligação em vez de criá-la"
    )

    relatorios_git = sub.add_parser(
        "relatorios-do-git",
        help="reconstrói relatórios diários a partir do histórico de VÁRIOS "
        "repositórios, um por dia, com hora e duração por projeto; idempotente "
        "pela data (dia existente é complementado, nunca sobrescrito)",
    )
    relatorios_git.add_argument(
        "--database", required=True, help="database dos relatórios diários"
    )
    relatorios_git.add_argument(
        "--repo",
        action="append",
        metavar="NOME=CAMINHO",
        help='repositório a incluir; repita para vários. Ex.: --repo "Felixo AI '
        'Core=/home/eu/Felixo-AI-Core". O NOME é o que aparece no relatório',
    )
    relatorios_git.add_argument(
        "--descobrir",
        action="append",
        metavar="PASTA",
        help="varre a pasta e inclui TODOS os repositórios git encontrados "
        "(até 3 níveis). É o que acha o projeto que você esqueceu de registrar; "
        "combinável com --repo, que vence no caso de nome repetido",
    )
    relatorios_git.add_argument("--desde", help="data ISO inicial (inclusiva)")
    relatorios_git.add_argument("--ate", help="data ISO final (inclusiva)")
    relatorios_git.add_argument("--autor", help="filtra por autor, como git --author")
    relatorios_git.add_argument("--area", help='valor da coluna "Área" nos dias novos')
    relatorios_git.add_argument("--status", help='valor da coluna "Status" nos dias novos')
    relatorios_git.add_argument(
        "--sem-estatisticas",
        dest="sem_estatisticas",
        action="store_true",
        help="não coleta arquivos/linhas por commit (uma chamada de git a menos)",
    )
    relatorios_git.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="só mostra os dias que seriam escritos, sem tocar no Notion",
    )

    relatorio_do_dia = sub.add_parser(
        "relatorio-do-dia",
        help="cria ou complementa a linha do dia em Relatórios diários; "
        "--corpo é sempre o relato completo, as demais colunas são sempre um "
        "resumo curto — o comando avisa se uma delas ficou grande demais",
    )
    relatorio_do_dia.add_argument(
        "--database", required=True, help="database dos relatórios diários"
    )
    relatorio_do_dia.add_argument(
        "--data", help="data ISO (AAAA-MM-DD); padrão: hoje"
    )
    relatorio_do_dia.add_argument(
        "--corpo",
        help="relato completo do dia, em Markdown — SEMPRE vai no corpo da "
        "página, nunca numa propriedade. Complementa um dia já existente "
        "(nunca sobrescreve). '-' lê do stdin.",
    )
    relatorio_do_dia.add_argument(
        "--arquivo-md",
        dest="arquivo_md",
        metavar="ARQUIVO",
        help="lê o relato (--corpo) deste arquivo Markdown",
    )
    relatorio_do_dia.add_argument(
        "--permitir-corpo-vazio",
        dest="permitir_corpo_vazio",
        action="store_true",
        help="uso excepcional: grava sem --corpo (só as colunas)",
    )
    relatorio_do_dia.add_argument(
        "--resumo", help='coluna "Resumo": uma frase que se entende sozinha'
    )
    relatorio_do_dia.add_argument(
        "--o-que-fiz",
        dest="o_que_fiz",
        help='coluna "O que fiz": poucas linhas — o relato inteiro vai em --corpo',
    )
    relatorio_do_dia.add_argument(
        "--bloqueios",
        help='coluna "Bloqueios": limitações declaradas, resumidas',
    )
    relatorio_do_dia.add_argument(
        "--proximos-passos",
        dest="proximos_passos",
        help='coluna "Próximos passos"',
    )
    relatorio_do_dia.add_argument("--status", help='valor da coluna "Status"')
    relatorio_do_dia.add_argument("--area", help='valor da coluna "Área"')

    buscar = sub.add_parser("buscar", help="pesquisa páginas e databases visíveis")
    buscar.add_argument("query", nargs="?", help="texto do título; vazio lista tudo")

    clonar = sub.add_parser(
        "clonar-database",
        help="clona um database com todas as propriedades, sem vínculo com a origem",
    )
    clonar.add_argument("database_id")
    clonar.add_argument("--titulo", help="título do clone (padrão: '<origem> (cópia)')")
    clonar.add_argument("--pagina", help="página onde criar o clone (padrão: a pai da origem)")
    clonar.add_argument(
        "--com-linhas",
        action="store_true",
        help="copia também as linhas da origem",
    )
    clonar.add_argument(
        "--relacoes",
        choices=("auto-novo", "texto"),
        default="auto-novo",
        help="auto-novo: auto-relações apontam pro clone, externas preservam; "
        "texto: relações viram texto sem vínculo",
    )

    criar_subpagina = sub.add_parser(
        "criar-subpagina",
        help="cria uma página filha simples dentro de outra página (não é linha de database)",
    )
    criar_subpagina.add_argument("pagina_pai_id")
    criar_subpagina.add_argument("titulo")
    criar_subpagina.add_argument(
        "--conteudo",
        help="Markdown opcional já preenchido na criação da subpágina; '-' lê do stdin",
    )
    criar_subpagina.add_argument(
        "--arquivo-md", dest="arquivo_md", metavar="ARQUIVO", help="lê o Markdown deste arquivo"
    )

    inspecionar_estrutura = sub.add_parser(
        "inspecionar-estrutura",
        help="lê recursivamente a árvore de subpáginas/databases de uma página, "
        "para investigar o padrão de um projeto de referência sem editar nada",
    )
    inspecionar_estrutura.add_argument("pagina_id")
    inspecionar_estrutura.add_argument(
        "--profundidade",
        type=int,
        default=3,
        help="quantos níveis de subpágina descer (padrão: 3)",
    )

    clonar_estrutura = sub.add_parser(
        "clonar-estrutura",
        help="copia a forma de uma página de projeto (títulos de subpágina, schema de "
        "databases) para outra página, sem herdar o conteúdo específico da origem",
    )
    clonar_estrutura.add_argument("pagina_referencia_id")
    clonar_estrutura.add_argument("pagina_destino_id")

    inventario = sub.add_parser(
        "inventario",
        help="grava em JSON cada página/database visível com created_time, "
        "last_edited_time, caminho de ancestrais e colunas preenchidas (um /search "
        "paginado; ~1 min para ~4 mil itens)",
    )
    inventario.add_argument("--saida", required=True, help="arquivo JSON a gravar")
    inventario.add_argument(
        "--filtro", choices=("page", "database"), help="só páginas ou só databases"
    )

    baixar_corpos = sub.add_parser(
        "baixar-corpos",
        help="baixa o corpo (Markdown) das páginas de um inventário, um <id>.md por "
        "página com cabeçalho de metadados; RETOMÁVEL (o que já baixou é pulado) e "
        "priorizado (páginas soltas e databases pequenos primeiro)",
    )
    baixar_corpos.add_argument("inventario", help="JSON gravado por 'inventario'")
    baixar_corpos.add_argument("--destino", required=True, help="pasta dos arquivos .md")
    baixar_corpos.add_argument(
        "--ignorar-caminho",
        action="append",
        metavar="CAMINHO",
        help='prefixo de caminho a pular, com " / " entre níveis (repita)',
    )
    baixar_corpos.add_argument(
        "--ignorar-database", action="append", metavar="ID", help="database a pular (repita)"
    )
    baixar_corpos.add_argument(
        "--somente-database",
        action="append",
        metavar="ID",
        help="só linhas destes databases (repita)",
    )
    baixar_corpos.add_argument(
        "--priorizar",
        metavar="REGEX",
        help="nos databases volumosos, baixa antes as linhas cujo título/colunas casam",
    )
    baixar_corpos.add_argument(
        "--limite", type=int, help="no máximo N páginas nesta rodada (o resto fica adiado)"
    )
    baixar_corpos.add_argument(
        "--trabalhadores",
        type=int,
        default=3,
        help="threads simultâneas (padrão: 3; o Notion limita ~3 req/s)",
    )
    baixar_corpos.add_argument(
        "--incluir-arquivados", action="store_true", help="também baixa itens arquivados"
    )
    baixar_corpos.add_argument(
        "--progresso-a-cada",
        type=int,
        default=25,
        metavar="N",
        help="mostra o progresso no stderr a cada N páginas (0 desliga)",
    )

    buscar_conteudo = sub.add_parser(
        "buscar-conteudo",
        help="procura uma expressão regular no TEXTO COMPLETO baixado por "
        "'baixar-corpos' (o 'buscar' casa só o título); sem acentos e sem caixa por "
        "padrão, com trechos do original",
    )
    buscar_conteudo.add_argument("pasta", help="pasta gravada por 'baixar-corpos'")
    buscar_conteudo.add_argument("expressao", help="expressão regular (sintaxe do Python)")
    buscar_conteudo.add_argument(
        "--contexto", type=int, default=90, help="caracteres de cada lado do trecho"
    )
    buscar_conteudo.add_argument(
        "--max-trechos", dest="max_trechos", type=int, default=4, help="trechos por página"
    )
    buscar_conteudo.add_argument("--limite", type=int, help="no máximo N páginas")
    buscar_conteudo.add_argument(
        "--com-acentos", action="store_true", help="diferencia letras acentuadas"
    )
    buscar_conteudo.add_argument(
        "--diferenciar-caixa", action="store_true", help="diferencia maiúsculas"
    )

    modelos = sub.add_parser(
        "modelos",
        help="modelos nativos (templates) de um database: 'listar' e 'preencher' os "
        "modelos vazios ('New page' sem corpo) com nome, colunas e corpo de um "
        "manifesto JSON; a API não cria modelo nem define o padrão",
    )
    sub_modelos = modelos.add_subparsers(dest="acao_modelos", required=True)
    modelos_listar = sub_modelos.add_parser("listar", help="lista os modelos do database")
    modelos_preencher = sub_modelos.add_parser(
        "preencher",
        help="preenche os modelos vazios na ordem do manifesto (idempotente)",
    )
    for parser_modelos in (modelos_listar, modelos_preencher):
        parser_modelos.add_argument("database_id")
        parser_modelos.add_argument(
            "--fonte", help="data source a usar quando o database tem mais de um"
        )
    modelos_preencher.add_argument(
        "--manifesto",
        required=True,
        help='JSON: [{"nome", "arquivo" (Markdown, relativo ao manifesto) ou "copiar_de" '
        '(página de origem do corpo), "propriedades": {"Coluna": "valor"}}]',
    )
    modelos_preencher.add_argument(
        "--dry-run", action="store_true", help="só mostra qual modelo receberia cada item"
    )

    copiar_corpo = sub.add_parser(
        "copiar-corpo",
        help="copia o corpo de uma página para o fim de outra BLOCO A BLOCO (tabela, "
        "checklist, colunas, callout e menções preservados, sem passar por Markdown); "
        "subpágina, database e arquivo hospedado no Notion ficam em 'ignorados'",
    )
    copiar_corpo.add_argument("origem_id", help="página de onde ler")
    copiar_corpo.add_argument("destino_id", help="página que recebe os blocos (no fim)")
    copiar_corpo.add_argument(
        "--so-se-vazio",
        dest="so_se_vazio",
        action="store_true",
        help="não escreve se o destino já tiver algum bloco (idempotente ao repetir)",
    )
    copiar_corpo.add_argument(
        "--dry-run", action="store_true", help="só lê e planeja; mostra a contagem por tipo"
    )
    copiar_corpo.add_argument(
        "--conferir",
        action="store_true",
        help="relê o destino antes e depois e compara a contagem de blocos por tipo",
    )
    copiar_corpo.add_argument(
        "--mesmo-com-database",
        dest="mesmo_com_database",
        action="store_true",
        help="aceita escrever num destino que contém database",
    )

    montar_estrutura_projeto = sub.add_parser(
        "montar-estrutura-projeto",
        help="aplica o padrão fixo de projeto do workspace (## Acompanhamento com 4 "
        "subpáginas + ## Planejamento e documentação com 2 databases) numa página",
    )
    montar_estrutura_projeto.add_argument("pagina_id")

    reordenar_bloco = sub.add_parser(
        "reordenar-bloco",
        help="MOVE um bloco que já existe para outra posição na mesma página (para "
        "INSERIR texto novo num ponto, use 'escrever --apos'). A API do Notion não "
        "move blocos: isto grava um backup em JSON, cria a cópia na posição pedida e "
        "só então apaga o original — o bloco ganha um ID NOVO. Só texto simples "
        "sem filhos (parágrafo, títulos, listas, to-do, citação, callout, toggle, "
        "código, divisória); subpágina, database, tabela, imagem, colunas e blocos "
        "com filhos são recusados sem apagar nada",
    )
    reordenar_bloco.add_argument("pagina_id", help="página que contém o bloco como filho direto")
    reordenar_bloco.add_argument("bloco_id")
    reordenar_bloco.add_argument("--apos", help="ID do bloco irmão após o qual mover")
    reordenar_bloco.add_argument(
        "--inicio", action="store_true", help="move para o início da lista de filhos"
    )
    reordenar_bloco.add_argument(
        "--dir-backup",
        dest="dir_backup",
        metavar="PASTA",
        help="pasta do backup em JSON (padrão: NOTION_AUTOMACOES_BACKUP_DIR ou a pasta "
        "de estado do usuário, ~/.local/state/notion-automacoes/backups; nunca o "
        "diretório corrente). A saída traz o caminho absoluto em 'backup_path'",
    )
    reordenar_bloco.add_argument(
        "--forcar-tipos-arriscados",
        action="store_true",
        help="sem efeito, mantida para scripts antigos: subpágina e database nunca "
        "são reordenados (a API não os recria por este caminho)",
    )

    garantir_coluna = sub.add_parser(
        "garantir-coluna",
        help="adiciona uma coluna a um database já existente, sem apagar nada — "
        "criar-database só define schema na criação; este comando cobre a lacuna "
        "de evoluir um database depois de criado. Idempotente: não mexe em nada "
        "se a coluna já existe",
    )
    garantir_coluna.add_argument("database_id")
    garantir_coluna.add_argument("nome_coluna")
    garantir_coluna.add_argument(
        "tipo",
        help="tipos: titulo, texto, numero, data, select, multi_select, checkbox, "
        "email, url, telefone, pessoas, arquivos, relacao",
    )
    garantir_coluna.add_argument(
        "--opcoes",
        action="append",
        help="opções iniciais de select/multi_select (CSV; aceita repetição). Só valem "
        "quando a coluna é criada agora; numa coluna que já existe, nada muda",
    )
    garantir_coluna.add_argument(
        "--relacionar-com",
        dest="relacionar_com",
        help="ID do database alvo — obrigatório (e exclusivo) para o tipo 'relacao'. "
        "A relação é bidirecional: o Notion cria a coluna espelho no database alvo",
    )

    renomear_coluna = sub.add_parser(
        "renomear-coluna",
        help="renomeia uma coluna (propriedade) já existente no schema de um "
        "database, sem tocar no tipo, nas opções nem nas linhas — cobre o caso "
        "de o Notion criar sozinho a coluna espelho de uma relação nova com um "
        "nome genérico. Para trocar o título do database inteiro, use "
        "renomear-database",
    )
    renomear_coluna.add_argument("database_id")
    renomear_coluna.add_argument("nome_atual")
    renomear_coluna.add_argument("novo_nome")

    remover_coluna = sub.add_parser(
        "remover-coluna",
        help="REMOVE uma coluna do schema de um database — os valores dela somem de "
        "todas as linhas; exige --sim e recusa a coluna de título. Útil para desfazer "
        "as colunas que o Notion cria no destino ao mover linhas entre databases",
    )
    remover_coluna.add_argument("database_id")
    remover_coluna.add_argument("coluna", help="nome exato da coluna")
    remover_coluna.add_argument(
        "--sim", action="store_true", help="confirma a remoção (sem ele, nada é feito)"
    )

    atualizar_github = sub.add_parser(
        "atualizar-github",
        help="re-sincroniza o database GITHUB (repos novos, propriedades, README mudado)",
    )
    atualizar_github.add_argument(
        "--contas",
        action="append",
        help="contas do GitHub (CSV); padrão: variável de ambiente GITHUB_CONTAS",
    )
    atualizar_github.add_argument(
        "--database",
        help="database de destino (padrão: NOTION_DATABASE_ID)",
    )
    atualizar_github.add_argument(
        "--sem-readme",
        action="store_true",
        help="atualiza só as propriedades, sem mexer na subpágina README",
    )
    atualizar_github.add_argument(
        "--sem-arquivados",
        action="store_true",
        help="ignora repositórios arquivados no GitHub (mantém só os ativos)",
    )
    atualizar_github.add_argument(
        "--apenas-mudancas",
        action="store_true",
        help="pula repositórios existentes sem alteração (updated_at não avançou)",
    )

    exportar_docx = sub.add_parser(
        "exportar-docx",
        help=(
            "exporta relatorios diarios do Notion para DOCX, um arquivo por dia; "
            "a saida reproduz o modelo visual dos relatorios, mas e gerada "
            "programaticamente — acabamento fino pode exigir ajuste manual no Word"
        ),
    )
    exportar_docx.add_argument("--database", help="database de relatorios; padrao: env")
    exportar_docx.add_argument("--de", required=True, help="data inicial YYYY-MM-DD")
    exportar_docx.add_argument("--ate", required=True, help="data final YYYY-MM-DD")
    exportar_docx.add_argument("--saida", required=True, help="diretorio de saida")
    exportar_docx.add_argument(
        "--campo-data",
        default="Data",
        help="nome da propriedade de data usada no filtro (padrao: Data)",
    )

    criar_database = sub.add_parser(
        "criar-database",
        help="cria um database numa página, com schema tipado a partir de --prop",
    )
    criar_database.add_argument("pagina_id", help="página que recebe o database")
    criar_database.add_argument("titulo")
    criar_database.add_argument(
        "--prop",
        action="append",
        help='coluna no formato "Nome=tipo" (tipos: titulo, texto, numero, data, '
        "select, multi_select, checkbox, email, url, telefone, pessoas, arquivos); "
        "sem coluna 'titulo', uma propriedade 'Nome' é criada",
    )
    criar_database.add_argument(
        "--inline", action="store_true", help="cria embutido no corpo da página"
    )
    criar_database.add_argument("--icone", help="emoji usado como ícone")
    criar_database.add_argument("--descricao", help="descrição do database")
    criar_database.add_argument(
        "--prefixo-id",
        dest="prefixo_id",
        help="cria propriedade ID (unique_id) com este prefixo — único por workspace",
    )

    importar_planilha = sub.add_parser(
        "importar-planilha",
        help="importa .xlsx/.csv para um database (upsert idempotente por Origem; use "
        "--chave para casar pelo registro e --dry-run para ver o plano)",
    )
    importar_planilha.add_argument("database_id", help="database de destino")
    importar_planilha.add_argument("caminho", help="arquivo .xlsx ou .csv")
    importar_planilha.add_argument("--aba", help="aba do .xlsx (padrão: a ativa)")
    importar_planilha.add_argument(
        "--coluna-titulo",
        dest="coluna_titulo",
        help="coluna usada como título da linha (padrão: a primeira)",
    )
    importar_planilha.add_argument(
        "--tipo",
        action="append",
        help='tipo de coluna no formato "Coluna=tipo" (numero, data, select, '
        "checkbox, email, url, telefone; padrão: texto). Números e datas aceitam "
        "formato brasileiro; valores inválidos vão para Observações",
    )
    importar_planilha.add_argument(
        "--renomear",
        action="append",
        help='mapeia coluna para propriedade: "Coluna=Nome no Notion"',
    )
    importar_planilha.add_argument(
        "--chave",
        metavar="COLUNA",
        help="coluna que identifica cada registro (ex.: Email): a Origem passa a ser "
        "'arquivo#Coluna=valor' e reordenar a planilha não troca registros. Chave "
        "vazia ou repetida é recusada antes de gravar. Sem --chave vale a posição da "
        "linha, e uma linha cuja página achada tem outro título vai para 'conflitos' "
        "em vez de sobrescrever",
    )
    importar_planilha.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="não grava nada: os contadores e 'conflitos' dizem o que seria feito "
        "(as páginas existentes são lidas)",
    )

    aparencia_parser = sub.add_parser(
        "aparencia",
        help="define o ícone e/ou a capa de uma página: emoji (só ícone), URL http(s) ou "
        "imagem local (sobe pela File Upload API). Ícone ou capa que a página já tem são "
        "mantidos, a não ser com --substituir",
    )
    aparencia_parser.add_argument("page_id", help="página ou linha de database")
    aparencia_parser.add_argument("--icone", help="emoji, URL http(s) ou arquivo de imagem")
    aparencia_parser.add_argument("--capa", help="URL http(s) ou arquivo de imagem")
    aparencia_parser.add_argument(
        "--substituir",
        action="store_true",
        help="troca ícone/capa mesmo que a página já tenha",
    )

    anexar = sub.add_parser(
        "anexar-arquivo",
        help="sobe um arquivo local (até 20 MB) e anexa numa propriedade de arquivos",
    )
    anexar.add_argument("page_id", help="linha de database que recebe o anexo")
    anexar.add_argument("caminho", help="arquivo local")
    anexar.add_argument(
        "--propriedade",
        help='nome da propriedade de arquivos (padrão: "Arquivos e mídia")',
    )
    anexar.add_argument(
        "--substituir",
        action="store_true",
        help="troca os anexos existentes em vez de acrescentar",
    )

    mover_pagina = sub.add_parser(
        "mover-pagina",
        help="move uma página para outra página, database ou data source e confere o "
        "pai relido; antes, prevê as colunas que o Notion cria no destino e os "
        "valores que se perdem (perda exige --aceitar-perdas)",
    )
    mover_pagina.add_argument("page_id")
    mover_pagina.add_argument("novo_pai_id")
    mover_pagina.add_argument(
        "--tipo-pai",
        dest="tipo_pai",
        choices=("page_id", "database_id", "data_source_id"),
        default="page_id",
        help="tipo do novo pai (padrão: page_id); database_id usa o único data source "
        "do database — com vários, informe a fonte e use data_source_id",
    )
    mover_pagina.add_argument(
        "--dry-run",
        action="store_true",
        help="só mostra a previsão (colunas criadas no destino, valores perdidos)",
    )
    mover_pagina.add_argument(
        "--aceitar-perdas",
        dest="aceitar_perdas",
        action="store_true",
        help="move mesmo que algum valor de coluna vá se perder (relação, opção "
        "inexistente no destino, tipo diferente)",
    )

    mover_database = sub.add_parser(
        "mover-database",
        help="move (re-parenteia) um database inteiro para outra página",
    )
    mover_database.add_argument("database_id")
    mover_database.add_argument("novo_pai_id")

    renomear_database = sub.add_parser(
        "renomear-database",
        help="troca o título de um database, sem tocar no schema nem nas linhas — "
        "resolve os databases 'Untitled' que sobram de templates duplicados",
    )
    renomear_database.add_argument("database_id")
    renomear_database.add_argument("novo_titulo")

    perfis = sub.add_parser(
        "perfis",
        help="gerencia perfis locais de workspaces/keys do Notion",
    )
    sub_perfis = perfis.add_subparsers(dest="acao_perfil", required=True)

    sub_perfis.add_parser("listar", help="lista perfis salvos sem expor tokens")

    adicionar = sub_perfis.add_parser("adicionar", help="salva uma key/workspace local")
    adicionar.add_argument("alias", help="nome curto: letras, numeros, '-' ou '_'")
    adicionar.add_argument("--token", required=True, help="token da integração do Notion")
    adicionar.add_argument("--database", help="database padrão desse workspace")
    adicionar.add_argument("--nome", help="nome legível do workspace")
    adicionar.add_argument("--descricao", help="observação curta para diferenciar o perfil")
    adicionar.add_argument(
        "--ativar",
        action="store_true",
        help="também define este perfil como padrão para próximos comandos",
    )
    adicionar.add_argument(
        "--sobrescrever",
        action="store_true",
        help="atualiza o perfil se o alias já existir",
    )

    usar = sub_perfis.add_parser("usar", help="define o perfil ativo")
    usar.add_argument("alias")

    mostrar = sub_perfis.add_parser("mostrar", help="mostra um perfil sem expor o token")
    mostrar.add_argument("alias", nargs="?")

    remover = sub_perfis.add_parser("remover", help="remove um perfil salvo")
    remover.add_argument("alias")
    remover.add_argument("--sim", action="store_true", help="confirma a remoção")

    sub.add_parser("guia", help="lista todos os comandos com o que fazem e exemplos")
    return parser


def executar(
    argv: Sequence[str] | None = None,
    *,
    tasklist_factory: TaskListFactory = _criar_tasklist,
    client_factory: ClientFactory = _criar_client,
) -> tuple[int, dict[str, Any] | str]:
    """Roda um comando e devolve ``(código de saída, saída)``.

    Com ``--json`` a saída é sempre um envelope — inclusive num argumento
    inválido, que antes saía como texto do argparse no stderr — e nenhuma
    exceção escapa como traceback: o que não tem tratamento próprio vira
    ``erro_interno`` (o traceback vai para o stderr, para o diagnóstico).
    """

    parser = construir_parser()
    lista = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = parser.parse_args(lista)
    except _ErroDeArgumento as exc:
        if "--json" not in lista:
            # Sem --json, o comportamento do argparse: uso + erro no stderr.
            exc.parser.exit(SAIDA_USO, f"{exc.parser.format_usage()}{exc.parser.prog}: "
                            f"error: {exc.mensagem}\n")
        erro = ErroClassificado(
            codigo="uso_invalido",
            mensagem=f"{exc.mensagem} (veja '{exc.parser.prog} --help')",
            saida=SAIDA_USO,
            proximo_passo=f"{exc.parser.prog} --help",
        )
        return erro.saida, _envelope_erro(erro)
    try:
        dados = _despachar(args, tasklist_factory=tasklist_factory, client_factory=client_factory)
        return 0, _envelope(True, dados=dados) if args.json else _formatar_humano(
            args.comando, dados
        )
    except Exception as exc:  # noqa: BLE001 - fronteira: nenhum traceback no lugar do JSON
        erro = classificar_erro(exc)
        if erro.codigo == "erro_interno":
            traceback.print_exc(file=sys.stderr)
        return erro.saida, _envelope_erro(erro) if args.json else _texto_erro(erro)


def _despachar(
    args: argparse.Namespace,
    *,
    tasklist_factory: TaskListFactory,
    client_factory: ClientFactory,
) -> Any:
    """Chama o ``cmd_*`` do subcomando e devolve os dados de sucesso."""

    comando = args.comando
    if comando not in {"perfis", "guia"}:
        perfis_workspace.aplicar_perfil(args.perfil)
    if comando == "guia":
        dados = cmd_guia(args)
    elif comando == "perfis":
        dados = cmd_perfis(args)
    elif comando == "listar":
        dados = cmd_listar(args, tasklist_factory=tasklist_factory)
    elif comando == "ler":
        dados = cmd_ler(args, tasklist_factory=tasklist_factory)
    elif comando == "criar":
        dados = cmd_criar(
            args, tasklist_factory=tasklist_factory, client_factory=client_factory
        )
    elif comando == "editar":
        dados = cmd_editar(args, tasklist_factory=tasklist_factory)
    elif comando == "mover":
        dados = cmd_mover(args, tasklist_factory=tasklist_factory)
    elif comando == "concluir":
        dados = cmd_concluir(args, tasklist_factory=tasklist_factory)
    elif comando == "opcoes":
        dados = cmd_opcoes(args, tasklist_factory=tasklist_factory)
    elif comando == "databases":
        dados = cmd_databases(args, client_factory=client_factory)
    elif comando == "database-atual":
        dados = cmd_database_atual(args, client_factory=client_factory)
    elif comando == "escolher-database":
        dados = cmd_escolher_database(args)
    elif comando == "normalizar-nomes":
        dados = cmd_normalizar_nomes(args, client_factory=client_factory)
    elif comando == "mapear":
        dados = cmd_mapear(args, client_factory=client_factory)
    elif comando == "conteudo":
        dados = cmd_conteudo(args, client_factory=client_factory)
    elif comando == "exemplo":
        dados = cmd_exemplo(args, client_factory=client_factory)
    elif comando == "linhas":
        dados = cmd_linhas(args, client_factory=client_factory)
    elif comando == "blocos":
        dados = cmd_blocos(args, client_factory=client_factory)
    elif comando == "ler-bloco":
        dados = cmd_ler_bloco(args, client_factory=client_factory)
    elif comando == "editar-linha":
        dados = cmd_editar_linha(args, client_factory=client_factory)
    elif comando == "escrever":
        dados = cmd_escrever(args, client_factory=client_factory)
    elif comando == "editar-bloco":
        dados = cmd_editar_bloco(args, client_factory=client_factory)
    elif comando == "apagar-bloco":
        dados = cmd_apagar_bloco(args, client_factory=client_factory)
    elif comando == "limpar":
        dados = cmd_limpar(args, client_factory=client_factory)
    elif comando == "restaurar-bloco":
        dados = cmd_restaurar_bloco(args, client_factory=client_factory)
    elif comando == "schema":
        dados = cmd_schema(args, client_factory=client_factory)
    elif comando == "relacionar":
        dados = cmd_relacionar(args, client_factory=client_factory)
    elif comando == "relatorios-do-git":
        dados = cmd_relatorios_do_git(args, client_factory=client_factory)
    elif comando == "relatorio-do-dia":
        dados = cmd_relatorio_do_dia(args, client_factory=client_factory)
    elif comando == "buscar":
        dados = cmd_buscar(args, client_factory=client_factory)
    elif comando == "clonar-database":
        dados = cmd_clonar_database(args, client_factory=client_factory)
    elif comando == "criar-subpagina":
        dados = cmd_criar_subpagina(args, client_factory=client_factory)
    elif comando == "inspecionar-estrutura":
        dados = cmd_inspecionar_estrutura(args, client_factory=client_factory)
    elif comando == "inventario":
        dados = cmd_inventario(args, client_factory=client_factory)
    elif comando == "baixar-corpos":
        dados = cmd_baixar_corpos(args, client_factory=client_factory)
    elif comando == "buscar-conteudo":
        dados = cmd_buscar_conteudo(args, client_factory=client_factory)
    elif comando == "modelos":
        dados = cmd_modelos(args, client_factory=client_factory)
    elif comando == "copiar-corpo":
        dados = cmd_copiar_corpo(args, client_factory=client_factory)
    elif comando == "clonar-estrutura":
        dados = cmd_clonar_estrutura(args, client_factory=client_factory)
    elif comando == "montar-estrutura-projeto":
        dados = cmd_montar_estrutura_projeto(args, client_factory=client_factory)
    elif comando == "reordenar-bloco":
        dados = cmd_reordenar_bloco(args, client_factory=client_factory)
    elif comando == "garantir-coluna":
        dados = cmd_garantir_coluna(args, client_factory=client_factory)
    elif comando == "remover-coluna":
        dados = cmd_remover_coluna(args, client_factory=client_factory)
    elif comando == "renomear-coluna":
        dados = cmd_renomear_coluna(args, client_factory=client_factory)
    elif comando == "atualizar-github":
        dados = cmd_atualizar_github(args, client_factory=client_factory)
    elif comando == "exportar-docx":
        dados = cmd_exportar_docx(args, client_factory=client_factory)
    elif comando == "criar-database":
        dados = cmd_criar_database(args, client_factory=client_factory)
    elif comando == "importar-planilha":
        dados = cmd_importar_planilha(args, client_factory=client_factory)
    elif comando == "anexar-arquivo":
        dados = cmd_anexar_arquivo(args, client_factory=client_factory)
    elif comando == "aparencia":
        dados = cmd_aparencia(args, client_factory=client_factory)
    elif comando == "mover-pagina":
        dados = cmd_mover_pagina(args, client_factory=client_factory)
    elif comando == "mover-database":
        dados = cmd_mover_database(args, client_factory=client_factory)
    elif comando == "renomear-database":
        dados = cmd_renomear_database(args, client_factory=client_factory)
    else:
        raise CLIError(f"Comando desconhecido: {comando}")
    return dados


def _garantir_saida_utf8() -> None:
    """Evita ``UnicodeEncodeError`` em consoles Windows (cp1252).

    Páginas do Notion trazem setas, emojis e travessões que o cp1252 não
    representa; reconfigura stdout/stderr para UTF-8 com substituição, para a
    saída nunca derrubar o comando por causa de um caractere.
    """

    for fluxo in (sys.stdout, sys.stderr):
        reconfigure = getattr(fluxo, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _garantir_saida_utf8()
    codigo, saida = executar(argv)
    if isinstance(saida, dict):
        print(_json(saida))
    else:
        print(saida)
    return codigo
