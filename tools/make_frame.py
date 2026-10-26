#!/usr/bin/env python3
"""Turn a picture of an empty frame into the frame used by "View on your wall".

    python3 tools/make_frame.py frame-photo.jpg assets/frames/carved

The picture must show the frame straight on, on a white background, with a
white opening (a product rendering like the one from the frame maker).
Only the wood is kept: the white around it and inside it is cut away.

Writes two files into the output folder:
  frame.jpg    the wood, cropped to the frame; the cut-away parts are filled
               with nearby wood colour so no white shows at the edges
  frame.json   the outline of the wood as triangles, the opening, and the
               parts of the frame that may stretch

The AR page builds a 3D frame from these for each painting. To fit a
painting that is wider, narrower or upright, the corners and the ornament in
the middle of each side keep their shape, and only the stretches between
them get longer or shorter. Portrait paintings get the frame turned on its
side.

Options
  --stretch-x 0.075-0.415,0.585-0.925
      the stretches along the top and bottom, as fractions of the opening's
      width; everything outside them keeps its shape
  --stretch-y 0.085-0.355,0.645-0.915
      the same along the left and right sides, as fractions of its height
  --threshold 205
      a pixel counts as wood when its darkest colour channel is below this

Requires Pillow, numpy and shapely 2.1 or newer (pip install pillow numpy shapely).
"""
import argparse
import json
import os

import numpy as np
import shapely
from PIL import Image
from shapely.geometry import LinearRing, Polygon, box
from shapely.geometry.polygon import orient

MARGIN = 8           # px of filled colour kept around the wood in the texture
SIMPLIFY = 0.7       # px; removes the pixel staircase from the outline
MIN_PIECE = 200      # px²; smaller separate specks are dropped
MIN_GAP = 40         # px²; smaller white spots inside the wood are filled in


def wood_mask(img, threshold):
    """Wood pixels, minus the pale one-pixel fringe where the wood meets white."""
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    m = rgb.min(axis=2) < threshold
    inner = m.copy()
    inner[1:] &= m[:-1]
    inner[:-1] &= m[1:]
    inner[:, 1:] &= m[:, :-1]
    inner[:, :-1] &= m[:, 1:]
    return inner


def mask_to_polygon(mask):
    """Union of the horizontal runs of wood pixels, one row at a time."""
    boxes = []
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    for y in range(mask.shape[0]):
        starts = np.flatnonzero(edges[y] == 1)
        ends = np.flatnonzero(edges[y] == -1)
        boxes.extend(box(x0, y, x1, y + 1) for x0, x1 in zip(starts, ends))
    return shapely.unary_union(boxes)


def clean(geom, center):
    """Keep the frame: drop specks, fill small spots, keep the opening."""
    parts = [g for g in getattr(geom, "geoms", [geom]) if g.area >= MIN_PIECE]
    frame = max(parts, key=lambda g: g.area)
    if len(parts) > 1:
        print(f"note: {len(parts) - 1} loose piece(s) outside the main frame kept")
    out = []
    for part in parts:
        holes = [r for r in part.interiors
                 if Polygon(r).area >= MIN_GAP or Polygon(r).contains(center)]
        out.append(Polygon(part.exterior, holes))
    opening = [h for h in frame.interiors if Polygon(h).contains(center)]
    if not opening:
        raise SystemExit("could not find the white opening in the middle of the frame")
    return out, Polygon(opening[0])


def insert_crossings(coords, xs, ys):
    """Add a point wherever an outline edge crosses a stretch line, so that each
    triangle stays on one side of every line and stretches without bending."""
    out = []
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        out.append((x0, y0))
        cuts = []
        for s in xs:
            if (x0 - s) * (x1 - s) < 0:
                t = (s - x0) / (x1 - x0)
                cuts.append((t, (s, y0 + t * (y1 - y0))))
        for s in ys:
            if (y0 - s) * (y1 - s) < 0:
                t = (s - y0) / (y1 - y0)
                cuts.append((t, (x0 + t * (x1 - x0), s)))
        out.extend(p for _, p in sorted(cuts))
    out.append(out[0])
    return out


def blur(a, r):
    """Box blur applied three times (close to a Gaussian), edges clamped."""
    for _ in range(3):
        for axis in (0, 1):
            pad = [(0, 0)] * a.ndim
            pad[axis] = (r + 1, r)
            c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
            hi = np.take(c, range(2 * r + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, range(0, c.shape[axis] - 2 * r - 1), axis=axis)
            a = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return a


def fill_outside(img, mask):
    """Paint the cut-away pixels with the colour of the nearest wood, so the
    texture has no white fringe when the phone shrinks it."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    m = mask.astype(np.float32)
    out = rgb.copy()
    todo = ~mask
    for radius in (1, 3, 8, 24):
        weight = blur(m, radius)
        layers = blur(rgb * m[..., None], radius)
        ok = todo & (weight > 1e-3)
        out[ok] = layers[ok] / weight[ok][:, None]
        todo &= ~ok
    out[todo] = rgb[mask].mean(axis=0)
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8))


def parse_ranges(text):
    return [tuple(float(v) for v in part.split("-")) for part in text.split(",")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("outdir")
    ap.add_argument("--stretch-x", default="0.075-0.415,0.585-0.925")
    ap.add_argument("--stretch-y", default="0.085-0.355,0.645-0.915")
    ap.add_argument("--threshold", type=int, default=205)
    ap.add_argument("--quality", type=int, default=88)
    args = ap.parse_args()

    src = Image.open(args.image).convert("RGB")
    full_mask = wood_mask(src, args.threshold)
    ys, xs = np.nonzero(full_mask)
    x0 = max(0, xs.min() - MARGIN)
    y0 = max(0, ys.min() - MARGIN)
    x1 = min(src.width, xs.max() + 1 + MARGIN)
    y1 = min(src.height, ys.max() + 1 + MARGIN)
    img = src.crop((x0, y0, x1, y1))
    mask = full_mask[y0:y1, x0:x1]
    w, h = img.size

    pieces, opening = clean(mask_to_polygon(mask), shapely.Point(w / 2, h / 2))
    ox0, oy0, ox1, oy1 = opening.bounds
    ow, oh = ox1 - ox0, oy1 - oy0

    # Stretch lines sit on half pixels so they never run along an outline edge.
    def lines(ranges, start, length):
        return [[round(start + a * length) + 0.5, round(start + b * length) + 0.5] for a, b in ranges]
    stretch_x = lines(parse_ranges(args.stretch_x), ox0, ow)
    stretch_y = lines(parse_ranges(args.stretch_y), oy0, oh)
    cut_x = sorted(v for r in stretch_x for v in r)
    cut_y = sorted(v for r in stretch_y for v in r)

    # Outline with the crossing points added, exterior counter-clockwise.
    polys = []
    for p in pieces:
        p = orient(p.simplify(SIMPLIFY, preserve_topology=True), sign=1.0)
        ext = insert_crossings(list(p.exterior.coords), cut_x, cut_y)
        holes = [insert_crossings(list(r.coords), cut_x, cut_y) for r in p.interiors]
        polys.append(Polygon(ext, holes))

    # Triangulate each cell between the stretch lines on its own.
    bx = [-1e9] + cut_x + [1e9]
    by = [-1e9] + cut_y + [1e9]
    index, vertices, triangles = {}, [], []

    def vid(x, y):
        key = (round(x * 1000), round(y * 1000))
        if key not in index:
            index[key] = len(vertices) // 2
            vertices.extend((round(x, 3), round(y, 3)))
        return index[key]

    for poly in polys:
        for i in range(len(bx) - 1):
            for j in range(len(by) - 1):
                piece = poly.intersection(box(bx[i], by[j], bx[i + 1], by[j + 1]))
                if piece.is_empty:
                    continue
                for g in getattr(piece, "geoms", [piece]):
                    if g.geom_type != "Polygon" or g.area < 1e-6:
                        continue
                    for tri in shapely.constrained_delaunay_triangles(g).geoms:
                        a, b, c = tri.exterior.coords[:3]
                        if abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) < 1e-9:
                            continue
                        triangles.extend((vid(*a), vid(*b), vid(*c)))

    rings = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            ids = []
            for x, y in ring.coords[:-1]:
                key = (round(x * 1000), round(y * 1000))
                if key not in index:
                    raise SystemExit(f"outline point {x:.2f},{y:.2f} missing from the triangles")
                ids.append(index[key])
            rings.append(ids)

    os.makedirs(args.outdir, exist_ok=True)
    fill_outside(img, mask).save(os.path.join(args.outdir, "frame.jpg"),
                                 quality=args.quality, optimize=True, progressive=True)
    data = {
        "image": "frame.jpg",
        "width": w,
        "height": h,
        "opening": [ox0, oy0, ox1, oy1],
        "stretch": {"x": stretch_x, "y": stretch_y},
        "vertices": vertices,
        "triangles": triangles,
        "rings": rings,
    }
    with open(os.path.join(args.outdir, "frame.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{w}x{h} px, opening {ow:.0f}x{oh:.0f} px, "
          f"{len(vertices) // 2} points, {len(triangles) // 3} triangles, {len(rings)} outlines")


if __name__ == "__main__":
    main()
