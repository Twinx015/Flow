"""`flow --import FILE`: CSV / m3u / txt song lists into downloads or playlists.

Parses rows with auto-detected columns (url, video id, title, artist, album,
duration), then offers an interactive panel: download everything into a new
playlist, download without a playlist, or play the tracks online one by one.
"""

import csv
import pathlib
import re
import sys
import threading

from backend import config, playlist, ui
from backend.Online import commands, player, youtube

M3U_TAGS = ("#EXTM3U", "#EXTINF")
_URL_RE = re.compile(r"https?://\S+")
_VID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|shorts/|embed/|/watch/)([A-Za-z0-9_-]{6,20})")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,20}$")

URL_KEYS = ("url", "link", "video url", "webpage url", "watch url", "youtube url")
ID_KEYS = ("video id", "video_id", "videoid", "id")
TITLE_KEYS = ("title", "track", "track name", "track title", "song", "song name", "name")
ARTIST_KEYS = (
    "artist",
    "artists",
    "artist name",
    "artist name(s)",
    "artist(s)",
    "channel",
    "channel name",
)
ALBUM_KEYS = ("album", "album name")
DURATION_KEYS = (
    "duration",
    "duration (ms)",
    "duration(ms)",
    "duration_ms",
    "duration time",
    "length",
)

OPTIONS = (
    "Download all as a playlist (asks for a name)",
    "Download (no playlist)",
    "Play online one by one",
)

P = config.Primary
S = config.Secondary
T = config.Tertiary
E = config.RED
R = config.Reset


def _blank_row():
    return {
        "url": "",
        "vid": "",
        "title": "",
        "artist": "",
        "album": "",
        "query": "",
        "duration": 0,
        "local": None,
    }


def _row_ok(row):
    return bool(
        row["url"] or row["vid"] or row["local"] or row["title"] or row["artist"]
    )


def _video_id(url):
    match = _VID_RE.search(url or "")
    return match.group(1) if match else ""


def _finish_row(row):
    row["vid"] = row["vid"] or _video_id(row["url"])
    row["query"] = " ".join(x for x in (row["title"], row["artist"]) if x).strip()
    return row if _row_ok(row) else None


def _parse_duration(name, value):
    """Seconds from an m:ss, plain-seconds, or milliseconds column."""
    text = str(value or "").strip()
    if not text:
        return 0
    if ":" in text:
        try:
            total = 0.0
            for part in text.split(":"):
                total = total * 60 + float(part)
        except ValueError:
            return 0
        return int(total) if total > 0 else 0
    try:
        num = int(float(text))
    except ValueError:
        return 0
    if num <= 0:
        return 0
    if "ms" in name.lower() or num > 10 * 3600:
        return num // 1000
    return num


def _parse_csv(path):
    rows = []
    try:
        with path.open(newline="", encoding="utf-8-sig", errors="replace") as fh:
            for raw in csv.DictReader(fh):
                row = _blank_row()
                for col, val in (raw or {}).items():
                    if val is None:
                        continue
                    key = (col or "").strip().lower()
                    val = str(val).strip()
                    if key in URL_KEYS and "://" in val:
                        found = _URL_RE.search(val)
                        row["url"] = found.group(0) if found else val
                    elif key in ID_KEYS and _ID_RE.match(val):
                        row["vid"] = val
                    elif key in TITLE_KEYS:
                        row["title"] = val or row["title"]
                    elif key in ARTIST_KEYS:
                        row["artist"] = val or row["artist"]
                    elif key in ALBUM_KEYS:
                        row["album"] = val or row["album"]
                    elif key in DURATION_KEYS:
                        row["duration"] = _parse_duration(key, val)
                parsed = _finish_row(row)
                if parsed:
                    rows.append(parsed)
    except (OSError, UnicodeDecodeError, csv.Error):
        return []
    return rows


def _parse_m3u(path):
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    pending = _blank_row()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            _, _, rest = line.partition(":")
            dur_part, _, title_part = rest.partition(",")
            try:
                pending["duration"] = int(float(dur_part))
            except ValueError:
                pending["duration"] = 0
            pending["title"] = title_part.strip()
            continue
        if line.startswith("#"):
            continue
        row = _blank_row()
        row["duration"] = pending["duration"]
        row["title"] = pending["title"]
        pending = _blank_row()
        if line.startswith(("http://", "https://")):
            row["url"] = line
        elif pathlib.Path(line).expanduser().is_file():
            row["local"] = str(pathlib.Path(line).expanduser())
            if not row["title"]:
                from backend import library

                row["title"] = library.title_for_stem(pathlib.Path(line).stem)
        else:
            row["query"] = line
            row["title"] = row["title"] or line
        parsed = _finish_row(row)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_txt(path):
    """One song per line: a URL (with optional leading label) or a search query."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("#EXTINF") or line.startswith("#EXTM3U"):
            continue
        row = _blank_row()
        match = _URL_RE.search(line)
        if match:
            row["url"] = match.group(0)
            rest = line[: match.start()] + line[match.end() :]
            row["title"] = rest.strip(" -–—|,:;")
            row["row_url"] = True  # marker only, kept for the preview
        else:
            row["title"] = line
        parsed = _finish_row(row)
        if parsed:
            rows.append(parsed)
    for row in rows:
        row.pop("row_url", None)
    return rows


def parse(path):
    """One file -> list of normalized rows; the extension guides the parser,
    with content sniffing for anything else."""
    path = pathlib.Path(path).expanduser()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _parse_csv(path)
    if suffix in (".m3u", ".m3u8"):
        return _parse_m3u(path)
    try:
        head = path.read_text(encoding="utf-8-sig", errors="replace")[:4096]
    except (OSError, UnicodeDecodeError):
        return []
    if any(tag in head for tag in M3U_TAGS):
        return _parse_m3u(path)
    first = next((line for line in head.splitlines() if line.strip()), "")
    header = first.lower()
    if "," in first and any(
        k in header for k in ("title", "url", "artist", "album", "song", "video")
    ):
        return _parse_csv(path)
    return _parse_txt(path)


def _style():
    return ui.questionary_style()


def _pick_action():
    """The panel: 0 playlist+download, 1 plain download, 2 play one by one."""
    try:
        import questionary
    except ImportError:
        questionary = None
    if questionary and sys.stdin.isatty():
        choices = [questionary.Choice(title=t, value=i) for i, t in enumerate(OPTIONS)]
        try:
            return questionary.select(
                "Import the tracks as:",
                choices=choices,
                default=0,
                style=_style(),
            ).ask()
        except Exception:
            return None
    print(f"{T}Interactive panel needs a terminal (run `flow --import FILE` in a shell){R}")
    return None


def _ask_playlist_name(path):
    """Name for the new playlist; defaults to the file's stem."""
    default = path.stem
    try:
        import questionary

        if sys.stdin.isatty():
            answer = questionary.text(
                f"Playlist name (default: {default}):",
                default="",
                style=_style(),
            ).ask()
            return (answer or "").strip() or default
    except Exception:
        pass
    try:
        answer = input(f"Playlist name (default: {default}): ").strip()
    except EOFError, KeyboardInterrupt:
        return None
    return answer or default


def _resolve(row, index=None, total=None):
    """One row -> (entry, title, duration) online, or ("local", Path), or None."""
    if row["local"]:
        return ("local", pathlib.Path(row["local"]))
    stop = False
    label = "Searching" if index is None else f"Resolving {index}/{total}"
    thread = threading.Thread(
        target=commands._spinner, args=(lambda: stop, label), daemon=True
    )
    thread.start()
    try:
        url = row["url"] or (
            f"https://www.youtube.com/watch?v={row['vid']}" if row["vid"] else ""
        )
        if url:
            entry = youtube.get_entry(url)
            if entry is None:
                return None
            title = entry.get("title") or row["title"] or "Unknown"
            dur = entry.get("duration") or row["duration"]
            return (entry, title, dur)
        query = row["query"] or row["title"]
        results = youtube.search(query, 1)
        if not results:
            return None
        return results[0]
    finally:
        stop = True
        thread.join()


def _skip_label(row):
    title = row["title"] or row["query"] or row["url"]
    return commands._truncate_title(title)


def _download_unit(unit, fmt):
    if unit[0] == "local":
        return
    entry, _title, _dur = unit
    commands._download_one(entry, fmt)


def _import_as_playlist(path, rows, args):
    name = _ask_playlist_name(path)
    if not name:
        return
    if playlist.create(name) is False and not playlist.exists(name):
        print(f"{E}     Cannot create playlist '{name}'{R}")
        return
    fmt = commands._resolve_fmt(args)
    if fmt is None:
        return
    total = len(rows)
    added = 0
    for index, row in enumerate(rows, 1):
        unit = _resolve(row, index, total)
        if unit is None:
            print(f"{E}     Skipped: {_skip_label(row)}{R}")
            continue
        if unit[0] == "local":
            track = playlist.make_track(
                title=row["title"] or pathlib.Path(row["local"]).stem,
                local_path=row["local"],
                duration=row["duration"],
            )
            if playlist.add_track(name, track)[0] == "added":
                added += 1
            print(f"{T}    On device: {commands._truncate_title(track['title'])}{R}")
            continue
        entry, title, dur = unit
        track = playlist.make_track(
            title=title,
            ref=row["url"] or entry.get("webpage_url"),
            video_id=entry.get("id"),
            duration=dur,
        )
        if playlist.add_track(name, track)[0] == "added":
            added += 1
        _download_unit(unit, fmt)
    print(f"{S} Imported {added}/{total} tracks into playlist '{name}'{R}")


def _download_only(rows, args):
    fmt = commands._resolve_fmt(args)
    if fmt is None:
        return
    total = len(rows)
    for index, row in enumerate(rows, 1):
        unit = _resolve(row, index, total)
        if unit is None:
            print(f"{E}     Skipped: {_skip_label(row)}{R}")
            continue
        _download_unit(unit, fmt)


def _play_online(rows, args):
    from backend.Offline import player as off_player

    commands._clear_all_nav()
    index = 0
    try:
        while 0 <= index < len(rows):
            row = rows[index]
            unit = _resolve(row, index + 1, len(rows))
            if unit is None:
                print(f"{E}     Skipped: {_skip_label(row)}{R}")
                index += 1
                continue
            nxt = (
                rows[index + 1].get("title") or rows[index + 1].get("query")
                if index + 1 < len(rows)
                else None
            )
            if unit[0] == "local":
                off_player.play_file(
                    unit[1],
                    row["title"] or "Unknown",
                    args,
                    next_title=nxt,
                    nav=(index + 1 < len(rows), index > 0),
                )
                index += commands._nav_delta()
                continue
            entry, title, _dur = unit
            player.play_entry(
                entry,
                title,
                args,
                next_title=nxt,
                nav=(index + 1 < len(rows), index > 0),
            )
            index += commands._nav_delta()
    except KeyboardInterrupt, commands._StopPlayback:
        pass


def run(paths, args=None):
    """Parse each file, preview the rows, run the chosen panel action."""
    if config.Mode != "Online":
        print(f"{E}Import needs online mode — run `switch` first{R}")
        return
    for raw in paths:
        path = pathlib.Path(raw).expanduser()
        if not path.exists():
            print(f"{E}Cannot find '{raw}'{R}")
            continue
        rows = parse(path)
        if not rows:
            print(f"{E}No tracks found in '{path.name}'{R}")
            continue
        print(f"{S}Importing {len(rows)} tracks from {path.name}:{R}")
        for index, row in enumerate(rows[:10], 1):
            label = row["title"] or row["query"] or row["url"]
            kind = "url " if (row["url"] or row["vid"] or row["local"]) else "search"
            print(f"{P}  {index}.{R} [{kind}] {label}")
        if len(rows) > 10:
            print(f"  ... and {len(rows) - 10} more")
        choice = _pick_action()
        if choice is None:
            return
        if choice == 0:
            _import_as_playlist(path, rows, args)
        elif choice == 1:
            _download_only(rows, args)
        else:
            _play_online(rows, args)
