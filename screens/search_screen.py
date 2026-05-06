"""Song search & download screen — Fross Garage Band design system.
Two-panel layout: scrollable song list (left) + song detail (right).
Sources: USDB · Ultrastar-ES · Karaoke Mugen · YouTube.
"""
import pygame, threading, os
from screens.base_screen import BaseScreen
from engine.usdb_client import SearchManager, RemoteSong, ALL_SOURCES
from engine import config as CFG
from ui import theme as T
import ui.components as C

# ── Source metadata ────────────────────────────────────────────────────────────
SOURCE_LABELS = {
    "usdb":    "USDB",
    "es":      "Ultrastar-ES",
    "kara":    "Karaoke Mugen",
    "youtube": "YouTube",
}
SOURCE_SHORT = {
    "usdb":    "USDB",
    "es":      "ES",
    "kara":    "KM",
    "youtube": "YT",
}
SOURCE_ORDER = ALL_SOURCES  # ["usdb", "es", "kara", "youtube"]
SOURCE_COLORS = {
    "usdb":    (255, 196,  28),   # gold
    "es":      (  0, 220,  60),   # gem-green
    "kara":    ( 20, 120, 255),   # gem-blue
    "youtube": (220,  40,  40),   # gem-red
}

# ── Design-system local colors (Fross Garage Band) ────────────────────────────
_NAVY       = ( 13,  27,  58)   # dark blue selection bg
_NAVY_LIGHT = ( 22,  46,  90)   # lighter blue panel
_BORDER     = ( 40,  40,  60)   # subtle panel border
_ROW_BG     = ( 18,  18,  26)   # normal row bg
_ROW_SEL    = ( 13,  27,  58)   # selected row bg

# ── Layout constants ───────────────────────────────────────────────────────────
HEADER_H   = 52
SEARCH_Y   = HEADER_H + 8
SEARCH_H   = 40
FILTER_Y   = SEARCH_Y + SEARCH_H + 6
FILTER_H   = 32
DIVIDER_Y  = FILTER_Y + FILTER_H + 6
LIST_TOP   = DIVIDER_Y + 4
LIST_BOT   = T.SCREEN_H - 26
STATUS_Y   = T.SCREEN_H - 13       # midbottom

SPLIT_X    = 796                    # x of vertical divider
LIST_X     = 0                      # left edge of list within its surface
LIST_W     = SPLIT_X - 10          # 786px
DETAIL_X   = SPLIT_X + 10          # x of detail panel on screen
DETAIL_W   = T.SCREEN_W - DETAIL_X - 8   # ≈464px

ROW_H      = 68
ROW_GAP    = 3
ROW_STRIDE = ROW_H + ROW_GAP

MARGIN     = 16                     # horizontal margin inside list / detail


class _TextInput:
    """Single-line text field."""
    def __init__(self, rect: pygame.Rect, placeholder: str = ""):
        self.rect        = rect
        self.placeholder = placeholder
        self.text        = ""
        self.focused     = False
        self._cursor_t   = 0.0

    def handle_event(self, event) -> bool:
        """Returns True when Enter is pressed."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
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

    def update(self, dt: float):
        self._cursor_t += dt

    def draw(self, surf: pygame.Surface):
        focused = self.focused
        border  = T.GOLD if focused else _BORDER
        pygame.draw.rect(surf, _ROW_BG,  self.rect, border_radius=8)
        pygame.draw.rect(surf, border,   self.rect, 1, border_radius=8)
        txt = self.text or self.placeholder
        col = T.TEXT_1 if self.text else T.TEXT_3
        C.text(surf, txt, "body_reg", 17, col,
               self.rect.x + 12, self.rect.centery, anchor="midleft")
        if focused and int(self._cursor_t * 2) % 2 == 0 and self.text:
            tw = C.text_size("body_reg", 17, self.text)[0]
            cx = self.rect.x + 12 + tw + 2
            pygame.draw.line(surf, T.TEXT_1,
                             (cx, self.rect.y + 9), (cx, self.rect.bottom - 9), 2)


class SearchScreen(BaseScreen):

    def __init__(self, game):
        super().__init__(game)
        cfg       = CFG.get()
        user, pw  = cfg.usdb_credentials
        self._mgr = SearchManager(
            songs_dir=os.path.abspath(cfg.songs_dir),
            usdb_user=user, usdb_pass=pw,
        )
        self._t           = 0.0
        self._sel         = -1
        self._scroll      = 0.0
        self._last_query  = ""
        self._sources     = set(SOURCE_ORDER)

        # Input widget (fills left panel width)
        search_rect = pygame.Rect(MARGIN, SEARCH_Y, LIST_W - 110, SEARCH_H)
        self._input = _TextInput(search_rect, placeholder="Search artist or title…")
        self._input.focused = True

        # Click-target rects (set during draw)
        self._row_rects   : list[pygame.Rect]     = []
        self._dl_rects    : list[pygame.Rect]     = []
        self._src_rects   : dict[str, pygame.Rect] = {}
        self._all_btn     : pygame.Rect | None    = None
        self._search_btn  : pygame.Rect | None    = None
        self._back_btn    : pygame.Rect | None    = None
        self._more_btn    : pygame.Rect | None    = None
        self._detail_dl   : pygame.Rect | None    = None   # download in detail panel

        # Auto-browse Karaoke Mugen on open (no auth required)
        self._do_search(query="", sources=["kara"])

    # ── Input handling ─────────────────────────────────────────────────────────

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.game.pop_screen()
                return
            if event.key in (pygame.K_UP, pygame.K_DOWN):
                delta = -1 if event.key == pygame.K_UP else 1
                n = len(self._mgr.results)
                if n:
                    self._sel = max(0, min(n - 1, self._sel + delta))
                    self._scroll_to_sel()
                return

        if self._input.handle_event(event):
            self._do_search()
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            btn = event.button
            pos = event.pos
            if btn == 4:    # scroll up
                self._scroll = max(0.0, self._scroll - ROW_STRIDE)
                return
            if btn == 5:    # scroll down
                self._scroll += ROW_STRIDE
                return
            if btn != 1:
                return
            if self.handle_home_click(event):
                return
            if self._back_btn and self._back_btn.collidepoint(pos):
                self.game.pop_screen()
                return
            if self._search_btn and self._search_btn.collidepoint(pos):
                self._do_search()
                return
            if self._more_btn and self._more_btn.collidepoint(pos):
                self._mgr.load_more()
                return
            # "ALL" source toggle
            if self._all_btn and self._all_btn.collidepoint(pos):
                if len(self._sources) == len(SOURCE_ORDER):
                    # If all active, keep kara only as default
                    self._sources = {"kara"}
                else:
                    self._sources = set(SOURCE_ORDER)
                self._do_search()
                return
            # Source filter pills
            for src, r in self._src_rects.items():
                if r.collidepoint(pos):
                    if src in self._sources:
                        if len(self._sources) > 1:
                            self._sources.discard(src)
                    else:
                        self._sources.add(src)
                    self._do_search()
                    return
            # Download button in detail panel
            if self._detail_dl and self._detail_dl.collidepoint(pos):
                self._try_download_sel()
                return
            # Download buttons in list rows
            for i, r in enumerate(self._dl_rects):
                if r.collidepoint(pos):
                    self._try_download(i)
                    return
            # Row selection
            for i, r in enumerate(self._row_rects):
                if r.collidepoint(pos):
                    self._sel = i
                    return

    def _do_search(self, query: str = None, sources: list = None):
        q = (query if query is not None else self._input.text).strip()
        self._last_query = q
        self._sel        = -1
        self._scroll     = 0.0
        srcs = sources if sources is not None else list(self._sources)
        self._mgr.search(q, srcs)

    def _try_download_sel(self):
        results = self._mgr.results
        if 0 <= self._sel < len(results):
            self._try_download(self._sel)

    def _try_download(self, i: int):
        results = self._mgr.results
        if i >= len(results):
            return
        song = results[i]
        sid  = song.song_id
        st   = self._mgr.dl_status(sid)
        if st in ("", "error"):
            if st == "error":
                self._mgr._dl_status.pop(sid, None)
            self._mgr.download(song, on_done=lambda s: None)

    def _scroll_to_sel(self):
        """Ensure selected row is visible."""
        clip_h  = LIST_BOT - LIST_TOP
        row_top = self._sel * ROW_STRIDE
        row_bot = row_top + ROW_H
        if row_top < self._scroll:
            self._scroll = float(row_top)
        elif row_bot > self._scroll + clip_h:
            self._scroll = float(row_bot - clip_h)

    # ── Update ─────────────────────────────────────────────────────────────────

    def update(self, dt: float):
        self._t += dt
        self._input.update(dt)

    # ── Draw ───────────────────────────────────────────────────────────────────

    def draw(self, surf: pygame.Surface):
        surf.fill(T.BG)
        self._draw_header(surf)
        self._draw_search_bar(surf)
        self._draw_filter_row(surf)
        self._draw_divider(surf)
        self._draw_list(surf)
        self._draw_detail(surf)
        self._draw_status(surf)
        self.draw_home_btn(surf)

    # ── Header ─────────────────────────────────────────────────────────────────

    def _draw_header(self, surf: pygame.Surface):
        # Dark navy header bar
        hdr = pygame.Surface((T.SCREEN_W, HEADER_H), pygame.SRCALPHA)
        pygame.draw.rect(hdr, (*_NAVY, 240), hdr.get_rect())
        # Subtle gold accent line at bottom
        pygame.draw.line(hdr, (*T.GOLD_DIM, 80), (0, HEADER_H - 1), (T.SCREEN_W, HEADER_H - 1))
        surf.blit(hdr, (0, 0))

        C.text(surf, "DOWNLOAD MUSIC", "display_bold", 22, T.TEXT_1,
               MARGIN, HEADER_H // 2, anchor="midleft", uppercase=True)
        C.text(surf, "USDB  ·  Ultrastar-ES  ·  Karaoke Mugen  ·  YouTube",
               "body_reg", 13, T.TEXT_3,
               MARGIN + 210, HEADER_H // 2, anchor="midleft")

        # Back button (right side, before home)
        self._back_btn = pygame.Rect(T.SCREEN_W - 220, (HEADER_H - 32) // 2, 104, 32)
        pygame.draw.rect(surf, _NAVY_LIGHT, self._back_btn, border_radius=6)
        pygame.draw.rect(surf, _BORDER, self._back_btn, 1, border_radius=6)
        C.text(surf, "< VOLTAR", "body_bold", 14, T.TEXT_2,
               self._back_btn.centerx, self._back_btn.centery, anchor="center")

    # ── Search bar ─────────────────────────────────────────────────────────────

    def _draw_search_bar(self, surf: pygame.Surface):
        self._input.draw(surf)

        busy = self._mgr.busy
        bx   = self._input.rect.right + 8
        self._search_btn = pygame.Rect(bx, SEARCH_Y, LIST_W - bx + LIST_X, SEARCH_H)
        bg   = T.DIMMED if busy else _NAVY
        C.pill(surf, self._search_btn, bg, alpha=240)
        pygame.draw.rect(surf, T.GOLD if not busy else _BORDER,
                         self._search_btn, 1,
                         border_radius=self._search_btn.height // 2)
        label = ("Buscando" + "." * (int(self._t * 3) % 4)) if busy else "BUSCAR"
        C.text(surf, label, "body_bold", 15, T.GOLD if not busy else T.TEXT_3,
               self._search_btn.centerx, self._search_btn.centery, anchor="center")

    # ── Source filter pills ────────────────────────────────────────────────────

    def _draw_filter_row(self, surf: pygame.Surface):
        all_active = len(self._sources) == len(SOURCE_ORDER)

        sx = MARGIN
        # "TUDO" (all) pill
        tw, _ = C.text_size("body_bold", 14, "TUDO")
        self._all_btn = pygame.Rect(sx, FILTER_Y + 1, tw + 26, FILTER_H - 2)
        bg  = T.GOLD    if all_active else _ROW_BG
        tc  = T.TEXT_INV if all_active else T.TEXT_3
        C.pill(surf, self._all_btn, bg, alpha=220 if all_active else 180)
        if not all_active:
            pygame.draw.rect(surf, _BORDER, self._all_btn, 1,
                             border_radius=self._all_btn.height // 2)
        C.text(surf, "TUDO", "body_bold", 14, tc,
               self._all_btn.centerx, self._all_btn.centery, anchor="center")
        sx += self._all_btn.width + 6

        self._src_rects = {}
        for src in SOURCE_ORDER:
            active = src in self._sources and not all_active
            col    = SOURCE_COLORS[src]
            label  = SOURCE_SHORT[src]
            tw, _  = C.text_size("body_bold", 14, label)
            pr     = pygame.Rect(sx, FILTER_Y + 1, tw + 26, FILTER_H - 2)
            if active:
                C.pill(surf, pr, col, alpha=210)
            else:
                pygame.draw.rect(surf, _ROW_BG, pr, border_radius=pr.height // 2)
                pygame.draw.rect(surf, col if src in self._sources else _BORDER,
                                 pr, 1, border_radius=pr.height // 2)
            tc = T.TEXT_INV if active else (col if src in self._sources else T.TEXT_3)
            C.text(surf, label, "body_bold", 14, tc,
                   pr.centerx, pr.centery, anchor="center")
            self._src_rects[src] = pr
            sx += pr.width + 5

        # Result count (right-aligned on same row)
        n = len(self._mgr.results)
        if n > 0:
            count_lbl = f"{n} música{'s' if n != 1 else ''} encontrada{'s' if n != 1 else ''}"
            C.text(surf, count_lbl, "body_reg", 13, T.TEXT_3,
                   LIST_W - MARGIN, FILTER_Y + FILTER_H // 2, anchor="midright")

    # ── Thin horizontal divider ────────────────────────────────────────────────

    def _draw_divider(self, surf: pygame.Surface):
        C.h_divider(surf, 0, T.SCREEN_W, DIVIDER_Y, color=_BORDER, alpha=160)

    # ── Song list (left panel) ─────────────────────────────────────────────────

    def _draw_list(self, surf: pygame.Surface):
        results = self._mgr.results
        clip_h  = LIST_BOT - LIST_TOP

        self._row_rects = []
        self._dl_rects  = []
        self._more_btn  = None

        # ── Empty / loading placeholder ────────────────────────────────────────
        if not results:
            mid_y = LIST_TOP + clip_h // 2
            if self._mgr.busy:
                dots = "." * (int(self._t * 3) % 4)
                C.text(surf, f"Buscando{dots}", "body_bold", 20, T.GOLD,
                       LIST_W // 2, mid_y - 20, anchor="center")
                if self._last_query:
                    C.text(surf, self._last_query, "body_reg", 14, T.TEXT_3,
                           LIST_W // 2, mid_y + 8, anchor="center")
            else:
                if self._last_query:
                    C.text(surf, f'Nenhum resultado para "{self._last_query}"',
                           "body_reg", 16, T.TEXT_3,
                           LIST_W // 2, mid_y - 16, anchor="center")
                    C.text(surf, "Tente outra busca ou ative mais fontes",
                           "body_reg", 13, T.TEXT_3,
                           LIST_W // 2, mid_y + 12, anchor="center")
                else:
                    C.text(surf, "Busque uma música acima",
                           "body_reg", 16, T.TEXT_3,
                           LIST_W // 2, mid_y - 16, anchor="center")
                    C.text(surf, "USDB, Karaoke Mugen, Ultrastar-ES e YouTube",
                           "body_reg", 13, T.TEXT_3,
                           LIST_W // 2, mid_y + 12, anchor="center")
            return

        scroll_i = int(self._scroll)

        # Total height needed for all rows + load-more
        total_h  = len(results) * ROW_STRIDE
        MORE_H   = 38
        surf_h   = max(clip_h, total_h + MORE_H + 8)

        # Off-screen clip surface — only left panel width
        clip_s = pygame.Surface((LIST_W, surf_h), pygame.SRCALPHA)

        for i, song in enumerate(results):
            ry        = i * ROW_STRIDE
            vis_y     = ry - scroll_i
            # Skip rows outside the visible clip
            if vis_y + ROW_H < 0 or vis_y > clip_h:
                self._row_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                self._dl_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                continue

            sel = (i == self._sel)
            # Row background
            rr  = pygame.Rect(0, ry, LIST_W, ROW_H)
            bg  = pygame.Surface((LIST_W, ROW_H), pygame.SRCALPHA)
            bc  = _ROW_SEL if sel else _ROW_BG
            pygame.draw.rect(bg, (*bc, 235), bg.get_rect(), border_radius=8)
            if sel:
                pygame.draw.rect(bg, (*T.GOLD, 70), bg.get_rect(), 1, border_radius=8)
                # Left accent bar
                pygame.draw.rect(bg, (*T.GOLD, 200),
                                 pygame.Rect(0, 8, 3, ROW_H - 16), border_radius=2)
            clip_s.blit(bg, rr.topleft)

            # Source color dot
            src_col = SOURCE_COLORS.get(song.source, T.DIMMED)
            pygame.draw.circle(clip_s, src_col, (MARGIN, ry + ROW_H // 2), 4)

            tx = MARGIN + 14
            # Title
            title = song.title[:46] if len(song.title) > 46 else song.title
            title_col = T.TEXT_1 if sel else T.TEXT_1
            C.text(clip_s, title, "body_bold", 17, title_col,
                   tx, ry + 8, anchor="topleft")
            # Artist + source
            src_lbl = SOURCE_LABELS.get(song.source, song.source.upper())
            meta    = f"{song.artist}  ·  {src_lbl}"
            if song.language:
                meta += f"  ·  {song.language}"
            C.text(clip_s, meta, "body_reg", 13, T.TEXT_3,
                   tx, ry + 32, anchor="topleft")

            # Download button (right side of row)
            dstat  = self._mgr.dl_status(song.song_id)
            dprog  = self._mgr.dl_progress(song.song_id)
            BTN_W, BTN_H2 = 102, 30
            dl_local_y    = ry + (ROW_H - BTN_H2) // 2
            dl_r = pygame.Rect(LIST_W - BTN_W - MARGIN, dl_local_y, BTN_W, BTN_H2)

            if dstat == "done":
                C.pill(clip_s, dl_r, T.SUCCESS, alpha=200)
                C.text(clip_s, "SALVO", "body_bold", 13, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "error":
                C.pill(clip_s, dl_r, T.RED, alpha=200)
                C.text(clip_s, "RETRY", "body_bold", 13, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "need_login":
                C.pill(clip_s, dl_r, T.WARNING, alpha=200)
                C.text(clip_s, "LOGIN", "body_bold", 13, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "browser":
                C.pill(clip_s, dl_r, T.INFO, alpha=200)
                C.text(clip_s, "ABERTO", "body_bold", 13, T.TEXT_INV,
                       dl_r.centerx, dl_r.centery, anchor="center")
            elif dstat == "downloading":
                pygame.draw.rect(clip_s, _NAVY, dl_r, border_radius=dl_r.height // 2)
                pygame.draw.rect(clip_s, src_col, dl_r, 1, border_radius=dl_r.height // 2)
                if dprog > 0:
                    fw = max(dl_r.height, int(dl_r.width * dprog))
                    fill = pygame.Rect(dl_r.x, dl_r.y, fw, dl_r.height)
                    pygame.draw.rect(clip_s, (*src_col, 60), fill,
                                     border_radius=dl_r.height // 2)
                    lbl = f"{int(dprog * 100)}%"
                else:
                    lbl = "." * (int(self._t * 3) % 4) or "..."
                C.text(clip_s, lbl, "body_bold", 13, src_col,
                       dl_r.centerx, dl_r.centery, anchor="center")
            else:
                # Idle — ghost button (shows only on selected row)
                if sel:
                    C.pill(clip_s, dl_r, T.GOLD, alpha=210)
                    C.text(clip_s, "BAIXAR", "body_bold", 13, T.TEXT_INV,
                           dl_r.centerx, dl_r.centery, anchor="center")
                else:
                    pygame.draw.rect(clip_s, _BORDER, dl_r, 1,
                                     border_radius=dl_r.height // 2)
                    C.text(clip_s, "BAIXAR", "body_bold", 13, T.TEXT_3,
                           dl_r.centerx, dl_r.centery, anchor="center")

            # Year (left of download button)
            if song.year:
                C.text(clip_s, song.year, "body_reg", 13, T.TEXT_3,
                       dl_r.x - 8, ry + ROW_H // 2, anchor="midright")

            # Screen-space rects for click detection
            real_row = pygame.Rect(0, LIST_TOP + ry - scroll_i, LIST_W, ROW_H)
            real_dl  = pygame.Rect(dl_r.x, LIST_TOP + dl_local_y - scroll_i, BTN_W, BTN_H2)
            self._row_rects.append(real_row)
            self._dl_rects.append(real_dl)

        # ── Load-more button ───────────────────────────────────────────────────
        if results and not self._mgr.busy:
            my   = total_h + 4
            mvis = my - scroll_i
            if 0 <= mvis <= clip_h:
                mr = pygame.Rect(LIST_W // 2 - 90, my, 180, MORE_H)
                pygame.draw.rect(clip_s, _ROW_BG, mr, border_radius=8)
                pygame.draw.rect(clip_s, _BORDER, mr, 1, border_radius=8)
                C.text(clip_s, "+ Carregar mais", "body_bold", 14, T.TEXT_3,
                       mr.centerx, mr.centery, anchor="center")
                self._more_btn = pygame.Rect(mr.x, LIST_TOP + my - scroll_i,
                                             mr.width, mr.height)
        elif results and self._mgr.busy:
            my   = total_h + 4
            mvis = my - scroll_i
            if 0 <= mvis <= clip_h:
                dots = "." * (int(self._t * 3) % 4)
                C.text(clip_s, f"Carregando{dots}", "body_reg", 14, T.GOLD,
                       LIST_W // 2, my + MORE_H // 2, anchor="center")

        surf.blit(clip_s, (0, LIST_TOP),
                  area=pygame.Rect(0, scroll_i, LIST_W, clip_h))

        # Vertical divider between panels
        pygame.draw.line(surf, _BORDER,
                         (SPLIT_X, LIST_TOP), (SPLIT_X, LIST_BOT))

    # ── Detail panel (right side) ──────────────────────────────────────────────

    def _draw_detail(self, surf: pygame.Surface):
        results = self._mgr.results
        dx = DETAIL_X
        dw = DETAIL_W
        dy = LIST_TOP
        dh = LIST_BOT - LIST_TOP

        self._detail_dl = None

        # ── Nothing selected ──────────────────────────────────────────────────
        if self._sel < 0 or self._sel >= len(results):
            C.text(surf, "Selecione uma música", "body_reg", 16, T.TEXT_3,
                   dx + dw // 2, dy + dh // 2, anchor="center")
            return

        song   = results[self._sel]
        src_col = SOURCE_COLORS.get(song.source, T.DIMMED)
        src_lbl = SOURCE_LABELS.get(song.source, song.source.upper())

        # Panel background
        panel_r = pygame.Rect(dx, dy, dw, dh)
        panel_s = pygame.Surface((dw, dh), pygame.SRCALPHA)
        pygame.draw.rect(panel_s, (*_NAVY, 60), panel_s.get_rect(), border_radius=8)
        surf.blit(panel_s, (dx, dy))

        cy = dy + 24   # cursor y

        # Source pill (large)
        tw, _ = C.text_size("body_bold", 15, src_lbl)
        pr = pygame.Rect(dx + MARGIN, cy, tw + 24, 28)
        C.pill(surf, pr, src_col, alpha=210)
        C.text(surf, src_lbl.upper(), "body_bold", 15, T.TEXT_INV,
               pr.centerx, pr.centery, anchor="center")
        cy += pr.height + 16

        # Title
        title = song.title
        # Wrap if too long
        max_chars = 30
        if len(title) > max_chars:
            title = title[:max_chars - 1] + "…"
        C.text(surf, title, "display_bold", 26, T.TEXT_1,
               dx + MARGIN, cy, anchor="topleft")
        cy += 34

        # Artist
        artist = song.artist[:36] if len(song.artist) > 36 else song.artist
        C.text(surf, artist, "body_semi", 18, T.TEXT_2,
               dx + MARGIN, cy, anchor="topleft")
        cy += 26

        # Meta row: year · language · audio badge
        meta_parts = []
        if song.year:
            meta_parts.append(song.year)
        if song.language:
            meta_parts.append(song.language)
        if meta_parts:
            C.text(surf, "  ·  ".join(meta_parts), "body_reg", 14, T.TEXT_3,
                   dx + MARGIN, cy, anchor="topleft")
            cy += 22

        if song.has_audio:
            tw, _ = C.text_size("body_bold", 12, "♪ ÁUDIO")
            ar = pygame.Rect(dx + MARGIN, cy, tw + 16, 20)
            C.pill(surf, ar, T.SUCCESS, alpha=160)
            C.text(surf, "♪ ÁUDIO", "body_bold", 12, T.TEXT_INV,
                   ar.centerx, ar.centery, anchor="center")
            cy += 28

        cy += 12
        C.h_divider(surf, dx + MARGIN, dx + dw - MARGIN, cy, color=_BORDER, alpha=120)
        cy += 14

        # Download status + button
        dstat  = self._mgr.dl_status(song.song_id)
        dprog  = self._mgr.dl_progress(song.song_id)

        BTN_W  = dw - MARGIN * 2
        BTN_H  = 48

        dl_r = pygame.Rect(dx + MARGIN, cy, BTN_W, BTN_H)
        self._detail_dl = dl_r

        if dstat == "done":
            C.pill(surf, dl_r, T.SUCCESS, alpha=220)
            C.text(surf, "✓  SALVO NA BIBLIOTECA", "body_bold", 18, T.TEXT_INV,
                   dl_r.centerx, dl_r.centery, anchor="center")
        elif dstat == "error":
            C.pill(surf, dl_r, T.RED, alpha=220)
            C.text(surf, "ERRO — TENTAR NOVAMENTE", "body_bold", 16, T.TEXT_INV,
                   dl_r.centerx, dl_r.centery, anchor="center")
        elif dstat == "need_login":
            C.pill(surf, dl_r, T.WARNING, alpha=220)
            C.text(surf, "LOGIN NECESSÁRIO", "body_bold", 18, T.TEXT_INV,
                   dl_r.centerx, dl_r.centery, anchor="center")
            self._detail_dl = None
        elif dstat == "browser":
            C.pill(surf, dl_r, T.INFO, alpha=220)
            C.text(surf, "ABERTO NO NAVEGADOR", "body_bold", 18, T.TEXT_INV,
                   dl_r.centerx, dl_r.centery, anchor="center")
            self._detail_dl = None
        elif dstat == "downloading":
            pygame.draw.rect(surf, _NAVY, dl_r, border_radius=dl_r.height // 2)
            pygame.draw.rect(surf, src_col, dl_r, 1, border_radius=dl_r.height // 2)
            if dprog > 0:
                fw = max(dl_r.height, int(dl_r.width * dprog))
                fill = pygame.Rect(dl_r.x, dl_r.y, fw, dl_r.height)
                pygame.draw.rect(surf, (*src_col, 50), fill,
                                 border_radius=dl_r.height // 2)
                pct = f"Baixando…  {int(dprog * 100)}%"
            else:
                pct = "Baixando" + "." * (int(self._t * 3) % 4)
            C.text(surf, pct, "body_bold", 18, src_col,
                   dl_r.centerx, dl_r.centery, anchor="center")
            self._detail_dl = None
        else:
            # Idle — big gold download button
            shim = 1.0 + 0.03 * __import__('math').sin(self._t * 2.8)
            C.pill(surf, dl_r, T.GOLD, alpha=int(220 * shim))
            C.text(surf, "⬇  BAIXAR MÚSICA", "body_xbold", 20, T.TEXT_INV,
                   dl_r.centerx, dl_r.centery, anchor="center")

        cy += BTN_H + 14

        # Hint
        C.text(surf, "ESC  Voltar  ·  ↑↓  Navegar  ·  Enter  Buscar",
               "body_reg", 12, T.TEXT_3,
               dx + dw // 2, LIST_BOT - 10, anchor="midbottom")

    # ── Status bar ─────────────────────────────────────────────────────────────

    def _draw_status(self, surf: pygame.Surface):
        msg = self._mgr.status
        if msg:
            col = T.GOLD if self._mgr.busy else T.TEXT_3
            C.text(surf, msg, "body_reg", 12, col,
                   T.SCREEN_W // 2, STATUS_Y, anchor="midbottom")


# ── Settings screen (simple info panel) ───────────────────────────────────────

class SettingsScreen(BaseScreen):
    def __init__(self, game):
        super().__init__(game)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.game.pop_screen()

    def draw(self, surf):
        surf.fill(T.BG)
        C.text(surf, "SETTINGS", "display_black", 54, T.GOLD,
               T.SCREEN_W // 2, 32, anchor="midtop", uppercase=True)
        C.h_divider(surf, 60, T.SCREEN_W - 60, 100, alpha=100)

        items = [
            ("Song folder",     "songs/  (drop UltraStar folders here)"),
            ("Song format",     "UltraStar .txt — Vocaluxe / USDX compatible"),
            ("Audio formats",   "MP3 · OGG · WAV · FLAC"),
            ("Pitch detection", "HPS / FFT via sounddevice (real-time)"),
            ("Tolerance",       "±2.5 semitones  (octave-folded)"),
            ("Import",          "Song Select > press I > choose folder"),
            ("Download songs",  "usdb.animux.de  (free, largest DB)"),
            ("Version",         "SingFross 1.0  ·  2025"),
        ]

        y = 120
        for key, val in items:
            C.text(surf, key, "cond_bold", 16, T.GOLD_DIM,
                   120, y, uppercase=True)
            C.text(surf, val, "body_semi", 17, T.TEXT_2, 360, y)
            y += 48

        C.text(surf, "ESC  Go back", "body_reg", 14, T.TEXT_3,
               T.SCREEN_W // 2, T.SCREEN_H - 28, anchor="midbottom")
