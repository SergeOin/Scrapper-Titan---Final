<#
.SYNOPSIS
  Script d'aide pour automatiser les tâches de développement.

.USAGE
  . .\tasks.ps1           # charger les fonctions dans la session
  Invoke-Task setup        # installe deps + playwright
  Invoke-Task lint         # ruff + mypy (rapide)
  Invoke-Task format       # formate le code
  Invoke-Task test         # pytest rapide
  Invoke-Task coverage     # coverage détaillé
  Invoke-Task server       # lance l'API
  Invoke-Task worker       # lance le worker
  Invoke-Task compose-up   # démarre stack docker-compose
  Invoke-Task compose-down # arrête stack

#>
param(
  [Parameter(Position=0)] [string]$Task,
  [switch]$Help
)

function Ensure-Venv {
  if (-not (Test-Path .venv)) {
    Write-Host "[venv] Création environnement virtuel" -ForegroundColor Cyan
    python -m venv .venv
  }
  & .\.venv\Scripts\Activate.ps1
}

function Invoke-Task {
  param([string]$Name)
  switch ($Name) {
    'setup' {
      Ensure-Venv
      python -m pip install --upgrade pip
      pip install -r requirements.txt
      try { python -m playwright install chromium } catch { Write-Warning "Playwright install a échoué (proxy?)" }
    }
    'lint' {
      Ensure-Venv
      ruff check .; mypy .
    }
    'format' {
      Ensure-Venv
      ruff check . --fix; black .
    }
    'test' {
      Ensure-Venv
      pytest -q --maxfail=1 --disable-warnings
    }
    'coverage' {
      Ensure-Venv
      pytest --cov=scraper --cov=server --cov-report=term-missing
    }
    'server' {
      Ensure-Venv
      uvicorn server.main:app --reload --port 8000
    }
    'worker' {
      Ensure-Venv
      python -m scraper.worker
    }
    'backfill-search' {
      Ensure-Venv
      Write-Host "Backfilling search_norm and ensuring indices on SQLite..." -ForegroundColor Cyan
      python scripts/backfill_search_norm.py --db .\fallback.sqlite3
      if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
      Write-Host "Vacuuming SQLite..." -ForegroundColor Cyan
      python -c "import sqlite3; conn = sqlite3.connect('fallback.sqlite3');\nwith conn:\n    conn.execute('VACUUM');\nprint('vacuum_done')"
    }
    'compose-up' {
      docker compose up -d --build
    }
    'compose-down' {
      docker compose down -v
    }
    Default {
      Write-Host "Tâche inconnue: $Name" -ForegroundColor Red
    }
  }
}

if ($Help -or -not $Task) {
  Write-Host "Tâches disponibles:" -ForegroundColor Yellow
  'setup','lint','format','test','coverage','server','worker','backfill-search','compose-up','compose-down' | ForEach-Object { " - $_" }
  if (-not $Task) { return }
}

Invoke-Task -Name $Task
