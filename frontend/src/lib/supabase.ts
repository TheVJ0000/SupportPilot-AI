import { createClient, type SupabaseClient } from '@supabase/supabase-js'

export class SupabaseConfigurationError extends Error {
  constructor() {
    super(
      'Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY.',
    )
    this.name = 'SupabaseConfigurationError'
  }
}

let supabaseClient: SupabaseClient | undefined

export function getSupabaseClient(): SupabaseClient {
  if (supabaseClient) return supabaseClient

  const url = import.meta.env.VITE_SUPABASE_URL?.trim()
  const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY?.trim()

  if (!url || !publishableKey) {
    throw new SupabaseConfigurationError()
  }

  supabaseClient = createClient(url, publishableKey, {
    auth: {
      autoRefreshToken: true,
      detectSessionInUrl: true,
      persistSession: true,
    },
  })

  return supabaseClient
}
