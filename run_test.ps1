Param(
    [string]$RecognitionUrl = "http://localhost:8000/api/license-plates",
    [string]$MatchUrl = "http://localhost:8000/api/plates/match"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSCommandPath
$ManualScript = Join-Path $Root 'start-manual-capture.ps1'
$KeyFile = Join-Path $Root 'openai-key.txt'

if (-not (Test-Path $ManualScript)) {
    throw "start-manual-capture.ps1 not found at $ManualScript"
}

if (-not $env:OPENAI_API_KEY -and (Test-Path $KeyFile)) {
    $env:OPENAI_API_KEY = (Get-Content -LiteralPath $KeyFile -Raw).Trim()
    Write-Host "[run_test] Loaded OPENAI_API_KEY from openai-key.txt"
}

if (-not $env:OPENAI_API_KEY) {
    Write-Warning "[run_test] OPENAI_API_KEY is not set. GPT-based recognition will fail."
}

Write-Host "[run_test] Recognition URL: $RecognitionUrl"
Write-Host "[run_test] Match URL       : $MatchUrl"

& $ManualScript --recognition-url $RecognitionUrl --match-url $MatchUrl @Args
$ExitCode = $LASTEXITCODE
Write-Host "[run_test] Finished with exit code $ExitCode"
exit $ExitCode
