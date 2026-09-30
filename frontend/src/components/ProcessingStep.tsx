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
        <span className="flex h-16 w-16 animate-seal items-center justify-center rounded-full border border-accent/30 bg-accent/8">
          <img src="/logo.png" alt="" className="h-9 w-9 object-contain" />
        </span>
        <p className="text-center text-sm text-ink-muted">
          Lendo <span className="font-medium text-ink">{fileName}</span>
        </p>
        <div className="h-1 w-full max-w-xs overflow-hidden rounded-full bg-rule">
          <div className="h-full w-1/2 animate-indeterminate rounded-full bg-accent" />
        </div>
      </CardContent>
    </Card>
  )
}
