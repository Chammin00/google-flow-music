#!/usr/bin/env python3
"""
Separate-TrackStems.py

Reusable Demucs (htdemucs) 4-stem + instrumental separator using FFmpeg I/O
(bypassing torchaudio/torchcodec entirely).

Outputs 48 kHz 16-bit stereo WAV files into <out-dir>:
  - drums.wav
  - bass.wav
  - other.wav
  - vocals.wav
  - instrumental.wav  (drums + bass + other, zero vocals)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model

DEMUCS_SR = 44100
OUT_SR = 48000
CHANNELS = 2
EXPECTED_FILES = ("drums.wav", "bass.wav", "other.wav", "vocals.wav", "instrumental.wav")


def decode_audio_for_demucs(input_path: Path, max_sec: float = 120.0) -> np.ndarray:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if max_sec > 0:
        cmd.extend(["-t", f"{max_sec:.3f}"])
    cmd.extend(["-i", str(input_path), "-ar", str(DEMUCS_SR), "-ac", str(CHANNELS), "-f", "f32le", "-"])

    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg decode failed for '{input_path}': {proc.stderr.decode('utf-8', errors='replace')}"
        )

    arr = np.frombuffer(proc.stdout, dtype=np.float32)
    n_samples = len(arr) // CHANNELS
    # shape (C, N) for Demucs
    return arr[: n_samples * CHANNELS].reshape((n_samples, CHANNELS)).T.copy()


def write_stem_wav(audio_ch_n: np.ndarray, out_path: Path) -> None:
    """Resamples 44.1 kHz (2, N) float32 -> 48 kHz 16-bit stereo WAV via FFmpeg."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    interleaved = np.clip(audio_ch_n.T, -0.99, 0.99).astype(np.float32)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(DEMUCS_SR),
        "-ac",
        str(CHANNELS),
        "-i",
        "-",
        "-ar",
        str(OUT_SR),
        "-ac",
        str(CHANNELS),
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, input=interleaved.tobytes(), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg encode failed for '{out_path}': {proc.stderr.decode('utf-8', errors='replace')}"
        )


def separate_track(
    input_path: Path,
    out_dir: Path,
    max_sec: float = 120.0,
    force: bool = False,
    model: Optional[Any] = None,
) -> Dict[str, Any]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input audio file not found: {input_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    if not force and all((out_dir / fname).is_file() for fname in EXPECTED_FILES):
        return {
            "status": "cached",
            "input": str(input_path),
            "out_dir": str(out_dir),
            "files": {fname.replace(".wav", ""): str(out_dir / fname) for fname in EXPECTED_FILES},
        }

    loaded_model = model if model is not None else get_model("htdemucs")
    loaded_model.cpu()
    loaded_model.eval()

    audio_np = decode_audio_for_demucs(input_path, max_sec=max_sec)
    mix_tensor = torch.from_numpy(audio_np).unsqueeze(0)  # (1, 2, N)

    with torch.no_grad():
        sources = apply_model(
            loaded_model,
            mix_tensor,
            device="cpu",
            shifts=1,
            split=True,
            overlap=0.25,
            progress=False,
        )

    sources_np = sources.squeeze(0).cpu().numpy()  # (4, 2, N)
    source_names = list(loaded_model.sources)
    stem_map: Dict[str, np.ndarray] = {}
    for idx, sname in enumerate(source_names):
        stem_map[sname] = sources_np[idx]
        write_stem_wav(sources_np[idx], out_dir / f"{sname}.wav")

    inst_mix = np.zeros_like(audio_np)
    for sname in ("drums", "bass", "other"):
        if sname in stem_map:
            inst_mix += stem_map[sname]
    write_stem_wav(inst_mix, out_dir / "instrumental.wav")

    return {
        "status": "separated",
        "input": str(input_path),
        "out_dir": str(out_dir),
        "sources": source_names,
        "duration_sec": round(audio_np.shape[1] / DEMUCS_SR, 3),
        "files": {fname.replace(".wav", ""): str(out_dir / fname) for fname in EXPECTED_FILES},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Separate audio track into Demucs htdemucs stems.")
    parser.add_argument("--input", required=True, type=Path, help="Input audio file path")
    parser.add_argument("--out-dir", required=True, type=Path, help="Destination directory for stem WAVs")
    parser.add_argument("--max-sec", type=float, default=120.0, help="Max seconds to process (0 = full file)")
    parser.add_argument("--force", action="store_true", help="Re-separate even if cached WAVs exist")
    args = parser.parse_args()

    res = separate_track(args.input, args.out_dir, max_sec=args.max_sec, force=args.force)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
