import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type ProcessingStepProps = {
  fileName: string
}

export function ProcessingStep({ fileName }: ProcessingStepProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Processando na sessão</CardTitle>
        <CardDescription>
          O PDF não permanece no servidor. Nesta fundação, o pipeline só conta páginas
          e devolve um JSON vazio — as camadas de triagem e o Gemini entram depois.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col items-center gap-5 py-8" role="status" aria-live="polite">
        <span className="relative flex h-24 w-24 items-center justify-center">
          <svg className="absolute inset-0 h-full w-full animate-[spin_9s_linear_infinite]" viewBox="0 0 100 100" aria-hidden>
            <circle cx="50" cy="50" r="48" fill="none" stroke="var(--color-rule)" strokeWidth="0.75" />
            <circle cx="50" cy="50" r="48" fill="none" stroke="var(--color-burgundy)" strokeWidth="1.25" strokeDasharray="30 272" strokeLinecap="round" />
          </svg>
          <img src="/logo.png" alt="" className="h-14 w-14 animate-seal rounded-full object-contain" />
        </span>
        <p className="text-center text-sm text-ink-muted">
          <span className="eyebrow mr-2">Lendo</span>
          <span className="font-display text-xl text-ink">{fileName}</span>
        </p>
        <div className="h-1 w-full max-w-xs overflow-hidden rounded-full bg-rule">
          <div className="h-full w-1/2 animate-indeterminate rounded-full bg-accent" />
        </div>
      </CardContent>
    </Card>
  )
}
