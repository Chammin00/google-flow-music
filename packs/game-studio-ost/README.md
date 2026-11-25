# Game Studio & Interactive Web Apps Adaptive OST Pack

6 adaptive 4-stem soundtrack blueprints mapped directly to your active game engines and web apps:
- **UE5 (`shadow_blade_ue5`):** `game-shadow-blade-dojo` (`48 kHz WAV`, 4 stems)
- **Unity 6 (`paper_mario_unity`):** `game-paper-ronin-expedition` (`44.1 kHz WAV`, 4 stems)
- **Godot 4 (`chess_clash_godot`):** `game-chess-clash-tactical` (`48 kHz OGG`, 4 stems)
- **Godot 4 (`shattered_pagoda_godot`):** `game-shattered-pagoda-duel` (`48 kHz OGG`, 4 stems)
- **Godot 4 & Web (`turbo_type_godot`, `first_grade_learning`):** `game-turbo-type-rally` (`48 kHz OGG` / `192k MP3`, 4 stems)
- **WebGL & AAC (`my_planetarium`, `aac`):** `app-planetarium-cosmic-drift` (`44.1 kHz OGG` / `192k MP3`)

## How Vertical Remixing Works With Flow Music Stems
Each track is prompted for clean **4-stem separation** (`instruments`, `bass`, `drums`, `vocals`) on a strict steady BPM grid with loopable phrasing:
- **Exploration / Menu:** `instruments` + light `bass`
- **Tension / Combo Start:** `instruments` + `bass` + subtle `drums`
- **Combat / High Streak:** All `instruments` + `bass` + `drums` at full energy
- **Climax / Finisher:** All 4 stems including `vocals` / choir / lead hooks

Export engine-ready sample-accurate loops anytime via:
```powershell
.\scripts\Export-GameAudioStems.ps1 -TrackSlug game-shattered-pagoda-duel -Engine Godot
```
