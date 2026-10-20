# 🔗 MCP — Ponte com o Felixo-AI-Core

> **O que é este documento**: descreve a camada MCP (Model Context Protocol)
> deste projeto — como as capacidades de Notion são expostas como ferramentas
> que agentes do Felixo-AI-Core consomem.
>
> **MCP e CLI são irmãos.** Ambos são **bordas finas sobre os mesmos `services/`** —
> nenhum reimplementa regra de negócio. O **MCP** serve os agentes do Felixo-AI-Core;
> a **CLI** ([Ciclo 2](AGENTES.md#-ciclo-2--agentes-do-front-rico-cli-e-multi-tabela),
> pasta `src/felixo_notion_mcp/api/cli/`) serve uso direto por linha de
> comando e uma IA local. Quem mexer numa
> operação deve garantir que a regra continue nos `services`, para as duas bordas
> herdarem o mesmo comportamento.

> **Estado em 2026-10-07:** o servidor MCP vive em
> `src/felixo_notion_mcp/api/mcp/server.py`, no pacote único do repositório. Na
> instalação publicada (pacote `notion-workspace-app`) ele é iniciado pela fachada
> `notion-automacoes mcp start`; no checkout, por `felixo-notion-mcp mcp start`.

---

## Visão geral

O [Felixo-AI-Core](https://github.com/Felipe-Alcantara/Felixo-AI-Core) é o
orquestrador de agentes. Este projeto é a **camada de dados do Notion**. A
comunicação entre os dois acontece via **MCP**: este projeto oferece
ferramentas; o Felixo-AI-Core decide qual agente usa qual ferramenta.

```text
┌─────────────────────────────────┐
│  Felixo-AI-Core (orquestrador) │
│  Decide quem faz o que         │
└──────────┬──────────────────────┘
           │ MCP (stdio)
┌──────────▼──────────────────────┐
│  mcp_server.py (este projeto)   │
│  Ferramentas notion.*           │
│  Invólucros sobre services/     │
└──────────┬──────────────────────┘
           │ notion_starter
┌──────────▼──────────────────────┐
│  API do Notion                  │
└─────────────────────────────────┘
```

---

## Ferramentas expostas

| Ferramenta | Acesso | Confirmação | O que faz |
|---|---|---|---|
| `notion.list_tasks` | read | não | Lista tarefas, com filtro opcional por status |
| `notion.create_task` | write | sim | Cria uma nova tarefa |
| `notion.move_status` | write | sim | Move uma tarefa para outro status |
| `notion.conclude_task` | write | sim | Conclui uma tarefa com o status informado |
| `notion.update_project_page` | write | sim | Atualiza metadados de uma página de projeto |
| `notion.search` | read | não | Pesquisa páginas e databases visíveis à integração |
| `notion.read_page_content` | read | não | Lê o conteúdo (corpo) de uma página como Markdown; se o ID for um database, avisa e já traz as linhas |
| `notion.list_database_rows` | read | não | Lista as linhas de um database (resolve *data sources* do modelo novo do Notion) |
| `notion.clone_database` | write | sim | Clona um database com todas as propriedades, sem vínculo com a origem (auto-relações apontam pro clone, externas são preservadas; copia linhas opcionalmente) |
| `notion.append_content` | write | sim | Anexa conteúdo (Markdown) ao final de uma página |
| `notion.edit_block` | write | sim | Substitui o texto de um bloco existente |
| `notion.delete_block` | **delete** | **sim** | Apaga (arquiva) um bloco — **destrutivo** |

As ferramentas de tarefas/projetos cobrem as **propriedades**; as de conteúdo
(`search`, `read_page_content`, `append_content`, `edit_block`, `delete_block`)
dão acesso ao **corpo** das páginas — qualquer página visível à integração, não
só os databases configurados. Assim a IA pesquisa, lê notas, escreve e edita
conteúdo, e — com confirmação — apaga blocos.

Cada ferramenta é um invólucro fino sobre os casos de uso de
`services/tarefas.py`, `services/projetos.py` e `services/conteudo.py` (em
`src/felixo_notion_mcp/`) — não reimplementa regra de negócio. Entradas
textuais obrigatórias são validadas na borda MCP e erros internos/upstream são
sanitizados.

### Anotações MCP

As ferramentas declaram anotações MCP:

- **read** (`notion.list_tasks`): `readOnlyHint=True`, `destructiveHint=False`,
  `openWorldHint=True`
- **create** (`notion.create_task`): `readOnlyHint=False`, `destructiveHint=False`,
  `idempotentHint=False`, `openWorldHint=True`
- **update** (`notion.move_status`, `notion.conclude_task`,
  `notion.update_project_page` e `notion.edit_block`):
  `readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=True`,
  `openWorldHint=True`
- **read** (`notion.search`, `notion.read_page_content`,
  `notion.list_database_rows`): `readOnlyHint=True`, `destructiveHint=False`,
  `openWorldHint=True`
- **create** (`notion.append_content`): `readOnlyHint=False`,
  `destructiveHint=False`, `idempotentHint=False`, `openWorldHint=True`
- **delete** (`notion.delete_block`): `readOnlyHint=False`,
  **`destructiveHint=True`**, `idempotentHint=True`, `openWorldHint=True` — o
  host deve sempre confirmar antes de executar

Essas anotações são apenas **hints do protocolo**. A confirmação obrigatória é
responsabilidade do host: o catálogo do Felixo-AI-Core deve registrar toda ferramenta
`write` com `requiresConfirmation: true`.

---

## Como rodar

### CLI irmã

A CLI do Ciclo 2 fica em `src/felixo_notion_mcp/api/cli/` e usa os mesmos casos de uso de
`src/felixo_notion_mcp/services/tarefas.py`. Ela é útil quando uma IA local ou script quer uma
saída JSON estável sem subir servidor MCP:

```bash
notion-automacoes --json tasks listar
notion-automacoes --json tasks criar "Nova tarefa" --status "Entrada"
notion-automacoes --json tasks editar <task_id> --status "Assim que possível"
notion-automacoes --json tasks opcoes
notion-automacoes --json tasks mapear
```

Contrato de saída:

```json
{ "ok": true, "dados": {} }
```

Em erro:

```json
{ "ok": false, "erro": { "mensagem": "..." } }
```

### Pré-requisitos

```bash
pipx install "notion-automacoes[app]"  # uso público
# ou, pelo checkout deste repositório:
uv sync --locked --all-extras
```

### Variáveis de ambiente

O servidor MCP lê do ambiente (ou do `.env` na raiz):

| Variável | Obrigatória | Descrição |
|---|---|---|
| `NOTION_TOKEN` | sim | Token de integração do Notion |
| `NOTION_DATABASE_ID` | sim | ID do database de tarefas |

### Execução

```bash
# Instalação pública: stdio (padrão — o Felixo-AI-Core spawna assim)
notion-automacoes mcp start

# Checkout deste repositório:
uv run felixo-notion-mcp mcp start
# ou direto pelo módulo do servidor:
uv run python -m felixo_notion_mcp.api.mcp.server

# Streamable HTTP para debug local (endpoint http://127.0.0.1:8000/mcp)
uv run python -m felixo_notion_mcp.api.mcp.server --transport streamable-http
```

Ou pelo menu interativo:

```bash
python start_app.py
# → "Subir servidor MCP"
```

O menu abre o MCP em um terminal dedicado; o menu principal permanece livre para
subir a API web ou iniciar outras ações em paralelo.

---

## Configuração no Felixo-AI-Core

A configuração abaixo representa o contrato esperado para o cliente de servidores MCP
externos do Felixo-AI-Core:

```json
{
  "notion": {
    "command": "notion-automacoes",
    "args": ["mcp", "start"],
    "env": {
      "NOTION_TOKEN": "${NOTION_TOKEN}",
      "NOTION_DATABASE_ID": "${NOTION_DATABASE_ID}"
    }
  }
}
```

### Contrato do catálogo

Em 25 de junho de 2026, o catálogo real em
`app/electron/services/mcp/felixo-tool-catalog.cjs` incorporou a camada `notion`
no commit `75c8a12`. As entradas registradas são:

```javascript
{
  name: 'notion.list_tasks',
  layer: 'notion',
  access: 'read',
  status: 'planned',
  description: 'List Notion tasks, optionally filtered by status.',
},
{
  name: 'notion.create_task',
  layer: 'notion',
  access: 'write',
  status: 'planned',
  requiresConfirmation: true,
  description: 'Create a task in Notion after confirmation.',
},
{
  name: 'notion.move_status',
  layer: 'notion',
  access: 'write',
  status: 'planned',
  requiresConfirmation: true,
  description: 'Move a Notion task to another status after confirmation.',
},
{
  name: 'notion.conclude_task',
  layer: 'notion',
  access: 'write',
  status: 'planned',
  requiresConfirmation: true,
  description: 'Conclude a Notion task after confirmation.',
},
{
  name: 'notion.update_project_page',
  layer: 'notion',
  access: 'write',
  status: 'planned',
  requiresConfirmation: true,
  description: 'Update a Notion project page after confirmation.',
},
```

O catálogo fixa a política de confirmação do host. O status `planned` exibido no
snapshot acima descreve o catálogo do Felixo-AI-Core em 25/06/2026, não a
publicação do pacote nem a disponibilidade do servidor neste repositório. O
servidor pode ser validado diretamente por `stdio` ou Streamable HTTP.

---

## Arquitetura e decisões

1. **Sem Django**: o servidor MCP cria a `TaskList` diretamente do
   `notion_starter`, lendo token e database ID do ambiente. Não depende do
   Django — é um processo separado do servidor web.

2. **DI dos serviços**: as funções de `services.tarefas` aceitam um parâmetro
   `tasklist` injetável. O MCP server cria a `TaskList` e injeta, seguindo o
   mesmo padrão que os testes usam.

3. **Delete protegido**: `notion.delete_block` arquiva blocos e é destrutiva. A
   ferramenta declara `destructiveHint=True`; o host deve exigir confirmação antes
   de executar. Mudanças de tarefa, conteúdo e páginas de projeto também requerem
   confirmação no host.

4. **Transportes**: `stdio` é o padrão local para o Felixo-AI-Core. Streamable HTTP
   existe apenas para depuração local. SSE legado não é exposto.

5. **Página de projeto por caso de uso**: `notion.update_project_page` constrói um
   `RepoInfo` normalizado e delega a `services.projetos.atualizar_pagina_projeto`.
   O serviço reutiliza `CamposProjeto` e o mapeamento da sincronização GitHub; o MCP
   não monta payload cru do Notion.

6. **SDK `mcp` 2.x** (`mcp>=2.3,<3`, classe `MCPServer`, que no 1.x se chamava
   `FastMCP`). O servidor atende as duas eras do protocolo: clientes que abrem com o
   handshake `initialize` (versões de 2025, como `2025-06-18` e `2025-11-25`) e
   clientes que usam `server/discover` (`2026-07-28`). O `serverInfo` anuncia o nome
   `notion` e a versão do pacote. Falha prevista (entrada inválida, Notion
   indisponível, configuração ausente) sai como `ToolError`, por
   `EntradaInvalidaError` e `FalhaDaFerramentaError`: o cliente recebe
   `isError: true` com a mensagem já sanitizada (`Error executing tool <nome>:
   <motivo>`). Qualquer outro erro o SDK trata como queda: o traceback fica no log do
   servidor e o modelo só fica sabendo que a ferramenta falhou, sem detalhe interno.

---

## Testes

```bash
uv run python -m pytest tests/api/mcp/ tests/services/test_services_projetos.py tests/api/cli/test_cli_notion_tasks.py -v
```

Os testes cobrem:

- superfície pública com namespace `notion.*`;
- anotações MCP de leitura, criação e atualização;
- serialização de `Tarefa` sem expor `bruto`;
- validação de entradas e variáveis de ambiente;
- ferramentas com Notion mockado (`responses`);
- seleção real do transporte passado ao SDK;
- metadata do servidor;
- o que o modelo lê quando uma ferramenta falha (falha prevista com a mensagem,
  queda sem detalhe interno);
- **o contrato no fio** (`test_mcp_stdio.py`): sobe o servidor por `stdio` e conversa
  em JSON-RPC cru, sem o SDK do lado do cliente. Confere a negociação de um protocolo
  da era do `initialize`, o `serverInfo`, as instruções, as 18 ferramentas, as
  anotações em camelCase, os esquemas de entrada, o erro de ferramenta como
  `isError` e a saída limpa ao fechar o stdin. Como não depende da versão do SDK, é
  ele que pega uma troca de versão que mude o que o host recebe.

Validação de 25 de junho de 2026: **32 testes focados** (`test_mcp_server.py` +
`test_services_projetos.py`) e handshake real por `stdio` listando as cinco
ferramentas `notion.*`.

Validação de 19 de outubro de 2026, na migração para o SDK `mcp` 2.3.0: os testes
de `tests/api/mcp/` passam em Python 3.10, 3.11 e 3.13. O cliente oficial do SDK 2.x
conectou por `stdio` nas duas eras (`2026-07-28` no modo `auto`, `2025-11-25` no
modo `legacy`), listando as 18 ferramentas. O transporte Streamable HTTP respondeu
ao `initialize` em `http://127.0.0.1:8000/mcp`.

## Ferramentas da biblioteca (2026-10-20)

Além das 18 ferramentas de tarefas e conteúdo, o servidor expõe a biblioteca como cascas
finas sobre os mesmos serviços da CLI: `notion.set_page_appearance` (ícone e capa; imagem
local acima do limite sobe comprimida), `notion.discover_articles`, `notion.extract_article`,
`notion.translate_markdown` (OpenRouter, código intacto), `notion.article_to_pdf`,
`notion.generate_cover` e `notion.import_articles` (rascunhos para um database, sem duplicar;
`dry_run` por padrão). Geração de PDF, capas e redução de imagens pedem o extra
`[biblioteca]` (markdown, pyyaml, pillow) e, no caso do PDF, Edge ou Chrome instalado.

## Views e Registro diário (2026-10-20)

Três ferramentas sobre os serviços `views` e `registro_diario`, as mesmas dos comandos
`ordenar-view` e `registro-diario` da CLI:

- `notion.sort_view` — ordena uma view pela Views API oficial (`/views`, versão `2026-03-11`)
  e confere por releitura. A API devolve a propriedade pelo ID, não pelo nome.
- `notion.ensure_daily_log_day` — cria a linha de um dia (`DD-MM-AAAA`) só se ela não
  existir, com propriedades antes do corpo; sem corpo, usa o do modelo "Dia padrão".
- `notion.estimate_daily_log` — estima horas por área, hora de acordar, sono e produtividade
  pelos commits do GitHub (`GITHUB_TOKEN` para repositórios privados) e pelos blocos
  `HH:MM–HH:MM` dos relatórios diários. Sem `aplicar` só mostra; com `aplicar` grava nos
  campos vazios. Banho nunca é estimado, e dia sem rastro fica vazio.

Criar modelo nativo de database e defini-lo como padrão continua fora da API pública e do
MCP oficial do Notion (medido em 2026-10-20): isso só pela interface.
