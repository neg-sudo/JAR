"""Generate the JAR application icon (run from the repository root).

Requires Pillow, which is also an optional GUI dependency.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "jar" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)


def font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_icon(size: int = 512) -> Image.Image:
    scale = size / 512.0
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(values):
        return tuple(int(v * scale) for v in values)

    # Rounded dark background.
    draw.rounded_rectangle(box((8, 8, 504, 504)), radius=int(96 * scale), fill=(11, 18, 32, 255))

    # Jar body with a soft glass look.
    draw.rounded_rectangle(box((150, 178, 362, 436)), radius=int(34 * scale), fill=(226, 232, 240, 255))
    draw.rounded_rectangle(box((162, 190, 350, 424)), radius=int(26 * scale), fill=(203, 213, 225, 255))

    # Lid.
    draw.rounded_rectangle(box((168, 126, 344, 184)), radius=int(18 * scale), fill=(34, 197, 94, 255))
    draw.rounded_rectangle(box((186, 138, 326, 156)), radius=int(8 * scale), fill=(134, 239, 172, 255))

    # Label.
    draw.rounded_rectangle(box((178, 256, 334, 374)), radius=int(18 * scale), fill=(15, 23, 42, 255))
    label_font = font(int(74 * scale))
    text = "JAR"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=label_font)
    text_width = right - left
    text_height = bottom - top
    draw.text(
        ((size - text_width) / 2 - left, (256 + 374) / 2 * scale - text_height / 2 - top),
        text,
        font=label_font,
        fill=(74, 222, 128, 255),
    )

    # Highlight streak.
    draw.rounded_rectangle(box((176, 200, 194, 400)), radius=int(9 * scale), fill=(248, 250, 252, 150))
    return image


def main() -> None:
    icon = draw_icon(512)
    icon.save(ASSETS / "jar.png")
    icon.resize((256, 256), Image.LANCZOS).save(ASSETS / "jar-256.png")
    icon.resize((64, 64), Image.LANCZOS).save(ASSETS / "jar-tray.png")
    icon.save(
        ASSETS / "jar.ico",
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Wrote icons to {ASSETS}")


if __name__ == "__main__":
    main()
