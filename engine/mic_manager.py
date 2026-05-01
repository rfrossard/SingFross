"""Multi-player microphone manager.

Wraps up to 2 independent sounddevice InputStreams, each running their own
HPS pitch-detection callback.  Device names/indices come from the config.
"""
import threading
import numpy as np
from collections import deque
from typing import Optional

try:
    import sounddevice as sd
    _SD = True
except Exception:
    _SD = False

# ── Pitch-detection constants ────────────────────────────────────────────────
SR          = 44100
CHUNK       = 4096
HPS_H       = 2          # harmonic product spectrum depth
NOISE_FLOOR = 0.008
PITCH_LO    = 70         # Hz
PITCH_HI    = 1050       # Hz
SMOOTH      = 0.35


def _freq_to_midi(f: float) -> float:
    if f <= 0:
        return -1.0
    return 69.0 + 12.0 * np.log2(f / 440.0)


def _hps(chunk: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    if rms < NOISE_FLOOR:
        return 0.0
    win  = chunk * np.hanning(len(chunk))
    spec = np.abs(np.fft.rfft(win, n=CHUNK))
    freq = np.fft.rfftfreq(CHUNK, 1.0 / SR)
    hps  = spec.copy()
    for h in range(2, HPS_H + 1):
        ds     = spec[::h]
        length = min(len(hps), len(ds))
        hps[:length] *= ds[:length]
        hps[length:]  = 0.0
    lo = int(np.searchsorted(freq, PITCH_LO))
    hi = int(np.searchsorted(freq, PITCH_HI))
    if lo >= hi:
        return 0.0
    return float(freq[int(np.argmax(hps[lo:hi])) + lo])


def list_input_devices() -> list[dict]:
    """Return list of {index, name} dicts for all input devices."""
    if not _SD:
        return []
    devices = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                devices.append({"index": i, "name": d["name"]})
    except Exception:
        pass
    return devices


class PlayerMic:
    """Single player's microphone — pitch + volume, thread-safe."""

    def __init__(self, player_idx: int):
        self.player_idx = player_idx
        self._lock      = threading.Lock()
        self._midi      = -1.0
        self._volume    = 0.0
        self._history   = deque(maxlen=8)
        self._stream    = None
        self._active    = False

    @property
    def available(self) -> bool:
        return self._active and self._stream is not None

    # ── API ──────────────────────────────────────────────────────────────────

    @property
    def midi_note(self) -> float:
        with self._lock:
            return self._midi

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    def start(self, device=None, sensitivity: float = 1.0):
        if not _SD:
            return
        if self._active:
            self.stop()
        self._sensitivity = sensitivity
        try:
            kwargs: dict = dict(
                samplerate=SR,
                channels=1,
                dtype="float32",
                blocksize=CHUNK,
                callback=self._cb,
            )
            if device is not None:
                kwargs["device"] = device
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
            self._active = True
            print(f"[Mic P{self.player_idx+1}] Opened device {device!r}")
        except Exception as e:
            print(f"[Mic P{self.player_idx+1}] Cannot open device {device!r}: {e}")
            self._stream  = None
            self._active  = False

    def stop(self):
        self._active = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            self._midi   = -1.0
            self._volume = 0.0

    # ── Internal ─────────────────────────────────────────────────────────────

    def _cb(self, indata, frames, time_info, status):
        chunk  = indata[:, 0] * self._sensitivity
        rms    = float(np.sqrt(np.mean(chunk ** 2)))
        freq   = _hps(chunk)
        new    = _freq_to_midi(freq) if freq > 0 else -1.0
        with self._lock:
            self._volume = rms
            if new < 0:
                self._history.clear()
                self._midi = -1.0
            else:
                self._history.append(new)
                med = float(np.median(list(self._history)))
                self._midi = (med if self._midi < 0
                              else self._midi * (1 - SMOOTH) + med * SMOOTH)


class MicManager:
    """Owns up to 2 PlayerMic instances, loaded from config."""

    def __init__(self):
        self.players: list[PlayerMic] = [PlayerMic(0), PlayerMic(1)]

    def start(self, cfg):
        """Start mic(s) based on config. cfg = engine.config.Config instance."""
        two = cfg.two_player
        for i, pm in enumerate(self.players):
            if i == 0 or two:
                p      = cfg.player[i]
                device = p.get("mic_device", None)
                sens   = float(p.get("mic_sensitivity", 1.0))
                pm.start(device=device, sensitivity=sens)

    def stop(self):
        for pm in self.players:
            pm.stop()

    # ── Backwards-compat shim for code that used PitchDetector directly ─────

    @property
    def midi_note(self) -> float:
        return self.players[0].midi_note

    @property
    def volume(self) -> float:
        return self.players[0].volume

    @property
    def available(self) -> bool:
        return self.players[0].available
