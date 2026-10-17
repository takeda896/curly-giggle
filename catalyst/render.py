"""Frame renderer: draws one 1920x1080 frame of a scene at time t.

Every scene is a plain dict from script.json; `visual.type` picks the layout.
"""
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 30
FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"

BG = (6, 8, 11)
WHITE = (242, 245, 247)
GRAY = (138, 150, 163)
DIM = (74, 85, 97)
TEAL = (47, 224, 181)
RED = (255, 77, 90)
YELLOW = (255, 210, 63)
ORANGE = (255, 138, 51)
ACCENTS = {"teal": TEAL, "red": RED, "yellow": YELLOW}

FONT_FILES = {
    "head": "oswald-latin-700-normal.woff",
    "head5": "oswald-latin-500-normal.woff",
    "head4": "oswald-latin-400-normal.woff",
    "body": "Inter-Regular.otf",
    "semi": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "xbold": "Inter-ExtraBold.otf",
}


@lru_cache(maxsize=None)
def font(kind, size):
    return ImageFont.truetype(str(FONTS / FONT_FILES[kind]), size)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def appear(t, delay, dur=0.55):
    return ease((t - delay) / dur)


def rgba(c, a):
    return (c[0], c[1], c[2], int(255 * clamp(a)))


def mix(c1, c2, k):
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


# ---------------------------------------------------------------- background

@lru_cache(maxsize=16)
def background(seed, accent):
    """Oversized dark background with a soft glow and a faint grid; frames crop a drifting window."""
    rnd = random.Random(seed)
    bw, bh = W + 240, H + 140
    img = Image.new("RGB", (bw, bh), BG)
    glow = Image.new("RGB", (bw // 8, bh // 8), BG)
    gd = ImageDraw.Draw(glow)
    for _ in range(2):
        cx, cy = rnd.uniform(0.15, 0.85) * glow.width, rnd.uniform(0.2, 0.8) * glow.height
        r = rnd.uniform(0.25, 0.4) * glow.width
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=mix(BG, accent, 0.16))
    glow = glow.filter(ImageFilter.GaussianBlur(14)).resize((bw, bh), Image.BICUBIC)
    img = Image.blend(img, glow, 1.0)
    grid = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(grid)
    for x in range(0, bw, 80):
        d.line([(x, 0), (x, bh)], fill=(255, 255, 255, 9))
    for y in range(0, bh, 80):
        d.line([(0, y), (bw, y)], fill=(255, 255, 255, 9))
    for _ in range(90):
        x, y = rnd.uniform(0, bw), rnd.uniform(0, bh)
        r = rnd.uniform(1, 2.4)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*accent, rnd.randint(25, 70)))
    img = Image.alpha_composite(img.convert("RGBA"), grid)
    # vignette
    vig = Image.new("L", (bw // 8, bh // 8), 0)
    ImageDraw.Draw(vig).ellipse([-vig.width * 0.15, -vig.height * 0.25, vig.width * 1.15, vig.height * 1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(20)).resize((bw, bh), Image.BICUBIC)
    dark = Image.new("RGBA", (bw, bh), (*BG, 255))
    return Image.composite(img, dark, vig).convert("RGB")


def bg_frame(seed, accent, t):
    img = background(seed, accent)
    dx = 120 + 100 * math.sin(t * 0.05 + seed)
    dy = 70 + 55 * math.cos(t * 0.04 + seed * 0.7)
    return img.crop((int(dx), int(dy), int(dx) + W, int(dy) + H))


# ---------------------------------------------------------------- text helpers

def rich_parts(text):
    """'FOR *MICROSOFT.*' -> [('FOR ', False), ('MICROSOFT.', True)]"""
    out, hot = [], False
    for i, seg in enumerate(text.split("*")):
        if seg:
            out.append((seg, hot))
        hot = not hot
    return out


def text_width(text, f, spacing=0):
    return sum(f.getlength(s) for s, _ in rich_parts(text)) + spacing * max(len(text.replace("*", "")) - 1, 0)


def draw_rich(d, xy, text, f, color, accent, alpha, anchor="m", spacing=0):
    """Draw text with *accent* segments. anchor: l/m/r horizontally; y is the text top."""
    x, y = xy
    w = text_width(text, f, spacing)
    if anchor == "m":
        x -= w / 2
    elif anchor == "r":
        x -= w
    for seg, hot in rich_parts(text):
        c = accent if hot else color
        if spacing:
            for ch in seg:
                d.text((x, y), ch, font=f, fill=rgba(c, alpha))
                x += f.getlength(ch) + spacing
        else:
            d.text((x, y), seg, font=f, fill=rgba(c, alpha))
            x += f.getlength(seg)
    return w


def fit(kind, size, texts, maxw, spacing=0):
    """Largest font (<= size) at which every line fits in maxw."""
    while size > 20 and max(text_width(tx, font(kind, size), spacing) for tx in texts) > maxw:
        size -= 4
    return font(kind, size)


def wrap(text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        trial = (cur + " " + w_).strip()
        if f.getlength(trial) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- icons

def icon(d, kind, cx, cy, s, p, t, accent):
    """Simple vector icons. p = entrance progress (0..1), t = scene time for idle motion."""
    a = p
    s = s * (0.85 + 0.15 * p)
    if kind == "tower":
        top, bot = cy - s * 0.42, cy + s * 0.5
        pts_l, pts_r = [], []
        for i in range(21):
            k = i / 20
            y = top + (bot - top) * k
            half = s * (0.2 + 0.16 * ((k - 0.62) / 0.62) ** 2)
            pts_l.append((cx - half, y))
            pts_r.append((cx + half, y))
        poly = pts_l + pts_r[::-1]
        d.polygon(poly, fill=rgba((28, 34, 42), a), outline=rgba(accent, a))
        d.line(pts_l, fill=rgba(accent, a), width=5)
        d.line(pts_r, fill=rgba(accent, a), width=5)
        d.line([pts_l[0], pts_r[0]], fill=rgba(accent, a), width=5)
        d.line([(cx - s * 0.62, bot), (cx + s * 0.62, bot)], fill=rgba(accent, a), width=5)
        for i in range(5):
            ph = (t * 0.35 + i / 5) % 1
            r = s * (0.08 + 0.14 * ph)
            x = cx + s * 0.06 * math.sin(i * 2.1) + s * 0.25 * ph
            y = top - s * 0.06 - s * 0.55 * ph
            d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(GRAY, a * 0.45 * (1 - ph)))
    elif kind == "bolt":
        pts = [(0.12, -0.5), (-0.28, 0.06), (-0.02, 0.06), (-0.14, 0.5), (0.3, -0.1), (0.04, -0.1), (0.16, -0.5)]
        pulse = 1 + 0.03 * math.sin(t * 3)
        poly = [(cx + x * s * pulse, cy + y * s * pulse) for x, y in pts]
        d.polygon(poly, fill=rgba(YELLOW, a), outline=rgba(WHITE, a))
    elif kind == "chip":
        r = s * 0.3
        for i in range(6):
            o = -r + (i + 0.5) * (2 * r / 6)
            for x1, y1, x2, y2 in [(cx + o, cy - r, cx + o, cy - r - s * 0.1), (cx + o, cy + r, cx + o, cy + r + s * 0.1),
                                   (cx - r, cy + o, cx - r - s * 0.1, cy + o), (cx + r, cy + o, cx + r + s * 0.1, cy + o)]:
                d.line([(x1, y1), (x2, y2)], fill=rgba(accent, a), width=6)
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=s * 0.05, fill=rgba((24, 30, 38), a), outline=rgba(accent, a), width=6)
        ir = r * 0.55
        glow = 0.5 + 0.5 * math.sin(t * 2.5)
        d.rounded_rectangle([cx - ir, cy - ir, cx + ir, cy + ir], radius=s * 0.03, fill=rgba(mix((24, 30, 38), accent, 0.25 + 0.2 * glow), a))
        f = font("head", int(s * 0.2))
        d.text((cx, cy), "AI", font=f, fill=rgba(WHITE, a), anchor="mm")
    elif kind == "drop":
        r = s * 0.28
        oy = cy + s * 0.1
        d.ellipse([cx - r, oy - r, cx + r, oy + r], fill=rgba((40, 150, 230), a))
        d.polygon([(cx - r * 0.97, oy - r * 0.25), (cx, cy - s * 0.48), (cx + r * 0.97, oy - r * 0.25)], fill=rgba((40, 150, 230), a))
        d.ellipse([cx - r * 0.55, oy - r * 0.45, cx - r * 0.25, oy - r * 0.05], fill=rgba(WHITE, a * 0.6))
    elif kind == "flame":
        fl = 1 + 0.06 * math.sin(t * 9) + 0.04 * math.sin(t * 13.7)

        def flame(scale, col):
            pts = []
            for i in range(41):
                k = i / 40 * 2 * math.pi
                x = math.sin(k) * 0.3
                y = -math.cos(k)
                y = y * 0.5 if y > 0 else y * 0.5 * (1 + 0.9 * fl * (1 - abs(math.sin(k))) ** 0.5)
                x *= (1 - max(0, -y) * 0.6)
                pts.append((cx + x * s * scale, cy + 0.15 * s + y * s * scale * 0.9))
            d.polygon(pts, fill=rgba(col, a))
        flame(1.0, ORANGE)
        flame(0.62, YELLOW)
        flame(0.3, WHITE)
    elif kind == "house":
        w2 = s * 0.34
        base, roof = cy + s * 0.4, cy - s * 0.05
        d.polygon([(cx - w2 * 1.25, roof), (cx, cy - s * 0.45), (cx + w2 * 1.25, roof)], fill=rgba(accent, a))
        d.rectangle([cx - w2, roof, cx + w2, base], fill=rgba((28, 34, 42), a), outline=rgba(accent, a), width=6)
        on = 0.6 + 0.4 * math.sin(t * 2)
        d.rectangle([cx - w2 * 0.6, roof + s * 0.1, cx - w2 * 0.15, roof + s * 0.26], fill=rgba(mix(DIM, YELLOW, on), a))
        d.rectangle([cx + w2 * 0.15, roof + s * 0.1, cx + w2 * 0.6, roof + s * 0.26], fill=rgba(mix(DIM, YELLOW, on), a))
        d.rectangle([cx - w2 * 0.18, base - s * 0.2, cx + w2 * 0.18, base], fill=rgba(DIM, a))


def glow_layer(layer, box, radius=24, strength=0.7):
    """Add a blurred copy behind the pixels inside box (cheap: blurs only that crop)."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    crop = layer.crop((x0, y0, x1, y1))
    small = crop.resize((max(crop.width // 4, 1), max(crop.height // 4, 1)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(radius / 4)).resize(crop.size, Image.BILINEAR)
    r, g, b, al = small.split()
    al = al.point(lambda v: int(v * strength))
    small = Image.merge("RGBA", (r, g, b, al))
    base = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    base.paste(small, (x0, y0))
    return Image.alpha_composite(base, layer)


# ---------------------------------------------------------------- layouts

def stagger(i, n, dur, start=0.15, span=0.55):
    step = min(0.9, dur * span / max(n, 1))
    return start + i * step


def lay_title(d, v, t, dur, acc):
    lines = v["lines"]
    y0 = 540 - len(lines) * 85 - 40
    draw_rich(d, (W / 2, y0), v.get("kicker", ""), font("bold", 32), acc, acc, appear(t, 0.1), spacing=6)
    for i, line in enumerate(lines):
        p = appear(t, 0.3 + i * 0.35, 0.7)
        draw_rich(d, (W / 2, y0 + 70 + i * 175 + 30 * (1 - p)), line, fit("head", 160, lines, W - 240), WHITE, acc, p)
    p = appear(t, 0.9, 0.8)
    lw = 360 * p
    d.rectangle([W / 2 - lw / 2, y0 + 70 + len(lines) * 175 + 40, W / 2 + lw / 2, y0 + 70 + len(lines) * 175 + 46], fill=rgba(acc, p))


def lay_card(d, v, t, dur, acc):
    p0 = appear(t, 0.05)
    draw_rich(d, (W / 2, 400), v["num"], font("bold", 36), acc, acc, p0, spacing=10)
    p = appear(t, 0.25, 0.7)
    draw_rich(d, (W / 2, 455 + 30 * (1 - p)), v["title"], fit("head", 140, [v["title"]], W - 240), WHITE, acc, p)
    lw = 520 * appear(t, 0.5, 0.9)
    d.rectangle([W / 2 - lw / 2, 650, W / 2 + lw / 2, 656], fill=rgba(acc, p))


def lay_text(d, v, t, dur, acc):
    lines = v["lines"]
    f = fit("head", 112, lines, W - 240)
    y0 = 520 - len(lines) * 70 - 30
    draw_rich(d, (W / 2, y0 - 70), v.get("kicker", ""), font("bold", 32), acc, acc, appear(t, 0.05), spacing=6)
    for i, line in enumerate(lines):
        p = appear(t, stagger(i, len(lines), dur), 0.6)
        draw_rich(d, (W / 2, y0 + i * 140 + 24 * (1 - p)), line, f, WHITE, acc, p)


def lay_icon(d, v, t, dur, acc, layer_boxes):
    cx, cy, s = 560, 470, 420
    p = appear(t, 0.05, 0.8)
    icon(d, v["icon"], cx, cy, s, p, t, acc)
    layer_boxes.append((cx - s * 0.8, cy - s * 0.9, cx + s * 0.8, cy + s * 0.8))
    x = 900
    heads = v["headline"]
    draw_rich(d, (x, 300), v.get("kicker", ""), font("bold", 32), acc, acc, appear(t, 0.2), anchor="l", spacing=6)
    f = fit("head", 116, heads, W - x - 100)
    for i, line in enumerate(heads):
        pi = appear(t, 0.4 + i * 0.4, 0.6)
        draw_rich(d, (x - 30 * (1 - pi), 360 + i * (f.size + 20)), line, f, WHITE, acc, pi, anchor="l")


def fmt_num(x, decimals):
    return f"{x:,.{decimals}f}"


def lay_stat(d, v, t, dur, acc, layer_boxes):
    has_icon = "icon" in v
    cx = 1110 if has_icon else W / 2
    if has_icon:
        pi = appear(t, 0.05, 0.8)
        icon(d, v["icon"], 470, 450, 340, pi, t, acc)
        layer_boxes.append((470 - 280, 450 - 300, 470 + 280, 450 + 280))
    k = ease(clamp((t - 0.2) / 1.3))
    dec = v.get("decimals", 0 if float(v["value"]).is_integer() else 1)
    txt = v.get("prefix", "") + fmt_num(v["value"] * k, dec) + v.get("suffix", "")
    p = appear(t, 0.1)
    f = fit("head", 250, [v.get("prefix", "") + fmt_num(v["value"], dec) + v.get("suffix", "")], 1200 if has_icon else 1700)
    d.text((cx, 470), txt, font=f, fill=rgba(acc, p), anchor="ms")
    lf = font("bold", 34)
    for i, line in enumerate(wrap(v["label"], lf, 1000 if has_icon else 1500)):
        draw_rich(d, (cx, 520 + i * 48), line, lf, WHITE, acc, appear(t, 0.5), spacing=2)
    if v.get("sub"):
        draw_rich(d, (cx, 640), v["sub"], font("body", 36), GRAY, acc, appear(t, 0.9))


def lay_bars(d, v, t, dur, acc):
    bars = v["bars"]
    n = len(bars)
    draw_rich(d, (W / 2, 150), v["title"], font("bold", 34), WHITE, acc, appear(t, 0.05), spacing=4)
    base, maxh = 790, 440
    left, right = 300, 1620
    slot = (right - left) / n
    bw = min(260, slot * 0.55)
    vmax = max(b.get("hi", b["value"]) for b in bars)
    d.line([(left - 40, base), (right + 40, base)], fill=rgba(DIM, appear(t, 0.05)), width=3)
    for i, b in enumerate(bars):
        delay = stagger(i, n, dur, 0.3, 0.45)
        g = ease(clamp((t - delay) / 1.0))
        col = DIM if b.get("color") == "muted" else ACCENTS.get(b.get("color", ""), acc)
        cx = left + slot * (i + 0.5)
        h = maxh * b["value"] / vmax * g
        if "hi" in b:
            hh = maxh * b["hi"] / vmax * g
            d.rectangle([cx - bw / 2, base - hh, cx + bw / 2, base], fill=rgba(col, 0.28 * g), outline=rgba(col, 0.8 * g), width=3)
            top = base - hh
        else:
            top = base - h
        d.rectangle([cx - bw / 2, base - h, cx + bw / 2, base], fill=rgba(col, g))
        lab_p = appear(t, delay + 0.6)
        d.text((cx, top - 22), b["display"], font=font("head", 76), fill=rgba(WHITE, lab_p), anchor="ms")
        d.text((cx, base + 52), b["label"], font=font("bold", 30), fill=rgba(GRAY, appear(t, delay)), anchor="ms")
        if b.get("note"):
            nf = font("bold", 26)
            tw = nf.getlength(b["note"])
            nx, ny = cx + bw / 2 + 24, top + 34
            pn = appear(t, delay + 0.9)
            d.rounded_rectangle([nx, ny - 22, nx + tw + 36, ny + 22], radius=22, fill=rgba(mix(BG, col, 0.35), pn), outline=rgba(col, pn), width=2)
            d.text((nx + 18 + tw / 2, ny), b["note"], font=nf, fill=rgba(WHITE, pn), anchor="mm")


def lay_list(d, v, t, dur, acc):
    items = v["items"]
    draw_rich(d, (W / 2, 190), v["title"], font("head", 84), WHITE, acc, appear(t, 0.05))
    y0 = 360
    for i, item in enumerate(items):
        p = appear(t, stagger(i, len(items), dur, 0.5, 0.7), 0.6)
        head, _, tail = item.partition("·")
        x = 420 - 40 * (1 - p)
        y = y0 + i * 150
        if v.get("numbered"):
            d.ellipse([x - 40, y - 4, x + 40, y + 76], fill=rgba(acc, p))
            d.text((x, y + 36), str(i + 1), font=font("head", 52), fill=rgba(BG, p), anchor="mm")
        else:
            d.rectangle([x - 8, y, x, y + 72], fill=rgba(acc, p))
        d.text((x + 70, y - 6), head.strip(), font=font("head", 64), fill=rgba(WHITE, p))
        if tail:
            d.text((x + 72, y + 74), tail.strip(), font=font("body", 32), fill=rgba(GRAY, p))


def lay_timeline(d, v, t, dur, acc):
    ev = v["events"]
    n = len(ev)
    draw_rich(d, (W / 2, 170), v["title"], font("head", 84), WHITE, acc, appear(t, 0.05))
    y = 520
    left, right = 260, 1660
    total = ease(clamp((t - 0.3) / max(dur * 0.7, 1)))
    d.line([(left, y), (left + (right - left) * total, y)], fill=rgba(acc, 1), width=6)
    for i, e in enumerate(ev):
        x = left + (right - left) * i / max(n - 1, 1)
        p = appear(t, 0.3 + max(dur * 0.7, 1) * i / max(n - 1, 1) - 0.2, 0.5)
        r = 16 + 4 * p
        d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(acc, p), outline=rgba(WHITE, p), width=3)
        d.text((x, y - 50), e["date"], font=font("head", 60), fill=rgba(acc, p), anchor="ms")
        for j, line in enumerate(wrap(e["text"], font("semi", 30), 320)):
            d.text((x, y + 60 + j * 40), line, font=font("semi", 30), fill=rgba(WHITE, p), anchor="mt")


def lay_versus(d, v, t, dur, acc):
    for i, side in enumerate([v["left"], v["right"]]):
        p = appear(t, 0.2 + i * 1.2, 0.6)
        cx = 520 if i == 0 else 1400
        col = acc if i == 0 else YELLOW
        d.rounded_rectangle([cx - 340, 280, cx + 340, 720], radius=24, fill=rgba((16, 21, 27), p * 0.9), outline=rgba(col, p), width=3)
        d.text((cx, 360), side["title"], font=fit("head", 64, [side["title"]], 620), fill=rgba(col, p), anchor="mm")
        for j, line in enumerate(wrap(side["text"], font("semi", 40), 580)):
            d.text((cx, 460 + j * 56), line, font=font("semi", 40), fill=rgba(WHITE, p), anchor="mt")
    p = appear(t, 0.8)
    d.text((W / 2, 500), "VS", font=font("head", 90), fill=rgba(GRAY, p), anchor="mm")


LAYOUTS = {"title": lay_title, "card": lay_card, "text": lay_text, "bars": lay_bars,
           "list": lay_list, "timeline": lay_timeline, "versus": lay_versus}


# ---------------------------------------------------------------- frame

def caption_at(captions, t):
    for s, e, txt in captions:
        if s <= t < e:
            return txt
    return None


def draw_caption(d, txt, cx, y, f, maxw):
    lines = wrap(txt, f, maxw)
    lh = f.size * 1.3
    tw = max(f.getlength(l) for l in lines)
    top = y - lh * len(lines)
    d.rounded_rectangle([cx - tw / 2 - 26, top - 14, cx + tw / 2 + 26, y + 10], radius=14, fill=(0, 0, 0, 165))
    for i, l in enumerate(lines):
        d.text((cx, top + i * lh), l, font=f, fill=(*WHITE, 255), anchor="mt")


def render_frame(scene, t, dur, seed, chapter_label, captions=None, with_captions=True):
    v = scene["visual"]
    acc = ACCENTS.get(v.get("accent", "teal"), TEAL)
    frame = bg_frame(seed, acc, t + seed * 10).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    boxes = []
    kind = v["type"]
    if kind == "icon":
        lay_icon(d, v, t, dur, acc, boxes)
    elif kind == "stat":
        lay_stat(d, v, t, dur, acc, boxes)
    else:
        LAYOUTS[kind](d, v, t, dur, acc)
    for b in boxes:
        layer = glow_layer(layer, b, radius=40, strength=0.55)
    out = 1 - ease((t - (dur - 0.3)) / 0.3) if t > dur - 0.3 else 1.0
    if out < 1:
        al = layer.getchannel("A").point(lambda a: int(a * out))
        layer.putalpha(al)
    frame = Image.alpha_composite(frame, layer)
    hud = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hud)
    if chapter_label and kind != "card":
        hd.rectangle([80, 66, 86, 96], fill=(*acc, 255))
        hd.text((102, 64), chapter_label.upper(), font=font("semi", 26), fill=(*GRAY, 255))
    hd.text((W - 80, 64), "THE CATALYST", font=font("head5", 28), fill=(*GRAY, 200), anchor="ra")
    if v.get("source"):
        hd.text((80, 868), "Source: " + v["source"], font=font("body", 24), fill=(*GRAY, 210))
    if with_captions and captions:
        txt = caption_at(captions, t)
        if txt:
            draw_caption(hd, txt, W / 2, 1010, font("bold", 42), 1500)
    frame = Image.alpha_composite(frame, hud)
    return frame.convert("RGB")
