"""Background vocal/instrumental separator using Facebook Demucs.

Separates an mp3 into vocals.wav + no_vocals.wav stored in the song folder.
Uses the htdemucs model (already downloaded to ~/.cache/torch/hub/checkpoints/).

Usage:
    sep = VocalSeparator()
    sep.start(mp3_path, song_folder)   # non-blocking
    # poll sep.status / sep.progress in game loop
    if sep.stems_ready(song_folder):
        audio.load_stems(no_vocals_path, vocals_path)
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


# Status constants
IDLE        = "idle"
RUNNING     = "running"
DONE        = "done"
ERROR       = "error"
UNAVAILABLE = "unavailable"   # demucs not installed


class VocalSeparator:
    """Thread-safe background Demucs runner."""

    def __init__(self):
        self._status   : str   = IDLE
        self._progress : float = 0.0
        self._error    : str   = ""
        self._thread   : threading.Thread | None = None
        self._lock     = threading.Lock()

    # ── Public read-only props ────────────────────────────────────────────────

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def progress(self) -> float:
        with self._lock:
            return self._progress

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    # ── Query helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def stems_ready(song_folder: str) -> bool:
        """True when both wav stems exist in the song folder."""
        return (
            os.path.exists(os.path.join(song_folder, "vocals.wav")) and
            os.path.exists(os.path.join(song_folder, "no_vocals.wav"))
        )

    @staticmethod
    def vocals_path(song_folder: str) -> str:
        return os.path.join(song_folder, "vocals.wav")

    @staticmethod
    def instrumental_path(song_folder: str) -> str:
        return os.path.join(song_folder, "no_vocals.wav")

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, mp3_path: str, song_folder: str) -> None:
        """Launch background separation (no-op if already running or done)."""
        with self._lock:
            if self._status in (RUNNING, UNAVAILABLE):
                return
        # Fast path: stems already on disk
        if self.stems_ready(song_folder):
            with self._lock:
                self._status   = DONE
                self._progress = 1.0
            return
        with self._lock:
            self._status   = RUNNING
            self._progress = 0.0
            self._error    = ""
        t = threading.Thread(
            target=self._run,
            args=(mp3_path, song_folder),
            daemon=True,
            name="VocalSeparator",
        )
        t.start()
        self._thread = t

    # ── Background worker ─────────────────────────────────────────────────────

    def _run(self, mp3_path: str, song_folder: str) -> None:
        try:
            # Check demucs is importable
            import importlib.util
            if importlib.util.find_spec("demucs") is None:
                with self._lock:
                    self._status = UNAVAILABLE
                    self._error  = "demucs not installed – run: pip install demucs"
                return

            with self._lock:
                self._progress = 0.05

            tmp_dir = os.path.join(song_folder, "_demucs_tmp")
            os.makedirs(tmp_dir, exist_ok=True)

            cmd = [
                sys.executable, "-m", "demucs",
                "--two-stems", "vocals",
                "-n", "htdemucs",
                "--out", tmp_dir,
                mp3_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr[-600:] or "demucs exited non-zero")

            # Locate output: tmp_dir/htdemucs/<stem_name>/vocals.wav
            stem_name = Path(mp3_path).stem
            src_dir   = os.path.join(tmp_dir, "htdemucs", stem_name)

            vocals_src = os.path.join(src_dir, "vocals.wav")
            instr_src  = os.path.join(src_dir, "no_vocals.wav")

            if not os.path.exists(vocals_src) or not os.path.exists(instr_src):
                raise FileNotFoundError(
                    f"Expected stems not found in {src_dir}. "
                    f"Files present: {os.listdir(src_dir) if os.path.isdir(src_dir) else '(dir missing)'}"
                )

            shutil.move(vocals_src, os.path.join(song_folder, "vocals.wav"))
            shutil.move(instr_src,  os.path.join(song_folder, "no_vocals.wav"))
            shutil.rmtree(tmp_dir, ignore_errors=True)

            with self._lock:
                self._status   = DONE
                self._progress = 1.0

        except Exception as exc:
            shutil.rmtree(
                os.path.join(song_folder, "_demucs_tmp"), ignore_errors=True
            )
            with self._lock:
                self._status = ERROR
                self._error  = str(exc)
            print(f"[VocalSeparator] {exc}")
