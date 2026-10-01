import type { Conflict, PayslipEntry, TimeCardEntry } from '@/lib/types'

export type ReviewDraft = {
  time_cards: TimeCardEntry[]
  payslips: PayslipEntry[]
}

type ParsedConflict =
  | { kind: 'time_card'; date: string }
  | { kind: 'payslip'; competence: string; itemName: string }
  | { kind: 'base_salary'; competence: string }

export function parseConflictField(field: string): ParsedConflict | null {
  const baseSalary = /^payslips\[([^\]]+)\]\.base_salary$/.exec(field)
  if (baseSalary) {
    return { kind: 'base_salary', competence: baseSalary[1] }
  }
  const payslip = /^payslips\[([^|]+)\|(.+)\]$/.exec(field)
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

export function applyConflictKeepPage(
  draft: ReviewDraft,
  conflict: Conflict,
  keepPage: number,
): ReviewDraft {
  const parsed = parseConflictField(conflict.field)
  if (!parsed) {
    return draft
  }
  if (parsed.kind === 'time_card') {
    return {
      ...draft,
      time_cards: draft.time_cards.filter(
        (row) => row.date !== parsed.date || row.source_page === keepPage,
      ),
    }
  }
  if (parsed.kind === 'payslip') {
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

export function applyBaseSalaryChoice(
  payslips: PayslipEntry[],
  competence: string,
  salary: number,
): PayslipEntry[] {
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
