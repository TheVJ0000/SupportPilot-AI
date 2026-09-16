import type { Citation } from './adminApi'

export const panel = 'rounded-2xl border border-white/10 bg-slate-900/60 p-5 sm:p-6'
export const button =
  'rounded-lg border border-white/15 px-4 py-2 text-sm font-semibold hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 disabled:opacity-40'
export const textLink =
  'text-cyan-200 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300'
export function label(value: string) {
  return value.replaceAll('_', ' ')
}
export function timestamp(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

export function citationLocation(citation: Citation) {
  const location = citation.locator
  if (location.kind === 'faq') return 'FAQ'
  const start =
    location.kind === 'pdf'
      ? location.page_start
      : location.kind === 'docx'
        ? location.block_start
        : location.line_start
  const end =
    location.kind === 'pdf'
      ? location.page_end
      : location.kind === 'docx'
        ? location.block_end
        : location.line_end
  const unit = location.kind === 'pdf' ? 'Page' : location.kind === 'docx' ? 'Block' : 'Line'
  return `${unit}${start === end ? '' : 's'} ${start}${start === end ? '' : `–${end}`}`
}
