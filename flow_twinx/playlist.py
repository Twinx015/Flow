import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import time

PLAYLISTS_DIR = pathlib.Path.home() / ".flow/playlists"
PLAYLISTS_FILE = pathlib.Path.home() / ".flow/playlists.json"
LEGACY_BAK = pathlib.Path.home() / ".flow/playlists.json.bak"
PLAYLIST_DIR = pathlib.Path.home() / ".flow/playlist"

_SCHEMA_VERSION = 2
_LOCK_FILE = PLAYLISTS_DIR / ".lock"

_SUBCOMMANDS = {
    "add": "add",
    "a": "add",
    "remove": "remove",
    "r": "remove",
    "rm": "remove",
    "list": "list",
    "l": "list",
    "ls": "list",
    "create": "create",
    "c": "create",
    "new": "create",
    "delete": "delete",
    "d": "delete",
    "del": "delete",
    "rename": "rename",
    "rn": "rename",
    "move": "move",
    "mv": "move",
    "duplicate": "duplicate",
    "dup": "duplicate",
    "copy": "duplicate",
    "merge": "merge",
    "sort": "sort",
    "clear": "clear",
    "dedupe": "dedupe",
    "info": "info",
    "export": "export",
    "import": "import",
    "imp": "import",
    "download": "download",
    "dl": "download",
}

RESERVED_NAMES = {"liked"}


def resolve_subcmd(word):
    return _SUBCOMMANDS.get(word, word)


def _slugify(name):
    s = re.sub(r"[^\w\s-]", "", name.lower(), flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    if not s:
        s = hashlib.sha1(name.encode()).hexdigest()[:12]
    return s[:64]


@contextlib.contextmanager
def _locked():
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(_LOCK_FILE, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_write_json(path, obj):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _load_file(path):
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("tracks"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _scan():
    """Return {display_name_lower: (display_name, path)} for all playlists."""
    out = {}
    if not PLAYLISTS_DIR.exists():
        return out
    for p in sorted(PLAYLISTS_DIR.glob("*.json")):
        data = _load_file(p)
        if not data:
            continue
        name = data.get("name") or p.stem
        out.setdefault(name.lower(), (name, p))
    return out


def _migrate_legacy_locked():
    """Convert legacy ~/.flow/playlists.json to the per-file store. Under lock."""
    if not PLAYLISTS_FILE.exists():
        return
    try:
        legacy = json.loads(PLAYLISTS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(legacy, dict) or not legacy:
        os.replace(PLAYLISTS_FILE, LEGACY_BAK)
        return
    existing = {n for n, _ in _scan().values()}
    for name, songs in legacy.items():
        if name in existing or not isinstance(songs, list):
            continue
        tracks = [
            make_track(
                title=s.get("title", ""),
                ref=s.get("url", ""),
                video_id=s.get("video_id", ""),
            )
            for s in songs
            if isinstance(s, dict)
        ]
        _write_new(name, tracks)
    os.replace(PLAYLISTS_FILE, LEGACY_BAK)


def _ensure_store():
    if PLAYLISTS_FILE.exists() or not PLAYLISTS_DIR.exists():
        with _locked():
            _migrate_legacy_locked()


def _auto_thumb(thumb, video_id):
    """Resolve an existing cached thumbnail path for a video_id."""
    if thumb:
        return str(thumb)
    if not video_id:
        return None
    try:
        from . import library

        p = pathlib.Path(library.thumbnail_path(video_id))
        if p.exists():
            return str(p)
    except Exception:
        pass
    return None


def make_track(
    title="", ref="", video_id="", duration=0, source=None, local_path=None, thumb=None
):
    ref = str(ref or "")
    if source is None:
        source = "youtube" if ref.startswith(("http://", "https://")) else "local"
    tid = video_id or (hashlib.sha1(ref.encode()).hexdigest()[:12] if ref else "")
    thumb_path = _auto_thumb(thumb, video_id)
    return {
        "id": tid,
        "title": title or "Unknown",
        "source": source,
        "ref": ref,
        "local_path": str(local_path) if local_path else None,
        "duration": int(duration or 0),
        "added": int(time.time()),
        "thumb": thumb_path,
    }


def _path_for(name):
    hit = _scan().get(name.lower())
    return hit[1] if hit else None


def _new_path(name):
    base = _slugify(name)
    candidate = PLAYLISTS_DIR / f"{base}.json"
    n = 2
    while candidate.exists():
        candidate = PLAYLISTS_DIR / f"{base}-{n}.json"
        n += 1
    return candidate


def _write_new(name, tracks, description=""):
    now = int(time.time())
    data = {
        "version": _SCHEMA_VERSION,
        "name": name,
        "description": description,
        "created": now,
        "modified": now,
        "tracks": tracks,
    }
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(_new_path(name), data)


def _mutate(name, fn):
    """Load playlist by display name, apply fn(data)->bool, save atomically."""
    with _locked():
        path = _path_for(name)
        if path is None:
            return False
        data = _load_file(path)
        if data is None:
            return False
        result = fn(data)
        if result:
            data["modified"] = int(time.time())
            _atomic_write_json(path, data)
        return bool(result)


def _norm_name(s):
    return re.sub(r"[\s_-]+", "", s.lower())


def resolve_name(query):
    names = list_all()
    if query in names:
        return query
    ci = {n.lower(): n for n in names}
    hit = ci.get(query.lower())
    if hit:
        return hit
    matches = search_names(query)
    if len(matches) == 1:
        return matches[0]
    return None


def search_names(query):
    q = query.lower()
    qn = _norm_name(q)
    names = list_all()
    prefix = [n for n in names if n.lower().startswith(q)]
    if len(prefix) == 1:
        return prefix
    sub = [n for n in names if q in n.lower()]
    if len(sub) == 1:
        return sub
    return [n for n in names if qn and qn in _norm_name(n)]


def list_all():
    _ensure_store()
    return sorted((n for n, _ in _scan().values()), key=str.lower)


def exists(name):
    actual = resolve_name(name) if name else None
    return actual is not None


def get(name):
    actual = resolve_name(name) if name else None
    if actual is None:
        return []
    path = _path_for(actual)
    data = _load_file(path) if path else None
    return list(data.get("tracks", [])) if data else []


def info(name):
    actual = resolve_name(name) if name else None
    if actual is None:
        return None
    path = _path_for(actual)
    data = _load_file(path) if path else None
    if not data:
        return None
    tracks = data.get("tracks", [])
    return {
        "name": data.get("name", actual),
        "description": data.get("description", ""),
        "created": data.get("created", 0),
        "modified": data.get("modified", 0),
        "count": len(tracks),
        "duration": sum(int(t.get("duration") or 0) for t in tracks),
        "local_count": sum(1 for t in tracks if local_available(t)),
    }


def create(name, description=""):
    name = name.strip()
    if not name:
        return False
    with _locked():
        _migrate_legacy_locked()
        if _path_for(name) is not None or name.lower() in RESERVED_NAMES:
            return False
        _write_new(name, [], description=description)
        return True


def delete(name):
    with _locked():
        path = _path_for(name)
        if path is None:
            return False
        path.unlink()
        return True


def rename(old, new):
    new = new.strip()
    if not new:
        return False
    with _locked():
        path = _path_for(old)
        if path is None:
            return False
        if new.lower() != old.lower() and _path_for(new) is not None:
            return False
        data = _load_file(path)
        if not data:
            return False
        data["name"] = new
        data["modified"] = int(time.time())
        new_path = _new_path(new)
        _atomic_write_json(new_path, data)
        path.unlink()
        return True


def duplicate(src, new_name):
    new_name = new_name.strip()
    if not new_name:
        return False
    with _locked():
        path = _path_for(src)
        if path is None or _path_for(new_name) is not None:
            return False
        data = _load_file(path)
        if not data:
            return False
        now = int(time.time())
        copy = {
            "version": _SCHEMA_VERSION,
            "name": new_name,
            "description": data.get("description", ""),
            "created": now,
            "modified": now,
            "tracks": [dict(t) for t in data.get("tracks", [])],
        }
        PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(_new_path(new_name), copy)
        return True


def merge(dst, src):
    """Merge src tracks into dst. Returns (added, skipped) or None on error."""
    with _locked():
        dst_path = _path_for(dst)
        src_path = _path_for(src)
        if dst_path is None or src_path is None:
            return None
        ddata = _load_file(dst_path)
        sdata = _load_file(src_path)
        if not ddata or not sdata:
            return None
        seen = {t.get("id") for t in ddata.get("tracks", [])}
        added = skipped = 0
        for t in sdata.get("tracks", []):
            if t.get("id") in seen:
                skipped += 1
                continue
            ddata.setdefault("tracks", []).append(dict(t))
            seen.add(t.get("id"))
            added += 1
        if added:
            ddata["modified"] = int(time.time())
            _atomic_write_json(dst_path, ddata)
        return added, skipped


def set_description(name, description):
    def fn(data):
        if data.get("description") == description:
            return False
        data["description"] = description
        return True

    return _mutate(name, fn)


def add_track(name, track):
    """Add a normalized track dict. Returns ('added'|'skipped'|'error', message)."""
    outcome = []

    def fn(data):
        tid = track.get("id")
        for t in data.get("tracks", []):
            if t.get("id") == tid:
                outcome.append("skipped")
                return False
        data.setdefault("tracks", []).append(dict(track))
        outcome.append("added")
        return True

    ok = _mutate(name, fn)
    if not ok and not outcome:
        return "error", "Playlist not found"
    state = outcome[0] if outcome else "skipped"
    return state, track.get("title", "")


def add_song(name, title, video_id="", url="", duration=0, source=None, local_path=None):
    """Compat wrapper around add_track. Returns True only when newly added."""
    state, _ = add_track(
        name,
        make_track(
            title=title,
            ref=url,
            video_id=video_id,
            duration=duration,
            source=source,
            local_path=local_path,
        ),
    )
    return state == "added"


def remove_song(name, index=None, title_match=None):
    removed_box = []

    def fn(data):
        songs = data.get("tracks", [])
        if index is not None:
            if index < 0 or index >= len(songs):
                return False
            removed_box.append(songs.pop(index))
            return True
        if title_match:
            for i, s in enumerate(songs):
                if title_match.lower() in str(s.get("title", "")).lower():
                    removed_box.append(songs.pop(i))
                    return True
        return False

    ok = _mutate(name, fn)
    if ok and removed_box:
        return True, removed_box[0].get("title", "")
    if index is None and title_match is None:
        return False, "Specify index or song name"
    return False, "Song not found"


def move(name, frm, to):
    """Reorder: move track at 0-based index frm to 0-based position to."""

    def fn(data):
        tracks = data.get("tracks", [])
        if frm < 0 or frm >= len(tracks):
            return False
        dest = max(0, min(to, len(tracks) - 1))
        tracks.insert(dest, tracks.pop(frm))
        return True

    return _mutate(name, fn)


def reorder(name, order):
    """Reorder tracks to match the given id sequence. Returns bool.

    ``order`` must contain every existing track id exactly as often as it
    appears in the playlist; anything else is rejected.
    """

    def fn(data):
        tracks = data.get("tracks", [])
        current = [str(t.get("id")) for t in tracks]
        if not isinstance(order, list) or sorted(current) != sorted(map(str, order)):
            return False
        by_id = {}
        for t in tracks:
            by_id.setdefault(t.get("id"), []).append(t)
        new_tracks = []
        for tid in order:
            bucket = by_id.get(tid)
            if bucket:
                new_tracks.append(bucket.pop(0))
        data["tracks"] = new_tracks
        return True

    return _mutate(name, fn)


def clear(name):
    removed_box = []

    def fn(data):
        removed_box.append(len(data.get("tracks", [])))
        data["tracks"] = []
        return True

    _mutate(name, fn)
    return removed_box[0] if removed_box else 0


def dedupe(name):
    removed_box = []

    def fn(data):
        tracks = data.get("tracks", [])
        seen = set()
        kept = []
        for t in tracks:
            tid = t.get("id")
            if tid in seen:
                continue
            seen.add(tid)
            kept.append(t)
        removed_box.append(len(tracks) - len(kept))
        data["tracks"] = kept
        return len(kept) != len(tracks)

    _mutate(name, fn)
    return removed_box[0] if removed_box else 0


_SORT_KEYS = {
    "title": lambda t: str(t.get("title", "")).lower(),
    "added": lambda t: int(t.get("added") or 0),
    "duration": lambda t: -int(t.get("duration") or 0),
}


def sort_playlist(name, key="title"):
    sort_fn = _SORT_KEYS.get(key)
    if sort_fn is None:
        return False

    def fn(data):
        data["tracks"] = sorted(data.get("tracks", []), key=sort_fn)
        return True

    return _mutate(name, fn)


def export_m3u(name, out_path=None):
    tracks = get(name)
    if not tracks:
        return None
    actual = resolve_name(name)
    if out_path is None:
        out_dir = pathlib.Path.home() / "Downloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{_slugify(actual)}.m3u"
    lines = ["#EXTM3U"]
    for t in tracks:
        dur = int(t.get("duration") or 0)
        lines.append(f"#EXTINF:{dur},{t.get('title', 'Unknown')}")
        lines.append(t.get("local_path") or t.get("ref", ""))
    out_path = pathlib.Path(out_path)
    out_path.write_text("\n".join(lines) + "\n")
    return out_path


def import_m3u(path, name=None):
    path = pathlib.Path(path).expanduser()
    if not path.exists():
        return None
    if not name:
        name = path.stem
    name = name.strip()
    if create(name) is False and not exists(name):
        return None
    count = 0
    pending_title = ""
    pending_dur = 0
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            _, _, rest = line.partition(":")
            dur_part, _, title_part = rest.partition(",")
            try:
                pending_dur = int(float(dur_part))
            except ValueError:
                pending_dur = 0
            pending_title = title_part.strip()
            continue
        if line.startswith("#"):
            continue
        state, _ = add_track(
            name, make_track(title=pending_title, ref=line, duration=pending_dur)
        )
        if state == "added":
            count += 1
        pending_title = ""
        pending_dur = 0
    return name, count


def find_local_copy(video_id):
    """Locate an existing download for a video_id via the library, then disk."""
    if not video_id:
        return None
    try:
        from . import library

        path = library.get_download_path(video_id)
        if path and pathlib.Path(path).exists():
            return path
    except Exception:
        pass
    downloads = pathlib.Path.home() / ".flow/downloads"
    if downloads.exists():
        for p in sorted(downloads.glob(f"{video_id}.*")):
            if p.suffix.lower() in (".mp3", ".m4a", ".opus", ".webm", ".ogg"):
                return str(p)
    return None


def local_available(track):
    lp = track.get("local_path")
    if lp and pathlib.Path(lp).exists():
        return True
    if track.get("source") == "youtube":
        return bool(find_local_copy(track.get("id")))
    return False


def resolve_track(track):
    """Return a playable source: a local file Path when available, else stream ref."""
    lp = track.get("local_path")
    if lp and pathlib.Path(lp).exists():
        return pathlib.Path(lp)
    found = (
        find_local_copy(track.get("id")) if track.get("source") == "youtube" else None
    )
    if found:
        return pathlib.Path(found)
    return track.get("ref", "")


def backfill_local(name, index, path):
    """Record a discovered local copy for the track at 0-based index."""

    def fn(data):
        tracks = data.get("tracks", [])
        if index < 0 or index >= len(tracks):
            return False
        if tracks[index].get("local_path") == str(path):
            return False
        tracks[index]["local_path"] = str(path)
        return True

    try:
        _mutate(name, fn)
    except Exception:
        pass


def backfill_thumb(name, index, path):
    """Record a discovered thumbnail for the track at 0-based index."""

    def fn(data):
        tracks = data.get("tracks", [])
        if index < 0 or index >= len(tracks):
            return False
        if tracks[index].get("thumb") == str(path):
            return False
        tracks[index]["thumb"] = str(path)
        return True

    try:
        _mutate(name, fn)
    except Exception:
        pass


def download_dir(name):
    d = PLAYLIST_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d
