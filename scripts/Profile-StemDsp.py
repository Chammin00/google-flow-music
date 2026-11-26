#!/usr/bin/env python3
"""
Profile-StemDsp.py

`fast-anything` DSP profiler, equivalence verifier & benchmark suite.
Profiles the real stem DSP workload on cached stems (rom_p5_mask_75,
rom_sparkle_100_p1, rom_misia_80), compares original Python-loop implementations
against vectorized kernels in `scripts/flow_music_dsp.py`, verifies numerical
equivalence, checks Rust/fast-anything toolchain availability, and writes
exports/dsp_profile_report.json.
"""

from __future__ import annotations

import argparse
import cProfile
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import pstats
import shutil
import time
from typing import Any, Dict, List, Tuple
import wave

import numpy as np

from flow_music_dsp import (
    compute_stem_phase_lag as opt_phase_lag,
    detect_spine_downbeat as opt_downbeat,
    find_best_drum_phase_offset as opt_drum_offset,
    zero_phase_filter as opt_zero_phase_filter,
)

SAMPLE_RATE = 48000
HUB_ROOT = Path(__file__).resolve().parent.parent
STEMS_CACHE_DIR = HUB_ROOT / "exports" / "stems_cache"
REPORT_PATH = HUB_ROOT / "exports" / "dsp_profile_report.json"


def read_wav_f32_stdlib(wav_path: Path) -> np.ndarray:
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        if sr != SAMPLE_RATE:
            raise ValueError(f"Expected {SAMPLE_RATE} Hz, got {sr} Hz")
        ch = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sampwidth == 2:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")
    arr = arr.reshape(-1, ch)
    if ch == 1:
        arr = np.column_stack([arr, arr])
    return arr[:, :2].copy()


# ---- Exact baseline reference functions before vectorization ----
def base_phase_lag(orig: np.ndarray, stem_sum: np.ndarray, max_lag: int = 2000) -> Tuple[int, float, float]:
    n_tot = min(len(orig), len(stem_sum))
    center = min(20 * SAMPLE_RATE, n_tot // 2)
    win = min(4 * SAMPLE_RATE, max(SAMPLE_RATE, n_tot - 2 * max_lag - 1024))
    ref_start = max(max_lag + 64, min(center, n_tot - win - max_lag - 64))

    o_mono = orig[ref_start : ref_start + win].mean(axis=1).astype(np.float64)
    o_norm = o_mono / (np.linalg.norm(o_mono) + 1e-12)
    s_search = stem_sum[ref_start - max_lag : ref_start + win + max_lag].mean(axis=1).astype(np.float64)

    n_fft = 1 << int(math.ceil(math.log2(len(s_search) + len(o_norm))))
    cc = np.fft.irfft(np.fft.rfft(s_search, n=n_fft) * np.conj(np.fft.rfft(o_norm, n=n_fft)), n=n_fft)

    best_lag = 0
    best_corr = -1e18
    corr_zero = 0.0
    for idx in range(0, 2 * max_lag + 1):
        lag = idx - max_lag
        s_seg = s_search[idx : idx + win]
        c = float(cc[idx] / (np.linalg.norm(s_seg) + 1e-12))
        if lag == 0:
            corr_zero = c
        if c > best_corr:
            best_corr = c
            best_lag = lag
    return best_lag, round(corr_zero, 4), round(best_corr, 4)


def base_downbeat(drums: np.ndarray, bass: np.ndarray, bar_sec: float, min_start_sec: float = 0.0) -> float:
    groove_mono = (drums + 0.5 * bass).mean(axis=1)
    drm_mono = drums.mean(axis=1)
    dur_sec = len(drm_mono) / float(SAMPLE_RATE)
    n_secs = max(1, int(dur_sec))

    sec_rms = [
        float(np.sqrt(np.mean(drm_mono[s * SAMPLE_RATE : (s + 1) * SAMPLE_RATE] ** 2) + 1e-12))
        for s in range(n_secs)
    ]
    active_vals = [r for r in sec_rms if r > 0.005]
    med_drm = float(np.median(active_vals)) if active_vals else 0.02
    enter_sec = min_start_sec
    for s in range(int(min_start_sec), n_secs):
        if sec_rms[s] >= 0.35 * med_drm:
            enter_sec = float(s)
            break

    max_search_bars = min(12, max(4, int((dur_sec - enter_sec - bar_sec) // bar_sec)))
    win = int(round(0.035 * SAMPLE_RATE))
    steps = max(40, int(round(bar_sec * 400.0)))

    best_score = -1.0
    best_t = enter_sec
    for k in range(steps):
        ph = (k / float(steps)) * bar_sec
        t0 = enter_sec + ph
        sc = 0.0
        for b in range(max_search_bars):
            p = int(round((t0 + b * bar_sec) * SAMPLE_RATE))
            if p + win < len(groove_mono):
                sc += float(np.sqrt(np.mean(groove_mono[p : p + win] ** 2) + 1e-12))
        if sc > best_score:
            best_score = sc
            best_t = t0

    while best_t - bar_sec >= max(0.05, enter_sec - 0.35):
        p_prev = int(round((best_t - bar_sec) * SAMPLE_RATE))
        if p_prev >= 0 and np.sqrt(np.mean(drm_mono[p_prev : p_prev + win] ** 2)) >= 0.35 * med_drm:
            best_t -= bar_sec
        else:
            break
    return round(best_t, 4)


def base_zero_phase_filter(src: np.ndarray, start_idx: int, end_idx: int, cutoff_hz: float, mode: str = "lowpass") -> np.ndarray:
    n_seg = max(0, end_idx - start_idx)
    if n_seg == 0:
        return np.zeros((0, src.shape[1]), dtype=np.float32)
    pad = SAMPLE_RATE // 2
    ctx_start = max(0, start_idx - pad)
    ctx_end = min(len(src), end_idx + pad)
    core = src[ctx_start:ctx_end].astype(np.float32, copy=False)
    left_pad = pad - (start_idx - ctx_start)
    right_pad = pad - (ctx_end - end_idx)
    buf = np.pad(core, ((left_pad, right_pad), (0, 0)), mode="constant") if (left_pad > 0 or right_pad > 0) else core
    freqs = np.fft.rfftfreq(len(buf), d=1.0 / float(SAMPLE_RATE))
    fc = float(cutoff_hz)
    if mode == "lowpass":
        mag = 1.0 / np.sqrt(1.0 + (freqs / fc) ** 4)
    else:
        safe_f = np.maximum(freqs, 1.0)
        mag = 1.0 / np.sqrt(1.0 + (fc / safe_f) ** 4)
        mag[0] = 0.0
    spec = np.fft.rfft(buf, axis=0)
    filtered = np.fft.irfft(spec * mag.astype(np.float32)[:, None], n=len(buf), axis=0).astype(np.float32)
    return filtered[pad : pad + n_seg].copy()


def base_drum_offset(
    drums_a: np.ndarray,
    a_start_sec: float,
    drums_b: np.ndarray,
    b_anchor_sec: float,
    window_bars: float = 2.0,
    bar_sec: float = 3.2,
    max_shift_sec: float = 0.080,
) -> Tuple[float, float]:
    from flow_music_dsp import compute_onset_env

    hop = 120
    win_n = int(round(window_bars * bar_sec * SAMPLE_RATE))
    a0 = max(0, int(round(a_start_sec * SAMPLE_RATE)))
    a_seg = drums_a[a0 : a0 + win_n].mean(axis=1)
    max_shift_n = int(round(max_shift_sec * SAMPLE_RATE))
    b_mid = int(round(b_anchor_sec * SAMPLE_RATE))
    b_search_start = max(0, b_mid - max_shift_n)
    b_search_end = min(len(drums_b), b_mid + win_n + max_shift_n)
    b_seg = drums_b[b_search_start:b_search_end].mean(axis=1)

    env_a = compute_onset_env(a_seg, hop=hop)
    env_b = compute_onset_env(b_seg, hop=hop)
    n_a = len(env_a)
    if len(env_b) <= n_a + 10:
        return 0.0, 0.0

    best_corr = -1e18
    best_b_idx = (b_mid - b_search_start) // hop
    for j in range(0, len(env_b) - n_a):
        c = float(np.dot(env_a, env_b[j : j + n_a]) / n_a)
        if c > best_corr:
            best_corr = c
            best_b_idx = j
    matched_b_sample = b_search_start + best_b_idx * hop
    lag_sec = (matched_b_sample - b_mid) / float(SAMPLE_RATE)
    return round(lag_sec, 4), round(best_corr, 4)


def run_representative_workload() -> Dict[str, Any]:
    """Clean workload entry point for `fast-anything scan -- python scripts/Profile-StemDsp.py --workload-only`."""
    specs = [
        ("rom_p5_mask_75", 75.0),
        ("rom_sparkle_100_p1", 100.0),
        ("rom_misia_80", 80.0),
    ]
    outputs = []
    ref_drums = None
    for idx, (key, bpm) in enumerate(specs):
        cdir = STEMS_CACHE_DIR / key
        orig = read_wav_f32_stdlib(cdir / "original.wav")
        drums = read_wav_f32_stdlib(cdir / "drums.wav")
        bass = read_wav_f32_stdlib(cdir / "bass.wav")
        other = read_wav_f32_stdlib(cdir / "other.wav")
        vocals = read_wav_f32_stdlib(cdir / "vocals.wav")
        n = min(len(orig), len(drums), len(bass), len(other), len(vocals))
        stem_sum = drums[:n] + bass[:n] + other[:n] + vocals[:n]

        lag_info = opt_phase_lag(orig[:n], stem_sum, SAMPLE_RATE, max_lag=2000)
        bar_sec = 240.0 / bpm
        anchor = opt_downbeat(drums[:n], bass[:n], bar_sec=bar_sec, sample_rate=SAMPLE_RATE)
        hp = opt_zero_phase_filter(other[:n], 0, n, 210.0, mode="highpass", sr=SAMPLE_RATE)
        if idx == 0:
            ref_drums = drums[:n]
            offset = (0.0, 1.0)
        else:
            offset = opt_drum_offset(ref_drums, 0.0, drums[:n], anchor, window_bars=2.0, bar_sec=bar_sec)
        outputs.append({"key": key, "lag": lag_info[0], "anchor": anchor, "hp_samples": len(hp), "offset": offset})
    return {"workload": outputs}


def run_benchmark_and_equivalence() -> Dict[str, Any]:
    datasets = []
    for key, bpm in (("rom_p5_mask_75", 75.0), ("rom_sparkle_100_p1", 100.0), ("rom_misia_80", 80.0)):
        cdir = STEMS_CACHE_DIR / key
        orig = read_wav_f32_stdlib(cdir / "original.wav")
        drums = read_wav_f32_stdlib(cdir / "drums.wav")
        bass = read_wav_f32_stdlib(cdir / "bass.wav")
        other = read_wav_f32_stdlib(cdir / "other.wav")
        vocals = read_wav_f32_stdlib(cdir / "vocals.wav")
        n = min(len(orig), len(drums), len(bass), len(other), len(vocals))
        datasets.append({
            "key": key,
            "bpm": bpm,
            "bar_sec": 240.0 / bpm,
            "orig": orig[:n],
            "drums": drums[:n],
            "bass": bass[:n],
            "other": other[:n],
            "stem_sum": drums[:n] + bass[:n] + other[:n] + vocals[:n],
        })

    # Profile Baseline vs Optimized across the 3 cached stems
    pr_base = cProfile.Profile()
    t0 = time.perf_counter()
    pr_base.enable()
    base_results = {}
    for ds in datasets:
        k = ds["key"]
        lag = base_phase_lag(ds["orig"], ds["stem_sum"])
        anc = base_downbeat(ds["drums"], ds["bass"], ds["bar_sec"])
        filt = base_zero_phase_filter(ds["other"], 0, len(ds["other"]), 210.0, mode="highpass")
        off = base_drum_offset(datasets[0]["drums"], 0.0, ds["drums"], anc, bar_sec=ds["bar_sec"])
        base_results[k] = (lag, anc, filt, off)
    pr_base.disable()
    base_total_ms = (time.perf_counter() - t0) * 1000.0

    pr_opt = cProfile.Profile()
    t1 = time.perf_counter()
    pr_opt.enable()
    opt_results = {}
    for ds in datasets:
        k = ds["key"]
        lag = opt_phase_lag(ds["orig"], ds["stem_sum"], SAMPLE_RATE, max_lag=2000)
        anc = opt_downbeat(ds["drums"], ds["bass"], ds["bar_sec"], sample_rate=SAMPLE_RATE)
        filt = opt_zero_phase_filter(ds["other"], 0, len(ds["other"]), 210.0, mode="highpass", sr=SAMPLE_RATE)
        off = opt_drum_offset(datasets[0]["drums"], 0.0, ds["drums"], anc, bar_sec=ds["bar_sec"], sample_rate=SAMPLE_RATE)
        opt_results[k] = (lag, anc, filt, off)
    pr_opt.disable()
    opt_total_ms = (time.perf_counter() - t1) * 1000.0

    # Per-function isolated timings on rom_p5_mask_75 (80s stem) + equivalence checks
    ds0 = datasets[0]
    fn_benchmarks: List[Dict[str, Any]] = []

    tb0 = time.perf_counter(); bl = base_phase_lag(ds0["orig"], ds0["stem_sum"]); tb1 = time.perf_counter()
    ol = opt_phase_lag(ds0["orig"], ds0["stem_sum"], SAMPLE_RATE, max_lag=2000); tb2 = time.perf_counter()
    assert bl[0] == ol[0] and abs(bl[1] - ol[1]) <= 1e-4 and abs(bl[2] - ol[2]) <= 1e-4, f"phase lag mismatch {bl} vs {ol}"
    fn_benchmarks.append({
        "function": "compute_stem_phase_lag",
        "baseline_ms": round((tb1 - tb0) * 1000.0, 2),
        "optimized_ms": round((tb2 - tb1) * 1000.0, 2),
        "speedup_x": round((tb1 - tb0) / max(1e-6, (tb2 - tb1)), 2),
        "equivalence": f"exact lag={ol[0]} diff=0, corr_diff={abs(bl[2]-ol[2]):.6f}",
    })

    tb0 = time.perf_counter(); ba = base_downbeat(ds0["drums"], ds0["bass"], ds0["bar_sec"]); tb1 = time.perf_counter()
    oa = opt_downbeat(ds0["drums"], ds0["bass"], ds0["bar_sec"], sample_rate=SAMPLE_RATE); tb2 = time.perf_counter()
    assert abs(ba - oa) <= 0.0001, f"downbeat mismatch {ba} vs {oa}"
    fn_benchmarks.append({
        "function": "detect_spine_downbeat",
        "baseline_ms": round((tb1 - tb0) * 1000.0, 2),
        "optimized_ms": round((tb2 - tb1) * 1000.0, 2),
        "speedup_x": round((tb1 - tb0) / max(1e-6, (tb2 - tb1)), 2),
        "equivalence": f"exact anchor={oa}s diff={abs(ba-oa):.6f}s",
    })

    tb0 = time.perf_counter(); bf = base_zero_phase_filter(ds0["other"], 0, len(ds0["other"]), 210.0, "highpass"); tb1 = time.perf_counter()
    of = opt_zero_phase_filter(ds0["other"], 0, len(ds0["other"]), 210.0, "highpass", SAMPLE_RATE); tb2 = time.perf_counter()
    max_abs = float(np.max(np.abs(bf - of)))
    rms_diff = float(np.sqrt(np.mean((bf - of) ** 2)))
    assert max_abs < 2e-4 and rms_diff < 2e-5, f"filter mismatch max_abs={max_abs} rms={rms_diff}"
    fn_benchmarks.append({
        "function": "zero_phase_filter",
        "baseline_ms": round((tb1 - tb0) * 1000.0, 2),
        "optimized_ms": round((tb2 - tb1) * 1000.0, 2),
        "speedup_x": round((tb1 - tb0) / max(1e-6, (tb2 - tb1)), 2),
        "equivalence": f"max_abs_diff={max_abs:.2e}, rms_diff={rms_diff:.2e}",
    })

    tb0 = time.perf_counter(); bo = base_drum_offset(ds0["drums"], 0.0, datasets[1]["drums"], 0.5, bar_sec=datasets[1]["bar_sec"]); tb1 = time.perf_counter()
    oo = opt_drum_offset(ds0["drums"], 0.0, datasets[1]["drums"], 0.5, bar_sec=datasets[1]["bar_sec"], sample_rate=SAMPLE_RATE); tb2 = time.perf_counter()
    assert abs(bo[0] - oo[0]) <= 1e-4 and abs(bo[1] - oo[1]) <= 1e-4, f"drum offset mismatch {bo} vs {oo}"
    fn_benchmarks.append({
        "function": "find_best_drum_phase_offset",
        "baseline_ms": round((tb1 - tb0) * 1000.0, 2),
        "optimized_ms": round((tb2 - tb1) * 1000.0, 2),
        "speedup_x": round((tb1 - tb0) / max(1e-6, (tb2 - tb1)), 2),
        "equivalence": f"exact lag_sec={oo[0]}s, corr={oo[1]}",
    })

    # Verify equivalence across ALL 3 cached stems
    for ds in datasets:
        k = ds["key"]
        bl_k, ba_k, bf_k, bo_k = base_results[k]
        ol_k, oa_k, of_k, oo_k = opt_results[k]
        assert bl_k[0] == ol_k[0]
        assert abs(ba_k - oa_k) <= 0.0001
        assert float(np.max(np.abs(bf_k - of_k))) < 2e-4
        assert abs(bo_k[0] - oo_k[0]) <= 1e-4

    s_base = io.StringIO()
    pstats.Stats(pr_base, stream=s_base).sort_stats("cumtime").print_stats(12)
    s_opt = io.StringIO()
    pstats.Stats(pr_opt, stream=s_opt).sort_stats("cumtime").print_stats(12)

    cargo_path = shutil.which("cargo")
    fast_cli_path = shutil.which("fast-anything")

    report = {
        "schema": "flow-music-dsp-profile/1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "cached_stems_tested": [ds["key"] for ds in datasets],
        "overall_3_stem_dsp": {
            "baseline_ms": round(base_total_ms, 2),
            "optimized_ms": round(opt_total_ms, 2),
            "speedup_x": round(base_total_ms / max(1e-6, opt_total_ms), 2),
        },
        "kernel_benchmarks": fn_benchmarks,
        "all_equivalence_assertions_passed": True,
        "toolchain": {
            "cargo_installed": bool(cargo_path),
            "fast_anything_cli_installed": bool(fast_cli_path),
            "pure_module_ready": str(HUB_ROOT / "scripts" / "flow_music_dsp.py"),
            "install_and_port_commands": [
                "winget install Rustlang.Rustup",
                "npm install -g @el4cteo/fast-anything",
                "fast-anything scan -- python scripts/Profile-StemDsp.py --workload-only",
                "fast-anything port <id>",
                "fast-anything verify <id> && fast-anything enable <id>",
            ],
        },
        "cprofile_baseline_top": s_base.getvalue().splitlines()[:18],
        "cprofile_optimized_top": s_opt.getvalue().splitlines()[:18],
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile & benchmark Google Flow Music pure DSP kernels")
    parser.add_argument("--workload-only", action="store_true", help="Run clean DSP workload for fast-anything scan")
    args = parser.parse_args()

    if args.workload_only:
        res = run_representative_workload()
        print(json.dumps(res, indent=2))
    else:
        rep = run_benchmark_and_equivalence()
        print(
            json.dumps(
                {
                    "status": "ok",
                    "report": str(REPORT_PATH),
                    "overall_3_stem_dsp": rep["overall_3_stem_dsp"],
                    "kernel_benchmarks": rep["kernel_benchmarks"],
                    "all_equivalence_assertions_passed": rep["all_equivalence_assertions_passed"],
                    "toolchain": {
                        "cargo_installed": rep["toolchain"]["cargo_installed"],
                        "fast_anything_cli_installed": rep["toolchain"]["fast_anything_cli_installed"],
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
