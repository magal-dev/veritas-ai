import { ThemeToggle } from '@/components/ThemeToggle'
import { Badge } from '@/components/ui/badge'

type BrandBarProps = {
  /** Quando presente, a marca vira um botão de volta à apresentação. */
  onHome?: () => void
}

export function BrandBar({ onHome }: BrandBarProps) {
  const brand = (
    <>
      <img src="/logo-light.png" alt="" className="h-9 w-9 animate-pop object-contain" />
      <span className="font-display text-2xl tracking-[0.04em] animate-fade [animation-delay:200ms]">
        Veritas AI
      </span>
    </>
  )

  return (
    <div className="flex items-center justify-between gap-4">
      {onHome ? (
        <button
          type="button"
          onClick={onHome}
          title="Voltar à apresentação"
          className="flex cursor-pointer items-center gap-3 rounded-main text-offwhite transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offwhite/70"
        >
          {brand}
        </button>
      ) : (
        <div className="flex items-center gap-3">{brand}</div>
      )}
      <div className="flex items-center gap-3">
        <Badge className="animate-fade border-offwhite/30 text-offwhite/80 [animation-delay:400ms]">
          Fundação 0.1
        </Badge>
        <ThemeToggle />
      </div>
    </div>
  )
}
