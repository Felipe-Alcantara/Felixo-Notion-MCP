# ✅ Qualidade

Este documento é o contrato de qualidade **deste repositório**. Ele traduz o
[Felixo System Design](https://github.com/Felipe-Alcantara/Felixo-System-Design) para os
checks reais do projeto, sem depender de memória de conversa.

> **Um repositório, um pacote, um gate.** Desde a etapa 1 do monólito (2026-10-07) o código
> das ferramentas vive em `src/felixo_notion_mcp/`, e o gate abaixo vale para tudo: biblioteca,
> CLI, servidor MCP, API Django e SPA. Não há mais gate por módulo. O mapa das camadas está em
> [`ARQUITETURA.md`](ARQUITETURA.md) e o roteamento por tipo de pedido, no
> [`AGENTS.md`](../AGENTS.md).

## Gate local

Antes de encerrar uma mudança, rode, na raiz do repositório:

```bash
uv sync --locked --all-extras    # dependências travadas em uv.lock, pacote em modo editável
uv run ruff check .              # lint (inclui scripts/ e tests/)
uv run python -m pytest          # a suíte inteira
```

Se a mudança tocou o `front/`, acrescente:

```bash
cd front
npm ci
npm run lint
npm run build
```

- `python start_app.py` é o menu interativo de entrada: instala o pacote em modo editável,
  configura o token e o database de tarefas no `.env` (os perfis de workspace são da CLI:
  `felixo-notion-mcp auth`), sobe o app e o servidor MCP e mostra o Status — sem decorar
  comando. O Status mostra também de onde o pacote é importado (a mesma informação do `doctor`).
- `uv run felixo-notion-mcp doctor` confere Python, dependências, perfis, rede, portas e **de
  onde o pacote está sendo importado** (a linha termina em `checkout editável` quando você está
  rodando o seu código). Ele só **informa**: o antigo `check-dev.py` foi aposentado e o `doctor`
  não avisa nem falha quando o pacote vem de outro lugar.
- Os testes mockam todo o HTTP: nenhum check exige token real do Notion, GitHub ou OpenRouter.

## CI

O workflow [`ci.yml`](../.github/workflows/ci.yml) roda a cada push no `main` e em todo PR:

- `ruff check .` e `pytest` em **Ubuntu, Windows e macOS × Python 3.11, 3.12 e 3.13** (o 3.10 saiu em 2026-10-21),
  com `uv sync --locked`;
- `npm run lint`, `npm run build` e `npm audit --audit-level=high` no `front/`;
- construção do wheel e **conferência do conteúdo** (`scripts/empacotamento/conferir_wheel.py`:
  o bundle da SPA e os assets que o `index.html` cita precisam estar dentro);
- `pip-audit` sobre o lock inteiro, em três passos (Python 3.13 e 3.11 no Linux, mais os pins
  que só existem em Windows e macOS).

Limites que dependem de um sistema específico ficam registrados em [`IA.md`](../IA.md). Hoje, o
build do binário nativo só foi exercitado em Linux x64.

## Critério de Pronto

Uma mudança só está pronta quando:

- O gate passou (`ruff` + `pytest`, e `lint` + `build` do front quando ele mudou) — ou a
  impossibilidade foi registrada com motivo objetivo.
- Comportamento novo ou bug corrigido tem teste quando aplicável.
- Documentação viva foi atualizada quando comandos, contratos, arquitetura, UX ou o
  **roteamento** mudam (`README.md`, `AGENTS.md`, `docs/ARQUITETURA.md`, `docs/`).
- O `IA.md` preserva o histórico: decisões novas entram como registros datados, sem apagar a
  linha de raciocínio anterior.
- Scripts e ferramentas reutilizáveis foram priorizados antes de edição manual; exceções foram
  registradas objetivamente.
- Documentação pública não promete estado futuro já resolvido: instalação, versão, links,
  entry points e limitações conferem com o que está publicado (hoje, os pacotes antigos; veja
  [`DISTRIBUICAO.md`](DISTRIBUICAO.md)).
- Links relativos apontam para arquivos existentes; nenhum documento manda clonar módulo, entrar
  em `modules/` ou rodar scripts que foram aposentados.
- Segredos, IDs reais e artefatos locais continuam fora do Git.
- As fronteiras de camada seguem intactas: `api/` (CLI, MCP, HTTP) não tem regra de negócio;
  `domain/` e `services/` não conhecem HTTP; só `integrations/notion_client.py` fala com a API
  do Notion; `core/` não depende de nenhuma outra camada.
- O contrato da CLI segue preso: o teste de `tests/contrato/` compara o parser com o retrato do
  que a CLI aceitava. Falha ali é regressão, não motivo para regravar o retrato.

## Git

- Refatoração estrutural de alto risco ou feature grande ganha **branch** (uma por etapa do
  plano, apagada depois do merge); ajuste pequeno pode ir direto ao `main` de quem mantém.
- Faça commits pequenos e coesos no formato `tipo: descrição` (`feat`/`fix`/`docs`/`refactor`/
  `chore`).
- **Um tema por commit.** Interno (`IA.md`, `AGENTS.md`), público (`README.md`, guias) e API
  (contratos de CLI, MCP e REST) não se misturam no mesmo commit.
- Atualize a documentação viva junto da mudança (no mesmo PR), em commits separados por tema.

## Referências

- [`AGENTS.md`](../AGENTS.md) — roteiro operacional para agentes e mantenedores.
- [`ARQUITETURA.md`](ARQUITETURA.md) — as camadas e de onde veio cada arquivo.
- [`IA.md`](../IA.md) — memória técnica e decisões do projeto.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — como contribuir.
- [Guia de distribuição](DISTRIBUICAO.md) — pacotes publicados, binários e a transição para o
  pacote único.
- [Felixo System Design](https://github.com/Felipe-Alcantara/Felixo-System-Design) — o padrão
  de qualidade de origem.
