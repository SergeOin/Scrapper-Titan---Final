import { useState, FormEvent } from 'react'

type Props = {
  onAdd: (url: string) => Promise<void>
}

export function AddBlockedAccountForm({ onAdd }: Props){
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent){
    e.preventDefault()
    setError(null)
    setLoading(true)
    try{
      await onAdd(url)
      setUrl('')
    }catch(err:any){
      setError(err?.message || 'Erreur inconnue')
    }finally{
      setLoading(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg bg-slate-800 p-4 shadow">
      <h3 className="mb-3 text-base font-semibold">Ajouter un compte à bloquer</h3>
      <div className="grid gap-3">
        <div>
          <label className="mb-1 block text-sm" htmlFor="url">URL ou identifiant LinkedIn</label>
          <input id="url" aria-label="URL ou identifiant LinkedIn" className="w-full rounded-md border border-slate-600 bg-slate-900 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-sky-500" placeholder="https://www.linkedin.com/in/username ou username" value={url} onChange={e=>setUrl(e.target.value)} required />
        </div>
        <div className="flex items-end">
          <button type="submit" disabled={loading} className="inline-flex items-center justify-center rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-sky-500 disabled:opacity-60">
            {loading ? 'Ajout…' : 'Bloquer'}
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
      <p className="mt-2 text-xs text-slate-400">Les URLs invalides ou en doublon sont rejetées.</p>
    </form>
  )
}
