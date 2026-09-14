import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'
import { AuthLayout } from '../components/AuthLayout'
import { FormField } from '../components/FormField'

interface RegistrationErrors {
  displayName?: string
  email?: string
  password?: string
  confirmation?: string
  form?: string
}

export function RegisterPage() {
  const { signUp, configurationError } = useAuth()
  const navigate = useNavigate()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [errors, setErrors] = useState<RegistrationErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [confirmationEmail, setConfirmationEmail] = useState<string | null>(null)

  function validate(): RegistrationErrors {
    const nextErrors: RegistrationErrors = {}
    const normalizedName = displayName.trim()
    if (normalizedName.length < 2 || normalizedName.length > 100) {
      nextErrors.displayName = 'Display name must be between 2 and 100 characters.'
    }
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      nextErrors.email = 'Enter a valid email address.'
    }
    if (password.length < 8) {
      nextErrors.password = 'Use at least 8 characters.'
    }
    if (confirmation !== password) {
      nextErrors.confirmation = 'Passwords do not match.'
    }
    return nextErrors
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return

    const validationErrors = validate()
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) return

    setSubmitting(true)
    try {
      const result = await signUp({
        displayName: displayName.trim(),
        email: email.trim(),
        password,
      })
      if (result.confirmationRequired) {
        setConfirmationEmail(email.trim())
      } else {
        navigate('/app/workspaces', { replace: true })
      }
    } catch {
      setErrors({ form: 'Unable to create your account. Please try again.' })
    } finally {
      setSubmitting(false)
    }
  }

  if (confirmationEmail) {
    return (
      <AuthLayout
        title="Check your email"
        description="Your account was created, but you are not signed in yet. Verify your email before continuing."
        alternateText="Already verified?"
        alternateLabel="Go to login"
        alternateTo="/login"
      >
        <div aria-live="polite" className="rounded-2xl border border-cyan-300/20 bg-cyan-300/5 p-5 text-sm leading-6 text-cyan-100">
          We sent a confirmation link to <strong>{confirmationEmail}</strong>. Follow that link, then sign in.
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Create your account"
      description="Start with your identity. Your first business workspace comes next."
      alternateText="Already have an account?"
      alternateLabel="Log in"
      alternateTo="/login"
    >
      <form className="space-y-5" noValidate onSubmit={handleSubmit}>
        <FormField
          id="display-name"
          label="Display name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          autoComplete="name"
          disabled={submitting}
          error={errors.displayName}
          required
        />
        <FormField
          id="register-email"
          label="Email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="email"
          disabled={submitting}
          error={errors.email}
          required
        />
        <FormField
          id="register-password"
          label="Password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          disabled={submitting}
          error={errors.password}
          required
        />
        <FormField
          id="confirm-password"
          label="Confirm password"
          type="password"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          autoComplete="new-password"
          disabled={submitting}
          error={errors.confirmation}
          required
        />

        <div aria-live="polite" className="min-h-6 text-sm text-rose-300">
          {errors.form ?? configurationError}
        </div>

        <button
          className="w-full rounded-xl bg-cyan-300 px-5 py-3.5 font-bold text-[#07111f] transition hover:bg-cyan-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#07111f] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting || Boolean(configurationError)}
          type="submit"
        >
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </AuthLayout>
  )
}
