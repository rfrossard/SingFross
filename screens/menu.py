"""Main menu screen — YARG-style typographic layout."""
import pygame, math, random
from screens.base_screen import BaseScreen
from ui import theme as T
import ui.components as C
from ui.particles import ParticleSystem

ITEMS = [
    ("PLAY",                "song_select"),
    ("SEARCH SONGS",        "search"),
    ("YOUTUBE TO KARAOKE",  "youtube_karaoke"),
    ("SETTINGS",            "settings"),
    ("QUIT",                None),
]


class MenuScreen(BaseScreen):
    def __init__(self, game):
        super().__init__(game)
        self._t          = 0.0
        self._selected   = 0
        self._item_rects = []
        self._particles  = ParticleSystem()
        self._spark_t    = 0.0
        self._bolts = [(random.randint(0, T.SCREEN_W),
                        random.randint(0, T.SCREEN_H // 2),
                        random.randint(28, 70), random.randint(60, 150))
                       for _ in range(8)]

    # ── Input ────────────────────────────────────────────────────────────────

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self._selected = (self._selected - 1) % len(ITEMS)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self._selected = (self._selected + 1) % len(ITEMS)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._activate(self._selected)
        elif event.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self._item_rects):
                if r.collidepoint(event.pos):
                    self._selected = i
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, r in enumerate(self._item_rects):
                if r.collidepoint(event.pos):
                    self._activate(i)

    def _activate(self, idx):
        label, target = ITEMS[idx]
        if target:
            self.game.push_screen(target)
        else:
            self.game.quit()

    # ── Update ───────────────────────────────────────────────────────────────

    def update(self, dt):
        self._t       += dt
        self._spark_t += dt
        self._particles.update(dt)
        if self._spark_t > 0.12:
            self._spark_t = 0.0
            self._particles.stream(
                random.randint(80, T.SCREEN_W - 80),
                random.randint(60, 220),
                T.GOLD, count=1, size=2, speed=35)

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surf):
        surf.fill(T.BG)

        # Subtle background bolts
        for bx, by, bw, bh in self._bolts:
            C.lightning(surf, bx, by, bw, bh, T.GOLD, alpha=18)

        self._draw_logo(surf)
        self._draw_menu(surf)
        self._draw_footer(surf)
        self._particles.draw(surf)

    def _draw_logo(self, surf):
        cy = 105

        # Section label style (Red Hat Display) — "GARAGE BAND KARAOKE"
        C.text_shadow(surf, "GARAGE BAND KARAOKE", "display_bold", 18,
                      T.GOLD_DIM, T.SCREEN_W // 2, cy - 32,
                      anchor="midbottom", uppercase=True,
                      shadow_color=(0, 0, 0), offset=(1, 2))

        # Main title — Red Hat Display Black, huge
        C.text_shadow(surf, "SINGFROSS", "display_black", 96,
                      T.GOLD, T.SCREEN_W // 2, cy,
                      anchor="midtop", shadow_color=(60, 40, 0), offset=(4, 5))

        # Animated underline
        shimmer = C.pulse(self._t, 0.7)
        lw  = 480
        lx  = T.SCREEN_W // 2 - lw // 2
        ly  = cy + 108
        seg = pygame.Surface((lw, 2), pygame.SRCALPHA)
        for i in range(lw):
            t2  = i / lw
            env = math.sin(t2 * math.pi)               # fade in/out at edges
            a   = int(env * (100 + 100 * shimmer))
            seg.set_at((i, 0), (*T.GOLD, a))
        surf.blit(seg, (lx, ly))

    def _draw_menu(self, surf):
        self._item_rects = []
        base_y  = 260
        spacing = 74

        for i, (label, _) in enumerate(ITEMS):
            sel  = (i == self._selected)
            iy   = base_y + i * spacing
            shim = C.pulse(self._t, 1.2)

            if sel:
                # Subtle highlight pill
                pill_w, pill_h = 380, 60
                pr = pygame.Rect(T.SCREEN_W // 2 - pill_w // 2,
                                 iy - pill_h // 2 + 4, pill_w, pill_h)
                C.pill(surf, pr, T.GOLD, alpha=int(22 + 10 * shim))

                # Gold left/right lightning accents
                C.lightning(surf, T.SCREEN_W // 2 - 215, iy - 28,
                            26, 56, T.GOLD, alpha=int(160 + 60 * shim))
                C.lightning(surf, T.SCREEN_W // 2 + 189, iy - 28,
                            26, 56, T.GOLD, alpha=int(160 + 60 * shim))

                color = T.GOLD
                slot  = "body_xbold"
                size  = 52
            else:
                color = T.TEXT_3
                slot  = "body_bold"
                size  = 44

            r = C.text(surf, label, slot, size, color,
                       T.SCREEN_W // 2, iy, anchor="center", uppercase=True)
            self._item_rects.append(r.inflate(240, 24))

    def _draw_footer(self, surf):
        # Mic status pill
        ok     = self.game.mic_manager.available
        col    = T.SUCCESS if ok else T.RED
        label  = "* MIC CONNECTED" if ok else "* MIC NOT FOUND"
        tw, th = C.text_size("cond_bold", 15, label)
        pr     = pygame.Rect(T.SCREEN_W - tw - 32, T.SCREEN_H - 38, tw + 20, 24)
        C.pill(surf, pr, col, alpha=30)
        C.text(surf, label, "cond_bold", 15, col,
               pr.centerx, pr.centery, anchor="center", uppercase=True)

        C.text(surf, "UP/DN  NAVIGATE   ·   ENTER  SELECT   ·   F11  FULLSCREEN",
               "body_reg", 14, T.TEXT_3,
               T.SCREEN_W // 2, T.SCREEN_H - 28, anchor="midbottom")
