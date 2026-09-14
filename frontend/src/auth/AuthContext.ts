import { createContext } from 'react'
import type { Session, User } from '@supabase/supabase-js'

export interface SignUpInput {
  displayName: string
  email: string
  password: string
}

export interface SignUpResult {
  confirmationRequired: boolean
}

export interface AuthContextValue {
  session: Session | null
  user: User | null
  accessToken: string | null
  loading: boolean
  configurationError: string | null
  signIn: (email: string, password: string) => Promise<void>
  signUp: (input: SignUpInput) => Promise<SignUpResult>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
