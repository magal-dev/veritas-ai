/** Nomes em pt-BR dos campos do schema de extração (docs/SCHEMA_EXTRACAO.md). */
const FIELD_LABELS: Record<string, string> = {
  date: 'data',
  competence: 'competência',
  clock_in: 'entrada',
  clock_out: 'saída',
  break_start: 'início do intervalo',
  break_end: 'fim do intervalo',
  item_name: 'verba',
  amount: 'valor',
  base_salary: 'salário-base',
  overtime_paid_hours: 'horas extras pagas',
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field
}

export function fieldList(fields: string[]): string {
  return fields.map(fieldLabel).join(', ')
}
