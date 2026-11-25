#Requires -Version 5.1
<#
.SYNOPSIS
    Mixes a Google Flow Music track or 4-stem split underneath an anime/video cut with dialogue sidechain ducking.

.DESCRIPTION
    Supports mixing either isolated stems (drums, bass, instruments, vocals) from -TrackDir or a single
    -MasterTrack underneath -InputVideo. Automatically ducks the vocals stem when stems are present,
    applies optional per-cut gain automation from a cues.json timeline, and sidechain-compresses the score
    against the video's dialogue/SFX track using FFmpeg.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputVideo,

    [Parameter(Mandatory = $false)]
    [string]$TrackDir = '',

    [Parameter(Mandatory = $false)]
    [string]$MasterTrack = '',

    [Parameter(Mandatory = $false)]
    [string]$OutputVideo = '',

    [Parameter(Mandatory = $false)]
    [double]$ScoreBaseDb = -8.0,

    [Parameter(Mandatory = $false)]
    [double]$VocalDuckDb = -30.0,

    [Parameter(Mandatory = $false)]
    [switch]$DropVocalsUnderDialogue = $true,

    [Parameter(Mandatory = $false)]
    [double]$SidechainThreshold = 0.03,

    [Parameter(Mandatory = $false)]
    [double]$SidechainRatio = 6.0,

    [Parameter(Mandatory = $false)]
    [string]$CueSheetPath = '',

    [Parameter(Mandatory = $false)]
    [switch]$OutputJson
)

$CallerDirectory = (Get-Location).Path
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

Import-Module -Name (Join-Path -Path $ScriptDir -ChildPath 'FlowMusicCommon.psm1') -Force

$resolvedVideo = Resolve-CallerPath -Path $InputVideo -BaseDirectory $CallerDirectory
if (-not (Test-Path -LiteralPath $resolvedVideo)) {
    throw ("Input video file not found: {0}" -f $resolvedVideo)
}

$resolvedOutput = if ([string]::IsNullOrWhiteSpace($OutputVideo)) {
    $parentDir = Split-Path -Parent $resolvedVideo
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedVideo)
    $ext = [System.IO.Path]::GetExtension($resolvedVideo)
    Join-Path -Path $parentDir -ChildPath ("{0}_scored{1}" -f $baseName, $ext)
} else {
    Resolve-CallerPath -Path $OutputVideo -BaseDirectory $CallerDirectory
}

$resolvedTrackDir = if ([string]::IsNullOrWhiteSpace($TrackDir)) { '' } else { Resolve-CallerPath -Path $TrackDir -BaseDirectory $CallerDirectory }
$resolvedMaster = if ([string]::IsNullOrWhiteSpace($MasterTrack)) { '' } else { Resolve-CallerPath -Path $MasterTrack -BaseDirectory $CallerDirectory }

$stemInputs = [ordered]@{}
$mixMode = ''

if (-not [string]::IsNullOrWhiteSpace($resolvedMaster)) {
    if (-not (Test-Path -LiteralPath $resolvedMaster)) {
        throw ("MasterTrack file not found: {0}" -f $resolvedMaster)
    }
    $mixMode = 'master'
}
elseif (-not [string]::IsNullOrWhiteSpace($resolvedTrackDir)) {
    if (-not (Test-Path -LiteralPath $resolvedTrackDir)) {
        throw ("TrackDir not found: {0}" -f $resolvedTrackDir)
    }
    $trackJsonFile = Join-Path -Path $resolvedTrackDir -ChildPath 'track.json'
    $meta = if (Test-Path -LiteralPath $trackJsonFile) {
        Get-Content -LiteralPath $trackJsonFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } else {
        $null
    }
    $assets = Find-TrackAudioAssets -TrackDir $resolvedTrackDir -TrackMeta $meta
    if ($assets.Stems.Count -gt 0) {
        $stemInputs = $assets.Stems
        $mixMode = 'stems'
    }
    elseif ($null -ne $assets.MasterPath) {
        $resolvedMaster = $assets.MasterPath
        $mixMode = 'master'
    }
    else {
        throw ("No stem or master audio files found inside TrackDir: {0}" -f $resolvedTrackDir)
    }
}
else {
    throw "Specify either -TrackDir or -MasterTrack."
}

$videoInfo = Get-AudioMediaInfo -Path $resolvedVideo
$videoDur = if ($videoInfo.DurationSec -gt 0.0) { $videoInfo.DurationSec } else { 30.0 }
$durStr = Format-InvariantNumber -Value $videoDur -Decimals 4

$cueExpr = ''
$cueCount = 0
if (-not [string]::IsNullOrWhiteSpace($CueSheetPath)) {
    $resolvedCuePath = Resolve-CallerPath -Path $CueSheetPath -BaseDirectory $CallerDirectory
    if (-not (Test-Path -LiteralPath $resolvedCuePath)) {
        throw ("Cue sheet file not found: {0}" -f $resolvedCuePath)
    }
    $cueObj = Get-Content -LiteralPath $resolvedCuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $cueList = @($cueObj.cues)
    if ($cueList.Count -gt 0) {
        $cueCount = $cueList.Count
        $terms = New-Object System.Collections.Generic.List[string]
        $fallbackGuards = New-Object System.Collections.Generic.List[string]
        foreach ($c in $cueList) {
            $sStr = Format-InvariantNumber -Value ([double]$c.startSec) -Decimals 3
            $eStr = Format-InvariantNumber -Value ([double]$c.endSec) -Decimals 3
            $cGainDb = if ($null -ne $c.scoreGainDb) { [double]$c.scoreGainDb } else { 0.0 }
            $cLin = [math]::Pow(10.0, ($cGainDb / 20.0))
            $cLinStr = Format-InvariantNumber -Value $cLin -Decimals 4
            $terms.Add(("(gte(t\,{0})*lt(t\,{1})*{2})" -f $sStr, $eStr, $cLinStr))
            $fallbackGuards.Add(("(1-gte(t\,{0})*lt(t\,{1}))" -f $sStr, $eStr))
        }
        $cueExpr = "(" + ($terms -join "+") + "+(" + ($fallbackGuards -join "*") + "))"
    }
}

$baseLinear = [math]::Pow(10.0, ($ScoreBaseDb / 20.0))
$baseLinearStr = Format-InvariantNumber -Value $baseLinear -Decimals 4

$ffArgs = New-Object System.Collections.Generic.List[string]
$ffArgs.Add('-y')
$ffArgs.Add('-hide_banner')
$ffArgs.Add('-loglevel')
$ffArgs.Add('error')
$ffArgs.Add('-i')
$ffArgs.Add($resolvedVideo)

$filterSteps = New-Object System.Collections.Generic.List[string]
$inputIndex = 1

if ($mixMode -eq 'stems') {
    $stemLabels = New-Object System.Collections.Generic.List[string]
    foreach ($stemKey in $stemInputs.Keys) {
        $ffArgs.Add('-stream_loop')
        $ffArgs.Add('-1')
        $ffArgs.Add('-i')
        $ffArgs.Add($stemInputs[$stemKey])

        $stemLabel = ("stem_{0}" -f $stemKey)
        $stemGainExpr = ''
        if ($stemKey -eq 'vocals' -and $DropVocalsUnderDialogue) {
            $vLin = [math]::Pow(10.0, ($VocalDuckDb / 20.0))
            $vLinStr = Format-InvariantNumber -Value $vLin -Decimals 5
            $stemGainExpr = (",volume={0}" -f $vLinStr)
        }

        $filterSteps.Add(("[{0}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{1},asetpts=PTS-STARTPTS{2}[{3}]" -f $inputIndex, $durStr, $stemGainExpr, $stemLabel))
        $stemLabels.Add(("[" + $stemLabel + "]"))
        $inputIndex++
    }

    $stemCount = $stemLabels.Count
    if ($stemCount -eq 1) {
        $filterSteps.Add(("{0}anull[score_raw]" -f $stemLabels[0]))
    } else {
        $filterSteps.Add(("{0}amix=inputs={1}:duration=first:normalize=0[score_raw]" -f ($stemLabels -join ''), $stemCount))
    }
} else {
    $ffArgs.Add('-stream_loop')
    $ffArgs.Add('-1')
    $ffArgs.Add('-i')
    $ffArgs.Add($resolvedMaster)
    $filterSteps.Add(("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{0},asetpts=PTS-STARTPTS[score_raw]" -f $durStr))
}

if ([string]::IsNullOrWhiteSpace($cueExpr)) {
    $filterSteps.Add(("[score_raw]volume={0}[score]" -f $baseLinearStr))
} else {
    $filterSteps.Add(("[score_raw]volume='{0}*{1}':eval=frame[score]" -f $baseLinearStr, $cueExpr))
}

if ($videoInfo.HasAudio) {
    $thrStr = Format-InvariantNumber -Value $SidechainThreshold -Decimals 4
    $ratStr = Format-InvariantNumber -Value $SidechainRatio -Decimals 2
    $filterSteps.Add('[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,highpass=f=80,asplit=2[orig_a][sc_key]')
    $filterSteps.Add(("[score][sc_key]sidechaincompress=threshold={0}:ratio={1}:attack=25:release=350[score_ducked]" -f $thrStr, $ratStr))
    $filterSteps.Add('[orig_a][score_ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.95[outa]')
} else {
    $filterSteps.Add('[score]alimiter=limit=0.95[outa]')
}

$filterComplex = ($filterSteps -join '; ')

$outParent = Split-Path -Parent $resolvedOutput
if (-not [string]::IsNullOrWhiteSpace($outParent) -and -not (Test-Path -LiteralPath $outParent)) {
    $null = New-Item -ItemType Directory -Path $outParent -Force
}

$ffArgs.Add('-filter_complex')
$ffArgs.Add($filterComplex)
$ffArgs.Add('-map')
$ffArgs.Add('0:v:0')
$ffArgs.Add('-map')
$ffArgs.Add('[outa]')
$ffArgs.Add('-c:v')
$ffArgs.Add('copy')
$ffArgs.Add('-c:a')
$ffArgs.Add('aac')
$ffArgs.Add('-b:a')
$ffArgs.Add('256k')
$ffArgs.Add('-ar')
$ffArgs.Add('48000')
$ffArgs.Add('-shortest')
$ffArgs.Add($resolvedOutput)

if ($PSCmdlet.ShouldProcess($resolvedOutput, ("Mix Flow Music ({0}) into '{1}'" -f $mixMode, $resolvedVideo))) {
    $res = Invoke-NativeProcess -FilePath 'ffmpeg' -Arguments $ffArgs.ToArray()
    if ($res.ExitCode -ne 0) {
        throw ("FFmpeg score mix failed (exit {0}): {1}" -f $res.ExitCode, $res.StdErr)
    }

    $outInfo = Get-AudioMediaInfo -Path $resolvedOutput
    $summary = [PSCustomObject]@{
        Status                  = 'Success'
        MixMode                 = $mixMode
        InputVideo              = $resolvedVideo
        OutputVideo             = $outInfo.Path
        DurationSec             = $outInfo.DurationSec
        SampleRate              = $outInfo.SampleRate
        Channels                = $outInfo.Channels
        StemsUsed               = @($stemInputs.Keys)
        DropVocalsUnderDialogue = [bool]$DropVocalsUnderDialogue
        CueCount                = $cueCount
        ScoreBaseDb             = $ScoreBaseDb
        Bytes                   = $outInfo.Bytes
    }

    if ($OutputJson) {
        Write-Output ($summary | ConvertTo-Json -Depth 6)
    } else {
        $summary
    }
}
