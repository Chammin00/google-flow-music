# YouTube Monetization-Safe Beat Pack

Copyright-safe, Content-ID-free **Google Flow Music** tracks engineered specifically for:
- `youtube channels` (`Build-AudioManifest.ps1` -> `assets/licensed/music/flow_music` -> `audio_manifest.json`)
- `youtube shorts edit for gaming` (`Get-RemasterAudioTracks.ps1 -Category Flow_Music` | `Invoke-VideoAudioRemaster.ps1 -MusicVolumeDb -20`)

These 6 blueprints mirror the exact sonic lanes documented in `SOUNDTRACK_CURATION_GUIDE.md` and `CHANNEL_BLUEPRINT.md`, giving you authentic 90s neo-soul swing, 80s Japanese jazz fusion, city pop, and 90s anime tournament funk **without risking demonetization or copyright claims**.

## Included Tracks
1. `yt-neosoul-rhodes-swing` — Warm Fender Rhodes + unquantized boom-bap swing (`84 BPM`, `D minor`)
2. `yt-jp-jazz-fusion-midnight` — 80s Japanese jazz fusion slap bass + DX7 synth + guitar lead (`124 BPM`, `E major`)
3. `yt-citypop-summer-groove` — Breezy Stratocaster funk chop + crisp 80s city pop groove (`112 BPM`, `A major`)
4. `yt-90s-anime-tournament-funk` — 90s anime brass hits + rebellious slap bass + sax stabs (`134 BPM`, `G minor`)
5. `yt-lofi-rainy-acid-jazz` — Muffled acoustic bass + rainy night Rhodes for commentary/voiceovers (`88 BPM`, `F minor`)
6. `yt-cozy-garden-sleep-bed` — Warm looping nocturnal ambient garden bed for 1–8h sleep/study videos (`68 BPM`, `C major`)

## Quick Scaffold
```powershell
.\scripts\Initialize-SoundtrackPack.ps1 -PackName youtube-monetization-beats
```
Once exported from Flow Music into each `vault/<slug>/master.wav`, run:
```powershell
.\scripts\Sync-FlowMusicVault.ps1
```
This normalizes everything to `-14 LUFS`, exports `320k MP3` files into `youtube channels` and `exports/youtube_remaster`, and automatically rebuilds `audio_manifest.json`.
