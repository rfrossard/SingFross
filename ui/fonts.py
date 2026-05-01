"""Font registry – loads bundled TTFs once and serves cached instances."""
import os
import pygame

_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")

# Slot → (filename, fallback pygame sysfont name)
_SLOTS = {
    # Headers / brand
    "display_black": ("RedHatDisplay-Black.ttf",   None),
    "display_bold":  ("RedHatDisplay-Bold.ttf",    None),
    # Body – almost everything
    "body_xbold":    ("Barlow-ExtraBold.ttf",      None),
    "body_bold":     ("Barlow-Bold.ttf",            None),
    "body_semi":     ("Barlow-SemiBold.ttf",        None),
    "body_reg":      ("Barlow-Regular.ttf",         None),
    # HUD numbers (Unbounded = wide, punchy)
    "num_black":     ("Unbounded-Black.ttf",        None),
    "num_bold":      ("Unbounded-Bold.ttf",         None),
    # Compact HUD labels
    "cond_xbold":    ("BarlowCondensed-ExtraBold.ttf", None),
    "cond_bold":     ("BarlowCondensed-Bold.ttf",   None),
}

_cache: dict[tuple, pygame.font.Font] = {}
_loaded: dict[str, str] = {}   # slot → resolved path


def _resolve(slot: str) -> str:
    if slot in _loaded:
        return _loaded[slot]
    fname, _ = _SLOTS[slot]
    path = os.path.join(_ASSETS, fname)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Font not found: {path}")
    _loaded[slot] = path
    return path


def get(slot: str, size: int) -> pygame.font.Font:
    """Return a cached Font for (slot, size). Call after pygame.init()."""
    key = (slot, size)
    if key not in _cache:
        _cache[key] = pygame.font.Font(_resolve(slot), size)
    return _cache[key]


def clear():
    _cache.clear()
    _loaded.clear()
