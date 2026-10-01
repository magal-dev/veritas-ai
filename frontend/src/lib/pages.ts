/** Agrupa páginas consecutivas: [1, 2, 3, 5, 7, 8] -> ["1–3", "5", "7–8"]. */
export function toPageRanges(pages: number[]): string[] {
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  const ranges: string[] = []
  let start = sorted[0]
  let previous = sorted[0]
  for (const page of sorted.slice(1)) {
    if (page === previous + 1) {
      previous = page
      continue
    }
    ranges.push(start === previous ? `${start}` : `${start}–${previous}`)
    start = page
    previous = page
  }
  if (start !== undefined) ranges.push(start === previous ? `${start}` : `${start}–${previous}`)
  return ranges
}
