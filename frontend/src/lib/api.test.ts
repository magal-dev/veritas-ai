import { afterEach, describe, expect, it, vi } from 'vitest'

import { discardJob, getPreview, updateExtraction } from '@/lib/api'

function mockFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('erros da API', () => {
  it('repassa o código de erro estável do backend', async () => {
    mockFetch(json({ detail: { error_code: 'EXTRACTION_MISSING', message: 'Sem extração.' } }, 409))
    await expect(getPreview('abc')).rejects.toEqual({
      error_code: 'EXTRACTION_MISSING',
      message: 'Sem extração.',
    })
  })

  it('converte detail em texto para HTTP_ERROR', async () => {
    mockFetch(json({ detail: 'Not Found' }, 404))
    await expect(getPreview('abc')).rejects.toEqual({ error_code: 'HTTP_ERROR', message: 'Not Found' })
  })

  it('usa mensagem genérica quando a resposta não é JSON', async () => {
    mockFetch(new Response('Bad Gateway', { status: 502 }))
    await expect(getPreview('abc')).rejects.toMatchObject({ error_code: 'HTTP_ERROR' })
  })
})

describe('rotas', () => {
  it('envia a revisão via PATCH com JSON', async () => {
    const fetchMock = mockFetch(json({ job_id: 'abc' }, 200))
    const body = { time_cards: [], payslips: [], conflicts: [] }
    await updateExtraction('abc', body)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs/abc/extraction', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  })

  it('descartar sessão já expirada (404) não é erro', async () => {
    mockFetch(new Response(null, { status: 404 }))
    await expect(discardJob('abc')).resolves.toBeUndefined()
  })
})
