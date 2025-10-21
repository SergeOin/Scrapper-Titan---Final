import { useState } from 'react'
import { ShieldX } from 'lucide-react'
import { useBlockedAccounts } from '../hooks/useBlockedAccounts'
import { AddBlockedAccountForm } from './AddBlockedAccountForm'
import { BlockedAccountsList } from './BlockedAccountsList'

export function BlockedAccountsPage(){
  const { items, loading, error, add, remove } = useBlockedAccounts()
  const [toast, setToast] = useState<string | null>(null)

  function notify(msg: string){
    setToast(msg)
    setTimeout(()=> setToast(null), 3000)
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-4 flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <ShieldX className="h-6 w-6 text-sky-400" aria-hidden />
          Comptes LinkedIn bloqués
        </h1>
        <a href="/" className="text-sm text-sky-300 hover:text-sky-200">⟵ Retour au tableau</a>
      </header>

      {toast && (
        <div role="status" className="mb-3 rounded-md bg-slate-800 px-3 py-2 text-sm text-slate-100 shadow">{toast}</div>
      )}
      {error && (
        <div role="alert" className="mb-3 rounded-md bg-rose-900/50 px-3 py-2 text-sm text-rose-100 shadow">{error}</div>
      )}

      <div className="grid gap-4">
  <AddBlockedAccountForm onAdd={async (url)=>{ await add(url); notify('Compte ajouté à la liste de blocage'); }} />
        {loading ? (
          <div className="rounded-lg bg-slate-800 p-4 text-sm text-slate-300">Chargement…</div>
        ) : (
          <BlockedAccountsList items={items} onUnblock={async (id)=>{ await remove(id); notify('Compte débloqué'); }} />
        )}
      </div>
    </div>
  )
}
