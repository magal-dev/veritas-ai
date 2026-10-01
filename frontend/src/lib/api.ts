import type {
  ApiError,
  ExtractionUpdateBody,
  JobCreated,
  JobPreviewResponse,
  JobStatusResponse,
} from '@/lib/types'

async function parseError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as { detail?: ApiError | string }
    if (payload.detail && typeof payload.detail === 'object') {
      return payload.detail
    }
    if (typeof payload.detail === 'string') {
      return { error_code: 'HTTP_ERROR', message: payload.detail }
    }
  } catch {
    /* ignore */
  }
  return {
    error_code: 'HTTP_ERROR',
    message: 'Não foi possível concluir a operação. Tente novamente.',
  }
}

export async function createJob(file: File): Promise<JobCreated> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch('/api/v1/jobs', { method: 'POST', body })
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as JobCreated
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(`/api/v1/jobs/${jobId}`)
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as JobStatusResponse
}

export async function getPreview(jobId: string): Promise<JobPreviewResponse> {
  const response = await fetch(`/api/v1/jobs/${jobId}/preview`)
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as JobPreviewResponse
}

export async function updateExtraction(
  jobId: string,
  body: ExtractionUpdateBody,
): Promise<JobPreviewResponse> {
  const response = await fetch(`/api/v1/jobs/${jobId}/extraction`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw await parseError(response)
  }
  return (await response.json()) as JobPreviewResponse
}

export async function downloadExcel(jobId: string): Promise<Blob> {
  const response = await fetch(`/api/v1/jobs/${jobId}/excel`)
  if (!response.ok) {
    throw await parseError(response)
  }
  return await response.blob()
}

export async function discardJob(jobId: string): Promise<void> {
  const response = await fetch(`/api/v1/jobs/${jobId}`, { method: 'DELETE' })
  if (!response.ok && response.status !== 404) {
    throw await parseError(response)
  }
}
