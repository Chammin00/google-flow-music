#!/usr/bin/env python3
"""
Build-AnimeHitBlends.py

Produces 3 AI stem-separated (htdemucs), beat-locked, key-locked, vocal-pocket-ducked
Anime x YouTube BGM Hit Blends:
  1. hit01-champloo-canyon       (98.00 BPM, F major)  — Samurai Champloo x m-flo x Wild Canyon x Nujabes
  2. hit02-lost-in-studiopolis   (122.00 BPM, A minor) — JJK Lost in Paradise x Sonic Mania Studiopolis x Lupin III
  3. hit03-conan-will-change     (132.00 BPM, F minor) — Persona 5 Life Will Change x Detective Conan x Mondo Grosso

Outputs per hit:
  - exports/hits/<slug>.mp3         (320k MP3 ready to audition)
  - vault/<slug>/master.wav         (48 kHz 16-bit stereo WAV, -14 LUFS)
  - vault/<slug>/stems/{vocals,instruments}.wav
  - vault/<slug>/{track.json, prompt.md, lyrics.md}
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_LUFS = -14.0
TARGET_GROOVE_RMS = 0.21
TARGET_VOCAL_RMS = 0.185

HUB_ROOT = Path(__file__).resolve().parent.parent
STEMS_CACHE_DIR = HUB_ROOT / "exports" / "stems_cache"
HITS_DIR = HUB_ROOT / "exports" / "hits"
VAULT_DIR = HUB_ROOT / "vault"

SOURCES: Dict[str, Path] = {
    "champloo_battlecry": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Samurai Champloo Opening Theme Battlecry.mp3"),
    "mflo_been_so_long": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\m-flo - been so long (Instrumental).mp3"),
    "sa2_wild_canyon": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\sonic_adventure_wild_canyon.mp3"),
    "nujabes_aruarian": Path(r"G:\My Drive\Gaming & Development\Music & Audio\Highlights_Japanese_RnB_Jazz\Nujabes - Aruarian Dance Instrumental.mp3"),
    "jjk_lost_in_paradise": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\JUJUTSU KAISEN - Ending Lost in Paradise feat. AKLO.mp3"),
    "sonic_mania_studiopolis": Path(r"G:\My Drive\Gaming & Development\Music & Audio\Background_Sonic_OST\Sonic Mania - Studiopolis Zone Act 1.mp3"),
    "lupin_2018": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\anime hype\Lupin III Part 5 OP FULLLUPIN TROIS 2018by Yuji Ohno & Lupintic Six - Copy.mp3"),
    "p5_life_will_change": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Persona 5 - Life Will Change (中英歌詞).mp3"),
    "conan_main": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\anime hype\[Detective Conan OST] Main Theme (Extended) - Copy.mp3"),
    "mondo_grosso_acid": Path(r"G:\My Drive\Gaming & Development\Music & Audio\80s_90s_Japanese_Jazz_RnB\Mondo Grosso - Souffles H Acid Jazz (1993).mp3"),
}


def load_separator_module() -> Any:
    sep_path = HUB_ROOT / "scripts" / "Separate-TrackStems.py"
    spec = importlib.util.spec_from_file_location("separate_track_stems", sep_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load separator script: {sep_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decode_f32(path: Path, af_filter: str) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
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
    ]
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
        f"loudnorm=I={target_lufs:.1f}:TP=-1.2:LRA=9:print_format=json",
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
    """Finds the best Beat 1 onset inside [search_start_sec, search_end_sec] locked across 4 bars."""
    mono = audio.mean(axis=1)
    bar_samples = int(round(((60.0 * 4.0) / bpm) * SAMPLE_RATE))
    win = int(SAMPLE_RATE * 0.025)
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
        score = grid_sum + bar1_rms * 1.25
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


def place_inst_phrase(
    timeline: np.ndarray,
    src_full: np.ndarray,
    src_hp: np.ndarray,
    src_start_sec: float,
    tl_start_sec: float,
    n_bars: int,
    bpm: float,
    out_style: str = "echo",
) -> float:
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
    phrase = chunk_full.copy()

    n_fi = min(n_len, int(round(0.030 * SAMPLE_RATE)))
    if n_fi > 0:
        phrase[:n_fi] *= eq_fade_in(n_fi)

    if out_style == "echo":
        sweep_n = min(n_len, int(round(2.0 * beat_sec * SAMPLE_RATE)))
        if sweep_n > 0:
            w = raised_cos_ramp(sweep_n, 0.0, 1.0)
            phrase[-sweep_n:] = chunk_full[-sweep_n:] * (1.0 - w) + chunk_hp[-sweep_n:] * w

        cut_n = min(n_len, int(round(0.035 * SAMPLE_RATE)))
        if cut_n > 0:
            phrase[-cut_n:] *= eq_fade_out(cut_n)

        echo_n = min(n_len, int(round(beat_sec * SAMPLE_RATE)))
        if echo_n > 0:
            echo_src = chunk_hp[-echo_n:].copy()
            edge_n = min(echo_n // 4, int(round(0.020 * SAMPLE_RATE)))
            if edge_n > 0:
                echo_src[:edge_n] *= eq_fade_in(edge_n)
                echo_src[-edge_n:] *= eq_fade_out(edge_n)
            eighth_n = int(round(0.5 * beat_sec * SAMPLE_RATE))
            for tap_idx, tap_gain in enumerate((0.24, 0.11, 0.04), start=1):
                tap_pos = i_end - echo_n + tap_idx * eighth_n
                tap_end = min(len(timeline), tap_pos + echo_n)
                if tap_pos >= 0 and tap_end > tap_pos:
                    timeline[tap_pos:tap_end] += echo_src[: tap_end - tap_pos] * tap_gain

    elif out_style == "fadeout":
        fade_n = min(n_len, int(round(2.5 * SAMPLE_RATE)))
        if fade_n > 0:
            phrase[-fade_n:] *= raised_cos_ramp(fade_n, 1.0, 0.0)

    write_end = min(len(timeline), i_end)
    if write_end > i_start:
        timeline[i_start:write_end] += phrase[: write_end - i_start]

    return tl_end_sec


def onset_envelope(mono: np.ndarray, hop: int = 120) -> np.ndarray:
    """2.5 ms resolution energy-flux onset envelope for drum-to-drum phase locking."""
    win = hop * 2
    n = max(1, (len(mono) - win) // hop)
    sq = mono[: n * hop].reshape(n, hop) ** 2
    rms = np.sqrt(np.mean(sq, axis=1) + 1e-12)
    diff = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    norm = float(np.std(diff) + 1e-9)
    return (diff - np.mean(diff)) / norm


def find_vocal_entry_sec(vocals: np.ndarray, bpm: float) -> float:
    """Finds the start of the first active vocal phrase bar inside [0s, 45s]."""
    bar_sec = (60.0 * 4.0) / bpm
    bar_n = int(round(bar_sec * SAMPLE_RATE))
    mono = vocals.mean(axis=1)
    max_search_bars = min(int(45.0 / bar_sec), len(mono) // bar_n)

    bar_rms_list = []
    for b in range(max_search_bars):
        seg = mono[b * bar_n : (b + 1) * bar_n]
        bar_rms_list.append(float(np.sqrt(np.mean(seg ** 2) + 1e-12)))

    if not bar_rms_list:
        return 0.0
    peak_bar_rms = max(bar_rms_list)
    thresh = max(0.025, 0.30 * peak_bar_rms)

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
    """
    Cross-correlates onset envelopes of `vocal_drums` against `inst_timeline`
    over +/- 0.5 bar (2.5 ms steps) so vocal phrasing locks directly into the new beat pocket.
    """
    hop = 120  # 2.5 ms at 48 kHz
    bar_sec = (60.0 * 4.0) / bpm
    window_sec = min(12.0 * bar_sec, (len(inst_timeline) / SAMPLE_RATE) - tl_vocal_enter_sec - bar_sec)
    window_sec = max(4.0 * bar_sec, window_sec)

    w_len = int(round(window_sec * SAMPLE_RATE))
    v_start = max(0, int(round(vocal_entry_sec * SAMPLE_RATE)))
    i_start = max(0, int(round(tl_vocal_enter_sec * SAMPLE_RATE)))

    v_slice = slice_wrapped(vocal_drums, v_start, w_len).mean(axis=1)
    i_slice = slice_wrapped(inst_timeline, i_start, w_len).mean(axis=1)

    v_env = onset_envelope(v_slice, hop=hop)
    i_env = onset_envelope(i_slice, hop=hop)

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

    # Positive lag means i_env[lag:] aligns with v_env[:], so shifting vocal entry by +lag*hop locks drums!
    return round((best_lag * hop) / SAMPLE_RATE, 4)


def vocal_activity_envelope(vocals_tl: np.ndarray) -> np.ndarray:
    """Computes smooth 0..1 vocal presence envelope (~50 ms window) for midrange pocket ducking."""
    mono = np.abs(vocals_tl.mean(axis=1))
    win = int(SAMPLE_RATE * 0.050)
    kernel = np.ones(win, dtype=np.float32) / float(win)
    smoothed = np.convolve(mono, kernel, mode="same")
    # Smoothly map vocal RMS above 0.012 toward 1.0 by 0.06
    alpha = np.clip((smoothed - 0.012) / 0.048, 0.0, 1.0).astype(np.float32)
    return alpha[:, None]


def build_single_hit(
    slug: str,
    title: str,
    genre: str,
    key_name: str,
    target_bpm: float,
    moods: List[str],
    vocal_track_key: str,
    vocal_raw_bpm: float,
    vocal_pitch_st: int,
    beats_spec: List[Dict[str, Any]],
    flow_prompt: str,
    flow_passes: List[str],
    cue_notes: str,
) -> Dict[str, Any]:
    bar_sec = (60.0 * 4.0) / target_bpm

    # 1. Decode & stretch all 3 instrumental beat segments (pre-leveled to TARGET_GROOVE_RMS)
    decoded_beats = []
    for bs in beats_spec:
        tempo_ratio = target_bpm / float(bs["raw_bpm"])
        pitch_ratio = 2.0 ** (float(bs.get("pitch_st", 0)) / 12.0)
        af_full = f"rubberband=tempo={tempo_ratio:.6f}:pitch={pitch_ratio:.6f}:transients=crisp:phase=laminar"
        af_hp = f"{af_full},highpass=f=360"

        b_full = decode_f32(bs["path"], af_full)
        b_hp = decode_f32(bs["path"], af_hp)
        anchor = detect_groove_downbeat(b_full, target_bpm, bs["search_start"], bs["search_end"])

        # Pre-level over 8 bars from anchor
        s0 = int(round(anchor * SAMPLE_RATE))
        s1 = min(len(b_full), s0 + int(round(8.0 * bar_sec * SAMPLE_RATE)))
        rms = float(np.sqrt(np.mean(b_full[s0:s1] ** 2) + 1e-12)) if s1 > s0 else TARGET_GROOVE_RMS
        scale = TARGET_GROOVE_RMS / max(0.02, rms)
        b_full *= scale
        b_hp *= scale
        decoded_beats.append((bs, b_full, b_hp, anchor, round(scale, 4)))

    # 40 bars total: Part 1 (16 bars) -> Part 2 (16 bars) -> Part 3 (8 bars)
    total_bars = sum(int(bs["bars"]) for bs in beats_spec)
    total_sec = total_bars * bar_sec
    total_samples = int(round(total_sec * SAMPLE_RATE))
    inst_timeline = np.zeros((total_samples + int(2.0 * SAMPLE_RATE), CHANNELS), dtype=np.float32)

    cur_tl = 0.0
    section_bounds = []
    for idx, (bs, b_full, b_hp, anchor, _) in enumerate(decoded_beats):
        out_style = "fadeout" if idx == len(decoded_beats) - 1 else "echo"
        next_tl = place_inst_phrase(
            inst_timeline,
            b_full,
            b_hp,
            src_start_sec=anchor,
            tl_start_sec=cur_tl,
            n_bars=int(bs["bars"]),
            bpm=target_bpm,
            out_style=out_style,
        )
        section_bounds.append({"label": bs["label"], "start_sec": round(cur_tl, 3), "end_sec": round(next_tl, 3)})
        cur_tl = next_tl

    inst_timeline = inst_timeline[:total_samples].copy()

    # 2. Decode isolated vocals + drum reference of the vocal track
    v_cache = STEMS_CACHE_DIR / vocal_track_key
    vocals_wav = v_cache / "vocals.wav"
    drums_wav = v_cache / "drums.wav"
    v_tempo = target_bpm / float(vocal_raw_bpm)
    v_pitch = 2.0 ** (float(vocal_pitch_st) / 12.0)

    voc_af = (
        f"rubberband=tempo={v_tempo:.6f}:pitch={v_pitch:.6f}:transients=crisp:phase=laminar,"
        "highpass=f=130,equalizer=f=3200:t=q:w=1.2:g=2.2,"
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2,"
        "aecho=0.8:0.7:42|84:0.12|0.06"
    )
    drm_af = f"rubberband=tempo={v_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar"

    voc_processed = decode_f32(vocals_wav, voc_af)
    voc_drums = decode_f32(drums_wav, drm_af)

    vocal_entry_sec = find_vocal_entry_sec(voc_processed, target_bpm)

    # Vocals enter cleanly after a 4-bar instrumental intro and span 32 bars (leaving 4-bar instrumental outro)
    tl_vocal_enter_sec = 4.0 * bar_sec
    lag_sec = compute_drum_phase_lag_sec(voc_drums, vocal_entry_sec, inst_timeline, tl_vocal_enter_sec, target_bpm)

    # Apply fine phase lag while keeping vocals inside [tl_vocal_enter_sec - 0.5*bar, ...]
    vocal_dur_bars = total_bars - 8  # bars 5..36 (32 bars active singing)
    vocal_span_samples = int(round(vocal_dur_bars * bar_sec * SAMPLE_RATE))
    v_src_idx = int(round(vocal_entry_sec * SAMPLE_RATE))
    v_slice = slice_wrapped(voc_processed, v_src_idx, vocal_span_samples)

    # Soft noise-gate bleed suppression where vocal drops below 0.008
    v_env_gate = np.abs(v_slice.mean(axis=1))
    win_g = int(SAMPLE_RATE * 0.060)
    v_smooth = np.convolve(v_env_gate, np.ones(win_g, dtype=np.float32) / float(win_g), mode="same")
    gate_gain = np.where(v_smooth >= 0.008, 1.0, 0.25 + 0.75 * (v_smooth / 0.008)).astype(np.float32)[:, None]
    v_slice *= gate_gain

    # Level vocals to TARGET_VOCAL_RMS over active vocal samples
    active_samples = v_slice[v_smooth >= 0.015]
    if len(active_samples) > 1000:
        cur_v_rms = float(np.sqrt(np.mean(active_samples ** 2) + 1e-12))
    else:
        cur_v_rms = float(np.sqrt(np.mean(v_slice ** 2) + 1e-12))
    v_scale = TARGET_VOCAL_RMS / max(0.01, cur_v_rms)
    v_slice *= v_scale

    # Clean 40ms fade-in & 2-bar fade-out on vocals
    fi_n = min(len(v_slice), int(round(0.040 * SAMPLE_RATE)))
    fo_n = min(len(v_slice), int(round(1.5 * bar_sec * SAMPLE_RATE)))
    if fi_n > 0:
        v_slice[:fi_n] *= eq_fade_in(fi_n)
    if fo_n > 0:
        v_slice[-fo_n:] *= raised_cos_ramp(fo_n, 1.0, 0.0)

    vocals_timeline = np.zeros((total_samples, CHANNELS), dtype=np.float32)
    tl_v_start = max(0, int(round((tl_vocal_enter_sec + lag_sec) * SAMPLE_RATE)))
    tl_v_end = min(total_samples, tl_v_start + len(v_slice))
    if tl_v_end > tl_v_start:
        vocals_timeline[tl_v_start:tl_v_end] = v_slice[: tl_v_end - tl_v_start]

    # 3. Dynamic vocal-pocket midrange ducking (750-3600 Hz attenuated -3.5 dB under vocals)
    inst_ducked = apply_ffmpeg_filter_mem(inst_timeline, "equalizer=f=1900:t=h:w=2400:g=-3.5")
    min_len = min(len(inst_timeline), len(inst_ducked), len(vocals_timeline))
    inst_timeline = inst_timeline[:min_len]
    inst_ducked = inst_ducked[:min_len]
    vocals_timeline = vocals_timeline[:min_len]

    alpha = vocal_activity_envelope(vocals_timeline)
    inst_pocket = inst_timeline * (1.0 - alpha) + inst_ducked * alpha

    master_mix = inst_pocket + vocals_timeline
    raw_peak = float(np.max(np.abs(master_mix)) + 1e-9)
    if raw_peak > 0.92:
        scale_h = 0.92 / raw_peak
        master_mix *= scale_h
        inst_pocket *= scale_h
        vocals_timeline *= scale_h

    # 4. Write vault track files & master audio (-14.0 LUFS, -1.1 dB limiter)
    vault_track_dir = VAULT_DIR / slug
    stems_dir = vault_track_dir / "stems"
    vault_track_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)
    HITS_DIR.mkdir(parents=True, exist_ok=True)

    master_wav = vault_track_dir / "master.wav"
    preview_mp3 = HITS_DIR / f"{slug}.mp3"
    vocals_out = stems_dir / "vocals.wav"
    inst_out = stems_dir / "instruments.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_m = tmp / "raw_master.wav"
        raw_v = tmp / "raw_vocals.wav"
        raw_i = tmp / "raw_inst.wav"

        write_raw_wav(master_mix, raw_m)
        write_raw_wav(vocals_timeline, raw_v)
        write_raw_wav(inst_pocket, raw_i)

        raw_lufs, raw_tp, gain_db = measure_loudness(raw_m, TARGET_LUFS)
        af_master = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"

        encode_mastered(raw_m, master_wav, af_master, "wav")
        encode_mastered(raw_m, preview_mp3, af_master, "mp3", bitrate="320k")
        encode_mastered(raw_v, vocals_out, af_master, "wav")
        encode_mastered(raw_i, inst_out, af_master, "wav")

    # 5. Write UTF-8 (no BOM) track.json, prompt.md, lyrics.md
    track_obj = {
        "slug": slug,
        "title": title,
        "artist": "Chase (@chaseham00) / Google Flow Music",
        "bpm": int(round(target_bpm)),
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
        "stems": {
            "instruments": "stems/instruments.wav",
            "vocals": "stems/vocals.wav",
        },
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
        f"- **BPM / Key / Meter:** {int(round(target_bpm))} BPM | {key_name} | 4/4\n"
        f"- **Genre:** {genre}\n"
        f"- **Moods:** {', '.join(moods)}\n"
        f"- **License Note:** Local render uses AI-separated OST stems (`exports/hits/{slug}.mp3`). "
        f"Paste the prompt below into Google Flow Music to generate a 100% original, monetization-safe version.\n\n"
        f"## 1. Initial Flow Music Studio Prompt\n> {flow_prompt}\n\n"
        f"## 2. Conversational Producer Directives\n{passes_md}\n"
    )
    (vault_track_dir / "prompt.md").write_text(prompt_md, encoding="utf-8", newline="\n")
    (vault_track_dir / "lyrics.md").write_text(
        f"# Lyrics / Vocal Reference - {title}\n\n{cue_notes}\n",
        encoding="utf-8",
        newline="\n",
    )

    m_rep = verify_audio(master_wav)
    mp3_rep = verify_audio(preview_mp3)
    v_rep = verify_audio(vocals_out)
    i_rep = verify_audio(inst_out)

    return {
        "slug": slug,
        "title": title,
        "bpm": target_bpm,
        "key": key_name,
        "vocal_entry_sec": round(vocal_entry_sec, 3),
        "tl_vocal_start_sec": round(tl_v_start / SAMPLE_RATE, 3),
        "drum_phase_lag_sec": lag_sec,
        "vocal_rms_post": round(float(np.sqrt(np.mean(vocals_timeline ** 2))), 4),
        "sections": section_bounds,
        "mastering": {"raw_lufs": raw_lufs, "raw_tp_db": raw_tp, "applied_gain_db": gain_db},
        "outputs": {
            "preview_mp3": mp3_rep,
            "master_wav": m_rep,
            "vocals_wav": v_rep,
            "instruments_wav": i_rep,
        },
    }


def main() -> None:
    for key, p in SOURCES.items():
        if not p.is_file():
            raise FileNotFoundError(f"Missing source track '{key}': {p}")

    # Step A: Separate the 4 tracks that need clean htdemucs vocals/drums or vocal-free instrumentals
    sep_mod = load_separator_module()
    tracks_to_separate = [
        ("champloo_battlecry", SOURCES["champloo_battlecry"]),
        ("sa2_wild_canyon", SOURCES["sa2_wild_canyon"]),
        ("jjk_lost_in_paradise", SOURCES["jjk_lost_in_paradise"]),
        ("p5_life_will_change", SOURCES["p5_life_will_change"]),
    ]
    needs_model = any(
        not all((STEMS_CACHE_DIR / k / fn).is_file() for fn in sep_mod.EXPECTED_FILES)
        for k, _ in tracks_to_separate
    )
    shared_model = sep_mod.get_model("htdemucs") if needs_model else None

    sep_results = []
    for k, src_path in tracks_to_separate:
        res = sep_mod.separate_track(src_path, STEMS_CACHE_DIR / k, max_sec=120.0, force=False, model=shared_model)
        sep_results.append({"key": k, "status": res["status"]})

    # Step B: Build the 3 Hit Blends
    hits_report = []

    # Hit #1: Champloo Canyon (98 BPM, F major)
    hits_report.append(
        build_single_hit(
            slug="hit01-champloo-canyon",
            title="Champloo Canyon (Samurai Champloo x m-flo x Wild Canyon x Nujabes)",
            genre="Golden-Era 90s Tokyo Boom-Bap Jazz Rap",
            key_name="F major",
            target_bpm=98.0,
            moods=["chill", "hip-hop", "boom-bap", "90s-tokyo", "groove"],
            vocal_track_key="champloo_battlecry",
            vocal_raw_bpm=97.995,
            vocal_pitch_st=0,
            beats_spec=[
                {
                    "label": "m-flo Been So Long (Intro + Verse 1)",
                    "path": SOURCES["mflo_been_so_long"],
                    "raw_bpm": 95.990,
                    "pitch_st": 0,
                    "bars": 16,
                    "search_start": 0.20,
                    "search_end": 4.50,
                },
                {
                    "label": "SA2 Wild Canyon Instrumental (Verse 2 + Hook)",
                    "path": STEMS_CACHE_DIR / "sa2_wild_canyon" / "instrumental.wav",
                    "raw_bpm": 99.980,
                    "pitch_st": 0,
                    "bars": 16,
                    "search_start": 1.60,
                    "search_end": 6.50,
                },
                {
                    "label": "Nujabes Aruarian Dance (Outro)",
                    "path": SOURCES["nujabes_aruarian"],
                    "raw_bpm": 99.235,
                    "pitch_st": -3,
                    "bars": 8,
                    "search_start": 14.00,
                    "search_end": 20.00,
                },
            ],
            flow_prompt="98 BPM in F major. Golden-era 90s Tokyo lo-fi boom-bap jazz hip-hop featuring warm Fender Rhodes seventh chords, dusty vinyl acoustic guitar loops, melodic woodwind flute phrases, crisp unquantized snare crack, deep upright jazz bass, and relaxed rhythmic male rap vocals.",
            flow_passes=[
                "Keep the Rhodes and flute samples warm in the midrange while carving a gentle 2 kHz pocket for tight rhythmic rap delivery.",
                "Swap the last 8 bars to a stripped-back acoustic guitar and warm vinyl crackle outro.",
                "Export clean vocals, drums, bass, and instruments stems on the 98 BPM grid.",
            ],
            cue_notes="4-bar m-flo intro -> 32 bars Shing02 Battlecry vocals gliding across m-flo (12 bars) + SA2 Wild Canyon instrumental (16 bars) + Nujabes acoustic transition (4 bars) -> 4-bar Nujabes outro.",
        )
    )

    # Hit #2: Lost in Studiopolis (122 BPM, A minor)
    hits_report.append(
        build_single_hit(
            slug="hit02-lost-in-studiopolis",
            title="Lost in Studiopolis (JJK Lost in Paradise x Sonic Mania x Lupin III)",
            genre="Neon Shibuya Funk-Disco & Heist Brass",
            key_name="A minor",
            target_bpm=122.0,
            moods=["hype", "funk", "disco", "shibuya", "upbeat"],
            vocal_track_key="jjk_lost_in_paradise",
            vocal_raw_bpm=121.995,
            vocal_pitch_st=-1,
            beats_spec=[
                {
                    "label": "Sonic Mania Studiopolis Act 1 (Intro + Hook/Verse)",
                    "path": SOURCES["sonic_mania_studiopolis"],
                    "raw_bpm": 119.990,
                    "pitch_st": 0,
                    "bars": 16,
                    "search_start": 0.00,
                    "search_end": 4.20,
                },
                {
                    "label": "Lupin III Part 5 Heist Brass (Rap Verse)",
                    "path": SOURCES["lupin_2018"],
                    "raw_bpm": 120.000,
                    "pitch_st": 2,
                    "bars": 16,
                    "search_start": 10.00,
                    "search_end": 18.00,
                },
                {
                    "label": "Sonic Mania Studiopolis Act 1 (Final Hook + Outro)",
                    "path": SOURCES["sonic_mania_studiopolis"],
                    "raw_bpm": 119.990,
                    "pitch_st": 0,
                    "bars": 8,
                    "search_start": 16.00,
                    "search_end": 24.00,
                },
            ],
            flow_prompt="122 BPM in A minor. High-style neon Tokyo funk-disco fusion pairing punchy 16-bit synth-brass chord stabs and slap bass with live anime big-band heist horns, crisp four-on-the-floor disco groove, and charismatic soulful Japanese funk + rap vocals.",
            flow_passes=[
                "Tighten the disco bassline and snare clap so the rap verse snaps cleanly over the live brass stabs.",
                "Bring back the bright synth-funk hook chorus for the final 8 bars with explosive horn fills.",
                "Export full master and isolated vocals/instruments stems.",
            ],
            cue_notes="4-bar Studiopolis synth-funk intro -> 32 bars ALI + AKLO Lost in Paradise vocals (-1 st -> A min) across Studiopolis (12 bars) -> Lupin III (+2 st -> A min, 16 bars) -> Studiopolis finale (4 bars) -> 4-bar outro.",
        )
    )

    # Hit #3: Conan Will Change Your Life (132 BPM, F minor)
    hits_report.append(
        build_single_hit(
            slug="hit03-conan-will-change",
            title="Conan Will Change Your Life (Persona 5 x Detective Conan x Mondo Grosso)",
            genre="Tokyo Acid-Jazz Anime Heist Anthem",
            key_name="F minor",
            target_bpm=132.0,
            moods=["hype", "acid-jazz", "heist", "sax", "action"],
            vocal_track_key="p5_life_will_change",
            vocal_raw_bpm=132.000,
            vocal_pitch_st=0,
            beats_spec=[
                {
                    "label": "Detective Conan Main Theme (Intro + Verse 1)",
                    "path": SOURCES["conan_main"],
                    "raw_bpm": 132.885,
                    "pitch_st": 0,
                    "bars": 16,
                    "search_start": 0.40,
                    "search_end": 4.50,
                },
                {
                    "label": "Mondo Grosso Souffles H (Acid-Jazz Chorus Explosion)",
                    "path": SOURCES["mondo_grosso_acid"],
                    "raw_bpm": 126.125,
                    "pitch_st": 0,
                    "bars": 16,
                    "search_start": 16.00,
                    "search_end": 24.00,
                },
                {
                    "label": "Detective Conan Main Theme (Sax Finale)",
                    "path": SOURCES["conan_main"],
                    "raw_bpm": 132.885,
                    "pitch_st": 0,
                    "bars": 8,
                    "search_start": 30.00,
                    "search_end": 42.00,
                },
            ],
            flow_prompt="132 BPM in F minor. Driving 1990s Tokyo club acid-jazz anime heist anthem with screaming tenor saxophone lead, punchy Rhodes electric piano, tight funk slap bass, syncopated jazz horn hits, and soaring soulful female acid-jazz vocals.",
            flow_passes=[
                "Build tension with the iconic jazz-sax heist groove before dropping into warm 90s club acid-jazz Rhodes on the chorus.",
                "Ensure the sax solo and lead vocals trade phrases cleanly without midrange masking.",
                "Export 48 kHz master and isolated stems.",
            ],
            cue_notes="4-bar Detective Conan sax intro -> 32 bars Lyn Life Will Change vocals across Conan Main Theme (12 bars) -> Mondo Grosso Acid Jazz (16 bars) -> Conan climax (4 bars) -> 4-bar sax outro.",
        )
    )

    print(json.dumps({"status": "success", "separated": sep_results, "hits": hits_report}, indent=2))


if __name__ == "__main__":
    main()
