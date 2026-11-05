$ErrorActionPreference = 'Stop'
$client = $PSScriptRoot
$project = Split-Path -Parent $client
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python.exe' }
Set-Location -LiteralPath $client
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8744
