"""Reading and writing the archive's JSON records.

Records are written one per line and sorted by key, so each batch shows up
in git as a short diff of the lines it added or changed.
"""
import datetime
import json

from . import config


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}" for k, v in sorted(data.items())]
    path.write_text("{\n" + ",\n".join(lines) + ("\n" if lines else "") + "}\n")


def photos():
    return load(config.PHOTOS)


def batch_id():
    """Name for a new sync: today's date, with a suffix for a second sync on the same day."""
    day = datetime.date.today().isoformat()
    existing = {p.stem for p in config.EMBEDDINGS.glob(f"{day}*.npz")}
    if day not in existing:
        return day
    n = 2
    while f"{day}-{n}" in existing:
        n += 1
    return f"{day}-{n}"


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
