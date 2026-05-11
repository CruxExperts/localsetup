#!/usr/bin/env pwsh
# Localsetup v3 does not support native Windows installs.

Write-Host "Localsetup v3 supports Windows through WSL2 only."
Write-Host ""
Write-Host "Run Localsetup from inside WSL and point agents at WSL paths:"
Write-Host "  wsl"
Write-Host "  cd /path/to/repo"
Write-Host "  ./install --directory ."
Write-Host ""
Write-Host "For automation inside WSL, use:"
Write-Host "  ./install --directory . --non-interactive --yes"
Write-Host ""
Write-Host "Native PowerShell installation was intentionally removed for v3."
exit 1
