#Requires -Version 5.1
<#
.SYNOPSIS
    Scaffolds ready-to-fill Flow Music vault track workspaces from curated soundtrack packs.

.DESCRIPTION
    Reads packs/<packName>/pack.json and creates track folders in vault/<slug>/ via
    New-FlowMusicTrack.ps1, pre-populating BPM, key, moods, targets, Flow Music briefs, and lyrics.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dead-channel-13', 'youtube-monetization-beats', 'game-studio-ost', 'yyh-dandadan-fusion', 'all')]
    [string]$PackName,

    [Parameter(Mandatory = $false)]
    [string]$VaultRoot = '',

    [Parameter(Mandatory = $false)]
    [switch]$Force,

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

$newTrackScript = Join-Path -Path $ScriptDir -ChildPath 'New-FlowMusicTrack.ps1'
if (-not (Test-Path -LiteralPath $newTrackScript)) {
    throw ("Required script missing: {0}" -f $newTrackScript)
}

$packsToRun = if ($PackName -eq 'all') {
    @('dead-channel-13', 'youtube-monetization-beats', 'game-studio-ost', 'yyh-dandadan-fusion')
} else {
    @($PackName)
}

$results = New-Object System.Collections.Generic.List[object]
$createdCount = 0
$skippedCount = 0

foreach ($pack in $packsToRun) {
    $packJsonPath = Join-MultiPath -Parts @($HubRoot, 'packs', $pack, 'pack.json')
    if (-not (Test-Path -LiteralPath $packJsonPath)) {
        throw ("Pack manifest not found: {0}" -f $packJsonPath)
    }

    $packData = Get-Content -LiteralPath $packJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($t in @($packData.tracks)) {
        $slug = [string]$t.slug
        if ($PSCmdlet.ShouldProcess($slug, ("Initialize track from pack '{0}'" -f $pack))) {
            $invokeParams = @{
                Slug          = $slug
                Title         = [string]$t.title
                Genre         = [string]$t.genre
                Bpm           = [int]$t.bpm
                Key           = [string]$t.key
                TimeSignature = if ($null -ne $t.timeSignature) { [string]$t.timeSignature } else { '4/4' }
                Moods         = @($t.moods | ForEach-Object { [string]$_ })
                Targets       = @($t.targets | ForEach-Object { [string]$_ })
                PromptText    = [string]$t.prompt
                LyricsText    = if ($null -ne $t.lyrics) { [string]$t.lyrics } else { '' }
                CueNotes      = if ($null -ne $t.cueNotes) { [string]$t.cueNotes } else { '' }
                VaultRoot     = $resolvedVaultRoot
                Instrumental  = [bool]$t.instrumental
                Loopable      = [bool]$t.loopable
                Force         = [bool]$Force
            }

            $res = & $newTrackScript @invokeParams
            if ($res.Status -eq 'Created') {
                $createdCount++
            } else {
                $skippedCount++
            }
            $results.Add([PSCustomObject]@{
                Pack     = $pack
                Slug     = $res.Slug
                Status   = $res.Status
                TrackDir = $res.TrackDir
            })
        }
    }
}

$summary = [PSCustomObject]@{
    Status   = 'Success'
    PackName = $PackName
    VaultRoot = $resolvedVaultRoot
    Created  = $createdCount
    Skipped  = $skippedCount
    Tracks   = $results.ToArray()
}

if ($OutputJson) {
    Write-Output ($summary | ConvertTo-Json -Depth 6)
} else {
    $summary
}
