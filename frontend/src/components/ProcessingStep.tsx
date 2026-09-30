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
      <span
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 aspect-square w-[max(160%,40rem)] -translate-x-1/2 -translate-y-1/2"
      >
        <span className="block h-full w-full animate-breathe rounded-full bg-[radial-gradient(closest-side,rgba(95,28,28,0.22),rgba(95,28,28,0.08)_55%,transparent)]" />
      </span>
      <CardHeader className="relative">
        <CardTitle>Processando na sessão</CardTitle>
        <CardDescription>
          O PDF não permanece no servidor. Nesta fundação, o pipeline só conta páginas
          e devolve um JSON vazio — as camadas de triagem e o Gemini entram depois.
        </CardDescription>
      </CardHeader>
      <CardContent className="relative flex flex-col items-center gap-5 py-8" role="status" aria-live="polite">
        <span className="relative flex h-24 w-24 items-center justify-center">
          <img src="/logo.png" alt="" className="h-14 w-14 animate-breathe-logo rounded-full object-contain" />
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
