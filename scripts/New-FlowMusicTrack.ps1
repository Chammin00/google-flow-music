#Requires -Version 5.1
<#
.SYNOPSIS
    Creates or updates a canonical track workspace inside the Google Flow Music vault.

.DESCRIPTION
    Scaffolds vault/<slug>/ with track.json (UTF-8 without BOM), prompt.md, lyrics.md,
    and stems/. Optionally copies a master audio file and isolated stems (drums, bass,
    instruments, vocals) into the track directory.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Slug,

    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $false)]
    [string]$Genre = '90s Anime Jazz-Rock',

    [Parameter(Mandatory = $false)]
    [int]$Bpm = 120,

    [Parameter(Mandatory = $false)]
    [string]$Key = 'C minor',

    [Parameter(Mandatory = $false)]
    [string]$TimeSignature = '4/4',

    [Parameter(Mandatory = $false)]
    [string[]]$Moods = @('energetic'),

    [Parameter(Mandatory = $false)]
    [string[]]$Targets = @('youtube_channels', 'youtube_remaster'),

    [Parameter(Mandatory = $false)]
    [switch]$Instrumental,

    [Parameter(Mandatory = $false)]
    [switch]$Loopable,

    [Parameter(Mandatory = $false)]
    [string]$PromptText = '',

    [Parameter(Mandatory = $false)]
    [string]$LyricsText = '',

    [Parameter(Mandatory = $false)]
    [string]$CueNotes = '',

    [Parameter(Mandatory = $false)]
    [string]$FlowSessionUrl = '',

    [Parameter(Mandatory = $false)]
    [string]$MasterSourcePath = '',

    [Parameter(Mandatory = $false)]
    [string]$DrumsSourcePath = '',

    [Parameter(Mandatory = $false)]
    [string]$BassSourcePath = '',

    [Parameter(Mandatory = $false)]
    [string]$InstrumentsSourcePath = '',

    [Parameter(Mandatory = $false)]
    [string]$VocalsSourcePath = '',

    [Parameter(Mandatory = $false)]
    [string]$VaultRoot = '',

    [Parameter(Mandatory = $false)]
    [switch]$Force
)

$CallerDirectory = (Get-Location).Path
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

$HubRoot = Split-Path -Parent $ScriptDir
Import-Module -Name (Join-Path -Path $ScriptDir -ChildPath 'FlowMusicCommon.psm1') -Force

$cleanSlug = ($Slug.ToLowerInvariant() -replace '[^a-z0-9-]+', '-').Trim('-')
if ([string]::IsNullOrWhiteSpace($cleanSlug)) {
    throw ("Invalid slug '{0}': must contain at least one alphanumeric character." -f $Slug)
}

$resolvedVaultRoot = if ([string]::IsNullOrWhiteSpace($VaultRoot)) {
    Join-Path -Path $HubRoot -ChildPath 'vault'
} else {
    Resolve-CallerPath -Path $VaultRoot -BaseDirectory $CallerDirectory
}

$trackDir = Join-Path -Path $resolvedVaultRoot -ChildPath $cleanSlug
$stemsDir = Join-Path -Path $trackDir -ChildPath 'stems'
$trackJsonPath = Join-Path -Path $trackDir -ChildPath 'track.json'
$promptPath = Join-Path -Path $trackDir -ChildPath 'prompt.md'
$lyricsPath = Join-Path -Path $trackDir -ChildPath 'lyrics.md'

if ((Test-Path -LiteralPath $trackJsonPath) -and (-not $Force)) {
    return [PSCustomObject]@{
        Status        = 'Skipped'
        Slug          = $cleanSlug
        TrackDir      = $trackDir
        TrackJsonPath = $trackJsonPath
        PromptPath    = $promptPath
        LyricsPath    = $lyricsPath
        MasterPath    = $null
        Stems         = @{}
    }
}

if ($PSCmdlet.ShouldProcess($trackDir, ("Create Flow Music track '{0}'" -f $cleanSlug))) {
    if (-not (Test-Path -LiteralPath $trackDir)) {
        $null = New-Item -ItemType Directory -Path $trackDir -Force
    }
    if (-not (Test-Path -LiteralPath $stemsDir)) {
        $null = New-Item -ItemType Directory -Path $stemsDir -Force
    }

    $masterRel = 'master.wav'
    $copiedMaster = $null
    if (-not [string]::IsNullOrWhiteSpace($MasterSourcePath)) {
        $srcMaster = Resolve-CallerPath -Path $MasterSourcePath -BaseDirectory $CallerDirectory
        if (-not (Test-Path -LiteralPath $srcMaster)) {
            throw ("Master audio source not found: {0}" -f $srcMaster)
        }
        $ext = [System.IO.Path]::GetExtension($srcMaster).ToLowerInvariant()
        $masterRel = 'master' + $ext
        $copiedMaster = Join-Path -Path $trackDir -ChildPath $masterRel
        Copy-Item -LiteralPath $srcMaster -Destination $copiedMaster -Force
    }

    $stemSpec = [ordered]@{
        drums       = $DrumsSourcePath
        bass        = $BassSourcePath
        instruments = $InstrumentsSourcePath
        vocals      = $VocalsSourcePath
    }

    $stemsRel = [ordered]@{}
    $copiedStems = [ordered]@{}
    foreach ($stemKey in $stemSpec.Keys) {
        $rawSrc = $stemSpec[$stemKey]
        if (-not [string]::IsNullOrWhiteSpace($rawSrc)) {
            $srcStem = Resolve-CallerPath -Path $rawSrc -BaseDirectory $CallerDirectory
            if (-not (Test-Path -LiteralPath $srcStem)) {
                throw ("Stem '{0}' source not found: {1}" -f $stemKey, $srcStem)
            }
            $sExt = [System.IO.Path]::GetExtension($srcStem).ToLowerInvariant()
            $relPath = 'stems/' + $stemKey + $sExt
            $destStem = Join-Path -Path $stemsDir -ChildPath ($stemKey + $sExt)
            Copy-Item -LiteralPath $srcStem -Destination $destStem -Force
            $stemsRel[$stemKey] = $relPath
            $copiedStems[$stemKey] = $destStem
        } else {
            $stemsRel[$stemKey] = 'stems/' + $stemKey + '.wav'
        }
    }

    $cleanMoods = @($Moods | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if (@($cleanMoods).Count -eq 0) {
        $cleanMoods = @('energetic')
    }
    $cleanTargets = @($Targets | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $trackObj = [ordered]@{
        slug            = $cleanSlug
        title           = $Title
        artist          = 'Chase (@chaseham00) / Google Flow Music'
        bpm             = $Bpm
        key             = $Key
        timeSignature   = $TimeSignature
        moods           = $cleanMoods
        genre           = $Genre
        instrumental    = [bool]$Instrumental
        loopable        = [bool]$Loopable
        licenseTier     = 'Original Creator Track (Flow Music)'
        synthIdVerified = $true
        flowSessionUrl  = $FlowSessionUrl
        targets         = $cleanTargets
        masterFile      = $masterRel
        stems           = $stemsRel
        cueNotes        = $CueNotes
        createdAt       = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
    }

    $jsonStr = $trackObj | ConvertTo-Json -Depth 6
    Write-Utf8NoBomFile -Path $trackJsonPath -Content $jsonStr

    $promptBody = if ([string]::IsNullOrWhiteSpace($PromptText)) {
        "Describe genre ($Genre), $Bpm BPM in $Key, instrumentation, vocal delivery, groove feel, and arrangement arc."
    } else {
        $PromptText.Trim()
    }

    $cueSection = if ([string]::IsNullOrWhiteSpace($CueNotes)) {
        "- Target projects: $($cleanTargets -join ', ')"
    } else {
        "- Target projects: $($cleanTargets -join ', ')`r`n- Cue notes: $CueNotes"
    }

    $promptDoc = @"
# Google Flow Music Brief - $Title

- **Slug:** ``$cleanSlug``
- **BPM / Key / Meter:** $Bpm BPM | $Key | $TimeSignature
- **Genre:** $Genre
- **Moods:** $($cleanMoods -join ', ')
- **Loopable:** $([bool]$Loopable) | **Instrumental:** $([bool]$Instrumental)

## 1. Initial Flow Music Studio Prompt
$promptBody

## 2. Conversational Producer Directives (Replace / Extend / Cover)
- **Pass 1 (Groove & Low End):** Tighten pocket between bass and drums without muddying mids.
- **Pass 2 (Section Replace):** Refine chorus lift or transition bars while preserving the core motif.
- **Pass 3 (Extend / Stems):** Extend clean tail or loopable ending before splitting 4 stems (``drums``, ``bass``, ``instruments``, ``vocals``).

## 3. Target & Cue Routing
$cueSection
"@
    Write-Utf8NoBomFile -Path $promptPath -Content $promptDoc

    $lyricsBody = if ([string]::IsNullOrWhiteSpace($LyricsText)) {
        if ($Instrumental) {
            "[Instrumental]`r`nNo lead vocals. Focus on expressive lead melody, rhythm pocket, and clean stem separation."
        } else {
            "[Intro]`r`n(Instrumental build)`r`n`r`n[Verse 1]`r`nWrite verse lines here or paste Flow Music Ghostwriter output.`r`n`r`n[Chorus]`r`nWrite hook lines here.`r`n`r`n[Outro]`r`n(Clean fade or loop point)"
        }
    } else {
        $LyricsText.Trim()
    }

    $lyricsDoc = @"
# Lyrics - $Title

$lyricsBody
"@
    Write-Utf8NoBomFile -Path $lyricsPath -Content $lyricsDoc

    return [PSCustomObject]@{
        Status        = 'Created'
        Slug          = $cleanSlug
        TrackDir      = $trackDir
        TrackJsonPath = $trackJsonPath
        PromptPath    = $promptPath
        LyricsPath    = $lyricsPath
        MasterPath    = $copiedMaster
        Stems         = $copiedStems
    }
}
