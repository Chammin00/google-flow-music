#Requires -Version 5.1
<#
.SYNOPSIS
    Exports sample-accurate, equal-duration aligned Flow Music stems and adaptive_manifest.json for game engines.

.DESCRIPTION
    Measures unified integrated loudness from the master (or primary stem), aligns every stem
    to the exact same sample-accurate duration (preventing loop/layer drift), encodes engine-native
    formats for Godot 4 (OGG 48kHz), Unity 6 (WAV 44.1kHz), Unreal Engine 5 (WAV 48kHz), and Web
    (OGG + MP3 44.1kHz), and writes adaptive_manifest.json with adaptive state presets.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$TrackSlug = '',

    [Parameter(Mandatory = $false)]
    [string]$TrackDir = '',

    [Parameter(Mandatory = $false)]
    [string]$VaultRoot = '',

    [Parameter(Mandatory = $false)]
    [ValidateSet('All', 'Godot', 'Unity', 'Unreal', 'Web')]
    [string]$Engine = 'All',

    [Parameter(Mandatory = $false)]
    [string]$TargetDir = '',

    [Parameter(Mandatory = $false)]
    [double]$TargetLufs = -16.0,

    [Parameter(Mandatory = $false)]
    [switch]$OutputJson
)

$CallerDirectory = (Get-Location).Path
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

$HubRoot = Split-Path -Parent $ScriptDir
Import-Module -Name (Join-Path -Path $ScriptDir -ChildPath 'FlowMusicCommon.psm1') -Force

$resolvedVaultRoot = if ([string]::IsNullOrWhiteSpace($VaultRoot)) {
    Join-Path -Path $HubRoot -ChildPath 'vault'
} else {
    Resolve-CallerPath -Path $VaultRoot -BaseDirectory $CallerDirectory
}

$resolvedTrackDir = ''
if (-not [string]::IsNullOrWhiteSpace($TrackDir)) {
    $resolvedTrackDir = Resolve-CallerPath -Path $TrackDir -BaseDirectory $CallerDirectory
}
elseif (-not [string]::IsNullOrWhiteSpace($TrackSlug)) {
    $resolvedTrackDir = Join-Path -Path $resolvedVaultRoot -ChildPath $TrackSlug
}
else {
    throw "Specify either -TrackSlug or -TrackDir."
}

if (-not (Test-Path -LiteralPath $resolvedTrackDir)) {
    throw ("Track directory not found: {0}" -f $resolvedTrackDir)
}

$trackJsonPath = Join-Path -Path $resolvedTrackDir -ChildPath 'track.json'
$meta = if (Test-Path -LiteralPath $trackJsonPath) {
    Get-Content -LiteralPath $trackJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $null
}

$slug = if ($null -ne $meta -and -not [string]::IsNullOrWhiteSpace([string]$meta.slug)) {
    [string]$meta.slug
} else {
    Split-Path -Leaf $resolvedTrackDir
}

$title = if ($null -ne $meta -and -not [string]::IsNullOrWhiteSpace([string]$meta.title)) {
    [string]$meta.title
} else {
    $slug
}

$bpm = if ($null -ne $meta -and $null -ne $meta.bpm) { [int]$meta.bpm } else { 120 }
$key = if ($null -ne $meta -and -not [string]::IsNullOrWhiteSpace([string]$meta.key)) { [string]$meta.key } else { 'C minor' }
$timeSig = if ($null -ne $meta -and -not [string]::IsNullOrWhiteSpace([string]$meta.timeSignature)) { [string]$meta.timeSignature } else { '4/4' }
$loopable = if ($null -ne $meta -and $null -ne $meta.loopable) { [bool]$meta.loopable } else { $true }

$assets = Find-TrackAudioAssets -TrackDir $resolvedTrackDir -TrackMeta $meta
if ($assets.Stems.Count -eq 0 -and $null -eq $assets.MasterPath) {
    throw ("No stems or master audio found in track directory: {0}" -f $resolvedTrackDir)
}

$targetDurationSec = 0.0
if ($null -ne $assets.MasterPath) {
    $mInfo = Get-AudioMediaInfo -Path $assets.MasterPath
    if ([double]$mInfo.DurationSec -gt $targetDurationSec) {
        $targetDurationSec = [double]$mInfo.DurationSec
    }
}
foreach ($stemKey in $assets.Stems.Keys) {
    $sInfo = Get-AudioMediaInfo -Path $assets.Stems[$stemKey]
    if ([double]$sInfo.DurationSec -gt $targetDurationSec) {
        $targetDurationSec = [double]$sInfo.DurationSec
    }
}
if ($targetDurationSec -le 0.0) {
    throw "Could not determine audio duration for stem alignment."
}

$loudnessRef = if ($null -ne $assets.MasterPath) {
    $assets.MasterPath
} else {
    $firstStem = @($assets.Stems.Keys)[0]
    $assets.Stems[$firstStem]
}
$loudness = Measure-AudioIntegratedLoudness -Path $loudnessRef -TargetLufs $TargetLufs
$gainDb = [double]$loudness.GainDb

$enginesToExport = if ($Engine -eq 'All') {
    @('Godot', 'Unity', 'Unreal', 'Web')
} else {
    @($Engine)
}

$engineConfigs = @{
    'Godot'  = @{ Formats = @(@{ Ext = 'ogg'; Bitrate = '256k' }); SampleRate = 48000 }
    'Unity'  = @{ Formats = @(@{ Ext = 'wav'; Bitrate = '' });     SampleRate = 44100 }
    'Unreal' = @{ Formats = @(@{ Ext = 'wav'; Bitrate = '' });     SampleRate = 48000 }
    'Web'    = @{ Formats = @(@{ Ext = 'ogg'; Bitrate = '192k' }, @{ Ext = 'mp3'; Bitrate = '192k' }); SampleRate = 44100 }
}

$statePresets = [ordered]@{
    exploration = [ordered]@{
        instruments = [ordered]@{ linear = 1.0; db = 0.0 }
        bass        = [ordered]@{ linear = 0.45; db = -6.9 }
        drums       = [ordered]@{ linear = 0.0; db = -80.0 }
        vocals      = [ordered]@{ linear = 0.0; db = -80.0 }
    }
    tension = [ordered]@{
        instruments = [ordered]@{ linear = 1.0; db = 0.0 }
        bass        = [ordered]@{ linear = 0.85; db = -1.4 }
        drums       = [ordered]@{ linear = 0.45; db = -6.9 }
        vocals      = [ordered]@{ linear = 0.0; db = -80.0 }
    }
    combat = [ordered]@{
        instruments = [ordered]@{ linear = 1.0; db = 0.0 }
        bass        = [ordered]@{ linear = 1.0; db = 0.0 }
        drums       = [ordered]@{ linear = 1.0; db = 0.0 }
        vocals      = [ordered]@{ linear = 0.0; db = -80.0 }
    }
    climax = [ordered]@{
        instruments = [ordered]@{ linear = 1.0; db = 0.0 }
        bass        = [ordered]@{ linear = 1.0; db = 0.0 }
        drums       = [ordered]@{ linear = 1.0; db = 0.0 }
        vocals      = [ordered]@{ linear = 1.0; db = 0.0 }
    }
}

$resolvedBaseTarget = if ([string]::IsNullOrWhiteSpace($TargetDir)) {
    Join-MultiPath -Parts @($HubRoot, 'exports', 'game-audio')
} else {
    Resolve-CallerPath -Path $TargetDir -BaseDirectory $CallerDirectory
}

$engineExports = New-Object System.Collections.Generic.List[object]

foreach ($eng in $enginesToExport) {
    $cfg = $engineConfigs[$eng]
    $engLower = $eng.ToLowerInvariant()

    $outTrackDir = if (-not [string]::IsNullOrWhiteSpace($TargetDir) -and ($Engine -ne 'All')) {
        Join-Path -Path $resolvedBaseTarget -ChildPath $slug
    } else {
        Join-MultiPath -Parts @($resolvedBaseTarget, $engLower, $slug)
    }
    $stemsOutDir = Join-Path -Path $outTrackDir -ChildPath 'stems'

    if ($PSCmdlet.ShouldProcess($outTrackDir, ("Export aligned {0} stems for '{1}'" -f $eng, $slug))) {
        if (-not (Test-Path -LiteralPath $stemsOutDir)) {
            $null = New-Item -ItemType Directory -Path $stemsOutDir -Force
        }

        $exportedStemMap = [ordered]@{}
        $exportedStemFormats = [ordered]@{}
        $exportedFiles = New-Object System.Collections.Generic.List[string]

        if ($null -ne $assets.MasterPath) {
            $primaryFmt = $cfg.Formats[0]
            $masterDest = Join-Path -Path $outTrackDir -ChildPath ("master.{0}" -f $primaryFmt.Ext)
            $null = Convert-FlowAudioFile `
                -InputPath $assets.MasterPath `
                -OutputPath $masterDest `
                -Format $primaryFmt.Ext `
                -SampleRate $cfg.SampleRate `
                -GainDb $gainDb `
                -Bitrate $primaryFmt.Bitrate `
                -AlignDurationSec $targetDurationSec
            $exportedFiles.Add($masterDest)
        }

        foreach ($stemKey in $assets.Stems.Keys) {
            $srcStem = $assets.Stems[$stemKey]
            $fmtPaths = New-Object System.Collections.Generic.List[string]
            foreach ($fmtSpec in $cfg.Formats) {
                $destPath = Join-Path -Path $stemsOutDir -ChildPath ("{0}.{1}" -f $stemKey, $fmtSpec.Ext)
                $null = Convert-FlowAudioFile `
                    -InputPath $srcStem `
                    -OutputPath $destPath `
                    -Format $fmtSpec.Ext `
                    -SampleRate $cfg.SampleRate `
                    -GainDb $gainDb `
                    -Bitrate $fmtSpec.Bitrate `
                    -AlignDurationSec $targetDurationSec
                $exportedFiles.Add($destPath)
                $fmtPaths.Add(("stems/{0}.{1}" -f $stemKey, $fmtSpec.Ext))
            }
            $exportedStemMap[$stemKey] = $fmtPaths[0]
            $exportedStemFormats[$stemKey] = $fmtPaths.ToArray()
        }

        $manifestObj = [ordered]@{
            slug          = $slug
            title         = $title
            bpm           = $bpm
            key           = $key
            timeSignature = $timeSig
            durationSec   = [math]::Round($targetDurationSec, 4)
            sampleRate    = $cfg.SampleRate
            loopable      = $loopable
            engine        = $eng
            targetLufs    = $TargetLufs
            appliedGainDb = $gainDb
            stems         = $exportedStemMap
            stemFormats   = $exportedStemFormats
            states        = $statePresets
            exportedAt    = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        }

        $manifestPath = Join-Path -Path $outTrackDir -ChildPath 'adaptive_manifest.json'
        Write-Utf8NoBomFile -Path $manifestPath -Content ($manifestObj | ConvertTo-Json -Depth 8)

        $engineExports.Add([PSCustomObject]@{
            Engine       = $eng
            OutputDir    = $outTrackDir
            ManifestPath = $manifestPath
            SampleRate   = $cfg.SampleRate
            DurationSec  = [math]::Round($targetDurationSec, 4)
            GainDb       = $gainDb
            StemCount    = $assets.Stems.Count
            Files        = $exportedFiles.ToArray()
        })
    }
}

$summary = [PSCustomObject]@{
    Status      = 'Success'
    Slug        = $slug
    Title       = $title
    Bpm         = $bpm
    DurationSec = [math]::Round($targetDurationSec, 4)
    TargetLufs  = $TargetLufs
    GainDb      = $gainDb
    Exports     = $engineExports.ToArray()
}

if ($OutputJson) {
    Write-Output ($summary | ConvertTo-Json -Depth 8)
} else {
    $summary
}
