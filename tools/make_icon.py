"""Generate SingFross.icns — YARG-style: dark bg, gold mic + bold lightning."""
import os, subprocess, shutil
from PIL import Image, ImageDraw, ImageFilter

ROOT     = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_PNG  = os.path.join(ROOT, "assets", "icon_1024.png")
ICONSET  = os.path.join(ROOT, "assets", "SingFross.iconset")
OUT_ICNS = os.path.join(ROOT, "assets", "SingFross.icns")
BUNDLE   = "/Applications/SingFross.app/Contents/Resources/SingFross.icns"

GOLD   = (255, 196,  28)
WHITE  = (255, 255, 255)
BG     = ( 10,  10,  14)
DARK   = ( 18,  18,  28)


def draw_bolt_polygon(draw, cx, top_y, bot_y, size, fill):
    """
    Proper 6-point lightning bolt polygon (top-right → bottom-left zigzag).
    Based on standard SVG bolt shape: M20,0 L0,14 L11,14 L0,28 L20,14 L9,14 Z
    """
    half = int(size * 0.135)   # horizontal half-span
    notch = int(size * 0.012)  # small notch step at mid
    mid_y = (top_y + bot_y) // 2

    pts = [
        (cx + half,   top_y),   # 1 top-right
        (cx - half,   mid_y),   # 2 mid-left
        (cx + notch,  mid_y),   # 3 notch inward-right
        (cx - half,   bot_y),   # 4 bot-left
        (cx + half,   mid_y),   # 5 mid-right
        (cx - notch,  mid_y),   # 6 notch inward-left
    ]
    draw.polygon(pts, fill=fill)
    return pts


def make_base(size=1024) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r    = size // 5

    # ── Rounded-square background ─────────────────────────────────────────
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=r, fill=(*BG, 255))

    # Subtle centre glow
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    for step in range(16, 0, -1):
        frac = step / 16
        rs   = int(size * 0.55 * frac)
        a    = int(18 * (1 - frac))
        gd.ellipse([size//2-rs, size//2-rs, size//2+rs, size//2+rs],
                   fill=(30, 30, 55, a))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # ── Microphone geometry ───────────────────────────────────────────────
    mc_w = int(size * 0.32)
    mc_h = int(size * 0.42)
    mc_x = (size - mc_w) // 2
    mc_y = int(size * 0.08)
    mc_r = mc_w // 2
    lw   = max(4, size // 88)   # stroke width

    # Capsule fill (dark interior)
    draw.rounded_rectangle(
        [mc_x, mc_y, mc_x + mc_w, mc_y + mc_h],
        radius=mc_r, fill=(*DARK, 255),
    )
    # Capsule gold border
    draw.rounded_rectangle(
        [mc_x, mc_y, mc_x + mc_w, mc_y + mc_h],
        radius=mc_r, outline=(*GOLD, 255), width=lw,
    )

    # Grille lines (3 subtle horizontal bars inside capsule)
    gw = int(mc_w * 0.60)
    gx = mc_x + (mc_w - gw) // 2
    for frac in (0.30, 0.50, 0.70):
        gy = mc_y + int(mc_h * frac)
        draw.line([(gx, gy), (gx + gw, gy)],
                  fill=(*GOLD, 55), width=max(2, lw // 2))

    # ── Lightning bolt (large, centred in mic capsule) ────────────────────
    cx     = size // 2
    bolt_t = mc_y + int(mc_h * 0.06)
    bolt_b = mc_y + int(mc_h * 0.94)

    # Glow layer behind bolt
    glow2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd2   = ImageDraw.Draw(glow2)
    draw_bolt_polygon(gd2, cx, bolt_t, bolt_b, size, (*GOLD, 120))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(radius=size // 36))
    img   = Image.alpha_composite(img, glow2)
    draw  = ImageDraw.Draw(img)

    # Solid bolt (bright gold)
    draw_bolt_polygon(draw, cx, bolt_t, bolt_b, size, (*GOLD, 255))

    # ── Mic stand ─────────────────────────────────────────────────────────
    stand_top = mc_y + mc_h
    arc_w     = int(mc_w * 1.50)
    arc_h     = int(size * 0.095)
    ax        = (size - arc_w) // 2

    draw.arc([ax, stand_top, ax + arc_w, stand_top + arc_h * 2],
             start=200, end=340, fill=(*GOLD, 255), width=lw)

    pole_top = stand_top + arc_h
    pole_bot = int(size * 0.755)
    draw.line([(cx, pole_top), (cx, pole_bot)],
              fill=(*GOLD, 255), width=lw)

    base_w = int(size * 0.30)
    bx1    = cx - base_w // 2
    bx2    = cx + base_w // 2
    draw.line([(bx1, pole_bot), (bx2, pole_bot)],
              fill=(*GOLD, 255), width=lw)
    dot = lw + 2
    draw.ellipse([bx1-dot, pole_bot-dot, bx1+dot, pole_bot+dot],
                 fill=(*GOLD, 255))
    draw.ellipse([bx2-dot, pole_bot-dot, bx2+dot, pole_bot+dot],
                 fill=(*GOLD, 255))

    # ── "SF" wordmark (clean geometric, readable at medium sizes) ─────────
    label_y  = int(size * 0.815)
    ch_h     = int(size * 0.105)
    ch_w     = int(size * 0.085)
    gap      = int(size * 0.028)
    sw       = max(3, size // 100)
    total_w  = ch_w * 2 + gap
    lx       = (size - total_w) // 2

    _draw_S(draw, lx,              label_y, ch_w, ch_h, sw, GOLD)
    _draw_F(draw, lx + ch_w + gap, label_y, ch_w, ch_h, sw, WHITE)

    return img


def _draw_S(draw, x, y, w, h, sw, col):
    c = (*col, 255)
    b = sw
    m = h // 2
    # top bar
    draw.rectangle([x,      y,         x+w,    y+b],       fill=c)
    # mid bar
    draw.rectangle([x,      y+m-b//2,  x+w,    y+m+b//2],  fill=c)
    # bot bar
    draw.rectangle([x,      y+h-b,     x+w,    y+h],       fill=c)
    # top-left vertical
    draw.rectangle([x,      y,         x+b,    y+m],        fill=c)
    # bot-right vertical
    draw.rectangle([x+w-b,  y+m,       x+w,    y+h],       fill=c)


def _draw_F(draw, x, y, w, h, sw, col):
    c  = (*col, 255)
    b  = sw
    m  = int(h * 0.48)
    mw = int(w * 0.72)
    # vertical spine (full height)
    draw.rectangle([x,   y,       x+b,   y+h],      fill=c)
    # top bar (full width)
    draw.rectangle([x,   y,       x+w,   y+b],      fill=c)
    # mid bar (shorter)
    draw.rectangle([x,   y+m-b//2, x+mw, y+m+b//2], fill=c)


def build_iconset(base: Image.Image):
    os.makedirs(ICONSET, exist_ok=True)
    for s in [16, 32, 64, 128, 256, 512, 1024]:
        base.resize((s, s),   Image.LANCZOS).save(
            os.path.join(ICONSET, f"icon_{s}x{s}.png"))
        if s <= 512:
            base.resize((s*2, s*2), Image.LANCZOS).save(
                os.path.join(ICONSET, f"icon_{s}x{s}@2x.png"))


def main():
    print("Generating 1024×1024 icon…")
    img = make_base(1024)
    img.save(OUT_PNG)
    print(f"  → {OUT_PNG}")

    print("Building iconset…")
    build_iconset(img)

    print("Converting to .icns via iconutil…")
    subprocess.run(["iconutil", "-c", "icns", ICONSET, "-o", OUT_ICNS], check=True)
    print(f"  → {OUT_ICNS}")

    if os.path.isdir(os.path.dirname(BUNDLE)):
        shutil.copy2(OUT_ICNS, BUNDLE)
        subprocess.run(["touch", "/Applications/SingFross.app"], check=False)
        print(f"  → installed to app bundle")

    # 32×32 PNG for pygame window titlebar
    img.resize((32, 32), Image.LANCZOS).save(
        os.path.join(ROOT, "assets", "icon_32.png"))
    print("Done.")


if __name__ == "__main__":
    main()
