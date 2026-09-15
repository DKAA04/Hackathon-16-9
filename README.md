# CivicLens Hackathon Starter

Pivot-ready starter for Antwerp 16/09.

## Stack
- React + Vite + TypeScript
- FastAPI
- CSV / XLSX / JSON / PDF ingestion
- optional OpenAI
- demo-mode fallback that works with zero API keys

## Setup

PowerShell:

```powershell
cd "C:\Users\Usuario\Documents\Agap\hackathons\Hackathon-Antwerp-16.9"
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

Terminal 1:

```powershell
.\dev-backend.ps1
```

Terminal 2:

```powershell
.\dev-frontend.ps1
```

Open http://localhost:5173

Backend docs: http://localhost:8000/docs

## GitHub

```powershell
git init
git remote remove origin 2>$null
git remote add origin git@github.com:DKAA04/Hackathon-16-9.git
git add .
git commit -m "feat: hackathon starter"
git branch -M main
git push -u origin main
```

## Tomorrow's data

Drop released files in `backend/data/incoming/`, then POST:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/api/ingest `
  -Method Post
```

Then turn Demo Mode OFF in the UI.

## Gimmicks already included

- polished evidence-first console
- Ctrl+K command palette
- visible confidence scoring
- evidence/provenance drawer
- demo-mode fallback
- voice-ready UI affordance for ElevenLabs
- challenge-agnostic ingestion layer


## Supabase integration

The supplied Supabase project is wired into the Vite frontend using `@supabase/supabase-js`.

- Local credentials: `frontend/.env.local`
- Safe template: `frontend/.env.example`
- Client: `frontend/src/lib/supabase.ts`
- Startup connectivity indicator: visible in the dashboard
- `frontend/.env.local` is Git-ignored

The original Next.js `@supabase/ssr` cookie helpers are not used because this starter is React + Vite, not Next.js. If the app is migrated to Next later, those helpers become relevant.
