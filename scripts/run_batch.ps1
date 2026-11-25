# Illustrator batch runner - one application instance, many JSX scripts in sequence.
# Encodes the stability lessons from large batch jobs (24+ books, multi-language):
#   - wait 2s after each JSX (closing a doc needs time; 0.2s caused RPC_E_SERVERFAULT)
#   - one session for the whole list (do NOT restart every N books)
#   - never hard-kill mid-run (breaks COM -> 0x800706BA); Quit() gracefully
#   - trust the JSX log's success marker, not the COM return value (often undefined)
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_batch.ps1 `
#       -List books.txt [-MaxRetry 2] [-WaitMs 2000] [-DoneMarker "DONE total_ms"]
#   books.txt = one .jsx path per line (relative to this script's directory).
# JSX contract: write <jsx>.log next to itself containing DoneMarker on success,
# and "ERROR: ..." on failure. See references/batch-pipeline.md section 6.
param(
    [Parameter(Mandatory = $true)][string]$List,
    [int]$MaxRetry = 2,
    [int]$WaitMs = 2000,
    [string]$DoneMarker = "DONE total_ms"
)
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
# the caller may pass an absolute list path (rebuild.py / export_geometry.py do);
# Join-Path would mangle it into "<scriptdir>\D:\..." and every job would be MISSING
if ([System.IO.Path]::IsPathRooted($List)) { $listPath = $List } else { $listPath = Join-Path $root $List }
# -Encoding UTF8 is REQUIRED: the list is written by python as UTF-8, and PS 5.1
# defaults to the ANSI codepage. With a non-ASCII project path (e.g. 技能验证) every
# entry decodes to mojibake and every job reports MISSING.
$jsxs = @(Get-Content -LiteralPath $listPath -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })

function Say($m) { Write-Host ("[" + (Get-Date -Format "HH:mm:ss") + "] " + $m) }

# ---- 0. Close PDF readers: a locked PDF makes Illustrator save fail silently ----
foreach ($n in @('Acrobat', 'AcroRd32', 'AcrobatDC')) {
    $p = Get-Process $n -ErrorAction SilentlyContinue
    if ($p) { Say ("closing PDF reader: " + $n); $p | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
}

# ---- 1. Clean start: kill stray Illustrator, wait until truly gone ----
$old = Get-Process Illustrator -ErrorAction SilentlyContinue
if ($old) {
    Say "stray Illustrator found, cleaning"
    $old | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (Get-Process Illustrator -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
}

Say "starting Illustrator (once for the whole list)"
$ai = $null
for ($k = 1; $k -le 3; $k++) {
    try {
        $ai = New-Object -ComObject Illustrator.Application
        $v = $ai.Version
        Say ("ready version=" + $v)
        break
    } catch {
        Say ("start failed try=" + $k + " :: " + $_.Exception.Message)
        $ai = $null
        Get-Process Illustrator -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    }
}
if ($ai -eq $null) { Say "FATAL: Illustrator cannot start"; exit 1 }

# ---- 2. Sequential execution ----
$results = @()
foreach ($jsx in $jsxs) {
    if ([System.IO.Path]::IsPathRooted($jsx)) { $full = $jsx } else { $full = Join-Path $root $jsx }
    $log  = [System.IO.Path]::ChangeExtension($full, ".log")
    if (-not (Test-Path $full)) { Say ("MISSING " + $jsx); $results += "$jsx MISSING"; continue }

    $ok = $false
    for ($k = 1; $k -le $MaxRetry -and -not $ok; $k++) {
        if (Test-Path $log) { Remove-Item $log -Force -ErrorAction SilentlyContinue }
        $t = Get-Date
        Say ("START " + $jsx + "  (try " + $k + ")")
        try {
            $ai.DoJavaScriptFile($full) | Out-Null
        } catch {
            Say ("  COM exception: " + $_.Exception.Message)
        }
        # Recovery window after the JSX closes its document. Do NOT shrink this.
        Start-Sleep -Milliseconds $WaitMs
        $txt = ""
        if (Test-Path $log) { $txt = Get-Content $log -Raw -ErrorAction SilentlyContinue }
        $dur = [int]((Get-Date) - $t).TotalSeconds
        if ($txt -match [regex]::Escape($DoneMarker)) {
            $ok = $true
            Say ("  OK  " + $jsx + "  " + $dur + "s")
        } elseif ($txt -match "ERROR:") {
            $first = (($txt.Trim() -split "`r?`n") | Where-Object { $_ -match "ERROR:" } | Select-Object -First 1)
            Say ("  JSERR " + $jsx + " :: " + $first)
        } else {
            Say ("  no log output (possibly blocked by a dialog)")
        }
    }
    if ($ok) { $results += "$jsx OK" } else { $results += "$jsx FAIL" }
}

# ---- 3. Graceful exit, no hard kill ----
Say "all done, closing Illustrator"
try {
    $ai.Quit()
} catch {
    Say ("Quit exception: " + $_.Exception.Message)
}
$exited = $false
for ($i = 0; $i -lt 180; $i++) {
    if (-not (Get-Process Illustrator -ErrorAction SilentlyContinue)) { $exited = $true; break }
    Start-Sleep -Milliseconds 500
}
if ($exited) {
    Say "Illustrator exited cleanly"
} else {
    Say "WARN: Illustrator did not exit in 90s, forcing"
    Get-Process Illustrator -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

Say "===== summary ====="
$results | ForEach-Object { Say $_ }
Write-Host "BATCH DONE"
