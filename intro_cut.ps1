#requires -Version 5.1
# Intro/Outro schneiden: FFmpeg (Codec + Bitrate) oder DaVinci Resolve (Render-Preset).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string] $InputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$DefaultsPath = Join-Path $ScriptRoot 'intro_cut_defaults.json'
$ResolveScript = Join-Path $ScriptRoot 'intro_cut_resolve.py'

function Read-Defaults {
    if (-not (Test-Path -LiteralPath $DefaultsPath)) {
        return $null
    }
    try {
        $raw = Get-Content -LiteralPath $DefaultsPath -Raw -Encoding UTF8
        return $raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Write-Defaults($obj) {
    try {
        $obj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $DefaultsPath -Encoding UTF8
    } catch {
        Write-Warning "Konnte Voreinstellungen nicht speichern: $_"
    }
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-HasAudioStream([string] $filePath) {
    if (-not (Test-Command 'ffprobe')) { return $false }
    $arg = @('-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=index', '-of', 'csv=p=0', $filePath)
    $out = & ffprobe @arg 2>&1
    return ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($out | Out-String).Trim()))
}

function Get-MediaDurationSec([string] $filePath) {
    if (-not (Test-Command 'ffprobe')) {
        throw "ffprobe wurde nicht gefunden. Bitte FFmpeg installieren und im PATH eintragen."
    }
    $arg = @(
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        $filePath
    )
    $out = & ffprobe @arg 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "ffprobe Fehler: $out"
    }
    $line = ($out | Out-String).Trim()
    $d = 0.0
    if (-not [double]::TryParse($line.Replace(',', '.'), [ref]$d)) {
        throw "Ungueltige Dauer von ffprobe: $line"
    }
    return $d
}

function Pick-InputFile {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = 'Videodatei auswaehlen'
    $dlg.Filter = 'Video|*.mp4;*.mkv;*.mov;*.m4v;*.avi;*.webm;*.mts;*.m2ts|Alle Dateien|*.*'
    if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }
    return $dlg.FileName
}

function Read-DoublePrompt([string] $label, [double] $defaultVal) {
    while ($true) {
        $hint = "Standard: $defaultVal"
        $in = Read-Host "$label ($hint)"
        if ([string]::IsNullOrWhiteSpace($in)) { return $defaultVal }
        $v = 0.0
        if ([double]::TryParse($in.Replace(',', '.'), [ref]$v) -and $v -ge 0) { return $v }
        Write-Host "Bitte eine Zahl groesser oder gleich 0 eingeben." -ForegroundColor Yellow
    }
}

function Read-ModePrompt([string] $defaultMode) {
    Write-Host ""
    Write-Host "Modus: 1 = FFmpeg (Codec und Bitrate waehlbar)  |  2 = DaVinci Resolve (Deliver-Preset)"
    $in = Read-Host "Modus (Standard: $defaultMode)"
    if ([string]::IsNullOrWhiteSpace($in)) { return $defaultMode }
    if ($in -eq '1') { return 'ffmpeg' }
    if ($in -eq '2') { return 'resolve' }
    $m = $in.Trim().ToLowerInvariant()
    if ($m -eq 'ffmpeg' -or $m -eq 'resolve') { return $m }
    Write-Host "Ungueltige Eingabe - Standard wird verwendet." -ForegroundColor Yellow
    return $defaultMode
}

function Get-OutputExtension([string] $videoCodec, [string] $srcPath) {
    if ($videoCodec -eq 'copy') {
        return [System.IO.Path]::GetExtension($srcPath)
    }
    $c = $videoCodec.ToLowerInvariant()
    if ($c -match 'vp9|vpx') { return '.webm' }
    if ($c -match 'av1|svtav1|aom') { return '.mkv' }
    return '.mp4'
}

function Invoke-FfmpegCut {
    param(
        [string] $FilePath,
        [double] $IntroSec,
        [double] $OutroSec,
        [string] $VideoCodec,
        [string] $VideoBitrate,
        [string] $AudioCodec,
        [string] $AudioBitrate
    )

    if (-not (Test-Command 'ffmpeg')) {
        throw "ffmpeg wurde nicht gefunden. Bitte installieren und im PATH eintragen."
    }

    $dur = Get-MediaDurationSec $FilePath
    $newDur = $dur - $IntroSec - $OutroSec
    if ($newDur -le 0) {
        throw "Ergebnis zu kurz: Gesamtdauer ${dur}s, Intro ${IntroSec}s, Outro ${OutroSec}s."
    }

    $dir = [System.IO.Path]::GetDirectoryName($FilePath)
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($FilePath)
    $ext = Get-OutputExtension $VideoCodec $FilePath
    $outPath = Join-Path $dir ($stem + '_introcut' + $ext)

    $vPart = @()
    if ($VideoCodec -eq 'copy') {
        $vPart = @('-c:v', 'copy')
    } else {
        if ([string]::IsNullOrWhiteSpace($VideoBitrate)) {
            throw "Video-Bitrate fehlt (oder 'copy' fuer Stream-Kopie waehlen)."
        }
        $vPart = @('-c:v', $VideoCodec, '-b:v', $VideoBitrate)
    }

    $aPart = @()
    if ($AudioCodec -eq 'copy') {
        $aPart = @('-c:a', 'copy')
    } else {
        $aPart = @('-c:a', $AudioCodec, '-b:a', $AudioBitrate)
    }

    $mov = @()
    if ($ext -match '\.(mp4|m4v|mov)$') {
        $mov = @('-movflags', '+faststart')
    }

    $hasAudio = Test-HasAudioStream $FilePath
    $mapPart = @('-map', '0:v:0')
    $audioPart = @()
    if ($hasAudio) {
        $mapPart += @('-map', '0:a:0')
        $audioPart = $aPart
    } else {
        $audioPart = @('-an')
    }

    $videoBr = if ($VideoCodec -ne 'copy') { $VideoBitrate } else { '(copy)' }
    $audioBr = if ($AudioCodec -ne 'copy') { $AudioBitrate } else { '(copy)' }

    Write-Host ""
    Write-Host "Quelle:     $FilePath"
    Write-Host "Dauer:      $([math]::Round($dur, 3)) s"
    Write-Host "Schneiden:  +${IntroSec}s / -${OutroSec}s -> neu $([math]::Round($newDur, 3)) s"
    Write-Host "Video:      $VideoCodec $videoBr"
    if ($hasAudio) {
        Write-Host "Audio:      $AudioCodec $audioBr"
    } else {
        Write-Host "Audio:      (kein Ton in der Quelle - Ausgabe ohne Audio)"
    }
    Write-Host "Ziel:       $outPath"
    Write-Host ""

    $ffArgs = @(
        '-hide_banner',
        '-y',
        '-i', $FilePath,
        '-ss', ([string]$IntroSec).Replace(',', '.'),
        '-t', ([string]$newDur).Replace(',', '.')
    ) + $mapPart + $vPart + $audioPart + $mov + $outPath

    $p = Start-Process -FilePath 'ffmpeg' -ArgumentList $ffArgs -NoNewWindow -PassThru -Wait
    if ($p.ExitCode -ne 0) {
        throw "ffmpeg beendete mit Code $($p.ExitCode)."
    }
    Write-Host "Fertig." -ForegroundColor Green
}

function Invoke-ResolveCut {
    param(
        [string] $FilePath,
        [double] $IntroSec,
        [double] $OutroSec,
        [string] $Preset
    )

    $py = $null
    foreach ($c in @('py', 'python')) {
        if (Test-Command $c) { $py = $c; break }
    }
    if (-not $py) {
        throw "Python nicht gefunden (py/python). Fuer Resolve bitte Python installieren."
    }
    if (-not (Test-Path -LiteralPath $ResolveScript)) {
        throw "Fehlt: $ResolveScript"
    }

    $presetArg = @()
    if (-not [string]::IsNullOrWhiteSpace($Preset)) {
        $presetArg = @('--preset', $Preset.Trim())
    }

    $args = @(
        $ResolveScript,
        '--input', $FilePath,
        '--intro', ([string]$IntroSec).Replace(',', '.'),
        '--outro', ([string]$OutroSec).Replace(',', '.')
    ) + $presetArg

    Write-Host "Starte DaVinci-Pipeline (Resolve muss Studio + External Scripting = Local sein)..."
    & $py @args
    if ($LASTEXITCODE -ne 0) {
        throw "intro_cut_resolve.py beendete mit Code $LASTEXITCODE."
    }
}

# --- main ---
$d = Read-Defaults
if (-not $d) {
    $d = [pscustomobject]@{
        IntroSec       = 3.0
        OutroSec       = 2.0
        Mode           = 'ffmpeg'
        VideoCodec     = 'libx264'
        VideoBitrate   = '8M'
        AudioCodec     = 'aac'
        AudioBitrate   = '192k'
        RenderPreset   = 'YouTube - 1080p'
    }
}

$path = $InputPath.Trim()
if ([string]::IsNullOrWhiteSpace($path)) {
    $path = Pick-InputFile
    if ([string]::IsNullOrWhiteSpace($path)) {
        Write-Host "Abbruch - keine Datei gewaehlt."
        exit 1
    }
}

if (-not (Test-Path -LiteralPath $path)) {
    Write-Host "Datei nicht gefunden: $path" -ForegroundColor Red
    exit 1
}
$path = (Resolve-Path -LiteralPath $path).Path

Write-Host "=== Intro Cutter ===" -ForegroundColor Cyan
Write-Host "Datei: $path"

$intro = Read-DoublePrompt "Intro am Anfang entfernen (Sekunden)" ([double]$d.IntroSec)
$outro = Read-DoublePrompt "Outro am Ende entfernen (Sekunden)" ([double]$d.OutroSec)
$mode = Read-ModePrompt ([string]$d.Mode)

$save = [pscustomobject]@{
    IntroSec     = $intro
    OutroSec     = $outro
    Mode         = $mode
    VideoCodec   = $d.VideoCodec
    VideoBitrate = $d.VideoBitrate
    AudioCodec   = $d.AudioCodec
    AudioBitrate = $d.AudioBitrate
    RenderPreset = $d.RenderPreset
}

if ($mode -eq 'ffmpeg') {
    Write-Host ""
    Write-Host "Video-Codec (Beispiele: libx264, libx265, libvpx-vp9, libsvtav1, h264_nvenc, hevc_nvenc, copy)"
    $vcIn = Read-Host "Codec (Standard: $($d.VideoCodec))"
    if (-not [string]::IsNullOrWhiteSpace($vcIn)) { $save.VideoCodec = $vcIn.Trim() }

    if ($save.VideoCodec -ne 'copy') {
        $vbIn = Read-Host "Video-Bitrate, z. B. 8M oder 5000k (Standard: $($d.VideoBitrate))"
        if (-not [string]::IsNullOrWhiteSpace($vbIn)) { $save.VideoBitrate = $vbIn.Trim() }
    }

    Write-Host "Audio: aac (empfohlen) oder copy"
    $acIn = Read-Host "Audio-Codec (Standard: $($d.AudioCodec))"
    if (-not [string]::IsNullOrWhiteSpace($acIn)) { $save.AudioCodec = $acIn.Trim() }

    if ($save.AudioCodec -ne 'copy') {
        $abIn = Read-Host "Audio-Bitrate (Standard: $($d.AudioBitrate))"
        if (-not [string]::IsNullOrWhiteSpace($abIn)) { $save.AudioBitrate = $abIn.Trim() }
    }

    Invoke-FfmpegCut -FilePath $path -IntroSec $intro -OutroSec $outro `
        -VideoCodec $save.VideoCodec -VideoBitrate $save.VideoBitrate `
        -AudioCodec $save.AudioCodec -AudioBitrate $save.AudioBitrate
} else {
    Write-Host ""
    Write-Host "Render-Preset exakt wie in Resolve Deliver (leer = Standard aus intro_cut_defaults.json / Fallback-Kette)."
    $rp = Read-Host "Preset (Standard: $($d.RenderPreset))"
    if (-not [string]::IsNullOrWhiteSpace($rp)) { $save.RenderPreset = $rp.Trim() }

    Invoke-ResolveCut -FilePath $path -IntroSec $intro -OutroSec $outro -Preset $save.RenderPreset
}

Write-Defaults $save
Write-Host ""
Write-Host "Einstellungen gespeichert: $DefaultsPath"
