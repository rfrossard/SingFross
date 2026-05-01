"""Full settings screen — tabs: Audio · Lyrics · Players · Calibration."""
import pygame, math, time
from screens.base_screen import BaseScreen
from engine import config as CFG
from engine.mic_manager import list_input_devices
from ui import theme as T, fonts as F
import ui.components as C

TABS = ["AUDIO", "LYRICS", "PLAYERS", "CALIBRATION"]

# ── Colour presets for lyrics ────────────────────────────────────────────────
LYRIC_COLORS = [
    ("White",      (255, 255, 255)),
    ("Gold",       (255, 196,  28)),
    ("Cyan",       ( 80, 220, 255)),
    ("Green",      ( 60, 220,  90)),
    ("Pink",       (255, 100, 160)),
    ("Orange",     (255, 140,  30)),
]
ACTIVE_COLORS = [
    ("Gold",       (255, 196,  28)),
    ("White",      (255, 255, 255)),
    ("Green",      ( 60, 220,  90)),
    ("Cyan",       ( 80, 220, 255)),
    ("Red",        (220,  50,  50)),
]
FONT_SLOTS = [
    ("Barlow Bold",      "body_bold"),
    ("Barlow ExtraBold", "body_xbold"),
    ("Barlow Regular",   "body_reg"),
    ("Barlow Condensed", "cond_bold"),
    ("Red Hat Display",  "display_bold"),
]
LYRIC_SIZES = [24, 28, 32, 36, 40, 46, 52]

# ── Player colours ────────────────────────────────────────────────────────────
PLAYER_COLORS = [
    (255, 196,  28),   # gold
    ( 56, 160, 255),   # blue
    ( 60, 220,  90),   # green
    (220,  50,  50),   # red
    (200,  80, 255),   # purple
    (255, 140,  30),   # orange
]
AVATARS = ["🎤","⭐","🎸","🥁","🎵","🎶","🦁","🐯","🦊","🐺",
           "👑","💎","🔥","⚡","🌙","☀️","🎯","🏆","💪","🎪"]


class _TextInput:
    def __init__(self, rect, initial="", max_len=24):
        self.rect    = rect
        self.text    = initial[:max_len]
        self.focused = False
        self.max_len = max_len
        self._t      = 0.0

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.focused = self.rect.collidepoint(event.pos)
        if not self.focused or event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_TAB):
            self.focused = False
        elif event.unicode and event.unicode.isprintable() and len(self.text) < self.max_len:
            self.text += event.unicode
        return False

    def update(self, dt): self._t += dt

    def draw(self, surf):
        bc = T.GOLD if self.focused else T.HIGHWAY_GRID
        pygame.draw.rect(surf, T.BG_CARD, self.rect, border_radius=6)
        pygame.draw.rect(surf, bc, self.rect, 1, border_radius=6)
        C.text(surf, self.text or "…", "body_reg", 17,
               T.TEXT_1 if self.text else T.TEXT_3,
               self.rect.x+10, self.rect.centery, anchor="midleft")
        if self.focused and int(self._t*2)%2==0:
            tw = C.text_size("body_reg",17,self.text)[0]
            x  = self.rect.x+10+tw+1
            pygame.draw.line(surf, T.TEXT_1,
                             (x, self.rect.y+5),(x, self.rect.bottom-5),2)


class _Slider:
    def __init__(self, rect, lo, hi, value, step=1, fmt="{:.0f}"):
        self.rect  = rect
        self.lo, self.hi = lo, hi
        self.value = value
        self.step  = step
        self.fmt   = fmt
        self._drag = False

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._drag = True
                self._update(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP:
            self._drag = False
        elif event.type == pygame.MOUSEMOTION and self._drag:
            self._update(event.pos[0])

    def _update(self, mx):
        t = (mx - self.rect.x) / self.rect.width
        t = max(0.0, min(1.0, t))
        raw = self.lo + t * (self.hi - self.lo)
        self.value = round(raw / self.step) * self.step

    def draw(self, surf, label="", value_label=None):
        # Track
        C.progress_bar(surf, self.rect,
                       (self.value - self.lo) / max(1, self.hi - self.lo),
                       color=T.GOLD, bg=T.HIGHWAY_GRID)
        # Thumb
        t  = (self.value - self.lo) / max(1, self.hi - self.lo)
        tx = int(self.rect.x + t * self.rect.width)
        pygame.draw.circle(surf, T.GOLD, (tx, self.rect.centery), 9)
        pygame.draw.circle(surf, T.TEXT_1, (tx, self.rect.centery), 4)
        # Labels
        if label:
            C.text(surf, label, "cond_bold", 13, T.TEXT_3,
                   self.rect.x, self.rect.y - 18, uppercase=True)
        vl = value_label or self.fmt.format(self.value)
        C.text(surf, vl, "body_bold", 15, T.TEXT_1,
               self.rect.right + 12, self.rect.centery, anchor="midleft")


class SettingsScreen(BaseScreen):

    def __init__(self, game):
        super().__init__(game)
        self._tab   = 0
        self._tab_rects: list[pygame.Rect] = []
        self._t     = 0.0
        self._cfg   = CFG.get()
        self._devices = list_input_devices()
        self._dirty = False
        self._cal_playing = False
        self._cal_start   = 0.0
        self._cal_taps: list[float] = []

        self._build_widgets()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_widgets(self):
        cfg = self._cfg

        # AUDIO tab
        self._vol_sl  = _Slider(pygame.Rect(200, 200, 400, 14),
                                0.0, 1.0, cfg.volume, step=0.05, fmt="{:.0%}")
        self._sync_sl = _Slider(pygame.Rect(200, 280, 400, 14),
                                -500, 500, cfg.get("audio","sync_offset_ms",default=0),
                                step=10, fmt="{:+.0f} ms")

        # LYRICS tab
        ly = cfg.lyrics
        self._lyric_font_idx  = next(
            (i for i,(l,s) in enumerate(FONT_SLOTS) if s==ly.get("font_slot")), 0)
        self._lyric_size_idx  = next(
            (i for i,s in enumerate(LYRIC_SIZES) if s==ly.get("size",36)), 3)
        self._lyric_col_idx   = 0
        self._active_col_idx  = 0

        # PLAYERS tab — name inputs + device dropdowns per player
        players = cfg.player
        self._p_names   = [
            _TextInput(pygame.Rect(200, 200 + i*120, 260, 36),
                       initial=players[i].get("name","Player "+str(i+1)))
            for i in range(2)
        ]
        self._p_dev_idx = [
            self._device_idx(players[i].get("mic_device")) for i in range(2)
        ]
        self._p_col_idx = [
            self._color_idx(players[i].get("color",[255,196,28])) for i in range(2)
        ]
        self._p_av_idx  = [
            self._avatar_idx(players[i].get("avatar","🎤")) for i in range(2)
        ]
        self._two_player = cfg.two_player

        # USDB credentials
        user, pw = cfg.usdb_credentials
        self._usdb_user = _TextInput(pygame.Rect(200, 420, 260, 36), initial=user)
        self._usdb_pass = _TextInput(pygame.Rect(200, 470, 260, 36), initial=pw)

    def _device_idx(self, dev):
        devs = [None] + [d["name"] for d in self._devices]
        try:
            return devs.index(dev)
        except ValueError:
            return 0

    def _color_idx(self, color):
        for i, c in enumerate(PLAYER_COLORS):
            if list(c) == list(color):
                return i
        return 0

    def _avatar_idx(self, av):
        try:
            return AVATARS.index(av)
        except ValueError:
            return 0

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            k = event.key
            if k == pygame.K_ESCAPE:
                self._save()
                self.game.pop_screen()
                return
            elif k in (pygame.K_LEFT, pygame.K_a):
                self._tab = (self._tab - 1) % len(TABS)
                return
            elif k in (pygame.K_RIGHT, pygame.K_d):
                self._tab = (self._tab + 1) % len(TABS)
                return

        # Tab clicks
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.handle_home_click(event):
                self._save()
                return
            if hasattr(self, "_back_btn") and self._back_btn.collidepoint(event.pos):
                self._save()
                self.game.pop_screen()
                return
            for i, r in enumerate(self._tab_rects):
                if r.collidepoint(event.pos):
                    self._tab = i
                    return

        tab = self._tab
        if tab == 0:
            self._vol_sl.handle_event(event)
            self._sync_sl.handle_event(event)
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION,
                               pygame.MOUSEBUTTONUP):
                self._dirty = True
        elif tab == 1:
            self._handle_lyrics_events(event)
        elif tab == 2:
            self._handle_players_events(event)
        elif tab == 3:
            self._handle_cal_events(event)

    def _handle_lyrics_events(self, event):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        mx, my = event.pos
        # Font buttons
        for i, r in enumerate(getattr(self, "_font_rects", [])):
            if r.collidepoint(mx, my):
                self._lyric_font_idx = i; self._dirty = True
        # Size buttons
        for i, r in enumerate(getattr(self, "_size_rects", [])):
            if r.collidepoint(mx, my):
                self._lyric_size_idx = i; self._dirty = True
        # Colour swatches
        for i, r in enumerate(getattr(self, "_lcol_rects", [])):
            if r.collidepoint(mx, my):
                self._lyric_col_idx = i; self._dirty = True
        for i, r in enumerate(getattr(self, "_acol_rects", [])):
            if r.collidepoint(mx, my):
                self._active_col_idx = i; self._dirty = True

    def _handle_players_events(self, event):
        for ti in self._p_names:
            ti.handle_event(event)
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        mx, my = event.pos
        # Device selectors
        devs = [None] + [d["name"] for d in self._devices]
        for pi in range(2):
            for di, r in enumerate(getattr(self, f"_dev_rects_{pi}", [])):
                if r.collidepoint(mx, my):
                    self._p_dev_idx[pi] = di
                    self._dirty = True
                    device = devs[di] if di < len(devs) else None
                    sens   = float(self._cfg.player[pi].get("mic_sensitivity", 1.0))
                    self.game.mic_manager.players[pi].start(device=device, sensitivity=sens)
            # Colour swatches
            for ci, r in enumerate(getattr(self, f"_pcol_rects_{pi}", [])):
                if r.collidepoint(mx, my):
                    self._p_col_idx[pi] = ci; self._dirty = True
            # Avatar picker
            for ai, r in enumerate(getattr(self, f"_pav_rects_{pi}", [])):
                if r.collidepoint(mx, my):
                    self._p_av_idx[pi] = ai; self._dirty = True
        # 2-player toggle
        if hasattr(self, "_two_btn") and self._two_btn.collidepoint(mx, my):
            self._two_player = not self._two_player; self._dirty = True
        # USDB credentials
        self._usdb_user.handle_event(event)
        self._usdb_pass.handle_event(event)

    def _handle_cal_events(self, event):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        mx, my = event.pos
        if hasattr(self, "_cal_start_btn") and self._cal_start_btn.collidepoint(mx, my):
            self._cal_playing = True
            self._cal_start   = time.perf_counter()
            self._cal_taps    = []
            pygame.mixer.music.stop()
        if hasattr(self, "_cal_tap_btn") and self._cal_tap_btn.collidepoint(mx,my):
            if self._cal_playing:
                self._cal_taps.append(time.perf_counter() - self._cal_start)
        if hasattr(self, "_cal_apply_btn") and self._cal_apply_btn.collidepoint(mx,my):
            self._apply_calibration()

    def _apply_calibration(self):
        if len(self._cal_taps) < 2:
            return
        # Expected beat interval (assume ~120 BPM test tone = 0.5s)
        expected = 0.5
        diffs     = [self._cal_taps[i+1]-self._cal_taps[i]
                    for i in range(len(self._cal_taps)-1)]
        avg_tap   = sum(diffs)/len(diffs)
        # Offset: how much earlier/later user tapped vs expected
        offset_ms = round((avg_tap - expected) * 1000, 0)
        self._sync_sl.value = max(-500, min(500, offset_ms))
        self._dirty = True

    # ── Update ────────────────────────────────────────────────────────────

    def update(self, dt):
        self._t += dt
        for ti in self._p_names:
            ti.update(dt)
        self._usdb_user.update(dt)
        self._usdb_pass.update(dt)

    # ── Save ──────────────────────────────────────────────────────────────

    def _save(self):
        if not self._dirty:
            return
        cfg = self._cfg
        # Audio
        cfg.set("audio", "volume",          round(self._vol_sl.value, 2))
        cfg.set("audio", "sync_offset_ms",  int(self._sync_sl.value))
        # Lyrics
        ly_slot = FONT_SLOTS[self._lyric_font_idx][1]
        ly_size = LYRIC_SIZES[self._lyric_size_idx]
        ly_col  = list(LYRIC_COLORS[self._lyric_col_idx][1])
        ac_col  = list(ACTIVE_COLORS[self._active_col_idx][1])
        cfg.set("lyrics", "font_slot",    ly_slot)
        cfg.set("lyrics", "size",         ly_size)
        cfg.set("lyrics", "color",        ly_col)
        cfg.set("lyrics", "active_color", ac_col)
        # Players
        devs = [None] + [d["name"] for d in self._devices]
        for i in range(2):
            cfg.set("players", i, "name",       self._p_names[i].text or f"Player {i+1}")
            cfg.set("players", i, "mic_device",
                    devs[self._p_dev_idx[i]] if self._p_dev_idx[i] < len(devs) else None)
            cfg.set("players", i, "color",      list(PLAYER_COLORS[self._p_col_idx[i]]))
            cfg.set("players", i, "avatar",     AVATARS[self._p_av_idx[i]])
        cfg.set("two_player", self._two_player)
        # USDB
        cfg.set("usdb", "username", self._usdb_user.text)
        cfg.set("usdb", "password", self._usdb_pass.text)
        cfg.save()

    # ── Draw ──────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)
        self._draw_back_btn(surf)
        self._draw_tabs(surf)
        C.h_divider(surf, 20, T.SCREEN_W-20, 80, alpha=100)

        if   self._tab == 0: self._draw_audio(surf)
        elif self._tab == 1: self._draw_lyrics(surf)
        elif self._tab == 2: self._draw_players(surf)
        elif self._tab == 3: self._draw_calibration(surf)

        C.text(surf, "< / >  Switch tabs    ESC  Save & Back",
               "body_reg", 13, T.TEXT_3,
               T.SCREEN_W//2, T.SCREEN_H-18, anchor="midbottom")

    def _draw_back_btn(self, surf):
        btn = pygame.Rect(T.SCREEN_W - 280, 20, 110, 36)
        self._back_btn = btn
        pygame.draw.rect(surf, T.BG_CARD, btn, border_radius=8)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, btn, 1, border_radius=8)
        C.text(surf, "< BACK", "body_bold", 15, T.TEXT_2,
               btn.centerx, btn.centery, anchor="center")
        self.draw_home_btn(surf, y=20, h=36)

    def _draw_tabs(self, surf):
        self._tab_rects = []
        sx = 20
        for i, label in enumerate(TABS):
            sel = (i == self._tab)
            tw, _ = C.text_size("cond_bold", 18, label)
            tr = pygame.Rect(sx, 20, tw+28, 42)
            if sel:
                C.pill(surf, tr, T.GOLD, alpha=220)
                C.text(surf, label, "cond_bold", 18, T.TEXT_INV,
                       tr.centerx, tr.centery, anchor="center", uppercase=True)
            else:
                pygame.draw.rect(surf, T.HIGHWAY_GRID, tr, 1, border_radius=tr.height//2)
                C.text(surf, label, "cond_bold", 18, T.TEXT_3,
                       tr.centerx, tr.centery, anchor="center", uppercase=True)
            self._tab_rects.append(tr)
            sx += tr.width + 10

    def _row(self, surf, y, label, widget_fn):
        C.text(surf, label, "cond_bold", 14, T.TEXT_3,
               40, y, anchor="midleft", uppercase=True)
        widget_fn(y)

    # ── Audio tab ─────────────────────────────────────────────────────────

    def _draw_audio(self, surf):
        y = 120
        C.text(surf, "VOLUME", "cond_bold", 14, T.TEXT_3, 40, y, uppercase=True)
        self._vol_sl.rect.y = y + 22
        self._vol_sl.draw(surf)
        y += 70
        C.text(surf, "LYRICS SYNC OFFSET", "cond_bold", 14, T.TEXT_3,
               40, y, uppercase=True)
        C.text(surf, "(positive = lyrics appear earlier)",
               "body_reg", 13, T.TEXT_3, 240, y, anchor="midleft")
        self._sync_sl.rect.y = y + 22
        self._sync_sl.draw(surf)
        y += 90
        C.text(surf, "USDB ACCOUNT", "cond_bold", 14, T.TEXT_3,
               40, y-4, uppercase=True)
        C.text(surf, "Required to download song .txt files from USDB",
               "body_reg", 13, T.TEXT_3, 40, y+16)
        y += 48
        C.text(surf, "Username", "body_reg", 14, T.TEXT_2, 40, y+10)
        self._usdb_user.rect.topleft = (200, y)
        self._usdb_user.draw(surf)
        y += 50
        C.text(surf, "Password", "body_reg", 14, T.TEXT_2, 40, y+10)
        self._usdb_pass.rect.topleft = (200, y)
        # Mask password
        orig = self._usdb_pass.text
        self._usdb_pass.text = "*" * len(orig)
        self._usdb_pass.draw(surf)
        self._usdb_pass.text = orig

    # ── Lyrics tab ────────────────────────────────────────────────────────

    def _draw_lyrics(self, surf):
        y = 110

        # Font selection
        C.text(surf, "FONT", "cond_bold", 14, T.TEXT_3, 40, y, uppercase=True)
        y += 26
        self._font_rects = []
        x = 40
        for i, (label, slot) in enumerate(FONT_SLOTS):
            sel  = (i == self._lyric_font_idx)
            tw,_ = C.text_size("body_bold", 15, label)
            r    = pygame.Rect(x, y, tw+20, 32)
            C.pill(surf, r, T.GOLD if sel else T.BG_CARD, alpha=220 if sel else 160)
            if not sel:
                pygame.draw.rect(surf, T.HIGHWAY_GRID, r, 1,
                                 border_radius=r.height//2)
            C.text(surf, label, "body_reg", 14, T.TEXT_INV if sel else T.TEXT_2,
                   r.centerx, r.centery, anchor="center")
            self._font_rects.append(r)
            x += r.width + 8
        y += 46

        # Size selection
        C.text(surf, "SIZE", "cond_bold", 14, T.TEXT_3, 40, y, uppercase=True)
        y += 26
        self._size_rects = []
        x = 40
        for i, sz in enumerate(LYRIC_SIZES):
            sel  = (i == self._lyric_size_idx)
            r    = pygame.Rect(x, y, 44, 32)
            C.pill(surf, r, T.GOLD if sel else T.BG_CARD, alpha=220 if sel else 160)
            if not sel:
                pygame.draw.rect(surf, T.HIGHWAY_GRID, r, 1, border_radius=r.height//2)
            C.text(surf, str(sz), "body_bold", 14,
                   T.TEXT_INV if sel else T.TEXT_2,
                   r.centerx, r.centery, anchor="center")
            self._size_rects.append(r)
            x += 52
        y += 52

        # Text colour
        C.text(surf, "TEXT COLOUR", "cond_bold", 14, T.TEXT_3, 40, y, uppercase=True)
        y += 26
        self._lcol_rects = []
        x = 40
        for i, (name, col) in enumerate(LYRIC_COLORS):
            sel = (i == self._lyric_col_idx)
            r   = pygame.Rect(x, y, 36, 36)
            pygame.draw.circle(surf, col, r.center, 16)
            if sel:
                pygame.draw.circle(surf, T.TEXT_1, r.center, 18, 3)
            self._lcol_rects.append(r)
            x += 48
        y += 54

        # Active colour
        C.text(surf, "ACTIVE SYLLABLE COLOUR", "cond_bold", 14, T.TEXT_3,
               40, y, uppercase=True)
        y += 26
        self._acol_rects = []
        x = 40
        for i, (name, col) in enumerate(ACTIVE_COLORS):
            sel = (i == self._active_col_idx)
            r   = pygame.Rect(x, y, 36, 36)
            pygame.draw.circle(surf, col, r.center, 16)
            if sel:
                pygame.draw.circle(surf, T.TEXT_1, r.center, 18, 3)
            self._acol_rects.append(r)
            x += 48
        y += 64

        # Live preview
        C.h_divider(surf, 40, T.SCREEN_W-40, y-8, alpha=60)
        slot  = FONT_SLOTS[self._lyric_font_idx][1]
        size  = LYRIC_SIZES[self._lyric_size_idx]
        tcol  = LYRIC_COLORS[self._lyric_col_idx][1]
        acol  = ACTIVE_COLORS[self._active_col_idx][1]
        C.text(surf, "PREVIEW", "cond_bold", 12, T.TEXT_3, 40, y, uppercase=True)
        y += 20
        preview = [("Hold ", tcol), ("on ", acol), ("to ", tcol),
                   ("me ", tcol), ("tight ", tcol)]
        px = 40
        for word, col in preview:
            img = F.get(slot, size).render(word, True, col)
            surf.blit(img, (px, y))
            px += img.get_width()

    # ── Players tab ───────────────────────────────────────────────────────

    def _draw_players(self, surf):
        devs_labels = ["Default mic"] + [d["name"] for d in self._devices]

        for pi in range(2):
            base_y = 100 + pi * 278
            col    = PLAYER_COLORS[self._p_col_idx[pi]]

            # Player header
            pr = pygame.Rect(30, base_y, T.SCREEN_W - 60, 38)
            C.panel(surf, pr, color=T.BG_CARD, alpha=180)
            pygame.draw.rect(surf, col, pygame.Rect(30, base_y, 4, 38), border_radius=2)
            C.text(surf, f"PLAYER {pi+1}", "cond_bold", 16, col,
                   48, base_y + 19, anchor="midleft", uppercase=True)

            # Live mic status + volume meter
            pm     = self.game.mic_manager.players[pi]
            status_col = T.SUCCESS if pm.available else T.RED
            status_txt = "* CONNECTED" if pm.available else "* NOT CONNECTED"
            C.text(surf, status_txt, "cond_bold", 12, status_col,
                   T.SCREEN_W - 90, base_y + 19, anchor="midright", uppercase=True)
            if pm.available:
                vol  = min(1.0, pm.volume * 12)
                bar  = pygame.Rect(T.SCREEN_W - 240, base_y + 12, 140, 14)
                C.progress_bar(surf, bar, vol, color=col, bg=T.HIGHWAY_GRID)

            y = base_y + 50
            # Name
            C.text(surf, "Name", "body_reg", 13, T.TEXT_3, 50, y + 7)
            self._p_names[pi].rect.topleft = (160, y)
            self._p_names[pi].draw(surf)
            y += 40

            # Microphone device — scrollable row (show all devices)
            C.text(surf, "Mic", "body_reg", 13, T.TEXT_3, 50, y + 4)
            rects_attr = f"_dev_rects_{pi}"
            setattr(self, rects_attr, [])
            dx = 160
            row_surf = pygame.Surface((T.SCREEN_W - 180, 30), pygame.SRCALPHA)
            dev_rects_local = []
            for di, dlabel in enumerate(devs_labels):
                sel   = (di == self._p_dev_idx[pi])
                short = dlabel[:28]
                tw, _ = C.text_size("body_reg", 12, short)
                dr    = pygame.Rect(dx - 160, 0, tw + 14, 26)
                C.pill(row_surf, dr, col if sel else T.BG_CARD, alpha=200 if sel else 140)
                if not sel:
                    pygame.draw.rect(row_surf, T.HIGHWAY_GRID, dr, 1,
                                     border_radius=dr.height // 2)
                C.text(row_surf, short, "body_reg", 12,
                       T.TEXT_INV if sel else T.TEXT_2,
                       dr.centerx, dr.centery, anchor="center")
                dev_rects_local.append(pygame.Rect(dx, y + pr.y - pr.y + base_y + 50 + 40, dr.width, dr.height))
                # Store screen-space rects
                getattr(self, rects_attr).append(pygame.Rect(dx, y, dr.width, dr.height))
                dx += dr.width + 5
            surf.blit(row_surf, (160, y))
            y += 38

            # Colour swatches
            C.text(surf, "Colour", "body_reg", 13, T.TEXT_3, 50, y + 5)
            col_rects_attr = f"_pcol_rects_{pi}"
            setattr(self, col_rects_attr, [])
            cx = 160
            for ci, c in enumerate(PLAYER_COLORS):
                sel = (ci == self._p_col_idx[pi])
                cr  = pygame.Rect(cx, y, 26, 26)
                pygame.draw.circle(surf, c, cr.center, 11)
                if sel:
                    pygame.draw.circle(surf, T.TEXT_1, cr.center, 13, 2)
                getattr(self, col_rects_attr).append(cr)
                cx += 32
            y += 34

            # Avatar row
            C.text(surf, "Avatar", "body_reg", 13, T.TEXT_3, 50, y + 3)
            av_rects_attr = f"_pav_rects_{pi}"
            setattr(self, av_rects_attr, [])
            ax = 160
            for ai, em in enumerate(AVATARS[:14]):
                sel = (ai == self._p_av_idx[pi])
                ar  = pygame.Rect(ax, y, 28, 28)
                if sel:
                    C.pill(surf, ar, col, alpha=180)
                C.text(surf, em, "body_reg", 17, T.TEXT_1,
                       ar.centerx, ar.centery, anchor="center")
                getattr(self, av_rects_attr).append(ar)
                ax += 32

        # 2-player toggle
        ty = T.SCREEN_H - 72
        C.text(surf, "2-PLAYER MODE", "cond_bold", 14, T.TEXT_2,
               40, ty, anchor="midleft", uppercase=True)
        self._two_btn = pygame.Rect(220, ty - 14, 76, 28)
        active = self._two_player
        C.pill(surf, self._two_btn, T.SUCCESS if active else T.BG_CARD,
               alpha=220 if active else 150)
        if not active:
            pygame.draw.rect(surf, T.HIGHWAY_GRID, self._two_btn, 1,
                             border_radius=self._two_btn.height // 2)
        C.text(surf, "ON" if active else "OFF", "body_bold", 13,
               T.TEXT_INV if active else T.TEXT_3,
               self._two_btn.centerx, self._two_btn.centery, anchor="center")

    # ── Calibration tab ───────────────────────────────────────────────────

    def _draw_calibration(self, surf):
        y = 100
        C.text(surf, "SYNC CALIBRATION", "display_bold", 26, T.TEXT_1,
               40, y, uppercase=True)
        y += 40
        C.text(surf,
               "If lyrics are out of sync with the audio, use this tool\n"
               "to measure your setup's audio latency.",
               "body_reg", 17, T.TEXT_2, 40, y)
        y += 68

        C.h_divider(surf, 40, T.SCREEN_W-40, y, alpha=60)
        y += 24

        C.text(surf, "HOW TO USE", "cond_bold", 13, T.TEXT_3, 40, y, uppercase=True)
        y += 22
        steps = [
            "1. Click START — a metronome beat plays.",
            "2. TAP the button in time with what you HEAR.",
            "3. Tap at least 4 times, then click APPLY.",
            "4. The offset is calculated and saved automatically.",
        ]
        for step in steps:
            C.text(surf, step, "body_reg", 16, T.TEXT_2, 55, y)
            y += 26
        y += 16

        # Start button
        self._cal_start_btn = pygame.Rect(40, y, 160, 48)
        C.pill(surf, self._cal_start_btn,
               T.SUCCESS if self._cal_playing else T.GOLD, alpha=220)
        C.text(surf, "STOP" if self._cal_playing else "PLAY",
               "body_bold", 18, T.TEXT_INV,
               self._cal_start_btn.centerx, self._cal_start_btn.centery,
               anchor="center", uppercase=True)

        # Tap button
        self._cal_tap_btn = pygame.Rect(220, y, 160, 48)
        alpha = 220 if self._cal_playing else 80
        C.pill(surf, self._cal_tap_btn, T.INFO, alpha=alpha)
        C.text(surf, "TAP BEAT", "body_bold", 18,
               T.TEXT_INV if self._cal_playing else T.TEXT_3,
               self._cal_tap_btn.centerx, self._cal_tap_btn.centery,
               anchor="center", uppercase=True)

        y += 64
        # Tap count
        C.text(surf, f"Taps recorded: {len(self._cal_taps)}",
               "body_reg", 15, T.TEXT_2, 40, y)
        y += 32

        # Current offset display
        C.text(surf, f"Current offset: {int(self._sync_sl.value):+d} ms",
               "body_semi", 18, T.GOLD, 40, y)
        y += 48

        # Apply button
        self._cal_apply_btn = pygame.Rect(40, y, 160, 44)
        en = len(self._cal_taps) >= 2
        C.pill(surf, self._cal_apply_btn, T.GOLD if en else T.BG_CARD,
               alpha=220 if en else 100)
        if not en:
            pygame.draw.rect(surf, T.HIGHWAY_GRID, self._cal_apply_btn, 1,
                             border_radius=self._cal_apply_btn.height//2)
        C.text(surf, "APPLY", "body_bold", 18,
               T.TEXT_INV if en else T.TEXT_3,
               self._cal_apply_btn.centerx, self._cal_apply_btn.centery,
               anchor="center", uppercase=True)

        if self._cal_playing:
            beat = math.sin(
                (time.perf_counter() - self._cal_start) * math.pi * 2 * 2)
            r = int(60 + 30 * beat)
            dot_r = int(12 + 8 * max(0, beat))
            dot_s = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
            pygame.draw.circle(dot_s, (*T.GOLD, 200), (dot_r, dot_r), dot_r)
            surf.blit(dot_s, (500, y + 22 - dot_r))
