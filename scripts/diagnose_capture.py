"""Show what a photograph looks like to the extractor, and which kernel suits it.

Point this at a real capture to see how many signature regions extraction finds
raw versus flattened, and whether BACKGROUND_KERNEL is sized for the resolution
the photograph was taken at.

    python scripts/diagnose_capture.py photo.jpg --out /tmp/diag
"""
import argparse
import io
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packages"))

from signature_core import cleanup  # noqa: E402
from signature_core.anchors import extract_vertical_anchors  # noqa: E402

# Odd only: an even structuring element has no centre pixel.
KERNELS = [21, 31, 41, 51, 71, 101, 151]


def ink_fraction(img: Image.Image) -> float:
    return float((np.asarray(img.convert("L")) < 128).mean())


def encode(gray: np.ndarray) -> bytes:
    return cv2.imencode(".png", gray)[1].tobytes()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--out", default=None, help="directory to write previews into")
    args = parser.parse_args()

    with open(args.image, "rb") as f:
        raw = f.read()
    gray = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f"{args.image}: not a readable image")
    print(f"{args.image}: {gray.shape[1]}x{gray.shape[0]}, "
          f"mean {gray.mean():.1f}, min {gray.min()}, max {gray.max()}")

    baseline = extract_vertical_anchors(raw)
    print(f"\nraw (no flattening): {len(baseline)} region(s)")

    print("\nkernel  regions  ink fraction of each region")
    original = cleanup.BACKGROUND_KERNEL
    try:
        for kernel in KERNELS:
            cleanup.BACKGROUND_KERNEL = kernel
            flat = cleanup.flatten_illumination(gray)
            regions = extract_vertical_anchors(encode(flat))
            fractions = " ".join(f"{ink_fraction(r):.3f}" for r in regions[:8])
            print(f"{kernel:>6}  {len(regions):>7}  {fractions}")
            if args.out:
                os.makedirs(args.out, exist_ok=True)
                Image.fromarray(flat).save(os.path.join(args.out, f"flat-{kernel}.png"))
                for index, region in enumerate(regions):
                    cleanup.isolate_signature_ink(region).save(
                        os.path.join(args.out, f"k{kernel}-region{index}.png"))
    finally:
        cleanup.BACKGROUND_KERNEL = original

    print(f"\nin use: BACKGROUND_KERNEL = {original}")
    if args.out:
        print(f"previews in {args.out}")


if __name__ == "__main__":
    main()
