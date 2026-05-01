"""YouTube-to-Karaoke engine.

Handles: search, thumbnail fetch, audio/video download, subtitle extraction,
UltraStar .txt generation, and cover art download.
"""
import os, re, json, math, threading, time, tempfile, shutil
from typing import Optional


# ── FFmpeg detection ─────────────────────────────────────────────────────────

_FFMPEG_SEARCH = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/snap/bin",
]

def _find_ffmpeg() -> Optional[str]:
    if shutil.which("ffmpeg"):
        return os.path.dirname(shutil.which("ffmpeg"))
    for d in _FFMPEG_SEARCH:
        if os.path.isfile(os.path.join(d, "ffmpeg")):
            return d
    return None

_FFMPEG_DIR: Optional[str] = _find_ffmpeg()

_AUDIO_EXTS = (".mp3", ".m4a", ".ogg", ".opus", ".webm", ".aac", ".flac", ".wav")

# ── Data structures ──────────────────────────────────────────────────────────

class YTVideo:
    """Lightweight representation of a search result."""
    __slots__ = ("id", "title", "channel", "duration_s", "thumbnail_url",
                 "views", "url")

    def __init__(self, vid_id, title, channel, duration_s, thumbnail_url,
                 views=0):
        self.id            = vid_id
        self.title         = title
        self.channel       = channel
        self.duration_s    = duration_s       # seconds (int)
        self.thumbnail_url = thumbnail_url
        self.views         = views
        self.url           = f"https://www.youtube.com/watch?v={vid_id}"

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration_s), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── Search ───────────────────────────────────────────────────────────────────

def search_karaoke(query: str, max_results: int = 15) -> list[YTVideo]:
    """Search YouTube for karaoke videos using yt-dlp.

    Always appends 'karaoke' to the query so results are relevant.
    Returns up to max_results YTVideo objects.
    """
    import yt_dlp

    kq  = query.strip() + " karaoke"
    ydl_opts = {
        "quiet":             True,
        "no_warnings":       True,
        "extract_flat":      True,
        "skip_download":     True,
        "default_search":    "ytsearch",
        "playlistend":       max_results,
    }

    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{kq}", download=False)
            entries = info.get("entries", []) if info else []
            for e in entries:
                if not e:
                    continue
                vid_id = e.get("id") or e.get("url", "")
                if not vid_id:
                    continue
                thumb = (e.get("thumbnails") or [{}])[-1].get("url", "") \
                        or f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
                results.append(YTVideo(
                    vid_id       = vid_id,
                    title        = e.get("title", "Unknown"),
                    channel      = e.get("uploader") or e.get("channel", ""),
                    duration_s   = int(e.get("duration") or 0),
                    thumbnail_url= thumb,
                    views        = int(e.get("view_count") or 0),
                ))
    except Exception as e:
        print(f"[YT search] {e}")

    return results


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def fetch_thumbnail(video: YTVideo) -> Optional[bytes]:
    """Download thumbnail bytes (JPEG). Returns None on failure."""
    import urllib.request
    urls_to_try = [
        f"https://img.youtube.com/vi/{video.id}/hqdefault.jpg",
        f"https://img.youtube.com/vi/{video.id}/mqdefault.jpg",
        video.thumbnail_url,
    ]
    for url in urls_to_try:
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.read()
        except Exception:
            continue
    return None


# ── Subtitle → UltraStar conversion ─────────────────────────────────────────
#
# UltraStar .txt format reference (what the game's song_parser.py expects):
#
#   #TITLE:Song Title
#   #ARTIST:Artist Name
#   #LANGUAGE:Portuguese
#   #BPM:120
#   #GAP:0               ← silence in ms before beat 0
#   #MP3:audio.mp3
#   : 0  4  50 Le        ← TYPE BEAT DURATION PITCH SYLLABLE
#   : 4  4  50 gi        ←   no leading space = same word
#   : 8  4  50 ão        ←   (concatenated with previous)
#   : 12 4  50  Ur       ←   leading space = new word
#   - 32                 ← line break at beat 32
#   E                    ← end of song
#
# Timing:  ms_per_beat = 60000 / (BPM * 4)   →  BPM=120 → 125 ms/beat
#          beat = (time_ms − gap_ms) / ms_per_beat
# Pitch:   50 = middle (no actual pitch data from subtitles)

def _json3_to_ultrastar(j3_path: str, gap_ms: float = 0.0,
                        bpm: float = 120.0) -> list[str]:
    """Convert YouTube json3 subtitle file to UltraStar note lines.

    json3 gives word-level timing which maps well to UltraStar syllables.
    Each subtitle segment becomes one or more notes.
    """
    ms_per_beat = 60000.0 / (bpm * 4.0)

    def ms_to_beat(ms: float) -> int:
        return max(0, int(round((ms - gap_ms) / ms_per_beat)))

    notes = []
    try:
        with open(j3_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[json3] parse error: {e}")
        return notes

    # Gather all word-level segments with absolute timing
    segs = []
    for ev in data.get("events", []):
        t_start = ev.get("tStartMs", 0)
        for seg in ev.get("segs", []):
            txt = seg.get("utf8", "").replace("\n", " ").strip()
            if not txt:
                continue
            offset = seg.get("tOffsetMs", 0)
            abs_ms = t_start + offset
            dur_ms = ev.get("dDurationMs", 500)
            segs.append((abs_ms, dur_ms, txt))

    if not segs:
        return notes

    # Group into lines (new line = >1.5s gap or explicit newline in text)
    lines = []
    current = []
    prev_end = 0
    for abs_ms, dur_ms, txt in segs:
        if current and abs_ms - prev_end > 1500:
            lines.append(current)
            current = []
        current.append((abs_ms, dur_ms, txt))
        prev_end = abs_ms + dur_ms

    if current:
        lines.append(current)

    # Build UltraStar lines
    for li, line in enumerate(lines):
        for abs_ms, dur_ms, txt in line:
            beat     = ms_to_beat(abs_ms)
            dur_beat = max(1, int(round(dur_ms / ms_per_beat)))
            # Prepend space before each word except the first on a line
            idx   = line.index((abs_ms, dur_ms, txt))
            text  = (" " + txt) if idx > 0 else txt
            notes.append(f": {beat} {dur_beat} 50 {text}")
        if li < len(lines) - 1:
            gap_beat = ms_to_beat(lines[li + 1][0][0])
            notes.append(f"- {gap_beat}")

    return notes


def _srt_to_ultrastar(srt_path: str, gap_ms: float = 0.0,
                      bpm: float = 120.0) -> list[str]:
    """Fallback: convert SRT subtitles to UltraStar notes (line granularity)."""
    ms_per_beat = 60000.0 / (bpm * 4.0)

    def tc_to_ms(tc: str) -> float:
        tc = tc.replace(",", ".")
        parts = tc.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
        return 0.0

    def ms_to_beat(ms: float) -> int:
        return max(0, int(round((ms - gap_ms) / ms_per_beat)))

    notes = []
    try:
        with open(srt_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return notes

    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        tc_line = next((l for l in lines if "-->" in l), None)
        if not tc_line:
            continue
        parts = tc_line.split("-->")
        start_ms = tc_to_ms(parts[0].strip())
        end_ms   = tc_to_ms(parts[1].split()[0].strip())
        text     = " ".join(l for l in lines if not l.strip().isdigit()
                            and "-->" not in l).strip()
        if text:
            entries.append((start_ms, end_ms, text))

    for i, (start_ms, end_ms, text) in enumerate(entries):
        beat     = ms_to_beat(start_ms)
        dur_beat = max(1, ms_to_beat(end_ms) - beat)
        # Split text into words for a more natural UltraStar flow
        words = text.split()
        if not words:
            continue
        for wi, word in enumerate(words):
            w_beat = beat + int(wi * dur_beat / len(words))
            w_dur  = max(1, dur_beat // len(words))
            txt    = (" " + word) if wi > 0 else word
            notes.append(f": {w_beat} {w_dur} 50 {txt}")
        if i < len(entries) - 1:
            gap_beat = ms_to_beat(entries[i + 1][0])
            notes.append(f"- {gap_beat}")

    return notes


# ── VTT subtitle parser ───────────────────────────────────────────────────────

def _vtt_to_ultrastar(vtt_path: str, gap_ms: float = 0.0,
                      bpm: float = 120.0) -> list[str]:
    """Convert WebVTT (including YouTube progressive word-level VTT) to UltraStar.

    YouTube's VTT auto-subs are "progressive": each cue repeats the previous
    words and adds one more.  We deduplicate by keeping the final cue per
    100 ms start-time bucket.
    """
    ms_per_beat = 60000.0 / (bpm * 4.0)

    def tc_to_ms(tc: str) -> float:
        tc = tc.strip().replace(",", ".")
        parts = tc.split(":")
        try:
            if len(parts) == 3:
                h, m, s = parts
                return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
            if len(parts) == 2:
                m, s = parts
                return (int(m) * 60 + float(s)) * 1000
        except ValueError:
            pass
        return 0.0

    def ms_to_beat(ms: float) -> int:
        return max(0, int(round((ms - gap_ms) / ms_per_beat)))

    def strip_tags(s: str) -> str:
        s = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d+>", "", s)   # <00:00:01.400>
        s = re.sub(r"<[^>]+>", "", s)                      # <c>, <b>, etc.
        return re.sub(r"\s+", " ", s).strip()

    try:
        with open(vtt_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(f"[VTT] read error: {e}")
        return []

    # Match cue blocks: timestamp --> timestamp [optional settings] \n text
    tc_pat = r"(\d{1,2}:\d{2}[\.,]\d+|\d{2}:\d{2}:\d{2}[\.,]\d+)"
    cue_re = re.compile(
        tc_pat + r"\s*-->\s*" + tc_pat + r"[^\n]*\n((?:(?!-->)(?!\n\n)[^\n]*\n?)*)",
        re.MULTILINE,
    )

    # Collect raw cues, group by 100ms start bucket (dedup progressive YouTube VTT)
    buckets: dict[int, tuple] = {}
    for m in cue_re.finditer(content):
        start_ms = tc_to_ms(m.group(1))
        end_ms   = tc_to_ms(m.group(2))
        text     = strip_tags(m.group(3)).strip()
        if not text:
            continue
        key = int(start_ms / 100)
        # Keep the last (most complete) cue for each 100ms bucket
        buckets[key] = (start_ms, end_ms, text)

    entries = sorted(buckets.values(), key=lambda x: x[0])
    if not entries:
        return []

    notes: list[str] = []
    for i, (start_ms, end_ms, text) in enumerate(entries):
        words = text.split()
        if not words:
            continue
        total_ms   = max(1, end_ms - start_ms)
        per_word   = total_ms / len(words)
        for wi, word in enumerate(words):
            w_ms  = start_ms + int(wi * per_word)
            beat  = ms_to_beat(w_ms)
            dur   = max(1, int(round(per_word / ms_per_beat)))
            txt   = (" " + word) if wi > 0 else word
            notes.append(f": {beat} {dur} 50 {txt}")
        # Line break if there is a gap > 800 ms to the next cue
        if i < len(entries) - 1 and (entries[i + 1][0] - end_ms) > 800:
            notes.append(f"- {ms_to_beat(entries[i + 1][0])}")

    return notes


# ── Shared subtitle downloader ────────────────────────────────────────────────

#: Language priority list — Portuguese first for Brazilian music, then Spanish, then English
_LANG_PRIORITY = ["pt", "pt-BR", "pt-PT", "es", "es-419", "es-ES",
                  "en", "en-US", "en-GB"]


def fetch_subtitles_as_ultrastar(yt_url: str,
                                 bpm: float = 120.0,
                                 gap_ms: float = 0.0) -> list[str]:
    """Download subtitles for a YouTube URL and return UltraStar note lines.

    Tries priority languages (pt/es/en) first, then falls back to any language.
    Returns empty list if no subtitles found.
    """
    try:
        import yt_dlp as _yt
    except ImportError:
        return []

    def _scan(directory: str) -> list[str]:
        if not os.path.isdir(directory):
            return []
        files = sorted(os.listdir(directory))
        for ext, parser in [(".json3", _json3_to_ultrastar),
                             (".vtt",   _vtt_to_ultrastar),
                             (".srt",   _srt_to_ultrastar)]:
            match = next((os.path.join(directory, f) for f in files
                          if f.endswith(ext)), None)
            if match:
                result = parser(match, gap_ms, bpm)
                if result:
                    return result
        return []

    base_opts = {
        "quiet":          True,
        "no_warnings":    True,
        "skip_download":  True,
        "writeautosub":   True,
        "writesubtitles": True,
        "subtitlesformat":"json3/vtt/srv3/ttml/srt",
    }

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # Pass 1 — priority languages
        opts = {**base_opts,
                "subtitleslangs": _LANG_PRIORITY,
                "outtmpl": os.path.join(tmpdir, "sub1.%(ext)s")}
        try:
            with _yt.YoutubeDL(opts) as ydl:
                ydl.download([yt_url])
        except Exception:
            pass

        lines = _scan(tmpdir)
        if lines:
            return lines

        # Pass 2 — any available language
        opts2 = {**base_opts,
                 "subtitleslangs": ["all"],
                 "outtmpl": os.path.join(tmpdir, "sub2.%(ext)s")}
        try:
            with _yt.YoutubeDL(opts2) as ydl:
                ydl.download([yt_url])
        except Exception:
            pass

        return _scan(tmpdir)


# ── Main download function ────────────────────────────────────────────────────

class DownloadResult:
    def __init__(self):
        self.mp3_path:   Optional[str] = None
        self.txt_path:   Optional[str] = None
        self.video_path: Optional[str] = None
        self.cover_path: Optional[str] = None
        self.folder:     Optional[str] = None
        self.error:      Optional[str] = None
        self.progress:   float         = 0.0   # 0–1
        self.stage:      str           = "starting"


def _safe_dirname(title: str) -> str:
    """Turn a video title into a safe folder name."""
    name = re.sub(r'[\\/*?:"<>|]', "", title)
    name = re.sub(r'\s+', " ", name).strip()
    return name[:80] or "Unknown Song"


def download_karaoke(video: YTVideo, songs_dir: str,
                     result: DownloadResult,
                     progress_cb=None) -> None:
    """Full download pipeline — runs in a background thread.

    Saves into songs_dir/<safe-title>/:
      audio.mp3, video.mp4 (no audio), cover.jpg, <title>.txt

    Updates result.progress (0-1) and result.stage throughout.
    """
    import yt_dlp

    def _prog(p):
        if progress_cb:
            progress_cb(p)
        result.progress = p

    dirname  = _safe_dirname(video.title)
    dest_dir = os.path.join(songs_dir, dirname)
    os.makedirs(dest_dir, exist_ok=True)
    result.folder = dest_dir

    bpm    = 120.0
    gap_ms = 0.0

    # ── 1. Download audio ─────────────────────────────────────────────────
    result.stage = "Downloading audio..."
    _prog(0.05)

    def _find_audio(stem: str) -> Optional[str]:
        """Find any audio file with given stem in dest_dir."""
        for ext in _AUDIO_EXTS:
            p = os.path.join(dest_dir, f"{stem}{ext}")
            if os.path.exists(p):
                return p
        return None

    audio_path = _find_audio("audio")
    if not audio_path:
        ydl_audio_opts: dict = {
            "quiet":          True,
            "no_warnings":    True,
            "format":         "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl":        os.path.join(dest_dir, "audio.%(ext)s"),
        }

        if _FFMPEG_DIR:
            ydl_audio_opts["ffmpeg_location"] = _FFMPEG_DIR
            ydl_audio_opts["postprocessors"]  = [{
                "key":             "FFmpegExtractAudio",
                "preferredcodec":  "mp3",
                "preferredquality":"192",
            }]

        def audio_hook(d):
            if d["status"] == "downloading":
                pct = d.get("_percent_str", "0%").strip().rstrip("%")
                try:
                    _prog(0.05 + float(pct) / 100.0 * 0.30)
                except ValueError:
                    pass
            elif d["status"] == "finished":
                _prog(0.35)

        ydl_audio_opts["progress_hooks"] = [audio_hook]
        try:
            with yt_dlp.YoutubeDL(ydl_audio_opts) as ydl:
                ydl.download([video.url])
        except Exception as e:
            result.error = f"Audio download failed: {e}"
            return

        audio_path = _find_audio("audio")

    if not audio_path:
        result.error = "Audio file not found after download."
        return

    result.mp3_path = audio_path   # may be .m4a / .opus etc. — pygame plays all

    # ── 2. Download subtitles (lyrics) ───────────────────────────────────
    result.stage = "Extracting lyrics..."
    _prog(0.38)

    # fetch_subtitles_as_ultrastar tries pt/es/en, then any available language
    note_lines = fetch_subtitles_as_ultrastar(video.url, bpm=bpm, gap_ms=gap_ms)

    _prog(0.55)

    # ── 3. Download video (video-only stream, best quality) ───────────────
    result.stage = "Downloading video..."

    video_path = os.path.join(dest_dir, "video.mp4")
    if not os.path.exists(video_path):
        ydl_vid_opts = {
            "quiet":      True,
            "no_warnings":True,
            "format":     "bestvideo[ext=mp4]/bestvideo",
            "outtmpl":    video_path,
        }

        def vid_hook(d):
            if d["status"] == "downloading":
                pct = d.get("_percent_str", "0%").strip().rstrip("%")
                try:
                    _prog(0.55 + float(pct) / 100.0 * 0.25)
                except ValueError:
                    pass
            elif d["status"] == "finished":
                _prog(0.80)

        ydl_vid_opts["progress_hooks"] = [vid_hook]
        try:
            with yt_dlp.YoutubeDL(ydl_vid_opts) as ydl:
                ydl.download([video.url])
        except Exception as e:
            print(f"[YT video] {e}")  # non-fatal

    result.video_path = video_path if os.path.exists(video_path) else None

    # ── 4. Cover art ─────────────────────────────────────────────────────
    result.stage = "Downloading cover..."
    _prog(0.82)

    cover_path = os.path.join(dest_dir, "cover.jpg")
    if not os.path.exists(cover_path):
        # Try iTunes first (better quality)
        try:
            from engine.usdb_client import download_cover
            # Extract clean artist/title from video title
            title_parts = video.title.split(" - ", 1)
            if len(title_parts) == 2:
                artist, title = title_parts[0].strip(), title_parts[1].strip()
            else:
                artist, title = video.channel, video.title
            # Strip "karaoke" from title for better iTunes match
            title = re.sub(r'\bkaraoke\b', "", title, flags=re.IGNORECASE).strip()
            download_cover(artist, title, dest_dir, force=False)
        except Exception:
            pass

        if not os.path.exists(cover_path):
            # Fallback: YouTube thumbnail
            thumb_data = fetch_thumbnail(video)
            if thumb_data:
                with open(cover_path, "wb") as f:
                    f.write(thumb_data)

    result.cover_path = cover_path if os.path.exists(cover_path) else None

    # ── 5. Write UltraStar .txt ──────────────────────────────────────────
    result.stage = "Writing karaoke file..."
    _prog(0.92)

    # Build clean title/artist
    title_parts = video.title.split(" - ", 1)
    if len(title_parts) == 2:
        song_artist = title_parts[0].strip()
        song_title  = re.sub(r'\bkaraoke\b', "", title_parts[1],
                             flags=re.IGNORECASE).strip(" -|")
    else:
        song_artist = video.channel or "Unknown"
        song_title  = re.sub(r'\bkaraoke\b', "", video.title,
                             flags=re.IGNORECASE).strip(" -|") or video.title

    txt_path = os.path.join(dest_dir, f"{_safe_dirname(song_title)}.txt")

    audio_filename = os.path.basename(audio_path)   # e.g. "audio.mp3" or "audio.m4a"
    header = [
        f"#TITLE:{song_title}",
        f"#ARTIST:{song_artist}",
        "#LANGUAGE:English",
        f"#BPM:{bpm:.0f}",
        f"#GAP:{gap_ms:.0f}",
        f"#MP3:{audio_filename}",
        f"#COVER:{'cover.jpg' if result.cover_path else ''}",
        f"#VIDEO:{'video.mp4' if result.video_path else ''}",
    ]

    lines_out = header + (note_lines if note_lines else []) + ["E"]
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + "\n")

    result.txt_path = txt_path
    result.stage    = "Done"
    _prog(1.0)


# ── Download manager ─────────────────────────────────────────────────────────

class YTDownloadManager:
    """Thread-safe manager for one concurrent download."""

    def __init__(self):
        self._result:  Optional[DownloadResult] = None
        self._thread:  Optional[threading.Thread] = None
        self._video_id: Optional[str] = None

    def is_idle(self) -> bool:
        return self._thread is None or not self._thread.is_alive()

    def result_for(self, video_id: str) -> Optional[DownloadResult]:
        if self._video_id == video_id:
            return self._result
        return None

    def start(self, video: YTVideo, songs_dir: str) -> DownloadResult:
        result           = DownloadResult()
        self._result     = result
        self._video_id   = video.id
        self._thread     = threading.Thread(
            target=download_karaoke,
            args=(video, songs_dir, result),
            daemon=True)
        self._thread.start()
        return result
