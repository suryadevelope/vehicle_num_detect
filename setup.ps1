<# 
.SYNOPSIS
    Setup script for Dual Camera ALPR System with Telegram notifications

.DESCRIPTION
    This script creates a virtual environment (.venv), installs dependencies,
    and sets up the ALPR system for dual camera license plate detection
    with serial communication and Telegram notifications.

.NOTES
    Author: Fast ALPR Setup
    Requires: PowerShell 5.1+, Python 3.10+
#>

param(
    [switch]$ForceRecreate,
    [switch]$SkipVenv,
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$venvDir = Join-Path $scriptDir ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$pipExe = Join-Path $venvDir "Scripts\pip.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Dual Camera ALPR System Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

function Check-PythonVersion {
    try {
        $version = & $PythonPath --version 2>&1
        Write-Host "Found Python: $version" -ForegroundColor Green
        if ($version -match "Python (\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
                Write-Error "Python 3.10 or higher is required. Found $version"
                exit 1
            }
        }
        return $true
    } catch {
        Write-Error "Python not found. Please install Python 3.10+ from https://python.org"
        exit 1
    }
}

function Create-VirtualEnvironment {
    if ((Test-Path $venvDir) -and !$ForceRecreate) {
        Write-Host "Virtual environment already exists at $venvDir" -ForegroundColor Yellow
        Write-Host "Use -ForceRecreate to recreate it" -ForegroundColor Yellow
        return
    }
    
    if ((Test-Path $venvDir) -and $ForceRecreate) {
        Write-Host "Removing existing virtual environment..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $venvDir
    }
    
    Write-Host "Creating virtual environment at $venvDir..." -ForegroundColor Cyan
    & $PythonPath -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create virtual environment"
        exit 1
    }
    Write-Host "Virtual environment created successfully!" -ForegroundColor Green
}

function Upgrade-Pip {
    Write-Host "Upgrading pip..." -ForegroundColor Cyan
    & $pipExe install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to upgrade pip, continuing anyway..."
    }
}

function Install-Dependencies {
    Write-Host "Installing dependencies..." -ForegroundColor Cyan
    
    # Install ONNX runtime for Windows (DirectML)
    & $pipExe install onnxruntime-directml
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to install onnxruntime-directml, trying CPU version..."
        & $pipExe install onnxruntime
    }
    
    # Install fast-alpr with ONNX dependencies
    & $pipExe install -e .[onnx-directml]
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install fast-alpr"
        exit 1
    }
    
    # Install additional requirements
    $requirements = @(
        "opencv-python",
        "pyserial",
        "requests",
        "numpy"
    )
    
    foreach ($req in $requirements) {
        Write-Host "Installing $req..." -ForegroundColor Cyan
        & $pipExe install $req
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to install $req"
        }
    }
    
    Write-Host "All dependencies installed!" -ForegroundColor Green
}

function Invoke-PythonCode {
    # Windows PowerShell 5.1 strips embedded double quotes when passing a
    # multi-line string to a native exe via -c, which breaks the Python code.
    # Writing the code to a temp .py file and running it avoids that.
    param([string]$Code)
    $tempFile = Join-Path $env:TEMP ("alpr_check_" + [guid]::NewGuid().ToString("N") + ".py")
    try {
        Set-Content -Path $tempFile -Value $Code -Encoding utf8
        & $pythonExe $tempFile | Out-Host
        return $LASTEXITCODE
    } finally {
        Remove-Item -Path $tempFile -ErrorAction SilentlyContinue
    }
}

function Verify-Installation {
    Write-Host "Verifying installation..." -ForegroundColor Cyan

    $testScript = @'
import sys
try:
    import cv2
    import serial
    import requests
    import numpy as np
    from fast_alpr import ALPR
    print("All imports successful!")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"NumPy version: {np.__version__}")
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)
'@

    $exitCode = Invoke-PythonCode -Code $testScript
    if ($exitCode -ne 0) {
        Write-Error "Installation verification failed"
        exit 1
    }
    Write-Host "Installation verified successfully!" -ForegroundColor Green
}

function Check-Config {
    $configPath = Join-Path $scriptDir "config.json"
    if (-not (Test-Path $configPath)) {
        Write-Warning "config.json not found! Please create it with your Telegram bot token and chat ID."
        return
    }
    
    $config = Get-Content $configPath | ConvertFrom-Json
    if ($config.telegram.bot_token -eq "YOUR_BOT_TOKEN_HERE" -or $config.telegram.chat_id -eq "YOUR_CHAT_ID_HERE") {
        Write-Warning "Please update config.json with your actual Telegram bot token and chat ID"
    } else {
        Write-Host "Config.json looks good!" -ForegroundColor Green
    }
}

function Show-CameraInfo {
    Write-Host ""
    Write-Host "Camera Detection:" -ForegroundColor Cyan
    $testScript = @'
import cv2
for i in range(4):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Camera {i}: {w}x{h} - AVAILABLE")
        cap.release()
    else:
        print(f"Camera {i}: NOT AVAILABLE")
'@
    Invoke-PythonCode -Code $testScript | Out-Null
}

function Show-SerialPorts {
    Write-Host ""
    Write-Host "Available Serial Ports:" -ForegroundColor Cyan
    $ports = [System.IO.Ports.SerialPort]::GetPortNames()
    if ($ports.Count -eq 0) {
        Write-Host "  No serial ports found" -ForegroundColor Yellow
    } else {
        foreach ($port in $ports) {
            Write-Host "  $port"
        }
    }
}

function Create-RunScript {
    $runScript = Join-Path $scriptDir "run_alpr.ps1"
    # Single-quoted here-string: nothing is expanded, so $ and \ are written as-is.
    $content = @'
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
'@
    Set-Content -Path $runScript -Value $content -Encoding UTF8
    Write-Host "Created run_alpr.ps1" -ForegroundColor Green
}

# Main execution
Write-Host "Step 1: Checking Python installation..." -ForegroundColor Cyan
Check-PythonVersion

if (!$SkipVenv) {
    Write-Host ""
    Write-Host "Step 2: Creating virtual environment..." -ForegroundColor Cyan
    Create-VirtualEnvironment
    
    Write-Host ""
    Write-Host "Step 3: Upgrading pip..." -ForegroundColor Cyan
    Upgrade-Pip
    
    Write-Host ""
    Write-Host "Step 4: Installing dependencies..." -ForegroundColor Cyan
    Install-Dependencies
    
    Write-Host ""
    Write-Host "Step 5: Verifying installation..." -ForegroundColor Cyan
    Verify-Installation
} else {
    Write-Host "Skipping virtual environment setup (--SkipVenv)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Step 6: Checking configuration..." -ForegroundColor Cyan
Check-Config

Write-Host ""
Write-Host "Step 7: Detecting cameras..." -ForegroundColor Cyan
Show-CameraInfo

Write-Host ""
Write-Host "Step 8: Checking serial ports..." -ForegroundColor Cyan
Show-SerialPorts

Write-Host ""
Write-Host "Step 9: Creating run script..." -ForegroundColor Cyan
Create-RunScript

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host "  1. Edit config.json with your Telegram bot token and chat ID"
Write-Host "  2. Connect your cameras (check indices in config.json)"
Write-Host "  3. Connect your serial device (check port in config.json)"
Write-Host "  4. Run the system: .\run_alpr.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Controls during runtime:" -ForegroundColor Cyan
Write-Host "  'q' - Quit" -ForegroundColor Gray
Write-Host "  'a' - Manual trigger Path A" -ForegroundColor Gray
Write-Host "  'b' - Manual trigger Path B" -ForegroundColor Gray
Write-Host ""