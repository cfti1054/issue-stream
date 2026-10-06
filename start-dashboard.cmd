@echo off
rem Double-click: collector + API + web dashboard (free, no Docker)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dashboard.ps1" %*
