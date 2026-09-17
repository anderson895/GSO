"""Slice left_and_right_leaf.png into two separate corner decorations.

The source is a single 1536x1024 transparent PNG holding one leaf cluster in the
top-left corner and its mirror in the top-right. Each half is cropped to its own
alpha bounds (ignoring the faint dust specks) and written to the Django static
image folder so the templates can position them independently.
"""
from PIL import Image

SRC = r"D:\Downloads\JanHeart Marasigan\NEWGSO\NewDeansUI\left_and_right_leaf.png"
OUT_DIR = r"D:\Downloads\JanHeart Marasigan\NEWGSO\GSOSYSTEM - Jul 25\records\static\images"

# Specks below this alpha are compression noise, not part of the artwork.
ALPHA_FLOOR = 40


def dense_bbox(alpha, box):
    """Bounding box of pixels inside `box` whose alpha clears ALPHA_FLOOR."""
    region = alpha.crop(box)
    mask = region.point(lambda a: 255 if a >= ALPHA_FLOOR else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise SystemExit(f"no opaque pixels found in {box}")
    left, upper, right, lower = bbox
    return (box[0] + left, box[1] + upper, box[0] + right, box[1] + lower)


def main():
    src = Image.open(SRC).convert("RGBA")
    width, height = src.size
    alpha = src.getchannel("A")

    halves = {
        "leaf-corner-left.png": (0, 0, width // 2, height),
        "leaf-corner-right.png": (width // 2, 0, width, height),
    }

    for name, box in halves.items():
        crop = dense_bbox(alpha, box)
        piece = src.crop(crop)
        out = f"{OUT_DIR}\\{name}"
        piece.save(out, optimize=True)
        print(f"{name}: crop={crop} size={piece.size}")


if __name__ == "__main__":
    main()
