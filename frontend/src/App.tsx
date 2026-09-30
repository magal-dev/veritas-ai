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
      anchor.download = 'veritas-pjecalc-provisorio.xlsx'
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
      <header className="relative overflow-hidden border-b border-burgundy/60 bg-darkgray text-offwhite">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 w-2/3 bg-[radial-gradient(600px_220px_at_100%_0%,rgba(95,28,28,0.55),transparent_70%)]"
        />
        <div className="relative mx-auto flex max-w-5xl flex-col gap-5 px-4 py-7 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-5">
            <img
              src="/logo.png"
              alt="Veritas AI"
              className="h-16 w-16 shrink-0 animate-fade object-contain sm:h-20 sm:w-20"
            />
            <div>
              <p className="text-[11px] uppercase tracking-[0.28em] text-offwhite/60">
                Veritas AI · PJe-Calc
              </p>
              <h1 className="mt-1.5 font-display text-2xl font-medium tracking-tight sm:text-3xl">
                Extração inteligente de dados processuais
              </h1>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-offwhite/75">
                Cartões de ponto e holerites saem do PDF do processo e entram numa planilha
                para o PJe-Calc. A sessão é efêmera: upload, revisão, download e descarte.
              </p>
            </div>
          </div>
          <Badge className="w-fit shrink-0 border-offwhite/20 bg-offwhite/5 text-offwhite/80">
            <span className="h-1.5 w-1.5 rounded-full bg-offwhite/60" aria-hidden />
            Fundação 0.1 · sem persistência
          </Badge>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-10">
        <div className="flex animate-fade items-start gap-3 rounded-main border border-rule bg-paper-2/70 px-4 py-3 text-sm text-ink">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-accent" aria-hidden />
          <p className="leading-relaxed">
            Privacy by Design: não há contas, histórico nem armazenamento de conteúdo
            processual. O PostgreSQL, quando disponível, registra só metadados operacionais
            (duração, status, contagem de páginas).
          </p>
        </div>

        <Stepper current={step} />

        <div key={step} className="animate-rise">
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
        </div>
      </main>
    </div>
  )
}
