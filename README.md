# 🧩 Felixo Notion MCP

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Notion API](https://img.shields.io/badge/Notion-API-000000?style=for-the-badge&logo=notion&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-Server-6C47FF?style=for-the-badge)
[![PyPI](https://img.shields.io/pypi/v/notion-automacoes?style=for-the-badge&label=PyPI)](https://pypi.org/project/notion-automacoes/)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Notion para pessoas e para IAs: biblioteca, CLI, servidor MCP e app local, com ferramentas de coleta e curadoria de conteúdo no mesmo pacote Python.**

[🚀 Como Usar](#-como-usar) • [🧰 Comandos](#-comandos-principais) • [🏛️ Arquitetura](docs/ARQUITETURA.md) • [🤖 Para IAs](#-para-ias) • [🤝 Contribuições](#-contribuições)

</div>

---

## 📋 Índice

- [⭐ **O menu de entrada**](#-o-menu-de-entrada) ⭐ **DESTAQUE**
- [📋 Sobre o Projeto](#-sobre-o-projeto)
- [📁 Estrutura do Projeto](#-estrutura-do-projeto)
- [🧰 Ferramentas Disponíveis](#-ferramentas-disponíveis)
- [🚀 Como Usar](#-como-usar)
- [📚 Guia Rápido](#-guia-rápido)
- [🔧 Funcionalidades Técnicas](#-funcionalidades-técnicas)
- [⚠️ Limitações](#️-limitações)
- [🛡️ Segurança](#️-segurança)
- [📖 Documentação](#-documentação)
- [🌌 Ecossistema Felixo](#-ecossistema-felixo)
- [📝 Licença](#-licença)
- [👤 Autor](#-autor)
- [🤝 Contribuições](#-contribuições)

---

## ⭐ O menu de entrada

> **🚀 UM COMANDO, SEM DECORAR NADA**
>
> ```bash
> python start_app.py
> ```

### 💡 Por que começar por ele?

- **🎯 Tudo num lugar**: instalar, configurar o token, subir o app web, subir o servidor MCP e ver o estado do ambiente.
- **🧭 Descritivo**: cada opção do menu explica o que vai fazer antes de fazer.
- **🪶 Abre sem nada instalado**: o `start_app.py` usa só a biblioteca padrão do Python, então funciona num clone recém-baixado, em Windows, macOS e Linux.
- **🩺 Status honesto**: a opção Status mostra o estado real do ambiente e também de onde o pacote é importado (a mesma informação do `felixo-notion-mcp doctor`).

Menu: **Usar o app** (app web local) • **Para IA e integrações** (CLI, GitHub, servidor MCP, mapa) • **Configurar e instalar** (token e database de tarefas, dependências, API, qualidade) • **Status** • **Sair**. O **Configurar** define só o token do Notion e o database de tarefas, guardados no `.env`; os perfis de workspace se gerenciam à parte, com `felixo-notion-mcp auth` (ou `notion-tasks perfis`).

Tecnologias da interface: terminal colorido com `rich` e `questionary`.

---

## 📋 Sobre o Projeto

O **Felixo Notion MCP** é um **monólito modular Python** que reúne quatro interfaces complementares: a biblioteca `felixo_notion_mcp`, a CLI `notion-tasks`, um servidor MCP e um app web local com API Django e SPA React. Ele conecta agentes e pessoas ao Notion para ler, criar e atualizar tarefas, páginas e databases. A biblioteca também coleta e organiza artigos e posts, traduz Markdown, gera PDFs e capas e importa rascunhos para uma biblioteca no Notion.

O projeto reuniu quatro repositórios — a biblioteca `notion-starter`, a CLI `notion-tasks-cli`, o app `notion-workspace-app` e o hub de documentação — num único checkout e pacote. A consolidação do monólito começou em 07/10/2026; desde então, o pacote unificado também recebeu funcionalidades novas, incluindo a biblioteca de conteúdo descrita abaixo.

### 🧩 Um repositório, um pacote

- ✅ O pacote construído por este checkout chama-se `felixo-notion-mcp` (import `felixo_notion_mcp`) e preserva o histórico Git dos projetos incorporados.
- ✅ O código está organizado em `domain`, `services`, `repositories`, `integrations`, `api` e `core`; veja [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
- ✅ A biblioteca de conteúdo reúne coleta de artigos, tradução de Markdown, geração de PDF e capas, otimização de imagens, processamento de blogs Hugo e importação idempotente para o Notion.
- ✅ As dependências estão travadas em `uv.lock`. A CI cobre Ubuntu, Windows e macOS com Python 3.11–3.13, além de lint, auditoria de dependências e build do front e do pacote.
- ✅ `felixo-notion-mcp doctor` informa de onde o pacote está sendo importado e se o checkout está instalado em modo editável.
- ✅ `notion-tasks` e os perfis locais continuam disponíveis; os pacotes públicos ainda seguem a transição descrita em [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md).

---

## 📁 Estrutura do Projeto

```text
Felixo-Notion-MCP/
│
├── 📁 src/felixo_notion_mcp/    # o pacote
│   ├── 📁 domain/               # regras puras: propriedades, schema, Markdown ↔ blocos, tarefas
│   ├── 📁 services/             # tarefas, conteúdo, relações, relatórios, GitHub e biblioteca
│   ├── 📁 repositories/         # persistência local (Django ORM): estado operacional
│   ├── 📁 integrations/         # Notion, GitHub, OpenRouter, web, PDF e imagens
│   ├── 📁 api/                  # bordas: cli/, mcp/, http/ (Django) e launcher.py
│   └── 📁 core/                 # configuração, perfis, exceções, logging, utilitários
│
├── 📁 front/                    # fonte da SPA React (o build entra no wheel)
├── 📁 tests/                    # espelha as camadas, mais o contrato da CLI
├── 📁 scripts/                  # empacotamento nativo, migração e scripts reutilizáveis
├── 📁 examples/                 # exemplos de uso da biblioteca
├── 📁 docs/                     # arquitetura, biblioteca, distribuição, contratos, MCP, qualidade…
├── 📁 .github/workflows/        # CI e validação manual de binários publicados
│
├── start_app.py                 # menu interativo de entrada
├── pyproject.toml · uv.lock     # metadados do pacote e dependências travadas
├── AGENTS.md · CLAUDE.md        # roteamento e contexto para agentes de IA
├── IA.md                        # linha do tempo de decisões
├── DESIGN-WORKSPACE-NOTION.md   # padrão de organização do workspace Notion
├── CONTRIBUTING.md              # como contribuir
├── .env.example                 # modelo de variáveis de ambiente (sem valores)
├── README.md                    # este arquivo
└── LICENSE
```

---

## 🧰 Ferramentas Disponíveis

### 💻 CLI para IAs e pessoas (`src/felixo_notion_mcp/api/cli/`)

**`notion-tasks`** (apelido permanente) e **`felixo-notion-mcp`**
- Cria, edita, move e conclui tarefas; consulta schema e relações; lê e escreve páginas em Markdown; mapeia o workspace; clona e organiza databases; importa planilhas; exporta relatórios para DOCX; sincroniza repositórios do GitHub.
- Inclui comandos de biblioteca: coleta e extração de artigos, tradução de Markdown, geração de PDF e capas, ajuste de imagens, conversão de blogs Hugo em PDFs e rascunhos e importação desses rascunhos para o Notion.
- Também define ícone/capa em páginas, anexa arquivos a linhas, cria/garante/renomeia/remove colunas e databases, move páginas, copia corpos e preenche modelos nativos.
- O `--help` é um guia escrito para IAs, e os erros em `--json` vêm num envelope único (`codigo`, `mensagem`, `proximo_passo`).
- Exemplo: `notion-tasks conteudo <id>` → propriedades e corpo da página, avisando quando ela contém um database.
- A fonte de código deste checkout contém os comandos recentes da biblioteca; eles ainda não fazem parte dos pacotes públicos anteriores à etapa 4 da distribuição.

📖 [Ver o roteamento e as regras de operação](AGENTS.md)

---

### 🔌 Servidor MCP (`src/felixo_notion_mcp/api/mcp/`)

**`server.py`**
- Registra **30 ferramentas MCP** para tarefas, projetos, pesquisa, leitura, databases, views, blocos, anexos, aparência de páginas, biblioteca de conteúdo e Registro diário.
- Lote de tarefas: `notion.import_tasks` grava rascunhos (`<chave>.json` + `<chave>.md`) como tarefas, sem duplicar, com as relações nos dois sentidos e a seção "Tarefas relacionadas" nas duas pontas.
- Usa `stdio` por padrão e oferece Streamable HTTP para depuração local.
- Anota ferramentas de leitura, criação, atualização e exclusão. O host cliente deve pedir confirmação antes das escritas; exclusão de bloco também sinaliza `destructiveHint`.
- Ferramentas de biblioteca: `notion.set_page_appearance`, `notion.discover_articles`, `notion.extract_article`, `notion.translate_markdown`, `notion.article_to_pdf`, `notion.generate_cover` e `notion.import_articles`.
- Views e Registro diário: `notion.sort_view` (ordena uma view pela Views API), `notion.ensure_daily_log_day` (cria o dia sem duplicar), `notion.carry_over_daily_log` (cria o dia com as tarefas que ficaram abertas no anterior) e `notion.estimate_daily_log` (estima horas, hora de acordar, sono e produtividade por commits e relatórios).
- Exemplo: `felixo-notion-mcp mcp start` → servidor pronto para o Claude Code ou o Cursor.

📖 [Ver ferramentas, transportes e integração](docs/MCP.md)

---

### 🌐 App web local (`src/felixo_notion_mcp/api/http/` e `front/`)

**API Django + SPA React**
- Kanban, lista e grade de tarefas, filtros, formulário de criação/edição e exploração somente leitura de databases visíveis à integração.
- Mostra a database e a data source ativas e oferece links para conferir tarefas no Notion.
- A SPA já vem compilada no wheel; Node e npm só são necessários no checkout de desenvolvimento.
- Exemplo: `felixo-notion-mcp app start` → API e SPA em `127.0.0.1`.

📖 [Ver os contratos REST](docs/CONTRATOS.md) • [infraestrutura](docs/INFRA.md)

---

### 📚 Biblioteca (`domain/`, `services/`, `integrations/`)

**`NotionClient`, `TaskList`, conversão Markdown ↔ blocos**
- Cliente com retries, rate limit e paginação; builders e leitores de propriedades; comparação e descrição de schema; conversão Markdown/blocos.
- Serviços para conteúdo seguro, relações, movimentação de páginas, inventário, integração GitHub, relatórios e biblioteca de artigos.
- Exemplo: `markdown_para_blocos("# Título")` → blocos prontos para a API.

📖 [Ver o mapa das camadas](docs/ARQUITETURA.md) • [exemplos](examples/)

### 📰 Biblioteca de conteúdo

Os comandos recentes transformam fontes web e blogs em material organizado para pesquisa:

- `coletar-artigos` descobre URLs por feed, sitemap e página inicial; `--extrair` também baixa e extrai os artigos.
- Para blogs versionados, a biblioteca também pode baixar uma pasta de conteúdo diretamente do GitHub, sem clonar o repositório.
- `traduzir` traduz Markdown preservando blocos de código e estrutura.
- `artigo-pdf` gera PDF a partir de Markdown com autoria, URL de origem e aviso de licença opcional.
- `gerar-capa` cria uma capa PNG; `ajustar-imagem` reduz dimensões e tamanho de imagens.
- `blog-para-biblioteca` processa posts Hugo em lote, gerando PDFs e rascunhos com organização por tags; paralelismo, largura/qualidade das imagens e limite de upload são configuráveis.
- `importar-artigos` faz upsert idempotente dos rascunhos em um database do Notion, anexa os PDFs e aplica ícone/capa; aceita execução paralela e `--dry-run` para mostrar o plano sem gravar.
- `aparencia` aplica ou atualiza ícone e capa de páginas/linhas; `anexar-arquivo` acrescenta arquivo local preservando os anexos existentes.
- `garantir-coluna` adiciona uma coluna ao schema sem recriar a database, prepara as opções de `select`/`multi_select` e pode criar relações com outra database.

PDF e processamento de imagens usam o extra `[biblioteca]`; a geração de PDF requer Edge ou Chrome instalado. Importar planilhas usa o extra `[planilha]`.

📖 [Ver os comandos no AGENTS.md](AGENTS.md) • [índice da documentação](docs/README.md)

---

## 🚀 Como Usar

### Opção 1: instalar o pacote publicado (mais simples) 📦

Para só **usar** o Notion, sem clone, Git ou Node:

```bash
pipx install "notion-automacoes[app]"
# ou: uv tool install "notion-automacoes[app]"
notion-automacoes --version
notion-automacoes doctor
```

> **Em transição.** Os pacotes publicados no PyPI hoje são `notion-automacoes` (CLI), `notion-starter` e `notion-workspace-app`. O pacote `felixo-notion-mcp` é construído a partir deste repositório e será publicado na etapa 4. Os comandos `notion-tasks` são os mesmos nos dois. Os detalhes estão em [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md).

> **Funcionalidades recentes:** a coleta e curadoria de artigos, os comandos de PDF/imagens e a integração completa da biblioteca estão no checkout unificado. Para usá-los antes da etapa 4, instale e execute este checkout em modo editável.

### Opção 2: pelo checkout (para mexer no código) 🛠️

#### Instalação

```bash
# Clone o repositório
git clone https://github.com/Felipe-Alcantara/Felixo-Notion-MCP.git
cd Felixo-Notion-MCP

# O caminho mais curto: o menu instala e configura por você
python start_app.py

# Ou manualmente, com as dependências travadas
uv sync --locked --all-extras
```

#### Executando

```bash
uv run felixo-notion-mcp doctor      # diagnóstico: Python, dependências, perfis, rede, origem do pacote
uv run notion-tasks --help           # o guia completo da CLI
uv run python -m pytest              # a suíte (HTTP mockado: não precisa de token nem de rede)
uv run ruff check .                  # lint
```

### Configurar o token

```bash
export NOTION_TOKEN=ntn_...          # ou copie .env.example para .env
export NOTION_DATABASE_ID=...        # opcional: o database de tarefas padrão
```

Outras integrações são opcionais e só precisam ser configuradas quando usadas:

| Variável | Usada por |
|---|---|
| `GITHUB_TOKEN` | Acesso a repositórios privados e limites ampliados da API GitHub. Para repositórios públicos, normalmente é dispensável. |
| `OPENROUTER_API_KEY` | Tradução de Markdown e recursos da camada de IA via OpenRouter. |
| `NOTION_PROJECTS_DATABASE_ID` | Database padrão para páginas de projetos importadas do GitHub. |
| `NOTION_REPORTS_DATABASE_ID` | Database padrão para exportação de relatórios diários. |

Veja [.env.example](.env.example) para as demais opções do app local, do Django e do binário nativo. Nunca coloque tokens ou chaves no controle de versão.

Ou salve workspaces como **perfis** (recomendado para quem alterna entre workspaces):

```bash
notion-tasks perfis adicionar <alias>   # salva uma key/workspace local
notion-tasks perfis usar <alias>        # define o perfil ativo
notion-tasks perfis listar              # mostra os perfis sem expor tokens
notion-tasks --perfil <alias> <comando> # usa outro perfil só nesta execução
```

> **Atenção à precedência** (da maior para a menor): `--perfil <alias>` → **perfil ativo** → `NOTION_TOKEN` do ambiente ou do `.env`. Com um perfil ativo, o token dele **vence silenciosamente** a variável de ambiente. Se um link válido devolve "Recurso não encontrado", confira primeiro o perfil ativo com `notion-tasks perfis listar` — você pode estar consultando outro workspace.

Os perfis ficam na **pasta de configuração do usuário** (`~/.config/notion-tasks/` ou `%APPDATA%\notion-tasks\`), não ao lado do pacote, então trocar o modo de instalação não os afeta.

### 🧰 Comandos principais

```bash
# 1. SEMPRE comece lendo o que o link é
notion-tasks conteudo <id>       # propriedades + corpo. Se vier "databases_dentro",
                                 # o conteúdo são as LINHAS da tabela, não esta página
notion-tasks schema <id>         # colunas, tipos, valores aceitos e relações do database

# Tarefas
notion-tasks listar
notion-tasks criar "Tarefa" --status "Entrada" \
  --set "Prioridade=Alta" --conteudo "## Contexto..."   # linha completa numa chamada
notion-tasks mover <id> --status "Concluído"

# Workspace
notion-tasks mapear              # resume o workspace inteiro
notion-tasks mapear --html mapa.html   # relatório navegável: árvore, duplicatas, órfãos
notion-tasks buscar <termo>      # pesquisa páginas e databases
notion-tasks linhas <id>         # lista linhas de um database

# Linha de database (propriedades ANTES do conteúdo)
notion-tasks editar-linha <id> --set "Status=Feito"      # substitui uma coluna
notion-tasks editar-linha <id> --append "Resumo=..."     # acrescenta sem perder o atual
notion-tasks relacionar <a> <b> --coluna "Relacionadas"  # liga nos dois sentidos
notion-tasks importar-tarefas ./rascunhos --database <id> --dry-run  # lote de tarefas, sem duplicar

# Conteúdo de páginas
notion-tasks escrever <id>                 # anexa Markdown (recusa página que contém database)
notion-tasks escrever <id> --apos <bloco>  # insere no meio da página
notion-tasks blocos <id> --metadados       # blocos com ID, criado/editado em
notion-tasks editar-bloco <id> --trocar "de" --por "para"  # troca um trecho sem perder formatação
notion-tasks restaurar-bloco <id>          # desfaz uma exclusão

# Relatórios diários (saída programática: acabamento fino pode pedir ajuste manual no Word)
notion-tasks exportar-docx --database <id> --de 2026-07-01 --ate 2026-07-06 --saida ./exports
notion-tasks relatorios-do-git --database <id> --descobrir ./repositorios --dry-run

# Biblioteca de conteúdo (disponível no checkout unificado)
notion-tasks coletar-artigos https://exemplo.com --extrair
notion-tasks traduzir artigo.md artigo-pt.md --idioma "português do Brasil"
notion-tasks artigo-pdf artigo.md artigo.pdf --url-original https://exemplo.com/artigo --autor "Nome"
notion-tasks gerar-capa "Título" "Subtítulo" capa.png
notion-tasks ajustar-imagem original.jpg reduzida.jpg --limite-mb 5
notion-tasks blog-para-biblioteca ./blog-hugo \
  --base-url https://exemplo.com --mapa akitaonrails \
  --pdfs ./pdfs --rascunhos ./rascunhos
notion-tasks importar-artigos ./rascunhos --database <id> --dry-run
notion-tasks aparencia <page_id> --icone 📚 --capa ./capa.png
notion-tasks anexar-arquivo <page_id> ./artigo.pdf

# Sincronização de repositórios GitHub
notion-tasks atualizar-github --contas usuario1,usuario2 --apenas-mudancas --dry-run

# Servidor MCP e app local
felixo-notion-mcp mcp start      # servidor MCP (stdio)
felixo-notion-mcp app start      # API e SPA locais

# Guia completo
notion-tasks --help
```

---

## 📚 Guia Rápido

### Para Iniciantes
1. Rode `python start_app.py`.
2. Escolha **Instalar/Setup** e depois **Configurar** para salvar o token do Notion.
3. Escolha **Iniciar** para abrir o app web, ou **Status** para conferir o ambiente.

### 🤖 Para IAs
1. Leia [`AGENTS.md`](AGENTS.md): ele roteia cada pedido (usar o Notion ou desenvolver as ferramentas) e traz as regras de operação.
2. Ao receber um link do Notion, rode `notion-tasks conteudo <id>` **antes de escrever qualquer coisa**.
3. [`CLAUDE.md`](CLAUDE.md) é o contexto carregado automaticamente pelo Claude Code.

### Para Desenvolvedores
1. `uv sync --locked --all-extras` e `uv run python -m pytest`.
2. Ache o arquivo certo na tabela de [`AGENTS.md`](AGENTS.md) ou no mapa de [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
3. Leia o [`CONTRIBUTING.md`](CONTRIBUTING.md) antes de abrir o PR.

---

## 🔧 Funcionalidades Técnicas

- **Camadas com direção única**: `api` → `services` → `integrations` → `domain` → `core`. A borda não tem regra de negócio, `domain` e `services` não conhecem HTTP, e só `integrations/notion_client.py` fala com a API do Notion.
- **Cliente Notion resiliente**: paginação, retries orientados por tipo de falha e rate limit; configuração pode vir de variáveis, `.env` ou perfis locais.
- **Conteúdo seguro**: leitura de propriedades antes do corpo, proteção contra escrita solta em páginas que contêm databases e reescrita que preserva blocos que o Markdown não recria.
- **Schema e relações**: descrição de colunas e opções aceitas, prevenção de alterações em propriedades calculadas e ligação idempotente de relações nos dois sentidos.
- **Importações idempotentes**: planilhas e rascunhos de artigos atualizam registros por chave de origem em vez de duplicá-los.
- **Biblioteca de conteúdo**: descoberta e extração web, tradução Markdown, blogs Hugo, PDFs com metadados/licença, capas e otimização de imagens.
- **MCP com protocolo atual**: o servidor usa o SDK MCP 2.x, `stdio` como transporte padrão e Streamable HTTP para depuração local.
- **App multi-database**: a interface explora databases acessíveis em modo somente leitura e mantém a edição de tarefas no contrato dedicado.
- **Contrato da CLI preso por teste**: o retrato do parser (`tests/contrato/retrato_cli.json`) garante que o que a CLI aceitava continua aceito.
- **Envelope de erro único** na CLI: `{"ok": false, "erro": {"codigo", "mensagem", "proximo_passo", ...}}`.
- **Importação sob demanda**: `import felixo_notion_mcp` não carrega `requests`; por isso o menu abre num Python sem dependências.
- **Distribuição e CI**: dependências travadas em `uv.lock`, auditoria (`pip-audit`, `npm audit`), matriz multiplataforma e conferência do conteúdo do wheel.

---

## ⚠️ Limitações

- **Distribuição em transição**: o pacote `felixo-notion-mcp` ainda não está no PyPI; os pacotes publicados continuam `notion-automacoes`, `notion-starter` e `notion-workspace-app`.
- **Comandos recentes da biblioteca**: estão no checkout `0.6.0.dev0`; os pacotes públicos anteriores à etapa 4 não os incluem.
- **Binário nativo**: o build e o smoke do pacote unificado foram exercitados em Linux x64. Há um workflow manual para validar binários de Releases em contêineres Linux/Windows e runners macOS; a publicação do pacote unificado e dos próprios binários ainda depende da etapa 4.
- **MCP hospedado**: o servidor local usa `stdio` e oferece Streamable HTTP para depuração. O modo hospedado multiusuário, com contas e OAuth, ainda não existe.
- **Biblioteca de artigos**: a geração de PDF exige Edge ou Chrome instalado; recursos de mídia dependem do extra `[biblioteca]`, e a importação de planilhas depende de `[planilha]`.
- **DOCX**: a exportação de relatórios reproduz o modelo visual de forma programática; o acabamento fino pode exigir ajuste manual no Word.

---

## 🛡️ Segurança

⚠️ **IMPORTANTE:** o token do Notion dá acesso ao seu workspace. Trate-o como uma senha.

- O token **nunca é impresso** pela CLI, e os perfis ficam na pasta de configuração do seu usuário, fora do repositório.
- O `.env` é ignorado pelo git; o repositório só traz o `.env.example`, sem valores.
- A CLI exige confirmação explícita (`--sim`) para ações destrutivas. No MCP, o host cliente deve confirmar operações de escrita; a exclusão de bloco também declara `destructiveHint`.
- Reescritas de páginas criam o conteúdo novo antes de apagar o antigo e preservam blocos que não podem ser recriados de Markdown; `--apagar-tudo` remove essa proteção de forma explícita.
- Os backups de bloco ficam na pasta de estado do usuário, nunca no diretório atual.
- O app web local é feito para uma pessoa, na própria máquina: escuta por padrão só em `127.0.0.1`, não tem login nem limite de requisições, e as rotas que escrevem só aceitam `Content-Type: application/json`, o que impede que uma página aberta no navegador as dispare em segundo plano. Não o exponha numa rede nem na internet.
- Compartilhe com a integração do Notion só as páginas e os databases que ela precisa enxergar.

---

## 📖 Documentação

- 🏛️ [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md): as camadas, a direção das dependências e de onde veio cada arquivo.
- 📦 [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md): pacotes, binários nativos e a transição para o pacote único.
- ✅ [`docs/QUALIDADE.md`](docs/QUALIDADE.md): o gate e o critério de pronto.
- 🔗 [`docs/MCP.md`](docs/MCP.md): ferramentas MCP e integração com clientes.
- 🧱 [`docs/CONTRATOS.md`](docs/CONTRATOS.md): objetos, rotas REST e erros.
- 🐙 [`docs/GITHUB-DATABASE.md`](docs/GITHUB-DATABASE.md): manter seus repositórios do GitHub numa database do Notion.
- 🔄 [`docs/INTEGRACOES.md`](docs/INTEGRACOES.md): GitHub e ingestão de arquivos.
- 📊 [`docs/PADRAO-RELATORIOS.md`](docs/PADRAO-RELATORIOS.md): formato e regras dos relatórios diários.
- 🗺️ [`docs/README.md`](docs/README.md): índice da documentação, incluindo escala, SaaS, IA e roadmap.
- 🤖 [`AGENTS.md`](AGENTS.md) • [`CLAUDE.md`](CLAUDE.md) • [`IA.md`](IA.md): roteamento, contexto e histórico de decisões.

---

## 🌌 Ecossistema Felixo

Este projeto faz parte de um ecossistema maior de desenvolvimento com multiagentes, em ordem cronológica:

1. [Felixo-System-Design](https://github.com/Felipe-Alcantara/Felixo-System-Design) — padrão de qualidade e boas práticas de vibe coding
2. [Felixo-AI-Core](https://github.com/Felipe-Alcantara/Felixo-AI-Core) — orquestrador Electron para spawnar, monitorar e desenvolver com multiagentes
3. [Openia](https://github.com/Felipe-Alcantara/Openia) — qualquer modelo de IA na interface do Claude Code
4. **Felixo Notion MCP** — este projeto (antes, "Automações do Notion")
5. [OpenRouter-Monitorator](https://github.com/Felipe-Alcantara/OpenRouter-Monitorator) — métricas de uso e custo de modelos via OpenRouter

---

## 📝 Licença

Este projeto está sob a licença MIT — veja o arquivo [`LICENSE`](LICENSE).

---

## 👤 Autor

**Felipe Alcantara**

- GitHub: [@Felipe-Alcantara](https://github.com/Felipe-Alcantara)
- Repositório: [Felixo-Notion-MCP](https://github.com/Felipe-Alcantara/Felixo-Notion-MCP)

---

## 🤝 Contribuições

Contribuições são bem-vindas! Sinta-se à vontade para:

- Reportar bugs e propor melhorias
- Sugerir novas automações ou comandos
- Melhorar a documentação e o roteamento para agentes

Veja o [`CONTRIBUTING.md`](CONTRIBUTING.md) para o ambiente, os padrões e o fluxo de PR.

### 💡 Ideias para quem quiser contribuir

O projeto ainda pode crescer em várias direções, e qualquer uma delas é um bom ponto de partida:

- **Registro único de operações** para manter paridade entre MCP, CLI e API REST.
- **MCP hospedado**, com contas, OAuth do Notion e isolamento por usuário.
- **Teste automatizado de arquitetura** para proteger as fronteiras entre camadas.
- **Distribuição do pacote unificado e binários nativos**, incluindo assinatura e validação final por plataforma.
- **Evolução da SPA**, incluindo operações de escrita seguras para databases explorados.

---

⭐ Se este projeto foi útil, considere deixar uma estrela no GitHub!
