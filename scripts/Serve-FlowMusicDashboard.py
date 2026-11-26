#!/usr/bin/env python3
"""
Serve-FlowMusicDashboard.py

Lightweight local HTTP audition & catalog server for Google Flow Music (exports/hits/).
Supports RFC 7233 Byte-Range audio streaming (206 Partial Content), live SHA-256
deployment verification, one-click Sync Bridge triggers, and catalog refreshes.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import webbrowser

HUB_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = HUB_ROOT / "dashboard"
CATALOG_JSON = DASHBOARD_DIR / "hits_catalog.json"
HITS_DIR = (HUB_ROOT / "exports" / "hits").resolve()
CONFIG_PATH = HUB_ROOT / "config" / "project-targets.json"
BRIDGE_PS1 = HUB_ROOT / "scripts" / "Sync-FlowMusicBridge.ps1"

ALLOWED_ASSETS = {
    "styles.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "index.html": "text/html; charset=utf-8",
}


def load_catalog_builder() -> Any:
    mod_path = HUB_ROOT / "scripts" / "Build-HitsDashboardCatalog.py"
    spec = importlib.util.spec_from_file_location("build_hits_catalog", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {mod_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compute_live_sync_status() -> Dict[str, Any]:
    builder = load_catalog_builder()
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rom_dir = Path(cfg["targets"]["rom_studio_3d"]["path"])
    dc13_dir = Path(cfg["targets"]["dead_channel_13"]["path"])

    rom_items = []
    for zone, slug in (
        ("action", "rom01-palace-shorts-hook"),
        ("palace", "rom02-velvet-palace-longform"),
        ("vault", "rom03-console-vault-bgm"),
    ):
        src = HITS_DIR / f"{slug}.mp3"
        src_sha = builder.sha256_file(src) if src.is_file() else ""
        st = builder.check_deploy_status(slug, src_sha, rom_dir, dc13_dir)
        rom_items.append({"slug": slug, "zone": zone, "in_sync": st["in_sync"], "exists": st["exists"]})

    dc_items = []
    for slug in ("yyh01-sunset-credits-suite", "yyh02-spirit-detective-chill"):
        src = HITS_DIR / f"{slug}.mp3"
        src_sha = builder.sha256_file(src) if src.is_file() else ""
        st = builder.check_deploy_status(slug, src_sha, rom_dir, dc13_dir)
        dc_items.append({"slug": slug, "in_sync": st["in_sync"], "exists": st["exists"]})

    return {
        "rom_studio_3d": {
            "synced": sum(1 for x in rom_items if x["in_sync"]),
            "total": len(rom_items),
            "manifest_exists": (rom_dir / "bgm_manifest.json").is_file(),
            "tracks": rom_items,
        },
        "dead_channel_13": {
            "synced": sum(1 for x in dc_items if x["in_sync"]),
            "total": len(dc_items),
            "manifest_exists": (dc13_dir / "credits_teasers_manifest.json").is_file(),
            "tracks": dc_items,
        },
    }


def parse_range_header(range_header: str, file_size: int) -> Optional[Tuple[int, int]]:
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not m:
        return None
    s_raw, e_raw = m.group(1), m.group(2)
    if s_raw == "" and e_raw == "":
        return None
    if s_raw == "":
        # Suffix byte range: last N bytes
        suffix = int(e_raw)
        if suffix <= 0:
            return None
        start = max(0, file_size - suffix)
        return start, file_size - 1
    start = int(s_raw)
    end = int(e_raw) if e_raw else file_size - 1
    if start >= file_size or end < start:
        return None
    return start, min(end, file_size - 1)


class FlowDashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, code: int, payload: Dict[str, Any]) -> None:
        raw = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _send_bytes(self, code: int, content_type: str, body: bytes, cache: str = "no-cache") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            index_file = DASHBOARD_DIR / "index.html"
            if not index_file.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "dashboard/index.html missing"})
                return
            self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", index_file.read_bytes())
            return

        if path.startswith("/assets/"):
            rel = path[len("/assets/") :]
            if rel not in ALLOWED_ASSETS:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Asset not found"})
                return
            asset_file = DASHBOARD_DIR / rel
            if not asset_file.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Missing {rel}"})
                return
            self._send_bytes(HTTPStatus.OK, ALLOWED_ASSETS[rel], asset_file.read_bytes())
            return

        if path == "/api/catalog":
            refresh = qs.get("refresh", ["0"])[0] == "1"
            if refresh or not CATALOG_JSON.is_file():
                builder = load_catalog_builder()
                data = builder.build_catalog(CATALOG_JSON)
                self._send_json(HTTPStatus.OK, data)
                return
            data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
            self._send_json(HTTPStatus.OK, data)
            return

        if path == "/api/sync-status":
            self._send_json(HTTPStatus.OK, compute_live_sync_status())
            return

        if path.startswith("/audio/"):
            fname = path[len("/audio/") :]
            if "/" in fname or "\\" in fname or not fname.lower().endswith(".mp3"):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid audio name"})
                return
            target = (HITS_DIR / fname).resolve()
            if target.parent != HITS_DIR or not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Audio file not found"})
                return
            self._serve_mp3_with_range(target)
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _serve_mp3_with_range(self, file_path: Path) -> None:
        size = file_path.stat().st_size
        range_hdr = self.headers.get("Range")
        try:
            if range_hdr:
                parsed = parse_range_header(range_hdr, size)
                if parsed is None:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start, end = parsed
                length = end - start + 1
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with file_path.open("rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            else:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with file_path.open("rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/sync":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"})
            return

        length = int(self.headers.get("Content-Length") or "0")
        body: Dict[str, Any] = {}
        if length > 0:
            raw = self.rfile.read(min(length, 65536)).decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
                return

        target = str(body.get("target") or "All")
        if target not in ("All", "RomStudio", "DeadChannel13"):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid target; expected All, RomStudio, or DeadChannel13"})
            return
        force = bool(body.get("force", False))

        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(BRIDGE_PS1),
            "-Target",
            target,
            "-OutputJson",
        ]
        if force:
            cmd.append("-Force")

        proc = subprocess.run(cmd, cwd=str(HUB_ROOT), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"status": "error", "stderr": proc.stderr.strip(), "stdout": proc.stdout.strip()},
            )
            return

        bridge_result = json.loads(proc.stdout)
        builder = load_catalog_builder()
        catalog = builder.build_catalog(CATALOG_JSON)
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "bridge": bridge_result,
                "sync_summary": catalog["sync_summary"],
            },
        )


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Google Flow Music Audition & Catalog Dashboard")
    parser.add_argument("--port", type=int, default=8787, help="TCP port on 127.0.0.1")
    parser.add_argument("--no-browser", action="store_true", help="Do not launch browser automatically")
    args = parser.parse_args()

    if not CATALOG_JSON.is_file():
        load_catalog_builder().build_catalog(CATALOG_JSON)

    server = ExclusiveThreadingHTTPServer(("127.0.0.1", args.port), FlowDashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(json.dumps({"status": "listening", "url": url, "port": args.port}), flush=True)

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
