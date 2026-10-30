"""Paths and settings shared by the pipeline commands."""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The archive's memory. Committed, so every batch continues from the last.
ARCHIVE = REPO / "archive"
SETTINGS = json.loads((ARCHIVE / "settings.json").read_text())
PHOTOS = ARCHIVE / "photos.json"      # every photo seen: when it was taken, where it came from, where it went
SOURCES = ARCHIVE / "sources.json"    # Drive files already read (Takeout zips and loose photos)
WORKS = ARCHIVE / "works.json"        # public paintings: stages in order, with notes
DRAFTS = ARCHIVE / "drafts.json"      # works grouped in review but not yet published
EMBEDDINGS = ARCHIVE / "embeddings"   # image embeddings, one file per batch
BATCHES = ARCHIVE / "batches"         # log of each batch

# Site paths.
WORK_PAGES = REPO / "_works"
WORK_IMAGES = REPO / "assets" / "img" / "works"
VAULT_DIR = REPO / "assets" / "vault"
VAULT_META = REPO / "_data" / "vault.json"
COMMENTS_DATA = REPO / "_data" / "comments.yml"
PROTECT_SCRIPT = REPO / "tools" / "protect_image.py"

# Working files. Never committed: full-size photos stay out of the repository.
CACHE = Path(os.environ.get("PIPELINE_CACHE", Path.home() / ".cache" / "mahdiart-pipeline"))
ORIGINALS = CACHE / "originals"
THUMBS = CACHE / "thumbs"
REVIEW = CACHE / "review"
DOWNLOADS = CACHE / "downloads"
MODEL = CACHE / "models" / "dinov2-small.onnx"
