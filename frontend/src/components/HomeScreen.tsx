import { ArrowDown, ArrowRight, Check } from 'lucide-react'

import { BrandBar } from '@/components/BrandBar'
import { CountUp } from '@/components/CountUp'
import { Reveal } from '@/components/Reveal'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useInView } from '@/lib/use-in-view'
import { cn } from '@/lib/utils'

type HomeScreenProps = {
  onStart: () => void
}

const TITLE: { text: string; italic?: boolean; br?: boolean }[] = [
  { text: 'Do' },
  { text: 'processo' },
  { text: 'à' },
  { text: 'planilha,', br: true },
  { text: 'sem', italic: true },
  { text: 'reter', italic: true },
  { text: 'nada.', italic: true },
]

const MOVEMENTS = [
  {
    numeral: 'I',
    title: 'Triagem local',
    body:
      'Todas as páginas são lidas no servidor, sem custo de API. Palavras-chave, horários, valores e o sumário do PDF apontam as candidatas; páginas escaneadas são pontuadas pelo aspecto de tabela.',
  },
  {
    numeral: 'II',
    title: 'Leitura assistida',
    body:
      'Só as candidatas seguem ao Gemini, em lotes paralelos. Cada página é classificada como cartão de ponto ou holerite e convertida em registros com confiança e página de origem.',
  },
  {
    numeral: 'III',
    title: 'Revisão humana',
    body:
      'Formato, coerência da jornada, duplicatas e conflitos entre páginas são sinalizados. Você corrige na própria tabela; a planilha só é liberada sem conflitos abertos.',
  },
  {
    numeral: 'IV',
    title: 'Planilha e descarte',
    body:
      'O Excel é gerado sob demanda, entregue e apagado. O JSON extraído deixa a memória. Nenhum dado processual sobrevive à sessão.',
  },
]

const FIGURES = [
  { value: 3, label: 'camadas de triagem antes de qualquer IA' },
  { value: 25, label: 'páginas candidatas, no máximo, por processo' },
  { value: 5, label: 'chamadas ao Gemini, no máximo, em paralelo' },
  { value: 0, label: 'dados processuais retidos após o download' },
]

const ABSENCES = [
  'Sem contas, cadastro ou histórico de extrações',
  'PDF apagado assim que o processamento termina',
  'Excel apagado logo após o download',
  'Banco apenas com metadados operacionais',
]

/* Mosaico de páginas: 6 × 8 folhas, poucas acendem como candidatas. */
const COLS = 6
const ROWS = 8
const CANDIDATES = new Set([9, 10, 11, 26, 27, 40])
const SCAN_START = 0.9
const SCAN_DURATION = 2.6

function PageLattice() {
  return (
    <figure className="flex flex-col gap-4" aria-label="Ilustração: entre muitas páginas, poucas são selecionadas para leitura">
      <div className="relative overflow-hidden rounded-main border border-offwhite/20 p-4 sm:p-5">
        <div className="grid grid-cols-6 gap-2 sm:gap-2.5">
          {Array.from({ length: COLS * ROWS }, (_, index) => {
            const row = Math.floor(index / COLS)
            const hit = CANDIDATES.has(index)
            const lit = SCAN_START + (row / ROWS) * SCAN_DURATION
            return (
              <span
                key={index}
                aria-hidden
                className="relative block aspect-[3/4] animate-fade rounded-[2px] border border-offwhite/15 bg-offwhite/[0.03]"
                style={{ animationDelay: `${150 + index * 12}ms` }}
              >
                <span className="absolute inset-x-[18%] top-[22%] block h-px bg-offwhite/15" />
                <span className="absolute inset-x-[18%] top-[38%] block h-px bg-offwhite/10" />
                <span className="absolute inset-x-[18%] top-[54%] block h-px w-[40%] bg-offwhite/10" />
                {hit && (
                  <span
                    className="absolute -inset-px block animate-pop rounded-[2px] bg-offwhite shadow-[0_0_24px_-2px_rgba(236,231,211,0.55)]"
                    style={{ animationDelay: `${lit}s` }}
                  >
                    {[22, 34, 46, 58, 70].map((top) => (
                      <span
                        key={top}
                        className="absolute inset-x-[16%] block h-px bg-burgundy/40"
                        style={{ top: `${top}%` }}
                      />
                    ))}
                  </span>
                )}
              </span>
            )
          })}
        </div>
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 block h-full animate-scan"
          style={{ animationDelay: `${SCAN_START}s`, animationDuration: `${SCAN_DURATION}s` }}
        >
          <span className="block h-px bg-offwhite/70 shadow-[0_0_16px_2px_rgba(236,231,211,0.45)]" />
        </span>
      </div>
      <figcaption className="eyebrow flex flex-wrap items-center gap-x-3 gap-y-1 text-offwhite/60">
        <span>48 páginas</span>
        <ArrowRight className="h-3 w-3" aria-hidden />
        <span className="text-offwhite">6 candidatas</span>
        <ArrowRight className="h-3 w-3" aria-hidden />
        <span>2 chamadas</span>
      </figcaption>
    </figure>
  )
}

function Figures() {
  const { ref, inView } = useInView<HTMLDListElement>(0.4)
  return (
    <dl ref={ref} className="grid grid-cols-2 gap-x-6 gap-y-10 lg:grid-cols-4">
      {FIGURES.map((figure, index) => (
        <div
          key={figure.label}
          className={cn('flex flex-col gap-3', inView ? 'animate-rise' : 'opacity-0')}
          style={inView ? { animationDelay: `${index * 90}ms` } : undefined}
        >
          <span className="relative block h-px bg-rule">
            {inView && (
              <span
                className="absolute inset-0 block origin-left animate-draw bg-accent"
                style={{ animationDelay: `${250 + index * 90}ms` }}
              />
            )}
          </span>
          <dd className="font-display text-6xl leading-none tabular-nums text-accent sm:text-7xl">
            {inView ? <CountUp value={figure.value} duration={1100} /> : 0}
          </dd>
          <dt className="max-w-[16rem] text-[13px] leading-relaxed text-ink-muted">{figure.label}</dt>
        </div>
      ))}
    </dl>
  )
}

export function HomeScreen({ onStart }: HomeScreenProps) {
  return (
    <>
      <header className="grain grain-dark relative overflow-hidden bg-burgundy text-offwhite">
        <div
          aria-hidden
          className="pointer-events-none absolute -right-1/4 -top-1/2 h-[140%] w-3/4 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(236,231,211,0.10),transparent)]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-1/3 -left-1/4 h-[90%] w-2/3 animate-drift rounded-full bg-[radial-gradient(closest-side,rgba(27,27,27,0.25),transparent)] [animation-direction:alternate-reverse]"
        />
        <div className="relative mx-auto flex max-w-5xl flex-col gap-12 px-4 pb-14 pt-5 sm:px-8 sm:pb-20 sm:pt-6">
          <BrandBar />

          <div className="grid items-end gap-12 lg:grid-cols-[1.35fr_1fr] lg:gap-16">
            <div className="flex flex-col gap-7">
              <p className="eyebrow animate-fade text-offwhite/70 [animation-delay:300ms]">
                Extração inteligente de dados processuais · PJe-Calc
              </p>
              <h1
                className="font-display text-[44px] leading-[1.02] tracking-[-0.02em] sm:text-[64px] lg:text-[72px]"
                aria-label="Do processo à planilha, sem reter nada."
              >
                {TITLE.map((word, index) => (
                  <span key={word.text}>
                    <span aria-hidden className="inline-block overflow-hidden pb-1 align-bottom">
                      <span
                        className={cn('inline-block animate-reveal', word.italic && 'italic text-offwhite/80')}
                        style={{ animationDelay: `${350 + index * 90}ms` }}
                      >
                        {word.text}
                        {' '}
                      </span>
                    </span>
                    {word.br && <br className="hidden sm:block" />}
                  </span>
                ))}
              </h1>
              <p className="max-w-xl animate-rise text-[16px] leading-relaxed text-offwhite/80 [animation-delay:1000ms] sm:text-[17px]">
                O Veritas AI lê o PDF do processo trabalhista, encontra cartões de ponto e
                holerites em meio a centenas de páginas e devolve uma planilha revisada para
                o cálculo. Quando o download termina, a sessão se desfaz.
              </p>
              <div className="flex animate-rise flex-col gap-3 [animation-delay:1150ms] sm:flex-row sm:items-center">
                <Button
                  type="button"
                  size="lg"
                  onClick={onStart}
                  className="group/btn bg-offwhite text-burgundy shadow-[0_10px_24px_-10px_rgba(0,0,0,0.6)] hover:bg-[#f6f3e7] focus-visible:ring-offwhite/60 focus-visible:ring-offset-burgundy"
                >
                  Iniciar uma sessão
                  <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
                </Button>
                <a
                  href="#metodo"
                  className="group/link inline-flex h-12 items-center justify-center gap-2 rounded-main px-5 text-[12px] font-semibold uppercase tracking-[0.16em] text-offwhite/80 transition-colors hover:text-offwhite focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offwhite/60"
                >
                  Como funciona
                  <ArrowDown className="h-4 w-4 transition-transform duration-300 group-hover/link:translate-y-0.5" aria-hidden />
                </a>
              </div>
            </div>
            <div className="mx-auto w-full max-w-xs animate-rise [animation-delay:500ms] sm:max-w-sm lg:max-w-none">
              <PageLattice />
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-24 px-4 py-20 sm:gap-32 sm:px-8 sm:py-28">
        <section aria-labelledby="oficio" className="grid gap-8 lg:grid-cols-[1fr_2fr] lg:gap-16">
          <Reveal>
            <p id="oficio" className="eyebrow text-accent">
              Para contadores e peritos
            </p>
          </Reveal>
          <div className="flex flex-col gap-8">
            <Reveal>
              <p className="font-display text-[30px] leading-[1.12] tracking-[-0.01em] sm:text-[42px]">
                Um processo tem centenas de páginas. O cálculo depende de poucas,{' '}
                <span className="italic text-accent">e de cada horário, cada rubrica,</span>{' '}
                transcritos sem erro.
              </p>
            </Reveal>
            <Reveal delay={120}>
              <p className="max-w-2xl text-[15px] leading-relaxed text-ink-muted">
                Petições, procurações e despachos dividem o mesmo arquivo com as folhas que
                interessam ao cálculo trabalhista. Encontrá-las e digitá-las é trabalho lento e
                sujeito a falhas. O Veritas AI assume a busca e a leitura; o especialista
                mantém a palavra final sobre cada número.
              </p>
            </Reveal>
          </div>
        </section>

        <section id="metodo" aria-labelledby="metodo-titulo" className="flex scroll-mt-8 flex-col gap-12">
          <Reveal className="flex flex-col gap-3">
            <p className="eyebrow text-accent">Método</p>
            <h2 id="metodo-titulo" className="font-display text-[34px] leading-[1.05] tracking-[-0.01em] sm:text-5xl">
              Quatro movimentos, <span className="italic">uma sessão.</span>
            </h2>
          </Reveal>
          <ol className="grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
            {MOVEMENTS.map((movement, index) => (
              <li key={movement.numeral}>
                <Reveal delay={index * 110} className="flex flex-col gap-4">
                  <span className="relative block h-px bg-rule">
                    <span className="absolute inset-0 block origin-left animate-draw bg-accent" style={{ animationDelay: `${300 + index * 110}ms` }} />
                    <span className="absolute -top-[3px] left-0 block h-[7px] w-[7px] rotate-45 border border-accent bg-accent" />
                  </span>
                  <span className="font-display text-3xl italic leading-none text-accent">{movement.numeral}</span>
                  <h3 className="font-display text-2xl leading-tight">{movement.title}</h3>
                  <p className="text-[14px] leading-relaxed text-ink-muted">{movement.body}</p>
                </Reveal>
              </li>
            ))}
          </ol>
        </section>

        <section aria-label="Números do funil">
          <Figures />
        </section>

        <section aria-labelledby="privacidade">
          <Reveal>
            <Card className="relative overflow-hidden">
              <div className="grid gap-10 px-5 py-8 sm:px-10 sm:py-12 lg:grid-cols-[1.1fr_1fr] lg:gap-14">
                <div className="flex flex-col gap-4">
                  <p className="eyebrow text-accent">Privacy by Design</p>
                  <h2 id="privacidade" className="font-display text-[32px] leading-[1.05] tracking-[-0.01em] sm:text-[44px]">
                    O que <span className="italic">não existe</span> é o que protege.
                  </h2>
                  <p className="max-w-md text-[15px] leading-relaxed text-ink-muted">
                    Processos trabalhistas carregam CPF, salários e jornadas. Por isso a
                    privacidade aqui é decisão de arquitetura: o dado só existe enquanto
                    é útil, em memória, e desaparece com a sessão, em linha com a
                    minimização e a necessidade da LGPD (Lei 13.709/2018).
                  </p>
                </div>
                <ul className="stagger flex flex-col self-center">
                  {ABSENCES.map((item) => (
                    <li key={item} className="flex items-start gap-4 border-t border-rule py-4 last:border-b">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-accent" strokeWidth={1.75} aria-hidden />
                      <span className="text-[15px] leading-snug">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          </Reveal>
        </section>

        <section aria-labelledby="limites" className="grid gap-8 lg:grid-cols-[1fr_2fr] lg:gap-16">
          <Reveal>
            <p id="limites" className="eyebrow text-accent">
              Limites declarados
            </p>
          </Reveal>
          <Reveal delay={100} className="flex flex-col gap-4">
            <p className="max-w-2xl text-[15px] leading-relaxed text-ink-muted">
              <span className="text-ink">Nenhuma extração é perfeita.</span> Cada registro traz
              confiança, página de origem e trecho fonte, e campos ausentes ou ambíguos são
              marcados, nunca inventados. A planilha segue o layout{' '}
              <code className="text-ink">provisional-0.1</code>, uma hipótese de trabalho, e não o
              modelo oficial do PJe-Calc.
            </p>
          </Reveal>
        </section>

        <section aria-labelledby="comecar">
          <Reveal className="flex flex-col items-start gap-6 border-t border-ink/70 pt-12 sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-col gap-3">
              <h2 id="comecar" className="font-display text-[34px] leading-[1.05] tracking-[-0.01em] sm:text-5xl">
                Envie o PDF. <span className="italic text-accent">O resto acontece aqui</span>
                <br className="hidden sm:block" /> e termina com a sessão.
              </h2>
            </div>
            <Button type="button" size="lg" className="group/btn w-full shrink-0 sm:w-auto" onClick={onStart}>
              Iniciar uma sessão
              <ArrowRight className="h-4 w-4 transition-transform duration-300 group-hover/btn:translate-x-1" aria-hidden />
            </Button>
          </Reveal>
        </section>
      </main>
    </>
  )
}
