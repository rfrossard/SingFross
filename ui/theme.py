"""Visual theme constants — YARG-inspired dark rock palette."""

# ── Backgrounds ────────────────────────────────────────────────────────────
BG            = (10,  10,  14)
BG_PANEL      = (18,  18,  26)
BG_CARD       = (24,  24,  34)
BG_CARD_SEL   = (30,  30,  44)
BG_OVERLAY    = (0,   0,   0)     # used with alpha

# ── Primary accents ────────────────────────────────────────────────────────
GOLD          = (255, 196,  28)   # main brand gold
GOLD_DIM      = (200, 145,  10)
GOLD_GLOW     = (255, 220,  80)
RED           = (220,  42,  42)
RED_DIM       = (160,  30,  30)
DIMMED        = ( 80,  80, 100)   # neutral muted – unknown source badges

# ── Semantic colours ────────────────────────────────────────────────────────
SUCCESS       = ( 54, 214,  90)   # hit / perfect
INFO          = ( 56, 160, 255)
WARNING       = (255, 180,  30)

# ── Text hierarchy ──────────────────────────────────────────────────────────
TEXT_1        = (255, 255, 255)   # primary – titles, active items
TEXT_2        = (185, 185, 200)   # secondary – subtitles, meta
TEXT_3        = (105, 105, 120)   # tertiary – hints, disabled
TEXT_INV      = ( 10,  10,  14)   # on bright backgrounds

# ── Note highway ────────────────────────────────────────────────────────────
HIGHWAY_BG    = ( 10,  10,  16)
HIGHWAY_GRID  = ( 26,  26,  38)
HIGHWAY_GRID2 = ( 20,  20,  30)
NOTE_NORMAL   = (180, 180, 210)
NOTE_GOLDEN   = (255, 196,  28)
NOTE_HIT      = ( 54, 214,  90)
NOTE_GOLDEN_HIT=(255, 240, 110)
PLAYER_DOT    = (255, 255, 255)

# ── Layout ──────────────────────────────────────────────────────────────────
SCREEN_W      = 1280
SCREEN_H      = 720
FPS           = 60

HUD_H         = 80
HIGHWAY_TOP   = HUD_H + 10
HIGHWAY_BOT   = 510
HIGHWAY_LEFT  = 40
HIGHWAY_RIGHT = 1240
LYRICS_Y      = 528
CURRENT_X     = int(HIGHWAY_LEFT + (HIGHWAY_RIGHT - HIGHWAY_LEFT) * 0.25)
LOOK_AHEAD    = 6.0
LOOK_BACK     = 1.5

NOTE_PITCH_MIN = 40
NOTE_PITCH_MAX = 80

# ── Ratings ─────────────────────────────────────────────────────────────────
RATING_STYLE = {
    "LEGENDARY": (GOLD,    "LEGENDARY"),
    "ROCK STAR": (SUCCESS, "ROCK STAR"),
    "SINGER":    (INFO,    "SINGER"),
    "AMATEUR":   (TEXT_2,  "AMATEUR"),
    "TONE DEAF": (RED,     "TONE DEAF"),
}
