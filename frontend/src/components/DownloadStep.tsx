import { ShieldCheck } from 'lucide-react'

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
          <span className="mb-2 flex h-11 w-11 animate-pop items-center justify-center rounded-full bg-accent text-paper">
            <ShieldCheck className="h-5 w-5" aria-hidden />
          </span>
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
