"""Generate deterministic PNG/ICO assets for the packaged application."""

from pathlib import Path
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

size = 512
image = Image.new("RGBA", (size, size), (7, 13, 22, 255))
draw = ImageDraw.Draw(image)

# Cyan aura rings.
for width, inset, alpha in ((18, 40, 255), (7, 77, 155), (4, 105, 90)):
    color = (48, 218, 248, alpha)
    draw.ellipse((inset, inset, size - inset, size - inset), outline=color, width=width)

# Original hunter mark: compass chevron + energy core.
cyan = (53, 222, 248, 255)
white = (231, 241, 247, 255)
navy = (12, 29, 43, 255)
draw.polygon([(256, 80), (385, 243), (318, 222), (256, 145), (194, 222), (127, 243)], fill=cyan)
draw.polygon([(256, 432), (127, 269), (194, 290), (256, 367), (318, 290), (385, 269)], fill=white)
draw.ellipse((204, 204, 308, 308), fill=navy, outline=white, width=12)
draw.ellipse((230, 230, 282, 282), fill=cyan)

png = ASSETS / "hunter_duel_icon.png"
ico = ASSETS / "hunter_duel.ico"
image.save(png)
image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(png)
print(ico)

