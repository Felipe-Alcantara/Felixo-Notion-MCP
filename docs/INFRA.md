# 🏗️ INFRA — Servidor, configuração e deploy

> **Onde está o código (etapa 1 do monólito, 2026-10-07):** o servidor vive em
> `src/felixo_notion_mcp/`: o projeto Django e as rotas REST em `api/http/`, o estado
> operacional em `repositories/operations/` e a configuração em `core/config.py`. Os
> caminhos `server/` abaixo são os do antigo `notion-workspace-app`; a correspondência
> está na tabela origem → destino de [ARQUITETURA.md](ARQUITETURA.md). `front/` fica
> na raiz do repositório. Para uso sem checkout, instale
> [`notion-automacoes[app]`](DISTRIBUICAO.md).

> **O que é**: como o servidor deste projeto roda **local** e como é **hospedado**.
> Cobre a estrutura de pastas do servidor, a configuração por ambiente, o estado
> operacional em SQLite e notas de deploy. É a entrega do **Agente Infra**
> ([AGENTES.md](AGENTES.md) → *Agente Infra*); a visão geral está no [PLANO.md](PLANO.md).

---

## 🧱 Stack

- **Django** (5+; testado no 6.x) como backend, conforme a decisão fixada no
  [PLANO.md](PLANO.md) (*Decisões fixadas → Stack do servidor*).
- **SQLite** apenas para **estado operacional** (jobs, locks). O **conteúdo**
  (tarefas, páginas) continua no **Notion**, a fonte da verdade.
- Sem dependências extras além do Django: a leitura de `.env` e da config é própria
  (sem `python-dotenv`), no mesmo espírito enxuto do `notion_starter`.

---

## 📁 Estrutura do servidor (`server/`)

Por camadas, conforme a arquitetura-alvo do [PLANO.md](PLANO.md):

```text
server/
├── manage.py            # CLI do Django (insere server/ no path)
├── config/              # projeto Django: settings, urls, wsgi, asgi
├── core/                # config (ambiente), token — sem HTTP, sem regra de negócio
│   └── config.py        # carrega .env + resolve Config (SECRET_KEY, DEBUG, token…)
├── integrations/        # adaptadores externos
│   └── notion.py        # fábrica fina sobre o notion_starter (cliente/TaskList)
├── services/            # casos de uso (regra de negócio) — Agente Backend preenche
├── api/                 # borda HTTP (rotas REST) — Agente Backend preenche
│   ├── urls.py          # /api/health (pronto); /api/tarefas (Backend)
│   └── views.py         # views finas: parse, validação, delegação
└── operations/          # estado operacional em SQLite (jobs/locks) + migrações
```

**Fronteira de camadas** (sagrada, ver [AGENTES.md](AGENTES.md)): `api` não tem regra
de negócio; `services` não conhece HTTP; o mundo externo fica isolado em `integrations`;
`core` é só configuração. O `notion_starter` (em `src/`) é a base e é consumido via
`integrations.notion`.

---

## ⚙️ Configuração por ambiente

Nenhum segredo no repositório. Tudo vem de variáveis de ambiente (ou de um `.env`
local, ignorado pelo git). Lidas por `core/config.py`:

| Variável | Para quê | Padrão |
|---|---|---|
| `NOTION_TOKEN` | Token da integração do Notion | — (obrigatório para falar com o Notion) |
| `NOTION_DATABASE_ID` | Database de tarefas padrão | — (opcional; pode vir por chamada) |
| `DJANGO_SECRET_KEY` | Chave secreta do Django | chave de **dev** se `DEBUG`; **exigida** se `DEBUG=0` |
| `DJANGO_DEBUG` | Liga o modo debug (`1`/`true`) | `0` (produção por padrão) |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos (separados por vírgula) | `localhost,127.0.0.1,[::1]`, com ou sem debug (`*` em debug deixava um site qualquer falar com a API por DNS rebinding) |
| `OPERATIONAL_DB_PATH` | Caminho do SQLite operacional | `operacional.sqlite3` na raiz |

> **Guarda de produção**: com `DJANGO_DEBUG=0` e sem `DJANGO_SECRET_KEY`, o servidor
> **recusa subir** (em vez de usar uma chave insegura). Defina a chave no deploy.

---

## ▶️ Rodar local

Pelo menu (porta de entrada única):

```bash
python start_app.py     # → "🚀 Iniciar tudo"
```

A opção principal usa `127.0.0.1:8000` para a API Django e `127.0.0.1:5173`
para a SPA React/Vite. Ela pergunta antes de instalar o extra `app` (o Django)
quando falta, e só instala num checkout; valida o Node do front (Vite exige
Node 20.19+ ou 22.12+), instala `front/node_modules` quando faltar, aplica as
migrações e abre o navegador no front React automaticamente. O menu principal permanece disponível; `Ctrl+C` encerra somente
o app no terminal dedicado. A opção “Subir API Django” permanece para quem quiser
subir só a API ou escolher outro `host:porta`.

Manualmente:

```bash
uv sync --locked --all-extras
DJANGO_DEBUG=1 uv run python -m felixo_notion_mcp.api.http.manage migrate
DJANGO_DEBUG=1 uv run python -m felixo_notion_mcp.api.http.manage runserver 127.0.0.1:8000

cd front
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Smoke test: `GET http://127.0.0.1:8000/api/health` → `{"status": "ok", ...}`.

---

## 🚀 Deploy / hospedagem

Decisão de alcance: **uso pessoal, porém hospedado** (ver [ESCALA.md](ESCALA.md) e
[SAAS.md](SAAS.md)). Sem fixar provedor à força; o servidor é um Django WSGI/ASGI comum.

Checklist mínimo de produção:

- [ ] `DJANGO_SECRET_KEY` definido (longo e aleatório), fora do repo.
- [ ] `DJANGO_DEBUG=0` e `DJANGO_ALLOWED_HOSTS` com o domínio real.
- [ ] `NOTION_TOKEN` (e `NOTION_DATABASE_ID`, se usado) no ambiente do servidor.
- [ ] Servir via `gunicorn config.wsgi` (ou um ASGI como `uvicorn config.asgi`),
      a partir de `server/`, atrás de um proxy reverso (TLS).
- [ ] `python manage.py migrate` no deploy. Para o front do Ciclo 2 (SPA React + Vite),
      o build é `vite build` em `front/`, servindo o `dist/` por um proxy/CDN ou
      estático do servidor (não é `collectstatic` de template Django).
- [ ] `OPERATIONAL_DB_PATH` apontando para um volume persistente (o SQLite não some
      a cada deploy).

> Quando a concorrência crescer, a evolução natural (fila de jobs, workers, Postgres)
> está descrita em [ESCALA.md](ESCALA.md). O SQLite operacional aqui é o ponto de
> partida deliberado para uso pessoal/baixa concorrência.
