# StreamOps-managed repo-local start script.
[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(0, 2147483647)]
    [int]$OutputIndex = 0,
    [string]$DataDir,
    [ValidateRange(0.01, 30)]
    [double]$CaptureTimeout = 3,
    [ValidateSet("critical", "error", "warning", "info", "debug", "trace")]
    [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Repo-local virtual environment is missing. Run install-streamops-node.ps1 first."
}

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $repoRoot ".streamops\node"
}
elseif (-not [IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}

$logDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logDir "node-$timestamp.stdout.log"
$stderrLog = Join-Path $logDir "node-$timestamp.stderr.log"
$arguments = @(
    "-m", "streamops.cli", "runserver",
    "--host", $BindHost,
    "--port", $Port,
    "--output-index", $OutputIndex,
    "--data-dir", ('"{0}"' -f $DataDir.Replace('"', '\"')),
    "--capture-timeout", $CaptureTimeout.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--log-level", $LogLevel
)

$process = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

$probeHost = if ($BindHost -eq "0.0.0.0") { "127.0.0.1" } else { $BindHost }
$healthUrl = "http://${probeHost}:$Port/api/v1/health"
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 500
    $process.Refresh()
    if ($process.HasExited) {
        throw "streamops-node exited during startup. Inspect $stderrLog"
    }
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        if ($health.status -eq "ok") {
            $runtimePath = Join-Path $DataDir "runtime.json"
            $runtimePid = if (Test-Path -LiteralPath $runtimePath) {
                (Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json).pid
            }
            else {
                $process.Id
            }
            Write-Host "streamops-node is running (PID $runtimePid): $healthUrl"
            Write-Host "Logs: $logDir"
            exit 0
        }
    }
    catch {
        # The server may still be initializing DXGI.
    }
}

if (-not $process.HasExited) {
    & (Join-Path $PSScriptRoot "stop-streamops-node.ps1") -DataDir $DataDir
}
throw "streamops-node did not become healthy within 15 seconds. Inspect $stderrLog"
