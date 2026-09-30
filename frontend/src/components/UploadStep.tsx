import { FileText, FileUp } from 'lucide-react'
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
      <CardHeader>
        <CardTitle>Enviar o PDF do processo</CardTitle>
        <CardDescription>
          O arquivo é lido só para contar páginas e em seguida é apagado do servidor.
          Nada do conteúdo processual é gravado em banco.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label
          htmlFor={inputId}
          className={cn(
            'group flex cursor-pointer flex-col items-center gap-3 rounded-main border border-dashed bg-paper/60 px-4 py-12 text-center transition-all duration-300 hover:border-accent/60 hover:bg-paper',
            dragging ? 'scale-[1.01] border-accent bg-accent/6' : 'border-rule',
            file && 'border-solid border-accent/40 bg-paper',
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
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-accent/8 text-accent transition-transform duration-300 group-hover:-translate-y-0.5">
            {file ? (
              <FileText key="file" className="h-6 w-6 animate-pop" aria-hidden />
            ) : (
              <FileUp className="h-6 w-6" aria-hidden />
            )}
          </span>
          <span className="text-sm font-medium text-ink">
            {file ? file.name : 'Clique para escolher o PDF ou solte o arquivo aqui'}
          </span>
          <span className="text-xs text-ink-muted">
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
          <p className="text-xs text-ink-muted max-w-md">
            A extração com Gemini ainda não está ligada. Você vai percorrer o fluxo
            completo e baixar a planilha no layout provisório, sem linhas de dados.
          </p>
          <Button
            type="button"
            size="lg"
            disabled={!file || busy}
            onClick={() => file && onSubmit(file)}
          >
            {busy ? 'Enviando…' : 'Processar na sessão'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
