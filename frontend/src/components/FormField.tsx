import type { InputHTMLAttributes } from 'react'

export function FormField({
  label,
  error,
  ...inputProps
}: { label: string; error?: string } & InputHTMLAttributes<HTMLInputElement>) {
  const errorId = error ? `${inputProps.id}-error` : undefined
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor={inputProps.id}>
        {label}
      </label>
      <input
        {...inputProps}
        aria-describedby={errorId}
        aria-invalid={Boolean(error)}
        className="w-full rounded-xl border border-white/10 bg-slate-950/50 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-300/70 focus:ring-2 focus:ring-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-60"
      />
      {error && (
        <p className="mt-2 text-sm text-rose-300" id={errorId}>
          {error}
        </p>
      )}
    </div>
  )
}
