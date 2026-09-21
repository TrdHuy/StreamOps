param(
    [string]$SceneName = "gaming-poc",
    [int]$VideoSeconds = 5,
    [string]$ArtifactRoot = "artifacts/e2e"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "FAIL: $Message"
    exit 1
}

function Run-Step([string]$Name, [scriptblock]$Command) {
    Write-Host "RUN: $Name"
    $output = & $Command 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($output) {
            $output | Select-Object -Last 40 | Out-Host
        }
        Fail "$Name failed with exit code $LASTEXITCODE"
    }
    return $output
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail "missing expected file: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-LatestReviewDir([string]$Root, [string]$Scene) {
    $sceneRoot = Join-Path $Root $Scene
    if (-not (Test-Path -LiteralPath $sceneRoot)) {
        Fail "review artifact directory not found: $sceneRoot"
    }
    $latest = Get-ChildItem -LiteralPath $sceneRoot -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        Fail "no review timestamp directory found under: $sceneRoot"
    }
    return $latest.FullName
}

function Assert-ReviewArtifacts([string]$ReviewDir, [bool]$RequireVideo) {
    $previewPath = Join-Path $ReviewDir "preview.png"
    $verifyPath = Join-Path $ReviewDir "verify.json"
    $reportPath = Join-Path $ReviewDir "report.md"

    foreach ($path in @($previewPath, $verifyPath, $reportPath)) {
        if (-not (Test-Path -LiteralPath $path)) {
            Fail "missing review artifact: $path"
        }
    }

    $verify = Read-JsonFile $verifyPath
    if ($verify.status -ne "PASS") {
        Fail "review verify status is $($verify.status), expected PASS: $verifyPath"
    }

    if ($RequireVideo) {
        $videoPath = [string]$verify.artifacts.video
        if (-not $videoPath) {
            Fail "verify.json does not include artifacts.video"
        }
        if (-not (Test-Path -LiteralPath $videoPath)) {
            Fail "video artifact not found: $videoPath"
        }
        if ((Get-Item -LiteralPath $videoPath).Length -le 0) {
            Fail "video artifact is empty: $videoPath"
        }
        if ((Split-Path -Parent $videoPath) -ne $ReviewDir) {
            Fail "video artifact is not in review directory: $videoPath"
        }

        $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
        if (-not $ffprobe) {
            Fail "ffprobe is required to validate that the video opens"
        }
        $duration = & $ffprobe.Source -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $videoPath
        if ($LASTEXITCODE -ne 0) {
            Fail "ffprobe failed for video artifact: $videoPath"
        }
        $durationValue = [double]::Parse($duration, [Globalization.CultureInfo]::InvariantCulture)
        if ($durationValue -le 0) {
            Fail "video artifact duration is not positive: $videoPath"
        }
    }
}

if (-not [Environment]::GetEnvironmentVariable("OBS_WEBSOCKET_PASSWORD")) {
    Fail "OBS_WEBSOCKET_PASSWORD is not set in this shell"
}

$tcp = Test-NetConnection -ComputerName 127.0.0.1 -Port 4455 -WarningAction SilentlyContinue
if (-not $tcp.TcpTestSucceeded) {
    Fail "OBS WebSocket is not reachable at 127.0.0.1:4455"
}

Run-Step "pytest" { python -m pytest } | Out-Null
Run-Step "apply $SceneName" { streamops scene apply $SceneName } | Out-Null

$secondApplyOutput = & streamops scene apply $SceneName
if ($LASTEXITCODE -ne 0) {
    $secondApplyOutput | Out-Host
    Fail "second apply failed with exit code $LASTEXITCODE"
}
if (($secondApplyOutput -join "`n") -notmatch "already matches desired state") {
    $secondApplyOutput | Out-Host
    Fail "second apply was not idempotent"
}
Write-Host "RUN: apply $SceneName second pass"

$reviewRoot = Join-Path $ArtifactRoot "review"
$videoRoot = Join-Path $ArtifactRoot "video"

Run-Step "review $SceneName" { streamops scene review $SceneName --artifact-root $reviewRoot } | Out-Null
$reviewDir = Get-LatestReviewDir $reviewRoot $SceneName
Assert-ReviewArtifacts $reviewDir $false

Run-Step "review $SceneName --video $VideoSeconds" {
    streamops scene review $SceneName --artifact-root $videoRoot --video $VideoSeconds
} | Out-Null
$videoReviewDir = Get-LatestReviewDir $videoRoot $SceneName
Assert-ReviewArtifacts $videoReviewDir $true

Write-Host "PASS"
Write-Host "commands:"
Write-Host "- python -m pytest"
Write-Host "- streamops scene apply $SceneName"
Write-Host "- streamops scene apply $SceneName"
Write-Host "- streamops scene review $SceneName --artifact-root $reviewRoot"
Write-Host "- streamops scene review $SceneName --artifact-root $videoRoot --video $VideoSeconds"
Write-Host "artifacts:"
Write-Host "- review: $reviewDir"
Write-Host "- video: $videoReviewDir"
