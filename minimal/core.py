"""Player state, transport control, search and playback."""

import json
import os
import pathlib
import random

from backend import config, library, registry, status
from backend.Offline import commands as off_commands
from backend.Offline import file as lib
from backend.Offline import player as off_player
from backend.Online import commands as on_commands
from backend.Online import player as on_player
from backend.Online import youtube
from backend.status import _fresh, _vid_from_thumb

from . import out
from .common import clock, entry_url, live_player, ns, signal

SEARCH_FILE = pathlib.Path.home() / ".flow/search.json"


def status_cmd():
    """One line, or one JSON object, describing the player."""
    registry.prune()
    data = status.read()
    player = live_player()
    state = "stopped"
    if player is not None and _fresh(data):
        state = "playing" if data.get("playing") else "paused"
    video_id = _vid_from_thumb(data.get("thumbnail") or "") or ""
    meta = library.get(video_id) or {} if video_id else {}
    payload = {
        "state": state,
        "title": data.get("title") or "",
        "artist": meta.get("artist") or "",
        "duration": int(data.get("duration") or 0),
        "video_id": video_id,
        "pid": (player or {}).get("pid"),
    }
    if state == "stopped":
        text = "stopped"
    else:
        text = f"{state}  {payload['title']}"
        if payload["artist"]:
            text += f" - {payload['artist']}"
        if payload["pid"]:
            text += f"  (pid {payload['pid']})"
    out.emit(payload, text)


def stop():
    """Stop the running player."""
    with out.quiet():
        stopped = config.kill_stored()
    if stopped:
        out.emit({"status": "stopped"}, "ok  stopped")
    else:
        out.emit({"status": "idle"}, "nothing was playing")


def pause():
    """Toggle pause on the running player."""
    _control("pause", "pause toggled")


def next_track():
    """Skip to the next track."""
    _control("next", "next")


def prev_track():
    """Go back to the previous track."""
    _control("prev", "previous")


def seek(seconds, back=False):
    """Seek forwards or backwards by a number of seconds."""
    if live_player() is None:
        out.fail("no player running")
    delta = int(seconds) * 1000 * (-1 if back else 1)
    action = "seek_bwd" if back else "seek_fwd"
    with out.quiet():
        config.write_seek(delta)
        target = signal(action, {"delta": delta})
    if target is None:
        out.fail("no player running")
    direction = "back" if back else "forward"
    out.emit(
        {
            "status": "ok",
            "command": "seekb" if back else "seek",
            "seconds": int(seconds),
            "pid": _pid(target),
        },
        f"ok  seek {direction} {int(seconds)}s",
    )


_EMIT_CMD = {"prev": "previous"}


def _control(action, label):
    with out.quiet():
        target = signal(action)
    if target is None:
        out.fail("no player running")
    out.emit(
        {"status": "ok", "command": _EMIT_CMD.get(action, action), "pid": _pid(target)},
        f"ok  {label}",
    )


def _pid(target):
    return None if target == "web" else target


def search(query, limit=None):
    """Search YouTube without playing anything; remember the rows for `play <index>`."""
    with out.quiet():
        results = youtube.search(query, limit or config.MAX_SEARCH_RESULTS)
    if not results:
        out.fail(f"no results for {query!r}")
    rows = [
        {
            "index": index,
            "video_id": entry.get("id") or "",
            "title": title,
            "duration": int(duration or 0),
            "url": entry_url(entry),
        }
        for index, (entry, title, duration) in enumerate(results, 1)
    ]
    _save_search(query, results)
    out.emit(
        rows, [f"{r['index']}. {r['title']} ({clock(r['duration'])})" for r in rows]
    )


def _save_search(query, results):
    """Remember the rows so a later `play <index>` can pick one."""
    data = {
        "query": query,
        "results": [
            {"url": entry_url(entry), "title": title} for entry, title, _ in results
        ],
    }
    SEARCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEARCH_FILE.with_name(SEARCH_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, SEARCH_FILE)


def _load_search():
    """Rows from the last `search`, failing when nothing is saved."""
    try:
        rows = json.loads(SEARCH_FILE.read_text()).get("results") or []
    except (OSError, ValueError, AttributeError):
        rows = []
    if not rows:
        out.fail("no saved search; run 'flow-min search <query>' first")
    return rows


def _play_saved(index, shuffle=False, foreground=False):
    """Play row `index` (1-based) of the last `search`."""
    rows = _load_search()
    if not 1 <= index <= len(rows):
        out.fail(f"index {index} out of range (1-{len(rows)})")
    row = rows[index - 1]
    with out.quiet():
        info = youtube.get_entry(row.get("url") or "")
    if not info:
        out.fail(f"could not resolve a stream for {row.get('title')!r}")
    _play_online(info, row.get("title") or "", shuffle=shuffle, foreground=foreground)


def play(query, index=1, shuffle=False, foreground=False):
    """Play a YouTube search result or direct link; a bare number picks a saved row."""
    if query.strip().isdigit():
        _play_saved(int(query), shuffle=shuffle, foreground=foreground)
        return
    video_id = youtube.video_id_from_url(query)
    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        with out.quiet():
            info = youtube.get_entry(url)
        if not info:
            out.fail(f"could not resolve a stream for {query!r}")
        title = info.get("title") or ""
        _play_online(info, title, shuffle=shuffle, foreground=foreground)
        return
    with out.quiet():
        results = youtube.search(query, config.MAX_SEARCH_RESULTS)
    if not results:
        out.fail(f"no results for {query!r}")
    if not 1 <= index <= len(results):
        out.fail(f"index {index} out of range (1-{len(results)})")
    entry, title, _ = results[index - 1]
    with out.quiet():
        info = youtube.get_entry(entry_url(entry))
    if not info:
        out.fail(f"could not resolve a stream for {title!r}")
    _play_online(info, title, shuffle=shuffle, foreground=foreground)


def play_off(query, shuffle=False, foreground=False):
    """Play a downloaded song by name."""
    with out.quiet():
        matches = lib.find_songs(query)
    if not matches:
        out.fail(f"no downloaded song matching {query!r}")
    _play_file(matches[0], shuffle=shuffle, foreground=foreground, matches=len(matches))


def play_paths(paths, foreground=False, label=None, shuffle=False, repeat=False, repeat_count=0):
    """Play a queue of downloaded files."""
    paths = [pathlib.Path(p) for p in paths]
    if not paths:
        out.fail("nothing to play")
    if shuffle:
        random.shuffle(paths)
    payload = {
        "status": "playing",
        "tracks": len(paths),
        "title": lib.display_name(paths[0]),
    }
    args = ns(shuffle=False, bg=False, repeat=repeat, repeat_count=repeat_count)
    if foreground:
        with out.quiet():
            off_commands._play_queue(paths, args)
        out.emit(payload, f"played  {len(paths)} track(s)")
        return
    _spawn(
        off_player._install_controls,
        lambda: off_commands._play_queue(paths, args),
        payload,
        label or f"playing  {len(paths)} track(s)",
    )


def play_online_queue(results, foreground=False, label=None):
    """Play a queue of YouTube entries as (entry, title, duration) triples."""
    if not results:
        out.fail("nothing to play")
    payload = {"status": "playing", "tracks": len(results), "title": results[0][1]}
    args = ns(shuffle=False, bg=False)
    if foreground:
        with out.quiet():
            on_commands._play_queue(results, args)
        out.emit(payload, f"played  {len(results)} track(s)")
        return
    _spawn(
        on_player._install_controls,
        lambda: on_commands._play_queue(results, args),
        payload,
        label or f"playing  {len(results)} track(s)",
    )


def resume(foreground=False):
    """Play the current or last played track again."""
    data = status.read()
    title = data.get("title") or ""
    thumb = data.get("thumbnail") or ""
    video_id = _vid_from_thumb(thumb) or ""
    if not title:
        out.fail("nothing to resume")
    if thumb.startswith("http"):
        if not video_id:
            out.fail(f"cannot tell which track {title!r} is")
        with out.quiet():
            info = youtube.get_entry(f"https://www.youtube.com/watch?v={video_id}")
        if not info:
            out.fail(f"could not resolve a stream for {title!r}")
        _play_online(info, title, foreground=foreground)
        return
    path = library.get_download_path(video_id) if video_id else None
    if not path:
        out.fail(f"{title!r} is not downloaded")
    _play_file(pathlib.Path(path), foreground=foreground)


def _play_online(info, title, shuffle=False, foreground=False):
    payload = {
        "status": "playing",
        "title": title,
        "video_id": info.get("id") or "",
        "artist": info.get("artist") or info.get("channel") or "",
        "duration": int(info.get("duration") or 0),
    }
    args = ns(shuffle=shuffle, bg=False)
    if foreground:
        with out.quiet():
            on_player.play_entry(info, title, args)
        out.emit(payload, f"played  {title}")
        return
    _spawn(
        on_player._install_controls,
        lambda: on_player.play_entry(info, title, args),
        payload,
        f"playing  {title}",
    )


def _play_file(path, shuffle=False, foreground=False, matches=1):
    path = pathlib.Path(path)
    title = lib.display_name(path)
    payload = {
        "status": "playing",
        "title": title,
        "path": str(path),
        "matches": matches,
    }
    args = ns(shuffle=shuffle, bg=False)
    if foreground:
        with out.quiet():
            off_player.play_file(path, title, args)
        out.emit(payload, f"played  {title}")
        return
    _spawn(
        off_player._install_controls,
        lambda: off_player.play_file(path, title, args),
        payload,
        f"playing  {title}",
    )


def _spawn(setup, run, payload, text):
    """Replace the running player with a detached child that runs `run`."""
    with out.quiet():
        config.kill_stored()
    pid = out.fork_bg()
    if pid:
        out.emit(dict(payload, pid=pid), f"{text}  (pid {pid})")
        return
    with out.quiet():
        setup()
        run()
