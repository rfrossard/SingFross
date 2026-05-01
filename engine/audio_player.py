"""Music playback via pygame.mixer — fixed timing model.

Timing contract:
  - play() starts the audio file from position 0 immediately.
  - position_sec() returns elapsed wall-clock seconds since play() was called.
  - This matches beat_to_sec(beat) = gap_ms/1000 + beat * ms_per_beat/1000
    because the GAP is already built into the audio file (silence at the start).

Dual-stem support:
  - load_stems(instrumental_path, vocals_path) loads separated stems.
  - The instrumental is played via pygame.mixer.music (the streaming path).
  - The vocals are loaded as a pygame.mixer.Sound on a dedicated channel.
  - Both are started in the same call so they remain in sync.
  - set_vocal_volume(0..1) adjusts the vocal channel independently.
"""
import pygame
import time


_VOCAL_CHANNEL = 0   # reserved pygame.mixer channel index for vocals


class AudioPlayer:
    def __init__(self):
        self._start_wall  : float | None = None
        self._playing     : bool  = False
        self._loaded      : bool  = False
        self._volume      : float = 0.8
        self._sync_offset : float = 0.0    # seconds; positive = shift notes earlier

        # Dual-stem state
        self._stems_loaded : bool = False
        self._vocal_sound  : pygame.mixer.Sound | None = None
        self._vocal_ch     : pygame.mixer.Channel | None = None
        self._vocal_vol    : float = 1.0    # 0.0 = mute, 1.0 = full

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self, path: str) -> None:
        """Load a single audio file (original, un-separated)."""
        self._unload_stems()
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self._volume)
            self._loaded       = True
            self._playing      = False
            self._stems_loaded = False
        except Exception as e:
            print(f"[AudioPlayer] Cannot load {path}: {e}")
            self._loaded = False

    def load_stems(self, instrumental_path: str, vocals_path: str) -> None:
        """Load separated stems for dual-channel mixing.

        instrumental_path  → streamed via pygame.mixer.music (low RAM)
        vocals_path        → loaded as Sound on a dedicated channel
        """
        self._unload_stems()
        try:
            pygame.mixer.music.load(instrumental_path)
            pygame.mixer.music.set_volume(self._volume)
            self._loaded = True

            # Reserve channel 0 for vocals (set_reserved prevents auto-allocation)
            pygame.mixer.set_reserved(1)
            self._vocal_ch    = pygame.mixer.Channel(_VOCAL_CHANNEL)
            self._vocal_sound = pygame.mixer.Sound(vocals_path)
            self._vocal_ch.set_volume(self._vocal_vol)

            self._stems_loaded = True
            self._playing      = False
        except Exception as e:
            print(f"[AudioPlayer] Cannot load stems: {e}")
            self._stems_loaded = False

    def _unload_stems(self) -> None:
        if self._stems_loaded and self._vocal_ch is not None:
            try:
                self._vocal_ch.stop()
            except Exception:
                pass
        self._vocal_sound  = None
        self._vocal_ch     = None
        self._stems_loaded = False

    # ── Playback control ─────────────────────────────────────────────────────

    def play(self) -> None:
        if not self._loaded:
            return
        self._start_wall = time.perf_counter()
        pygame.mixer.music.play()
        if self._stems_loaded and self._vocal_ch and self._vocal_sound:
            # Start vocal channel in the same frame — practically zero offset
            self._vocal_ch.play(self._vocal_sound)
        self._playing = True

    def stop(self) -> None:
        if self._loaded:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        if self._stems_loaded and self._vocal_ch:
            try:
                self._vocal_ch.stop()
            except Exception:
                pass
        self._playing    = False
        self._start_wall = None

    def pause(self) -> None:
        if self._playing:
            pygame.mixer.music.pause()
            if self._stems_loaded and self._vocal_ch:
                self._vocal_ch.pause()

    def unpause(self) -> None:
        if self._playing:
            pygame.mixer.music.unpause()
            if self._stems_loaded and self._vocal_ch:
                self._vocal_ch.unpause()

    # ── Volume ────────────────────────────────────────────────────────────────

    def set_volume(self, v: float) -> None:
        """Master volume (applies to instrumental / full track)."""
        self._volume = max(0.0, min(1.0, v))
        if self._loaded:
            pygame.mixer.music.set_volume(self._volume)

    def set_vocal_volume(self, v: float) -> None:
        """Vocal stem volume — 0 = fully muted, 1 = original level."""
        self._vocal_vol = max(0.0, min(1.0, v))
        if self._stems_loaded and self._vocal_ch:
            self._vocal_ch.set_volume(self._vocal_vol)

    @property
    def vocal_volume(self) -> float:
        return self._vocal_vol

    # ── Sync ─────────────────────────────────────────────────────────────────

    def set_sync_offset(self, offset_sec: float) -> None:
        """Positive offset shifts notes to appear earlier (audio feels late)."""
        self._sync_offset = offset_sec

    def update(self) -> None:
        """No-op kept for API compatibility."""
        pass

    # ── Position ─────────────────────────────────────────────────────────────

    def position_sec(self) -> float:
        """Wall-clock seconds since play() was called, adjusted by sync offset."""
        if self._start_wall is None:
            return 0.0
        return (time.perf_counter() - self._start_wall) + self._sync_offset

    # ── State ────────────────────────────────────────────────────────────────

    @property
    def is_playing(self) -> bool:
        return self._loaded and self._playing

    @property
    def stems_loaded(self) -> bool:
        return self._stems_loaded
