"""Find photos of the same painting.

Every photo gets a DINOv2 image embedding. Photos whose embeddings are close
are likely the same painting, whether they were taken minutes or months
apart; photos close in time are given a lower bar, because consecutive
stages of one painting can change a lot. The result is a set of proposed
groups and contact sheets that Claude reviews before anything is published.
"""
import hashlib
import json
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config, ingest, store

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
FONT = config.REPO / "tools" / "fonts" / "IBMPlexMono-Medium.ttf"

# Thresholds, calibrated on the 2023-2025 albums. Mahdi's works share a style,
# so embedding similarity alone puts different paintings as close (0.80-0.85)
# as stages of one painting. Candidates found by similarity are therefore
# confirmed by matching local features (SIFT) under a perspective transform:
# unrelated works give at most ~14 consistent matches, the same work 25 to
# several hundred.
NEIGHBOURS = 12        # candidates per new photo, from embedding similarity
NEARBY_SIM = 0.70      # also compare photos taken within NEARBY_DAYS at least this similar
NEARBY_DAYS = 2
SAME_WORK = 25         # consistent matches for "the same work"
MAYBE_SAME = 15        # weaker evidence, used only between photos close in time and similarity
MAYBE_SIM, MAYBE_DAYS = 0.80, 30
DUPLICATE = 150        # this many matches within DUPLICATE_SECONDS: the same shot taken twice
DUPLICATE_SECONDS = 600
HUB_DEGREE, HUB_DAYS = 5, 3  # a photo matched to this many others on this many days is a studio view


# --- embeddings --------------------------------------------------------------

def _model():
    import onnxruntime as ort

    if not config.MODEL.exists():
        config.MODEL.parent.mkdir(parents=True, exist_ok=True)
        tmp = config.MODEL.with_suffix(".part")
        urllib.request.urlretrieve(config.SETTINGS["model_url"], tmp)
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        if digest != config.SETTINGS["model_sha256"]:
            tmp.unlink()
            raise RuntimeError(f"model checksum mismatch: {digest}")
        tmp.replace(config.MODEL)
    return ort.InferenceSession(str(config.MODEL), providers=["CPUExecutionProvider"])


def _pixels(path):
    """Pad to a square with the image's mean colour (keeping the whole composition), then 224 px."""
    with Image.open(path) as im:
        im = im.convert("RGB")
    w, h = im.size
    s = max(w, h)
    fill = tuple(int(c) for c in np.asarray(im.resize((32, 32))).reshape(-1, 3).mean(0))
    sq = Image.new("RGB", (s, s), fill)
    sq.paste(im, ((s - w) // 2, (s - h) // 2))
    x = np.asarray(sq.resize((224, 224), Image.BICUBIC), np.float32) / 255.0
    return ((x - MEAN) / STD).transpose(2, 0, 1)


def _normalise(v):
    """Unit-normalise the CLS half and the patch-mean half separately, then the whole."""
    a, b = v[:, :384], v[:, 384:]
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return np.concatenate([a, b], axis=1) / np.sqrt(2)


def embed(pids, batch, log=print):
    """Compute embeddings for these photos and save them as archive/embeddings/<batch>.npz."""
    have = set(load_embeddings()[0])
    pids = [p for p in pids if p not in have]
    if not pids:
        return 0
    sess = _model()
    out, done = [], []
    for i in range(0, len(pids), 16):
        chunk = [p for p in pids[i:i + 16] if ingest.thumb(p)]
        if not chunk:
            continue
        x = np.stack([_pixels(ingest.thumb(p)) for p in chunk])
        out.append(sess.run(None, {"pixel_values": x})[0])
        done += chunk
        log(f"  embedded {len(done)}/{len(pids)}")
    vec = _normalise(np.concatenate(out)).astype(np.float16)
    config.EMBEDDINGS.mkdir(parents=True, exist_ok=True)
    path = config.EMBEDDINGS / f"{batch}.npz"
    if path.exists():  # a second embed in the same batch: add to it
        old = np.load(path)
        done, vec = list(old["ids"]) + done, np.concatenate([old["vec"], vec])
    np.savez_compressed(path, ids=np.array(done), vec=vec)
    return len(pids)


def load_embeddings():
    ids, vecs = [], []
    for p in sorted(config.EMBEDDINGS.glob("*.npz")):
        d = np.load(p)
        ids += [str(i) for i in d["ids"]]
        vecs.append(d["vec"].astype(np.float32))
    if not ids:
        return [], np.zeros((0, 768), np.float32)
    return ids, np.concatenate(vecs)


# --- contact sheets ----------------------------------------------------------

def _font(size):
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default(size)


def sheet(pids, out, cols=6, cell=300, title=None, captions=None):
    """A grid of thumbnails labelled with each photo's short id and date."""
    photos = store.photos()
    rows = max(1, (len(pids) + cols - 1) // cols)
    head = 34 if title else 0
    S = Image.new("RGB", (cols * cell, head + rows * (cell + 40)), "white")
    d = ImageDraw.Draw(S)
    f, fs = _font(15), _font(20)
    if title:
        d.text((8, 6), title, fill="black", font=fs)
    for k, pid in enumerate(pids):
        x, y = (k % cols) * cell, head + (k // cols) * (cell + 40)
        t = ingest.thumb(pid)
        if t:
            with Image.open(t) as im:
                im = im.convert("RGB")
                im.thumbnail((cell - 8, cell - 8))
                S.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        rec = photos.get(pid, {})
        d.text((x + 6, y + cell), f"{k + 1}  {pid[:6]}  {(rec.get('taken') or '')[:10]}", fill="black", font=f)
        if captions and captions.get(pid):
            d.text((x + 6, y + cell + 18), captions[pid][:34], fill=(150, 30, 30), font=f)
    out.parent.mkdir(parents=True, exist_ok=True)
    S.save(out, quality=82)
    return out


def overview(groups, out, per_row=8, cell=170):
    """One row per group (name, dates, first photos), to sort a whole batch from a few images."""
    photos = store.photos()
    f = _font(15)
    label_w = 150
    S = Image.new("RGB", (label_w + per_row * cell, len(groups) * (cell + 8)), "white")
    d = ImageDraw.Draw(S)
    for r, (name, pids) in enumerate(groups):
        y = r * (cell + 8)
        first, last = (photos[pids[0]].get("taken") or "")[:10], (photos[pids[-1]].get("taken") or "")[:10]
        d.text((6, y + 8), name, fill="black", font=_font(20))
        d.text((6, y + 38), f"{len(pids)} photos", fill="black", font=f)
        d.text((6, y + 58), first, fill=(90, 90, 90), font=f)
        if last != first:
            d.text((6, y + 76), last, fill=(90, 90, 90), font=f)
        shown = pids if len(pids) <= per_row else pids[:per_row - 1] + [pids[-1]]
        for k, pid in enumerate(shown):
            t = ingest.thumb(pid)
            if t:
                with Image.open(t) as im:
                    im = im.convert("RGB")
                    im.thumbnail((cell - 6, cell - 6))
                    S.paste(im, (label_w + k * cell + (cell - im.width) // 2, y + (cell - im.height) // 2))
        if len(pids) > per_row:
            d.text((label_w + (per_row - 1) * cell - 30, y + cell // 2), "…", fill="black", font=_font(28))
        d.line([(0, y + cell + 4), (S.width, y + cell + 4)], fill=(220, 220, 220))
    out.parent.mkdir(parents=True, exist_ok=True)
    S.save(out, quality=80)
    return out


def resolve(prefixes, photos=None):
    """Full ids from unique prefixes (at least 6 characters)."""
    photos = photos or store.photos()
    out = []
    for p in prefixes:
        hits = [k for k in photos if k.startswith(p)]
        if len(p) < 6 or len(hits) != 1:
            raise SystemExit(f"'{p}' does not match exactly one photo")
        out.append(hits[0])
    return out


def similar(pid, k=8):
    """The k photos most similar to this one: [(id, similarity)]."""
    ids, vec = load_embeddings()
    i = ids.index(pid)
    s = vec @ vec[i]
    order = np.argsort(-s)
    return [(ids[j], float(s[j])) for j in order[1:k + 1]]


def info(pids):
    photos = store.photos()
    return json.dumps({p: photos[p] for p in pids}, indent=1, ensure_ascii=False)


# --- grouping ----------------------------------------------------------------

class Matcher:
    """Counts local features that agree on one perspective transform between two photos."""

    def __init__(self):
        import cv2

        self.cv2 = cv2
        self.sift = cv2.SIFT_create(nfeatures=1500)
        self.bf = cv2.BFMatcher()
        self.cache = {}

    def features(self, pid):
        if pid not in self.cache:
            path = ingest.thumb(pid)
            g = self.cv2.imread(str(path), self.cv2.IMREAD_GRAYSCALE) if path else None
            self.cache[pid] = self.sift.detectAndCompute(g, None) if g is not None else ([], None)
        return self.cache[pid]

    def inliers(self, a, b):
        cv2 = self.cv2
        ka, da = self.features(a)
        kb, db = self.features(b)
        if da is None or db is None or len(ka) < 8 or len(kb) < 8:
            return 0
        good = [m for m, n in (p for p in self.bf.knnMatch(da, db, k=2) if len(p) == 2)
                if m.distance < 0.75 * n.distance]
        if len(good) < 8:
            return 0
        src = np.float32([ka[m.queryIdx].pt for m in good])
        dst = np.float32([kb[m.trainIdx].pt for m in good])
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
        return int(mask.sum()) if mask is not None else 0


def propose(log=print):
    """Group the photos waiting for review, and link them to works already published.

    Returns a dict with "groups" (lists of new photo ids, in time order, each
    with the evidence that joined them and any existing work they continue)
    and "singles" (new photos not linked to anything).
    """
    photos = store.photos()
    ids, vec = load_embeddings()
    pos = {p: i for i, p in enumerate(ids)}
    new = [p for p in ids if photos[p]["status"] == "new"]
    gone = ingest.fetch([p for p in new if not (config.THUMBS / f"{p}.jpg").exists()], log)
    if gone:
        log(f"{len(gone)} waiting photos could not be fetched from Drive (source deleted?)")
    anchors = {p for p in ids if photos[p].get("work") and photos[p]["status"] in ("published", "private")}
    pool = [p for p in ids if p in anchors or photos[p]["status"] == "new"]
    pidx = np.array([pos[p] for p in pool])
    ts = {p: photos[p].get("ts") or 0 for p in pool}

    sims = vec[[pos[p] for p in new]] @ vec[pidx].T
    pairs = set()
    for r, a in enumerate(new):
        order = np.argsort(-sims[r])
        for j in order[:NEIGHBOURS + 1]:
            b = pool[j]
            if b != a:
                pairs.add(tuple(sorted((a, b))))
        for j in np.where(sims[r] >= NEARBY_SIM)[0]:
            b = pool[j]
            if b != a and abs(ts[a] - ts[b]) <= NEARBY_DAYS * 86400:
                pairs.add(tuple(sorted((a, b))))
    log(f"checking {len(pairs)} candidate pairs among {len(new)} new photos")

    m = Matcher()
    edges, dupes = [], []
    for k, (a, b) in enumerate(sorted(pairs)):
        n = m.inliers(a, b)
        sim = float(vec[pos[a]] @ vec[pos[b]])
        days = abs(ts[a] - ts[b]) / 86400
        if n >= SAME_WORK or (n >= MAYBE_SAME and sim >= MAYBE_SIM and days <= MAYBE_DAYS):
            edges.append((a, b, n, round(sim, 3)))
            if n >= DUPLICATE and days * 86400 <= DUPLICATE_SECONDS:
                dupes.append((a, b))
        if k and k % 2000 == 0:
            log(f"  {k}/{len(pairs)}")

    parent = {p: p for p in new}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Studio views show several works at once and would chain them all
    # together; a photo matched to many photos taken on different days is
    # kept out of the grouping and reported on its own.
    degree, days_seen = {}, {}
    for a, b, n, sim in edges:
        for x, y in ((a, b), (b, a)):
            degree[x] = degree.get(x, 0) + 1
            days_seen.setdefault(x, set()).add((photos[y].get("taken") or "")[:10])
    hubs = {p for p in degree if degree[p] >= HUB_DEGREE and len(days_seen[p]) >= HUB_DAYS}

    links = {}
    for a, b, n, sim in edges:
        if a in parent and b in parent and a not in hubs and b not in hubs:
            parent[find(a)] = find(b)
    groups = {}
    for p in new:
        groups.setdefault(find(p), []).append(p)
    for a, b, n, sim in edges:  # new photo -> existing work
        for x, y in ((a, b), (b, a)):
            if x in parent and y in anchors and x not in hubs:
                root = find(x)
                w = photos[y]["work"]
                best = links.setdefault(root, {}).get(w)
                if not best or n > best[1]:
                    links[root][w] = (y, n)

    # A new photo matching a published one this closely is the same photo
    # (or the same moment), e.g. a stage that was added to the site by hand.
    on_site = {}
    for a, b, n, sim in edges:
        for x, y in ((a, b), (b, a)):
            if x in parent and y in anchors and n >= DUPLICATE and n > on_site.get(x, ("", 0))[1]:
                on_site[x] = (y, n)

    out = {"groups": [], "singles": [], "studio_views": sorted(hubs & set(new), key=lambda p: ts[p]),
           "already_published": {x: {"photo": y, "work": photos[y]["work"], "matches": n}
                                 for x, (y, n) in on_site.items()}}
    for root, members in groups.items():
        members.sort(key=lambda p: ts[p])
        if len(members) == 1 and members[0] in hubs:
            continue
        if len(members) == 1 and root not in links:
            out["singles"].append(members[0])
            continue
        mset = set(members)
        out["groups"].append({
            "photos": members,
            "first": photos[members[0]].get("taken"), "last": photos[members[-1]].get("taken"),
            "evidence": [[a, b, n] for a, b, n, _ in edges if a in mset and b in mset],
            "duplicates": [[a, b] for a, b in dupes if a in mset and b in mset],
            "continues": {w: {"photo": y, "matches": n} for w, (y, n) in links.get(root, {}).items()},
        })
    out["groups"].sort(key=lambda g: ts[g["photos"][0]])
    out["singles"].sort(key=lambda p: ts[p])
    return out


def write_review(proposal, folder, log=print):
    """Contact sheets and a summary for Claude to review."""
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*"):
        old.unlink()
    photos = store.photos()
    lines = [f"# Review: {sum(len(g['photos']) for g in proposal['groups'])} photos in "
             f"{len(proposal['groups'])} proposed groups, {len(proposal['singles'])} singles", ""]
    for n, g in enumerate(proposal["groups"], 1):
        name = f"G{n:03d}"
        cont = "; ".join(f"continues **{w}** (matches {v['photo'][:6]}, {v['matches']} points)"
                         for w, v in g["continues"].items())
        lines.append(f"## {name}  {len(g['photos'])} photos  {g['first'][:10]} → {g['last'][:10]}  {cont}")
        lines.append("ids: " + " ".join(p[:6] for p in g["photos"]))
        if g["duplicates"]:
            lines.append("same shot twice: " + ", ".join(f"{a[:6]}={b[:6]}" for a, b in g["duplicates"]))
        lines.append("")
        anchors = [v["photo"] for v in g["continues"].values()]
        sheet(anchors + g["photos"], folder / f"{name}.jpg", cols=6, cell=260,
              title=f"{name}: {g['first'][:10]} to {g['last'][:10]}",
              captions={a: f"existing: {photos[a]['work']}" for a in anchors})
    already = proposal.get("already_published", {})
    if already:
        lines.append("## Already on the site")
        lines.append("These match a published image almost exactly; usually skip them as "
                     "\"already on the site as <work>\":")
        for x, v in sorted(already.items(), key=lambda kv: kv[1]["work"]):
            lines.append(f"- {x[:6]} = {v['photo'][:6]} in {v['work']} ({v['matches']} points)")
        lines.append("")
    views = proposal.get("studio_views", [])
    for k in range(0, len(views), 30):
        chunk = views[k:k + 30]
        name = f"V{k // 30 + 1:03d}"
        lines.append(f"## {name}  studio views (matched to many photos on different days)")
        lines.append("ids: " + " ".join(p[:6] for p in chunk))
        lines.append("")
        sheet(chunk, folder / f"{name}.jpg", cols=6, cell=260, title=f"{name}: studio views")
    singles = proposal["singles"]
    for k in range(0, len(singles), 30):
        chunk = singles[k:k + 30]
        name = f"S{k // 30 + 1:03d}"
        lines.append(f"## {name}  singles {photos[chunk[0]]['taken'][:10]} → {photos[chunk[-1]]['taken'][:10]}")
        lines.append("ids: " + " ".join(p[:6] for p in chunk))
        lines.append("")
        sheet(chunk, folder / f"{name}.jpg", cols=6, cell=260, title=f"{name}: photos not linked to others")
    named = [(f"G{n:03d}", g["photos"]) for n, g in enumerate(proposal["groups"], 1)]
    for k in range(0, len(named), 10):
        overview(named[k:k + 10], folder / f"O{k // 10 + 1:03d}.jpg")
    lines.insert(1, "Start with the overview sheets O*.jpg (one row per group), then open a group's own "
                    "sheet G*.jpg when you need to see every photo.\n")
    (folder / "proposals.md").write_text("\n".join(lines) + "\n")
    (folder / "proposals.json").write_text(json.dumps(proposal, indent=1))
    log(f"review files in {folder}")
