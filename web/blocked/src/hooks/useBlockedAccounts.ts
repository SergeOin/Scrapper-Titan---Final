import { useEffect, useState } from 'react'
import { addBlocked, fetchBlocked, removeBlocked, type BlockedAccount } from '../lib/api'

export function useBlockedAccounts(){
  const [items, setItems] = useState<BlockedAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load(){
    setLoading(true)
    setError(null)
    try{
      const list = await fetchBlocked()
      setItems(list)
    }catch(e:any){
      setError(e?.message || 'Erreur de chargement')
    }finally{
      setLoading(false)
    }
  }

  async function add(url: string){
    setError(null)
    const trimmed = (url||'').trim()
    if(!trimmed) throw new Error('Veuillez saisir une URL ou un identifiant LinkedIn')
    const exists = items.some(it => it.url.toLowerCase() === trimmed.toLowerCase())
    if(exists) throw new Error('Ce compte est déjà dans la liste')
    const created = await addBlocked({ url: trimmed })
    setItems(prev => [created, ...prev])
    return created
  }

  async function remove(id: string){
    await removeBlocked(id)
    setItems(prev => prev.filter(it => it.id !== id))
  }

  useEffect(()=>{ load() }, [])
  return { items, loading, error, reload: load, add, remove }
}
