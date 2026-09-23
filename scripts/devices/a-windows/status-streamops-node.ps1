# StreamOps-managed repo-local status script.
[CmdletBinding()]
param([string]$DataDir)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Test-RepoOwnedProcess([int]$ProcessId) {
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) {
        return $false
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate.Path) -and
        $candidate.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $false
    }
    $parent = Get-Process -Id $processInfo.ParentProcessId -ErrorAction SilentlyContinue
    return $null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.Path) -and
        $parent.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)
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

$runtimePath = Join-Path $DataDir "runtime.json"
if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host "streamops-node is not running (no runtime state)."
    exit 1
}

$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$process = Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue
if ($null -eq $process -or -not (Test-RepoOwnedProcess $runtime.pid)) {
    Write-Host "streamops-node is not running (stale runtime state for PID $($runtime.pid))."
    exit 1
}

$probeHost = if ($runtime.host -eq "0.0.0.0") { "127.0.0.1" } else { $runtime.host }
$healthUrl = "http://${probeHost}:$($runtime.port)/api/v1/health"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
}
catch {
    Write-Host "streamops-node process $($runtime.pid) exists but health check failed: $healthUrl"
    exit 1
}

Write-Host "streamops-node is running (PID $($runtime.pid), port $($runtime.port), output $($runtime.output_index))."
Write-Host "Health: $healthUrl"
exit 0
