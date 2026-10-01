import { ArrowRight } from 'lucide-react'
import { Fragment, useEffect, useState } from 'react'

import { CountUp } from '@/components/CountUp'
import { cn } from '@/lib/utils'

/*
 * Índice dos autos de um processo fictício, lido peça por peça.
 * Peças irrelevantes são riscadas; cartões de ponto, holerites e recibos
 * recebem marca na margem. A legenda acompanha: folhas lidas, páginas
 * candidatas (teto de 25) e chamadas ao Gemini (5 páginas por chamada).
 */
type Piece = { title: string; pages: number; candidate?: boolean }

const PIECES: Piece[] = [
  { title: 'Petição inicial', pages: 24 },
  { title: 'Procuração', pages: 2 },
  { title: 'Documentos pessoais', pages: 4 },
  { title: 'CTPS', pages: 6 },
  { title: 'Contrato de trabalho', pages: 5 },
  { title: 'Cartão de ponto 01–03/21', pages: 3, candidate: true },
  { title: 'Cartão de ponto 04–06/21', pages: 3, candidate: true },
  { title: 'Holerites 01–03/21', pages: 3, candidate: true },
  { title: 'Termo de rescisão', pages: 3 },
  { title: 'Notificação', pages: 2 },
  { title: 'Contestação', pages: 34 },
  { title: 'Carta de preposição', pages: 3 },
  { title: 'Contrato social', pages: 12 },
  { title: 'Cartão de ponto 07–12/21', pages: 6, candidate: true },
  { title: 'Holerites 04–12/21', pages: 8, candidate: true },
  { title: 'Recibo de férias', pages: 2, candidate: true },
  { title: 'Réplica', pages: 18 },
  { title: 'Ata de audiência', pages: 3 },
  { title: 'Despacho', pages: 1 },
  { title: 'Laudo pericial contábil', pages: 29 },
  { title: 'Impugnação ao laudo', pages: 9 },
  { title: 'Razões finais', pages: 10 },
  { title: 'Sentença', pages: 24 },
  { title: 'Embargos de declaração', pages: 7 },
  { title: 'Recurso ordinário', pages: 30 },
  { title: 'Acórdão', pages: 26 },
  { title: 'Certidão de trânsito em julgado', pages: 1 },
]

const PAGES_PER_CALL = 5
const ROW_REM = 2.75
const VISIBLE = 7
const CURSOR_ROW = 3
const STEP_MS = 1300

const STARTS = PIECES.reduce<number[]>((acc, _, index) => {
  acc.push(index === 0 ? 1 : acc[index - 1] + PIECES[index - 1].pages)
  return acc
}, [])
const TOTAL_PAGES = STARTS[STARTS.length - 1] + PIECES[PIECES.length - 1].pages - 1

function folhas(index: number) {
  const start = STARTS[index]
  const end = start + PIECES[index].pages - 1
  return start === end ? `fls. ${start}` : `fls. ${start}–${end}`
}

function plural(count: number, singular: string, pluralForm: string) {
  return count === 1 ? singular : pluralForm
}

/** Posição absoluta do cursor; cresce sem parar, o índice dá a volta. */
function useCursor() {
  const [cursor, setCursor] = useState(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      const id = requestAnimationFrame(() => setCursor(16))
      return () => cancelAnimationFrame(id)
    }
    let interval = 0
    const start = window.setTimeout(() => {
      setCursor((value) => value + 1)
      interval = window.setInterval(() => setCursor((value) => value + 1), STEP_MS)
    }, 1600)
    return () => {
      window.clearTimeout(start)
      window.clearInterval(interval)
    }
  }, [])

  return cursor
}

function CheckMark({ drawn }: { drawn: boolean }) {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path
        d="M3 8.5l3.2 3.2L13 4.8"
        pathLength={1}
        strokeDasharray={1}
        className="transition-[stroke-dashoffset] duration-500 ease-out"
        style={{ strokeDashoffset: drawn ? 0 : 1, transitionDelay: drawn ? '250ms' : '0ms' }}
      />
    </svg>
  )
}

export function AutosIndex() {
  const cursor = useCursor()
  const position = cursor % PIECES.length

  let read = 0
  let candidates = 0
  for (let index = 0; index < position; index++) {
    read += PIECES[index].pages
    if (PIECES[index].candidate) candidates += PIECES[index].pages
  }
  const calls = Math.ceil(candidates / PAGES_PER_CALL)

  const rows = []
  for (let offset = -CURSOR_ROW - 1; offset <= VISIBLE - CURSOR_ROW; offset++) {
    const absolute = cursor + offset
    if (absolute < 0) continue
    const index = absolute % PIECES.length
    // Peças de uma volta anterior do índice já foram lidas; as da volta atual, só até o cursor.
    const done = offset < 0
    rows.push({ absolute, index, offset, done })
  }

  return (
    <figure className="flex flex-col gap-5" aria-label="Ilustração: o índice dos autos é lido peça por peça; só cartões de ponto, holerites e recibos seguem para extração">
      <div className="flex items-baseline justify-between border-b border-offwhite/35 pb-2 text-offwhite/70">
        <span className="eyebrow">Índice dos autos</span>
        <span className="eyebrow tabular-nums">{TOTAL_PAGES} folhas</span>
      </div>

      <div
        aria-hidden
        className="relative overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_18%,black_82%,transparent)]"
        style={{ height: `${VISIBLE * ROW_REM}rem` }}
      >
        <span
          className="absolute inset-x-0 border-y border-offwhite/25 bg-offwhite/[0.04]"
          style={{ top: `${CURSOR_ROW * ROW_REM}rem`, height: `${ROW_REM}rem` }}
        >
          <span className="absolute -left-px inset-y-[-1px] w-0.5 bg-offwhite" />
        </span>

        {rows.map(({ absolute, index, offset, done }) => {
          const piece = PIECES[index]
          const current = offset === 0
          const struck = done && !piece.candidate
          return (
            <div
              key={absolute}
              className="absolute inset-x-0 grid animate-fade grid-cols-[5.25rem_minmax(0,1fr)_1.25rem] items-center gap-3 pl-3 transition-transform duration-700 ease-[cubic-bezier(0.65,0,0.35,1)] sm:grid-cols-[6rem_minmax(0,1fr)_5.5rem]"
              style={{ height: `${ROW_REM}rem`, transform: `translateY(${(offset + CURSOR_ROW) * ROW_REM}rem)` }}
            >
              <span
                className={cn(
                  'text-[10.5px] font-medium uppercase tracking-[0.12em] tabular-nums transition-colors duration-500 sm:text-[11px]',
                  current ? 'text-offwhite' : done ? 'text-offwhite/40' : 'text-offwhite/55',
                )}
              >
                {folhas(index)}
              </span>
              <span className="min-w-0">
                <span className="relative inline-block max-w-full align-middle">
                  <span
                    className={cn(
                      'block truncate font-display text-[17px] leading-none transition-colors duration-500 sm:text-[19px]',
                      current || (done && piece.candidate) ? 'text-offwhite' : done ? 'text-offwhite/35' : 'text-offwhite/60',
                      piece.candidate && done && 'italic',
                    )}
                  >
                    {piece.title}
                  </span>
                  <span
                    className="absolute left-0 top-1/2 block h-px w-full origin-left bg-offwhite/45 transition-transform duration-500 ease-out"
                    style={{ transform: `scaleX(${struck ? 1 : 0})`, transitionDelay: struck ? '150ms' : '0ms' }}
                  />
                </span>
              </span>
              <span className="flex items-center justify-end gap-1.5 text-offwhite">
                {piece.candidate && (
                  <>
                    <span
                      className={cn(
                        'eyebrow hidden tracking-[0.14em] transition-opacity duration-500 sm:inline',
                        done ? 'opacity-70' : 'opacity-0',
                      )}
                    >
                      Extrair
                    </span>
                    <CheckMark drawn={done} />
                  </>
                )}
              </span>
            </div>
          )
        })}
      </div>

      <figcaption className="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-end gap-x-2 border-t border-offwhite/35 pt-4 text-offwhite/60 sm:gap-x-4">
        {[
          { id: 'read', value: read, label: plural(read, 'lida', 'lidas') },
          { id: 'candidates', value: candidates, label: plural(candidates, 'candidata', 'candidatas'), highlight: true },
          { id: 'calls', value: calls, label: plural(calls, 'chamada', 'chamadas') },
        ].map((item, index) => (
          <Fragment key={item.id}>
            {index > 0 && <ArrowRight className="mb-1 h-3 w-3 shrink-0" aria-hidden />}
            <span className={cn('flex min-w-0 flex-col gap-1', item.highlight && 'text-offwhite')}>
              <span className="font-display text-3xl leading-none tabular-nums">
                <CountUp value={item.value} duration={700} />
              </span>
              <span className="eyebrow tracking-[0.14em] sm:tracking-[0.2em]">{item.label}</span>
            </span>
          </Fragment>
        ))}
      </figcaption>
    </figure>
  )
}
