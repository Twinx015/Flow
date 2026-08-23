

import pathlib
import time

from . import playlist
from .imports import config

P = config.Primary
S = config.Secondary
T = config.Tertiary
M = config.Muted
E = config.Red
G = config.Grey
R = config.Reset

m = lambda t: print(f"{M}{t}{R}")
e = lambda t: print(f"{E}{t}{R}")
i = lambda t: print(f"{P if config.Mode == 'Online' else S}{t}{R}")


def _truncate(title, limit=56):
    title = str(title or "Unknown")
    return title if len(title) <= limit else title[:limit] + "..."


def _fmt_dur(secs):
    secs = int(secs or 0)
    if secs <= 0:
        return ""
    mins, s = divmod(secs, 60)
    if mins >= 60:
        h, mins = divmod(mins, 60)
        return f"{h}:{mins:02d}:{s:02d}"
    return f"{mins}:{s:02d}"


def _fmt_date(ts):
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _resolve_or_error(name):
    actual = playlist.resolve_name(name)
    if actual:
        return actual
    matches = playlist.search_names(name)
    if len(matches) > 1:
        e(f"     Ambiguous playlist '{name}'. Did you mean:")
        for x in matches[:8]:
            m(f"       {x}")
    else:
        e(f"     Playlist '{name}' not found")
    return None


def _print_tracks(name, tracks):
    i(f"  {name}:")
    if not tracks:
        m("     (empty)")
        return
    for idx, s in enumerate(tracks, 1):
        suffix = ""
        dur = _fmt_dur(s.get("duration"))
        if dur:
            suffix += f"  [{dur}]"
        try:
            if playlist.local_available(s):
                suffix += f" {T}*local{R}"
        except Exception:
            pass
        m(f"  {idx}. {_truncate(s.get('title'))}{suffix}")


def _print_info(actual):
    inf = playlist.info(actual)
    if not inf:
        e(f"     Cannot read info for '{actual}'")
        return
    i(f"  {inf['name']}")
    m(f"  description : {inf['description'] or '-'}")
    local_bit = f" ({inf['local_count']} on device)" if inf["local_count"] else ""
    m(f"  tracks      : {inf['count']}{local_bit}")
    total = _fmt_dur(inf["duration"])
    m(f"  duration    : {total or '-'}")
    m(f"  created     : {_fmt_date(inf['created'])}")
    m(f"  modified    : {_fmt_date(inf['modified'])}")


def handle(extra, args=None, hooks=None):
    """Dispatch a `playlist ...` command line."""
    hooks = hooks or {}

    if not extra:
        names = playlist.list_all()
        if not names:
            m("No playlists")
            return
        i("Playlists:")
        for name in names:
            inf = playlist.info(name) or {}
            count = inf.get("count", 0)
            dur = _fmt_dur(inf.get("duration"))
            tail = f"  ({count} songs"
            tail += f", {dur})" if dur else ")"
            m(f"  {name}{tail}")
        return

    subcmd = playlist.resolve_subcmd(extra[0])

    if subcmd == "create":
        if len(extra) < 2:
            e("Usage: playlist create <name>")
            return
        name = " ".join(extra[1:]).strip()
        if name.lower() in playlist.RESERVED_NAMES:
            e(f"     '{name}' is a reserved playlist name")
            return
        if playlist.create(name):
            i(f"Created playlist: {name}")
        else:
            m(f"Playlist '{name}' already exists")

    elif subcmd == "delete":
        if len(extra) < 2:
            e("Usage: playlist delete <name>")
            return
        raw = " ".join(extra[1:])
        actual = _resolve_or_error(raw)
        if not actual:
            return
        if playlist.delete(actual):
            i(f"Deleted playlist: {actual}")
        else:
            m(f"Playlist '{raw}' not found")

    elif subcmd == "rename":
        if len(extra) < 3:
            e("Usage: playlist rename <old> <new>")
            return
        old_raw = extra[1]
        old = _resolve_or_error(old_raw)
        if not old:
            return
        new = " ".join(extra[2:])
        if playlist.rename(old, new):
            i(f"Renamed: {old} -> {new}")
        else:
            e(f"     Cannot rename to '{new}' (already exists?)")

    elif subcmd == "duplicate":
        if len(extra) < 3:
            e("Usage: playlist duplicate <src> <new>")
            return
        src = _resolve_or_error(extra[1])
        if not src:
            return
        new_name = " ".join(extra[2:])
        if playlist.duplicate(src, new_name):
            i(f"Copied {src} -> {new_name}")
        else:
            e(f"     Cannot duplicate (source missing or '{new_name}' exists)")

    elif subcmd == "merge":
        if len(extra) < 3:
            e("Usage: playlist merge <dst> <src>")
            return
        dst = _resolve_or_error(extra[1])
        src = _resolve_or_error(extra[2])
        if not dst or not src:
            return
        result = playlist.merge(dst, src)
        if result is None:
            e("     Merge failed")
            return
        added, skipped = result
        i(f"Merged into {dst}: {added} added, {skipped} duplicates skipped")

    elif subcmd == "move":
        if len(extra) < 4 or not extra[2].isdigit() or not extra[3].isdigit():
            e("Usage: playlist move <name> <from> <to>   (1-based positions)")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        frm, to = int(extra[2]) - 1, int(extra[3]) - 1
        if playlist.move(actual, frm, to):
            i(f"Moved track {frm + 1} -> position {to + 1} in {actual}")
        else:
            e("     Index out of range")

    elif subcmd == "sort":
        if len(extra) < 2:
            e("Usage: playlist sort <name> [title|added|duration]")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        key = extra[2] if len(extra) > 2 else "title"
        if playlist.sort_playlist(actual, key):
            i(f"Sorted {actual} by {key}")
        else:
            e(f"     Cannot sort by '{key}' (use title|added|duration)")

    elif subcmd == "clear":
        if len(extra) < 2:
            e("Usage: playlist clear <name>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        n = playlist.clear(actual)
        i(f"Cleared {n} tracks from {actual}")

    elif subcmd == "dedupe":
        if len(extra) < 2:
            e("Usage: playlist dedupe <name>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        n = playlist.dedupe(actual)
        if n:
            i(f"Removed {n} duplicate tracks from {actual}")
        else:
            m(f"No duplicates in {actual}")

    elif subcmd == "info":
        if len(extra) < 2:
            e("Usage: playlist info <name>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        _print_info(actual)

    elif subcmd == "export":
        if len(extra) < 2:
            e("Usage: playlist export <name> [outfile.m3u]")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        out_path = extra[2] if len(extra) > 2 else None
        out = playlist.export_m3u(actual, out_path)
        if out:
            i(f"Exported {actual} -> {out}")
        else:
            e(f"     Playlist '{actual}' is empty")

    elif subcmd == "import":
        if len(extra) < 2:
            e("Usage: playlist import <file.m3u> [name]")
            return
        pl_name = extra[2] if len(extra) > 2 else None
        result = playlist.import_m3u(extra[1], pl_name)
        if result is None:
            e(f"     Cannot import '{extra[1]}'")
            return
        imported_name, count = result
        i(f"Imported {count} tracks into {imported_name}")

    elif subcmd == "list":
        if len(extra) < 2:
            e("Usage: playlist list <name>")
            return
        raw = extra[1]
        if raw.lower() in playlist.RESERVED_NAMES and "list_liked" in hooks:
            hooks["list_liked"]()
            return
        actual = _resolve_or_error(raw)
        if not actual:
            return
        _print_tracks(actual, playlist.get(actual))

    elif subcmd == "remove":
        if len(extra) < 3:
            e("Usage: playlist remove <name> <index_or_name>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        target = " ".join(extra[2:])
        if target.isdigit():
            ok, msg = playlist.remove_song(actual, index=int(target) - 1)
        else:
            ok, msg = playlist.remove_song(actual, title_match=target)
        if ok:
            i(f"Removed: {msg} from {actual}")
        else:
            e(f"     {msg}")

    elif subcmd == "add":
        if len(extra) < 3:
            e("Usage: playlist add <name> <index_or_query>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        make_source = hooks.get("add_source")
        if make_source is None:
            e("     Add is not supported in this mode")
            return
        track = make_source(extra[2:], args)
        if track is None:
            return
        state, msg = playlist.add_track(actual, track)
        if state == "added":
            i(f"Added: {_truncate(track.get('title'))} to {actual}")
        elif state == "skipped":
            m(f"Already in {actual}: {_truncate(track.get('title'))}")
        else:
            e(f"     {msg}")

    elif subcmd == "download":
        if len(extra) < 2:
            e("Usage: playlist download <name>")
            return
        actual = _resolve_or_error(extra[1])
        if not actual:
            return
        tracks = playlist.get(actual)
        if not tracks:
            m(f"Playlist '{actual}' is empty")
            return
        dl_hook = hooks.get("download")
        if dl_hook is None:
            e("     Download is not supported in this mode")
            return
        dl_hook(actual, tracks, args)

    elif subcmd == "play":
        if len(extra) < 2:
            e("Usage: playlist play <name>")
            return
        raw = extra[1]
        if getattr(args, "download", False):
            if raw.lower() in playlist.RESERVED_NAMES:
                e(f"     Cannot download reserved playlist '{raw}'")
                return
            actual = _resolve_or_error(raw)
            if not actual:
                return
            tracks = playlist.get(actual)
            if not tracks:
                m(f"Playlist '{actual}' is empty")
                return
            dl_hook = hooks.get("download")
            if dl_hook is None:
                e("     Download is not supported in this mode")
                return
            dl_hook(actual, tracks, args)
            return
        if raw.lower() in playlist.RESERVED_NAMES and "play_liked" in hooks:
            hooks["play_liked"](args)
            return
        actual = _resolve_or_error(raw)
        if not actual:
            return
        tracks = playlist.get(actual)
        if not tracks:
            m(f"Playlist '{actual}' is empty")
            return
        hooks["play"](actual, tracks, args)

    else:
        raw = extra[0]
        if raw.lower() in playlist.RESERVED_NAMES and "list_liked" in hooks:
            hooks["list_liked"]()
            return
        actual = _resolve_or_error(raw)
        if not actual:
            return
        _print_tracks(actual, playlist.get(actual))
