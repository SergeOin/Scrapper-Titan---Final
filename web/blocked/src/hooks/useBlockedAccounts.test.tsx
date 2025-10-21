import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useBlockedAccounts } from './useBlockedAccounts'

const mockFetch = vi.fn()

function setupFetch(data: any, ok = true, status = 200){
  mockFetch.mockResolvedValueOnce({ ok, status, json: async ()=>data })
}

describe('useBlockedAccounts', () => {
  beforeEach(()=>{
    vi.stubGlobal('fetch', mockFetch as any)
    mockFetch.mockReset()
  })

  it('loads list on mount', async () => {
    setupFetch({ items: [] })
    const { result } = renderHook(()=>useBlockedAccounts())
    expect(result.current.loading).toBe(true)
    // wait for the hook to finish initial load
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items).toEqual([])
  })

  it('prevents duplicate add on client side', async () => {
    setupFetch({ items: [{ id:'1', url:'https://www.linkedin.com/in/dup', blocked_at:'2024-01-01T00:00:00Z' }] })
    const { result } = renderHook(()=>useBlockedAccounts())
    await Promise.resolve()

    await expect(result.current.add('https://www.linkedin.com/in/dup')).rejects.toThrow()
  })
})
