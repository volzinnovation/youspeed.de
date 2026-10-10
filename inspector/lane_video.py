"""Loopback-only decoded dashcam frames for the lane annotation editor."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from uuid import uuid4


class VideoError(Exception):
    def __init__(self, message, status=422):
        self.status = status
        super().__init__(message)


class LaneVideos:
    MAX_UPLOAD = 16 * 1024**3
    MAX_FRAMES = 1_000_000
    FORMATS = "mov,matroska,avi,mpegts"

    def __init__(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise VideoError("Spurannotation benötigt lokale ffmpeg- und ffprobe-Programme.", 503)
        try:
            for program in ("ffmpeg", "ffprobe"):
                subprocess.run([program, "-version"], capture_output=True, timeout=10, check=True)
        except (subprocess.SubprocessError, OSError):
            raise VideoError("Lokale FFmpeg-Installation startet nicht. ffmpeg -version und ffprobe -version prüfen.", 503) from None
        self.temp = tempfile.TemporaryDirectory(prefix="youspeed-lane-videos-")
        self.sessions = {}
        self.lock = threading.Lock()

    def close(self):
        self.temp.cleanup()

    def upload(self, stream, length, name):
        if not 0 < length <= self.MAX_UPLOAD:
            raise VideoError("Video muss zwischen 1 Byte und 16 GiB groß sein.", 413)
        with self.lock:
            for token, item in list(self.sessions.items()):
                if time.monotonic() - item["used"] > 7200:
                    shutil.rmtree(item["directory"], ignore_errors=True)
                    del self.sessions[token]
            if len(self.sessions) >= 4:
                raise VideoError("Vier Videos geöffnet. Ein Video schließen oder Server neu starten.", 429)
            if shutil.disk_usage(self.temp.name).free < length + 256 * 1024**2:
                raise VideoError("Nicht genügend temporärer Speicher für das Video.", 507)
            token = uuid4().hex
            directory = Path(self.temp.name) / token
            directory.mkdir(mode=0o700)
            # Reserve a slot before accepting another simultaneous upload.
            item = {"directory": directory, "used": time.monotonic(), "lock": threading.Lock()}
            self.sessions[token] = item
        try:
            path = directory / "source.video"
            digest = hashlib.sha256()
            with path.open("wb") as output:
                remaining = length
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise VideoError("Videoübertragung abgebrochen.", 400)
                    output.write(block)
                    digest.update(block)
                    remaining -= len(block)
            result = subprocess.run([
                "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", self.FORMATS, "-select_streams", "v:0",
                "-show_frames", "-show_streams", "-show_entries",
                "frame=best_effort_timestamp,key_frame,width,height:stream=time_base,width,height:stream_side_data=rotation",
                "-of", "json", str(path),
            ], capture_output=True, timeout=600, check=True)
            data = json.loads(result.stdout)
            video = data["streams"][0]
            numerator, denominator = map(int, video["time_base"].split("/"))
            if not 0 < numerator <= denominator:
                raise ValueError("time base")
            frames = data["frames"]
            if not 0 < len(frames) <= self.MAX_FRAMES:
                raise ValueError("frame count")
            pts = [int(frame["best_effort_timestamp"]) for frame in frames]
            if any(abs(p) > 2**53 - 1 for p in pts) or any(b <= a for a, b in zip(pts, pts[1:])):
                raise VideoError("Frame-Zeitstempel sind nicht eindeutig aufsteigend. Video verlustfrei neu muxen.")
            width, height = int(video["width"]), int(video["height"])
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 36_000_000):
                raise ValueError("dimensions")
            if any((int(f["width"]), int(f["height"])) != (width, height) for f in frames):
                raise VideoError("Wechselnde Bildgeometrie wird nicht unterstützt.")
            rotation = next((int(s["rotation"]) % 360 for s in video.get("side_data_list", []) if "rotation" in s), 0)
            if rotation not in (0, 90, 180, 270):
                raise VideoError("Nur rechtwinklige Videoausrichtung wird unterstützt.")
            if rotation in (90, 270):
                width, height = height, width
            index = [{"index": i, "pts": str(value), "timeSeconds": (value - pts[0]) * numerator / denominator}
                     for i, value in enumerate(pts)]
            if not all(math.isfinite(f["timeSeconds"]) for f in index):
                raise ValueError("timestamps")
            source = {"id": digest.hexdigest(), "sha256": digest.hexdigest(),
                      "name": Path(name).name[:255] or "dashcam", "byteLength": length,
                      "width": width, "height": height, "timeBase": video["time_base"],
                      "startPts": str(pts[0]), "sourceRotation": rotation,
                      "transform": "ffmpeg_autorotate_full_frame", "frames": index}
            item.update(source=source, path=path)
            return {"session": token, "source": source}
        except VideoError:
            self.delete(token)
            raise
        except (subprocess.SubprocessError, ValueError, KeyError, IndexError, OSError):
            self.delete(token)
            raise VideoError("Video konnte nicht eindeutig indexiert werden. MOV/MP4, MKV, AVI oder MPEG-TS mit dekodierbaren Frames verwenden.") from None

    def delete(self, token):
        with self.lock:
            item = self.sessions.pop(token, None)
        if item:
            with item["lock"]:
                shutil.rmtree(item["directory"], ignore_errors=True)

    def frame(self, token, index):
        with self.lock:
            item = self.sessions.get(token)
            if not item or "source" not in item:
                raise VideoError("Videositzung fehlt. Video erneut öffnen.", 404)
            item["used"] = time.monotonic()
        source = item["source"]
        if not 0 <= index < len(source["frames"]):
            raise VideoError("Frame außerhalb des Videos.", 400)
        with item["lock"]:
            target = item["directory"] / f"{index}.png"
            if not target.exists():
                frame = source["frames"][index]
                common = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                          "-format_whitelist", self.FORMATS]
                # Copy original PTS through decoding and select that exact frame.
                # Input seeking only accelerates decoding; it never chooses the label's identity.
                for seek in (max(0, frame["timeSeconds"] - 2), None):
                    command = common + (["-ss", str(seek)] if seek is not None else [])
                    command += ["-copyts", "-i", str(item["path"]), "-map", "0:v:0",
                                "-vf", f"select=eq(pts\\,{frame['pts']})", "-frames:v", "1",
                                "-fps_mode", "passthrough", "-c:v", "png", "-f", "image2pipe", "pipe:1"]
                    try:
                        output = subprocess.run(command, capture_output=True, check=True, timeout=120).stdout
                    except (subprocess.SubprocessError, OSError):
                        output = b""
                    if output.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack(">II", output[16:24]) == (source["width"], source["height"]):
                        target.write_bytes(output)
                        break
                else:
                    raise VideoError("Exakter Frame konnte nicht dekodiert werden. Kein Ersatzbild wird verwendet.")
                # Keep only a small decoder cache; annotated images live in the user's dataset.
                cached = sorted(item["directory"].glob("*.png"), key=lambda p: p.stat().st_mtime)
                for old in cached[:-16]:
                    old.unlink(missing_ok=True)
            return target.read_bytes()
