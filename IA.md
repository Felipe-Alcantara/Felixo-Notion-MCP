# 🤖 IA.md — Contexto operacional do projeto

> **O que é**: Memória técnica do projeto para retomada de contexto por IA ou por
> um novo mantenedor, sem precisar reler todo o código ou o histórico de conversa.
> Baseado no template de contexto do Felixo System Design.

> ⚠️ **NOTA DE ESTRUTURA (2026-07-02)**: o monorepo descrito neste documento foi
> separado em módulos. Os caminhos citados abaixo (`src/`, `cli/`, `server/`,
> `front/`) hoje vivem em repositórios próprios — veja o mapa de roteamento no
> **`AGENTS.md`** deste hub, que é o guia operacional atual. Este arquivo permanece
> como **histórico de decisões** (as decisões continuam válidas; só os caminhos
> mudaram): `src/notion_starter` → repo `notion-starter`; `cli/` + `core/` +
> `integrations/` + `services/` → repo `notion-tasks-cli`; `server/` + `front/` +
> `start_app.py` → repo `notion-workspace-app`.

> ⚠️ **NOTA DE ESTRUTURA (2026-10-07)**: a separação acima foi desfeita. Os três
> módulos voltaram para este repositório como um **pacote único**,
> `felixo-notion-mcp` (import `felixo_notion_mcp`), organizado em camadas em
> `src/felixo_notion_mcp/`. Quando uma entrada datada abaixo citar `notion_starter`,
> `cli/`, `server/` ou `modules/`, o caminho de hoje está na tabela origem → destino
> de [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md). O registro completo da mudança é a
> entrada "Etapa 1 do monolito", no fim deste arquivo.

---

## 📊 ESTADO ATUAL (RESUMO VIVO)

<!--
  EXCEÇÃO à regra append-only: esta seção é um RESUMO reescrevível.
  Ela responde "onde o projeto está AGORA" em poucas linhas. Reescreva-a
  livremente a cada mudança de estado — o histórico detalhado continua
  protegido nas seções datadas abaixo e nos archives.
-->

Última atualização: [2026-10-19] — só as linhas de gate e de dependências; o resto é de
[2026-10-07] e não foi reconferido.

- **Fase**: etapa 1 do monolito concluída na branch `refactor/monolito`, à espera do
  merge no `main`. O hub e os três módulos (`notion-starter`, `notion-tasks-cli`,
  `notion-workspace-app`) viraram um pacote só, `felixo-notion-mcp` `0.6.0.dev0`, em
  camadas `domain`, `services`, `repositories`, `integrations`, `api` e `core`. Não há
  mais `modules/`: o código vive em `src/felixo_notion_mcp/`. As etapas 2 a 4 (paridade
  MCP, modo hospedado, migração dos consumidores e distribuição) seguem a spec de
  `docs/superpowers/specs/2026-10-07-monolito-felixo-notion-mcp-design.md`.
- **Gate**: `uv sync --locked --all-extras`, `uv run ruff check .` e
  `uv run python -m pytest` (1782 passed, 4 skipped em 2026-10-19); no `front/`,
  `npm run lint` e `npm run build`. A CI roda em Ubuntu, Windows e macOS com Python
  3.10 a 3.13, mais `pip-audit` e `npm audit`. Nenhum check exige token real.
- **Dependências** (2026-10-19): SDK `mcp` 2.x (`mcp>=2.3,<3`, `MCPServer`), ruff 0.17 e
  lock Python e `front/` atualizados dentro das faixas. Os majors do `front/` (React 19,
  framer-motion 14) ficaram para depois. O `notion-tasks` que os agentes do AI Core usam
  roda do `.venv` deste checkout, então `uv sync --locked --all-extras` depois de mudar o
  lock é o que o mantém em dia. Detalhes na entrada datada de 2026-10-19.
- **Ferramentas aposentadas**: `bootstrap.py`, `check-dev.py`, `sync.py` e `SYNC.md`
  saíram. A pergunta do `check-dev.py` ("o código que roda é o que eu edito?") virou
  `felixo-notion-mcp doctor` e a linha de origem do Status do `start_app.py`; os dois
  só informam, não avisam como o `check-dev.py` fazia.
- **Roteamento de agentes**: `AGENTS.md` e `CLAUDE.md` roteiam por camada
  (`src/felixo_notion_mcp/<camada>/<arquivo>`). O mapa de camadas e a tabela origem →
  destino estão em `docs/ARQUITETURA.md`.
- **Distribuição**: os pacotes publicados continuam `notion-automacoes` `0.5.0`,
  `notion-starter` e `notion-workspace-app`, e os binários continuam
  `notion-automacoes-<alvo>`; nada disso muda até a etapa 4. O binário nativo foi
  construído e testado só em Linux x64 (entrada de 2026-10-07 sobre o empacotamento).
- **Histórico**: registros de junho/2026 (era monorepo) arquivados em
  [`docs/ia-archive/IA-ARCHIVE-2026-06.md`](docs/ia-archive/IA-ARCHIVE-2026-06.md); os
  `IA.md` dos três módulos, na íntegra, em
  [`docs/ia-archive/`](docs/ia-archive/) (`IA-notion-starter.md`,
  `IA-notion-tasks-cli.md`, `IA-notion-workspace-app.md`).
- **Estado legal**: o pacote e o repositório identificam `Felipe Alcantara` como
  titular; colaboradores não alteram essa titularidade.
- **Próximos passos**: a CI em Windows e macOS roda pela primeira vez no push e no PR
  da etapa 1 (tarefa 11); depois vem a etapa 2 (`feat/paridade-mcp`). Melhorias de
  produto continuam abertas à comunidade.

[2026-08-21] O setup do hub passou a instalar `notion-starter` antes de
`notion-tasks-cli`, ambos em modo editável a partir de `modules/`. Isso evita
que o executável global use uma cópia antiga em `site-packages` e mantém a CLI
alinhada ao working copy preparado pelo `bootstrap.py`. O README documenta o
fluxo multiplataforma e o gate foi validado com 352 testes do starter e 168 da
CLI, além do `ruff` da CLI.

[2026-07-18] Registros de junho/2026 (era monorepo) movidos na íntegra para
`docs/ia-archive/IA-ARCHIVE-2026-06.md` (compactação sem perda do template).

---

## 🎯 OBJETIVO DO PROJETO

[2026-06-24] `notion-starter-boilerplate` é um boilerplate/template open source para
iniciar projetos sobre a API do Notion. Traz um cliente Python tipado, helpers de
propriedade, validação de schema e exceções claras como base pronta para clonar e
adaptar. Independente de framework, uma única dependência de runtime (`requests`).
Público: desenvolvedores que vão começar uma integração com o Notion.
Distribuição: como TEMPLATE (clone/"Use this template" e renomeie), não como pacote
PyPI fechado. O `pyproject.toml` segue funcional para `pip install -e` local.

[2026-06-29] O repositório público `Automa-es-do-Notion` passou a ser documentado como
aplicação local de automações para Notion, GitHub e IA, não como template genérico.
O core `notion_starter` continua sendo a base importável, mas README, metadados do
`pyproject.toml`, CONTRIBUTING e `start_app.py` agora descrevem o produto real.

---

## 🏁 METAS & MILESTONES

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md)._

---

## 🛠️ STACK & DEPENDÊNCIAS

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
Stack atual do hub: Python 3.10+ (scripts de workspace, sem dependência de
runtime além de `requests`/`pytest` para dev); código e dependências reais nos
módulos._

---

## 📐 DECISÕES DE ARQUITETURA

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
As decisões continuam válidas — só os caminhos mudaram para os módulos (ver
nota de estrutura no topo)._

---

## 🎨 DECISÕES DE DESIGN & CONVENÇÕES

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
Convenções vigentes resumidas no `AGENTS.md` (português, Conventional Commits,
fronteiras de camada)._

---

## 🧪 TESTES IMPORTANTES

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
As suítes vivem nos módulos; o gate do hub é `check-dev.py`._

---

## 🐛 BUGS & FIXES RELEVANTES

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md)._

---

## 🔗 INTEGRAÇÕES & SERVIÇOS EXTERNOS

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
Integrações (Notion, OpenRouter, GitHub, MCP) configuradas nos módulos; nenhum
segredo versionado._

---

## 📝 NOTAS GERAIS

_Registros de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md)._

---

## 🧠 RESUMOS DE DECISÃO

_Resumos de junho/2026 no [archive](docs/ia-archive/IA-ARCHIVE-2026-06.md).
Abaixo, os registros da era hub (julho/2026 em diante)._

[2026-07-06] CONTEXTO: Rodada de padronização do hub segundo o Felixo System Design
("Padrão de qualidade"). O hub tinha diretórios fantasma remanescentes da divisão do
monorepo (`cli/`, `server/`, `src/`, `tests/` contendo apenas `__pycache__`), caches de
tooling (`.pytest_cache/`, `.ruff_cache/`) e o `operacional.sqlite3` (estado do app antigo,
gitignorado) na raiz — ruído que não pertence a um repositório que é só documentação e
roteamento. O README já era forte, mas faltavam seções obrigatórias do padrão de README.
DECISÃO: (1) remover o resíduo local do monorepo, deixando na raiz apenas docs + roteamento
+ ferramentas de bootstrap (`bootstrap.py`, `sync.py`, `check-dev.py`); (2) completar o
README com as seções ⭐ obrigatórias que faltavam — Índice, Estrutura do Projeto (árvore do
hub), Autor e o rodapé de Contribuições + CTA — e padronizar o header (badges
`for-the-badge`, descrição em negrito, links rápidos). Não alterei a titularidade do
`LICENSE` (copyright "André Gustavo" difere do autor Git "Felipe Martin"): mudança de
titularidade de licença é decisão do dono, fica registrada aqui como pendência a confirmar.
VALIDAÇÃO: âncoras do Índice conferidas contra os cabeçalhos `##` do README; `git status`
antes da limpeza estava limpo (o resíduo era não rastreado/ignorado, então a remoção não
afeta o histórico versionado). Nenhum código foi tocado — funcionalidade continua vivendo
nos módulos, conforme AGENTS.md.

[2026-07-06b] CONTEXTO: Ergonomia de desenvolvimento dos módulos (task "verificar se está
fácil tanto para uso quanto para desenvolvimento"). Observado que os módulos estavam
clonados em DOIS lugares — em `modules/` (cópia feita pelo bootstrap dentro do hub) e na
pasta acima (`../notion-starter`, `../notion-tasks-cli`, `../notion-workspace-app`), mesmos
remotes e commits. O `bootstrap.py` antigo sempre criava a cópia dentro do hub, ignorando o
clone que já existia, gerando duplicação e ambiguidade sobre "onde eu desenvolvo".
DECISÃO: `bootstrap.py` passa a reusar o clone existente. Ordem de preferência por módulo:
(1) já preparado em `modules/<nome>` → `git pull --ff-only`; (2) já clonado em `../<nome>` →
cria um LINK em `modules/<nome>` apontando para lá (junction no Windows via `mklink /J`, que
não exige admin; symlink no POSIX), reusando o mesmo working copy; (3) não existe →
`git clone` do GitHub. `modules/<nome>` segue sendo o caminho canônico de dev, então
check-dev.py e todo o roteamento do AGENTS.md continuam válidos sem mudança — o `.git` é
resolvido através do link. Escolhi o link (em vez de "só usar ../<nome>") para não quebrar
nada que já aponta para `modules/`.
VALIDAÇÃO: removido `modules/`, rodado `python bootstrap.py` → detectou os três clones em
`../` e criou junctions (confirmado por `os.path.realpath('modules/notion-starter')` →
`...\Github\notion-starter`); `git pull --ff-only` rodou dentro de cada link ("Already up to
date"); `python check-dev.py` reporta os três `[OK]` (o `.git` é encontrado através da
junction). Docs vivas atualizadas no mesmo passo: README (seção "Primeiro passo") e AGENTS.md
(pré-requisito bootstrap).

[2026-07-06c] CONTEXTO: Lote de tarefas de uso/dev vindas de agentes que operavam o Notion:
(1) "resolver as propriedades" — ao editar uma página que é linha de database, os agentes só
mexiam no conteúdo (blocos), nunca nas propriedades, a menos que explicitados; (4) proposta de
um comando "editar-linha" no notion-tasks-cli (o CLI cobria conteúdo e tarefas, mas não editava
propriedades de linhas genéricas, forçando ir à API crua com o token do hub); (3) tornar o
append de conteúdo seguro (preservar o existente, respeitar limites, verificar pós-PATCH).
DECISÃO: as tarefas 1 e 4 têm a mesma raiz — faltava um caminho de propriedades para linha
genérica. Adicionado `NotionClient.obter_pagina` no notion-starter (GET /pages/{id} já traz o
`type` de cada coluna) e o comando `editar-linha <page_id> --set "Nome=valor"` no
notion-tasks-cli (`services/propriedades.py`), que infere o tipo da própria página, converte o
valor (title, rich_text, number, checkbox, select, status, multi_select, relation, people, date
com intervalo "inicio..fim", email, phone, url), limpa com valor vazio e recusa tipos calculados.
O `--help`/guia passou a recomendar "comece pelas propriedades, depois o conteúdo" — atacando a
raiz da tarefa 1 (agora há caminho e ele é o recomendado). Tarefa 3: `escrever_conteudo` passou a
anexar em lotes de 100 (limite do Notion por requisição; o limite de 2000 chars/rich_text já era
tratado por `content.py` na lib) e a confirmar, pela resposta da API, que todos os blocos foram
criados (erro em escrita parcial); o append sempre entra ao final, preservando o existente. A
correção de conteudo.py foi espelhada em notion-workspace-app/server (camada services duplicada).
VALIDAÇÃO: notion-starter 21/21 testes; notion-tasks-cli 72/72 (incl. novos test_services_
propriedades e test_services_conteudo, e casos de editar-linha no test_cli); notion-workspace-app
test_services_conteudo 12/12 (novo teste de lotes via callback do `responses`). Smoke test:
`python -m cli editar-linha --help` e `guia` mostram o comando e a nova dica. Os três repos foram
commitados e publicados no main. PENDÊNCIA de runtime: o notion_starter instalado (site-packages,
via git+https) ainda não tem `obter_pagina` — é preciso reinstalar a dependência para o
`editar-linha` funcionar em execução real (os testes usam doubles e não dependem disso).

[2026-07-06d] CONTEXTO: Ao atualizar o relatório diário no Notion (database "Relatórios
diários"), caí exatamente no vício da tarefa 1: atualizei o CONTEÚDO (blocos, via `escrever`)
e esqueci as PROPRIEDADES (colunas rich_text "O que fiz", "Resumo", "Próximos passos"). O
usuário apontou. Além disso pediu que a PRÓPRIA ferramenta recomende, de forma explícita,
mexer nas propriedades primeiro e no conteúdo depois.
DECISÃO: (1) Atualizei as propriedades preservando o conteúdo original — peguei os objetos
rich_text originais de cada coluna e anexei um item novo ao final (respeitando o teto de 2000
unidades por item), via `atualizar_pagina`; isso é exatamente o comportamento que a tarefa 3
descrevia para rich_text. (2) Reforcei o guia do CLI: novo campo estrutural
`fluxo_recomendado` (guia --json e humano) com a REGRA "propriedades primeiro (editar-linha),
conteúdo depois (escrever)", e os `--help` de `editar-linha` e `escrever` passaram a apontar a
ordem. Commit `feat` no notion-tasks-cli (add8e33), com teste garantindo a ordem no guia.
LIMITAÇÃO REGISTRADA (próximo passo): o comando `editar-linha` faz FULL-REPLACE do valor e o
builder `properties.rich_text` cria um único item — ou seja, não fatia texto >2000 nem anexa
preservando o existente. Para colunas rich_text longas (como as do relatório) hoje é preciso ir
via `atualizar_pagina` montando o array. Ideia: dar ao `editar-linha` um modo "append" e fazer
o builder de rich_text fatiar em ≤2000 como o `content.py` já faz para blocos.
VALIDAÇÃO: notion-tasks-cli 74/74 testes; guia humano mostra o fluxo em destaque; relatório
06/07 conferido via API — "O que fiz" (6932 chars, 5 itens: 4 originais + 1 novo), "Resumo"
(2064, 2 itens) e "Próximos passos" (1355, 2 itens) com o texto original íntegro no início e a
seção Automações do Notion ao final; Status/Área/Data mantidos.

[2026-07-06e] CONTEXTO: Fechar a lacuna registrada em [2026-07-06d]: o `editar-linha` fazia
full-replace e não fatiava rich_text >2000, então atualizar propriedades longas (como as do
relatório) exigia montar o array via API na mão. Pedido: deixar tudo preparado para uso da
forma mais otimizada, seguindo o padrão.
DECISÃO: (1) Na lib (notion-starter): centralizei a fatia UTF-16 em `utils.fatiar_utf16` e o
teto em `constants.MAX_RICH_TEXT` (antes privados em content.py — agora reusados sem duplicar,
content.py passou a importá-los), e os builders `properties.title`/`rich_text` passaram a
fatiar texto >2000 em vários itens que o Notion concatena. Texto curto segue gerando 1 item
(compatível). (2) No CLI (notion-tasks-cli): `editar-linha` ganhou `--append "Nome=texto"`, que
acrescenta ao final de colunas de texto preservando os itens rich_text originais (lê via
obter_pagina, limpa os itens para forma gravável, junta o texto novo fatiado, num único PATCH);
`--set` segue substituindo. Valida conflito set+append na mesma coluna e append em coluna não
textual. O append NÃO apara espaços (preserva o separador \n\n), diferente do --set.
(3) Dev: instalei o notion-starter em modo EDITÁVEL apontando para o clone local (via o junction
de modules/), então mudanças na lib valem na hora para o CLI, sem reinstalar do git a cada vez —
o setup de desenvolvimento mais otimizado, alinhado ao fluxo de junctions do bootstrap.
VALIDAÇÃO: notion-starter 171/171 (novos testes de fatia: 4500 chars→[2000,2000,500], emoji
conta 2 unidades UTF-16, vazio→1 item); notion-tasks-cli 79/79 (append preserva original,
fatia em 2000, erro em coluna não-texto, erro set+append na mesma coluna, set+append juntos em
colunas diferentes). End-to-end real na Notion: `editar-linha <relatório> --append "Resumo="`
(no-op) reenviou os itens originais e o Resumo continuou com 2 itens/2064 chars — preservação
confirmada sem poluir. Commits e push: notion-starter (d278d3d), notion-tasks-cli (ad2e52a).

[2026-07-06f] CONTEXTO: Fechamento da rodada — garantir que git, docs e a database (relatório
no Notion) reflitam tudo, seguindo o padrão de qualidade.
DECISÃO: (1) Git: os quatro repositórios (hub + três módulos) já estavam commitados (Conventional
Commits, docs no mesmo passo) e sincronizados com o origin/main — confirmado por fetch, sem
ahead/behind. (2) Docs vivas atualizadas: hub AGENTS.md (roteamento MODO USO ganhou `editar-linha`
com a ordem propriedades→conteúdo; MODO DEV ganhou linhas para `obter_pagina`/`atualizar_pagina`
e `services/propriedades.py`), hub README (comandos e tabela de roteamento com editar-linha e
obter_pagina), e notion-starter README/AGENTS (obter_pagina, builders de propriedade que fatiam
>2000, `utils.fatiar_utf16`). (3) Database: o relatório de 06/07 foi atualizado com o trabalho
mais recente usando a PRÓPRIA CLI — `escrever` para o conteúdo e `editar-linha --append` para as
colunas "O que fiz", "Resumo" e "Próximos passos" (dogfooding do modo append), preservando o
conteúdo original.
VALIDAÇÃO: relatório conferido via API — "O que fiz" 6 itens/7311 chars, "Resumo" 3/2387,
"Próximos passos" 3/1510, todos com o texto original íntegro no início e a atualização ao final.
Commits/push: notion-starter docs (81ecb75); hub (docs de roteamento) neste passo.

[2026-07-07] CONTEXTO: Task do Notion "Colocar um módulo de github para notion" (Prioridade
Hiperfoco/Urgente) pedia um módulo que importasse repositórios do GitHub para uma database do
Notion e fosse fácil de atualizar. Investigação mostrou que a FUNCIONALIDADE JÁ EXISTIA madura no
`notion-tasks-cli` (`services/inventario_github.py` + `integrations/github.py`, exposta pelo
comando `atualizar-github`): upsert por URL, ~20 propriedades ricas, README em subpágina com
detecção de mudança por hash. O trabalho real foi documentar/expor e estender, não recriar.
DECISÃO: (1) Documentar/expor — novo guia `docs/GITHUB-DATABASE.md` (uso, rotina, FAQ), linkado no
README e no AGENTS (a tabela MODO USO não citava `atualizar-github`; agora cita). (2) Estender — o
serviço e o CLI ganharam `ignorar_arquivados`/`--sem-arquivados` para manter a database só com
repositórios ativos; filtro aplicado no ponto compartilhado `_coletar_repos` (vale para
`exportar_repos` e `atualizar_repos`), com testes de serviço e de CLI. (3) Qualidade do hub
(Felixo): o hub ganhou `start_app.py` — menu interativo obrigatório (contrato #11) que instala a
CLI, sincroniza módulos, configura o `.env` e opera o Notion; documentado no README como forma
principal de rodar. `docs/QUALIDADE.md` estava desatualizado (descrevia o gate do antigo monorepo:
`scripts/quality_check.py`, `front/`, npm, `CONTRIBUTING.md` — nada disso existe no hub); reescrito
para a realidade do hub (gate = `check-dev.py`/`start_app.py`; gate de código = `pytest` por módulo).
VALIDAÇÃO: suíte do `notion-tasks-cli` verde (82 passed); `--sem-arquivados` aparece no `--help` e é
propagado ao serviço (teste de CLI); `start_app.py` valida sintaxe, helpers e renderiza o Status.
Commit/push do código vai no repo do módulo (`notion-tasks-cli`), não no hub.

[2026-07-07b] CONTEXTO: Pedido de portar as funções de coleta/análise do app React
`Felipe-Alcantara/Git-Hub-Repositories` para o Notion — "principalmente importar vários perfis de uma
vez, verificando duplicatas". INVESTIGAÇÃO: a função destacada JÁ existia no ecossistema
(`atualizar-github --contas a,b,c`: multi-conta, dedup por URL/upsert, privados do usuário
autenticado, resiliente por conta). Cruzando o app com o módulo, faltavam de fato duas coisas: (1)
aceitar URL de perfil/`@handle` (o app tem `extractUsername`); (2) sync incremental por data
(`updated_at`) que o app usa para pular repos sem mudança e reportar novos/atualizados/pulados.
DECISÃO — ONDE MORAR (seguindo o padrão de qualidade #9, evitar duplicação): `integrations/github.py`
era byte-idêntico nos dois repos (`notion-tasks-cli` e `notion-workspace-app/server`) e
`inventario_github.py` só divergia pela minha edição `--sem-arquivados` de [2026-07-07] que eu tinha
esquecido de espelhar (drift proibido pelo AGENTS). Consolidar a camada no `notion-starter` é o
passo de roadmap, mas é refactor grande/arriscado (imports de 3 repos + Django/MCP) —
desproporcional. Escolhi: escrever a lógica nova como FUNÇÕES PURAS reutilizáveis no ponto DRY que
cobre todos os callers, e manter as duas cópias byte-idênticas (política vigente), corrigindo o
drift. IMPLEMENTAÇÃO: (a) `extrair_login(texto)` em `integrations/github.py`, chamada por
`_validar_usuario` — logo TODO caller (CLI, serviço, app/MCP) passa a aceitar URL/@handle/nome sem
mudar; (b) `apenas_mudancas` em `atualizar_repos` + helpers puros `_parse_data` (tolera `Z` e
`+00:00`) e `_repo_mudou_desde_pagina` (compara `updated_at` do GitHub com a coluna "Atualizado em"
gravada; na dúvida atualiza), novo contador `paginas_puladas`; (c) flags CLI `--apenas-mudancas` (a
`--sem-arquivados` já existia) e o resumo humano/JSON ganhou `pulados`. Aplicado nos DOIS repos
(cópias idênticas de novo); testes espelhados nas suítes de cada um (o app tinha suíte bem mais
rica). Expor as flags no MCP/REST do workspace-app fica como dívida anotada.
VALIDAÇÃO: `notion-tasks-cli` 96 passed; `notion-workspace-app` 66 passed nos testes de
github/inventário (as 3 falhas restantes são as pré-existentes conhecidas do Windows —
`test_start_app`×2, `test_services_ingestao`×1). Ruff sem erros novos (só o `I001` pré-existente em
`inventario_github.py`, idêntico nos dois repos). `github.py` e `inventario_github.py` confirmados
byte-idênticos entre os repos após a mudança.

[2026-07-07c] CONTEXTO: Fechamento da dívida anotada em [2026-07-07b]: versionar melhor o
`notion-tasks-cli`, expor as flags novas no MCP/REST do `notion-workspace-app` e reduzir duplicação
entre CLI e app. Havia uma tensão de arquitetura: o hub fala em consolidar `integrations/services`
no `notion-starter`, mas o AGENTS local do `notion-starter` proíbe regra de negócio de produto
nessa biblioteca base.
DECISÃO: consolidar agora apenas os ADAPTADORES puros e reutilizáveis (`GitHubClient`/`RepoInfo` e
OpenRouter) no `notion-starter`, mantendo os imports públicos antigos como shims compatíveis em
`notion-tasks-cli/integrations/*` e `notion-workspace-app/server/integrations/*`. Os `services/*`
continuam nos consumidores por enquanto, porque carregam regra de negócio de produto e movê-los
para a lib base violaria a fronteira local; a próxima consolidação deve ser desenhada como pacote
compartilhado ou como camada explicitamente aceita no `notion-starter`, não como despejo automático.
O `notion-tasks-cli` foi bumpado para `0.1.1`; o `notion-starter` também para `0.1.1` por expor
novos módulos públicos. O workspace-app ganhou `POST /api/github/atualizar` e a ferramenta MCP
`notion.update_github_inventory`, ambas com `sem_readme`, `sem_arquivados` e `apenas_mudancas`,
delegando finas para `services.inventario_github.atualizar_repos`.
VALIDAÇÃO: `notion-starter` 171/171; `notion-tasks-cli` 96/96; `notion-workspace-app`
269/272, restando só as três falhas Windows já documentadas no AGENTS (`test_services_ingestao`
encoding cp1252 e `test_start_app`×2 normalização de paths POSIX em Windows). Testes focados das
novas bordas passaram: `tests/test_api_tarefas.py` + `tests/test_mcp_server.py` = 63/63, e
`tests/test_integrations_openrouter.py` = 15/15 após ajustar o shim para preservar monkeypatch do
cache.

[2026-07-07d] CONTEXTO: Fechamento da dívida restante de [2026-07-07c]. Depois de expor as flags
no REST/MCP e consolidar adaptadores, ainda restava a duplicação de `services/*` entre
`notion-tasks-cli` e `notion-workspace-app/server`. O usuário pediu resolver de vez e atualizar a
nota do relatório.
DECISÃO: mover os 10 serviços byte-idênticos para `notion-starter/src/notion_starter/services/`
(`clonagem`, `conteudo`, `exploracao`, `ia`, `ingestao`, `inventario_github`, `normalizacao`,
`projetos`, `sincronizar_github`, `tarefas`) e transformar os arquivos correspondentes nos dois
consumidores em shims de compatibilidade. `services/propriedades.py` permanece no CLI porque não
é duplicado e representa funcionalidade específica da borda CLI. `integrations/notion.py` também
permanece em cada consumidor: é a fábrica de configuração/ambiente, não regra compartilhada. O
`notion-starter` foi bumpado para `0.1.2`; o `notion-tasks-cli` também para `0.1.2` para distinguir
a build com shims. AGENTS/README dos quatro repos foram atualizados para remover a regra antiga
de "aplique bugfix nos dois" e apontar a implementação real para `notion_starter.services`.
VALIDAÇÃO: `notion-starter` 171/171; `notion-tasks-cli` 96/96; `notion-workspace-app` 269/272,
restando somente as três falhas Windows já documentadas (`test_services_ingestao` e
`test_start_app`×2). Falha intermediária por mojibake foi corrigida restaurando os serviços do
Git com leitura/escrita UTF-8 explícita antes dos testes finais.

[2026-07-07e] CONTEXTO: Pedido de transformar a exportação one-off de relatórios diários do
Notion para DOCX em módulo padronizado. A nota da task exigia: sem token hardcoded, sem paths/IDs
fixos, unificar propriedades + corpo sem `props.json`, preferir Python, testes e documentação.
DECISÃO: a regra de negócio ficou em `notion-starter/src/notion_starter/services/relatorios_docx.py`
porque já é a camada compartilhada consolidada; o `notion-tasks-cli` ganhou apenas a borda fina
`exportar-docx`. O serviço consulta o database por período (`Data` por padrão), lê blocos
recursivamente como Markdown, renderiza um DOCX por relatório com capa, sumário manual, tabela de
propriedades, seções de destaque (Resumo/Bloqueios/Próximos passos) e relatório completo. A
dependência escolhida foi `python-docx` por coesão com o ecossistema Python. O CLI aceita
`--database` ou `NOTION_REPORTS_DATABASE_ID` (fallback `NOTION_DATABASE_ID`), `--de`, `--ate`,
`--saida` e `--campo-data`. `notion-starter` e `notion-tasks-cli` foram bumpados para `0.1.3`.
VALIDAÇÃO: testes focados criados para o serviço (`test_services_relatorios_docx.py`) e para a CLI
(`test_cli_notion_tasks.py -k exportar_docx`). Renderização visual DOCX via LibreOffice não foi
possível no ambiente local porque `soffice` não está instalado; a validação estrutural abre o
arquivo com `python-docx` e verifica propriedades/corpo/tabelas.

[2026-07-08] CONTEXTO: Pedido de colocar todos os repositórios do ecossistema no padrão de
qualidade (Felixo System Design). A separação do monorepo deixou os módulos sem os artefatos
obrigatórios que viviam na raiz: CONTRIBUTING, IA.md, CI, `.env.example` (starter) e menu de
entrada (CLI). O workspace-app ainda carregava 13 erros de ruff pós-consolidação e 3 falhas de
teste "conhecidas" no Windows.
DECISÃO: cada módulo ganhou `CONTRIBUTING.md`, `IA.md` próprio (linha do tempo a partir da
separação, apontando para este IA.md como histórico) e CI GitHub Actions (ruff + pytest em
Python 3.10–3.13; o app também valida o front com oxlint + build Vite, recuperando o gate do
monorepo). `notion-starter` ganhou `.env.example`; a exceção "sem start_app.py por ser
biblioteca" foi registrada no IA.md dele. `notion-tasks-cli` ganhou `start_app.py` (menu
interativo: Instalar / Configurar .env / Status / Usar). No `notion-workspace-app`, o ruff foi
zerado (imports pós-shims + E501) e as 3 falhas Windows foram corrigidas de vez — eram bugs de
portabilidade dos TESTES (escrita sem `encoding="utf-8"` e comparação de caminhos POSIX
literais com `Path` do Windows), não do produto; a nota de "falhas pré-existentes" saiu do
AGENTS.md do hub.
VALIDAÇÃO: `notion-starter` 183/183 + ruff limpo; `notion-tasks-cli` 109/109 + ruff limpo +
smoke do menu (Status/Usar); `notion-workspace-app` 272/272 + ruff limpo + `npm run lint` +
`npm run build` verdes — primeira vez com as três suítes 100% verdes no Windows. Commits
pushados nos três módulos (Conventional Commits, direto no main).

[2026-07-13] CONTEXTO: Numa sessão de MODO USO, um agente recebeu um link válido de página
("Relatórios") e a CLI devolveu "Recurso não encontrado" mesmo após trocar o `NOTION_TOKEN`
exportado pelo token correto. O agente diagnosticou errado ("página não compartilhada com a
integração") e só depois descobriu a causa real: havia um **perfil ativo** salvo na CLI
(`notion-tasks perfis`), e o perfil ativo vence silenciosamente a variável de ambiente — os dois
tokens testados nunca chegaram a ser usados. `--perfil relatorios` resolveu na hora.
DECISÃO: documentar a precedência (perfil ativo > `NOTION_TOKEN` do ambiente/`.env`) no
AGENTS.md (seção MODO USO, com troubleshooting do sintoma "mesmo workspace com tokens
diferentes") e no README (bloco de configuração do token), e rotear `perfis`/`--perfil` na tabela
de comandos do AGENTS.md — o hub documentava apenas a variável de ambiente, que não é a fonte de
verdade quando há perfis salvos.
VALIDAÇÃO: reprodução real na sessão (busca idêntica com dois tokens diferentes; acesso imediato
com `--perfil relatorios`). Melhoria de código correspondente (avisar quando `NOTION_TOKEN` é
ignorado e indicar o perfil em uso nos erros) pertence ao `notion-tasks-cli`/`notion-starter`,
registrada aqui como pendência para PR futuro nos módulos.

[2026-07-18] CONTEXTO: conclusão da padronização de qualidade do hub e dos três módulos.
O hub já atendia ao padrão de README, mas o `IA.md` havia crescido a ponto de dificultar
retomadas; os módulos ainda tinham READMEs mínimos e não possuíam um contrato `QUALIDADE.md`.
DECISÃO: compactar sem perda os registros de junho do hub em
`docs/ia-archive/IA-ARCHIVE-2026-06.md`; adicionar resumo vivo; elevar os três READMEs ao
Felixo System Design; criar `QUALIDADE.md` por módulo; registrar como exceção motivada o uso
de versões mínimas em pacotes Python instaláveis, mantendo o lockfile do frontend.
VALIDAÇÃO: todas as linhas não vazias do `IA.md` anterior continuam no arquivo vivo ou no
archive; links locais e comandos do CLI foram conferidos; `check-dev.py` e compilação do hub
passaram; `notion-starter` 235 testes, `notion-tasks-cli` 127, `notion-workspace-app` 256 com
2 skips, Ruff limpo nos três, Oxlint e build Vite verdes, e `npm audit` sem vulnerabilidades.

[2026-08-10] CONTEXTO: a página **Artigos** (`1fc91f95497e81d68ed0fd5befb68b0b`) vai virar a central
de escrita do blog e precisava estar pronta antes da produção começar. Estado encontrado: uma
database com duas colunas apenas (`Nome` e `Data de inicio da escrita`) e duas linhas — um artigo
completo com fontes e uma pauta só com título. Sem etapa, sem tema, sem resumo, sem URL: não dava
para saber o que estava pronto, o que estava parado nem o que já tinha ido ao ar.
DECISÃO: organizar a database no lugar, sem recriá-la, seguindo o `DESIGN-WORKSPACE-NOTION.md`.
Sete colunas tipadas acrescentadas com `garantir-coluna` (idempotente, não apaga nada): `Etapa`
(select — Ideia, Rascunho, Revisão, Publicado, Modelo), `Temas`, `Resumo`, `Data de publicação`,
`URL publicada`, `Tempo de leitura (min)` e `Observações`. As duas linhas existentes foram
padronizadas com `editar-linha`, e toda inferência foi para `Observações` em vez de virar dado
silencioso — a regra do design de que informação ambígua nunca é descartada. O modelo de artigo
virou **uma linha** (Etapa `Modelo`, criada por `importar-planilha`), não uma subpágina: a API do
Notion não cria template nativo de database, e a regra da página é que o trabalho acontece nas
linhas, nunca em blocos soltos abaixo da tabela. O fluxo foi documentado na subpágina "Como
funciona a central de artigos", pendurada num tópico `## Como usar` + divisória, no formato de
tópico do design.
VALIDAÇÃO: tudo executado pela CLI (`garantir-coluna`, `editar-linha`, `importar-planilha`,
`escrever`, `criar-subpagina`, `editar-bloco`, `apagar-bloco`), nenhuma mudança manual. Releitura
das três linhas e da subpágina depois de escrever. A revisão encontrou um defeito de dado que não
estava no pedido: o título do artigo publicável tinha a letra "ê" gravada como caractere de
substituição (U+FFFD), de uma gravação anterior com codificação errada — corrigido, com o motivo
registrado em `Observações`, e uma varredura confirmou que não sobrou nenhum outro na página.
PENDÊNCIA: a database continua sem ícone, descrição e `unique_id` com prefixo, que o design pede.
A CLI só define os três na criação (`criar-database`) e não expõe alteração posterior; o
`unique_id`, além disso, não pode ser acrescentado a uma database existente pela API do Notion —
retrofitá-lo exigiria recriar a database e mover as linhas, ao custo dos links e do histórico das
páginas atuais. Fica como pedido de comando novo na CLI (atualizar metadados de database), não
como esquecimento. `reordenar-bloco --inicio` também não conseguiu pôr um heading acima da
database (`child_database` não é reordenável pela API): os dois blocos criados para isso foram
apagados e a página ficou com a database no topo, que é o conteúdo principal dela de qualquer
forma.

[2026-08-10] CONTEXTO: pergunta de acompanhamento sobre a central de artigos — dá para criar um
template NATIVO de database no Notion (o menu do botão "Novo") em vez de um modelo em linha comum?
DECISÃO: verificar contra a API antes de responder, em vez de repetir a suposição registrada no
dia. Sondagem: `POST /pages` com `is_template: true` responde 400 ("should be not present");
`GET /data_sources/{id}/templates` existe e responde 200 (lista vazia), mas não há `POST`
correspondente ("Invalid request URL"); e o campo `template` do `POST /pages` aceita apenas
`none`, `default` ou `template_id` — serve para APLICAR um template existente, nunca para criar.
Conclusão: criar só à mão pela interface; uma vez criado à mão, o template passa a ser listável e
aplicável pela API, então linhas novas podem nascer dele programaticamente. Isso muda a
recomendação registrada antes, que tratava o template nativo como inviável de ponta a ponta.
O modelo em linha (Etapa `Modelo`) foi então elevado de esqueleto a especificação executável:
tese com teste de validade, resumo em três frases, leitor único, estrutura por seção com regra de
fonte e ressalva metodológica, voz, lista de anti-padrões que reprovam o rascunho, definição de
pronto e uma seção final com as regras que valem quando quem escreve é um modelo de IA
(não inventar número nem link, declarar a lacuna em `Observações`, entregar sem as instruções do
modelo). Renomeado para "🧩 Template para artigos — duplicar para começar".
VALIDAÇÃO: sondagem executada com o token do perfil, sem criar nada no workspace (todas as
tentativas de criação retornaram erro de validação). Corpo do modelo reescrito com
`escrever --substituir`, propriedades por `editar-linha`, subpágina de fluxo atualizada por
`editar-bloco` e `escrever`. Releitura da linha e da subpágina depois de gravar.

[2026-08-13] CONTEXTO: Felipe notou que as entradas na database
[Relatórios](https://app.notion.com/p/Relat-rios-32591f95497e812bb975d9f8c8999dcc?source=copy_link)
registram bem o dia, mas nem sempre a hora — enquanto alguns agentes mais cuidadosos já anotavam
manualmente hora e duração (ex.: "Commit automático do Fetch All das 08:36"). Pedido: tornar isso
o padrão.
DECISÃO: automatizar em vez de depender de cada agente lembrar — `git_historico.py` no
`notion-starter` já extraía a hora de cada commit; ganhou `DiaDeTrabalho.duracao_minutos` e
`.duracao_por_extenso()` (diferença entre primeiro e último commit do dia, formatada como
`"5h30"`/`"35 min"`), e `resumo_markdown()` passou a incluir isso na linha de resumo. Novo
`docs/PADRAO-RELATORIOS.md` registra a regra (hora sempre; duração quando houver mais de um
commit; registro manual `HH:MM–HH:MM` quando não há commits associados) e é referenciado a partir
do `AGENTS.md`, na linha de roteamento de `relatorios_diarios.py`.
VALIDAÇÃO: testes novos em `test_git_historico.py` (5), 295 testes do `notion-starter` verdes,
`ruff` limpo. Correção de processo: a mudança nasceu em branch por engano — pequena e coesa,
não se encaixava em nenhuma das três exceções de `docs/GIT-POLITICA-DE-VERSIONAMENTO.md` (feature
grande, refatoração significativa ou alto risco) — corrigida com fast-forward para o `main` e a
branch apagada (local e remota) nos dois repositórios (`notion-starter` e este hub).

---

## [2026-08-17] Lacunas de uso viradas em ferramenta — sessão de trabalho real

**Contexto.** Uma sessão longa operando o Notion pela CLI (17 tarefas criadas
com corpo rico, 16 reescritas e 48 ligações simétricas montadas entre elas)
serviu de teste de uso real do ecossistema. Toda fricção encontrada virou
mudança nos módulos, não anotação. Detalhes técnicos nos `IA.md` de
`notion-starter` e `notion-tasks-cli`, mesma data.

**O que faltava e passou a existir:**

1. **Ler o schema.** Não havia comando para descobrir as colunas de um database
   — foi preciso chamar `/v1/databases/<id>` cru para saber os valores de
   `Prioridade` e a configuração das relações. Virou `notion-tasks schema`.

2. **Ligar duas linhas.** Foi preciso escrever à mão um script que gravasse as
   duas pontas de cada ligação. Virou `notion-tasks relacionar`, que **confere**
   a outra ponta em vez de deduzir do tipo declarado — porque o tipo não prevê o
   comportamento (experimento registrado no `IA.md` do `notion-starter`).

3. **Reescrever sem destruir.** `escrever --substituir` apagava imagem e
   `child_database` em silêncio; foi preciso escrever uma limpeza sob medida
   para preservar a imagem de uma tarefa. Virou o padrão da biblioteca.

4. **A regra do link virou guarda.** Escrever numa página que contém database
   agora **falha** com a lista das databases e o caminho pronto para as linhas.
   Era regra escrita no `AGENTS.md` que modelos mais fracos ignoravam — regra em
   documento não segura modelo fraco, ferramenta que recusa segura.

5. **Criar linha completa numa chamada.** `criar --set --conteudo` fecha o ciclo
   que eram três comandos. E o erro pós-criação passa a trazer o ID da linha, em
   vez de deixar órfã.

**Decisão de fundo registrada:** quando uma regra de operação do Notion for
importante o bastante para estar no `AGENTS.md`, avaliar se ela pode virar
**comportamento da ferramenta**. Documentação orienta quem lê; guarda protege
quem não leu. As duas coisas juntas é o padrão daqui em diante.

---

## [2026-08-17] Publicação em lote no Notion: o que só aparece depois de publicar

**Contexto.** Publicação de **201 relatórios diários** reconstruídos do git (115
criados, 86 complementados) na database `62971953…`. Três lições que só
apareceram porque o resultado foi **lido** depois de escrito.

### 1. Ler o resultado publicado é parte da entrega

A ferramenta tinha 20 testes verdes e um `--dry-run` conferido — e mesmo assim
publicou o mesmo repositório **duas vezes por dia**, uma com o nome de produto
(`--repo`) e outra com o nome da pasta (`--descobrir`). Os testes cobriam a
agregação; o defeito estava na **montagem da lista de entrada**, que nenhum
teste tocava. O bug foi encontrado abrindo um relatório publicado, não pela
suíte. Corrigido deduplicando por caminho resolvido, com teste de regressão.

**Regra que fica:** escrita em lote sobre dados que já existem termina com uma
leitura de amostra do que foi gravado, não com o "ok" do comando.

### 2. `select` do Notion aceita valor inválido — e cria a opção

A publicação passou `--area "Projetos"`, que não existe naquele database (as
opções são Trabalho, Pessoal, Estudos, Saúde, Outro). A API **não recusou**:
criou a opção nova e poluiu o schema. Corrigido nas 115 páginas e a opção foi
removida.

Isso reforça a regra do `schema`: rodar `notion-tasks schema <id>` **antes** de
escrever responde exatamente essa pergunta — e teria evitado o estrago.

### 3. Retry sem espera não é retry

O script de limpeza tinha `for tentativa in range(5)` com `continue` puro no
429. As cinco tentativas queimavam no mesmo instante e o rate limit virava
falha fatal no meio do lote. Corrigido com espera exponencial respeitando
`Retry-After`, e paralelismo reduzido de 6 para 3 trabalhadores.

### Padrão de escrita em lote adotado daqui em diante

1. `--dry-run` primeiro, sempre.
2. Script **idempotente e retomável** — ele vai ser interrompido.
3. Backoff de verdade em cima de 429/409/5xx.
4. Amostrar o resultado publicado antes de considerar concluído.

---

## [2026-08-23] Precedência perfil × ambiente: fica como está, e o porquê

**Contexto.** A tarefa *"Qualidade — deixar a suíte e o lint verdes numa máquina
com perfil configurado"* nasceu de uma medição feita hoje mais cedo: um teste do
`notion-tasks-cli` vermelho (`test_database_atual_traz_titulo_real`) e 8 erros de
`ruff`. O teste falhava porque `aplicar_perfil` sobrescreve `NOTION_DATABASE_ID`
no ambiente do processo, e o teste tentava isolar só o ambiente.

### Medição de hoje, no clone local

| Verificação | Resultado |
| --- | --- |
| `notion-tasks-cli` **com o store de perfis real na raiz do módulo** | **168 passaram** |
| `notion-starter` | **354 passaram** |
| `ruff check .` (antes) | 8 erros, todos em `check-dev.py` |

O teste **não falha mais**: `tests/conftest.py` ganhou, em `03f2980`
(17/08/2026), a fixture `perfis_isolados`, que aponta `workspaces.ARQUIVO_PADRAO`
para um `tmp_path` e limpa `NOTION_TOKEN`/`NOTION_DATABASE_ID`/`NOTION_PROFILE`.
Ou seja, o item "isolar o perfil no teste" já estava resolvido antes da tarefa
ser escrita — a medição que a originou pegou outro estado da máquina (a cópia
instalada em `site-packages`, cujo store fica ao lado do pacote).

Verificado copiando o store **real** para a raiz do módulo e rodando a suíte:
168/168. O isolamento segura o caso que a tarefa temia.

### A decisão

**A precedência fica como está:** `--perfil` > perfil ativo salvo > ambiente
(`NOTION_TOKEN`/`NOTION_DATABASE_ID`, inclusive vindos do `.env`).

O comportamento usual de CLI seria o inverso (ambiente vence arquivo de
configuração), e foi por isso que a alternativa foi levada ao dono do projeto com
o efeito colateral **medido**: o `.env` deste repositório define
`NOTION_DATABASE_ID=30296e2d…` (o To Do da HOME), e `core/config.py` só exporta a
chave quando ela ainda não está no ambiente. Inverter a ordem faria **todo comando
rodado de dentro do repositório** mirar a HOME em vez do perfil ativo — troca de
alvo silenciosa, exatamente o tipo de surpresa que a mudança pretendia evitar.

Decisão do dono, em 23/08/2026: **manter**. O custo aceito é conhecido e já está
documentado no `AGENTS.md` ("vence mesmo que `NOTION_TOKEN` esteja exportado,
silenciosamente") e na regra 8 da skill de operação do Notion — quando um ID
válido devolve "Recurso não encontrado", o primeiro passo é `perfis listar`.

### Lint

Os 8 erros eram todos de `check-dev.py`, que veio no pull: `import subprocess`
sem uso, cinco f-strings sem placeholder e os imports-sonda `pytest`/`requests`.
Os dois últimos viraram `importlib.util.find_spec` — a pergunta ali é
*disponibilidade*, e importar de verdade só para descobrir isso executa o módulo
inteiro; de quebra, agora o script diz **qual** pacote falta em vez de parar no
primeiro. `ruff check .`: **All checks passed**.

### Achado fora do escopo, registrado

`notion-workspace-app` tem **3 testes vermelhos** (`test_services_conteudo.py`
×2 e `test_mcp_server.py::test_append_content_conta_blocos`): esperam um `PATCH`
e o código faz um `GET` de leitura antes de escrever. **Não** é divergência entre
cópias do `notion_starter` — o `client.py` instalado e o do módulo são iguais no
trecho envolvido. São testes desatualizados em relação ao comportamento de
"ler antes de escrever". Fora do critério desta tarefa (que cobre `notion-starter`
e `notion-tasks-cli`); virou tarefa própria.

---

## [2026-08-24] As três cópias do `notion-starter`: a ordem de instalação era o bug

**Correção de rota da entrada [2026-08-21] acima.** Aquela entrada registrou que o
setup passou a instalar `notion-starter` **antes** de `notion-tasks-cli` "para evitar
que o executável use uma cópia antiga em `site-packages`". Medido agora, a ordem faz
exatamente o contrário do que a entrada prometia.

### O que foi medido (24/08/2026, venv limpo, Python 3.12)

O `pyproject.toml` do `notion-tasks-cli` declara
`notion-starter @ git+https://github.com/Felipe-Alcantara/notion-starter.git`.
Consequência: **instalar a CLI baixa o starter do GitHub e desinstala o editável**.

| Ordem | Resultado de `notion_starter.__file__` |
| --- | --- |
| starter, depois CLI (a documentada) | `site-packages/notion_starter/__init__.py` — a cópia do GitHub |
| CLI, depois starter | `modules/notion-starter/src/notion_starter/__init__.py` — o código local |

A saída do pip é explícita no passo errado: `Attempting uninstall: notion-starter` →
`Successfully uninstalled` → instala a baixada. Nada falha, nada avisa.

Instalar os dois de uma vez (`pip install -e A -e B`) **não é alternativa**: falha com
`ResolutionImpossible`, e não por defasagem de versão — as duas cópias já estavam em
0.2.0, no mesmo commit `55c866d`. O conflito é o *pin por URL direta* em si.

### Decisão

Fonte de verdade continua sendo **o GitHub publicado** — é o que faz
`pip install git+…/notion-tasks-cli` funcionar em qualquer máquina, e é o que o
`bootstrap.py` clona. Descartada a dependência por caminho relativo: tornaria o
repo autossuficiente ao preço de quebrar a instalação de quem não tem o hub clonado.
O que muda é o **ambiente de desenvolvimento**, que passa a sobrepor o starter pela
cópia editável de `modules/`.

### O que mudou

- `start_app.py`: `_instalar_cli_dos_modulos` instala `(CLI_DIR, STARTER_DIR)` — starter
  por último, com o porquê na docstring.
- `check-dev.py`: `origem_do_starter` responde de onde o `notion_starter` vem e, quando
  não vem de `modules/`, diz como consertar. Este é o guarda: o modo de falha era
  silencioso, agora tem quem grite.
- `tests/test_check_dev.py`: três casos de comportamento do guarda (editável, cópia
  errada, não instalado). Primeira suíte do hub.
- `README.md` e `AGENTS.md`: ordem corrigida e o motivo explicado onde ele é lido.

### Efeito colateral que quase passou por perdido

Trocar o modo de instalação **parece apagar os perfis salvos**: `perfis listar` passou a
dizer "Nenhum perfil configurado". Não apaga — `core/workspaces.py` define
`ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / ".notion-workspaces.json"`, ou
seja, o arquivo mora **ao lado do pacote instalado**, e mudar a instalação muda o
endereço. Bastou copiar o arquivo da pasta antiga para `modules/notion-tasks-cli/`
(o `.gitignore` do módulo já o cobre; nada disso vai para commit). Que o estado do
usuário siga o local de instalação é frágil por si só — virou tarefa própria.

### Estado final da máquina

`notion_starter` e `cli` importando de `modules/`, ambos 0.2.0, `pip check` sem
nenhuma quebra envolvendo notion, `check-dev.py` em `[OK]`, e uma marca inserida em
`modules/notion-starter` apareceu no import sem reinstalar nada (marca revertida).

---

## [2026-08-24] Perfis migrados para a pasta de configuração do usuário

Complemento da entrada anterior. O efeito colateral ali registrado — trocar o modo de
instalação parecer apagar os perfis — foi corrigido na origem: o `notion-tasks-cli`
0.2.1 (`e6206c1`) passou a guardar o store em `~/.config/notion-tasks/`
(`%APPDATA%\notion-tasks\` no Windows), com migração automática do endereço antigo.

O aviso que este README trazia, mandando copiar o arquivo à mão, deixou de valer e foi
substituído. Medido na máquina: instalação trocada de editável para não editável e de
volta, `perfis listar` idêntico nos dois modos, e uma única cópia do store restante no
disco — fora de qualquer repositório git.

---

## [2026-08-27] A ordem de instalação validada em Windows — Linux não bastava

**Continuação de [2026-08-24] acima.** Aquela entrada corrigiu a ordem de instalação
(CLI antes do `notion-starter`) e mediu só em Linux, Python 3.12, com a ressalva
explícita: "isso não se supõe, se mede". Ficou tarefa própria até cobrir Windows e
macOS. Esta entrada fecha o Windows; macOS continua sem máquina disponível para medir.

### O que foi medido (Windows, Python 3.14 — não o mesmo Python da medição original)

Ambiente isolado: hub clonado do zero num diretório novo, ao lado dos três módulos já
clonados nesta máquina (`E:\Programação\Github\{notion-starter,notion-tasks-cli,
notion-workspace-app}`), para exercitar de propósito o caminho de risco que o próprio
ponto de atenção da task citava — o `bootstrap.py` criando **junction**, não clonando
separado.

| Verificação | Resultado |
| --- | --- |
| `bootstrap.py` cria junction (não clone separado) | ✔ — `icacls`/`Get-Item` confirmam `LinkType=Junction`, sem privilégio de administrador |
| `check-dev.py` depois do setup pela ordem nova | `[OK] notion_starter vem de modules/notion-starter (editável)` |
| Marca inserida em `modules/notion-starter/src/notion_starter/__init__.py` aparece no import sem reinstalar | ✔ — testado no arquivo real do clone-irmão (via junction), revertido com `git checkout --` em seguida |
| `.notion-workspaces.json` — `pasta_configuracao()` | `%APPDATA%\notion-tasks`, o valor real do ambiente, não o fallback |

A instalação foi disparada chamando `_instalar_cli_dos_modulos()` diretamente (a mesma
função que o menu do `start_app.py` chama) num venv limpo — o menu em si usa `rich` e
não tem modo não interativo para automação; a função é o que estava sob teste, não a
navegação do menu.

### O que ficou fora

**macOS não foi medido** — sem máquina disponível nesta sessão. Continua exatamente a
mesma lacuna que a entrada de 24/08 já declarava, agora restrita a um sistema em vez de
dois.

### Um achado que não estava no escopo original, mas é do mesmo trabalho

A parte da task sobre o endereço dos perfis (item acrescentado em 24/08) pedia
confirmar se a ACL herdada no Windows é aceitável para guardar token. **Não é, nesta
máquina**: `%APPDATA%\Roaming` concede Leitura e Execução ao grupo
`CodexSandboxUsers` (sandbox do Codex CLI já presente aqui), e isso propaga para
qualquer arquivo criado em `%APPDATA%\notion-tasks\` — incluindo o store de token.
`os.chmod`, que o código já sabia ser no-op no Windows, não protege disso. Detalhe
completo e commit no `IA.md` do `notion-tasks-cli` (`51bf659`); virou task própria lá,
não consertada aqui em cima da hora.

### Critério de aceite — como ficou (até 27/08)

- `check-dev.py` responde `[OK]` no Windows depois do setup pelo menu. **Feito.**
  Linux já estava medido (24/08). macOS **não medido** — sem máquina.
- A marca aparece sem reinstalação nos três sistemas. **Feito em Linux e Windows.**
  macOS **não medido**.
- Se algum sistema divergir, o motivo fica registrado — não divergiu em nenhum dos
  dois sistemas medidos até aqui.

## [2026-08-27] macOS validado — os três sistemas fecham sem divergência

**Continuação da entrada acima, mesmo dia.** Máquina Apple ficou disponível na
sessão seguinte; fecha a lacuna que a validação de Windows deixou.

### O que foi medido (macOS, Python 3.14.7, Darwin 24.5.0)

Ambiente isolado em `/tmp/notion-macos-validation/`: os três módulos
(`notion-starter`, `notion-tasks-cli`, `notion-workspace-app`) clonados do zero
como irmãos do hub, também clonado do zero ali — para exercitar de propósito o
caminho de risco citado no ponto de atenção da task: `bootstrap.py` criando
**symlink** de verdade (não junction — isso é coisa de Windows), reusando o
clone-irmão em vez de duplicar.

| Verificação | Resultado |
| --- | --- |
| `bootstrap.py` cria symlink (não clone separado), sem privilégio elevado | ✔ — `ls -la modules/` mostra `lrwxr-xr-x` apontando para `/private/tmp/notion-macos-validation/<módulo>`; nenhum `sudo` envolvido |
| `check-dev.py` depois do setup pela ordem nova | `[OK] notion_starter vem de modules/notion-starter (editável)` |
| Marca inserida em `modules/notion-starter/src/notion_starter/__init__.py` aparece no import sem reinstalar | ✔ — `import notion_starter` enxergou o atributo novo direto do clone-irmão via symlink; revertido com `git checkout --` em seguida, `git status` limpo |
| `pasta_configuracao()` sem `XDG_CONFIG_HOME` definido | `~/.config/notion-tasks` — o fallback documentado, medido com `env -i` para garantir que a variável não estava setada por acidente no shell |

A instalação foi disparada chamando `_instalar_cli_dos_modulos()` diretamente (mesma
função do menu do `start_app.py`), mesmo motivo já registrado na entrada de Windows:
o menu usa `rich` e não tem modo não interativo para automação.

### Nada divergiu

Symlink em vez de junction é a única diferença estrutural entre macOS e Windows, e já
era esperada (é o próprio código que faz essa distinção por `os.name`). Fora isso, os
três sistemas — Linux (24/08), Windows e macOS (27/08) — concordam: ordem de instalação
(CLI antes do `notion-starter`) resolve o problema original, `check-dev.py` confirma
editável, marca aparece sem reinstalar, pasta de configuração cai no padrão XDG.

### Critério de aceite — fechado nos três sistemas

- `check-dev.py` responde `[OK]` depois do setup pelo menu (ou pela função direta) em
  Linux, Windows e macOS. **Feito nos três.**
- A marca aparece sem reinstalação nos três sistemas. **Feito nos três.**
- `pasta_configuracao()` medida (não suposta) nos três sistemas. **Feito nos três** —
  Linux e macOS caem no fallback XDG, Windows usa `%APPDATA%`.
- Se algum sistema divergir, o motivo fica registrado — **nenhum divergiu** além da
  diferença esperada symlink/junction.

### Evidência de origem

Task: `3c991f95-497e-81af-bec1-e86f4febbec6` (subtarefa de
`3c691f95-497e-81e0-ab46-fd05af43fd36`). Validação de Windows: entrada acima, mesmo
`IA.md`, 27/08/2026.

## [2026-09-04] Distribuição única publicada e documentação alinhada

### Decisão técnica

O caminho de uso sem clone ficou publicado como a distribuição `notion-automacoes`
(versão `0.3.0`), com `notion-tasks` preservado como alias. O núcleo
`notion-starter` é publicado como dependência versionada; o extra `app` instala o
`notion-workspace-app`, que leva o bundle da SPA React dentro do wheel. O primeiro
release é Python puro para Python 3.10+, usando `pipx`/`uv`; binários nativos foram
deliberadamente deixados fora até existir decisão separada de manutenção,
assinatura, update e rollback.

### O que foi implementado

- `notion-starter`, `notion-automacoes` e `notion-workspace-app` receberam
  metadados de build e versão coerente `0.3.0`;
- `cli/unificada.py` reúne `tasks`, `auth`, `doctor`, `app start`, `mcp start` e
  `update`, sem duplicar regra de negócio;
- a dependência Git direta foi removida do CLI e do app;
- o app passou a incluir `start_app.py`, entry points públicos e a SPA compilada;
  no wheel, o launcher serve o bundle via Django e não consulta Node/npm;
- workflows `release.yml` constroem, validam com `twine check`, exercitam smoke em
  Ubuntu/Windows/macOS e publicam apenas por Trusted Publishing após os gates;
- foi corrigido o conflito de importação entre os pacotes legados `core` da CLI e
  do app, e os testes do app passaram a representar a leitura de schema feita por
  `TaskList.criar`.

### Evidência e limites

Localmente: starter **355 testes**, CLI **198 testes**, app **256 testes + 2 skips**;
`ruff` limpo nos três; `npm run lint`, `npm run build` e `twine check` aprovados.
Os workflows de release passaram nos três sistemas suportados e publicaram os
wheels/sdists por Trusted Publishing. Um ambiente limpo instalou os wheels,
respondeu a `--version`, `--help`, `doctor`, `auth listar` e confirmou a rota
Django `/` servindo o bundle.

Na mesma rodada, a documentação do hub e dos módulos foi atualizada para separar
uso público e desenvolvimento, corrigir links do antigo monorepo e manter
`README`, `QUALIDADE`, `CONTRIBUTING`, `AGENTS` e `IA` coerentes. O `LICENSE` do
hub agora também identifica `Felipe Alcantara`; a menção histórica a André
Gustavo não representa titularidade.

## [2026-09-04] Gate final da documentação e da distribuição

O gate oficial do app foi reexecutado após alinhar o fixture REST ao schema do
`notion-starter==0.3.0`: **279 testes passaram** em Python 3.10, 3.11, 3.12 e
3.13, e o frontend passou por lint/build. As CIs finais do starter e da CLI
também passaram; os links das execuções estão em `docs/DISTRIBUICAO.md`.

## [2026-09-08] Contrato de atualização dos binários nativos

A task de distribuição definiu o mecanismo compatível com PyInstaller sem
alterar o contrato publicado Python `0.3.0`: a entrada nativa consulta a Release
estável do GitHub, escolhe um asset por sistema/arquitetura, valida SHA-256 e
faz troca atômica. A versão anterior fica em `<executável>.previous`; no
Windows, um helper espera o processo pai terminar antes de substituir o arquivo
bloqueado. O rollback de produto continua manual pela Release anterior, que
deve manter pelo menos os dois releases estáveis mais recentes.

O mecanismo foi implementado no módulo `notion-tasks-cli`, em
`cli/atualizacao_nativa.py`, integrado em `cli/unificada.py` e documentado em
`docs/DISTRIBUICAO.md`. A suíte offline valida os quatro alvos e os caminhos de
checksum/troca/helper. A aceitação física — executáveis PyInstaller assinados,
notarização, execução nos quatro sistemas e rollback com asset real — permanece
dependente das tasks irmãs de empacotamento e assinatura; nenhum binário nativo
foi publicado nesta etapa.

## [2026-09-26] Manipulação de blocos sem perda de dados (starter 0.4.0, CLI 0.5.0, app 0.3.1) e limpeza de backups pessoais

Uma auditoria da manipulação de blocos, com 3 verificadores por achado, confirmou falhas de **perda de dados**.
Entre elas: `reordenar-bloco` apagava antes de copiar, perdia filhos e mandava `--inicio` para o fim;
`escrever --substituir` apagava antes de validar; `relacionar` perdia relações acima de 25; `editar-bloco`
perdia menções e formatação; `importar-planilha` usava a posição da linha como chave. As correções saíram no
notion-starter 0.4.0 e na CLI notion-automacoes 0.5.0 (PyPI e binários nativos). A CLI ganhou
`escrever --apos/--inicio`, `blocos --metadados/--completo/--recursivo/--contendo`, `ler-bloco`,
`editar-bloco --trocar/--por` e `--arquivo`, `restaurar-bloco`, IDs sem hífen e links, e envelope de erro com
`codigo`. O notion-workspace-app 0.3.1 só amplia a faixa do starter (`<0.5.0`), para o extra `[app]` resolver
a CLI nova. O `AGENTS.md` e o `README.md` foram atualizados com os comandos novos.

**Backups pessoais no repositório público:** o backup do `reordenar-bloco` caía no diretório atual, e 2 JSON
com texto do workspace entraram aqui no commit automático de 28/07/2026. A CLI 0.5.0 grava os backups em
`~/.local/state/notion-automacoes/backups`. A pedido do mantenedor, os 2 arquivos foram removidos também do
histórico da `main` (`git filter-repo`, com force-push). Um backup espelho completo do repositório anterior
foi guardado antes. Os PRs #2 e #3 ainda referenciam o commit antigo; as refs de PR são somente leitura, e
a remoção delas (e do cache de commits por SHA) depende do Suporte do GitHub. Clones antigos precisam de
`git fetch && git reset --hard origin/main`.

## [2026-09-27] Ferramentas para organizar o workspace viram features (starter + CLI)

**Pedido do mantenedor.** Todo script, feature ou decisão nova usada para editar
os workspaces precisa virar feature dos repositórios, não código de tarefa. A
organização de artigos de 2026-09-27 tinha sido feita com um pacote de tarefa
(fora dos repositórios); o que ele fazia foi portado com testes, sem rede.

**Fatos medidos no workspace real em 2026-09-27 (base dos testes e da doc).**

- `PATCH /pages/{id}` com `parent` responde 200 e o Notion **ignora** o campo.
  O que move é `POST /pages/{id}/move` (versão `2025-09-03`); a releitura
  mostra `{"type": "database_id", ...}` quando o destino é data source.
- Mover uma linha para outro database **cria no destino** as colunas da origem
  que faltam lá e **descarta** valores com opção inexistente e relações.
- `GET /data_sources/{id}/templates` lista os modelos (`"New page"` quando sem
  título); a API não cria modelo nem define o padrão, mas escrever num modelo
  existente funciona.
- Copiar blocos: a leitura traz `null` que a escrita recusa, e o lote de 100 é
  atômico.
- `/search` sem termo: 3.841 itens em 62 s; corpos de ~1.800 páginas: ~30 min.

**O que entrou.**

- notion-starter: `mover_pagina` verificado (`3130d5e`); `copia_corpo`
  (`445f3cc`); `listar_modelos`, `valor_de_texto` e `modelos` (`9cfe49e`);
  `inventario_workspace`, `corpos` e `busca_conteudo` (`576d323`); leitores de
  `created_time`/`created_by`/`unique_id` e `remover_coluna` (`42da753`).
- notion-tasks-cli: `mover-pagina` com previsão e `--aceitar-perdas`
  (`3b3d875`); `copiar-corpo` (`db6b8c7`); `modelos listar|preencher`
  (`38fe516`); `criar --database` (`0511757`); `inventario`, `baixar-corpos` e
  `buscar-conteudo` (`cd9df88`); `remover-coluna` (`2deae46`).

**Decisão de contrato.** As APIs novas entraram no `main` do starter **sem**
mudar a versão (`0.4.1`), por instrução do mantenedor (nada de release, tag ou
versão nesta entrega). Como a CI da CLI resolve o starter do PyPI, a CLI
importa esses serviços **dentro do comando** (`_servico_do_starter`): com o
starter publicado, só os comandos novos recusam (`configuracao`) e os testes
deles pulam. Para publicar: release do starter com as APIs novas, faixa da CLI
subindo junto, e então a importação pode voltar ao topo.

**Validação.** starter 677 testes, CLI 363 (342 + 23 pulados com o starter do
PyPI, como na CI), app 279 com o starter novo; `ruff` limpo nos três; CI verde
em cada push. Nada foi escrito no Notion real.

**Incidente registrado.** O disco E: encheu durante o trabalho (28 KB livres) e
um `git pull` dos módulos parou no meio, deixando arquivos com 0 byte
(inclusive `cli/notion_tasks.py`, o que derrubou a CLI editável por alguns
minutos). O reparo foi concluir o fast-forward depois de apagar só caches
regeneráveis; o desenvolvimento seguiu em clones no C:, e os checkouts de E:
ficaram para ser sincronizados quando houver espaço. Outro achado: o
`notion-tasks` do PATH importava a CLI de um scratchpad de outra sessão
(0.4.1), não do checkout — por isso o `editar-bloco` parecia não conferir o
tipo do bloco, coisa que o `main` 0.5.0 já faz.

## [2026-09-28] Sessão "Organizar artigos": ideias de conteúdo num database só e tasks de artigos fechadas

Registro da sessão de uso (27/09 22:26 → 28/09 ~01:10) feita com a CLI e os
serviços deste ecossistema. O registro técnico das features que nasceram dela
está na entrada anterior; aqui ficam o estado, as decisões e os becos sem saída.

**Estado:** concluído. O database "Artigos" (`1fc91f95-497e-80d3-8dbd-ebbdcca5fec7`)
virou **Ideias criativas**, mudou de Estudo para a HOME e reúne 17 ideias (8 artigos,
9 vídeos), cada uma com **Criado em** igual à data da primeira anotação, e 16 modelos
nativos. Das tasks de artigo, 5 foram fechadas e 4 continuam abertas. Relatório com
linha do tempo e 11 figuras: subpágina do "Relatório — 27/09/2026".

**Decidido:**

- Renomear para Ideias criativas e colocar vídeos e outros formatos no mesmo database,
  com a coluna **Formato** — pedido do Felipe, para achar tudo num lugar. Ficou aberta
  a decisão sobre o pipeline de produção de vídeo descrito na página *youtube*.
- **Criado em** é coluna de data editável, com a data da fonte original (tarefa, página,
  vídeo, repositório). A coluna automática `created_time` marcaria 27/09 nas linhas
  criadas na organização e perderia a cronologia, que era o objetivo.
- Mover os 9 vídeos com `POST /pages/{id}/move`, e não copiar e arquivar: preserva ID,
  links e corpo. A coluna `Tema/Pilar`, criada no destino como efeito do movimento, foi
  removida depois de conferir que os 9 valores estavam preservados em Temas e Observações.
- Não mexer no GitHub (`felixo-blog` é público) — decisão do Felipe.
- Fechar task só quando o trabalho principal é escrita. Foram 7 lentes de busca sobre
  503 tarefas abertas, 3 verificadores independentes por candidata e decisão por maioria.
  Antes de fechar, as seções que faltavam ("O que fazer", "Critérios de aceite") foram
  copiadas para a linha da pauta. Tasks de ferramenta, infraestrutura ou decisão abertas
  na mesma noite continuam abertas.

**Descoberto (além da entrada anterior):**

- `PATCH /data_sources/{id}` com `default_template_id` responde 200 e **ignora** o
  pedido. O modelo padrão só se define pela interface.
- Nenhuma ideia estava escondida nos corpos. As 306 páginas com sinais de artigo, lidas
  por inteiro, deram 0 ideias novas e 1 texto começado: um relato de 02/07/2026 em
  Arquivos / Lixeira, levado para a pauta do júnior.
- "Vault" (1.020 páginas) e "Blog" (12) são exemplos de um template duplicado três vezes
  (23/05/2025, 25/05/2025, 16/03/2026), não escrita do Felipe.
- O conector Notion do claude.ai desta máquina aponta para **outro workspace** (404 no
  database de artigos). Para o workspace do Felipe, só a CLI serve.
- Linhas de teste criadas pela interface (uma em branco, uma a partir do modelo) entram
  nas consultas. Por isso "ideia" passou a ser "linha com Criado em" nos scripts da tarefa.

**Becos sem saída (não repita):**

- Filtrar tarefas por "Áreas da vida = Artigos": não existe essa área. O ID que parecia
  ser dela é da área Projetos.
- `editar-bloco` pela CLI do PATH em lista ou citação: falha enquanto a CLI instalada for
  o clone 0.4.1 de outra sessão. Reinstale a partir do checkout, ou edite pelo cliente
  preservando o tipo.
- Definir o modelo padrão pela API: o pedido é aceito e ignorado.
- Idempotência de acréscimo por "marca única por linha": deixava passar texto repetido
  quando um segundo acréscimo diferente ia para a mesma coluna. Compare o próprio trecho.

**Em aberto:**

- Falta fazer (tarefas abertas no To Do List da HOME): liberar espaço no E: (1,9 MB
  livres), sincronizar os checkouts (`git pull --ff-only` nos três repositórios) e
  reinstalar a CLI editável (CLI primeiro, starter por último).
- Falta decidir (Felipe): release do notion-starter com os serviços novos; onde vive o
  pipeline de produção de vídeo.
- Três cliques na interface: modelo padrão, ordenação da view por Criado em e as duas
  linhas de teste.
- Não verificado: páginas renderizadas no Notion (só relidas pela API); o Felixo Editor
  com o database misturando formatos.

**Próximo passo:** liberar espaço no E: e rodar
`git -C "E:/Programação/Github/<repo>" pull --ff-only` nos três repositórios, depois
`python -m pip install -e "E:\Programação\Github\notion-tasks-cli"` e
`python -m pip install -e "E:\Programação\Github\notion-starter"`.

## [2026-10-02] Validação Linux do auto-update nativo e relançamento pós-troca em macOS/Linux

A validação física no Linux x64 (asset `v0.4.1` publicado, cópia isolada) confirmou update real para a
`v0.5.0`, checksum, permissão e rollback pelas duas vias (`.previous` e Release anterior), mas revelou que o
**auto-update disparado por comando comum** quebrava o próprio comando com `Error -3 while decompressing
data`: o onefile do PyInstaller lê módulos do próprio arquivo sob demanda, e a troca acontecia com o processo
antigo vivo. A correção ficou no `notion-tasks-cli` (`cli/atualizacao_nativa.py` `relancar_atualizado`,
`cli/unificada.py`): depois da troca, o comando continua no executável novo, com os mesmos argumentos e
`PYINSTALLER_RESET_ENVIRONMENT=1`. O contrato em `docs/DISTRIBUICAO.md` foi atualizado com o comportamento e
com o estado da aceitação física (Windows e Linux validados; macOS, assinatura e VM limpa pendentes). A
correção só vale para binários publicados a partir da próxima Release; a `v0.5.0` ainda falha uma vez ao se
atualizar.

## [2026-10-07] Empacotamento nativo aponta para o pacote único (build Linux validado)

O build PyInstaller (`scripts/empacotamento/build_native.py`) passou a apontar para `felixo_notion_mcp`:
metadata de `felixo-notion-mcp`, `--collect-submodules felixo_notion_mcp` e o arquivo de versão
`felixo-notion-mcp-version.txt` em `felixo_notion_mcp/api/cli/` dentro do bundle (onde `versao.py` o lê). O nome
do arquivo tem uma fonte só, em `versao.py`. A raiz do repositório que o build usa como diretório de trabalho
subiu de `parents[1]` para `parents[2]`, porque o script saiu de `scripts/` para `scripts/empacotamento/`. Nomes
de asset (`notion-automacoes-<alvo>`) e `REPOSITORIO_GITHUB` não mudaram.

Medido num build real em Linux x64 (Python 3.13, PyInstaller 6): `--version` responde `0.6.0` (vem do arquivo
embutido, não da metadata, que diz `0.6.0.dev0`), `auth listar` e `--json doctor` rodam sem traceback, e o
`doctor` descreve o pacote como `binário nativo`, nunca como checkout. Sem `--collect-submodules`, o serviço
carregado por `importlib.import_module` (`buscar-conteudo`) some do binário (27 MB contra 48 MB) e o `doctor`
continua verde; por isso o smoke agora também roda `buscar-conteudo` e confere a origem do pacote.

**Limite:** só o Linux x64 foi construído e testado nesta etapa. Windows e macOS (x64 e arm64) ficam com a CI de
release da etapa 4, que é quem vai rodar este mesmo build e este mesmo smoke nos três sistemas.

## [2026-10-07] Etapa 1 do monolito: hub e três módulos viram um pacote só

**Decisão.** O ecossistema já foi um monorepo até 02/07/2026 e foi separado de propósito (`docs/MODULARIZACAO.md`).
A separação custou três pacotes com faixas de versão casadas, `bootstrap.py`, `check-dev.py` e o bug das "três
cópias do starter" (entrada de 24/08/2026). A spec
`docs/superpowers/specs/2026-10-07-monolito-felixo-notion-mcp-design.md` (seção 8) divide a volta em quatro
etapas; esta é a **etapa 1**: só reorganizar, sem mudar comportamento. As etapas 2 a 4 (registro único de
operações e paridade do MCP; modo hospedado; migração do AI Core e do Editor mais a distribuição) ficam para
outras branches, cada uma com plano e gate próprios.

**O que foi feito** (branch `refactor/monolito`, base `23d9ebb`, tarefas 1 a 10 do plano da etapa):

- Os três módulos entraram com o **histórico preservado** (`git filter-repo --to-subdirectory-filter` e merge
  com `--allow-unrelated-histories`), e `git log --follow` e `git blame` continuam funcionando.
- O código foi movido por **script** para as camadas `domain`, `services`, `repositories`, `integrations`,
  `api/{cli,mcp,http}` e `core`, em `src/felixo_notion_mcp/`. A tabela de movimentos
  (`scripts/migracao/mapa_modulos.py`) é a fonte única; os imports foram reescritos pelo mesmo mapa
  (`scripts/migracao/reescrever_imports.py`), não à mão. O resumo origem → destino está em
  `docs/ARQUITETURA.md`.
- Um pacote só, `felixo-notion-mcp` `0.6.0.dev0`, com `uv.lock`, um `start_app.py` na raiz (que abre sem nada
  instalado) e CI em matriz (Ubuntu, Windows, macOS × Python 3.10 a 3.13, `pip-audit`, `npm audit`, conferência
  do conteúdo do wheel).
- `bootstrap.py`, `check-dev.py`, `sync.py` e `SYNC.md` saíram. `AGENTS.md` e `CLAUDE.md` passaram a rotear
  por camada.

**Imports e contagens.** SHAs importados (`main` de cada repositório, em 07/10/2026): `notion-starter`
`42da753`, `notion-tasks-cli` `73ffcd9`, `notion-workspace-app` `0e958ba`; merges `881b531`, `f9f9473` e
`2177b4d`.

| Suíte | Antes (linha de base) | Depois |
| --- | --- | --- |
| `notion-starter` | 678 passed | movida inteira |
| `notion-tasks-cli` | 370 passed | movida inteira, menos 2 testes de faixa do starter, trocados pelo contrato novo do `pyproject` |
| `notion-workspace-app` | 256 passed, 2 skipped | movida inteira |
| hub | 3 passed (`test_check_dev.py`) | saíram junto com o `check-dev.py` |
| **Pacote único** | **1307 passed (soma) + 2 skipped** | **1677 passed, 1 skipped** |

O skip que sobra é por desenho: `tests/scripts/test_migracao.py` pula quando `_importado/` já não tem arquivos
rastreados (a migração terminou). A diferença para cima vem de testes novos: retrato da CLI, scripts de
migração, `doctor` e origem do pacote, `start_app.py` da raiz, conferência do wheel e smoke do binário (1676 no
fim da tarefa 9; a tarefa 10 acrescentou 1, o da mensagem do extra de planilha). Nenhuma suíte migrada perdeu
teste além dos 5 acima, que saíram de propósito.

**Decisões do controlador durante a etapa (Rulings).**

1. **Sobras ignoradas só no checkout principal.** O afastamento de `cli/ front/ server/ src/` ignorados não se
   aplica ao worktree (checkout limpo); roda no checkout principal antes de ele receber o merge, porque é ali
   que essas pastas colidiriam com o layout novo.
2. **`apenas_mapear` na tabela de movimentos.** Shims de 21 linhas e duplicatas do app saem por `git rm`, mas
   os nomes antigos deles entram no mapa apontando para o módulo real; sem isso os `from services.tarefas
   import` da CLI e do app não seriam reescritos.
3. **A execução vai até a tarefa 10 e a revisão final.** Push, PR, merge e renomeação do repositório
   (tarefa 11) são efeitos externos e pedem confirmação do mantenedor (ver o item 13).
4. **Imports relativos viram absolutos.** O plano dizia que relativos não mudam, mas 25 imports relativos em 9
   arquivos do starter quebram quando os arquivos vão para pacotes diferentes; o reescritor passou a
   convertê-los pelo mapa (script em vez de edição manual repetida).
5. **Guardas de string no reescritor.** Extensões de arquivo e de site, e nomes de uma palavra comuns, não são
   trocados fora de um nome pontuado maior; sem isso `api.notion.com` e `RAIZ / "mcp_server.py"` virariam
   caminhos de módulo quebrados. Ficaram 30 avisos, 4 corrigidos à mão.
6. **Ruff com `src = ["src"]`.** Com `tests/core` presente, o isort tratava `core` como pacote de primeira
   parte e reordenava imports de `scripts/`; a raiz `tests` saiu da lista.
7. **O logger passa de `notion_starter` para `felixo_notion_mcp`**, acompanhando o nome do pacote, porque o
   pacote antigo deixa de existir no monolito. Quem configurava o logger pelo nome antigo precisa trocar.
8. **`_servico_do_starter` fica como está.** A função (import dinâmico de serviço que podia faltar no starter do
   PyPI) já aponta para `felixo_notion_mcp.services`; simplificar as 8 chamadas é refatoração da etapa 2. Na
   tarefa 10 só as mensagens mudaram: num pacote único, serviço ausente significa instalação quebrada.
9. **Versão embutida e `--add-data` do binário na tarefa 9.** O caminho `_MEIPASS/"cli"` de `versao.py` e o
   `--add-data` do build ficaram para a tarefa dona do empacotamento nativo.
10. **Commits de movimento mistos ficam.** `ba61283` e `0d2e2de` misturam arquivamento de `IA.md` e remoção de
    READMEs de módulo com o movimento do código; separar exigiria reescrever o histórico da branch. A partir
    da tarefa 6, documentação e código vão em commits separados.
11. **`felixo_notion_mcp/__init__.py` exporta por `__getattr__` preguiçoso (PEP 562).** O launcher precisa
    abrir sem dependência instalada e a tarefa 7 o chama no mesmo processo; mantém `__all__` e todo nome
    público. O custo é que um erro de import só aparece no primeiro uso do nome (coberto por teste que
    importa todos os nomes de `__all__`).
12. **Três achados da CI corrigidos.** `permissions: contents: read` e `persist-credentials: false`; segundo
    passo do `pip-audit` avaliando os marcadores do Python 3.10; `conferir_wheel` exige `static/js/app.js` e
    todo asset que o `index.html` da SPA cita. O plano previa aceitar como lacuna os pins que só existem em
    Windows e macOS (`pywin32`, `pefile`, `macholib`, `colorama`, `tzdata`); como o `uv export` não tem opção
    de plataforma, a CI os extrai do mesmo arquivo e os audita por nome e versão num terceiro passo.
13. **A tarefa 11 foi autorizada pelo mantenedor** (instrução de 07/10: etapa completa, push, PR, CI, merge e
    apagar a branch). A renomeação do repositório ainda recebe um clique de confirmação imediatamente antes,
    porque afeta remotes de outros agentes e o canvas. O mantenedor também decidiu parar ao fim da etapa 1
    para avaliar antes de começar as etapas 2 a 4.
14. **A marca "Automações do Notion" fica na interface até a etapa 4.** O banner do menu
    (`api/launcher.py`), o `templates/tarefas.html` e a descrição do `pyproject.toml` seguem com o nome
    antigo, porque é a etapa 4 que troca a identidade pública publicada (nome da distribuição no PyPI,
    binários e Releases). O custo, se isso estiver errado, é ter telas locais com o nome antigo por uma etapa.

**Bugs achados e corrigidos na etapa.**

- **Token ausente virava "Erro interno".** A fábrica do cliente passou a levantar a `ImproperlyConfigured`
  própria da biblioteca (`RuntimeError`), mas a view capturava só a do Django; sem token, a resposta era "Erro
  interno inesperado" em vez da orientação para iniciar o app. A view captura as duas, com teste que usa a rota
  real sem token (`ed147b3`).
- **`REPO_RAIZ` congelado apontava para fora da pasta privada.** No binário (PyInstaller), `parents[3]` saía
  de `_MEIPASS` para a pasta que a contém (no Linux, a temporária do sistema, gravável por qualquer usuário),
  e um `.env` plantado ali seria carregado a cada execução; congelado, a raiz é a própria `_MEIPASS`
  (`2d3ee4c`).
- **O launcher não abria sem dependências.** Importar o pacote carregava `requests` pelo `__init__`,
  `_pacote_instalado()` era sempre verdadeiro e o `execv` trocava para um `.venv` sem checar se ele importava
  o pacote (`b8b5f5c`; Ruling 11).
- **O smoke do binário disparava o auto-update.** `tasks buscar-conteudo` não estava na lista de comandos
  isentos e chamaria a Release real, gravaria cache e poderia trocar o binário em teste; o smoke agora isola a
  variável de update e a pasta do usuário (`71d04ef`).
- **O retrato da CLI mudava entre versões do Python.** O argparse deriva `required` de posicionais por versão
  (até 3.12, `REMAINDER` e `*` saem obrigatórios; na 3.13, não), o que quebraria o teste de contrato na CI; o
  posicional é obrigatório se, e só se, o `nargs` não admite zero argumentos, e o JSON ficou idêntico em
  3.10, 3.11, 3.12 e 3.13 (`4d35afe`).
- **O launcher instalaria por nome uma distribuição que ninguém registrou.** Fora do checkout,
  `_comando_pip_projeto` montava `pip install felixo-notion-mcp[app]` e o Iniciar tudo o rodava sem perguntar;
  quem registrasse o nome no PyPI ganharia execução de código em quem instalou do código-fonte. Agora fora do
  checkout nada roda `pip`, o Iniciar tudo pergunta antes, e as mensagens apontam o checkout (`e457c02`).
- **O `update` ainda imprimia a receita por nome.** Achado pela revisão do item anterior:
  `_gerenciador_atualizacao` montava `pip install --upgrade`, `pipx upgrade` e `uv tool upgrade` a partir de
  `DISTRIBUICAO` em qualquer ambiente (o `.venv` do checkout inclusive), e `felixo-notion-mcp update` os
  imprimia. Nada era executado, mas era a mesma receita, e a varredura de mensagens não via o nome que vinha da
  constante. Fora do binário nativo, `update` descreve o ambiente e imprime a receita do checkout (`git pull` e
  `uv sync --all-extras`) ou, fora dele, que a distribuição ainda não está publicada e como instalar do
  código-fonte; no JSON `comando` é `null` e a receita vem em `instrucao`, com `executado` sempre `false`. A
  varredura passou a ler o AST e pega o comando montado a partir de `DISTRIBUICAO`. A asserção
  `pipx upgrade felixo-notion-mcp` de `test_cli_unificada.py` (citada em "Mudanças de propósito" abaixo) saiu
  por isso; os comandos por gerenciador voltam na etapa 4, quando o nome estiver publicado (`2c6e1a0`).
- **A instalação comum lia e gravava o `.env` e o banco uma pasta acima.** Numa instalação (wheel, pipx), a
  raiz de `core/config.py` caía em `<venv>/lib/pythonX.Y` em vez de `site-packages`, onde a CLI e o app antigos
  os guardavam; um `pipx upgrade` reaproveita o venv, e um token salvo pelo menu instalado sumia em silêncio.
  A raiz agora é a do checkout só se há `pyproject.toml` ali, e `site-packages` numa instalação (`8de2a28`).
- **A suíte podia mover um store de perfis real e carregava o `.env` real do checkout.** `_migrar_legado` usa
  `shutil.move`, e a fixture de isolamento não zerava `ARQUIVOS_LEGADOS`: um store antigo com tokens iria para
  uma pasta temporária do pytest, apagada no fim (reproduzido com um arquivo falso). Além disso, `notion_tasks`
  e o servidor MCP carregam o `.env` ao serem importados, na coleta, e o checkout principal tem um de verdade.
  O `conftest.py` zera os endereços legados e troca `carregar_env_file` antes da coleta por uma versão que
  pula o `.env` padrão (`e3e9b53`).
- **Também corrigidos:** teste de import preguiçoso com `parents[1]` que apontava para um `src` inexistente e
  era mascarado pela instalação editável (`a0c9cc9`); raiz do build nativo (`parents[1]` virou `parents[2]`
  ao sair para `scripts/empacotamento/`); wheel que passaria servindo página em branco por faltar o bundle da
  SPA (`conferir_wheel`); `npm audit` com três altas no `front/` (`d62a4e6`).

**Mudanças de propósito que parecem regressão.**

- **Asserções que mudaram de propósito:** os dois testes de faixa do `notion-starter` de `test_pyproject.py`
  viraram o contrato novo (nome `felixo-notion-mcp`, nenhuma dependência de `notion-starter`,
  `notion-workspace-app` ou `notion-automacoes`, e os executáveis apontando para funções que existem);
  em `test_cli_unificada.py`, `pipx upgrade notion-automacoes` virou `pipx upgrade felixo-notion-mcp`,
  `"notion-automacoes[app]"` virou `"felixo-notion-mcp[app]"` e `--version` prende o literal
  `notion-automacoes 0.6.0.dev0`; `test_versao_starter.py` compara `felixo_notion_mcp.__version__` com o
  `pyproject` (o pacote nasce em `0.6.0.dev0`); no launcher, o comando que reabre o menu é
  `-m felixo_notion_mcp.api.launcher` (rodar o arquivo por caminho quebra a biblioteca padrão) e o extra de
  instalação é `.[app]`, já que `[server]` deixou de existir.
- **Logger renomeado** de `notion_starter` para `felixo_notion_mcp` (Ruling 7): é mudança de comportamento
  para quem configurava o logger por nome. Nenhum código ou teste do repositório dependia do nome antigo.
- **Mensagens de execução** que ainda citavam `notion-starter` (instalação do extra de planilha, relatório
  DOCX, serviço ausente da CLI) passaram a citar `felixo-notion-mcp`, porque os textos antigos tratavam de
  uma distribuição que deixou de ser dependência. O serviço ausente agora diz "instalação quebrada" e
  aponta para o `doctor`. Nenhum teste dependia do texto antigo; quatro ganharam asserções que o prendem
  (`test_cli_copiar_corpo`, `test_cli_remover_coluna`, `test_relatorios_docx_import_preguicoso` e o novo
  caso do extra de planilha em `test_fonte_planilha`). As docstrings que citavam `notion_starter.*` como
  módulo atual passaram a citar o módulo real, pelo mapa da migração; as menções históricas deliberadas
  ("herdada do `notion_starter`", "tempo em que a CLI e o `notion-starter` tinham versões separadas")
  ficaram. Os apelidos locais `starter_properties` e `starter_schema` em `notion_tasks.py` e `server.py`
  seguem como estão (nome de variável, não texto).

**Refinamentos sobre a spec.**

- **`scripts/empacotamento/` em vez de `packaging/`** (spec 2.2). Uma pasta `packaging/` na raiz do
  `sys.path` esconderia a biblioteca `packaging`, da qual pip, hatch e pytest dependem. O Dockerfile do modo
  hospedado (etapa 3) fica na raiz, como o guia de deploy no Railway pede.
- **`sync.py` aposentado em vez de movido** (spec 2.3.3 mandava mover). Ele só sincronizava os módulos, que
  deixaram de existir; `criar_tarefas_investigadas_*.py` foi para `scripts/notion/`.
- **Sobras não colidentes mantidas** (spec 2.3.7). Só as pastas ignoradas que colidem com o layout novo
  (`cli/`, `front/`, `server/`, `src/`) são afastadas; `operacional.sqlite3`, `.notion-backups/` e `Arquivos/`
  continuam onde estão, ignoradas pelo git e sem colidir com nada.
- **`api/operations/` não nasce nesta etapa.** O app Django `operations` (modelos `Job` e `Lock`) foi para
  `repositories/operations/` com rótulo e tabelas preservados; o registro único de operações da spec 3.2 é da
  etapa 2.
- **Extra `[server]` virou `[app]`**; o modo hospedado (`[servidor]`) é da etapa 3. `core/origem.py` é novo e
  atende o `doctor` e o Status do menu.
- **A baseline do starter é 678, não 677:** o `IA.md` de 27/09 registrava 677 e a medição de 07/10 deu 678.
- **Itens do menu antigo do hub que saíram.** O `start_app.py` do hub tinha o "Usar" (guia, listar, opções e
  comando livre da CLI) e um editor de variáveis de ambiente (`GITHUB_CONTAS` e parecidas). Não foram
  portados: quem os usava passa a rodar a própria CLI (`felixo-notion-mcp` ou `notion-tasks`, com `guia`,
  `listar`, `opcoes` e `--help`) e a editar o `.env`, que tem o modelo em `.env.example`.
- **Estreitamento da spec 2.3.2 aceito na etapa 1.** A spec pedia "Configurar (perfis/chaves)" e "Status (o
  doctor)". O Configurar do menu define só o token do Notion e o database de tarefas (os perfis são da CLI:
  `felixo-notion-mcp auth` ou `notion-tasks perfis`), e o Status mostra o estado do ambiente e de onde o pacote
  é importado, sem rodar o `doctor` inteiro, que fica na CLI. A documentação (`README.md`, `start_app.py`,
  `docs/QUALIDADE.md`, `AGENTS.md`) descreve o menu assim.

**Limites e o que não mudou.**

- O binário nativo foi **construído e testado só em Linux x64** (Python 3.13, PyInstaller 6). Windows e macOS
  (x64 e arm64) passam pela CI de testes pela primeira vez na tarefa 11, e o build e o smoke nativos nesses
  sistemas ficam para a CI de release da etapa 4. Detalhes do build real na entrada "Empacotamento nativo
  aponta para o pacote único" (commit `0811ea1`), logo acima.
- Os **pacotes publicados no PyPI não mudam** até a etapa 4: `notion-automacoes` `0.5.0`, `notion-starter` e
  `notion-workspace-app` seguem como estão, e os assets dos binários continuam `notion-automacoes-<alvo>`.
  `REPOSITORIO_GITHUB` do atualizador nativo também não mudou.
- Código sem uso até a etapa 2: `_servico_do_starter` e as 8 chamadas (Ruling 8). Dívida herdada, para a
  revisão final: `domain/tasks.py` importa `integrations.notion_client` (domínio dependendo de integração); o
  teste de arquitetura da spec 3.1 é da etapa 2.
- Pendência aberta: `mcp start` no binário nativo usa `sys.executable -m`, padrão herdado do código antigo que
  não funciona em PyInstaller onefile; não foi verificado em build.
- **O nome `felixo-notion-mcp` no PyPI precisa ser reivindicado cedo.** Um *pending publisher* do Trusted
  Publishing **não reserva** o nome: quem registrar `felixo-notion-mcp` antes da etapa 4 passa a ser o dono dele
  (em 07/10/2026 a consulta ao PyPI ainda dava 404). Enquanto isso, nada no código instala a distribuição por
  nome: o launcher só instala em modo editável dentro de um checkout, e as mensagens apontam o extra e o
  checkout (`uv sync --all-extras` ou `pip install -e ".[app]"`). A publicação da `0.6.0` da etapa 4 depende de
  o nome ser do projeto.
- Guias antigos de `docs/` que não estavam no escopo desta tarefa (`CONTRATOS.md`, `PLANO.md`, `AGENTES.md`,
  `INTEGRACOES.md` e parecidos) ainda citam `server/`, `cli/` e `notion_starter` do tempo dos módulos; o
  caminho de hoje está na tabela origem → destino de `docs/ARQUITETURA.md`. Atualizá-los fica para uma
  tarefa própria. Já foram corrigidos `INFRA.md` e `MCP.md`, que mandavam entrar em `modules/`.

**Como validar:** `uv sync --locked --all-extras`, `uv run ruff check .`, `uv run python -m pytest`, e
`uv run felixo-notion-mcp doctor` para ver de onde o pacote está sendo importado.

## [2026-10-10] Validação dos binários nativos em máquina limpa: dois defeitos de distribuição medidos

**Contexto.** A task "validar os 4 binários nativos 0.4.0 em máquinas/VMs limpas sem Python" pedia provar que
os binários da Release rodam fora do runner que os constrói. O smoke da release roda no mesmo runner do build,
que tem Python e a glibc mais nova, e ainda define `PYTHONIOENCODING`; ele não enxerga o que um usuário encontra.

**O que entrou.** `scripts/empacotamento/validar_binario_limpo.sh` (Linux e macOS) e
`validar_binario_limpo.ps1` (Windows) rodam sem instalar nada: conferem o SHA-256 publicado, a ausência de
Python no `PATH` e executam `--version`, `--help`, `tasks --help`, `doctor` e `--json doctor` numa pasta de
usuário descartável. O workflow manual `.github/workflows/validar-binarios.yml` roda os scripts em contêineres
mínimos (seis distribuições Linux, sem rede), em contêineres Server Core 2022 e 2025 e nos runners macOS 14 e 15
(ARM) e 15 (Intel). A tag e o repositório da Release são entradas do workflow.

**O que foi medido** (runs `38102477673` para a `v0.5.0` e `38102479991` para a `v0.4.0`, mesmo resultado):

- macOS Intel e ARM: os cinco comandos saem com código 0. O binário tem assinatura *ad hoc*; com o atributo de
  quarentena, `spctl` responde `rejected`. Pelo terminal ele roda mesmo em quarentena.
- Windows Server 2022 e 2025 sem Python: quatro comandos passam; **`doctor` sai com código 2** e
  `'charmap' codec can't encode character '✓'` quando a saída é capturada. A fachada
  (`api/cli/unificada.py`) não força UTF-8 na saída; só `notion_tasks.py` faz isso. O smoke não pega porque
  define `PYTHONIOENCODING=utf-8`.
- Linux: passa em Ubuntu 24.04, Debian 13 e Fedora 42. **Falha em Ubuntu 22.04, Debian 12 e Rocky 9** com
  `GLIBC_2.38 not found`: o binário é construído em `ubuntu-24.04` e herda a glibc dele.

**Limitações.** Os runners do macOS trazem `/usr/bin/python3`; lá não existe máquina "sem Python", e o que se
mediu foi a execução com `PATH` mínimo e ambiente vazio. O aviso do SmartScreen e a janela do Gatekeeper só
aparecem numa sessão com tela, ao abrir pelo Explorer ou pelo Finder: não foram vistos. Os dois defeitos e a
conferência com tela viraram tasks; nenhum foi corrigido aqui, porque a correção só se prova numa Release nova,
que é da etapa 4.

**Como validar:** `gh workflow run validar-binarios.yml -f tag=v0.5.0` e ler o resumo do run; num Linux local,
`docker run --rm --network none -v "$PWD/bin:/b:ro" -v "$PWD/scripts/empacotamento:/s:ro" debian:12 sh
/s/validar_binario_limpo.sh /b/notion-automacoes-linux-x64 /b/notion-automacoes-linux-x64.sha256`.

## [2026-10-19] Dependências atualizadas e servidor MCP migrado para o SDK `mcp` 2.x

Registrado pelo agente "Atualização da lib" (canvas do Felixo AI Core).

**Contexto.** O pedido teve três partes: (1) migrar o SDK `mcp` de 1.30 para 2.x; (2) atualizar
as demais dependências, Python e `front/`, sem trocar de major; (3) atualizar a cópia da lib que o
Felixo AI Core e a CLI usam. Antes de mexer, o gate estava verde: ruff limpo e 1771 testes
passando, 4 pulados.

**O que entrou**, um commit por lote:

- `e06cf28`: `front/package-lock.json` dentro das faixas (vite 8.3.4, oxlint 1.89.0, tailwindcss
  4.3.3, lucide-react 1.59.0 e outros). `npm audit`: 0 vulnerabilidades. O oxlint 1.89 traz a
  regra `react(set-state-in-effect)`, que aponta 3 avisos em código que já existia; eles não
  bloqueiam (o lint sai com código 0).
- `8f97110`: `uv.lock` dentro das faixas (pydantic 2.14.1, starlette 1.9.0, certifi, filelock,
  platformdirs, pluggy, pycparser). Nenhuma delas é importada direto pelo código.
- `3d9c020`: ruff 0.16.10 → 0.17.1. As quebras da 0.17 (Python padrão 3.11, conjunto padrão de
  regras) não alcançam este projeto, que declara `target-version` e `select` no `pyproject.toml`.
- `53dd522`: `tests/api/mcp/test_mcp_stdio.py`, um teste de contrato que sobe o servidor por
  `stdio` e conversa em JSON-RPC cru, sem o SDK do lado do cliente. Entrou e passou ainda no
  1.30, para servir de rede para a migração.
- `f37db16`: `mcp>=2.3,<3` e lock em 2.3.0. `FastMCP` virou `MCPServer`, as anotações passaram
  para snake_case no Python (no fio continuam camelCase) e o `serverInfo` anuncia a versão do
  pacote. O 1.x anunciava a versão do SDK, e o 2.x anunciaria vazio.
- `b2abb70`: `docs/MCP.md` com o SDK 2.x, as duas eras do protocolo e o teste de stdio.

**Decisão: falha prevista sai como `ToolError`.** O teste de stdio pegou uma regressão que os
testes antigos, que chamam as funções Python direto, não viam. No SDK 2.x só a mensagem de um
`ToolError` chega ao modelo. Qualquer outra exceção vira `Error executing tool <nome>`. Com isso,
o motivo da recusa (`'page_id' e obrigatorio`, `Servidor MCP nao configurado corretamente.`)
tinha sumido. `_executar` agora levanta `EntradaInvalidaError` (`ToolError` + `ValueError`) e
`FalhaDaFerramentaError` (`ToolError` + `RuntimeError`), então quem chama as funções direto
continua vendo os tipos de antes. Erro inesperado continua sendo `RuntimeError`, que o SDK trata
como queda: o traceback fica no log do servidor e o modelo não recebe detalhe interno. Esse
caminho ficou assim de propósito: um `ToolError` registraria o erro sem traceback. Com a correção
desfeita, os 3 testes novos de erro falham.

**Item 3: a cópia que o AI Core usa já é este checkout.** O código do AI Core não chama a lib:
o bloco "Tarefas Notion" fala direto com a API do Notion (`notion-client.cjs`), e o MCP do Notion
ainda é `planned` no catálogo. Os agentes chamam `notion-tasks` pelo `PATH`, e o único
`notion-tasks` desta máquina é o atalho `~/.local/bin/notion-tasks.cmd`. Ele roda
`<checkout>/.venv/Scripts/python.exe -m felixo_notion_mcp.api.cli` com
`PYTHONPATH=<checkout>/src`. Não há cópia em pipx, em `uv tool` nem binário baixado. Atualizar a
cópia é, portanto, manter o `.venv` em dia: `uv sync --locked --all-extras` depois de cada
mudança de lock, como foi feito em cada lote. Depois da atualização, o atalho rodou
`notion-tasks --json listar` (2054 tarefas) e `opcoes` contra o Notion real, só leitura, e
importa `mcp` 2.3.0 do `.venv`. Ninguém sabe quem criou o atalho: nenhum dos dois repositórios
tem script que o escreva.

**Validação.** Suíte inteira com o SDK 2.3: 1782 testes passando, 4 pulados (as 1771 de antes
mais 11 novos). Testes de `tests/api/mcp/` em Python 3.10, 3.11 e 3.13. O cliente oficial do SDK
2.x conectou por `stdio` nas duas eras: `2026-07-28` no modo `auto` e `2025-11-25` no modo
`legacy`, com 18 ferramentas. O teste de stdio cobre `2025-06-18`. O Streamable HTTP respondeu ao
`initialize` em `127.0.0.1:8000/mcp`. O `pip-audit` sobre o lock exportado, inclusive os pins por
plataforma, não acha vulnerabilidade conhecida, e o uv 0.12.13 da CI aceita o lock
(`uv lock --check`).

**Binário nativo Windows.** O build com o SDK 2.3 passa, e o pacote inclui `mcp.server.mcpserver`
e os validadores `mcp_types._v2025_11_25`/`_v2026_07_28`. No `smoke_native.py`, passam
`--version`, `--help` e `tasks --help`, e o `--json doctor` responde `ok: true`. O smoke falha na
conferência do texto `binário nativo`: o binário escreve `·` e `á` fora de UTF-8, mesmo com
`PYTHONIOENCODING=utf-8`, e o texto chega corrompido.
Não ficou provado se a falha já existia antes da migração: um build de comparação a partir de
`3d9c020` (antes do SDK 2.x) foi interrompido no meio, a pedido, para fechar a sessão. A suspeita
é que seja anterior: a conferência não passa pelo SDK, e o binário Windows do pacote único nunca
tinha passado por este smoke (ver a entrada de 2026-10-07). Para fechar a dúvida, rode o mesmo
build e o mesmo smoke em `3d9c020`. A chamada `mcp start` no binário continua sem funcionar
(`sys.executable -m` em onefile, pendência de 2026-10-07).

**Limitações e pendências.**

- Numa das rodadas da suíte, com a CPU disputada pelo `npm update`, um teste falhou perto de 85% e
  a execução estourou o prazo antes de mostrar qual era. Pela posição, era um dos testes de
  `test_services_historico_repositorios.py`, que rodam `git` de verdade. A rodada seguinte, com o
  mesmo lock, passou inteira, e esse arquivo passa isolado. Fica registrado como intermitente sob
  carga, sem teste identificado.
- Ficam para uma atualização própria, por serem major: React e React DOM 19, `@types/react` e
  `@types/react-dom` 19 e framer-motion 14.
- Os 3 avisos de `react(set-state-in-effect)` no `front/` (`use-tarefas.js`, `use-exploracao.js`,
  `tarefa-form.jsx`) pedem revisão dos efeitos com verificação visual. Não foram tocados.
- Confirmado de novo: neste caminho com acento, o `.venv` não importa o pacote sem `PYTHONPATH=src`
  (o `.pth` editável não resolve). Já existe task no Notion para isso. O teste de stdio contorna
  passando ao processo filho a pasta de onde o próprio teste importou o pacote.
- `felixo-notion-mcp doctor` sem `PYTHONUTF8=1` ainda quebra com `charmap` no Windows. É o
  defeito medido em 2026-10-10 e não tem relação com esta atualização.

**Como validar:** `uv sync --locked --all-extras`, `uv run ruff check .`,
`uv run python -m pytest` (no Windows, neste caminho, com `PYTHONPATH=src` para os comandos fora do
pytest) e, só para o contrato do MCP, `uv run python -m pytest tests/api/mcp/test_mcp_stdio.py`.
No `front/`: `npm ci`, `npm run lint`, `npm run build` e `npm audit --audit-level=high`.

## [2026-10-20] Pendência: scripts da biblioteca ainda não são módulos do pacote

Registrado pelo agente "Atualização da lib" (canvas do Felixo AI Core).

**Contexto.** As importações de rapha.land (15 artigos, MIT) e akitaonrails.com (817 posts,
CC BY-NC-SA 4.0) para a database Books produziram ferramentas novas. Parte entrou no pacote; parte
ficou como script solto em `scripts/notion/`.

**Já no pacote:** comando `aparencia` (domain/services/CLI); `garantir-coluna --opcoes`; leitor de
colunas `files` em `domain/readers.py`.

**Ainda fora do pacote (dívida):**

- `scripts/notion/importar_artigos_para_biblioteca.py`: dedup pela URL da fonte, completa sem apagar,
  anexos, aparência, paralelo. Chama a CLI por subprocesso (`python -m felixo_notion_mcp.api.cli`),
  não os serviços.
- `scripts/notion/blog_hugo_para_biblioteca.py` + `scripts/notion/mapas/akitaonrails.json`: posts de
  blog Hugo em PDFs e rascunhos (tags pela taxonomia, categorias, capas).
- `scripts/notion/artigo_para_pdf.py`: Markdown em PDF via Edge/Chrome headless, licença MIT/CC,
  redução de imagens.
- Os dois de PDF dependem de `markdown`, `pyyaml`, `pillow` e `certifi`, declarados só no PEP 723.
- Nenhuma dessas operações nem `aparencia` existe como ferramenta MCP.

**Plano proposto (não executado, a pedido):** caso de uso de importação em `services/` usando o
`NotionClient` direto; geração de PDF em `integrations/` com extra opcional `[biblioteca]`; leitura de
blog Hugo em `services/` com o mapa como configuração; comandos CLI e ferramentas MCP
(`notion.set_page_appearance`, `notion.import_articles`), atualizando o teste de contrato que hoje
espera 18 ferramentas; scripts viram atalhos finos. Por mexer em várias camadas, fazer numa branch
própria.

**Armadilhas aprendidas:** plano gratuito do Notion aceita até 5 MiB por arquivo; `cmd.exe` quebra
argumentos com `"` e `&` (nunca chamar a CLI pelo `.cmd`); o Notion aceita até 100 opções por
requisição de schema; posts do mesmo dia e mesmo título precisam de nome de arquivo único; arquivos
com quebra `\r\n` contaminam caminhos lidos no Git Bash.

## [2026-10-20] Biblioteca vira módulos do pacote (resolve a pendência anterior)

Registrado pelo agente "Atualização da lib". Branch `refactor/biblioteca-em-modulos`.

**O que mudou.** Os scripts de `scripts/notion/` usados nas importações de rapha.land e
akitaonrails.com viraram módulos em camadas, com CLI e MCP:

- `integrations/pdf.py` (Markdown em PDF via Edge/Chrome), `integrations/imagens.py` (reduzir,
  comprimir até caber, gerar capa original com Pillow), `integrations/web.py` (feed, sitemap,
  extração do miolo do artigo) e `GitHubClient.listar_arvore`/`ler_arquivo`;
- `services/downloads.py` (cache, retentativa, limite), `services/coleta.py` (descobrir artigos
  de um site; baixar uma pasta de um repositório), `services/traducao.py` (Markdown em pedaços
  pelo `ProvedorIA`, código intacto), `services/organizacao.py` (taxonomia, tags, mapas de
  categoria), `services/blog_hugo.py` (sem argparse: `OpcoesLote` + `gerar_lote`) e
  `services/biblioteca.py` (gravar sem duplicar usando os serviços, sem subprocesso nem shell);
- `services/aparencia.py` comprime a imagem local que passa do limite de upload;
- CLI: `coletar-artigos`, `artigo-pdf`, `traduzir`, `gerar-capa`, `ajustar-imagem`,
  `blog-para-biblioteca`, `importar-artigos` (em `api/cli/biblioteca.py`);
- MCP: `notion.set_page_appearance`, `discover_articles`, `extract_article`,
  `translate_markdown`, `article_to_pdf`, `generate_cover`, `import_articles` (25 ferramentas).

**Decisão.** A ferramenta não verifica nem bloqueia por licença de conteúdo: quem usa decide e
assume (pedido do dono do projeto). O PDF aceita um aviso de licença opcional no rodapé.

**Dependências.** Extra opcional `[biblioteca]`: markdown, pyyaml, pillow. PDF exige Edge ou
Chrome. Tradução usa a chave do OpenRouter que o projeto já lê do ambiente.

**Removido.** `scripts/notion/importar_artigos_para_biblioteca.py` (agora `importar-artigos`).
## [2026-10-20] Database "Registro diário" na HOME e opções de select no `criar-database`

Registro do agente *Organização* (canvas).

**Estado:** concluído pela API; três passos que só a interface faz ficaram com a pessoa.

- Criado o database inline **Registro diário** (`3ff91f95-497e-81e4-b31d-d7358e13a62b`,
  data source `3ff91f95-497e-8107-8e6c-000b7f1d3744`) na HOME, sob um tópico novo
  `## Registro diário` (divisória + título, como os outros tópicos). Ícone 📔, descrição,
  `unique_id` com prefixo `DIA` e as 10 colunas do pedido, conferidas com `schema`.
- **Feature:** `schema_propriedade` (e, por ela, `criar-database --prop`) aceita opções em
  `select`/`multi_select`: `"Banho=select:Sim,Não"`. Antes, a coluna nascia sem opções e
  a primeira escrita é que as inventava. Testes em `tests/domain/test_properties.py`.
- Manifesto do modelo **Dia padrão** em `scripts/notion/registro_diario/` (validado com
  `modelos preencher --dry-run`).

**Não dá pela API** (versão 2022-06-28 do cliente; já medido antes para modelos): criar
visualização (calendário por `Data`), definir ordenação da view, criar modelo nativo e
marcá-lo como padrão. **Próximo passo, pela interface:** adicionar a view Calendário por
`Data`, ordenar a tabela por `Data` decrescente, clicar em "Novo modelo" sem digitar nada e
rodar `notion-tasks modelos preencher 3ff91f95-497e-81e4-b31d-d7358e13a62b --manifesto
scripts/notion/registro_diario/modelos.json`; depois marcar "Dia padrão" como padrão.

### [2026-10-20] Continuação — ordenação pela Views API; modelo nativo aguardando o cookie

- **Medido (API `2026-03-11`):** `POST /pages` com `is_template` → 400 ("should be not
  present"); `POST /data_sources/{id}/templates` → 400 `invalid_request_url`. O MCP oficial
  do Notion também não tem ferramenta que crie modelo (só lista e aplica). Criar modelo e
  definir o padrão continua possível **só** pela API interna do app web (`/api/v3`,
  cookie `token_v2`). A pessoa escolheu esse caminho, num módulo isolado com o cookie só
  por variável de ambiente (`NOTION_TOKEN_V2`).
- **Feito:** `NotionClient.listar_views/obter_view/atualizar_view` (constante
  `NOTION_VIEWS_VERSION`), serviço `services/views.py` e comando `ordenar-view`, que
  confere por releitura. Aplicado: view "Tabela" (`3ff91f95-497e-816d-bdec-000cf3894482`)
  do Registro diário ordenada por `Data` decrescente. A releitura devolve a propriedade
  **pelo ID** (`PWK]`), não pelo nome, por isso a conferência compara direção e quantidade.
- **Estado: aguardando a pessoa.** O pedido do cookie pelo painel foi dispensado. Sem
  `NOTION_TOKEN_V2` no `.env` não dá para medir o formato da transação interna (em
  especial onde o Notion guarda o modelo padrão), e escrever esse módulo sem medir seria
  adivinhar. Próximo passo, com o cookie: medir com `syncRecordValues` num database que já
  tem modelo padrão (Ideias criativas), escrever `integrations/notion_interno.py` + comando,
  criar o "Dia padrão" e preenchê-lo com `modelos preencher` (manifesto em
  `scripts/notion/registro_diario/`).
- **Decisão (mesmo dia):** a pessoa preferiu não passar o cookie nem configurar o MCP do
  Chrome (não está neste perfil do Claude; `claude mcp list` vazio). Ela cria o modelo em
  branco pela interface e o agente preenche com `modelos preencher`. O módulo de API
  interna fica **fora do escopo** por ora.
- **Defeito corrigido:** `modelos listar` devolvia os exemplos de `inventario`,
  `baixar-corpos` e `buscar-conteudo` dentro do resultado: uma substituição em massa
  (`055317c`) os tirou de `EXEMPLOS_GUIA` e os colou no `return`. Voltaram para o guia, e
  o teste agora trava as chaves do resultado.
- **Retrato da CLI:** `ordenar-view` foi **acrescentado** a `tests/contrato/retrato_cli.json`
  (só inserção; nenhuma linha de comando antiga mudou). O retrato guarda o que não pode
  quebrar, e comando novo é acréscimo, não regressão.
- **Modelo preenchido:** a pessoa criou o modelo em branco e `modelos preencher` o
  transformou em **Dia padrão** (`3ff91f95-497e-800c-b600-ea11a7d596fc`): `Status do dia =
  Aberto`, opcionais vazias, corpo do pedido. Conferido relendo com `conteudo`. O título do
  modelo é o próprio nome ("Dia padrão"), porque no Notion o nome do modelo **é** a coluna
  de título; cada dia novo sobrescreve com `DD-MM-AAAA`.
- **Estado final:** concluído, exceto **marcar "Dia padrão" como modelo padrão**, que fica
  com a pessoa (⋯ do modelo → Definir como padrão). A API não faz isso. Para conferir:
  `notion-tasks --json modelos listar 3ff91f95-497e-81e4-b31d-d7358e13a62b` → `"padrao": true`.
- **Modelo preenchido:** "Dia padrão" (`3ff91f95-497e-800c-b600-ea11a7d596fc`) criado em branco
  pela pessoa e preenchido por `modelos preencher` (a rodada interrompida já tinha gravado; a
  seguinte respondeu `ja_existia`). Relido: nome, `Status do dia = Aberto`, corpo completo.
  **Estado final:** concluído, exceto marcar o modelo como padrão (`is_default` ainda
  `false`), que só a interface faz — aguardando a pessoa.
- **Concluído (2026-10-20):** a pessoa marcou "Dia padrão" como padrão; relido pela API com `is_default: true`.

### [2026-10-20] Registro diário preenchido de 16/10 a 20/10

- **Fontes:** database Relatórios diários (`62971953-ca6e-4aaa-97c7-320e0cfd4ae7`) para 16 e 17/10;
  commits do GitHub da conta (`gh api search/commits`) para 19 e 20/10. O repositório do
  MeuEcoo Mídia não é acessível por esta conta do `gh`; para ele valem só os relatórios.
- **Criados:** 16-10 (DIA-2), 17-10 (DIA-3), 19-10 (DIA-4) como `Encerrado`; 20-10 (DIA-5) como
  `Aberto`, com o resumo em branco para a pessoa fechar o dia. **18/10 não tem linha:** sem
  relatório e sem commit, criar seria inventar. Horas, sono, banho e produtividade ficaram
  vazios: os blocos de trabalho dos relatórios se sobrepõem (agentes em paralelo), então somar
  seria estimar. Só `Projetos pessoais = Sim`, que tem evidência.
- **Classificação (do agente, revisável):** felixo-blog e Felixo-Notion-MCP em Projetos pessoais;
  MeuEcoo Mídia e crm-solar-prototipo em Tarefas de trabalho.
- **Atenção:** este checkout está 35 commits atrás de `origin/main`, que já tem
  `garantir-coluna --opcoes` e ajustes no retrato da CLI (commits de 20/10, 01:55–02:13). As
  mudanças locais desta sessão (opções em `criar-database`, `ordenar-view`, correção de
  `modelos listar`) **não foram commitadas** e precisam ser reconciliadas com esse trabalho antes
  do commit. **Estado:** preenchimento concluído; reconciliação de código aguardando a pessoa.
- **Horas estimadas (pedido da pessoa, mesmo dia):** relatório → união dos blocos por área, sem
  contar duas vezes a sobreposição; só git → sessões de commits (intervalo de mais de 2 h abre
  sessão nova) + 30 min antes do primeiro commit. Gravado: 16/10 5.4 trabalho / 8 pessoal;
  17/10 1.6 / 0.1; 19/10 — / 3.5; 20/10 0.5 / 6.7 (parcial). Cada dia diz nas Anotações que
  as horas são estimadas e como. `Acordei às`, `Sono`, `Banho` e `Produtividade` continuam
  vazios: nenhuma fonte os indica (o primeiro commit não é hora de acordar). **Estado:** concluído.
- **Rotina estimada (pedido da pessoa):** Acordei às = primeira atividade − 1 h (16: 10:00, 17:
  10:20, 19: 13:30); Sono = última atividade da véspera + 30 min até acordar, só quando a véspera
  tem registro e o resultado é plausível (17: 10.5 h; 16 e 19 sem véspera registrada); Produtividade
  por horas no dia (≥ 7 h Alta, 3–7 h Média, < 3 h Baixa): 16 Alta, 17 Baixa, 19 Média, 20 Alta.
  20/10 ficou sem hora de acordar e sem sono: commits desde 00:59 com pausas de ~2 h tornam a
  noite ambígua. Banho vazio (nenhuma fonte). Critérios anotados em cada dia. **Estado:** concluído.
- **20/10:** a pessoa informou que acordou às 08:20; sono estimado em 1.6 h (06:43–08:20, depois dos commits da madrugada até 06:13).
- **19/10:** Banho = Sim (informado pela pessoa). Os outros dias continuam vazios, sem informação.

## [2026-10-20] Scripts da sessão "Registro diário" viram módulos (CLI e MCP)

Agente *Organização* (canvas). **Estado:** concluído.

- **O que eram scripts e virou módulo:** busca de commits no GitHub →
  `GitHubClient.buscar_commits`; união de intervalos, sessões de commits, acordar, sono e
  produtividade → `domain/rotina_diaria.py`; criação do dia sem duplicar, leitura dos
  relatórios, estimativa e aplicação só nos vazios → `services/registro_diario.py`; corpo do
  "Dia padrão" (antes em `scripts/notion/registro_diario/`) → `CORPO_DIA_PADRAO`. Expostos em
  `registro-diario garantir|estimar` na CLI e em `notion.sort_view`,
  `notion.ensure_daily_log_day` e `notion.estimate_daily_log` no MCP.
- **Defeitos que os testes e a validação com dados reais pegaram:**
  1. **A busca de commits do GitHub filtra datas em UTC.** O commit `cce0940`, às 22:06 de
     15/10 (−03:00), aparecia como do dia 16 na listagem por dia feita à mão. Por isso a
     afirmação desta sessão de que "a noite de 15/10 não tinha registro" estava **errada**: o
     sono de 16/10 é estimável (11.9 h). `estimar_periodo` pede um dia a mais e agrupa pelo
     fuso do próprio commit.
  2. **Conta manual errada:** o sono de 17/10 gravado à mão (10.5 h) era 10.9 h
     (23:23 → 10:20).
  3. O aquecimento de 30 min de um commit à 00:00 começa na véspera: atividade que começa no
     dia anterior também é noite estendida, não hora de acordar.
  4. "Meu Ecoo Midia" (relatório) não casava com o termo `MeuEcoo`: a área compara nomes sem
     caixa, espaço, hífen nem sublinhado.
- **Integração com `origin/main`:** o checkout estava 35 commits atrás. O `garantir-coluna
  --opcoes` que chegou montava o schema na camada de API; agora ele e o `criar-database
  --prop "X=select:A,B"` usam a mesma regra do domínio (`schema_propriedade(opcoes=)`). O
  teste do retrato da CLI de `origin/main` já aceita subcomando novo, então a edição local
  no `retrato_cli.json` foi descartada.
- **Beco sem saída registrado:** criar modelo nativo e marcá-lo como padrão não existe na API
  pública (`2026-03-11`: `is_template` → 400; `POST /data_sources/{id}/templates` →
  `invalid_request_url`) nem no MCP oficial do Notion. Só a API interna do app web (cookie
  `token_v2`), que a pessoa preferiu não usar.

### [2026-10-20] Toggle pelo Markdown e organização do dia por repositório

- **Pedido da pessoa:** no Registro diário, um título (`###`) por repositório; assuntos do
  mesmo repositório ficam em toggles (`>`), não em subtítulos repetidos ("MeuEcoo Mídia —
  Cobrança", "MeuEcoo Mídia — Afiliados"…), que deixavam a página confusa.
- **Feature:** `markdown_para_blocos` transforma `> título` **seguido de linhas recuadas** em
  toggle com essas linhas dentro (o mesmo `>` que cria toggle na interface). `> texto` sem
  linhas recuadas continua citação, então nenhum Markdown antigo muda de significado. A
  leitura devolve o toggle como `> texto` com os filhos recuados, e a reescrita refaz o
  toggle. Profundidade: toggle → tarefa → passo cabe nos 2 níveis por requisição da API.
- **Aplicado:** página de 20-10-2026 com as 18 tarefas do dia; MeuEcoo Mídia em 6 toggles
  (Cobrança, Afiliados, Login e acesso, Zernio e redes sociais, Produto, Comunicação).
  **Estado:** concluído; aguardando a pessoa confirmar o repositório "WhatsApp Agents".
- **Defeito pego no uso (mesmo dia):** ao mover o WhatsApp Agents para Tarefas de trabalho
  (é repositório privado do trabalho, como o MeuEcoo; por isso não aparecia no `gh`), o
  `escrever --substituir` **preservou** os 6 toggles antigos e duplicou a seção no topo,
  porque `toggle` ainda estava em `TIPOS_NAO_RECRIAVEIS`, de quando o Markdown não o
  recriava. Os 6 duplicados foram apagados (arquivados, restauráveis) e toggle entrou em
  `TIPOS_RECRIAVEIS`: toggle só de texto sai e volta na reescrita; com imagem, database ou
  outro não recriável dentro, a regra de contêiner preserva o toggle inteiro. **Estado:**
  concluído.

### [2026-10-21] Pendências do dia anterior viram o comando `registro-diario pendencias`

- **Pedido da pessoa:** criar a página de 21-10-2026 no Registro diário (acordou 07:40, sem
  banho, dormiu 02:00, começando o trabalho) e passar para ela tudo o que ficou pendente em
  20-10-2026, no mesmo padrão (título por repositório, toggles por assunto).
- **Decisão: cópia bloco a bloco, não Markdown.** A escrita por Markdown grava no máximo
  2 níveis por requisição e achata o resto (`MAX_NIVEIS_ANINHADOS`), e o dia tem 4: toggle →
  tarefa → passo → nota. O gravador do `copiar_corpo` já anexava os filhos fundos depois, no
  bloco criado; o miolo virou `copiar_blocos` para gravar uma árvore já filtrada.
- **Regra** (`domain/pendencias_do_dia.py`): tarefa sem check vai inteira, com os passos
  feitos e as notas, porque dizem onde ela parou; toggle vai só com as pendentes e some sem
  nenhuma; título de repositório só entra com pendência embaixo; as três seções de tarefas
  ficam sempre; anotações e resumo ficam na origem.
- **Serviço** (`levar_pendencias`): sem origem, usa o último dia antes (maior `Data`
  anterior); nunca duplica o dia; recusa origem fora do modelo antes de criar; se a escrita
  falha no meio, manda a linha nova para a lixeira, para a repetição funcionar. Bordas:
  `registro-diario pendencias` na CLI e `notion.carry_over_daily_log` no MCP.
- **Aplicado e validado:** a página de 21-10-2026 foi criada primeiro por um script
  descartável, conferido linha a linha com o dia 20 (só saíram CRM Solar e Felixo Notion
  MCP, todas concluídas; 19 tarefas levadas; corrigido "opçãoer" → "opção"). Depois do
  comando pronto, um `--dry-run` real para 22/10 achou o dia 21 sozinho e a prévia bateu com
  a seção de tarefas da página (201 linhas idênticas).
- **Ambiente (não corrigido):** o `.venv` está em Python 3.11, que lê o `.pth` do pacote
  editável na codificação do Windows; com o caminho acentuado (`Programação\…\Repositórios`),
  o `src` some do `sys.path` e `uv run notion-tasks` dá `ModuleNotFoundError`. O pytest não
  sente (`pythonpath = ["src"]`). Contorno usado: `PYTHONPATH=src`. Correção: recriar o
  `.venv` com Python 3.13 ou mais novo, que lê `.pth` em UTF-8.
- **Estado:** concluído. Em aberto com a pessoa: se tarefa sem check com todos os passos
  marcados (as duas da Zernio em 21/10) deve passar adiante.

### [2026-10-21] Scripts que viram módulo: o mapa do workspace

- **Pedido da pessoa:** verificar quais scripts do repositório podem virar módulo. Levantamento:
  `examples/coletar_mapa.py` + `gerar_arvore_html.py` (mapa do workspace) e
  `scripts/notion/criar_tarefas_de_rascunhos.py` + `verificar_…` (tarefas a partir de
  rascunhos). Ficam como script: os lotes únicos com dados no código (`scripts/notion/`
  datados e do monólito), `scripts/migracao/` (migração concluída), `scripts/empacotamento/`
  (build e CI), os demais `examples/` (documentação da biblioteca) e o `start_app.py`.
- **Defeito encontrado (pela leitura do código):** a opção "Mapear workspace" do menu rodava
  os dois exemplos por `subprocess`, mas o wheel não leva `examples/` (só o sdist). Instalado,
  `REPO_RAIZ` é o `site-packages`, então a opção chamava um arquivo inexistente.
- **Feito:** `services/mapa_workspace.py` (`coletar_mapa`, `montar_mapa`, `gerar_html`,
  `gravar_mapa`), movido sem mudar comportamento: mesma contagem por `consultar_database`
  (falha vira `-1`) e o mesmo HTML. O `mapear` ganhou `--saida` e `--html` (flags opcionais,
  reaproveitam a busca do resumo); o menu chama o serviço e grava na pasta atual. Os dois
  exemplos saíram.
- **Validação:** suíte inteira verde; `mapear --saida --html` no workspace real: 5.730 itens,
  118 databases todos contados, HTML de 1,35 MB, 143 s.
- **Observado e não mexido:** a opção "Rodar exemplo" do menu também roda `examples/` e tem o
  mesmo problema fora do checkout; como o propósito dela é demonstrar exemplos, ficou.
- **Estado:** concluído. Próximo: `criar_tarefas_de_rascunhos.py` vira `importar-tarefas`.

### [2026-10-21] Scripts que viram módulo: rascunhos de tarefas viram `importar-tarefas`

- **Pedido da pessoa:** a segunda conversão do levantamento. Decisões dela: formato
  **genérico** (`propriedades` conferidas pelo schema, `lote.json` com as comuns) e cabeçalho
  de sessão **no `.md`** (o módulo não inventa texto). O formato antigo (etapa, esforço,
  prioridade, tipo, repositório fixos) deixou de ser aceito.
- **Feito:** `domain/schema.problemas_de_valores` (extraída da biblioteca, que passou a usá-la),
  `domain/rascunhos_de_tarefas.py` (validar, `chave:x` vira link, arestas, rodadas, seção),
  `services/importacao_tarefas.py` (carregar, importar em etapas, conferir; chama os serviços
  do pacote em vez da CLI por `subprocess`), comando `importar-tarefas` e `notion.import_tasks`.
  `LoteIncompletoError`: etapa que falha em parte para o lote ali; rodar de novo completa.
  Os scripts `criar_`/`verificar_tarefas_de_rascunhos.py` e o teste deles saíram.
- **Defeito pego antes de usar:** a primeira versão tratava toda relação de mão única do
  próprio database como simétrica. O schema real do To Do List da HOME tem `Subtarefas` e
  `Tarefa principal`, do mesmo tipo de `Subtarefas relacionadas`; o `relacionar` grava a volta
  na mesma coluna, então ligar por `Subtarefas` faria A subtarefa de B e B de A. Correção: a
  de mão única só entra se o `lote.json` a declarar em `simetricas`; a de mão dupla segue
  livre; a de outro database vai em `propriedades`.
- **Validação:** suíte inteira verde; duas mutações conferidas (uma sobreviveu e o teste de
  conferência foi reforçado). `--dry-run` real no To Do List (2.056 linhas, 14 s): link de
  tarefa existente aceito e lido, a simétrica A↔B virou uma ligação, aviso de `chave:sumida`;
  e a recusa de `Subtarefas` com a mensagem que explica o caminho. Nada foi gravado no
  workspace: a escrita está coberta pelos testes com o workspace em memória.
- **Fora do repositório:** a skill "Anotações cruas viram tarefas" do Felixo AI Core ainda
  manda escrever um script na etapa 5; o caminho agora é o `importar-tarefas`.
- **Estado:** concluído.

### [2026-10-21] Python 3.10 sai do suporte

- **Contexto:** ao subir o trabalho do dia, a CI da `main` já estava vermelha desde 20/10 só no
  job `pacote`: o `pip-audit` acusava o `certifi 2026.10.18`. Atualizado o `certifi` (lock
  regenerado com o `uv 0.12.13` da CI, não com o `0.13.0` local, que mudaria o formato do
  lock), o passo seguinte, que antes nem rodava, acusou 8 CVEs no `pillow 12.3.0` do Python
  3.10. O `pillow 13.0.0`, que as corrige, exige Python 3.11: no 3.10 não havia correção.
- **Decisão da pessoa:** encerrar o 3.10 (fim do suporte oficial em outubro de 2026), em vez
  de tirar as imagens do 3.10 ou ignorar as CVEs.
- **Feito:** `requires-python >=3.11`, sem `typing_extensions` nem os ramos `tomli`;
  `PYTHON_MINIMO` em `core/constants.py` é o que o `doctor` e o Status do menu conferem, preso
  ao pyproject por teste; ruff mira `py311` (`datetime.UTC`); CI em 3.11–3.13, com o
  `pip-audit` do menor Python no 3.11 (ainda há `django 5.2` só abaixo do 3.12). O lock só
  perdeu as variantes do 3.10. Documentos datados (planos, specs, releases antigos) ficaram.
- **Estado:** concluído; a CI do push confirma.

### [2026-10-21] Subtarefas virou hierarquia de verdade (par de mão dupla)

- **Pedido da pessoa:** corrigir o `relacionar` com a coluna `Subtarefas`.
- **Correção do que eu tinha registrado:** a entrada do `importar-tarefas` dizia que o
  `relacionar` criava o ciclo ao gravar a volta na mesma coluna. **Errado no mecanismo.**
  Experimento controlado (2 tarefas temporárias, já na lixeira): gravar só
  `A.Subtarefas = [B]`, sem o `relacionar`, fez `B.Subtarefas` trazer A na hora; `Tarefa
  principal` ficou vazia. Quem espelha na mesma coluna é o **Notion**, para toda relação de
  mão única do próprio database (como já se vira em `Subtarefas relacionadas` em 17/08). O
  `relacionar` relê a outra ponta, encontra a volta e não grava nada — não tinha defeito.
- **Causa real:** `Subtarefas`/`Tarefa principal` (vindas do recurso de subitens e renomeadas
  pela normalização) eram duas `single_property` soltas, então nunca guardaram direção: 440
  de 441 e 904 de 904 ligações estavam nos dois sentidos da mesma coluna.
- **Feito:** o aviso do `schema` diz agora que a auto-referente de mão única é simétrica e não
  serve para hierarquia. `scripts/notion/migrar_hierarquia_subtarefas.py` renomeou as colunas
  para `(antiga)`, criou `Subtarefas` ↔ `Tarefa principal` de mão dupla e ligou as estrelas
  (o pai é o de grau maior): **523 subtarefas em 74 pais**. **51 pares ambíguos** (isolados ou
  em corrente) não foram migrados e seguem nas colunas antigas. Conferido por releitura: 523
  de 523 nos dois lados, 0 ciclos; rodar de novo não grava nada.
- **Tropeço na aplicação:** a releitura do schema logo depois de mudá-lo vinha atrasada (o
  `GET /databases` clássico levou mais de 30 s para mostrar a coluna criada pelo data source);
  a primeira execução renomeou as colunas e parou sem criar o par, com 0 pares e 0 escritas.
  O script passou a ler pelo data source e a esperar cada mudança aparecer.
- **Estado:** concluído. Pendente com a pessoa: decidir os 51 ambíguos e, depois de conferir,
  remover as colunas `(antiga)`.

### [2026-10-21] Pendências do dia: passos todos feitos contam como tarefa concluída

- **Decisão da pessoa** (o `TODO(human)` que ficou na cópia de trabalho): tarefa sem check, mas
  com todos os passos (`to_do` filhos) marcados, fica no dia de origem — era o caso das duas
  tarefas da Zernio em 21/10, que passaram adiante só porque a caixa ficou sem marca.
- **Armadilha coberta por teste:** tarefa sem nenhum passo (só "Dependência") continua
  dependendo só da caixa; `all([])` daria concluída a qualquer uma delas.
- **Estado:** concluído.
