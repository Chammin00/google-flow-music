#!/usr/bin/env python3
"""
Build-YuYuConnectedBlend.py

Transforms `yyh01-sunset-credits-suite` into a single, continuously connected
4-stem DJ blend at 124.00 BPM (natural vocals, 0 semitones):
  - Stretch FIRST -> Demucs SECOND so all 4 stems stay 0-sample phase-locked
    to `original.wav`.
  - Play pristine untouched `original.wav` during every track's vocal body,
    seamlessly weaving `drums + bass + other` across 8-bar (15.48s) DJ bridges
    with EQ bass swap, kick-locked drum morph, and zero-phase Butterworth sweeps.
  - Bookended by `Struggle of Sadness` (Opening Overture + Closing Finale).
"""

from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from demucs.pretrained import get_model
from scipy.io import wavfile

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import flow_music_dsp as _dsp

SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_BPM = 124.0
TARGET_LUFS = -14.5
TARGET_GROOVE_RMS = 0.20

BAR_SEC = (60.0 * 4.0) / TARGET_BPM   # 1.935483871s
BEAT_SEC = 60.0 / TARGET_BPM          # 0.483870968s

HUB_ROOT = Path(__file__).resolve().parent.parent
STEMS_CACHE_DIR = HUB_ROOT / "exports" / "stems_cache"

ANIME_OST_DIR = Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs")
YOUTUBE_MUSIC_DIR = Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music")

PREP_SPECS: List[Dict[str, Any]] = [
    {
        "key": "yyh_ed3_124",
        "label": "Yu Yu Hakusho ED 3 - Unbalanced Kiss (124 BPM, 0 st)",
        "path": ANIME_OST_DIR / "Yu Yu Hakusho ED 3 1080p English.mp3",
        "raw_bpm": 118.48,
        "target_bpm": 124.00,
        "prep_af": (
            f"rubberband=tempo={124.00 / 118.48:.6f}:pitch=1.0:transients=crisp:phase=laminar,"
            "highpass=f=28,highshelf=f=8000:g=1.2"
        ),
        "max_input_sec": None,
    },
    {
        "key": "yyh_ed5_124",
        "label": "Yu Yu Hakusho ED 5 - Daydream Generation (124 BPM, 0 st)",
        "path": ANIME_OST_DIR / "Yu Yu Hakusho ED 5 1080p English.mp3",
        "raw_bpm": 126.60,
        "target_bpm": 124.00,
        "prep_af": (
            f"rubberband=tempo={124.00 / 126.60:.6f}:pitch=1.0:transients=crisp:phase=laminar,"
            "highpass=f=28,highshelf=f=8000:g=1.2"
        ),
        "max_input_sec": None,
    },
    {
        "key": "yyh_ed1_124",
        "label": "Yu Yu Hakusho ED 1 - The Homework Doesnt End (124 BPM, 0 st)",
        "path": ANIME_OST_DIR / "Yu Yu Hakusho - ED 1 - Bluray 1080p - English - The Homework Doesnt End.mp3",
        "raw_bpm": 132.82,
        "target_bpm": 124.00,
        "prep_af": (
            f"rubberband=tempo={124.00 / 132.82:.6f}:pitch=1.0:transients=crisp:phase=laminar,"
            "highpass=f=28,highshelf=f=9000:g=-1.0"
        ),
        "max_input_sec": None,
    },
    {
        "key": "yyh_chill_nat",
        "label": "Yu Yu Hakusho - Struggle of Sadness (Natural 85 BPM Bookend)",
        "path": YOUTUBE_MUSIC_DIR / "yu_yu_hakusho_chill.mp3",
        "raw_bpm": 85.00,
        "target_bpm": 85.00,
        "prep_af": "highpass=f=28",
        "max_input_sec": 55.0,
    },
]


def load_module(name: str, rel_path: str) -> Any:
    mod_path = HUB_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_wav_f32(wav_path: Path) -> np.ndarray:
    """Read a stereo 48 kHz WAV file into float32 (N, 2) array."""
    sr, data = wavfile.read(str(wav_path))
    if sr != SAMPLE_RATE:
        raise ValueError(f"Expected {SAMPLE_RATE} Hz WAV, got {sr} Hz in {wav_path}")
    if data.dtype == np.int16:
        arr = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        arr = data.astype(np.float32) / 2147483648.0
    else:
        arr = data.astype(np.float32)
    if arr.ndim == 1:
        arr = np.column_stack([arr, arr])
    return arr[:, :CHANNELS].copy()


def render_prepared_original(spec: Dict[str, Any], out_wav: Path, force: bool = False) -> str:
    """Render time-stretched & tonally matched 48 kHz 16-bit stereo original.wav."""
    if not force and out_wav.is_file() and out_wav.stat().st_size > 10000:
        return "cached"
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if spec.get("max_input_sec"):
        cmd.extend(["-t", f"{float(spec['max_input_sec']):.3f}"])
    cmd.extend([
        "-i",
        str(spec["path"]),
        "-af",
        spec["prep_af"],
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg original render failed for {spec['key']}: {proc.stderr}")
    return "rendered"


def prepare_all_caches(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Pre-stretch/polish originals first, then run htdemucs once per track."""
    sep_mod = load_module("separate_track_stems", "scripts/Separate-TrackStems.py")
    shared_model = None
    prep_results: Dict[str, Dict[str, Any]] = {}

    for spec in PREP_SPECS:
        src_path: Path = spec["path"]
        if not src_path.is_file():
            raise FileNotFoundError(f"Missing source track '{spec['key']}': {src_path}")

        cache_dir = STEMS_CACHE_DIR / spec["key"]
        original_wav = cache_dir / "original.wav"
        orig_status = render_prepared_original(spec, original_wav, force=force)

        need_sep = force or not all((cache_dir / fn).is_file() for fn in sep_mod.EXPECTED_FILES)
        if need_sep and shared_model is None:
            shared_model = get_model("htdemucs")
            shared_model.cpu()
            shared_model.eval()

        sep_res = sep_mod.separate_track(
            original_wav,
            cache_dir,
            max_sec=0.0,
            force=force,
            model=shared_model,
        )
        prep_results[spec["key"]] = {
            "spec": spec,
            "cache_dir": cache_dir,
            "original_status": orig_status,
            "demucs_status": sep_res["status"],
        }
    return prep_results


def shift_array(arr: np.ndarray, lag_samples: int, target_len: int) -> np.ndarray:
    """Shift arr by lag_samples so aligned[i] = arr[i + lag_samples] clipped to target_len."""
    out = np.zeros((target_len, arr.shape[1]), dtype=np.float32)
    src_start = max(0, lag_samples)
    dst_start = max(0, -lag_samples)
    copy_len = min(len(arr) - src_start, target_len - dst_start)
    if copy_len > 0:
        out[dst_start : dst_start + copy_len] = arr[src_start : src_start + copy_len]
    return out


def compute_stem_phase_lag(orig: np.ndarray, stem_sum: np.ndarray, max_lag: int = 2000) -> Tuple[int, float, float]:
    """Find sample lag in [-max_lag, +max_lag] aligning stems to original (delegates to flow_music_dsp)."""
    return _dsp.compute_stem_phase_lag(orig, stem_sum, sample_rate=SAMPLE_RATE, max_lag=max_lag)


def align_stems_to_original(cache_dir: Path, norm_rms: float = TARGET_GROOVE_RMS) -> Dict[str, Any]:
    """Load original + 4 stems, align stems by exact cross-corr lag, and normalize identically."""
    orig = read_wav_f32(cache_dir / "original.wav")
    raw_stems = {name: read_wav_f32(cache_dir / f"{name}.wav") for name in ("drums", "bass", "other", "vocals")}

    min_len = min([len(orig)] + [len(v) for v in raw_stems.values()])
    orig = orig[:min_len]
    stem_sum = np.zeros_like(orig)
    for arr in raw_stems.values():
        stem_sum += arr[:min_len]

    lag, corr_before, corr_after = compute_stem_phase_lag(orig, stem_sum, max_lag=2000)
    aligned = {name: shift_array(arr, lag, len(orig)) for name, arr in raw_stems.items()}
    aligned["instrumental"] = aligned["drums"] + aligned["bass"] + aligned["other"]

    b0 = min(len(orig) // 4, 10 * SAMPLE_RATE)
    b1 = min(len(orig) - b0, 65 * SAMPLE_RATE)
    if b1 <= b0:
        b0, b1 = 0, len(orig)
    body_rms = float(np.sqrt(np.mean(orig[b0:b1] ** 2) + 1e-12))
    scale = norm_rms / max(0.015, body_rms)

    orig *= scale
    for k in aligned:
        aligned[k] *= scale

    return {
        "original": orig,
        "drums": aligned["drums"],
        "bass": aligned["bass"],
        "other": aligned["other"],
        "vocals": aligned["vocals"],
        "instrumental": aligned["instrumental"],
        "lag_samples": lag,
        "corr_before": corr_before,
        "corr_after": corr_after,
        "scale": round(scale, 4),
        "duration_sec": round(len(orig) / float(SAMPLE_RATE), 3),
    }


def diagnose_tracks(prep_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Inspect vocal bounds, drum profiles, and stem/original phase alignment."""
    report: Dict[str, Any] = {}
    for key, info in prep_results.items():
        st = align_stems_to_original(info["cache_dir"])
        dur = st["duration_sec"]
        n_secs = int(dur)
        voc_rms = [
            round(float(np.sqrt(np.mean(st["vocals"][s * SAMPLE_RATE : (s + 1) * SAMPLE_RATE] ** 2) + 1e-12)), 4)
            for s in range(n_secs)
        ]
        peak_v = max(voc_rms) if voc_rms else 0.0
        active_v = [s for s, val in enumerate(voc_rms) if val >= 0.15 * peak_v]
        report[key] = {
            "original_status": info["original_status"],
            "demucs_status": info["demucs_status"],
            "duration_sec": dur,
            "stem_phase_lag_samples": st["lag_samples"],
            "corr_after": st["corr_after"],
            "body_scale": st["scale"],
            "first_vocal_sec": active_v[0] if active_v else None,
            "last_vocal_sec": active_v[-1] if active_v else None,
        }
    return report


def ramp_cosine(n: int, v0: float, v1: float, power: float = 1.0) -> np.ndarray:
    """Smooth raised-cosine ramp from v0 -> v1 with optional shaping exponent."""
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    u = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    s = 0.5 * (1.0 - np.cos(math.pi * u))
    if power != 1.0:
        s = s ** float(power)
    return v0 + (v1 - v0) * s


def eq_in(n: int) -> np.ndarray:
    return _dsp.eq_in(n)


def eq_out(n: int) -> np.ndarray:
    return _dsp.eq_out(n)


def zero_phase_filter(
    src: np.ndarray,
    start_idx: int,
    end_idx: int,
    cutoff_hz: float,
    mode: str = "lowpass",
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """Zero-phase 2nd-order Butterworth filter (delegates to 5-smooth FFT padded flow_music_dsp)."""
    return _dsp.zero_phase_filter(src, start_idx, end_idx, cutoff_hz, mode=mode, sr=sr)


def apply_filter_sweep(
    chunk: np.ndarray,
    start_idx: int,
    end_idx: int,
    cutoff_hz: float,
    mode: str,
    fade_to_filtered: bool,
) -> np.ndarray:
    """Blend between dry and zero-phase filtered audio inside [start_idx:end_idx]."""
    out = chunk.copy()
    i0 = max(0, start_idx)
    i1 = min(len(out), end_idx)
    if i1 <= i0:
        return out
    filt = zero_phase_filter(out, i0, i1, cutoff_hz=cutoff_hz, mode=mode)
    w = ramp_cosine(i1 - i0, 0.0, 1.0) if fade_to_filtered else ramp_cosine(i1 - i0, 1.0, 0.0)
    out[i0:i1] = out[i0:i1] * (1.0 - w) + filt * w
    return out


def compute_onset_env(mono: np.ndarray, hop: int = 120) -> np.ndarray:
    return _dsp.compute_onset_env(mono, hop=hop)


def find_best_drum_phase_offset(
    drums_a: np.ndarray,
    a_start_sec: float,
    drums_b: np.ndarray,
    b_anchor_sec: float,
    window_bars: float = 2.0,
    bar_sec: float = BAR_SEC,
    max_shift_sec: float = 0.080,
) -> Tuple[float, float]:
    """Correlate 2.5ms-hop drum onset envelopes via vectorized flow_music_dsp kernel."""
    return _dsp.find_best_drum_phase_offset(
        drums_a,
        a_start_sec,
        drums_b,
        b_anchor_sec,
        window_bars=window_bars,
        bar_sec=bar_sec,
        max_shift_sec=max_shift_sec,
        sample_rate=SAMPLE_RATE,
    )


def extract_bar_loop(
    stem: np.ndarray,
    start_sec: float,
    loop_start_sec: float,
    loop_end_sec: float,
    needed_sec: float,
) -> np.ndarray:
    """
    Play from start_sec through loop_end_sec cleanly, then extend on exact
    bar-grid length (`loop_end_sec - loop_start_sec`) with 35ms equal-power seam
    blends (zero beat-grid drift!).
    """
    need_n = int(round(needed_sec * SAMPLE_RATE))
    out = np.zeros((need_n, CHANNELS), dtype=np.float32)

    s0 = max(0, int(round(start_sec * SAMPLE_RATE)))
    l0 = max(0, int(round(loop_start_sec * SAMPLE_RATE)))
    l1 = min(len(stem), int(round(loop_end_sec * SAMPLE_RATE)))
    period = max(SAMPLE_RATE // 2, l1 - l0)
    xf = min(int(0.035 * SAMPLE_RATE), period // 8)

    head_end = min(len(stem), l1)
    head_len = max(0, min(need_n, head_end - s0))
    if head_len > 0:
        out[:head_len] = stem[s0 : s0 + head_len]

    pos = head_len
    prev_tail_start = l1
    while pos < need_n:
        take = min(period, need_n - pos)
        out[pos : pos + take] = stem[l0 : l0 + take]

        # Smooth 35ms seam using overshoot past prev_tail_start fading into l0
        if xf > 0 and prev_tail_start + xf <= len(stem) and take >= xf:
            tail_over = stem[prev_tail_start : prev_tail_start + xf]
            out[pos : pos + xf] = tail_over * eq_out(xf) + out[pos : pos + xf] * eq_in(xf)

        pos += take
        prev_tail_start = l0 + take
    return out


def make_echo_vocal_tail(
    vocals_src: np.ndarray,
    start_sec: float,
    fade_sec: float,
    bridge_len_samples: int,
) -> np.ndarray:
    """Fade out final sung syllable + subtle 400-2800 Hz quarter/half-note dub tail."""
    out = np.zeros((bridge_len_samples, CHANNELS), dtype=np.float32)
    s0 = max(0, int(round(start_sec * SAMPLE_RATE)))
    n_fade = min(len(vocals_src) - s0, int(round(fade_sec * SAMPLE_RATE)), bridge_len_samples)
    if n_fade <= 0:
        return out

    tail = vocals_src[s0 : s0 + n_fade].copy()
    tail *= ramp_cosine(n_fade, 1.0, 0.0, power=1.15)
    out[:n_fade] += tail

    # Warm midrange echo on final 1.2s of sung phrase
    echo_win = min(n_fade, int(round(1.25 * SAMPLE_RATE)))
    echo_src = tail[-echo_win:].copy()
    # Gentle band-limit via zero-phase lowpass + highpass
    echo_bp = zero_phase_filter(echo_src, 0, len(echo_src), cutoff_hz=2600.0)
    echo_bp = zero_phase_filter(echo_bp, 0, len(echo_bp), cutoff_hz=400.0, mode="highpass")
    e_edge = min(len(echo_bp) // 4, int(0.030 * SAMPLE_RATE))
    if e_edge > 0:
        echo_bp[:e_edge] *= eq_in(e_edge)
        echo_bp[-e_edge:] *= eq_out(e_edge)

    anchor = n_fade - echo_win
    for beats_delay, gain in ((1, 0.22), (2, 0.10)):
        d_pos = anchor + int(round(beats_delay * BEAT_SEC * SAMPLE_RATE))
        d_end = min(bridge_len_samples, d_pos + len(echo_bp))
        if d_pos >= 0 and d_end > d_pos:
            out[d_pos:d_end] += echo_bp[: d_end - d_pos] * gain
    return out


def render_stem_weave_bridge(
    st_a: Dict[str, np.ndarray],
    a_bridge_start_sec: float,
    a_loop_start_sec: float,
    a_loop_end_sec: float,
    st_b: Dict[str, np.ndarray],
    other_b_curve: np.ndarray,
    drums_b_raw: np.ndarray,
    bass_b_raw: np.ndarray,
    orig_b_handoff_sec: float,
    vocal_a_fade_sec: float = 0.85,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Render an 8-bar (15.484s) connected DJ bridge:
      - Bars 0-1: Vocals A exit cleanly w/ warm dub echo; Drums A + Bass A groove.
      - Bars 1.5-4: Other B eases in low (500 Hz -> full) over Drums A + Bass A;
                    Other A ducks (1.0 -> 0.32) & warms (1400 Hz).
      - Bars 4-5: EQ Bass Swap (Bass A -> Bass B), Other A -> 0.0,
                  Drums A high-pass (320 Hz) -> 0.0 as kick-locked Drums B blooms.
      - Bars 6-7: Track A = 0.0; stems of B crossfade smoothly into pristine original_B.
    Returns (bridge_master, bridge_inst_only, orig_b_resume_sample).
    """
    bridge_bars = 8
    bridge_sec = bridge_bars * BAR_SEC
    n_bridge = int(round(bridge_sec * SAMPLE_RATE))

    b_idx = lambda bars: int(round((bars / float(bridge_bars)) * n_bridge))

    # --- Track A stems across bridge ---
    drums_a = extract_bar_loop(st_a["drums"], a_bridge_start_sec, a_loop_start_sec, a_loop_end_sec, bridge_sec)[:n_bridge]
    bass_a = extract_bar_loop(st_a["bass"], a_bridge_start_sec, a_loop_start_sec, a_loop_end_sec, bridge_sec)[:n_bridge]
    other_a = extract_bar_loop(st_a["other"], a_bridge_start_sec, a_loop_start_sec, a_loop_end_sec, bridge_sec)[:n_bridge]
    voc_a_tail = make_echo_vocal_tail(st_a["vocals"], a_bridge_start_sec, vocal_a_fade_sec, n_bridge)

    # Drums A: solid Bars 0..4, high-pass kick at 320 Hz + fade 1.0 -> 0.0 across Bars 4..6
    drums_a = apply_filter_sweep(drums_a, b_idx(4.0), b_idx(6.0), cutoff_hz=320.0, mode="highpass", fade_to_filtered=True)
    da_gain = np.ones((n_bridge, 1), dtype=np.float32)
    da_gain[b_idx(4.0) : b_idx(6.0)] = ramp_cosine(b_idx(6.0) - b_idx(4.0), 1.0, 0.0)
    da_gain[b_idx(6.0) :] = 0.0
    drums_a *= da_gain

    # Bass A: solid Bars 0..4, clean 1-bar EQ Bass Swap across Bars 4..5
    ba_gain = np.ones((n_bridge, 1), dtype=np.float32)
    ba_gain[b_idx(4.0) : b_idx(5.0)] = ramp_cosine(b_idx(5.0) - b_idx(4.0), 1.0, 0.0)
    ba_gain[b_idx(5.0) :] = 0.0
    bass_a *= ba_gain

    # Other A: duck 1.0 -> 0.32 & warm at 1400 Hz across Bars 1..4, then fade 0.32 -> 0.0 across Bars 4..6
    other_a = apply_filter_sweep(other_a, b_idx(1.0), b_idx(4.0), cutoff_hz=1400.0, mode="lowpass", fade_to_filtered=True)
    other_a[b_idx(4.0) : b_idx(6.0)] = zero_phase_filter(other_a, b_idx(4.0), b_idx(6.0), cutoff_hz=1400.0, mode="lowpass")
    oa_gain = np.ones((n_bridge, 1), dtype=np.float32)
    oa_gain[b_idx(1.0) : b_idx(4.0)] = ramp_cosine(b_idx(4.0) - b_idx(1.0), 1.0, 0.32)
    oa_gain[b_idx(4.0) : b_idx(6.0)] = ramp_cosine(b_idx(6.0) - b_idx(4.0), 0.32, 0.0)
    oa_gain[b_idx(6.0) :] = 0.0
    other_a *= oa_gain

    # --- Track B stems across bridge ---
    # Other B: enters at Bar 1.5 blooming 500 Hz -> full across Bars 1.5..6.0
    other_b = other_b_curve[:n_bridge].copy()
    o_enter, o_open = b_idx(1.5), b_idx(6.0)
    other_b = apply_filter_sweep(other_b, o_enter, o_open, cutoff_hz=500.0, mode="lowpass", fade_to_filtered=False)
    ob_gain = np.zeros((n_bridge, 1), dtype=np.float32)
    ob_gain[o_enter:o_open] = ramp_cosine(o_open - o_enter, 0.0, 1.0, power=1.35)
    ob_gain[o_open:] = 1.0
    other_b *= ob_gain

    # Bass B: swaps in cleanly on Bar 4..5
    bass_b = bass_b_raw[:n_bridge].copy()
    bb_gain = np.zeros((n_bridge, 1), dtype=np.float32)
    bb_gain[b_idx(4.0) : b_idx(5.0)] = ramp_cosine(b_idx(5.0) - b_idx(4.0), 0.0, 1.0)
    bb_gain[b_idx(5.0) :] = 1.0
    bass_b *= bb_gain

    # Drums B: kick-locked entry across Bars 4.5..6.5 w/ 450 Hz -> full bloom on first bar
    drums_b = drums_b_raw[:n_bridge].copy()
    d_enter, d_open = b_idx(4.5), b_idx(6.5)
    drums_b = apply_filter_sweep(drums_b, d_enter, b_idx(5.5), cutoff_hz=450.0, mode="lowpass", fade_to_filtered=False)
    db_gain = np.zeros((n_bridge, 1), dtype=np.float32)
    db_gain[d_enter:d_open] = ramp_cosine(d_open - d_enter, 0.0, 1.0, power=1.15)
    db_gain[d_open:] = 1.0
    drums_b *= db_gain

    mix_b_stems = other_b + bass_b + drums_b
    mix_a_inst = drums_a + bass_a + other_a

    # Across Bar 6.0..7.0, smoothly crossfade B's woven stems -> pristine phase-locked original_B!
    xf0, xf1 = b_idx(6.0), b_idx(7.0)
    orig_b_bar6_start = max(0, int(round((orig_b_handoff_sec - BAR_SEC) * SAMPLE_RATE)))
    len_b_slice = n_bridge - xf0
    orig_b_seg = st_b["original"][orig_b_bar6_start : orig_b_bar6_start + len_b_slice].copy()
    inst_b_seg = st_b["instrumental"][orig_b_bar6_start : orig_b_bar6_start + len_b_slice].copy()

    w_stems = np.ones((n_bridge, 1), dtype=np.float32)
    w_orig = np.zeros((n_bridge, 1), dtype=np.float32)
    w_stems[xf0:xf1] = ramp_cosine(xf1 - xf0, 1.0, 0.0)
    w_stems[xf1:] = 0.0
    w_orig[xf0:xf1] = ramp_cosine(xf1 - xf0, 0.0, 1.0)
    w_orig[xf1:] = 1.0

    b_master_part = mix_b_stems * w_stems
    b_master_part[xf0 : xf0 + len(orig_b_seg)] += orig_b_seg * w_orig[xf0 : xf0 + len(orig_b_seg)]

    b_inst_part = mix_b_stems * w_stems
    b_inst_part[xf0 : xf0 + len(inst_b_seg)] += inst_b_seg * w_orig[xf0 : xf0 + len(inst_b_seg)]

    bridge_inst = mix_a_inst + b_inst_part
    bridge_master = mix_a_inst + voc_a_tail + b_master_part
    orig_b_resume_sample = orig_b_bar6_start + len_b_slice
    return bridge_master, bridge_inst, orig_b_resume_sample


def assemble_connected_suite() -> Dict[str, Any]:
    engine = load_module("build_chill_tokyo_blends", "scripts/Build-ChillTokyoBlends.py")
    prep_results = prepare_all_caches(force=False)

    st_ed3 = align_stems_to_original(STEMS_CACHE_DIR / "yyh_ed3_124", norm_rms=TARGET_GROOVE_RMS)
    st_ed5 = align_stems_to_original(STEMS_CACHE_DIR / "yyh_ed5_124", norm_rms=TARGET_GROOVE_RMS)
    st_ed1 = align_stems_to_original(STEMS_CACHE_DIR / "yyh_ed1_124", norm_rms=TARGET_GROOVE_RMS)
    st_chill = align_stems_to_original(STEMS_CACHE_DIR / "yyh_chill_nat", norm_rms=0.165)

    # =========================================================================
    # SECTION 0: BOOKEND OVERTURE — Struggle of Sadness -> ED 3 Opening Downbeat
    # =========================================================================
    ov_solo_sec = 8.758
    ov_weave_sec = 4.0 * BAR_SEC  # 7.742s
    ov_handoff = int(round(0.090 * SAMPLE_RATE))
    ov_total_sec = ov_solo_sec + ov_weave_sec  # 16.500s
    ov_len = int(round(ov_total_sec * SAMPLE_RATE))

    chill_ov = (st_chill["other"] + st_chill["bass"])[:ov_len].copy()
    fi_ov = int(round(0.65 * SAMPLE_RATE))
    chill_ov[:fi_ov] *= ramp_cosine(fi_ov, 0.0, 1.0)
    ov_fade_i0 = int(round(ov_solo_sec * SAMPLE_RATE))
    chill_ov = apply_filter_sweep(chill_ov, ov_fade_i0, ov_len, cutoff_hz=1400.0, mode="lowpass", fade_to_filtered=True)
    chill_ov[ov_fade_i0:] *= ramp_cosine(ov_len - ov_fade_i0, 1.0, 0.0, power=1.15)

    # Phase-lock ED3's 4-bar groove pocket (+ 90ms overshoot tail) to ED3's opening downbeat (1.290s)
    lag0, corr0 = find_best_drum_phase_offset(
        st_ed3["drums"], 1.290, st_ed3["drums"], 72.903, window_bars=2.0
    )
    ed3_pocket_anchor = 72.903 + lag0
    ov_ext_sec = ov_weave_sec + 0.090
    ed3_ov_drums = extract_bar_loop(st_ed3["drums"], ed3_pocket_anchor, ed3_pocket_anchor, ed3_pocket_anchor + 2.0 * BAR_SEC, ov_ext_sec)
    ed3_ov_other = extract_bar_loop(st_ed3["other"], ed3_pocket_anchor, ed3_pocket_anchor, ed3_pocket_anchor + 2.0 * BAR_SEC, ov_ext_sec)
    n_ovw = int(round(ov_weave_sec * SAMPLE_RATE))
    ed3_ov_drums = apply_filter_sweep(ed3_ov_drums, 0, n_ovw, cutoff_hz=500.0, mode="lowpass", fade_to_filtered=False)
    ed3_ov_drums[:n_ovw] *= ramp_cosine(n_ovw, 0.0, 1.0, power=1.25)
    ed3_ov_other = zero_phase_filter(ed3_ov_other, 0, len(ed3_ov_other), cutoff_hz=680.0, mode="lowpass")
    ed3_ov_other[:n_ovw] *= ramp_cosine(n_ovw, 0.0, 0.45, power=1.35)
    ed3_ov_other[n_ovw:] *= 0.45

    ov_mix = np.zeros((ov_len + ov_handoff, CHANNELS), dtype=np.float32)
    ov_mix[:ov_len] += chill_ov
    ov_start_w = ov_len - n_ovw
    n_ov_ext = min(len(ed3_ov_drums), len(ov_mix) - ov_start_w)
    ov_mix[ov_start_w : ov_start_w + n_ov_ext] += (ed3_ov_drums[:n_ov_ext] + ed3_ov_other[:n_ov_ext])
    ov_mix[-ov_handoff:] *= ramp_cosine(ov_handoff, 1.0, 0.0)

    # =========================================================================
    # SECTION 1: ED 3 BODY (`1.290s -> 70.968s` = 36 bars = 69.677s)
    # =========================================================================
    ed3_body_s0 = int(round(1.290 * SAMPLE_RATE))
    ed3_body_s1 = int(round(70.968 * SAMPLE_RATE))
    ed3_body_orig = st_ed3["original"][ed3_body_s0:ed3_body_s1].copy()
    ed3_body_inst = st_ed3["instrumental"][ed3_body_s0:ed3_body_s1].copy()
    ed3_body_orig[:ov_handoff] *= ramp_cosine(ov_handoff, 0.0, 1.0)
    ed3_body_inst[:ov_handoff] *= ramp_cosine(ov_handoff, 0.0, 1.0)

    # =========================================================================
    # BRIDGE #1 (8 BARS = 15.484s): ED 3 (`70.968s`) -> ED 5 (`6.817s`)
    # =========================================================================
    lag1, corr1 = find_best_drum_phase_offset(
        st_ed3["drums"], 72.903, st_ed5["drums"], 74.560, window_bars=3.0, max_shift_sec=0.080
    )
    bridge_bars = 8
    bridge_sec = bridge_bars * BAR_SEC
    n_bridge = int(round(bridge_sec * SAMPLE_RATE))
    b_bar4 = int(round((4.0 / 8.0) * n_bridge))

    # ED 5 other_B: clean 2-bar intro tease -> straight into real intro at Bar 4.0
    ed5_i1 = 1.010 + lag1
    ed5_i3 = 4.881 + lag1
    other_b1_pre = extract_bar_loop(st_ed5["other"], ed5_i1, ed5_i1, ed5_i3, 4.0 * BAR_SEC)
    other_b1 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    other_b1[:b_bar4] = other_b1_pre[:b_bar4]
    s_i1 = max(0, int(round(ed5_i1 * SAMPLE_RATE)))
    take_ob1 = min(n_bridge - b_bar4, len(st_ed5["other"]) - s_i1)
    other_b1[b_bar4 : b_bar4 + take_ob1] = st_ed5["other"][s_i1 : s_i1 + take_ob1]

    # ED 5 drums_B & bass_B across Bars 4..7: Bar-1 locked groove pocket from 74.560 + lag1
    ed5_out_start = 74.560 + lag1
    s_o5 = max(0, int(round(ed5_out_start * SAMPLE_RATE)))
    drums_b1 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    bass_b1 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    take_b1 = min(n_bridge - b_bar4, len(st_ed5["drums"]) - s_o5)
    drums_b1[b_bar4 : b_bar4 + take_b1] = st_ed5["drums"][s_o5 : s_o5 + take_b1]
    bass_b1[b_bar4 : b_bar4 + take_b1] = st_ed5["bass"][s_o5 : s_o5 + take_b1]

    ed5_handoff_sec = 6.817 + lag1  # Bar 7 = 6.817 (1-bar pickup fill -> 8.752 vocals!)
    b1_master, b1_inst, ed5_body_s0 = render_stem_weave_bridge(
        st_a=st_ed3,
        a_bridge_start_sec=70.968,
        a_loop_start_sec=72.903,
        a_loop_end_sec=76.774,
        st_b=st_ed5,
        other_b_curve=other_b1,
        drums_b_raw=drums_b1,
        bass_b_raw=bass_b1,
        orig_b_handoff_sec=ed5_handoff_sec,
        vocal_a_fade_sec=0.85,
    )

    # =========================================================================
    # SECTION 2: ED 5 BODY (`ed5_body_s0` -> `72.625s + lag1`)
    # =========================================================================
    ed5_body_end_sec = 72.625 + lag1
    ed5_body_s1 = int(round(ed5_body_end_sec * SAMPLE_RATE))
    ed5_body_orig = st_ed5["original"][ed5_body_s0:ed5_body_s1].copy()
    ed5_body_inst = st_ed5["instrumental"][ed5_body_s0:ed5_body_s1].copy()

    # =========================================================================
    # BRIDGE #2 (8 BARS = 15.484s): ED 5 (`72.625 + lag1`) -> ED 1 (`7.169 + lag2`)
    # =========================================================================
    # Micro-lock ED 5's Bar 4..6 pocket (`76.496 + lag1`) directly against ED 1's Bar 2 (`3.298`)
    lag2, corr2 = find_best_drum_phase_offset(
        st_ed5["drums"], 76.496 + lag1, st_ed1["drums"], 3.298, window_bars=2.0, max_shift_sec=0.080
    )
    ed1_l0 = 1.363 + lag2
    ed1_l1 = 5.234 + lag2
    # At Bar 4.0, ED 1 stems start at 1.363 + lag2 -> Bar 6.0 is 5.234 + lag2 (matching orig_b_bar6_start!)
    ed1_pre4_other = extract_bar_loop(st_ed1["other"], ed1_l0, ed1_l0, ed1_l1, 4.0 * BAR_SEC)
    other_b2 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    other_b2[:b_bar4] = ed1_pre4_other[:b_bar4]
    s_ed1_bar4 = max(0, int(round(ed1_l0 * SAMPLE_RATE)))
    rem_b2 = min(n_bridge - b_bar4, len(st_ed1["other"]) - s_ed1_bar4)
    other_b2[b_bar4 : b_bar4 + rem_b2] = st_ed1["other"][s_ed1_bar4 : s_ed1_bar4 + rem_b2]

    drums_b2 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    bass_b2 = np.zeros((n_bridge, CHANNELS), dtype=np.float32)
    drums_b2[b_bar4 : b_bar4 + rem_b2] = st_ed1["drums"][s_ed1_bar4 : s_ed1_bar4 + rem_b2]
    bass_b2[b_bar4 : b_bar4 + rem_b2] = st_ed1["bass"][s_ed1_bar4 : s_ed1_bar4 + rem_b2]

    ed1_handoff_sec = 7.169 + lag2  # Bar 7 = 7.169 (Bar 6 = 5.234, Bar 8 = 9.105 vocal drop!)
    b2_master, b2_inst, ed1_body_s0 = render_stem_weave_bridge(
        st_a=st_ed5,
        a_bridge_start_sec=72.625 + lag1,
        a_loop_start_sec=76.496 + lag1,
        a_loop_end_sec=80.367 + lag1,
        st_b=st_ed1,
        other_b_curve=other_b2,
        drums_b_raw=drums_b2,
        bass_b_raw=bass_b2,
        orig_b_handoff_sec=ed1_handoff_sec,
        vocal_a_fade_sec=0.65,
    )

    # =========================================================================
    # SECTION 3: ED 1 BODY (`ed1_body_s0` -> `80.718s + lag2`)
    # =========================================================================
    ed1_body_end_sec = 80.718 + lag2
    ed1_body_s1 = int(round(ed1_body_end_sec * SAMPLE_RATE))
    ed1_body_orig = st_ed1["original"][ed1_body_s0:ed1_body_s1].copy()
    ed1_body_inst = st_ed1["instrumental"][ed1_body_s0:ed1_body_s1].copy()

    # =========================================================================
    # SECTION 4: BOOKEND FINALE — ED 1 Resolution (`80.718+lag2..88.460+lag2`)
    #            -> Struggle of Sadness Return (`0..31.0s`, 6.0s sunset fade)
    # =========================================================================
    fin_weave_sec = 4.0 * BAR_SEC  # 7.742s
    n_fin_w = int(round(fin_weave_sec * SAMPLE_RATE))
    s_ed1_fin = ed1_body_s1

    ed1_fin_inst = (st_ed1["other"][s_ed1_fin : s_ed1_fin + n_fin_w] + st_ed1["bass"][s_ed1_fin : s_ed1_fin + n_fin_w]).copy()
    ed1_fin_inst = apply_filter_sweep(ed1_fin_inst, 0, n_fin_w, cutoff_hz=1400.0, mode="lowpass", fade_to_filtered=True)
    ed1_fin_inst *= ramp_cosine(n_fin_w, 1.0, 0.0, power=1.15)

    ed1_fin_drums = st_ed1["drums"][s_ed1_fin : s_ed1_fin + n_fin_w].copy()
    ed1_fin_drums = apply_filter_sweep(ed1_fin_drums, 0, n_fin_w, cutoff_hz=900.0, mode="lowpass", fade_to_filtered=True)
    ed1_fin_drums *= ramp_cosine(n_fin_w, 1.0, 0.0, power=1.15)

    # Gentle fading vocal tail at 80.718s (`0.75s`) + subtle warm echo
    ed1_fin_voc = make_echo_vocal_tail(st_ed1["vocals"], ed1_body_end_sec, 0.75, n_fin_w)

    # Struggle of Sadness eases back in low & warm over last 5.0s of ED 1's resolution
    chill_ret_overlap = int(round(5.0 * SAMPLE_RATE))
    chill_ret_len = min(len(st_chill["other"]), int(round(31.0 * SAMPLE_RATE)))
    chill_fin = (st_chill["other"] + st_chill["bass"])[:chill_ret_len].copy()
    n_c_in = int(round(4.5 * SAMPLE_RATE))
    chill_fin = apply_filter_sweep(chill_fin, 0, n_c_in, cutoff_hz=550.0, mode="lowpass", fade_to_filtered=False)
    chill_fin[:n_c_in] *= ramp_cosine(n_c_in, 0.0, 1.0, power=1.40)

    n_c_out = int(round(6.0 * SAMPLE_RATE))
    fo_i0 = chill_ret_len - n_c_out
    chill_fin = apply_filter_sweep(chill_fin, fo_i0, chill_ret_len, cutoff_hz=1400.0, mode="lowpass", fade_to_filtered=True)
    chill_fin[fo_i0:] *= ramp_cosine(n_c_out, 1.0, 0.0, power=1.15)

    # Assemble Finale section
    fin_total = n_fin_w + chill_ret_len - chill_ret_overlap
    fin_master = np.zeros((fin_total, CHANNELS), dtype=np.float32)
    fin_inst = np.zeros((fin_total, CHANNELS), dtype=np.float32)
    fin_inst[:n_fin_w] += ed1_fin_inst + ed1_fin_drums
    fin_master[:n_fin_w] += ed1_fin_inst + ed1_fin_drums + ed1_fin_voc
    c_start = n_fin_w - chill_ret_overlap
    fin_inst[c_start : c_start + chill_ret_len] += chill_fin
    fin_master[c_start : c_start + chill_ret_len] += chill_fin

    # =========================================================================
    # CONCATENATE TIMELINE — 0-SAMPLE CONTINUOUS PHASE-LOCKED JOINS
    # =========================================================================
    pieces_master = [
        ("Overture: Struggle of Sadness -> ED 3 Drums Tease", ov_mix),
        ("YYH ED 3: Unbalanced Kiss (Original Stereo)", ed3_body_orig),
        ("8-Bar Stem-Weave Bridge #1 (ED 3 -> ED 5)", b1_master),
        ("YYH ED 5: Daydream Generation (Original Stereo)", ed5_body_orig),
        ("8-Bar Stem-Weave Bridge #2 (ED 5 -> ED 1)", b2_master),
        ("YYH ED 1: The Homework Doesn't End (Original Stereo)", ed1_body_orig),
        ("Bookend Finale: ED 1 Resolution -> Struggle of Sadness", fin_master),
    ]
    pieces_inst = [
        ("Overture", ov_mix),
        ("ED 3 Inst", ed3_body_inst),
        ("Bridge 1 Inst", b1_inst),
        ("ED 5 Inst", ed5_body_inst),
        ("Bridge 2 Inst", b2_inst),
        ("ED 1 Inst", ed1_body_inst),
        ("Finale Inst", fin_inst),
    ]

    sections_meta: List[Dict[str, Any]] = []
    cur_pos = 0
    overlaps = [0, ov_handoff, 0, 0, 0, 0, 0]  # ED 3 body overlaps Overture's 90ms tail!

    total_len = sum(len(arr) for _, arr in pieces_master) - sum(overlaps)
    timeline_master = np.zeros((total_len, CHANNELS), dtype=np.float32)
    timeline_inst = np.zeros((total_len, CHANNELS), dtype=np.float32)

    for idx, ((lbl, m_arr), (_, i_arr)) in enumerate(zip(pieces_master, pieces_inst)):
        pos = max(0, cur_pos - overlaps[idx])
        end_pos = min(total_len, pos + len(m_arr))
        take = end_pos - pos
        timeline_master[pos:end_pos] += m_arr[:take]
        timeline_inst[pos:end_pos] += i_arr[:take]
        sections_meta.append({
            "label": lbl,
            "start_sec": round(pos / float(SAMPLE_RATE), 3),
            "end_sec": round(end_pos / float(SAMPLE_RATE), 3),
        })
        cur_pos = end_pos

    timeline_master = timeline_master[:cur_pos]
    timeline_inst = timeline_inst[:cur_pos]

    # Gentle master bus glue compression (+0.83 dB linear makeup) + peak guard
    glue_af = "acompressor=threshold=-16dB:ratio=1.7:attack=25:release=180:makeup=1.1"
    glued_master = engine.apply_ffmpeg_filter_mem(timeline_master, glue_af)
    glued_inst = engine.apply_ffmpeg_filter_mem(timeline_inst, glue_af)

    raw_peak = float(np.max(np.abs(glued_master)) + 1e-9)
    if raw_peak > 0.92:
        sc_p = 0.92 / raw_peak
        glued_master *= sc_p
        glued_inst *= sc_p

    slug = "yyh01-sunset-credits-suite"
    title = "Yu Yu Hakusho Sunset Credits Suite (Connected 124 BPM 4-Stem DJ Blend)"
    genre = "90s Anime Sunset Credits Continuous 4-Stem DJ Blend"
    key_name = "D minor -> G minor -> Bb major / F minor -> G major"
    moods = ["nostalgic", "sunset", "city-pop", "anime-credits", "chill", "dj-blend"]
    cue_notes = (
        "Continuously connected 124.00 BPM 4-stem DJ blend (0 st natural vocals) bookended by Struggle of Sadness: "
        f"Overture ({sections_meta[0]['start_sec']}s-{sections_meta[0]['end_sec']}s) -> "
        f"ED 3 Body ({sections_meta[1]['start_sec']}s-{sections_meta[1]['end_sec']}s) -> "
        f"8-Bar Stem-Weave Bridge #1 ({sections_meta[2]['start_sec']}s-{sections_meta[2]['end_sec']}s) -> "
        f"ED 5 Body ({sections_meta[3]['start_sec']}s-{sections_meta[3]['end_sec']}s) -> "
        f"8-Bar Stem-Weave Bridge #2 ({sections_meta[4]['start_sec']}s-{sections_meta[4]['end_sec']}s) -> "
        f"ED 1 Body ({sections_meta[5]['start_sec']}s-{sections_meta[5]['end_sec']}s) -> "
        f"Bookend Finale ({sections_meta[6]['start_sec']}s-{sections_meta[6]['end_sec']}s)."
    )

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
        raw_i = tmp / "raw_inst.wav"
        engine.write_raw_wav(glued_master, raw_m)
        engine.write_raw_wav(glued_inst, raw_i)

        raw_lufs, raw_tp, gain_db = engine.measure_loudness(raw_m, TARGET_LUFS)
        af_master = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"

        engine.encode_mastered(raw_m, master_wav, af_master, "wav")
        engine.encode_mastered(raw_m, preview_mp3, af_master, "mp3", bitrate="320k")
        engine.encode_mastered(raw_i, inst_out, af_master, "wav")

    track_obj = {
        "slug": slug,
        "title": title,
        "artist": "Chase (@chaseham00) / Google Flow Music",
        "bpm": round(TARGET_BPM, 2),
        "key": key_name,
        "timeSignature": "4/4",
        "moods": moods,
        "genre": genre,
        "instrumental": False,
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

    flow_prompt = (
        "124 BPM sunset ending credits DJ suite transitioning smoothly from D minor / G minor through "
        "Bb major / F minor and resolving back to G major. Warm 1993 anime nostalgia with analog DX7 electric piano, "
        "driving slap bass, crisp pocket drums, soaring brass swells, and continuous beat-matched DJ stem bridges."
    )
    flow_passes = [
        "Open with a late-night emotional ballad motif and tease the 124 BPM drum groove underneath before the beat drops.",
        "Weave incoming synth chords over outgoing live drums & bass across 8-bar bridges with clean 1-bar EQ bass swaps and kick-locked drum transitions.",
        "Resolve back to the opening motif on the shared G root with warm low-passed fade-out and -14.5 LUFS glued master.",
    ]
    passes_md = "\n".join(f"- **Pass {i + 1}:** {p}" for i, p in enumerate(flow_passes))
    prompt_md = (
        f"# Google Flow Music Brief - {title}\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **BPM / Key / Meter:** {TARGET_BPM} BPM | {key_name} | 4/4\n"
        f"- **Genre:** {genre}\n"
        f"- **Moods:** {', '.join(moods)}\n"
        f"- **License Note:** Local render saved to `exports/hits/{slug}.mp3`. "
        f"Paste the prompt below into Google Flow Music to generate a 100% original, monetization-safe version.\n\n"
        f"## 1. Initial Flow Music Studio Prompt\n> {flow_prompt}\n\n"
        f"## 2. Conversational Producer Directives\n{passes_md}\n"
    )
    (vault_track_dir / "prompt.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    (vault_track_dir / "lyrics.md").write_text(
        f"# Connected 4-Stem DJ Arrangement - {title}\n\n{cue_notes}\n",
        encoding="utf-8",
        newline="\n",
    )

    # Check continuous-groove 1s min RMS inside Bridge #1 & Bridge #2
    b1_s0 = int(round(sections_meta[2]["start_sec"] * SAMPLE_RATE))
    b1_s1 = int(round(sections_meta[2]["end_sec"] * SAMPLE_RATE))
    b2_s0 = int(round(sections_meta[4]["start_sec"] * SAMPLE_RATE))
    b2_s1 = int(round(sections_meta[4]["end_sec"] * SAMPLE_RATE))

    def min_1s_rms(seg_start: int, seg_end: int) -> float:
        vals = [
            float(np.sqrt(np.mean(glued_master[p : min(seg_end, p + SAMPLE_RATE)] ** 2)))
            for p in range(seg_start, seg_end - SAMPLE_RATE + 1, SAMPLE_RATE)
        ]
        return round(min(vals), 4) if vals else 0.0

    # Vocal separation between last vocal of ED3->ED5 and ED5->ED1
    voc_sep_b1_sec = round((8.752 + lag1 - ed5_handoff_sec) + (7.0 * BAR_SEC - 0.85), 2)
    voc_sep_b2_sec = round((9.105 + lag2 - ed1_handoff_sec) + (7.0 * BAR_SEC - 0.0), 2)

    return {
        "status": "success",
        "slug": slug,
        "bpm": TARGET_BPM,
        "phase_alignment": {
            "yyh_ed3_124": {"lag_samples": st_ed3["lag_samples"], "corr_after": st_ed3["corr_after"]},
            "yyh_ed5_124": {"lag_samples": st_ed5["lag_samples"], "corr_after": st_ed5["corr_after"]},
            "yyh_ed1_124": {"lag_samples": st_ed1["lag_samples"], "corr_after": st_ed1["corr_after"]},
            "yyh_chill_nat": {"lag_samples": st_chill["lag_samples"], "corr_after": st_chill["corr_after"]},
        },
        "drum_locks": {
            "overture_ed3_pocket": {"drum_phase_lag_ms": round(lag0 * 1000.0, 2), "drum_peak_corr": corr0},
            "bridge1_ed3_to_ed5": {"drum_phase_lag_ms": round(lag1 * 1000.0, 2), "drum_peak_corr": corr1},
            "bridge2_ed5_to_ed1": {"drum_phase_lag_ms": round(lag2 * 1000.0, 2), "drum_peak_corr": corr2},
        },
        "vocal_separation_sec": {
            "bridge1_ed3_to_ed5": voc_sep_b1_sec,
            "bridge2_ed5_to_ed1": voc_sep_b2_sec,
        },
        "bridge_min_1s_rms": {
            "bridge1": min_1s_rms(b1_s0, b1_s1),
            "bridge2": min_1s_rms(b2_s0, b2_s1),
        },
        "sections": sections_meta,
        "mastering": {"raw_lufs": raw_lufs, "raw_tp_db": raw_tp, "applied_gain_db": gain_db},
        "outputs": {
            "preview_mp3": engine.verify_audio(preview_mp3),
            "master_wav": engine.verify_audio(master_wav),
            "instruments_wav": engine.verify_audio(inst_out),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build connected 4-stem Yu Yu Hakusho DJ blend.")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare 124 BPM stems and print diagnostics only.")
    parser.add_argument("--force-prep", action="store_true", help="Force re-stretch and re-separation.")
    args = parser.parse_args()

    prep_results = prepare_all_caches(force=args.force_prep)
    if args.prepare_only:
        diag = diagnose_tracks(prep_results)
        print(json.dumps({"stage": "prepare_and_diagnose", "tracks": diag}, indent=2))
        return

    res = assemble_connected_suite()
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
