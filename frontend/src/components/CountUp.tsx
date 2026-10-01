import { useEffect, useRef, useState } from 'react'

type CountUpProps = {
  value: number
  duration?: number
}

/** Conta do valor exibido até `value` (de 0 na montagem). */
export function CountUp({ value, duration = 900 }: CountUpProps) {
  const [shown, setShown] = useState(0)
  const shownRef = useRef(0)

  useEffect(() => {
    const from = shownRef.current
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || from === value) {
      shownRef.current = value
      const id = requestAnimationFrame(() => setShown(value))
      return () => cancelAnimationFrame(id)
    }
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const next = Math.round(from + (value - from) * (1 - Math.pow(1 - t, 3)))
      shownRef.current = next
      setShown(next)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return <>{shown}</>
}
