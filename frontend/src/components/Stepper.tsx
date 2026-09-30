import { Check } from 'lucide-react'

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
  const progress = (currentIndex / (STEPS.length - 1)) * 100

  return (
    <nav aria-label="Etapas do fluxo">
      <ol className="relative grid grid-cols-4">
        <span
          aria-hidden
          className="absolute left-[12.5%] right-[12.5%] top-[17px] h-px bg-rule"
        />
        <span
          aria-hidden
          className="absolute left-[12.5%] top-[17px] h-px bg-accent transition-[width] duration-700 ease-out"
          style={{ width: `${progress * 0.75}%` }}
        />
        {STEPS.map((step, index) => {
          const done = index < currentIndex
          const active = index === currentIndex
          return (
            <li
              key={step.id}
              aria-current={active ? 'step' : undefined}
              className="relative flex flex-col items-center gap-2 text-center"
            >
              <span
                className={cn(
                  'relative z-10 flex h-9 w-9 items-center justify-center rounded-full border text-sm font-medium transition-all duration-500',
                  done && 'border-accent bg-accent text-paper',
                  active && 'border-accent bg-paper-2 text-accent ring-4 ring-accent/12',
                  !active && !done && 'border-rule bg-paper-2 text-ink-muted',
                )}
              >
                {done ? <Check key="done" className="h-4 w-4 animate-pop" aria-hidden /> : index + 1}
              </span>
              <span
                className={cn(
                  'text-xs font-medium tracking-wide transition-colors duration-500 sm:text-sm',
                  active ? 'text-ink' : done ? 'text-accent' : 'text-ink-muted',
                )}
              >
                {step.label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
