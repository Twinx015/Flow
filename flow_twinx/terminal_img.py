import base64
import hashlib
import math
import pathlib
import shutil
import sys
import urllib.request

CELL_W = 10
CELL_H = 20
CHUNK = 4096
THUMB_CACHE = pathlib.Path.home() / ".flow/downloads/.cache"


def detect_kitty() -> bool:
    import os

    if os.environ.get("FLOW_NO_IMG", "").strip().lower() in ("1", "true", "yes"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    if "kitty" in (os.environ.get("TERM") or "").lower():
        return True
    if os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    if os.environ.get("WEZTERM_EXECUTABLE"):
        return True
    return False


def resolve_source(thumb):
    t = (thumb or "").strip()
    if not t:
        return None
    if t.startswith(("http://", "https://")):
        return _download(t)
    home = pathlib.Path.home()
    if t.startswith("/downloads/") or t.startswith("/cache/") or t.startswith("/.flow"):
        p = home / ".flow" / t.lstrip("/")
    else:
        p = pathlib.Path(t).expanduser()
    if p.is_file():
        return p
    return None


def _download(url):
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(url.encode()).hexdigest() + ".jpg"
    p = THUMB_CACHE / name
    if p.is_file():
        return p
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if data:
            p.write_bytes(data)
            return p
    except Exception:
        pass
    return None


def prepare(path, max_rows=5, max_cols=None):
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return None
    if max_cols is None:
        term_w = shutil.get_terminal_size().columns
        max_cols = max(10, min(24, term_w - 30))
    scale = min(max_cols * CELL_W / w, max_rows * CELL_H / h)
    pw = max(1, int(w * scale))
    ph = max(1, int(h * scale))
    cols = math.ceil(pw / CELL_W)
    rows = math.ceil(ph / CELL_H)
    return pw, ph, cols, rows


def render(path, pw, ph, cols, rows):
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB").resize((pw, ph), Image.LANCZOS)
        buf = _png_bytes(im)

    b64 = base64.standard_b64encode(buf).decode()
    parts = []
    sent = 0
    total = len(b64)
    while sent < total:
        chunk = b64[sent : sent + CHUNK]
        more = 1 if sent + CHUNK < total else 0
        if sent == 0:
            ctrl = f"a=T,f=100,s={pw},v={ph},c={cols},r={rows},m={more}"
        else:
            ctrl = f"m={more}"
        parts.append(f"\x1b_G{ctrl};{chunk}\x1b\\")
        sent += CHUNK
    if total == 0:
        parts.append(f"\x1b_Ga=T,f=100,s={pw},v={ph},c={cols},r={rows};\x1b\\")
    sys.stdout.write("".join(parts))
    sys.stdout.flush()


def _png_bytes(im):
    import io

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
