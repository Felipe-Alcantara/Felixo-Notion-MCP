# 🤝 Contribuindo com o Felixo Notion MCP

Obrigado por querer contribuir! Este repositório reúne, num único pacote Python
(`felixo-notion-mcp`, import `felixo_notion_mcp`), tudo o que antes era o `notion-starter`
(biblioteca), o `notion-tasks-cli` (CLI para IAs, o "MCP via CLI"), o `notion-workspace-app`
(API Django, SPA React, servidor MCP e menu) e o hub de documentação. Issues, correções de
documentação, novos subcomandos, helpers, exemplos, testes, melhorias de resiliência e de UX
no front são bem-vindos.

> Contribuições devem preservar os contratos existentes, a documentação viva e o gate de
> qualidade descritos abaixo.

**Nota de transição.** Os pacotes que estão no PyPI hoje continuam `notion-automacoes`,
`notion-starter` e `notion-workspace-app`; o pacote `felixo-notion-mcp` é construído a partir
deste repositório, mas só é publicado na etapa 4 do plano (veja
[`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md)). Para contribuir, nada disso muda: o código
está aqui.

---

## 🚀 Como Contribuir

1. **Faça um fork** do repositório.
2. **Crie uma branch** descritiva (`fix/...`, `feat/...`, `docs/...`) para mudanças grandes;
   correções pequenas podem ir direto no `main` de quem mantém.
3. **Faça suas mudanças** seguindo os padrões abaixo.
4. **Rode os testes e o lint** antes de abrir o PR.
5. **Abra um Pull Request** explicando o que mudou e por quê.

Não tem certeza por onde começar? Abra uma issue descrevendo a ideia — a gente conversa antes
de você investir tempo no código. A seção "Contribuições" do [`README.md`](README.md) lista
ideias abertas.

---

## 🛠️ Ambiente de Desenvolvimento

```bash
git clone https://github.com/Felipe-Alcantara/Felixo-Notion-MCP.git
cd Felixo-Notion-MCP
python start_app.py          # menu: Instalar/Setup, Configurar, Iniciar, Status

# Ou manualmente, com as dependências travadas em uv.lock:
uv sync --locked --all-extras
uv run ruff check .
uv run python -m pytest      # HTTP mockado: não precisa de token nem de rede

# Gate do front (SPA React)
cd front
npm ci
npm run lint
npm run build
```

Requer Python 3.11+ e, para o front, Node 20.19+ ou 22.12+. O `wheel` leva a SPA já
compilada; Node e npm só são necessários no checkout de desenvolvimento. Copie
`.env.example` para `.env` apenas para uso real contra um workspace do Notion — nunca
versione o `.env`.

**Editou o código e nada mudou?** Rode `uv run felixo-notion-mcp doctor` (ou olhe a linha
"Origem do pacote" no Status do `start_app.py`): ele mostra de onde o `felixo_notion_mcp` está
sendo importado e se é o checkout editável. Se a pasta não for a `src/felixo_notion_mcp` do
seu clone, uma cópia instalada em outro lugar está sendo executada no lugar do seu código. O
`doctor` só **informa**; ele não avisa nem falha por isso.

---

## 🧭 Onde mexer

O código fica em `src/felixo_notion_mcp/`, em camadas: `domain/`, `services/`,
`repositories/`, `integrations/`, `api/` e `core/`. A tabela "o pedido mexe em… → arquivo" do
[`AGENTS.md`](AGENTS.md) e o mapa de [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) dizem em
qual arquivo cada tipo de mudança entra.

---

## ✅ Padrões de Qualidade

- **Entenda o padrão existente antes de alterar.** As fronteiras de camada valem: a borda
  (`api/`: CLI, MCP, HTTP) valida argumentos, formata a saída e delega — **sem regra de
  negócio**; `domain/` e `services/` **não conhecem HTTP**; só `integrations/notion_client.py`
  fala com a API do Notion; `core/` não depende de nenhuma outra camada. Se uma borda precisa
  de uma regra, ela vira um caso de uso em `services/`.
- **Prefira a solução mais simples** que resolva o problema real. O pacote tem poucas
  dependências de runtime de propósito.
- **Preserve contratos.** São consumidos por IAs, scripts e pelo front, e mudança quebradora
  precisa ser explícita e documentada (no `--help`, no `README.md` e no `IA.md`):
  - assinaturas públicas da biblioteca, objetos (`Tarefa`, `RepoInfo`…) e exceções
    (`NotionSyncError` e derivadas);
  - o envelope JSON da CLI (`{ok, dados}` / `{ok, erro}`) e os nomes e argumentos dos
    subcomandos — o teste de contrato `tests/contrato/` compara a CLI com um retrato do que
    ela aceita, e uma falha ali é regressão, não motivo para regravar o retrato;
  - o apelido `notion-tasks`, que é permanente;
  - as rotas REST, os serializers, o envelope de erro (`validacao`, `nao_encontrado`,
    `erro_upstream`, `erro_interno`) e as ferramentas `notion.*` do MCP.
- **Tipos e validação.** `TypedDict` para payloads, `dataclass` para resultados; valide
  entradas externas. Operações destrutivas exigem confirmação explícita (ex.:
  `apagar-bloco --sim`).
- **Não exponha segredos.** Nada de tokens, IDs reais ou URLs privadas no código, nos testes
  ou na documentação; o SQLite operacional fica fora do git.
- **Teste o comportamento.** Bugs corrigidos viram caso de regressão; o HTTP é sempre
  mockado com `responses`, e os serviços recebem doubles por injeção.
- **Código, docstrings e mensagens de erro em português.**
- **Atualize a documentação viva** (`README.md`, `--help` da CLI, `docs/` e `IA.md`) no mesmo
  passo quando a mudança alterar comportamento, estrutura ou comandos.

---

## ✍️ Padrões de Linguagem (Documentação e Logs)

- **Escreva para qualquer leitor** — linguagem geral e acessível, sem jargão interno.
- **Sem valores hardcoded** — use placeholders genéricos em vez de caminhos, tokens ou IDs
  reais.
- **Enquadre o trabalho futuro como convite à contribuição** em vez de uma lista de tarefas
  interna.

---

## 🔄 Fluxo de Pull Request

Um bom PR responde claramente:

- **O que mudou?**
- **Por que mudou?**
- **Como foi validado?** (ex.: `uv run ruff check .` + `uv run python -m pytest`, e
  `npm run lint` + `npm run build` quando o `front/` mudou)
- **Qual risco sobrou?**

Mantenha o PR focado: evite misturar refatoração ampla com novas funcionalidades. Use commits
pequenos no formato `tipo: descrição` (`feat`/`fix`/`docs`/`refactor`/`chore`), **um tema
por commit**: uma decisão interna (`IA.md`), uma mudança pública (`README.md`, guias) e uma
mudança de contrato (CLI, MCP, REST) são commits diferentes. A CI roda a suíte em Ubuntu,
Windows e macOS com Python 3.11 a 3.13, mais `pip-audit` e `npm audit`.

---

## 💬 Código de Conduta

Seja respeitoso e acolhedor. Este é um espaço para aprender e construir juntos —
contribuições de pessoas de todos os níveis de experiência são bem-vindas.
