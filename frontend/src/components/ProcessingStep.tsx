import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import { useEffect, useState } from 'react'

type ProcessingStepProps = {
  fileName: string
}

function useElapsed() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => window.clearInterval(id)
  }, [])
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0')
  const ss = String(seconds % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

export function ProcessingStep({ fileName }: ProcessingStepProps) {
  const elapsed = useElapsed()
  return (
    <Card className="relative overflow-hidden">
      <CardHeader className="relative">
        <CardTitle>Processando na sessão</CardTitle>
        <CardDescription>
          O PDF não permanece no servidor. A triagem local e a classificação Gemini
          rodam nesta sessão — os dados ficam só em memória.
        </CardDescription>
      </CardHeader>
      <CardContent className="relative flex flex-col items-center gap-5 py-8" role="status" aria-live="polite">
        <span className="relative flex h-24 w-24 items-center justify-center">
          <span aria-hidden className="absolute inset-2 animate-halo rounded-full bg-[radial-gradient(closest-side,color-mix(in_srgb,var(--color-accent)_18%,transparent),transparent)]" />
          <span aria-hidden className="absolute inset-4 animate-ripple rounded-full border border-accent/40" />
          <span aria-hidden className="absolute inset-4 animate-ripple rounded-full border border-accent/40 [animation-delay:1.2s]" />
          <span aria-hidden className="absolute inset-4 animate-ripple rounded-full border border-accent/40 [animation-delay:2.4s]" />
          <img src="/logo.png" alt="" className="relative h-14 w-14 animate-breathe-logo rounded-full object-contain" />
        </span>
        <p className="relative text-center text-sm text-ink-muted">
          <span className="eyebrow mr-2">Lendo</span>
          <span className="font-display text-xl text-ink">{fileName}</span>
        </p>
        <div className="relative h-px w-full max-w-xs overflow-hidden bg-rule">
          <div className="h-full w-1/2 animate-indeterminate bg-accent" />
        </div>
        <p className="relative eyebrow tabular-nums text-ink-muted">Tempo de sessão · {elapsed}</p>
      </CardContent>
    </Card>
  )
}
