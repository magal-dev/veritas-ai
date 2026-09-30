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

const TITLE = [
  { text: 'Extração' },
  { text: 'inteligente' },
  { text: 'de' },
  { text: 'dados', italic: true },
  { text: 'processuais', italic: true },
]

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
      <header className="grain grain-dark relative overflow-hidden bg-burgundy text-offwhite">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-1/4 -top-1/2 h-[140%] w-3/4 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(236,231,211,0.10),transparent)]"
        />
        <div className="relative mx-auto flex max-w-5xl flex-col gap-6 px-4 pb-8 pt-5 sm:px-8 sm:pb-9 sm:pt-6">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <img src="/logo-light.png" alt="" className="h-9 w-9 animate-pop object-contain" />
              <span className="font-display text-2xl tracking-[0.04em] animate-fade [animation-delay:200ms]">
                Veritas AI
              </span>
            </div>
            <Badge className="animate-fade border-offwhite/30 text-offwhite/80 [animation-delay:400ms]">
              Fundação 0.1
            </Badge>
          </div>
          <h1 className="font-display text-[34px] leading-[1.05] tracking-[-0.02em] sm:text-5xl" aria-label="Extração inteligente de dados processuais">
            {TITLE.map((word, index) => (
              <span key={word.text} aria-hidden className="inline-block overflow-hidden pb-1 align-bottom">
                <span
                  className={`inline-block animate-reveal ${word.italic ? 'italic text-offwhite/80' : ''}`}
                  style={{ animationDelay: `${250 + index * 90}ms` }}
                >
                  {word.text}
                  {'\u00A0'}
                </span>
              </span>
            ))}
          </h1>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 sm:gap-12 sm:px-8 sm:py-14">
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

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-5xl items-start gap-4 px-4 py-6 sm:px-8 sm:py-8">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-accent" strokeWidth={1.5} aria-hidden />
          <p className="max-w-2xl text-[13px] leading-relaxed text-ink-muted">
            <span className="eyebrow mr-2 text-ink">Privacy by Design</span>
            Não há contas, histórico nem armazenamento de conteúdo processual. O PostgreSQL,
            quando disponível, registra só metadados operacionais (duração, status, contagem
            de páginas).
          </p>
        </div>
      </footer>
    </div>
  )
}
