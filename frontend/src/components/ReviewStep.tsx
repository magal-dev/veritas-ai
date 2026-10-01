import { CountUp } from '@/components/CountUp'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { ExtractionResult } from '@/lib/types'

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

function lowConfidenceClass(confidence: number): string {
  return confidence < 0.5 ? 'bg-accent/6' : ''
}

export function ReviewStep({ extraction, onContinue, onDiscard }: ReviewStepProps) {
  const hasQualityIssues =
    extraction.unclassified_candidate_pages.length > 0 ||
    extraction.missing_fields.length > 0 ||
    extraction.conflicts.length > 0

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
          <CardContent className="space-y-2 text-sm text-ink-muted">
            {extraction.unclassified_candidate_pages.length > 0 && (
              <p>
                Páginas candidatas não classificadas:{' '}
                {extraction.unclassified_candidate_pages.join(', ')}
              </p>
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
                extraction.time_cards.map((row, index) => (
                  <TableRow
                    key={`${row.date}-${row.source_page}`}
                    className={`animate-rise ${lowConfidenceClass(row.confidence)}`}
                    style={{ animationDelay: `${index * 35}ms` }}
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
                extraction.payslips.map((row, index) => (
                  <TableRow
                    key={`${row.competence}-${row.item_name}-${row.source_page}`}
                    className={`animate-rise ${lowConfidenceClass(row.confidence)}`}
                    style={{ animationDelay: `${index * 35}ms` }}
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
