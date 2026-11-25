# Google Flow Music Brief — Example Track Title

- **Slug:** `example-track-slug`
- **BPM / Key / Meter:** 120 BPM | C minor | 4/4
- **Genre:** 90s Anime Jazz-Rock
- **Loopable:** false | **Instrumental:** false

## 1. Initial Flow Music Studio Prompt
> Describe genre, era, instrumentation, vocal delivery, groove feel, BPM, and arrangement arc.

## 2. Conversational Producer Directives (Replace / Extend / Cover)
- **Pass 1 (Groove & Low End):** Ask the producer to tighten pocket between slap bass and crisp snare ghost notes.
- **Pass 2 (Section Replace):** Target bridge or chorus energy without altering the core hook.
- **Pass 3 (Extend / Loop Tail):** Extend clean 8-bar outro or create seamless loop point before exporting stems.

## 3. Export Checklist
- [ ] Export Master (`WAV` or high-bitrate `MP3`) as `master.<ext>` in this folder
- [ ] Split & export Stems into `stems/`: `drums.<ext>`, `bass.<ext>`, `instruments.<ext>`, `vocals.<ext>`
- [ ] Update `flowSessionUrl` and `targets` in `track.json`
- [ ] Run `.\scripts\Sync-FlowMusicVault.ps1`
