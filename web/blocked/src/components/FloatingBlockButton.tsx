import { UserX } from 'lucide-react'

type Props = {
  onClick: () => void
}

export function FloatingBlockButton({ onClick }: Props){
  return (
    <button
      aria-label="Ouvrir la gestion des comptes bloqués"
      title="Gestion des comptes bloqués"
      onClick={onClick}
      className="fixed bottom-6 right-6 inline-flex items-center gap-2 rounded-full bg-sky-600 px-4 py-2 text-sm font-semibold text-white shadow-lg hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-300">
      <UserX className="h-4 w-4" /> Blocage
    </button>
  )
}
