import { ShieldCheck } from 'lucide-react'
import { useCallback, useState } from 'react'

import { DownloadStep } from '@/components/DownloadStep'
import { ProcessingStep } from '@/components/ProcessingStep'
import { ReviewStep } from '@/components/ReviewStep'
import { Stepper, type FlowStep } from '@/components/Stepper'
import { UploadStep } from '@/components/UploadStep'
import { Badge } from '@/components/ui/badge'
import { createJob, discardJob, downloadExcel, getPreview } from '@/lib/api'
import type { ApiError, ExtractionResult } from '@/lib/types'

type SessionState = {
  jobId: string
  fileName: string
  extraction: ExtractionResult | null
}

const emptySession: SessionState = {
  jobId: '',
  fileName: '',
  extraction: null,
}

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as ApiError).message)
  }
  return 'Falha de comunicação com a API. Confirme se o backend está em http://127.0.0.1:8765.'
}

export default function App() {
  const [step, setStep] = useState<FlowStep>('upload')
  const [session, setSession] = useState<SessionState>(emptySession)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [discarded, setDiscarded] = useState(false)

  const reset = useCallback(() => {
    setStep('upload')
    setSession(emptySession)
    setBusy(false)
    setError(null)
    setDiscarded(false)
  }, [])

  async function handleDiscard() {
    if (session.jobId) {
      try {
        await discardJob(session.jobId)
      } catch {
        /* sessão já pode ter expirado */
      }
    }
    setDiscarded(true)
    setStep('download')
    setSession(emptySession)
  }

  async function handleUpload(file: File) {
    setBusy(true)
    setError(null)
    setStep('processing')
    setSession({ jobId: '', fileName: file.name, extraction: null })
    try {
      const created = await createJob(file)
      const preview = await getPreview(created.job_id)
      setSession({
        jobId: created.job_id,
        fileName: file.name,
        extraction: preview.extraction,
      })
      setStep('review')
    } catch (err) {
      setError(errorMessage(err))
      setStep('upload')
    } finally {
      setBusy(false)
    }
  }

  async function handleDownload() {
    if (!session.jobId) {
      setError('Sessão inexistente. Envie o PDF novamente.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const blob = await downloadExcel(session.jobId)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'pjecalc-provisorio.xlsx'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
      await discardJob(session.jobId)
      setDiscarded(true)
      setSession(emptySession)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-svh">
      <header className="border-b border-rule bg-ink text-paper-2">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-paper/70">TCC · PJe-Calc</p>
            <h1 className="font-display text-2xl sm:text-3xl mt-1">
              Extração inteligente de dados processuais
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-paper/80 leading-relaxed">
              Cartões de ponto e holerites saem do PDF do processo e entram numa planilha
              para o PJe-Calc. A sessão é efêmera: upload, revisão, download e descarte.
            </p>
          </div>
          <Badge className="w-fit border-paper/20 bg-ink text-paper">Fundação 0.1 · sem persistência</Badge>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8">
        <div className="flex items-start gap-3 rounded-xl border border-accent/20 bg-white px-4 py-3 text-sm text-ink">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden />
          <p>
            Privacy by Design: não há contas, histórico nem armazenamento de conteúdo
            processual. O PostgreSQL, quando disponível, registra só metadados operacionais
            (duração, status, contagem de páginas).
          </p>
        </div>

        <Stepper current={step} />

        {step === 'upload' && (
          <UploadStep busy={busy} error={error} onSubmit={handleUpload} />
        )}
        {step === 'processing' && <ProcessingStep fileName={session.fileName} />}
        {step === 'review' && session.extraction && (
          <ReviewStep
            extraction={session.extraction}
            onContinue={() => setStep('download')}
            onDiscard={() => void handleDiscard()}
          />
        )}
        {step === 'download' && (
          <DownloadStep
            busy={busy}
            discarded={discarded}
            error={error}
            onDownload={() => void handleDownload()}
            onRestart={reset}
          />
        )}
      </main>
    </div>
  )
}
