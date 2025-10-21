import { useState } from 'react'
import { Trash2, UserX } from 'lucide-react'
import { type BlockedAccount } from '../lib/api'
import { ConfirmModal } from './ConfirmModal'

type Props = {
  items: BlockedAccount[]
  onUnblock: (id: string) => Promise<void>
}

export function BlockedAccountsList({ items, onUnblock }: Props){
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  return (
    <div className="rounded-lg bg-slate-800 p-4 shadow">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold">Comptes bloqués</h3>
        <div className="text-xs text-slate-400">Total: {items.length}</div>
      </div>
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-slate-400">Aucun compte bloqué pour le moment.</p>
      ) : (
        <ul className="divide-y divide-slate-700">
          {items.map((it)=> (
            <li key={it.id} className="flex items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <UserX className="h-4 w-4 text-sky-400" aria-hidden />
                  <a href={it.url} target="_blank" rel="noreferrer" className="truncate text-sky-300 hover:underline">{it.url}</a>
                </div>
                <div className="mt-1 text-xs text-slate-400">{new Date(it.blocked_at).toLocaleString('fr-FR')}</div>
              </div>
              <button
                aria-label={`Débloquer ${it.url}`}
                onClick={()=>setConfirmId(it.id)}
                disabled={busy === it.id}
                className="inline-flex items-center gap-1 rounded-md bg-rose-600 px-3 py-1.5 text-sm hover:bg-rose-500 disabled:opacity-60">
                <Trash2 className="h-4 w-4" /> Débloquer
              </button>
            </li>
          ))}
        </ul>
      )}

      <ConfirmModal
        open={!!confirmId}
        title="Confirmer le déblocage"
        description="Ce compte sera retiré de la liste des blocages."
        confirmText="Débloquer"
        onClose={()=>setConfirmId(null)}
        onConfirm={async ()=>{
          if(!confirmId) return
          setBusy(confirmId)
          try{
            await onUnblock(confirmId)
          } finally {
            setBusy(null)
            setConfirmId(null)
          }
        }}
      />
    </div>
  )
}
