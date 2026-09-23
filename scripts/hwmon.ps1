param(
    [int]$RefreshSeconds = 23,
    [switch]$Once,
    [string]$GameProcessName = "Diablo IV",
    [int]$PresentMonSampleSeconds = 3,
    [switch]$InstallMissingDependencies,
    [switch]$SkipObs,
    [string]$ObsHost = "127.0.0.1",
    [int]$ObsPort = 4455
)

$ErrorActionPreference = "Continue"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$TempRoot = Join-Path $env:TEMP "streamops-hwmon"

function Format-Number([double]$Value, [int]$Digits = 1) {
    if ([double]::IsNaN($Value) -or [double]::IsInfinity($Value)) {
        return "n/a"
    }
    return $Value.ToString("N$Digits", [Globalization.CultureInfo]::InvariantCulture)
}

function Format-BytesPerSecond([double]$Bytes) {
    if ($null -eq $Bytes) { return "n/a" }
    $units = @("B/s", "KB/s", "MB/s", "GB/s")
    $value = [double]$Bytes
    $unitIndex = 0
    while ($value -ge 1024 -and $unitIndex -lt ($units.Count - 1)) {
        $value = $value / 1024
        $unitIndex++
    }
    return "$(Format-Number $value 1) $($units[$unitIndex])"
}

function Format-MiB([double]$MiB) {
    if ($null -eq $MiB) { return "n/a" }
    if ($MiB -ge 1024) {
        return "$(Format-Number ($MiB / 1024) 1) GiB"
    }
    return "$(Format-Number $MiB 0) MiB"
}

function Get-FirstCommandPath([string[]]$Names) {
    foreach ($name in $Names) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Get-CounterSamples([string[]]$Paths) {
    try {
        return (Get-Counter -Counter $Paths -ErrorAction Stop).CounterSamples
    } catch {
        return @()
    }
}

function Get-SystemStats {
    $samples = Get-CounterSamples @(
        "\Processor(_Total)\% Processor Time",
        "\Memory\Available MBytes",
        "\PhysicalDisk(_Total)\Disk Read Bytes/sec",
        "\PhysicalDisk(_Total)\Disk Write Bytes/sec",
        "\Network Interface(*)\Bytes Received/sec",
        "\Network Interface(*)\Bytes Sent/sec"
    )

    $byPath = @{}
    foreach ($sample in $samples) {
        $byPath[$sample.Path.ToLowerInvariant()] = [double]$sample.CookedValue
    }

    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    $totalMemMiB = 0.0
    $availMemMiB = 0.0
    if ($os) {
        $totalMemMiB = [double]$os.TotalVisibleMemorySize / 1024
        $availMemMiB = [double]$os.FreePhysicalMemory / 1024
    }
    if ($byPath.Keys | Where-Object { $_ -like "*\memory\available mbytes" }) {
        $availKey = ($byPath.Keys | Where-Object { $_ -like "*\memory\available mbytes" } | Select-Object -First 1)
        $availMemMiB = $byPath[$availKey]
    }

    $read = 0.0
    $write = 0.0
    $netRx = 0.0
    $netTx = 0.0
    foreach ($key in $byPath.Keys) {
        if ($key -like "*\physicaldisk(_total)\disk read bytes/sec") { $read = $byPath[$key] }
        elseif ($key -like "*\physicaldisk(_total)\disk write bytes/sec") { $write = $byPath[$key] }
        elseif ($key -like "*\network interface(*\bytes received/sec") { $netRx += $byPath[$key] }
        elseif ($key -like "*\network interface(*\bytes sent/sec") { $netTx += $byPath[$key] }
    }

    $cpu = $null
    $cpuKey = ($byPath.Keys | Where-Object { $_ -like "*\processor(_total)\% processor time" } | Select-Object -First 1)
    if ($cpuKey) { $cpu = $byPath[$cpuKey] }

    $usedMemMiB = [Math]::Max(0, $totalMemMiB - $availMemMiB)
    $usedMemPct = if ($totalMemMiB -gt 0) { ($usedMemMiB / $totalMemMiB) * 100 } else { 0 }

    return [pscustomobject]@{
        CpuPct = $cpu
        RamUsedMiB = $usedMemMiB
        RamTotalMiB = $totalMemMiB
        RamPct = $usedMemPct
        DiskRead = $read
        DiskWrite = $write
        NetRx = $netRx
        NetTx = $netTx
    }
}

function Get-GpuEngineStats {
    $samples = Get-CounterSamples @(
        "\GPU Engine(*)\Utilization Percentage",
        "\GPU Adapter Memory(*)\Dedicated Usage",
        "\GPU Adapter Memory(*)\Shared Usage"
    )

    $engineTotals = @{}
    $dedicatedBytes = 0.0
    $sharedBytes = 0.0
    foreach ($sample in $samples) {
        $path = $sample.Path.ToLowerInvariant()
        $value = [double]$sample.CookedValue
        if ($path -like "*\gpu engine(*\utilization percentage") {
            $engineType = "unknown"
            if ($path -match "engtype_([a-z0-9_]+)\)") {
                $engineType = $Matches[1]
            }
            if (-not $engineTotals.ContainsKey($engineType)) {
                $engineTotals[$engineType] = 0.0
            }
            $engineTotals[$engineType] += $value
        } elseif ($path -like "*\gpu adapter memory(*\dedicated usage") {
            $dedicatedBytes += $value
        } elseif ($path -like "*\gpu adapter memory(*\shared usage") {
            $sharedBytes += $value
        }
    }

    $encode = 0.0
    $decode = 0.0
    foreach ($key in $engineTotals.Keys) {
        if ($key -like "videoencode*") { $encode += $engineTotals[$key] }
        if ($key -like "videodecode*") { $decode += $engineTotals[$key] }
    }

    return [pscustomobject]@{
        Engines = $engineTotals
        EncodePct = $encode
        DecodePct = $decode
        DedicatedMiB = $dedicatedBytes / 1MB
        SharedMiB = $sharedBytes / 1MB
    }
}

function Get-NvidiaStats {
    $smi = Get-FirstCommandPath @("nvidia-smi.exe", "nvidia-smi")
    if (-not $smi) {
        return [pscustomobject]@{ Available = $false; Reason = "nvidia-smi not found" }
    }

    $fields = "name,driver_version,utilization.gpu,utilization.memory,memory.total,memory.used,temperature.gpu,power.draw,clocks.gr,clocks.mem,encoder.stats.sessionCount,encoder.stats.averageFps,encoder.stats.averageLatency"
    try {
        $global:LASTEXITCODE = 0
        $output = & $smi "--query-gpu=$fields" "--format=csv,noheader,nounits" 2>$null
        $line = $output | Select-Object -First 1
        if (($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) -or -not $line) {
            return [pscustomobject]@{ Available = $false; Reason = "nvidia-smi query failed" }
        }
        $parts = $line -split "\s*,\s*"
        return [pscustomobject]@{
            Available = $true
            Name = $parts[0]
            Driver = $parts[1]
            GpuPct = [double]$parts[2]
            MemUtilPct = [double]$parts[3]
            VramTotalMiB = [double]$parts[4]
            VramUsedMiB = [double]$parts[5]
            TempC = [double]$parts[6]
            PowerW = [double]$parts[7]
            GraphicsClockMHz = [double]$parts[8]
            MemoryClockMHz = [double]$parts[9]
            EncoderSessions = [int]$parts[10]
            EncoderFps = [double]$parts[11]
            EncoderLatencyMs = [double]$parts[12]
        }
    } catch {
        return [pscustomobject]@{ Available = $false; Reason = $_.Exception.Message }
    }
}

function Get-DiabloProcess([string]$Name) {
    $escaped = [Regex]::Escape($Name)
    $processes = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match $escaped -or $_.ProcessName -match "Diablo|D4" } |
        Sort-Object CPU -Descending
    return $processes | Select-Object -First 1
}

function Install-PresentMonIfRequested {
    param([switch]$Install)
    if (-not $Install) { return $false }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }

    Write-Host "PresentMon not found; installing Intel.PresentMon.Console with winget..."
    & $winget.Source install --id Intel.PresentMon.Console -e --accept-source-agreements --accept-package-agreements | Out-Host
    return ($LASTEXITCODE -eq 0)
}

function Get-PresentMonPath {
    $path = Get-FirstCommandPath @("PresentMon.exe", "presentmon.exe", "PresentMon", "presentmon")
    if ($path) { return $path }

    $roots = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:ProgramFiles",
        "${env:ProgramFiles(x86)}"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    foreach ($root in $roots) {
        $matches = Get-ChildItem -LiteralPath $root -Recurse -Filter "PresentMon*.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "^PresentMon.*\.exe$" } |
            Sort-Object FullName
        foreach ($match in $matches) {
            if (Test-PresentMonExecutable -Path $match.FullName) {
                return $match.FullName
            }
        }
    }
    return $null
}

function Test-PresentMonExecutable([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $help = & $Path --help 2>&1
        $text = ($help -join "`n")
        return ($text -match "--process_id" -and $text -match "--output_file" -and $text -match "--timed")
    } catch {
        return $false
    }
}

function Get-PresentMonSupportedOptions([string]$Path) {
    $help = & $Path --help 2>&1
    $text = ($help -join "`n")
    return [pscustomobject]@{
        StopExistingSession = ($text -match "--stop_existing_session")
        TerminateAfterTimed = ($text -match "--terminate_after_timed")
        TrackGpuVideo = ($text -match "--track_gpu_video")
        NoConsoleStats = ($text -match "--no_console_stats")
    }
}

function Read-PresentMonCsv([string]$Path, [int]$ProcessId) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $rows = Import-Csv -LiteralPath $Path -ErrorAction Stop |
            Where-Object { $_.ProcessID -eq [string]$ProcessId }
    } catch {
        return $null
    }
    if (-not $rows) { return $null }

    $frameTimes = @()
    foreach ($row in $rows) {
        $candidate = $null
        foreach ($name in @("MsBetweenPresents", "MsBetweenDisplayChange", "MsBetweenAppStart")) {
            if ($row.PSObject.Properties.Name -contains $name) {
                $candidate = $row.$name
                break
            }
        }
        if ($candidate -and $candidate -ne "NA") {
            $value = 0.0
            if ([double]::TryParse($candidate, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$value) -and $value -gt 0) {
                $frameTimes += $value
            }
        }
    }

    if ($frameTimes.Count -eq 0) { return $null }
    $avgMs = ($frameTimes | Measure-Object -Average).Average
    $minMs = ($frameTimes | Measure-Object -Minimum).Minimum
    $maxMs = ($frameTimes | Measure-Object -Maximum).Maximum
    $fps = if ($avgMs -gt 0) { 1000.0 / $avgMs } else { 0 }

    return [pscustomobject]@{
        Frames = $frameTimes.Count
        AvgMs = $avgMs
        MinMs = $minMs
        MaxMs = $maxMs
        Fps = $fps
    }
}

function Get-PresentMonStats([System.Diagnostics.Process]$Process, [int]$Seconds, [switch]$InstallMissing) {
    if (-not $Process) {
        return [pscustomobject]@{ Available = $false; Reason = "Diablo IV process not found" }
    }

    $presentMon = Get-PresentMonPath
    if (-not $presentMon) {
        Install-PresentMonIfRequested -Install:$InstallMissing | Out-Null
        $presentMon = Get-PresentMonPath
    }
    if (-not $presentMon) {
        return [pscustomobject]@{
            Available = $false
            Reason = "PresentMon not found. Install: winget install --id Intel.PresentMon.Console -e --accept-source-agreements --accept-package-agreements"
        }
    }

    if (-not (Test-Path -LiteralPath $TempRoot)) {
        New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    }
    $csv = Join-Path $TempRoot ("presentmon-{0}.csv" -f ([Guid]::NewGuid().ToString("N")))
    $sessionName = "StreamOpsHwmon-{0}" -f ([Guid]::NewGuid().ToString("N").Substring(0, 8))
    $options = Get-PresentMonSupportedOptions -Path $presentMon
    $args = @(
        "--session_name", $sessionName,
        "--process_id", [string]$Process.Id,
        "--timed", [string]$Seconds,
        "--output_file", $csv
    )
    if ($options.TerminateAfterTimed) { $args += "--terminate_after_timed" }
    if ($options.StopExistingSession) { $args += "--stop_existing_session" }
    if ($options.TrackGpuVideo) { $args += "--track_gpu_video" }
    if ($options.NoConsoleStats) { $args += "--no_console_stats" }

    try {
        $output = & $presentMon @args 2>&1
        if ($LASTEXITCODE -ne 0) {
            $tail = ($output | Select-Object -Last 4) -join " "
            return [pscustomobject]@{ Available = $false; Reason = "PresentMon failed: $tail" }
        }
        $stats = Read-PresentMonCsv -Path $csv -ProcessId $Process.Id
        if (-not $stats) {
            return [pscustomobject]@{ Available = $false; Reason = "PresentMon produced no frame rows for PID $($Process.Id)" }
        }
        $stats | Add-Member -NotePropertyName Available -NotePropertyValue $true
        $stats | Add-Member -NotePropertyName Tool -NotePropertyValue $presentMon
        return $stats
    } finally {
        if (Test-Path -LiteralPath $csv) {
            Remove-Item -LiteralPath $csv -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-ObsStats {
    param([string]$HostName, [int]$Port)

    $obsProcess = Get-Process -Name "obs64", "obs32", "obs" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $obsProcess) {
        return [pscustomobject]@{ Available = $false; Skipped = $true; Reason = "OBS is not running" }
    }

    $tcp = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
    if (-not $tcp.TcpTestSucceeded) {
        return [pscustomobject]@{ Available = $false; Skipped = $true; Reason = "OBS is running, but WebSocket is not reachable at ${HostName}:$Port" }
    }

    $code = @"
import json
import os
import sys
from streamops.obs_client import ObsClient

client = ObsClient(
    host=sys.argv[1],
    port=int(sys.argv[2]),
    password=os.environ.get("OBS_WEBSOCKET_PASSWORD") or None,
)
with client:
    print(json.dumps(client.request("GetStats")))
"@
    try {
        Push-Location $RepoRoot
        $json = python -c $code $HostName $Port 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $json) {
            return [pscustomobject]@{ Available = $false; Skipped = $true; Reason = "OBS stats query failed; check OBS_WEBSOCKET_PASSWORD" }
        }
        $stats = $json | ConvertFrom-Json
        $stats | Add-Member -NotePropertyName Available -NotePropertyValue $true
        return $stats
    } catch {
        return [pscustomobject]@{ Available = $false; Skipped = $true; Reason = $_.Exception.Message }
    } finally {
        Pop-Location -ErrorAction SilentlyContinue
    }
}

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host $Title
    Write-Host ("-" * $Title.Length)
}

function Write-Snapshot {
    $now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $system = Get-SystemStats
    $gpuEngines = Get-GpuEngineStats
    $nvidia = Get-NvidiaStats
    $game = Get-DiabloProcess -Name $GameProcessName
    $pm = Get-PresentMonStats -Process $game -Seconds $PresentMonSampleSeconds -InstallMissing:$InstallMissingDependencies
    if ($SkipObs) {
        $obs = [pscustomobject]@{ Available = $false; Skipped = $true; Reason = "skipped by -SkipObs" }
    } else {
        $obs = Get-ObsStats -HostName $ObsHost -Port $ObsPort
    }

    Write-Host ""
    Write-Host "StreamOps Hardware Monitor  $now"
    Write-Host ("Repo: {0}" -f $RepoRoot)

    Write-Section "System"
    Write-Host ("CPU: {0}%   RAM: {1}/{2} ({3}%)" -f (Format-Number $system.CpuPct 1), (Format-MiB $system.RamUsedMiB), (Format-MiB $system.RamTotalMiB), (Format-Number $system.RamPct 1))
    Write-Host ("Disk: read {0}, write {1}" -f (Format-BytesPerSecond $system.DiskRead), (Format-BytesPerSecond $system.DiskWrite))
    Write-Host ("Net:  down {0}, up {1}" -f (Format-BytesPerSecond $system.NetRx), (Format-BytesPerSecond $system.NetTx))

    Write-Section "GPU"
    if ($nvidia.Available) {
        Write-Host ("NVIDIA: {0} driver {1}" -f $nvidia.Name, $nvidia.Driver)
        Write-Host ("Util: GPU {0}%, memory {1}%   VRAM: {2}/{3}" -f (Format-Number $nvidia.GpuPct 1), (Format-Number $nvidia.MemUtilPct 1), (Format-MiB $nvidia.VramUsedMiB), (Format-MiB $nvidia.VramTotalMiB))
        Write-Host ("Thermal/Power: {0} C, {1} W   Clocks: graphics {2} MHz, memory {3} MHz" -f (Format-Number $nvidia.TempC 0), (Format-Number $nvidia.PowerW 1), (Format-Number $nvidia.GraphicsClockMHz 0), (Format-Number $nvidia.MemoryClockMHz 0))
        Write-Host ("NVENC: sessions {0}, avg fps {1}, latency {2} ms" -f $nvidia.EncoderSessions, (Format-Number $nvidia.EncoderFps 1), (Format-Number $nvidia.EncoderLatencyMs 1))
    } else {
        Write-Host ("NVIDIA: unavailable ({0})" -f $nvidia.Reason)
    }
    Write-Host ("GPU engines: encode {0}%, decode {1}%   Adapter memory: dedicated {2}, shared {3}" -f (Format-Number $gpuEngines.EncodePct 1), (Format-Number $gpuEngines.DecodePct 1), (Format-MiB $gpuEngines.DedicatedMiB), (Format-MiB $gpuEngines.SharedMiB))

    Write-Section "Diablo IV"
    if ($game) {
        Write-Host ("Process: {0} PID {1}" -f $game.ProcessName, $game.Id)
    } else {
        Write-Host "Process: not found"
    }
    if ($pm.Available) {
        Write-Host ("PresentMon: {0} FPS, avg frame {1} ms, min {2} ms, max {3} ms, frames {4}" -f (Format-Number $pm.Fps 1), (Format-Number $pm.AvgMs 2), (Format-Number $pm.MinMs 2), (Format-Number $pm.MaxMs 2), $pm.Frames)
    } else {
        Write-Host ("PresentMon: unavailable ({0})" -f $pm.Reason)
    }

    Write-Section "OBS"
    if ($obs.Available) {
        Write-Host ("FPS: {0}   Render skipped: {1}/{2}   Output skipped: {3}/{4}" -f (Format-Number ([double]$obs.activeFps) 1), $obs.renderSkippedFrames, $obs.renderTotalFrames, $obs.outputSkippedFrames, $obs.outputTotalFrames)
        Write-Host ("CPU: {0}%   Memory: {1} MiB   Disk available: {2} MiB" -f (Format-Number ([double]$obs.cpuUsage) 1), (Format-Number ([double]$obs.memoryUsage) 0), (Format-Number ([double]$obs.availableDiskSpace) 0))
    } else {
        Write-Host ("OBS: skipped ({0})" -f $obs.Reason)
    }
}

try {
    do {
        Write-Snapshot
        if ($Once) { break }
        Write-Host ""
        Write-Host ("Next refresh in {0}s. Press Ctrl-C to stop." -f $RefreshSeconds)
        Start-Sleep -Seconds $RefreshSeconds
    } while ($true)
} catch [System.Management.Automation.PipelineStoppedException] {
    throw
} catch {
    Write-Error $_
    exit 1
}
