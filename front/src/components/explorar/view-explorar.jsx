import { useMemo, useState } from 'react'
import { AlertCircle, Database, ExternalLink, Loader2, Search } from 'lucide-react'
import { useExploracao } from '../../hooks/use-exploracao'

/**
 * Aba "Explorar" — read-only: escolhe um database visível e mostra suas
 * colunas/linhas numa tabela genérica que se adapta a qualquer schema.
 */
export function ViewExplorar() {
  const {
    databases,
    carregandoLista,
    erroLista,
    selecionado,
    descricao,
    carregandoDescricao,
    erroDescricao,
    selecionar,
  } = useExploracao()
  const [busca, setBusca] = useState('')

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase()
    if (!q) return databases
    return databases.filter((d) => d.titulo.toLowerCase().includes(q))
  }, [databases, busca])

  return (
    <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
      <aside className="flex flex-col gap-3">
        <div className="relative">
          <Search
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500"
            aria-hidden="true"
          />
          <input
            type="search"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder="Buscar database..."
            className="w-full rounded-2xl border border-white/10 bg-zinc-900/60 py-2 pl-9 pr-3 text-sm text-white placeholder:text-zinc-500 focus-visible:outline-2 focus-visible:outline-brand-500"
          />
        </div>

        {erroLista && <Erro mensagem={erroLista} />}

        <div className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto pr-1">
          {carregandoLista ? (
            <Carregando texto="Carregando databases..." />
          ) : filtrados.length === 0 ? (
            <p className="px-2 py-4 text-sm text-zinc-500">Nenhum database encontrado.</p>
          ) : (
            filtrados.map((db) => (
              <button
                key={db.id}
                type="button"
                onClick={() => selecionar(db)}
                className={[
                  'flex items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm transition-colors',
                  selecionado?.id === db.id
                    ? 'border-brand-500/40 bg-brand-500/10 text-white'
                    : 'border-transparent text-zinc-300 hover:bg-white/5',
                ].join(' ')}
              >
                <Database size={15} className="flex-shrink-0 text-brand-400" aria-hidden="true" />
                <span className="truncate">{db.titulo}</span>
              </button>
            ))
          )}
        </div>
      </aside>

      <section aria-label="Conteúdo do database" className="min-w-0">
        {!selecionado ? (
          <EstadoInicial />
        ) : carregandoDescricao ? (
          <Carregando texto={`Lendo "${selecionado.titulo}"...`} />
        ) : erroDescricao ? (
          <Erro mensagem={erroDescricao} />
        ) : (
          <TabelaGenerica titulo={selecionado.titulo} descricao={descricao} />
        )}
      </section>
    </div>
  )
}

function TabelaGenerica({ titulo, descricao }) {
  const colunas = descricao?.colunas ?? []
  const linhas = descricao?.linhas ?? []

  if (colunas.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-sm text-zinc-400">
        Este database não tem colunas acessíveis à integração. Compartilhe-o com a integração no
        Notion para liberar a leitura.
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">{titulo}</h2>
        <span className="text-xs text-zinc-500">
          {linhas.length} linha{linhas.length === 1 ? '' : 's'} · {colunas.length} colunas
        </span>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-white/10">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-zinc-900/60">
              {colunas.map((col) => (
                <th
                  key={col.nome}
                  className="whitespace-nowrap px-3 py-2 text-left font-medium text-zinc-300"
                  title={col.tipo}
                >
                  {col.nome}
                </th>
              ))}
              <th className="px-3 py-2" aria-label="Abrir no Notion" />
            </tr>
          </thead>
          <tbody>
            {linhas.length === 0 ? (
              <tr>
                <td
                  colSpan={colunas.length + 1}
                  className="px-3 py-6 text-center text-zinc-500"
                >
                  Database sem linhas.
                </td>
              </tr>
            ) : (
              linhas.map((linha) => (
                <tr key={linha.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                  {colunas.map((col, idx) => (
                    <td
                      key={col.nome}
                      className={[
                        'px-3 py-2 align-top',
                        idx === 0 ? 'font-medium text-white' : 'text-zinc-300',
                      ].join(' ')}
                    >
                      {linha.valores?.[col.nome] || <span className="text-zinc-600">—</span>}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right">
                    {linha.url && (
                      <a
                        href={linha.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex text-zinc-500 hover:text-brand-400"
                        aria-label="Abrir no Notion"
                      >
                        <ExternalLink size={14} aria-hidden="true" />
                      </a>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function EstadoInicial() {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-white/10 p-8 text-center">
      <Database size={28} className="text-zinc-600" aria-hidden="true" />
      <p className="max-w-md text-sm text-zinc-400">
        Escolha um database à esquerda para ver suas colunas e linhas. Funciona com qualquer
        database do seu Notion — não só a todolist.
      </p>
    </div>
  )
}

function Carregando({ texto }) {
  return (
    <div className="flex items-center gap-3 px-2 py-6 text-sm text-zinc-400">
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
      {texto}
    </div>
  )
}

function Erro({ mensagem }) {
  return (
    <div
      className="flex items-start gap-3 rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-100"
      role="alert"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
      <span>{mensagem}</span>
    </div>
  )
}
