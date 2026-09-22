param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

$ErrorActionPreference = "Stop"

$hwmonScript = Join-Path $RepoRoot "scripts\hwmon.ps1"
if (-not (Test-Path -LiteralPath $hwmonScript)) {
    throw "Missing hwmon script: $hwmonScript"
}

$profiles = @(
    (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "WindowsPowerShell\Microsoft.PowerShell_profile.ps1"),
    (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "PowerShell\Microsoft.PowerShell_profile.ps1")
)

$functionBlock = @"

function hwmon {
    & "$hwmonScript" @args
}
"@

foreach ($profilePath in $profiles) {
    $profileDir = Split-Path -Parent $profilePath
    if (-not (Test-Path -LiteralPath $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }

    $content = ""
    if (Test-Path -LiteralPath $profilePath) {
        $content = Get-Content -LiteralPath $profilePath -Raw
    }

    $pattern = "(?ms)^\s*function\s+hwmon\s*\{.*?^\s*\}\s*"
    if ($content -match $pattern) {
        $content = [Regex]::Replace($content, $pattern, "")
    }

    $newContent = $content.TrimEnd() + $functionBlock + [Environment]::NewLine
    Set-Content -LiteralPath $profilePath -Value $newContent -Encoding UTF8
    Write-Host "updated: $profilePath"
}
