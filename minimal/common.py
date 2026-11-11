"""Shared helpers: the args object backend commands expect, signalling, formatting."""

import json
import os
import time
import types
import urllib.request

from backend import config, ipc, library, registry, status


def ns(**over):
    """Backend commands read their flags off an args namespace."""
    base = {
        "bg": True,
        "shuffle": False,
        "repeat": False,
        "repeat_count": 0,
        "multi": False,
        "download": False,
        "format": None,
        "save_playlist": None,
    }
    base.update(over)
    return types.SimpleNamespace(**base)


def live_player():
    """The running player record, web GUI included."""
    return registry.resolve("vlc") or registry.resolve("web")


def web_command(port, command, payload=None):
    """POST a control command to the web player."""
    data = {"command": command}
    if payload:
        data.update(payload)
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/control",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            return True
    except Exception:
        return False


def signal(action, payload=None):
    """Deliver a control action to the running player; returns its pid or "web"."""
    entry = registry.resolve("vlc")
    if entry is not None:
        if ipc.send(entry, action, payload):
            return entry["pid"]
        config.clear_pid_if(entry["pid"])
    web = registry.resolve("web")
    command = ipc.WEB_COMMANDS.get(action, action)
    if web is not None and web.get("port") and web_command(web["port"], command, payload):
        return "web"
    return None


def clock(seconds):
    """Seconds as m:ss."""
    seconds = int(seconds or 0)
    return f"{seconds // 60}:{seconds % 60:02d}"


def stamp(when):
    """Epoch seconds as YYYY-MM-DD HH:MM."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "-"


def entry_url(entry):
    """Watch URL for a yt-dlp entry, flat or full."""
    if isinstance(entry, str):
        return entry
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if not url:
        video_id = entry.get("id") or entry.get("video_id")
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
    return url or ""


def current():
    """The playing or last played track as (video_id, title)."""
    from backend.status import _vid_from_thumb

    data = status.read()
    title = data.get("title") or ""
    video_id = _vid_from_thumb(data.get("thumbnail") or "") or ""
    if not video_id and title:
        for vid, entry in library.load().items():
            if entry.get("title") == title:
                video_id = vid
                break
    return video_id, title


def library_rows(query=None, liked=None):
    """Library rows as plain dicts, ascending by title."""
    rows = []
    for video_id, entry in library.load().items():
        if not entry.get("downloaded"):
            continue
        if liked is not None and bool(entry.get("liked")) is not liked:
            continue
        rows.append(
            {
                "video_id": video_id,
                "title": entry.get("title") or video_id,
                "artist": entry.get("artist") or "",
                "language": entry.get("language") or "",
                "duration": int(entry.get("duration") or 0),
                "plays": int(entry.get("song_count") or 0),
                "liked": bool(entry.get("liked")),
                "path": entry.get("song") or "",
                "thumbnail": entry.get("thumbnail") or library.thumbnail_path(video_id),
            }
        )
    if query:
        needle = query.lower()
        rows = [r for r in rows if needle in r["title"].lower() or needle in r["artist"].lower()]
    rows.sort(key=lambda row: row["title"].lower())
    return rows


def song_line(row):
    """One downloaded song as a single plain line."""
    who = f" - {row['artist']}" if row["artist"] else ""
    return f"{row['title']}{who} ({clock(row['duration'])})"
