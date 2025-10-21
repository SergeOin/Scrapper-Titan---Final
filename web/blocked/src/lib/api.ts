export type BlockedAccount = {
  id: string
  url: string
  blocked_at: string
}

export async function fetchBlocked(): Promise<BlockedAccount[]> {
  const r = await fetch('/blocked-accounts', { credentials: 'include' })
  if (!r.ok) throw new Error('Erreur chargement (' + r.status + ')')
  const data = await r.json()
  return Array.isArray(data.items) ? data.items : []
}

export async function addBlocked(input: { url: string }): Promise<BlockedAccount> {
  const r = await fetch('/blocked-accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  })
  if (!r.ok) throw new Error('Échec du débloquage (' + r.status + ')')
}
