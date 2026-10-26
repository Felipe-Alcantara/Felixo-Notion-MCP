import { useMemo, useState } from 'react'
import { AlertCircle, ExternalLink, Loader2, Plus, RefreshCw } from 'lucide-react'
import { Button } from '../ui/button'
import { Filtros } from './filtros'
import { TarefaFormModal } from './tarefa-form'
import { ViewGrade } from './view-grade'
import { ViewKanban } from './view-kanban'
import { ViewLista } from './view-lista'
import { useDatabaseAtual } from '../../hooks/use-database-atual'
import { useOpcoes } from '../../hooks/use-opcoes'
import { useTarefas } from '../../hooks/use-tarefas'

const STORAGE_KEY = 'notion-tarefas-ui-v1'

const DEFAULT_UI_STATE = {
  busca: '',
  statusFiltro: '',
  duracaoFiltro: '',
  areaFiltro: '',
  ordenacao: 'status',
  view: 'grade',
}

function carregarEstadoInicial() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? { ...DEFAULT_UI_STATE, ...JSON.parse(raw) } : DEFAULT_UI_STATE
  } catch {
    return DEFAULT_UI_STATE
  }
}

function salvarEstado(estado) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(estado))
  } catch {
    // LocalStorage pode estar indisponivel; a UI continua funcional.
  }
}

function normalizarTexto(valor) {
  return String(valor ?? '')
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
}

function compararPorPrazo(a, b) {
  const prazoA = a.prazo ? new Date(a.prazo).getTime() : Number.POSITIVE_INFINITY
  const prazoB = b.prazo ? new Date(b.prazo).getTime() : Number.POSITIVE_INFINITY
  return prazoA - prazoB || a.nome.localeCompare(b.nome, 'pt-BR')
}

function ordenarTarefas(tarefas, ordenacao) {
  const copia = [...tarefas]
  if (ordenacao === 'nome') {
    return copia.sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'))
  }
  if (ordenacao === 'nome-desc') {
    return copia.sort((a, b) => b.nome.localeCompare(a.nome, 'pt-BR'))
  }
  if (ordenacao === 'prazo') {
    return copia.sort(compararPorPrazo)
  }
  return copia.sort(
    (a, b) =>
      String(a.status ?? '').localeCompare(String(b.status ?? ''), 'pt-BR') ||
      a.nome.localeCompare(b.nome, 'pt-BR'),
  )
}

/**
 * App de tarefas (todolist principal). Mantido intacto como tela padrão; só foi
 * extraído de App.jsx para conviver com a aba "Explorar".
 */
export function PainelTarefas() {
  const [uiState, setUiState] = useState(carregarEstadoInicial)
  const [modalAberto, setModalAberto] = useState(false)
  const [tarefaSelecionada, setTarefaSelecionada] = useState(null)
  const { tarefas, carregando, erro, carregar, criar, editar } = useTarefas({
    status: uiState.statusFiltro,
    duracao: uiState.duracaoFiltro,
    area: uiState.areaFiltro,
  })
  const { opcoes, erro: erroOpcoes } = useOpcoes()
  const { database, erro: erroDatabase } = useDatabaseAtual()

  const atualizarUiState = (campo, valor) => {
    setUiState((atual) => {
      const proximo = { ...atual, [campo]: valor }
      salvarEstado(proximo)
      return proximo
    })
  }

  const tarefasFiltradas = useMemo(() => {
    const busca = normalizarTexto(uiState.busca)
    const filtradas = tarefas.filter((tarefa) => {
      const texto = normalizarTexto(
        [tarefa.nome, tarefa.status, tarefa.duracao, ...(tarefa.areas_nomes ?? [])].join(' '),
      )
      const bateBusca = !busca || texto.includes(busca)
      const bateStatus = !uiState.statusFiltro || tarefa.status === uiState.statusFiltro
      const bateDuracao = !uiState.duracaoFiltro || tarefa.duracao === uiState.duracaoFiltro
      const bateArea = !uiState.areaFiltro || (tarefa.areas ?? []).includes(uiState.areaFiltro)
      return bateBusca && bateStatus && bateDuracao && bateArea
    })
    return ordenarTarefas(filtradas, uiState.ordenacao)
  }, [tarefas, uiState])

  const abrirCriacao = () => {
    setTarefaSelecionada(null)
    setModalAberto(true)
  }

  const abrirEdicao = (tarefa) => {
    setTarefaSelecionada(tarefa)
    setModalAberto(true)
  }

  const salvarTarefa = async (body) => {
    if (tarefaSelecionada) {
      return editar(tarefaSelecionada.id, body)
    }
    return criar(body)
  }

  const limparFiltros = () => {
    const proximo = { ...uiState, busca: '', statusFiltro: '', duracaoFiltro: '', areaFiltro: '' }
    setUiState(proximo)
    salvarEstado(proximo)
  }

  const resumo = {
    total: tarefas.length,
    visiveis: tarefasFiltradas.length,
    abertas: tarefas.filter((tarefa) => tarefa.status !== 'Concluída').length,
  }

  return (
    <>
      <section className="flex flex-col gap-4 border-b border-white/5 pb-6 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wider text-brand-300">
            Painel Notion
          </p>
          <h1 className="text-2xl font-semibold leading-tight text-white sm:text-3xl">Tarefas</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
            Etapas, esforço e áreas vêm direto do seu Notion.
          </p>
          <DatabaseAtiva database={database} erro={erroDatabase} />
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Metric label="Total" value={resumo.total} />
          <Metric label="Visíveis" value={resumo.visiveis} />
          <Metric label="Em aberto" value={resumo.abertas} />
          <Button type="button" variant="brand" onClick={abrirCriacao}>
            <Plus size={16} aria-hidden="true" />
            Nova tarefa
          </Button>
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-zinc-950/50 p-4 sm:p-5">
        <Filtros
          busca={uiState.busca}
          setBusca={(valor) => atualizarUiState('busca', valor)}
          statusFiltro={uiState.statusFiltro}
          setStatusFiltro={(valor) => atualizarUiState('statusFiltro', valor)}
          duracaoFiltro={uiState.duracaoFiltro}
          setDuracaoFiltro={(valor) => atualizarUiState('duracaoFiltro', valor)}
          areaFiltro={uiState.areaFiltro}
          setAreaFiltro={(valor) => atualizarUiState('areaFiltro', valor)}
          ordenacao={uiState.ordenacao}
          setOrdenacao={(valor) => atualizarUiState('ordenacao', valor)}
          view={uiState.view}
          setView={(valor) => atualizarUiState('view', valor)}
          opcoes={opcoes}
          onClear={limparFiltros}
        />
      </section>

      {(erro || erroOpcoes) && (
        <div
          className="flex items-start gap-3 rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-100"
          role="alert"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden="true" />
          <div>
            <p className="font-medium">Não foi possível carregar todos os dados.</p>
            <p className="mt-1 text-red-200/80">{erro ?? erroOpcoes}</p>
          </div>
        </div>
      )}

      {carregando ? (
        <div className="flex min-h-72 items-center justify-center rounded-2xl border border-white/10">
          <div className="flex items-center gap-3 text-sm text-zinc-400">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden="true" />
            Carregando tarefas...
          </div>
        </div>
      ) : tarefasFiltradas.length === 0 ? (
        <EstadoVazio onCreate={abrirCriacao} onClear={limparFiltros} onReload={carregar} />
      ) : (
        <section aria-label="Tarefas filtradas">
          {uiState.view === 'lista' && <ViewLista tarefas={tarefasFiltradas} onEdit={abrirEdicao} />}
          {uiState.view === 'kanban' && (
            <ViewKanban
              tarefas={tarefasFiltradas}
              statusList={opcoes?.status ?? []}
              onEdit={abrirEdicao}
            />
          )}
          {uiState.view === 'grade' && <ViewGrade tarefas={tarefasFiltradas} onEdit={abrirEdicao} />}
        </section>
      )}

      <TarefaFormModal
        key={tarefaSelecionada?.id ?? 'nova'}
        open={modalAberto}
        onClose={() => setModalAberto(false)}
        onSubmit={salvarTarefa}
        tarefa={tarefaSelecionada}
        opcoes={opcoes}
      />
    </>
  )
}

function DatabaseAtiva({ database, erro }) {
  if (erro) {
    return (
      <p className="text-xs text-amber-300">
        Database ativa indisponível agora. Confirme o Notion pelo menu ou recarregue a página.
      </p>
    )
  }
  if (!database) {
    return <p className="text-xs text-zinc-500">Carregando database ativa...</p>
  }
  const dataSources = database.data_sources?.length
    ? database.data_sources.join(', ')
    : 'sem data source acessível'

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
      <span className="rounded-full border border-brand-500/30 bg-brand-500/10 px-2.5 py-1 text-brand-200">
        Database ativa
      </span>
      <span className="text-white">{database.titulo}</span>
      <span className="text-zinc-500">{database.id}</span>
      <span className="text-zinc-500">Fonte: {dataSources}</span>
      {database.url && (
        <a
          href={database.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-brand-300 hover:text-brand-200"
        >
          Abrir no Notion
          <ExternalLink size={12} aria-hidden="true" />
        </a>
      )}
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div className="min-w-20 rounded-xl border border-white/10 bg-zinc-900/60 px-3 py-2">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-lg font-semibold leading-none text-white">{value}</p>
    </div>
  )
}

function EstadoVazio({ onCreate, onClear, onReload }) {
  return (
    <div className="flex min-h-72 flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-white/10 p-8 text-center">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-white">Nenhuma tarefa encontrada</h2>
        <p className="max-w-md text-sm text-zinc-400">
          Ajuste os filtros ou crie uma tarefa para continuar trabalhando neste database.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-3">
        <Button type="button" variant="brand" onClick={onCreate}>
          <Plus size={16} aria-hidden="true" />
          Nova tarefa
        </Button>
        <Button type="button" variant="outline" onClick={onClear}>
          Limpar filtros
        </Button>
        <Button type="button" variant="ghost" onClick={onReload}>
          <RefreshCw size={16} aria-hidden="true" />
          Recarregar
        </Button>
      </div>
    </div>
  )
}
