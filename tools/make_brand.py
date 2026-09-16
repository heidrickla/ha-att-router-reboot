"""Generate the in-repo brand images.

Since Home Assistant 2026.3 a custom integration carries its own brand images
and no pull request against `home-assistant/brands` is needed. HACS reads
`custom_components/<domain>/brand/` first.

Sizes:

    icon.png       256x256 exactly
    icon@2x.png    512x512 exactly
    logo.png       shortest side 128-256
    logo@2x.png    shortest side 256-512

The mark is what the integration does: the gateway, standing as the BGW320
does, with its status lights, and a restart arrow over it. Transparent
background so it sits on either theme.

    python tools/make_brand.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

DOMAIN = "att_router_reboot"

BODY = (34, 52, 86, 255)
FACE = (52, 76, 120, 255)
LIGHT_ON = (98, 214, 132, 255)
LIGHT_OFF = (120, 136, 160, 255)
ARROW = (245, 176, 66, 255)
CLEAR = (0, 0, 0, 0)


def draw(size: tuple[int, int], pad_frac: float) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, CLEAR)
    d = ImageDraw.Draw(img)

    # Work in a square box centred on the canvas so the mark is the same on
    # the icon and the wide logo.
    side = min(w, h)
    pad = side * pad_frac
    box = side - 2 * pad
    x0 = (w - box) / 2
    y0 = (h - box) / 2
    line = max(3, int(box * 0.06))
    radius = box * 0.08

    # The gateway: a tall body on the left two thirds of the box.
    gw_x0 = x0 + box * 0.06
    gw_x1 = x0 + box * 0.56
    gw_y0 = y0 + box * 0.04
    gw_y1 = y0 + box * 0.96
    d.rounded_rectangle([gw_x0, gw_y0, gw_x1, gw_y1], radius=radius, fill=BODY)
    inset = box * 0.05
    d.rounded_rectangle(
        [gw_x0 + inset, gw_y0 + inset, gw_x1 - inset, gw_y1 - inset],
        radius=radius * 0.6,
        fill=FACE,
    )

    # Status lights down the face: power, broadband, service.
    cx = (gw_x0 + gw_x1) / 2
    r = box * 0.045
    for i, colour in enumerate((LIGHT_ON, LIGHT_ON, LIGHT_OFF)):
        cy = gw_y0 + box * (0.22 + 0.16 * i)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    # The restart arrow: an open ring on the right with an arrowhead.
    ax = x0 + box * 0.76
    ay = y0 + box * 0.50
    ar = box * 0.20
    bbox = [ax - ar, ay - ar, ax + ar, ay + ar]
    d.arc(bbox, start=300, end=240, fill=ARROW, width=line)
    # Arrowhead where the arc ends. PIL measures angles clockwise from 3
    # o'clock, so 240 degrees is the upper left of the ring and the arc arrives
    # there travelling clockwise: the head points along that tangent.
    end = math.radians(240)
    ex, ey = ax + ar * math.cos(end), ay + ar * math.sin(end)
    tangent = (-math.sin(end), math.cos(end))
    radial = (math.cos(end), math.sin(end))
    head = box * 0.13
    d.polygon(
        [
            (ex + tangent[0] * head, ey + tangent[1] * head),
            (ex + radial[0] * head * 0.7, ey + radial[1] * head * 0.7),
            (ex - radial[0] * head * 0.7, ey - radial[1] * head * 0.7),
        ],
        fill=ARROW,
    )
    return img


def main() -> None:
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "custom_components",
        DOMAIN,
        "brand",
    )
    os.makedirs(out, exist_ok=True)
    specs = {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "logo.png": (512, 256),
        "logo@2x.png": (1024, 512),
    }
    for name, size in specs.items():
        path = os.path.join(out, name)
        draw(size, pad_frac=0.06).save(path, "PNG")
        print(f"  {name:14s} {size[0]}x{size[1]}")

    # Verify against the published rules rather than trusting the call above.
    ok = True
    for name, (want_w, want_h) in specs.items():
        with Image.open(os.path.join(out, name)) as im:
            w, h = im.size
            mode = im.mode
        if name.startswith("icon"):
            good = (w, h) == (want_w, want_h) and w == h
        else:
            short = min(w, h)
            good = (256 <= short <= 512) if "@2x" in name else (128 <= short <= 256)
        good &= mode == "RGBA"
        print(f"  check {name:14s} {w}x{h} {mode} {'OK' if good else 'FAILS THE RULE'}")
        ok &= good
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
