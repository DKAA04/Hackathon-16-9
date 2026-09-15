$ErrorActionPreference = "Stop"

Write-Host "=== CivicLens setup ===" -ForegroundColor Green

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python not found" }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js not found" }

Push-Location backend
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Pop-Location

Push-Location frontend
npm install
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Pop-Location

New-Item -ItemType Directory -Force -Path "backend\data\incoming" | Out-Null

Write-Host ""
Write-Host "DONE" -ForegroundColor Green
Write-Host "Backend:  .\dev-backend.ps1"
Write-Host "Frontend: .\dev-frontend.ps1"
