import { describe, expect, it } from 'vitest'

import { fieldLabel, fieldList } from '@/lib/fields'
import { toPageRanges } from '@/lib/pages'

describe('toPageRanges', () => {
  it('agrupa páginas consecutivas', () => {
    expect(toPageRanges([1, 2, 3, 5, 7, 8])).toEqual(['1–3', '5', '7–8'])
  })

  it('ordena e remove repetidas', () => {
    expect(toPageRanges([8, 2, 7, 2, 1])).toEqual(['1–2', '7–8'])
  })

  it('lista vazia não gera intervalo', () => {
    expect(toPageRanges([])).toEqual([])
  })
})

describe('fieldLabel / fieldList', () => {
  it('traduz campos conhecidos e mantém os desconhecidos', () => {
    expect(fieldLabel('clock_in')).toBe('entrada')
    expect(fieldLabel('campo_novo')).toBe('campo_novo')
    expect(fieldList(['amount', 'base_salary'])).toBe('valor, salário-base')
  })
})
