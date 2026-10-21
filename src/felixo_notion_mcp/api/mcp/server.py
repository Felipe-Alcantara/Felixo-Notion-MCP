"""Servidor MCP — expoe as capacidades de Notion como ferramentas MCP.

Cada ferramenta e um involucro fino sobre os casos de uso de
``services.tarefas``.  O Felixo-AI-Core consome estas ferramentas via MCP
(stdio) para que agentes leiam e editem tarefas sem acessar o Notion
diretamente.

Guarda-corpos
~~~~~~~~~~~~~
- Ferramentas de escrita sinalizam ``readOnlyHint=False`` e
  ``openWorldHint=True`` — o cliente (Felixo-AI-Core) decide se pede
  confirmacao com base no seu catalogo (``requiresConfirmation``).
- ``notion.delete_block`` e destrutiva e sinaliza ``destructiveHint=True``;
  o host deve exigir confirmacao antes de executar.
- Segredos (token, database ID) vem do ambiente, nunca hardcoded.

A ``TaskList`` e criada diretamente de ``domain.tasks`` (sem Django),
e **injetada** nas funcoes de ``services.tarefas`` — o mesmo padrao de DI
que os testes usam.

Uso::

    notion-automacoes-mcp                   # stdio (padrao — Felixo-AI-Core spawna assim)
    notion-automacoes-mcp --transport streamable-http  # debug HTTP local
    python3 -m felixo_notion_mcp.api.mcp.server        # o mesmo, sem o executavel
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from felixo_notion_mcp import (
    NotionAPIError,
    NotionClient,
    NotionConfigurationError,
    NotionHTTPError,
    TaskList,
    __version__,
)
from felixo_notion_mcp.core.config import carregar_env_file

# Carrega ``.env`` (se existir) para resolver token e database ID.
carregar_env_file()

# ---------------------------------------------------------------------------
# Anotacoes reutilizaveis (MCP spec 2025-03-26)
# ---------------------------------------------------------------------------

# No Python os campos são snake_case (SDK mcp 2.x); no fio continuam camelCase
# (``readOnlyHint``...), que é o que o host lê.
_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
_CREATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
_UPDATE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
_DELETE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=True,
)

_T = TypeVar("_T")
Transport = Literal["stdio", "streamable-http"]

# ---------------------------------------------------------------------------
# Servidor MCP
# ---------------------------------------------------------------------------

mcp = MCPServer(
    "notion",
    # Sem isto o SDK 2.x anuncia versão vazia no ``serverInfo`` (o 1.x anunciava a
    # versão do próprio SDK, não a deste pacote).
    version=__version__,
    instructions=(
        "Ferramentas para gerenciar tarefas e conteudo no Notion. "
        "REGRA DO LINK: ao receber um link/ID do Notion, LEIA e entenda do que "
        "se trata (notion.read_page_content) ANTES de qualquer escrita; se for "
        "um database, o trabalho e nas LINHAS (notion.list_database_rows, "
        "localizar a linha certa e atualiza-la) — nunca ignorar o database e "
        "escrever blocos soltos abaixo dele. REGRA DE LEITURA: propriedades e "
        "corpo sao partes da mesma pagina; leia primeiro as propriedades, "
        "depois o corpo. "
        "Ferramentas de escrita (notion.create_task, notion.move_status, "
        "notion.conclude_task, notion.append_content, notion.edit_block) e "
        "atualizacao de projetos (notion.update_project_page) requerem "
        "confirmacao: o cliente so deve executa-las depois que o usuario "
        "confirmar a operacao. A ferramenta destrutiva notion.delete_block "
        "(destructiveHint) apaga conteudo e exige confirmacao explicita."
    ),
)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _criar_notion_client() -> NotionClient:
    """Cria um cliente Notion direto do ambiente (sem Django)."""

    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise NotionConfigurationError(
            "NOTION_TOKEN nao configurado. Defina a variavel de ambiente ou "
            "use o .env na raiz do projeto."
        )
    return NotionClient(token=token)


def _criar_tasklist() -> TaskList:
    """Cria uma ``TaskList`` direto do ambiente (sem Django)."""

    db_id = os.environ.get("NOTION_DATABASE_ID", "").strip()
    if not db_id:
        raise NotionConfigurationError(
            "NOTION_DATABASE_ID nao configurado. Defina a variavel de ambiente "
            "ou use o .env na raiz do projeto."
        )
    return TaskList(_criar_notion_client(), db_id)


def _tarefa_dict(tarefa: Any) -> dict[str, Any]:
    """Serializa uma ``Tarefa`` para dict (mesmo contrato da API REST)."""

    return {
        "id": tarefa.id,
        "nome": tarefa.nome,
        "status": tarefa.status,
        "prazo": tarefa.prazo,
        "url": tarefa.url,
    }


def _projeto_dict(projeto: Any) -> dict[str, Any]:
    """Serializa a referência pública de uma página de projeto."""

    return {"id": projeto.id, "url": projeto.url}


def _resumo_inventario_dict(resumo: Any) -> dict[str, Any]:
    """Serializa o resumo do inventário GitHub para MCP/REST."""

    return {
        "repos_encontrados": resumo.repos_encontrados,
        "paginas_criadas": resumo.paginas_criadas,
        "paginas_atualizadas": resumo.paginas_atualizadas,
        "paginas_puladas": resumo.paginas_puladas,
        "readmes_escritos": resumo.readmes_escritos,
        "readmes_atualizados": resumo.readmes_atualizados,
        "erros": resumo.erros,
    }


def _texto_obrigatorio(valor: str, campo: str) -> str:
    """Normaliza uma entrada textual obrigatoria da borda MCP."""

    normalizado = valor.strip()
    if not normalizado:
        raise ValueError(f"'{campo}' e obrigatorio")
    return normalizado


def _texto_opcional(valor: str | None) -> str | None:
    """Normaliza uma entrada textual opcional; vazio vira ``None``."""

    if valor is None:
        return None
    return valor.strip() or None


def _inteiro_nao_negativo(valor: int, campo: str) -> int:
    """Valida uma contagem inteira da borda MCP."""

    if valor < 0:
        raise ValueError(f"'{campo}' nao pode ser negativo")
    return valor


class EntradaInvalidaError(ToolError, ValueError):
    """Entrada recusada pela borda MCP; o modelo le o motivo e corrige a chamada."""


class FalhaDaFerramentaError(ToolError, RuntimeError):
    """Falha prevista (Notion indisponivel, configuracao ausente) com mensagem segura."""


def _executar(acao: Callable[[], _T]) -> _T:
    """Executa uma ferramenta sem expor detalhes internos ou do provedor.

    Falha prevista sai como ``ToolError``: o SDK ``mcp`` 2.x so entrega ao modelo a
    mensagem de um ``ToolError``. Qualquer outra excecao o SDK trata como queda:
    registra o traceback no servidor e o modelo ve apenas que a ferramenta falhou.
    """

    try:
        return acao()
    except ValueError as exc:
        raise EntradaInvalidaError(str(exc)) from exc
    except NotionHTTPError as exc:
        if exc.status_code == 404:
            raise FalhaDaFerramentaError("Tarefa nao encontrada.") from exc
        raise FalhaDaFerramentaError("Falha ao falar com o Notion.") from exc
    except NotionAPIError as exc:
        raise FalhaDaFerramentaError("Falha ao falar com o Notion.") from exc
    except NotionConfigurationError as exc:
        raise FalhaDaFerramentaError("Servidor MCP nao configurado corretamente.") from exc
    except Exception as exc:
        raise RuntimeError("Erro interno inesperado no servidor MCP.") from exc


# ---------------------------------------------------------------------------
# Ferramentas MCP
# ---------------------------------------------------------------------------


@mcp.tool(name="notion.list_tasks", annotations=_READ)
def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
    """Lista tarefas do Notion, opcionalmente filtrando por status.

    Ferramenta de leitura (read) — nao modifica dados.

    Args:
        status: Nome da etapa para filtrar (ex.: "Entrada").
                Se omitido, lista todas.

    Returns:
        Lista de tarefas com id, nome, status, prazo e url.
    """

    from felixo_notion_mcp.services import tarefas as svc

    def _listar() -> list[dict[str, Any]]:
        tl = _criar_tasklist()
        tarefas = svc.listar_tarefas(status=_texto_opcional(status), tasklist=tl)
        return [_tarefa_dict(t) for t in tarefas]

    return _executar(_listar)


@mcp.tool(name="notion.create_task", annotations=_CREATE)
def create_task(
    nome: str,
    status: str | None = None,
    prazo: str | None = None,
) -> dict[str, Any]:
    """Cria uma nova tarefa no Notion.

    Ferramenta de escrita (write) — requer confirmacao do usuario.

    Args:
        nome: Titulo da tarefa (obrigatorio).
        status: Etapa inicial (ex.: "Entrada"). Opcional.
        prazo: Data no formato AAAA-MM-DD. Opcional.

    Returns:
        A tarefa criada com id, nome, status, prazo e url.
    """

    from felixo_notion_mcp.services import tarefas as svc

    def _criar() -> dict[str, Any]:
        nome_normalizado = _texto_obrigatorio(nome, "nome")
        tl = _criar_tasklist()
        tarefa = svc.criar_tarefa(
            nome_normalizado,
            status=_texto_opcional(status),
            prazo=_texto_opcional(prazo),
            tasklist=tl,
        )
        return _tarefa_dict(tarefa)

    return _executar(_criar)


@mcp.tool(name="notion.move_status", annotations=_UPDATE)
def move_status(task_id: str, status: str) -> dict[str, Any]:
    """Move uma tarefa para outro status no Notion.

    Ferramenta de escrita (write) — requer confirmacao do usuario.

    Args:
        task_id: ID da tarefa no Notion.
        status: Nova etapa (ex.: "Assim que possível").

    Returns:
        A tarefa atualizada com id, nome, status, prazo e url.
    """

    from felixo_notion_mcp.services import tarefas as svc

    def _mover() -> dict[str, Any]:
        task_id_normalizado = _texto_obrigatorio(task_id, "task_id")
        status_normalizado = _texto_obrigatorio(status, "status")
        tl = _criar_tasklist()
        tarefa = svc.mover_status(
            task_id_normalizado,
            status_normalizado,
            tasklist=tl,
        )
        return _tarefa_dict(tarefa)

    return _executar(_mover)


@mcp.tool(name="notion.conclude_task", annotations=_UPDATE)
def conclude_task(task_id: str, status_concluido: str) -> dict[str, Any]:
    """Conclui uma tarefa no Notion com o status de conclusao informado.

    Ferramenta de escrita (write) — requer confirmacao do usuario.

    Args:
        task_id: ID da tarefa no Notion.
        status_concluido: Nome da etapa que representa conclusão.
                          (ex.: "Concluída").

    Returns:
        A tarefa concluida com id, nome, status, prazo e url.
    """

    from felixo_notion_mcp.services import tarefas as svc

    def _concluir() -> dict[str, Any]:
        task_id_normalizado = _texto_obrigatorio(task_id, "task_id")
        status_normalizado = _texto_obrigatorio(status_concluido, "status_concluido")
        tl = _criar_tasklist()
        tarefa = svc.concluir_tarefa(
            task_id_normalizado,
            status_normalizado,
            tasklist=tl,
        )
        return _tarefa_dict(tarefa)

    return _executar(_concluir)


@mcp.tool(name="notion.update_project_page", annotations=_UPDATE)
def update_project_page(
    page_id: str,
    nome_completo: str,
    descricao: str | None = None,
    url_html: str | None = None,
    homepage: str | None = None,
    linguagem: str | None = None,
    topicos: list[str] | None = None,
    estrelas: int = 0,
    forks: int = 0,
    privado: bool = False,
    atualizado_em: str | None = None,
) -> dict[str, Any]:
    """Atualiza uma página de projeto com metadados normalizados do GitHub.

    Ferramenta de escrita idempotente — requer confirmacao do usuario.
    """

    from felixo_notion_mcp.integrations.github import RepoInfo
    from felixo_notion_mcp.services import projetos as svc

    def _atualizar() -> dict[str, Any]:
        page_id_normalizado = _texto_obrigatorio(page_id, "page_id")
        nome_normalizado = _texto_obrigatorio(nome_completo, "nome_completo")
        repo = RepoInfo(
            nome=nome_normalizado.rsplit("/", 1)[-1],
            nome_completo=nome_normalizado,
            descricao=_texto_opcional(descricao),
            url_html=_texto_opcional(url_html),
            homepage=_texto_opcional(homepage),
            linguagem=_texto_opcional(linguagem),
            topicos=[
                topico_normalizado
                for topico in (topicos or [])
                if (topico_normalizado := topico.strip())
            ],
            estrelas=_inteiro_nao_negativo(estrelas, "estrelas"),
            forks=_inteiro_nao_negativo(forks, "forks"),
            privado=privado,
            atualizado_em=_texto_opcional(atualizado_em),
        )
        projeto = svc.atualizar_pagina_projeto(
            page_id_normalizado,
            repo,
            notion_client=_criar_notion_client(),
        )
        return _projeto_dict(projeto)

    return _executar(_atualizar)


@mcp.tool(name="notion.update_github_inventory", annotations=_UPDATE)
def update_github_inventory(
    contas: list[str],
    database_id: str | None = None,
    sem_readme: bool = False,
    sem_arquivados: bool = False,
    apenas_mudancas: bool = False,
) -> dict[str, Any]:
    """Re-sincroniza o database GITHUB com propriedades e README.

    Ferramenta de escrita idempotente — requer confirmacao do usuario.

    Args:
        contas: Contas GitHub, handles ou URLs de perfil.
        database_id: Database de destino. Se omitido, usa NOTION_DATABASE_ID.
        sem_readme: Quando verdadeiro, atualiza so propriedades.
        sem_arquivados: Quando verdadeiro, ignora repositorios arquivados.
        apenas_mudancas: Quando verdadeiro, pula paginas existentes sem mudanca.
    """

    from felixo_notion_mcp.integrations.github import GitHubClient
    from felixo_notion_mcp.services import inventario_github as svc

    def _atualizar() -> dict[str, Any]:
        contas_limpas = [conta.strip() for conta in contas if conta and conta.strip()]
        if not contas_limpas:
            raise ValueError("'contas' e obrigatorio")
        db_id = _texto_opcional(database_id) or os.environ.get("NOTION_DATABASE_ID", "").strip()
        if not db_id:
            raise ValueError("'database_id' e obrigatorio")
        resumo = svc.atualizar_repos(
            contas_limpas,
            db_id,
            github_client=GitHubClient(),
            notion_client=_criar_notion_client(),
            sincronizar_readme=not sem_readme,
            ignorar_arquivados=sem_arquivados,
            apenas_mudancas=apenas_mudancas,
        )
        return _resumo_inventario_dict(resumo)

    return _executar(_atualizar)


@mcp.tool(name="notion.search", annotations=_READ)
def search(query: str | None = None) -> list[dict[str, str]]:
    """Pesquisa paginas e databases visiveis a integracao no Notion.

    Ferramenta de leitura (read) — nao modifica dados.

    Args:
        query: Texto para casar com o titulo. Se omitido, lista tudo o que e
               visivel a integracao.

    Returns:
        Lista de itens com id, tipo (page/database), titulo e url.
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _buscar() -> list[dict[str, str]]:
        return svc.buscar(_texto_opcional(query), cliente=_criar_notion_client())

    return _executar(_buscar)


@mcp.tool(name="notion.read_page_content", annotations=_READ)
def read_page_content(page_id: str) -> dict[str, str]:
    """Le uma pagina completa do Notion: propriedades PRIMEIRO, depois o corpo.

    Ferramenta de leitura (read) — nao modifica dados. Propriedades e corpo sao
    partes da MESMA pagina; comece a leitura pelas ``propriedades`` (ha paginas
    com mais informacao nas colunas do que no corpo) e so entao leia o
    ``markdown``. Se o resultado indicar ``tipo: database``, o alvo e um
    database: trabalhe nas LINHAS (localize a certa e atualize-a) em vez de
    escrever blocos soltos abaixo dele.

    Args:
        page_id: ID da pagina cujo conteudo sera lido.

    Returns:
        Um dict com ``id``, ``tipo``, ``propriedades`` (coluna -> valor
        preenchido) e ``markdown`` (vazio se a pagina nao tiver corpo); para
        databases, ``linhas`` no lugar de ``propriedades``.
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _ler() -> dict[str, Any]:
        page_id_normalizado = _texto_obrigatorio(page_id, "page_id")
        resultado = svc.ler_pagina_ou_database(page_id_normalizado, cliente=_criar_notion_client())
        if resultado["tipo"] == "database":
            # Borda acrescenta o aviso voltado a quem consome o MCP.
            resultado["aviso"] = "Isto e um database: use notion.list_database_rows."
        return resultado

    return _executar(_ler)


@mcp.tool(name="notion.list_database_rows", annotations=_READ)
def list_database_rows(database_id: str) -> dict[str, Any]:
    """Lista as linhas (paginas) de um database do Notion.

    Ferramenta de leitura (read) — nao modifica dados. Resolve os *data sources*
    do database (modelo novo do Notion) e devolve as linhas normalizadas. Use
    quando notion.read_page_content indicar que o ID e um database.

    Args:
        database_id: ID do database.

    Returns:
        Um dict com ``id`` e ``linhas`` (cada uma com id, titulo e url). A lista
        vem vazia se o database nao tiver data source acessivel a integracao.
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _listar() -> dict[str, Any]:
        database_id_normalizado = _texto_obrigatorio(database_id, "database_id")
        linhas = svc.listar_linhas(database_id_normalizado, cliente=_criar_notion_client())
        return {"id": database_id_normalizado, "linhas": linhas}

    return _executar(_listar)


@mcp.tool(name="notion.clone_database", annotations=_CREATE)
def clone_database(
    database_id: str,
    titulo: str | None = None,
    pagina_destino: str | None = None,
    com_linhas: bool = False,
    relacoes: str = "auto-novo",
) -> dict[str, Any]:
    """Clona um database com todas as propriedades, sem vinculo com a origem.

    Ferramenta de escrita (write) — requer confirmacao do usuario. Replica o
    schema completo (status, select, relacoes) num database novo. Relacoes que a
    origem fazia consigo mesma viram auto-relacoes do clone; relacoes para outros
    databases sao preservadas. Opcionalmente copia as linhas.

    Args:
        database_id: ID do database de origem.
        titulo: Titulo do clone (padrao: ``"<origem> (copia)"``).
        pagina_destino: ID da pagina onde criar o clone (padrao: a pai da origem).
        com_linhas: Quando verdadeiro, copia tambem as linhas da origem.
        relacoes: ``"auto-novo"`` (padrao) ou ``"texto"`` (relacoes viram texto).

    Returns:
        Um dict com ``id``, ``data_source_id``, ``titulo``, ``propriedades`` e
        ``linhas_copiadas``.
    """

    from felixo_notion_mcp.services import clonagem as svc

    def _clonar() -> dict[str, Any]:
        database_id_normalizado = _texto_obrigatorio(database_id, "database_id")
        return svc.clonar_database(
            database_id_normalizado,
            titulo=(titulo or "").strip() or None,
            pagina_destino=(pagina_destino or "").strip() or None,
            com_linhas=com_linhas,
            relacoes=relacoes,
            cliente=_criar_notion_client(),
        )

    return _executar(_clonar)


@mcp.tool(name="notion.append_content", annotations=_CREATE)
def append_content(page_id: str, markdown: str) -> dict[str, Any]:
    """Anexa conteudo (em Markdown) ao final de uma pagina do Notion.

    Ferramenta de escrita (write) — requer confirmacao do usuario.

    Args:
        page_id: ID da pagina que recebera o conteudo.
        markdown: Texto em Markdown a anexar (titulos, listas, codigo, etc.).

    Returns:
        Um dict com ``id`` e ``blocos_anexados`` (quantidade de blocos criados).
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _anexar() -> dict[str, Any]:
        page_id_normalizado = _texto_obrigatorio(page_id, "page_id")
        conteudo = _texto_obrigatorio(markdown, "markdown")
        total = svc.escrever_conteudo(page_id_normalizado, conteudo, cliente=_criar_notion_client())
        return {"id": page_id_normalizado, "blocos_anexados": total}

    return _executar(_anexar)


@mcp.tool(name="notion.edit_block", annotations=_UPDATE)
def edit_block(block_id: str, markdown: str) -> dict[str, Any]:
    """Substitui o texto de um bloco existente por uma linha de Markdown.

    Ferramenta de escrita idempotente — requer confirmacao do usuario.

    Args:
        block_id: ID do bloco a editar.
        markdown: Nova linha de conteudo, em Markdown.

    Returns:
        Um dict com ``id`` e ``editado`` (True).
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _editar() -> dict[str, Any]:
        block_id_normalizado = _texto_obrigatorio(block_id, "block_id")
        conteudo = _texto_obrigatorio(markdown, "markdown")
        svc.editar_bloco(block_id_normalizado, conteudo, cliente=_criar_notion_client())
        return {"id": block_id_normalizado, "editado": True}

    return _executar(_editar)


@mcp.tool(name="notion.delete_block", annotations=_DELETE)
def delete_block(block_id: str) -> dict[str, Any]:
    """Apaga (arquiva) um bloco do Notion. DESTRUTIVO — requer confirmacao.

    A anotacao ``destructiveHint`` sinaliza ao cliente que esta operacao remove
    conteudo; o cliente so deve executa-la apos confirmacao explicita do usuario.

    Args:
        block_id: ID do bloco a apagar.

    Returns:
        Um dict com ``id`` e ``apagado`` (True).
    """

    from felixo_notion_mcp.services import conteudo as svc

    def _apagar() -> dict[str, Any]:
        block_id_normalizado = _texto_obrigatorio(block_id, "block_id")
        svc.excluir_bloco(block_id_normalizado, cliente=_criar_notion_client())
        return {"id": block_id_normalizado, "apagado": True}

    return _executar(_apagar)


@mcp.tool(name="notion.create_database", annotations=_CREATE)
def create_database(
    pagina_id: str,
    titulo: str,
    propriedades: dict[str, str] | None = None,
    is_inline: bool = False,
    icone: str | None = None,
    descricao: str | None = None,
    prefixo_id: str | None = None,
) -> dict[str, Any]:
    """Cria um database numa pagina, com schema tipado.

    Ferramenta de escrita (write) — requer confirmacao do usuario.

    Args:
        pagina_id: ID da pagina que recebe o database.
        titulo: Titulo do database.
        propriedades: Mapeamento ``coluna -> tipo`` (titulo, texto, numero,
            data, select, multi_select, checkbox, email, url, telefone,
            pessoas, arquivos). Sem coluna 'titulo', uma propriedade "Nome"
            e criada automaticamente.
        is_inline: Cria embutido no corpo da pagina.
        icone: Emoji usado como icone.
        descricao: Descricao do database.
        prefixo_id: Cria propriedade "ID" (unique_id) com este prefixo —
            o prefixo e unico por workspace.

    Returns:
        Um dict com ``id``, ``titulo``, ``url`` e ``propriedades``.
    """

    from felixo_notion_mcp.domain import properties as starter_properties

    def _criar() -> dict[str, Any]:
        pagina = _texto_obrigatorio(pagina_id, "pagina_id")
        titulo_normalizado = _texto_obrigatorio(titulo, "titulo")
        schema: dict[str, dict[str, object]] = {}
        for nome, tipo in (propriedades or {}).items():
            schema[nome] = starter_properties.schema_propriedade(tipo)
        if not any("title" in fragmento for fragmento in schema.values()):
            schema["Nome"] = starter_properties.schema_propriedade("titulo")
        resultado = _criar_notion_client().criar_database(
            pagina,
            titulo_normalizado,
            schema,
            is_inline=is_inline,
            icone=_texto_opcional(icone),
            descricao=_texto_opcional(descricao),
            prefixo_id=_texto_opcional(prefixo_id),
        )
        return {
            "id": resultado.get("id", ""),
            "titulo": titulo_normalizado,
            "url": resultado.get("url"),
            "propriedades": sorted(schema),
        }

    return _executar(_criar)


@mcp.tool(name="notion.import_spreadsheet", annotations=_CREATE)
def import_spreadsheet(
    database_id: str,
    caminho: str,
    aba: str | None = None,
    coluna_titulo: str | None = None,
    tipos: dict[str, str] | None = None,
    renomear: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Importa uma planilha local (.xlsx/.csv) para um database do Notion.

    Ferramenta de escrita (write) — requer confirmacao do usuario. O import e
    idempotente: cada linha faz upsert pela propriedade "Origem"
    (arquivo:linha), entao reexecutar atualiza em vez de duplicar.

    Args:
        database_id: Database de destino.
        caminho: Arquivo .xlsx (requer openpyxl) ou .csv local.
        aba: Aba do .xlsx (padrao: a ativa).
        coluna_titulo: Coluna usada como titulo da linha (padrao: a primeira).
        tipos: Mapeamento ``coluna -> tipo`` (numero, data, select, checkbox,
            email, url, telefone; padrao: texto). Numeros e datas aceitam o
            formato brasileiro; valores invalidos vao para "Observações".
        renomear: Mapeamento ``coluna -> nome da propriedade`` no Notion.

    Returns:
        Um dict com ``criados``, ``atualizados``, ``erros`` e
        ``itens_processados``.
    """

    from felixo_notion_mcp.services import ingestao as svc

    def _importar() -> dict[str, Any]:
        db = _texto_obrigatorio(database_id, "database_id")
        fonte = svc.FontePlanilha(
            _texto_obrigatorio(caminho, "caminho"),
            aba=_texto_opcional(aba),
            coluna_titulo=_texto_opcional(coluna_titulo),
            tipos=tipos or {},
            renomear=renomear or {},
        )
        resultado = svc.ingerir(fonte, client=_criar_notion_client(), database_id=db)
        return {
            "database_id": db,
            "criados": resultado.criados,
            "atualizados": resultado.atualizados,
            "erros": resultado.erros,
            "itens_processados": resultado.itens_processados,
        }

    return _executar(_importar)


@mcp.tool(name="notion.upload_file", annotations=_CREATE)
def upload_file(
    page_id: str,
    caminho: str,
    propriedade: str = "Arquivos e mídia",
    substituir: bool = False,
) -> dict[str, Any]:
    """Sobe um arquivo local (ate 20 MB) e anexa numa propriedade de arquivos.

    Ferramenta de escrita (write) — requer confirmacao do usuario. Por padrao
    o anexo e acrescentado aos existentes, sem apagar nada.

    Args:
        page_id: Linha de database que recebe o anexo.
        caminho: Arquivo local a subir.
        propriedade: Nome da propriedade de arquivos (padrao: "Arquivos e mídia").
        substituir: Troca os anexos existentes em vez de acrescentar.

    Returns:
        Um dict com ``upload_id``, ``arquivo`` e ``total_anexos``.
    """

    from felixo_notion_mcp.services import anexos as svc

    def _anexar() -> dict[str, Any]:
        return svc.anexar_arquivo(
            _texto_obrigatorio(page_id, "page_id"),
            _texto_obrigatorio(caminho, "caminho"),
            propriedade=_texto_opcional(propriedade) or "Arquivos e mídia",
            substituir=substituir,
            cliente=_criar_notion_client(),
        )

    return _executar(_anexar)


@mcp.tool(name="notion.move_page", annotations=_UPDATE)
def move_page(
    page_id: str,
    novo_pai_id: str,
    tipo_pai: str = "page_id",
) -> dict[str, Any]:
    """Move (re-parenteia) uma pagina para outra pagina ou database.

    Ferramenta de escrita idempotente — requer confirmacao do usuario.
    ATENCAO: mover uma pagina que CONTEM databases e aceito pela API mas
    silenciosamente ignorado; nesse caso use notion.move_database em cada
    database e descarte a pagina vazia.

    Args:
        page_id: ID da pagina a mover.
        novo_pai_id: ID do novo pai.
        tipo_pai: ``"page_id"`` (padrao) ou ``"database_id"``.

    Returns:
        Um dict com ``id``, ``novo_pai`` e ``tipo_pai``.
    """

    def _mover() -> dict[str, Any]:
        pagina = _texto_obrigatorio(page_id, "page_id")
        destino = _texto_obrigatorio(novo_pai_id, "novo_pai_id")
        _criar_notion_client().mover_pagina(pagina, destino, tipo_pai=tipo_pai)
        return {"id": pagina, "novo_pai": destino, "tipo_pai": tipo_pai}

    return _executar(_mover)


@mcp.tool(name="notion.move_database", annotations=_UPDATE)
def move_database(database_id: str, novo_pai_id: str) -> dict[str, Any]:
    """Move (re-parenteia) um database inteiro para outra pagina.

    Ferramenta de escrita idempotente — requer confirmacao do usuario.

    Args:
        database_id: ID do database a mover.
        novo_pai_id: ID da pagina que recebera o database.

    Returns:
        Um dict com ``id`` e ``novo_pai``.
    """

    def _mover() -> dict[str, Any]:
        db = _texto_obrigatorio(database_id, "database_id")
        destino = _texto_obrigatorio(novo_pai_id, "novo_pai_id")
        _criar_notion_client().mover_database(db, destino)
        return {"id": db, "novo_pai": destino}

    return _executar(_mover)


# ---------------------------------------------------------------------------
# Views e Registro diário
# ---------------------------------------------------------------------------


@mcp.tool(name="notion.sort_view", annotations=_UPDATE)
def sort_view(
    database_id: str,
    propriedade: str,
    direcao: str = "desc",
    view_id: str | None = None,
    nome: str | None = None,
) -> dict[str, Any]:
    """Ordena uma view de database por uma propriedade (Views API) e confere por releitura.

    Ferramenta de escrita idempotente — requer confirmação do usuário. Substitui a
    ordenação anterior. Sem ``view_id``, usa a primeira view de tabela do database.
    ``direcao``: ``desc``/``decrescente`` ou ``asc``/``crescente``.
    """

    from felixo_notion_mcp.services import views as svc

    def _ordenar() -> dict[str, Any]:
        return svc.ordenar_view(
            _texto_obrigatorio(database_id, "database_id"),
            _texto_obrigatorio(propriedade, "propriedade"),
            direcao,
            view_id=_texto_opcional(view_id),
            nome=_texto_opcional(nome),
            cliente=_criar_notion_client(),
        ).para_dict()

    return _executar(_ordenar)


@mcp.tool(name="notion.ensure_daily_log_day", annotations=_CREATE)
def ensure_daily_log_day(
    database_id: str,
    data: str,
    status: str = "Aberto",
    valores: dict[str, str] | None = None,
    conteudo: str | None = None,
) -> dict[str, Any]:
    """Cria a linha de um dia no Registro diário só se ela não existir (nunca duplica).

    Ferramenta de escrita — requer confirmação do usuário. ``data`` em ``AAAA-MM-DD``.
    O título vira ``DD-MM-AAAA``; ``valores`` são outras colunas com informação real
    (nunca invente rotina); ``conteudo`` é o corpo em Markdown, escrito depois das
    propriedades. Se o dia já existe, nada muda e ``criado`` volta ``False``.
    """

    from datetime import date

    from felixo_notion_mcp.services import registro_diario as svc

    def _garantir() -> dict[str, Any]:
        return svc.garantir_dia(
            _texto_obrigatorio(database_id, "database_id"),
            date.fromisoformat(_texto_obrigatorio(data, "data")),
            status=_texto_obrigatorio(status, "status"),
            valores=valores or {},
            conteudo=_texto_opcional(conteudo),
            cliente=_criar_notion_client(),
        )

    return _executar(_garantir)


@mcp.tool(name="notion.carry_over_daily_log", annotations=_CREATE)
def carry_over_daily_log(
    database_id: str,
    data: str,
    origem_id: str | None = None,
    status: str = "Aberto",
    valores: dict[str, str] | None = None,
    fecho: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cria o dia no Registro diário levando as tarefas não concluídas do dia anterior.

    Ferramenta de escrita — requer confirmação do usuário (``dry_run`` só mostra a
    prévia). ``data`` em ``AAAA-MM-DD``; a origem é ``origem_id`` ou o último dia
    registrado antes. Tarefa pendente vai inteira (passos e notas), bloco a bloco;
    concluída fica na origem. ``valores`` são colunas com informação real (nunca
    invente rotina); ``fecho`` é o Markdown depois das tarefas (anotações e resumo).
    Se o dia já existe, nada muda e ``criado`` volta ``False``.
    """

    from datetime import date

    from felixo_notion_mcp.services import registro_diario as svc

    def _levar() -> dict[str, Any]:
        return svc.levar_pendencias(
            _texto_obrigatorio(database_id, "database_id"),
            date.fromisoformat(_texto_obrigatorio(data, "data")),
            origem_id=_texto_opcional(origem_id),
            status=_texto_obrigatorio(status, "status"),
            valores=valores or {},
            fecho=_texto_opcional(fecho),
            dry_run=dry_run,
            cliente=_criar_notion_client(),
        )

    return _executar(_levar)


@mcp.tool(name="notion.estimate_daily_log", annotations=_UPDATE)
def estimate_daily_log(
    database_id: str,
    de: str,
    ate: str,
    autor: str,
    relatorios_id: str | None = None,
    trabalho: list[str] | None = None,
    aplicar: bool = False,
    sobrescrever: bool = False,
) -> dict[str, Any]:
    """Estima horas, hora de acordar, sono e produtividade de cada dia do Registro diário.

    Usa os commits do GitHub de ``autor`` (``GITHUB_TOKEN`` no ambiente para ver
    repositórios privados) e os blocos ``HH:MM–HH:MM`` dos relatórios diários
    (``relatorios_id``). ``trabalho`` são trechos de nome que contam como trabalho; o
    resto conta como projeto pessoal. Sem ``aplicar`` só mostra; com ``aplicar`` grava
    nos campos vazios (escrita — requer confirmação), e ``sobrescrever`` troca também
    os preenchidos. Banho nunca é estimado. Datas em ``AAAA-MM-DD``.
    """

    from datetime import date

    from felixo_notion_mcp.integrations.github import GitHubClient
    from felixo_notion_mcp.services import registro_diario as svc

    def _estimar() -> dict[str, Any]:
        return svc.estimar_periodo(
            _texto_obrigatorio(database_id, "database_id"),
            date.fromisoformat(_texto_obrigatorio(de, "de")),
            date.fromisoformat(_texto_obrigatorio(ate, "ate")),
            autor=_texto_obrigatorio(autor, "autor"),
            github=GitHubClient(),
            relatorios_id=_texto_opcional(relatorios_id),
            trabalho=list(trabalho or []),
            aplicar=aplicar,
            sobrescrever=sobrescrever,
            cliente=_criar_notion_client(),
        )

    return _executar(_estimar)


@mcp.tool(name="notion.import_tasks", annotations=_CREATE)
def import_tasks(
    pasta: str,
    database_id: str,
    so: list[str] | None = None,
    paralelo: int = 4,
    dry_run: bool = False,
    conferir: bool = False,
) -> dict[str, Any]:
    """Grava um lote de rascunhos como tarefas num database, sem duplicar.

    Ferramenta de escrita — requer confirmação do usuário (``dry_run`` só valida e
    mostra o plano). ``pasta`` tem ``<chave>.json`` (``chave``, ``titulo``,
    ``propriedades``, ``relacoes`` com ``alvo``/``coluna``/``motivo``) e ``<chave>.md``
    (o corpo); ``lote.json`` opcional traz as ``propriedades`` comuns. Valida tudo pelo
    schema antes de escrever, pula títulos que já existem, escreve corpo só em página
    vazia, liga as relações nos dois sentidos e escreve "Tarefas relacionadas" nas
    duas pontas. ``conferir`` relê tudo ao fim e devolve ``problemas``.
    """

    from pathlib import Path

    from felixo_notion_mcp.services import importacao_tarefas as svc

    def _importar() -> dict[str, Any]:
        return svc.importar_tarefas(
            svc.carregar_lote(Path(_texto_obrigatorio(pasta, "pasta")), so=so),
            _texto_obrigatorio(database_id, "database_id"),
            paralelo=paralelo,
            dry_run=dry_run,
            conferir=conferir,
            cliente=_criar_notion_client(),
        )

    return _executar(_importar)


# ---------------------------------------------------------------------------
# Biblioteca: aparência, coleta, tradução, PDF, capas e importação
# ---------------------------------------------------------------------------


@mcp.tool(name="notion.set_page_appearance", annotations=_UPDATE)
def set_page_appearance(
    page_id: str, icone: str | None = None, capa: str | None = None, substituir: bool = False
) -> dict[str, Any]:
    """Define o ícone e/ou a capa de uma página (emoji, URL ou imagem local).

    Ferramenta de escrita — requer confirmação do usuário. Ícone ou capa que a página
    já tem são mantidos, a não ser com ``substituir``. Imagem local acima do limite
    de upload sobe comprimida.
    """

    from felixo_notion_mcp.services import aparencia as svc

    def _definir() -> dict[str, Any]:
        return svc.definir_aparencia(
            _texto_obrigatorio(page_id, "page_id"),
            icone=_texto_opcional(icone),
            capa=_texto_opcional(capa),
            substituir=substituir,
            cliente=_criar_notion_client(),
        )

    return _executar(_definir)


@mcp.tool(name="notion.discover_articles", annotations=_READ)
def discover_articles(site: str, usar_pagina_inicial: bool = True) -> dict[str, Any]:
    """Lista os artigos de um site (feed, sitemap e links da página inicial). Leitura."""

    from felixo_notion_mcp.services import coleta

    def _descobrir() -> dict[str, Any]:
        achado = coleta.descobrir_artigos(
            _texto_obrigatorio(site, "site"), usar_pagina_inicial=usar_pagina_inicial
        )
        return {
            "site": achado.site,
            "fontes": achado.fontes,
            "artigos": [vars(item) for item in achado.artigos],
        }

    return _executar(_descobrir)


@mcp.tool(name="notion.extract_article", annotations=_READ)
def extract_article(url: str) -> dict[str, Any]:
    """Baixa uma página e extrai título, data, texto, links e imagens. Leitura."""

    from felixo_notion_mcp.services import coleta

    return _executar(lambda: vars(coleta.coletar_artigo(_texto_obrigatorio(url, "url"))))


@mcp.tool(name="notion.translate_markdown", annotations=_READ)
def translate_markdown(
    texto: str, idioma: str = "português do Brasil", modelo: str | None = None
) -> dict[str, str]:
    """Traduz um Markdown pelo OpenRouter, deixando blocos de código intactos."""

    from felixo_notion_mcp.integrations.openrouter import ProvedorOpenRouter
    from felixo_notion_mcp.services import traducao

    def _traduzir() -> dict[str, str]:
        return {
            "texto": traducao.traduzir_markdown(
                _texto_obrigatorio(texto, "texto"),
                provedor=ProvedorOpenRouter(),
                idioma=idioma,
                modelo=_texto_opcional(modelo),
            )
        }

    return _executar(_traduzir)


@mcp.tool(name="notion.article_to_pdf", annotations=_CREATE)
def article_to_pdf(
    caminho_markdown: str,
    saida_pdf: str,
    url_original: str,
    autor: str,
    licenca: str | None = None,
    pasta_cache_imagens: str | None = None,
) -> dict[str, Any]:
    """Gera o PDF de um Markdown com metadados (Edge/Chrome headless). Cria arquivo local."""

    from pathlib import Path

    from felixo_notion_mcp.integrations import pdf

    def _gerar() -> dict[str, Any]:
        saida = pdf.gerar_pdf(
            Path(_texto_obrigatorio(caminho_markdown, "caminho_markdown")).read_text(
                encoding="utf-8"
            ),
            Path(_texto_obrigatorio(saida_pdf, "saida_pdf")),
            url_original=url_original,
            autor=autor,
            licenca=_texto_opcional(licenca),
            cache_imagens=Path(pasta_cache_imagens) if pasta_cache_imagens else None,
        )
        return {"pdf": str(saida), "bytes": saida.stat().st_size}

    return _executar(_gerar)


@mcp.tool(name="notion.generate_cover", annotations=_CREATE)
def generate_cover(
    titulo: str, subtitulo: str, saida_png: str, estilo: str = "claro"
) -> dict[str, Any]:
    """Desenha uma capa 1500x600 original (tipografia e formas abstratas). Cria arquivo local."""

    from pathlib import Path

    from felixo_notion_mcp.integrations import imagens

    def _gerar() -> dict[str, Any]:
        saida = imagens.gerar_capa(titulo, subtitulo, Path(saida_png), estilo=estilo)
        return {"capa": str(saida), "bytes": saida.stat().st_size}

    return _executar(_gerar)


@mcp.tool(name="notion.import_articles", annotations=_CREATE)
def import_articles(
    pasta_rascunhos: str,
    database_id: str,
    opcoes_livres: list[str] | None = None,
    nao_completar: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Grava rascunhos (``<chave>.json``/``.md``) numa biblioteca sem duplicar nem apagar.

    Ferramenta de escrita — requer confirmação. ``dry_run`` (padrão) só mostra o plano.
    """

    from pathlib import Path

    from felixo_notion_mcp.services import biblioteca

    def _importar() -> dict[str, Any]:
        return biblioteca.importar_artigos(
            biblioteca.carregar_rascunhos(
                Path(_texto_obrigatorio(pasta_rascunhos, "pasta_rascunhos"))
            ),
            _texto_obrigatorio(database_id, "database_id"),
            cliente=_criar_notion_client(),
            opcoes_livres=opcoes_livres or [],
            nao_completar=biblioteca.ler_pares(nao_completar or [], "nao_completar"),
            dry_run=dry_run,
        )

    return _executar(_importar)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


def _resolver_transporte(argv: Sequence[str] | None = None) -> Transport:
    """Resolve o transporte solicitado pela CLI."""

    parser = argparse.ArgumentParser(description="Servidor MCP de tarefas do Notion.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="Transporte MCP (padrao: stdio).",
    )
    args = parser.parse_args(argv)
    return args.transport


def main(argv: Sequence[str] | None = None) -> None:
    """Inicia o servidor no transporte escolhido."""

    mcp.run(transport=_resolver_transporte(argv))


if __name__ == "__main__":
    main()
