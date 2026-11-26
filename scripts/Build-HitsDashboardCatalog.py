#!/usr/bin/env python3
"""
Build-HitsDashboardCatalog.py

Scans all MP3 tracks in exports/hits/, joins vault/catalog.json & track.json metadata,
runs ffprobe + FFmpeg loudnorm (-14.5 LUFS reference) + 120-bin RMS waveform extraction,
verifies SHA-256 deployment status in 3D ROM Studio & DEAD CHANNEL 13, and writes
dashboard/hits_catalog.json (UTF-8 without BOM).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List

import numpy as np

HUB_ROOT = Path(__file__).resolve().parent.parent
HITS_DIR = HUB_ROOT / "exports" / "hits"
VAULT_DIR = HUB_ROOT / "vault"
CONFIG_PATH = HUB_ROOT / "config" / "project-targets.json"
DASHBOARD_DIR = HUB_ROOT / "dashboard"
DEFAULT_OUT = DASHBOARD_DIR / "hits_catalog.json"

WAVEFORM_BINS = 120


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def probe_mp3(path: Path) -> Dict[str, Any]:
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate,channels,bit_rate:format=duration,size,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    info = json.loads(raw)
    stream = info["streams"][0]
    fmt = info["format"]
    return {
        "duration_sec": round(float(fmt["duration"]), 3),
        "size_bytes": int(fmt["size"]),
        "sample_rate": int(stream.get("sample_rate") or 48000),
        "channels": int(stream.get("channels") or 2),
        "bit_rate": int(stream.get("bit_rate") or fmt.get("bit_rate") or 320000),
    }


def measure_loudness(path: Path) -> Dict[str, float]:
    res = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "loudnorm=I=-14.5:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    matches = re.findall(r'\{\s*"input_i"[\s\S]*?\}', res.stderr)
    if not matches:
        raise RuntimeError(f"loudnorm JSON missing for {path.name}")
    ln = json.loads(matches[-1])
    return {
        "integrated_lufs": round(float(ln["input_i"]), 2),
        "true_peak_db": round(float(ln["input_tp"]), 2),
        "lra_lu": round(float(ln["input_lra"]), 2),
    }


def extract_waveform_peaks(path: Path, num_bins: int = WAVEFORM_BINS) -> List[float]:
    res = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    pcm = np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if len(pcm) < num_bins:
        return [0.25] * num_bins
    # Trim evenly into num_bins chunks for fast vectorized RMS
    usable = (len(pcm) // num_bins) * num_bins
    blocks = pcm[:usable].reshape(num_bins, -1)
    rms = np.sqrt(np.mean(blocks * blocks, axis=1) + 1e-12)
    peak = float(np.max(rms)) if np.max(rms) > 1e-6 else 1.0
    norm = np.clip(rms / peak, 0.05, 1.0)
    return [round(float(v), 3) for v in norm]


def classify_track(slug: str) -> Dict[str, str]:
    if slug.startswith("rom"):
        return {"category": "rom_suite", "category_label": "3D ROM Suite"}
    if slug.startswith("yyh"):
        return {"category": "yyh_credits", "category_label": "YYH Credits & Teasers"}
    if slug.startswith("chill"):
        return {"category": "chill_tokyo", "category_label": "Chill Tokyo"}
    if slug.startswith("hit"):
        return {"category": "anime_hits", "category_label": "Anime Hits"}
    return {"category": "other", "category_label": "Other"}


def compute_invideo_metadata(slug: str, duration_sec: float, synth_verified: bool) -> Dict[str, Any]:
    rights_badge = "COMMERCIAL READY" if synth_verified else "REFERENCE PREVIEW (SWAP BEFORE MONETIZING)"
    if slug == "rom01-palace-shorts-hook":
        return {
            "bus": "BUS_MUSIC",
            "duck_db": -11.0,
            "cue_windows": [
                {"label": "Action Arena Loop & YT Shorts Hook", "start_sec": 0.0, "end_sec": 28.8, "start_f24": 0, "end_f24": 691}
            ],
            "youtube_role": "High-CTR YouTube Shorts 9:16 hook + 3D ROM Studio Action Arena BGM",
            "hook_guidance": "Drop vocal/FX hit on Beat 1 (100 BPM); duck -11 dB behind Shorts captions.",
            "rights_badge": rights_badge,
        }
    if slug == "rom02-velvet-palace-longform":
        return {
            "bus": "BUS_MUSIC",
            "duck_db": -11.0,
            "cue_windows": [
                {"label": "Full 60-Bar Circular Longform Bed", "start_sec": 0.0, "end_sec": duration_sec, "start_f24": 0, "end_f24": round(duration_sec * 24)}
            ],
            "youtube_role": "Long-form gaming commentary bed + 3D ROM Studio Palace Rotunda BGM",
            "hook_guidance": "Warm unbroken 75 BPM pocket sits cleanly beneath dialogue with -11 dB sidechain.",
            "rights_badge": rights_badge,
        }
    if slug == "rom03-console-vault-bgm":
        return {
            "bus": "BUS_MUSIC",
            "duck_db": -11.0,
            "cue_windows": [
                {"label": "Console Wings Loop (40 Bars)", "start_sec": 0.0, "end_sec": duration_sec, "start_f24": 0, "end_f24": round(duration_sec * 24)}
            ],
            "youtube_role": "3D ROM Studio Console Wings & PC Lounge menu BGM (N64/PS2 chill)",
            "hook_guidance": "Nostalgic 80 BPM pocket; safe infinite loop across menu browsing.",
            "rights_badge": rights_badge,
        }
    if slug == "yyh01-sunset-credits-suite":
        return {
            "bus": "BUS_MUSIC",
            "duck_db": -11.0,
            "cue_windows": [
                {"label": "Dead Channel 13 Ep 01 Credits", "start_sec": 0.0, "end_sec": 48.0, "start_f24": 0, "end_f24": 1152},
                {"label": "Dead Channel 13 Ep 02 Credits", "start_sec": 86.2, "end_sec": 134.2, "start_f24": 2069, "end_f24": 3221},
            ],
            "youtube_role": "90s anime ending credits suite & verbal/visual End-Screen bridge bed",
            "hook_guidance": "Warm 1.5s LPF dissolve out of episode climax; keeps viewers through End-Screen card.",
            "rights_badge": rights_badge,
        }
    if slug == "yyh02-spirit-detective-chill":
        return {
            "bus": "BUS_MUSIC",
            "duck_db": -11.0,
            "cue_windows": [
                {"label": "Midnight Teaser / Recap Cut (30s)", "start_sec": 0.0, "end_sec": 30.0, "start_f24": 0, "end_f24": 720}
            ],
            "youtube_role": "DEAD CHANNEL 13 late-night recap / Episode 03 dialogue underscore",
            "hook_guidance": "Instrumental 82 BPM bed leaves clean midband room for Japanese voice dialogue.",
            "rights_badge": rights_badge,
        }
    return {
        "bus": "BUS_MUSIC",
        "duck_db": -11.0,
        "cue_windows": [
            {"label": "Featured Preview Cut", "start_sec": 0.0, "end_sec": round(min(30.0, duration_sec), 3), "start_f24": 0, "end_f24": round(min(30.0, duration_sec) * 24)}
        ],
        "youtube_role": "Google Flow Music showcase blend / reference mix for original Beat generation",
        "hook_guidance": "Audition loop feel before generating 100% original commercial variant via Flow Music prompt.",
        "rights_badge": rights_badge,
    }


def check_deploy_status(
    slug: str,
    src_sha: str,
    rom_bgm_dir: Path,
    dc13_dir: Path,
) -> Dict[str, Any]:
    rom_zones = {
        "rom01-palace-shorts-hook": "action",
        "rom02-velvet-palace-longform": "palace",
        "rom03-console-vault-bgm": "vault",
    }
    if slug in rom_zones:
        dst = rom_bgm_dir / f"{slug}.mp3"
        exists = dst.is_file()
        in_sync = exists and (sha256_file(dst) == src_sha)
        return {
            "target_key": "rom_studio_3d",
            "target_label": f"3D ROM Studio ({rom_zones[slug]})",
            "dest_path": str(dst),
            "exists": exists,
            "in_sync": in_sync,
        }

    if slug in ("yyh01-sunset-credits-suite", "yyh02-spirit-detective-chill"):
        wav_dst = dc13_dir / f"{slug}.wav"
        prev_dst = dc13_dir / "previews" / f"{slug}.mp3"
        wav_exists = wav_dst.is_file()
        prev_exists = prev_dst.is_file()
        prev_sync = prev_exists and (sha256_file(prev_dst) == src_sha)
        return {
            "target_key": "dead_channel_13",
            "target_label": "Dead Channel 13 (WAV + Preview)",
            "dest_path": str(wav_dst),
            "preview_path": str(prev_dst),
            "exists": wav_exists and prev_exists,
            "in_sync": wav_exists and prev_sync,
        }

    return {
        "target_key": "hub_only",
        "target_label": "Hub Vault Only",
        "dest_path": "",
        "exists": True,
        "in_sync": True,
    }


def build_catalog(output_path: Path = DEFAULT_OUT) -> Dict[str, Any]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    targets_cfg = cfg["targets"]
    rom_bgm_dir = Path(targets_cfg["rom_studio_3d"]["path"])
    dc13_dir = Path(targets_cfg["dead_channel_13"]["path"])

    vault_catalog_map: Dict[str, Any] = {}
    cat_path = VAULT_DIR / "catalog.json"
    if cat_path.is_file():
        vc = json.loads(cat_path.read_text(encoding="utf-8-sig"))
        for item in vc.get("tracks", []):
            vault_catalog_map[item["slug"]] = item

    mp3_files = sorted(HITS_DIR.glob("*.mp3"), key=lambda p: p.name.lower())
    tracks: List[Dict[str, Any]] = []

    for mp3 in mp3_files:
        slug = mp3.stem
        vmeta: Dict[str, Any] = {}
        tjson = VAULT_DIR / slug / "track.json"
        if tjson.is_file():
            vmeta = json.loads(tjson.read_text(encoding="utf-8-sig"))
        elif slug in vault_catalog_map:
            vmeta = vault_catalog_map[slug]

        probe = probe_mp3(mp3)
        loud = measure_loudness(mp3)
        peaks = extract_waveform_peaks(mp3, WAVEFORM_BINS)
        sha = sha256_file(mp3)

        bpm = float(vmeta.get("bpm") or 0.0)
        bar_sec = round(240.0 / bpm, 4) if bpm > 0 else 0.0
        cat = classify_track(slug)
        synth_verified = bool(vmeta.get("synthIdVerified", False))
        deploy = check_deploy_status(slug, sha, rom_bgm_dir, dc13_dir)

        tracks.append(
            {
                "slug": slug,
                "title": str(vmeta.get("title") or slug),
                "artist": str(vmeta.get("artist") or "Chase (@chaseham00) / Google Flow Music"),
                "category": cat["category"],
                "category_label": cat["category_label"],
                "bpm": bpm,
                "bar_sec": bar_sec,
                "key": str(vmeta.get("key") or "Unknown"),
                "time_signature": str(vmeta.get("timeSignature") or "4/4"),
                "genre": str(vmeta.get("genre") or ""),
                "moods": list(vmeta.get("moods") or []),
                "instrumental": bool(vmeta.get("instrumental", False)),
                "loopable": bool(vmeta.get("loopable", False)),
                "license_tier": str(vmeta.get("licenseTier") or ""),
                "synth_id_verified": synth_verified,
                "targets": list(vmeta.get("targets") or []),
                "cue_notes": str(vmeta.get("cueNotes") or ""),
                "audio_url": f"/audio/{mp3.name}",
                "file_name": mp3.name,
                "source_path": str(mp3),
                "sha256": sha,
                "duration_sec": probe["duration_sec"],
                "frames_24fps": int(round(probe["duration_sec"] * 24.0)),
                "sample_rate": probe["sample_rate"],
                "channels": probe["channels"],
                "bit_rate": probe["bit_rate"],
                "size_bytes": probe["size_bytes"],
                "integrated_lufs": loud["integrated_lufs"],
                "true_peak_db": loud["true_peak_db"],
                "lra_lu": loud["lra_lu"],
                "waveform_peaks": peaks,
                "deployment": deploy,
                "invideo": compute_invideo_metadata(slug, probe["duration_sec"], synth_verified),
            }
        )

    rom_synced = sum(1 for t in tracks if t["deployment"]["target_key"] == "rom_studio_3d" and t["deployment"]["in_sync"])
    dc13_synced = sum(1 for t in tracks if t["deployment"]["target_key"] == "dead_channel_13" and t["deployment"]["in_sync"])
    avg_lufs = round(sum(t["integrated_lufs"] for t in tracks) / max(1, len(tracks)), 2)

    catalog = {
        "schema": "flow-music-hits-dashboard/1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hits_dir": str(HITS_DIR),
        "track_count": len(tracks),
        "avg_lufs": avg_lufs,
        "loopable_count": sum(1 for t in tracks if t["loopable"]),
        "sync_summary": {
            "rom_studio_3d": {"synced": rom_synced, "total": 3},
            "dead_channel_13": {"synced": dc13_synced, "total": 2},
        },
        "tracks": tracks,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dashboard/hits_catalog.json for Google Flow Music hits.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path")
    args = parser.parse_args()
    cat = build_catalog(Path(args.out))
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.out),
                "track_count": cat["track_count"],
                "avg_lufs": cat["avg_lufs"],
                "loopable_count": cat["loopable_count"],
                "sync_summary": cat["sync_summary"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
