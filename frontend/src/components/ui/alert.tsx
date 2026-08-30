import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

function Alert({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="alert"
      className={cn(
        'rounded-lg border border-danger/30 bg-danger/8 px-4 py-3 text-sm text-danger',
        className,
      )}
      {...props}
    />
  )
}

function AlertInfo({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'rounded-lg border border-accent/25 bg-accent/8 px-4 py-3 text-sm text-ink leading-relaxed',
        className,
      )}
      {...props}
    />
  )
}

export { Alert, AlertInfo }
