<#
.SYNOPSIS
    Financial Command Center'i Windows'ta baslatir (ROADMAP 5.4).

.EXAMPLE
    .\run.ps1              # API + scheduler + web paneli -> http://127.0.0.1:8000
    .\run.ps1 -Backtest    # backtest raporu yazdirir
    .\run.ps1 -Ui          # eski Flet paneli (artik birincil arayuz degil)
    .\run.ps1 -All         # API'yi ayri pencerede baslatip Flet panelini acar
#>
[CmdletBinding()]
param(
    [switch]$Ui,
    [switch]$All,
    [switch]$Backtest,
    [int]$Horizon = 5
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Sanal ortam bulunamadi: $python`nOnce: py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}

if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Warning ".env olusturuldu (.env.example kopyasi). API anahtarlarini doldurun."
}

$env:PYTHONPATH = $root
Set-Location $root

if ($Backtest) {
    & $python -m core.backtest --horizon $Horizon
    exit $LASTEXITCODE
}

if ($All) {
    Write-Host "API ayri pencerede baslatiliyor..." -ForegroundColor Cyan
    Start-Process -FilePath $python -ArgumentList "main.py" -WorkingDirectory $root
    Start-Sleep -Seconds 4
    & $python -m flet run "ui\main_app.py"
    exit $LASTEXITCODE
}

if ($Ui) {
    Write-Host "Panel aciliyor (API ayri calismali)..." -ForegroundColor Cyan
    & $python -m flet run "ui\main_app.py"
    exit $LASTEXITCODE
}

Write-Host "API + scheduler + panel baslatiliyor -> http://127.0.0.1:8000" -ForegroundColor Cyan
& $python main.py
exit $LASTEXITCODE
