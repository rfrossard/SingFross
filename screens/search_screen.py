"""Song search & download screen — USDB · Ultrastar-ES · Karaoke Mugen · YouTube."""
import pygame, threading, os
from screens.base_screen import BaseScreen
from engine.usdb_client import SearchManager, RemoteSong, ALL_SOURCES
from engine import config as CFG
from ui import theme as T
import ui.components as C

SOURCE_LABELS = {
    "usdb":    "USDB",
    "es":      "Ultrastar-ES",
    "kara":    "Karaoke Mugen",
    "youtube": "YouTube",
}
SOURCE_LABELS_SHORT = {
    "usdb":    "USDB",
    "es":      "ES",
    "kara":    "KM",
    "youtube": "YT",
}
SOURCE_ORDER  = ALL_SOURCES   # ["usdb", "es", "kara", "youtube"]
SOURCE_COLORS = {
    "usdb":    T.GOLD,
    "es":      T.SUCCESS,
    "kara":    T.INFO,
    "youtube": (220, 60, 60),
}

LIMIT_OPTIONS = [20, 30, 50, 100]


class _TextInput:
    """Minimal single-line text input widget."""
    def __init__(self, rect: pygame.Rect, placeholder=""):
        self.rect        = rect
        self.placeholder = placeholder
        self.text        = ""
        self.focused     = False
        self._cursor_t   = 0.0

    def handle_event(self, event) -> bool:
        """Returns True if Enter was pressed."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.focused = self.rect.collidepoint(event.pos)
        if not self.focused:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_ESCAPE:
                self.focused = False
            elif event.unicode and event.unicode.isprintable():
                self.text += event.unicode
        return False

    def update(self, dt):
        self._cursor_t += dt

    def draw(self, surf):
        border = T.GOLD if self.focused else T.HIGHWAY_GRID
        pygame.draw.rect(surf, T.BG_CARD, self.rect, border_radius=8)
        pygame.draw.rect(surf, border,    self.rect, 1, border_radius=8)
        txt = self.text or self.placeholder
        col = T.TEXT_1 if self.text else T.TEXT_3
        C.text(surf, txt, "body_reg", 18, col,
               self.rect.x + 14, self.rect.centery, anchor="midleft")
        if self.focused and int(self._cursor_t * 2) % 2 == 0:
            tw = C.text_size("body_reg", 18, self.text)[0]
            cx = self.rect.x + 14 + tw + 2
            pygame.draw.line(surf, T.TEXT_1,
                             (cx, self.rect.y + 8),
                             (cx, self.rect.bottom - 8), 2)


class SearchScreen(BaseScreen):

    ROW_H   = 72
    LIST_X  = 20
    LIST_W  = T.SCREEN_W - 40

    def __init__(self, game):
        super().__init__(game)
        cfg     = CFG.get()
        user, pw = cfg.usdb_credentials
        self._mgr   = SearchManager(
            songs_dir=os.path.abspath(cfg.songs_dir),
            usdb_user=user, usdb_pass=pw,
        )
        self._t          = 0.0
        self._sel        = -1
        self._scroll     = 0.0
        self._limit      = 20      # active result count limit
        self._row_rects  : list[pygame.Rect] = []
        self._dl_rects   : list[pygame.Rect] = []
        self._sources    = set(SOURCE_ORDER)
        self._last_query = ""
        self._input      = _TextInput(
            pygame.Rect(self.LIST_X, 80, T.SCREEN_W - 200, 44),
            placeholder="Search artist or title…",
        )
        self._input.focused = True

        # Rects set during draw — used for click detection
        self._src_rects   : dict             = {}
        self._limit_rects : dict[int, pygame.Rect] = {}
        self._more_btn    : pygame.Rect | None = None
        self._back_btn    : pygame.Rect | None = None
        self._search_btn  : pygame.Rect | None = None

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.pop_screen()
            return
        if self._input.handle_event(event):
            self._do_search()
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 4:
                self._scroll = max(0, self._scroll - self.ROW_H)
            elif event.button == 5:
                self._scroll += self.ROW_H
            elif event.button == 1:
                if self.handle_home_click(event):
                    return
                if self._back_btn and self._back_btn.collidepoint(event.pos):
                    self.game.pop_screen()
                    return
                self._handle_click(event.pos)

    def _handle_click(self, pos):
        # Source filter tabs
        for src, r in self._src_rects.items():
            if r.collidepoint(pos):
                if src in self._sources:
                    if len(self._sources) > 1:
                        self._sources.discard(src)
                else:
                    self._sources.add(src)
                self._do_search()
                return

        # Limit selector
        for lim, r in self._limit_rects.items():
            if r.collidepoint(pos):
                if lim != self._limit:
                    self._limit = lim
                    self._do_search()
                return

        # Search button
        if self._search_btn and self._search_btn.collidepoint(pos):
            self._do_search()
            return

        # Load-more button
        if self._more_btn and self._more_btn.collidepoint(pos):
            self._mgr.load_more()
            return

        # Download button (checked before row selection to avoid conflict)
        for i, r in enumerate(self._dl_rects):
            if r.collidepoint(pos):
                results = self._mgr.results
                if i < len(results):
                    song = results[i]
                    if self._mgr.dl_status(song.song_id) in ("", "error"):
                        if self._mgr.dl_status(song.song_id) == "error":
                            self._mgr._dl_status.pop(song.song_id, None)
                        self._mgr.download(song, on_done=lambda s: None)
                return

        # Row selection
        for i, r in enumerate(self._row_rects):
            if r.collidepoint(pos):
                self._sel = i
                return

    def _do_search(self):
        q = self._input.text.strip()
        if not q:
            return
        self._sel        = -1
        self._scroll     = 0.0
        self._last_query = q
        self._mgr.search(q, list(self._sources), limit=self._limit)

    # ── Update ────────────────────────────────────────────────────────────

    def update(self, dt):
        self._t += dt
        self._input.update(dt)

    # ── Draw ──────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)
        self._draw_header(surf)
        self._draw_input(surf)
        self._draw_list(surf)
        self._draw_status(surf)

    def _draw_header(self, surf):
        C.text(surf, "FIND SONGS", "display_bold", 28, T.TEXT_1,
               self.LIST_X, 18, anchor="topleft", uppercase=True)
        C.text(surf, "USDB  ·  Ultrastar-ES  ·  Karaoke Mugen  ·  YouTube",
               "body_reg", 14, T.TEXT_3, self.LIST_X, 54, anchor="topleft")
        self._back_btn = pygame.Rect(T.SCREEN_W - 280, 18, 110, 34)
        pygame.draw.rect(surf, T.BG_CARD, self._back_btn, border_radius=8)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, self._back_btn, 1, border_radius=8)
        C.text(surf, "< BACK", "body_bold", 14, T.TEXT_2,
               self._back_btn.centerx, self._back_btn.centery, anchor="center")
        self.draw_home_btn(surf, y=18, h=34)

    def _draw_input(self, surf):
        self._input.draw(surf)

        # Search button
        self._search_btn = pygame.Rect(self._input.rect.right + 12, 80, 140, 44)
        busy = self._mgr.busy
        C.pill(surf, self._search_btn, T.DIMMED if busy else T.GOLD, alpha=220)
        slbl = ("Searching" + "." * (int(self._t * 3) % 4)) if busy else "SEARCH"
        C.text(surf, slbl, "body_xbold", 16, T.TEXT_INV,
               self._search_btn.centerx, self._search_btn.centery,
               anchor="center", uppercase=not busy)

        # ── Row 2: source filter pills (left) + limit picker (right) ────────
        row_y = 136

        # Source filter pills
        sx = self.LIST_X
        self._src_rects = {}
        for src in SOURCE_ORDER:
            label  = SOURCE_LABELS[src].upper()
            active = src in self._sources
            col    = SOURCE_COLORS[src]
            tw, _  = C.text_size("body_bold", 16, label)
            pr     = pygame.Rect(sx, row_y, tw + 28, 30)
            C.pill(surf, pr, col, alpha=210 if active else 60)
            if not active:
                pygame.draw.rect(surf, col, pr, 1, border_radius=pr.height // 2)
            C.text(surf, label, "body_bold", 16,
                   T.TEXT_INV if active else col,
                   pr.centerx, pr.centery, anchor="center")
            self._src_rects[src] = pr
            sx += pr.width + 8

        # Limit picker — right-aligned on the same row
        C.text(surf, "RESULTS:", "cond_bold", 13, T.TEXT_3,
               T.SCREEN_W - 295, row_y + 15, anchor="midleft", uppercase=True)
        lx = T.SCREEN_W - 220
        self._limit_rects = {}
        for lim in LIMIT_OPTIONS:
            lbl    = str(lim)
            active = (lim == self._limit)
            tw, _  = C.text_size("body_bold", 14, lbl)
            lr     = pygame.Rect(lx, row_y + 2, tw + 20, 26)
            C.pill(surf, lr, T.GOLD if active else T.BG_CARD,
                   alpha=220 if active else 180)
            if not active:
                pygame.draw.rect(surf, T.HIGHWAY_GRID, lr, 1,
                                 border_radius=lr.height // 2)
            C.text(surf, lbl, "body_bold", 14,
                   T.TEXT_INV if active else T.TEXT_2,
                   lr.centerx, lr.centery, anchor="center")
            self._limit_rects[lim] = lr
            lx += lr.width + 4

        C.h_divider(surf, self.LIST_X, T.SCREEN_W - self.LIST_X, 174, alpha=80)

    def _draw_list(self, surf):
        results = self._mgr.results
        top     = 180
        bot     = T.SCREEN_H - 36
        clip_h  = bot - top

        # Clip surface — tall enough for all rows + load-more button
        row_stride  = self.ROW_H + 4
        total_rows_h = len(results) * row_stride
        MORE_BTN_H  = 40
        clip_total   = max(clip_h, total_rows_h + MORE_BTN_H + 8)
        clip_s       = pygame.Surface((self.LIST_W, clip_total), pygame.SRCALPHA)

        self._row_rects = []
        self._dl_rects  = []
        self._more_btn  = None

        # ── Loading placeholder ───────────────────────────────────────────
        if self._mgr.busy and not results:
            dots = "." * (int(self._t * 3) % 4)
            C.text(surf, f"Searching{dots}", "body_bold", 22, T.GOLD,
                   T.SCREEN_W // 2, top + clip_h // 2 - 24, anchor="center")
            C.text(surf, self._last_query, "body_reg", 16, T.TEXT_3,
                   T.SCREEN_W // 2, top + clip_h // 2 + 10, anchor="center")
            surf.blit(clip_s, (self.LIST_X, top),
                      area=pygame.Rect(0, 0, self.LIST_W, clip_h))
            return

        if not results:
            if not self._mgr.busy:
                if self._last_query:
                    C.text(surf, f'No results for "{self._last_query}"',
                           "body_reg", 18, T.TEXT_3,
                           T.SCREEN_W // 2, top + clip_h // 2 - 16, anchor="center")
                    C.text(surf, "Try a different query or enable more sources below",
                           "body_reg", 14, T.TEXT_3,
                           T.SCREEN_W // 2, top + clip_h // 2 + 14, anchor="center")
                else:
                    C.text(surf, "Search for an artist or song title above",
                           "body_reg", 18, T.TEXT_3,
                           T.SCREEN_W // 2, top + clip_h // 2 - 16, anchor="center")
                    C.text(surf, "USDB requires credentials (Settings > Audio)",
                           "body_reg", 14, T.TEXT_3,
                           T.SCREEN_W // 2, top + clip_h // 2 + 14, anchor="center")
            return

        scroll_i = int(self._scroll)

        for i, song in enumerate(results):
            ry = i * row_stride

            # Off-screen?  Push dummy rects and skip drawing.
            visible_y = ry - scroll_i
            if visible_y + self.ROW_H < 0 or visible_y > clip_h:
                self._row_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                self._dl_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                continue

            sel = (i == self._sel)
            rr  = pygame.Rect(0, ry, self.LIST_W, self.ROW_H)

            # Row background
            bg  = pygame.Surface((self.LIST_W, self.ROW_H), pygame.SRCALPHA)
            bc  = T.BG_CARD_SEL if sel else T.BG_CARD
            pygame.draw.rect(bg, (*bc, 230), bg.get_rect(), border_radius=8)
            if sel:
                pygame.draw.rect(bg, (*T.GOLD, 60), bg.get_rect(), 1, border_radius=8)
            clip_s.blit(bg, rr.topleft)

            # Source badge
            src_col  = SOURCE_COLORS.get(song.source, T.DIMMED)
            src_lbl  = SOURCE_LABELS_SHORT.get(song.source, song.source.upper())
            bw, bh   = C.text_size("body_bold", 14, src_lbl)
            badge_w  = bw + 18
            br = pygame.Rect(10, ry + (self.ROW_H - 22) // 2, badge_w, 22)
            C.pill(clip_s, br, src_col, alpha=210)
            C.text(clip_s, src_lbl, "body_bold", 14, T.TEXT_INV,
                   br.centerx, br.centery, anchor="center")

            # Title / artist
            tx = br.right + 12
            C.text(clip_s, song.title[:52], "body_bold", 18, T.TEXT_1,
                   tx, ry + 9, anchor="topleft")
            meta = song.artist
            if song.language:
                meta += f"  ·  {song.language}"
            C.text(clip_s, meta, "body_reg", 14, T.TEXT_3,
                   tx, ry + 36, anchor="topleft")

            # Download button — y is relative to clip_s row, NOT to screen
            dstat    = self._mgr.dl_status(song.song_id)
            dprog    = self._mgr.dl_progress(song.song_id)

            BTN_W, BTN_H = 120, 34
            # dl_r.y is local to the row (within clip_s)
            dl_local_y = ry + (self.ROW_H - BTN_H) // 2
            dl_r = pygame.Rect(self.LIST_W - BTN_W - 10, dl_local_y, BTN_W, BTN_H)

            if dstat == "done":
                C.pill(clip_s, dl_r, T.SUCCESS, alpha=210)
                C.text(clip_s, "SAVED", "body_bold", 15, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "error":
                C.pill(clip_s, dl_r, T.RED, alpha=210)
                C.text(clip_s, "RETRY", "body_bold", 15, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "need_login":
                C.pill(clip_s, dl_r, T.WARNING, alpha=210)
                C.text(clip_s, "LOGIN REQ.", "body_bold", 13, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "browser":
                C.pill(clip_s, dl_r, T.INFO, alpha=210)
                C.text(clip_s, "OPENED", "body_bold", 15, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "downloading":
                pygame.draw.rect(clip_s, T.BG_CARD, dl_r,
                                 border_radius=dl_r.height // 2)
                pygame.draw.rect(clip_s, T.GOLD, dl_r, 1,
                                 border_radius=dl_r.height // 2)
                if dprog > 0:
                    fill_w = max(dl_r.height, int(dl_r.width * dprog))
                    fill_r = pygame.Rect(dl_r.x, dl_r.y, fill_w, dl_r.height)
                    pygame.draw.rect(clip_s, (*T.GOLD, 60), fill_r,
                                     border_radius=dl_r.height // 2)
                    pct_lbl = f"{int(dprog * 100)}%"
                else:
                    pct_lbl = "." * (int(self._t * 3) % 4) or "..."
                C.text(clip_s, pct_lbl, "body_bold", 15, T.GOLD,
                       dl_r.centerx, dl_r.centery, anchor="center")
            else:
                C.pill(clip_s, dl_r, T.GOLD, alpha=220)
                C.text(clip_s, "DOWNLOAD", "body_bold", 15, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")

            # Year + audio tag (left of download button)
            meta_x = dl_r.x - 10
            if song.year:
                C.text(clip_s, song.year, "body_bold", 15, T.TEXT_2,
                       meta_x, ry + 9, anchor="topright")
            if song.has_audio:
                C.text(clip_s, "audio", "body_reg", 13, T.SUCCESS,
                       meta_x, ry + 36, anchor="topright")

            # Screen-space rects.
            # clip_s is drawn with area starting at scroll_i and blitted at (LIST_X, top),
            # so clip_s row ry appears on screen at top + ry - scroll_i.
            real_row = pygame.Rect(self.LIST_X,          top + ry         - scroll_i, self.LIST_W, self.ROW_H)
            real_dl  = pygame.Rect(self.LIST_X + dl_r.x, top + dl_local_y - scroll_i, BTN_W,       BTN_H)

            self._row_rects.append(real_row)
            self._dl_rects.append(real_dl)

        # ── Load-more button ──────────────────────────────────────────────
        if results and not self._mgr.busy:
            more_y   = total_rows_h + 6
            more_vis = more_y - scroll_i
            if 0 <= more_vis <= clip_h:
                mr = pygame.Rect(self.LIST_W // 2 - 110, more_y, 220, MORE_BTN_H)
                pygame.draw.rect(clip_s, T.BG_CARD, mr, border_radius=8)
                pygame.draw.rect(clip_s, T.HIGHWAY_GRID, mr, 1, border_radius=8)
                C.text(clip_s, "+ LOAD 20 MORE", "body_bold", 15, T.TEXT_2,
                       mr.centerx, mr.centery, anchor="center", uppercase=True)
                # screen-space rect (scroll-adjusted)
                self._more_btn = pygame.Rect(
                    self.LIST_X + mr.x, top + more_y - scroll_i, mr.width, mr.height)
        elif results and self._mgr.busy:
            more_y   = total_rows_h + 6
            more_vis = more_y - scroll_i
            if 0 <= more_vis <= clip_h:
                dots = "." * (int(self._t * 3) % 4)
                C.text(clip_s, f"Loading{dots}", "body_reg", 14, T.GOLD,
                       self.LIST_W // 2, more_y + MORE_BTN_H // 2, anchor="center")

        surf.blit(clip_s, (self.LIST_X, top),
                  area=pygame.Rect(0, scroll_i, self.LIST_W, clip_h))

    def _draw_status(self, surf):
        msg = self._mgr.status
        if msg:
            col = T.GOLD if self._mgr.busy else T.TEXT_3
            C.text(surf, msg, "body_reg", 13, col,
                   T.SCREEN_W // 2, T.SCREEN_H - 20, anchor="midbottom")
