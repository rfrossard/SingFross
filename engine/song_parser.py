"""UltraStar .txt song format parser (compatible with Vocaluxe & USDX)."""
import os, re
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Note:
    note_type: str      # ':' normal, '*' golden, 'F' freestyle
    beat: int
    duration: int
    pitch: int          # MIDI relative (0 = C4)
    text: str

@dataclass
class LineBreak:
    beat: int

@dataclass
class Song:
    title: str          = "Unknown"
    artist: str         = "Unknown"
    language: str       = ""
    genre: str          = ""
    year: str           = ""
    bpm: float          = 120.0
    gap: float          = 0.0      # ms before beat 0
    mp3: str            = ""
    cover: str          = ""
    background: str     = ""
    video: str          = ""
    notes: List         = field(default_factory=list)
    folder: str         = ""

    # Derived
    @property
    def ms_per_beat(self) -> float:
        return 60000.0 / (self.bpm * 4.0)

    def beat_to_ms(self, beat: int) -> float:
        return self.gap + beat * self.ms_per_beat

    def beat_to_sec(self, beat: int) -> float:
        return self.beat_to_ms(beat) / 1000.0

    @property
    def duration_sec(self) -> float:
        notes_only = [n for n in self.notes if isinstance(n, Note)]
        if not notes_only:
            return 9999.0   # audio-only stub: end is driven by music-end event
        last = notes_only[-1]
        return self.beat_to_sec(last.beat + last.duration) + 2.0

    @property
    def mp3_path(self) -> Optional[str]:
        if self.mp3 and self.folder:
            p = os.path.join(self.folder, self.mp3)
            return p if os.path.exists(p) else None
        return None

    @property
    def cover_path(self) -> Optional[str]:
        if self.cover and self.folder:
            p = os.path.join(self.folder, self.cover)
            return p if os.path.exists(p) else None
        return None

    @property
    def pitch_range(self):
        notes_only = [n for n in self.notes if isinstance(n, Note)]
        if not notes_only:
            return 40, 80
        pitches = [n.pitch for n in notes_only]
        lo, hi = min(pitches), max(pitches)
        pad = max(5, (hi - lo) // 4)
        return lo - pad, hi + pad

    def lines(self):
        """Yield lists of Note objects grouped by line."""
        current = []
        for item in self.notes:
            if isinstance(item, LineBreak):
                if current:
                    yield current
                current = []
            elif isinstance(item, Note):
                current.append(item)
        if current:
            yield current

    def line_at_sec(self, t: float):
        """Return (line_notes, line_index) for a given time."""
        all_lines = list(self.lines())
        for i, line in enumerate(all_lines):
            if not line:
                continue
            start = self.beat_to_sec(line[0].beat)
            end   = self.beat_to_sec(line[-1].beat + line[-1].duration)
            if start <= t <= end + 0.5:
                return line, i
        return None, -1


def parse(path: str) -> Song:
    folder = os.path.dirname(os.path.abspath(path))
    song = Song(folder=folder)

    # utf-8-sig handles optional BOM (﻿) present in many USDB-downloaded files
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = f.readlines()

    for raw in lines:
        # Strip only line endings — preserve trailing spaces used by USDB as
        # word-boundary markers (e.g. "Smoke " means the next syllable starts a new word)
        line = raw.rstrip('\r\n')
        stripped = line.lstrip()
        if not stripped:
            continue

        # Header tags
        if stripped.startswith("#"):
            m = re.match(r"#([^:]+):(.+)", stripped)
            if m:
                key, val = m.group(1).strip().upper(), m.group(2).strip()
                if key == "TITLE":    song.title    = val
                elif key == "ARTIST": song.artist   = val
                elif key == "LANGUAGE": song.language = val
                elif key == "GENRE":  song.genre    = val
                elif key == "YEAR":   song.year     = val
                elif key == "BPM":    song.bpm      = float(val.replace(",", "."))
                elif key == "GAP":    song.gap      = float(val.replace(",", "."))
                elif key == "MP3":    song.mp3      = val
                elif key == "AUDIO":  song.mp3      = val   # newer tag alias
                elif key == "COVER":  song.cover    = val
                elif key == "BACKGROUND": song.background = val
                elif key == "VIDEO":  song.video    = val
            continue

        # End marker
        if stripped.rstrip().upper() == "E":
            break

        # Line break
        if stripped.startswith("-"):
            parts = stripped.split()
            beat = int(parts[1]) if len(parts) > 1 else 0
            song.notes.append(LineBreak(beat=beat))
            continue

        # Note line: TYPE BEAT DURATION PITCH TEXT
        # Match against `line` (not `stripped`) so trailing spaces in syllable text
        # are preserved. USDB trailing-space convention: "Smoke " → next word starts new word.
        # Leading-space convention: " on" → space before syllable.
        m = re.match(r'^([:\*FRf])\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)(.*)', stripped)
        if not m:
            continue
        ntype = m.group(1)
        if ntype not in (":", "*", "F", "R"):
            continue
        try:
            beat     = int(m.group(2))
            duration = int(m.group(3))
            pitch    = int(m.group(4))
            sylraw   = m.group(5)           # e.g. " on" or "Smoke " or " Smoke"
            # Strip exactly one separator space after the pitch field; keep the rest
            # (trailing space = word boundary in USDB trailing-space convention)
            text     = sylraw[1:] if sylraw and sylraw[0] in (' ', '\t') else sylraw
        except ValueError:
            continue

        song.notes.append(Note(
            note_type=ntype,
            beat=beat,
            duration=duration,
            pitch=pitch,
            text=text,
        ))

    return song


def scan_library(songs_dir: str) -> List[Song]:
    songs = []
    if not os.path.isdir(songs_dir):
        return songs
    for root, dirs, files in os.walk(songs_dir):
        for f in files:
            if f.endswith(".txt"):
                try:
                    s = parse(os.path.join(root, f))
                    if s.notes or s.mp3_path:   # include audio-only stubs
                        songs.append(s)
                except Exception:
                    pass
    songs.sort(key=lambda s: s.title.lower())
    return songs
