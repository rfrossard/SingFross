"""Results screen and Settings screen."""
import pygame, math
from screens.base_screen import BaseScreen
from ui import theme as T
import ui.components as C
from ui import fonts as F
from ui.particles import ParticleSystem


class ResultsScreen(BaseScreen):
    def __init__(self, game, state, song):
        super().__init__(game)
        self.state     = state
        self.song      = song
        self.particles = ParticleSystem()
        self._t        = 0.0
        self._burst    = False

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.game.push_screen("song_select")
            elif event.key == pygame.K_ESCAPE:
                self.game.go_home()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.handle_home_click(event):
                return
            if hasattr(self, "_btn_again") and self._btn_again.collidepoint(event.pos):
                self.game.push_screen("song_select")
            elif hasattr(self, "_btn_menu") and self._btn_menu.collidepoint(event.pos):
                self.game.go_home()

    def update(self, dt):
        self._t += dt
        self.particles.update(dt)
        if not self._burst and self._t > 0.35:
            self._burst = True
            import random
            for _ in range(5):
                cx = random.randint(120, T.SCREEN_W - 120)
                cy = random.randint(80, 260)
                col = T.GOLD if random.random() > 0.4 else T.SUCCESS
                self.particles.burst(cx, cy, col, count=24, size=7, speed=210, glow=True)

    def draw(self, surf):
        surf.fill(T.BG)
        C.lightning(surf, 30,  80, 70, 180, T.GOLD, alpha=22)
        C.lightning(surf, T.SCREEN_W - 100, 80, 70, 180, T.GOLD, alpha=22)

        self._draw_header(surf)
        self._draw_rating(surf)
        self._draw_stats(surf)
        self._draw_buttons(surf)
        self.particles.draw(surf)
        self.draw_home_btn(surf)

    def _draw_header(self, surf):
        C.text(surf, "PERFORMANCE COMPLETE", "display_bold", 22, T.TEXT_3,
               T.SCREEN_W // 2, 24, anchor="midtop", uppercase=True)
        C.text_shadow(surf, self.song.title, "display_black", 38, T.TEXT_1,
                      T.SCREEN_W // 2, 54, anchor="midtop",
                      shadow_color=(0,0,0), offset=(2,3))
        C.text(surf, self.song.artist, "body_reg", 18, T.TEXT_3,
               T.SCREEN_W // 2, 100, anchor="midtop")
        C.h_divider(surf, 200, T.SCREEN_W - 200, 128, alpha=80)

    def _draw_rating(self, surf):
        rating = self.state.rating
        col, label = T.RATING_STYLE.get(rating, (T.TEXT_2, rating))

        # Pulsing scale
        sc  = 1.0 + 0.04 * math.sin(self._t * 2.8)
        sz  = int(72 * sc)
        img = F.get("display_black", sz).render(label.upper(), True, col)
        sh  = F.get("display_black", sz).render(label.upper(), True, (0, 0, 0))
        rx  = T.SCREEN_W // 2 - img.get_width() // 2
        surf.blit(sh,  (rx + 3, 146))
        surf.blit(img, (rx, 143))

        C.stars_row(surf, T.SCREEN_W // 2, 236, 5, self.state.stars,
                    spacing=52, r=20)

    def _draw_stats(self, surf):
        pr = pygame.Rect(T.SCREEN_W // 2 - 290, 286, 580, 248)
        C.panel(surf, pr, alpha=190)

        rows = [
            ("FINAL SCORE",      f"{self.state.total_score:,}",                 T.GOLD,    "num_black",  36),
            ("ACCURACY",         f"{int(self.state.accuracy * 100)}%",          T.SUCCESS, "num_bold",   30),
            ("MAX COMBO",        str(self.state.max_combo),                     T.INFO,    "num_bold",   30),
            ("NOTES HIT",        f"{self.state.notes_hit} / {self.state.notes_total}", T.TEXT_2, "body_bold", 22),
        ]

        # Score gets its own full-width row
        score_row = rows[0]
        C.text(surf, score_row[0], "cond_bold", 13, T.TEXT_3,
               pr.x + 30, pr.y + 18, uppercase=True)
        C.text_shadow(surf, score_row[1], score_row[4], score_row[3], score_row[2],
                      pr.x + 30, pr.y + 34, shadow_color=(60,40,0), offset=(2,2))

        # Remaining stats in a two-column grid
        C.h_divider(surf, pr.x + 20, pr.right - 20, pr.y + 88, alpha=80)

        cols_data = rows[1:]
        cw = (pr.width - 60) // len(cols_data)
        for ci, (label, val, col, slot, size) in enumerate(cols_data):
            cx = pr.x + 30 + ci * cw
            C.text(surf, label, "cond_bold", 12, T.TEXT_3,
                   cx, pr.y + 102, uppercase=True)
            C.text_shadow(surf, val, slot, size, col,
                          cx, pr.y + 120, shadow_color=(0,0,0), offset=(1,2))

    def _draw_buttons(self, surf):
        bw, bh = 230, 52
        by     = T.SCREEN_H - 76
        shim   = C.pulse(self._t, 1.4)

        self._btn_again = pygame.Rect(T.SCREEN_W // 2 - bw - 16, by, bw, bh)
        self._btn_menu  = pygame.Rect(T.SCREEN_W // 2 + 16,       by, bw, bh)

        # Primary button (Play Again)
        C.pill(surf, self._btn_again, T.GOLD, alpha=int(215 + 35 * shim))
        C.text(surf, ">>  PLAY AGAIN", "body_xbold", 20, T.TEXT_INV,
               self._btn_again.centerx, self._btn_again.centery,
               anchor="center", uppercase=True)

        # Secondary button (Menu)
        C.pill(surf, self._btn_menu, T.BG_CARD, alpha=200)
        pygame.draw.rect(surf, T.HIGHWAY_GRID, self._btn_menu, 1,
                         border_radius=self._btn_menu.height // 2)
        C.text(surf, "#  MAIN MENU", "body_bold", 20, T.TEXT_2,
               self._btn_menu.centerx, self._btn_menu.centery,
               anchor="center", uppercase=True)

        C.text(surf, "ENTER  Play Again   ·   ESC  Menu",
               "body_reg", 13, T.TEXT_3,
               T.SCREEN_W // 2, T.SCREEN_H - 18, anchor="midbottom")


# ── Settings (simple info screen) ──────────────────────────────────────────

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
