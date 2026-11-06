import os
import pathlib
import random
import signal
import sys
import time

from backend import (
    config,
    help_detail,
    ipc,
    keys,
    library,
    platform,
    playlist,
    plist_cli,
    shortcuts,
    summary,
)
from backend.config import merge_flags
from backend.Offline import file as lib
from backend.Offline import player
from backend.ping import is_connected

P = config.Primary
S = config.Secondary
T = config.Tertiary
M = config.Muted
E = config.RED
G = config.GREY
R = config.Reset
config.keep_live(globals())

m = lambda t: print(f"{M}{t}{R}")
e = lambda t: print(f"{E}{t}{R}")
i = lambda t: print(f"{P if config.Mode == 'Online' else S}{t}{R}")


def _fork_bg(label):
    config.kill_stored()
    if not platform.can_fork():
        i(f"{label} (background playback is unavailable on this OS)")
        return True
    pid = os.fork()
    if pid > 0:
        config.save_pid(pid)
        i(f"{label} in background (PID: {pid})")
        return False
    player._install_controls()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    return True


class _StopPlayback(Exception):
    """Raised by _nav_delta when playback should stop cleanly (MPRIS Stop)."""


def _nav_delta():
    if player._stop_req:
        player._stop_req = False
        player._next_req = False
        player._prev_req = False
        raise _StopPlayback
    if player._prev_req:
        player._prev_req = False
        player._next_req = False
        return -1
    player._next_req = False
    return 1


try:
    import readline

    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

_last_results = []
_last_played = None

_radio_quit = False
_radio_skip = False
_radio_tracks = []


def _radio_sigint(sig, frame):
    global _radio_skip
    _radio_skip = True


def _radio_sigquit(sig, frame):
    global _radio_quit
    _radio_quit = True


COMMANDS = {
    "play": "Play song(s) from local library | all by play all | and liked",
    "search": "Search local music library",
    "list": "List local music library",
    "radio": "Radio mode | shuffle & loop library (seed: radio <song>) | Ctrl+C next | Ctrl+Q quit",
    "clear": "Clears the terminal and re-print the logo.",
    "like": "Like the currently playing song",
    "unlike": "Unlike the currently playing song",
    "delete": "Delete a downloaded song (alias: dl-d)",
    "rename": "Rename a downloaded song (alias: re)",
    "lang": "Play songs by language tag | lang <tag> | -s shuffle",
    "artist": "Play songs by artist | artist <name> | -s shuffle",
    "tags": "Library tags | tags (editor) | tags list/add/remove/rename/delete",
    "playlist": "Manage playlists | create add remove list play rename move dup merge sort clear dedupe info export import (-m for multi add/remove) (alias: plist)",
    "switch": "Switch to Online mode (checks connection)",
    "help": "Show this help message",
    "short": "Show/update command shortcuts",
    "config": "Change primary/secondary/tertiary colors, format, display",
    "check": "Check all dependencies (ffmpeg, vlc, yt-dlp, psutil)",
    "summary": "Play summary | -l per-song table | -s <sort> | --top N | -c clear all plays",
    "export": "Copy downloaded songs to ~/Downloads | -p <path> for elsewhere",
    "exit": "Exit Flow",
}


class _Completer:
    def __init__(self):
        self.matches = []

    def complete(self, text, state):
        if state == 0:
            line = readline.get_line_buffer()
            parts = line.split()
            if len(parts) <= 1:
                options = [c for c in COMMANDS if c.startswith(text)]
            elif parts[0] == "play":
                songs = lib.get_song_names()
                options = sorted(
                    set(n for n in songs if n.lower().startswith(text.lower()))
                )
            elif parts[0] in ("delete", "dl-d", "rename", "re"):
                songs = lib.get_song_names()
                options = sorted(
                    set(n for n in songs if n.lower().startswith(text.lower()))
                )
            elif parts[0] in ("lang", "artist", "ar"):
                index = 1 if parts[0] in ("artist", "ar") else 0
                words = library.get_tag_counts()[index]
                options = sorted(w for w, _ in words if w.startswith(text.lower()))
            elif parts[0] == "tags":
                options = [
                    a for a in ("list", "add", "remove", "rename", "delete")
                    if a.startswith(text)
                ]
            else:
                options = []
            self.matches = options
        try:
            return self.matches[state]
        except IndexError:
            return None


def _setup_completion():
    if not _HAS_READLINE:
        return
    readline.set_completer(_Completer().complete)
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n;")


def run(cmd: str, extra: list[str], args):
    _setup_completion()
    cmd = shortcuts.resolve(cmd)
    inf = "-i" in extra
    extra = [x for x in extra if x != "-i"]
    if "-f" in extra:
        extra = [x for x in extra if x != "-f"]
        print(f"Unknown flag: -f")
    extra, args = (
        merge_flags(extra, args)
        if cmd not in ("config", "check", "short", "summary", "export")
        else (extra, args)
    )
    if cmd == "play":
        play(extra, args)
    elif cmd == "search":
        search(" ".join(extra) if extra else "")
    elif cmd == "import":
        e("Import needs online mode — run `switch` first")
    elif cmd in ("scrobbler", "scr"):
        from backend.scrobbler import cli as scrobbler_cli

        scrobbler_cli.handle(extra)
    elif cmd == "list":
        list_library()
    elif cmd in ("radio", "rd"):
        radio(extra, args)
    elif cmd == "like":
        like_track()
    elif cmd == "unlike":
        unlike_track()
    elif cmd in ("delete", "dl-d"):
        delete_song(extra)
    elif cmd in ("rename", "re"):
        rename_track(extra)
    elif cmd in ("lang", "language"):
        lang_track(extra, args)
    elif cmd in ("artist", "ar"):
        artist_track(extra, args)
    elif cmd == "tags":
        tags_cmd(extra, args)
    elif cmd in ("playlist", "plist"):
        playlist_cmd(extra, args)
    elif cmd == "switch":
        switch_mode()
    elif cmd == "help":
        show_help(inf)
    elif cmd == "short":
        shortcuts.cmd_short(extra, m)
    elif cmd == "config":
        config.cmd_config(extra, args)
    elif cmd == "check":
        config.check_deps()
    elif cmd == "summary":
        summary.cmd_summary(extra, args)
    elif cmd == "export":
        config.export_flow(config.export_dest(extra))
    else:
        e(f"Unknown command: {cmd}")


def _pick_index(results, question="Play which track?"):
    from ..ui import pick

    choices = [(lib.display_name(p), i) for i, p in enumerate(results)]
    choice, used = pick(
        question,
        choices,
        instruction="(↑↓ navigate, Enter to play)",
        mode="offline",
    )
    if used:
        return choice
    if not sys.stdin.isatty():
        return 0
    m("  Multiple matches:")
    for i, p in enumerate(results, 1):
        m(f"  {i}. {lib.display_name(p)}")
    while True:
        try:
            raw = input(f"{P}{question} [1-{len(results)}] {R}").strip()
        except EOFError, KeyboardInterrupt:
            return None
        if not raw:
            return None
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(results):
                return idx
        e("    Invalid choice")


def _pick_result():
    return _pick_index(_last_results)


def _pick_target(targets, action="delete"):
    from ..ui import pick

    choices = [(_truncate(t), t) for t in targets]
    choice, used = pick(
        "Pick a song",
        choices,
        instruction="(↑↓ navigate, Enter to select)",
        mode="offline",
    )
    if used:
        return choice
    if not sys.stdin.isatty():
        return targets[0]
    m("    Multiple matches:")
    for n, t in enumerate(targets, 1):
        m(f"      {n}. {_truncate(t)}")
    try:
        raw = input(
            f"{P}Pick a song to {action} [1-{len(targets)}] (Enter to cancel): {R}"
        ).strip()
    except EOFError, KeyboardInterrupt:
        return None
    if not raw.isdigit():
        return None
    sel = int(raw) - 1
    if sel < 0 or sel >= len(targets):
        e("     Invalid choice")
        return None
    return targets[sel]


def _style():
    from ..ui import questionary_style

    return questionary_style()


def _select_song():
    songs = lib.get_all_songs()
    if not songs:
        e("No songs in library")
        return None
    from ..ui import pick

    choices = [(lib.display_name(p), p) for p in songs]
    choice, used = pick(
        "Play which song?",
        choices,
        instruction="(↑↓ navigate, Enter to play)",
        mode="offline",
    )
    if used:
        return choice
    if not sys.stdin.isatty():
        return songs[0]
    return _pick_song_numbered(songs)


def _pick_song_numbered(songs):
    m("  Select a song:")
    for i, p in enumerate(songs, 1):
        m(f"  {i}. {lib.display_name(p)}")
    try:
        raw = input(f"{P}Play which song? [1-{len(songs)}] {R}").strip()
    except EOFError, KeyboardInterrupt:
        return None
    if not raw:
        return None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(songs):
            return songs[idx]
    e("    Invalid choice")
    return None


def _pick_many(results):
    from ..ui import make_choice, parse_index_list, pick_many

    choices = [
        make_choice(f"{i}. {lib.display_name(p)}", i) for i, p in enumerate(results)
    ]
    picked, used = pick_many(
        "Play which tracks?",
        choices,
        instruction="(Space toggle, a all, Enter play)",
        mode="offline",
    )
    if used:
        return None if picked is None else sorted(picked)
    if not sys.stdin.isatty():
        return [0]
    m("  Multiple matches:")
    for i, p in enumerate(results, 1):
        m(f"  {i}. {lib.display_name(p)}")
    while True:
        try:
            raw = input(
                f"{P}Play which tracks? [1-{len(results)}, e.g. 1,3 or all] {R}"
            ).strip()
        except EOFError, KeyboardInterrupt:
            return None
        if not raw:
            return None
        if raw.lower() in ("a", "all"):
            return list(range(len(results)))
        picked = parse_index_list(raw, len(results))
        if picked:
            return picked
        e("    Invalid choice")


def play(extra: list[str], args):
    global _last_results, _last_played
    arg = " ".join(extra) if extra else None

    if arg and arg == "liked":
        _play_liked(args)
        return
    elif arg and arg == "all":
        _play_all(args)
        return

    multi = getattr(args, "multi", False)
    if not arg:
        song_path = _select_song()
        if song_path is None:
            return
    elif arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(_last_results):
            e("Index out of range")
            return
        song_path = _last_results[idx]
    else:
        results = lib.find_songs(arg)
        if not results:
            e(f"No songs found matching '{arg}'")
            return
        if len(results) == 1:
            song_path = results[0]
        elif multi:
            _last_results = results
            picks = _pick_many(results)
            if not picks:
                return
            _play_queue([results[p] for p in picks], args)
            return
        else:
            _last_results = results
            idx = _pick_result()
            if idx is None:
                return
            song_path = results[idx]

    _last_played = song_path
    if getattr(args, "bg", False):
        if not _fork_bg("Now playing"):
            return
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    if repeat:
        try:
            while True:
                player.play_file(song_path, lib.display_name(song_path), args)
                if player._stop_req:
                    player._stop_req = False
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt, _StopPlayback:
            pass
    else:
        player.play_file(song_path, lib.display_name(song_path), args)


def _play_queue(paths, args):
    global _last_played
    if getattr(args, "bg", False):
        if not _fork_bg("Now playing"):
            return
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    try:
        while True:
            idx = 0
            while 0 <= idx < len(paths):
                _last_played = paths[idx]
                player.play_file(
                    paths[idx],
                    lib.display_name(paths[idx]),
                    args,
                    nav=(idx + 1 < len(paths), idx > 0),
                )
                idx += _nav_delta()
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt, _StopPlayback:
        pass


def resume(title, args, thumb=None):
    global _last_played
    local = None
    if thumb:
        try:
            vid = pathlib.Path(thumb).stem
            local = library.get_download_path(vid)
        except Exception:
            local = None
    if not local:
        matches = lib.find_songs(title)
        if len(matches) == 1:
            local = matches[0]
        elif len(matches) > 1:
            m("Multiple matches for last track:")
            for i, p in enumerate(matches, 1):
                m(f"  {i}. {lib.display_name(p)}")
            return
    if not local:
        e("No local copy of the last track found")
        return
    fpath = pathlib.Path(local)
    _last_played = fpath
    if getattr(args, "bg", False):
        if not _fork_bg("Resuming"):
            return
    player.play_file(fpath, title, args)


def _play_liked(args):
    global _last_played
    liked = lib.get_liked_songs()
    if not liked:
        e("No liked songs yet")
        return
    songs = list(liked)
    if getattr(args, "shuffle", False):
        random.shuffle(songs)
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    if getattr(args, "bg", False):
        if not _fork_bg("Playing liked songs"):
            return
    try:
        while True:
            idx = 0
            while 0 <= idx < len(songs):
                song = songs[idx]
                _last_played = song
                player.play_file(
                    song,
                    lib.display_name(song),
                    args,
                    nav=(idx + 1 < len(songs), idx > 0),
                )
                idx += _nav_delta()
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt, _StopPlayback:
        pass


def _play_all(args):
    global _last_played
    all_songs = lib.get_all_songs()
    if not all_songs:
        e("No downloaded songs yet")
        return
    songs = list(all_songs)
    if getattr(args, "shuffle", False):
        random.shuffle(songs)
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    if getattr(args, "bg", False):
        if not _fork_bg("Playing all songs"):
            return
    try:
        while True:
            idx = 0
            while 0 <= idx < len(songs):
                song = songs[idx]
                _last_played = song
                player.play_file(
                    song,
                    lib.display_name(song),
                    args,
                    nav=(idx + 1 < len(songs), idx > 0),
                )
                idx += _nav_delta()
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt, _StopPlayback:
        pass


def like_track():
    global _last_played
    if not _last_played:
        e("No song currently playing")
        return
    song_path = _last_played
    liked = lib.get_liked_songs()
    if song_path in liked:
        lib.unlike_song(song_path)
        i(f"Unliked: {lib.display_name(song_path)}")
    else:
        dest = lib.like_song(song_path)
        if dest:
            i(f"Liked: {lib.display_name(song_path)}")
        else:
            m(f"{lib.display_name(song_path)} is already liked")


def unlike_track():
    global _last_played
    if not _last_played:
        e("No song currently playing")
        return
    song_path = _last_played
    liked = lib.get_liked_songs()
    if song_path in liked:
        lib.unlike_song(song_path)
        i(f"Unliked: {lib.display_name(song_path)}")
    else:
        m(f"Not liked: {lib.display_name(song_path)}")


def act_on_current(action, title, thumb=None):
    local = None
    if thumb:
        try:
            vid = pathlib.Path(thumb).stem
            local = library.get_download_path(vid)
        except Exception:
            local = None
    if not local:
        matches = lib.find_songs(title)
        if len(matches) == 1:
            local = matches[0]
        elif len(matches) > 1:
            e(f"    Multiple local matches for '{title}'")
            return
    if not local:
        e(f"    No local copy found for '{title}'")
        return
    fpath = pathlib.Path(local)
    if action == "download":
        i(f"    Already on device: {lib.display_name(fpath)}")
        return
    if action == "unlike":
        liked = lib.get_liked_songs()
        if fpath in liked:
            lib.unlike_song(fpath)
            i(f"    Unliked: {lib.display_name(fpath)}")
        else:
            m(f"    Not liked: {lib.display_name(fpath)}")
        return
    liked = lib.get_liked_songs()
    if fpath in liked:
        lib.unlike_song(fpath)
        i(f"    Unliked: {lib.display_name(fpath)}")
    else:
        dest = lib.like_song(fpath)
        if dest:
            i(f"    Liked: {lib.display_name(fpath)}")
        else:
            m(f"    {lib.display_name(fpath)} is already liked")


def _audio_files(index):
    return [
        (_vid, info.get("song"), info.get("title", ""))
        for _vid, info in index.items()
        if info.get("song")
    ]


def _match_songs(arg, prefer_library=False):
    """Last-results index or a fuzzy name match; None means the index was bogus.

    `prefer_library` resolves a number against the name-sorted listing `list`
    prints instead, so `rename 17` means the same row whether or not a
    `list`/`search` just ran.
    """
    global _last_results
    if arg.isdigit():
        idx = int(arg) - 1
        if prefer_library:
            listed = lib.get_songs()
            if 0 <= idx < len(listed):
                return [listed[idx]]
        if 0 <= idx < len(_last_results):
            return [_last_results[idx]]
        return None

    targets = []
    index = library.load()
    q = arg.lower()
    for _vid, path, title in _audio_files(index):
        if (
            q in (title or "").lower()
            or q in (_vid or "").lower()
            or (path and q in pathlib.Path(path).stem.lower())
        ):
            targets.append(pathlib.Path(path))
    for f in lib.find_songs(arg):
        if f not in targets:
            targets.append(f)
    return targets


def rename_track(extra):
    arg = " ".join(extra) if extra else None
    if not arg:
        e("Usage: rename <name | index>")
        return

    targets = _match_songs(arg, prefer_library=True)
    if targets is None:
        e("     Index out of range")
        return
    if not targets:
        e(f"     No song matching '{arg}'")
        return
    if len(targets) > 1:
        song = _pick_target(targets, "rename")
        if song is None:
            m("    Cancelled")
            return
    else:
        song = targets[0]

    old_name = lib.display_name(song)
    listed = lib.get_songs()
    label = old_name
    if song in listed:
        label = f"{old_name} (#{listed.index(song) + 1})"
    try:
        new_name = input(f"{P}New name for '{label}': {R}").strip()
    except EOFError, KeyboardInterrupt:
        return
    if not new_name:
        m("     Rename cancelled")
        return
    if new_name == old_name:
        m(f"     Already named '{old_name}'")
        return

    library.rename(song.stem, new_name)
    i(f"Renamed: {old_name} → {new_name}")


def delete_song(extra):
    global _last_results
    arg = " ".join(extra) if extra else None
    if not arg:
        e("Usage: delete <name | index>")
        return

    targets = _match_songs(arg)
    if targets is None:
        e("     Index out of range")
        return

    if not targets:
        e(f"     No downloaded song matching '{arg}'")
        return

    if len(targets) > 1:
        path = _pick_target(targets)
        if path is None:
            m("    Cancelled")
            return
    else:
        path = targets[0]

    try:
        ans = input(f"{M}Delete '{_truncate(path)}' (y/N)? {R}")
    except EOFError:
        return
    if ans.strip().lower() not in ("y", "yes"):
        m("    Cancelled")
        return

    vid = path.stem
    if library.get_download_path(vid):
        library.delete(vid)
    else:
        lib.delete_file(path)
    if library.get(vid):
        library.mark_unliked(vid)
    i(f"    Deleted: {_truncate(path)}")


def _truncate(p):
    return config._truncate_title(library.title_for_stem(pathlib.Path(p).stem))


def playlist_cmd(extra, args=None):
    global _last_played

    def add_source(target_words, args):
        target = target_words[0]
        if target.isdigit():
            idx = int(target) - 1
            if idx < 0 or idx >= len(_last_results):
                e("Index out of range")
                return None
            song_path = _last_results[idx]
        else:
            results = lib.find_songs(target)
            if not results:
                e(f"No songs found matching '{target}'")
                return None
            if len(results) == 1:
                song_path = results[0]
            else:
                idx = _pick_index(results)
                if idx is None:
                    return None
                song_path = results[idx]
        return playlist.make_track(
            title=lib.display_name(song_path), ref=str(song_path), source="local"
        )

    def play(actual, tracks, args):
        global _last_played
        tracks = list(tracks)
        if getattr(args, "shuffle", False):
            random.shuffle(tracks)
        repeat = getattr(args, "repeat", False)
        repeat_count = getattr(args, "repeat_count", 0)
        iteration = 0
        if getattr(args, "bg", False):
            if not _fork_bg(f"Playing playlist: {actual}"):
                return
        try:
            while True:
                idx = 0
                while 0 <= idx < len(tracks):
                    s = tracks[idx]
                    src = playlist.resolve_track(s)
                    fpath = pathlib.Path(src)
                    if not fpath.exists():
                        m(f"    Skipping {s.get('title', 'Unknown')} (file not found)")
                        idx += 1
                        continue
                    next_title = (
                        tracks[idx + 1].get("title") if idx + 1 < len(tracks) else None
                    )
                    _last_played = fpath
                    player.play_file(
                        fpath,
                        s.get("title", "Unknown"),
                        args,
                        next_title=next_title,
                        nav=(idx + 1 < len(tracks), idx > 0),
                    )
                    idx += _nav_delta()
                if not repeat:
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt, _StopPlayback:
            pass

    def list_liked():
        songs = lib.get_liked_songs()
        if not songs:
            m("No liked songs yet")
            return
        i("  liked:")
        for idx, p in enumerate(songs, 1):
            m(f"  {idx}. {lib.display_name(p)}")

    plist_cli.handle(
        extra,
        args,
        {
            "add_source": add_source,
            "play": play,
            "play_liked": _play_liked,
            "list_liked": list_liked,
        },
    )


def search(query: str):
    global _last_results, _last_played
    if not query:
        e("Search query required")
        return
    results = lib.find_songs(query)
    if not results:
        e("No results found")
        return
    _last_results = results
    idx = _pick_index(results)
    if idx is None:
        return
    song_path = results[idx]
    _last_played = song_path
    player.play_file(song_path, lib.display_name(song_path), None)


def list_library():
    global _last_results
    songs = lib.get_songs()
    liked = lib.get_liked_songs()

    if songs:
        _last_results = songs
        i("\nSongs:")
        for idx, p in enumerate(songs, 1):
            m(f"  {idx}. {lib.display_name(p)}")
    if liked:
        i("\nLiked Songs:")
        for p in liked:
            m(f"  {lib.display_name(p)}")
    if not songs and not liked:
        e("No music in library")


def _play_tag_rows(rows, args, label):
    paths = [
        pathlib.Path(r["song"])
        for r in rows
        if r.get("song") and pathlib.Path(r["song"]).exists()
    ]
    if not paths:
        e(f"No downloaded songs tagged {label}")
        return
    if getattr(args, "shuffle", False):
        random.shuffle(paths)
    i(f"  {len(paths)} song(s) tagged {label}")
    _play_queue(paths, args)


def lang_track(extra, args):
    """`lang <tag>` plays every downloaded song with that one-word language tag."""
    tag = " ".join(extra).strip()
    if not tag:
        e("Usage: lang <tag>")
        list_tags()
        return
    _play_tag_rows(library.get_tag_rows("language", tag), args, f"'{tag}'")


def artist_track(extra, args):
    """`artist <name>` plays every downloaded song by that artist."""
    name = " ".join(extra).strip()
    if not name:
        e("Usage: artist <name>")
        list_tags()
        return
    _play_tag_rows(library.get_tag_rows("artist", name), args, f"'{name}'")


def list_tags():
    """What the library can be played by right now."""
    langs, artists = library.get_tag_counts()
    custom = library.all_song_tags()
    if not langs and not artists and not custom:
        e("No tags yet")
        m("  Try: tags add <song> <tag>  (bare `tags` opens the editor)")
        return
    if langs:
        m("\nLanguages:")
        for word, count in langs:
            m(f"  {word} ({count})")
    if artists:
        m("\nArtists:")
        for word, count in artists:
            m(f"  {word} ({count})")
    if custom:
        m("\nTags:")
        for word, count in custom:
            m(f"  {word} ({count})")


def edit_tags():
    """Interactive tag editor: language, artist and free-form tags."""
    from ..ui import pick

    try:
        import questionary  # noqa: F401 - presence check
    except ImportError:
        questionary = None
    if questionary is None:
        e("Tag editor needs questionary; the plain forms still work:")
        m("  tags list | tags add <song> <tag> | tags remove <song> <tag>")
        m("  tags rename <tag> <new> | tags delete <tag>")
        return
    kind, used = pick(
        "What do you want to edit?",
        [
            ("Language tags", "language"),
            ("Artist tags", "artist"),
            ("Free-form tags", "custom"),
        ],
        instruction="(↑↓ navigate, Enter to select)",
        mode="offline",
    )
    if not used or kind is None:
        return
    if kind == "custom":
        _edit_custom()
    else:
        label = "Language" if kind == "language" else "Artist"
        _edit_field(kind, label)


def _edit_field(field, label):
    """Whole-tag and per-song editing for the language/artist column."""
    from ..ui import pick, questionary_style

    actions = [
        (f"Set {label} value on songs", "set"),
        (f"Rename a {label} value everywhere", "rename"),
        (f"Delete {label} value(s) everywhere", "delete"),
        (f"Clear {label} value(s) on songs", "clear"),
    ]
    action, used = pick(
        f"{label} tags - what do you want to do?",
        actions,
        instruction="(↑↓ navigate, Enter to select)",
        mode="offline",
    )
    if not used or action is None:
        return
    style = questionary_style("offline")
    if action == "set":
        ids = _pick_songs(f"Which songs get this {label.lower()}?")
        if ids is None:
            return
        if not ids:
            m("    No songs picked")
            return
        value = _ask_text(f"{label} value (empty clears it):", style)
        if value is None:
            m("    Cancelled")
            return
        value = value.strip()
        done = 0
        for vid in ids:
            if library.set_song_field(vid, field, value):
                done += 1
        m(f"     {label.lower()} set on {done} song(s)")
    elif action == "rename":
        _edit_field_rename(field, label, style)
    elif action == "delete":
        _edit_field_delete(field, label, style)
    else:
        _edit_field_clear(field, label, style)


def _edit_field_rename(field, label, style):
    from ..ui import pick

    words = library.get_tag_counts()[0 if field == "language" else 1]
    if not words:
        m(f"     No {label.lower()} tags yet")
        return
    choice, used = pick(
        f"Which {label.lower()} tag?",
        [(f"{word} ({count})", word) for word, count in words],
        instruction="(↑↓ navigate, Enter to select)",
        mode="offline",
    )
    if not used or choice is None:
        return
    new = _ask_text(f"New name for '{choice}':", style, default=choice)
    if new is None or not new.strip():
        m("    Cancelled")
        return
    new = new.strip()
    if new.lower() == choice.lower():
        m(f"     Already named '{choice}'")
        return
    changed = library.rename_field_tag(field, choice, new)
    m(f"     Renamed {choice!r} -> {new!r} on {changed} song(s)")


def _edit_field_delete(field, label, style):
    words = library.get_tag_counts()[0 if field == "language" else 1]
    if not words:
        m(f"     No {label.lower()} tags yet")
        return
    picks = _pick_many_tags(f"Which {label.lower()} tags?", words)
    if picks is None:
        return
    if not picks:
        m("    No tags picked")
        return
    if not _ask_confirm(
        f"Delete {len(picks)} {label.lower()} tag(s) from every song?", style
    ):
        m("    Cancelled")
        return
    total = 0
    for word in picks:
        total += library.delete_field_tag(field, word)
    m(f"     Deleted {len(picks)} {label.lower()} tag(s) from {total} song(s)")


def _edit_field_clear(field, label, style):
    ids = _pick_songs(f"Which songs clear their {label.lower()}?")
    if ids is None:
        return
    if not ids:
        m("    No songs picked")
        return
    if not _ask_confirm(f"Clear {label.lower()} from {len(ids)} song(s)?", style):
        m("    Cancelled")
        return
    done = 0
    for vid in ids:
        if library.set_song_field(vid, field, ""):
            done += 1
    m(f"     Cleared {label.lower()} from {done} song(s)")


def _edit_custom():
    """Interactive editing for the free-form tags."""
    from ..ui import pick, questionary_style

    actions = [
        ("Add a tag to songs", "add"),
        ("Remove a tag from songs", "remove"),
        ("Rename a tag everywhere", "rename"),
        ("Delete tag(s) everywhere", "delete"),
        ("Clear tags on songs", "clear"),
    ]
    action, used = pick(
        "Free-form tags - what do you want to do?",
        actions,
        instruction="(↑↓ navigate, Enter to select)",
        mode="offline",
    )
    if not used or action is None:
        return
    style = questionary_style("offline")
    if action == "add":
        _edit_custom_add(style)
    elif action == "remove":
        _edit_custom_remove(style)
    elif action == "rename":
        _edit_custom_rename(style)
    elif action == "delete":
        _edit_custom_delete(style)
    else:
        _edit_custom_clear(style)


def _edit_custom_add(style):
    """Add one tag to several checkbox-picked songs."""
    existing = library.all_song_tags()
    if existing:
        m("     existing tags: " + ", ".join(word for word, _ in existing))
    ids = _pick_songs("Which songs get the tag?")
    if ids is None:
        return
    if not ids:
        m("    No songs picked")
        return
    tag = _ask_text("Tag name:", style)
    if tag is None:
        m("    Cancelled")
        return
    tag = tag.strip()
    if not tag:
        m("    Empty tag - cancelled")
        return
    done = 0
    for vid in ids:
        if library.set_song_tag(vid, tag, True):
            done += 1
    m(f"     Tagged {done} song(s) with '{tag}'")


def _edit_custom_remove(style):
    """Pick several songs, then one tag to take off all of them."""
    from ..ui import pick

    ids = _pick_songs("Which songs lose the tag?")
    if ids is None:
        return
    if not ids:
        m("    No songs picked")
        return
    tags = set()
    for vid in ids:
        tags.update(library.song_tags(vid))
    if not tags:
        m("     None of those songs have free-form tags")
        return
    choice, used = pick(
        "Which tag?", [(t, t) for t in sorted(tags)], mode="offline"
    )
    if not used or choice is None:
        return
    done = 0
    for vid in ids:
        if choice in library.song_tags(vid):
            library.set_song_tag(vid, choice, False)
            done += 1
    m(f"     Removed '{choice}' from {done} song(s)")


def _edit_custom_rename(style):
    """Rename one tag everywhere; each tag needs its own new name."""
    from ..ui import pick

    words = library.all_song_tags()
    if not words:
        m("     No free-form tags yet")
        return
    choice, used = pick(
        "Which tag?",
        [(f"{word} ({count})", word) for word, count in words],
        mode="offline",
    )
    if not used or choice is None:
        return
    new = _ask_text(f"New name for '{choice}':", style, default=choice)
    if new is None or not new.strip():
        m("    Cancelled")
        return
    new = new.strip()
    if new == choice:
        m(f"     Already named '{choice}'")
        return
    changed = library.rename_tag(choice, new)
    m(f"     Renamed {choice!r} -> {new!r} on {changed} song(s)")


def _edit_custom_delete(style):
    """Checkbox-pick several tags and delete them all after one confirm."""
    words = library.all_song_tags()
    if not words:
        m("     No free-form tags yet")
        return
    picks = _pick_many_tags("Which tags?", words)
    if picks is None:
        return
    if not picks:
        m("    No tags picked")
        return
    if not _ask_confirm(f"Delete {len(picks)} tag(s) from every song?", style):
        m("    Cancelled")
        return
    total = 0
    for word in picks:
        total += library.delete_tag(word)
    m(f"     Deleted {len(picks)} tag(s) from {total} song(s)")


def _edit_custom_clear(style):
    """Clear every free-form tag on several checkbox-picked songs."""
    ids = _pick_songs("Which songs lose all their tags?")
    if ids is None:
        return
    if not ids:
        m("    No songs picked")
        return
    if not _ask_confirm(f"Clear every tag on {len(ids)} song(s)?", style):
        m("    Cancelled")
        return
    dropped = 0
    for vid in ids:
        dropped += library.clear_song_tags(vid)
    m(f"     Cleared {dropped} tag(s) from {len(ids)} song(s)")


def _song_label(row):
    parts = [row["title"]]
    if row["artist"]:
        parts.append(row["artist"])
    if row["language"]:
        parts.append(f"({row['language']})")
    if row["tags"]:
        parts.append("[" + ", ".join(row["tags"]) + "]")
    return "  ".join(parts)


def _pick_songs(prompt):
    """Checkbox-pick downloaded songs; [] when none picked, None on cancel."""
    rows = library.downloaded_rows()
    if not rows:
        m("     No downloaded songs to tag")
        return None
    from ..ui import pick_many

    choices = [(_song_label(r), r["video_id"]) for r in rows]
    picked, used = pick_many(prompt, choices, mode="offline")
    if not used:
        return None
    return picked or []


def _pick_many_tags(prompt, words):
    """Checkbox-pick tags; [] when none picked, None on cancel."""
    from ..ui import pick_many

    if not words:
        return None
    choices = [(f"{word} ({count})", word) for word, count in words]
    picked, used = pick_many(prompt, choices, mode="offline")
    if not used:
        return None
    return picked or []


def _ask_text(prompt, style, default=""):
    try:
        import questionary

        return questionary.text(prompt, default=default, style=style).ask()
    except KeyboardInterrupt, EOFError:
        return None


def _ask_confirm(prompt, style):
    try:
        import questionary

        return questionary.confirm(prompt, style=style).ask()
    except KeyboardInterrupt, EOFError:
        return None


def tags_add_song(extra):
    """`tags add <song> <tag>` puts a free-form tag on one downloaded song."""
    if len(extra) < 2:
        e("Usage: tags add <song> <tag>")
        return
    path = _one_song(extra[0])
    if path is None:
        e("     No downloaded song matching that name")
        return
    tag = " ".join(extra[1:]).strip()
    if not tag:
        e("Usage: tags add <song> <tag>")
        return
    if library.set_song_tag(path.stem, tag, True):
        m(f"     Tagged '{_truncate(path)}' with '{tag}'")
    else:
        e("     Could not tag that song")


def tags_remove_song(extra):
    """`tags remove <song> <tag>` takes a free-form tag off one downloaded song."""
    if len(extra) < 2:
        e("Usage: tags remove <song> <tag>")
        return
    path = _one_song(extra[0])
    if path is None:
        e("     No downloaded song matching that name")
        return
    tag = " ".join(extra[1:]).strip()
    if library.set_song_tag(path.stem, tag, False):
        m(f"     Removed '{tag}' from '{_truncate(path)}'")


def tags_rename(extra):
    """`tags rename <tag> <new>` renames a free-form tag on every song."""
    if len(extra) < 2:
        e("Usage: tags rename <tag> <new tag>")
        return
    old = extra[0]
    new = " ".join(extra[1:]).strip()
    changed = library.rename_tag(old, new)
    if changed:
        m(f"     Renamed '{old}' -> '{new}' on {changed} song(s)")
    else:
        m(f"     No song uses tag '{old}'")


def tags_delete(extra):
    """`tags delete <tag>` drops a free-form tag from every song."""
    if not extra:
        e("Usage: tags delete <tag>")
        return
    tag = " ".join(extra).strip()
    changed = library.delete_tag(tag)
    if changed:
        m(f"     Deleted tag '{tag}' from {changed} song(s)")
    else:
        m(f"     No song uses tag '{tag}'")


def _one_song(query):
    """Resolve a name/index to one downloaded song path, or None."""
    targets = _match_songs(query, prefer_library=True)
    if not targets:
        return None
    if len(targets) > 1:
        return _pick_target(targets, "tag")
    return targets[0]


def tags_cmd(extra, args):
    """`tags` opens the tag editor; `tags list|add|remove|rename|delete` are scriptable."""
    if not extra:
        if sys.stdin.isatty():
            edit_tags()
        else:
            list_tags()
        return
    action = extra[0].lower()
    rest = extra[1:]
    if action == "list":
        list_tags()
    elif action == "add":
        tags_add_song(rest)
    elif action == "remove":
        tags_remove_song(rest)
    elif action == "rename":
        tags_rename(rest)
    elif action == "delete":
        tags_delete(rest)
    else:
        e(f"Unknown tags action: {action}")
        m("  Try: tags | tags list | tags add <song> <tag>")
        m("       tags remove <song> <tag> | tags rename <tag> <new> | tags delete <tag>")


def switch_mode():
    if is_connected():
        config.Mode = "Online"
    else:
        e("No internet connection")


def _radio_seed(query):
    global _last_results

    head, _, tail = query.rpartition(" ")
    if tail.isdigit():
        idx = int(tail) - 1
        if head:
            matches = lib.find_songs(head)
            label = f"'{head}'"
        else:
            matches = _last_results
            label = "the last results"
        if not matches:
            e(f"No songs found matching {label}")
            return None
        if not 0 <= idx < len(matches):
            e(f"Index out of range for {label} (1-{len(matches)})")
            return None
        return matches[idx]

    matches = lib.find_songs(query)
    if not matches:
        e(f"No songs found matching '{query}'")
        return None
    if len(matches) == 1:
        return matches[0]
    _last_results = matches
    idx = _pick_index(matches, "Seed radio with which track?")
    return None if idx is None else matches[idx]


def _radio_queue(query):

    tracks = list(lib.get_all_songs())
    if not query:
        random.shuffle(tracks)
        return tracks
    seed = _radio_seed(query)
    if seed is None:
        return None
    rest = [p for p in tracks if p != seed]
    random.shuffle(rest)
    return [seed, *rest]


def radio(extra, args):
    global _last_played, _radio_quit, _radio_skip, _radio_tracks
    if not lib.get_all_songs():
        e("No songs in library")
        return
    query = " ".join(extra) if extra else None
    tracks = _radio_queue(query)
    if tracks is None:
        return
    _radio_tracks = tracks

    if getattr(args, "bg", False):
        if not _fork_bg(f"Radio playing {len(tracks)} tracks"):
            return

    _radio_quit = False
    _radio_skip = False

    old_sigint = signal.signal(signal.SIGINT, _radio_sigint)
    old_sigquit = None
    old_sigusr1 = None
    ctl = sys.stdin.fileno()
    tty_fd = None
    player._radio_active = True

    if not platform.is_windows():
        old_sigquit = signal.signal(signal.SIGQUIT, _radio_sigquit)
        old_sigusr1 = signal.getsignal(signal.SIGUSR1)
        try:
            tty_fd = os.open("/dev/tty", os.O_RDWR)
            ctl = tty_fd
        except OSError:
            pass
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)

    def _radio_key(ch):
        if ch == 0x10:
            ipc.dispatch("pause")

    radio_reader = keys.RawReader(_radio_key, fd=ctl)
    radio_reader.start()

    flags = {"quit": lambda: _radio_quit, "skip": lambda: _radio_skip}

    seed = f"seeded with '{lib.display_name(tracks[0])}' | " if query else ""
    i(f"\n[Radio] {seed}playing {len(tracks)} songs (Ctrl+C next, Ctrl+Q quit)")
    try:
        while True:
            idx = 0
            while 0 <= idx < len(tracks) and not _radio_quit:
                _radio_skip = False
                song = tracks[idx]
                next_song = tracks[idx + 1] if idx + 1 < len(tracks) else None
                next_title = lib.display_name(next_song) if next_song else None
                _last_played = song
                player.play_file(
                    song,
                    lib.display_name(song),
                    args,
                    flags=flags,
                    next_title=next_title,
                    nav=(idx + 1 < len(tracks), idx > 0),
                )
                if _radio_quit:
                    break
                idx += _nav_delta()
            if _radio_quit:
                break
    except KeyboardInterrupt, _StopPlayback:
        pass
    finally:
        player._radio_active = False
        radio_reader.stop()
        if not platform.is_windows():
            if tty_fd is not None:
                try:
                    os.close(tty_fd)
                except OSError:
                    pass
            try:
                signal.signal(signal.SIGQUIT, old_sigquit)
            except (ValueError, OSError):
                pass
            try:
                signal.signal(signal.SIGUSR1, old_sigusr1)
            except (ValueError, OSError):
                pass
        signal.signal(signal.SIGINT, old_sigint)


def show_help(inf=False):
    if inf:
        print(f"{T}Offline Commands (detailed):{R}")
        for cmd, lines in help_detail._offline_help().items():
            for line in lines:
                print(f"  {line}")
            print()
    else:
        print(f"{T}Offline Commands:{R}")
        for cmd, desc in COMMANDS.items():
            print(f"  {T}{cmd:12s}{R} {G}{desc}{R}")
        print(
            f"  {T}plugins{R} {G}install/list/run/update Flow plugins | flow plugins list{R}"
        )
        print(f"{G}  Use 'help -i' for detailed usage{R}")
