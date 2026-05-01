"""Song search & download from 4 sources:
  1. USDB (usdb.animux.de)       — largest UltraStar DB, requires login
  2. ultrastar-es.org            — Spanish/international community, YouTube-backed
  3. Karaoke Mugen (kara.moe)    — anime/game/pop, free REST API, ASS→UltraStar
  4. YouTube Karaoke (yt-dlp)    — any song as karaoke via YouTube search
"""
import os, re, threading, time, json
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import requests
    _REQ = True
except ImportError:
    _REQ = False

try:
    import yt_dlp
    _YTDLP = True
except ImportError:
    _YTDLP = False


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class RemoteSong:
    source:    str           # "usdb" | "es" | "kara" | "youtube"
    song_id:   str
    title:     str
    artist:    str
    language:  str  = ""
    genre:     str  = ""
    year:      str  = ""
    rating:    float = 0.0
    golden:    bool = False
    has_audio: bool = False
    detail_url:str  = ""
    youtube_id:str  = ""    # non-empty → audio downloadable via yt-dlp
    txt_url:   str  = ""    # direct .txt download URL (may need auth)
    # kara.moe extra fields
    kara_kid:  str  = ""    # kara.moe UUID for downloading lyrics + media
    duration:  int  = 0     # seconds

    @property
    def display(self) -> str:
        return f"{self.artist} — {self.title}"


# ── Session helper ────────────────────────────────────────────────────────────

def _session() -> "requests.Session":
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })
    return s


# ── Source 1: USDB (usdb.animux.de) ──────────────────────────────────────────

USDB_BASE  = "https://usdb.animux.de"
USDB_LIST  = USDB_BASE + "/?link=list"
USDB_LOGIN = USDB_BASE + "/?link=home"
USDB_DL    = USDB_BASE + "/?link=counter&id={sid}"


def _usdb_login(session, user: str, pw: str) -> bool:
    try:
        r = session.post(USDB_LOGIN,
                         data={"user": user, "pass": pw, "login": "Login"},
                         timeout=15)
        return "You are not logged in" not in r.text
    except Exception:
        return False


def _parse_usdb_row(tr_html: str) -> Optional[RemoteSong]:
    m_id = re.search(r'id=(\d+)', tr_html)
    if not m_id:
        return None
    sid = m_id.group(1)

    tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_html, re.S)
    if len(tds) < 4:
        return None

    def clean(s): return re.sub(r'<[^>]+>', '', s).strip()

    artist   = clean(tds[1]) if len(tds) > 1 else ""
    title    = clean(tds[2]) if len(tds) > 2 else ""
    language = clean(tds[5]) if len(tds) > 5 else ""
    genre    = clean(tds[6]) if len(tds) > 6 else ""
    golden   = bool(re.search(r'golden', tr_html, re.I))

    if not title and not artist:
        return None

    return RemoteSong(
        source="usdb", song_id=sid,
        title=title, artist=artist,
        language=language, genre=genre,
        golden=golden, has_audio=False,
        detail_url=f"{USDB_BASE}/?link=detail&id={sid}",
    )


def search_usdb(query: str, session=None, limit: int = 40) -> list[RemoteSong]:
    """Search USDB. Returns [] if not logged in or network error."""
    if not _REQ:
        return []
    sess = session or _session()
    try:
        parts = query.split(" ", 1)
        payload = {
            "interpret": parts[0] if len(parts) > 1 else "",
            "title":     parts[1] if len(parts) > 1 else parts[0],
            "order":     "rating",
            "ud":        "desc",
            "limit":     str(limit),
            "start":     "0",
        }
        r = sess.post(USDB_LIST, data=payload, timeout=15)
        if "You are not logged in" in r.text:
            return []
        rows = re.findall(
            r'<tr[^>]*class="[^"]*even[^"]*"[^>]*>(.*?)</tr>|'
            r'<tr[^>]*class="[^"]*odd[^"]*"[^>]*>(.*?)</tr>',
            r.text, re.S,
        )
        results = []
        for even, odd in rows:
            s = _parse_usdb_row(even or odd)
            if s:
                results.append(s)
        return results
    except Exception as e:
        print(f"[USDB] Search error: {e}")
        return []


def download_usdb_txt(song: RemoteSong, dest_dir: str, session=None) -> Optional[str]:
    """Download USDB .txt (requires login session). Returns path or None."""
    if not _REQ:
        return None
    sess = session or _session()
    try:
        url = USDB_DL.format(sid=song.song_id)
        r   = sess.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 50:
            return None
        if b"#TITLE" not in r.content[:300]:
            return None
        fname  = f"{song.artist} - {song.title}.txt".replace("/", "_")
        folder = os.path.join(dest_dir, f"{song.artist} - {song.title}")
        os.makedirs(folder, exist_ok=True)
        path   = os.path.join(folder, fname)
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception as e:
        print(f"[USDB] Download error: {e}")
        return None


# ── Source 2: ultrastar-es.org ────────────────────────────────────────────────

ES_BASE   = "https://ultrastar-es.org"
ES_SEARCH = ES_BASE + "/en/canciones"


def search_es(query: str, limit: int = 40) -> list[RemoteSong]:
    """Scrape ultrastar-es (may be slow/down). Songs include YouTube IDs for yt-dlp."""
    if not _REQ:
        return []
    try:
        sess = _session()
        r = sess.get(ES_SEARCH, params={"busqueda": query}, timeout=20)

        items = re.findall(
            r'<li\s+title="See all complete information of ([^"]+?)"\s+'
            r'data-id="([^"]+?)"[^>]*>(.*?)</li>',
            r.text, re.S,
        )

        results = []
        for title_attr, yt_id, content in items[:limit]:
            if " - " in title_attr:
                artist, title = title_attr.split(" - ", 1)
            else:
                artist, title = "", title_attr

            lang = re.search(
                r'<dt>Language</dt>\s*<dd><a[^>]+>([^<]+)</a>', content)
            year = re.search(
                r'<dt>Year</dt>\s*<dd><a[^>]+>(\d+)', content)
            txt_m = re.search(
                r'href="(/[^"]*descargar/txt[^"]*?)"', content)

            results.append(RemoteSong(
                source="es",
                song_id=yt_id,
                title=title.strip(),
                artist=artist.strip(),
                language=lang.group(1).strip() if lang else "",
                year=year.group(1) if year else "",
                has_audio=True,
                youtube_id=yt_id,
                detail_url=f"https://www.youtube.com/watch?v={yt_id}",
                txt_url=(ES_BASE + txt_m.group(1)) if txt_m else "",
            ))
        return results
    except Exception as e:
        print(f"[ultrastar-es] Search error: {e}")
        return []


# ── Source 3: Karaoke Mugen (kara.moe) ───────────────────────────────────────
# Free public REST API — anime, J-pop, K-pop, Western pop.
# Lyrics: .ass format (SubStation Alpha with \k timing tags) → converted to UltraStar.
# Audio: .mp3/.mp4 directly downloadable from kara.moe CDN.

KARA_API  = "https://kara.moe/api/karas/search"
KARA_LYR  = "https://kara.moe/downloads/lyrics/{kid}.ass"
KARA_MED  = "https://kara.moe/downloads/medias/{kid}"   # + extension from mediafile


def search_kara(query: str, limit: int = 30) -> list[RemoteSong]:
    """Search kara.moe for karaoke songs. Free, no auth required."""
    if not _REQ:
        return []
    try:
        sess = _session()
        r = sess.get(KARA_API,
                     params={"q": query, "size": limit, "from": 0},
                     timeout=15)
        if r.status_code != 200:
            return []
        data    = r.json()
        content = data.get("content", [])
        results = []
        for item in content:
            titles = item.get("titles", {})
            title  = (titles.get("eng") or titles.get("qro")
                      or next(iter(titles.values()), "Unknown"))
            singers = [s["name"] for s in item.get("singers", [])]
            artist  = " & ".join(singers) if singers else "Unknown"
            langs   = [l.get("short", l.get("name", "")) for l in item.get("langs", [])]
            year    = str(item.get("year", "")) if item.get("year") else ""
            kid     = item.get("kid", "")
            mf      = item.get("mediafile", "")           # e.g. "uuid.mp3" or "uuid.mp4"
            dur     = int(item.get("duration", 0) or 0)

            if not kid:
                continue

            results.append(RemoteSong(
                source     = "kara",
                song_id    = kid,
                title      = title,
                artist     = artist,
                language   = "/".join(langs) if langs else "",
                year       = year,
                has_audio  = True,
                kara_kid   = kid,
                duration   = dur,
                detail_url = f"https://kara.moe/kara/{kid}",
            ))
        return results
    except Exception as e:
        print(f"[kara.moe] Search error: {e}")
        return []


def _ass_to_ultrastar(ass_content: str, gap_ms: float = 0.0,
                      bpm: float = 120.0) -> list[str]:
    """Convert SubStation Alpha .ass with \\k tags to UltraStar note lines.

    \\kN means N centiseconds per syllable (N*10 = ms).
    """
    ms_per_beat = 60000.0 / (bpm * 4.0)

    def tc_to_ms(tc: str) -> float:
        """Convert h:mm:ss.cs to milliseconds."""
        parts = tc.strip().split(":")
        try:
            if len(parts) == 3:
                h, m, s = parts
                return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
        except ValueError:
            pass
        return 0.0

    def ms_to_beat(ms: float) -> int:
        return max(0, int(round((ms - gap_ms) / ms_per_beat)))

    notes    = []
    dialogues = re.findall(
        r'^Dialogue:\s*\d+,([^,]+),([^,]+),[^,]*,[^,]*,\d+,\d+,\d+,[^,]*,(.*)',
        ass_content, re.MULTILINE)

    # Sort by start time
    dialogues = sorted(dialogues, key=lambda d: tc_to_ms(d[0]))

    # Remove override tags we don't need
    def strip_tags(txt):
        return re.sub(r'\{[^\\k][^}]*\}', '', txt)

    prev_end_ms = 0
    line_break_needed = False

    for i, (start_tc, end_tc, raw_text) in enumerate(dialogues):
        start_ms = tc_to_ms(start_tc)
        end_ms   = tc_to_ms(end_tc)

        if start_ms == 0 and end_ms == 0:
            continue

        # Add line break if there was a gap > 1s since last line
        if line_break_needed or (i > 0 and start_ms - prev_end_ms > 1000):
            if notes:
                notes.append(f"- {ms_to_beat(start_ms)}")

        # Strip override tags but keep \k tags
        clean_text = re.sub(r'\{(?!\\k)[^}]*\}', '', raw_text)
        # Remove {\an*} and similar positioning tags
        clean_text = re.sub(r'\{\\an\d+\}', '', clean_text)
        clean_text = re.sub(r'\{\\pos[^}]+\}', '', clean_text)

        # Check if has \k timing tags
        k_parts = re.findall(r'\{\\k(\d+)\}([^{]*)', clean_text)

        if k_parts:
            # Word-level timed syllables
            cur_ms = start_ms
            for ki, (k_str, syl_text) in enumerate(k_parts):
                k_cs     = int(k_str)           # centiseconds
                syl_ms   = k_cs * 10            # → milliseconds
                syl_text = syl_text.rstrip('\r\n')
                if not syl_text:
                    cur_ms += syl_ms
                    continue
                beat     = ms_to_beat(cur_ms)
                dur_beat = max(1, int(round(syl_ms / ms_per_beat)))
                txt      = (" " + syl_text.strip()) if ki > 0 else syl_text.strip()
                notes.append(f": {beat} {dur_beat} 50 {txt}")
                cur_ms += syl_ms
        else:
            # No \k tags — treat whole line as one note
            text = re.sub(r'\{[^}]+\}', '', clean_text).strip()
            if not text:
                prev_end_ms = end_ms
                line_break_needed = False
                continue
            words = text.split()
            if not words:
                prev_end_ms = end_ms
                continue
            total_ms = max(1, end_ms - start_ms)
            per_word_ms = total_ms / len(words)
            for wi, word in enumerate(words):
                w_ms  = start_ms + int(wi * per_word_ms)
                beat  = ms_to_beat(w_ms)
                dur   = max(1, int(round(per_word_ms / ms_per_beat)))
                txt   = (" " + word) if wi > 0 else word
                notes.append(f": {beat} {dur} 50 {txt}")

        prev_end_ms = end_ms
        line_break_needed = False

        # If the next entry starts >1s later, flag a line break
        if i + 1 < len(dialogues):
            next_start = tc_to_ms(dialogues[i + 1][0])
            if next_start - end_ms > 1000:
                line_break_needed = True

    return notes


def download_kara(song: RemoteSong, dest_dir: str,
                  progress_cb: Callable = None) -> dict:
    """Download lyrics (.ass→.txt) and audio from kara.moe.

    Returns dict with keys: txt_path, audio_path, error.
    """
    if not _REQ:
        return {"error": "requests not available"}

    kid     = song.kara_kid
    stem    = f"{song.artist} - {song.title}".replace("/", "_").replace(":", "-")
    folder  = os.path.join(dest_dir, stem)
    os.makedirs(folder, exist_ok=True)

    result = {"txt_path": None, "audio_path": None, "error": None}

    sess = _session()

    # 1. Download .ass lyrics
    if progress_cb:
        progress_cb("Downloading lyrics from Karaoke Mugen...")
    try:
        r = sess.get(KARA_LYR.format(kid=kid), timeout=30, stream=True)
        if r.status_code == 200:
            ass_bytes = r.content
            ass_text  = ass_bytes.decode("utf-8-sig", errors="replace")
            note_lines = _ass_to_ultrastar(ass_text)

            # Detect actual media extension from kara.moe metadata
            audio_ext = ".mp3"

            txt_name = f"{stem}.txt"
            txt_path = os.path.join(folder, txt_name)
            header = [
                f"#TITLE:{song.title}",
                f"#ARTIST:{song.artist}",
                f"#LANGUAGE:{song.language}",
                f"#YEAR:{song.year}",
                "#BPM:120",
                "#GAP:0",
                f"#MP3:audio{audio_ext}",
                "#COVER:cover.jpg",
            ]
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(header + note_lines + ["E"]) + "\n")
            result["txt_path"] = txt_path
        else:
            result["error"] = f"Lyrics download failed: HTTP {r.status_code}"
    except Exception as e:
        result["error"] = f"Lyrics error: {e}"
        return result

    # 2. Download audio (try .mp3 then .mp4)
    if progress_cb:
        progress_cb("Downloading audio from Karaoke Mugen...")
    audio_path = None
    for ext in (".mp3", ".mp4", ".ogg"):
        audio_url  = KARA_MED.format(kid=kid) + ext
        audio_dest = os.path.join(folder, f"audio{ext}")
        if os.path.exists(audio_dest):
            audio_path = audio_dest
            break
        try:
            r = sess.get(audio_url, timeout=5, stream=True)
            if r.status_code == 200:
                total = int(r.headers.get("Content-Length", 0))
                downloaded = 0
                with open(audio_dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_cb:
                            pct = downloaded / total
                            progress_cb(f"Audio {int(pct*100)}%")
                audio_path = audio_dest
                break
        except Exception:
            continue

    if audio_path:
        result["audio_path"] = audio_path
        # Patch the #MP3 tag with actual extension
        ext = os.path.splitext(audio_path)[1]
        if result["txt_path"] and ext != ".mp3":
            _patch_mp3_tag(result["txt_path"], f"audio{ext}")
    else:
        # Fall back to YouTube search
        if progress_cb:
            progress_cb("Falling back to YouTube for audio...")
        result["audio_path"] = download_audio(
            f"ytsearch1:{song.artist} {song.title}",
            folder, "audio", progress_cb=progress_cb,
        )
        if result["audio_path"]:
            _patch_mp3_tag(result["txt_path"],
                           os.path.basename(result["audio_path"]))

    return result


# ── Source 4: YouTube Karaoke (yt-dlp) ───────────────────────────────────────

def search_youtube_karaoke(query: str, limit: int = 20) -> list[RemoteSong]:
    """Search YouTube for karaoke videos. Always appends 'karaoke' to query."""
    if not _YTDLP:
        return []
    kq = query.strip() + " karaoke"
    ydl_opts = {
        "quiet":          True,
        "no_warnings":    True,
        "extract_flat":   True,
        "skip_download":  True,
        "default_search": "ytsearch",
        "playlistend":    limit,
    }
    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info    = ydl.extract_info(f"ytsearch{limit}:{kq}", download=False)
            entries = info.get("entries", []) if info else []
            for e in entries:
                if not e:
                    continue
                vid_id = e.get("id") or ""
                if not vid_id:
                    continue
                title  = e.get("title", "Unknown")
                # Try to parse "Artist - Title (Karaoke)" pattern
                m = re.match(r'^(.+?)\s*[-–]\s*(.+?)(?:\s*[\(\[].+[\)\]])?$', title)
                if m:
                    artist = m.group(1).strip()
                    song_t = re.sub(r'\bkaraoke\b', "", m.group(2),
                                    flags=re.IGNORECASE).strip(" -|()")
                else:
                    artist = e.get("uploader", "") or ""
                    song_t = re.sub(r'\bkaraoke\b', "", title,
                                    flags=re.IGNORECASE).strip(" -|")

                results.append(RemoteSong(
                    source     = "youtube",
                    song_id    = vid_id,
                    title      = song_t or title,
                    artist     = artist,
                    has_audio  = True,
                    youtube_id = vid_id,
                    duration   = int(e.get("duration") or 0),
                    detail_url = f"https://www.youtube.com/watch?v={vid_id}",
                    genre      = f"{int(e.get('duration',0)//60)}:{int(e.get('duration',0)%60):02d}",
                ))
    except Exception as e:
        print(f"[YouTube search] {e}")
    return results


def download_youtube_karaoke(song: RemoteSong, dest_dir: str,
                             progress_cb: Callable = None) -> dict:
    """Download YouTube karaoke: audio (mp3) + subtitle extraction → UltraStar .txt."""
    from engine.youtube_client import download_karaoke as yt_dl, DownloadResult, YTVideo
    import tempfile

    result = {"txt_path": None, "audio_path": None, "error": None}

    vid = YTVideo(
        vid_id       = song.youtube_id,
        title        = f"{song.artist} - {song.title}",
        channel      = song.artist,
        duration_s   = song.duration,
        thumbnail_url= f"https://img.youtube.com/vi/{song.youtube_id}/mqdefault.jpg",
    )
    dr = DownloadResult()

    def _cb(p):
        dr.progress = p
        if progress_cb:
            progress_cb(f"{dr.stage} {int(p*100)}%")

    try:
        download_karaoke(vid, dest_dir, dr, progress_cb=_cb)
    except Exception as e:
        result["error"] = str(e)
        return result

    if dr.error:
        result["error"] = dr.error
    result["txt_path"]   = dr.txt_path
    result["audio_path"] = dr.mp3_path
    return result


# ── FFmpeg detection ─────────────────────────────────────────────────────────

_AUDIO_EXTS = (".mp3", ".m4a", ".ogg", ".opus", ".webm", ".aac", ".flac", ".wav")

# Common install locations not always in PATH (Homebrew macOS, etc.)
_FFMPEG_SEARCH = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/snap/bin",
]


def _find_ffmpeg() -> Optional[str]:
    """Return directory containing ffmpeg, or None if not found anywhere."""
    import shutil
    # First try PATH
    if shutil.which("ffmpeg"):
        import os as _os
        return _os.path.dirname(shutil.which("ffmpeg"))
    # Then try known locations
    for d in _FFMPEG_SEARCH:
        if os.path.isfile(os.path.join(d, "ffmpeg")):
            return d
    return None


_FFMPEG_DIR: Optional[str] = _find_ffmpeg()   # resolved once at import


# ── Audio download via yt-dlp ─────────────────────────────────────────────────

def download_audio(youtube_url_or_query: str, dest_folder: str,
                   filename_stem: str,
                   progress_cb: Callable[[str], None] = None) -> Optional[str]:
    """Download best audio from YouTube.

    With ffmpeg available → converts to MP3 192k.
    Without ffmpeg → downloads native format (m4a / opus / webm).
    pygame.mixer can play all of these, so either path works.
    """
    if not _YTDLP:
        return None

    out_tmpl = os.path.join(dest_folder, f"{filename_stem}.%(ext)s")

    def hook(d):
        if progress_cb and d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            progress_cb(f"Downloading audio {pct}")

    def _find_downloaded() -> Optional[str]:
        for ext in _AUDIO_EXTS:
            p = os.path.join(dest_folder, f"{filename_stem}{ext}")
            if os.path.exists(p):
                return p
        return None

    ydl_opts: dict = {
        "format":         "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl":        out_tmpl,
        "quiet":          True,
        "no_warnings":    True,
        "progress_hooks": [hook],
        "noplaylist":     True,
    }

    if _FFMPEG_DIR:
        # FFmpeg found — convert to MP3 for maximum compatibility
        ydl_opts["ffmpeg_location"] = _FFMPEG_DIR
        ydl_opts["postprocessors"]  = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
        preferred_ext = ".mp3"
        if progress_cb:
            pass   # normal flow
    else:
        # No FFmpeg — download native format (m4a preferred, pygame plays it fine)
        preferred_ext = None
        if progress_cb:
            progress_cb("Note: ffmpeg not found — downloading native audio format")

    preferred_path = (os.path.join(dest_folder, f"{filename_stem}{preferred_ext}")
                      if preferred_ext else None)

    urls_to_try = [youtube_url_or_query]
    if "youtube.com/watch" in youtube_url_or_query or "youtu.be/" in youtube_url_or_query:
        urls_to_try.append(f"ytsearch1:{filename_stem}")

    for url in urls_to_try:
        if preferred_path and os.path.exists(preferred_path):
            return preferred_path
        found = _find_downloaded()
        if found:
            return found
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            if preferred_path and os.path.exists(preferred_path):
                return preferred_path
            found = _find_downloaded()
            if found:
                return found
        except Exception as e:
            print(f"[yt-dlp] {url!r}: {e}")

    return None


# ── Cover art ─────────────────────────────────────────────────────────────────

COVER_FILENAME = "cover.jpg"
_ITUNES_URL    = "https://itunes.apple.com/search"


def download_cover(artist: str, title: str, dest_folder: str,
                   force: bool = False) -> Optional[str]:
    """Download album art via iTunes Search API. Returns saved path or None."""
    if not _REQ:
        return None
    dest = os.path.join(dest_folder, COVER_FILENAME)
    if os.path.exists(dest) and not force:
        return dest
    try:
        sess = _session()
        r = sess.get(_ITUNES_URL,
                     params={"term": f"{artist} {title}", "entity": "song", "limit": 5},
                     timeout=10)
        results = r.json().get("results", [])
        if not results:
            r = sess.get(_ITUNES_URL,
                         params={"term": artist, "entity": "musicArtist", "limit": 3},
                         timeout=10)
            results = r.json().get("results", [])
        if not results:
            return None
        url = results[0].get("artworkUrl100", "")
        if not url:
            return None
        url = url.replace("100x100bb", "600x600bb").replace("100x100", "600x600")
        img_r = sess.get(url, timeout=15)
        if img_r.status_code != 200:
            return None
        with open(dest, "wb") as f:
            f.write(img_r.content)
        return dest
    except Exception as e:
        print(f"[Cover] {e}")
        return None


def _patch_cover_tag(txt_path: str, cover_filename: str):
    """Insert or replace #COVER: in an existing UltraStar .txt."""
    try:
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not l.upper().startswith("#COVER:")]
        insert_at = 0
        for i, l in enumerate(new_lines):
            if l.upper().startswith("#ARTIST:") or l.upper().startswith("#TITLE:"):
                insert_at = i + 1
        new_lines.insert(insert_at, f"#COVER:{cover_filename}\n")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[Cover patch] {e}")


def _make_stub_txt(folder: str, artist: str, title: str,
                   audio_filename: str, cover_filename: str = "") -> str:
    """Create a minimal UltraStar .txt so the song is loadable."""
    lines = [
        f"#TITLE:{title}\n",
        f"#ARTIST:{artist}\n",
        f"#MP3:{audio_filename}\n",
    ]
    if cover_filename:
        lines.append(f"#COVER:{cover_filename}\n")
    lines += ["#BPM:120\n", "#GAP:0\n", "E\n"]
    safe = f"{artist} - {title}".replace("/", "_").replace(":", "-")
    path = os.path.join(folder, f"{safe}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return path


def _patch_mp3_tag(txt_path: str, mp3_name: str):
    """Insert or replace #MP3 tag in an existing UltraStar .txt."""
    try:
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        new_lines = []
        has_mp3   = False
        for line in lines:
            if line.startswith("#MP3:") or line.startswith("#AUDIO:"):
                new_lines.append(f"#MP3:{mp3_name}\n")
                has_mp3 = True
            else:
                new_lines.append(line)
        if not has_mp3:
            insert_at = 0
            for i, l in enumerate(new_lines):
                if l.startswith("#"):
                    insert_at = i + 1
            new_lines.insert(insert_at, f"#MP3:{mp3_name}\n")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[patch_mp3] {e}")


# ── Unified search & download manager ────────────────────────────────────────

# Source ordering for UI display
ALL_SOURCES = ["usdb", "es", "kara", "youtube"]


class SearchManager:
    """Runs searches across sources in background threads, streams partial results."""

    def __init__(self, songs_dir: str, usdb_user: str = "", usdb_pass: str = ""):
        self.songs_dir  = songs_dir
        self._user      = usdb_user
        self._pass      = usdb_pass
        self._usdb_sess = None
        self._results:    list[RemoteSong] = []
        self._lock      = threading.Lock()
        self._busy      = False
        self._status    = ""
        self._cancel    = False    # set True to abort in-flight search
        self._dl_status:   dict[str, str]   = {}
        self._dl_progress: dict[str, float] = {}
        # Pagination state
        self._current_query  : str       = ""
        self._current_sources: list[str] = list(ALL_SOURCES)
        self._current_limit  : int       = 20

    def _get_usdb_session(self):
        if self._usdb_sess is None:
            self._usdb_sess = _session()
            if self._user and self._pass:
                ok = _usdb_login(self._usdb_sess, self._user, self._pass)
                self._status = "USDB logged in" if ok else "USDB: login failed"
        return self._usdb_sess

    @property
    def results(self) -> list[RemoteSong]:
        with self._lock:
            return list(self._results)

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def status(self) -> str:
        return self._status

    def search(self, query: str, sources: list[str] = None, limit: int = 20):
        """Start a search. Cancels any in-flight search and starts fresh."""
        self._cancel = True
        sources = sources or list(ALL_SOURCES)
        self._busy           = True
        self._cancel         = False
        self._status         = "Searching..."
        self._current_query  = query
        self._current_sources = list(sources)
        self._current_limit  = limit
        with self._lock:
            self._results = []
        threading.Thread(target=self._search_bg, args=(query, sources, limit),
                         daemon=True).start()

    def load_more(self):
        """Append 20 more results by re-running the last search with limit+20."""
        if not self._current_query or self._busy:
            return
        new_limit = self._current_limit + 20
        self._cancel = True
        self._busy           = True
        self._cancel         = False
        self._status         = "Loading more..."
        self._current_limit  = new_limit
        with self._lock:
            self._results = []
        threading.Thread(
            target=self._search_bg,
            args=(self._current_query, self._current_sources, new_limit),
            daemon=True,
        ).start()

    def _search_bg(self, query: str, sources: list[str], limit: int):
        partial:  dict[str, list] = {}
        lock      = threading.Lock()
        threads   = []

        def run(name, fn, *args):
            try:
                r = fn(*args)
            except Exception as e:
                print(f"[{name}] {e}")
                r = []
            if self._cancel:
                return
            with lock:
                partial[name] = r
            # Stream partial results immediately
            combined = []
            for src in ALL_SOURCES:
                combined.extend(partial.get(src, []))
            with self._lock:
                self._results = combined
            n = sum(len(v) for v in partial.values())
            self._status = f"{n} result{'s' if n!=1 else ''} found — still searching..."

        try:
            if "usdb" in sources:
                if self._user and self._pass:
                    sess = self._get_usdb_session()
                    t = threading.Thread(
                        target=run, args=("usdb", search_usdb, query, sess, limit),
                        daemon=True)
                    threads.append(t); t.start()
                else:
                    self._status = "USDB: add credentials in Settings to search"

            if "es" in sources:
                t = threading.Thread(target=run, args=("es", search_es, query, limit),
                                     daemon=True)
                threads.append(t); t.start()

            if "kara" in sources:
                t = threading.Thread(target=run, args=("kara", search_kara, query, limit),
                                     daemon=True)
                threads.append(t); t.start()

            if "youtube" in sources:
                t = threading.Thread(
                    target=run, args=("youtube", search_youtube_karaoke, query, limit),
                    daemon=True)
                threads.append(t); t.start()

            for t in threads:
                t.join(timeout=40)

        except Exception as e:
            self._status = f"Search error: {e}"
        finally:
            if not self._cancel:
                with self._lock:
                    n = len(self._results)
                self._status = (f"{n} result{'s' if n!=1 else ''} found"
                                if n > 0 else "No results found")
            self._busy = False

    def dl_status(self, song_id: str) -> str:
        return self._dl_status.get(song_id, "")

    def dl_progress(self, song_id: str) -> float:
        return self._dl_progress.get(song_id, 0.0)

    def download(self, song: RemoteSong, on_done: Callable = None):
        sid = song.song_id
        if self._dl_status.get(sid) in ("downloading", "done"):
            return
        self._dl_status[sid]   = "downloading"
        self._dl_progress[sid] = 0.0
        threading.Thread(target=self._download_bg, args=(song, on_done),
                         daemon=True).start()

    def _download_bg(self, song: RemoteSong, on_done):
        sid = song.song_id
        try:
            os.makedirs(self.songs_dir, exist_ok=True)
            stem   = f"{song.artist} - {song.title}".replace("/", "_").replace(":", "-")
            folder = os.path.join(self.songs_dir, stem)
            os.makedirs(folder, exist_ok=True)

            import re as _re

            def status(msg):
                self._status = msg
                m = _re.search(r'([\d.]+)%', msg)
                self._dl_progress[sid] = float(m.group(1)) / 100.0 if m else 0.0

            # ── ES ──────────────────────────────────────────────────────────
            if song.source == "es":
                yt_url = f"https://www.youtube.com/watch?v={song.youtube_id}"

                # 1. Download audio + subtitles in parallel
                audio_result: list = [None]
                note_result:  list = [[]]

                def _fetch_audio_es():
                    audio_result[0] = download_audio(
                        yt_url, folder, stem, progress_cb=status)

                def _fetch_notes_es():
                    # Try ES txt_url first (official UltraStar file)
                    if song.txt_url:
                        try:
                            sess = _session()
                            r = sess.get(song.txt_url, timeout=15)
                            if r.status_code == 200 and b"#TITLE" in r.content[:500]:
                                note_result[0] = [("__txt__", r.content)]
                                return
                        except Exception as e:
                            print(f"[ES txt_url] {e}")
                    # Fall back: YouTube subtitles via yt-dlp
                    status("Fetching lyrics from YouTube subtitles...")
                    try:
                        from engine.youtube_client import fetch_subtitles_as_ultrastar
                        note_result[0] = fetch_subtitles_as_ultrastar(yt_url)
                    except Exception as e:
                        print(f"[ES subtitles] {e}")

                status(f"Downloading: {song.title}...")
                t_audio = threading.Thread(target=_fetch_audio_es, daemon=True)
                t_notes = threading.Thread(target=_fetch_notes_es, daemon=True)
                t_audio.start(); t_notes.start()
                t_audio.join(); t_notes.join()

                audio_path  = audio_result[0]
                notes_data  = note_result[0]

                if audio_path:
                    audio_file = os.path.basename(audio_path)
                    status("Fetching cover art...")
                    cover_path = download_cover(song.artist, song.title, folder)
                    cover_file = os.path.basename(cover_path) if cover_path else ""

                    # Write txt — either from ES official file, subtitle lines, or stub
                    if notes_data and isinstance(notes_data[0], tuple) and notes_data[0][0] == "__txt__":
                        # Official UltraStar txt from ES website
                        raw_txt = notes_data[0][1]
                        txt_path = os.path.join(folder, f"{stem}.txt")
                        with open(txt_path, "wb") as f:
                            f.write(raw_txt)
                        _patch_mp3_tag(txt_path, audio_file)
                        if cover_file:
                            _patch_cover_tag(txt_path, cover_file)
                    elif notes_data:
                        # Subtitle-derived UltraStar lines
                        txt_path = os.path.join(folder, f"{stem}.txt")
                        header = [
                            f"#TITLE:{song.title}",
                            f"#ARTIST:{song.artist}",
                            f"#LANGUAGE:{song.language}",
                            "#BPM:120",
                            "#GAP:0",
                            f"#MP3:{audio_file}",
                        ]
                        if cover_file:
                            header.append(f"#COVER:{cover_file}")
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write("\n".join(header + notes_data + ["E"]) + "\n")
                    else:
                        # No lyrics found — create audio-only stub
                        _make_stub_txt(folder, song.artist, song.title,
                                       audio_file, cover_file)

                    self._dl_status[sid] = "done"
                    self._dl_progress[sid] = 1.0
                    status(f"Downloaded: {song.title}")
                else:
                    self._dl_status[sid] = "error"
                    status(f"Could not download audio for {song.title}")

            # ── USDB ─────────────────────────────────────────────────────────
            elif song.source == "usdb":
                txt_result:   list = [None]
                audio_result: list = [None]

                def _fetch_txt():
                    txt_result[0] = download_usdb_txt(
                        song, self.songs_dir, self._get_usdb_session())

                def _fetch_audio():
                    audio_result[0] = download_audio(
                        f"ytsearch1:{song.artist} {song.title} official audio",
                        folder, stem, progress_cb=status,
                    )

                status("Downloading lyrics + audio in parallel...")
                t_txt   = threading.Thread(target=_fetch_txt,   daemon=True)
                t_audio = threading.Thread(target=_fetch_audio, daemon=True)
                t_txt.start(); t_audio.start()
                t_audio.join()
                status("Waiting for lyrics...")
                t_txt.join()

                txt_path   = txt_result[0]
                audio_path = audio_result[0]

                if not txt_path:
                    if not (self._user and self._pass):
                        self._dl_status[sid] = "need_login"
                        status("USDB: add credentials in Settings")
                    else:
                        self._dl_status[sid] = "error"
                        status("USDB: could not download lyrics file")
                    return

                if audio_path:
                    _patch_mp3_tag(txt_path, os.path.basename(audio_path))
                    status("Fetching cover art...")
                    cover_path = download_cover(song.artist, song.title, folder)
                    if cover_path:
                        _patch_cover_tag(txt_path, os.path.basename(cover_path))
                self._dl_status[sid] = "done"
                self._dl_progress[sid] = 1.0
                status(f"Downloaded: {song.title}")

            # ── Karaoke Mugen ────────────────────────────────────────────────
            elif song.source == "kara":
                r = download_kara(song, self.songs_dir, progress_cb=status)
                if r.get("error"):
                    self._dl_status[sid] = "error"
                    status(f"Error: {r['error']}")
                else:
                    txt_path = r.get("txt_path")
                    if txt_path:
                        status("Fetching cover art...")
                        cover_path = download_cover(song.artist, song.title,
                                                    os.path.dirname(txt_path))
                        if cover_path:
                            _patch_cover_tag(txt_path,
                                             os.path.basename(cover_path))
                    self._dl_status[sid] = "done"
                    self._dl_progress[sid] = 1.0
                    status(f"Downloaded: {song.title}")

            # ── YouTube Karaoke ──────────────────────────────────────────────
            elif song.source == "youtube":
                from engine.youtube_client import (
                    download_karaoke as yt_dl_fn, DownloadResult, YTVideo)

                vid = YTVideo(
                    vid_id       = song.youtube_id,
                    title        = f"{song.artist} - {song.title}",
                    channel      = song.artist,
                    duration_s   = song.duration,
                    thumbnail_url= (f"https://img.youtube.com/vi/"
                                    f"{song.youtube_id}/mqdefault.jpg"),
                )
                dr = DownloadResult()

                def _yt_cb(p):
                    self._dl_progress[sid] = p
                    status(f"{dr.stage} {int(p*100)}%")

                yt_dl_fn(vid, self.songs_dir, dr, progress_cb=_yt_cb)

                if dr.error:
                    self._dl_status[sid] = "error"
                    status(f"Error: {dr.error}")
                else:
                    self._dl_status[sid] = "done"
                    self._dl_progress[sid] = 1.0
                    status(f"Downloaded: {song.title}")

        except Exception as e:
            self._dl_status[sid] = "error"
            err_str = str(e)
            # Produce a concise user-visible message for common errors
            if "ffmpeg" in err_str.lower() or "ffprobe" in err_str.lower():
                self._status = "Audio download failed: ffmpeg not found — install via: brew install ffmpeg"
            elif "Audio download failed" in err_str:
                self._status = err_str[:120]
            else:
                self._status = f"Download error: {err_str[:100]}"
            print(f"[Download] {e}")
        finally:
            if on_done:
                on_done(song)
