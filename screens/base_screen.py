"""Base class for all game screens — provides shared home-button drawing."""
import pygame
from ui import theme as T
import ui.components as C


class BaseScreen:
    def __init__(self, game):
        self.game = game
        self._home_btn = pygame.Rect(0, 0, 1, 1)   # set in draw_home_btn

    # ── Shared home button ────────────────────────────────────────────────────

    def draw_home_btn(self, surf,
                      x: int = None, y: int = 14,
                      w: int = 110, h: int = 36) -> pygame.Rect:
        """Draw the Home button top-right and return its Rect.
        Call this from every screen's draw() and check click in handle_event.
        """
        if x is None:
            x = T.SCREEN_W - w - 14
        btn = pygame.Rect(x, y, w, h)
        self._home_btn = btn
        pygame.draw.rect(surf, T.BG_CARD, btn, border_radius=8)
        pygame.draw.rect(surf, T.GOLD_DIM, btn, 1, border_radius=8)
        C.text(surf, "@ HOME", "body_bold", 13, T.GOLD,
               btn.centerx, btn.centery, anchor="center")
        return btn

    def handle_home_click(self, event) -> bool:
        """Call in handle_event. Returns True if home was clicked (caller should return)."""
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self._home_btn.collidepoint(event.pos)):
            self.game.go_home()
            return True
        return False

    # ── Abstract interface ────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event):
        pass

    def update(self, dt: float):
        pass

    def draw(self, surf: pygame.Surface):
        pass
