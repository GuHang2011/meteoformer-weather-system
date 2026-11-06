param([int]$Port = 8016)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtime = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    throw 'Missing Python environment. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r backend\requirements-model.txt'
}
$frontendPath = Join-Path $projectRoot 'frontend'
Push-Location $frontendPath
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host "MeteoFormer: http://127.0.0.1:$Port"
Write-Host 'Initial administrator password: backend/data/initial-admin-password.txt (unless METEO_ADMIN_PASSWORD is configured).'
Push-Location (Join-Path $projectRoot 'backend')
try { & $runtime -m uvicorn meteo.app:app --host 127.0.0.1 --port $Port --workers 1 }
finally { Pop-Location }
