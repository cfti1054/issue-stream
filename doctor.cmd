@echo off
rem Double-click: check which free data sources respond on this PC
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-dashboard.ps1" -Doctor
