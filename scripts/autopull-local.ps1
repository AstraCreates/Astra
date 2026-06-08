# Auto-pull from git remote and restart services when changes are detected.
# Run this in a background PowerShell window on the dev machine.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\autopull-local.ps1

param(
    [int]$IntervalSeconds = 30
)

$Repo = Split-Path $PSScriptRoot -Parent
$ErrorActionPreference = "SilentlyContinue"

Write-Host "autopull-local: watching $Repo (every ${IntervalSeconds}s)" -ForegroundColor Cyan

while ($true) {
    Set-Location $Repo

    git fetch origin main 2>$null
    if (-not $?) { Start-Sleep $IntervalSeconds; continue }

    $Local  = git rev-parse HEAD 2>$null
    $Remote = git rev-parse origin/main 2>$null

    if ($Remote -and $Local -ne $Remote) {
        $Changed = git diff --name-only "$Local" "$Remote" 2>$null

        # Merge (rebase) remote changes
        git pull --rebase origin main 2>&1 | Write-Host

        $BackendChanged  = $Changed | Select-String -Pattern "^(backend/|requirements\.txt|Dockerfile\.backend|docker-compose\.yml)"
        $FrontendChanged = $Changed | Select-String -Pattern "^(frontend/|Dockerfile\.frontend|docker-compose\.yml)"

        Write-Host "autopull-local: $Local..$Remote  backend=$([bool]$BackendChanged) frontend=$([bool]$FrontendChanged)" -ForegroundColor Yellow

        if ($BackendChanged) {
            Write-Host "Restarting backend..." -ForegroundColor Green
            # Kill any running uvicorn on port 8000
            $proc = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty OwningProcess -First 1
            if ($proc) { Stop-Process -Id $proc -Force -ErrorAction SilentlyContinue }
        }

        if ($FrontendChanged) {
            Write-Host "Frontend changed — restart dev server to pick up changes." -ForegroundColor Green
        }
    }

    Start-Sleep $IntervalSeconds
}
