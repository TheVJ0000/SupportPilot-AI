import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { getSupabaseClient } from '../lib/supabase'
import { AuthContext, type SignUpInput, type SignUpResult } from './AuthContext'

const AUTH_CONFIGURATION_MESSAGE =
  'Authentication is not configured for this installation. Add the Supabase URL and publishable key.'

class AuthActionError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AuthActionError'
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => {
    try {
      return getSupabaseClient()
    } catch {
      return null
    }
  })
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(client !== null)
  const [configurationError] = useState<string | null>(
    client ? null : AUTH_CONFIGURATION_MESSAGE,
  )

  useEffect(() => {
    if (!client) return
    let active = true

    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, nextSession) => {
      if (active) setSession(nextSession)
    })

    void client.auth
      .getSession()
      .then(({ data, error }) => {
        if (!active) return
        if (error) {
          setSession(null)
          return
        }
        setSession(data.session)
      })
      .catch(() => {
        if (active) setSession(null)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
      subscription.unsubscribe()
    }
  }, [client])

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const { data, error } = await getSupabaseClient().auth.signInWithPassword({ email, password })
      if (error || !data.session) {
        throw new AuthActionError('Unable to sign in. Check your email and password.')
      }
      setSession(data.session)
    } catch (error) {
      if (error instanceof AuthActionError) throw error
      throw new AuthActionError('Unable to sign in. Check your email and password.')
    }
  }, [])

  const signUp = useCallback(async (input: SignUpInput): Promise<SignUpResult> => {
    try {
      const { data, error } = await getSupabaseClient().auth.signUp({
        email: input.email,
        password: input.password,
        options: { data: { display_name: input.displayName } },
      })

      if (error || !data.user) {
        throw new AuthActionError('Unable to create your account. Please try again.')
      }

      if (data.session) setSession(data.session)
      return { confirmationRequired: data.session === null }
    } catch (error) {
      if (error instanceof AuthActionError) throw error
      throw new AuthActionError('Unable to create your account. Please try again.')
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      const { error } = await getSupabaseClient().auth.signOut()
      if (error) throw error
      setSession(null)
    } catch {
      throw new AuthActionError('Unable to sign out. Please try again.')
    }
  }, [])

  const value = useMemo(
    () => ({
      session,
      user: session?.user ?? null,
      accessToken: session?.access_token ?? null,
      loading,
      configurationError,
      signIn,
      signUp,
      signOut,
    }),
    [configurationError, loading, session, signIn, signOut, signUp],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
