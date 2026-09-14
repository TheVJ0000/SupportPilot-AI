export function PageLoader({ label }: { label: string }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#07111f] px-6 text-white">
      <div aria-live="polite" className="flex items-center gap-3 text-slate-300">
        <span className="size-2.5 animate-pulse rounded-full bg-cyan-300 shadow-[0_0_18px_rgba(103,232,249,0.75)]" />
        {label}
      </div>
    </main>
  )
}
