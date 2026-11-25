# Google Flow Music — Central Soundtrack, Stem & Cross-Project Integration Hub

Unified audio vault, mastering/loudness normalizer, adaptive game stem exporter, video score mixer, and MCP bridge powering all creative, gaming, YouTube, and web app projects in `G:\My Drive\Antigravity\Projects`.

## Architecture Overview

```text
Google Flow-music/
├── config/
│   └── project-targets.json        # 12 configured export targets (YouTube, Movies, UE5, Unity, Godot, Web)
├── vault/
│   ├── _template/                  # Canonical track.json, prompt.md, lyrics.md, stems/ template
│   ├── catalog.json                # Auto-generated searchable vault catalog
│   └── <track-slug>/               # One folder per Flow Music song (master.* + stems/{drums,bass,instruments,vocals}.*)
├── packs/
│   ├── dead-channel-13/            # 6 anime OP/ED/cue/character briefs + shots.json cues.json timeline
│   ├── youtube-monetization-beats/ # 6 Content-ID-safe 90s neo-soul, JP jazz fusion, city pop & sleep beds
│   └── game-studio-ost/            # 6 adaptive 4-stem game & web app soundtracks
├── game-audio/templates/
│   ├── godot/                      # AdaptiveFlowMusicPlayer.gd (AudioStreamSynchronized)
│   ├── unity/                      # AdaptiveFlowMusicController.cs (AudioSettings.dspTime)
│   ├── unreal/                     # import_flow_music_stems.py (UE5 AssetImportTask)
│   └── web/                        # flow-music-web-engine.js (Web Audio API)
├── scripts/
│   ├── FlowMusicCommon.psm1        # Shared PS 5.1 FFmpeg/FFprobe, UTF-8 no-BOM & loudness helpers
│   ├── New-FlowMusicTrack.ps1      # Scaffold a new vault track workspace
│   ├── Initialize-SoundtrackPack.ps1 # Scaffold an entire soundtrack pack into vault/
│   ├── Sync-FlowMusicVault.ps1     # Normalize, convert, sync to target projects & rebuild manifests
│   ├── Invoke-DeadChannelScoreMix.ps1 # Dialogue-ducked 4-stem video score mixer
│   ├── Export-GameAudioStems.ps1   # Duration-aligned stem + adaptive_manifest.json exporter
│   └── Register-FlowMusicMcp.ps1   # Opt-in installer for flow-music MCP in ~/.gemini/config/mcp_config.json
└── tests/
    └── Test-FlowMusicPipeline.ps1  # End-to-end automated FFmpeg + vault + pack + MCP registration suite
```

## Quickstart Workflow

### 1. Scaffold Soundtrack Packs (or Create a Custom Track)
```powershell
Set-Location "G:\My Drive\Antigravity\Projects\Google Flow-music"

# Initialize all 18 pre-written Flow Music briefs & lyrics across Dead Channel 13, YouTube, and Game Studio:
.\scripts\Initialize-SoundtrackPack.ps1 -PackName all

# Or create a custom track:
.\scripts\New-FlowMusicTrack.ps1 -Slug "my-new-beat" -Title "My New Beat" -Bpm 124 -Key "E minor" -Instrumental -Loopable
```

### 2. Add Your Google Flow Music Exports & Sync Everywhere
Drop your downloaded `master.wav` (or `.mp3`) and split stems (`stems/drums.wav`, `stems/bass.wav`, `stems/instruments.wav`, `stems/vocals.wav`) into `vault/<track-slug>/`, then run:
```powershell
.\scripts\Sync-FlowMusicVault.ps1
```
What `Sync-FlowMusicVault.ps1` does automatically:
- Measures the integrated loudness of `master` once per target LUFS (`-14` for YouTube, `-16` for Movies/Games, `-18` for Planetarium/AAC), then applies the **exact same gain offset + limiter** across `master` and every stem so stem mix balance stays intact.
- Exports format-matched files (`mp3` 320k/256k/192k, `wav` 44.1/48 kHz, `ogg` 44.1/48 kHz) to every target project listed in `track.json`.
- Rebuilds `vault/catalog.json` and automatically triggers `Build-AudioManifest.ps1` in `youtube channels` whenever YouTube tracks change.

### 3. Mix *DEAD CHANNEL 13* Dialogue-Ducked Scores
```powershell
.\scripts\Invoke-DeadChannelScoreMix.ps1 `
    -InputVideo "..\Google Flow- Movies\dead-channel-13\DEAD_CHANNEL_13_EN_DUB.mp4" `
    -TrackDir ".\vault\dc13-cue-zero-beat-protocol" `
    -CueSheetPath ".\packs\dead-channel-13\cues.json"
```

### 4. Export Sample-Accurate Adaptive Game Stems
```powershell
.\scripts\Export-GameAudioStems.ps1 -TrackSlug "game-shattered-pagoda-duel" -Engine Godot
```
Drop the matching script from `game-audio/templates/` into Godot 4, Unity 6, UE5, or your Web app to crossfade seamlessly between `exploration`, `tension`, `combat`, and `climax` states.

### 5. Opt-In MCP Server Activation
Register the `flow-music` FastMCP server (`G:\My Drive\Antigravity\Projects\MCP\flow-music-mcp`) in your Antigravity config when ready:
```powershell
.\scripts\Register-FlowMusicMcp.ps1
```
