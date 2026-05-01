"""YouTube-to-Karaoke screen.

Layout:
  ┌──────────────────────────────────────────────────┐
  │ [  Search bar                              SEARCH ]│  top bar
  ├──────────────────┬───────────────────────────────┤
  │ scrollable list  │  thumbnail + metadata          │
  │ of results       │  + download button             │
  │                  │                                │
  └──────────────────┴───────────────────────────────┘
"""
import pygame, os, threading, re
from screens.base_screen import BaseScreen
from engine.youtube_client import (
    YTVideo, YTDownloadManager, search_karaoke, fetch_thumbnail,
    DownloadResult,
)
from engine import config as CFG
from ui import theme as T
import ui.components as C

# Layout constants
_LIST_W    = 420
_TOP_H     = 64
_PANEL_PAD = 16

_SONGS_DIR = os.path.join(os.path.dirname(__file__), "..", "songs")


class _Thumb:
    """Lazily loads a video thumbnail from bytes."""
    def __init__(self):
        self._surf  = None
        self._busy  = False
        self._tried = False

    def load_async(self, video: YTVideo, size=(160, 90)):
        if self._busy or self._tried:
            return
        self._busy  = True
        self._tried = True

        def _worker():
            data = fetch_thumbnail(video)
            if data:
                import io
                try:
                    raw = pygame.image.load(io.BytesIO(data)).convert()
                    self._surf = pygame.transform.smoothscale(raw, size)
                except Exception:
                    pass
            self._busy = False

        threading.Thread(target=_worker, daemon=True).start()

    @property
    def surface(self):
        return self._surf


class _TextInput:
    def __init__(self, rect: pygame.Rect, placeholder=""):
        self.rect        = rect
        self.placeholder = placeholder
        self.text        = ""
        self.focused     = True
        self._cursor_t   = 0.0

    def handle_event(self, event) -> bool:
        """Returns True when Enter pressed."""
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
        if self.focused and self.text and int(self._cursor_t * 2) % 2 == 0:
            tw = C.text_size("body_reg", 18, self.text)[0]
            cx = self.rect.x + 14 + tw + 2
            cy = self.rect.centery
            pygame.draw.line(surf, T.TEXT_1,
                             (cx, cy - 9), (cx, cy + 9), 2)


class YoutubeKaraokeScreen(BaseScreen):

    def __init__(self, game):
        super().__init__(game)

        cfg        = CFG.get()
        self._songs_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..",
                         cfg._data.get("songs_dir", "songs")))

        # Search state
        self._search_input = _TextInput(
            pygame.Rect(16, 14, T.SCREEN_W - 200, 36),
            placeholder="Search YouTube for karaoke songs…")
        self._searching    = False
        self._results:     list[YTVideo] = []
        self._thumbs:      dict[str, _Thumb] = {}   # video_id → _Thumb
        self._search_err   = ""
        self._t            = 0.0

        # Selection & scroll
        self._sel          = 0
        self._scroll       = 0.0

        # Download manager
        self._dl_mgr       = YTDownloadManager()
        self._dl_result:   dict[str, DownloadResult] = {}  # video_id → result

        # Preview image (large, right panel) — thumbnail of selected video
        self._preview:     _Thumb = _Thumb()
        self._preview_vid  = None

        # Button rects (set in draw)
        self._back_btn      = pygame.Rect(0, 0, 1, 1)
        self._search_btn    = pygame.Rect(0, 0, 1, 1)
        self._play_btn      = pygame.Rect(0, 0, 1, 1)
        self._dl_btn        = pygame.Rect(0, 0, 1, 1)
        self._row_rects:    list[pygame.Rect] = []

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_event(self, event):
        if self._search_input.handle_event(event):
            self._do_search()
            return

        if self.handle_home_click(event):
            return

        if event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_ESCAPE:
                self.game.pop_screen()
            elif k in (pygame.K_UP, pygame.K_w):
                self._sel = max(0, self._sel - 1)
                self._on_sel_change()
            elif k in (pygame.K_DOWN, pygame.K_s):
                self._sel = min(len(self._results) - 1, self._sel + 1)
                self._on_sel_change()
            elif k == pygame.K_RETURN and not self._search_input.focused:
                self._start_download()

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if self._back_btn.collidepoint(pos):
                self.game.pop_screen()
            elif self._search_btn.collidepoint(pos):
                self._do_search()
            elif self._dl_btn.collidepoint(pos):
                self._start_download()
            elif hasattr(self, "_play_btn_active") and self._play_btn.collidepoint(pos):
                self._play_downloaded()
            else:
                for i, r in enumerate(self._row_rects):
                    if r.collidepoint(pos):
                        if i == self._sel:
                            pass  # already selected, do nothing extra
                        else:
                            self._sel = i
                            self._on_sel_change()
                        break

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            delta = -1 if event.button == 4 else 1
            self._sel = max(0, min(len(self._results) - 1, self._sel + delta))
            self._on_sel_change()

    def _on_sel_change(self):
        """Trigger async thumbnail load for newly selected video's preview."""
        if not self._results or self._sel >= len(self._results):
            return
        vid = self._results[self._sel]
        if self._preview_vid != vid.id:
            self._preview_vid = vid.id
            self._preview     = _Thumb()
            # Load a larger preview thumbnail
            self._preview.load_async(vid, size=(620, 349))  # 16:9

    def _do_search(self):
        q = self._search_input.text.strip()
        if not q or self._searching:
            return
        self._searching = True
        self._search_err = ""
        self._results    = []
        self._sel        = 0
        self._thumbs     = {}
        self._preview    = _Thumb()
        self._preview_vid = None

        def _worker():
            try:
                vids = search_karaoke(q, max_results=20)
                self._results = vids
                if vids:
                    self._on_sel_change()
            except Exception as e:
                self._search_err = str(e)
            finally:
                self._searching = False

        threading.Thread(target=_worker, daemon=True).start()

    def _start_download(self):
        if not self._results or self._sel >= len(self._results):
            return
        vid = self._results[self._sel]
        if vid.id in self._dl_result:
            r = self._dl_result[vid.id]
            if r.progress < 1.0 and not r.error:
                return  # already downloading
        result = self._dl_mgr.start(vid, self._songs_dir)
        self._dl_result[vid.id] = result

    def _play_downloaded(self):
        if not self._results or self._sel >= len(self._results):
            return
        vid = self._results[self._sel]
        r   = self._dl_result.get(vid.id)
        if r and r.txt_path and os.path.exists(r.txt_path):
            from engine.song_parser import parse
            try:
                song = parse(r.txt_path)
                self.game.start_song(song)
            except Exception as e:
                print(f"[YT play] {e}")

    # ── Update ────────────────────────────────────────────────────────────

    def update(self, dt):
        self._t += dt
        self._search_input.update(dt)

        # Load row thumbnails for visible items
        for i, vid in enumerate(self._results):
            if vid.id not in self._thumbs:
                th = _Thumb()
                self._thumbs[vid.id] = th
            self._thumbs[vid.id].load_async(vid, size=(142, 80))

        # Smooth scroll
        target = self._sel * 100
        self._scroll += (target - self._scroll) * min(1.0, dt * 12)

    # ── Draw ──────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)
        self._draw_topbar(surf)
        C.h_divider(surf, 0, T.SCREEN_W, _TOP_H, alpha=120)
        self._draw_list(surf)
        C.h_divider(surf, _LIST_W, _LIST_W + 1, _TOP_H, alpha=120,
                    color=T.HIGHWAY_GRID)
        self._draw_detail(surf)
        # Vertical separator
        pygame.draw.line(surf, T.HIGHWAY_GRID,
                         (_LIST_W, _TOP_H), (_LIST_W, T.SCREEN_H), 1)

    # ── Top bar ───────────────────────────────────────────────────────────

    def _draw_topbar(self, surf):
        # Back button
        self._back_btn = pygame.Rect(T.SCREEN_W - 260, 14, 110, 36)
        pygame.draw.rect(surf, T.BG_CARD, self._back_btn, border_radius=8)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, self._back_btn, 1, border_radius=8)
        C.text(surf, "< BACK", "body_bold", 14, T.TEXT_2,
               self._back_btn.centerx, self._back_btn.centery, anchor="center")
        self.draw_home_btn(surf, y=14, h=36)

        # Search input
        self._search_input.rect = pygame.Rect(16, 14, T.SCREEN_W - 270, 36)
        self._search_input.draw(surf)

        # Search button
        self._search_btn = pygame.Rect(T.SCREEN_W - 260, 14, 110, 36)
        busy = self._searching
        C.pill(surf, self._search_btn, T.GOLD if not busy else T.DIMMED,
               alpha=220)
        lbl = ("Searching" + "." * (int(self._t * 3) % 4)) if busy else "SEARCH"
        C.text(surf, lbl, "body_bold", 14, T.TEXT_INV,
               self._search_btn.centerx, self._search_btn.centery,
               anchor="center", uppercase=True)

    # ── Left list ─────────────────────────────────────────────────────────

    def _draw_list(self, surf):
        top     = _TOP_H + 1
        bot     = T.SCREEN_H
        vis_h   = bot - top
        row_h   = 100
        lx      = 0
        lw      = _LIST_W

        clip = pygame.Surface((lw, vis_h), pygame.SRCALPHA)
        self._row_rects = []

        if self._searching and not self._results:
            dots = "." * (int(self._t * 3) % 4)
            C.text(clip, f"Searching{dots}", "body_reg", 18, T.TEXT_3,
                   lw // 2, vis_h // 2, anchor="center")
            surf.blit(clip, (lx, top))
            return

        if not self._results:
            msg = self._search_err or "Search for a karaoke song above"
            C.text(clip, msg, "body_reg", 16, T.TEXT_3,
                   lw // 2, vis_h // 2, anchor="center")
            surf.blit(clip, (lx, top))
            return

        mid_y = vis_h // 2
        for i, vid in enumerate(self._results):
            ry = i * row_h - int(self._scroll) + mid_y - row_h // 2
            if ry + row_h < -10 or ry > vis_h + 10:
                self._row_rects.append(pygame.Rect(-9999, -9999, 1, 1))
                continue

            sel = (i == self._sel)
            # Background
            bg = pygame.Surface((lw, row_h), pygame.SRCALPHA)
            if sel:
                pygame.draw.rect(bg, (*T.BG_CARD_SEL, 240),
                                 bg.get_rect(), border_radius=8)
                pygame.draw.rect(bg, (*T.GOLD, 80),
                                 bg.get_rect(), 1, border_radius=8)
            else:
                pygame.draw.rect(bg, (*T.BG_CARD, 160),
                                 bg.get_rect(), border_radius=6)
            clip.blit(bg, (0, ry))

            if sel:
                pygame.draw.rect(clip, T.GOLD, (0, ry + 10, 3, row_h - 20),
                                 border_radius=2)

            # Thumbnail (142×80)
            th   = self._thumbs.get(vid.id)
            tx, ty = 10, ry + (row_h - 80) // 2
            if th and th.surface:
                clip.blit(th.surface, (tx, ty))
            else:
                pygame.draw.rect(clip, T.BG_PANEL, (tx, ty, 142, 80),
                                 border_radius=4)
                # Loading dots
                if th and th._busy:
                    dots = "." * (int(self._t * 3) % 4)
                    C.text(clip, dots, "body_reg", 14, T.TEXT_3,
                           tx + 71, ty + 40, anchor="center")

            # Text
            tx2 = tx + 152
            title_col  = T.TEXT_1 if sel else T.TEXT_2
            C.text(clip, vid.title[:38], "body_bold", 14, title_col,
                   tx2, ry + 14, anchor="topleft")
            C.text(clip, vid.channel[:34], "body_reg", 12, T.TEXT_3,
                   tx2, ry + 34, anchor="topleft")
            C.text(clip, vid.duration_str, "cond_bold", 12, T.TEXT_3,
                   tx2, ry + 54, anchor="topleft")

            # Download status badge
            dr = self._dl_result.get(vid.id)
            if dr:
                if dr.progress >= 1.0 and not dr.error:
                    badge_col = T.SUCCESS
                    badge_txt = "SAVED"
                elif dr.error:
                    badge_col = T.RED
                    badge_txt = "ERROR"
                else:
                    badge_col = T.INFO
                    pct = int(dr.progress * 100)
                    badge_txt = f"{pct}%"
                bw, _ = C.text_size("cond_bold", 11, badge_txt)
                br = pygame.Rect(lw - bw - 22, ry + 12, bw + 16, 20)
                C.pill(clip, br, badge_col, alpha=200)
                C.text(clip, badge_txt, "cond_bold", 11, T.TEXT_INV,
                       br.centerx, br.centery, anchor="center", uppercase=True)

            real_r = pygame.Rect(lx, top + ry, lw, row_h)
            self._row_rects.append(real_r)

        surf.blit(clip, (lx, top))

    # ── Right detail panel ────────────────────────────────────────────────

    def _draw_detail(self, surf):
        dx  = _LIST_W + _PANEL_PAD
        dw  = T.SCREEN_W - dx - _PANEL_PAD
        top = _TOP_H + _PANEL_PAD

        if not self._results:
            C.text(surf, "Search for a song to preview it here",
                   "body_reg", 18, T.TEXT_3,
                   dx + dw // 2, top + 200, anchor="midtop")
            return

        if self._sel >= len(self._results):
            return

        vid = self._results[self._sel]
        y   = top

        # ── Large thumbnail preview ───────────────────────────────────────
        preview_h = int(dw * 9 / 16)   # 16:9
        preview_r = pygame.Rect(dx, y, dw, preview_h)

        if self._preview.surface:
            s = pygame.transform.smoothscale(self._preview.surface,
                                             (dw, preview_h))
            surf.blit(s, preview_r.topleft)
        else:
            pygame.draw.rect(surf, T.BG_CARD, preview_r, border_radius=8)
            if self._preview._busy:
                dots = "." * (int(self._t * 3) % 4)
                C.text(surf, f"Loading{dots}", "body_reg", 16, T.TEXT_3,
                       preview_r.centerx, preview_r.centery, anchor="center")
            else:
                C.text(surf, "[  VIDEO PREVIEW  ]", "body_bold", 20, T.TEXT_3,
                       preview_r.centerx, preview_r.centery, anchor="center")

        # YouTube logo indicator
        C.text(surf, "YouTube", "body_bold", 11, (255, 80, 80),
               dx + 8, y + preview_h - 18, anchor="topleft")

        y += preview_h + 12

        # ── Metadata ─────────────────────────────────────────────────────
        C.text_shadow(surf, vid.title[:48], "body_bold", 18, T.TEXT_1,
                      dx, y, anchor="topleft",
                      shadow_color=(0, 0, 0), offset=(1, 2))
        y += 26

        C.text(surf, vid.channel, "body_reg", 14, T.TEXT_3, dx, y)
        y += 20

        meta_parts = [vid.duration_str]
        if vid.views > 0:
            if vid.views >= 1_000_000:
                meta_parts.append(f"{vid.views / 1_000_000:.1f}M views")
            elif vid.views >= 1_000:
                meta_parts.append(f"{vid.views // 1000}K views")
            else:
                meta_parts.append(f"{vid.views} views")
        C.text(surf, "  ·  ".join(meta_parts), "body_reg", 13, T.TEXT_3,
               dx, y)
        y += 26

        C.h_divider(surf, dx, dx + dw, y, alpha=70)
        y += 14

        # ── Download status / button ──────────────────────────────────────
        dr = self._dl_result.get(vid.id)
        self._play_btn_active = False

        btn_r = pygame.Rect(dx, T.SCREEN_H - 120, dw, 48)
        self._dl_btn = btn_r

        if dr is None:
            # Ready to download
            shim = C.pulse(self._t, 1.4)
            C.pill(surf, btn_r, T.GOLD, alpha=int(210 + 35 * shim))
            C.text(surf, ">> DOWNLOAD KARAOKE", "body_xbold", 18, T.TEXT_INV,
                   btn_r.centerx, btn_r.centery, anchor="center", uppercase=True)

        elif dr.error:
            # Error — show retry
            C.pill(surf, btn_r, T.RED, alpha=200)
            C.text(surf, "ERROR — RETRY", "body_bold", 16, T.TEXT_1,
                   btn_r.centerx, btn_r.centery, anchor="center")
            err_r = pygame.Rect(dx, btn_r.top - 28, dw, 22)
            C.text(surf, dr.error[:70], "body_reg", 12, T.RED,
                   dx, err_r.y, anchor="topleft")
            # Reset so clicking retries
            if pygame.mouse.get_pressed()[0]:
                pass  # handled in click handler

        elif dr.progress >= 1.0:
            # Done
            pygame.draw.rect(surf, T.BG_CARD, btn_r, border_radius=btn_r.height // 2)
            pygame.draw.rect(surf, T.SUCCESS, btn_r, 2, border_radius=btn_r.height // 2)
            C.text(surf, "SAVED", "body_bold", 16, T.SUCCESS,
                   btn_r.centerx, btn_r.centery - 4, anchor="center")
            C.text(surf, dr.folder[:60] if dr.folder else "",
                   "body_reg", 11, T.TEXT_3,
                   btn_r.centerx, btn_r.bottom + 4, anchor="midtop")

            # Play button
            play_r = pygame.Rect(dx, T.SCREEN_H - 62, dw, 44)
            self._play_btn = play_r
            shim2 = C.pulse(self._t, 1.1)
            C.pill(surf, play_r, T.SUCCESS, alpha=int(195 + 40 * shim2))
            C.text(surf, ">> PLAY / TEST", "body_xbold", 18, T.TEXT_INV,
                   play_r.centerx, play_r.centery, anchor="center", uppercase=True)
            self._play_btn_active = True

        else:
            # Downloading — progress bar + stage label
            pct = dr.progress
            # Animated fill bar
            C.pill(surf, btn_r, T.BG_CARD, alpha=200)
            fill_w = max(btn_r.height, int(btn_r.width * pct))
            fill_r = pygame.Rect(btn_r.x, btn_r.y, fill_w, btn_r.height)
            C.pill(surf, fill_r, T.INFO, alpha=200)
            C.text(surf,
                   f"{dr.stage}  {int(pct * 100)}%",
                   "body_bold", 15, T.TEXT_1,
                   btn_r.centerx, btn_r.centery, anchor="center")

        # ── Hint ─────────────────────────────────────────────────────────
        C.text(surf, "UP/DN  Select   ·   ENTER  Download   ·   ESC  Back",
               "body_reg", 12, T.TEXT_3,
               T.SCREEN_W // 2 + _LIST_W // 2, T.SCREEN_H - 10,
               anchor="midbottom")
