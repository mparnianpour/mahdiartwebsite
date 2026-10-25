"""Command line: python3 -m pipeline <command>. See pipeline/PLAYBOOK.md."""
import argparse
import collections
import json
import sys
from pathlib import Path

from . import comments, config, ingest, publish, sorter, store, vault


def cmd_status(a):
    photos = store.photos()
    by = collections.Counter(r["status"] for r in photos.values())
    kinds = collections.Counter(r.get("kind") for r in photos.values() if r.get("kind"))
    print(f"photos recorded: {len(photos)}")
    print("  by status:", dict(sorted(by.items())))
    print("  by kind:  ", dict(sorted(kinds.items())))
    sources = store.load(config.SOURCES)
    print(f"Drive files read: {len(sources)}")
    for fid, s in sorted(sources.items(), key=lambda kv: kv[1]["read"]):
        print(f"  {s['read'][:10]}  {s['name']}  ({s.get('new', 0)} new)")
    works = store.load(config.WORKS)
    print(f"public works: {len(works)}")
    ids, _ = sorter.load_embeddings()
    print(f"embeddings: {len(ids)}")


def cmd_sync(a):
    batch, new = ingest.sync(max_sources=a.max_sources)
    print(f"batch {batch}: {len(new)} new photos")
    if new:
        sorter.embed(new, batch)


def cmd_embed(a):
    photos = store.photos()
    todo = [p for p, r in photos.items() if r.get("type") == "image" and r["status"] != "skipped"]
    print(f"embedded {sorter.embed(todo, a.batch or store.batch_id())} photos")


def cmd_fetch(a):
    missing = ingest.fetch(sorter.resolve(a.ids))
    if missing:
        print("could not fetch:", " ".join(missing))


def cmd_sheet(a):
    pids = sorter.resolve(a.ids)
    print(sorter.sheet(pids, Path(a.out), cols=a.cols, cell=a.cell, title=a.title))


def cmd_similar(a):
    photos = store.photos()
    for pid in sorter.resolve(a.ids):
        print(pid, photos[pid].get("taken"))
        for other, s in sorter.similar(pid, a.k):
            r = photos[other]
            print(f"  {s:.3f}  {other}  {r.get('taken', '')[:10]}  {r['status']:8} {r.get('work') or ''}")


def cmd_propose(a):
    proposal = sorter.propose()
    sorter.write_review(proposal, Path(a.out) if a.out else config.REVIEW)
    g = proposal["groups"]
    print(f"{len(g)} groups ({sum(len(x['photos']) for x in g)} photos), {len(proposal['singles'])} singles")


def cmd_apply(a):
    summary = publish.apply(a.decisions)
    print(json.dumps(summary, indent=1))
    if summary["pending"]:
        print("drawings wait for VAULT_PASSWORD before they go into the sketchbook:", ", ".join(summary["pending"]))


def cmd_publish_pending(a):
    if not vault.password():
        raise SystemExit("VAULT_PASSWORD is not set")
    print(f"moved {publish.publish_pending()} photos into the sketchbook")


def cmd_render(a):
    pid = sorter.resolve([a.id])[0]
    year = int(store.photos()[pid]["taken"][:4])
    crop = [float(v) for v in a.crop.split(",")] if a.crop else None
    publish.render(pid, a.out, year, crop, a.rotate)
    print(a.out)


def cmd_rekey(a):
    import os

    new = os.environ.get("NEW_VAULT_PASSWORD")
    if not new:
        raise SystemExit("set NEW_VAULT_PASSWORD (and VAULT_PASSWORD to the current one)")
    vault.Vault(create=False).rekey(new)
    print("sketchbook re-encrypted with the new password")


def cmd_comments(a):
    if a.approve or a.reject:
        replies = dict(r.split("=", 1) for r in a.reply or [])
        comments.decide(a.approve or [], a.reject or [], replies)
        print(f"approved {len(a.approve or [])}, rejected {len(a.reject or [])}")
        return
    if not config.SETTINGS.get("comments_sheet"):
        print("no comments sheet configured (archive/settings.json: comments_sheet)")
        return
    new = comments.new_comments()
    print(json.dumps(new, indent=1, ensure_ascii=False) if new else "no new comments")


def cmd_info(a):
    print(sorter.info(sorter.resolve(a.ids)))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m pipeline", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="counts of photos, sources and works").set_defaults(fn=cmd_status)
    s = sub.add_parser("sync", help="read new files from the Drive folders, then embed the new photos")
    s.add_argument("--max-sources", type=int, help="read at most this many new Drive files")
    s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("embed", help="embed photos that have no embedding yet")
    s.add_argument("--batch")
    s.set_defaults(fn=cmd_embed)
    s = sub.add_parser("fetch", help="bring full-size originals back into the cache")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_fetch)
    s = sub.add_parser("sheet", help="contact sheet of the given photos")
    s.add_argument("ids", nargs="+")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--cols", type=int, default=6)
    s.add_argument("--cell", type=int, default=300)
    s.add_argument("--title")
    s.set_defaults(fn=cmd_sheet)
    s = sub.add_parser("similar", help="most similar photos to each given photo")
    s.add_argument("ids", nargs="+")
    s.add_argument("-k", type=int, default=8)
    s.set_defaults(fn=cmd_similar)
    s = sub.add_parser("propose", help="group the new photos and write review sheets")
    s.add_argument("-o", "--out", help=f"folder for the review files (default {config.REVIEW})")
    s.set_defaults(fn=cmd_propose)
    s = sub.add_parser("apply", help="apply a review's decisions (YAML) and publish")
    s.add_argument("decisions")
    s.set_defaults(fn=cmd_apply)
    sub.add_parser("publish-pending", help="move drawings that waited for VAULT_PASSWORD into the sketchbook"
                   ).set_defaults(fn=cmd_publish_pending)
    s = sub.add_parser("render", help="watermarked web copy of one photo")
    s.add_argument("id")
    s.add_argument("out")
    s.add_argument("--crop", help="x0,y0,x1,y1 as fractions of the photo, e.g. 0.05,0.1,0.95,0.9")
    s.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270], help="degrees clockwise")
    s.set_defaults(fn=cmd_render)
    sub.add_parser("rekey", help="change the sketchbook password").set_defaults(fn=cmd_rekey)
    s = sub.add_parser("comments", help="list new visitor comments, or approve/reject them by key")
    s.add_argument("--approve", nargs="*")
    s.add_argument("--reject", nargs="*")
    s.add_argument("--reply", nargs="*", help="key=text replies shown under approved comments")
    s.set_defaults(fn=cmd_comments)
    s = sub.add_parser("info", help="the archive record of each given photo")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_info)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
