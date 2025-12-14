export type BlockedAccount = {
  id: string
  url: string
  blocked_at: string
}

declare global {
  interface Window {
    __DESKTOP_TRIGGER_KEY?: string
  }
}

function desktopTriggerKey(): string | undefined {
  try {
    return typeof window !== 'undefined' ? window.__DESKTOP_TRIGGER_KEY : undefined
  } catch {
    return undefined
  }
}

function desktopHeaders(extra?: Record<string, string>): Record<string, string> {
  const key = desktopTriggerKey()
  return key ? { ...(extra || {}), 'X-Desktop-Trigger': key } : { ...(extra || {}) }
}

export async function fetchBlocked(): Promise<BlockedAccount[]> {
  const r = await fetch('/blocked-accounts', { credentials: 'include', headers: desktopHeaders() })
  if (!r.ok) throw new Error('Erreur chargement (' + r.status + ')')
  const data = await r.json()
  return Array.isArray(data.items) ? data.items : []
}

export async function addBlocked(input: { url: string }): Promise<BlockedAccount> {
  const r = await fetch('/blocked-accounts', {
    method: 'POST',
    headers: desktopHeaders({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify(input),
  })
  if (r.status === 409) throw new Error('Ce compte est déjà bloqué')
  if (!r.ok) throw new Error('Échec de l\'ajout (' + r.status + ')')
  const data = await r.json()
  return data.item
}

export async function removeBlocked(id: string): Promise<void> {
  const r = await fetch(`/blocked-accounts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: desktopHeaders(),
  })
  if (!r.ok) throw new Error('Échec du débloquage (' + r.status + ')')
}
