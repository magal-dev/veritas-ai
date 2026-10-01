export type JobStatus =
  | 'accepted'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'discarded'
  | 'expired'

export type TimeCardEntry = {
  date: string
  competence: string | null
  clock_in: string | null
  clock_out: string | null
  break_start: string | null
  break_end: string | null
  source_page: number
  source_excerpt?: string | null
  confidence: number
  missing_fields: string[]
  ambiguous_fields: string[]
}

export type PayslipEntry = {
  competence: string
  item_name: string
  amount: number
  base_salary?: number | null
  overtime_paid_hours?: number | null
  source_page: number
  source_excerpt?: string | null
  confidence: number
  missing_fields: string[]
  ambiguous_fields: string[]
}

export type ExtractionUpdateBody = {
  time_cards: TimeCardEntry[]
  payslips: PayslipEntry[]
  /** Conflitos do Gemini ainda abertos; os entre páginas o backend recalcula. */
  conflicts: Conflict[]
}

export type Conflict = {
  field: string
  values: unknown[]
  source_pages: number[]
  note: string | null
}

export type ExtractionResult = {
  schema_version: string
  job_id: string
  time_cards: TimeCardEntry[]
  payslips: PayslipEntry[]
  unclassified_candidate_pages: number[]
  missing_fields: string[]
  ambiguous_fields: string[]
  conflicts: Conflict[]
  pdf_page_count: number
  candidate_page_count: number
  gemini_call_count: number
}

export type JobCreated = {
  job_id: string
  status: JobStatus
  pdf_page_count: number
  message: string
}

export type JobStatusResponse = {
  job_id: string
  status: JobStatus
  pdf_page_count: number
  candidate_page_count: number
  gemini_call_count: number
  created_at: string
  error_code: string | null
  pipeline_note: string
}

export type JobPreviewResponse = {
  job_id: string
  status: JobStatus
  extraction: ExtractionResult
}

export type ApiError = {
  error_code: string
  message: string
}

export const MAX_UPLOAD_MB = 80
