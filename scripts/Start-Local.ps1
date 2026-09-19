[CmdletBinding()]
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendDirectory = Join-Path $projectRoot 'frontend'
$backendDirectory = Join-Path $projectRoot 'backend'
$backendPython = Join-Path $backendDirectory '.venv\Scripts\python.exe'
$frontendPackage = Join-Path $frontendDirectory 'package.json'

if (-not (Test-Path -LiteralPath $backendPython -PathType Leaf)) {
    throw 'Backend environment is missing. Create backend\.venv and install the project first.'
}
if (-not (Test-Path -LiteralPath $frontendPackage -PathType Leaf)) {
    throw 'Frontend package.json is missing.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Node.js/npm is missing from PATH. Install Node.js 22.12 or newer.'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDirectory 'node_modules') -PathType Container)) {
    throw 'Frontend dependencies are missing. Run npm install once inside the frontend folder.'
}

function Test-LocalUrl {
    param([Parameter(Mandatory)][string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-PortInUse {
    param([Parameter(Mandatory)][int]$Port)

    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-LocalUrl {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$Seconds = 12
    )

    $waitDeadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (Test-LocalUrl -Url $Url) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $waitDeadline)
    return $false
}

function Start-DevelopmentWindow {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$Command
    )

    $escapedDirectory = $WorkingDirectory.Replace('"', '""')
    $windowCommand = "title $Title && cd /d `"$escapedDirectory`" && $Command"
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $windowCommand -WorkingDirectory $WorkingDirectory
}

$frontendUrl = 'http://localhost:5173/'
$backendHealthUrl = 'http://127.0.0.1:8000/api/health'
$frontendReady = Test-LocalUrl -Url $frontendUrl
$backendReady = Test-LocalUrl -Url $backendHealthUrl

if (-not $backendReady) {
    if (Test-PortInUse -Port 8000) {
        $backendReady = Wait-LocalUrl -Url $backendHealthUrl
        if (-not $backendReady) {
            throw 'Port 8000 is occupied by another program that is not SupportPilot. Close it, then run this launcher again.'
        }
    }
    else {
        $quotedPython = '"' + $backendPython.Replace('"', '""') + '"'
        Start-DevelopmentWindow `
            -Title 'SupportPilot AI - Backend (keep open)' `
            -WorkingDirectory $backendDirectory `
            -Command "$quotedPython -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
    }
}

if (-not $frontendReady) {
    if (Test-PortInUse -Port 5173) {
        $frontendReady = Wait-LocalUrl -Url $frontendUrl
        if (-not $frontendReady) {
            throw 'Port 5173 is occupied by another program that is not SupportPilot. Close it, then run this launcher again.'
        }
    }
    else {
        Start-DevelopmentWindow `
            -Title 'SupportPilot AI - Frontend (keep open)' `
            -WorkingDirectory $frontendDirectory `
            -Command 'npm.cmd run dev -- --host 127.0.0.1 --port 5173'
    }
}

$deadline = (Get-Date).AddSeconds(45)
do {
    $frontendReady = Test-LocalUrl -Url $frontendUrl
    $backendReady = Test-LocalUrl -Url $backendHealthUrl
    if ($frontendReady -and $backendReady) {
        break
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

if (-not $frontendReady -or -not $backendReady) {
    throw 'Startup timed out. Keep both new command windows open and read their last error messages.'
}

Write-Host 'SupportPilot AI is running.' -ForegroundColor Green
Write-Host "Frontend: $frontendUrl"
Write-Host "Backend:  $backendHealthUrl"
Write-Host 'Keep both SupportPilot command windows open while using localhost.'

if (-not $NoBrowser) {
    $chromeCandidates = @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }

    if ($chromeCandidates.Count -gt 0) {
        Start-Process -FilePath $chromeCandidates[0] -ArgumentList $frontendUrl
    }
    else {
        Start-Process $frontendUrl
    }
}
