#!/usr/bin/env python3
"""Prepare a photo for the website: resize, watermark and tag it.

Every image on the site should go through this script before it is added:

    python3 tools/protect_image.py photo.jpg assets/img/works/<slug>/final.jpg

What it does
  * resizes the photo to at most 2000 px on the long side
  * draws a visible watermark: "© <year> Mahdi Parnianpour"
      --style tiled   faint diagonal text across the whole image, plus a
                      credit in the corner (default; hard to crop or paint out)
      --style corner  only the credit in the corner
  * embeds the copyright in the file (EXIF Artist/Copyright and XMP), with
    the IPTC/PLUS "data mining" field set to prohibit AI/ML training while
    still allowing search-engine indexing

Options
  --crop x0,y0,x1,y1   crop the photo to this box first (pixels)
  --year 2026          year shown in the watermark (default: this year)
  --max 2000           longest side in pixels

Requires Pillow 11 or newer (pip install pillow).
"""
import argparse
import datetime
import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

ARTIST = "Mahdi Parnianpour"
SITE = "https://mparnianpour.github.io/mahdiartwebsite/"
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "IBMPlexMono-Medium.ttf")

# PLUS "Data Mining" vocabulary: prohibited, except for search engine indexing.
DATA_MINING = "http://ns.useplus.org/ldf/vocab/DMI-PROHIBITED-EXCEPTSEARCHENGINEINDEXING"


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default(size)


def corner_credit(img, text):
    """Small credit in the bottom-right corner, readable on light and dark areas."""
    w, h = img.size
    size = max(14, round(min(w, h) * 0.026))
    f = font(size)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    margin = size
    x = w - (x1 - x0) - margin
    y = h - (y1 - y0) - margin - y0
    d.text((x, y), text, font=f, fill=(255, 255, 255, 215),
           stroke_width=max(1, size // 12), stroke_fill=(20, 18, 16, 120))
    return Image.alpha_composite(img, layer)


def tiled(img, text):
    """Faint diagonal text repeated across the whole image."""
    w, h = img.size
    size = max(14, round(min(w, h) * 0.034))
    f = font(size)
    diag = int(math.hypot(w, h)) + size * 4
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    tw = (x1 - x0) + size * 3
    row = size * 5
    for i, y in enumerate(range(0, diag, row)):
        offset = (i % 2) * tw // 2
        for x in range(-tw + offset, diag, tw):
            d.text((x, y), text, font=f, fill=(255, 255, 255, 46),
                   stroke_width=max(1, size // 14), stroke_fill=(20, 18, 16, 26))
    layer = layer.rotate(30, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    layer = layer.crop((left, top, left + w, top + h))
    return Image.alpha_composite(img, layer)


def xmp_packet(year):
    rights = f"© {year} {ARTIST}. All rights reserved. Not licensed for AI or machine-learning training."
    return f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/"
    xmlns:plus="http://ns.useplus.org/ldf/xmp/1.0/"
    xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/">
   <dc:creator><rdf:Seq><rdf:li>{ARTIST}</rdf:li></rdf:Seq></dc:creator>
   <dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{rights}</rdf:li></rdf:Alt></dc:rights>
   <xmpRights:Marked>True</xmpRights:Marked>
   <xmpRights:WebStatement>{SITE}</xmpRights:WebStatement>
   <plus:DataMining>{DATA_MINING}</plus:DataMining>
   <Iptc4xmpCore:CreatorContactInfo rdf:parseType="Resource">
    <Iptc4xmpCore:CiUrlWork>{SITE}</Iptc4xmpCore:CiUrlWork>
   </Iptc4xmpCore:CreatorContactInfo>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode("utf-8")


def protect(img, year, style="tiled", crop=None, max_side=2000):
    """Return a resized, watermarked RGB copy of a PIL image. `crop` is a pixel box."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if crop:
        img = img.crop(tuple(int(v) for v in crop))
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = img.convert("RGBA")
    if style == "tiled":
        out = tiled(out, f"© {ARTIST.upper()}")
    return corner_credit(out, f"© {year} {ARTIST}").convert("RGB")


def save(img, path, year):
    """Save as JPEG with the copyright and no-AI-training metadata."""
    exif = Image.Exif()
    exif[0x013B] = ARTIST                                         # Artist
    exif[0x8298] = f"Copyright {year} {ARTIST}. All rights reserved."  # Copyright (EXIF is ASCII only)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    img.save(path, "JPEG", quality=85, optimize=True, progressive=True,
             exif=exif, xmp=xmp_packet(year))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--style", choices=["tiled", "corner"], default="tiled")
    p.add_argument("--crop", help="x0,y0,x1,y1 in pixels of the input photo")
    p.add_argument("--year", type=int, default=datetime.date.today().year)
    p.add_argument("--max", type=int, default=2000)
    a = p.parse_args()

    crop = a.crop.split(",") if a.crop else None
    out = protect(Image.open(a.input), a.year, a.style, crop, a.max)
    save(out, a.output, a.year)
    print(f"{a.output}  {out.size[0]}×{out.size[1]}  watermark: {a.style}")


if __name__ == "__main__":
    main()
