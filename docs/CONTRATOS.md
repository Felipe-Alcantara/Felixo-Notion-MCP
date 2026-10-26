# 🧱 CONTRATOS — Domínio, API e estrutura (fixados pelo Agente 0)

> **O que é**: o contrato estável que os demais agentes consomem para trabalhar em
> paralelo sem divergir — objetos de domínio, formato das rotas REST e a estrutura de
> pastas do servidor. É o entregável da **Onda 1** (Agente 0 — Contratos & Fundação) do
> [AGENTES.md](AGENTES.md).
>
> **Por que existe**: o trabalho paralelo só converge se ninguém inventar o formato de um
> objeto ou rota que outro consome. Aqui isso fica escrito uma vez. Mudança quebradora é
> explícita, documentada e justificada (guarda-corpo de [PLANO.md](PLANO.md)).
>
> **Documento vivo**: evolui junto com `README.md` e `IA.md`. Os esboços de
> [PLANO.md](PLANO.md) (Fase 2) são a origem; este documento os fixa.

> **Localização atual:** a implementação está distribuída entre
> [`notion-starter`](https://github.com/Felipe-Alcantara/notion-starter),
> [`notion-tasks-cli`](https://github.com/Felipe-Alcantara/notion-tasks-cli) e
> [`notion-workspace-app`](https://github.com/Felipe-Alcantara/notion-workspace-app).
> Os caminhos de código usados nos exemplos apontam para esses repositórios.

---

## 📋 Índice

- [1. Objetos de domínio](#1-objetos-de-domínio)
- [2. Contrato das rotas REST](#2-contrato-das-rotas-rest)
- [3. Formato de erro](#3-formato-de-erro)
- [4. Estrutura de pastas do servidor](#4-estrutura-de-pastas-do-servidor)
- [5. Helpers de leitura (Fase 0)](#5-helpers-de-leitura-fase-0)

---

## 1. Objetos de domínio

Os objetos de domínio são **simples e estáveis**: a forma que front, IA e integrações
consomem, sem conhecer o JSON cru do Notion. A tradução entre o Notion e estes objetos é
responsabilidade da camada `integrations` (`notion_starter`), nunca da API nem do front.

### `Tarefa` (em [`tasks.py`](https://github.com/Felipe-Alcantara/notion-starter/blob/main/src/notion_starter/tasks.py))

A unidade central. **Este é o contrato — não redefinir os campos existentes; só estender.**

| Campo | Tipo | Significado |
|---|---|---|
| `id` | `str` | ID da página (a tarefa) no Notion. |
| `nome` | `str` | Texto do título. |
| `status` | `str \| None` | Nome da etapa atual (ou `None`). |
| `prazo` | `str \| None` | Data do prazo em ISO 8601 (ou `None`). |
| `duracao` | `str \| None` | Nome da opção de esforço (ou `None`). |
| `areas` | `list[str]` | IDs das páginas relacionadas em "Áreas da vida". |
| `areas_nomes` | `list[str]` | Nomes dessas áreas, resolvidos pela `TaskList` (vazio até o enriquecimento; `tarefa_de_pagina` é pura). |
| `url` | `str \| None` | Link da tarefa no Notion. |
| `bruto` | `dict` | JSON original, para campos não mapeados (não serializar na API). |

> **Contexto (ciclo 2):** `duracao` e `areas` foram acrescentados porque o uso real do
> database principal preenche `Etapa`, `Esforço` e `Áreas da vida` em 100% das tarefas,
> enquanto `Prazo`/`Prioridade`/`Projeto`/`Subitens` ficam vazios. O front e a CLI mapeiam
> o que de fato se usa. Campos novos são **aditivos** — clientes antigos continuam válidos.

**Serialização na API** (o que sai/entra em JSON nas rotas) — o subconjunto público de
`Tarefa`, **sem** `bruto`:

```json
{
  "id": "abc123",
  "nome": "Estudar a API do Notion",
  "status": "Entrada",
  "prazo": "2026-07-01",
  "duracao": "Dias",
  "areas": ["area-id-1"],
  "areas_nomes": ["Estudos"],
  "url": "https://notion.so/abc123"
}
```

### Mapeamento de colunas e multi-tabela (`CamposTarefa`)

Os nomes das colunas são **configuráveis por database** via `CamposTarefa`
(`nome`/`status`/`prazo`/`duracao`/`areas`), porque variam entre workspaces. O caso
principal hoje é o todolist da home (database "Tarefas — HOME (principal)"), mas a mesma
`TaskList` atende **outras tabelas** ao receber outro `database_id` + `CamposTarefa`. A
seleção de qual database alimentar a lista vive no `start_app.py` (grava
`NOTION_DATABASE_ID` no `.env`). Generalizar para qualquer database arbitrário é um ponto
de extensão futuro — o contrato já nasce configurável para não travar isso.

No database principal, o vocabulário canônico da fonte é: `Tarefa`, `Etapa`,
`Esforço`, `Prazo` e `Áreas da vida`. As opções também vêm da fonte, sem tradução
local no front: por exemplo `Entrada`, `Assim que possível`, `Concluída`, `Agora`
e `Hoje`.

### Objeto de valores simples de uma página

Saída de `readers.extrair_valores(pagina)` (ver §5): um mapa **`nome_da_coluna → valor
simples`**, usado por front/IA/integrações para ler qualquer página sem navegar o JSON
aninhado. Tipos ainda não suportados aparecem com valor `null`.

### Objetos de fases futuras (esboço, ainda não fixados)

Reservados aqui para as fases que os criam; o **Agente** dono de cada fase os fixa quando
implementar, mantendo a mesma filosofia (objeto simples + tradução isolada):

- `RepoInfo` — um repositório do GitHub (Fase 4, Agente Integrações).
- `ItemColetado` — um item de uma fonte de ingestão (Fase 3, Agente Integrações).
- `Modelo` — um modelo do catálogo OpenRouter (Fase 5, Agente IA).

---

## 2. Contrato das rotas REST

Base: `/api/`. Corpo e resposta em JSON. As views são **finas** (parse, validação,
delegação para `services`); a regra de negócio fica nos casos de uso
(`services/tarefas.py`), que são finos sobre a `TaskList`.

Toda rota que lê corpo (`POST` e `PATCH`) exige `Content-Type: application/json` e responde
`400 validacao` para qualquer outro tipo (texto, formulário ou sem tipo), antes de falar com o
Notion. As rotas não usam cookie de sessão, então o CSRF do Django não se aplica; esta exigência
é a defesa: o navegador só envia JSON de outro site depois de um preflight, que o servidor não
responde.

### `GET /api/tarefas` — listar

Lista as tarefas. Os filtros opcionais são aplicados na consulta ao Notion, não só no
front, para o database real continuar sendo a fonte de verdade.

- **Query string**:
  - `status` (opcional) — filtra por nome de status.
  - `duracao` (opcional) — filtra por nome da coluna de duração/esforço.
  - `area` (opcional, repetível ou CSV) — filtra por IDs relacionados em
    `Áreas da vida`.
- **200 OK**:

```json
{ "tarefas": [ { "id": "…", "nome": "…", "status": "…", "prazo": "…", "url": "…" } ] }
```

### `POST /api/tarefas` — criar

Cria uma tarefa nova.

- **Request body**:

```json
{ "nome": "Estudar a API do Notion", "status": "Entrada", "duracao": "Dias", "areas": ["area-id-1"], "prazo": "2026-07-01" }
```

  - `nome` (obrigatório); `status`, `duracao`, `areas` (lista de IDs) e `prazo`
    (ISO 8601) são opcionais.
- **201 Created**: o objeto `Tarefa` serializado (§1).
- **400**: `nome` ausente/vazio.

### `PATCH /api/tarefas/{id}` — editar

Atualiza uma tarefa existente. Aceita um ou mais campos; mover/concluir continua sendo
mudar `status`. **Retrocompatível**: `{ "status": … }` sozinho continua válido.

- **Path**: `id` — ID da página da tarefa.
- **Request body** (todos os campos opcionais, ao menos um obrigatório):

```json
{ "nome": "…", "status": "Concluída", "duracao": "Minutos", "areas": ["area-id-1"], "prazo": "2026-07-01" }
```

- **200 OK**: o objeto `Tarefa` serializado (§1).
- **400**: corpo vazio / sem campos. **404**: tarefa inexistente.

### `GET /api/opcoes` — opções para os seletores

Devolve os valores possíveis para o front/CLI montarem seletores em vez de texto livre.
Lidas do schema do database (Etapa/Esforço) e do database de áreas (relations).

- **200 OK**:

```json
{
  "status": ["Entrada", "Assim que possível", "Concluída", "..."],
  "duracao": ["Minutos", "Poucas horas", "Dias", "..."],
  "areas": [{ "id": "area-id-1", "nome": "Estudos" }, { "id": "area-id-2", "nome": "Trabalho" }]
}
```

### `GET /api/database-atual` — contexto da database ativa

Devolve a database de tarefas que a interface está operando naquele momento. Serve para a
UI indicar explicitamente qual tabela está ativa e oferecer um link de conferência no
Notion.

- **200 OK**:

```json
{
  "id": "<database_id>",
  "titulo": "Tarefas — HOME (pessoal)",
  "data_sources": ["Tarefas — HOME (pessoal)"],
  "url": "https://www.notion.so/<page_url>"
}
```

> **Confirmação antes de escrever**: criação e mudança de status são operações de
> **escrita**. Quando acionadas por IA/MCP (Fases 5–6), exigem confirmação humana antes de
> efetivar (`requiresConfirmation`); o guarda-corpo "copiloto que sugere e a pessoa
> confirma" vale para toda escrita originada de agente.

---

## 3. Formato de erro

Toda resposta de erro segue o mesmo envelope, para o front tratar de forma uniforme:

```json
{ "erro": { "codigo": "validacao", "mensagem": "O campo 'nome' é obrigatório." } }
```

| HTTP | `codigo` | Quando |
|---|---|---|
| 400 | `validacao` | Corpo/parâmetro inválido ou faltando. |
| 404 | `nao_encontrado` | Recurso (tarefa) inexistente. |
| 502 | `erro_upstream` | Falha ao falar com o Notion (após retries). |
| 500 | `erro_interno` | Qualquer outra falha inesperada. |

A `mensagem` é legível e **nunca** contém token, ID interno sensível ou caminho local.

---

## 4. Estrutura de pastas do servidor

Por camadas, conforme [PLANO.md](PLANO.md) → arquitetura-alvo. A fronteira entre camadas é
sagrada: **API não tem regra de negócio; regra de negócio não conhece HTTP; integração
externa fica isolada.**

```text
server/
├── config/         projeto Django (settings, urls, wsgi/asgi) — só fiação
├── api/            borda HTTP: views finas + urls (parse/validação/delegação)
├── services/       casos de uso (orquestram a TaskList, ingestão, sync) — a regra
├── integrations/   adaptadores externos isolados (notion_starter, github, openrouter)
├── core/           config por ambiente, logging, token — sem HTTP
└── operations/     estado operacional em SQLite (Job, Lock) — não é conteúdo

cli/                CLI para IA: borda fina sobre services/ (ler/editar/mover/…)
front/              SPA React + Tailwind + Vite (consome a API REST) — ciclo 2
```

- **`api`** depende de `services`; **`services`** depende de `integrations` e `core`;
  `integrations` e `core` não dependem de `api`. Sem dependência circular.
- **`cli/` e a camada MCP** (`server/mcp_server.py`) são **bordas finas** sobre os
  mesmos `services` — não reimplementam regra. MCP serve os agentes do Felixo-AI-Core;
  a CLI serve uso direto/scripts e uma IA local. O **front React** (`front/`) consome a
  mesma API REST; sem regra de negócio no front.
- O **conteúdo** (tarefas, páginas) é a fonte da verdade no Notion; o **SQLite** guarda só
  estado de execução (jobs, locks), nunca conteúdo.

---

## 5. Helpers de leitura (Fase 0)

Entregues em [`readers.py`](https://github.com/Felipe-Alcantara/notion-starter/blob/main/src/notion_starter/readers.py) — o par de
**leitura** dos helpers de **escrita** de [`properties.py`](https://github.com/Felipe-Alcantara/notion-starter/blob/main/src/notion_starter/properties.py).
Funções puras (sem rede), cada uma devolvendo um valor simples e tratando o campo vazio.

```python
from notion_starter import readers as r

r.ler_title(prop)        -> str          # "" se vazio
r.ler_rich_text(prop)    -> str
r.ler_select(prop)       -> str | None
r.ler_status(prop)       -> str | None
r.ler_multi_select(prop) -> list[str]
r.ler_date(prop)         -> str | None   # data de início (ISO)
r.ler_email/ler_url/ler_phone_number(prop) -> str | None
r.ler_number(prop)       -> float | int | None
r.ler_checkbox(prop)     -> bool
r.ler_relation(prop)     -> list[str]    # IDs das páginas relacionadas
r.ler_people(prop)       -> list[str]    # IDs das pessoas

r.ler_propriedade(prop)  -> Any          # despacha pelo campo "type"
r.extrair_valores(pagina) -> dict[str, Any]   # { nome_da_coluna: valor_simples }
```

`extrair_valores` é o atalho recomendado para front/IA/integrações lerem uma página
inteira de uma vez. Coberto por testes puros em
[`tests/test_readers.py`](https://github.com/Felipe-Alcantara/notion-starter/blob/main/tests/test_readers.py).
