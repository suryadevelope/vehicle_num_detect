<#
.SYNOPSIS
    Run the Dual Camera ALPR System
#>

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
$mainScript = Join-Path $scriptDir "main.py"

if (-not (Test-Path $pythonExe)) {
    Write-Error "Virtual environment not found. Run setup.ps1 first."
    exit 1
}

if (-not (Test-Path $mainScript)) {
    Write-Error "main.py not found!"
    exit 1
}

Write-Host "Starting Dual Camera ALPR System..." -ForegroundColor Cyan
& $pythonExe $mainScript
