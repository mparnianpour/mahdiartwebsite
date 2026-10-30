"""Apply a batch's review decisions to the archive and the site.

Claude writes the decisions as YAML after reviewing the contact sheets
(format in pipeline/PLAYBOOK.md). Paintings get a public page in _works/
with every stage watermarked; sketches and drawings go into the encrypted
sketchbook; everything else is recorded as skipped or held with a reason.
"""
import datetime
import importlib.util
import re

import yaml
from PIL import Image, ImageOps

from . import config, ingest, sorter, store, vault

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MANAGED_KEYS = ("date", "year", "image", "archive", "stages")
_protect = None


def protect_mod():
    """tools/protect_image.py, loaded as a module."""
    global _protect
    if _protect is None:
        spec = importlib.util.spec_from_file_location("protect_image", config.PROTECT_SCRIPT)
        _protect = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_protect)
    return _protect


def _open_original(pid):
    path = ingest.original_path(pid)
    if not path:
        missing = ingest.fetch([pid])
        path = None if missing else ingest.original_path(pid)
    if not path:
        raise SystemExit(f"{pid}: the full-size photo is not in the cache and its Drive source is gone")
    return Image.open(path)


def render(pid, out, year, crop=None, rotate=0, style="tiled"):
    """A watermarked web copy of a photo.

    rotate: degrees clockwise (90, 180, 270), to show every stage of a work the
    same way up. crop: [x0, y0, x1, y1] as fractions of the rotated photo.
    """
    pm = protect_mod()
    with _open_original(pid) as original:
        img = ImageOps.exif_transpose(original)
        if rotate:
            img = img.rotate(-rotate, expand=True)
        box = None
        if crop:
            w, h = img.size
            box = [round(crop[0] * w), round(crop[1] * h), round(crop[2] * w), round(crop[3] * h)]
        pm.save(pm.protect(img, year, style, box), out, year)


def _date(rec):
    return datetime.date.fromisoformat(rec["taken"][:10])


# --- public paintings --------------------------------------------------------

def _read_page(path):
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_page(path, fm, body):
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False)
    path.write_text(f"---\n{front}---\n\n{body.strip()}\n")


def publish_work(slug, works=None, photos=None, log=print):
    """Write the work's images and its page from archive/works.json."""
    works = works or store.load(config.WORKS)
    photos = photos or store.photos()
    w = works[slug]
    folder = config.WORK_IMAGES / slug
    for st in w["stages"]:
        out = folder / f"{st['id']}.jpg"
        look = [st.get("crop"), st.get("rotate", 0)]
        if not out.exists() or st.get("rendered") != look:
            render(st["id"], out, _date(photos[st["id"]]).year, st.get("crop"), st.get("rotate", 0))
            st["rendered"] = look
            log(f"  image {out.relative_to(config.REPO)}")
    for old in folder.glob("*.jpg"):  # stages removed in a later review
        if old.stem not in {st["id"] for st in w["stages"]}:
            old.unlink()

    page = config.WORK_PAGES / f"{slug}.md"
    fm, body = _read_page(page) if page.exists() else ({}, "")
    if page.exists() and fm.get("archive") != slug:
        raise SystemExit(f"{page.name} was written by hand; add stages to it by hand (see PLAYBOOK)")
    last = photos[w["stages"][-1]["id"]]
    hero = w.get("hero") or w["stages"][-1]["id"]
    new = {"title": w["title"]}
    for k in ("medium", "size"):
        if w.get(k):
            new[k] = w[k]
    if w.get("status"):
        new["status"] = w["status"]
    for k, v in fm.items():  # keep anything set by hand, except the fields the pipeline owns
        if k not in MANAGED_KEYS and not (k in new and w.get("_set", {}).get(k)):
            new[k] = v
    new.update({
        "date": _date(last), "year": _date(last).year,
        "image": f"/assets/img/works/{slug}/{hero}.jpg",
        "archive": slug,
        "stages": [{k: v for k, v in (("image", f"/assets/img/works/{slug}/{st['id']}.jpg"),
                                      ("date", _date(photos[st["id"]])),
                                      ("label", st.get("label")), ("note", st.get("note"))) if v}
                   for st in w["stages"]],
    })
    new.setdefault("featured", False)
    if w.get("text") and (not body.strip() or w.get("_set", {}).get("text")):
        body = w["text"]
    _write_page(page, new, body)
    log(f"  page {page.relative_to(config.REPO)} ({len(w['stages'])} stages)")


# --- hand-written pages -----------------------------------------------------------

def adopt(log=print):
    """Record the images of hand-written work pages (no `archive:` line) as published photos.

    Those works were put on the site before the pipeline existed, or by hand
    since. Recording them lets `propose` recognise later photos of the same
    works, and photos that are already on the site, instead of proposing
    them as new works. Returns the ids added.
    """
    import hashlib

    photos = store.photos()
    added = []
    for page in sorted(config.WORK_PAGES.glob("*.md")):
        fm, _ = _read_page(page)
        if not fm or fm.get("archive"):
            continue
        slug = page.stem
        items = [(st.get("image"), st.get("date"), "painting") for st in fm.get("stages") or []]
        items.append((fm.get("image"), fm.get("date"), "painting"))
        items += [(sk.get("image"), sk.get("date"), "drawing") for sk in fm.get("sketches") or []]
        for path, date, kind in items:
            f = config.REPO / str(path or "").lstrip("/")
            if not path or not f.is_file():
                continue
            pid = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
            if pid in photos:
                continue
            day = date or fm.get("date") or datetime.date.today()
            day = day if isinstance(day, datetime.date) else datetime.date.fromisoformat(str(day)[:10])
            moment = datetime.datetime.combine(day, datetime.time(12)).replace(tzinfo=ingest.TZ)
            with Image.open(f) as img:
                w, h = ingest.make_thumb(pid, img)
            photos[pid] = {"name": f.name, "album": "site", "source": {"site": str(path)}, "batch": "site",
                           "added": store.now(), "taken": moment.strftime("%Y-%m-%dT%H:%M:%S"),
                           "ts": int(moment.timestamp()), "taken_estimated": not date, "type": "image",
                           "w": w, "h": h, "kind": kind, "work": slug, "status": "published"}
            added.append(pid)
    if added:
        store.save(config.PHOTOS, photos)
        sorter.embed(added, f"site-{datetime.date.today().isoformat()}", log)
        log(f"recorded {len(added)} images from hand-written pages")
    return added


# --- applying decisions ---------------------------------------------------------

def _expand(refs, photos):
    """Photo ids from ids, id prefixes and review references.

    "G045" is every waiting photo of proposed group 45; "S003#4" and "V001#2"
    are the 4th photo on singles sheet S003 and the 2nd on studio-views sheet
    V001, as numbered on the sheets written by `propose`.
    """
    import json
    import re as _re

    proposal = None
    out = []
    for ref in refs:
        ref = str(ref)
        m = _re.fullmatch(r"([GSV])(\d{3})(?:#(\d+))?", ref)
        if not m:
            out += sorter.resolve([ref], photos)
            continue
        if proposal is None:
            proposal = json.loads((config.REVIEW / "proposals.json").read_text())
        kind, n, i = m.group(1), int(m.group(2)), m.group(3)
        if kind == "G":
            members = [p for p in proposal["groups"][n - 1]["photos"] if photos[p]["status"] in ("new", "held")]
            out += members if i is None else [members[int(i) - 1]]
        else:
            pool = proposal["singles"] if kind == "S" else proposal.get("studio_views", [])
            chunk = pool[(n - 1) * 30:n * 30]
            out += chunk if i is None else [chunk[int(i) - 1]]
    return out


def _auto_slug(kind, first, taken):
    """untitled-2025-11-12 / drawing-2025-07-25, with -2, -3 … when taken."""
    base = f"{'drawing' if kind == 'drawing' else 'untitled'}-{first}"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def apply(path, log=print, draft=False):
    """Apply review decisions. With draft=True, record the grouping only (archive/drafts.json):
    no page, image or sketchbook entry is written until publish_drafts."""
    d = yaml.safe_load(open(path)) or {}
    photos = store.photos()
    works = store.load(config.WORKS)
    drafts = store.load(config.DRAFTS)
    v = None
    summary = {"public": [], "private": [], "pending": [], "drafts": [], "skipped": 0, "held": 0}
    stamp = store.now()
    taken_slugs = set(works) | set(drafts) | {r.get("work") for r in photos.values() if r.get("work")}

    def take(pid, work):
        rec = photos[pid]
        if rec["status"] in ("new", "held", "private-pending", "grouped") or rec.get("work") == work:
            return rec
        raise SystemExit(f"{pid} is already {rec['status']} in {rec.get('work')}; not moving it")

    for w in d.get("works") or []:
        kind = w.get("kind", "painting")
        specs = []
        for s in w["stages"]:
            s = s if isinstance(s, dict) else {"id": s}
            specs += [dict(s, id=pid) for pid in _expand([s["id"]], photos)]
        ids = [s["id"] for s in specs]
        if len(set(ids)) != len(ids):
            raise SystemExit(f"{w.get('slug') or ids[0]}: a photo is listed twice")
        slug = w.get("slug") or "auto"
        if slug == "auto":
            slug = _auto_slug(kind, min(photos[p]["taken"][:10] for p in ids), taken_slugs)
        taken_slugs.add(slug)
        if not SLUG.match(slug):
            raise SystemExit(f"bad slug: {slug}")
        stages = {s["id"]: s for s in specs}
        for pid in ids:
            take(pid, slug)

        if draft:
            dr = drafts.setdefault(slug, {"kind": kind, "stages": [], "created": stamp})
            if kind == "painting":  # drawings keep no text in the public archive
                for k in ("title", "status", "medium", "size", "text", "hero"):
                    if w.get(k):
                        dr[k] = sorter.resolve([str(w[k])], photos)[0] if k == "hero" else w[k]
            old = {st["id"]: st for st in dr["stages"]}
            for pid, s in stages.items():
                st = old.setdefault(pid, {"id": pid})
                for k in (("label", "note", "crop", "rotate") if kind == "painting" else ("crop", "rotate")):
                    if s.get(k) is not None:
                        st[k] = s[k]
            dr["stages"] = sorted(old.values(), key=lambda st: photos[st["id"]]["ts"])
            dr["updated"] = stamp
            for pid in ids:
                photos[pid].update(kind=kind, work=slug, status="grouped")
            summary["drafts"].append(slug)
            continue

        if kind == "painting":
            cur = works.get(slug)
            if cur is None:
                if not w.get("title"):
                    raise SystemExit(f"{slug}: a new work needs a title")
                cur = works[slug] = {"title": w["title"], "kind": "painting", "stages": [], "created": stamp}
            cur["_set"] = {}
            for k in ("title", "status", "medium", "size", "text", "hero"):
                if w.get(k):
                    cur[k] = sorter.resolve([str(w[k])], photos)[0] if k == "hero" else w[k]
                    cur["_set"][k] = True
            old = {st["id"]: st for st in cur["stages"]}
            for pid, s in stages.items():
                st = old.setdefault(pid, {"id": pid})
                for k in ("label", "note", "crop", "rotate"):
                    if s.get(k) is not None:
                        st[k] = s[k]
            cur["stages"] = sorted(old.values(), key=lambda st: photos[st["id"]]["ts"])
            cur["updated"] = stamp
            for pid in ids:
                photos[pid].update(kind="painting", work=slug, status="published")
            publish_work(slug, works, photos, log)
            cur.pop("_set", None)
            summary["public"].append(slug)

        elif kind == "drawing":
            if v is None and vault.password():
                v = vault.Vault()
                idx = v.index()
            if v is None:
                for pid in ids:
                    photos[pid].update(kind="drawing", work=slug, status="private-pending")
                summary["pending"].append(slug)
                continue
            e = idx["entries"].setdefault(slug, {"title": w.get("title") or "", "photos": [], "created": stamp})
            for k in ("title", "note", "medium"):
                if w.get(k):
                    e[k] = w[k]
            have = {p["id"]: p for p in e["photos"]}
            for pid, s in stages.items():
                rec = photos[pid]
                ph = have.setdefault(pid, {"id": pid})
                ph["date"] = rec["taken"][:10]
                for k in ("label", "note"):
                    if s.get(k):
                        ph[k] = s[k]
                if not v.has_image(pid):
                    with _open_original(pid) as img:
                        ph["w"], ph["h"] = v.put_image(pid, img, _date(rec).year)
                rec.update(kind="drawing", work=slug, status="private")
            e["photos"] = sorted(have.values(), key=lambda p: photos[p["id"]]["ts"])
            e["date"], e["first"] = e["photos"][-1]["date"], e["photos"][0]["date"]
            e["updated"] = stamp
            summary["private"].append(slug)
        else:
            raise SystemExit(f"{slug}: kind must be painting or drawing")

    for key, status in (("skip", "skipped"), ("hold", "held")):
        for ref, reason in (d.get(key) or {}).items():
            for pid in _expand([ref], photos):
                take(pid, photos[pid].get("work"))
                photos[pid].update(status=status, reason=str(reason))
                summary["skipped" if status == "skipped" else "held"] += 1

    if v is not None:
        v.save_index(idx)
    store.save(config.WORKS, works)
    store.save(config.DRAFTS, drafts)
    store.save(config.PHOTOS, photos)
    return summary


def publish_drafts(slugs=None, log=print):
    """Publish grouped drafts (all, or the given slugs): paintings to their pages,
    drawings to the sketchbook (or private-pending without VAULT_PASSWORD)."""
    import tempfile

    drafts = store.load(config.DRAFTS)
    chosen = list(drafts) if not slugs else slugs
    missing = [s for s in chosen if s not in drafts]
    if missing:
        raise SystemExit("no such draft: " + ", ".join(missing))
    entries = []
    for slug in chosen:
        dr = drafts[slug]
        e = {k: v for k, v in dr.items() if k not in ("created", "updated")}
        e["slug"] = slug
        if dr["kind"] == "painting" and not e.get("title"):
            e["title"] = "Untitled"
        entries.append(e)
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        yaml.safe_dump({"works": entries}, f, allow_unicode=True)
    summary = apply(f.name, log)
    drafts = store.load(config.DRAFTS)
    for slug in chosen:
        drafts.pop(slug, None)
    store.save(config.DRAFTS, drafts)
    return summary


def publish_pending(log=print):
    """Move drawings that waited for VAULT_PASSWORD into the sketchbook."""
    photos = store.photos()
    pending = {}
    for pid, rec in photos.items():
        if rec["status"] == "private-pending":
            pending.setdefault(rec["work"], []).append({"id": pid})
    if not pending:
        return 0
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        yaml.safe_dump({"works": [{"slug": s, "kind": "drawing", "stages": st} for s, st in pending.items()]}, f)
    apply(f.name, log)
    return sum(len(st) for st in pending.values())
