import { ArrowDown, ArrowRight } from 'lucide-react'

import { AutosIndex } from '@/components/AutosIndex'
import { BrandBar } from '@/components/BrandBar'
import { Reveal } from '@/components/Reveal'
import { Button } from '@/components/ui/button'
import { useInView } from '@/lib/use-in-view'
import { cn } from '@/lib/utils'

type HomeScreenProps = {
  onStart: () => void
}

/*
 * A página segue a sessão do usuário: envio, triagem, conferência, download.
 * Cada etapa tem composição própria; o fio comum é o risco que o índice dos
 * autos usa para peças descartadas, repetido no fim para o que é apagado.
 */

/** Trecho fictício da tabela de revisão (folhas batem com o índice dos autos). */
const SAMPLE_ROWS: {
  date: string
  clockIn: string
  clockOut: string
  page: string
  flag?: 'missing' | 'low' | 'conflict'
}[] = [
  { date: '01/03/2021', clockIn: '08:02', clockOut: '17:58', page: '42' },
  { date: '02/03/2021', clockIn: '07:57', clockOut: '', page: '42', flag: 'missing' },
  { date: '03/03/2021', clockIn: '08:10', clockOut: '18:03', page: '42', flag: 'low' },
  { date: '04/03/2021', clockIn: '07:55 · 07:59', clockOut: '17:50', page: '42 · 43', flag: 'conflict' },
  { date: '05/03/2021', clockIn: '08:00', clockOut: '18:01', page: '43' },
]

const FLAG_LABEL = {
  missing: 'saída ausente',
  low: 'confiança baixa',
  conflict: 'folhas discordam',
}

const DISCARDED = [
  { item: 'PDF do processo', when: 'apagado ao fim da triagem' },
  { item: 'Planilha', when: 'apagada do servidor após o download' },
  { item: 'Tabela revisada', when: 'some quando a sessão expira (15 min) ou é encerrada' },
]

const STORED = [
  'Data e hora do processamento',
  'Status e código de erro',
  'Número de páginas do PDF',
  'Número de páginas candidatas',
  'Número de chamadas ao Gemini',
]

const NOT_STORED = [
  'Nome do arquivo',
  'Texto ou imagem das páginas',
  'Horários e verbas extraídos',
  'Nomes, CPF, número do processo',
  'Conta de usuário (não há login)',
]

function StepLabel({ n, children }: { n: string; children: string }) {
  return (
    <p className="flex items-baseline gap-3 text-accent">
      <span className="font-display text-[15px] tabular-nums">{n}</span>
      <span className="eyebrow">{children}</span>
    </p>
  )
}

function ReviewSample() {
  return (
    <figure
      className="overflow-hidden rounded-main border border-rule bg-raised shadow-[0_30px_50px_-34px_rgba(27,27,27,0.45)]"
      aria-label="Exemplo fictício da tabela de revisão: uma linha com saída ausente, uma com confiança baixa e uma em que duas folhas discordam"
    >
      <div className="flex items-center justify-between border-b border-rule px-4 py-2.5 text-ink-muted">
        <span className="eyebrow">Cartão de ponto · 03/2021</span>
        <span className="eyebrow">exemplo</span>
      </div>
      <table className="w-full text-left text-[13px] tabular-nums" aria-hidden>
        <thead className="text-ink-muted">
          <tr className="border-b border-rule">
            <th className="px-4 py-2 font-medium">Data</th>
            <th className="px-2 py-2 font-medium">Entrada</th>
            <th className="px-2 py-2 font-medium">Saída</th>
            <th className="hidden px-2 py-2 font-medium sm:table-cell">fls.</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {SAMPLE_ROWS.map((row) => (
            <tr
              key={row.date}
              className={cn(
                'border-b border-rule/70 last:border-0',
                row.flag === 'conflict' && 'bg-accent/[0.07]',
              )}
            >
              <td className="px-4 py-2.5">{row.date}</td>
              <td className={cn('px-2 py-2.5', row.flag === 'conflict' && 'font-medium text-accent')}>
                {row.clockIn}
              </td>
              <td className="px-2 py-2.5">
                {row.clockOut || <span className="inline-block h-4 w-10 rounded-sm border border-dashed border-accent/60 align-middle" />}
              </td>
              <td className="hidden px-2 py-2.5 text-ink-muted sm:table-cell">{row.page}</td>
              <td className="px-4 py-2.5 text-right">
                {row.flag && (
                  <span
                    className={cn(
                      'whitespace-nowrap text-[11px]',
                      row.flag === 'conflict' ? 'font-medium text-accent' : 'text-ink-muted',
                    )}
                  >
                    {FLAG_LABEL[row.flag]}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}

function DiscardList() {
  const { ref, inView } = useInView<HTMLUListElement>(0.5)
  return (
    <ul ref={ref} className="flex flex-col">
      {DISCARDED.map((entry, index) => (
        <li
          key={entry.item}
          className="grid gap-1 border-t border-rule py-4 last:border-b sm:grid-cols-[11rem_1fr] sm:gap-6"
        >
          <span className="relative inline-block self-start justify-self-start font-display text-[22px] leading-tight">
            {entry.item}
            <span
              aria-hidden
              className="absolute left-0 top-[55%] block h-px w-full origin-left bg-ink/60 transition-transform duration-700 ease-out"
              style={{ transform: `scaleX(${inView ? 1 : 0})`, transitionDelay: `${300 + index * 350}ms` }}
            />
          </span>
          <span className="text-[14px] leading-relaxed text-ink-muted sm:pt-1.5">{entry.when}</span>
        </li>
      ))}
    </ul>
  )
}

export function HomeScreen({ onStart }: HomeScreenProps) {
  return (
    <>
      <header className="grain grain-dark relative bg-burgundy text-offwhite">
        <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -right-1/4 -top-1/2 h-[140%] w-3/4 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(236,231,211,0.08),transparent)]" />
        </div>
        <div className="relative mx-auto flex max-w-6xl flex-col gap-10 px-4 pb-12 pt-5 sm:px-8 sm:pt-6 lg:gap-14 lg:pb-0">
          <BrandBar />

          <h1 className="max-w-4xl animate-rise font-display text-[40px] leading-[1.04] tracking-[-0.02em] [animation-delay:250ms] sm:text-[60px] lg:text-[76px]">
            Do PDF do processo para uma planilha de ponto e holerites.
          </h1>

          <div className="grid gap-12 lg:grid-cols-12 lg:gap-8">
            <div className="flex animate-rise flex-col gap-7 [animation-delay:450ms] lg:col-span-5 lg:pb-16">
              <p className="text-[16px] leading-relaxed text-offwhite/80 sm:text-[17px]">
                Envie o processo inteiro. O Veritas AI localiza as folhas de cartão de ponto e
                holerite, transcreve horários e verbas e mostra o resultado numa tabela para você
                conferir antes de baixar.
              </p>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <Button
                  type="button"
                  size="lg"
                  onClick={onStart}
                  className="group/btn bg-offwhite text-burgundy shadow-[0_10px_24px_-10px_rgba(0,0,0,0.6)] hover:bg-[#f6f3e7] focus-visible:ring-offwhite/60 focus-visible:ring-offset-burgundy"
                >
                  Enviar PDF
                  <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
                </Button>
                <a
                  href="#sessao"
                  className="group/link inline-flex h-12 items-center justify-center gap-2 rounded-main px-5 text-[12px] font-semibold uppercase tracking-[0.16em] text-offwhite/80 transition-colors hover:text-offwhite focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offwhite/60"
                >
                  Como funciona
                  <ArrowDown className="h-4 w-4 transition-transform duration-300 group-hover/link:translate-y-0.5" aria-hidden />
                </a>
              </div>
            </div>

            {/* No desktop o índice desce além do cabeçalho e invade a primeira etapa. */}
            <div className="relative z-10 animate-rise [animation-delay:600ms] lg:col-span-6 lg:col-start-7 lg:-mb-52">
              <div className="mx-auto w-full max-w-sm rounded-main sm:max-w-md lg:max-w-none lg:bg-burgundy-deep lg:p-8 lg:shadow-[0_40px_60px_-30px_rgba(27,27,27,0.55)]">
                <AutosIndex />
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col px-4 py-20 sm:px-8 sm:py-24">
        <section id="sessao" aria-labelledby="sessao-titulo" className="scroll-mt-8">
          <div className="grid gap-14 lg:grid-cols-12 lg:gap-8">
            <div className="flex flex-col gap-14 lg:col-span-5">
              <Reveal>
                <h2 id="sessao-titulo" className="font-display text-[34px] leading-[1.05] tracking-[-0.01em] sm:text-[44px]">
                  O que acontece depois do envio
                </h2>
              </Reveal>
              <Reveal delay={100} className="flex flex-col gap-3">
                <StepLabel n="01">Envio</StepLabel>
                <p className="text-[15px] leading-relaxed text-ink-muted">
                  <span className="text-ink">Um arquivo só, o processo inteiro.</span> Até 80 MB,
                  nativo ou escaneado. Não é preciso separar as folhas antes.
                </p>
              </Reveal>
            </div>

            <Reveal className="flex flex-col gap-3 lg:col-span-5 lg:col-start-8 lg:mt-64">
              <StepLabel n="02">Triagem</StepLabel>
              <p className="text-[15px] leading-relaxed text-ink-muted">
                <span className="text-ink">Todas as folhas são lidas no servidor, sem IA.</span>{' '}
                Palavras-chave, horários e valores apontam as candidatas, como no índice acima.
                Só elas, no máximo 25, vão ao Gemini, que lê a imagem da folha e transcreve. O
                resto do processo não sai do servidor.
              </p>
            </Reveal>
          </div>

          <div className="mt-24 grid items-start gap-10 sm:mt-32 lg:grid-cols-12 lg:gap-8">
            <Reveal className="flex flex-col gap-3 lg:col-span-4 lg:pt-16">
              <StepLabel n="03">Conferência</StepLabel>
              <p className="text-[15px] leading-relaxed text-ink-muted">
                <span className="text-ink">Você confere antes de baixar.</span> Cada linha traz a
                folha de origem. Campo que não pôde ser lido fica vazio e marcado, nunca estimado.
                Quando duas folhas discordam, você escolhe qual vale; enquanto houver conflito
                aberto, o download fica bloqueado.
              </p>
            </Reveal>
            <Reveal delay={150} className="lg:col-span-7 lg:col-start-6 lg:-mr-10">
              <ReviewSample />
            </Reveal>
          </div>

          <div className="mt-24 grid gap-8 sm:mt-32 lg:grid-cols-12 lg:gap-8">
            <Reveal className="flex flex-col gap-3 lg:col-span-3 lg:col-start-2">
              <StepLabel n="04">Download</StepLabel>
              <p className="text-[15px] leading-relaxed text-ink-muted">
                <span className="text-ink">Você baixa o .xlsx.</span> Depois disso, o que veio do
                processo deixa o servidor.
              </p>
            </Reveal>
            <Reveal delay={100} className="lg:col-span-7 lg:col-start-6">
              <DiscardList />
            </Reveal>
          </div>
        </section>

        <section aria-labelledby="registro" className="mt-28 sm:mt-40">
          <Reveal className="grid gap-10 border-t border-ink/70 pt-10 lg:grid-cols-12 lg:gap-8">
            <h2 id="registro" className="font-display text-[30px] leading-[1.08] tracking-[-0.01em] sm:text-[38px] lg:col-span-4">
              O que fica registrado
            </h2>
            <div className="grid gap-8 sm:grid-cols-2 lg:col-span-8">
              <div className="flex flex-col gap-3">
                <p className="eyebrow text-accent">No banco, por processamento</p>
                <ul className="flex flex-col text-[14px]">
                  {STORED.map((item) => (
                    <li key={item} className="border-b border-rule py-2.5">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-col gap-3">
                <p className="eyebrow text-ink-muted">Em lugar nenhum</p>
                <ul className="flex flex-col text-[14px] text-ink-muted">
                  {NOT_STORED.map((item) => (
                    <li key={item} className="border-b border-rule py-2.5">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Reveal>
        </section>

        <section aria-labelledby="comecar" className="mt-28 sm:mt-36">
          <Reveal className="grid gap-10 lg:grid-cols-12 lg:items-end lg:gap-8">
            <div className="flex flex-col items-start gap-6 lg:col-span-6">
              <h2 id="comecar" className="font-display text-[34px] leading-[1.05] tracking-[-0.01em] sm:text-5xl">
                Começar pelo PDF
              </h2>
              <Button type="button" size="lg" className="group/btn w-full sm:w-auto" onClick={onStart}>
                Enviar PDF
                <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
              </Button>
            </div>
            <aside className="border-l-2 border-accent/60 pl-4 text-[13px] leading-relaxed text-ink-muted lg:col-span-5 lg:col-start-8">
              <span className="font-medium text-ink">Limites.</span> A leitura pode errar; por
              isso a conferência existe. A planilha segue o layout{' '}
              <code className="text-ink">provisional-0.1</code>, uma hipótese de trabalho, não o
              modelo oficial do PJe-Calc. Revise antes de importar.
            </aside>
          </Reveal>
        </section>
      </main>
    </>
  )
}
