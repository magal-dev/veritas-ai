import { FileUp } from 'lucide-react'
import { useId, useState } from 'react'

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
          className="flex cursor-pointer flex-col items-center gap-3 rounded-xl border border-dashed border-rule bg-paper px-4 py-10 text-center hover:border-accent/50"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            validate(event.dataTransfer.files[0] ?? null)
          }}
        >
          <FileUp className="h-8 w-8 text-accent" aria-hidden />
          <span className="text-sm text-ink">
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
