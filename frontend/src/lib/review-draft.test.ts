import { describe, expect, it } from 'vitest'

import {
  applyBaseSalaryChoice,
  applyConflictKeepPage,
  conflictKey,
  formatAmount,
  formatConflictValue,
  markEdited,
  parseAmount,
  parseConflictField,
  withKeys,
  withoutKeys,
} from '@/lib/review-draft'
import type { Conflict, PayslipEntry, TimeCardEntry } from '@/lib/types'

function timeCard(overrides: Partial<TimeCardEntry> = {}): TimeCardEntry {
  return {
    date: '2024-03-01',
    competence: '2024-03',
    clock_in: '08:00',
    clock_out: '17:00',
    break_start: '12:00',
    break_end: '13:00',
    source_page: 3,
    confidence: 0.7,
    missing_fields: [],
    ambiguous_fields: [],
    ...overrides,
  }
}

function payslip(overrides: Partial<PayslipEntry> = {}): PayslipEntry {
  return {
    competence: '2024-04',
    item_name: 'Salário Base',
    amount: 3200,
    base_salary: 3200,
    source_page: 2,
    confidence: 0.8,
    missing_fields: [],
    ambiguous_fields: [],
    ...overrides,
  }
}

function conflict(field: string, sourcePages: number[] = [2, 5]): Conflict {
  return { field, values: [], source_pages: sourcePages, note: null }
}

describe('withKeys / withoutKeys', () => {
  it('adiciona chave estável e a remove sem perder campos', () => {
    const rows = [timeCard(), timeCard({ date: '2024-03-02' })]
    const keyed = withKeys(rows, 'tc')
    expect(keyed.map((row) => row._key)).toEqual(['tc0', 'tc1'])
    expect(withoutKeys(keyed)).toEqual(rows)
  })
})

describe('markEdited', () => {
  it('fixa confiança 1 e limpa só as pendências do campo editado', () => {
    const row = payslip({ missing_fields: ['amount', 'base_salary'], ambiguous_fields: ['item_name'] })
    const edited = markEdited(row, { amount: 3300 })
    expect(edited.amount).toBe(3300)
    expect(edited.confidence).toBe(1)
    expect(edited.missing_fields).toEqual(['base_salary'])
    expect(edited.ambiguous_fields).toEqual(['item_name'])
  })

  it('editar um horário limpa as pendências dos quatro horários', () => {
    const row = timeCard({
      missing_fields: ['clock_out', 'competence'],
      ambiguous_fields: ['break_start', 'break_end'],
    })
    const edited = markEdited(row, { clock_in: '07:55' })
    expect(edited.missing_fields).toEqual(['competence'])
    expect(edited.ambiguous_fields).toEqual([])
  })

  it('não altera a linha original', () => {
    const row = timeCard({ missing_fields: ['clock_out'] })
    markEdited(row, { clock_out: '17:10' })
    expect(row.missing_fields).toEqual(['clock_out'])
    expect(row.confidence).toBe(0.7)
  })
})

describe('parseConflictField', () => {
  it('reconhece os formatos gerados pelo validador', () => {
    expect(parseConflictField('time_cards[2024-03-01]')).toEqual({ kind: 'time_card', date: '2024-03-01' })
    expect(parseConflictField('payslips[2024-04|Horas Extras 50%]')).toEqual({
      kind: 'payslip',
      competence: '2024-04',
      itemName: 'Horas Extras 50%',
    })
    expect(parseConflictField('payslips[2024-04].base_salary')).toEqual({
      kind: 'base_salary',
      competence: '2024-04',
    })
  })

  it('devolve null para conflitos livres do Gemini', () => {
    expect(parseConflictField('clock_out')).toBeNull()
    expect(parseConflictField('')).toBeNull()
  })
})

describe('applyConflictKeepPage', () => {
  it('mantém só a página escolhida para a data em conflito', () => {
    const draft = {
      time_cards: [
        timeCard({ source_page: 3 }),
        timeCard({ source_page: 7, clock_out: '18:00' }),
        timeCard({ date: '2024-03-02', source_page: 7 }),
      ],
      payslips: [payslip()],
    }
    const result = applyConflictKeepPage(draft, conflict('time_cards[2024-03-01]', [3, 7]), 7)
    expect(result.time_cards.map((row) => [row.date, row.source_page])).toEqual([
      ['2024-03-01', 7],
      ['2024-03-02', 7],
    ])
    expect(result.payslips).toBe(draft.payslips)
  })

  it('compara verbas sem acento, caixa ou espaços extras', () => {
    const draft = {
      time_cards: [],
      payslips: [
        payslip({ item_name: 'Salário  Base', source_page: 2 }),
        payslip({ item_name: 'SALARIO BASE', source_page: 5, amount: 3250 }),
        payslip({ item_name: 'INSS', source_page: 5, amount: 412.47 }),
        payslip({ competence: '2024-05', source_page: 9 }),
      ],
    }
    const result = applyConflictKeepPage(draft, conflict('payslips[2024-04|salario base]'), 5)
    expect(result.payslips.map((row) => [row.item_name, row.source_page])).toEqual([
      ['SALARIO BASE', 5],
      ['INSS', 5],
      ['Salário Base', 9],
    ])
  })

  it('não mexe no rascunho para conflito sem formato conhecido', () => {
    const draft = { time_cards: [timeCard()], payslips: [payslip()] }
    expect(applyConflictKeepPage(draft, conflict('clock_out'), 3)).toBe(draft)
  })
})

describe('applyBaseSalaryChoice', () => {
  it('aplica o salário-base só na competência escolhida', () => {
    const rows = [payslip(), payslip({ item_name: 'INSS' }), payslip({ competence: '2024-05' })]
    const result = applyBaseSalaryChoice(rows, '2024-04', 3300)
    expect(result.map((row) => row.base_salary)).toEqual([3300, 3300, 3200])
  })
})

describe('conflictKey', () => {
  it('distingue o mesmo campo em páginas diferentes', () => {
    expect(conflictKey(conflict('time_cards[2024-03-01]', [3, 7]))).not.toBe(
      conflictKey(conflict('time_cards[2024-03-01]', [3, 8])),
    )
  })
})

describe('formatConflictValue', () => {
  it('formata número como moeda brasileira', () => {
    expect(formatConflictValue(3500)).toMatch(/R\$\s*3\.500,00/)
  })

  it('resume a jornada e omite horários vazios', () => {
    expect(formatConflictValue({ clock_in: '08:00', clock_out: '17:00', break_start: '', break_end: null })).toBe(
      'in: 08:00 · out: 17:00',
    )
  })

  it('cai para JSON quando o objeto não tem horários', () => {
    expect(formatConflictValue({ foo: 1 })).toBe('{"foo":1}')
    expect(formatConflictValue('texto')).toBe('texto')
  })
})

describe('parseAmount / formatAmount', () => {
  it.each([
    ['3.500,00', 3500],
    ['3500,5', 3500.5],
    ['3500', 3500],
    [' 1.234.567,89 ', 1234567.89],
    ['-98,55', -98.55],
  ])('lê %s', (text, expected) => {
    expect(parseAmount(text)).toBe(expected)
  })

  it.each(['3,500.00', '35.00,00', 'abc', '', '1,234'])('rejeita %s', (text) => {
    expect(parseAmount(text)).toBeNull()
  })

  it('faz ida e volta no formato brasileiro', () => {
    expect(formatAmount(3500)).toBe('3.500,00')
    expect(parseAmount(formatAmount(1234.5))).toBe(1234.5)
  })
})
