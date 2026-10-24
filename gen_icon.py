import os, math
from PIL import Image, ImageDraw, ImageFont

ROOT = r"C:\Users\Admin\Desktop\YT-Batch-Downloader-Mistu"
A = os.path.join(ROOT, "assets")
os.makedirs(A, exist_ok=True)

# Clean, simple modern palette
RED = (230, 33, 23)        # YouTube Red
WHITE = (255, 255, 255)
DARK = (24, 27, 34)
BG_LIGHT = (248, 249, 250)

ARIBLK = r"C:\Windows\Fonts\ariblk.ttf"
SEGOE_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"

_MASTER = None


def _master() -> Image:
    """Generate master 2048x2048 icon: Clean YouTube Red squircle with bold white download arrow."""
    global _MASTER
    if _MASTER is not None:
        return _MASTER

    S = 2048
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 1. Sleek rounded squircle (YouTube Red)
    pad = int(S * 0.06)
    radius = int(S * 0.22)
    d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=radius, fill=RED + (255,))

    # 2. Bold, clean white download arrow
    x_mid = S // 2

    # Vertical shaft
    shaft_w = int(S * 0.14)
    shaft_top = int(S * 0.26)
    shaft_bot = int(S * 0.52)
    d.rectangle([x_mid - shaft_w // 2, shaft_top, x_mid + shaft_w // 2, shaft_bot], fill=WHITE + (255,))

    # Arrow head (triangle pointing down)
    arrow_w = int(S * 0.40)
    arrow_tip_y = int(S * 0.68)
    d.polygon([
        (x_mid - arrow_w // 2, shaft_bot),
        (x_mid + arrow_w // 2, shaft_bot),
        (x_mid, arrow_tip_y)
    ], fill=WHITE + (255,))

    # Bottom tray/bracket
    tray_y = int(S * 0.74)
    tray_h = int(S * 0.08)
    tray_w = int(S * 0.46)
    tray_rad = tray_h // 2
    d.rounded_rectangle([x_mid - tray_w // 2, tray_y, x_mid + tray_w // 2, tray_y + tray_h],
                        radius=tray_rad, fill=WHITE + (255,))

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


def wizard_bmp(w: int, h: int) -> Image:
    """Left-panel art for the Inno wizard (clean modern layout)."""
    W, H = w * 4, h * 4
    img = Image.new("RGB", (W, H), (245, 247, 250))
    d = ImageDraw.Draw(img)

    # Top accent bar
    d.rectangle([0, 0, W, int(H * 0.015)], fill=RED)

    # Clean centered icon
    art_w = int(w * 0.58) * 4
    art = icon_art(art_w)
    img.paste(art, ((W - art_w) // 2, int(H * 0.12)), art)

    # Typography
    font_path = SEGOE_BOLD if os.path.isfile(SEGOE_BOLD) else ARIBLK
    try:
        f_title = ImageFont.truetype(font_path, int(w * 0.09) * 4)
        f_sub = ImageFont.truetype(font_path, int(w * 0.06) * 4)
        f_tag = ImageFont.truetype(font_path, int(w * 0.045) * 4)
    except Exception:
        f_title = f_sub = f_tag = ImageFont.load_default()

    d.text((W // 2, int(H * 0.56)), "MISTUS", font=f_title, fill=DARK, anchor="mm")
    d.text((W // 2, int(H * 0.65)), "BATCH YT", font=f_title, fill=RED, anchor="mm")
    d.text((W // 2, int(H * 0.74)), "DOWNLOADER", font=f_sub, fill=DARK, anchor="mm")

    # Clean badge
    badge_w = int(W * 0.76)
    badge_h = int(H * 0.05)
    badge_y = int(H * 0.86)
    d.rounded_rectangle([(W - badge_w) // 2, badge_y, (W + badge_w) // 2, badge_y + badge_h],
                        radius=badge_h // 2, fill=(235, 238, 242))
    d.text((W // 2, badge_y + badge_h // 2), "FAST • SIMPLE • RELIABLE",
           font=f_tag, fill=(100, 110, 125), anchor="mm")

    return img.resize((w, h), Image.LANCZOS)


def save_wizard():
    wizard_bmp(192, 386).save(os.path.join(A, "wizard_192.bmp"))
    wizard_bmp(164, 314).save(os.path.join(A, "wizard_164.bmp"))
    for (w, h), name in (((32, 32), "wizsmall_32.bmp"),
                         ((55, 58), "wizsmall_55.bmp")):
        m = min(w, h) - 6
        art = icon_art(m)
        canvas = Image.new("RGB", (w, h), (245, 247, 250))
        canvas.paste(art, ((w - m) // 2, (h - m) // 2), art)
        canvas.save(os.path.join(A, name))
    wizard_bmp(192, 386).resize((384, 772), Image.LANCZOS).save(
        os.path.join(A, "wizard_preview.png"))
    print("wizard bitmaps written")


if __name__ == "__main__":
    save_ico()
    save_wizard()
    for f in sorted(os.listdir(A)):
        print(f"{f:24s} {os.path.getsize(os.path.join(A, f)) / 1024:8.1f} KB")
