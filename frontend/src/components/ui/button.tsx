import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex cursor-pointer items-center justify-center gap-2 rounded-main text-sm font-medium tracking-wide transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-paper-2 active:translate-y-px disabled:pointer-events-none disabled:opacity-45',
  {
    variants: {
      variant: {
        default:
          'bg-accent text-paper shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_6px_16px_-8px_rgba(95,28,28,0.7)] hover:bg-accent-hover hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_10px_22px_-8px_rgba(95,28,28,0.8)]',
        secondary:
          'bg-paper-2 text-ink border border-rule hover:border-accent/50 hover:bg-white',
        ghost: 'text-ink-muted hover:bg-ink/5 hover:text-ink',
        danger: 'bg-danger text-paper-2 hover:bg-danger/90',
      },
      size: {
        default: 'h-10 px-4 py-2',
        lg: 'h-11 px-6',
        sm: 'h-8 px-3 text-xs',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />
  )
}

export { Button, buttonVariants }
