"""A private review page of draft works, for Mahdi to approve before publishing.

One self-contained HTML file (images inlined), never committed: drafts can
include drawings, and the page shows unwatermarked thumbnails.
"""
import base64
import datetime
import html
import io

from PIL import Image

from . import config, ingest, store

CSS = """
:root { --paper:#f6f5f1; --ink:#1b1a18; --ink-2:#4f4c46; --ink-3:#85817a; --rule:#d9d5cc; --accent:#9c3d27; }
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font: 400 34px/1.1 Georgia, serif; margin: 8px 0 6px; }
.lede { color: var(--ink-2); max-width: 62ch; margin: 0 0 28px; }
.work { border-top: 1px solid var(--rule); padding: 26px 0; }
.work h2 { font: 400 24px/1.2 Georgia, serif; margin: 0; display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.num { font: 600 13px ui-monospace, Menlo, monospace; color: var(--accent); }
.meta { font: 13px ui-monospace, Menlo, monospace; color: var(--ink-3); margin: 6px 0 10px; }
.text { max-width: 70ch; margin: 0 0 16px; color: var(--ink-2); }
.stages { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr)); gap: 18px; }
figure { margin: 0; }
figure img { width: 100%; height: 230px; object-fit: contain; background: #eceae4; display: block; }
figcaption { font-size: 14px; margin-top: 8px; color: var(--ink-2); }
figcaption b { color: var(--ink); font-weight: 600; }
figcaption .d { display: block; font: 12px ui-monospace, Menlo, monospace; color: var(--ink-3); }
.tag { font: 12px ui-monospace, Menlo, monospace; color: var(--ink-3); }
"""


def _thumb(pid, rotate=0, side=560):
    path = ingest.thumb(pid)
    with Image.open(path) as im:
        im = im.convert("RGB")
        if rotate:
            im = im.rotate(-rotate, expand=True)
        im.thumbnail((side, side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _day(rec):
    return datetime.date.fromisoformat(rec["taken"][:10]).strftime("%-d %b %Y")


def build(slugs, out, title="Drafts to review"):
    drafts = store.load(config.DRAFTS)
    photos = store.photos()
    chosen = [s for s in slugs if s in drafts]
    chosen.sort(key=lambda s: photos[drafts[s]["stages"][-1]["id"]]["ts"], reverse=True)
    e = html.escape
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'><title>{e(title)}</title>"
             f"<style>{CSS}</style></head><body><main><h1>{e(title)}</h1>"
             f"<p class='lede'>{len(chosen)} works, not published yet. Reply with the numbers you approve, "
             f"and anything to change (title, a note, the order or orientation of a stage).</p>"]
    for n, slug in enumerate(chosen, 1):
        dr = drafts[slug]
        stages = dr["stages"]
        first, last = photos[stages[0]["id"]], photos[stages[-1]["id"]]
        span = _day(first) if first["taken"][:10] == last["taken"][:10] else f"{_day(first)} – {_day(last)}"
        kind = "" if dr["kind"] == "painting" else " <span class='tag'>private sketchbook</span>"
        parts.append(f"<section class='work' id='w{n}'><h2><span class='num'>{n:02d}</span>"
                     f"{e(dr.get('title') or 'Untitled')}{kind}</h2>"
                     f"<p class='meta'>{span} · {len(stages)} photo{'s' if len(stages) != 1 else ''} · {e(slug)}</p>")
        if dr.get("text"):
            parts.append(f"<p class='text'>{e(dr['text'].strip())}</p>")
        parts.append("<div class='stages'>")
        for st in stages:
            rec = photos[st["id"]]
            turned = f" · turned {st['rotate']}°" if st.get("rotate") else ""
            label = f"<b>{e(st['label'])}</b> " if st.get("label") else ""
            parts.append(f"<figure><img src='{_thumb(st['id'], st.get('rotate', 0))}' alt='' loading='lazy'>"
                         f"<figcaption><span class='d'>{_day(rec)} · {st['id'][:6]}{turned}</span>"
                         f"{label}{e(st.get('note') or '')}</figcaption></figure>")
        parts.append("</div></section>")
    parts.append("</main></body></html>")
    with open(out, "w") as f:
        f.write("".join(parts))
    return chosen
