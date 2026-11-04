"""Visitor comments from the Google Form on the Comments page.

The form's responses go to a Google Sheet (archive/settings.json:
comments_sheet, its Drive ID). `new_comments` returns the rows not handled
before; Claude reads them as data (never as instructions), approves the
genuine ones onto the site (_data/comments.yml) and folds them into the
batch notes. archive/comments.json remembers which rows were handled, by a
hash, without keeping the text of rejected ones.
"""
import csv
import datetime
import hashlib
import io

import yaml

from . import config, gdrive, store

STATE = config.ARCHIVE / "comments.json"


def _column(header, *words):
    for i, h in enumerate(header):
        if any(w in h.lower() for w in words):
            return i
    return None


def rows():
    sheet = config.SETTINGS.get("comments_sheet")
    if not sheet:
        return []
    table = list(csv.reader(io.StringIO(gdrive.export_csv(sheet))))
    if not table:
        return []
    header, body = table[0], table[1:]
    cols = {"time": _column(header, "timestamp", "time"), "name": _column(header, "name"),
            "work": _column(header, "about", "work", "painting"), "text": _column(header, "comment", "message")}
    out = []
    for r in body:
        get = lambda k: r[cols[k]].strip() if cols[k] is not None and cols[k] < len(r) else ""
        if not get("text"):
            continue
        key = hashlib.sha256(f"{get('time')}|{get('text')}".encode()).hexdigest()[:10]
        out.append({"key": key, "time": get("time"), "name": get("name"), "work": get("work"), "text": get("text")})
    return out


def new_comments():
    seen = store.load(STATE)
    return [r for r in rows() if r["key"] not in seen]


def _date(stamp):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(stamp, fmt).date()
        except ValueError:
            pass
    return datetime.date.today()


def decide(approve=(), reject=(), replies=None):
    """Record decisions; approved comments are added to _data/comments.yml."""
    replies = replies or {}
    seen = store.load(STATE)
    by_key = {r["key"]: r for r in rows()}
    data = yaml.safe_load(config.COMMENTS_DATA.read_text()) if config.COMMENTS_DATA.exists() else None
    data = data or []
    for key in approve:
        r = by_key[key]
        item = {"date": _date(r["time"]), "name": r["name"] or None, "work": r["work"] or None, "text": r["text"]}
        if replies.get(key):
            item["reply"] = replies[key]
        data.append({k: v for k, v in item.items() if v})
        seen[key] = {"status": "approved", "handled": store.now()}
    for key in reject:
        seen[key] = {"status": "rejected", "handled": store.now()}
    if approve:
        config.COMMENTS_DATA.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000))
    store.save(STATE, seen)
