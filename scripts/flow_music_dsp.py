#!/usr/bin/env python3
"""
flow_music_dsp.py

Pure-NumPy audio DSP kernels for Google Flow Music blend & stem mastering pipelines.
Zero I/O, zero external globals, and deterministic signatures compatible with both
vectorized NumPy execution and optional Rust extraction via `fast-anything`.
"""

from __future__ import annotations

from bisect import bisect_left
import math
from typing import List, Sequence, Tuple

import numpy as np


def _build_5smooth_table(limit: int) -> List[int]:
    """Generate sorted 5-smooth integers (2^a * 3^b * 5^c) up to limit."""
    vals = []
    p2 = 1
    while p2 <= limit:
        p3 = p2
        while p3 <= limit:
            p5 = p3
            while p5 <= limit:
                vals.append(p5)
                p5 *= 5
            p3 *= 3
        p2 *= 2
    vals.sort()
    return vals


_SMOOTH_LIMIT = 32_000_000
_SMOOTH_TABLE = _build_5smooth_table(_SMOOTH_LIMIT)


def next_fast_fft_len(n: int) -> int:
    """Return smallest integer >= n whose prime factors are solely in {2, 3, 5}."""
    if n <= 1:
        return 1
    if n <= _SMOOTH_LIMIT:
        idx = bisect_left(_SMOOTH_TABLE, n)
        if idx < len(_SMOOTH_TABLE):
            return _SMOOTH_TABLE[idx]
    val = 1 << (n - 1).bit_length()
    return val


def eq_in(n: int) -> np.ndarray:
    """Quarter-sine equal-power fade-in envelope."""
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    return np.sin(np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None])


def eq_out(n: int) -> np.ndarray:
    """Quarter-cosine equal-power fade-out envelope."""
    if n <= 0:
        return np.zeros((0, 1), dtype=np.float32)
    return np.cos(np.linspace(0.0, math.pi * 0.5, n, dtype=np.float32)[:, None])


def compute_stem_phase_lag(
    orig: np.ndarray,
    stem_sum: np.ndarray,
    sample_rate: int = 48000,
    max_lag: int = 2000,
) -> Tuple[int, float, float]:
    """
    Find sample lag in [-max_lag, +max_lag] aligning stems to original via O(N) FFT
    cross-correlation and O(1)-per-lag cumulative sliding window norm.
    """
    n_tot = min(len(orig), len(stem_sum))
    center = min(20 * sample_rate, n_tot // 2)
    win = min(4 * sample_rate, max(sample_rate, n_tot - 2 * max_lag - 1024))
    ref_start = max(max_lag + 64, min(center, n_tot - win - max_lag - 64))

    o_mono = orig[ref_start : ref_start + win].mean(axis=1).astype(np.float64)
    o_norm = o_mono / (np.linalg.norm(o_mono) + 1e-12)
    s_search = stem_sum[ref_start - max_lag : ref_start + win + max_lag].mean(axis=1).astype(np.float64)

    n_fft = next_fast_fft_len(len(s_search) + len(o_norm))
    cc = np.fft.irfft(np.fft.rfft(s_search, n=n_fft) * np.conj(np.fft.rfft(o_norm, n=n_fft)), n=n_fft)

    m = min(2 * max_lag + 1, len(s_search) - win + 1)
    if m <= 0:
        return 0, 0.0, 0.0

    sq = s_search * s_search
    csum = np.empty(len(sq) + 1, dtype=np.float64)
    csum[0] = 0.0
    np.cumsum(sq, out=csum[1:])

    win_energy = np.maximum(csum[win : win + m] - csum[:m], 0.0)
    norms = np.sqrt(win_energy) + 1e-12
    corrs = cc[:m] / norms

    best_idx = int(np.argmax(corrs))
    best_lag = best_idx - max_lag
    zero_idx = min(max_lag, m - 1)
    corr_zero = float(corrs[zero_idx])
    best_corr = float(corrs[best_idx])
    return best_lag, round(corr_zero, 4), round(best_corr, 4)


def detect_spine_downbeat(
    drums: np.ndarray,
    bass: np.ndarray,
    bar_sec: float,
    sample_rate: int = 48000,
    min_start_sec: float = 0.0,
    prefer_earlier_if_close: bool = True,
) -> float:
    """
    Locate the cleanest Bar-1 downbeat anchor after any drumless intro using O(N)
    cumulative squared energy and vectorized 2D bar-grid scoring.
    """
    groove_mono = (drums + 0.5 * bass).mean(axis=1).astype(np.float64)
    drm_mono = drums.mean(axis=1).astype(np.float64)
    dur_sec = len(drm_mono) / float(sample_rate)
    n_secs = max(1, int(dur_sec))

    if len(drm_mono) >= n_secs * sample_rate:
        sec_blocks = drm_mono[: n_secs * sample_rate].reshape(n_secs, sample_rate)
        sec_rms = np.sqrt(np.mean(sec_blocks * sec_blocks, axis=1) + 1e-12)
    else:
        sec_rms = np.array(
            [
                float(np.sqrt(np.mean(drm_mono[s * sample_rate : (s + 1) * sample_rate] ** 2) + 1e-12))
                for s in range(n_secs)
            ],
            dtype=np.float64,
        )

    active_vals = sec_rms[sec_rms > 0.005]
    med_drm = float(np.median(active_vals)) if len(active_vals) > 0 else 0.02
    enter_sec = float(min_start_sec)
    for s in range(int(min_start_sec), n_secs):
        if sec_rms[s] >= 0.35 * med_drm:
            enter_sec = float(s)
            break

    max_search_bars = min(12, max(4, int((dur_sec - enter_sec - bar_sec) // bar_sec)))
    win = int(round(0.035 * sample_rate))
    steps = max(40, int(round(bar_sec * 400.0)))

    gsq = groove_mono * groove_mono
    gcsum = np.empty(len(gsq) + 1, dtype=np.float64)
    gcsum[0] = 0.0
    np.cumsum(gsq, out=gcsum[1:])

    k_axis = np.arange(steps, dtype=np.float64)[:, None]
    b_axis = np.arange(max_search_bars, dtype=np.float64)[None, :]
    t0_arr = enter_sec + (k_axis / float(steps)) * float(bar_sec)
    p_grid = np.rint((t0_arr + b_axis * float(bar_sec)) * float(sample_rate)).astype(np.int64)

    n_groove = len(groove_mono)
    valid = (p_grid >= 0) & (p_grid + win < n_groove)
    safe_p = np.where(valid, p_grid, 0)
    win_rms = np.sqrt(np.maximum(gcsum[safe_p + win] - gcsum[safe_p], 0.0) / float(max(1, win)) + 1e-12)
    scores = np.sum(np.where(valid, win_rms, 0.0), axis=1)

    best_idx = int(np.argmax(scores))
    best_t = float(t0_arr[best_idx, 0]) if len(scores) > 0 else enter_sec

    if prefer_earlier_if_close:
        while best_t - bar_sec >= max(0.05, enter_sec - 0.35):
            p_prev = int(round((best_t - bar_sec) * sample_rate))
            if p_prev >= 0 and p_prev + win <= len(drm_mono) and np.sqrt(np.mean(drm_mono[p_prev : p_prev + win] ** 2)) >= 0.35 * med_drm:
                best_t -= bar_sec
            else:
                break

    return round(best_t, 4)


def zero_phase_filter(
    src: np.ndarray,
    start_idx: int,
    end_idx: int,
    cutoff_hz: float,
    mode: str = "lowpass",
    sr: int = 48000,
) -> np.ndarray:
    """
    Pure real-FFT zero-phase 2nd-order Butterworth filter on src[start_idx:end_idx]
    with 0.5s padded context and 5-smooth FFT length padding so PocketFFT never hits
    slow prime-factor paths while remaining numerically equivalent to direct rfft.
    """
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

    n_fft = next_fast_fft_len(len(buf))
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sr))
    fc = float(cutoff_hz)
    if mode == "lowpass":
        mag = 1.0 / np.sqrt(1.0 + (freqs / fc) ** 4)
    elif mode == "highpass":
        safe_f = np.maximum(freqs, 1.0)
        mag = 1.0 / np.sqrt(1.0 + (fc / safe_f) ** 4)
        mag[0] = 0.0
    else:
        raise ValueError(f"Unsupported filter mode: {mode}")

    spec = np.fft.rfft(buf, n=n_fft, axis=0)
    filtered = np.fft.irfft(spec * mag.astype(np.float32)[:, None], n=n_fft, axis=0).astype(np.float32)
    return filtered[pad : pad + n_seg].copy()


def compute_onset_env(mono: np.ndarray, hop: int = 120) -> np.ndarray:
    n = max(1, len(mono) // hop)
    rms = np.sqrt(np.mean(mono[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    diff = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    return (diff - float(np.mean(diff))) / float(np.std(diff) + 1e-9)


def find_best_drum_phase_offset(
    drums_a: np.ndarray,
    a_start_sec: float,
    drums_b: np.ndarray,
    b_anchor_sec: float,
    window_bars: float = 2.0,
    bar_sec: float = (60.0 * 4.0) / 124.0,
    max_shift_sec: float = 0.080,
    sample_rate: int = 48000,
) -> Tuple[float, float]:
    """
    Correlate 2.5ms-hop drum onset envelopes across [-max_shift_sec, +max_shift_sec]
    using vectorized np.correlate.
    """
    hop = 120
    win_n = int(round(window_bars * bar_sec * sample_rate))
    a0 = max(0, int(round(a_start_sec * sample_rate)))
    a_seg = drums_a[a0 : a0 + win_n].mean(axis=1)

    max_shift_n = int(round(max_shift_sec * sample_rate))
    b_mid = int(round(b_anchor_sec * sample_rate))
    b_search_start = max(0, b_mid - max_shift_n)
    b_search_end = min(len(drums_b), b_mid + win_n + max_shift_n)
    b_seg = drums_b[b_search_start:b_search_end].mean(axis=1)

    env_a = compute_onset_env(a_seg, hop=hop)
    env_b = compute_onset_env(b_seg, hop=hop)
    n_a = len(env_a)
    n_candidates = len(env_b) - n_a
    if n_candidates <= 10:
        return 0.0, 0.0

    corrs = np.correlate(env_b[: n_candidates + n_a - 1], env_a, mode="valid") / float(n_a)
    best_b_idx = int(np.argmax(corrs))
    best_corr = float(corrs[best_b_idx])

    matched_b_sample = b_search_start + best_b_idx * hop
    lag_sec = (matched_b_sample - b_mid) / float(sample_rate)
    return round(lag_sec, 4), round(best_corr, 4)


def eval_bar_curve(n_len: int, keyframes: Sequence[Tuple[float, float]], total_bars: float) -> np.ndarray:
    """Interpolate continuous parameter curve across bar keyframes using smooth raised cosine."""
    bars_axis = np.linspace(0.0, float(total_bars), n_len, endpoint=False, dtype=np.float32)
    pts = sorted(keyframes, key=lambda x: x[0])
    out = np.full(n_len, float(pts[0][1]), dtype=np.float32)

    for i in range(len(pts) - 1):
        b0, v0 = float(pts[i][0]), float(pts[i][1])
        b1, v1 = float(pts[i + 1][0]), float(pts[i + 1][1])
        if b1 <= b0:
            continue
        mask = (bars_axis >= b0) & (bars_axis <= b1)
        if np.any(mask):
            u = (bars_axis[mask] - b0) / (b1 - b0)
            s = 0.5 * (1.0 - np.cos(math.pi * u))
            out[mask] = v0 + (v1 - v0) * s

    out[bars_axis > float(pts[-1][0])] = float(pts[-1][1])
    return out[:, None]


def apply_circular_loop_wrap(audio: np.ndarray, total_samples: int, wrap_samples: int) -> np.ndarray:
    """Wrap tail overshoot onto head samples with quarter-sine equal-power crossfade."""
    out = audio[:total_samples].copy()
    w = min(wrap_samples, len(audio) - total_samples, total_samples // 4)
    if w > 0:
        tail = audio[total_samples : total_samples + w].copy()
        out[:w] = out[:w] * eq_in(w) + tail * eq_out(w)
    return out
