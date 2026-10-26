# Distribuição da CLI única

> **Estado em 2026-10-07 (etapa 1 do monólito):** este repositório agora se constrói como
> **`felixo-notion-mcp` `0.6.0.dev0`**, mas **nada foi publicado com esse nome**. Os pacotes do
> PyPI (`notion-automacoes`, `notion-starter`, `notion-workspace-app`) e os binários nativos
> (`notion-automacoes-<alvo>`) seguem exatamente como estavam até a etapa 4. A seção
> "Transição para o pacote único" diz o que muda e quando; "Distribuição publicada" e as
> seguintes, até "Evidências da publicação", continuam sendo o contrato do que está no PyPI e
> nas Releases.

## Transição para o pacote único

O hub e os três módulos viraram um pacote só
([spec do monólito](superpowers/specs/2026-10-07-monolito-felixo-notion-mcp-design.md),
[arquitetura](ARQUITETURA.md)). Até a etapa 4, quem instala continua instalando os pacotes de
antes. O que está planejado para o corte:

| O que | Hoje (publicado) | Na etapa 4 |
| --- | --- | --- |
| CLI | `notion-automacoes` `0.5.0` | `0.6.0` de transição: sem código próprio, depende de `felixo-notion-mcp` e reexpõe `notion-automacoes` e `notion-tasks`, com aviso no stderr |
| Biblioteca | `notion-starter` `0.4.1` | `0.5.0`, só com o aviso de incorporação; o código continua igual para quem o importa |
| App | `notion-workspace-app` `0.3.1` | versão final que depende de `felixo-notion-mcp[app]`, com o aviso |
| Pacote novo | não publicado | `felixo-notion-mcp` `0.6.0`, por Trusted Publishing |
| Binários nativos | `notion-automacoes-<alvo>`, nas Releases do `notion-tasks-cli` | assets `felixo-notion-mcp-<alvo>` no repositório novo, mais a Release-ponte `v0.5.1` no `notion-tasks-cli` |

A ordem do corte importa: pacote novo e binários, depois os pacotes de transição, depois a
Release-ponte, e só então o arquivamento dos repositórios antigos. Arquivar antes da
Release-ponte trancaria os binários antigos na versão atual.

### O que este repositório já é

- Distribuição `felixo-notion-mcp`, import `felixo_notion_mcp`, versão `0.6.0.dev0`.
- Executáveis: `felixo-notion-mcp` (principal), `notion-tasks` (apelido permanente) e, de
  transição, `notion-automacoes`, `notion-automacoes-app` e `notion-automacoes-mcp`.
- Extras: `app` (Django, `questionary`, `rich`), `planilha` (`openpyxl`), `native` (PyInstaller)
  e `dev`. O extra do modo hospedado (`servidor`) é da etapa 3.
- O wheel leva a SPA compilada. Para construir e conferir:

```bash
uv sync --locked --all-extras
(cd front && npm ci && npm run build)
uv build
uv run python -m scripts.empacotamento.conferir_wheel dist/*.whl
```

- A CI (`.github/workflows/ci.yml`) roda ruff e a suíte em Ubuntu, Windows e macOS com Python
  3.11 a 3.13, lint e build do front, `npm audit`, `pip-audit` e a conferência do wheel.
  **Não há workflow de release nem de publicação aqui ainda**: quem publica até a etapa 4 são
  os repositórios dos módulos.

### O que não muda nesta etapa

- Os nomes de asset `notion-automacoes-<alvo>` e o `REPOSITORIO_GITHUB` do atualizador nativo
  (que continua apontando para as Releases do `notion-tasks-cli`).
- O comando `notion-tasks`, as linhas de comando em geral e o arquivo de perfis
  (`notion-tasks/.notion-workspaces.json` na pasta de configuração do usuário).

### Binário nativo a partir deste repositório

Os scripts do PyInstaller vivem em `scripts/empacotamento/` (`build_native.py`,
`native_entrypoint.py`, `smoke_native.py`). O build e o smoke foram exercitados **só em Linux
x64**; Windows e macOS (x64 e arm64) ficam para a CI de release da etapa 4. Para gerar um
executável de teste local:

```bash
uv run python -m scripts.empacotamento.build_native --target linux-x64 --version v0.6.0 --output dist/native
```

## Distribuição publicada

> **Contrato de 2026-09-08**, escrito quando a versão `0.3.0` foi publicada no PyPI (a CLI
> está hoje na `0.5.0`). Daqui até "Evidências da publicação" está o contrato para usar e
> verificar a distribuição sem exigir clone, Git ou Node na máquina de quem usa o produto.

## Instalação do usuário

O nome público da distribuição é `notion-automacoes`. A instalação completa é
uma única linha:

```bash
pipx install "notion-automacoes[app]"
# ou
uv tool install "notion-automacoes[app]"
```

O extra `app` instala Django, MCP e a aplicação local; a SPA React já vem
compilada dentro do wheel Python. Portanto, o usuário não precisa de checkout,
`pip install` de URL Git, `npm`, `node` ou `--break-system-packages`.

Verificação inicial, sem token:

```bash
notion-automacoes --version
notion-automacoes doctor
```

Configuração e uso:

```bash
notion-automacoes auth adicionar pessoal --token ntn_... --database <id> --ativar
notion-automacoes tasks listar
notion-automacoes app start
notion-automacoes mcp start
notion-automacoes update
```

O comando histórico continua válido:

```bash
notion-tasks listar
```

Perfis ficam na pasta de configuração do usuário e não são removidos por
upgrade ou desinstalação do pacote. A CLI nunca imprime o token. Para conferir
uma instalação sem chamar operações de escrita:

```bash
notion-automacoes --version
notion-automacoes --help
notion-automacoes doctor
notion-automacoes auth listar
```

## Contrato dos pacotes

Os três projetos usam a versão publicada coerente `0.3.0`:

1. `notion-starter` — biblioteca base publicada primeiro;
2. `notion-workspace-app` — API Django, MCP, launcher e bundle da SPA;
3. `notion-automacoes` — fachada CLI e alias compatível `notion-tasks`.

| Pacote | Papel | Publicação |
| --- | --- | --- |
| `notion-starter` | cliente Notion e serviços compartilhados | [PyPI](https://pypi.org/project/notion-starter/) |
| `notion-automacoes` | CLI única e perfis | [PyPI](https://pypi.org/project/notion-automacoes/) |
| `notion-workspace-app` | app local, API, SPA e MCP | [PyPI](https://pypi.org/project/notion-workspace-app/) |

O CLI depende de `notion-starter>=0.3.0,<0.4.0`, sem `Requires-Dist` apontando
para Git. O app declara runtime em `pyproject.toml`; ferramentas de teste ficam
no extra `dev`. O extra `app` do CLI é opcional para permitir a publicação
sequencial dos pacotes, mas é a instalação recomendada para o produto completo.

## Release Python, binários nativos e smoke

Cada repositório de módulo tem um workflow `release.yml` (neste repositório unificado ele
ainda não existe; chega na etapa 4) que:

- constrói sdist e wheel;
- valida metadados com `twine check`;
- instala o wheel em Ubuntu, Windows e macOS, nos Python 3.11 e 3.13;
- roda `--version`, `--help`, `doctor` e os imports/entry points pertinentes;
- publica com Trusted Publishing do GitHub Actions, sem token PyPI no repositório.

No app, o job de build roda `npm ci` e `npm run build` antes de `python -m build`.
O resultado entra em `server/static/frontend/` no wheel, mas o artefato gerado
continua ignorado no checkout para não virar fonte paralela.

O primeiro release não inclui binários nativos: o contrato publicado continua
Python 3.10+ com `pipx`/`uv`. A decisão posterior de distribuição já definiu o
contrato do mecanismo nativo abaixo; os binários só entram quando as tasks de
empacotamento PyInstaller e assinatura concluírem seus artefatos.

## Contrato de binários nativos, atualização e rollback

O mecanismo nasceu no `notion-tasks-cli` (`cli/atualizacao_nativa.py`) e hoje vive neste
repositório em `src/felixo_notion_mcp/api/cli/atualizacao_nativa.py`, sem alterar o
pacote Python `0.3.0`. A Release
estável consulta a API de Releases do GitHub e só considera o alvo detectado
na máquina:

| Alvo | Asset do executável | Asset do checksum |
| --- | --- | --- |
| Windows x64 | `notion-automacoes-windows-x64.exe` | `notion-automacoes-windows-x64.exe.sha256` |
| macOS Intel | `notion-automacoes-macos-x64` | `notion-automacoes-macos-x64.sha256` |
| macOS Apple Silicon | `notion-automacoes-macos-arm64` | `notion-automacoes-macos-arm64.sha256` |
| Linux x64 | `notion-automacoes-linux-x64` | `notion-automacoes-linux-x64.sha256` |

O updater rejeita tags inválidas, drafts e pré-releases, exige o par de assets
do alvo, baixa para o mesmo diretório do executável e confere SHA-256 antes de
qualquer troca. Em macOS/Linux a troca usa `os.replace` e guarda a versão
anterior em `<executável>.previous`, restaurando-a se a operação falhar. No
Windows o próprio executável é reiniciado como helper: ele espera o processo pai
terminar, faz a mesma troca e relança os argumentos originais. Duas regras
nascem de medições no Windows (21/10/2026):

- **A troca repete.** Renomear um executável em uso falha de vez em quando com
  `WinError 32` (violação de compartilhamento), mesmo muito depois de o processo
  iniciar, e passa na tentativa seguinte. O helper repete por até 30 s, só para
  `WinError 5` e `32`, antes de desistir e restaurar o original.
- **O relançamento é uma instância independente.** O helper é um onefile do
  PyInstaller e roda sem console. Sem `PYINSTALLER_RESET_ENVIRONMENT=1`, o
  executável novo, filho dele, herdava a pasta de extração do helper
  (`_PYI_APPLICATION_HOME_DIR`) e morria quando o helper saía: o comando original
  se perdia sem erro.

Quando a troca automática acontece em macOS/Linux, o comando que a disparou
**não continua no processo antigo**: o executável onefile do PyInstaller lê
módulos do próprio arquivo sob demanda e, depois do `os.replace`, um import
tardio leria o arquivo novo com os offsets do antigo (`Error -3 while
decompressing data`). Por isso o processo antigo relança o executável novo com
os mesmos argumentos e `PYINSTALLER_RESET_ENVIRONMENT=1`, e só repassa o código
de saída. Medido em 02/10/2026 no Linux x64: a 0.4.1 publicada falha assim no
primeiro comando após o auto-update; o binário corrigido conclui o comando já
na 0.5.0.

Em um binário PyInstaller, comandos normais verificam a Release
automaticamente (no máximo uma vez por 24 horas, com cache local, depois de uma
consulta bem-sucedida; consulta que falhou vale 15 minutos, troca agendada no
Windows 30 minutos e troca que falhou 6 horas, para a atualização não ficar
escondida por um dia). A opção
`NOTION_AUTOMACOES_NO_UPDATE=1` desabilita a verificação automática. O comando
`notion-automacoes update --dry-run` mostra o plano sem baixar; em uma instalação
Python, `update` só imprime a receita e não executa nada. Enquanto o nome
`felixo-notion-mcp` não estiver publicado no PyPI (etapa 4), não há comando
`pipx`, `uv` ou `pip` que atualize a distribuição por nome: no checkout a receita é
`git pull` e `uv sync --all-extras`, e fora dele a mensagem diz que a distribuição
ainda não está publicada e como instalar a partir do código-fonte. No JSON, `comando`
é `null` e a receita vem em `instrucao`.

O rollback de produto é deliberadamente manual: cada publicação deve manter no
GitHub pelo menos as duas Releases estáveis mais recentes com seus quatro pares
de assets. Para reverter, escolha a Release anterior, baixe o asset do sistema,
confira a assinatura e o `.sha256`, encerre o programa e substitua o executável
pela versão escolhida. O updater automático nunca faz downgrade; o backup
`.previous` é uma recuperação local adicional, não substitui a Release
anterior.

### Como validar o auto-update e o rollback

```bash
uv run python -m scripts.empacotamento.validar_atualizacao_nativa --saida relatorio.md
# um build deste checkout como binário anterior (o comando original tem de concluir):
uv run python -m scripts.empacotamento.build_native --target linux-x64 --version v0.4.9 --output dist/native
uv run python -m scripts.empacotamento.validar_atualizacao_nativa   --de-binario dist/native/notion-automacoes-linux-x64 --de-versao v0.4.9
```

O validador faz, numa pasta descartável e com perfis, cache e `PATH` isolados, o que
uma pessoa faz: `update --dry-run`, um comando normal que dispara o auto-update, a
conferência da troca e do `.previous`, o relançamento do comando original, o
rollback pelo `.previous` e pela Release anterior (SHA-256 conferido), tudo isso
também com outro processo do binário vivo (o caminho "arquivo em uso") e com uma
segunda atualização com o `.previous` em uso. O workflow manual
`validar-atualizacao-nativa.yml` roda isso em Linux x64, macOS Intel, macOS Apple
Silicon e Windows, com as Releases publicadas e com um build do checkout. Só lê as
Releases: não publica nada.

### Estado da aceitação física (21/10/2026)

As Releases nativas `v0.4.0`, `v0.4.1` e `v0.5.0` estão publicadas com os quatro
pares de assets, **sem assinatura**; nada abaixo vale para binário assinado. O ciclo
completo acima rodou em VMs novas do GitHub, duas a três execuções por runner:

| Alvo | Runner | Releases publicadas | Build do checkout |
| --- | --- | --- | --- |
| Linux x64 | Ubuntu 24.04 (glibc 2.39) | 2 de 2 ok | 2 de 2 ok |
| macOS Intel | macOS 15.7 | 2 de 2 ok | 2 de 2 ok |
| macOS Apple Silicon | macOS 14.8 | 2 de 2 ok | 2 de 2 ok |
| macOS Apple Silicon | macOS 15 | 1 de 3 ok (2 execuções sem cota da API) | **não validado**: 3 execuções sem cota da API |
| Windows x64 | Server 2022 | 2 de 2 ok | 1 de 2 ok; na outra tudo ok até o validador cair (defeito dele, corrigido) |
| Windows x64 | Server 2025 | 2 de 3 ok; em 1 a troca não foi aplicada | 2 de 3 ok; na outra só a consulta `--dry-run` falhou, por rede |

"Ok" quer dizer: `--dry-run`, update disparado por um comando normal, troca, backup
`.previous`, rollback pelo `.previous` e pela Release anterior, e o mesmo com outro
processo do binário vivo. No macOS e no Linux, "build do checkout" é um binário
construído do `main` com a versão `0.4.9`, atualizado para a `v0.5.0` publicada.

Diferenças entre as duas colunas, todas medidas:

- Nas Releases publicadas o update é aplicado e o rollback funciona, mas o **comando
  que disparou o update se perde**: em macOS e Linux sai com `Error -3 while
  decompressing data` (código 2); no Windows o helper o relança e ele morre, numa
  corrida com a limpeza da pasta do helper: o comando se perdeu em 1 de 6 ciclos nos
  runners do GitHub e em 4 de 4 numa máquina Windows 11 de uso diário. No build do
  checkout o comando original concluiu em todos os ciclos em que o update rodou.
- No Windows a troca do helper publicado, que não repete, pode nem ser aplicada
  (executável e `.previous` intactos, nenhum aviso): 1 vez em 5 execuções nos
  runners; na máquina Windows 11, 3 vezes em 7 ciclos sem repetição (1 de 4 com os
  binários publicados e 2 de 3 com o build de 50 MB do checkout, antes da correção).
  O build do checkout, com a repetição, não perdeu nenhuma troca nos runners.
- Com outro processo do binário vivo, a troca é aplicada e esse processo continua
  vivo. Uma **segunda** atualização com o `.previous` ainda em uso por ele nem
  sempre é aplicada no Windows: o executável fica íntegro, mas nada avisa.

Limites: os runners trazem Python (no macOS e no Linux o `PATH` do binário ainda
enxerga `/usr/bin/python3`), então o que se provou é a execução com `PATH` mínimo e
ambiente vazio, não uma máquina sem Python. Ficam fora a assinatura
Authenticode/notarização e o aviso do SmartScreen e do Gatekeeper, que só aparecem
numa sessão com tela. A API anônima de Releases limita 60 consultas por hora e por
IP: num runner esgotado, o updater (que não envia token) e o validador veem `403`, e o
relatório mostra isso em vez de um resultado falso.

## Empacotamento PyInstaller e publicação controlada

O workflow `native-release.yml` do `notion-tasks-cli` constrói os quatro assets
com os nomes estáveis acima, gera um `.sha256` irmão e roda um smoke diretamente
no executável. O builder recebe a tag (`v0.4.0` ou posterior), portanto a versão
embutida no binário não depende do fallback da instalação Python.

O workflow publica os binários primeiro como artefatos da execução. A anexação à
GitHub Release ocorre apenas por `workflow_dispatch`, com `publicar_release=true`
e aprovação do ambiente protegido `native-release`. Essa barreira é intencional:
o processo de assinatura Windows Authenticode e macOS notarization deve concluir
antes da aprovação. A task de empacotamento não altera a Release `0.3.0`.

Para quem usa, a instalação nativa será: baixar o asset da sua plataforma na
Release estável, validar a assinatura e o `.sha256`, conceder permissão de
execução no macOS/Linux quando necessário e colocar o executável no `PATH`. O
binário roda sem Python instalado; o smoke do workflow executa a própria cópia
produzida, mas a aceitação final em máquinas limpas/VMs por plataforma continua
pendente até haver os assets assinados.

## Evidências da publicação

Os workflows de release foram executados a partir da tag `v0.3.0` e passaram nos
três repositórios:

- [`notion-starter` — release 0.3.0](https://github.com/Felipe-Alcantara/notion-starter/actions/runs/33908422673)
- [`notion-workspace-app` — release 0.3.0](https://github.com/Felipe-Alcantara/notion-workspace-app/actions/runs/33908594676)
- [`notion-tasks-cli` — release 0.3.0](https://github.com/Felipe-Alcantara/notion-tasks-cli/actions/runs/33908824167)

Cada workflow constrói wheel e sdist, executa `twine check`, faz smoke em
Ubuntu, Windows e macOS com Python 3.10 e 3.13 e publica via Trusted Publishing.
No app, a SPA é compilada antes do empacotamento e o wheel a serve sem
Node/npm.

## Titularidade e limites

Os metadados dos três pacotes e os respectivos arquivos `LICENSE` identificam
`Felipe Alcantara` como titular. Colaboradores podem contribuir com código e
documentação sem alterar essa titularidade. O primeiro release é Python puro;
binários nativos continuam fora do contrato até uma decisão própria sobre
assinatura, atualização, rollback e manutenção.

## Desenvolvimento

Para alterar o código, use um checkout deste repositório; não há mais módulos para
clonar:

```bash
uv sync --locked --all-extras
uv run felixo-notion-mcp doctor
```

O `doctor` mostra de onde o pacote está sendo importado e se é o checkout editável (só
informa; não avisa). Depois, edite a camada correspondente em `src/felixo_notion_mcp/`,
rode o gate e faça commit. O fluxo detalhado está em [`AGENTS.md`](../AGENTS.md) e em
[`QUALIDADE.md`](QUALIDADE.md).
