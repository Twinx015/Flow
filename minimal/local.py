"""Downloaded library: listing, likes, downloads and renames."""

import pathlib

from backend import config, library
from backend.Offline import file as lib
from backend.Online import youtube

from . import out
from .common import current, entry_url, library_rows, song_line


def list_songs(query=None, limit=None, liked=None):
    """List downloaded songs, ascending by name."""
    rows = library_rows(query=query, liked=liked)
    total = len(rows)
    if limit:
        rows = rows[:limit]
    out.emit(
        {"songs": rows, "matched": total},
        [song_line(row) for row in rows] or [f"no downloaded songs matching {query!r}" if query else "no downloaded songs"],
    )


def liked(limit=None):
    """List liked songs."""
    rows = [
        {"video_id": entry["video_id"], "title": entry["title"]}
        for entry in library.get_liked_entries()
    ]
    if limit:
        rows = rows[:limit]
    out.emit(rows, [row["title"] for row in rows] or ["no liked songs"])


def like():
    """Like the current or last played track."""
    video_id, title = current()
    if not video_id:
        out.fail("cannot tell which track this is")
    if library.is_liked(video_id):
        out.emit({"status": "already liked", "video_id": video_id, "title": title}, f"already liked  {title}")
        return
    library.mark_liked(video_id, title)
    payload = {"status": "liked", "video_id": video_id, "title": title}
    text = f"liked  {title}"
    if config.DOWN_ON_LIKE and not library.get_download_path(video_id):
        with out.quiet():
            path = youtube.download_url(entry_url({"id": video_id}), config.DOWNLOAD_DIR, fmt=config.FORMAT)
        if path:
            payload["downloaded"] = str(path)
            text += f"  ->  {path}"
    out.emit(payload, text)


def unlike():
    """Remove the like from the current or last played track."""
    video_id, title = current()
    if not video_id:
        out.fail("cannot tell which track this is")
    if not library.is_liked(video_id):
        out.emit({"status": "not liked", "video_id": video_id, "title": title}, f"not liked  {title}")
        return
    library.mark_unliked(video_id)
    out.emit({"status": "unliked", "video_id": video_id, "title": title}, f"unliked  {title}")


def download(query, index=1, fmt=None):
    """Download a YouTube search result into the library."""
    with out.quiet():
        results = youtube.search(query, config.MAX_SEARCH_RESULTS)
    if not results:
        out.fail(f"no results for {query!r}")
    if not 1 <= index <= len(results):
        out.fail(f"index {index} out of range (1-{len(results)})")
    entry, title, _ = results[index - 1]
    fmt = fmt or config.FORMAT
    if fmt != "webm" and not config.FFMPEG:
        fmt = "webm"
    with out.quiet():
        path = youtube.download_url(entry_url(entry), config.DOWNLOAD_DIR, fmt=fmt)
    if not path:
        out.fail(f"download failed for {title!r}")
    out.emit(
        {"status": "downloaded", "title": title, "video_id": entry.get("id") or "", "path": str(path)},
        f"downloaded  {title}  ->  {path}",
    )


def delete(query):
    """Delete a downloaded song and its files."""
    path = _one_download(query)
    title = lib.display_name(path)
    video_id = pathlib.Path(path).stem
    with out.quiet():
        removed = library.delete(video_id)
    if removed:
        out.emit({"status": "deleted", "video_id": video_id, "title": title}, f"deleted  {title}")
    else:
        out.emit({"status": "no file", "video_id": video_id, "title": title}, f"no file on disk for {title}")


def rename(query, new_name):
    """Give a downloaded song a new name."""
    path = _one_download(query)
    old_name = lib.display_name(path)
    video_id = pathlib.Path(path).stem
    with out.quiet():
        renamed = library.rename(video_id, new_name)
    if not renamed:
        out.fail("rename failed")
    out.emit(
        {"status": "renamed", "video_id": video_id, "title": library.get_title(video_id)},
        f"renamed  {old_name} -> {new_name}",
    )


def _one_download(query):
    with out.quiet():
        matches = lib.find_songs(query)
    if not matches:
        out.fail(f"no downloaded song matching {query!r}")
    if len(matches) > 1:
        rows = [{"title": lib.display_name(p), "path": str(p)} for p in matches]
        out.emit(rows, [f"{r['title']}  {r['path']}" for r in rows])
        out.fail(f"{len(matches)} songs match {query!r}; be more specific", 2)
    return matches[0]
