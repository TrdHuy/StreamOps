# StreamOps-managed repo-local bootstrap script.
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$ConfigureFirewall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$venvRoot = Join-Path $repoRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating repo-local virtual environment: $venvRoot"
    & python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the repo-local virtual environment."
    }
}

$extras = if ($Dev) { "server,dev" } else { "server" }
Write-Host "Installing StreamOps from the current repository ($extras)..."
Push-Location $repoRoot
try {
    & $python -m pip install --editable ".[${extras}]"
    if ($LASTEXITCODE -ne 0) {
        throw "StreamOps installation failed."
    }
}
finally {
    Pop-Location
}

if ($ConfigureFirewall) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "-ConfigureFirewall requires an elevated PowerShell session."
    }

    $ruleName = "StreamOps Node (repo-local)"
    $rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($null -eq $rule) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Enabled True `
            -Profile Private `
            -Program $python `
            -RemoteAddress LocalSubnet | Out-Null
    }
    else {
        $rule | Set-NetFirewallRule -Direction Inbound -Action Allow -Enabled True -Profile Private | Out-Null
        $rule | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $python | Out-Null
        $rule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress LocalSubnet | Out-Null
    }
    Write-Host "Firewall rule ready: $ruleName"
}

Write-Host "Repo-local StreamOps node is ready."
Write-Host "Run: $python -m streamops.cli runserver --port 8765"
