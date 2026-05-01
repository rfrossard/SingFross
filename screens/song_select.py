"""Song selection screen — Vocaluxe-style filtering & sorting, YARG layout."""
import pygame, os, threading, glob
from screens.base_screen import BaseScreen
from ui import theme as T
import ui.components as C
from engine.song_parser import scan_library
from engine import config as CFG

SONGS_DIR = os.path.join(os.path.dirname(__file__), "..", "songs")

SORT_MODES = ["TITLE", "ARTIST", "BPM", "YEAR"]


class _Card:
    def __init__(self, song):
        self.song           = song
        self._cover         = None
        self._tried         = False
        self._cover_fetching = False

    def cover(self, size=(200, 200)):
        if not self._tried:
            self._tried = True
            cp = self.song.cover_path
            if cp:
                try:
                    img = pygame.image.load(cp).convert()
                    self._cover = pygame.transform.smoothscale(img, size)
                except Exception:
                    pass
        return self._cover

    def fetch_cover_async(self, force: bool = False, query: str = None):
        """Trigger a background iTunes cover download.

        force=True  — re-download even if a cover already exists.
        query       — custom iTunes search string; if None uses "artist title".
        """
        if self._cover_fetching:
            return
        if not force and self.song.cover_path and query is None:
            return
        if not (self.song.artist or self.song.title):
            return
        self._cover_fetching = True

        song = self.song
        card = self

        def _worker():
            try:
                from engine.usdb_client import download_cover, _patch_cover_tag
                import glob
                cover_path = download_cover(song.artist, song.title, song.folder,
                                            force=True, query=query)
                if cover_path:
                    song.cover = os.path.basename(cover_path)
                    txts = glob.glob(os.path.join(song.folder, "*.txt"))
                    for t in txts:
                        _patch_cover_tag(t, os.path.basename(cover_path))
                    card._tried = False   # force reload on next draw
                    card._cover = None
            except Exception as e:
                print(f"[Cover async] {e}")
            finally:
                card._cover_fetching = False
        threading.Thread(target=_worker, daemon=True).start()


class SongSelectScreen(BaseScreen):

    ROW_H    = 82
    ROW_PAD  = 6
    LIST_X   = 20
    LIST_W   = 680
    DETAIL_X = 720

    def __init__(self, game):
        super().__init__(game)
        self._all_cards: list[_Card] = []
        self._cards:     list[_Card] = []
        self._sel        = 0
        self._scroll     = 0.0
        self._t          = 0.0
        self._sort_idx   = 0            # index into SORT_MODES
        self._filter_q   = ""           # active search query
        self._search_active = False     # is the search box focused?
        self._cursor_t   = 0.0
        self._sort_rects: list[pygame.Rect] = []
        # Per-song background-op status: "idle" | "fetching" | "done" | "error"
        self._lyrics_dl: dict[str, str] = {}   # keyed by song.folder
        self._cover_dl:  dict[str, str] = {}
        self._lyrics_btn: pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._cover_btn:  pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._rename_btn: pygame.Rect = pygame.Rect(0, 0, 1, 1)

        # ── Cover search-query editing (shown inline when cover btn clicked) ──
        self._cover_search        : bool  = False   # True = input bar visible
        self._cover_search_q      : str   = ""      # editable query string
        self._cover_confirm_btn   : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._cover_cancel_btn    : pygame.Rect = pygame.Rect(0, 0, 1, 1)

        # ── Rename modal ─────────────────────────────────────────────────────
        self._rename_mode    : bool = False
        self._rename_title   : str  = ""
        self._rename_artist  : str  = ""
        self._rename_field   : int  = 0    # 0 = title field, 1 = artist field
        # modal button rects — set in draw
        self._rename_ok_btn  : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._rename_can_btn : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._rename_title_r : pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._rename_artist_r: pygame.Rect = pygame.Rect(0, 0, 1, 1)

        self._reload()

    # ── Library ───────────────────────────────────────────────────────────────

    def _reload(self):
        cfg = CFG.get()
        songs_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", cfg._data.get("songs_dir","songs")))
        raw = scan_library(songs_dir)
        self._all_cards = [_Card(s) for s in raw]
        self._apply_filter()

    def _apply_filter(self):
        q = self._filter_q.lower().strip()
        if q:
            self._cards = [
                c for c in self._all_cards
                if q in c.song.title.lower() or q in c.song.artist.lower()
                or q in (c.song.genre or "").lower()
            ]
        else:
            self._cards = list(self._all_cards)
        self._sort()
        self._sel = min(self._sel, max(0, len(self._cards) - 1))

    def _sort(self):
        mode = SORT_MODES[self._sort_idx]
        if mode == "TITLE":
            self._cards.sort(key=lambda c: c.song.title.lower())
        elif mode == "ARTIST":
            self._cards.sort(key=lambda c: c.song.artist.lower())
        elif mode == "BPM":
            self._cards.sort(key=lambda c: c.song.bpm, reverse=True)
        elif mode == "YEAR":
            self._cards.sort(
                key=lambda c: int(c.song.year) if (c.song.year or "").isdigit() else 0,
                reverse=True)

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_event(self, event):
        # ── Rename modal intercepts all input while open ──────────────────────
        if self._rename_mode:
            if event.type == pygame.KEYDOWN:
                k = event.key
                if k == pygame.K_ESCAPE:
                    self._rename_mode = False
                elif k == pygame.K_RETURN:
                    self._commit_rename()
                elif k == pygame.K_TAB:
                    self._rename_field = 1 - self._rename_field
                elif k == pygame.K_BACKSPACE:
                    if self._rename_field == 0:
                        self._rename_title = self._rename_title[:-1]
                    else:
                        self._rename_artist = self._rename_artist[:-1]
                elif event.unicode and event.unicode.isprintable():
                    if self._rename_field == 0:
                        self._rename_title += event.unicode
                    else:
                        self._rename_artist += event.unicode
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._rename_ok_btn.collidepoint(event.pos):
                    self._commit_rename()
                elif self._rename_can_btn.collidepoint(event.pos):
                    self._rename_mode = False
                elif self._rename_title_r.collidepoint(event.pos):
                    self._rename_field = 0
                elif self._rename_artist_r.collidepoint(event.pos):
                    self._rename_field = 1
            return

        # ── Cover search query input intercepts keypresses while open ─────────
        if self._cover_search:
            if event.type == pygame.KEYDOWN:
                k = event.key
                if k == pygame.K_ESCAPE:
                    self._cover_search = False
                elif k == pygame.K_RETURN:
                    self._start_cover_fetch()
                elif k == pygame.K_BACKSPACE:
                    self._cover_search_q = self._cover_search_q[:-1]
                elif event.unicode and event.unicode.isprintable():
                    self._cover_search_q += event.unicode
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._cover_confirm_btn.collidepoint(event.pos):
                    self._start_cover_fetch()
                    return
                if self._cover_cancel_btn.collidepoint(event.pos):
                    self._cover_search = False
                    return
                # Fall through so clicks on other UI elements still work
            # Don't return — allow scroll wheel etc. to pass through

        if event.type == pygame.KEYDOWN:
            k = event.key
            if self._search_active:
                if k == pygame.K_ESCAPE:
                    self._search_active = False
                    self._filter_q = ""
                    self._apply_filter()
                elif k == pygame.K_RETURN:
                    self._search_active = False
                elif k == pygame.K_BACKSPACE:
                    self._filter_q = self._filter_q[:-1]
                    self._apply_filter()
                elif event.unicode and event.unicode.isprintable():
                    self._filter_q += event.unicode
                    self._apply_filter()
                return

            if k in (pygame.K_UP, pygame.K_w):
                self._sel = max(0, self._sel - 1)
                self._cover_search = False
            elif k in (pygame.K_DOWN, pygame.K_s):
                self._sel = min(len(self._cards) - 1, self._sel + 1)
                self._cover_search = False
            elif k in (pygame.K_RETURN, pygame.K_SPACE):
                self._play()
            elif k == pygame.K_ESCAPE:
                self.game.pop_screen()
            elif k == pygame.K_r:
                self._reload()
            elif k == pygame.K_i:
                self._import()
            elif k == pygame.K_TAB:
                self._sort_idx = (self._sort_idx + 1) % len(SORT_MODES)
                self._apply_filter()
            elif event.unicode and event.unicode.isprintable():
                # Start typing → activate search
                self._search_active = True
                self._filter_q = event.unicode
                self._apply_filter()

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 4:
                self._sel = max(0, self._sel - 1)
            elif event.button == 5:
                self._sel = min(len(self._cards)-1, self._sel+1)
            elif event.button == 1:
                if self.handle_home_click(event):
                    return
                if hasattr(self, "_back_btn") and self._back_btn.collidepoint(event.pos):
                    self.game.pop_screen()
                    return
                self._click(event.pos)

    def _click(self, pos):
        # Sort pills
        for i, r in enumerate(self._sort_rects):
            if r.collidepoint(pos):
                self._sort_idx = i
                self._apply_filter()
                return

        # Search bar
        if hasattr(self, "_search_bar") and self._search_bar.collidepoint(pos):
            self._search_active = True
            return

        # Clear button
        if hasattr(self,"_clear_btn") and self._clear_btn.collidepoint(pos) and self._filter_q:
            self._filter_q = ""
            self._search_active = False
            self._apply_filter()
            return

        # Song rows
        for i, r in enumerate(getattr(self, "_row_rects", [])):
            if r.collidepoint(pos):
                if i == self._sel:
                    self._play()
                else:
                    self._sel = i
                    self._cover_search = False
                return

        if self._lyrics_btn.collidepoint(pos):
            self._fetch_lyrics()
            return

        if self._cover_btn.collidepoint(pos):
            if self._cards and self._sel < len(self._cards):
                song = self._cards[self._sel].song
                if not self._cards[self._sel]._cover_fetching:
                    # Toggle search bar — pre-fill with suggested query
                    if not self._cover_search:
                        self._cover_search   = True
                        self._cover_search_q = f"{song.artist} {song.title}"
                    else:
                        self._cover_search = False
            return

        if self._rename_btn.collidepoint(pos):
            if self._cards and self._sel < len(self._cards):
                song = self._cards[self._sel].song
                self._rename_title  = song.title
                self._rename_artist = song.artist
                self._rename_field  = 0
                self._rename_mode   = True
            return

        if hasattr(self, "_play_btn") and self._play_btn.collidepoint(pos):
            self._play()

    def _fetch_lyrics(self):
        """Start background lyrics fetch for the selected song."""
        if not self._cards or self._sel >= len(self._cards):
            return
        song = self._cards[self._sel].song
        key  = song.folder or song.title
        if self._lyrics_dl.get(key) == "fetching":
            return
        self._lyrics_dl[key] = "fetching"
        threading.Thread(target=self._fetch_lyrics_bg, args=(song,),
                         daemon=True).start()

    def _fetch_lyrics_bg(self, song):
        """Background: search YouTube for karaoke subtitles, write into the song's .txt."""
        key = song.folder or song.title
        try:
            from engine.youtube_client import fetch_subtitles_as_ultrastar
            try:
                import yt_dlp as _yt
            except ImportError:
                self._lyrics_dl[key] = "error"
                return

            # Find the best YouTube match for this song
            search_q = f"ytsearch1:{song.artist} {song.title} karaoke"
            ydl_opts = {"quiet": True, "no_warnings": True,
                        "extract_flat": True, "skip_download": True}
            yt_url = None
            with _yt.YoutubeDL(ydl_opts) as ydl:
                info    = ydl.extract_info(search_q, download=False)
                entries = (info or {}).get("entries", [])
                if entries and entries[0]:
                    vid_id = entries[0].get("id", "")
                    if vid_id:
                        yt_url = f"https://www.youtube.com/watch?v={vid_id}"

            if not yt_url:
                self._lyrics_dl[key] = "error"
                return

            note_lines = fetch_subtitles_as_ultrastar(yt_url)
            if not note_lines:
                self._lyrics_dl[key] = "error"
                return

            # Patch the existing .txt — replace note lines, keep header
            txt_files = glob.glob(os.path.join(song.folder, "*.txt")) if song.folder else []
            if txt_files:
                txt_path = txt_files[0]
                with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                    raw = f.readlines()
                header = [l for l in raw
                          if l.lstrip().startswith("#")]
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.writelines(header)
                    f.write("\n".join(note_lines) + "\nE\n")
            elif song.folder:
                # Create a new .txt stub with lyrics
                audio_file = song.mp3 or ""
                safe = f"{song.artist} - {song.title}".replace("/", "_").replace(":", "-")
                txt_path = os.path.join(song.folder, f"{safe}.txt")
                header = [
                    f"#TITLE:{song.title}",
                    f"#ARTIST:{song.artist}",
                    f"#LANGUAGE:{song.language}",
                    "#BPM:120", "#GAP:0",
                ]
                if audio_file:
                    header.append(f"#MP3:{audio_file}")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(header + note_lines + ["E"]) + "\n")

            self._lyrics_dl[key] = "done"
        except Exception as e:
            print(f"[FetchLyrics] {e}")
            self._lyrics_dl[key] = "error"

    def _start_cover_fetch(self):
        """Confirm the cover search query and start background download."""
        self._cover_search = False
        if not self._cards or self._sel >= len(self._cards):
            return
        card = self._cards[self._sel]
        song = card.song
        key  = song.folder or song.title
        q    = self._cover_search_q.strip() or f"{song.artist} {song.title}"
        self._cover_dl[key] = "fetching"
        card.fetch_cover_async(force=True, query=q)

    def _commit_rename(self):
        """Apply the rename to the song object and patch the .txt file."""
        self._rename_mode = False
        if not self._cards or self._sel >= len(self._cards):
            return
        new_title  = self._rename_title.strip()
        new_artist = self._rename_artist.strip()
        if not new_title:
            return
        song = self._cards[self._sel].song
        old_title, old_artist = song.title, song.artist
        if new_title == old_title and new_artist == old_artist:
            return  # nothing changed

        # Update in-memory song object
        song.title  = new_title
        song.artist = new_artist

        # Patch #TITLE: / #ARTIST: in the .txt file
        if song.folder:
            for txt_path in glob.glob(os.path.join(song.folder, "*.txt")):
                try:
                    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                    out = []
                    for line in lines:
                        ul = line.upper().lstrip()
                        if ul.startswith("#TITLE:"):
                            out.append(f"#TITLE:{new_title}\n")
                        elif ul.startswith("#ARTIST:"):
                            out.append(f"#ARTIST:{new_artist}\n")
                        else:
                            out.append(line)
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.writelines(out)
                except Exception as e:
                    print(f"[Rename] {e}")

        # Re-sort the list to reflect the new title/artist
        self._apply_filter()

    def _play(self):
        if self._cards:
            self.game.start_song(self._cards[self._sel].song)

    def _import(self):
        try:
            import subprocess
            r = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt "Select UltraStar song folder")'],
                capture_output=True, text=True, timeout=30)
            folder = r.stdout.strip()
            if folder and os.path.isdir(folder):
                dst = os.path.join(os.path.abspath(SONGS_DIR),
                                   os.path.basename(folder.rstrip("/")))
                if not os.path.exists(dst):
                    import shutil; shutil.copytree(folder, dst)
            self._reload()
        except Exception as e:
            print(f"[Import] {e}")

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt):
        self._t        += dt
        self._cursor_t += dt
        target = self._sel * (self.ROW_H + self.ROW_PAD)
        self._scroll += (target - self._scroll) * min(1.0, dt * 14)

        # Sync cover_dl status with the card's _cover_fetching flag
        if self._cards and self._sel < len(self._cards):
            card = self._cards[self._sel]
            song = card.song
            key  = song.folder or song.title
            if self._cover_dl.get(key) == "fetching" and not card._cover_fetching:
                # fetching just finished — mark done (cover may or may not have loaded)
                self._cover_dl[key] = "done" if card.song.cover_path else "error"

    # ── Draw ──────────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)
        self._draw_header(surf)
        self._draw_list(surf)
        self._draw_detail(surf)
        if self._rename_mode:
            self._draw_rename_modal(surf)

    def _draw_rename_modal(self, surf):
        """Full-screen overlay with title & artist text fields."""
        # Dim background
        overlay = pygame.Surface((T.SCREEN_W, T.SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        surf.blit(overlay, (0, 0))

        # Modal box
        mw, mh = 560, 280
        mx = (T.SCREEN_W - mw) // 2
        my = (T.SCREEN_H - mh) // 2
        modal = pygame.Surface((mw, mh), pygame.SRCALPHA)
        modal.fill((*T.BG_PANEL, 245))
        pygame.draw.rect(modal, T.GOLD_DIM, modal.get_rect(), 1, border_radius=12)
        surf.blit(modal, (mx, my))

        C.text(surf, "RENAME SONG", "display_bold", 20, T.GOLD,
               mx + mw // 2, my + 18, anchor="midtop", uppercase=True)
        C.h_divider(surf, mx + 20, mx + mw - 20, my + 48, alpha=80)

        field_h = 40
        field_w = mw - 60
        fx = mx + 30

        def draw_field(label, text, rect, active):
            self_color = T.GOLD if active else T.HIGHWAY_GRID
            C.text(surf, label, "cond_bold", 12, T.TEXT_3,
                   fx, rect.y - 18, anchor="topleft", uppercase=True)
            pygame.draw.rect(surf, T.BG_CARD, rect, border_radius=8)
            pygame.draw.rect(surf, self_color, rect, 2 if active else 1, border_radius=8)
            blink = "|" if active and int(self._cursor_t * 2) % 2 == 0 else ""
            C.text(surf, text + blink, "body_semi", 17, T.TEXT_1,
                   rect.x + 12, rect.centery, anchor="midleft")

        title_r  = pygame.Rect(fx, my + 72, field_w, field_h)
        artist_r = pygame.Rect(fx, my + 148, field_w, field_h)
        self._rename_title_r  = title_r
        self._rename_artist_r = artist_r

        draw_field("Title",  self._rename_title,  title_r,  self._rename_field == 0)
        draw_field("Artist", self._rename_artist, artist_r, self._rename_field == 1)

        C.text(surf, "TAB — switch field   ·   ENTER — confirm   ·   ESC — cancel",
               "body_reg", 12, T.TEXT_3,
               mx + mw // 2, my + 202, anchor="midtop")

        # Confirm + Cancel buttons
        bw, bh = 130, 38
        gap     = 16
        total   = bw * 2 + gap
        bx0     = mx + (mw - total) // 2
        by      = my + mh - bh - 18

        ok_r  = pygame.Rect(bx0,        by, bw, bh)
        can_r = pygame.Rect(bx0 + bw + gap, by, bw, bh)
        self._rename_ok_btn  = ok_r
        self._rename_can_btn = can_r

        C.pill(surf, ok_r, T.GOLD, alpha=220)
        C.text(surf, "SAVE", "body_bold", 16, T.TEXT_INV,
               ok_r.centerx, ok_r.centery, anchor="center")

        pygame.draw.rect(surf, T.BG_CARD, can_r, border_radius=can_r.height // 2)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, can_r, 1, border_radius=can_r.height // 2)
        C.text(surf, "CANCEL", "body_bold", 16, T.TEXT_2,
               can_r.centerx, can_r.centery, anchor="center")

    def _draw_header(self, surf):
        C.text(surf, "MUSIC LIBRARY", "display_bold", 26, T.TEXT_1,
               self.LIST_X, 14, anchor="topleft", uppercase=True)

        # ── Search bar ────────────────────────────────────────────────────
        sb_w = 360
        sb_r = pygame.Rect(self.LIST_X, 46, sb_w, 32)
        self._search_bar = sb_r
        border = T.GOLD if self._search_active else T.HIGHWAY_GRID
        pygame.draw.rect(surf, T.BG_CARD, sb_r, border_radius=6)
        pygame.draw.rect(surf, border, sb_r, 1, border_radius=6)

        if self._filter_q:
            display = self._filter_q
            col     = T.TEXT_1
        else:
            display = "Search title, artist, genre…"
            col     = T.TEXT_3

        # Cursor
        cursor = ""
        if self._search_active and int(self._cursor_t * 2) % 2 == 0:
            cursor = "|"
        C.text(surf, display + cursor, "body_reg", 15, col,
               sb_r.x + 10, sb_r.centery, anchor="midleft")

        # Clear (×) button
        cx_r = pygame.Rect(sb_r.right + 6, 46, 32, 32)
        self._clear_btn = cx_r
        if self._filter_q:
            pygame.draw.rect(surf, T.BG_CARD, cx_r, border_radius=6)
            pygame.draw.rect(surf, T.TEXT_3, cx_r, 1, border_radius=6)
            C.text(surf, "X", "body_reg", 14, T.TEXT_3,
                   cx_r.centerx, cx_r.centery, anchor="center")

        # Song count
        n_str = (f"{len(self._cards)} / {len(self._all_cards)}"
                 if self._filter_q else f"{len(self._all_cards)} songs")
        C.text(surf, n_str, "body_reg", 13, T.TEXT_3,
               sb_r.right + 48, sb_r.centery, anchor="midleft")

        # ── Sort pills ────────────────────────────────────────────────────
        sx = self.LIST_X
        sy = 84
        self._sort_rects = []
        for i, label in enumerate(SORT_MODES):
            sel = (i == self._sort_idx)
            tw, _ = C.text_size("cond_bold", 12, label)
            pr = pygame.Rect(sx, sy, tw + 20, 22)
            C.pill(surf, pr, T.GOLD if sel else T.BG_CARD,
                   alpha=220 if sel else 120)
            C.text(surf, label, "cond_bold", 12,
                   T.TEXT_INV if sel else T.TEXT_3,
                   pr.centerx, pr.centery, anchor="center", uppercase=True)
            self._sort_rects.append(pr)
            sx += pr.width + 6

        # Back button
        self._back_btn = pygame.Rect(T.SCREEN_W - 280, 46, 120, 34)
        pygame.draw.rect(surf, T.BG_CARD, self._back_btn, border_radius=8)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, self._back_btn, 1, border_radius=8)
        C.text(surf, "< BACK", "body_bold", 14, T.TEXT_2,
               self._back_btn.centerx, self._back_btn.centery, anchor="center")
        self.draw_home_btn(surf, y=46, h=34)

        # Hints
        C.text(surf, "I Import   R Refresh   TAB Sort",
               "body_reg", 13, T.TEXT_3, T.SCREEN_W - 20, 20, anchor="topright")

        C.h_divider(surf, self.LIST_X, T.SCREEN_W - 20, 112, alpha=100)

    def _draw_list(self, surf):
        lx, lw, rh = self.LIST_X, self.LIST_W, self.ROW_H
        top        = 118
        bot        = T.SCREEN_H - 10
        visible_h  = bot - top

        clip_surf     = pygame.Surface((lw, visible_h), pygame.SRCALPHA)
        self._row_rects = []

        if not self._cards:
            msg = ("No songs match your search." if self._filter_q
                   else "NO SONGS FOUND — press I to import")
            C.text(clip_surf, msg, "body_reg", 18, T.TEXT_3,
                   lw // 2, visible_h // 2, anchor="center")
            surf.blit(clip_surf, (lx, top))
            return

        mid_y = visible_h // 2
        for i, card in enumerate(self._cards):
            ry = i * (rh + self.ROW_PAD) - int(self._scroll) + mid_y - rh // 2
            if ry + rh < -20 or ry > visible_h + 20:
                self._row_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                continue

            sel   = (i == self._sel)
            row_r = pygame.Rect(0, ry, lw, rh)

            bg = pygame.Surface((lw, rh), pygame.SRCALPHA)
            if sel:
                pygame.draw.rect(bg, (*T.BG_CARD_SEL, 240), bg.get_rect(), border_radius=10)
                pygame.draw.rect(bg, (*T.GOLD, 80), bg.get_rect(), 1, border_radius=10)
            else:
                pygame.draw.rect(bg, (*T.BG_CARD, 180), bg.get_rect(), border_radius=8)
            clip_surf.blit(bg, row_r.topleft)

            if sel:
                pygame.draw.rect(clip_surf, T.GOLD, (0, ry + 8, 3, rh - 16), border_radius=2)

            title_col  = T.TEXT_1 if sel else T.TEXT_2
            artist_col = T.TEXT_2 if sel else T.TEXT_3

            # Audio indicator dot
            if card.song.mp3_path:
                pygame.draw.circle(clip_surf, T.SUCCESS, (8, ry + rh//2), 4)

            C.text(clip_surf, card.song.title[:38], "body_bold", 19, title_col,
                   18, ry + 14, anchor="topleft")
            C.text(clip_surf, card.song.artist[:38], "body_reg", 14, artist_col,
                   18, ry + 42, anchor="topleft")

            # Right side: BPM + meta
            C.text(clip_surf, f"{card.song.bpm:.0f} BPM", "cond_bold", 12, T.TEXT_3,
                   lw - 12, ry + 14, anchor="topright", uppercase=True)
            meta = "  ·  ".join(filter(None, [card.song.genre, card.song.year]))
            if meta:
                C.text(clip_surf, meta, "body_reg", 12, T.TEXT_3,
                       lw - 12, ry + 40, anchor="topright")

            real_row = pygame.Rect(lx, top + ry, lw, rh)
            self._row_rects.append(real_row)

        surf.blit(clip_surf, (lx, top))

    def _draw_detail(self, surf):
        dx  = self.DETAIL_X
        dw  = T.SCREEN_W - dx - 20
        top = 118

        if not self._cards or self._sel >= len(self._cards):
            return

        card = self._cards[self._sel]
        song = card.song
        key  = song.folder or song.title
        y    = top + 8

        # Kick off cover download in the background if missing
        card.fetch_cover_async()

        # Album art / placeholder — displayed at half the panel width
        art_size = dw // 2
        cover_size = (art_size, art_size)
        cover = card.cover(cover_size)
        art_x = dx + (dw - art_size) // 2   # centered in detail panel
        if cover:
            surf.blit(cover, (art_x, y))
            y += art_size + 10
        else:
            ph = pygame.Rect(art_x, y, art_size, art_size)
            C.panel(surf, ph, color=T.BG_CARD, border=T.HIGHWAY_GRID,
                    radius=12, alpha=200)
            C.lightning(surf, ph.centerx - 28, y + 16, 56, art_size - 32, T.GOLD, alpha=40)
            if card._cover_fetching:
                dots = "." * (int(self._t * 3) % 4)
                C.text(surf, f"Fetching{dots}", "body_reg", 16, T.TEXT_3,
                       ph.centerx, ph.centery, anchor="center")
            else:
                C.text(surf, "?", "display_black", 52, T.TEXT_3,
                       ph.centerx, ph.centery, anchor="center")
            y += art_size + 10

        # ── Action buttons row: FETCH LYRICS | DOWNLOAD COVER ────────────────
        btn_h   = 34
        gap     = 8
        btn_w   = (dw - gap) // 2

        # --- FETCH LYRICS button ---
        lyr_status  = self._lyrics_dl.get(key, "idle")
        lbx = dx
        lby = y
        lyr_btn = pygame.Rect(lbx, lby, btn_w, btn_h)
        self._lyrics_btn = lyr_btn

        if lyr_status == "fetching":
            dots = "." * (int(self._t * 3) % 4)
            lbl_lyr  = f"Fetching{dots}"
            bg_lyr   = T.BG_CARD
            brd_lyr  = T.GOLD
            txt_lyr  = T.TEXT_3
        elif lyr_status == "done":
            lbl_lyr  = "✓ Lyrics OK"
            bg_lyr   = (30, 60, 40)
            brd_lyr  = T.SUCCESS
            txt_lyr  = T.SUCCESS
        elif lyr_status == "error":
            lbl_lyr  = "✗ Lyrics Failed"
            bg_lyr   = (60, 25, 25)
            brd_lyr  = T.RED
            txt_lyr  = T.RED
        else:
            lbl_lyr  = "♪ Fetch Lyrics"
            bg_lyr   = T.BG_CARD
            brd_lyr  = T.HIGHWAY_GRID
            txt_lyr  = T.TEXT_2

        pygame.draw.rect(surf, bg_lyr,  lyr_btn, border_radius=8)
        pygame.draw.rect(surf, brd_lyr, lyr_btn, 1, border_radius=8)
        C.text(surf, lbl_lyr, "body_semi", 13, txt_lyr,
               lyr_btn.centerx, lyr_btn.centery, anchor="center")

        # --- DOWNLOAD COVER button ---
        cov_status = self._cover_dl.get(key, "idle")
        cbx = dx + btn_w + gap
        cby = y
        cov_btn = pygame.Rect(cbx, cby, btn_w, btn_h)
        self._cover_btn = cov_btn

        if cov_status == "fetching" or card._cover_fetching:
            dots = "." * (int(self._t * 3) % 4)
            lbl_cov  = f"Fetching{dots}"
            bg_cov   = T.BG_CARD
            brd_cov  = T.GOLD
            txt_cov  = T.TEXT_3
        elif cov_status == "done":
            lbl_cov  = "✓ Cover OK"
            bg_cov   = (30, 60, 40)
            brd_cov  = T.SUCCESS
            txt_cov  = T.SUCCESS
        elif cov_status == "error":
            lbl_cov  = "✗ Cover Failed"
            bg_cov   = (60, 25, 25)
            brd_cov  = T.RED
            txt_cov  = T.RED
        else:
            lbl_cov  = "⬇ Cover"
            bg_cov   = T.BG_CARD
            brd_cov  = T.HIGHWAY_GRID
            txt_cov  = T.TEXT_2

        pygame.draw.rect(surf, bg_cov,  cov_btn, border_radius=8)
        pygame.draw.rect(surf, brd_cov, cov_btn, 1, border_radius=8)
        C.text(surf, lbl_cov, "body_semi", 13, txt_cov,
               cov_btn.centerx, cov_btn.centery, anchor="center")

        y += btn_h + 6

        # ── Cover search input (shown when user clicked ⬇ Cover) ─────────────
        if self._cover_search:
            inp_h = 30
            inp_r = pygame.Rect(dx, y, dw - 70, inp_h)
            pygame.draw.rect(surf, T.BG_CARD, inp_r, border_radius=6)
            pygame.draw.rect(surf, T.GOLD, inp_r, 1, border_radius=6)
            q_display = self._cover_search_q or ""
            blink = "|" if int(self._cursor_t * 2) % 2 == 0 else ""
            C.text(surf, q_display + blink, "body_reg", 13, T.TEXT_1,
                   inp_r.x + 8, inp_r.centery, anchor="midleft")

            # GO button
            go_r = pygame.Rect(inp_r.right + 4, y, 30, inp_h)
            self._cover_confirm_btn = go_r
            pygame.draw.rect(surf, T.GOLD, go_r, border_radius=6)
            C.text(surf, "GO", "cond_bold", 11, T.TEXT_INV,
                   go_r.centerx, go_r.centery, anchor="center")

            # ✕ cancel
            cx_r = pygame.Rect(go_r.right + 4, y, 28, inp_h)
            self._cover_cancel_btn = cx_r
            pygame.draw.rect(surf, T.BG_CARD, cx_r, border_radius=6)
            pygame.draw.rect(surf, T.TEXT_3, cx_r, 1, border_radius=6)
            C.text(surf, "✕", "body_reg", 13, T.TEXT_3,
                   cx_r.centerx, cx_r.centery, anchor="center")

            y += inp_h + 6
        else:
            y += 2

        # ── RENAME button (full width, subtle) ───────────────────────────────
        ren_h = 28
        ren_r = pygame.Rect(dx, y, dw, ren_h)
        self._rename_btn = ren_r
        pygame.draw.rect(surf, T.BG_CARD, ren_r, border_radius=6)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, ren_r, 1, border_radius=6)
        C.text(surf, "✏  RENAME SONG", "cond_bold", 12, T.TEXT_3,
               ren_r.centerx, ren_r.centery, anchor="center", uppercase=True)
        y += ren_h + 12

        # ── Song title / metadata ─────────────────────────────────────────────
        C.text_shadow(surf, song.title, "display_bold", 24, T.TEXT_1,
                      dx, y, anchor="topleft",
                      shadow_color=(0,0,0), offset=(1,2))
        y += 32
        C.text(surf, song.artist, "body_semi", 16, T.TEXT_2, dx, y)
        y += 28

        C.h_divider(surf, dx, dx + dw, y + 4, alpha=80)
        y += 18

        def meta_row(label, val, val_col=T.TEXT_2):
            nonlocal y
            C.text(surf, label, "cond_bold", 12, T.TEXT_3,  dx, y, uppercase=True)
            C.text(surf, val,   "body_semi", 14, val_col,   dx + 110, y)
            y += 24

        meta_row("Language", song.language or "—")
        meta_row("Genre",    song.genre    or "—")
        meta_row("Year",     song.year     or "—")
        meta_row("BPM",      f"{song.bpm:.1f}")
        meta_row("Audio",
                 "Found"    if song.mp3_path else "Missing",
                 T.SUCCESS  if song.mp3_path else T.RED)

        # Play button
        shim = C.pulse(self._t, 1.4)
        btn  = pygame.Rect(dx, T.SCREEN_H - 64, dw, 48)
        self._play_btn = btn
        C.pill(surf, btn, T.GOLD, alpha=int(215 + 30 * shim))
        C.text(surf, ">>  SING IT!", "body_xbold", 20, T.TEXT_INV,
               btn.centerx, btn.centery, anchor="center", uppercase=True)
