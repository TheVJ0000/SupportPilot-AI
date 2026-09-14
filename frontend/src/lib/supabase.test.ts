import { afterEach, describe, expect, it, vi } from 'vitest'
import { getSupabaseClient, SupabaseConfigurationError } from './supabase'

describe('Supabase client configuration', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('fails clearly only when an unconfigured client is requested', () => {
    vi.stubEnv('VITE_SUPABASE_URL', '')
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', '')

    expect(() => getSupabaseClient()).toThrow(SupabaseConfigurationError)
    expect(() => getSupabaseClient()).toThrow(/VITE_SUPABASE_URL/)
  })
})
