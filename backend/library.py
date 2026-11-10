import datetime
import hashlib
import json
import pathlib
import sqlite3
import time
import urllib.request
from contextlib import contextmanager

from backend.config import _truncate_title

DB_FILE = pathlib.Path.home() / ".flow/library.db"
THUMB_CACHE = pathlib.Path.home() / ".flow/downloads/.cache"

LEGACY_FILE = pathlib.Path.home() / ".flow/library.json"
_REMOVED_META_KEYS = {
    "track",
    "uploader",
    "channel",
    "upload_date",
    "release_date",
    "view_count",
    "like_count",
    "url",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    video_id     TEXT PRIMARY KEY,
    liked        INTEGER NOT NULL DEFAULT 0,
    downloaded   INTEGER NOT NULL DEFAULT 0,
    speed_dial   INTEGER NOT NULL DEFAULT 0,
    title        TEXT    NOT NULL DEFAULT '',
    custom_title TEXT,
    artist       TEXT,
    album        TEXT,
    language     TEXT,
    duration     INTEGER,
    song         TEXT,
    thumbnail    TEXT    NOT NULL DEFAULT '',
    song_count   INTEGER NOT NULL DEFAULT 0,
    first_played REAL,
    last_played  REAL
);

CREATE INDEX IF NOT EXISTS idx_songs_count  ON songs(song_count DESC);
CREATE INDEX IF NOT EXISTS idx_songs_played ON songs(last_played DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS play_days (
    day   TEXT PRIMARY KEY,
    plays INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS song_tags (
    video_id TEXT NOT NULL,
    tag      TEXT NOT NULL,
    PRIMARY KEY (video_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_song_tags_tag ON song_tags(tag);
"""

_COLUMNS = (
    "liked",
    "downloaded",
    "speed_dial",
    "title",
    "artist",
    "album",
    "duration",
    "song",
    "thumbnail",
    "song_count",
    "first_played",
    "last_played",
    "custom_title",
    "language",
)

_PLACEHOLDERS = ", ".join(["?"] * (len(_COLUMNS) + 1))
_ASSIGNMENTS = ", ".join(f"{c} = excluded.{c}" for c in _COLUMNS)

_UPSERT = (
    f"INSERT INTO songs (video_id, {', '.join(_COLUMNS)}) "
    f"VALUES ({_PLACEHOLDERS}) "
    f"ON CONFLICT(video_id) DO UPDATE SET {_ASSIGNMENTS}"
)


def _connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _ensure_schema(conn):
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(_SCHEMA)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(songs)")}
    if "custom_title" not in cols:
        conn.execute("ALTER TABLE songs ADD COLUMN custom_title TEXT")
    if "language" not in cols:
        conn.execute("ALTER TABLE songs ADD COLUMN language TEXT")
    _migrate_from_json(conn)
    _purge_auto_tags(conn)


@contextmanager
def _session():
    conn = _connect()
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


@contextmanager
def _write():
    """Serialized read-modify-write cycle. Rolls back on any exception."""
    with _session() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        conn.commit()


def _meta_get(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _meta_set(conn, key, value):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _purge_auto_tags(conn):
    """One-time wipe of the old language/artist auto tags; user tags survive."""
    if _meta_get(conn, "auto_tags_purged") == "1":
        return
    conn.execute("UPDATE songs SET language = NULL, artist = NULL")
    _meta_set(conn, "auto_tags_purged", "1")


def _migrate_from_json(conn):
    if _meta_get(conn, "json_migrated") == "1":
        return
    if not LEGACY_FILE.exists():
        return
    try:
        data = json.loads(LEGACY_FILE.read_text())
    except json.JSONDecodeError, OSError:
        data = {}
    if isinstance(data, dict):
        for video_id, entry in data.items():
            if isinstance(entry, dict):
                row = _legacy_to_row(video_id, entry)
                if row:
                    conn.execute(_UPSERT, row)
    _meta_set(conn, "json_migrated", "1")
    try:
        LEGACY_FILE.rename(LEGACY_FILE.with_name(LEGACY_FILE.name + ".bak"))
    except OSError:
        pass


def _legacy_to_row(video_id, entry):
    """Map a legacy JSON entry onto the column tuple `_UPSERT` expects."""
    song = entry.get("song")
    duration = entry.get("duration")
    try:
        duration = int(duration) if duration else None
    except TypeError, ValueError:
        duration = None
    count = entry.get("song_count") or 0
    try:
        count = int(count)
    except TypeError, ValueError:
        count = 0
    return (
        video_id,
        1 if entry.get("liked") else 0,
        1 if entry.get("downloaded") else 0,
        1 if entry.get("speed_dial") else 0,
        _truncate_title(entry.get("title") or ""),
        entry.get("artist") or None,
        entry.get("album") or None,
        duration,
        song or None,
        entry.get("thumbnail") or "",
        count,
        entry.get("first_played") or None,
        entry.get("last_played") or None,
        _truncate_title(entry.get("custom_title") or "") or None,
        entry.get("language") or None,
    )


def _row_to_entry(row) -> dict:
    custom = (row["custom_title"] or "").strip()
    return {
        "liked": bool(row["liked"]),
        "downloaded": bool(row["downloaded"]),
        "speed_dial": bool(row["speed_dial"]),
        "title": custom or row["title"] or "",
        "custom_title": custom,
        "artist": row["artist"],
        "album": row["album"],
        "language": row["language"],
        "duration": row["duration"],
        "song": row["song"],
        "thumbnail": row["thumbnail"] or "",
        "song_count": int(row["song_count"] or 0),
        "first_played": row["first_played"],
        "last_played": row["last_played"],
    }


def _to_values(entry: dict) -> tuple:
    duration = entry.get("duration")
    try:
        duration = int(duration) if duration else None
    except TypeError, ValueError:
        duration = None
    return (
        1 if entry.get("liked") else 0,
        1 if entry.get("downloaded") else 0,
        1 if entry.get("speed_dial") else 0,
        entry.get("title") or "",
        entry.get("artist") or None,
        entry.get("album") or None,
        duration,
        entry.get("song") or None,
        entry.get("thumbnail") or "",
        int(entry.get("song_count") or 0),
        entry.get("first_played") or None,
        entry.get("last_played") or None,
        _truncate_title(entry.get("custom_title") or "") or None,
        entry.get("language") or None,
    )


def _sanitize(entry: dict) -> dict:
    """Normalize one entry before it is written: truncated title, typed values."""
    out = dict(entry)
    out["title"] = _truncate_title(entry.get("title") or "")
    out["custom_title"] = _truncate_title(entry.get("custom_title") or "")
    out["language"] = (entry.get("language") or "").strip().lower() or None
    out["song_count"] = int(entry.get("song_count") or 0)
    return out


def _all_entries(conn) -> dict:
    rows = conn.execute("SELECT * FROM songs").fetchall()
    return {row["video_id"]: _row_to_entry(row) for row in rows}


def _get_entry(conn, video_id):
    row = conn.execute("SELECT * FROM songs WHERE video_id = ?", (video_id,)).fetchone()
    return _row_to_entry(row) if row else None


def _apply_diff(conn, before: dict, after: dict):
    """Write only the rows a mutator actually changed."""
    for video_id, entry in after.items():
        old = before.get(video_id)
        if old == entry:
            continue
        conn.execute(_UPSERT, (video_id, *_to_values(entry)))
    for video_id in before:
        if video_id not in after:
            conn.execute("DELETE FROM songs WHERE video_id = ?", (video_id,))


def load() -> dict:
    with _session() as conn:
        return _all_entries(conn)


def get(video_id: str) -> dict | None:
    if not video_id:
        return None
    with _session() as conn:
        return _get_entry(conn, video_id)


def get_title(video_id: str) -> str:
    entry = get(video_id)
    if entry and entry.get("title"):
        return entry["title"]
    return video_id


def title_for_stem(stem: str) -> str:
    return get_title(stem)


def is_liked(video_id: str) -> bool:
    entry = get(video_id)
    return bool(entry and entry.get("liked"))


def is_downloaded(video_id: str) -> bool:
    return get_download_path(video_id) is not None


def get_download_path(video_id: str) -> str | None:
    entry = get(video_id)
    if not entry or not entry.get("downloaded"):
        return None
    return entry.get("song")


def get_downloaded_ids() -> list:
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id FROM songs "
            "WHERE downloaded = 1 AND song IS NOT NULL AND song != '' "
            "ORDER BY video_id"
        ).fetchall()
    return [row["video_id"] for row in rows]


def get_liked_ids() -> list:
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id FROM songs WHERE liked = 1 ORDER BY video_id"
        ).fetchall()
    return [row["video_id"] for row in rows]


def get_liked_entries() -> list:
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id, title, custom_title FROM songs "
            "WHERE liked = 1 ORDER BY video_id"
        ).fetchall()
    return [
        {"video_id": r["video_id"], "title": r["custom_title"] or r["title"] or ""}
        for r in rows
    ]


def get_speed_dial_ids() -> list:
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id FROM songs WHERE speed_dial = 1 ORDER BY video_id"
        ).fetchall()
    return [row["video_id"] for row in rows]


def get_speed_dial_entries() -> list:
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id, title, custom_title FROM songs "
            "WHERE speed_dial = 1 ORDER BY video_id"
        ).fetchall()
    return [
        {"video_id": r["video_id"], "title": r["custom_title"] or r["title"] or ""}
        for r in rows
    ]


def get_song_count(video_id: str) -> int:
    entry = get(video_id)
    return int(entry.get("song_count") or 0) if entry else 0


def play_rows() -> list:
    """Per-song play counts across every mode (see `summary.py` / the web API)."""
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id, title, custom_title, artist, album, language, song,"
            "       thumbnail, duration, song_count, first_played, last_played "
            "FROM songs WHERE song_count > 0"
        ).fetchall()
    return [
        {
            "video_id": r["video_id"],
            "title": r["custom_title"] or r["title"] or r["video_id"],
            "artist": r["artist"] or "",
            "album": r["album"] or "",
            "language": r["language"] or "",
            "song": r["song"],
            "thumbnail": r["thumbnail"] or "",
            "duration": int(r["duration"] or 0),
            "song_count": int(r["song_count"] or 0),
            "first_played": r["first_played"] or 0.0,
            "last_played": r["last_played"] or 0.0,
        }
        for r in rows
    ]


def _by_name(rows) -> list:
    return sorted(rows, key=lambda r: (r["title"] or r["video_id"] or "").lower())


def songs_with_tag(tag: str) -> list:
    """Downloaded songs carrying one user tag, ascending by name."""
    tag = (tag or "").strip()
    if not tag:
        return []
    with _session() as conn:
        rows = conn.execute(
            "SELECT s.video_id, s.title, s.custom_title, s.song "
            "FROM song_tags t JOIN songs s ON s.video_id = t.video_id "
            "WHERE t.tag = ? COLLATE NOCASE "
            "AND s.downloaded = 1 AND s.song IS NOT NULL AND s.song != ''",
            (tag,),
        ).fetchall()
    return [
        {
            "video_id": r["video_id"],
            "title": r["custom_title"] or r["title"] or r["video_id"],
            "song": r["song"],
        }
        for r in _by_name(rows)
    ]


def downloaded_rows() -> list:
    """Every downloaded song with its tags, by name."""
    with _session() as conn:
        rows = conn.execute(
            "SELECT video_id, title, custom_title, artist, language "
            "FROM songs WHERE downloaded = 1 AND song IS NOT NULL AND song != ''"
        ).fetchall()
        tag_rows = conn.execute("SELECT video_id, tag FROM song_tags").fetchall()
    tags_by = {}
    for t in tag_rows:
        tags_by.setdefault(t["video_id"], []).append(t["tag"])
    out = []
    for r in rows:
        out.append(
            {
                "video_id": r["video_id"],
                "title": r["custom_title"] or r["title"] or r["video_id"],
                "artist": r["artist"] or "",
                "language": r["language"] or "",
                "tags": sorted(tags_by.get(r["video_id"], [])),
            }
        )
    return sorted(out, key=lambda row: row["title"].lower())


def song_tags(video_id: str) -> list:
    """Free-form tags on one song, alphabetically."""
    if not video_id:
        return []
    with _session() as conn:
        rows = conn.execute(
            "SELECT tag FROM song_tags WHERE video_id = ? ORDER BY tag",
            (video_id,),
        ).fetchall()
    return [r["tag"] for r in rows]


def all_song_tags() -> list:
    """Every free-form tag and how many songs carry it, most used first."""
    with _session() as conn:
        rows = conn.execute(
            "SELECT tag, COUNT(*) AS n FROM song_tags GROUP BY tag"
        ).fetchall()
    return sorted(((r["tag"], int(r["n"])) for r in rows), key=lambda kv: (-kv[1], kv[0]))


def set_song_tag(video_id: str, tag: str, on: bool = True) -> bool:
    """Add (`on=True`) or remove one free-form tag on a song. False if unknown."""
    tag = (tag or "").strip()
    if not video_id or not tag:
        return False
    with _write() as conn:
        exists = conn.execute(
            "SELECT 1 FROM songs WHERE video_id = ?", (video_id,)
        ).fetchone()
        if exists is None:
            return False
        if on:
            conn.execute(
                "INSERT OR IGNORE INTO song_tags (video_id, tag) VALUES (?, ?)",
                (video_id, tag),
            )
        else:
            conn.execute(
                "DELETE FROM song_tags WHERE video_id = ? AND tag = ?",
                (video_id, tag),
            )
        return True


def clear_song_tags(video_id: str) -> int:
    """Remove every free-form tag from a song; returns how many were dropped."""
    with _write() as conn:
        cur = conn.execute("DELETE FROM song_tags WHERE video_id = ?", (video_id,))
        return cur.rowcount


def rename_tag(old: str, new: str) -> int:
    """Rename a free-form tag on every song; returns how many songs changed."""
    old, new = (old or "").strip(), (new or "").strip()
    if not old or not new or old == new:
        return 0
    with _write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO song_tags (video_id, tag) "
            "SELECT video_id, ? FROM song_tags WHERE tag = ?",
            (new, old),
        )
        cur = conn.execute("DELETE FROM song_tags WHERE tag = ?", (old,))
        return cur.rowcount


def delete_tag(tag: str) -> int:
    """Drop a free-form tag from every song; returns how many songs changed."""
    tag = (tag or "").strip()
    if not tag:
        return 0
    with _write() as conn:
        cur = conn.execute("DELETE FROM song_tags WHERE tag = ?", (tag,))
        return cur.rowcount


def _default_entry(video_id: str, title: str = "") -> dict:
    return {
        "liked": False,
        "downloaded": False,
        "speed_dial": False,
        "title": title,
        "custom_title": "",
        "artist": None,
        "album": None,
        "language": None,
        "duration": None,
        "song": None,
        "thumbnail": thumbnail_path(video_id),
        "song_count": 0,
        "first_played": None,
        "last_played": None,
    }


def _mutate(fn):
    with _write() as conn:
        before = _all_entries(conn)
        library = {k: dict(v) for k, v in before.items()}
        changed = fn(library)
        if not changed:
            return library
        after = {k: _sanitize(v) for k, v in library.items() if isinstance(v, dict)}
        _apply_diff(conn, before, after)
        return library


def save(library: dict):
    """Replace the whole library with ``library`` in a single transaction."""
    with _write() as conn:
        before = _all_entries(conn)
        after = {k: _sanitize(v) for k, v in library.items() if isinstance(v, dict)}
        _apply_diff(conn, before, after)


def _set_thumbnail(video_id: str, path: str):
    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            return False
        entry["thumbnail"] = path
        library[video_id] = entry
        return True

    _mutate(mutate)


def download_thumbnail(video_id: str, thumb_url: str = "") -> str | None:
    if not video_id:
        return None
    path = thumbnail_path(video_id)
    if pathlib.Path(path).exists():
        _set_thumbnail(video_id, path)
        return path
    if not thumb_url:
        thumb_url = thumbnail_url_for(video_id)
    candidates = [thumb_url]
    if "i.ytimg.com/vi/" in thumb_url:
        try:
            vid = thumb_url.split("/vi/")[1].split("/")[0]
            candidates.insert(0, f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
        except IndexError:
            pass
    for url in candidates:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            if not data:
                continue
            THUMB_CACHE.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_bytes(data)
            _set_thumbnail(video_id, path)
            return path
        except Exception:
            continue
    return None


def thumbnail_path(video_id: str) -> str:
    return str(THUMB_CACHE / f"{video_id}.jpg")


def thumbnail_url_for(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def key_for(url: str, video_id: str = "") -> str:
    if video_id:
        return video_id
    if url:
        return f"s:{hashlib.sha1(url.encode()).hexdigest()}"
    return ""


def mark_speed_dial(video_id: str, title: str = "", path: str = ""):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            entry = _default_entry(video_id, title)
        entry["speed_dial"] = True
        if title and not entry.get("title"):
            entry["title"] = title
        if path:
            entry["song"] = path
        entry["thumbnail"] = thumbnail_path(video_id)
        library[video_id] = entry
        return True

    _mutate(mutate)


def unmark_speed_dial(video_id: str):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            return False
        entry["speed_dial"] = False
        if _forgettable(entry):
            library.pop(video_id, None)
        else:
            library[video_id] = entry
        return True

    _mutate(mutate)


def mark_liked(video_id: str, title: str = ""):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            entry = _default_entry(video_id, title)
        entry["liked"] = True
        if title and not entry.get("title"):
            entry["title"] = title
        entry["thumbnail"] = thumbnail_path(video_id)
        library[video_id] = entry
        return True

    _mutate(mutate)


def mark_unliked(video_id: str):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            return False
        entry["liked"] = False
        if _forgettable(entry):
            library.pop(video_id, None)
        else:
            library[video_id] = entry
        return True

    _mutate(mutate)


def track_download(video_id: str, path: str, title: str = "", meta=None):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            entry = _default_entry(video_id, title)
        entry["downloaded"] = True
        entry["song"] = path
        if title and not entry.get("title"):
            entry["title"] = title
        if meta:
            for k, v in meta.items():
                if v not in (None, ""):
                    entry[k] = v
        entry["thumbnail"] = thumbnail_path(video_id)
        library[video_id] = entry
        return True

    _mutate(mutate)


def meta_from_info(info: dict) -> dict:
    """Trim a track's YouTube metadata down to the fields the library stores."""
    meta = {}
    if info.get("album"):
        meta["album"] = info.get("album")
    duration = info.get("duration")
    if duration:
        try:
            meta["duration"] = int(duration)
        except TypeError, ValueError:
            pass
    return meta


def update_meta(video_id: str, meta: dict):
    """Merge fetched/backfilled metadata into the library entry."""
    if not video_id or not meta:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            entry = _default_entry(video_id)
        for k, v in meta.items():
            if v not in (None, ""):
                entry[k] = v
        library[video_id] = entry
        return True

    _mutate(mutate)


def rename(video_id: str, title: str) -> bool:
    """Pin a display name for a track; re-downloads and metadata refreshes keep it."""
    video_id = (video_id or "").strip()
    title = _truncate_title((title or "").strip())
    if not video_id or not title:
        return False

    def mutate(library):
        entry = library.get(video_id) or _default_entry(video_id, title)
        entry["custom_title"] = title
        library[video_id] = entry
        return True

    _mutate(mutate)
    return True


def clear_download(video_id: str):
    if not video_id:
        return

    def mutate(library):
        entry = library.get(video_id)
        if entry is None:
            return False
        entry["downloaded"] = False
        entry["song"] = None
        if _forgettable(entry):
            library.pop(video_id, None)
        else:
            library[video_id] = entry
        return True

    _mutate(mutate)
    with _write() as conn:
        conn.execute("DELETE FROM song_tags WHERE video_id = ?", (video_id,))


def _forgettable(entry: dict) -> bool:
    return (
        not entry.get("liked")
        and not entry.get("downloaded")
        and not entry.get("speed_dial")
        and not entry.get("song")
        and not int(entry.get("song_count") or 0)
    )


def bump_play(video_id: str, title: str = "", artist: str = "", duration=0) -> int:
    if not video_id:
        return 0
    try:
        duration = int(duration) if duration else 0
    except TypeError, ValueError:
        duration = 0
    now = time.time()
    with _write() as conn:
        entry = _get_entry(conn, video_id)
        if entry is None:
            entry = _default_entry(video_id, title)
        # Fill gaps only — a later play must not clobber metadata we have.
        if title and not entry.get("title"):
            entry["title"] = title
        if artist and not entry.get("artist"):
            entry["artist"] = artist
        if duration and not entry.get("duration"):
            entry["duration"] = duration
        entry["song_count"] = int(entry.get("song_count") or 0) + 1
        entry["first_played"] = entry.get("first_played") or now
        entry["last_played"] = now
        conn.execute(_UPSERT, (video_id, *_to_values(_sanitize(entry))))
        conn.execute(
            "INSERT INTO play_days (day, plays) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET plays = plays + 1",
            (datetime.date.today().isoformat(),),
        )
        return entry["song_count"]


def stats() -> dict:
    """Library-wide play totals, used by the CLI summary and the RPC surface."""
    rows = play_rows()
    total = sum(r["song_count"] for r in rows)
    day_start = datetime.datetime.combine(datetime.date.today(), datetime.time.min)
    today = sum(1 for r in rows if r["last_played"] >= day_start.timestamp())
    return {
        "total_plays": total,
        "unique_songs": len(rows),
        "played_today": today,
        "downloaded": len(get_downloaded_ids()),
        "liked": len(get_liked_ids()),
    }


def play_days(days: int = 7) -> list:
    """`[(day_offset, plays)]` per calendar day, both modes, oldest first."""
    today = datetime.date.today()
    counts: dict[str, int] = {}
    with _session() as conn:
        rows = conn.execute(
            "SELECT day, plays FROM play_days WHERE day >= ?",
            ((today - datetime.timedelta(days=days - 1)).isoformat(),),
        ).fetchall()
    for r in rows:
        counts[r["day"]] = int(r["plays"] or 0)
    return [
        (offset, counts.get((today - datetime.timedelta(days=offset)).isoformat(), 0))
        for offset in range(days - 1, -1, -1)
    ]


def clear_plays() -> int:
    """Zero every play counter and day bucket (both modes); rows survive."""
    with _write() as conn:
        conn.execute("DELETE FROM play_days")
        cur = conn.execute(
            "UPDATE songs SET song_count = 0, first_played = NULL, last_played = NULL "
            "WHERE song_count > 0"
        )
        return int(cur.rowcount)


def delete(video_id: str) -> bool:
    path = get_download_path(video_id)
    removed = bool(path)
    if path:
        p = pathlib.Path(path)
        if p.exists():
            p.unlink()
        stem = p.stem if p.suffix else p.name
        for other in p.parent.glob(f"{stem}*"):
            if other != p:
                try:
                    other.unlink()
                except OSError:
                    pass
    thumb = THUMB_CACHE / video_id
    for other in THUMB_CACHE.glob(f"{thumb.name}*"):
        try:
            other.unlink()
        except OSError:
            pass
    clear_download(video_id)
    return removed
