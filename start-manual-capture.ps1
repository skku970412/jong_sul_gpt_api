Param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$WorkerArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSCommandPath
$CameraScript = Join-Path $Root 'camera-capture\main.py'

function Get-VenvPython {
    param([string]$RootPath)

    $winPython = Join-Path $RootPath '.venv\Scripts\python.exe'
    if (Test-Path $winPython) {
        return $winPython
    }

    $unixPython = Join-Path $RootPath '.venv/bin/python'
    if (Test-Path $unixPython) {
        return $unixPython
    }

    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $systemPython) {
        return $systemPython.Path
    }

    return $null
}

if (-not (Test-Path $CameraScript)) {
    throw "camera-capture/main.py was not found. Run this script from the repository root."
}

$Python = Get-VenvPython -RootPath $Root
if (-not $Python) {
    throw "Unable to locate a python executable. Run .\setup.ps1 (or install python) and try again."
}

$OutputDir = Join-Path $Root 'captured'
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$Timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$OutputPath = Join-Path $OutputDir "manual-$Timestamp.jpg"

$Arguments = @(
    $CameraScript,
    '--skip-firebase',
    '--mock-signal-value', 'manual-trigger',
    '--output-path', $OutputPath
)

if ($WorkerArgs) {
    $Arguments += $WorkerArgs
}

$ReportsDir = Join-Path $Root 'camera-capture\reports'
$ArduinoScript = Join-Path $Root 'start-arduino-workflow.ps1'

Write-Host "[manual-capture] Python: $Python"
Write-Host "[manual-capture] Output: $OutputPath"

& $Python @Arguments
$ExitCode = $LASTEXITCODE

if ($ExitCode -ne 0) {
    Write-Error "[manual-capture] capture worker exited with code $ExitCode."
    exit $ExitCode
}

Write-Host "[manual-capture] Capture finished successfully."

# Try to read the latest report and trigger Arduino workflow if match=true
$latestReport = $null
if (Test-Path $ReportsDir) {
    $latestReport = Get-ChildItem -Path $ReportsDir -Filter 'report-*.json' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

if (-not $latestReport) {
    Write-Warning "[manual-capture] No report file found under $ReportsDir; skipping Arduino trigger."
    exit 0
}

try {
    $reportJson = Get-Content -LiteralPath $latestReport.FullName -Raw | ConvertFrom-Json
} catch {
    Write-Warning "[manual-capture] Failed to parse report $($latestReport.Name): $($_.Exception.Message)"
    exit 0
}

$recognizedPlate = $null
if ($reportJson.plate) { $recognizedPlate = $reportJson.plate }
elseif ($reportJson.match_response -and $reportJson.match_response.plate) { $recognizedPlate = $reportJson.match_response.plate }

$isMatch = $false
if ($reportJson.match_response -and $reportJson.match_response.match -eq $true) {
    $isMatch = $true
}

$plateText = if ($recognizedPlate) { $recognizedPlate } else { "n/a" }
Write-Host ("[manual-capture] Report: plate={0}, match={1}" -f $plateText, $isMatch)

if (-not $isMatch) {
    Write-Host "[manual-capture] Match not confirmed (match=false). Arduino workflow will not run."
    exit 0
}

if (-not (Test-Path $ArduinoScript)) {
    Write-Warning "[manual-capture] start-arduino-workflow.ps1 not found at $ArduinoScript; cannot trigger Arduino."
    exit 0
}

Write-Host "[manual-capture] Match confirmed. Starting Arduino workflow..."
try {
    & $ArduinoScript
    $arduinoExit = $LASTEXITCODE
    Write-Host "[manual-capture] Arduino workflow exited with code $arduinoExit."
} catch {
    Write-Warning "[manual-capture] Failed to launch Arduino workflow: $($_.Exception.Message)"
}

exit 0
