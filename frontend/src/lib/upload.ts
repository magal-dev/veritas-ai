import { MAX_UPLOAD_FILES, MAX_UPLOAD_MB } from '@/lib/types'

const PDF_TYPES = new Set(['application/pdf', 'application/x-pdf'])
const IMAGE_TYPES = new Set(['image/jpeg', 'image/jpg', 'image/pjpeg', 'image/png', 'image/webp'])
const PDF_EXTENSIONS = ['.pdf']
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']

/** Mesmas regras de `backend/services/upload_bundle.py::detect_kind`. */
export function uploadKind(file: Pick<File, 'name' | 'type'>): 'pdf' | 'image' | null {
  const name = file.name.toLowerCase()
  const type = file.type.toLowerCase()
  if (PDF_TYPES.has(type) || PDF_EXTENSIONS.some((ext) => name.endsWith(ext))) return 'pdf'
  if (IMAGE_TYPES.has(type) || IMAGE_EXTENSIONS.some((ext) => name.endsWith(ext))) return 'image'
  return null
}

/** Soma os arquivos novos à seleção, sem repetir o mesmo arquivo. */
export function mergeFiles(current: File[], incoming: File[]): File[] {
  const key = (file: File) => `${file.name}|${file.size}|${file.lastModified}`
  const seen = new Set(current.map(key))
  const merged = [...current]
  for (const file of incoming) {
    if (!seen.has(key(file))) {
      seen.add(key(file))
      merged.push(file)
    }
  }
  return merged
}

/** Mensagem do problema da seleção, ou null se ela pode ser enviada. */
export function checkUploadFiles(files: Pick<File, 'name' | 'type' | 'size'>[]): string | null {
  const invalid = files.find((file) => uploadKind(file) === null)
  if (invalid) {
    return `"${invalid.name}" não é PDF nem foto (JPG, PNG ou WEBP). Fotos do iPhone em HEIC: exporte como JPG.`
  }
  if (files.length > MAX_UPLOAD_FILES) {
    return `Envie no máximo ${MAX_UPLOAD_FILES} arquivos por vez.`
  }
  const total = files.reduce((sum, file) => sum + file.size, 0)
  if (total > MAX_UPLOAD_MB * 1024 * 1024) {
    return `Os arquivos somam mais de ${MAX_UPLOAD_MB} MB.`
  }
  return null
}
