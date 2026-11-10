"""Radio, tag upkeep, lyrics and playlists."""

import pathlib
import random

from backend import config, library, lyrics as lyrics_mod, playlist, status
from backend.Offline import file as lib
from backend.Online import youtube
from backend.status import _vid_from_thumb

from . import core, out
from .common import clock, current
from .local import _one_download


def radio(seed=None, limit=None):
    """Stream a radio mix seeded by a song, artist or channel name."""
    seed = seed or status.read().get("title") or ""
    if not seed:
        out.fail("radio needs a seed: flow-min radio <song|artist>")
    with out.quiet():
        tracks = youtube.fetch_radio(seed, limit or config.MAX_RESULTS_RADIO)
    if not tracks:
        out.fail(f"no radio tracks for {seed!r}")
    results = [
        ({"id": video_id, "webpage_url": f"https://www.youtube.com/watch?v={video_id}"}, title, duration)
        for title, video_id, duration in tracks
    ]
    core.play_online_queue(results, label=f"radio  {len(results)} tracks seeded by {seed}")


def radio_off(seed=None, limit=None):
    """Play the downloaded library shuffled, optionally filtered by name."""
    with out.quiet():
        paths = lib.get_all_songs()
    if seed:
        needle = seed.lower()
        paths = [p for p in paths if needle in lib.display_name(p).lower()]
    if not paths:
        out.fail(f"no downloaded songs matching {seed!r}" if seed else "no downloaded songs")
    random.shuffle(paths)
    if limit:
        paths = paths[:limit]
    core.play_paths(paths, label=f"radio  {len(paths)} local tracks")


def tags(action="list", args=None, shuffle=False, repeat=False, repeat_count=0, path=None):
    """Show user tags, or play/export/maintain them."""
    args = list(args or [])
    if action in (None, "list"):
        rows = [
            {"kind": "tag", "tag": tag, "count": count}
            for tag, count in library.all_song_tags()
        ]
        text = [f"{row['tag']}  {row['count']}" for row in rows]
        out.emit(rows, text or ["no tags yet"])
        return
    if action in ("play", "random"):
        tag = " ".join(args).strip()
        if not tag:
            out.fail(f"tags {action} needs a tag: tags {action} <tag>")
        with out.quiet():
            rows = library.songs_with_tag(tag)
        paths = [row["song"] for row in rows if row.get("song")]
        if not paths:
            out.fail(f"no downloaded songs tagged {tag!r}")
        if action == "random":
            paths = [random.choice(paths)]
            shuffle = repeat = False
        core.play_paths(
            paths,
            label=f"playing  {len(paths)} track(s) tagged {tag}",
            shuffle=shuffle,
            repeat=repeat,
            repeat_count=repeat_count,
        )
        return
    if action == "export":
        rest = list(args)
        dest = config.export_dest(rest) or (
            str(pathlib.Path(path).expanduser()) if path else None
        )
        tag = " ".join(rest).strip()
        if not tag:
            out.fail("tags export needs a tag: tags export <tag> [-p <dir>]")
        with out.quiet():
            rows = library.songs_with_tag(tag)
        if not rows:
            out.fail(f"no downloaded songs tagged {tag!r}")
        dest = dest or str(pathlib.Path.home() / "Downloads" / config._safe_filename(tag))
        with out.quiet():
            copied, tagged, out_dir = config.export_flow(
                dest, {row["video_id"] for row in rows}
            )
        if not copied:
            out.fail(f"no files to export for tag {tag!r}")
        out.emit(
            {"status": "exported", "tag": tag, "songs": copied, "path": str(out_dir)},
            f"exported  {copied} song(s) tagged '{tag}'  ->  {out_dir}",
        )
        return
    if action in ("add", "remove"):
        if len(args) < 2:
            out.fail(f"tags {action} needs a song and a tag: tags {action} <song> <tag>")
        path = _one_download(args[0])
        tag = " ".join(args[1:]).strip()
        if not tag:
            out.fail(f"tags {action}: empty tag")
        with out.quiet():
            ok = library.set_song_tag(pathlib.Path(path).stem, tag, action == "add")
        if not ok:
            out.fail(f"could not {action} the tag on {args[0]!r}")
        out.emit(
            {"status": action, "tag": tag, "song": lib.display_name(path)},
            f"{'tagged' if action == 'add' else 'untagged'}  '{tag}'  on  {lib.display_name(path)}",
        )
        return
    if action == "rename":
        if len(args) < 2:
            out.fail("tags rename needs a tag and its new name: rename <tag> <new>")
        old, new = args[0], " ".join(args[1:]).strip()
        with out.quiet():
            changed = library.rename_tag(old, new)
        out.emit(
            {"status": "renamed", "old": old, "new": new, "songs": changed},
            f"renamed  '{old}' -> '{new}'  ({changed} song(s))",
        )
        return
    if action == "delete":
        if not args:
            out.fail("tags delete needs a tag: delete <tag>")
        tag = " ".join(args).strip()
        with out.quiet():
            changed = library.delete_tag(tag)
        out.emit(
            {"status": "deleted", "tag": tag, "songs": changed},
            f"deleted  '{tag}'  ({changed} song(s))",
        )
        return
    out.fail(
        f"unknown tags action {action!r}; use list, play, random, export, add, remove, rename or delete"
    )


def lyrics():
    """Plain lyrics for the current or last played track."""
    video_id, title = current()
    if not title:
        out.fail("nothing playing")
    meta = library.get(video_id) or {}
    with out.quiet():
        found = lyrics_mod.fetch_lyrics(
            video_id=video_id, title=title, artist=meta.get("artist") or ""
        )
    if not found:
        out.fail(f"no lyrics found for {title!r}")
    payload = {
        "title": title,
        "artist": meta.get("artist") or "",
        "synced": bool(found.get("synced")),
        "lyrics": found.get("plain") or [],
    }
    out.emit(payload, payload["lyrics"] or ["no lyrics found"])


def playlist_cmd(name, action=None, argument=None, index=None):
    """Playlist subcommands: show, add, play, remove, clear, create, delete."""
    if action in (None, "show"):
        _playlist_show(name)
        return
    if action == "create":
        created = playlist.create(name)
        out.emit(
            {"status": "created" if created else "exists", "name": name},
            f"created  {name}" if created else f"playlist {name!r} already exists",
        )
        return
    if action == "delete":
        removed = playlist.delete(name)
        out.emit(
            {"status": "deleted" if removed else "missing", "name": name},
            f"deleted  {name}" if removed else f"no playlist {name!r}",
        )
        return
    if action == "clear":
        count = playlist.clear(name)
        out.emit({"status": "cleared", "name": name, "removed": count}, f"cleared  {count} track(s) from {name}")
        return
    if action == "remove":
        removed, detail = playlist.remove_song(name, index=index, title_match=argument)
        if not removed:
            out.fail(detail, 2)
        out.emit({"status": "removed", "name": name, "title": detail}, f"removed  {detail}")
        return
    if action == "add":
        _playlist_add(name, argument)
        return
    if action == "play":
        _playlist_play(name)
        return
    out.fail(f"unknown playlist action {action!r}; use show, add, play, remove, clear, create or delete")


def _playlist_show(name):
    tracks = playlist.get(name)
    if not tracks:
        out.fail(f"playlist {name!r} is empty or missing")
    rows = [
        {
            "index": index,
            "id": track.get("id") or "",
            "title": track.get("title") or "",
            "duration": int(track.get("duration") or 0),
            "local": bool(playlist.local_available(track)),
        }
        for index, track in enumerate(tracks, 1)
    ]
    text = [f"{row['index']}. {row['title']} ({clock(row['duration'])})" + ("" if row["local"] else "  [stream]") for row in rows]
    out.emit(rows, text)


def _playlist_add(name, query):
    if not query:
        out.fail("add needs a song name: flow-min playlist <name> add <song>")
    with out.quiet():
        results = youtube.search(query, config.MAX_SEARCH_RESULTS)
    if not results:
        out.fail(f"no results for {query!r}")
    entry, title, duration = results[0]
    video_id = entry.get("id") or ""
    added = playlist.add_song(
        name, title, video_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}", duration=int(duration or 0)
    )
    out.emit(
        {"status": "added" if added else "skipped", "name": name, "title": title, "video_id": video_id},
        f"added  {title}  to {name}" if added else f"{title} is already in {name}",
    )


def _playlist_play(name):
    tracks = playlist.get(name)
    if not tracks:
        out.fail(f"playlist {name!r} is empty or missing")
    paths = []
    for track in tracks:
        found = playlist.find_local_copy(track.get("id") or "")
        paths.append(pathlib.Path(found) if found else None)
    if all(paths):
        core.play_paths(paths, label=f"playing  {len(paths)} track(s) from {name}")
        return
    results = [
        ({"id": track.get("id") or "", "webpage_url": track.get("ref") or ""}, track.get("title") or "", int(track.get("duration") or 0))
        for track in tracks
    ]
    core.play_online_queue(results, label=f"streaming  {len(results)} track(s) from {name}")
