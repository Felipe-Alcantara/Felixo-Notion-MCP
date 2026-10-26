# 🎭 Modelos de uso

> **O que é**: as formas de usar o projeto e para quem cada uma serve. Vai do uso mais
> simples (importar a biblioteca) ao mais ambicioso (agentes autônomos via MCP). Ajuda a
> escolher o ponto de entrada certo e a enxergar como as camadas se empilham.

> Veja também: [PLANO.md](PLANO.md) (roadmap e fases) e
> [PORTABILIDADE.md](PORTABILIDADE.md) (adaptar para outros casos).

> **Estado em 2026-09-04:** biblioteca, CLI, app local, SPA e MCP já estão
> disponíveis. A instalação pública recomendada é `pipx install
> "notion-automacoes[app]"`; exemplos com `notion-automacoes` são o fluxo
> distribuído e exemplos com `python -m cli` representam o checkout de
> desenvolvimento.

---

## 📋 Índice

- [🧩 As camadas de uso](#-as-camadas-de-uso)
- [👥 Personas](#-personas)
- [🎬 Cenários práticos](#-cenários-práticos)
- [🪜 Trilha de adoção](#-trilha-de-adoção)

---

## 🧩 As camadas de uso

O projeto é uma pilha: cada camada usa a de baixo e nenhuma obriga a de cima. Você pode
parar em qualquer degrau.

| # | Camada | Como se usa | Quando faz sentido |
|---|---|---|---|
| 1 | **Biblioteca** | `from notion_starter import NotionClient, TaskList` | Já existe um script/app seu e você só quer falar com o Notion de forma tipada |
| 2 | **Menu de entrada** | `python start_app.py` no checkout | Quer instalar, configurar o token, escolher database, mapear o workspace ou subir o app sem decorar comando |
| 3 | **Servidor + front web** | sobe o Django (API) e a SPA **React + Tailwind + Vite** | Quer ver, filtrar e editar suas tarefas reais numa interface própria (grade/lista/kanban) |
| 4 | **CLI para IA** | `notion-automacoes tasks` (ou `notion-tasks`), borda fina sobre `services/` | Quer que uma IA local ou um script leia/edite/mova tarefas, escolha database e receba JSON estável |
| 5 | **IA assistida** | a IA sugere, você confirma | Quer ajuda para priorizar, resumir, criar tarefas em linguagem natural |
| 6 | **Agentes via MCP** | o Felixo-AI-Core orquestra | Quer só ler e adicionar tarefas enquanto agentes executam e registram |

> **CLI (4) e MCP (6) são bordas finas sobre os mesmos `services/`** — CLI para uso
> direto/IA local, MCP para os agentes do Felixo-AI-Core; sem duplicar regra.
>
> As camadas 1–4 já existem: biblioteca, menu, API + front React e CLI para IA. As camadas
> 5–6 seguem como evolução sobre a base já entregue (IA assistida e agentes via MCP).

Exemplos de CLI para consumo por IA/script:

```bash
notion-automacoes --json tasks listar --status "Entrada" --duracao "Dias" --area <area_id>
notion-automacoes --json tasks criar "Nova tarefa" --status "Entrada" --duracao "Dias"
notion-automacoes --json tasks editar <task_id> --status "Assim que possível" --area <area_id>
notion-automacoes --json tasks opcoes
notion-automacoes --json tasks normalizar-nomes --dry-run
notion-automacoes --json tasks mapear
```

---

## 👥 Personas

- **A pessoa dona do workspace** (uso central deste projeto): quer um "Notion do seu
  jeito" — lê, filtra, adiciona tarefas, e deixa a IA/agentes cuidarem do resto.
- **A desenvolvedora que integra**: pega só a **biblioteca** como base tipada para a
  própria integração com o Notion, sem querer o resto.
- **Quem usa como template**: clona, renomeia o pacote, troca o schema e adapta para um
  domínio diferente (ver [PORTABILIDADE.md](PORTABILIDADE.md)).
- **Quem contribui**: pega uma fase do roadmap ou uma ideia aberta e implementa de forma
  isolada.

---

## 🎬 Cenários práticos

### 1. "O que eu faço hoje?"
Lista as tarefas do dia (filtro por status/duração/área, e futuramente prazo) e, na
camada de IA, pede um resumo priorizado. Base já pronta:
`TaskList.listar(status=..., duracao=..., areas=[...])`.

### 2. "Cria essa tarefa pra mim"
Em linguagem natural → a IA propõe a tarefa (nome, status, prazo) → você confirma →
`TaskList.criar(...)` escreve no Notion. O modo confirmar-antes-de-escrever é o padrão
inicial.

### 3. "Organiza esses arquivos no Notion"
Aponta uma pasta local; o servidor analisa os arquivos, extrai metadados/resumo e cria
páginas organizadas (Fase 3 do roadmap).

### 4. "Cada projeto do meu GitHub vira uma página + tarefa"
O conector lê os repositórios e gera, por projeto, uma página descritiva e um tópico no
todolist (Fase 4 do roadmap).

### 5. "Vários agentes trabalhando, eu só acompanho"
O estado-alvo: você lê e adiciona tarefas; agentes orquestrados pelo Felixo-AI-Core
executam (código, artigos, pesquisas…) e registram de volta no Notion (Fase 6).

---

## 🪜 Trilha de adoção

Uma ordem natural de crescer, sem pular degraus:

```text
1. Biblioteca / menu  →  já dá valor (ler e escrever no Notion de forma tipada)
2. Servidor + front   →  o momento aha: ver, filtrar e editar tarefas reais (SPA React)
3. CLI para IA        →  uma IA local/script opera o todolist por linha de comando
4. IA assistida       →  a IA sugere; você confirma cada escrita
5. Fontes de dados    →  arquivos locais e GitHub viram páginas/tarefas
6. Agentes via MCP    →  o cérebro (Felixo-AI-Core) assume a execução
```

Cada degrau é útil sozinho. A graça do projeto é que você colhe valor desde o primeiro,
sem precisar do topo da pilha.
