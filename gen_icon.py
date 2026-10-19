import os, math
from PIL import Image, ImageDraw, ImageFont

ROOT = r"C:\Users\Admin\Desktop\YT-Batch-Downloader-Mistu"
A = os.path.join(ROOT, "assets")
os.makedirs(A, exist_ok=True)

CREAM = (242, 237, 228)
INK = (16, 15, 13)
YELLOW = (255, 210, 63)
PINK = (255, 107, 157)
BLUE = (122, 184, 255)
LIME = (156, 242, 77)
WHITE = (255, 255, 255)

ARIBLK = r"C:\Windows\Fonts\ariblk.ttf"

_MASTER = None


def _unit(x, y):
    L = math.hypot(x, y) or 1.0
    return x / L, y / L


def _offset_convex(poly, t):
    """Offset each edge of a convex polygon outward (miter join)."""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    n = len(poly)
    lines = []
    for i in range(n):
        p0, p1 = poly[i], poly[(i + 1) % n]
        ux, uy = _unit(p1[0] - p0[0], p1[1] - p0[1])
        n1 = (uy, -ux)
        mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        if (mx - cx) * n1[0] + (my - cy) * n1[1] < 0:
            n1 = (-n1[0], -n1[1])
        # line: nx*x + ny*y = nx*p0x + ny*p0y + t
        lines.append((n1[0], n1[1], n1[0] * p0[0] + n1[1] * p0[1] + t))
    out = []
    for i in range(n):
        a0, b0, c0 = lines[(i - 1) % n]
        a1, b1, c1 = lines[i]
        det = a0 * b1 - a1 * b0
        x = (c0 * b1 - c1 * b0) / det
        y = (a0 * c1 - a1 * c0) / det
        out.append((x, y))
    return out


def _master() -> Image:
    global _MASTER
    if _MASTER is not None:
        return _MASTER
    S = 4096
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lw = int(S * 0.026)

    pad = int(S * 0.092)
    o = int(S * 0.052)                       # hard shadow offset
    d.rounded_rectangle([pad + o, pad + o, S - pad + o, S - pad + o],
                        radius=int(S * 0.16), fill=INK + (255,))
    d.rounded_rectangle([pad, pad, S - pad, S - pad],
                        radius=int(S * 0.16),
                        fill=CREAM + (255,), outline=INK + (255,), width=lw)

    # three batch bars (the queue)
    bw = int(S * 0.42)
    bx = (S - bw) // 2
    bh = int(S * 0.056)
    gap = int(S * 0.086)
    y1 = int(S * 0.172)
    for k, col in enumerate((PINK, BLUE, LIME)):
        y = y1 + k * gap
        d.rounded_rectangle([bx + int(S * 0.013), y + int(S * 0.016),
                             bx + bw, y + bh + int(S * 0.016)],
                            radius=bh // 2, fill=INK + (255,))
        d.rounded_rectangle([bx, y, bx + bw, y + bh],
                            radius=bh // 2, fill=col + (255,),
                            outline=INK + (255,), width=int(S * 0.013))

    # chunky solid arrow (shaft + head as one ink silhouette — clean at
    # every size, no outline-join artifacts)
    d.rectangle([int(S * 0.400), int(S * 0.435), int(S * 0.600),
                 int(S * 0.610)], fill=INK + (255,))
    d.polygon([(int(S * 0.290), int(S * 0.610)), (int(S * 0.710),
               int(S * 0.610)), (int(S * 0.500), int(S * 0.805))],
              fill=INK + (255,))

    # tray
    ty = int(S * 0.836)
    d.rounded_rectangle([int(S * 0.22), ty, int(S * 0.78),
                         ty + int(S * 0.048)],
                        radius=int(S * 0.024), fill=INK + (255,))

    _MASTER = img
    return img


def icon_art(size: int) -> Image:
    return _master().resize((size, size), Image.LANCZOS)


def save_ico():
    p = os.path.join(A, "icon.ico")
    icon_art(256).save(p, format="ICO", sizes=[(16, 16), (24, 24), (32, 32),
                                               (48, 48), (64, 64),
                                               (128, 128), (256, 256)])
    icon_art(256).save(os.path.join(A, "icon_256.png"))
    icon_art(1024).save(os.path.join(A, "icon.png"))
    print("icon.ico + previews written")


def _fit_font(d, text, px, maxw):
    while px > 12:
        f = ImageFont.truetype(ARIBLK, px)
        bb = d.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= maxw:
            return f
        px = int(px * 0.95)
    return ImageFont.truetype(ARIBLK, 12)


def wizard_bmp(w: int, h: int) -> Image:
    """Left-panel art for the Inno wizard (bitmap, flat cream)."""
    W, H = w * 4, h * 4
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    fw = int(w * 0.020) * 4
    d.rectangle([0, 0, W - 1, H - 1], outline=INK, width=fw * 2)

    art_w = int(w * 0.66) * 4
    art = icon_art(art_w)
    img.paste(art, ((W - art_w) // 2, int(H * 0.040)), art)

    def block(text, px, ycent, fill):
        avail = int(W * 0.80) - int(w * 0.09) * 4
        f = _fit_font(d, text, px, avail)
        bb = d.textbbox((0, 0), text, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        pad_x = int(w * 0.050) * 4
        pad_y = int(w * 0.026) * 4
        x0 = (W - (tw + pad_x * 2)) // 2
        y0 = ycent - (th + pad_y * 2) // 2
        d.rounded_rectangle([x0 + int(w * 0.026) * 4,
                             y0 + int(w * 0.030) * 4,
                             x0 + tw + pad_x * 2 + int(w * 0.026) * 4,
                             y0 + th + pad_y * 2 + int(w * 0.030) * 4],
                            radius=int(w * 0.06) * 4, fill=INK)
        d.rounded_rectangle([x0, y0, x0 + tw + pad_x * 2, y0 + th + pad_y * 2],
                            radius=int(w * 0.06) * 4, fill=fill,
                            outline=INK, width=max(6, int(w * 0.011) * 4))
        d.text((W // 2, ycent), text, font=f, fill=INK, anchor="mm")

    block("MISTUS", int(w * 0.170) * 4, int(H * 0.505), WHITE)
    block("BATCH YT", int(w * 0.118) * 4, int(H * 0.600), YELLOW)
    block("DOWNLOADER", int(w * 0.118) * 4, int(H * 0.692), PINK)

    f_sm = ImageFont.truetype(ARIBLK, int(w * 0.062) * 4)
    d.text((W // 2, int(H * 0.832)), "FREE · FAST · BATCH",
           font=f_sm, fill=INK, anchor="mm")
    return img.resize((w, h), Image.LANCZOS)


def save_wizard():
    wizard_bmp(192, 386).save(os.path.join(A, "wizard_192.bmp"))
    wizard_bmp(164, 314).save(os.path.join(A, "wizard_164.bmp"))
    for (w, h), name in (((32, 32), "wizsmall_32.bmp"),
                         ((55, 58), "wizsmall_55.bmp")):
        m = min(w, h) - 8
        art = icon_art(m)
        canvas = Image.new("RGB", (w, h), CREAM)
        canvas.paste(art, ((w - m) // 2, (h - m) // 2), art)
        canvas.save(os.path.join(A, name))
    wizard_bmp(192, 386).resize((384, 772), Image.LANCZOS).save(
        os.path.join(A, "wizard_preview.png"))
    print("wizard bitmaps written")


save_ico()
save_wizard()
for f in sorted(os.listdir(A)):
    print(f"{f:24s} {os.path.getsize(os.path.join(A, f)) / 1024:8.1f} KB")
