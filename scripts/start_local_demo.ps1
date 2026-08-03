[CmdletBinding()]
param(
    [int]$BackendPort = 0,
    [int]$FrontendPort = 5173,
    [switch]$SkipInstall,
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $PSScriptRoot ".local-demo-processes.json"
. (Join-Path $PSScriptRoot "local_demo_process_guard.ps1")

function Require-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Missing $Name. Install it and reopen PowerShell."
    }
    return $command.Source
}

function Get-PnpmLauncher([string]$RepositoryRoot) {
    $pnpm = Get-Command "pnpm" -ErrorAction SilentlyContinue
    if ($null -ne $pnpm) {
        return [pscustomobject]@{ FilePath = $pnpm.Source; Prefix = @() }
    }

    $corepack = Get-Command "corepack" -ErrorAction SilentlyContinue
    if ($null -ne $corepack) {
        $packageManifest = Get-Content -LiteralPath (Join-Path $RepositoryRoot "web\package.json") -Raw | ConvertFrom-Json
        $packageManager = $packageManifest.packageManager
        if ($packageManager -notmatch "^pnpm@\d+\.\d+\.\d+$") {
            throw "web/package.json must declare an exact pnpm packageManager version."
        }
        Write-Host "pnpm is not on PATH; using corepack $packageManager."
        return [pscustomobject]@{ FilePath = $corepack.Source; Prefix = @($packageManager) }
    }

    throw "Missing pnpm and corepack. Install Node.js with Corepack or pnpm, then reopen PowerShell."
}

function Test-AvailableLoopbackPort([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch [System.Net.Sockets.SocketException] {
        return $false
    }
    finally {
        $listener.Stop()
    }
}

function Select-BackendPort([int]$RequestedPort) {
    $candidates = if ($RequestedPort -gt 0) { @($RequestedPort) } else { @(8000, 8010, 8020, 18000) }
    foreach ($candidate in $candidates) {
        if (Test-AvailableLoopbackPort $candidate) {
            return $candidate
        }
    }
    if ($RequestedPort -gt 0) {
        throw "Requested backend port $RequestedPort is unavailable."
    }

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        $fallbackPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
    Write-Host "Preferred backend ports are unavailable; using Windows-assigned port $fallbackPort."
    return $fallbackPort
}

if (Test-Path -LiteralPath $processFile) {
    try {
        $existingProcesses = Get-Content -Raw -LiteralPath $processFile | ConvertFrom-Json
        $existingBackend = Get-LocalDemoProcessValidation -Record $existingProcesses -Role backend -RequireListeningPort
        $existingFrontend = Get-LocalDemoProcessValidation -Record $existingProcesses -Role frontend -RequireListeningPort
    }
    catch {
        $existingBackend = [pscustomobject]@{ IsOwned = $false }
        $existingFrontend = [pscustomobject]@{ IsOwned = $false }
    }
    if ($existingBackend.IsOwned -and $existingFrontend.IsOwned) {
        if ($OpenBrowser) {
            $existingFrontendPort = [int]$existingProcesses.frontend_port
            $existingDemoReady = $false
            try {
                Invoke-WebRequest -Uri "http://127.0.0.1:$existingFrontendPort/" -UseBasicParsing -TimeoutSec 1 | Out-Null
                $existingDemoReady = $true
            }
            catch {
                # A broken prior startup must not be presented as ready.
            }
            if ($existingDemoReady) {
                Write-Host "Local synthetic demo is already running. Opening the consumer page."
                try {
                    Start-Process "http://127.0.0.1:$existingFrontendPort" -ErrorAction Stop
                }
                catch {
                    Write-Host "Open http://127.0.0.1:$existingFrontendPort in your browser."
                }
                return
            }
        }
        throw "A local demo process is already running. Run .\scripts\stop_local_demo.ps1 first."
    }
    Remove-Item -LiteralPath $processFile -Force
    Write-Host "Removed stale local demo process record."
}

$python = Require-Command "python"
$uv = Require-Command "uv"
$node = Require-Command "node"
$pnpm = Get-PnpmLauncher $repositoryRoot
$selectedBackendPort = Select-BackendPort $BackendPort

if (-not (Test-AvailableLoopbackPort $FrontendPort)) {
    throw "Frontend port $FrontendPort is unavailable. Set a different value with -FrontendPort."
}

$env:UV_LINK_MODE = "copy"
$env:RACS_BACKEND_PORT = "$selectedBackendPort"
$env:VITE_RACS_BACKEND_PORT = "$selectedBackendPort"
$projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$viteEntryPoint = Join-Path $repositoryRoot "web\node_modules\vite\bin\vite.js"
$sessionToken = [guid]::NewGuid().ToString("N")

Push-Location $repositoryRoot
$backend = $null
$backendRuntime = $null
$backendRecord = $null
$frontendRecord = $null
$frontend = $null
try {
    if (-not $SkipInstall) {
        & $uv sync --frozen --all-groups
        if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
        & $pnpm.FilePath @($pnpm.Prefix) --dir web install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw "pnpm install failed." }
    }
    if (-not (Test-Path -LiteralPath $projectPython)) {
        throw "Python environment is missing. Run this script once without -SkipInstall."
    }
    if (-not (Test-Path -LiteralPath $viteEntryPoint)) {
        throw "Frontend dependencies are missing. Run this script once without -SkipInstall."
    }

    $backend = Start-Process -FilePath $projectPython -ArgumentList @("-m", "customer_service.local_server", "--demo-token", $sessionToken, "--demo-repository", $repositoryRoot) -WorkingDirectory $repositoryRoot -PassThru -WindowStyle Hidden
    $backendRecord = [pscustomobject]@{
        record_version = 2
        session_token = $sessionToken
        repository_root = $repositoryRoot
        backend_process_id = $backend.Id
        backend_executable_path = $projectPython
        backend_port = $selectedBackendPort
        frontend_process_id = 0
        frontend_executable_path = "pending"
        frontend_port = $FrontendPort
    }
    $healthy = $false
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:$selectedBackendPort/health/live" -TimeoutSec 1 | Out-Null
            $healthy = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $healthy) {
        Stop-VerifiedLocalDemoProcess -Record $backendRecord -Role backend | Out-Null
        throw "Backend did not start on port $selectedBackendPort."
    }
    $backendConnection = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $selectedBackendPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $backendConnection) {
        $backendRuntime = Get-Process -Id $backendConnection.OwningProcess -ErrorAction SilentlyContinue
        if ($null -ne $backendRuntime) {
            $backendRecord.backend_process_id = $backendRuntime.Id
            $backendRecord.backend_executable_path = $backendRuntime.Path
        }
    }

    Write-Host "Starting consumer page..."
    $frontendArguments = @("--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort")
    $nodeArguments = @("--title=RACS-local-demo-$sessionToken", $viteEntryPoint) + $frontendArguments
    $frontend = Start-Process -FilePath $node -ArgumentList $nodeArguments -WorkingDirectory (Join-Path $repositoryRoot "web") -PassThru -WindowStyle Hidden
    $frontendRecord = [pscustomobject]@{
        record_version = 2
        session_token = $sessionToken
        repository_root = $repositoryRoot
        backend_process_id = $backendRecord.backend_process_id
        backend_executable_path = $backendRecord.backend_executable_path
        backend_port = $selectedBackendPort
        frontend_process_id = $frontend.Id
        frontend_executable_path = $node
        frontend_port = $FrontendPort
    }
    $frontendReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        if ($frontend.HasExited) {
            break
        }
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $frontendReady = $true
            break
        }
        catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $frontendReady) {
        throw "Frontend did not start on port $FrontendPort. Run without -SkipInstall if dependencies are missing."
    }

    [pscustomobject]@{
        record_version = 2
        session_token = $sessionToken
        repository_root = $repositoryRoot
        backend_process_id = $frontendRecord.backend_process_id
        backend_executable_path = $frontendRecord.backend_executable_path
        frontend_process_id = $frontendRecord.frontend_process_id
        frontend_executable_path = $frontendRecord.frontend_executable_path
        backend_port = $selectedBackendPort
        frontend_port = $FrontendPort
    } | ConvertTo-Json | Set-Content -LiteralPath $processFile -Encoding UTF8

    Write-Host "Local synthetic demo started."
    Write-Host "Consumer page: http://127.0.0.1:$FrontendPort"
    Write-Host "Backend health: http://127.0.0.1:$selectedBackendPort/health/live"
    Write-Host "No DeepSeek API key is required. Stop with: .\scripts\stop_local_demo.ps1"
    if ($OpenBrowser) {
        try {
            Start-Process "http://127.0.0.1:$FrontendPort" -ErrorAction Stop
        }
        catch {
            Write-Host "Open http://127.0.0.1:$FrontendPort in your browser."
        }
    }
}
catch {
    if ($null -ne $frontendRecord) {
        Stop-VerifiedLocalDemoProcess -Record $frontendRecord -Role frontend | Out-Null
    }
    if ($null -ne $backendRecord) {
        Stop-VerifiedLocalDemoProcess -Record $backendRecord -Role backend | Out-Null
    }
    if (Test-Path -LiteralPath $processFile) {
        Remove-Item -LiteralPath $processFile -Force
    }
    throw
}
finally {
    Pop-Location
}
