import errno
import fcntl
import os
import pathlib
import random
import signal
import sys
import termios
import threading
import time

from .. import help_detail, library, playlist, plist_cli, shortcuts
from ..imports import config, merge_flags
from ..Offline import player as off_player
from . import player, savan, youtube

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


def _fork_bg(label):
    config.kill_stored()
    pid = os.fork()
    if pid > 0:
        config.save_pid(pid)
        i(f"{label} in background (PID: {pid})")
        return False
    player.setup_nav_signals()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    return True


def _nav_delta():
    prev = player._prev_req or off_player._prev_req
    if prev:
        player._prev_req = False
        off_player._prev_req = False
        player._next_req = False
        off_player._next_req = False
        return -1
    player._next_req = False
    off_player._next_req = False
    return 1


COMMANDS = {
    "play": "Play a song from YouTube",
    "search": "Search YouTube for tracks",
    "savan": "Play a song from JioSaavn (alias: svn)",
    "savan-s": "Search JioSaavn for tracks (alias: svn-s)",
    "radio": "Generate a mix | radio <song> [index] | -p save as playlist | -d download",
    "like": "Like a song",
    "download": "Download audio from YouTube | -f <format> (opus, m4a, mp3, webm)",
    "delete": "Delete a downloaded song (alias: dl-d)",
    "playlist": "Manage playlists | create add remove list play rename move dup merge sort clear dedupe info export import download (alias: plist)",
    "switch": "Switch to Offline mode",
    "help": "Show this help message",
    "short": "Show/update command shortcuts",
    "config": "Change primary/secondary/tertiary colors, format, display",
    "check": "Check all dependencies (ffmpeg, vlc, yt-dlp, psutil)",
    "export": "Backup ~/.flow config to ~/Downloads",
    "exit": "Exit Flow",
}


def run(cmd: str, extra: list[str], args):
    cmd = shortcuts.resolve(cmd)
    inf = "-i" in extra
    extra = [x for x in extra if x != "-i"]
    playlist_name = None
    if "-p" in extra:
        pi = extra.index("-p")
        extra = extra[:pi] + extra[pi + 1 :]
        if extra and not extra[0].startswith("-"):
            playlist_name = extra.pop(0)
        setattr(args, "save_playlist", playlist_name or True)
    extra, args = (
        merge_flags(extra, args)
        if cmd not in ("config", "check", "short")
        else (extra, args)
    )
    if cmd == "play":
        play(extra, args)
    elif cmd == "search":
        search(" ".join(extra) if extra else "")
    elif cmd in ("savan", "svn"):
        savan_cmd(extra, args)
    elif cmd in ("savan-s", "svn-s"):
        savan_search(" ".join(extra) if extra else "")
    elif cmd == "like":
        like_track()
    elif cmd == "download":
        download(extra)
    elif cmd in ("delete", "dl-d"):
        delete_download(extra)
    elif cmd == "switch":
        switch_mode()
    elif cmd == "help":
        show_help(inf)
    elif cmd in ("radio", "rd"):
        radio(extra, args)
    elif cmd in ("playlist", "plist"):
        playlist_cmd(extra, args)
    elif cmd == "short":
        shortcuts.cmd_short(extra, m)
    elif cmd == "config":
        config.cmd_config(extra, args)
    elif cmd == "check":
        config.check_deps()
    elif cmd == "export":
        config.export_flow()
    else:
        print(f"Unknown command: {cmd}")


def _spinner(stop, label="Searching"):
    chars = "|/-\\"
    i = 0
    while not stop():
        sys.stdout.write(f"\r{P}{label}... {chars[i]}{R}")
        sys.stdout.flush()
        time.sleep(0.1)
        i = (i + 1) % len(chars)
    sys.stdout.write("\r" + " " * 50 + "\r")
    sys.stdout.flush()


def _do_search(query):
    global _last_results, _radio_tracks
    stop = False
    t = threading.Thread(target=_spinner, args=(lambda: stop,), daemon=True)
    t.start()
    _last_results = youtube.search(query, config.MAX_SEARCH_RESULTS)
    _radio_tracks = []
    stop = True
    t.join()


def play(extra: list[str], args):
    if config.kill_stored():
        print(f"{P}Stopped VLC{R}")
    global _last_results, _last_played
    arg = " ".join(extra) if extra else None
    if not arg:
        print("No song specified")
        return

    if getattr(args, "download", False):
        download(extra)

    if arg == "liked":
        _play_liked(args)
        return

    repeat = getattr(args, "repeat", False)
    shuffle = getattr(args, "shuffle", False)

    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(_last_results):
            print("Index out of range")
            return
        entry, title, _ = _last_results[idx]
        entry = _resolve_entry(entry)
        _last_played = (entry, title)
        if getattr(args, "bg", False):
            if not _fork_bg("Now playing"):
                return
        if repeat:
            repeat_count = getattr(args, "repeat_count", 0)
            iteration = 0
            try:
                while True:
                    player.play_entry(entry, title, args)
                    iteration += 1
                    if repeat_count > 0 and iteration >= repeat_count:
                        break
            except KeyboardInterrupt:
                pass
        else:
            player.play_entry(entry, title, args)
        return

    _do_search(arg)
    if not _last_results:
        print("No results found")
        return

    if repeat or shuffle:
        results = list(_last_results)
        if shuffle:
            random.shuffle(results)
        repeat_count = getattr(args, "repeat_count", 0)
        iteration = 0
        try:
            while True:
                idx = 0
                while 0 <= idx < len(results):
                    entry, title, _ = results[idx]
                    entry = _resolve_entry(entry)
                    _last_played = (entry, title)
                    if getattr(args, "bg", False):
                        if not _fork_bg("Now playing"):
                            return
                    player.play_entry(entry, title, args)
                    idx += _nav_delta()
                if not repeat:
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt:
            pass
    else:
        entry, title, _ = _last_results[0]
        entry = _resolve_entry(entry)
        _last_played = (entry, title)
        if getattr(args, "bg", False):
            if not _fork_bg("Now playing"):
                return
        player.play_entry(entry, title, args)


def _resolve_entry(entry):
    if entry.get("formats"):
        return entry
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if not url and entry.get("id"):
        url = f"https://www.youtube.com/watch?v={entry['id']}"
    if not url:
        return entry
    full = youtube.get_entry(url)
    return full if full else entry


def _play_liked(args):
    global _last_played
    liked = library.get_liked_entries()
    if not liked:
        e("     No liked songs yet")
        return
    tracks = [(s["title"], "") for s in liked if s.get("title")]
    if not tracks:
        e("     No liked songs yet")
        return
    if getattr(args, "shuffle", False):
        random.shuffle(tracks)
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    try:
        while True:
            idx = 0
            while 0 <= idx < len(tracks):
                title, url = tracks[idx]
                _do_search(title)
                if not _last_results:
                    m(f"    Skipping {_truncate_title(title)} (not found)")
                    idx += 1
                    continue
                entry, _, _ = _last_results[0]
                entry = _resolve_entry(entry)
                _last_played = (entry, title)
                player.play_entry(entry, title, args)
                idx += _nav_delta()
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt:
        pass


_savan_results = []


def savan_cmd(extra, args):
    if config.kill_stored():
        print(f"{P}Stopped VLC{R}")
    global _savan_results, _last_played
    arg = " ".join(extra) if extra else None
    if not arg:
        e("No song specified")
        return

    repeat = getattr(args, "repeat", False)
    shuffle = getattr(args, "shuffle", False)

    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(_savan_results):
            e("Index out of range")
            return
        entry, title, dur = _savan_results[idx]
        url = savan.best_url(entry)
        if not url:
            e("No playable URL found")
            return
        _last_played = (entry, title)
        if getattr(args, "bg", False):
            if not _fork_bg("Now playing"):
                return
        if repeat:
            repeat_count = getattr(args, "repeat_count", 0)
            iteration = 0
            try:
                while True:
                    player.play_url(url, title, args, dur, savan.thumb_url(entry))
                    iteration += 1
                    if repeat_count > 0 and iteration >= repeat_count:
                        break
            except KeyboardInterrupt:
                pass
        else:
            player.play_url(url, title, args, dur, savan.thumb_url(entry))
        return

    stop = False
    t = threading.Thread(target=_spinner, args=(lambda: stop,), daemon=True)
    t.start()
    _savan_results = savan.search(arg)
    stop = True
    t.join()
    if not _savan_results:
        e("No results found")
        return

    if repeat or shuffle:
        results = list(_savan_results)
        if shuffle:
            random.shuffle(results)
        repeat_count = getattr(args, "repeat_count", 0)
        iteration = 0
        try:
            while True:
                idx = 0
                while 0 <= idx < len(results):
                    entry, title, dur = results[idx]
                    url = savan.best_url(entry)
                    if not url:
                        e(f"No playable URL for {_truncate_title(title)}, skipping")
                        idx += 1
                        continue
                    _last_played = (entry, title)
                    if getattr(args, "bg", False):
                        if not _fork_bg("Now playing"):
                            return
                    player.play_url(url, title, args, dur, savan.thumb_url(entry))
                    idx += _nav_delta()
                if not repeat:
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt:
            pass
    else:
        entry, title, dur = _savan_results[0]
        url = savan.best_url(entry)
        if not url:
            e("No playable URL found")
            return
        _last_played = (entry, title)
        if getattr(args, "bg", False):
            if not _fork_bg("Now playing"):
                return
        player.play_url(url, title, args, dur, savan.thumb_url(entry))


def savan_search(query):
    global _savan_results
    if not query:
        e("Search query required")
        return
    stop = False
    t = threading.Thread(target=_spinner, args=(lambda: stop,), daemon=True)
    t.start()
    _savan_results = savan.search(query)
    stop = True
    t.join()
    if not _savan_results:
        e("No results found")
        return
    for i, (_, title, dur) in enumerate(_savan_results, 1):
        mins, secs = divmod(int(dur), 60)
        m(f"  {i}. {_truncate_title(title)}  ({mins}:{secs:02d})")


def like_track():
    global _last_played
    if not _last_played:
        e("     No song currently playing")
        return
    entry, title = _last_played
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if not url and entry.get("id"):
        url = f"https://www.youtube.com/watch?v={entry['id']}"
    if not url:
        e("     No URL for current song")
        return
    config.dev_print(
        "Like Track",
        {
            "title": title,
            "url": url,
            "video_id": entry.get("id"),
            "webpage_url": entry.get("webpage_url"),
            "original_url": entry.get("original_url"),
        },
    )
    video_id = library.key_for(url, entry.get("id"))
    if library.is_liked(video_id):
        library.mark_unliked(video_id)
        i(f"    Unliked: {_truncate_title(title)}")
    else:
        library.mark_liked(video_id, title)
        i(f"    Liked: {_truncate_title(title)}")
        if entry.get("id"):
            try:
                library.download_thumbnail(video_id, entry.get("thumbnail"))
            except Exception:
                pass
            if not library.get_download_path(video_id):
                _like_autodownload(url, video_id, title)


def _like_autodownload(url: str, video_id: str, title: str):
    fmt = config.FORMAT
    if fmt != "webm" and not config.FFMPEG:
        fmt = "webm"
    try:
        stop = False
        t = threading.Thread(
            target=_spinner,
            args=(lambda: stop, f"Downloading liked song: {_truncate_title(title)}"),
            daemon=True,
        )
        t.start()
        try:
            youtube.download_url(url, config.DOWNLOAD_DIR, fmt=fmt)
        finally:
            stop = True
            t.join()
        i(f"    Downloaded: {_truncate_title(title)}")
    except Exception as exc:
        e(f"    Auto-download failed: {exc}")


def search(query: str):
    global _last_results
    if not query:
        print("Search query required")
        return
    _do_search(query)
    if not _last_results:
        print("No results found")
        return
    for i, (entry, title, dur) in enumerate(_last_results, 1):
        mins, secs = divmod(int(dur), 60)
        uploader = entry.get("uploader", "")
        m(f"  {i}. {_truncate_title(title)}  ({mins}:{secs:02d}) [{uploader}]")


_truncate_title = config._truncate_title


def radio(extra, args):
    if config.kill_stored():
        print(f"{P}Stopped VLC{R}")
    global _radio_tracks
    query = " ".join(extra) if extra else None
    if not query:
        e("     Usage: radio <song_name> [index]")
        return

    parts = query.rsplit(" ", 1)
    if len(parts) == 1 and parts[0].isdigit():
        idx = int(parts[0]) - 1
        if _radio_tracks and 0 <= idx < len(_radio_tracks):
            title, vid, dur = _radio_tracks[idx]
            url = f"https://www.youtube.com/watch?v={vid}"
            config.dev_print(
                "Radio (play by index)",
                {
                    "title": title,
                    "video_id": vid,
                    "url": url,
                    "duration": f"{dur}s",
                },
            )
            entry = youtube.get_entry(url)
            if getattr(args, "bg", False):
                if not _fork_bg("Now playing"):
                    return
            player.play_entry(entry, title, args)
            return
        if _last_results and 0 <= idx < len(_last_results):
            entry, title, _ = _last_results[idx]
            query = title
        else:
            e("     Index out of range or no results loaded")
            return
    elif len(parts) > 1 and parts[-1].isdigit():
        idx = int(parts[-1]) - 1
        query = parts[0]
        if _radio_tracks and 0 <= idx < len(_radio_tracks):
            title, vid, dur = _radio_tracks[idx]
            url = f"https://www.youtube.com/watch?v={vid}"
            config.dev_print(
                "Radio (play by query+index)",
                {
                    "title": title,
                    "video_id": vid,
                    "url": url,
                    "duration": f"{dur}s",
                },
            )
            entry = youtube.get_entry(url)
            if getattr(args, "bg", False):
                if not _fork_bg("Now playing"):
                    return
            player.play_entry(entry, title, args)
            return
        e("     Index out of range or no radio loaded")
        return

    stop = False
    t = threading.Thread(target=_spinner, args=(lambda: stop,), daemon=True)
    t.start()
    tracks = youtube.fetch_radio(query, config.MAX_RESULTS_RADIO)
    stop = True
    t.join()

    if not tracks:
        e("     No radio tracks found")
        return

    _radio_tracks = tracks

    save_pl = getattr(args, "save_playlist", None)
    pl_name = save_pl if isinstance(save_pl, str) else tracks[0][0]
    if save_pl:
        if not playlist.exists(pl_name):
            playlist.create(pl_name)
        added = skipped = 0
        for title, vid, dur in _radio_tracks:
            url = f"https://www.youtube.com/watch?v={vid}"
            state, _ = playlist.add_track(
                pl_name,
                playlist.make_track(
                    title=title, ref=url, video_id=vid, duration=int(dur or 0)
                ),
            )
            if state == "added":
                added += 1
            elif state == "skipped":
                skipped += 1
        msg = f"    Saved {added} tracks to playlist: {pl_name}"
        if skipped:
            msg += f" ({skipped} duplicates skipped)"
        i(msg)
        if not getattr(args, "download", False):
            return

    if getattr(args, "download", False):
        dl_dir = playlist.download_dir(pl_name) if save_pl else config.DOWNLOAD_DIR
    else:
        dl_dir = None

    if getattr(args, "shuffle", False):
        random.shuffle(_radio_tracks)

    global _radio_quit, _radio_skip
    _radio_quit = False
    _radio_skip = False

    if getattr(args, "bg", False):
        if not _fork_bg(f"Playing {len(_radio_tracks)} tracks"):
            return

    old_sigint = signal.signal(signal.SIGINT, _radio_sigint)
    old_sigquit = signal.signal(signal.SIGQUIT, _radio_sigquit)
    old_sigusr1 = signal.getsignal(signal.SIGUSR1)

    fd = sys.stdin.fileno()
    old_term = None
    old_fd_flags = None
    try:
        old_term = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[0] &= ~termios.IXON
        new[6][termios.VQUIT] = 0x11
        new[6][termios.VSUSP] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
        old_fd_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_fd_flags | os.O_NONBLOCK)
    except termios.error, OSError:
        pass

    def _radio_sigusr1(sig, frame):
        player._sigusr1_toggle(sig, frame)

    signal.signal(signal.SIGUSR1, _radio_sigusr1)
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    player._radio_active = True

    radio_stop = threading.Event()

    def _radio_input_reader():
        try:
            while not radio_stop.is_set():
                try:
                    ch = os.read(fd, 1)
                except OSError as ex:
                    if ex.errno == errno.EAGAIN:
                        time.sleep(0.05)
                        continue
                    break
                if ch == b"\x10":
                    os.kill(os.getpid(), signal.SIGUSR1)
        except OSError:
            pass

    radio_reader = threading.Thread(target=_radio_input_reader, daemon=True)
    radio_reader.start()

    flags = {"quit": lambda: _radio_quit, "skip": lambda: _radio_skip}

    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0

    try:
        while True:
            idx = 0
            while idx < len(_radio_tracks) and not _radio_quit:
                title, vid, dur = _radio_tracks[idx]
                url = f"https://www.youtube.com/watch?v={vid}"
                config.dev_print(
                    "Radio (playing track)",
                    {
                        "title": title,
                        "video_id": vid,
                        "url": url,
                        "duration": f"{dur}s",
                        "position": f"{idx + 1}/{len(_radio_tracks)}",
                    },
                )
                entry = youtube.get_entry(url)

                if idx + 1 < len(_radio_tracks):
                    n_title, n_vid, n_dur = _radio_tracks[idx + 1]
                    n_short = _truncate_title(n_title)
                    n_mins, n_secs = divmod(int(n_dur), 60)
                    print(f"{T}\n\t[⥤ Next: {n_short:30s} {n_mins}:{n_secs:02d}]{R}")

                _radio_skip = False
                if dl_dir:
                    filepath = youtube.download_url(url, dl_dir)
                    i(
                        f"    Downloaded ({idx + 1}/{len(_radio_tracks)}): {_truncate_title(title)}"
                    )
                    off_player.play_file(filepath, title, args)
                else:
                    player.play_entry(entry, title, args, flags=flags)
                idx += _nav_delta()
            if not repeat or _radio_quit:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt:
        _radio_quit = True
    finally:
        player._radio_active = False
        radio_stop.set()
        if radio_reader.is_alive():
            radio_reader.join(timeout=0.2)
        if old_term is not None:
            try:
                if old_fd_flags is not None:
                    fcntl.fcntl(fd, fcntl.F_SETFL, old_fd_flags)
                termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
            except termios.error, OSError:
                pass
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGQUIT, old_sigquit)
        signal.signal(signal.SIGUSR1, old_sigusr1)


def download(extra: list[str]):
    global _last_results
    fmt = None
    if "-f" in extra:
        fi = extra.index("-f")
        if fi + 1 < len(extra):
            fmt = extra[fi + 1].lower()
            extra = extra[:fi] + extra[fi + 2 :]
        else:
            e("Usage: download <query> -f <format>")
            return
    if fmt and fmt not in ("opus", "m4a", "mp3", "webm"):
        e("Unknown format. Options: opus, m4a, mp3, webm")
        return
    if not fmt:
        fmt = config.FORMAT
    if fmt != "webm" and not config.FFMPEG:
        e(f"ffmpeg not found. Cannot convert to {fmt}. Install ffmpeg or use webm.")
        return

    arg = " ".join(extra) if extra else None
    if not arg:
        e("No song specified")
        return

    url = None
    title = "Unknown"
    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(_last_results):
            e("     Index out of range")
            return
        entry, _, _ = _last_results[idx]
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url and entry.get("id"):
            url = f"https://www.youtube.com/watch?v={entry['id']}"
        title = entry.get("title", "Unknown")
    else:
        _do_search(arg)
        if not _last_results:
            e("     No results found")
            return
        entry, _, _ = _last_results[0]
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not url and entry.get("id"):
            url = f"https://www.youtube.com/watch?v={entry['id']}"
        title = entry.get("title", "Unknown")

    if not url:
        e("     No URL found for this entry")
        return

    vid = entry.get("id") or ""
    if vid:
        existing = library.get_download_path(vid)
        if existing:
            existing_ext = pathlib.Path(existing).suffix.lstrip(".").lower()
            if existing_ext == fmt:
                i(f"    Already downloaded: {_truncate_title(title)}")
                return

    label = f"Downloading: {_truncate_title(title)}"
    if fmt != "webm":
        label += f" → {fmt}"
    stop = False
    t = threading.Thread(target=_spinner, args=(lambda: stop, label), daemon=True)
    t.start()
    try:
        youtube.download_url(url, config.DOWNLOAD_DIR, fmt=fmt)
    finally:
        stop = True
        t.join()
    if fmt != "webm":
        i(f"    Converted to {fmt}: {_truncate_title(title)}")
    else:
        i(f"    Downloaded: {_truncate_title(title)}")


_AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".wma", ".aac", ".webm"}


def _find_vid_by_path(index, path):
    for _vid, info in index.items():
        if info.get("path") == path:
            return _vid
    return None


def delete_download(extra: list[str]):
    global _last_results
    arg = " ".join(extra) if extra else None
    if not arg:
        e("Usage: delete <name | index>")
        return

    vid = None
    title = None
    if arg.isdigit():
        idx = int(arg) - 1
        if idx < 0 or idx >= len(_last_results):
            e("     Index out of range")
            return
        entry, title, _ = _last_results[idx]
        vid = entry.get("id")
    else:
        index = library.load()
        matches = [
            (_vid, info.get("path"), info.get("title", ""))
            for _vid, info in index.items()
            if arg.lower() in info.get("title", "").lower()
            or arg.lower() in (_vid or "").lower()
        ]
        if len(matches) == 1:
            vid, _, title = matches[0]
        elif len(matches) > 1:
            m("    Multiple matches:")
            for i, (_vid, _path, t) in enumerate(matches, 1):
                m(f"      {i}. {_truncate_title(t)}")
            return
        else:
            candidates = [
                f
                for f in sorted(config.DOWNLOAD_DIR.rglob("*"))
                if f.is_file()
                and f.suffix.lower() in _AUDIO_EXTS
                and (
                    arg.lower() in f.stem.lower()
                    or arg.lower() in library.title_for_stem(f.stem).lower()
                )
            ]
            if not candidates:
                e(f"     No downloaded song matching '{arg}'")
                return
            if len(candidates) > 1:
                m("    Multiple matches:")
                for i, f in enumerate(candidates, 1):
                    m(f"      {i}. {library.title_for_stem(f.stem)}")
                return
            path = str(candidates[0])
            vid = _find_vid_by_path(index, path)
            title = library.title_for_stem(candidates[0].stem)

    if not vid:
        e("     No video id found for this song")
        return

    path = library.get_download_path(vid)
    if not path:
        e("     Song not found in downloads")
        return

    try:
        ans = input(f"{M}Delete '{_truncate_title(title or pathlib.Path(path).stem)}'? (y/N) {R}")
    except EOFError:
        return
    if ans.strip().lower() not in ("y", "yes"):
        m("    Cancelled")
        return

    if library.delete(vid):
        i(f"    Deleted: {_truncate_title(title or pathlib.Path(path).stem)}")
    else:
        e("     Nothing to delete")


def switch_mode():
    config.Mode = "Offline"


def playlist_cmd(extra, args):
    global _last_played

    def add_source(target_words, args):
        target = target_words[0]
        if target.isdigit():
            idx = int(target) - 1
            if idx < 0 or idx >= len(_last_results):
                e("Index out of range")
                return None
            entry, title, dur = _last_results[idx]
        else:
            query = " ".join(target_words)
            _do_search(query)
            if not _last_results:
                e("No results found")
                return None
            entry, title, dur = _last_results[0]
        vid = entry.get("id", "")
        url = (
            entry.get("webpage_url")
            or entry.get("url")
            or f"https://www.youtube.com/watch?v={vid}"
        )
        track = playlist.make_track(
            title=title, ref=url, video_id=vid, duration=int(dur or 0)
        )
        local = playlist.find_local_copy(vid)
        if local:
            track["local_path"] = local
        return track

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
                    title = s.get("title", "Unknown")
                    short = _truncate_title(title)
                    src = playlist.resolve_track(s)
                    if isinstance(src, pathlib.Path):
                        print(
                            f"{P}Playing local copy: {short}...{R}", end="\r", flush=True
                        )
                        _last_played = (None, title)
                        playlist.backfill_local(actual, idx, src)
                        off_player.play_file(src, title, args)
                        idx += _nav_delta()
                        continue
                    vid = s.get("id", "")
                    url = src or f"https://www.youtube.com/watch?v={vid}"
                    print(f"{P}Fetching: {short}...{R}", end="\r", flush=True)
                    entry = youtube.get_entry(url)
                    if not entry:
                        m(f"    Skipping {short} (unavailable)")
                        idx += 1
                        continue
                    _last_played = (entry, title)
                    player.play_entry(entry, title, args)
                    idx += _nav_delta()
                if not repeat:
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt:
            pass

    def list_liked():
        liked = library.get_liked_entries()
        if not liked:
            m("No liked songs yet")
            return
        i("  liked:")
        for idx, s in enumerate(liked, 1):
            m(f"  {idx}. {_truncate_title(s.get('title', 'Unknown'))}")

    def download(actual, tracks, args):
        dl_dir = playlist.download_dir(actual)
        i(f"    Downloading {len(tracks)} songs to {dl_dir}...")
        done = 0
        for idx, s in enumerate(tracks, 1):
            vid = s.get("id", "")
            url = s.get("ref") or f"https://www.youtube.com/watch?v={vid}"
            try:
                youtube.download_url(url, dl_dir)
                local = playlist.find_local_copy(vid) or str(dl_dir)
                playlist.backfill_local(actual, idx - 1, local)
                done += 1
                i(
                    f"    Downloaded ({idx}/{len(tracks)}): {_truncate_title(s.get('title'))}"
                )
            except Exception as exc:
                e(
                    f"     Failed ({idx}/{len(tracks)}): {_truncate_title(s.get('title'))} - {exc}"
                )
        if done == len(tracks):
            i(f"    All {done} tracks available on device")

    plist_cli.handle(
        extra,
        args,
        {
            "add_source": add_source,
            "play": play,
            "play_liked": _play_liked,
            "list_liked": list_liked,
            "download": download,
        },
    )


def show_help(inf=False):
    if inf:
        print(f"{T}Online Commands (detailed):{R}")
        for cmd, lines in help_detail._online_help().items():
            for line in lines:
                print(f"  {line}")
            print()
    else:
        print(f"{T}Online Commands:{R}")
        for cmd, desc in COMMANDS.items():
            print(f"  {T}{cmd:12s}{R} {G}{desc}{R}")
        print(f"{G}  Use 'help -i' for detailed usage{R}")
