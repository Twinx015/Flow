"""Best-effort push of play state to the configured API (`config.api_url`).

When the set value is an http(s) URL, flow POSTs JSON after every recorded
play: `/now` with the current song name, artist and playlist (when playing
from one), and `/summary` with the whole `flow --summary` payload. Pushes
run in a daemon thread and never raise — a dead API must not break playback.
"""

import json
import logging
import threading
import time
import urllib.request

from backend import config, history, library, summary

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_playlist = ""
_inflight = set()


def set_playlist(name):
    """Remember the playlist name included with /now pushes; empty to clear."""
    global _playlist
    with _lock:
        _playlist = name or ""


def enabled():
    return bool(config.ApiUrl)


def playlist_name():
    with _lock:
        return _playlist


def _post(path, payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        config.ApiUrl.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "flow-twinx"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as resp:
            resp.read()
    except Exception as exc:
        logger.warning("API push %s failed: %s", path, exc)
        if config.DEV_MODE:
            config.dev_print("API Push Failed", {"path": path, "error": str(exc)})


def _push(path, payload_builder):
    if not enabled():
        return
    key = path
    if key in _inflight:
        return
    _inflight.add(key)

    def worker():
        try:
            _post(path, payload_builder())
        finally:
            _inflight.discard(key)

    threading.Thread(target=worker, name=f"flow-api{path}", daemon=True).start()


def push_now(title, artist="", mode=None):
    """POST the current song name, artist, and playlist (if any)."""

    def build():
        return {
            "title": title or "",
            "artist": artist or "",
            "playlist": playlist_name(),
            "mode": mode or config.Mode,
            "at": time.time(),
        }

    _push("/now", build)


def _top(rows, key):
    """Most-played value of a tag column, or "" when nothing has it."""
    counts = {}
    for row in rows:
        val = (row.get(key) or "").strip()
        if val:
            counts[val] = counts.get(val, 0) + row.get("song_count", 0)
    return max(counts, key=counts.get) if counts else ""


def _top_song(rows):
    best = max(rows, key=lambda r: r["song_count"], default=None)
    return best["title"] if best and best.get("song_count") else ""


def _trim_row(row):
    return {
        "video_id": row.get("video_id"),
        "title": row.get("title"),
        "artist": row.get("artist"),
        "album": row.get("album"),
        "language": row.get("language"),
        "duration": row.get("duration"),
        "song_count": row.get("song_count"),
        "first_played": row.get("first_played"),
        "last_played": row.get("last_played"),
    }


def summary_payload():
    """Everything `flow --summary` shows, as one JSON document."""
    rows = library.play_rows()
    lines = history.totals()
    lib = library.stats()
    combined = lib["total_plays"]
    online = lines["online_plays"]
    week = summary._week_rows()
    this_week, last_week = summary._week_sums()
    return {
        "at": time.time(),
        "mode": config.Mode,
        "totals": {
            "combined_plays": combined,
            "online_plays": online,
            "offline_plays": max(combined - online, 0),
            "unique_songs": lib["unique_songs"],
            "played_today": lib["played_today"],
            "downloaded": lib["downloaded"],
            "liked": lib["liked"],
        },
        "tops": {
            "artist": _top(rows, "artist"),
            "language": _top(rows, "language"),
            "song": _top_song(rows),
        },
        "last_7_days": [
            {"day": "today" if offset == 0 else f"-{offset}d", "online": on,
             "offline": off}
            for offset, on, off in week
        ],
        "this_week_plays": this_week,
        "last_week_plays": last_week,
        "songs": [_trim_row(r) for r in rows],
    }


def push_summary():
    """POST the full --summary payload."""
    _push("/summary", summary_payload)
