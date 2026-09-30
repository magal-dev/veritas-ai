import { Alert, AlertInfo } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type DownloadStepProps = {
  busy: boolean
  discarded: boolean
  error: string | null
  onDownload: () => void
  onRestart: () => void
}

export function DownloadStep({
  busy,
  discarded,
  error,
  onDownload,
  onRestart,
}: DownloadStepProps) {
  if (discarded) {
    return (
      <Card>
        <CardHeader>
          <svg className="mb-1 h-12 w-12 text-accent" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="24" cy="24" r="22" pathLength={1} strokeDasharray={1} className="animate-stroke" />
            <path d="M15 25l6 6 12-13" pathLength={1} strokeDasharray={1} className="animate-stroke [animation-delay:0.7s]" />
          </svg>
          <CardTitle>Sessão encerrada</CardTitle>
          <CardDescription>
            O JSON extraído foi apagado da memória. O PDF já havia sido removido do
            servidor no upload. Nenhum dado processual permanece neste sistema.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" onClick={onRestart}>
            Nova sessão
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Baixar a planilha provisória</CardTitle>
        <CardDescription>
          O arquivo segue o layout hipotético <code>provisional-0.1</code>, não o modelo
          oficial do PJe-Calc. Depois do download, esta sessão é descartada.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <AlertInfo>
          A planilha sai com as abas CartaoPonto, Holerite e MetadadosSessao. As duas
          primeiras vêm só com o cabeçalho enquanto a extração não estiver ligada.
        </AlertInfo>
        {error && <Alert>{error}</Alert>}
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="button" size="lg" disabled={busy} onClick={onDownload}>
            {busy ? 'Gerando…' : 'Baixar Excel e descartar'}
          </Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={onRestart}>
            Cancelar e recomeçar
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
