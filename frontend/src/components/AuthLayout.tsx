import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Brand } from './Brand'

export function AuthLayout({
  title,
  description,
  alternateText,
  alternateLabel,
  alternateTo,
  children,
}: {
  title: string
  description: string
  alternateText: string
  alternateLabel: string
  alternateTo: string
  children: ReactNode
}) {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#07111f] px-5 py-8 text-white sm:px-8">
      <div className="pointer-events-none absolute inset-0 opacity-80 [background-image:radial-gradient(circle_at_15%_20%,rgba(45,212,191,0.14),transparent_32%),radial-gradient(circle_at_85%_75%,rgba(56,189,248,0.12),transparent_34%)]" />
      <div className="relative mx-auto max-w-6xl">
        <Brand />
        <div className="mx-auto mt-12 max-w-md rounded-3xl border border-white/10 bg-white/[0.055] p-6 shadow-2xl shadow-cyan-950/30 backdrop-blur-xl sm:mt-16 sm:p-8">
          <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-3 leading-7 text-slate-400">{description}</p>
          <div className="mt-8">{children}</div>
          <p className="mt-7 text-center text-sm text-slate-400">
            {alternateText}{' '}
            <Link className="font-semibold text-cyan-300 hover:text-cyan-200" to={alternateTo}>
              {alternateLabel}
            </Link>
          </p>
        </div>
      </div>
    </main>
  )
}
