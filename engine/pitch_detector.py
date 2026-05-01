"""Real-time pitch detection using HPS (Harmonic Product Spectrum) via numpy FFT."""
import threading
import numpy as np
from collections import deque

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:
    _SD_AVAILABLE = False

SAMPLE_RATE   = 44100
CHUNK_SIZE    = 4096   # larger = better freq resolution (≈10.8 Hz/bin)
HPS_HARMONICS = 2      # 2 harmonics sufficient; more kills product for sparse spectra
NOISE_FLOOR   = 0.01   # RMS threshold to consider as signal
PITCH_MIN_HZ  = 70
PITCH_MAX_HZ  = 1050
SMOOTHING     = 0.35   # weight of new reading vs old (lower = smoother)


def freq_to_midi(freq: float) -> float:
    if freq <= 0:
        return -1.0
    return 69.0 + 12.0 * np.log2(freq / 440.0)


def midi_to_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def hps_detect(chunk: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Return detected frequency in Hz, or 0 if no signal."""
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    if rms < NOISE_FLOOR:
        return 0.0

    windowed = chunk * np.hanning(len(chunk))
    spectrum = np.abs(np.fft.rfft(windowed, n=CHUNK_SIZE))
    freqs    = np.fft.rfftfreq(CHUNK_SIZE, 1.0 / sr)

    # Standard HPS: hps[k] = product of spectrum[h*k] for h=1..N
    # Apply on full spectrum first, then pick peak in vocal range
    hps = spectrum.copy()
    for h in range(2, HPS_HARMONICS + 1):
        ds     = spectrum[::h]
        length = min(len(hps), len(ds))
        hps[:length] *= ds[:length]
    # Zero out anything beyond the shorter product length
    hps[length:] = 0.0

    lo = int(np.searchsorted(freqs, PITCH_MIN_HZ))
    hi = int(np.searchsorted(freqs, PITCH_MAX_HZ))
    lo = max(lo, 1)
    hi = min(hi, len(hps) - 1)

    if lo >= hi:
        return 0.0

    peak_idx = int(np.argmax(hps[lo:hi])) + lo
    return float(freqs[peak_idx])


class PitchDetector:
    """Runs pitch detection in a background thread."""

    def __init__(self):
        self._lock        = threading.Lock()
        self._raw_midi    = -1.0
        self._midi        = -1.0
        self._volume      = 0.0
        self._stream      = None
        self._active      = False
        self._history     = deque(maxlen=8)
        self.available    = _SD_AVAILABLE

    # ---- public API --------------------------------------------------------

    @property
    def midi_note(self) -> float:
        with self._lock:
            return self._midi

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    def start(self):
        if not _SD_AVAILABLE or self._active:
            return
        self._active = True
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=CHUNK_SIZE,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            print(f"[PitchDetector] Could not open mic: {e}")
            self._active = False

    def stop(self):
        self._active = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    # ---- internal ----------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status):
        chunk = indata[:, 0]
        rms   = float(np.sqrt(np.mean(chunk ** 2)))
        freq  = hps_detect(chunk)
        new_midi = freq_to_midi(freq) if freq > 0 else -1.0

        with self._lock:
            self._volume = rms
            if new_midi < 0:
                self._history.clear()
                self._midi = -1.0
            else:
                self._history.append(new_midi)
                median = float(np.median(list(self._history)))
                if self._midi < 0:
                    self._midi = median
                else:
                    self._midi = self._midi * (1 - SMOOTHING) + median * SMOOTHING
