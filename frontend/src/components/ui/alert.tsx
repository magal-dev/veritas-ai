import { CircleAlert, Info } from 'lucide-react'
import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

function Alert({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="alert"
      className={cn(
        'flex animate-rise items-start gap-3 rounded-main border border-danger/35 bg-danger/8 px-4 py-3 text-sm text-danger',
        className,
      )}
      {...props}
    >
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

function AlertInfo({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-main border border-accent/20 bg-accent/6 px-4 py-3 text-sm leading-relaxed text-ink',
        className,
      )}
      {...props}
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
      <div>{children}</div>
    </div>
  )
}

export { Alert, AlertInfo }
