#Requires -Version 5.1
<#
.SYNOPSIS
    One-command deployment bridge from Google Flow Music to 3D ROM Studio and DEAD CHANNEL 13.

.DESCRIPTION
    1. RomStudio (rom01-rom03): Deploys circular-looped 320k MP3s from exports/hits/ into
       G:\My Drive\Antigravity\Projects\game mods\assets\sounds\bgm\ using SHA-256 checks
       (zero re-encoding so 120ms circular loop seams remain bit-exact) and writes bgm_manifest.json.
    2. DeadChannel13 (yyh01, yyh02): Invokes Sync-FlowMusicVault.ps1 for dead_channel_13 (-16 LUFS
       48 kHz WAV masters + instruments stems + track.json sidecars), mirrors SHA-256-checked
       MP3 audition copies to audio/flow_music/previews/, and writes credits_teasers_manifest.json
       with 24 fps invideo-timeline / invideo-media cue windows.

.EXAMPLE
    Set-Location "G:\My Drive\Antigravity\Projects\Google Flow-music"
    .\scripts\Sync-FlowMusicBridge.ps1 -OutputJson
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('All', 'RomStudio', 'DeadChannel13')]
    [string]$Target = 'All',

    [Parameter(Mandatory = $false)]
    [switch]$Force,

    [Parameter(Mandatory = $false)]
    [switch]$DryRun,

    [Parameter(Mandatory = $false)]
    [switch]$OutputJson
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

$HubRoot = Split-Path -Parent $ScriptDir
Import-Module -Name (Join-Path -Path $ScriptDir -ChildPath 'FlowMusicCommon.psm1') -Force

$ConfigPath = Join-MultiPath -Parts @($HubRoot, 'config', 'project-targets.json')
$HitsDir = Join-MultiPath -Parts @($HubRoot, 'exports', 'hits')
$VaultDir = Join-Path -Path $HubRoot -ChildPath 'vault'
$SyncVaultScript = Join-Path -Path $ScriptDir -ChildPath 'Sync-FlowMusicVault.ps1'

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw ("Config file not found: {0}" -f $ConfigPath)
}

$ConfigObj = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Get-Sha256HexLower {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Copy-FileIfHashChanged {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $false)][switch]$ForceCopy,
        [Parameter(Mandatory = $false)][switch]$IsDryRun
    )

    if (-not (Test-Path -LiteralPath $SourcePath)) {
        throw ("Source file missing: {0}" -f $SourcePath)
    }

    $srcHash = Get-Sha256HexLower -Path $SourcePath
    $needsCopy = [bool]$ForceCopy
    if (-not $needsCopy) {
        if (-not (Test-Path -LiteralPath $DestinationPath)) {
            $needsCopy = $true
        } else {
            $dstHash = Get-Sha256HexLower -Path $DestinationPath
            if ($dstHash -ne $srcHash) {
                $needsCopy = $true
            }
        }
    }

    if (-not $needsCopy) {
        return [PSCustomObject]@{
            Action = 'UpToDate'
            Sha256 = $srcHash
        }
    }

    if ($IsDryRun) {
        return [PSCustomObject]@{
            Action = 'DryRun'
            Sha256 = $srcHash
        }
    }

    $dstParent = Split-Path -Parent $DestinationPath
    if (-not [string]::IsNullOrWhiteSpace($dstParent) -and -not (Test-Path -LiteralPath $dstParent)) {
        if ($PSCmdlet.ShouldProcess($dstParent, 'Create target audio directory')) {
            $null = New-Item -ItemType Directory -Path $dstParent -Force
        }
    }

    if ($PSCmdlet.ShouldProcess($DestinationPath, ("Copy bit-exact audio from {0}" -f $SourcePath))) {
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    }

    return [PSCustomObject]@{
        Action = 'Synced'
        Sha256 = $srcHash
    }
}

function Read-VaultTrackMeta {
    param([Parameter(Mandatory = $true)][string]$Slug)
    $metaPath = Join-MultiPath -Parts @($VaultDir, $Slug, 'track.json')
    if (-not (Test-Path -LiteralPath $metaPath)) {
        throw ("Vault metadata not found: {0}" -f $metaPath)
    }
    return (Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

$events = New-Object System.Collections.Generic.List[object]
$romStudioSynced = 0
$romStudioUpToDate = 0
$deadChannelEncoded = 0
$deadChannelSkipped = 0
$previewsSynced = 0
$previewsUpToDate = 0
$manifestsWritten = 0
$manifestPaths = New-Object System.Collections.Generic.List[string]

$doRom = ($Target -eq 'All') -or ($Target -eq 'RomStudio')
$doDc13 = ($Target -eq 'All') -or ($Target -eq 'DeadChannel13')

if ($doRom) {
    $romTargetProp = $ConfigObj.targets.PSObject.Properties['rom_studio_3d']
    if ($null -eq $romTargetProp) {
        throw "Missing 'rom_studio_3d' target entry in config/project-targets.json"
    }
    $romTargetCfg = $romTargetProp.Value
    $romBgmDir = [string]$romTargetCfg.path

    $romSpecs = @(
        [ordered]@{ zoneKey = 'action'; slug = 'rom01-palace-shorts-hook'; zones = @('raceway', 'hideseek', 'dronearena', 'freeplay') },
        [ordered]@{ zoneKey = 'palace'; slug = 'rom02-velvet-palace-longform'; zones = @('palace', 'rotunda', 'portals', 'leisure') },
        [ordered]@{ zoneKey = 'vault';  slug = 'rom03-console-vault-bgm'; zones = @('pclounge', 'gamecube', 'n64', 'ps2_ps3', 'ps1_ps4', 'sega', 'snes_nes', 'gba_nds') }
    )

    $bgmManifestTracks = New-Object System.Collections.Generic.List[object]
    foreach ($spec in $romSpecs) {
        $slug = [string]$spec.slug
        $srcMp3 = Join-Path -Path $HitsDir -ChildPath ("{0}.mp3" -f $slug)
        $dstMp3 = Join-Path -Path $romBgmDir -ChildPath ("{0}.mp3" -f $slug)

        $copyRes = Copy-FileIfHashChanged -SourcePath $srcMp3 -DestinationPath $dstMp3 -ForceCopy:$Force -IsDryRun:$DryRun
        if ($copyRes.Action -eq 'Synced') { $romStudioSynced++ }
        elseif ($copyRes.Action -eq 'UpToDate') { $romStudioUpToDate++ }

        $events.Add([PSCustomObject]@{
            Target     = 'rom_studio_3d'
            Slug       = $slug
            Asset      = 'mp3_320k_loop'
            Action     = $copyRes.Action
            OutputPath = $dstMp3
            Sha256     = $copyRes.Sha256
        })

        $meta = Read-VaultTrackMeta -Slug $slug
        $probe = Get-AudioMediaInfo -Path $srcMp3
        $bgmManifestTracks.Add([ordered]@{
            zoneKey         = [string]$spec.zoneKey
            assignedZones   = @($spec.zones)
            slug            = $slug
            file            = ("{0}.mp3" -f $slug)
            url             = ("assets/sounds/bgm/{0}.mp3" -f $slug)
            title           = [string]$meta.title
            bpm             = $meta.bpm
            key             = [string]$meta.key
            durationSec     = [math]::Round([double]$probe.DurationSec, 3)
            sampleRate      = [int]$probe.SampleRate
            bytes           = [long]$probe.Bytes
            sha256          = $copyRes.Sha256
            loopable        = [bool]$meta.loopable
            targetLufs      = if ($null -ne $romTargetCfg.targetLufs) { [double]$romTargetCfg.targetLufs } else { -14.5 }
            synthIdVerified = [bool]$meta.synthIdVerified
            licenseTier     = [string]$meta.licenseTier
        })
    }

    $bgmManifestPath = Join-Path -Path $romBgmDir -ChildPath 'bgm_manifest.json'
    if (-not $DryRun) {
        $bgmManifestObj = [ordered]@{
            schema      = 'rom-studio-bgm-manifest/1.0'
            generated   = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
            sourceHub   = $HubRoot
            targetDir   = $romBgmDir
            audioEngine = 'rom_studio_audio.js'
            trackCount  = $bgmManifestTracks.Count
            tracks      = $bgmManifestTracks.ToArray()
        }
        Write-Utf8NoBomFile -Path $bgmManifestPath -Content ($bgmManifestObj | ConvertTo-Json -Depth 6)
        $manifestsWritten++
        $manifestPaths.Add($bgmManifestPath)
    }
}

if ($doDc13) {
    $dcTargetProp = $ConfigObj.targets.PSObject.Properties['dead_channel_13']
    if ($null -eq $dcTargetProp) {
        throw "Missing 'dead_channel_13' target entry in config/project-targets.json"
    }
    $dcTargetCfg = $dcTargetProp.Value
    $dcAudioDir = [string]$dcTargetCfg.path
    $dcPreviewsDir = Join-Path -Path $dcAudioDir -ChildPath 'previews'

    $dcParams = @{
        Target              = 'dead_channel_13'
        TrackSlug           = @('yyh01-sunset-credits-suite', 'yyh02-spirit-detective-chill')
        SkipManifestRebuild = $true
        OutputJson          = $true
        Force               = [bool]$Force
        DryRun              = [bool]$DryRun
    }

    $dcRaw = (& $SyncVaultScript @dcParams) -join "`n"
    $dcRes = $dcRaw | ConvertFrom-Json
    $deadChannelEncoded = [int]$dcRes.EncodedFiles
    $deadChannelSkipped = [int]$dcRes.SkippedUpToDate

    foreach ($ev in @($dcRes.Events)) {
        $events.Add([PSCustomObject]@{
            Target     = 'dead_channel_13'
            Slug       = [string]$ev.Slug
            Asset      = [string]$ev.Asset
            Action     = [string]$ev.Action
            OutputPath = [string]$ev.OutputPath
            Sha256     = ''
        })
    }

    $dcSlugs = @('yyh01-sunset-credits-suite', 'yyh02-spirit-detective-chill')
    $dcManifestTracks = New-Object System.Collections.Generic.List[object]

    foreach ($slug in $dcSlugs) {
        $srcPreviewMp3 = Join-Path -Path $HitsDir -ChildPath ("{0}.mp3" -f $slug)
        $dstPreviewMp3 = Join-Path -Path $dcPreviewsDir -ChildPath ("{0}.mp3" -f $slug)
        $prevCopyRes = Copy-FileIfHashChanged -SourcePath $srcPreviewMp3 -DestinationPath $dstPreviewMp3 -ForceCopy:$Force -IsDryRun:$DryRun
        if ($prevCopyRes.Action -eq 'Synced') { $previewsSynced++ }
        elseif ($prevCopyRes.Action -eq 'UpToDate') { $previewsUpToDate++ }

        $events.Add([PSCustomObject]@{
            Target     = 'dead_channel_13'
            Slug       = $slug
            Asset      = 'preview_mp3'
            Action     = $prevCopyRes.Action
            OutputPath = $dstPreviewMp3
            Sha256     = $prevCopyRes.Sha256
        })

        $meta = Read-VaultTrackMeta -Slug $slug
        $wavPath = Join-Path -Path $dcAudioDir -ChildPath ("{0}.wav" -f $slug)
        $stemPath = Join-MultiPath -Parts @($dcAudioDir, $slug, 'stems', 'instruments.wav')
        $wavHash = if (Test-Path -LiteralPath $wavPath) { Get-Sha256HexLower -Path $wavPath } else { '' }
        $mp3Probe = Get-AudioMediaInfo -Path $srcPreviewMp3

        $cueSlices = if ($slug -eq 'yyh01-sunset-credits-suite') {
            @(
                [ordered]@{
                    usage          = 'EP01 Ending Credits (48.0s Struggle of Sadness + Unbalanced Kiss)'
                    sourceInSec    = 0.0
                    sourceOutSec   = 48.0
                    startFrame24   = 0
                    endFrame24     = 1152
                    bus            = 'BUS_MUSIC'
                    fadeOutFrames  = 108
                },
                [ordered]@{
                    usage          = 'EP02 Ending Credits (48.0s Bridge #1 -> Daydream Generation)'
                    sourceInSec    = 86.2
                    sourceOutSec   = 134.2
                    startFrame24   = 2069
                    endFrame24     = 3221
                    bus            = 'BUS_MUSIC'
                    fadeOutFrames  = 108
                }
            )
        } else {
            @(
                [ordered]@{
                    usage          = 'EP02/EP03 Midnight Teaser & Recap Underscore (30.0s)'
                    sourceInSec    = 0.0
                    sourceOutSec   = 30.0
                    startFrame24   = 0
                    endFrame24     = 720
                    bus            = 'BUS_MUSIC'
                    duckBehindDialogueDb = -11.0
                },
                [ordered]@{
                    usage          = 'Full Midnight Interlude Master'
                    sourceInSec    = 0.0
                    sourceOutSec   = [math]::Round([double]$mp3Probe.DurationSec, 3)
                    startFrame24   = 0
                    endFrame24     = [int][math]::Round([double]$mp3Probe.DurationSec * 24.0)
                    bus            = 'BUS_MUSIC'
                    duckBehindDialogueDb = -11.0
                }
            )
        }

        $dcManifestTracks.Add([ordered]@{
            slug                = $slug
            title               = [string]$meta.title
            bpm                 = $meta.bpm
            key                 = [string]$meta.key
            durationSec         = [math]::Round([double]$mp3Probe.DurationSec, 3)
            masterWav           = $wavPath
            instrumentalStemWav = $stemPath
            previewMp3          = $dstPreviewMp3
            wavSha256           = $wavHash
            mp3Sha256           = $prevCopyRes.Sha256
            synthIdVerified     = [bool]$meta.synthIdVerified
            licenseTier         = [string]$meta.licenseTier
            cueSlices           = $cueSlices
        })
    }

    $dcManifestPath = Join-Path -Path $dcAudioDir -ChildPath 'credits_teasers_manifest.json'
    if (-not $DryRun) {
        $dcManifestObj = [ordered]@{
            schema    = 'dc13-flow-music-bridge/1.0'
            generated = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
            sourceHub = $HubRoot
            targetDir = $dcAudioDir
            invideoMediaStandards = [ordered]@{
                fps                = 24
                frameMath          = 'half-open [start_f, end_f) at 24 fps'
                sidechainBusSource = 'BUS_DIALOGUE'
                musicBus           = 'BUS_MUSIC'
                duckDb             = -11.0
                targetBroadcastLufs = if ($null -ne $dcTargetCfg.targetLufs) { [double]$dcTargetCfg.targetLufs } else { -16.0 }
                targetYouTubeLufs  = -14.0
                limiterCeilingDbtp = -1.0
                rightsNotice       = 'yyh01 and yyh02 carry synthIdVerified=false external OST reference stems. Swap with original Google Flow Music renders before monetized commercial YouTube release.'
            }
            trackCount = $dcManifestTracks.Count
            tracks     = $dcManifestTracks.ToArray()
        }
        Write-Utf8NoBomFile -Path $dcManifestPath -Content ($dcManifestObj | ConvertTo-Json -Depth 7)
        $manifestsWritten++
        $manifestPaths.Add($dcManifestPath)
    }
}

$summary = [PSCustomObject]@{
    Status             = 'Success'
    Target             = $Target
    DryRun             = [bool]$DryRun
    Force              = [bool]$Force
    RomStudioSynced    = $romStudioSynced
    RomStudioUpToDate  = $romStudioUpToDate
    DeadChannelEncoded = $deadChannelEncoded
    DeadChannelSkipped = $deadChannelSkipped
    PreviewsSynced     = $previewsSynced
    PreviewsUpToDate   = $previewsUpToDate
    ManifestsWritten   = $manifestsWritten
    ManifestPaths      = $manifestPaths.ToArray()
    Events             = $events.ToArray()
}

if ($OutputJson) {
    Write-Output ($summary | ConvertTo-Json -Depth 8)
} else {
    $summary
}
