#Requires -Version 5.1
<#
.SYNOPSIS
    Scans the Google Flow Music vault, updates catalog.json, masters audio, and syncs to target projects.

.DESCRIPTION
    1. Scans vault/<slug>/ (skipping _template), probes present master and stem files via ffprobe,
       and writes vault/catalog.json (UTF-8 without BOM).
    2. For each track with audio files and configured targets in config/project-targets.json:
       - Measures integrated loudness of the master track once per target LUFS.
       - Applies the exact same gain offset and limiter to master and all stems (preserving mix balance).
       - Encodes master to <targetPath>\<slug>.<ext> and, if includeStems is true, duration-aligned stems
         to <targetPath>\<slug>\stems\<stem>.<ext> alongside a track.json sidecar.
    3. Runs postSyncScript (e.g. Build-AudioManifest.ps1) when files were updated on a target that defines one.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$VaultRoot = '',

    [Parameter(Mandatory = $false)]
    [string]$ConfigPath = '',

    [Parameter(Mandatory = $false)]
    [string[]]$Target = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$TrackSlug = @(),

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [switch]$SkipLoudnorm,

    [Parameter(Mandatory = $false)]
    [switch]$SkipManifestRebuild,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun,

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

$resolvedConfigPath = if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    Join-MultiPath -Parts @($HubRoot, 'config', 'project-targets.json')
} else {
    Resolve-CallerPath -Path $ConfigPath -BaseDirectory $CallerDirectory
}

if (-not (Test-Path -LiteralPath $resolvedVaultRoot)) {
    throw ("Vault directory not found: {0}" -f $resolvedVaultRoot)
}
if (-not (Test-Path -LiteralPath $resolvedConfigPath)) {
    throw ("Project targets config not found: {0}" -f $resolvedConfigPath)
}

$configRaw = Get-Content -LiteralPath $resolvedConfigPath -Raw -Encoding UTF8
$configObj = $configRaw | ConvertFrom-Json
$targetConfigs = $configObj.targets

$targetFilter = @($Target | ForEach-Object { $_ -split ',' } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToLowerInvariant() })
$slugFilter = @($TrackSlug | ForEach-Object { $_ -split ',' } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_.Trim().ToLowerInvariant() })

$trackDirs = @(Get-ChildItem -LiteralPath $resolvedVaultRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne '_template' -and (-not $_.Name.StartsWith('.')) } |
    Sort-Object Name)

$catalogTracks = New-Object System.Collections.Generic.List[object]
$syncEvents = New-Object System.Collections.Generic.List[object]
$targetsUpdated = New-Object System.Collections.Generic.HashSet[string]
$postSyncRuns = New-Object System.Collections.Generic.List[object]

$encodedFilesCount = 0
$skippedFilesCount = 0
$tracksWithAudioCount = 0

foreach ($dirItem in $trackDirs) {
    $trackJsonFile = Join-Path -Path $dirItem.FullName -ChildPath 'track.json'
    if (-not (Test-Path -LiteralPath $trackJsonFile)) {
        continue
    }

    $meta = Get-Content -LiteralPath $trackJsonFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $slug = if (-not [string]::IsNullOrWhiteSpace([string]$meta.slug)) { [string]$meta.slug } else { $dirItem.Name }
    $assets = Find-TrackAudioAssets -TrackDir $dirItem.FullName -TrackMeta $meta

    $masterInfo = $null
    if ($null -ne $assets.MasterPath) {
        $masterInfo = Get-AudioMediaInfo -Path $assets.MasterPath
    }

    $stemDetails = [ordered]@{}
    $maxDurSec = if ($null -ne $masterInfo) { [double]$masterInfo.DurationSec } else { 0.0 }
    foreach ($stemKey in $assets.Stems.Keys) {
        $sInfo = Get-AudioMediaInfo -Path $assets.Stems[$stemKey]
        $stemDetails[$stemKey] = [ordered]@{
            path        = $sInfo.Path
            durationSec = $sInfo.DurationSec
            sampleRate  = $sInfo.SampleRate
            channels    = $sInfo.Channels
            bytes       = $sInfo.Bytes
        }
        if ([double]$sInfo.DurationSec -gt $maxDurSec) {
            $maxDurSec = [double]$sInfo.DurationSec
        }
    }

    $hasAnyAudio = ($null -ne $assets.MasterPath) -or ($assets.Stems.Count -gt 0)
    if ($hasAnyAudio) {
        $tracksWithAudioCount++
    }

    $catalogTracks.Add([ordered]@{
        slug            = $slug
        title           = [string]$meta.title
        artist          = [string]$meta.artist
        bpm             = $meta.bpm
        key             = [string]$meta.key
        timeSignature   = [string]$meta.timeSignature
        moods           = @($meta.moods)
        genre           = [string]$meta.genre
        instrumental    = [bool]$meta.instrumental
        loopable        = [bool]$meta.loopable
        licenseTier     = [string]$meta.licenseTier
        synthIdVerified = [bool]$meta.synthIdVerified
        targets         = @($meta.targets)
        hasMaster       = ($null -ne $assets.MasterPath)
        masterPath      = $assets.MasterPath
        durationSec     = [math]::Round($maxDurSec, 4)
        sampleRate      = if ($null -ne $masterInfo) { $masterInfo.SampleRate } else { $null }
        availableStems  = @($assets.Stems.Keys)
        stems           = $stemDetails
        trackDir        = $dirItem.FullName
    })

    if (@($slugFilter).Count -gt 0 -and ($slugFilter -notcontains $slug.ToLowerInvariant())) {
        continue
    }

    if (-not $hasAnyAudio) {
        continue
    }

    $trackTargets = @($meta.targets | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if (@($targetFilter).Count -gt 0) {
        $trackTargets = @($trackTargets | Where-Object { $targetFilter -contains $_.ToLowerInvariant() })
    }

    if (@($trackTargets).Count -eq 0) {
        continue
    }

    $loudnessCache = @{}

    foreach ($targetKey in $trackTargets) {
        $targetProp = $targetConfigs.PSObject.Properties[$targetKey]
        if ($null -eq $targetProp) {
            $syncEvents.Add([PSCustomObject]@{
                Slug       = $slug
                Target     = $targetKey
                Asset      = 'target'
                Action     = 'MissingTargetConfig'
                OutputPath = ''
                GainDb     = 0.0
            })
            continue
        }

        $tCfg = $targetProp.Value
        $targetRoot = [string]$tCfg.path
        $format = ([string]$tCfg.format).ToLowerInvariant()
        $sampleRate = if ($null -ne $tCfg.sampleRate) { [int]$tCfg.sampleRate } else { 44100 }
        $bitrate = if ($null -ne $tCfg.bitrate) { [string]$tCfg.bitrate } else { '320k' }
        $targetLufs = if ($null -ne $tCfg.targetLufs) { [double]$tCfg.targetLufs } else { -16.0 }
        $includeStems = if ($null -ne $tCfg.includeStems) { [bool]$tCfg.includeStems } else { $false }

        $referenceAudio = if ($null -ne $assets.MasterPath) {
            $assets.MasterPath
        } else {
            $firstStemKey = @($assets.Stems.Keys)[0]
            $assets.Stems[$firstStemKey]
        }

        $lufsKey = Format-InvariantNumber -Value $targetLufs -Decimals 1
        if (-not $loudnessCache.ContainsKey($lufsKey)) {
            if ($SkipLoudnorm) {
                $loudnessCache[$lufsKey] = [PSCustomObject]@{ GainDb = 0.0; MeasuredI = $null }
            } else {
                $loudnessCache[$lufsKey] = Measure-AudioIntegratedLoudness -Path $referenceAudio -TargetLufs $targetLufs
            }
        }
        $gainDb = [double]$loudnessCache[$lufsKey].GainDb

        if ($null -ne $assets.MasterPath) {
            $masterOutPath = Join-Path -Path $targetRoot -ChildPath ("{0}.{1}" -f $slug, $format)
            $needsUpdate = Test-AudioNeedsUpdate -SourcePath $assets.MasterPath -DestinationPath $masterOutPath -Force:$Force

            if (-not $needsUpdate) {
                $skippedFilesCount++
                $syncEvents.Add([PSCustomObject]@{
                    Slug       = $slug
                    Target     = $targetKey
                    Asset      = 'master'
                    Action     = 'UpToDate'
                    OutputPath = $masterOutPath
                    GainDb     = $gainDb
                })
            }
            elseif ($DryRun) {
                $syncEvents.Add([PSCustomObject]@{
                    Slug       = $slug
                    Target     = $targetKey
                    Asset      = 'master'
                    Action     = 'DryRun'
                    OutputPath = $masterOutPath
                    GainDb     = $gainDb
                })
            }
            elseif ($PSCmdlet.ShouldProcess($masterOutPath, ("Sync master '{0}' to '{1}'" -f $slug, $targetKey))) {
                $null = Convert-FlowAudioFile `
                    -InputPath $assets.MasterPath `
                    -OutputPath $masterOutPath `
                    -Format $format `
                    -SampleRate $sampleRate `
                    -GainDb $gainDb `
                    -Bitrate $bitrate
                $encodedFilesCount++
                $null = $targetsUpdated.Add($targetKey)
                $syncEvents.Add([PSCustomObject]@{
                    Slug       = $slug
                    Target     = $targetKey
                    Asset      = 'master'
                    Action     = 'Synced'
                    OutputPath = $masterOutPath
                    GainDb     = $gainDb
                })
            }
        }

        if ($includeStems -and $assets.Stems.Count -gt 0) {
            $trackTargetFolder = Join-Path -Path $targetRoot -ChildPath $slug
            $stemsOutFolder = Join-Path -Path $trackTargetFolder -ChildPath 'stems'
            $trackSidecarWritten = $false

            foreach ($stemKey in $assets.Stems.Keys) {
                $srcStemPath = $assets.Stems[$stemKey]
                $stemOutPath = Join-Path -Path $stemsOutFolder -ChildPath ("{0}.{1}" -f $stemKey, $format)
                $stemNeedsUpdate = Test-AudioNeedsUpdate -SourcePath $srcStemPath -DestinationPath $stemOutPath -Force:$Force

                if (-not $stemNeedsUpdate) {
                    $skippedFilesCount++
                    $syncEvents.Add([PSCustomObject]@{
                        Slug       = $slug
                        Target     = $targetKey
                        Asset      = ("stem:{0}" -f $stemKey)
                        Action     = 'UpToDate'
                        OutputPath = $stemOutPath
                        GainDb     = $gainDb
                    })
                }
                elseif ($DryRun) {
                    $syncEvents.Add([PSCustomObject]@{
                        Slug       = $slug
                        Target     = $targetKey
                        Asset      = ("stem:{0}" -f $stemKey)
                        Action     = 'DryRun'
                        OutputPath = $stemOutPath
                        GainDb     = $gainDb
                    })
                }
                elseif ($PSCmdlet.ShouldProcess($stemOutPath, ("Sync stem '{0}/{1}' to '{2}'" -f $slug, $stemKey, $targetKey))) {
                    $null = Convert-FlowAudioFile `
                        -InputPath $srcStemPath `
                        -OutputPath $stemOutPath `
                        -Format $format `
                        -SampleRate $sampleRate `
                        -GainDb $gainDb `
                        -Bitrate $bitrate `
                        -AlignDurationSec $maxDurSec
                    $encodedFilesCount++
                    $null = $targetsUpdated.Add($targetKey)
                    $trackSidecarWritten = $true
                    $syncEvents.Add([PSCustomObject]@{
                        Slug       = $slug
                        Target     = $targetKey
                        Asset      = ("stem:{0}" -f $stemKey)
                        Action     = 'Synced'
                        OutputPath = $stemOutPath
                        GainDb     = $gainDb
                    })
                }
            }

            $sidecarPath = Join-Path -Path $trackTargetFolder -ChildPath 'track.json'
            if (-not $DryRun -and ($trackSidecarWritten -or (-not (Test-Path -LiteralPath $sidecarPath)) -or $Force)) {
                if ($PSCmdlet.ShouldProcess($sidecarPath, ("Write sidecar metadata for '{0}'" -f $slug))) {
                    $sidecarObj = [ordered]@{
                        slug            = $slug
                        title           = [string]$meta.title
                        artist          = [string]$meta.artist
                        bpm             = $meta.bpm
                        key             = [string]$meta.key
                        timeSignature   = [string]$meta.timeSignature
                        durationSec     = [math]::Round($maxDurSec, 4)
                        sampleRate      = $sampleRate
                        format          = $format
                        targetLufs      = $targetLufs
                        appliedGainDb   = $gainDb
                        loopable        = [bool]$meta.loopable
                        instrumental    = [bool]$meta.instrumental
                        stems           = @($assets.Stems.Keys)
                        syncedAt        = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
                    }
                    Write-Utf8NoBomFile -Path $sidecarPath -Content ($sidecarObj | ConvertTo-Json -Depth 5)
                }
            }
        }
    }
}

$catalogObj = [ordered]@{
    generated  = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    vaultRoot  = $resolvedVaultRoot
    trackCount = $catalogTracks.Count
    tracks     = $catalogTracks.ToArray()
}

$catalogPath = Join-Path -Path $resolvedVaultRoot -ChildPath 'catalog.json'
if (-not $DryRun -and $PSCmdlet.ShouldProcess($catalogPath, 'Write vault/catalog.json')) {
    Write-Utf8NoBomFile -Path $catalogPath -Content ($catalogObj | ConvertTo-Json -Depth 8)
}

if (-not $DryRun -and -not $SkipManifestRebuild) {
    foreach ($updatedTargetKey in $targetsUpdated) {
        $prop = $targetConfigs.PSObject.Properties[$updatedTargetKey]
        if ($null -eq $prop) { continue }
        $postProp = $prop.Value.PSObject.Properties['postSyncScript']
        if ($null -eq $postProp -or [string]::IsNullOrWhiteSpace([string]$postProp.Value)) { continue }
        $postScriptPath = [string]$postProp.Value
        if (Test-Path -LiteralPath $postScriptPath) {
            if ($PSCmdlet.ShouldProcess($postScriptPath, ("Run postSyncScript for target '{0}'" -f $updatedTargetKey))) {
                $postRes = Invoke-NativeProcess -FilePath 'powershell.exe' -Arguments @(
                    '-NoProfile',
                    '-ExecutionPolicy', 'Bypass',
                    '-File', $postScriptPath
                )
                $postSyncRuns.Add([PSCustomObject]@{
                    Target   = $updatedTargetKey
                    Script   = $postScriptPath
                    ExitCode = $postRes.ExitCode
                })
                if ($postRes.ExitCode -ne 0) {
                    throw ("postSyncScript failed for '{0}' (exit {1}): {2}" -f $updatedTargetKey, $postRes.ExitCode, $postRes.StdErr)
                }
            }
        }
    }
}

$summary = [PSCustomObject]@{
    Status              = 'Success'
    DryRun              = [bool]$DryRun
    VaultRoot           = $resolvedVaultRoot
    CatalogPath         = $catalogPath
    TotalTracks         = $catalogTracks.Count
    TracksWithAudio     = $tracksWithAudioCount
    EncodedFiles        = $encodedFilesCount
    SkippedUpToDate     = $skippedFilesCount
    TargetsUpdated      = @($targetsUpdated)
    PostSyncRuns        = $postSyncRuns.ToArray()
    Events              = $syncEvents.ToArray()
}

if ($OutputJson) {
    Write-Output ($summary | ConvertTo-Json -Depth 8)
} else {
    $summary
}
