# Inicia a Fenotipagem Digital no Windows (sem Docker).
# Uso no PowerShell, dentro da pasta do sistema:
#   powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".env")) {
  $chave = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object { [char]$_ })
  (Get-Content ".env.example") `
    -replace '^SECRET_KEY=.*$', "SECRET_KEY=$chave" `
    -replace '^DB_SCHEMA=.*$', 'DB_SCHEMA=fenotipagem' | Set-Content ".env" -Encoding UTF8
  Write-Host "Criei o arquivo .env. Preencha ADMIN_EMAIL, ADMIN_PASSWORD e DATABASE_URL e rode o iniciar.ps1 de novo."
  exit 0
}
if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
}
.\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt
if (-not $env:DATA_DIR) { $env:DATA_DIR = Join-Path $PSScriptRoot "dados" }
$porta = if ($env:PORT) { $env:PORT } else { "8000" }
Set-Location backend
Write-Host "Fenotipagem Digital em http://localhost:$porta  (Ctrl+C para parar)"
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $porta --env-file ..\.env
