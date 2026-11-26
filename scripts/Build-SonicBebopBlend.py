#!/usr/bin/env python3
"""
Build-SonicBebopBlend.py

Creates a seamless, non-overlapping DJ-flow continuous arrangement (138.000 BPM, G minor)
blending Cowboy Bebop (Tank!), Sonic 2 (Chemical Plant Zone), and Sonic 3 (IceCap Zone Act 1).

Only ONE track owns the melody and drums at a time, linked by beat-locked DJ transitions:
  - High-pass sweeps + tempo-synced eighth-note echo tails ('echo')
  - 1-bar DJ bass swap ('bass_swap')
  - Tight 2-bar call-and-response 'Trading Twos' ('snap')
  - Clean 2.5s ending fade ('fadeout')

Outputs:
  - vault/sonic23-bebop-fusion/master.wav (48 kHz 16-bit stereo WAV, -14 LUFS)
  - exports/blends/sonic23-bebop-fusion.mp3 (320k MP3 preview)
  - vault/sonic23-bebop-fusion/stems/{bass,drums,instruments,vocals}.wav
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

SAMPLE_RATE = 48000
CHANNELS = 2
TARGET_BPM = 138.0
TARGET_KEY = "G minor"
TARGET_LUFS = -14.0
TARGET_GROOVE_RMS = 0.22

HUB_ROOT = Path(__file__).resolve().parent.parent
VAULT_TRACK_DIR = HUB_ROOT / "vault" / "sonic23-bebop-fusion"
STEMS_DIR = VAULT_TRACK_DIR / "stems"
BLENDS_DIR = HUB_ROOT / "exports" / "blends"

DEFAULT_SOURCES = {
    "tank": Path(r"G:\My Drive\Personal & Family\Music & Audio\Anime Soundtracks & OSTs\Tank! Cowboy Bebop (Full version).mp3"),
    "chem": Path(r"G:\My Drive\Gaming & Development\Music & Audio\Background_Sonic_OST\Sonic 2 - Chemical Plant Zone.mp3"),
    "ice": Path(r"G:\My Drive\Antigravity\Projects\automate my day\modules\youtube\music\sonic3_icecap_zone_act1.mp3"),
}


def decode_ffmpeg_f32(path: Path, af_filter: str) -> np.ndarray:
    """Runs FFmpeg filtergraph and decodes 48 kHz stereo float32 PCM into numpy (N, 2)."""
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
            f"FFmpeg decode failed for '{path.name}' with filter '{af_filter}': "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    n_samples = len(audio) // CHANNELS
    return audio[: n_samples * CHANNELS].reshape((n_samples, CHANNELS)).copy()


def detect_tank_drop(tank_stereo: np.ndarray) -> float:
    """Finds the exact Bar 1 brass explosion downbeat (~18.12s) locked across 8 bars."""
    mono = tank_stereo.mean(axis=1)
    bar_samples = int(round(((60.0 * 4.0) / TARGET_BPM) * SAMPLE_RATE))
    win = int(SAMPLE_RATE * 0.020)
    hop = int(SAMPLE_RATE * 0.004)
    s_start = int(17.95 * SAMPLE_RATE)
    s_end = min(len(mono) - 8 * bar_samples - win, int(18.45 * SAMPLE_RATE))

    best_score = -1.0
    best_sample = int(18.125 * SAMPLE_RATE)

    for idx in range(s_start, s_end, hop):
        bar1_rms = float(np.sqrt(np.mean(mono[idx : idx + win] ** 2) + 1e-12))
        grid_sum = 0.0
        for b in range(8):
            pos = idx + b * bar_samples
            grid_sum += float(np.sqrt(np.mean(mono[pos : pos + win] ** 2) + 1e-12))
        score = grid_sum + bar1_rms * 1.5
        if score > best_score:
            best_score = score
            best_sample = idx

    return best_sample / SAMPLE_RATE


def detect_first_downbeat(audio_stereo: np.ndarray, max_search_sec: float = 3.0) -> float:
    """Finds the first musical downbeat onset after initial MP3 padding."""
    mono = audio_stereo.mean(axis=1)
    limit = min(len(mono), int(max_search_sec * SAMPLE_RATE))
    win = int(SAMPLE_RATE * 0.015)
    hop = int(SAMPLE_RATE * 0.002)

    peak_global = float(np.max(np.abs(mono[:limit])) + 1e-9)
    thresh = max(0.04, 0.22 * peak_global)

    for idx in range(0, max(1, limit - win), hop):
        rms = float(np.sqrt(np.mean(mono[idx : idx + win] ** 2)))
        if rms >= thresh:
            return idx / SAMPLE_RATE

    nz = np.where(np.abs(mono[:limit]) > 0.02)[0]
    return (float(nz[0]) / SAMPLE_RATE) if len(nz) > 0 else 0.0


def slice_wrapped(src: np.ndarray, start_sample: int, length_samples: int) -> np.ndarray:
    """Extracts `length_samples` starting at `start_sample` with safe wrap if needed."""
    if start_sample >= 0 and start_sample + length_samples <= len(src):
        return src[start_sample : start_sample + length_samples].copy()
    idx = (np.arange(length_samples, dtype=np.int64) + max(0, start_sample)) % len(src)
    return src[idx].copy()


def raised_cos_ramp(n: int, start_val: float, end_val: float) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    u = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    ease = 0.5 * (1.0 - np.cos(math.pi * u))
    return start_val + (end_val - start_val) * ease


def equal_power_fade_in(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    u = np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None]
    return np.sin(u)


def equal_power_fade_out(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    u = np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None]
    return np.cos(u)


def place_phrase(
    timeline: np.ndarray,
    src_full: np.ndarray,
    src_hp: np.ndarray,
    src_start_sec: float,
    tl_start_sec: float,
    n_bars: float,
    fade_in_ms: float = 30.0,
    out_style: str = "echo",
    next_bass_src: Optional[np.ndarray] = None,
    next_bass_start_sec: float = 0.0,
    duration_sec_override: Optional[float] = None,
) -> float:
    """
    Places a SOLO phrase onto `timeline` with beat-locked DJ transitions.
    Returns `tl_end_sec` (the exact Beat 1 downbeat for the next phrase).
    """
    bar_sec = (60.0 * 4.0) / TARGET_BPM
    beat_sec = 60.0 / TARGET_BPM

    dur_sec = duration_sec_override if duration_sec_override is not None else (float(n_bars) * bar_sec)
    tl_end_sec = tl_start_sec + dur_sec

    i_start = int(round(tl_start_sec * SAMPLE_RATE))
    n_len = int(round(dur_sec * SAMPLE_RATE))
    i_end = i_start + n_len
    s_start = int(round(src_start_sec * SAMPLE_RATE))

    chunk_full = slice_wrapped(src_full, s_start, n_len)
    chunk_hp = slice_wrapped(src_hp, s_start, n_len)

    # Start with pure full-spectrum solo phrase
    phrase = chunk_full.copy()

    # Smooth Beat 1 equal-power fade-in
    n_fi = min(n_len, int(round((fade_in_ms / 1000.0) * SAMPLE_RATE)))
    if n_fi > 0:
        phrase[:n_fi] *= equal_power_fade_in(n_fi)

    if out_style == "echo":
        # High-pass sweep over the last 2 beats (removes outgoing bass cleanly before incoming Beat 1)
        sweep_n = min(n_len, int(round(2.0 * beat_sec * SAMPLE_RATE)))
        if sweep_n > 0:
            w_hp = raised_cos_ramp(sweep_n, 0.0, 1.0)
            tail_full = chunk_full[-sweep_n:]
            tail_hp = chunk_hp[-sweep_n:]
            phrase[-sweep_n:] = tail_full * (1.0 - w_hp) + tail_hp * w_hp

        # Clean 35ms cut right on Beat 1
        cut_n = min(n_len, int(round(0.035 * SAMPLE_RATE)))
        if cut_n > 0:
            phrase[-cut_n:] *= equal_power_fade_out(cut_n)

        # Tempo-synced 8th-note echo tail sampled from the last 1 beat of high-passed outgoing track
        echo_beat_n = min(n_len, int(round(beat_sec * SAMPLE_RATE)))
        if echo_beat_n > 0:
            echo_src = chunk_hp[-echo_beat_n:].copy()
            edge_n = min(echo_beat_n // 4, int(round(0.020 * SAMPLE_RATE)))
            if edge_n > 0:
                echo_src[:edge_n] *= equal_power_fade_in(edge_n)
                echo_src[-edge_n:] *= equal_power_fade_out(edge_n)

            eighth_n = int(round(0.5 * beat_sec * SAMPLE_RATE))
            for tap_idx, tap_gain in enumerate((0.26, 0.12, 0.05), start=1):
                tap_pos = i_end - echo_beat_n + tap_idx * eighth_n
                tap_end = min(len(timeline), tap_pos + echo_beat_n)
                if tap_pos >= 0 and tap_end > tap_pos:
                    timeline[tap_pos:tap_end] += echo_src[: tap_end - tap_pos] * tap_gain

    elif out_style == "bass_swap":
        # 1-bar high-pass roll-off on outgoing track while incoming low-passed bass rises smoothly
        swap_n = min(n_len, int(round(bar_sec * SAMPLE_RATE)))
        if swap_n > 0:
            w_swap = raised_cos_ramp(swap_n, 0.0, 1.0)
            tail_full = chunk_full[-swap_n:]
            tail_hp = chunk_hp[-swap_n:]
            phrase[-swap_n:] = tail_full * (1.0 - w_swap) + tail_hp * w_swap

        cut_n = min(n_len, int(round(0.035 * SAMPLE_RATE)))
        if cut_n > 0:
            phrase[-cut_n:] *= equal_power_fade_out(cut_n)

        if next_bass_src is not None and swap_n > 0:
            b_start = int(round(next_bass_start_sec * SAMPLE_RATE))
            bass_seg = slice_wrapped(next_bass_src, b_start, swap_n)
            bass_env = raised_cos_ramp(swap_n, 0.0, 0.72)
            # Smooth 30ms handoff at very end of swap bar into full incoming Beat 1
            handoff_n = min(swap_n, int(round(0.030 * SAMPLE_RATE)))
            bass_seg *= bass_env
            bass_seg[-handoff_n:] *= equal_power_fade_out(handoff_n)
            tl_swap_start = i_end - swap_n
            if tl_swap_start >= 0 and i_end <= len(timeline):
                timeline[tl_swap_start:i_end] += bass_seg

    elif out_style == "snap":
        # Tight 35ms downbeat handoff + subtle 2-tap 8th-note high-passed echo for Trading Twos
        cut_n = min(n_len, int(round(0.035 * SAMPLE_RATE)))
        if cut_n > 0:
            phrase[-cut_n:] *= equal_power_fade_out(cut_n)

        echo_beat_n = min(n_len, int(round(0.75 * beat_sec * SAMPLE_RATE)))
        if echo_beat_n > 0:
            echo_src = chunk_hp[-echo_beat_n:].copy()
            edge_n = min(echo_beat_n // 4, int(round(0.018 * SAMPLE_RATE)))
            if edge_n > 0:
                echo_src[:edge_n] *= equal_power_fade_in(edge_n)
                echo_src[-edge_n:] *= equal_power_fade_out(edge_n)

            eighth_n = int(round(0.5 * beat_sec * SAMPLE_RATE))
            for tap_idx, tap_gain in enumerate((0.20, 0.08), start=1):
                tap_pos = i_end - echo_beat_n + tap_idx * eighth_n
                tap_end = min(len(timeline), tap_pos + echo_beat_n)
                if tap_pos >= 0 and tap_end > tap_pos:
                    timeline[tap_pos:tap_end] += echo_src[: tap_end - tap_pos] * tap_gain

    elif out_style == "fadeout":
        fade_n = min(n_len, int(round(2.5 * SAMPLE_RATE)))
        if fade_n > 0:
            phrase[-fade_n:] *= raised_cos_ramp(fade_n, 1.0, 0.0)
    else:
        raise ValueError(f"Unsupported out_style: {out_style}")

    write_end = min(len(timeline), i_end)
    if write_end > i_start:
        timeline[i_start:write_end] += phrase[: write_end - i_start]

    return tl_end_sec


def write_raw_wav(audio_f32: np.ndarray, raw_wav_path: Path) -> None:
    """Writes unclipped 32-bit float WAV via FFmpeg stdin."""
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
        str(raw_wav_path),
    ]
    proc = subprocess.run(cmd, input=clipped.tobytes(), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed writing raw WAV {raw_wav_path}: {proc.stderr.decode('utf-8', errors='replace')}")


def measure_loudness(wav_path: Path, target_lufs: float = TARGET_LUFS) -> Tuple[float, float, float]:
    """Measures integrated LUFS, true peak, and exact gain dB toward target_lufs."""
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


def render_mastered_audio(
    src_wav: Path,
    dest_path: Path,
    af_chain: str,
    fmt: str,
    bitrate: str = "320k",
) -> None:
    """Applies FFmpeg filter chain and encodes WAV or 320k MP3."""
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
        raise RuntimeError(f"Failed encoding {dest_path}: {proc.stderr}")


def verify_audio(path: Path) -> Dict[str, Any]:
    """Probes final duration, sample rate, channels, max_volume, and integrated LUFS."""
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


def compute_groove_rms(audio: np.ndarray, start_sec: float, duration_sec: float) -> float:
    i0 = max(0, int(round(start_sec * SAMPLE_RATE)))
    i1 = min(len(audio), int(round((start_sec + duration_sec) * SAMPLE_RATE)))
    if i1 <= i0:
        return TARGET_GROOVE_RMS
    return float(np.sqrt(np.mean(audio[i0:i1] ** 2) + 1e-12))


def build_blend(sources: Dict[str, Path] | None = None) -> Dict[str, Any]:
    src_map = sources or DEFAULT_SOURCES
    for key, p in src_map.items():
        if not p.is_file():
            raise FileNotFoundError(f"Missing source track '{key}': {p}")

    # Exact multi-bar measured tempo ratios -> 138.000 BPM in G minor
    tank_tempo = TARGET_BPM / 137.784
    chem_tempo = TARGET_BPM / 139.292
    chem_pitch = 2.0 ** (1.0 / 12.0)  # +1 semitone: F# minor -> G minor
    ice_tempo = TARGET_BPM / 138.273

    tank_full = decode_ffmpeg_f32(
        src_map["tank"],
        f"rubberband=tempo={tank_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar",
    )
    tank_hp = decode_ffmpeg_f32(
        src_map["tank"],
        f"rubberband=tempo={tank_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar,highpass=f=380",
    )

    chem_full = decode_ffmpeg_f32(
        src_map["chem"],
        f"rubberband=tempo={chem_tempo:.6f}:pitch={chem_pitch:.6f}:transients=crisp:phase=laminar",
    )
    chem_hp = decode_ffmpeg_f32(
        src_map["chem"],
        f"rubberband=tempo={chem_tempo:.6f}:pitch={chem_pitch:.6f}:transients=crisp:phase=laminar,highpass=f=380",
    )

    ice_full = decode_ffmpeg_f32(
        src_map["ice"],
        f"rubberband=tempo={ice_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar",
    )
    ice_hp = decode_ffmpeg_f32(
        src_map["ice"],
        f"rubberband=tempo={ice_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar,highpass=f=380",
    )
    ice_lp = decode_ffmpeg_f32(
        src_map["ice"],
        f"rubberband=tempo={ice_tempo:.6f}:pitch=1.0:transients=crisp:phase=laminar,lowpass=f=240",
    )

    bar_sec = (60.0 * 4.0) / TARGET_BPM  # 1.7391304s

    drop_t = detect_tank_drop(tank_full)
    chem_t0 = detect_first_downbeat(chem_full, max_search_sec=3.0)
    chem_bar5 = chem_t0 + 4.0 * bar_sec
    chem_bar13 = chem_t0 + 12.0 * bar_sec

    ice_t0 = detect_first_downbeat(ice_full, max_search_sec=2.0)
    ice_bar17 = ice_t0 + 16.0 * bar_sec

    # Pre-level every track to the exact same groove RMS so transitions flow seamlessly
    tank_scale = TARGET_GROOVE_RMS / compute_groove_rms(tank_full, drop_t, 8.0 * bar_sec)
    chem_scale = TARGET_GROOVE_RMS / compute_groove_rms(chem_full, chem_bar5, 8.0 * bar_sec)
    ice_scale = TARGET_GROOVE_RMS / compute_groove_rms(ice_full, ice_bar17, 8.0 * bar_sec)

    tank_full *= tank_scale
    tank_hp *= tank_scale
    chem_full *= chem_scale
    chem_hp *= chem_scale
    ice_full *= ice_scale
    ice_hp *= ice_scale
    ice_lp *= ice_scale

    # Total seamless duration: Part 1 (drop_t + 8 bars) + 32 additional bars
    total_dur_sec = drop_t + 40.0 * bar_sec
    total_samples = int(round(total_dur_sec * SAMPLE_RATE)) + int(round(1.5 * SAMPLE_RATE))
    timeline = np.zeros((total_samples, CHANNELS), dtype=np.float32)

    # Part 1: Cowboy Bebop Intro + 8 bars classic Tank! brass theme -> echo tail
    t = 0.0
    p1_dur = drop_t + 8.0 * bar_sec
    t_p2 = place_phrase(
        timeline,
        tank_full,
        tank_hp,
        src_start_sec=0.0,
        tl_start_sec=t,
        n_bars=0,
        fade_in_ms=20.0,
        out_style="echo",
        duration_sec_override=p1_dur,
    )

    # Part 2: Sonic 2 Chemical Plant Zone (8 bars SOLO from Bar 5) -> 1-bar bass swap into IceCap
    t_p3 = place_phrase(
        timeline,
        chem_full,
        chem_hp,
        src_start_sec=chem_bar5,
        tl_start_sec=t_p2,
        n_bars=8,
        fade_in_ms=30.0,
        out_style="bass_swap",
        next_bass_src=ice_lp,
        next_bass_start_sec=ice_bar17 - bar_sec,
    )

    # Part 3: Sonic 3 IceCap Zone Act 1 soaring chorus (8 bars SOLO from Bar 17) -> echo tail
    t_p4 = place_phrase(
        timeline,
        ice_full,
        ice_hp,
        src_start_sec=ice_bar17,
        tl_start_sec=t_p3,
        n_bars=8,
        fade_in_ms=30.0,
        out_style="echo",
    )

    # Part 4: Call-and-Response "Trading Twos" (4 x 2-bar SOLO handoffs)
    t_4b = place_phrase(
        timeline,
        tank_full,
        tank_hp,
        src_start_sec=drop_t + 8.0 * bar_sec,
        tl_start_sec=t_p4,
        n_bars=2,
        fade_in_ms=30.0,
        out_style="snap",
    )
    t_4c = place_phrase(
        timeline,
        chem_full,
        chem_hp,
        src_start_sec=chem_bar5 + 4.0 * bar_sec,
        tl_start_sec=t_4b,
        n_bars=2,
        fade_in_ms=30.0,
        out_style="snap",
    )
    t_4d = place_phrase(
        timeline,
        ice_full,
        ice_hp,
        src_start_sec=ice_bar17 + 4.0 * bar_sec,
        tl_start_sec=t_4c,
        n_bars=2,
        fade_in_ms=30.0,
        out_style="snap",
    )
    t_p5 = place_phrase(
        timeline,
        tank_full,
        tank_hp,
        src_start_sec=drop_t + 14.0 * bar_sec,
        tl_start_sec=t_4d,
        n_bars=2,
        fade_in_ms=30.0,
        out_style="echo",
    )

    # Part 5: Finale (4 bars Chemical Plant B-section -> 4 bars Tank! climax brass + clean fadeout)
    t_5b = place_phrase(
        timeline,
        chem_full,
        chem_hp,
        src_start_sec=chem_bar13,
        tl_start_sec=t_p5,
        n_bars=4,
        fade_in_ms=30.0,
        out_style="echo",
    )
    t_end = place_phrase(
        timeline,
        tank_full,
        tank_hp,
        src_start_sec=drop_t + 16.0 * bar_sec,
        tl_start_sec=t_5b,
        n_bars=4,
        fade_in_ms=30.0,
        out_style="fadeout",
    )

    exact_samples = int(round(t_end * SAMPLE_RATE))
    master_mix = timeline[:exact_samples].copy()

    raw_peak = float(np.max(np.abs(master_mix)) + 1e-9)
    if raw_peak > 0.92:
        master_mix *= 0.92 / raw_peak

    VAULT_TRACK_DIR.mkdir(parents=True, exist_ok=True)
    STEMS_DIR.mkdir(parents=True, exist_ok=True)
    BLENDS_DIR.mkdir(parents=True, exist_ok=True)

    master_wav_out = VAULT_TRACK_DIR / "master.wav"
    preview_mp3_out = BLENDS_DIR / "sonic23-bebop-fusion.mp3"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        raw_master = tmp / "raw_master.wav"
        write_raw_wav(master_mix, raw_master)

        measured_i, measured_tp, gain_db = measure_loudness(raw_master, TARGET_LUFS)
        master_af = f"volume={gain_db:.3f}dB,alimiter=limit=0.88:level=false"

        render_mastered_audio(raw_master, master_wav_out, master_af, "wav")
        render_mastered_audio(raw_master, preview_mp3_out, master_af, "mp3", bitrate="320k")

        stem_filters = {
            "bass": "lowpass=f=220,alimiter=limit=0.88:level=false",
            "drums": "bandpass=f=450:width_type=h:w=500,alimiter=limit=0.88:level=false",
            "instruments": "bandpass=f=1800:width_type=h:w=2400,alimiter=limit=0.88:level=false",
            "vocals": "highpass=f=3200,alimiter=limit=0.88:level=false",
        }
        stem_reports: Dict[str, Any] = {}
        for s_name, s_af in stem_filters.items():
            s_out = STEMS_DIR / f"{s_name}.wav"
            render_mastered_audio(master_wav_out, s_out, s_af, "wav")
            stem_reports[s_name] = verify_audio(s_out)

    master_report = verify_audio(master_wav_out)
    mp3_report = verify_audio(preview_mp3_out)

    return {
        "status": "success",
        "mode": "seamless_dj_flow_no_overlay",
        "bpm": TARGET_BPM,
        "key": TARGET_KEY,
        "bar_sec": round(bar_sec, 6),
        "alignment": {
            "tank_drop_sec": round(drop_t, 4),
            "chem_first_onset_sec": round(chem_t0, 4),
            "chem_bar5_groove_sec": round(chem_bar5, 4),
            "chem_bar13_b_sec": round(chem_bar13, 4),
            "ice_first_onset_sec": round(ice_t0, 4),
            "ice_bar17_chorus_sec": round(ice_bar17, 4),
        },
        "pre_level_scales": {
            "tank": round(tank_scale, 4),
            "chem": round(chem_scale, 4),
            "ice": round(ice_scale, 4),
        },
        "sections_sec": {
            "1_bebop_intro_and_brass": [0.0, round(t_p2, 3)],
            "2_sonic2_chemical_plant": [round(t_p2, 3), round(t_p3, 3)],
            "3_sonic3_icecap_chorus": [round(t_p3, 3), round(t_p4, 3)],
            "4a_trading_twos_tank": [round(t_p4, 3), round(t_4b, 3)],
            "4b_trading_twos_chemical": [round(t_4b, 3), round(t_4c, 3)],
            "4c_trading_twos_icecap": [round(t_4c, 3), round(t_4d, 3)],
            "4d_trading_twos_tank": [round(t_4d, 3), round(t_p5, 3)],
            "5a_finale_chemical_b": [round(t_p5, 3), round(t_5b, 3)],
            "5b_finale_tank_climax": [round(t_5b, 3), round(t_end, 3)],
        },
        "mastering": {
            "raw_integrated_lufs": measured_i,
            "raw_true_peak_db": measured_tp,
            "applied_gain_db": gain_db,
        },
        "outputs": {
            "master_wav": master_report,
            "preview_mp3": mp3_report,
            "stems": stem_reports,
        },
    }


def main() -> None:
    report = build_blend()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
