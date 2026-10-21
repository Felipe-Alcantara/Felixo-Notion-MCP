# 🏛️ Arquitetura — Felixo Notion MCP

> **Estado em 2026-10-07 (etapa 1 do monólito):** o código das ferramentas vive num
> pacote Python único, `felixo-notion-mcp` (import `felixo_notion_mcp`, versão
> `0.6.0.dev0`), organizado em camadas. Este documento mostra quais são as camadas, o que
> cada uma guarda, em que direção elas dependem umas das outras e de onde veio cada
> arquivo. A decisão e o histórico estão no [`IA.md`](../IA.md); o desenho completo das
> quatro etapas, na
> [spec do monólito](superpowers/specs/2026-10-07-monolito-felixo-notion-mcp-design.md).

---

## 📋 Índice

- [🧭 Visão geral](#-visão-geral)
- [📁 Mapa do repositório](#-mapa-do-repositório)
- [🧱 As camadas](#-as-camadas)
- [➡️ Direção das dependências](#️-direção-das-dependências)
- [🚪 Pontos de entrada](#-pontos-de-entrada)
- [🔀 Origem → destino](#-origem--destino)
- [🔭 O que ainda não existe](#-o-que-ainda-não-existe)

---

## 🧭 Visão geral

Até 06/10/2026 o ecossistema eram quatro repositórios: o hub (documentação e roteamento) e
três módulos (`notion-starter`, `notion-tasks-cli` e `notion-workspace-app`), cada um com o
próprio pacote, a própria versão e o próprio CI. Esta etapa reuniu tudo num repositório e
num pacote, **sem mudar comportamento**: as linhas de comando, o caminho dos perfis, os
rótulos do app Django e os nomes das tabelas são os mesmos de antes.

A organização segue as camadas do Felixo System Design (monólito modular). Os nomes de
pasta são em inglês, como o padrão manda; código, docstrings, mensagens e commits são em
português.

## 📁 Mapa do repositório

```text
Felixo-Notion-MCP/
│
├── 📁 src/felixo_notion_mcp/    # o pacote
│   ├── 📁 domain/               # regras puras: propriedades, schema, Markdown ↔ blocos, tarefas
│   ├── 📁 services/             # casos de uso (tarefas, conteúdo, relações, relatórios, GitHub…)
│   ├── 📁 repositories/         # persistência (Django ORM): estado operacional em SQLite
│   ├── 📁 integrations/         # quem fala com o mundo: Notion, GitHub, OpenRouter
│   ├── 📁 api/                  # as bordas: CLI, servidor MCP, HTTP/REST (Django) e o menu
│   └── 📁 core/                 # configuração, perfis, exceções, logging, constantes, utilitários
│
├── 📁 front/                    # fonte da SPA React; o build vai para api/http/static/frontend
├── 📁 tests/                    # espelha as camadas, mais contrato (retrato da CLI) e scripts
├── 📁 scripts/                  # empacotamento nativo, migração e scripts reutilizáveis
├── 📁 examples/                 # exemplos de uso da biblioteca
├── 📁 docs/                     # um documento por responsabilidade; specs; ia-archive/
├── 📁 .github/workflows/        # CI em matriz (Ubuntu, Windows, macOS × Python 3.11–3.13)
│
├── start_app.py                 # menu interativo: a porta de entrada única
├── pyproject.toml · uv.lock     # metadados do pacote e dependências travadas
└── README.md · AGENTS.md · CLAUDE.md · IA.md · CONTRIBUTING.md · .env.example · LICENSE
```

## 🧱 As camadas

Os caminhos desta tabela são relativos a `src/felixo_notion_mcp/`.

| Camada | O que guarda | Exemplos |
| --- | --- | --- |
| `domain/` | **Regras puras**: transformar e comparar dados do Notion, sem rede e sem E/S própria. | `content.py` (Markdown ↔ blocos), `properties.py` e `readers.py` (escrever e ler propriedades), `schema.py` (comparar e descrever databases), `tasks.py` (`Tarefa`, `TaskList`), `valores_br.py`, `git_historico.py` |
| `services/` | **Casos de uso**: uma função por intenção do usuário. Orquestram o domínio e as integrações; não conhecem HTTP nem argparse. | `tarefas.py`, `conteudo.py`, `relacoes.py`, `movimentacao.py`, `copia_corpo.py`, `modelos.py`, `schema.py`, `relatorios_diarios.py`, `relatorios_docx.py`, `sincronizar_github.py`, `ingestao.py`, `inventory.py` |
| `repositories/` | **Persistência** local: modelos do Django para o estado operacional (jobs e locks). Hoje só existe `operations/`. | `operations/models.py` (`Job`, `Lock`) e a migração `0001_initial` |
| `integrations/` | **Quem fala com fora.** Só `notion_client.py` conversa com a API do Notion; os adaptadores de GitHub e OpenRouter ficam aqui também. | `notion_client.py` (`NotionClient`: retries, rate limit, paginação), `notion.py` (fábrica de cliente e `TaskList` a partir da configuração), `github.py`, `openrouter.py` |
| `api/` | **As bordas**: traduzem entrada e saída e delegam. Sem regra de negócio. | `cli/` (`notion_tasks.py`, `unificada.py`, `erros.py`, `atualizacao_nativa.py`), `mcp/server.py`, `http/` (`config/`, `rest/`, `templates/`, `static/`), `launcher.py` (o menu) |
| `core/` | **Fundação** que todas as camadas podem usar: não depende de nenhuma outra. | `config.py` (ambiente e `.env`), `workspaces.py` (perfis), `exceptions.py` (`NotionSyncError` e derivadas), `logging.py`, `constants.py`, `utils.py`, `origem.py` |

Fora do pacote:

- **`front/`**: o código-fonte da SPA React. `npm run build` escreve o bundle em
  `api/http/static/frontend/` (ignorado pelo git), e o wheel o leva embutido.
- **`tests/`**: espelha as camadas (`tests/domain`, `tests/services`, `tests/integrations`,
  `tests/core`, `tests/repositories`, `tests/api/{cli,mcp,http}`), mais `tests/contrato/`
  (o retrato da linha de comando) e `tests/scripts/`.
- **`scripts/`**: `empacotamento/` (build do binário nativo com PyInstaller, smoke e
  conferência do wheel), `migracao/` (as ferramentas que fizeram esta mudança, mantidas
  como registro) e `notion/` (scripts pontuais de manipulação do Notion).

A raiz do pacote, `felixo_notion_mcp/__init__.py`, reexporta a API pública herdada do
`notion_starter` (`NotionClient`, `TaskList`, `properties`, `readers`…). Os nomes são
carregados **sob demanda**: importar o pacote não carrega `requests`, e por isso o menu
`start_app.py` abre num Python onde ainda não há nada instalado.

## ➡️ Direção das dependências

```text
api ──▶ services ──▶ integrations ──▶ domain ──▶ core

repositories fica ao lado: o Django o descobre por INSTALLED_APPS e ninguém o importa
```

- Uma camada só importa as que estão **à direita** dela (pode pular camadas: `api/` importa
  `domain/` e `core/` direto, por exemplo). `core/` não importa nenhuma outra.
- Importar nomes da raiz do pacote (`from felixo_notion_mcp import NotionClient`) vale para
  todas as camadas; é a API pública herdada, carregada sob demanda.
- **`api/` não tem regra de negócio**; se uma borda precisa de uma regra, ela vira um caso de
  uso em `services/`.
- **`services/` e `domain/` não conhecem HTTP**: quem faz requisição é `integrations/`, e só
  `integrations/notion_client.py` fala com a API do Notion.
- **Exceção conhecida:** `domain/tasks.py` importa `integrations/notion_client.py` (a
  `TaskList` usa o `NotionClient` diretamente). A dívida veio assim dos módulos originais e
  segue registrada para a etapa 2.
- A verificação **automática** dessas regras (um teste de arquitetura que falha se
  `domain/` ou `services/` importarem `os.environ`, Django, `mcp` ou `argparse`) está
  prevista para a etapa 2. Até lá, as regras valem por revisão.

## 🚪 Pontos de entrada

| Comando | Função | Para quê |
| --- | --- | --- |
| `felixo-notion-mcp` | `api.cli.unificada:main` | CLI principal: `tasks`, `auth`, `doctor`, `app`, `mcp`, `update` |
| `notion-tasks` | `api.cli.notion_tasks:main` | Apelido **permanente**: skills, prompts e `AGENTS.md` dependem dele |
| `notion-automacoes` | `api.cli.unificada:main` | Apelido de transição (nome do pacote publicado hoje) |
| `notion-automacoes-app` | `api.launcher:main` | Apelido de transição: abre o menu |
| `notion-automacoes-mcp` | `api.mcp.server:main` | Apelido de transição: servidor MCP direto |
| `python start_app.py` | `api.launcher:main` | Menu do checkout: Iniciar, Instalar/Setup, Configurar, Status |

`felixo-notion-mcp doctor` mostra, entre outros itens, **de onde o pacote está sendo
importado** e se é um checkout editável. Ele só informa; quem edita o código e não vê o
efeito deve conferir essa linha.

## 🔀 Origem → destino

Esta é a síntese, por diretório, da tabela de movimentos que aplicou a mudança
(`TABELA_MOVIMENTOS` em
[`scripts/migracao/mapa_modulos.py`](../scripts/migracao/mapa_modulos.py), a fonte única).
Os repositórios de origem foram importados com o histórico completo, então
`git log --follow` e `git blame` atravessam a mudança. As versões importadas foram
`notion-starter` `42da753`, `notion-tasks-cli` `73ffcd9` e `notion-workspace-app` `0e958ba`.

### De `notion-starter`

| Origem | Destino (em `src/felixo_notion_mcp/`) |
| --- | --- |
| `src/notion_starter/client.py` | `integrations/notion_client.py` |
| `src/notion_starter/github.py`, `openrouter.py` | `integrations/` |
| `src/notion_starter/properties.py`, `readers.py`, `content.py`, `schema.py`, `tasks.py`, `valores_br.py`, `git_historico.py` | `domain/` |
| `src/notion_starter/services/*` e `inventory.py` | `services/` |
| `src/notion_starter/constants.py`, `exceptions.py`, `logging.py`, `utils.py` | `core/` |
| `src/notion_starter/__init__.py` | `__init__.py` (exportações sob demanda) |
| `examples/` | `examples/` (na raiz do repositório) |
| `tests/` | `tests/domain`, `tests/services`, `tests/integrations`, `tests/core` |
| `IA.md` | `docs/ia-archive/IA-notion-starter.md` |

### De `notion-tasks-cli`

| Origem | Destino |
| --- | --- |
| `cli/*` (inclui `atualizacao_nativa.py`, `unificada.py`, `versao.py`) | `api/cli/` |
| `core/config.py`, `core/workspaces.py` | `core/` |
| `integrations/notion.py` | `integrations/notion.py` |
| `services/preflight.py`, `services/propriedades.py` | `services/` |
| `scripts/build_native.py`, `native_entrypoint.py`, `smoke_native.py` | `scripts/empacotamento/` (na raiz do repositório) |
| `integrations/github.py`, `openrouter.py` e os `services/*.py` que só reexportavam o starter | removidos (eram *shims*); os nomes antigos passam a apontar para o módulo real |
| `start_app.py` | removido (substituído pelo `start_app.py` único da raiz) |
| `tests/` | `tests/api/cli`, `tests/core`, `tests/integrations`, `tests/services` |
| `IA.md` | `docs/ia-archive/IA-notion-tasks-cli.md` |

### De `notion-workspace-app`

| Origem | Destino |
| --- | --- |
| `server/mcp_server.py` | `api/mcp/server.py` |
| `server/api/` | `api/http/rest/` |
| `server/config/`, `server/manage.py`, `server/templates/`, `server/static/` | `api/http/` |
| `server/operations/` (modelos `Job` e `Lock`) | `repositories/operations/` |
| `server/core/config.py`, `server/integrations/notion.py` | unificados com os equivalentes da CLI (`core/config.py`, `integrations/notion.py`) |
| `server/integrations/github.py`, `openrouter.py` e `server/services/*.py` (*shims*) | removidos; os nomes antigos passam a apontar para o módulo real |
| `start_app.py` | `api/launcher.py` (a implementação do menu; a porta é o `start_app.py` da raiz) |
| `front/` | `front/` (na raiz do repositório) |
| `tests/` | `tests/api/{cli,mcp,http}`, `tests/integrations`, `tests/services` |
| `IA.md` | `docs/ia-archive/IA-notion-workspace-app.md` |

### Do hub

| Origem | Destino |
| --- | --- |
| `bootstrap.py`, `check-dev.py`, `sync.py`, `SYNC.md` | aposentados: já não há módulos para clonar nem cópias do starter para conferir. A pergunta do `check-dev.py` ("o código que roda é o que eu edito?") virou o `doctor` |
| `criar_tarefas_investigadas_*.py` | `scripts/notion/` |
| `start_app.py` | substituído pelo `start_app.py` único da raiz |
| `modules/` | deixou de existir: o código vive em `src/` |

README, `CONTRIBUTING`, `.env.example`, `LICENSE`, `.gitignore`, `pyproject.toml` e CI de
cada módulo foram substituídos pelos da raiz. `AGENTS.md`, `CLAUDE.md`, `IA.md`, `docs/` e
`DESIGN-WORKSPACE-NOTION.md` do hub continuam e foram atualizados.

## 🔭 O que ainda não existe

Esta etapa só reorganiza. Estas peças estão desenhadas na spec e **abertas a quem quiser
ajudar**:

- **Registro único de operações** (`api/operations/`): cada operação declarada uma vez e as
  bordas (MCP, CLI e REST) geradas dela, com paridade entre elas e um contexto de execução
  explícito para os casos de uso (etapa 2).
- **Modo hospedado**: servidor MCP acessível por URL, com contas, OAuth e isolamento por
  pessoa (etapa 3).
- **Teste de arquitetura** que prende as regras de dependência desta página (etapa 2).
- **Migração dos consumidores** (Felixo AI Core e Felixo Editor) e a **distribuição**
  do pacote `felixo-notion-mcp` no PyPI e dos binários nativos (etapa 4). Até lá, os pacotes
  publicados continuam `notion-automacoes`, `notion-starter` e `notion-workspace-app`
  (veja [`DISTRIBUICAO.md`](DISTRIBUICAO.md)).
