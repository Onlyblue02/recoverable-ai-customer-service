Set-StrictMode -Version Latest

function Get-LocalDemoProcessValidation {
    param(
        [Parameter(Mandatory)]$Record,
        [Parameter(Mandatory)][ValidateSet("backend", "frontend")][string]$Role,
        [switch]$RequireListeningPort
    )

    $processId = [int]$Record."${Role}_process_id"
    $expectedExecutable = [string]$Record."${Role}_executable_path"
    $expectedPort = [int]$Record."${Role}_port"
    $sessionToken = [string]$Record.session_token
    $repositoryRoot = [string]$Record.repository_root

    if ($Record.record_version -ne 2 -or [string]::IsNullOrWhiteSpace($sessionToken) -or
        [string]::IsNullOrWhiteSpace($repositoryRoot) -or [string]::IsNullOrWhiteSpace($expectedExecutable) -or
        $processId -le 0 -or $expectedPort -le 0) {
        return [pscustomobject]@{ IsOwned = $false; Reason = "record_metadata_invalid"; Process = $null }
    }

    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return [pscustomobject]@{ IsOwned = $false; Reason = "process_not_found"; Process = $null }
    }
    if ([string]::IsNullOrWhiteSpace($process.Path) -or $process.Path -ine $expectedExecutable) {
        return [pscustomobject]@{ IsOwned = $false; Reason = "executable_mismatch"; Process = $process }
    }

    try {
        $processInfo = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    }
    catch {
        return [pscustomobject]@{ IsOwned = $false; Reason = "command_line_unavailable"; Process = $process }
    }
    $commandLine = [string]$processInfo.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine) -or -not $commandLine.Contains($sessionToken) -or
        -not $commandLine.Contains($repositoryRoot)) {
        return [pscustomobject]@{ IsOwned = $false; Reason = "command_line_mismatch"; Process = $process }
    }

    if ($RequireListeningPort) {
        $listener = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $expectedPort -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.OwningProcess -eq $processId } |
            Select-Object -First 1
        if ($null -eq $listener) {
            return [pscustomobject]@{ IsOwned = $false; Reason = "listener_mismatch"; Process = $process }
        }
    }

    return [pscustomobject]@{ IsOwned = $true; Reason = "verified"; Process = $process }
}

function Stop-VerifiedLocalDemoProcess {
    param(
        [Parameter(Mandatory)]$Record,
        [Parameter(Mandatory)][ValidateSet("backend", "frontend")][string]$Role,
        [switch]$RequireListeningPort
    )

    $validation = Get-LocalDemoProcessValidation -Record $Record -Role $Role -RequireListeningPort:$RequireListeningPort
    if (-not $validation.IsOwned) {
        Write-Warning "Did not stop $Role process: $($validation.Reason)."
        return $false
    }

    Stop-Process -Id $validation.Process.Id -Force -ErrorAction Stop
    return $true
}
