#!/usr/bin/env python3
"""
Build-ChillTokyoBlends.py

Produces 3 ultra-smooth, late-night Tokyo Chill Blends (75-98 BPM) with silky
chill_melt transitions (2-bar warm feathering, 90ms equal-power downbeat handoff,
and band-limited 320-2400 Hz quarter-note tails):

  1. chill01-champloo-canyon-pure  (98.00 BPM, F major)   — Pure Instrumental Beat
  2. chill02-midnight-tokyo-rain   (75.00 BPM, G minor)   — Pure Instrumental Rainy Jazz Lounge
  3. chill03-shiki-no-midnight     (92.50 BPM, Bb minor)  — Zero-Gate Silky Vocal Chill Blend
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_LUFS = -14.5
TARGET_GROOVE_RMS = 0.20
TARGET_VOCAL_RMS = 0.175

HUB_ROOT = Path(__file__).resolve().parent.parent
STEMS_CACHE_DIR = HUB_ROOT / "exports" / "stems_cache"
HITS_DIR = HUB_ROOT / "exports" / "hits"
VAULT_DIR = HUB_ROOT / "vault"

SOURCES: Dict[str, Path] = {
    "mflo_been_so_long": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\m-flo - been so long (Instrumental).mp3"),
    "sa2_wild_canyon": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\sonic_adventure_wild_canyon.mp3"),
    "utada_automatic": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\Hikaru Utada - Automatic (Instrumental).mp3"),
    "nujabes_aruarian": Path(r"G:\My Drive\Gaming & Development\Music & Audio\Highlights_Japanese_RnB_Jazz\Nujabes - Aruarian Dance Instrumental.mp3"),
    "p5_beneath_mask": Path(r"G:\My Drive\Gaming & Development\Music & Audio\Highlights_Japanese_RnB_Jazz\Persona 5 - Beneath the Mask Instrumental.mp3"),
    "hiroshi_romance": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\Hiroshi Suzuki - Romance.mp3"),
    "zelda_fairy_chill": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\zelda_fairy_fountain_chill.mp3"),
    "sonic3_azure_lake": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\sonic3_azure_lake.mp3"),
    "champloo_shiki_no_uta": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Samurai Champloo Ending Theme Shiki No Uta.mp3"),
    "misia_inst": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\MISIA - Tsutsumikomu You ni (Instrumental).mp3"),
    "space_lion": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Cowboy Bebop OST 1 - Space Lion.mp3"),
}


def load_separator_module() -> Any:
    sep_path = HUB_ROOT / "scripts" / "Separate-TrackStems.py"
    spec = importlib.util.spec_from_file_location("separate_track_stems", sep_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load separator script: {sep_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decode_f32(path: Path, af_filter: str, max_decode_sec: float = 140.0) -> np.ndarray:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if max_decode_sec > 0:
        cmd.extend(["-t", f"{max_decode_sec:.3f}"])
    cmd.extend([
        "-i",
        str(path),
        "-af",
        af_filter,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-f",
        "f32le",
        "-",
    ])
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg decode failed for '{path.name}' ({af_filter}): "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    n = len(raw) // CHANNELS
    return raw[: n * CHANNELS].reshape((n, CHANNELS)).copy()


def apply_ffmpeg_filter_mem(audio_f32: np.ndarray, af_filter: str) -> np.ndarray:
    clipped = np.clip(audio_f32, -0.99, 0.99).astype(np.float32)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-i",
        "-",
        "-af",
        af_filter,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-f",
        "f32le",
        "-",
    ]
    proc = subprocess.run(cmd, input=clipped.tobytes(), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg filter failed ({af_filter}): {proc.stderr.decode('utf-8', errors='replace')}")
    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    n = len(raw) // CHANNELS
    return raw[: n * CHANNELS].reshape((n, CHANNELS)).copy()


def write_raw_wav(audio_f32: np.ndarray, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio_f32, -0.98, 0.98).astype(np.float32)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-i",
        "-",
        "-c:a",
        "pcm_f32le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=clipped.tobytes(), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed writing WAV {out_path}: {proc.stderr.decode('utf-8', errors='replace')}")


def measure_loudness(wav_path: Path, target_lufs: float = TARGET_LUFS) -> Tuple[float, float, float]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(wav_path),
        "-af",
        f"loudnorm=I={target_lufs:.1f}:TP=-1.2:LRA=10:print_format=json",
        "-f",
        "null",
        os.devnull,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"loudnorm measure failed: {proc.stderr}")
    m = re.search(r'\{\s*"input_i"\s*:.*?\}', proc.stderr, flags=re.DOTALL)
    if not m:
        return -16.0, -1.0, 0.0
    data = json.loads(m.group(0))
    input_i = float(data["input_i"])
    input_tp = float(data["input_tp"])
    gain_db = max(-24.0, min(18.0, target_lufs - input_i))
    return round(input_i, 3), round(input_tp, 3), round(gain_db, 3)


def encode_mastered(src_wav: Path, dest_path: Path, af_chain: str, fmt: str, bitrate: str = "320k") -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src_wav),
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-af",
        af_chain,
    ]
    if fmt == "wav":
        cmd.extend(["-c:a", "pcm_s16le"])
    elif fmt == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", bitrate])
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    cmd.append(str(dest_path))

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Encode failed for {dest_path}: {proc.stderr}")


def verify_audio(path: Path) -> Dict[str, Any]:
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    pjson = json.loads(probe.stdout)
    astream = next(s for s in pjson["streams"] if s["codec_type"] == "audio")
    dur = round(float(pjson["format"]["duration"]), 4)

    vdet = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect", "-f", "null", os.devnull],
        capture_output=True,
        text=True,
        check=True,
    )
    max_m = re.search(r"max_volume:\s*([-\d.]+)\s*dB", vdet.stderr)
    mean_m = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", vdet.stderr)
    lufs, tp, _ = measure_loudness(path, TARGET_LUFS)

    return {
        "path": str(path),
        "duration_sec": dur,
        "sample_rate": int(astream["sample_rate"]),
        "channels": int(astream["channels"]),
        "max_volume_db": float(max_m.group(1)) if max_m else None,
        "mean_volume_db": float(mean_m.group(1)) if mean_m else None,
        "integrated_lufs": lufs,
        "true_peak_db": tp,
        "bytes": path.stat().st_size,
    }


def detect_groove_downbeat(audio: np.ndarray, bpm: float, search_start_sec: float, search_end_sec: float) -> float:
    mono = audio.mean(axis=1)
    bar_samples = int(round(((60.0 * 4.0) / bpm) * SAMPLE_RATE))
    win = int(SAMPLE_RATE * 0.030)
    hop = int(SAMPLE_RATE * 0.005)
    s0 = max(0, int(round(search_start_sec * SAMPLE_RATE)))
    s1 = min(len(mono) - 4 * bar_samples - win, int(round(search_end_sec * SAMPLE_RATE)))
    if s1 <= s0:
        return search_start_sec

    best_score = -1.0
    best_idx = s0
    for idx in range(s0, s1, hop):
        bar1_rms = float(np.sqrt(np.mean(mono[idx : idx + win] ** 2) + 1e-12))
        grid_sum = 0.0
        for b in range(4):
            pos = idx + b * bar_samples
            grid_sum += float(np.sqrt(np.mean(mono[pos : pos + win] ** 2) + 1e-12))
        score = grid_sum + bar1_rms * 1.15
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx / SAMPLE_RATE


def slice_wrapped(src: np.ndarray, start_sample: int, length_samples: int) -> np.ndarray:
    if start_sample >= 0 and start_sample + length_samples <= len(src):
        return src[start_sample : start_sample + length_samples].copy()
    idx = (np.arange(length_samples, dtype=np.int64) + max(0, start_sample)) % len(src)
    return src[idx].copy()


def raised_cos_ramp(n: int, v0: float, v1: float) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    u = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    ease = 0.5 * (1.0 - np.cos(math.pi * u))
    return v0 + (v1 - v0) * ease


def eq_fade_in(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    return np.sin(np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None])


def eq_fade_out(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    return np.cos(np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None])


def place_chill_phrase(
    timeline: np.ndarray,
    src_full: np.ndarray,
    src_hp: np.ndarray,
    src_tail_bp: np.ndarray,
    src_start_sec: float,
    tl_start_sec: float,
    n_bars: int,
    bpm: float,
    out_style: str = "chill_melt",
) -> float:
    """
    Places a chill SOLO beat phrase onto `timeline` with silky transitions:
      - `chill_melt`: gently rolls off outgoing bass over final 1 bar, uses a smooth 90ms
        equal-power downbeat handoff, and feathers a warm band-limited (320-2400 Hz)
        quarter-note echo tail into the incoming section.
      - `fadeout`: clean 3.0s raised-cosine outro fade.
    """
    bar_sec = (60.0 * 4.0) / bpm
    beat_sec = 60.0 / bpm
    dur_sec = float(n_bars) * bar_sec
    tl_end_sec = tl_start_sec + dur_sec

    i_start = int(round(tl_start_sec * SAMPLE_RATE))
    n_len = int(round(dur_sec * SAMPLE_RATE))
    i_end = i_start + n_len
    s_start = int(round(src_start_sec * SAMPLE_RATE))

    chunk_full = slice_wrapped(src_full, s_start, n_len)
    chunk_hp = slice_wrapped(src_hp, s_start, n_len)
    chunk_bp = slice_wrapped(src_tail_bp, s_start, n_len)
    phrase = chunk_full.copy()

    # Smooth 90ms equal-power fade-in on Beat 1 (or 40ms for very first phrase)
    fi_sec = 0.040 if tl_start_sec < 0.01 else 0.090
    n_fi = min(n_len, int(round(fi_sec * SAMPLE_RATE)))
    if n_fi > 0:
        phrase[:n_fi] *= eq_fade_in(n_fi)

    if out_style == "chill_melt":
        # Smooth bass feathering over the final 1 bar (4 beats)
        sweep_n = min(n_len, int(round(bar_sec * SAMPLE_RATE)))
        if sweep_n > 0:
            w = raised_cos_ramp(sweep_n, 0.0, 1.0)
            phrase[-sweep_n:] = chunk_full[-sweep_n:] * (1.0 - w) + chunk_hp[-sweep_n:] * w

        # Smooth 90ms equal-power downbeat release right on Beat 1
        cut_n = min(n_len, int(round(0.090 * SAMPLE_RATE)))
        if cut_n > 0:
            phrase[-cut_n:] *= eq_fade_out(cut_n)

        # Warm band-limited (320-2400 Hz) soft quarter-note tail
        tail_n = min(n_len, int(round(beat_sec * SAMPLE_RATE)))
        if tail_n > 0:
            tail_src = chunk_bp[-tail_n:].copy()
            edge_n = min(tail_n // 4, int(round(0.035 * SAMPLE_RATE)))
            if edge_n > 0:
                tail_src[:edge_n] *= eq_fade_in(edge_n)
                tail_src[-edge_n:] *= eq_fade_out(edge_n)

            quarter_n = int(round(beat_sec * SAMPLE_RATE))
            for tap_idx, tap_gain in enumerate((0.22, 0.09), start=1):
                tap_pos = i_end - tail_n + tap_idx * quarter_n
                tap_end = min(len(timeline), tap_pos + tail_n)
                if tap_pos >= 0 and tap_end > tap_pos:
                    timeline[tap_pos:tap_end] += tail_src[: tap_end - tap_pos] * tap_gain

    elif out_style == "fadeout":
        fade_n = min(n_len, int(round(4.0 * SAMPLE_RATE)))
        if fade_n > 0:
            phrase[-fade_n:] *= raised_cos_ramp(fade_n, 1.0, 0.0)

    write_end = min(len(timeline), i_end)
    if write_end > i_start:
        timeline[i_start:write_end] += phrase[: write_end - i_start]

    return tl_end_sec


def onset_envelope(mono: np.ndarray, hop: int = 120) -> np.ndarray:
    win = hop * 2
    n = max(1, (len(mono) - win) // hop)
    sq = mono[: n * hop].reshape(n, hop) ** 2
    rms = np.sqrt(np.mean(sq, axis=1) + 1e-12)
    diff = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    norm = float(np.std(diff) + 1e-9)
    return (diff - np.mean(diff)) / norm


def find_vocal_entry_sec(vocals: np.ndarray, bpm: float) -> float:
    bar_sec = (60.0 * 4.0) / bpm
    bar_n = int(round(bar_sec * SAMPLE_RATE))
    mono = vocals.mean(axis=1)
    max_search_bars = min(int(40.0 / bar_sec), len(mono) // bar_n)

    bar_rms_list = [
        float(np.sqrt(np.mean(mono[b * bar_n : (b + 1) * bar_n] ** 2) + 1e-12))
        for b in range(max_search_bars)
    ]
    if not bar_rms_list:
        return 0.0
    peak_bar = max(bar_rms_list)
    thresh = max(0.020, 0.28 * peak_bar)
    for b, r in enumerate(bar_rms_list):
        if r >= thresh:
            return b * bar_sec
    return 0.0


def compute_drum_phase_lag_sec(
    vocal_drums: np.ndarray,
    vocal_entry_sec: float,
    inst_timeline: np.ndarray,
    tl_vocal_enter_sec: float,
    bpm: float,
) -> float:
    hop = 120  # 2.5 ms at 48 kHz
    bar_sec = (60.0 * 4.0) / bpm
    window_sec = min(12.0 * bar_sec, (len(inst_timeline) / SAMPLE_RATE) - tl_vocal_enter_sec - bar_sec)
    window_sec = max(4.0 * bar_sec, window_sec)

    w_len = int(round(window_sec * SAMPLE_RATE))
    v_start = max(0, int(round(vocal_entry_sec * SAMPLE_RATE)))
    i_start = max(0, int(round(tl_vocal_enter_sec * SAMPLE_RATE)))

    v_env = onset_envelope(slice_wrapped(vocal_drums, v_start, w_len).mean(axis=1), hop=hop)
    i_env = onset_envelope(slice_wrapped(inst_timeline, i_start, w_len).mean(axis=1), hop=hop)

    max_shift = int(round((0.5 * bar_sec * SAMPLE_RATE) / hop))
    n_cmp = min(len(v_env), len(i_env))
    if n_cmp <= 2 * max_shift + 10:
        return 0.0

    best_lag = 0
    best_corr = -1e18
    for lag in range(-max_shift, max_shift + 1):
        if lag >= 0:
            c = float(np.dot(i_env[lag:n_cmp], v_env[: n_cmp - lag]) / (n_cmp - lag))
        else:
            k = -lag
            c = float(np.dot(i_env[: n_cmp - k], v_env[k:n_cmp]) / (n_cmp - k))
        if c > best_corr:
            best_corr = c
            best_lag = lag

    return round((best_lag * hop) / SAMPLE_RATE, 4)


def vocal_activity_envelope(vocals_tl: np.ndarray) -> np.ndarray:
    mono = np.abs(vocals_tl.mean(axis=1))
    win = int(SAMPLE_RATE * 0.065)
    kernel = np.ones(win, dtype=np.float32) / float(win)
    smoothed = np.convolve(mono, kernel, mode="same")
    alpha = np.clip((smoothed - 0.012) / 0.048, 0.0, 1.0).astype(np.float32)
    return alpha[:, None]


def build_chill_track(
    slug: str,
    title: str,
    genre: str,
    key_name: str,
    target_bpm: float,
    moods: List[str],
    beats_spec: List[Dict[str, Any]],
    flow_prompt: str,
    flow_passes: List[str],
    cue_notes: str,
    vocal_spec: Optional[Dict[str, Any]] = None,
    is_instrumental: Optional[bool] = None,
) -> Dict[str, Any]:
    bar_sec = (60.0 * 4.0) / target_bpm

    # 1. Decode, stretch, pitch-lock, and pre-level all instrumental segments
    decoded_beats = []
    for bs in beats_spec:
        tempo_ratio = target_bpm / float(bs["raw_bpm"])
        pitch_ratio = 2.0 ** (float(bs.get("pitch_st", 0)) / 12.0)
        af_full = f"rubberband=tempo={tempo_ratio:.6f}:pitch={pitch_ratio:.6f}:transients=crisp:phase=laminar"
        af_hp = f"{af_full},highpass=f=320"
        af_bp = f"{af_full},highpass=f=320,lowpass=f=2400"

        b_full = decode_f32(bs["path"], af_full, max_decode_sec=float(bs.get("max_decode_sec", 140.0)))
        b_hp = decode_f32(bs["path"], af_hp, max_decode_sec=float(bs.get("max_decode_sec", 140.0)))
        b_bp = decode_f32(bs["path"], af_bp, max_decode_sec=float(bs.get("max_decode_sec", 140.0)))
        anchor = detect_groove_downbeat(b_full, target_bpm, bs["search_start"], bs["search_end"])

        s0 = int(round(anchor * SAMPLE_RATE))
        s1 = min(len(b_full), s0 + int(round(8.0 * bar_sec * SAMPLE_RATE)))
        rms = float(np.sqrt(np.mean(b_full[s0:s1] ** 2) + 1e-12)) if s1 > s0 else TARGET_GROOVE_RMS
        scale = TARGET_GROOVE_RMS / max(0.02, rms)
        b_full *= scale
        b_hp *= scale
        b_bp *= scale
        decoded_beats.append((bs, b_full, b_hp, b_bp, anchor, round(scale, 4)))

    total_bars = sum(int(bs["bars"]) for bs in beats_spec)
    total_sec = total_bars * bar_sec
    total_samples = int(round(total_sec * SAMPLE_RATE))
    inst_timeline = np.zeros((total_samples + int(2.5 * SAMPLE_RATE), CHANNELS), dtype=np.float32)

    cur_tl = 0.0
    section_bounds = []
    for idx, (bs, b_full, b_hp, b_bp, anchor, _) in enumerate(decoded_beats):
        out_style = "fadeout" if idx == len(decoded_beats) - 1 else "chill_melt"
        next_tl = place_chill_phrase(
            inst_timeline,
            b_full,
            b_hp,
            b_bp,
            src_start_sec=anchor,
            tl_start_sec=cur_tl,
            n_bars=int(bs["bars"]),
            bpm=target_bpm,
            out_style=out_style,
        )
        section_bounds.append({"label": bs["label"], "start_sec": round(cur_tl, 3), "end_sec": round(next_tl, 3)})
        cur_tl = next_tl

    inst_timeline = inst_timeline[:total_samples].copy()

    # 2. Optional zero-gate silky vocal layer (only for chill03)
    vocals_timeline: Optional[np.ndarray] = None
    vocal_meta: Dict[str, Any] = {"has_vocals": False}

    if vocal_spec is not None:
        v_cache = STEMS_CACHE_DIR / vocal_spec["cache_key"]
        vocals_wav = v_cache / "vocals.wav"
        drums_wav = v_cache / "drums.wav"
        v_tempo = target_bpm / float(vocal_spec["raw_bpm"])
        v_pitch = 2.0 ** (float(vocal_spec.get("pitch_st", 0)) / 12.0)

        # Warm analog vocal polish ONLY — NO RMS noise gate, NO metallic aecho!
        voc_af = (
            f"rubberband=tempo={v_tempo:.6f}:pitch={v_pitch:.6f}:transients=crisp:phase=laminar,"
            "highpass=f=100,lowpass=f=11500,"
            "equalizer=f=2800:t=q:w=1.1:g=1.4,"
            "acompressor=threshold=-20dB:ratio=2.2:attack=15:release=220:makeup=1.5"
        )
        drm_af = f"rubberband=tempo={v_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar"

        voc_processed = decode_f32(vocals_wav, voc_af)
        voc_drums = decode_f32(drums_wav, drm_af)

        vocal_entry_sec = find_vocal_entry_sec(voc_processed, target_bpm)
        tl_vocal_enter_sec = 4.0 * bar_sec
        lag_sec = compute_drum_phase_lag_sec(voc_drums, vocal_entry_sec, inst_timeline, tl_vocal_enter_sec, target_bpm)

        vocal_dur_bars = total_bars - 8  # bars 5..36 (32 bars singing)
        vocal_span_samples = int(round(vocal_dur_bars * bar_sec * SAMPLE_RATE))
        v_slice = slice_wrapped(voc_processed, int(round(vocal_entry_sec * SAMPLE_RATE)), vocal_span_samples)

        # Level vocals smoothly over active frames without gating any breath/tails
        v_abs = np.abs(v_slice.mean(axis=1))
        active_samples = v_slice[v_abs >= 0.015]
        cur_v_rms = float(np.sqrt(np.mean(active_samples ** 2) + 1e-12)) if len(active_samples) > 1000 else float(np.sqrt(np.mean(v_slice ** 2) + 1e-12))
        v_slice *= TARGET_VOCAL_RMS / max(0.01, cur_v_rms)

        fi_n = min(len(v_slice), int(round(0.080 * SAMPLE_RATE)))
        fo_n = min(len(v_slice), int(round(2.0 * bar_sec * SAMPLE_RATE)))
        if fi_n > 0:
            v_slice[:fi_n] *= eq_fade_in(fi_n)
        if fo_n > 0:
            v_slice[-fo_n:] *= raised_cos_ramp(fo_n, 1.0, 0.0)

        vocals_timeline = np.zeros((total_samples, CHANNELS), dtype=np.float32)
        tl_v_start = max(0, int(round((tl_vocal_enter_sec + lag_sec) * SAMPLE_RATE)))
        tl_v_end = min(total_samples, tl_v_start + len(v_slice))
        if tl_v_end > tl_v_start:
            vocals_timeline[tl_v_start:tl_v_end] = v_slice[: tl_v_end - tl_v_start]

        # Gentle -2.5 dB midrange vocal-pocket ducking
        inst_ducked = apply_ffmpeg_filter_mem(inst_timeline, "equalizer=f=1900:t=h:w=2400:g=-2.5")
        min_len = min(len(inst_timeline), len(inst_ducked), len(vocals_timeline))
        inst_timeline = inst_timeline[:min_len]
        inst_ducked = inst_ducked[:min_len]
        vocals_timeline = vocals_timeline[:min_len]

        alpha = vocal_activity_envelope(vocals_timeline)
        inst_pocket = inst_timeline * (1.0 - alpha) + inst_ducked * alpha
        master_mix = inst_pocket + vocals_timeline

        vocal_meta = {
            "has_vocals": True,
            "vocal_entry_sec": round(vocal_entry_sec, 3),
            "tl_vocal_start_sec": round(tl_v_start / SAMPLE_RATE, 3),
            "drum_phase_lag_sec": lag_sec,
            "vocal_rms_post": round(float(np.sqrt(np.mean(vocals_timeline ** 2))), 4),
        }
    else:
        inst_pocket = inst_timeline
        master_mix = inst_timeline

    raw_peak = float(np.max(np.abs(master_mix)) + 1e-9)
    if raw_peak > 0.92:
        scale_h = 0.92 / raw_peak
        master_mix *= scale_h
        inst_pocket *= scale_h
        if vocals_timeline is not None:
            vocals_timeline *= scale_h

    # 3. Export MP3 + Vault WAV + Stems
    vault_track_dir = VAULT_DIR / slug
    stems_dir = vault_track_dir / "stems"
    vault_track_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)
    HITS_DIR.mkdir(parents=True, exist_ok=True)

    master_wav = vault_track_dir / "master.wav"
    preview_mp3 = HITS_DIR / f"{slug}.mp3"
    inst_out = stems_dir / "instruments.wav"
    vocals_out = stems_dir / "vocals.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_m = tmp / "raw_master.wav"
        raw_i = tmp / "raw_inst.wav"
        write_raw_wav(master_mix, raw_m)
        write_raw_wav(inst_pocket, raw_i)

        raw_lufs, raw_tp, gain_db = measure_loudness(raw_m, TARGET_LUFS)
        af_master = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"

        encode_mastered(raw_m, master_wav, af_master, "wav")
        encode_mastered(raw_m, preview_mp3, af_master, "mp3", bitrate="320k")
        encode_mastered(raw_i, inst_out, af_master, "wav")

        if vocals_timeline is not None:
            raw_v = tmp / "raw_vocals.wav"
            write_raw_wav(vocals_timeline, raw_v)
            encode_mastered(raw_v, vocals_out, af_master, "wav")

    stems_meta = {"instruments": "stems/instruments.wav"}
    if vocals_timeline is not None:
        stems_meta["vocals"] = "stems/vocals.wav"

    track_obj = {
        "slug": slug,
        "title": title,
        "artist": "Chase (@chaseham00) / Google Flow Music",
        "bpm": round(target_bpm, 2),
        "key": key_name,
        "timeSignature": "4/4",
        "moods": moods,
        "genre": genre,
        "instrumental": (vocals_timeline is None) if is_instrumental is None else bool(is_instrumental),
        "loopable": False,
        "licenseTier": "Personal Mashup Reference (Generate Original in Flow Music for Commercial Use)",
        "synthIdVerified": False,
        "flowSessionUrl": "",
        "targets": [],
        "masterFile": "master.wav",
        "stems": stems_meta,
        "cueNotes": cue_notes,
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with (vault_track_dir / "track.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(track_obj, f, indent=2)
        f.write("\n")

    passes_md = "\n".join(f"- **Pass {i+1}:** {p}" for i, p in enumerate(flow_passes))
    prompt_md = (
        f"# Google Flow Music Brief - {title}\n\n"
        f"- **Slug:** `{slug}`\n"
        f"- **BPM / Key / Meter:** {target_bpm} BPM | {key_name} | 4/4\n"
        f"- **Genre:** {genre}\n"
        f"- **Moods:** {', '.join(moods)}\n"
        f"- **License Note:** Local render saved to `exports/hits/{slug}.mp3`. "
        f"Paste the prompt below into Google Flow Music to generate a 100% original, monetization-safe version.\n\n"
        f"## 1. Initial Flow Music Studio Prompt\n> {flow_prompt}\n\n"
        f"## 2. Conversational Producer Directives\n{passes_md}\n"
    )
    (vault_track_dir / "prompt.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    (vault_track_dir / "lyrics.md").write_text(
        f"# Arrangement & Vocal Reference - {title}\n\n{cue_notes}\n",
        encoding="utf-8",
        newline="\n",
    )

    outputs: Dict[str, Any] = {
        "preview_mp3": verify_audio(preview_mp3),
        "master_wav": verify_audio(master_wav),
        "instruments_wav": verify_audio(inst_out),
    }
    if vocals_timeline is not None:
        outputs["vocals_wav"] = verify_audio(vocals_out)

    return {
        "slug": slug,
        "title": title,
        "bpm": target_bpm,
        "key": key_name,
        **vocal_meta,
        "sections": section_bounds,
        "mastering": {"raw_lufs": raw_lufs, "raw_tp_db": raw_tp, "applied_gain_db": gain_db},
        "outputs": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build late-night Tokyo chill blends.")
    parser.add_argument("--only", type=str, default=None, help="Optional single track slug to build.")
    args = parser.parse_args()
    only_slug = args.only.strip() if args.only else None

    for key, p in SOURCES.items():
        if not p.is_file():
            raise FileNotFoundError(f"Missing source track '{key}': {p}")

    sep_mod = load_separator_module()
    shiki_cache = STEMS_CACHE_DIR / "champloo_shiki_no_uta"
    wild_cache = STEMS_CACHE_DIR / "sa2_wild_canyon"
    shiki_status = "skipped"

    if only_slug in (None, "chill01-champloo-canyon-pure"):
        if not all((wild_cache / fn).is_file() for fn in sep_mod.EXPECTED_FILES):
            sep_mod.separate_track(SOURCES["sa2_wild_canyon"], wild_cache, max_sec=120.0, force=False)
    if only_slug in (None, "chill03-shiki-no-midnight"):
        shiki_res = sep_mod.separate_track(SOURCES["champloo_shiki_no_uta"], shiki_cache, max_sec=120.0, force=False)
        shiki_status = shiki_res["status"]

    results = []

    # Chill #1: Champloo Canyon — Pure Beat Edition (98.00 BPM, F major)
    if only_slug in (None, "chill01-champloo-canyon-pure"):
        results.append(
            build_chill_track(
                slug="chill01-champloo-canyon-pure",
                title="Champloo Canyon - Pure Beat Edition (m-flo x Wild Canyon x Utada x Nujabes)",
                genre="Late-Night 90s Tokyo Rhodes & Boom-Bap Instrumental",
                key_name="F major",
                target_bpm=98.0,
                moods=["chill", "neo-soul", "boom-bap", "90s-tokyo", "instrumental"],
                beats_spec=[
                    {
                        "label": "m-flo Been So Long (Silky Rhodes Intro + Groove)",
                        "path": SOURCES["mflo_been_so_long"],
                        "raw_bpm": 95.990,
                        "pitch_st": 0,
                        "bars": 16,
                        "search_start": 0.20,
                        "search_end": 4.50,
                    },
                    {
                        "label": "SA2 Wild Canyon Instrumental (Vocal-Free Flute Groove)",
                        "path": wild_cache / "instrumental.wav",
                        "raw_bpm": 99.980,
                        "pitch_st": 0,
                        "bars": 16,
                        "search_start": 1.60,
                        "search_end": 6.50,
                    },
                    {
                        "label": "Hikaru Utada Automatic Inst (Parallel F minor R&B Turnaround)",
                        "path": SOURCES["utada_automatic"],
                        "raw_bpm": 94.800,
                        "pitch_st": 0,
                        "bars": 8,
                        "search_start": 0.00,
                        "search_end": 4.00,
                    },
                    {
                        "label": "Nujabes Aruarian Dance (Acoustic Guitar Cooldown)",
                        "path": SOURCES["nujabes_aruarian"],
                        "raw_bpm": 99.235,
                        "pitch_st": -3,
                        "bars": 8,
                        "search_start": 14.00,
                        "search_end": 20.00,
                    },
                ],
                flow_prompt="98 BPM in F major, pure instrumental. Warm 1998 Tokyo R&B Fender Rhodes chords, soulful woodwind flute melodies, loose dusty boom-bap rimshots, deep analog upright bass, and acoustic Spanish guitar outro. Silky late-night study and cruising vibe, zero harsh transients.",
                flow_passes=[
                    "Keep the Rhodes warm and spacious while letting the flute melody breathe in the upper midrange.",
                    "Transition smoothly at bar 33 into a lush minor-key R&B chord turnaround before resolving to solo acoustic guitar.",
                    "Export clean loopable master and stems.",
                ],
                cue_notes="Pure unducked instrumental sequence: 16 bars m-flo -> 16 bars Wild Canyon (no vocals) -> 8 bars Utada Automatic -> 8 bars Nujabes Aruarian Dance.",
                vocal_spec=None,
            )
        )

    # Chill #2: Midnight Tokyo Rain (75.00 BPM, G minor — Organic Rainy Jazz Lounge)
    if only_slug in (None, "chill02-midnight-tokyo-rain"):
        results.append(
            build_chill_track(
                slug="chill02-midnight-tokyo-rain",
                title="Midnight Tokyo Rain (Persona 5 x Hiroshi Suzuki x MISIA x Space Lion)",
                genre="Rainy Cafe Acid Jazz, 70s Japanese Trombone & Tokyo R&B Lounge",
                key_name="G minor",
                target_bpm=75.0,
                moods=["chill", "rainy", "jazz-lounge", "late-night", "sax"],
                beats_spec=[
                    {
                        "label": "Persona 5 Beneath the Mask (Rainy Acid-Jazz Rhodes)",
                        "path": SOURCES["p5_beneath_mask"],
                        "raw_bpm": 74.000,
                        "pitch_st": 0,
                        "bars": 12,
                        "search_start": 0.00,
                        "search_end": 3.50,
                    },
                    {
                        "label": "Hiroshi Suzuki Romance (1975 Tokyo Midnight Trombone)",
                        "path": SOURCES["hiroshi_romance"],
                        "raw_bpm": 75.300,
                        "pitch_st": -2,
                        "bars": 12,
                        "search_start": 26.00,
                        "search_end": 34.00,
                    },
                    {
                        "label": "MISIA Tsutsumikomu You ni Inst (1998 Tokyo R&B Groove)",
                        "path": SOURCES["misia_inst"],
                        "raw_bpm": 80.000,
                        "pitch_st": -2,
                        "bars": 12,
                        "search_start": 10.00,
                        "search_end": 18.00,
                    },
                    {
                        "label": "Persona 5 Beneath the Mask (Rainy Rhodes Reprise)",
                        "path": SOURCES["p5_beneath_mask"],
                        "raw_bpm": 74.000,
                        "pitch_st": 0,
                        "bars": 8,
                        "search_start": 72.00,
                        "search_end": 82.00,
                    },
                    {
                        "label": "Cowboy Bebop Space Lion (Smoky Tenor Sax Epilogue)",
                        "path": SOURCES["space_lion"],
                        "raw_bpm": 75.000,
                        "pitch_st": 0,
                        "bars": 8,
                        "search_start": 10.00,
                        "search_end": 14.00,
                    },
                ],
                flow_prompt="75 BPM in G minor, pure organic instrumental. Rainy Shibuya midnight cafe acid jazz featuring warm Fender Rhodes seventh chords, smoky 1970s Japanese jazz trombone solo, silky 1998 Tokyo R&B piano/drums, brushed drum kit, deep walking upright bass, and a closing smoky tenor saxophone epilogue.",
                flow_passes=[
                    "Open with intimate Rhodes and brushed snare before melting into a warm 1975 Tokyo jazz trombone melody and silky 90s Tokyo R&B groove.",
                    "Reprise the rainy Rhodes chords into a lone smoky Cowboy Bebop-style tenor saxophone epilogue with a 4-second fade.",
                    "Export clean master and stems.",
                ],
                cue_notes="Organic 52-bar rainy Tokyo jazz-lounge journey at 75 BPM in G minor: 12 bars P5 Beneath the Mask -> 12 bars Hiroshi Suzuki Romance -> 12 bars MISIA Inst (-2 st) -> 8 bars P5 Reprise -> 8 bars Space Lion sax epilogue.",
                vocal_spec=None,
                is_instrumental=True,
            )
        )

    # Chill #3: Shiki No Midnight (92.50 BPM, Bb minor)
    if only_slug in (None, "chill03-shiki-no-midnight"):
        results.append(
            build_chill_track(
                slug="chill03-shiki-no-midnight",
                title="Shiki No Midnight (Shiki No Uta x Nujabes x m-flo)",
                genre="Smoky Midnight Tokyo Vocal Lo-Fi & R&B",
                key_name="Bb minor",
                target_bpm=92.5,
                moods=["chill", "soulful", "vocal", "late-night", "lofi"],
                beats_spec=[
                    {
                        "label": "Nujabes Aruarian Dance (Warm Boom-Bap Intro + Verse 1)",
                        "path": SOURCES["nujabes_aruarian"],
                        "raw_bpm": 99.235,
                        "pitch_st": 2,
                        "bars": 16,
                        "search_start": 14.00,
                        "search_end": 20.00,
                    },
                    {
                        "label": "m-flo Been So Long (Silky 90s Rhodes Chorus)",
                        "path": SOURCES["mflo_been_so_long"],
                        "raw_bpm": 95.990,
                        "pitch_st": -2,
                        "bars": 16,
                        "search_start": 0.20,
                        "search_end": 4.50,
                    },
                    {
                        "label": "Nujabes Aruarian Dance (Acoustic Outro)",
                        "path": SOURCES["nujabes_aruarian"],
                        "raw_bpm": 99.235,
                        "pitch_st": 2,
                        "bars": 8,
                        "search_start": 14.00,
                        "search_end": 20.00,
                    },
                ],
                flow_prompt="92.5 BPM in Bb minor. Smoky midnight Japanese lo-fi R&B featuring gentle acoustic guitar loops, dusty boom-bap snare, warm 90s Fender Rhodes chords, and intimate soulful female vocals with natural breathing room.",
                flow_passes=[
                    "Keep the female vocal natural and airy without harsh gating, gently carving -2.5 dB around 1.9 kHz in the Rhodes when singing.",
                    "Transition smoothly between acoustic guitar verses and lush Rhodes choruses.",
                    "Export master plus isolated vocals and instruments stems.",
                ],
                cue_notes="4-bar Nujabes intro -> 32 bars MINMI Shiki No Uta vocals (+0 st, zero noise gate) gliding across Nujabes (12 bars) -> m-flo Rhodes (16 bars) -> Nujabes (4 bars) -> 4-bar acoustic outro.",
                vocal_spec={
                    "cache_key": "champloo_shiki_no_uta",
                    "raw_bpm": 92.450,
                    "pitch_st": 0,
                },
            )
        )

    print(json.dumps({"status": "success", "only": only_slug, "shiki_separation": shiki_status, "blends": results}, indent=2))


if __name__ == "__main__":
    main()
