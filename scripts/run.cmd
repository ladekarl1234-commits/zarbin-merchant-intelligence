@echo off
REM Zarbin launcher (Windows cmd). Double-click or run: scripts\run.cmd
cd /d "%~dp0.."
where uv >nul 2>nul || (echo uv is not installed. See https://docs.astral.sh/uv/ && exit /b 1)
set UV_LINK_MODE=copy
echo Starting Zarbin... first run builds data marts (~30s).
echo Open the dashboard at http://localhost:8630
uv run zarin
