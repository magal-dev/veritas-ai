import { ArrowRight, FileText, FileUp, X } from 'lucide-react'
import { useId, useState } from 'react'

import { cn } from '@/lib/utils'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { checkUploadFiles, mergeFiles } from '@/lib/upload'
import { MAX_UPLOAD_MB } from '@/lib/types'

type UploadStepProps = {
  busy: boolean
  error: string | null
  onSubmit: (files: File[]) => void
}

export function UploadStep({ busy, error, onSubmit }: UploadStepProps) {
  const inputId = useId()
  const [files, setFiles] = useState<File[]>([])
  const [localError, setLocalError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  function add(incoming: FileList | null) {
    if (!incoming || incoming.length === 0) return
    const next = mergeFiles(files, Array.from(incoming))
    const problem = checkUploadFiles(next)
    setLocalError(problem)
    if (!problem) setFiles(next)
  }

  function remove(index: number) {
    setLocalError(null)
    setFiles((current) => current.filter((_, position) => position !== index))
  }

  const hasFiles = files.length > 0

  return (
    <Card>
      <CardHeader className="stagger">
        <CardTitle>Enviar cartão de ponto e holerite</CardTitle>
        <CardDescription>
          Envie só as folhas do cartão de ponto e do holerite (PDF ou fotos) ou o processo
          inteiro. Nada do conteúdo processual é gravado em banco.
        </CardDescription>
      </CardHeader>
      <CardContent className="stagger space-y-4">
        <label
          htmlFor={inputId}
          className={cn(
            'group relative flex cursor-pointer flex-col items-center gap-3 rounded-main bg-paper/50 px-4 py-10 text-center sm:py-14 transition-all duration-300 hover:bg-paper',
            dragging && 'bg-accent/6',
          )}
          onDragOver={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            add(event.dataTransfer.files)
          }}
        >
          {['left-0 top-0 border-l border-t', 'right-0 top-0 border-r border-t', 'bottom-0 left-0 border-b border-l', 'bottom-0 right-0 border-b border-r'].map((pos) => (
            <span
              key={pos}
              aria-hidden
              className={cn(
                'absolute h-5 w-5 border-ink/60 transition-all duration-300 group-hover:h-7 group-hover:w-7 group-hover:border-accent',
                dragging && 'h-7 w-7 border-accent',
                pos,
              )}
            />
          ))}
          <span className={cn('text-accent', !hasFiles && 'animate-float')}>
            {hasFiles ? (
              <FileText key="file" className="h-7 w-7 animate-pop" strokeWidth={1.25} aria-hidden />
            ) : (
              <FileUp className="h-7 w-7" strokeWidth={1.25} aria-hidden />
            )}
          </span>
          <span className="max-w-full break-words font-display text-xl leading-tight sm:text-2xl">
            {hasFiles
              ? `${files.length} arquivo(s) selecionado(s) · adicionar mais`
              : 'Escolha os arquivos ou solte-os aqui'}
          </span>
          <span className="eyebrow text-ink-muted">
            PDF ou fotos (JPG, PNG) · vários de uma vez · até {MAX_UPLOAD_MB} MB no total
          </span>
          <input
            id={inputId}
            type="file"
            multiple
            accept="application/pdf,.pdf,image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
            className="sr-only"
            disabled={busy}
            onChange={(event) => {
              add(event.target.files)
              event.target.value = ''
            }}
          />
        </label>

        {hasFiles && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Arquivos selecionados">
            {files.map((item, index) => (
              <li
                key={`${item.name}-${item.size}-${item.lastModified}`}
                className="flex max-w-full items-center gap-1 rounded-full border border-rule bg-paper-2 py-0.5 pl-2.5 pr-1 text-xs text-ink"
              >
                <span className="truncate">{item.name}</span>
                <button
                  type="button"
                  className="rounded-full p-0.5 text-ink-muted hover:text-accent"
                  aria-label={`Remover ${item.name}`}
                  disabled={busy}
                  onClick={() => remove(index)}
                >
                  <X className="h-3 w-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}

        {(localError || error) && <Alert>{localError || error}</Alert>}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-md text-[13px] leading-relaxed text-ink-muted">
            Fotos ou vários arquivos: até 25 páginas no total, todas são lidas, na ordem do envio.
            Num PDF único, a triagem local separa as folhas de cartão de ponto e holerite e deixa
            de fora petições e planilhas de cálculo; até 15 páginas, toda folha digitalizada ou
            fotografada é lida.
          </p>
          <Button
            type="button"
            size="lg"
            className="group/btn w-full sm:w-auto"
            disabled={!hasFiles || busy}
            onClick={() => hasFiles && onSubmit(files)}
          >
            {busy ? 'Enviando…' : 'Processar na sessão'}
            <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
