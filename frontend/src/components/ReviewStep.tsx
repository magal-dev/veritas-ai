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
      <TableCell colSpan={columns} className="py-8 text-center text-ink-muted">
        {message}
      </TableCell>
    </TableRow>
  )
}

export function ReviewStep({ extraction, onContinue, onDiscard }: ReviewStepProps) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Revisão da sessão</CardTitle>
          <CardDescription>
            Os dados extraídos existem só nesta sessão. Nesta fundação a tabela fica
            vazia de propósito: ainda não há classificação de cartão de ponto nem holerite.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
          <div className="rounded-lg border border-rule bg-paper p-3">
            <p className="text-xs uppercase tracking-wide text-ink-muted">Páginas no PDF</p>
            <p className="mt-1 font-display text-2xl">{extraction.pdf_page_count}</p>
          </div>
          <div className="rounded-lg border border-rule bg-paper p-3">
            <p className="text-xs uppercase tracking-wide text-ink-muted">Páginas candidatas</p>
            <p className="mt-1 font-display text-2xl">{extraction.candidate_page_count}</p>
          </div>
          <div className="rounded-lg border border-rule bg-paper p-3">
            <p className="text-xs uppercase tracking-wide text-ink-muted">Chamadas Gemini</p>
            <p className="mt-1 font-display text-2xl">{extraction.gemini_call_count}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
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
                extraction.time_cards.map((row) => (
                  <TableRow key={`${row.date}-${row.source_page}`}>
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

      <Card>
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
                extraction.payslips.map((row) => (
                  <TableRow key={`${row.competence}-${row.item_name}-${row.source_page}`}>
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
