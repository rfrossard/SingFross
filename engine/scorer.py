"""Scoring engine — note hit detection, combos, line bonuses, ratings.
Based on Vocaluxe scoring model: beat-accurate points, golden 2x, line bonuses.
"""
from dataclasses import dataclass, field
from typing import Optional
from engine.song_parser import Note, LineBreak

PITCH_TOLERANCE  = 2.5     # semitones allowed off-pitch
COMBO_THRESHOLDS = [0, 10, 25, 50]
MULTIPLIERS      = [1,  2,   4,   8]
POINTS_NORMAL    = 100     # per beat, normal note
POINTS_GOLDEN    = 200     # per beat, golden note (2×)
LINE_BONUS_MAX   = 1000    # perfect line bonus (all notes hit)


def _get_multiplier(combo: int) -> int:
    mult = 1
    for i, t in enumerate(COMBO_THRESHOLDS):
        if combo >= t:
            mult = MULTIPLIERS[i]
    return mult


# ── Line rating label (Vocaluxe-style per-line feedback) ─────────────────────

def line_label(pct: float) -> tuple[str, tuple]:
    """Return (label, color) for a line completion percentage 0-1."""
    from ui import theme as T
    if pct >= 1.0:  return "PERFECT LINE!", T.GOLD
    if pct >= 0.85: return "GREAT!",        T.SUCCESS
    if pct >= 0.60: return "GOOD",          T.INFO
    if pct >= 0.30: return "OK",            T.WARNING
    return "MISS",                           T.RED


@dataclass
class ScoreState:
    score:        int   = 0
    line_bonus:   int   = 0    # accumulated line bonuses (separate track)
    combo:        int   = 0
    max_combo:    int   = 0
    notes_hit:    int   = 0
    notes_total:  int   = 0
    beats_hit:    float = 0.0
    beats_total:  float = 0.0
    lines_perfect:int   = 0
    lines_total:  int   = 0
    _partial:     float = 0.0
    last_note:    object = None
    last_hit:     bool   = False

    @property
    def total_score(self) -> int:
        return self.score + self.line_bonus

    @property
    def multiplier(self) -> int:
        return _get_multiplier(self.combo)

    @property
    def accuracy(self) -> float:
        if self.beats_total == 0:
            return 0.0
        return self.beats_hit / self.beats_total

    @property
    def rating(self) -> str:
        pct = self.accuracy * 100
        if pct >= 95: return "LEGENDARY"
        if pct >= 80: return "ROCK STAR"
        if pct >= 60: return "SINGER"
        if pct >= 35: return "AMATEUR"
        return "TONE DEAF"

    @property
    def stars(self) -> int:
        pct = self.accuracy * 100
        if pct >= 95: return 5
        if pct >= 80: return 4
        if pct >= 60: return 3
        if pct >= 35: return 2
        if pct >= 10: return 1
        return 0


@dataclass
class LineResult:
    """Emitted once per lyric line when that line ends."""
    beats_hit:   float
    beats_total: float
    bonus:       int
    label:       str
    color:       tuple

    @property
    def pct(self) -> float:
        return self.beats_hit / self.beats_total if self.beats_total else 0.0


class Scorer:
    def __init__(self, song):
        self.song   = song
        self.state  = ScoreState()
        self._lines: list[list[Note]] = []   # grouped lyric lines
        self._line_idx    = 0                # which line we're in
        self._line_hit    = 0.0              # beats hit in current line
        self._line_total  = 0.0             # beats in current line
        self._line_result: Optional[LineResult] = None  # set when line ends
        self._build_lines()
        self._count_totals()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _build_lines(self):
        """Split song notes into lines at LineBreak markers."""
        current: list[Note] = []
        for item in self.song.notes:
            if isinstance(item, LineBreak):
                if current:
                    self._lines.append(current)
                    current = []
            elif isinstance(item, Note) and item.note_type != "F":
                current.append(item)
        if current:
            self._lines.append(current)

    def _count_totals(self):
        for n in self.song.notes:
            if isinstance(n, Note) and n.note_type != "F":
                self.state.notes_total += 1
                self.state.beats_total += n.duration
        self.state.lines_total = len(self._lines)
        self._advance_line()

    def _advance_line(self):
        """Load beats_total for the next lyric line."""
        self._line_hit   = 0.0
        self._line_total = 0.0
        if self._line_idx < len(self._lines):
            for n in self._lines[self._line_idx]:
                self._line_total += n.duration

    # ── Per-frame update ──────────────────────────────────────────────────────

    def update(self, player_midi: float, current_sec: float, dt: float) -> bool:
        """
        Call every frame. Returns True if a note was actively hit.
        After a lyric line ends, self.line_result is set for one frame.
        """
        self._line_result = None
        song  = self.song
        state = self.state

        # Find the active note at current_sec
        active_note: Optional[Note] = None
        for n in song.notes:
            if not isinstance(n, Note) or n.note_type == "F":
                continue
            ns = song.beat_to_sec(n.beat)
            ne = song.beat_to_sec(n.beat + n.duration)
            if ns <= current_sec < ne:
                active_note = n
                break

        # ── Note ended or no note ─────────────────────────────────────────────
        if active_note is None:
            if state.last_note is not None and not state.last_hit:
                state.combo = 0
            state.last_note = None
            state.last_hit  = False

            # Check if the current line's last note has passed → close line
            self._check_line_end(current_sec)
            return False

        # ── Entered a new note ────────────────────────────────────────────────
        if active_note is not state.last_note:
            state.last_note = active_note
            state.last_hit  = False

        if player_midi < 0:
            state.last_hit = False
            state.combo    = 0
            return False

        # Octave-fold — singer can be in any comfortable register
        target = float(active_note.pitch)
        diff   = (player_midi - target) % 12
        if diff > 6:
            diff -= 12
        hit = abs(diff) <= PITCH_TOLERANCE

        if hit:
            is_golden = (active_note.note_type == "*")
            pts_per_beat = POINTS_GOLDEN if is_golden else POINTS_NORMAL
            beat_frac = dt / (song.ms_per_beat / 1000.0)
            pts = pts_per_beat * state.multiplier * beat_frac
            state.score      += int(pts)
            state.beats_hit  += beat_frac
            self._line_hit   += beat_frac
            if not state.last_hit:
                state.combo      += 1
                state.max_combo   = max(state.combo, state.max_combo)
                state.notes_hit  += 1
            state.last_hit = True
        else:
            state.last_hit = False
            state.combo    = 0

        return hit

    @property
    def line_result(self) -> Optional[LineResult]:
        """Non-None for exactly one frame when a lyric line finishes."""
        return self._line_result

    def _check_line_end(self, current_sec: float):
        """Emit a LineResult when we've passed the last note of the current line."""
        if self._line_idx >= len(self._lines):
            return
        line = self._lines[self._line_idx]
        if not line:
            return
        last_note = line[-1]
        line_end_sec = self.song.beat_to_sec(last_note.beat + last_note.duration)
        if current_sec >= line_end_sec + 0.05:   # 50ms grace
            self._close_line()

    def _close_line(self):
        """Finalise the current line, award bonus, emit LineResult."""
        if self._line_idx >= len(self._lines):
            return
        total = max(self._line_total, 0.001)
        pct   = min(1.0, self._line_hit / total)
        bonus = int(LINE_BONUS_MAX * pct)
        label, color = line_label(pct)
        if pct >= 1.0:
            self.state.lines_perfect += 1
        self.state.line_bonus += bonus
        self._line_result = LineResult(
            beats_hit=self._line_hit,
            beats_total=self._line_total,
            bonus=bonus,
            label=label,
            color=color,
        )
        self._line_idx += 1
        self._advance_line()
