import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AuthLayout } from '../components/AuthLayout'
import { FormField } from '../components/FormField'
import { useAuth } from '../auth/useAuth'

export function LoginPage() {
  const { signIn, configurationError } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setError(null)

    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError('Enter a valid email address.')
      return
    }
    if (!password) {
      setError('Enter your password.')
      return
    }

    setSubmitting(true)
    try {
      await signIn(email.trim(), password)
      navigate('/app/workspaces', { replace: true })
    } catch {
      setError('Unable to sign in. Check your email and password.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      description="Sign in to continue to your SupportPilot workspace."
      alternateText="New to SupportPilot?"
      alternateLabel="Create an account"
      alternateTo="/register"
    >
      <form className="space-y-5" noValidate onSubmit={handleSubmit}>
        <FormField
          id="email"
          label="Email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          disabled={submitting}
          required
        />
        <FormField
          id="password"
          label="Password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          disabled={submitting}
          required
        />

        <div aria-live="polite" className="min-h-6 text-sm text-rose-300">
          {error ?? configurationError}
        </div>

        <button
          className="w-full rounded-xl bg-cyan-300 px-5 py-3.5 font-bold text-[#07111f] transition hover:bg-cyan-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#07111f] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting || Boolean(configurationError)}
          type="submit"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthLayout>
  )
}
