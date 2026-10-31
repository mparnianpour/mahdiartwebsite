"""Read-only Google Drive access with only the standard library and `cryptography`.

Credentials come from the GOOGLE_CREDENTIALS environment variable, holding
either the JSON itself or a path to it, in one of two formats:

* a service-account key ("type": "service_account"). The account only sees
  the folders Mahdi shares with it. This is what scheduled runs use.
* an authorized-user token ("type": "authorized_user", with client_id,
  client_secret and refresh_token), e.g. from a one-off sign-in.
"""
import base64
import io
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3/"
TOKEN_URI = "https://oauth2.googleapis.com/token"
FOLDER = "application/vnd.google-apps.folder"

_token = {"value": None, "expires": 0.0}


class DriveError(RuntimeError):
    pass


def _credentials():
    raw = os.environ.get("GOOGLE_CREDENTIALS", "").strip()
    if not raw:
        raise DriveError("GOOGLE_CREDENTIALS is not set; see pipeline/PLAYBOOK.md (Setup).")
    if not raw.startswith("{"):
        if os.path.exists(raw):
            with open(raw) as f:
                raw = f.read()
        else:  # the key file's contents, base64-encoded onto one line
            raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise DriveError(f"token request failed: HTTP {e.code} {e.read().decode()[:300]}") from None


def token():
    if _token["value"] and time.time() < _token["expires"] - 120:
        return _token["value"]
    c = _credentials()
    if c.get("type") == "service_account":
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(time.time())
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": c.get("private_key_id", "")}).encode())
        body = _b64(json.dumps({"iss": c["client_email"], "scope": SCOPE, "aud": TOKEN_URI,
                                "iat": now, "exp": now + 3600}).encode())
        key = serialization.load_pem_private_key(c["private_key"].encode(), password=None)
        sig = _b64(key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()))
        r = _post(TOKEN_URI, {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                              "assertion": f"{head}.{body}.{sig}"})
    elif c.get("type") == "authorized_user":
        r = _post(TOKEN_URI, {"grant_type": "refresh_token", "refresh_token": c["refresh_token"],
                              "client_id": c["client_id"], "client_secret": c["client_secret"]})
    else:
        raise DriveError("GOOGLE_CREDENTIALS must be a service-account key or an authorized-user token")
    _token.update(value=r["access_token"], expires=time.time() + r.get("expires_in", 3600))
    return _token["value"]


def _open(url, headers=None, timeout=120):
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token(), **(headers or {})})
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise DriveError(f"Drive request failed: HTTP {e.code} {e.read().decode()[:400]}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def get(path, **params):
    with _open(API + path + "?" + urllib.parse.urlencode(params)) as r:
        return json.load(r)


def list_files(q, fields="id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents"):
    out, page = [], None
    while True:
        params = {"q": q, "fields": f"nextPageToken,files({fields})", "pageSize": 1000,
                  "includeItemsFromAllDrives": "true", "supportsAllDrives": "true"}
        if page:
            params["pageToken"] = page
        r = get("files", **params)
        out += r.get("files", [])
        page = r.get("nextPageToken")
        if not page:
            return out


def find_folder(name_or_id):
    """A folder by its Drive ID or by name (the most recently changed, if several match)."""
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", name_or_id):
        try:
            f = get(f"files/{name_or_id}", fields="id,name,mimeType", supportsAllDrives="true")
            if f.get("mimeType") == FOLDER:
                return f
        except DriveError:
            pass
    name = name_or_id.replace("\\", "\\\\").replace("'", "\\'")
    found = list_files(f"name = '{name}' and mimeType = '{FOLDER}' and trashed = false", "id,name,modifiedTime")
    return max(found, key=lambda f: f["modifiedTime"]) if found else None


def walk(folder_id):
    """Every file under a folder, searching subfolders too."""
    out, todo, seen = [], [folder_id], set()
    while todo:
        fid = todo.pop()
        if fid in seen:
            continue
        seen.add(fid)
        for f in list_files(f"'{fid}' in parents and trashed = false"):
            (todo.append(f["id"]) if f["mimeType"] == FOLDER else out.append(f))
    return out


def download(file_id, dest):
    tmp = f"{dest}.part"
    with _open(f"{API}files/{file_id}?alt=media&supportsAllDrives=true", timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 8 << 20)
    os.replace(tmp, dest)


def export_csv(file_id):
    """A Google Sheet's first tab as CSV text."""
    with _open(f"{API}files/{file_id}/export?mimeType=text/csv") as r:
        return r.read().decode("utf-8")


class RangeFile(io.RawIOBase):
    """A Drive file opened for random access, fetching only the byte ranges read.

    Used to pull single photos back out of a Takeout zip without downloading it whole.
    """

    def __init__(self, file_id, size):
        self.file_id, self.size, self.pos = file_id, int(size), 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        with _open(f"{API}files/{self.file_id}?alt=media&supportsAllDrives=true",
                   {"Range": f"bytes={self.pos}-{end}"}) as r:
            data = r.read()
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)
