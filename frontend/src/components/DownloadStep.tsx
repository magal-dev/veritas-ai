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
        <CardTitle>Baixar os arquivos do PJe-Calc</CardTitle>
        <CardDescription>
          Um .zip com os CSVs que o PJe-Calc Cidadão importa e um LEIA-ME com os passos.
          Depois do download, esta sessão é descartada.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <AlertInfo>
          O cartão de ponto vai na aba Importar Jornada (cadastre antes a apuração com o
          período do contrato). Cada verba do holerite vira um arquivo para importar em seu
          próprio Histórico Salarial. Revise os dados no PJe-Calc depois de importar.
        </AlertInfo>
        {error && <Alert>{error}</Alert>}
        <div className="flex flex-col gap-3 sm:flex-row">
          <Button type="button" size="lg" disabled={busy} onClick={onDownload}>
            {busy ? 'Gerando…' : 'Baixar arquivos e descartar'}
          </Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={onRestart}>
            Cancelar e recomeçar
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
