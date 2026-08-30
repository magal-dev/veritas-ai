import { LoaderCircle } from 'lucide-react'

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
      <CardContent className="flex flex-col items-center gap-4 py-8">
        <LoaderCircle className="h-10 w-10 animate-spin text-accent" aria-hidden />
        <p className="text-sm text-ink-muted text-center">
          Lendo <span className="text-ink font-medium">{fileName}</span>
        </p>
      </CardContent>
    </Card>
  )
}
