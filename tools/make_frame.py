#!/usr/bin/env python3
"""Turn a picture of an empty frame into a frame for "View on your wall".

    python3 tools/make_frame.py frame-picture.jpg assets/frames/<name>

Any frame works: rectangular, oval, round or arched, carved or plain. The
picture should show the frame straight on, with its opening empty, on a
plain background of any colour (or a PNG with a transparent background).

How the frame is found
  * The background colour is read from the edges of the picture (or from the
    transparent pixels of a PNG). Everything that stands out from it, and is
    not joined to the edges, is the frame: that gives its outside contour.
  * The opening is the empty area around the centre of the frame. It may be
    the same colour as the background, or one plain colour of its own, such
    as a grey placeholder.
  * Background showing through gaps in the carving is cut away as well.

Writes into the output folder:
  frame.jpg    the frame, cropped; the cut-away parts are filled with nearby
               frame colour so nothing pale shows at the edges
  frame.json   the frame's outline as triangles, its opening, and the area
               behind the opening where the painting goes

The wall page keeps the frame's own shape. It puts the painting behind the
opening at its real size, centred on the centre of the opening, and scales
the frame so the painting fills the opening. If the painting is a different
shape from the opening, the opening shows its middle and the frame hides the
rest. Upright paintings get the frame turned on its side, unless --no-turn.

Options
  --no-turn       never turn the frame on its side (for frames with a definite
                  top, such as a crest or an arch)
  --threshold N   how different from the background (0-255) a pixel must be to
                  count as frame; worked out from the picture when left out

Requires Pillow, numpy and shapely 2.1 or newer (pip install pillow numpy shapely).
"""
import argparse
import json
import os

import numpy as np
import shapely
from PIL import Image, ImageDraw, ImageOps
from shapely.affinity import translate
from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient

MARGIN = 8           # px of filled colour kept around the frame in the texture
SIMPLIFY = 0.7       # px; removes the pixel staircase from the outline
MIN_PIECE = 200      # px²; smaller separate specks are dropped
MIN_GAP = 0.0005     # share of the frame's area; smaller see-through spots are kept as frame
MIN_OPENING = 0.03   # the opening must be at least this share of the frame's area


def erode(m):
    """Shrink a mask by one pixel (drops the soft fringe along its edges)."""
    out = m.copy()
    out[1:] &= m[:-1]
    out[:-1] &= m[1:]
    out[:, 1:] &= m[:, :-1]
    out[:, :-1] &= m[:, 1:]
    return out


def edge_pixels(a, width=4):
    return np.concatenate([a[:width].reshape(-1, *a.shape[2:]), a[-width:].reshape(-1, *a.shape[2:]),
                           a[:, :width].reshape(-1, *a.shape[2:]), a[:, -width:].reshape(-1, *a.shape[2:])])


def otsu(values):
    """The threshold that best splits values (0-255) into two groups."""
    hist = np.bincount(np.clip(values, 0, 255).astype(np.int64).ravel(), minlength=256).astype(np.float64)
    p = hist / hist.sum()
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega))
    return int(np.nanargmax(between)) + 1


def mask_to_polygon(mask):
    """Union of the horizontal runs of a mask, one row at a time."""
    boxes = []
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    edges = np.diff(padded, axis=1)
    for y in range(mask.shape[0]):
        starts = np.flatnonzero(edges[y] == 1)
        ends = np.flatnonzero(edges[y] == -1)
        boxes.extend(box(x0, y, x1, y + 1) for x0, x1 in zip(starts, ends))
    return shapely.unary_union(boxes)


def inside(poly, shape):
    """Boolean mask of the pixels inside a polygon."""
    return rasterize(poly, (shape[1], shape[0]))


def parts(geom):
    return [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty]


def rasterize(poly, size):
    """Polygon (without its holes) -> boolean mask."""
    img = Image.new("1", size, 0)
    draw = ImageDraw.Draw(img)
    for p in parts(poly):
        draw.polygon(list(p.exterior.coords), fill=1)
    return np.asarray(img, dtype=bool)


def find_frame(rgb, alpha, threshold):
    """Return (frame pieces, opening polygon, solid pixel mask) for the whole picture."""
    h, w = alpha.shape
    clear_edges = (edge_pixels(alpha) < 128).mean()
    if clear_edges > 0.5:
        print("background: transparent")
        diff = alpha
        threshold = threshold or 128
    else:
        bg = np.median(edge_pixels(rgb), axis=0)
        diff = np.abs(rgb - bg).max(axis=2)
        if (edge_pixels(diff) < 32).mean() < 0.6:
            print("warning: the edges of the picture are not one plain colour; "
                  "crop it so the frame sits on an even background")
        # Half of the split between background and frame: low enough that pale
        # highlights still count as frame; the soft edge is shaved off below.
        threshold = threshold or min(128, max(16, otsu(diff) // 2))
        print(f"background: rgb{tuple(int(c) for c in bg)}, threshold {threshold}")

    solid = erode(diff >= threshold)
    clear = mask_to_polygon(~solid)
    picture = box(0, 0, w, h)
    outside = [p for p in parts(clear) if p.exterior.intersects(picture.exterior)]
    enclosed = [p for p in parts(clear) if not p.exterior.intersects(picture.exterior)]
    pieces = [p for p in parts(picture.difference(shapely.unary_union(outside))) if p.area >= MIN_PIECE]
    if not pieces:
        raise SystemExit("could not find a frame: nothing stands out from the background")
    main = max(pieces, key=lambda p: p.area)
    if len(pieces) > 1:
        print(f"note: {len(pieces) - 1} loose piece(s) next to the frame kept")

    # The opening: the empty area around the centre of the frame.
    x0, y0, x1, y1 = main.bounds
    centre = Point((x0 + x1) / 2, (y0 + y1) / 2)
    around = [p for p in enclosed if p.contains(centre)]
    if around:
        opening = Polygon(around[0].exterior)
    else:
        # Not background: look for one plain colour of its own around the centre.
        cx, cy = int(centre.x), int(centre.y)
        seed = np.median(rgb[cy - 3:cy + 4, cx - 3:cx + 4].reshape(-1, 3), axis=0)
        bx0, by0, bx1, by1 = (int(v) for v in main.bounds)
        near = np.abs(rgb[by0:by1, bx0:bx1] - seed).max(axis=2)
        same = ~erode(near >= min(128, max(16, otsu(near) // 2)))
        found = [p for p in parts(translate(mask_to_polygon(same), bx0, by0)) if p.contains(centre)]
        if not found or found[0].exterior.intersects(main.exterior):
            raise SystemExit("could not find the opening around the centre of the frame; "
                             "use a picture with the opening empty")
        opening = Polygon(found[0].exterior)
    if opening.area < MIN_OPENING * main.area:
        raise SystemExit("the empty area around the centre is too small to be the opening; "
                         "use a picture with the opening empty")

    # Gaps in the carving: clearly background, not just a pale or dark patch of frame.
    gaps = [p for p in enclosed if p.area >= MIN_GAP * main.area and not opening.contains(p)
            and np.median(diff[inside(p, alpha.shape)]) <= threshold / 3]
    holes = shapely.unary_union([opening, *gaps])
    frame = [p for g in pieces for p in parts(g.difference(holes)) if p.area >= MIN_PIECE]
    print(f"opening: {opening.bounds[2] - opening.bounds[0]:.0f}x{opening.bounds[3] - opening.bounds[1]:.0f} px"
          f"{', ' + str(len(gaps)) + ' gap(s) in the carving' if gaps else ''}")
    return frame, opening, solid


def triangulate(polys):
    """Constrained triangulation; returns (flat xy list, triangle indices, outlines)."""
    index, vertices, triangles, rings = {}, [], [], []

    def vid(x, y):
        key = (round(x * 1000), round(y * 1000))
        if key not in index:
            index[key] = len(vertices) // 2
            vertices.extend((round(x, 3), round(y, 3)))
        return index[key]

    for poly in polys:
        for tri in shapely.constrained_delaunay_triangles(poly).geoms:
            a, b, c = tri.exterior.coords[:3]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) > 1e-9:
                triangles.extend((vid(*a), vid(*b), vid(*c)))
        for ring in [poly.exterior, *poly.interiors]:
            rings.append([vid(x, y) for x, y in ring.coords[:-1]])
    return vertices, triangles, rings


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
    """Paint the cut-away pixels with the colour of the nearest frame pixels, so
    the texture has no pale fringe when the phone shrinks it."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("outdir")
    ap.add_argument("--no-turn", action="store_true")
    ap.add_argument("--threshold", type=int)
    ap.add_argument("--quality", type=int, default=88)
    args = ap.parse_args()

    src = ImageOps.exif_transpose(Image.open(args.image))
    rgba = np.asarray(src.convert("RGBA")).astype(np.int16)
    frame, opening, solid = find_frame(rgba[..., :3], rgba[..., 3], args.threshold)

    # Crop to the frame.
    fx0, fy0, fx1, fy1 = shapely.unary_union(frame).bounds
    x0, y0 = max(0, int(fx0) - MARGIN), max(0, int(fy0) - MARGIN)
    x1, y1 = min(src.width, int(np.ceil(fx1)) + MARGIN), min(src.height, int(np.ceil(fy1)) + MARGIN)
    frame = [translate(p, -x0, -y0) for p in frame]
    opening = translate(opening, -x0, -y0)
    w, h = x1 - x0, y1 - y0

    polys = [orient(p.simplify(SIMPLIFY, preserve_topology=True), sign=1.0) for p in frame]
    vertices, triangles, rings = triangulate(polys)

    # Where the painting goes: the opening plus a narrow lip hidden under the frame.
    ox0, oy0, ox1, oy1 = opening.bounds
    lip = max(2.0, 0.012 * min(ox1 - ox0, oy1 - oy0))
    behind = opening.buffer(lip, join_style="mitre").intersection(shapely.unary_union(
        [Polygon(p.exterior) for p in frame]))
    behind = [orient(p.simplify(SIMPLIFY), sign=1.0) for p in parts(behind) if p.area >= MIN_PIECE]
    art_vertices, art_triangles, _ = triangulate(behind)

    wood = solid[y0:y1, x0:x1] & ~rasterize(opening, (w, h))
    os.makedirs(args.outdir, exist_ok=True)
    fill_outside(src.convert("RGB").crop((x0, y0, x1, y1)), wood).save(
        os.path.join(args.outdir, "frame.jpg"), quality=args.quality, optimize=True, progressive=True)
    data = {
        "image": "frame.jpg",
        "width": w,
        "height": h,
        "opening": [round(v, 2) for v in (ox0, oy0, ox1, oy1)],
        "rectangular": opening.area >= 0.97 * (ox1 - ox0) * (oy1 - oy0),
        "turn": not args.no_turn,
        "vertices": vertices,
        "triangles": triangles,
        "rings": rings,
        "art": {"vertices": art_vertices, "triangles": art_triangles},
    }
    with open(os.path.join(args.outdir, "frame.json"), "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"{w}x{h} px, {len(vertices) // 2} points, {len(triangles) // 3} triangles, "
          f"{len(rings)} outlines -> {args.outdir}")


if __name__ == "__main__":
    main()
