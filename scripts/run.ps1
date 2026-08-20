# Zarbin launcher (Windows PowerShell). Usage: ./scripts/run.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "uv is not installed. Install it from https://docs.astral.sh/uv/ then re-run." -ForegroundColor Yellow
  exit 1
}
# OneDrive/Windows blocks hardlinks into the venv; copy mode is resilient.
$env:UV_LINK_MODE = "copy"

$data = if ($env:ZARIN_DATA_PATH) { $env:ZARIN_DATA_PATH } else { Join-Path $root "data\other_challenge_data.csv.gz" }
if (-not (Test-Path $data)) {
  Write-Host "Dataset not found at: $data" -ForegroundColor Yellow
  Write-Host "Place other_challenge_data.csv.gz under data\ (or set ZARIN_DATA_PATH)." -ForegroundColor Yellow
  exit 1
}

Write-Host "Starting Zarbin... first run builds data marts (~30s)." -ForegroundColor Cyan
uv run zarin
