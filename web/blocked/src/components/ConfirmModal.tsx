import { ReactNode } from 'react'

type Props = {
  open: boolean
  title: string
  description?: string | ReactNode
  confirmText?: string
  cancelText?: string
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmModal({ open, title, description, confirmText='Confirmer', cancelText='Annuler', onConfirm, onClose }: Props){
  if(!open) return null
  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative z-10 w-[92%] max-w-md rounded-lg bg-slate-800 p-4 shadow-xl">
        <h2 className="text-lg font-semibold">{title}</h2>
        {description ? <div className="mt-2 text-sm text-slate-300">{description}</div> : null}
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded-md bg-slate-600 px-3 py-1.5 text-sm hover:bg-slate-500" onClick={onClose}>{cancelText}</button>
          <button className="rounded-md bg-red-600 px-3 py-1.5 text-sm hover:bg-red-500" onClick={onConfirm}>{confirmText}</button>
        </div>
      </div>
    </div>
  )
}
