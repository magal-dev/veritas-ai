import { useState } from 'react'

import { CountUp } from '@/components/CountUp'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toPageRanges } from '@/lib/pages'
import type { ExtractionResult } from '@/lib/types'

const INITIAL_ROWS = 10
const ROWS_STEP = 20
const INITIAL_RANGES = 12

type ReviewStepProps = {
  extraction: ExtractionResult
  onContinue: () => void
  onDiscard: () => void
}

function EmptyRow({ columns, message }: { columns: number; message: string }) {
  return (
    <TableRow>
      <TableCell colSpan={columns} className="py-10 text-center font-display text-lg italic text-ink-muted">
        {message}
      </TableCell>
    </TableRow>
  )
}

function ShowMore({
  visible,
  total,
  onMore,
  onCollapse,
}: {
  visible: number
  total: number
  onMore: () => void
  onCollapse: () => void
}) {
  if (total <= INITIAL_ROWS) return null
  const remaining = total - visible
  return (
    <div className="mt-4 flex flex-col items-center gap-2 border-t border-rule pt-4 sm:flex-row sm:justify-between">
      <p className="text-xs text-ink-muted">
        Exibindo {Math.min(visible, total)} de {total} linhas
      </p>
      <div className="flex gap-2">
        {visible > INITIAL_ROWS && (
          <Button type="button" variant="ghost" size="sm" onClick={onCollapse}>
            Recolher
          </Button>
        )}
        {remaining > 0 && (
          <Button type="button" variant="secondary" size="sm" onClick={onMore}>
            Mostrar mais {Math.min(ROWS_STEP, remaining)}
          </Button>
        )}
      </div>
    </div>
  )
}

function rowDelay(index: number, visible: number): string {
  // Só as linhas recém-reveladas animam, em cascata curta.
  const offset = Math.max(0, index - (visible - ROWS_STEP))
  return `${Math.min(index < INITIAL_ROWS ? index : offset, 20) * 30}ms`
}

function lowConfidenceClass(confidence: number): string {
  return confidence < 0.5 ? 'bg-accent/6' : ''
}

export function ReviewStep({ extraction, onContinue, onDiscard }: ReviewStepProps) {
  const hasQualityIssues =
    extraction.unclassified_candidate_pages.length > 0 ||
    extraction.missing_fields.length > 0 ||
    extraction.conflicts.length > 0
  const [timeCardRows, setTimeCardRows] = useState(INITIAL_ROWS)
  const [payslipRows, setPayslipRows] = useState(INITIAL_ROWS)
  const [showAllRanges, setShowAllRanges] = useState(false)
  const unclassifiedRanges = toPageRanges(extraction.unclassified_candidate_pages)
  const visibleRanges = showAllRanges ? unclassifiedRanges : unclassifiedRanges.slice(0, INITIAL_RANGES)

  return (
    <div className="space-y-4">
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Revisão da sessão</CardTitle>
          <CardDescription>
            Os dados extraídos existem só nesta sessão. Revise cartões de ponto e
            holerites antes de gerar o Excel.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-8 text-sm sm:grid-cols-3">
          <div className="animate-rise border-t border-ink/70 pt-3 [animation-delay:150ms]">
            <p className="eyebrow text-ink-muted">Páginas no PDF</p>
            <p className="mt-1 font-display text-6xl leading-none text-accent">
              <CountUp value={extraction.pdf_page_count} />
            </p>
          </div>
          <div className="animate-rise border-t border-ink/70 pt-3 [animation-delay:280ms]">
            <p className="eyebrow text-ink-muted">Páginas candidatas</p>
            <p className="mt-1 font-display text-6xl leading-none text-accent">
              <CountUp value={extraction.candidate_page_count} />
            </p>
          </div>
          <div className="animate-rise border-t border-ink/70 pt-3 [animation-delay:410ms]">
            <p className="eyebrow text-ink-muted">Chamadas Gemini</p>
            <p className="mt-1 font-display text-6xl leading-none text-accent">
              <CountUp value={extraction.gemini_call_count} />
            </p>
          </div>
        </CardContent>
      </Card>

      {hasQualityIssues && (
        <Card className="animate-rise [animation-delay:60ms]">
          <CardHeader>
            <CardTitle className="text-base">Pendências da extração</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-ink-muted">
            {extraction.unclassified_candidate_pages.length > 0 && (
              <div className="space-y-2">
                <p>
                  <span className="font-display text-2xl leading-none text-accent">
                    {extraction.unclassified_candidate_pages.length}
                  </span>{' '}
                  página(s) candidata(s) não classificada(s)
                </p>
                <ul className="flex flex-wrap gap-1.5" aria-label="Páginas não classificadas">
                  {visibleRanges.map((range) => (
                    <li
                      key={range}
                      className="rounded-full border border-rule bg-paper-2 px-2.5 py-0.5 font-mono text-xs tabular-nums text-ink"
                    >
                      {range.includes('–') ? `pp. ${range}` : `p. ${range}`}
                    </li>
                  ))}
                  {unclassifiedRanges.length > INITIAL_RANGES && (
                    <li>
                      <button
                        type="button"
                        className="rounded-full px-2.5 py-0.5 text-xs font-semibold text-accent underline-offset-2 hover:underline"
                        onClick={() => setShowAllRanges((value) => !value)}
                      >
                        {showAllRanges
                          ? 'ver menos'
                          : `+${unclassifiedRanges.length - INITIAL_RANGES} intervalos`}
                      </button>
                    </li>
                  )}
                </ul>
              </div>
            )}
            {extraction.missing_fields.length > 0 && (
              <p>Campos ausentes: {extraction.missing_fields.join(', ')}</p>
            )}
            {extraction.conflicts.length > 0 && (
              <p>{extraction.conflicts.length} conflito(s) entre documentos.</p>
            )}
          </CardContent>
        </Card>
      )}

      <Card className="animate-rise [animation-delay:120ms]">
        <CardHeader>
          <CardTitle>Cartão de ponto</CardTitle>
          <CardDescription>Horários de entrada, saída e intervalo.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Data</TableHead>
                <TableHead>Entrada</TableHead>
                <TableHead>Saída</TableHead>
                <TableHead>Intervalo</TableHead>
                <TableHead>Página</TableHead>
                <TableHead>Confiança</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {extraction.time_cards.length === 0 ? (
                <EmptyRow
                  columns={6}
                  message="Nenhum cartão de ponto classificado nesta sessão."
                />
              ) : (
                extraction.time_cards.slice(0, timeCardRows).map((row, index) => (
                  <TableRow
                    key={`${row.date}-${row.source_page}`}
                    className={`animate-rise ${lowConfidenceClass(row.confidence)}`}
                    style={{ animationDelay: rowDelay(index, timeCardRows) }}
                  >
                    <TableCell>{row.date}</TableCell>
                    <TableCell>{row.clock_in ?? '—'}</TableCell>
                    <TableCell>{row.clock_out ?? '—'}</TableCell>
                    <TableCell>
                      {row.break_start || row.break_end
                        ? `${row.break_start ?? '—'} – ${row.break_end ?? '—'}`
                        : '—'}
                    </TableCell>
                    <TableCell>{row.source_page}</TableCell>
                    <TableCell>{row.confidence.toFixed(2)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <ShowMore
            visible={timeCardRows}
            total={extraction.time_cards.length}
            onMore={() => setTimeCardRows((rows) => rows + ROWS_STEP)}
            onCollapse={() => setTimeCardRows(INITIAL_ROWS)}
          />
        </CardContent>
      </Card>

      <Card className="animate-rise [animation-delay:240ms]">
        <CardHeader>
          <CardTitle>Holerite / ficha financeira</CardTitle>
          <CardDescription>Verbas e valores extraídos do documento.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Competência</TableHead>
                <TableHead>Verba</TableHead>
                <TableHead>Valor</TableHead>
                <TableHead>Página</TableHead>
                <TableHead>Confiança</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {extraction.payslips.length === 0 ? (
                <EmptyRow
                  columns={5}
                  message="Nenhum holerite classificado nesta sessão."
                />
              ) : (
                extraction.payslips.slice(0, payslipRows).map((row, index) => (
                  <TableRow
                    key={`${row.competence}-${row.item_name}-${row.source_page}`}
                    className={`animate-rise ${lowConfidenceClass(row.confidence)}`}
                    style={{ animationDelay: rowDelay(index, payslipRows) }}
                  >
                    <TableCell>{row.competence}</TableCell>
                    <TableCell>{row.item_name}</TableCell>
                    <TableCell>
                      {row.amount.toLocaleString('pt-BR', {
                        style: 'currency',
                        currency: 'BRL',
                      })}
                    </TableCell>
                    <TableCell>{row.source_page}</TableCell>
                    <TableCell>{row.confidence.toFixed(2)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <ShowMore
            visible={payslipRows}
            total={extraction.payslips.length}
            onMore={() => setPayslipRows((rows) => rows + ROWS_STEP)}
            onCollapse={() => setPayslipRows(INITIAL_ROWS)}
          />
        </CardContent>
      </Card>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
        <Button type="button" variant="ghost" onClick={onDiscard}>
          Descartar sessão agora
        </Button>
        <Button type="button" size="lg" onClick={onContinue}>
          Seguir para o Excel
        </Button>
      </div>
    </div>
  )
}
