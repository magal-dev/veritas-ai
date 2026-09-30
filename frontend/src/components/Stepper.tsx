import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

const STEPS = [
  { id: 'upload', label: 'Upload', numeral: 'I' },
  { id: 'processing', label: 'Processamento', numeral: 'II' },
  { id: 'review', label: 'Revisão', numeral: 'III' },
  { id: 'download', label: 'Download', numeral: 'IV' },
] as const

export type FlowStep = (typeof STEPS)[number]['id']

const ORDER: FlowStep[] = ['upload', 'processing', 'review', 'download']

type StepperProps = {
  current: FlowStep
}

export function Stepper({ current }: StepperProps) {
  const currentIndex = ORDER.indexOf(current)

  return (
    <nav aria-label="Etapas do fluxo">
      <ol className="grid grid-cols-4 gap-x-4">
        {STEPS.map((step, index) => {
          const done = index < currentIndex
          const active = index === currentIndex
          return (
            <li key={step.id} aria-current={active ? 'step' : undefined} className="flex flex-col gap-3">
              <span className="relative block h-px bg-rule">
                {(done || active) && (
                  <span className="absolute inset-0 block origin-left animate-draw bg-accent" />
                )}
                <span
                  className={cn(
                    'absolute -top-[3px] left-0 block h-[7px] w-[7px] rotate-45 border transition-all duration-500',
                    done || active ? 'border-accent bg-accent' : 'border-rule bg-paper',
                    active && 'scale-150',
                  )}
                />
              </span>
              <span className="flex items-baseline gap-2">
                <span
                  className={cn(
                    'font-display text-2xl italic leading-none transition-colors duration-500',
                    done || active ? 'text-accent' : 'text-ink-muted/60',
                  )}
                >
                  {done ? <Check key="done" className="inline h-4 w-4 animate-pop" aria-hidden /> : step.numeral}
                </span>
                <span
                  className={cn(
                    'text-[11px] font-medium uppercase tracking-[0.18em] transition-colors duration-500',
                    active ? 'text-ink' : 'text-ink-muted',
                  )}
                >
                  {step.label}
                </span>
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
