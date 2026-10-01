import type { Conflict, PayslipEntry, TimeCardEntry } from '@/lib/types'

/** Linha do rascunho com chave estável: data, competência e verba são editáveis. */
export type Keyed<T> = T & { _key: string }

export function withKeys<T>(rows: T[], prefix: string): Keyed<T>[] {
  return rows.map((row, index) => ({ ...row, _key: `${prefix}${index}` }))
}

export function withoutKeys<T>(rows: Keyed<T>[]): T[] {
  return rows.map((row) => Object.fromEntries(Object.entries(row).filter(([name]) => name !== '_key')) as T)
}

type ReviewedRow = { confidence: number; missing_fields: string[]; ambiguous_fields: string[] }

const TIME_FIELDS = ['clock_in', 'clock_out', 'break_start', 'break_end']

/**
 * Linha editada pelo perito: confiança 1 e sem as pendências dos campos tocados. Pares e
 * ordem da jornada envolvem todos os horários, então editar um horário limpa os quatro;
 * o validador volta a sinalizar o que continuar incoerente.
 */
export function markEdited<T extends ReviewedRow>(row: T, patch: Partial<NoInfer<T>>): T {
  const edited = Object.keys(patch)
  const touched = edited.some((name) => TIME_FIELDS.includes(name))
    ? [...edited, ...TIME_FIELDS]
    : edited
  return {
    ...row,
    ...patch,
    confidence: 1,
    missing_fields: row.missing_fields.filter((name) => !touched.includes(name)),
    ambiguous_fields: row.ambiguous_fields.filter((name) => !touched.includes(name)),
  }
}

type ParsedConflict =
  | { kind: 'time_card'; date: string }
  | { kind: 'payslip'; competence: string; itemName: string }
  | { kind: 'base_salary'; competence: string }

/** Formatos gerados pelo validador; conflitos do Gemini não seguem nenhum deles. */
export function parseConflictField(field: string): ParsedConflict | null {
  const baseSalary = /^payslips\[([^\]]+)\]\.base_salary$/.exec(field)
  if (baseSalary) {
    return { kind: 'base_salary', competence: baseSalary[1] }
  }
  const payslip = /^payslips\[([^|\]]+)\|(.+)\]$/.exec(field)
  if (payslip) {
    return { kind: 'payslip', competence: payslip[1], itemName: payslip[2] }
  }
  const timeCard = /^time_cards\[([^\]]+)\]$/.exec(field)
  if (timeCard) {
    return { kind: 'time_card', date: timeCard[1] }
  }
  return null
}

function normalizeItem(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ')
}

export function applyConflictKeepPage<T extends TimeCardEntry, P extends PayslipEntry>(
  draft: { time_cards: T[]; payslips: P[] },
  conflict: Conflict,
  keepPage: number,
): { time_cards: T[]; payslips: P[] } {
  const parsed = parseConflictField(conflict.field)
  if (parsed?.kind === 'time_card') {
    return {
      ...draft,
      time_cards: draft.time_cards.filter(
        (row) => row.date !== parsed.date || row.source_page === keepPage,
      ),
    }
  }
  if (parsed?.kind === 'payslip') {
    const itemNorm = normalizeItem(parsed.itemName)
    return {
      ...draft,
      payslips: draft.payslips.filter(
        (row) =>
          row.competence !== parsed.competence ||
          normalizeItem(row.item_name) !== itemNorm ||
          row.source_page === keepPage,
      ),
    }
  }
  return draft
}

export function applyBaseSalaryChoice<P extends PayslipEntry>(
  payslips: P[],
  competence: string,
  salary: number,
): P[] {
  return payslips.map((row) =>
    row.competence === competence ? { ...row, base_salary: salary } : row,
  )
}

export function conflictKey(conflict: Conflict): string {
  return `${conflict.field}:${conflict.source_pages.join(',')}`
}

export function formatConflictValue(value: unknown): string {
  if (typeof value === 'number') {
    return value.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    const parts = ['clock_in', 'clock_out', 'break_start', 'break_end']
      .map((key) => {
        const raw = record[key]
        if (raw == null || raw === '') return null
        return `${key.replace('clock_', '').replace('break_', 'int. ')}: ${String(raw)}`
      })
      .filter(Boolean)
    return parts.length > 0 ? parts.join(' · ') : JSON.stringify(value)
  }
  return String(value)
}

const AMOUNT_RE = /^-?(\d{1,3}(\.\d{3})+|\d+)(,\d{1,2})?$/

/** Valor no formato brasileiro (`3.500,00`, `3500,5`, `3500`); `null` se fora do formato. */
export function parseAmount(text: string): number | null {
  const cleaned = text.trim()
  if (!AMOUNT_RE.test(cleaned)) return null
  return Number(cleaned.replace(/\./g, '').replace(',', '.'))
}

export function formatAmount(value: number): string {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
