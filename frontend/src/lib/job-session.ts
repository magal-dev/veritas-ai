/** Só o UUID da sessão. O conteúdo do processo não entra no navegador. */

const STORAGE_KEY = 'veritas.jobId'

export function readStoredJobId(): string {
  try {
    return sessionStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function storeJobId(jobId: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, jobId)
  } catch {
    /* sessão privada ou storage bloqueado: a revisão segue até o reload */
  }
}

export function clearStoredJobId(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* idem */
  }
}
