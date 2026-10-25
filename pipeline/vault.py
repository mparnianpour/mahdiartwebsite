"""The password-protected sketchbook.

The repository is public, so hiding a page behind a password prompt would
not protect the images: anyone could open the files directly. Instead every
sketch and drawing is encrypted (AES-256-GCM) before it is committed, with a
key derived from the password (PBKDF2-SHA256). The sketchbook page asks for
the password and decrypts the files in the visitor's browser
(assets/js/vault.js). Without the password the files are noise.

Files
  _data/vault.json        salt, iteration count and a check value (public)
  assets/vault/index.bin  encrypted list of drawings with dates and notes
  assets/vault/<id>.bin   encrypted watermarked image (1600 px)
  assets/vault/<id>.t.bin encrypted thumbnail (480 px)

The password comes from the VAULT_PASSWORD environment variable.
"""
import base64
import io
import json
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config, store

ITERATIONS = 600_000
CHECK = b"mahdi-parnianpour-sketchbook"


class VaultError(RuntimeError):
    pass


def password():
    return os.environ.get("VAULT_PASSWORD") or None


def _derive(pw, salt, iterations):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations).derive(pw.encode())


class Vault:
    def __init__(self, pw=None, create=True):
        pw = pw or password()
        if not pw:
            raise VaultError("VAULT_PASSWORD is not set")
        meta = json.loads(config.VAULT_META.read_text()) if config.VAULT_META.exists() else None
        if meta is None:
            if not create:
                raise VaultError("no vault yet")
            salt = secrets.token_bytes(16)
            self.key = _derive(pw, salt, ITERATIONS)
            meta = {"version": 1, "iterations": ITERATIONS, "salt": base64.b64encode(salt).decode(),
                    "check": base64.b64encode(self.encrypt(CHECK)).decode(), "drawings": 0, "photos": 0}
            self.meta = meta
            self.save_index({"entries": {}})
        else:
            self.meta = meta
            self.key = _derive(pw, base64.b64decode(meta["salt"]), meta["iterations"])
            try:
                ok = self.decrypt(base64.b64decode(meta["check"])) == CHECK
            except InvalidTag:
                ok = False
            if not ok:
                raise VaultError("VAULT_PASSWORD does not match the existing sketchbook")

    def encrypt(self, data):
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self.key).encrypt(nonce, data, None)

    def decrypt(self, blob):
        return AESGCM(self.key).decrypt(blob[:12], blob[12:], None)

    def index(self):
        path = config.VAULT_DIR / "index.bin"
        if not path.exists():
            return {"entries": {}}
        return json.loads(self.decrypt(path.read_bytes()))

    def save_index(self, idx):
        config.VAULT_DIR.mkdir(parents=True, exist_ok=True)
        data = json.dumps(idx, ensure_ascii=False, sort_keys=True).encode()
        (config.VAULT_DIR / "index.bin").write_bytes(self.encrypt(data))
        self.meta["drawings"] = len(idx["entries"])
        self.meta["photos"] = sum(len(e["photos"]) for e in idx["entries"].values())
        self.meta["updated"] = store.now()[:10]
        config.VAULT_META.parent.mkdir(parents=True, exist_ok=True)
        config.VAULT_META.write_text(json.dumps(self.meta, indent=1) + "\n")

    def has_image(self, pid):
        return (config.VAULT_DIR / f"{pid}.bin").exists()

    def put_image(self, pid, img, year):
        """Encrypt a watermarked PIL image and its thumbnail."""
        from .publish import protect_mod

        pm = protect_mod()
        sizes = []
        for suffix, side in ((".bin", 1600), (".t.bin", 480)):
            out = pm.protect(img, year, "tiled", None, side)
            buf = io.BytesIO()
            out.save(buf, "JPEG", quality=82, optimize=True, progressive=True)
            (config.VAULT_DIR / f"{pid}{suffix}").write_bytes(self.encrypt(buf.getvalue()))
            sizes.append(out.size)
        return sizes[0]

    def image(self, pid, thumb=False):
        return self.decrypt((config.VAULT_DIR / f"{pid}{'.t' if thumb else ''}.bin").read_bytes())

    def rekey(self, new_pw):
        """Re-encrypt everything under a new password (and a new salt)."""
        idx = self.index()
        blobs = {p.name: self.decrypt(p.read_bytes()) for p in config.VAULT_DIR.glob("*.bin") if p.name != "index.bin"}
        salt = secrets.token_bytes(16)
        self.key = _derive(new_pw, salt, ITERATIONS)
        self.meta.update(salt=base64.b64encode(salt).decode(), iterations=ITERATIONS,
                         check=base64.b64encode(self.encrypt(CHECK)).decode())
        for name, data in blobs.items():
            (config.VAULT_DIR / name).write_bytes(self.encrypt(data))
        self.save_index(idx)
