import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-rule px-3 py-1 text-[10.5px] font-medium uppercase tracking-[0.16em] text-ink-muted',
        className,
      )}
      {...props}
    />
  )
}

export { Badge }
