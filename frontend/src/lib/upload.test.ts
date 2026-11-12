import { describe, expect, it } from 'vitest'

import { checkUploadFiles, mergeFiles, uploadKind } from '@/lib/upload'
import { MAX_UPLOAD_FILES, MAX_UPLOAD_MB } from '@/lib/types'

function file(name: string, type = '', size = 10, lastModified = 1): File {
  const item = new File(['x'], name, { type, lastModified })
  Object.defineProperty(item, 'size', { value: size })
  return item
}

describe('tipos aceitos', () => {
  it('aceita PDF e fotos pelo tipo ou pela extensão', () => {
    expect(uploadKind(file('processo.PDF'))).toBe('pdf')
    expect(uploadKind(file('blob', 'application/pdf'))).toBe('pdf')
    expect(uploadKind(file('IMG_0001.JPG'))).toBe('image')
    expect(uploadKind(file('print', 'image/png'))).toBe('image')
    expect(uploadKind(file('foto.heic', 'image/heic'))).toBeNull()
  })
})

describe('seleção de arquivos', () => {
  it('soma arquivos novos sem repetir o mesmo', () => {
    const a = file('a.jpg', 'image/jpeg')
    const b = file('b.jpg', 'image/jpeg')
    expect(mergeFiles([a], [a, b])).toEqual([a, b])
  })

  it('aponta o arquivo de tipo não aceito', () => {
    expect(checkUploadFiles([file('a.jpg'), file('notas.txt', 'text/plain')])).toContain('notas.txt')
  })

  it('limita a quantidade e o tamanho total', () => {
    const many = Array.from({ length: MAX_UPLOAD_FILES + 1 }, (_, index) => file(`${index}.jpg`))
    expect(checkUploadFiles(many)).toContain(`${MAX_UPLOAD_FILES}`)
    const half = (MAX_UPLOAD_MB * 1024 * 1024) / 2 + 1
    expect(checkUploadFiles([file('a.pdf', '', half), file('b.pdf', '', half)])).toContain('MB')
    expect(checkUploadFiles([file('a.jpg'), file('b.pdf')])).toBeNull()
  })
})
