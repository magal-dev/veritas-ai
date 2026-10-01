import { useState } from 'react'

import { CountUp } from '@/components/CountUp'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fieldList } from '@/lib/fields'
import { toPageRanges } from '@/lib/pages'
import {
  applyBaseSalaryChoice,
  applyConflictKeepPage,
  conflictKey,
  formatAmount,
  formatConflictValue,
  markEdited,
  parseAmount,
  parseConflictField,
  withKeys,
  withoutKeys,
} from '@/lib/review-draft'
import type { Conflict, ExtractionResult, ExtractionUpdateBody, PayslipEntry, TimeCardEntry } from '@/lib/types'

const INITIAL_ROWS = 10
const ROWS_STEP = 20
const INITIAL_RANGES = 12
const INITIAL_CONFLICTS = 5

const inputClass =
  'w-full min-w-0 rounded-md border border-rule bg-paper px-2 py-1 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent aria-invalid:border-danger aria-invalid:ring-danger'

/** Texto livre enquanto digita; só valores no formato brasileiro chegam ao rascunho. */
function AmountInput({
  value,
  label,
  onCommit,
}: {
  value: number
  label: string
  onCommit: (amount: number) => void
}) {
  const [text, setText] = useState(() => formatAmount(value))
  const invalid = parseAmount(text) === null
  return (
    <input
      className={`${inputClass} text-right tabular-nums`}
      inputMode="decimal"
      value={text}
      aria-label={label}
      aria-invalid={invalid}
      title={invalid ? 'Use o formato 1.234,56' : undefined}
      onChange={(event) => {
        setText(event.target.value)
        const amount = parseAmount(event.target.value)
        if (amount !== null) onCommit(amount)
      }}
      onBlur={() => setText(formatAmount(parseAmount(text) ?? value))}
    />
  )
}

type ReviewStepProps = {
  extraction: ExtractionResult
  saving: boolean
  saveError: string | null
  onSave: (body: ExtractionUpdateBody) => Promise<void>
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
  const offset = Math.max(0, index - (visible - ROWS_STEP))
  return `${Math.min(index < INITIAL_ROWS ? index : offset, 20) * 30}ms`
}

function needsAttention(row: { confidence: number; missing_fields: string[]; ambiguous_fields: string[] }): boolean {
  return row.confidence < 0.5 || row.missing_fields.length > 0 || row.ambiguous_fields.length > 0
}

function attentionClass(row: Parameters<typeof needsAttention>[0]): string {
  return needsAttention(row) ? 'bg-accent/6' : ''
}

function attentionTitle(row: Parameters<typeof needsAttention>[0]): string | undefined {
  const notes = [
    row.confidence < 0.5 ? 'confiança baixa' : '',
    row.missing_fields.length > 0 ? `ausente: ${fieldList(row.missing_fields)}` : '',
    row.ambiguous_fields.length > 0 ? `conferir: ${fieldList(row.ambiguous_fields)}` : '',
  ].filter(Boolean)
  return notes.length > 0 ? notes.join(' · ') : undefined
}

function pageLabel(pages: number[]): string {
  const ranges = toPageRanges(pages)
  return `${pages.length > 1 ? 'pp.' : 'p.'} ${ranges.join(', ')}`
}

export function ReviewStep({
  extraction,
  saving,
  saveError,
  onSave,
  onContinue,
  onDiscard,
}: ReviewStepProps) {
  const [timeCards, setTimeCards] = useState(() => withKeys(extraction.time_cards, 't'))
  const [payslips, setPayslips] = useState(() => withKeys(extraction.payslips, 'p'))
  const [openConflicts, setOpenConflicts] = useState(extraction.conflicts)
  const [dirty, setDirty] = useState(false)

  const hasQualityIssues =
    extraction.unclassified_candidate_pages.length > 0 ||
    extraction.missing_fields.length > 0 ||
    extraction.ambiguous_fields.length > 0 ||
    openConflicts.length > 0

  const [timeCardRows, setTimeCardRows] = useState(INITIAL_ROWS)
  const [payslipRows, setPayslipRows] = useState(INITIAL_ROWS)
  const [showAllRanges, setShowAllRanges] = useState(false)
  const [showAllConflicts, setShowAllConflicts] = useState(false)

  const unclassifiedRanges = toPageRanges(extraction.unclassified_candidate_pages)
  const visibleRanges = showAllRanges ? unclassifiedRanges : unclassifiedRanges.slice(0, INITIAL_RANGES)
  const visibleConflicts = showAllConflicts ? openConflicts : openConflicts.slice(0, INITIAL_CONFLICTS)

  const canContinue =
    !dirty && openConflicts.length === 0 && extraction.conflicts.length === 0

  let continueHint = ''
  if (openConflicts.length > 0) {
    continueHint = 'Resolva os conflitos e salve as correções.'
  } else if (dirty) {
    continueHint = 'Salve as correções antes de seguir para o Excel.'
  }

  function patchTimeCard(key: string, patch: Partial<TimeCardEntry>) {
    setTimeCards((rows) => rows.map((row) => (row._key === key ? markEdited(row, patch) : row)))
    setDirty(true)
  }

  function patchPayslip(key: string, patch: Partial<PayslipEntry>) {
    setPayslips((rows) => rows.map((row) => (row._key === key ? markEdited(row, patch) : row)))
    setDirty(true)
  }

  function handleAcknowledge(conflict: Conflict) {
    setOpenConflicts((items) => items.filter((item) => conflictKey(item) !== conflictKey(conflict)))
    setDirty(true)
  }

  function handleKeepPage(conflict: Conflict, keepPage: number) {
    const next = applyConflictKeepPage({ time_cards: timeCards, payslips }, conflict, keepPage)
    setTimeCards(next.time_cards)
    setPayslips(next.payslips)
    setOpenConflicts((items) => items.filter((item) => conflictKey(item) !== conflictKey(conflict)))
    setDirty(true)
  }

  function handleBaseSalary(conflict: Conflict, salary: number) {
    const parsed = parseConflictField(conflict.field)
    if (parsed?.kind !== 'base_salary') return
    setPayslips(applyBaseSalaryChoice(payslips, parsed.competence, salary))
    setOpenConflicts((items) => items.filter((item) => conflictKey(item) !== conflictKey(conflict)))
    setDirty(true)
  }

  async function handleSave() {
    await onSave({
      time_cards: withoutKeys(timeCards),
      payslips: withoutKeys(payslips),
      conflicts: openConflicts.filter((conflict) => parseConflictField(conflict.field) === null),
    })
  }

  return (
    <div className="space-y-4">
      <Card className="animate-rise">
        <CardHeader>
          <CardTitle>Revisão da sessão</CardTitle>
          <CardDescription>
            Corrija horários e verbas na tabela, resolva conflitos entre páginas e salve antes de
            gerar o Excel.
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
              <p>Campos ausentes: {fieldList(extraction.missing_fields)}</p>
            )}
            {extraction.ambiguous_fields.length > 0 && (
              <p>
                Campos a conferir (leitura ambígua, fora do formato ou fora de ordem):{' '}
                {fieldList(extraction.ambiguous_fields)}
              </p>
            )}
            {openConflicts.length > 0 && (
              <div className="space-y-3">
                <p>
                  <span className="font-display text-2xl leading-none text-accent">
                    {openConflicts.length}
                  </span>{' '}
                  conflito(s) entre páginas — escolha qual versão manter ou iguale os valores na
                  tabela.
                </p>
                <ul className="space-y-3" aria-label="Conflitos entre páginas">
                  {visibleConflicts.map((conflict, index) => {
                    const parsed = parseConflictField(conflict.field)
                    return (
                      <li
                        key={`${conflict.field}-${index}`}
                        className="space-y-2 border-l-2 border-accent/60 pl-3"
                      >
                        <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
                          <span className="text-ink">{conflict.note ?? conflict.field}</span>
                          <span className="shrink-0 font-mono text-xs tabular-nums">
                            {pageLabel(conflict.source_pages)}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {parsed?.kind === 'base_salary' &&
                            conflict.values.map((value, valueIndex) => (
                              <Button
                                key={valueIndex}
                                type="button"
                                variant="secondary"
                                size="sm"
                                onClick={() => handleBaseSalary(conflict, Number(value))}
                              >
                                Usar {formatConflictValue(value)}
                              </Button>
                            ))}
                          {(parsed?.kind === 'time_card' || parsed?.kind === 'payslip') &&
                            conflict.source_pages.map((page) => (
                              <Button
                                key={page}
                                type="button"
                                variant="secondary"
                                size="sm"
                                onClick={() => handleKeepPage(conflict, page)}
                              >
                                Manter p. {page}
                              </Button>
                            ))}
                          {parsed === null && (
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              onClick={() => handleAcknowledge(conflict)}
                            >
                              Marcar como conferido
                            </Button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
                {openConflicts.length > INITIAL_CONFLICTS && (
                  <button
                    type="button"
                    className="text-xs font-semibold text-accent underline-offset-2 hover:underline"
                    onClick={() => setShowAllConflicts((value) => !value)}
                  >
                    {showAllConflicts
                      ? 'ver menos'
                      : `+${openConflicts.length - INITIAL_CONFLICTS} conflitos`}
                  </button>
                )}
              </div>
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
              {timeCards.length === 0 ? (
                <EmptyRow
                  columns={6}
                  message="Nenhum cartão de ponto classificado nesta sessão."
                />
              ) : (
                timeCards.slice(0, timeCardRows).map((row, index) => (
                  <TableRow
                    key={row._key}
                    className={`animate-rise ${attentionClass(row)}`}
                    title={attentionTitle(row)}
                    style={{ animationDelay: rowDelay(index, timeCardRows) }}
                  >
                    <TableCell>
                      <input
                        className={inputClass}
                        value={row.date}
                        onChange={(event) => patchTimeCard(row._key, { date: event.target.value })}
                        aria-label={`Data linha ${index + 1}`}
                      />
                    </TableCell>
                    <TableCell>
                      <input
                        className={inputClass}
                        value={row.clock_in ?? ''}
                        onChange={(event) =>
                          patchTimeCard(row._key, { clock_in: event.target.value || null })
                        }
                        aria-label={`Entrada linha ${index + 1}`}
                      />
                    </TableCell>
                    <TableCell>
                      <input
                        className={inputClass}
                        value={row.clock_out ?? ''}
                        onChange={(event) =>
                          patchTimeCard(row._key, { clock_out: event.target.value || null })
                        }
                        aria-label={`Saída linha ${index + 1}`}
                      />
                    </TableCell>
                    <TableCell className="space-y-1">
                      <input
                        className={inputClass}
                        value={row.break_start ?? ''}
                        placeholder="início"
                        onChange={(event) =>
                          patchTimeCard(row._key, { break_start: event.target.value || null })
                        }
                        aria-label={`Início intervalo linha ${index + 1}`}
                      />
                      <input
                        className={inputClass}
                        value={row.break_end ?? ''}
                        placeholder="fim"
                        onChange={(event) =>
                          patchTimeCard(row._key, { break_end: event.target.value || null })
                        }
                        aria-label={`Fim intervalo linha ${index + 1}`}
                      />
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
            total={timeCards.length}
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
              {payslips.length === 0 ? (
                <EmptyRow
                  columns={5}
                  message="Nenhum holerite classificado nesta sessão."
                />
              ) : (
                payslips.slice(0, payslipRows).map((row, index) => (
                  <TableRow
                    key={row._key}
                    className={`animate-rise ${attentionClass(row)}`}
                    title={attentionTitle(row)}
                    style={{ animationDelay: rowDelay(index, payslipRows) }}
                  >
                    <TableCell>
                      <input
                        className={inputClass}
                        value={row.competence}
                        onChange={(event) => patchPayslip(row._key, { competence: event.target.value })}
                        aria-label={`Competência linha ${index + 1}`}
                      />
                    </TableCell>
                    <TableCell>
                      <input
                        className={inputClass}
                        value={row.item_name}
                        onChange={(event) => patchPayslip(row._key, { item_name: event.target.value })}
                        aria-label={`Verba linha ${index + 1}`}
                      />
                    </TableCell>
                    <TableCell>
                      <AmountInput
                        value={row.amount}
                        label={`Valor linha ${index + 1}`}
                        onCommit={(amount) => patchPayslip(row._key, { amount })}
                      />
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
            total={payslips.length}
            onMore={() => setPayslipRows((rows) => rows + ROWS_STEP)}
            onCollapse={() => setPayslipRows(INITIAL_ROWS)}
          />
        </CardContent>
      </Card>

      {saveError && <Alert>{saveError}</Alert>}

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button type="button" variant="ghost" onClick={onDiscard} disabled={saving}>
          Descartar sessão agora
        </Button>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          {continueHint && (
            <p className="text-center text-xs text-ink-muted sm:text-right">{continueHint}</p>
          )}
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              type="button"
              variant="secondary"
              size="lg"
              disabled={!dirty || saving}
              onClick={() => void handleSave()}
            >
              {saving ? 'Salvando…' : 'Salvar correções'}
            </Button>
            <Button type="button" size="lg" disabled={!canContinue || saving} onClick={onContinue}>
              Seguir para o Excel
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
