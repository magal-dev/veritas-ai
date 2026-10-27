import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearStoredJobId, readStoredJobId, storeJobId } from '@/lib/job-session'

function memoryStorage() {
  const values = new Map<string, string>()
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('id da sessão no navegador', () => {
  it('guarda e apaga só o identificador', () => {
    memoryStorage()
    expect(readStoredJobId()).toBe('')
    storeJobId('6f0b1c2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c')
    expect(readStoredJobId()).toBe('6f0b1c2a-3d4e-4f5a-8b6c-7d8e9f0a1b2c')
    clearStoredJobId()
    expect(readStoredJobId()).toBe('')
  })

  it('trata storage indisponível como sessão ausente', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new Error('bloqueado')
      },
      setItem: () => {
        throw new Error('bloqueado')
      },
      removeItem: () => {
        throw new Error('bloqueado')
      },
    })
    expect(readStoredJobId()).toBe('')
    expect(() => storeJobId('abc')).not.toThrow()
    expect(() => clearStoredJobId()).not.toThrow()
  })
})
