# 🔄 Integrações — GitHub e ingestão de arquivos

> **O que é**: referência operacional das Fases 3 e 4 do projeto. Explica como
> coletar arquivos locais, consultar repositórios públicos/privados do GitHub e
> sincronizar esses dados com páginas e tarefas no Notion.

---

## 📋 Índice

- [Arquitetura](#️-arquitetura)
- [Configuração](#️-configuração)
- [Schemas esperados no Notion](#️-schemas-esperados-no-notion)
- [Conector GitHub](#-conector-github)
- [Ingestão de arquivos](#-ingestão-de-arquivos)
- [Sincronização GitHub → Notion](#-sincronização-github--notion)
- [Resiliência e segurança](#️-resiliência-e-segurança)
- [Limites atuais](#️-limites-atuais)

---

## 🏛️ Arquitetura

As responsabilidades permanecem separadas:

- `server/integrations/github.py` encapsula HTTP, token, retry, paginação,
  rate limit e normalização em `RepoInfo`.
- `server/services/ingestao.py` define o protocolo `Fonte` e coordena
  criação/atualização de páginas por `Origem`.
- `server/services/sincronizar_github.py` mapeia repositórios para páginas de
  projeto e usa a `TaskList` existente para criar tarefas sem duplicá-las.

Novas origens implementam `Fonte.coletar()` e produzem `ItemColetado`; o núcleo
de ingestão não precisa ser modificado.

---

## ⚙️ Configuração

As credenciais ficam somente no ambiente ou no `.env` local:

```env
# Opcional para repositórios públicos; necessário para privados.
GITHUB_TOKEN=

# Database que recebe as páginas de projetos.
NOTION_PROJECTS_DATABASE_ID=

# Database de tarefas usado pela TaskList.
NOTION_DATABASE_ID=
```

O token do GitHub deve ter apenas o acesso necessário. Tokens fine-grained são
preferíveis; habilite leitura de repositórios privados somente quando esse
comportamento for realmente usado.

---

## 🗃️ Schemas esperados no Notion

### Database de ingestão

| Propriedade | Tipo |
|---|---|
| `Nome` | title |
| `Fonte` | select |
| `Descrição` | rich_text |
| `Origem` | rich_text |

`Origem` é a chave de idempotência: se já existir uma página com o mesmo valor,
a ingestão atualiza essa página em vez de criar outra.

### Database de projetos GitHub

| Propriedade | Tipo |
|---|---|
| `Nome` | title |
| `Descrição` | rich_text |
| `URL` | url |
| `Homepage` | url |
| `Linguagem` | select |
| `Tópicos` | multi_select |
| `Estrelas` | number |
| `Forks` | number |
| `Privado` | checkbox |
| `Atualizado em` | date |

Os nomes podem ser alterados com `CamposProjeto`, sem modificar o caso de uso.
O database de tarefas segue `CamposTarefa`, documentado no contrato principal.

---

## 🐙 Conector GitHub

```python
from integrations.github import GitHubClient

github = GitHubClient()
repos = github.listar_repos("usuario")
detalhes = github.detalhar_repo("usuario/repositorio")
```

`listar_repos()` sempre consulta os repositórios públicos. Quando existe token,
o cliente identifica a conta autenticada e inclui privados somente se ela for a
mesma conta solicitada. Resultados públicos e privados são deduplicados.

`detalhar_repo()` acrescenta o mapa de linguagens e o README em texto; a ausência
de README é aceita e retorna `None`.

---

## 📁 Ingestão de arquivos

```python
from services.ingestao import FonteArquivos, ingerir

fonte = FonteArquivos(
    "./documentos",
    extensoes=[".md", ".txt", ".py"],
    recursivo=True,
)
resultado = ingerir(fonte)
```

A fonte:

- usa caminhos relativos como `Origem`, sem publicar o caminho absoluto local;
- ignora links simbólicos;
- lê apenas uma prévia limitada de extensões textuais conhecidas;
- trata arquivos binários somente por metadados;
- permite filtrar extensões e desativar a busca recursiva.

O resultado informa quantos itens foram processados, criados, atualizados ou
rejeitados. Uma falha pontual não interrompe o restante do lote.

---

## 🔁 Sincronização GitHub → Notion

```python
from services.sincronizar_github import sincronizar

resumo = sincronizar("usuario", status_tarefa="Backlog")
```

Para cada repositório:

1. a página de projeto é localizada pela propriedade `URL`;
2. a página existente é atualizada ou uma nova é criada;
3. a tarefa `Revisar repo: <nome>` é comparada com a `TaskList`;
4. a tarefa só é criada quando ainda não existe.

`ResumoSync` separa páginas criadas/atualizadas, tarefas criadas/existentes e
erros do lote.

---

## 🛡️ Resiliência e segurança

- Retry com backoff ocorre somente para falhas de rede, HTTP 5xx, HTTP 429 e
  HTTP 403 identificado como rate limit.
- Um HTTP 403 de permissão não é repetido automaticamente.
- `Retry-After` é respeitado quando fornecido.
- Headers de rate limit ficam disponíveis em `GitHubAPIError.rate_limit`.
- Entradas de usuário e `owner/repo` são validadas antes de montar a URL.
- Tokens nunca entram em retorno, log, documentação ou mensagem de commit.
- Testes usam mocks/fakes; nenhuma suíte depende de GitHub ou Notion reais.

---

## ⚠️ Limites atuais

- A ingestão cria e atualiza propriedades; envio de blocos/arquivos binários
  para o corpo de páginas pode ser adicionado por quem precisar desse fluxo.
- A sincronização é em lote e síncrona. Filas e checkpoints fazem sentido
  apenas quando volume ou concorrência justificarem a complexidade.
- O limite operacional padrão é 500 repositórios por coleta, configurável no
  `GitHubClient`.
