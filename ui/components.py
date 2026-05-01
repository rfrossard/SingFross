"""Reusable drawing helpers — YARG-style typography and components."""
import pygame
import math
from ui import theme as T
from ui import fonts as F

# ── Text rendering ──────────────────────────────────────────────────────────

def text(surf: pygame.Surface, txt: str, slot: str, size: int, color,
         x: int, y: int, anchor: str = "topleft",
         uppercase: bool = False, alpha: int = 255) -> pygame.Rect:
    """Render text with a font slot, anchor, optional uppercase transform."""
    f   = F.get(slot, size)
    s   = str(txt).upper() if uppercase else str(txt)
    img = f.render(s, True, color)
    if alpha < 255:
        img.set_alpha(alpha)
    r   = img.get_rect(**{anchor: (x, y)})
    surf.blit(img, r)
    return r


def text_shadow(surf, txt, slot, size, color, x, y, anchor="topleft",
                uppercase=False, shadow_color=(0, 0, 0), offset=(2, 3)):
    """text() with a drop-shadow behind it."""
    f   = F.get(slot, size)
    s   = str(txt).upper() if uppercase else str(txt)
    sh  = f.render(s, True, shadow_color)
    img = f.render(s, True, color)
    r   = img.get_rect(**{anchor: (x, y)})
    surf.blit(sh, r.move(*offset))
    surf.blit(img, r)
    return r


def text_size(slot: str, size: int, txt: str) -> tuple[int, int]:
    return F.get(slot, size).size(str(txt))


# ── Panels ──────────────────────────────────────────────────────────────────

def panel(surf, rect: pygame.Rect, color=T.BG_PANEL,
          border=T.HIGHWAY_GRID, radius: int = 10, alpha: int = 220):
    s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(s, (*color, alpha), s.get_rect(), border_radius=radius)
    surf.blit(s, rect.topleft)
    if border:
        pygame.draw.rect(surf, border, rect, 1, border_radius=radius)


def pill(surf, rect: pygame.Rect, color, alpha: int = 255):
    """Fully-rounded pill shape."""
    s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    pygame.draw.rect(s, (*color, alpha), s.get_rect(),
                     border_radius=rect.height // 2)
    surf.blit(s, rect.topleft)


# ── Progress / bars ─────────────────────────────────────────────────────────

def progress_bar(surf, rect: pygame.Rect, value: float,
                 color=T.GOLD, bg=T.HIGHWAY_GRID, radius: int = 4):
    pygame.draw.rect(surf, bg, rect, border_radius=radius)
    if value > 0:
        fill = rect.copy()
        fill.width = max(radius * 2, int(rect.width * min(1.0, value)))
        pygame.draw.rect(surf, color, fill, border_radius=radius)


# ── Stars ───────────────────────────────────────────────────────────────────

def star(surf, cx, cy, r, filled: bool,
         color=T.GOLD, outline=T.HIGHWAY_GRID):
    pts = []
    for i in range(10):
        a   = math.radians(i * 36 - 90)
        rad = r if i % 2 == 0 else r * 0.40
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    pygame.draw.polygon(surf, color if filled else outline, pts)
    if filled:
        pygame.draw.polygon(surf, T.GOLD_DIM, pts, 2)


def stars_row(surf, cx, cy, count, filled, spacing=44, r=16):
    total = (count - 1) * spacing
    for i in range(count):
        star(surf, cx - total // 2 + i * spacing, cy, r, i < filled)


# ── Note bars ───────────────────────────────────────────────────────────────

def note_bar(surf, rect: pygame.Rect, color, glow=None, radius: int = 5):
    pygame.draw.rect(surf, color, rect, border_radius=radius)
    if glow:
        g = rect.inflate(8, 6)
        gs = pygame.Surface((g.width, g.height), pygame.SRCALPHA)
        pygame.draw.rect(gs, (*glow, 70), gs.get_rect(), border_radius=radius + 3)
        surf.blit(gs, g.topleft, special_flags=pygame.BLEND_RGBA_ADD)


# ── Divider ─────────────────────────────────────────────────────────────────

def h_divider(surf, x1, x2, y, color=T.HIGHWAY_GRID, alpha=180):
    s = pygame.Surface((x2 - x1, 1), pygame.SRCALPHA)
    s.fill((*color, alpha))
    surf.blit(s, (x1, y))


# ── Multiplier badge ────────────────────────────────────────────────────────

def multiplier_badge(surf, cx, cy, mult):
    colors = {1: T.TEXT_3, 2: T.INFO, 4: T.SUCCESS, 8: T.GOLD}
    c   = colors.get(mult, T.GOLD)
    r   = pygame.Rect(0, 0, 64, 30)
    r.center = (cx, cy)
    pill(surf, r, c, alpha=200)
    text(surf, f"×{mult}", "num_bold", 16, T.TEXT_INV if mult >= 4 else T.TEXT_1,
         cx, cy, anchor="center", uppercase=False)


# ── Lightning decoration ────────────────────────────────────────────────────

def lightning(surf, x, y, w, h, color=T.GOLD, alpha=50):
    s = pygame.Surface((w, h), pygame.SRCALPHA)
    pts = [(w*.55,0),(w*.18,h*.45),(w*.50,h*.45),(w*.14,h),(w*.82,h*.38),(w*.50,h*.38)]
    pygame.draw.polygon(s, (*color, alpha), pts)
    surf.blit(s, (x, y))


# ── Utility ─────────────────────────────────────────────────────────────────

def pulse(t: float, speed: float = 2.0) -> float:
    return (math.sin(t * speed * math.pi) + 1) / 2
