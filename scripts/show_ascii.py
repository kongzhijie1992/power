#!/usr/bin/env python3
"""Render a small ASCII preview of an image file to the terminal.

Usage: .venv\Scripts\python scripts\show_ascii.py data/DE/seq_compare.png --width 80
"""
import sys
from pathlib import Path

try:
    from PIL import Image
except Exception:
    Image = None
try:
    import matplotlib.image as mpimg
except Exception:
    mpimg = None

CHARS = " .:-=+*#%@"


def ascii_preview(path, width=80):
    if Image is not None:
        img = Image.open(path).convert("L")
        w, h = img.size
        aspect = h / w
        new_w = int(width)
        new_h = max(2, int(aspect * new_w * 0.5))
        img = img.resize((new_w, new_h))
        pixels = list(img.getdata())
    elif mpimg is not None:
        # Read image via matplotlib and downsample using numpy (no Pillow required)
        import numpy as _np

        arr = mpimg.imread(str(path))
        if arr.ndim == 3:
            # convert RGB(A) to grayscale luminance
            arr = arr[..., :3].mean(axis=2)
        # arr is now 2D
        h, w = arr.shape
        aspect = h / w
        new_w = int(width)
        new_h = max(2, int(aspect * new_w * 0.5))

        # block-average downsample if blocks are >=1
        block_h = max(1, h // new_h)
        block_w = max(1, w // new_w)
        if block_h > 1 and block_w > 1:
            hh = (h // block_h) * block_h
            ww = (w // block_w) * block_w
            arr_cropped = arr[:hh, :ww]
            arr_blocks = arr_cropped.reshape((new_h, block_h, new_w, block_w))
            arr_small = arr_blocks.mean(axis=(1, 3))
        else:
            ys = _np.round(_np.linspace(0, h - 1, new_h)).astype(int)
            xs = _np.round(_np.linspace(0, w - 1, new_w)).astype(int)
            arr_small = arr[ys[:, None], xs[None, :]]

        # normalize to 0-255
        amin = float(arr_small.min())
        amax = float(arr_small.max())
        if amax - amin > 0:
            norm = (arr_small - amin) / (amax - amin)
        else:
            norm = arr_small * 0.0
        pixels = (norm * 255).astype(int).flatten().tolist()
    else:
        print("Neither Pillow nor matplotlib available; cannot render ASCII preview.")
        return 1

    lines = []
    for y in range(new_h):
        row = pixels[y * new_w : (y + 1) * new_w]
        line = "".join(CHARS[int(px / 255 * (len(CHARS) - 1))] for px in row)
        lines.append(line)
    print("\n".join(lines))
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: show_ascii.py <image> [--width N]")
        raise SystemExit(2)
    path = Path(sys.argv[1])
    width = 80
    if "--width" in sys.argv:
        try:
            width = int(sys.argv[sys.argv.index("--width") + 1])
        except Exception:
            pass
    if not path.exists():
        print(f"Image not found: {path}")
        raise SystemExit(2)
    raise SystemExit(ascii_preview(path, width))


if __name__ == "__main__":
    main()
