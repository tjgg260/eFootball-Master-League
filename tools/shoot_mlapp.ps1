# Launch ML.App on a given screen, screenshot it, and report anything it logged.
#
# The app finds its career by walking up for build/master.db, so a copy at the worktree root
# is picked up before the real save — keep one there when shooting.
#
#   powershell -File tools/shoot_mlapp.ps1 -Page Squad -Out build/shots/squad.png
param(
    [string]$Page = "Office",
    [string]$Out = "build/shots/shot.png",
    [int]$WaitSeconds = 20,
    [switch]$Continue,                       # click past the career picker first
    [double]$ContinueX = 0.578,              # CONTINUE button, as a fraction of the window
    [double]$ContinueY = 0.516,
    [int]$AfterContinueSeconds = 14,
    [double]$RightClickX = 0,                # window-relative point to right-click before shooting
    [double]$RightClickY = 0,
    [double]$LeftClickX = 0,                 # window-relative point to left-click first (tabs etc.)
    [double]$LeftClickY = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root "src\ML.App\bin\Debug\net8.0\ML.App.exe"
if (-not (Test-Path $exe)) { Write-Error "build ML.App first: $exe"; exit 2 }

$log = Join-Path (Split-Path -Parent $exe) "ml-crash.log"
if (Test-Path $log) { Remove-Item $log -Force }

$outPath = Join-Path $root $Out
$outDir = Split-Path -Parent $outPath
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

# Any ML.App left over from an earlier run holds ML.Core.dll/ML.Data.dll open and the next
# `dotnet build` fails with MSB3027 file locks that look nothing like the real cause.
Get-Process ML.App -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$env:ML_PAGE = $Page
$env:ML_RESUME = "1"        # skip the career picker and open the saved career straight away
$proc = Start-Process -FilePath $exe -PassThru
Write-Host "launched $Page (pid $($proc.Id)) - settling..."

# Kill the app however this script ends - an early `exit` would otherwise leak it.
trap { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; break }

# Give Avalonia time to build the page; a startup crash shows up as an early exit.
for ($i = 0; $i -lt $WaitSeconds; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) {
        Write-Host "PROCESS DIED after $i s (exit $($proc.ExitCode))"
        if (Test-Path $log) { Get-Content $log }
        exit 1
    }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Path (Join-Path $PSScriptRoot "WinShot.cs") -ReferencedAssemblies System.Drawing
[void][WinShot]::MakeDpiAware()

$proc.Refresh()
$h = $proc.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { Write-Host "no main window handle - is a modal open?" }
$r = [WinShot]::Raise($h)

# Fallback only: with ML_RESUME the picker is skipped, so this is for a career-less run.
if ($Continue) {
    $cx = $r.Left + [int](($r.Right - $r.Left) * $ContinueX)
    $cy = $r.Top + [int](($r.Bottom - $r.Top) * $ContinueY)
    Write-Host "clicking CONTINUE at $cx,$cy"
    [WinShot]::Click($cx, $cy)
    Start-Sleep -Seconds $AfterContinueSeconds
    if ($proc.HasExited) {
        Write-Host "PROCESS DIED after CONTINUE (exit $($proc.ExitCode))"
        if (Test-Path $log) { Get-Content $log }
        exit 1
    }
    $proc.Refresh()
    $h2 = $proc.MainWindowHandle
    if ($h2 -ne [IntPtr]::Zero) { $h = $h2 }
    $r = [WinShot]::Raise($h)
}

# CopyFromScreen against the real window rect: PrintWindow crops at high DPI.
$w = $r.Right - $r.Left
$ht = $r.Bottom - $r.Top
if ($w -le 0 -or $ht -le 0) {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $r.Left = $b.X; $r.Top = $b.Y; $w = $b.Width; $ht = $b.Height
    Write-Host "no window rect - falling back to full screen"
}

if ($LeftClickX -gt 0) {
    # Drive the UI a step first — switching a tab, opening a panel — then shoot what it shows.
    [WinShot]::ForceTop($h)
    $r = [WinShot]::Raise($h)
    $lx = $r.Left + [int](($r.Right - $r.Left) * $LeftClickX)
    $ly = $r.Top + [int](($r.Bottom - $r.Top) * $LeftClickY)
    Write-Host "left-click at $lx,$ly"
    [WinShot]::Click($lx, $ly)
    Start-Sleep -Milliseconds 1500
}

if ($RightClickX -gt 0) {
    # A context menu is its own popup window, so PrintWindow on the shell would miss it:
    # pin the app topmost, right-click for real, then grab the screen where it sits.
    [WinShot]::ForceTop($h)
    $r = [WinShot]::Raise($h)
    $cx = $r.Left + [int](($r.Right - $r.Left) * $RightClickX)
    $cy = $r.Top + [int](($r.Bottom - $r.Top) * $RightClickY)
    Write-Host "right-click at $cx,$cy"
    [WinShot]::RightClick($cx, $cy)
    Start-Sleep -Milliseconds 1500

    $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
    $g.Dispose()
}
else {
    # PrintWindow, not CopyFromScreen: Windows refuses to raise a background app's window, so a
    # screen grab of its rect returns whatever is actually on top.
    $bmp = [WinShot]::Capture($h)
}
$bmp.Save($outPath, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host "saved $outPath ($($bmp.Width) x $($bmp.Height))"
$bmp.Dispose()

$crashed = $false
if (Test-Path $log) {
    Write-Host "--- the app logged errors ---"
    Get-Content $log
    $crashed = $true
}

Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
if ($crashed) { exit 3 }
