#!/usr/bin/env python3
"""
Build-RomStudioYoutubeSuite.py

Creates a 3-track 3D ROM Studio & YouTube Gaming One-Beat Producer Suite where
each track is built around ONE unbroken `drums + bass` groove spine with key-
and BPM-locked melodic `other` stems (>210 Hz high-passed) weaving in and out
over the exact same pocket, circular-loop wrapped (120 ms) for infinite playback:

  1. rom01-palace-shorts-hook     (100.00 BPM, F maj,  24 bars =  57.60s) - YouTube Shorts
  2. rom02-velvet-palace-longform ( 75.00 BPM, D min,  60 bars = 192.00s) - Long-Form & Rotunda
  3. rom03-console-vault-bgm      ( 80.00 BPM, E min,  40 bars = 120.00s) - 3D ROM Vault BGM
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from demucs.pretrained import get_model

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import flow_music_dsp as _dsp

SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_LUFS = -14.5
SPINE_TARGET_RMS = 0.165
LOOP_WRAP_SEC = 0.120

HUB_ROOT = Path(__file__).resolve().parent.parent
STEMS_CACHE_DIR = HUB_ROOT / "exports" / "stems_cache"

YT_MUSIC_DIR = Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music")
JAZZ_DIR = Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB")
HI_JAZZ_DIR = Path(r"G:\My Drive\Gaming & Development\Music & Audio\Highlights_Japanese_RnB_Jazz")

# 8 new stretch-first -> Demucs-second caches (sa2_wild_canyon reuses existing cache!)
PREP_SPECS: List[Dict[str, Any]] = [
    {
        "key": "rom_sparkle_100_p1",
        "path": JAZZ_DIR / "Tatsuro Yamashita - Sparkle (Instrumental).mp3",
        "max_input_sec": 65.0,
        "prep_af": "rubberband=tempo=0.990589:pitch=1.059463:transients=crisp:phase=laminar,highpass=f=28",
    },
    {
        "key": "rom_mflo_100",
        "path": JAZZ_DIR / "m-flo - been so long (Instrumental).mp3",
        "max_input_sec": 65.0,
        "prep_af": "rubberband=tempo=1.041667:pitch=1.0:transients=crisp:phase=laminar,highpass=f=28",
    },
    {
        "key": "rom_p5_mask_75",
        "path": HI_JAZZ_DIR / "Persona 5 - Beneath the Mask Instrumental.mp3",
        "max_input_sec": 80.0,
        "prep_af": "rubberband=tempo=1.013514:pitch=1.0:transients=crisp:phase=laminar,highpass=f=28",
    },
    {
        "key": "rom_hiroshi_75",
        "path": JAZZ_DIR / "Hiroshi Suzuki - Romance.mp3",
        "max_input_sec": 80.0,
        "prep_af": "rubberband=tempo=0.999334:pitch=1.0:transients=crisp:phase=laminar,highpass=f=28",
    },
    {
        "key": "rom_dkc_aquatic_75_p2",
        "path": YT_MUSIC_DIR / "dkc_aquatic_ambiance.mp3",
        "max_input_sec": 75.0,
        "prep_af": "rubberband=tempo=0.994695:pitch=1.122462:transients=crisp:phase=laminar,highpass=f=28",
    },
    {
        "key": "rom_misia_80",
        "path": JAZZ_DIR / "MISIA - Tsutsumikomu You ni (Instrumental).mp3",
        "max_input_sec": 75.0,
        "prep_af": "highpass=f=28",
    },
    {
        "key": "rom_carrington_80",
        "path": YT_MUSIC_DIR / "perfect_dark_carrington_institute.mp3",
        "max_input_sec": 70.0,
        "prep_af": "highpass=f=28",
    },
    {
        "key": "rom_sbk_shop_80",
        "path": YT_MUSIC_DIR / "sbk_shop_theme.mp3",
        "max_input_sec": 65.0,
        "prep_af": "rubberband=tempo=1.066667:pitch=1.0:transients=crisp:phase=laminar,highpass=f=28",
    },
]

EXISTING_WILD_CANYON_MP3 = YT_MUSIC_DIR / "sonic_adventure_wild_canyon.mp3"


def load_module(name: str, rel_path: str) -> Any:
    mod_path = HUB_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prepare_rom_stems(conn: Any, force: bool = False) -> Dict[str, str]:
    """Pre-stretch/polish originals first, then run htdemucs once across all uncached tracks."""
    sep_mod = load_module("separate_track_stems", "scripts/Separate-TrackStems.py")
    wild_cache = STEMS_CACHE_DIR / "sa2_wild_canyon"
    if not all((wild_cache / fn).is_file() for fn in sep_mod.EXPECTED_FILES):
        if not EXISTING_WILD_CANYON_MP3.is_file():
            raise FileNotFoundError(f"Missing Wild Canyon source: {EXISTING_WILD_CANYON_MP3}")
        sep_mod.separate_track(EXISTING_WILD_CANYON_MP3, wild_cache, max_sec=120.0, force=False)

    statuses: Dict[str, str] = {"sa2_wild_canyon": "cached"}
    shared_model = None

    for spec in PREP_SPECS:
        src_path: Path = spec["path"]
        if not src_path.is_file():
            raise FileNotFoundError(f"Missing source track '{spec['key']}': {src_path}")

        cache_dir = STEMS_CACHE_DIR / spec["key"]
        original_wav = cache_dir / "original.wav"
        conn.render_prepared_original(spec, original_wav, force=force)

        need_sep = force or not all((cache_dir / fn).is_file() for fn in sep_mod.EXPECTED_FILES)
        if need_sep and shared_model is None:
            shared_model = get_model("htdemucs")
            shared_model.cpu()
            shared_model.eval()

        res = sep_mod.separate_track(
            original_wav,
            cache_dir,
            max_sec=0.0,
            force=force,
            model=shared_model,
        )
        statuses[spec["key"]] = res["status"]

    return statuses


def load_stem_bundle(conn: Any, cache_key: str) -> Dict[str, Any]:
    """Load drums/bass/other from cache cleanly (handles missing original.wav like sa2_wild_canyon)."""
    cache_dir = STEMS_CACHE_DIR / cache_key
    drums = conn.read_wav_f32(cache_dir / "drums.wav")
    bass = conn.read_wav_f32(cache_dir / "bass.wav")
    other = conn.read_wav_f32(cache_dir / "other.wav")
    n = min(len(drums), len(bass), len(other))
    drums, bass, other = drums[:n], bass[:n], other[:n]

    orig_path = cache_dir / "original.wav"
    lag = 0
    if orig_path.is_file():
        orig = conn.read_wav_f32(orig_path)[:n]
        vocals = conn.read_wav_f32(cache_dir / "vocals.wav")[:n]
        lag, _, _ = conn.compute_stem_phase_lag(orig, drums + bass + other + vocals, max_lag=2000)
        if lag != 0:
            drums = conn.shift_array(drums, lag, n)
            bass = conn.shift_array(bass, lag, n)
            other = conn.shift_array(other, lag, n)

    return {
        "cache_key": cache_key,
        "drums": drums,
        "bass": bass,
        "other": other,
        "duration_sec": round(n / float(SAMPLE_RATE), 3),
        "lag_samples": lag,
    }


def detect_spine_downbeat(
    drums: np.ndarray,
    bass: np.ndarray,
    bar_sec: float,
    min_start_sec: float = 0.0,
    prefer_earlier_if_close: bool = True,
) -> float:
    """Locate the cleanest Bar-1 downbeat anchor (delegates to vectorized flow_music_dsp)."""
    return _dsp.detect_spine_downbeat(
        drums,
        bass,
        bar_sec=bar_sec,
        sample_rate=SAMPLE_RATE,
        min_start_sec=min_start_sec,
        prefer_earlier_if_close=prefer_earlier_if_close,
    )


def detect_melodic_onset_sec(other_hp: np.ndarray, bar_sec: float, min_start_sec: float = 0.0) -> float:
    """For drumless ambient pads, find first bar-aligned active melodic onset."""
    dur_sec = len(other_hp) / float(SAMPLE_RATE)
    n_secs = max(1, int(dur_sec))
    rms_per_sec = [
        float(np.sqrt(np.mean(other_hp[s * SAMPLE_RATE : (s + 1) * SAMPLE_RATE] ** 2) + 1e-12))
        for s in range(n_secs)
    ]
    peak_r = max(rms_per_sec) if rms_per_sec else 0.01
    for s in range(int(min_start_sec), n_secs):
        if rms_per_sec[s] >= 0.28 * peak_r:
            # Quantize softly onto next tiny 0.05s or return clean onset
            return round(max(min_start_sec, float(s)), 3)
    return round(min_start_sec, 3)


def normalize_stem_active(stem: np.ndarray, target_rms: float, max_gain: float = 6.5) -> Tuple[np.ndarray, float]:
    """Scale stem so its active body RMS hits target_rms safely."""
    n_secs = max(1, len(stem) // SAMPLE_RATE)
    sec_rms = np.array([
        float(np.sqrt(np.mean(stem[s * SAMPLE_RATE : (s + 1) * SAMPLE_RATE] ** 2) + 1e-12))
        for s in range(n_secs)
    ])
    peak = float(np.max(sec_rms)) if len(sec_rms) else 0.02
    active = sec_rms[sec_rms >= 0.28 * peak]
    cur_rms = float(np.mean(active)) if len(active) else max(0.01, peak)
    scale = min(max_gain, target_rms / max(0.008, cur_rms))
    return (stem * scale).astype(np.float32), round(scale, 4)


def choose_loop_bars(anchor_sec: float, stem_dur_sec: float, bar_sec: float, candidates: Tuple[int, ...] = (16, 12, 8, 4)) -> int:
    """Pick the longest phrase loop length that cleanly fits inside the stem WAV."""
    avail = stem_dur_sec - anchor_sec - 0.15
    for c in candidates:
        if c * bar_sec <= avail:
            return c
    return max(2, int(avail // bar_sec))


def eval_bar_curve(n_len: int, keyframes: List[Tuple[float, float]], total_bars: float) -> np.ndarray:
    """Interpolate continuous parameter curve across bar keyframes (delegates to flow_music_dsp)."""
    return _dsp.eval_bar_curve(n_len, keyframes, total_bars)


def render_morphing_voice(
    conn: Any,
    voice_stem_hp210: np.ndarray,
    start_sec: float,
    loop_start_sec: float,
    loop_end_sec: float,
    bar_sec: float,
    ext_len: int,
    gain_keyframes: List[Tuple[float, float]],
    bright_keyframes: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Loop a high-passed (>210 Hz) melodic voice continuously on exact bar multiples
    over `ext_len`, then smoothly morph both level (`gain`) and tone (`550 Hz <->
    1600 Hz <-> full dry`) via zero-phase real-FFT bands (zero comb filtering!).
    """
    ext_bars = float(ext_len) / (bar_sec * float(SAMPLE_RATE))
    needed_sec = float(ext_len) / float(SAMPLE_RATE) + 0.05
    raw = conn.extract_bar_loop(
        voice_stem_hp210,
        start_sec=start_sec,
        loop_start_sec=loop_start_sec,
        loop_end_sec=loop_end_sec,
        needed_sec=needed_sec,
    )[:ext_len]

    lp_550 = conn.zero_phase_filter(raw, 0, ext_len, cutoff_hz=550.0, mode="lowpass")
    lp_1600 = conn.zero_phase_filter(raw, 0, ext_len, cutoff_hz=1600.0, mode="lowpass")

    bright = eval_bar_curve(ext_len, bright_keyframes, ext_bars)
    lo_u = np.clip(bright / 0.5, 0.0, 1.0)
    hi_u = np.clip((bright - 0.5) / 0.5, 0.0, 1.0)

    morphed_low = lp_550 * (1.0 - lo_u) + lp_1600 * lo_u
    morphed_full = lp_1600 * (1.0 - hi_u) + raw * hi_u
    shaped = np.where(bright <= 0.5, morphed_low, morphed_full)

    gain = eval_bar_curve(ext_len, gain_keyframes, ext_bars)
    return (shaped * gain).astype(np.float32)


def apply_circular_loop_wrap(conn: Any, audio: np.ndarray, total_samples: int, wrap_samples: int) -> np.ndarray:
    """Wrap tail overshoot onto head samples cleanly (delegates to flow_music_dsp)."""
    return _dsp.apply_circular_loop_wrap(audio, total_samples, wrap_samples)


def apply_loop_safe_ffmpeg_filter(
    chill: Any,
    conn: Any,
    audio: np.ndarray,
    af_filter: str,
    pad_samples: int = SAMPLE_RATE // 2,
) -> np.ndarray:
    """Apply FFmpeg dynamics over circular pre/post-roll and compensate lookahead latency."""
    p = min(pad_samples, len(audio) // 2)
    rolled = np.concatenate([audio[-p:], audio, audio[:p]], axis=0)
    processed = chill.apply_ffmpeg_filter_mem(rolled, af_filter)
    n_ref = min(len(rolled), len(processed))
    lag, _, _ = conn.compute_stem_phase_lag(rolled[:n_ref], processed[:n_ref], max_lag=600)
    shifted = conn.shift_array(processed, lag, len(rolled))
    return shifted[p : p + len(audio)].copy()


def build_one_beat_producer_track(
    conn: Any,
    chill: Any,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """Build one complete unbroken-spine loopable track from a declarative track spec."""
    slug: str = spec["slug"]
    title: str = spec["title"]
    bpm: float = float(spec["bpm"])
    bar_sec: float = (60.0 * 4.0) / bpm
    total_bars: int = int(spec["total_bars"])

    total_samples = int(round(total_bars * bar_sec * SAMPLE_RATE))
    wrap_samples = int(round(LOOP_WRAP_SEC * SAMPLE_RATE))
    ext_len = total_samples + wrap_samples
    ext_sec = ext_len / float(SAMPLE_RATE)

    # 1. Load & prepare unifying `drums + bass` spine
    spine_bundle = load_stem_bundle(conn, spec["spine_cache"])
    spine_anchor = detect_spine_downbeat(
        spine_bundle["drums"],
        spine_bundle["bass"],
        bar_sec=bar_sec,
        min_start_sec=float(spec.get("spine_min_start_sec", 0.0)),
    )
    spine_loop_bars = choose_loop_bars(spine_anchor, spine_bundle["duration_sec"], bar_sec, (24, 16, 12, 8))

    # Normalize drums + bass together so spine sits cleanly at SPINE_TARGET_RMS
    s0_idx = int(round(spine_anchor * SAMPLE_RATE))
    s1_idx = min(len(spine_bundle["drums"]), s0_idx + int(round(spine_loop_bars * bar_sec * SAMPLE_RATE)))
    raw_sb = spine_bundle["drums"][s0_idx:s1_idx] + spine_bundle["bass"][s0_idx:s1_idx]
    cur_sb_rms = float(np.sqrt(np.mean(raw_sb ** 2) + 1e-12)) if len(raw_sb) else SPINE_TARGET_RMS
    spine_scale = min(6.0, SPINE_TARGET_RMS / max(0.01, cur_sb_rms))

    sp_drums_scaled = (spine_bundle["drums"] * spine_scale).astype(np.float32)
    sp_bass_scaled = (spine_bundle["bass"] * spine_scale).astype(np.float32)

    drums_tl = conn.extract_bar_loop(
        sp_drums_scaled,
        start_sec=spine_anchor,
        loop_start_sec=spine_anchor,
        loop_end_sec=spine_anchor + spine_loop_bars * bar_sec,
        needed_sec=ext_sec + 0.05,
    )[:ext_len]
    bass_tl = conn.extract_bar_loop(
        sp_bass_scaled,
        start_sec=spine_anchor,
        loop_start_sec=spine_anchor,
        loop_end_sec=spine_anchor + spine_loop_bars * bar_sec,
        needed_sec=ext_sec + 0.05,
    )[:ext_len]

    # Optional Bar tension filter lift on spine drums (e.g. Bar 13 in rom01)
    for lift in spec.get("drum_lifts", []):
        l_start_bar = float(lift["start_bar"])
        l_end_bar = float(lift["end_bar"])
        fc = float(lift.get("cutoff_hz", 340.0))
        i0 = max(0, int(round(l_start_bar * bar_sec * SAMPLE_RATE)))
        i1 = min(ext_len, int(round(l_end_bar * bar_sec * SAMPLE_RATE)))
        if i1 > i0:
            hp_seg = conn.zero_phase_filter(drums_tl, i0, i1, cutoff_hz=fc, mode="highpass")
            n_seg = i1 - i0
            n_in = min(n_seg // 2, int(round(0.40 * bar_sec * SAMPLE_RATE)))
            n_rel = min(n_seg // 4, int(round(0.035 * SAMPLE_RATE)))
            w = np.ones((n_seg, 1), dtype=np.float32)
            if n_in > 0:
                w[:n_in] = conn.ramp_cosine(n_in, 0.0, 1.0)
            if n_rel > 0:
                w[-n_rel:] = conn.ramp_cosine(n_rel, 1.0, 0.0)
            drums_tl[i0:i1] = drums_tl[i0:i1] * (1.0 - w) + hp_seg * w

    spine_mix_ext = (drums_tl + bass_tl).astype(np.float32)
    melodic_mix_ext = np.zeros((ext_len, CHANNELS), dtype=np.float32)

    # 2. Prepare, phase-lock, high-pass (>210 Hz), and weave all melodic voices
    voice_reports: List[Dict[str, Any]] = []
    for v_spec in spec["voices"]:
        vb = load_stem_bundle(conn, v_spec["cache_key"])
        v_hp = conn.zero_phase_filter(vb["other"], 0, len(vb["other"]), cutoff_hz=210.0, mode="highpass")
        v_norm, v_scale = normalize_stem_active(v_hp, target_rms=float(v_spec["target_rms"]))

        if v_spec.get("phase_lock", True):
            raw_anchor = detect_spine_downbeat(
                vb["drums"],
                vb["bass"],
                bar_sec=bar_sec,
                min_start_sec=float(v_spec.get("min_start_sec", 0.0)),
            )
            align_bar = float(v_spec.get("align_bar", 0.0))
            align_tl_sample = int(round(align_bar * bar_sec * SAMPLE_RATE))
            win_bars = min(3.0, max(2.0, (len(spine_mix_ext) - align_tl_sample) / (bar_sec * SAMPLE_RATE) - 0.5))
            # Pass drums_tl starting at align_tl_sample vs vb["drums"] around raw_anchor
            lag_sec, peak_corr = conn.find_best_drum_phase_offset(
                drums_tl[align_tl_sample:],
                0.0,
                vb["drums"],
                raw_anchor,
                window_bars=win_bars,
                bar_sec=bar_sec,
                max_shift_sec=0.080,
            )
            locked_anchor = max(0.0, round(raw_anchor + lag_sec, 4))
        else:
            locked_anchor = detect_melodic_onset_sec(v_norm, bar_sec=bar_sec, min_start_sec=float(v_spec.get("min_start_sec", 0.0)))
            lag_sec, peak_corr = 0.0, None

        # Ensure `locked_anchor` lands directly on `align_bar` modulo `v_loop_bars`
        v_loop_bars = choose_loop_bars(locked_anchor, vb["duration_sec"], bar_sec, (16, 12, 8, 4))
        align_bar = float(v_spec.get("align_bar", 0.0))
        phase_offset_bars = align_bar % float(v_loop_bars)
        shift_bars_in_loop = (float(v_loop_bars) - phase_offset_bars) % float(v_loop_bars)
        loop_end_s = locked_anchor + v_loop_bars * bar_sec
        effective_start = locked_anchor + shift_bars_in_loop * bar_sec
        start_s = effective_start if effective_start < (loop_end_s - 0.1) else locked_anchor

        melodic_mix_ext += render_morphing_voice(
            conn=conn,
            voice_stem_hp210=v_norm,
            start_sec=start_s,
            loop_start_sec=locked_anchor,
            loop_end_sec=loop_end_s,
            bar_sec=bar_sec,
            ext_len=ext_len,
            gain_keyframes=v_spec["gain_keyframes"],
            bright_keyframes=v_spec["bright_keyframes"],
        )

        voice_reports.append({
            "label": v_spec["label"],
            "cache_key": v_spec["cache_key"],
            "anchor_sec": locked_anchor,
            "loop_bars": v_loop_bars,
            "scale": v_scale,
            "drum_lock_ms": round(lag_sec * 1000.0, 2) if v_spec.get("phase_lock", True) else None,
            "drum_corr": peak_corr,
        })

    # 3. Sum unbroken spine + woven melodic voices & wrap seamlessly at loop boundary (120 ms)
    raw_full = apply_circular_loop_wrap(conn, spine_mix_ext + melodic_mix_ext, total_samples, wrap_samples)
    raw_sb_wrap = apply_circular_loop_wrap(conn, spine_mix_ext, total_samples, wrap_samples)

    glue_af = "acompressor=threshold=-16dB:ratio=1.7:attack=25:release=180:makeup=1.1"
    glued_full = apply_loop_safe_ffmpeg_filter(chill, conn, raw_full, glue_af)
    glued_sb = apply_loop_safe_ffmpeg_filter(chill, conn, raw_sb_wrap, glue_af)

    raw_peak = float(np.max(np.abs(glued_full)) + 1e-9)
    if raw_peak > 0.92:
        sc_p = 0.92 / raw_peak
        glued_full *= sc_p
        glued_sb *= sc_p

    # 4. Measure -14.5 LUFS target, limit cleanly across circular wrap, & export
    vault_track_dir = chill.VAULT_DIR / slug
    stems_dir = vault_track_dir / "stems"
    vault_track_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)
    chill.HITS_DIR.mkdir(parents=True, exist_ok=True)

    master_wav = vault_track_dir / "master.wav"
    preview_mp3 = chill.HITS_DIR / f"{slug}.mp3"
    inst_out = stems_dir / "instruments.wav"
    spine_out = stems_dir / "drums_bass.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        glued_m_tmp = tmp / "glued_master.wav"
        chill.write_raw_wav(glued_full, glued_m_tmp)
        raw_lufs, raw_tp, gain_db = chill.measure_loudness(glued_m_tmp, TARGET_LUFS)

        af_master = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"
        mastered_full = apply_loop_safe_ffmpeg_filter(chill, conn, glued_full, af_master)
        mastered_sb = apply_loop_safe_ffmpeg_filter(chill, conn, glued_sb, af_master)

        # Seam continuity & unbroken groove check on final delay-compensated master
        seam_jump = round(float(np.max(np.abs(mastered_full[-1] - mastered_full[0]))), 4)
        sec_rms_vals = [
            float(np.sqrt(np.mean(mastered_full[s * SAMPLE_RATE : (s + 1) * SAMPLE_RATE] ** 2)))
            for s in range(1, max(2, int(total_samples // SAMPLE_RATE) - 1))
        ]
        min_body_1s_rms = round(min(sec_rms_vals), 4) if sec_rms_vals else 0.0

        raw_m = tmp / "raw_master.wav"
        raw_sb_wav = tmp / "raw_drums_bass.wav"
        chill.write_raw_wav(mastered_full, raw_m)
        chill.write_raw_wav(mastered_sb, raw_sb_wav)

        chill.encode_mastered(raw_m, master_wav, "anull", "wav")
        chill.encode_mastered(raw_m, preview_mp3, "anull", "mp3", bitrate="320k")
        chill.encode_mastered(raw_m, inst_out, "anull", "wav")
        chill.encode_mastered(raw_sb_wav, spine_out, "anull", "wav")

    track_obj = {
        "slug": slug,
        "title": title,
        "artist": "Chase (@chaseham00) / Google Flow Music",
        "bpm": round(bpm, 2),
        "key": spec["key"],
        "timeSignature": "4/4",
        "moods": spec["moods"],
        "genre": spec["genre"],
        "instrumental": True,
        "loopable": True,
        "licenseTier": "Personal Mashup Reference (Generate Original in Flow Music for Commercial Use)",
        "synthIdVerified": False,
        "flowSessionUrl": "",
        "targets": [],
        "masterFile": "master.wav",
        "stems": {
            "instruments": "stems/instruments.wav",
            "drums_bass": "stems/drums_bass.wav",
        },
        "cueNotes": spec["cue_notes"],
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with (vault_track_dir / "track.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(track_obj, f, indent=2)
        f.write("\n")

    passes_md = "\n".join(f"- **Pass {i + 1}:** {p}" for i, p in enumerate(spec["flow_passes"]))
    prompt_md = (
        f"# Google Flow Music Brief - {title}\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **BPM / Key / Meter:** {bpm} BPM | {spec['key']} | 4/4\n"
        f"- **Genre:** {spec['genre']}\n"
        f"- **Moods:** {', '.join(spec['moods'])}\n"
        f"- **Loopable:** True ({total_bars} bars = {round(total_samples / float(SAMPLE_RATE), 2)}s)\n"
        f"- **License Note:** Local reference master saved to `exports/hits/{slug}.mp3`. "
        f"Paste the prompt below into Google Flow Music to generate a 100% original, monetization-safe version.\n\n"
        f"## 1. Initial Flow Music Studio Prompt\n> {spec['flow_prompt']}\n\n"
        f"## 2. Conversational Producer Directives\n{passes_md}\n"
    )
    (vault_track_dir / "prompt.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    (vault_track_dir / "lyrics.md").write_text(
        f"# Arrangement & Loop Architecture - {title}\n\n{spec['cue_notes']}\n",
        encoding="utf-8",
        newline="\n",
    )

    return {
        "slug": slug,
        "title": title,
        "bpm": bpm,
        "key": spec["key"],
        "total_bars": total_bars,
        "spine": {
            "cache_key": spec["spine_cache"],
            "anchor_sec": spine_anchor,
            "loop_bars": spine_loop_bars,
            "scale": round(spine_scale, 4),
        },
        "voices": voice_reports,
        "loop_seam_max_diff": seam_jump,
        "min_body_1s_rms": min_body_1s_rms,
        "mastering": {"raw_lufs": raw_lufs, "raw_tp_db": raw_tp, "applied_gain_db": gain_db},
        "outputs": {
            "preview_mp3": chill.verify_audio(preview_mp3),
            "master_wav": chill.verify_audio(master_wav),
            "instruments_wav": chill.verify_audio(inst_out),
            "drums_bass_wav": chill.verify_audio(spine_out),
        },
    }


def get_track_specs() -> List[Dict[str, Any]]:
    return [
        # TRACK 1: YouTube Shorts (100.00 BPM, F major, 24 bars = 57.60s)
        {
            "slug": "rom01-palace-shorts-hook",
            "title": "ROM Palace Shorts Hook (Wild Canyon Beat x Tatsuro Sparkle x m-flo)",
            "bpm": 100.0,
            "total_bars": 24,
            "key": "F major",
            "genre": "90s Tokyo Funk Boom-Bap & Arcade Crate-Dig (YouTube Shorts)",
            "moods": ["upbeat", "stylish", "city-pop", "boom-bap", "shorts-hook"],
            "spine_cache": "sa2_wild_canyon",
            "spine_min_start_sec": 1.2,
            "drum_lifts": [{"start_bar": 12.0, "end_bar": 13.0, "cutoff_hz": 340.0}],
            "voices": [
                {
                    "label": "Tatsuro Yamashita - Sparkle (Funk Guitar Chop, +1 st)",
                    "cache_key": "rom_sparkle_100_p1",
                    "target_rms": 0.135,
                    "phase_lock": True,
                    "align_bar": 0.0,
                    "min_start_sec": 16.0,
                    "gain_keyframes": [(0.0, 1.0), (4.0, 1.0), (5.0, 0.45), (11.0, 0.45), (12.5, 0.0), (19.5, 0.0), (20.5, 0.85), (24.0, 1.0)],
                    "bright_keyframes": [(0.0, 1.0), (4.0, 1.0), (5.0, 0.65), (12.5, 0.45), (19.5, 0.10), (20.5, 1.0), (24.0, 1.0)],
                },
                {
                    "label": "SA2 Wild Canyon (Soulful Woodwind Flute Lead)",
                    "cache_key": "sa2_wild_canyon",
                    "target_rms": 0.130,
                    "phase_lock": True,
                    "align_bar": 4.0,
                    "min_start_sec": 1.2,
                    "gain_keyframes": [(0.0, 0.0), (3.2, 0.0), (4.5, 1.0), (11.5, 1.0), (13.0, 0.0), (19.5, 0.0), (20.5, 0.55), (23.2, 0.55), (24.0, 0.0)],
                    "bright_keyframes": [(0.0, 0.0), (3.2, 0.0), (4.5, 1.0), (11.5, 1.0), (13.0, 0.45), (19.5, 0.15), (20.5, 0.90), (24.0, 0.45)],
                },
                {
                    "label": "m-flo - Been So Long (Silky 90s Rhodes)",
                    "cache_key": "rom_mflo_100",
                    "target_rms": 0.135,
                    "phase_lock": True,
                    "align_bar": 12.0,
                    "min_start_sec": 16.0,
                    "gain_keyframes": [(0.0, 0.0), (8.0, 0.0), (10.5, 0.50), (12.0, 0.55), (13.5, 1.0), (19.0, 1.0), (20.8, 0.0), (24.0, 0.0)],
                    "bright_keyframes": [(0.0, 0.0), (8.0, 0.0), (10.5, 0.45), (13.5, 1.0), (19.0, 1.0), (20.8, 0.45), (24.0, 0.0)],
                },
            ],
            "flow_prompt": "100 BPM in F major, pure instrumental, seamlessly loopable 57.6s beat. Crisp 90s dusty boom-bap drums and thick upright bass pocket driving throughout; opens immediately with crisp Stratocaster funk guitar chops, evolves into soulful woodwind flute melody, drops into warm late-90s Tokyo Rhodes chords with a 1-bar high-pass drum lift, and wraps smoothly back to Bar 1.",
            "flow_passes": [
                "Hit immediately with the funk guitar hook at 0:00 for instant YouTube Shorts retention.",
                "Keep one unbroken drums + bass pocket from start to finish and high-pass melodic layers at 210 Hz.",
                "Export loop-seamless -14.5 LUFS stereo master plus isolated drums_bass stem.",
            ],
            "cue_notes": "Unbroken SA2 Wild Canyon drums+bass spine at 100.00 BPM (24 bars = 57.60s, circular loop): Bars 1-4 (0:00-0:09.6) Sparkle guitar hook -> Bars 5-12 (0:09.6-0:28.8) Wild Canyon flute lead w/ tucked guitar & m-flo tease -> Bar 13 (0:28.8) 1-bar drum high-pass lift -> Bars 13-20 (0:28.8-0:48.0) m-flo silky Rhodes lead -> Bars 21-24 (0:48.0-0:57.6) Sparkle + flute reprise into Bar 1 loop.",
        },
        # TRACK 2: YouTube Long-Form & Art Deco Rotunda (75.00 BPM, D min, 60 bars = 192.00s)
        {
            "slug": "rom02-velvet-palace-longform",
            "title": "Velvet Palace Rotunda (Beneath the Mask x Hiroshi Romance x DKC Aquatic)",
            "bpm": 75.0,
            "total_bars": 60,
            "key": "D minor / A minor",
            "genre": "Art Deco Rainy Acid-Jazz, 70s Trombone & Ambient Console Lounge",
            "moods": ["chill", "late-night", "rainy", "jazz-lounge", "commentary-bed"],
            "spine_cache": "rom_p5_mask_75",
            "spine_min_start_sec": 0.5,
            "drum_lifts": [],
            "voices": [
                {
                    "label": "Persona 5 - Beneath the Mask (Rainy Acid-Jazz Rhodes)",
                    "cache_key": "rom_p5_mask_75",
                    "target_rms": 0.120,
                    "phase_lock": True,
                    "align_bar": 0.0,
                    "min_start_sec": 0.5,
                    "gain_keyframes": [(0.0, 1.0), (11.5, 1.0), (13.0, 0.42), (24.0, 0.42), (25.5, 0.35), (35.5, 0.35), (37.5, 0.90), (48.0, 0.90), (50.0, 1.0), (60.0, 1.0)],
                    "bright_keyframes": [(0.0, 1.0), (11.5, 1.0), (13.0, 0.45), (24.0, 0.45), (25.5, 0.38), (35.5, 0.38), (37.5, 1.0), (60.0, 1.0)],
                },
                {
                    "label": "Hiroshi Suzuki - Romance (1975 Tokyo Midnight Trombone)",
                    "cache_key": "rom_hiroshi_75",
                    "target_rms": 0.125,
                    "phase_lock": True,
                    "align_bar": 12.0,
                    "min_start_sec": 2.0,
                    "gain_keyframes": [(0.0, 0.0), (11.0, 0.0), (13.5, 0.95), (23.0, 0.95), (25.0, 0.0), (39.5, 0.0), (41.5, 0.65), (46.5, 0.65), (48.5, 0.0), (60.0, 0.0)],
                    "bright_keyframes": [(0.0, 0.0), (11.0, 0.0), (13.5, 1.0), (23.0, 1.0), (25.0, 0.40), (39.5, 0.15), (41.5, 0.78), (46.5, 0.78), (48.5, 0.30), (60.0, 0.0)],
                },
                {
                    "label": "DKC - Aquatic Ambiance (David Wise Crystal Synth Pads, +2 st)",
                    "cache_key": "rom_dkc_aquatic_75_p2",
                    "target_rms": 0.115,
                    "phase_lock": False,
                    "align_bar": 24.0,
                    "min_start_sec": 4.0,
                    "gain_keyframes": [(0.0, 0.0), (22.5, 0.0), (25.5, 0.95), (36.0, 0.95), (38.0, 0.45), (47.0, 0.45), (49.0, 0.0), (60.0, 0.0)],
                    "bright_keyframes": [(0.0, 0.0), (22.5, 0.0), (25.5, 1.0), (36.0, 1.0), (38.0, 0.52), (47.0, 0.52), (49.0, 0.35), (60.0, 0.0)],
                },
            ],
            "flow_prompt": "75 BPM in D minor / A minor, pure instrumental, seamless 3:12 background loop. Rainy Art Deco cafe brushed drums and warm walking upright bass unbroken throughout; smooth Fender Rhodes chords yield gracefully to smoky late-night Japanese jazz trombone, dissolve into shimmering 16-bit crystal underwater pads over the same jazz rhythm section, and return warmly to Rhodes for effortless voiceover ducking.",
            "flow_passes": [
                "Keep brushed drums and upright bass steady at -14.5 LUFS with smooth midrange pocket suitable for -20 dB commentary.",
                "Morph smoothly between Rhodes, jazz trombone, and crystal ambient pads via low-pass filter blooms with zero abrupt drops.",
                "Export seamlessly loopable 60-bar master and drums_bass stem.",
            ],
            "cue_notes": "Unbroken Persona 5 brushed drums+bass spine at 75.00 BPM (60 bars = 192.00s / 3:12, circular loop): Bars 1-12 (0:00-0:38.4) P5 Rhodes -> Bars 13-24 (0:38.4-1:16.8) Hiroshi trombone solo -> Bars 25-36 (1:16.8-1:55.2) DKC Aquatic crystal pads -> Bars 37-48 (1:55.2-2:33.6) P5 Rhodes + pads + trombone callback -> Bars 49-60 (2:33.6-3:12.0) P5 home Rhodes into Bar 1 loop.",
        },
        # TRACK 3: 3D ROM Studio Console Vault BGM (80.00 BPM, E min / A min, 40 bars = 120.00s)
        {
            "slug": "rom03-console-vault-bgm",
            "title": "Console Vault Lounge (MISIA Pocket x Carrington Institute x Snowboard Kids)",
            "bpm": 80.0,
            "total_bars": 40,
            "key": "E minor / A minor",
            "genre": "Late-90s Tokyo R&B Pocket & N64 Cyber-Lounge Menu BGM",
            "moods": ["lounge", "nostalgic", "menu-bgm", "n64", "chill"],
            "spine_cache": "rom_misia_80",
            "spine_min_start_sec": 0.5,
            "drum_lifts": [],
            "voices": [
                {
                    "label": "MISIA - Tsutsumikomu You ni (1998 Tokyo R&B Electric Piano)",
                    "cache_key": "rom_misia_80",
                    "target_rms": 0.125,
                    "phase_lock": True,
                    "align_bar": 0.0,
                    "min_start_sec": 0.5,
                    "gain_keyframes": [(0.0, 1.0), (7.5, 1.0), (9.0, 0.42), (31.5, 0.42), (33.5, 1.0), (40.0, 1.0)],
                    "bright_keyframes": [(0.0, 1.0), (7.5, 1.0), (9.0, 0.45), (31.5, 0.45), (33.5, 1.0), (40.0, 1.0)],
                },
                {
                    "label": "Perfect Dark - Carrington Institute (N64 Luxury Glass Pads)",
                    "cache_key": "rom_carrington_80",
                    "target_rms": 0.115,
                    "phase_lock": True,
                    "align_bar": 8.0,
                    "min_start_sec": 2.0,
                    "gain_keyframes": [(0.0, 0.40), (7.5, 0.40), (9.5, 0.95), (19.5, 0.95), (21.0, 0.25), (32.0, 0.25), (34.0, 0.40), (40.0, 0.40)],
                    "bright_keyframes": [(0.0, 0.52), (7.5, 0.52), (9.5, 1.0), (19.5, 1.0), (21.0, 0.52), (40.0, 0.52)],
                },
                {
                    "label": "Snowboard Kids - Shop Theme (Playful N64 Groove Keys)",
                    "cache_key": "rom_sbk_shop_80",
                    "target_rms": 0.120,
                    "phase_lock": True,
                    "align_bar": 20.0,
                    "min_start_sec": 1.0,
                    "gain_keyframes": [(0.0, 0.0), (19.0, 0.0), (21.2, 0.95), (31.0, 0.95), (33.0, 0.0), (40.0, 0.0)],
                    "bright_keyframes": [(0.0, 0.0), (19.0, 0.0), (21.2, 1.0), (31.0, 1.0), (33.0, 0.42), (40.0, 0.0)],
                },
            ],
            "flow_prompt": "80 BPM in E minor / A minor, pure instrumental, seamless 2:00 architectural console vault loop. Silky 1998 Tokyo R&B sub-bass and crisp pocket drums run unbroken under glass-sheen luxury N64 lobby pads and playful retro electric piano shop keys, designed for browsing retro console collections cleanly.",
            "flow_passes": [
                "Anchor on an unhurried 80 BPM R&B pocket with subtle N64 glass pads breathing behind Bars 1-8.",
                "Feature Carrington-inspired cyber-lounge synth leads over Bars 9-20, then swap smoothly to playful console shop keys on Bars 21-32.",
                "Match Bar 40 pad level cleanly back to Bar 1 (0.40 bed) for invisible in-engine looping.",
            ],
            "cue_notes": "Unbroken MISIA 80.00 BPM R&B drums+bass spine (40 bars = 120.00s / 2:00, circular loop): Bars 1-8 (0:00-0:24) MISIA Rhodes + soft Carrington lobby pads -> Bars 9-20 (0:24-1:00) Carrington N64 synth lead -> Bars 21-32 (1:00-1:36) Snowboard Kids playful keys -> Bars 33-40 (1:36-2:00) MISIA + Carrington pads return into Bar 1 loop.",
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 3D ROM Studio & YouTube Gaming One-Beat Producer Suite.")
    parser.add_argument("--only", type=str, default=None, help="Optional single track slug to build.")
    parser.add_argument("--prepare-only", action="store_true", help="Pre-stretch and separate stems only.")
    parser.add_argument("--force-prep", action="store_true", help="Force re-stretch and re-separation.")
    args = parser.parse_args()

    only_slug = args.only.strip() if args.only else None
    conn = load_module("build_yuyu_connected_blend", "scripts/Build-YuYuConnectedBlend.py")
    chill = load_module("build_chill_tokyo_blends", "scripts/Build-ChillTokyoBlends.py")

    prep_statuses = prepare_rom_stems(conn, force=args.force_prep)
    if args.prepare_only:
        print(json.dumps({"stage": "prepare_rom_stems", "caches": prep_statuses}, indent=2))
        return

    results = []
    for spec in get_track_specs():
        if only_slug and spec["slug"] != only_slug:
            continue
        results.append(build_one_beat_producer_track(conn, chill, spec))

    if only_slug and not results:
        raise ValueError(f"Unknown --only slug '{only_slug}'")

    print(json.dumps({"status": "success", "caches": prep_statuses, "tracks": results}, indent=2))


if __name__ == "__main__":
    main()
