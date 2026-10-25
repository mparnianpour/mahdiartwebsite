"""Bring new photos in from Google Drive.

Reads the folders named in archive/settings.json. Two kinds of files are
understood there:

* Google Takeout zips (Google Photos exports). The JSON file Takeout writes
  next to each photo gives the time it was taken.
* Photos copied into the folder directly (e.g. by an auto-sync app).

Each photo is identified by a hash of its bytes, so a photo that arrives
twice (in two exports, or in an export and as a loose file) is recorded once.
Full-size files go to the local cache only; nothing here writes images into
the repository.
"""
import datetime
import hashlib
import io
import json
import os
import re
import zipfile
import zoneinfo
from pathlib import PurePosixPath

from PIL import Image, ImageOps

from . import config, gdrive, store

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv", ".webm", ".avi", ".gif"}
THUMB_SIZE = 640
TZ = zoneinfo.ZoneInfo(config.SETTINGS.get("timezone", "UTC"))

Image.MAX_IMAGE_PIXELS = 200_000_000


# --- Takeout metadata ------------------------------------------------------

def _sidecar_key(json_name):
    """'IMG.jpg.supplemental-metadata(1).json' -> ('IMG.jpg', '(1)'); handles Takeout's name truncation."""
    s = json_name[:-len(".json")]
    dup = ""
    m = re.search(r"\(\d+\)$", s)
    if m:
        dup, s = m.group(0), s[:m.start()]
    i = s.rfind(".")
    if i > 0 and "supplemental-metadata".startswith(s[i + 1:]):
        s = s[:i]
    return s, dup


def sidecars(zf):
    """Map each media entry in a Takeout zip to its JSON sidecar entry."""
    by_dir = {}
    for name in zf.namelist():
        p = PurePosixPath(name)
        if p.suffix.lower() == ".json" and p.name != "metadata.json":
            key, dup = _sidecar_key(p.name)
            by_dir.setdefault(str(p.parent), {})[(key, dup)] = name
    out = {}
    for name in zf.namelist():
        p = PurePosixPath(name)
        if p.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
            continue
        keys = by_dir.get(str(p.parent), {})
        stem, dup = p.name, ""
        m = re.search(r"\(\d+\)(?=\.[^.]+$)", p.name)
        if m:
            dup, stem = m.group(0), p.name[:m.start()] + p.name[m.end():]
        unedited = re.sub(r"-(edited|bearbeitet|modifié)(?=\.[^.]+$)", "", stem)
        hit = keys.get((stem, dup)) or keys.get((unedited, dup))
        if not hit:  # truncated names: the longest sidecar key the file name starts with
            cands = [(k, v) for (k, d), v in keys.items() if d == dup and len(k) >= 10 and stem.startswith(k)]
            hit = max(cands, key=lambda kv: len(kv[0]))[1] if cands else None
        if hit:
            out[name] = hit
    return out


def taken_time(img, sidecar, name, fallback_iso=None):
    """(local time 'YYYY-MM-DDTHH:MM:SS', unix seconds) of when the photo was taken."""
    if sidecar and sidecar.get("photoTakenTime", {}).get("timestamp"):
        ts = int(sidecar["photoTakenTime"]["timestamp"])
        if ts > 0:
            return datetime.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%dT%H:%M:%S"), ts
    local = None
    if img is not None:
        try:
            v = img.getexif().get_ifd(0x8769).get(0x9003)
            if v:
                local = datetime.datetime.strptime(v.strip()[:19], "%Y:%m:%d %H:%M:%S")
        except (ValueError, KeyError, AttributeError):
            local = None
    if local is None:
        m = re.search(r"(20\d\d)(\d\d)(\d\d)[_-](\d\d)(\d\d)(\d\d)", name)
        if m:
            try:
                local = datetime.datetime(*map(int, m.groups()))
            except ValueError:
                local = None
    if local is not None:
        return local.strftime("%Y-%m-%dT%H:%M:%S"), int(local.replace(tzinfo=TZ).timestamp())
    if fallback_iso:
        t = datetime.datetime.fromisoformat(fallback_iso.replace("Z", "+00:00"))
        return t.astimezone(TZ).strftime("%Y-%m-%dT%H:%M:%S"), int(t.timestamp())
    return None, 0


# --- cache -----------------------------------------------------------------

def original_path(pid):
    hits = list(config.ORIGINALS.glob(pid + ".*"))
    return hits[0] if hits else None


def make_thumb(pid, img):
    config.THUMBS.mkdir(parents=True, exist_ok=True)
    t = ImageOps.exif_transpose(img)
    if t.mode in ("RGBA", "LA", "P"):
        t = t.convert("RGBA")
        bg = Image.new("RGB", t.size, "white")
        bg.paste(t, mask=t.getchannel("A"))
        t = bg
    t = t.convert("RGB")
    t.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
    t.save(config.THUMBS / f"{pid}.jpg", quality=85)
    return t.size


def _keep_original(rec):
    return rec.get("status") in ("new", "held", "private-pending")


def add_item(photos, data, name, source, album, batch, sidecar=None, created=None):
    """Record one photo or video. Returns 'new', 'known' or 'skipped'."""
    pid = hashlib.sha256(data).hexdigest()[:12]
    ext = PurePosixPath(name).suffix.lower()
    known = photos.get(pid)
    if known:
        if _keep_original(known) and not original_path(pid):
            config.ORIGINALS.mkdir(parents=True, exist_ok=True)
            (config.ORIGINALS / f"{pid}{ext}").write_bytes(data)
        known.setdefault("also", [])
        if source not in known["also"] and source != known.get("source"):
            known["also"].append(source)
        return "known"

    rec = {"name": name, "album": album, "source": source, "batch": batch, "added": store.now()}
    if ext in VIDEO_EXT:
        rec.update(type="video", status="skipped", reason="video")
        rec["taken"], rec["ts"] = taken_time(None, sidecar, name, created)
        photos[pid] = rec
        return "skipped"

    config.ORIGINALS.mkdir(parents=True, exist_ok=True)
    path = config.ORIGINALS / f"{pid}{ext}"
    path.write_bytes(data)
    try:
        with Image.open(path) as img:
            img.load()
            rec["taken"], rec["ts"] = taken_time(img, sidecar, name, created)
            w, h = make_thumb(pid, img)
            rec.update(type="image", w=w, h=h, status="new")
    except Exception as e:  # unreadable (e.g. HEIC without a decoder)
        rec["taken"], rec["ts"] = taken_time(None, sidecar, name, created)
        rec.update(type="unsupported", status="skipped", reason=f"cannot open: {type(e).__name__}")
        path.unlink(missing_ok=True)
    photos[pid] = rec
    return "new" if rec["status"] == "new" else "skipped"


# --- sync --------------------------------------------------------------------

def _is_zip(f):
    return f["name"].lower().endswith(".zip") or f["mimeType"] in ("application/zip", "application/x-zip",
                                                                   "application/x-zip-compressed")


def _is_media(f):
    return f["mimeType"].startswith(("image/", "video/"))


def list_sources():
    files = []
    for ref in config.SETTINGS["drive_folders"]:
        folder = gdrive.find_folder(ref)
        if folder:
            files += [dict(f, folder=folder["name"]) for f in gdrive.walk(folder["id"])]
    return [f for f in files if _is_zip(f) or _is_media(f)]


def sync(max_sources=None, log=print):
    """Read Drive files not read before. Returns (batch id, ids of the new photos)."""
    photos, sources = store.photos(), store.load(config.SOURCES)
    batch = store.batch_id()
    todo = [f for f in list_sources()
            if sources.get(f["id"], {}).get("md5") != f.get("md5Checksum") or f["id"] not in sources]
    todo.sort(key=lambda f: f.get("createdTime", ""))
    if max_sources:
        todo = todo[:max_sources]
    before = set(photos)
    for f in todo:
        counts = {"new": 0, "known": 0, "skipped": 0}
        if _is_zip(f):
            config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
            path = config.DOWNLOADS / f"{f['id']}.zip"
            log(f"downloading {f['name']} ({int(f.get('size', 0)) / 1e6:.0f} MB)")
            gdrive.download(f["id"], path)
            with zipfile.ZipFile(path) as zf:
                side = sidecars(zf)
                for info in zf.infolist():
                    p = PurePosixPath(info.filename)
                    if info.is_dir() or p.suffix.lower() not in IMAGE_EXT | VIDEO_EXT:
                        continue
                    meta = json.loads(zf.read(side[info.filename])) if info.filename in side else None
                    stamp = datetime.datetime(*info.date_time).isoformat() + "Z"
                    counts[add_item(photos, zf.read(info), p.name, {"drive": f["id"], "entry": info.filename},
                                    p.parent.name, batch, meta, stamp)] += 1
            path.unlink()
        else:
            config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
            path = config.DOWNLOADS / f["id"]
            gdrive.download(f["id"], path)
            counts[add_item(photos, path.read_bytes(), f["name"], {"drive": f["id"]}, f["folder"], batch,
                            None, f.get("createdTime"))] += 1
            path.unlink()
        sources[f["id"]] = {"name": f["name"], "folder": f["folder"], "md5": f.get("md5Checksum"),
                            "size": int(f.get("size", 0)), "read": store.now(), **counts}
        log(f"  {f['name']}: {counts['new']} new, {counts['known']} already known, {counts['skipped']} skipped")
        store.save(config.PHOTOS, photos)
        store.save(config.SOURCES, sources)
    new = [pid for pid in photos if pid not in before and photos[pid]["status"] == "new"]
    return batch, new


WHOLE_ZIP = 10  # fetching at least this many photos from one zip: download it whole


def _store_original(pid, rec, data):
    if hashlib.sha256(data).hexdigest()[:12] != pid:
        return False
    config.ORIGINALS.mkdir(parents=True, exist_ok=True)
    path = config.ORIGINALS / f"{pid}{PurePosixPath(rec['name']).suffix.lower()}"
    path.write_bytes(data)
    if not (config.THUMBS / f"{pid}.jpg").exists():
        with Image.open(path) as img:
            make_thumb(pid, img)
    return True


def fetch(pids, log=print):
    """Make sure the full-size originals of these photos are in the cache (e.g. in a later batch).

    Returns the ids that could not be fetched (their Drive files are gone).
    """
    photos, sources = store.photos(), store.load(config.SOURCES)
    todo = [p for p in dict.fromkeys(pids) if not original_path(p)]
    by_zip = {}
    for pid in todo:
        src = photos[pid]["source"]
        if "entry" in src:
            by_zip.setdefault(src["drive"], []).append(pid)
    done = set()
    config.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for fid, group in by_zip.items():
        if len(group) < WHOLE_ZIP:
            continue
        path = config.DOWNLOADS / f"{fid}.zip"
        try:
            log(f"downloading {sources.get(fid, {}).get('name', fid)} for {len(group)} photos")
            gdrive.download(fid, path)
            with zipfile.ZipFile(path) as zf:
                for pid in group:
                    try:
                        if _store_original(pid, photos[pid], zf.read(photos[pid]["source"]["entry"])):
                            done.add(pid)
                    except KeyError:
                        pass
        except (gdrive.DriveError, zipfile.BadZipFile) as e:
            log(f"  {fid}: unavailable ({e})")
        finally:
            path.unlink(missing_ok=True)

    missing = []
    for pid in todo:
        if pid in done:
            continue
        rec = photos[pid]
        for src in [rec["source"]] + rec.get("also", []):
            try:
                if "entry" in src:
                    size = sources.get(src["drive"], {}).get("size") or \
                        int(gdrive.get(f"files/{src['drive']}", fields="size", supportsAllDrives="true")["size"])
                    raw = io.BufferedReader(gdrive.RangeFile(src["drive"], size), buffer_size=4 << 20)
                    with zipfile.ZipFile(raw) as zf:
                        data = zf.read(src["entry"])
                else:
                    tmp = config.DOWNLOADS / pid
                    gdrive.download(src["drive"], tmp)
                    data = tmp.read_bytes()
                    tmp.unlink()
            except (gdrive.DriveError, KeyError, zipfile.BadZipFile) as e:
                log(f"  {pid}: source {src['drive']} unavailable ({e})")
                continue
            if _store_original(pid, rec, data):
                break
        else:
            missing.append(pid)
    return missing


def thumb(pid):
    """A small JPEG of the photo for review sheets and embeddings, fetching it if needed."""
    path = config.THUMBS / f"{pid}.jpg"
    if path.exists():
        return path
    for p in config.WORK_IMAGES.glob(f"*/{pid}.jpg"):  # already published
        with Image.open(p) as img:
            make_thumb(pid, img)
        return path
    if not fetch([pid], log=lambda *_: None):
        return path
    return None


def clean_cache(keep):
    """Delete cached originals except for the given ids."""
    for p in config.ORIGINALS.glob("*"):
        if p.stem not in keep:
            os.remove(p)
