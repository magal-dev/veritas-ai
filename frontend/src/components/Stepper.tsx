import { cn } from '@/lib/utils'

const STEPS = [
  { id: 'upload', label: 'Upload' },
  { id: 'processing', label: 'Processamento' },
  { id: 'review', label: 'Revisão' },
  { id: 'download', label: 'Download' },
] as const

export type FlowStep = (typeof STEPS)[number]['id']

const ORDER: FlowStep[] = ['upload', 'processing', 'review', 'download']

type StepperProps = {
  current: FlowStep
}

export function Stepper({ current }: StepperProps) {
  const currentIndex = ORDER.indexOf(current)

  return (
    <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {STEPS.map((step, index) => {
        const done = index < currentIndex
        const active = index === currentIndex
        return (
          <li
            key={step.id}
            className={cn(
              'rounded-lg border px-3 py-2 text-sm',
              active && 'border-accent bg-accent/10 text-ink',
              done && 'border-accent/40 bg-white text-accent',
              !active && !done && 'border-rule bg-paper-2 text-ink-muted',
            )}
          >
            <span className="block text-[11px] uppercase tracking-wider opacity-70">
              Etapa {index + 1}
            </span>
            <span className="font-medium">{step.label}</span>
          </li>
        )
      })}
    </ol>
  )
}
