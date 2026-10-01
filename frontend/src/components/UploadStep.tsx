import { ArrowRight, FileText, FileUp } from 'lucide-react'
import { useId, useState } from 'react'

import { cn } from '@/lib/utils'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { MAX_UPLOAD_MB } from '@/lib/types'

type UploadStepProps = {
  busy: boolean
  error: string | null
  onSubmit: (file: File) => void
}

export function UploadStep({ busy, error, onSubmit }: UploadStepProps) {
  const inputId = useId()
  const [file, setFile] = useState<File | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  function validate(next: File | null) {
    setLocalError(null)
    if (!next) {
      setFile(null)
      return
    }
    const isPdf =
      next.type === 'application/pdf' || next.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) {
      setFile(null)
      setLocalError('Envie um arquivo PDF do processo.')
      return
    }
    if (next.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setFile(null)
      setLocalError(`O PDF não pode passar de ${MAX_UPLOAD_MB} MB nesta fundação.`)
      return
    }
    setFile(next)
  }

  return (
    <Card>
      <CardHeader className="stagger">
        <CardTitle>Enviar o PDF do processo</CardTitle>
        <CardDescription>
          O PDF é triado localmente e as páginas candidatas são enviadas ao Gemini.
          Nada do conteúdo processual é gravado em banco.
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
            validate(event.dataTransfer.files[0] ?? null)
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
          <span className={cn('text-accent', !file && 'animate-float')}>
            {file ? (
              <FileText key="file" className="h-7 w-7 animate-pop" strokeWidth={1.25} aria-hidden />
            ) : (
              <FileUp className="h-7 w-7" strokeWidth={1.25} aria-hidden />
            )}
          </span>
          <span className="max-w-full break-words font-display text-xl leading-tight sm:text-2xl">
            {file ? file.name : 'Escolha o PDF ou solte o arquivo aqui'}
          </span>
          <span className="eyebrow text-ink-muted">
            PDF nativo ou digitalizado · até {MAX_UPLOAD_MB} MB
          </span>
          <input
            id={inputId}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            disabled={busy}
            onChange={(event) => validate(event.target.files?.[0] ?? null)}
          />
        </label>

        {(localError || error) && <Alert>{localError || error}</Alert>}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-md text-[13px] leading-relaxed text-ink-muted">
            A triagem local identifica cartões de ponto e holerites. O Gemini classifica
            até 5 páginas candidatas por processo. PDFs escaneados (sem texto) ainda não
            são suportados.
          </p>
          <Button
            type="button"
            size="lg"
            className="group/btn w-full sm:w-auto"
            disabled={!file || busy}
            onClick={() => file && onSubmit(file)}
          >
            {busy ? 'Enviando…' : 'Processar na sessão'}
            <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
