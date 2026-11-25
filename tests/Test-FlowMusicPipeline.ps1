#Requires -Version 5.1
<#
.SYNOPSIS
    End-to-end automated verification for the Google Flow Music vault, FFmpeg pipelines, game stems, packs, and MCP registration.
#>
[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ScriptDir) { $ScriptDir = $PSScriptRoot }
Set-Location -Path $ScriptDir
$ErrorActionPreference = 'Stop'

$HubRoot = Split-Path -Parent $ScriptDir
$ScriptsDir = Join-Path -Path $HubRoot -ChildPath 'scripts'
Import-Module -Name (Join-Path -Path $ScriptsDir -ChildPath 'FlowMusicCommon.psm1') -Force

function Assert-True {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw ("ASSERTION FAILED: {0}" -f $Message)
    }
}

function Assert-NoUtf8Bom {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )
    Assert-True -Condition (Test-Path -LiteralPath $Path) -Message ("Expected JSON file missing: {0}" -f $Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3) {
        $hasBom = ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
        Assert-True -Condition (-not $hasBom) -Message ("File contains forbidden UTF-8 BOM: {0}" -f $Path)
    }
}

$tempRoot = Join-Path -Path $env:TEMP -ChildPath ("flow_music_e2e_test_" + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $tempRoot -Force

try {
    $mediaDir = Join-Path -Path $tempRoot -ChildPath 'src_media'
    $tempVault = Join-Path -Path $tempRoot -ChildPath 'vault'
    $tempExports = Join-Path -Path $tempRoot -ChildPath 'exports'
    $null = New-Item -ItemType Directory -Path $mediaDir -Force
    $null = New-Item -ItemType Directory -Path $tempVault -Force
    $null = New-Item -ItemType Directory -Path $tempExports -Force

    Write-Host "[1/6] Generating synthetic audio stems and test video..." -ForegroundColor Cyan
    $masterSrc = Join-Path -Path $mediaDir -ChildPath 'master.wav'
    $drumsSrc = Join-Path -Path $mediaDir -ChildPath 'drums.wav'
    $bassSrc = Join-Path -Path $mediaDir -ChildPath 'bass.wav'
    $instSrc = Join-Path -Path $mediaDir -ChildPath 'instruments.wav'
    $vocalsSrc = Join-Path -Path $mediaDir -ChildPath 'vocals.wav'
    $videoSrc = Join-Path -Path $mediaDir -ChildPath 'test_video.mp4'

    $toneJobs = @(
        @{ Out = $masterSrc; Freq = '220'; Dur = '2'; Vol = '0.35' },
        @{ Out = $drumsSrc;  Freq = '110'; Dur = '2'; Vol = '0.25' },
        @{ Out = $bassSrc;   Freq = '65';  Dur = '2'; Vol = '0.25' },
        @{ Out = $instSrc;   Freq = '440'; Dur = '2'; Vol = '0.25' },
        @{ Out = $vocalsSrc; Freq = '880'; Dur = '1.9'; Vol = '0.20' }
    )
    foreach ($tj in $toneJobs) {
        $res = Invoke-NativeProcess -FilePath 'ffmpeg' -Arguments @(
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', ("sine=frequency={0}:sample_rate=48000:duration={1}" -f $tj.Freq, $tj.Dur),
            '-ac', '2', '-af', ("volume={0}" -f $tj.Vol),
            '-c:a', 'pcm_s16le', $tj.Out
        )
        Assert-True -Condition ($res.ExitCode -eq 0) -Message ("Failed generating synthetic WAV {0}: {1}" -f $tj.Out, $res.StdErr)
    }

    $vidRes = Invoke-NativeProcess -FilePath 'ffmpeg' -Arguments @(
        '-y', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'color=c=black:s=320x180:r=24:d=2',
        '-f', 'lavfi', '-i', 'sine=frequency=300:sample_rate=48000:duration=2',
        '-ac', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', $videoSrc
    )
    Assert-True -Condition ($vidRes.ExitCode -eq 0) -Message ("Failed generating synthetic video: {0}" -f $vidRes.StdErr)

    Write-Host "[2/6] Testing New-FlowMusicTrack.ps1..." -ForegroundColor Cyan
    $newScript = Join-Path -Path $ScriptsDir -ChildPath 'New-FlowMusicTrack.ps1'
    $newRes = & $newScript `
        -Slug 'test-track' `
        -Title 'Pipeline Verification Track' `
        -Genre '90s Anime Jazz-Rock' `
        -Bpm 132 `
        -Key 'C minor' `
        -Moods @('intense', 'action') `
        -Targets @('t_mp3', 't_wav', 't_ogg') `
        -Loopable `
        -MasterSourcePath $masterSrc `
        -DrumsSourcePath $drumsSrc `
        -BassSourcePath $bassSrc `
        -InstrumentsSourcePath $instSrc `
        -VocalsSourcePath $vocalsSrc `
        -VaultRoot $tempVault

    Assert-True -Condition ($newRes.Status -eq 'Created') -Message 'New-FlowMusicTrack did not return Created'
    Assert-NoUtf8Bom -Path $newRes.TrackJsonPath
    Assert-True -Condition (Test-Path -LiteralPath $newRes.PromptPath) -Message 'prompt.md missing'
    Assert-True -Condition (Test-Path -LiteralPath $newRes.LyricsPath) -Message 'lyrics.md missing'

    Write-Host "[3/6] Testing Sync-FlowMusicVault.ps1 (first sync + idempotent skip)..." -ForegroundColor Cyan
    $tempConfig = Join-Path -Path $tempRoot -ChildPath 'project-targets.json'
    $cfgObj = [ordered]@{
        version = '1.0.0'
        targets = [ordered]@{
            t_mp3 = [ordered]@{ path = (Join-Path $tempExports 't_mp3'); format = 'mp3'; bitrate = '192k'; sampleRate = 44100; targetLufs = -14.0; includeStems = $false }
            t_wav = [ordered]@{ path = (Join-Path $tempExports 't_wav'); format = 'wav'; sampleRate = 48000; targetLufs = -16.0; includeStems = $true }
            t_ogg = [ordered]@{ path = (Join-Path $tempExports 't_ogg'); format = 'ogg'; sampleRate = 48000; targetLufs = -16.0; includeStems = $true }
        }
    }
    Write-Utf8NoBomFile -Path $tempConfig -Content ($cfgObj | ConvertTo-Json -Depth 6)

    $syncScript = Join-Path -Path $ScriptsDir -ChildPath 'Sync-FlowMusicVault.ps1'
    $syncRaw1 = (& $syncScript -VaultRoot $tempVault -ConfigPath $tempConfig -SkipManifestRebuild -OutputJson) -join "`n"
    $sync1 = $syncRaw1 | ConvertFrom-Json
    Assert-True -Condition ($sync1.Status -eq 'Success') -Message 'First sync failed'
    Assert-True -Condition ($sync1.EncodedFiles -eq 11) -Message ("Expected 11 encoded files (3 masters + 8 stems), got {0}" -f $sync1.EncodedFiles)
    Assert-NoUtf8Bom -Path $sync1.CatalogPath
    Assert-True -Condition (Test-Path -LiteralPath (Join-MultiPath @($tempExports, 't_mp3', 'test-track.mp3'))) -Message 'MP3 master missing'
    Assert-True -Condition (Test-Path -LiteralPath (Join-MultiPath @($tempExports, 't_wav', 'test-track', 'stems', 'vocals.wav'))) -Message 'WAV vocals stem missing'
    Assert-NoUtf8Bom -Path (Join-MultiPath @($tempExports, 't_wav', 'test-track', 'track.json'))
    Assert-True -Condition (Test-Path -LiteralPath (Join-MultiPath @($tempExports, 't_ogg', 'test-track', 'stems', 'drums.ogg'))) -Message 'OGG drums stem missing'

    $syncRaw2 = (& $syncScript -VaultRoot $tempVault -ConfigPath $tempConfig -SkipManifestRebuild -OutputJson) -join "`n"
    $sync2 = $syncRaw2 | ConvertFrom-Json
    Assert-True -Condition ($sync2.EncodedFiles -eq 0) -Message ("Expected 0 encoded files on second run, got {0}" -f $sync2.EncodedFiles)
    Assert-True -Condition ($sync2.SkippedUpToDate -eq 11) -Message ("Expected 11 skipped files on second run, got {0}" -f $sync2.SkippedUpToDate)

    Write-Host "[4/6] Testing Invoke-DeadChannelScoreMix.ps1 (4-stem + cues.json + dialogue ducking)..." -ForegroundColor Cyan
    $mixScript = Join-Path -Path $ScriptsDir -ChildPath 'Invoke-DeadChannelScoreMix.ps1'
    $cuesFile = Join-MultiPath -Parts @($HubRoot, 'packs', 'dead-channel-13', 'cues.json')
    $scoredOut = Join-Path -Path $tempRoot -ChildPath 'scored.mp4'
    $mixRaw = (& $mixScript -InputVideo $videoSrc -TrackDir $newRes.TrackDir -OutputVideo $scoredOut -CueSheetPath $cuesFile -OutputJson) -join "`n"
    $mixRes = $mixRaw | ConvertFrom-Json
    Assert-True -Condition ($mixRes.Status -eq 'Success') -Message 'Score mix failed'
    Assert-True -Condition ($mixRes.MixMode -eq 'stems') -Message 'Expected stems mix mode'
    Assert-True -Condition ($mixRes.CueCount -eq 5) -Message 'Expected 5 cue regions'

    $scoredInfo = Get-AudioMediaInfo -Path $scoredOut
    Assert-True -Condition ($scoredInfo.HasVideo -and $scoredInfo.HasAudio) -Message 'Scored MP4 missing video or audio stream'
    Assert-True -Condition ($scoredInfo.Codec -eq 'aac') -Message ("Expected aac codec, got {0}" -f $scoredInfo.Codec)
    Assert-True -Condition ($scoredInfo.SampleRate -eq 48000) -Message ("Expected 48000 Hz, got {0}" -f $scoredInfo.SampleRate)
    Assert-True -Condition ($scoredInfo.Channels -eq 2) -Message ("Expected stereo channels, got {0}" -f $scoredInfo.Channels)
    Assert-True -Condition ([math]::Abs($scoredInfo.DurationSec - 2.0) -le 0.25) -Message ("Unexpected scored MP4 duration: {0}" -f $scoredInfo.DurationSec)

    Write-Host "[5/6] Testing Export-GameAudioStems.ps1 -Engine All (duration alignment check)..." -ForegroundColor Cyan
    $exportScript = Join-Path -Path $ScriptsDir -ChildPath 'Export-GameAudioStems.ps1'
    $gameExportDir = Join-Path -Path $tempRoot -ChildPath 'game_exports'
    $exportRaw = (& $exportScript -TrackSlug 'test-track' -VaultRoot $tempVault -Engine All -TargetDir $gameExportDir -OutputJson) -join "`n"
    $exportRes = $exportRaw | ConvertFrom-Json
    Assert-True -Condition ($exportRes.Status -eq 'Success') -Message 'Game stem export failed'
    Assert-True -Condition (@($exportRes.Exports).Count -eq 4) -Message 'Expected 4 engine exports'

    foreach ($engExp in $exportRes.Exports) {
        Assert-NoUtf8Bom -Path $engExp.ManifestPath
        foreach ($fPath in $engExp.Files) {
            $fInfo = Get-AudioMediaInfo -Path $fPath
            Assert-True -Condition ([math]::Abs($fInfo.DurationSec - 2.0) -le 0.05) -Message ("Stem alignment drift on {0}: {1}s != 2.0s" -f $fPath, $fInfo.DurationSec)
        }
    }

    Write-Host "[6/6] Testing Register-FlowMusicMcp.ps1 (mock config) and Initialize-SoundtrackPack.ps1..." -ForegroundColor Cyan
    $mockConfig = Join-Path -Path $tempRoot -ChildPath 'mock_mcp_config.json'
    $mockSeed = @{ mcpServers = @{ 'existing-server' = @{ command = 'node'; args = @('index.js') } } } | ConvertTo-Json -Depth 5
    Write-Utf8NoBomFile -Path $mockConfig -Content $mockSeed

    $regScript = Join-Path -Path $ScriptsDir -ChildPath 'Register-FlowMusicMcp.ps1'
    $regRes = & $regScript -ConfigPath $mockConfig
    Assert-True -Condition ($regRes.Status -eq 'Registered') -Message 'MCP registration failed'
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace($regRes.BackupPath) -and (Test-Path -LiteralPath $regRes.BackupPath)) -Message 'MCP config backup missing'
    Assert-NoUtf8Bom -Path $mockConfig
    $parsedMock = Get-Content -LiteralPath $mockConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True -Condition ($null -ne $parsedMock.mcpServers.'existing-server') -Message 'Existing MCP server entry was lost'
    Assert-True -Condition ($null -ne $parsedMock.mcpServers.'flow-music') -Message 'flow-music MCP server entry missing'

    $packVault = Join-Path -Path $tempRoot -ChildPath 'pack_vault'
    $null = New-Item -ItemType Directory -Path $packVault -Force
    $initPackScript = Join-Path -Path $ScriptsDir -ChildPath 'Initialize-SoundtrackPack.ps1'
    $packRaw = (& $initPackScript -PackName all -VaultRoot $packVault -OutputJson) -join "`n"
    $packRes = $packRaw | ConvertFrom-Json
    Assert-True -Condition ($packRes.Created -eq 18) -Message ("Expected 18 scaffolded tracks across 3 packs, got {0}" -f $packRes.Created)

    Write-Host "ALL FLOW MUSIC PIPELINE E2E CHECKS PASSED!" -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
