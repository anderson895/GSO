"""Build the eLib building backdrop that fills the bottom-left of the login scene.

The photo is used near full colour rather than as a pale watermark, so it needs
a soft right edge to melt into the white page. Only that edge is baked in: the
templates crop the frame with object-fit, which would eat a baked top fade, so
the top is faded in CSS instead.

The photo is also mirrored -- the unflipped building faces off the left edge of
the page instead of into the content.
"""
from PIL import Image, ImageChops, ImageOps

SRC = r"D:\Downloads\JanHeart Marasigan\NEWGSO\buLSU ELIB.png"
OUT = (
    r"D:\Downloads\JanHeart Marasigan\NEWGSO\GSOSYSTEM - Jul 25"
    r"\records\static\images\elib-building.png"
)

# How much of the original colour survives (1.0 = untouched, 0 = white).
COLOUR_KEEP = 0.90

# Fraction of the frame the right-edge fade spans.
RIGHT_FADE = 0.22


def right_fade(size):
    """Alpha multiplier mask: opaque until RIGHT_FADE, then ramping to zero."""
    width, height = size
    start = int(width * (1 - RIGHT_FADE))
    span = max(1, width - start)

    row = [255 if x < start else int(255 * (1 - (x - start) / span)) for x in range(width)]
    mask = Image.new("L", size)
    mask.putdata(row * height)
    return mask


def main():
    src = ImageOps.mirror(Image.open(SRC).convert("RGBA"))

    white = Image.new("RGB", src.size, (255, 255, 255))
    softened = Image.blend(white, src.convert("RGB"), COLOUR_KEEP)

    # Trim the transparent sky first so the fade is measured off the artwork.
    alpha = src.getchannel("A")
    box = alpha.getbbox()
    softened = softened.crop(box)
    alpha = alpha.crop(box)

    alpha = ImageChops.multiply(alpha, right_fade(alpha.size))
    softened.putalpha(alpha)

    softened.save(OUT, optimize=True)
    print("wrote", OUT, softened.size)


if __name__ == "__main__":
    main()
