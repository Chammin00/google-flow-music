#!/usr/bin/env python3
"""
Build-YuYuSunsetBlends.py

Produces 2 Yu Yu Hakusho Sunset & Midnight Blends:
  1. yyh01-sunset-credits-suite  (Natural Pitch & Tempo — Full Ending Credits Suite
                                  with smooth fade-outs & warm low ease-in transitions)
  2. yyh02-spirit-detective-chill (82.00 BPM, G major / C major — Midnight Chill)
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Optional

import numpy as np

HUB_ROOT = Path(__file__).resolve().parent.parent

SOURCES: Dict[str, Path] = {
    "yyh_ed3": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Yu Yu Hakusho ED 3 1080p English.mp3"),
    "yyh_ed5": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Yu Yu Hakusho ED 5 1080p English.mp3"),
    "yyh_ed1": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Yu Yu Hakusho - ED 1 - Bluray 1080p - English - The Homework Doesnt End.mp3"),
    "yyh_chill": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\yu_yu_hakusho_chill.mp3"),
    "misia_inst": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\MISIA - Tsutsumikomu You ni (Instrumental).mp3"),
    "zelda_chill": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\zelda_fairy_fountain_chill.mp3"),
}


def load_chill_engine() -> Any:
    mod_path = HUB_ROOT / "scripts" / "Build-ChillTokyoBlends.py"
    spec = importlib.util.spec_from_file_location("build_chill_tokyo_blends", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load chill engine: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def zero_phase_lowpass(
    src: np.ndarray,
    start_idx: int,
    end_idx: int,
    cutoff_hz: float,
    sr: int = 48000,
) -> np.ndarray:
    """Apply a zero-phase 2nd-order Butterworth low-pass filter to src[start_idx:end_idx]."""
    n_seg = max(0, end_idx - start_idx)
    if n_seg == 0:
        return np.zeros((0, src.shape[1]), dtype=np.float32)

    pad = sr // 2
    ctx_start = max(0, start_idx - pad)
    ctx_end = min(len(src), end_idx + pad)
    core = src[ctx_start:ctx_end].astype(np.float32, copy=False)

    left_pad = pad - (start_idx - ctx_start)
    right_pad = pad - (ctx_end - end_idx)
    if left_pad > 0 or right_pad > 0:
        buf = np.pad(core, ((left_pad, right_pad), (0, 0)), mode="constant")
    else:
        buf = core

    freqs = np.fft.rfftfreq(len(buf), d=1.0 / float(sr))
    mag = (1.0 / np.sqrt(1.0 + (freqs / float(cutoff_hz)) ** 4)).astype(np.float32)[:, None]
    spec = np.fft.rfft(buf, axis=0)
    filtered = np.fft.irfft(spec * mag, n=len(buf), axis=0).astype(np.float32)
    return filtered[pad : pad + n_seg].copy()


def build_smooth_credits_suite(
    engine: Any,
    slug: str,
    title: str,
    genre: str,
    key_name: str,
    bpm: float,
    moods: List[str],
    tracks_spec: List[Dict[str, Any]],
    flow_prompt: str,
    flow_passes: List[str],
    cue_notes: str,
    is_instrumental: bool = False,
) -> Dict[str, Any]:
    """Assemble full natural-pitch tracks with smooth fade-outs and low warm ease-ins."""
    sr = engine.SAMPLE_RATE
    ch = engine.CHANNELS
    prepared: List[Dict[str, Any]] = []
    prev_tl_end_sec = 0.0

    for idx, ts in enumerate(tracks_spec):
        raw = engine.decode_f32(ts["path"], af_filter="highpass=f=28", max_decode_sec=145.0)
        s_start = max(0, int(round(float(ts["src_start"]) * sr)))
        s_end = min(len(raw), int(round(float(ts["src_end"]) * sr)))
        seg = raw[s_start:s_end].copy()
        if len(seg) < int(10.0 * sr):
            raise RuntimeError(f"Segment '{ts['label']}' too short after slice: {len(seg) / sr:.2f}s")

        # Normalize body RMS so quieter vintage masters (ED 3/ED 5) match ED 1 & Struggle of Sadness.
        b0 = int(round(8.0 * sr))
        b1 = min(len(seg) - int(round(8.0 * sr)), int(round(68.0 * sr)))
        if b1 <= b0:
            b0 = 0
            b1 = len(seg)
        body_rms = float(np.sqrt(np.mean(seg[b0:b1] ** 2) + 1e-12))
        scale = float(engine.TARGET_GROOVE_RMS) / max(0.015, body_rms)
        seg *= scale

        # Shape incoming ease-in before adding onto timeline.
        n_fi = min(len(seg) // 2, int(round(float(ts["fade_in_sec"]) * sr)))
        if n_fi > 0:
            u_in = np.linspace(0.0, 1.0, n_fi, dtype=np.float32)[:, None]
            if idx == 0:
                seg[:n_fi] *= 0.5 * (1.0 - np.cos(math.pi * u_in))
            else:
                warm_in = zero_phase_lowpass(seg, 0, n_fi, cutoff_hz=550.0, sr=sr)
                w_tone = 0.5 * (1.0 - np.cos(math.pi * u_in))
                seg[:n_fi] = warm_in * (1.0 - w_tone) + seg[:n_fi] * w_tone
                g_in = (0.5 * (1.0 - np.cos(math.pi * u_in))) ** 1.45
                seg[:n_fi] *= g_in

        # Shape smooth warm fade-out tail so every track exits without abrupt cuts.
        n_fo = min(len(seg) // 2, int(round(float(ts["fade_out_sec"]) * sr)))
        if n_fo > 0:
            fo_start = len(seg) - n_fo
            warm_out = zero_phase_lowpass(seg, fo_start, len(seg), cutoff_hz=1400.0, sr=sr)
            u_out = np.linspace(0.0, 1.0, n_fo, dtype=np.float32)[:, None]
            w_out = 0.5 * (1.0 - np.cos(math.pi * u_out))
            seg[fo_start:] = seg[fo_start:] * (1.0 - w_out) + warm_out * w_out
            g_out = (0.5 * (1.0 + np.cos(math.pi * u_out))) ** 1.15
            seg[fo_start:] *= g_out

        overlap_sec = 0.0 if idx == 0 else float(ts.get("overlap_sec", 0.0))
        tl_start_sec = 0.0 if idx == 0 else max(0.0, prev_tl_end_sec - overlap_sec)
        tl_end_sec = tl_start_sec + (len(seg) / float(sr))
        prev_tl_end_sec = tl_end_sec

        prepared.append({
            "label": ts["label"],
            "seg": seg,
            "tl_start_sec": tl_start_sec,
            "tl_end_sec": tl_end_sec,
            "body_rms_pre": round(body_rms, 4),
            "scale": round(scale, 4),
        })

    total_samples = max(int(round(p["tl_end_sec"] * sr)) + 1 for p in prepared)
    timeline = np.zeros((total_samples, ch), dtype=np.float32)
    sections = []
    for p in prepared:
        i0 = int(round(p["tl_start_sec"] * sr))
        seg = p["seg"]
        i1 = min(total_samples, i0 + len(seg))
        if i1 > i0:
            timeline[i0:i1] += seg[: i1 - i0]
        sections.append({
            "label": p["label"],
            "start_sec": round(p["tl_start_sec"], 3),
            "end_sec": round(p["tl_end_sec"], 3),
            "body_rms_pre": p["body_rms_pre"],
            "scale": p["scale"],
        })

    raw_peak = float(np.max(np.abs(timeline)) + 1e-9)
    if raw_peak > 0.92:
        timeline *= 0.92 / raw_peak

    vault_track_dir = engine.VAULT_DIR / slug
    stems_dir = vault_track_dir / "stems"
    vault_track_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)
    engine.HITS_DIR.mkdir(parents=True, exist_ok=True)

    master_wav = vault_track_dir / "master.wav"
    preview_mp3 = engine.HITS_DIR / f"{slug}.mp3"
    inst_out = stems_dir / "instruments.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_m = tmp / "raw_master.wav"
        engine.write_raw_wav(timeline, raw_m)

        raw_lufs, raw_tp, gain_db = engine.measure_loudness(raw_m, engine.TARGET_LUFS)
        af_master = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"

        engine.encode_mastered(raw_m, master_wav, af_master, "wav")
        engine.encode_mastered(raw_m, preview_mp3, af_master, "mp3", bitrate="320k")
        engine.encode_mastered(raw_m, inst_out, af_master, "wav")

    track_obj = {
        "slug": slug,
        "title": title,
        "artist": "Chase (@chaseham00) / Google Flow Music",
        "bpm": round(bpm, 2),
        "key": key_name,
        "timeSignature": "4/4",
        "moods": moods,
        "genre": genre,
        "instrumental": bool(is_instrumental),
        "loopable": False,
        "licenseTier": "Personal Mashup Reference (Generate Original in Flow Music for Commercial Use)",
        "synthIdVerified": False,
        "flowSessionUrl": "",
        "targets": [],
        "masterFile": "master.wav",
        "stems": {"instruments": "stems/instruments.wav"},
        "cueNotes": cue_notes,
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with (vault_track_dir / "track.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(track_obj, f, indent=2)
        f.write("\n")

    passes_md = "\n".join(f"- **Pass {i + 1}:** {p}" for i, p in enumerate(flow_passes))
    prompt_md = (
        f"# Google Flow Music Brief - {title}\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **BPM / Key / Meter:** {bpm} BPM | {key_name} | 4/4\n"
        f"- **Genre:** {genre}\n"
        f"- **Moods:** {', '.join(moods)}\n"
        f"- **License Note:** Local render saved to `exports/hits/{slug}.mp3`. "
        f"Paste the prompt below into Google Flow Music to generate a 100% original, monetization-safe version.\n\n"
        f"## 1. Initial Flow Music Studio Prompt\n> {flow_prompt}\n\n"
        f"## 2. Conversational Producer Directives\n{passes_md}\n"
    )
    (vault_track_dir / "prompt.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    (vault_track_dir / "lyrics.md").write_text(
        f"# Arrangement & Transition Reference - {title}\n\n{cue_notes}\n",
        encoding="utf-8",
        newline="\n",
    )

    outputs: Dict[str, Any] = {
        "preview_mp3": engine.verify_audio(preview_mp3),
        "master_wav": engine.verify_audio(master_wav),
        "instruments_wav": engine.verify_audio(inst_out),
    }

    return {
        "slug": slug,
        "title": title,
        "bpm": bpm,
        "key": key_name,
        "sections": sections,
        "mastering": {"raw_lufs": raw_lufs, "raw_tp_db": raw_tp, "applied_gain_db": gain_db},
        "outputs": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Yu Yu Hakusho Sunset & Midnight Blends.")
    parser.add_argument("--only", type=str, default=None, help="Optional single track slug to build.")
    args = parser.parse_args()
    only_slug = args.only.strip() if args.only else None

    for key, p in SOURCES.items():
        if not p.is_file():
            raise FileNotFoundError(f"Missing source track '{key}': {p}")

    engine = load_chill_engine()
    results = []

    # Blend 1: Pure Yu Yu Hakusho Ending Credits Sunset Suite (Natural Pitch & Tempo)
    if only_slug in (None, "yyh01-sunset-credits-suite"):
        results.append(
            build_smooth_credits_suite(
                engine=engine,
                slug="yyh01-sunset-credits-suite",
                title="Yu Yu Hakusho Sunset Credits Suite (ED 3 -> ED 5 -> ED 1 -> Struggle of Sadness)",
                genre="90s Anime Sunset Ending Credits & Warm City-Pop Nostalgia",
                key_name="D minor / Eb major / C major",
                bpm=120.0,
                moods=["nostalgic", "sunset", "city-pop", "anime-credits", "chill"],
                tracks_spec=[
                    {
                        "label": "Yu Yu Hakusho ED 3 - Unbalanced Kiss (Full Ending Credits)",
                        "path": SOURCES["yyh_ed3"],
                        "src_start": 1.05,
                        "src_end": 83.40,
                        "fade_in_sec": 0.35,
                        "fade_out_sec": 6.0,
                        "overlap_sec": 0.0,
                    },
                    {
                        "label": "Yu Yu Hakusho ED 5 - Daydream Generation (Full Ending Credits)",
                        "path": SOURCES["yyh_ed5"],
                        "src_start": 0.90,
                        "src_end": 84.40,
                        "fade_in_sec": 5.5,
                        "fade_out_sec": 6.0,
                        "overlap_sec": 2.2,
                    },
                    {
                        "label": "Yu Yu Hakusho ED 1 - The Homework Doesn't End (Full Ending Credits)",
                        "path": SOURCES["yyh_ed1"],
                        "src_start": 1.08,
                        "src_end": 83.20,
                        "fade_in_sec": 5.5,
                        "fade_out_sec": 6.5,
                        "overlap_sec": 2.2,
                    },
                    {
                        "label": "Yu Yu Hakusho - Struggle of Sadness (Sunset Credits Epilogue)",
                        "path": SOURCES["yyh_chill"],
                        "src_start": 0.15,
                        "src_end": 42.15,
                        "fade_in_sec": 5.5,
                        "fade_out_sec": 6.5,
                        "overlap_sec": 2.2,
                    },
                ],
                flow_prompt="120 BPM sunset credits suite moving across D minor, Eb major, and C major. Warm 1993 anime ending credits nostalgia with analog DX7 electric piano, soulful bassline, emotional brass swells, and gentle chill sunset chords.",
                flow_passes=[
                    "Keep original natural keys and let each full ending credits theme breathe from intro to natural resolution.",
                    "Fade out each ending theme smoothly over 6 seconds with gentle warmth roll-off, easing the next track in softly underneath at low volume before blooming open.",
                    "Export mastered stereo wav and preview mp3 at -14.5 LUFS.",
                ],
                cue_notes="Pure Yu Yu Hakusho Sunset Credits Suite (natural pitch & tempo): ED 3 Unbalanced Kiss (0:00.0-1:22.4, 6.0s fade-out) -> ED 5 Daydream Generation (1:20.2-2:43.7, 5.5s warm low ease-in, 6.0s fade-out) -> ED 1 The Homework Doesn't End (2:41.5-4:03.6, 5.5s warm low ease-in, 6.5s fade-out) -> Struggle of Sadness Epilogue (4:01.4-4:43.4, 5.5s warm low ease-in, 6.5s fade-out).",
                is_instrumental=False,
            )
        )

    # Blend 2: Spirit Detective Midnight Chill (82.00 BPM, G major / C major, Pure Instrumental)
    if only_slug in (None, "yyh02-spirit-detective-chill"):
        results.append(
            engine.build_chill_track(
                slug="yyh02-spirit-detective-chill",
                title="Spirit Detective Midnight Chill (Struggle of Sadness x MISIA x Zelda Chill)",
                genre="Late-Night 90s Anime Ballad & Tokyo R&B Instrumental",
                key_name="G major",
                target_bpm=82.0,
                moods=["chill", "late-night", "emotional", "rnb", "instrumental"],
                beats_spec=[
                    {
                        "label": "Yu Yu Hakusho - Struggle of Sadness (Opener)",
                        "path": SOURCES["yyh_chill"],
                        "raw_bpm": 85.05,
                        "pitch_st": 0,
                        "bars": 12,
                        "search_start": 0.00,
                        "search_end": 4.00,
                    },
                    {
                        "label": "MISIA - Tsutsumikomu You ni (1998 Tokyo R&B Instrumental)",
                        "path": SOURCES["misia_inst"],
                        "raw_bpm": 80.00,
                        "pitch_st": 0,
                        "bars": 12,
                        "search_start": 4.00,
                        "search_end": 10.00,
                    },
                    {
                        "label": "Zelda - Fairy Fountain Chill (Dreamy Turnaround)",
                        "path": SOURCES["zelda_chill"],
                        "raw_bpm": 78.00,
                        "pitch_st": 0,
                        "bars": 8,
                        "search_start": 11.00,
                        "search_end": 18.00,
                    },
                    {
                        "label": "Yu Yu Hakusho - Struggle of Sadness (Closing Reprise)",
                        "path": SOURCES["yyh_chill"],
                        "raw_bpm": 85.05,
                        "pitch_st": 0,
                        "bars": 8,
                        "search_start": 20.00,
                        "search_end": 28.00,
                    },
                ],
                flow_prompt="82 BPM in G major / C major, pure instrumental. Nostalgic 90s anime late-night synth-sax ballad melting into warm 1998 Tokyo R&B electric piano chords, deep soulful bass, and gentle chill hop percussion.",
                flow_passes=[
                    "Keep the emotional analog pads warm and unhurried while feathering bass transitions across every 8-12 bar phrase.",
                    "Return cleanly to the opening synth-ballad motif for the closing 8 bars with a 3s fade-out.",
                    "Export clean loopable master and instruments stem.",
                ],
                cue_notes="Pure instrumental 40-bar midnight chill journey at 82 BPM: YYH Struggle of Sadness (12 bars) -> MISIA Inst (12 bars) -> Zelda Fairy Chill (8 bars) -> YYH Reprise (8 bars).",
                vocal_spec=None,
                is_instrumental=True,
            )
        )

    print(json.dumps({"status": "success", "blends": results}, indent=2))


if __name__ == "__main__":
    main()
