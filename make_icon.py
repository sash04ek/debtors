"""Рисует иконку приложения (дом + монета с ₽) и собирает assets/icon.png, icon.icns, icon.ico."""
import subprocess
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "assets"
S = 2048  # рисуем крупно, потом уменьшаем — гладкие края


def gradient(size, top, bottom):
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return g.resize((size, size))


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # фон: скруглённый квадрат с градиентом
    bg = gradient(S, (38, 70, 130), (14, 30, 68)).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    m = int(S * 0.06)
    ImageDraw.Draw(mask).rounded_rectangle((m, m, S - m, S - m), radius=int(S * 0.225), fill=255)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)

    blue = (38, 70, 130, 255)
    white = (255, 255, 255, 255)

    # дом (слева), монета перекрывает его правый нижний угол
    cx, base = S * 0.40, S * 0.75
    w, wall_top = S * 0.46, S * 0.44
    x0, x1 = cx - w / 2, cx + w / 2
    d.rectangle((x0 + S * 0.03, wall_top, x1 - S * 0.03, base), fill=white)
    d.polygon([(cx, S * 0.15), (x1 + S * 0.05, wall_top + S * 0.02), (x0 - S * 0.05, wall_top + S * 0.02)], fill=white)
    d.rectangle((x1 - S * 0.14, S * 0.22, x1 - S * 0.07, S * 0.36), fill=white)          # труба
    d.rounded_rectangle((cx - S * 0.05, base - S * 0.21, cx + S * 0.09, base), radius=int(S * 0.02), fill=blue)  # дверь
    d.rectangle((x0 + S * 0.07, wall_top + S * 0.08, x0 + S * 0.17, wall_top + S * 0.18), fill=blue)             # окно

    # монета с ₽ справа внизу
    r = S * 0.20
    ccx, ccy = S * 0.71, S * 0.70
    d.ellipse((ccx - r - S * 0.022, ccy - r - S * 0.022, ccx + r + S * 0.022, ccy + r + S * 0.022), fill=(14, 30, 68, 255))
    d.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), fill=(245, 166, 35, 255))
    d.ellipse((ccx - r * 0.82, ccy - r * 0.82, ccx + r * 0.82, ccy + r * 0.82), outline=(255, 214, 120, 255), width=int(S * 0.010))
    # знак рубля рисуем фигурами (в шрифтах он может отсутствовать)
    ink = (90, 50, 0, 255)
    u = r
    d.rounded_rectangle((ccx - 0.32 * u, ccy - 0.60 * u, ccx + 0.44 * u, ccy + 0.20 * u), radius=int(0.40 * u), outline=ink, width=int(0.17 * u))
    d.rectangle((ccx - 0.32 * u, ccy - 0.60 * u, ccx - 0.15 * u, ccy + 0.62 * u), fill=ink)      # ножка
    d.rectangle((ccx - 0.48 * u, ccy + 0.16 * u, ccx + 0.26 * u, ccy + 0.32 * u), fill=ink)      # перекладина
    return img.resize((1024, 1024), Image.LANCZOS)


def draw_gear(size: int = 96, color=(128, 134, 145, 255)) -> Image.Image:
    """Шестерёнка для кнопки «Настройки» (прозрачный фон, серый цвет — читается на светлой и тёмной теме)."""
    import math
    k = 8                                   # суперсэмплинг для гладких краёв
    n = size * k
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = n / 2
    r_out, r_in, teeth = n * 0.47, n * 0.36, 8
    pts = []
    for i in range(teeth * 4):               # каждый зуб: 4 точки (подъём, верх, верх, спуск)
        a = 2 * math.pi * i / (teeth * 4) - math.pi / (teeth * 4)
        r = r_out if i % 4 in (1, 2) else r_in
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    d.polygon(pts, fill=color)
    d.ellipse((c - n * 0.38, c - n * 0.38, c + n * 0.38, c + n * 0.38), fill=color)   # тело
    d.ellipse((c - n * 0.17, c - n * 0.17, c + n * 0.17, c + n * 0.17), fill=(0, 0, 0, 0))  # отверстие
    return img.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    icon = draw()
    icon.save(OUT / "icon.png")
    draw_gear(28, (150, 156, 168, 255)).save(OUT / "gear.png")            # обычный
    draw_gear(28, (66, 133, 244, 255)).save(OUT / "gear_hover.png")       # при наведении
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # .icns через iconutil (macOS)
    iconset = OUT / "icon.iconset"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
        icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT / "icon.icns")], check=True)
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


if __name__ == "__main__":
    main()
