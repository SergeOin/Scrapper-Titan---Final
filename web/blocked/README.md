# Interface "Comptes LinkedIn bloqués"

Cette mini‑app React/TypeScript/Tailwind fournit la gestion des comptes à bloquer pour le scrapper.

## Scripts

- `npm install`
- `npm run dev` (développement)
- `npm run build` (génère `dist/`)

Le backend FastAPI sert automatiquement le build à l'URL `/blocked` si `web/blocked/dist` est présent.

## API (mock)
- `GET /blocked-accounts` → `{ items: [...], count }`
- `POST /blocked-accounts` body: `{ url: string, name?: string }`
- `DELETE /blocked-accounts/:id`

Toutes les validations et messages sont en français.
