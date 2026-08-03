[CmdletBinding()]
param(
    [string]$ProcessFile = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProcessFile)) {
    $processFile = Join-Path $PSScriptRoot ".local-demo-processes.json"
}
. (Join-Path $PSScriptRoot "local_demo_process_guard.ps1")

if (-not (Test-Path -LiteralPath $processFile)) {
    Write-Host "No local demo process record was found; nothing to stop."
    exit 0
}

try {
    $processes = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
}
catch {
    Write-Warning "Local demo process record is invalid; no process was stopped."
    Remove-Item -LiteralPath $processFile -Force
    exit 1
}

Stop-VerifiedLocalDemoProcess -Record $processes -Role frontend -RequireListeningPort | Out-Null
Stop-VerifiedLocalDemoProcess -Record $processes -Role backend -RequireListeningPort | Out-Null
Remove-Item -LiteralPath $processFile -Force
Write-Host "Local demo processes stopped."
