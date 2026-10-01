import type { ReactNode } from 'react'

import { useInView } from '@/lib/use-in-view'
import { cn } from '@/lib/utils'

type RevealProps = {
  children: ReactNode
  className?: string
  delay?: number
}

/** Entrada `rise` disparada quando o bloco chega à viewport. */
export function Reveal({ children, className, delay = 0 }: RevealProps) {
  const { ref, inView } = useInView<HTMLDivElement>()
  return (
    <div
      ref={ref}
      className={cn(inView ? 'animate-rise' : 'opacity-0', className)}
      style={inView && delay ? { animationDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  )
}
