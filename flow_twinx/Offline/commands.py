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

from .. import help_detail, playlist, shortcuts
from ..imports import config, is_connected, merge_flags
from . import file as lib
from . import player

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


def _fork_bg(label):
    config.kill_stored()
    pid = os.fork()
    if pid > 0:
        config.save_pid(pid)
        i(f"{label} in background (PID: {pid})")
        return False
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    return True


try:
    import readline

    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

_last_results = []
_last_played = None

_radio_quit = False
_radio_skip = False


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
    "radio": "Radio mode | shuffle & loop library | Ctrl+C next | Ctrl+Q quit",
    "like": "Like the currently playing song",
    "playlist": "Manage playlists (alias: plist)",
    "switch": "Switch to Online mode (checks connection)",
    "help": "Show this help message",
    "short": "Show/update command shortcuts",
    "config": "Change primary/secondary/tertiary colors, format, display",
    "check": "Check all dependencies (ffmpeg, vlc, yt-dlp, psutil)",
    "export": "Backup ~/.flow config to ~/Downloads",
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
                albums = lib.get_album_names()
                all_names = songs + albums
                options = sorted(
                    set(n for n in all_names if n.lower().startswith(text.lower()))
                )
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
    extra, args = (
        merge_flags(extra, args)
        if cmd not in ("config", "check", "short")
        else (extra, args)
    )
    if cmd == "play":
        play(extra, args)
    elif cmd == "search":
        search(" ".join(extra) if extra else "")
    elif cmd == "list":
        list_library()
    elif cmd in ("radio", "rd"):
        radio(extra, args)
    elif cmd == "like":
        like_track()
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
    elif cmd == "export":
        config.export_flow()
    else:
        e(f"Unknown command: {cmd}")


def play(extra: list[str], args):
    global _last_results, _last_played
    arg = " ".join(extra) if extra else None
    if not arg:
        e("No song specified")
        return

    if arg == "liked":
        _play_liked(args)
        return
    elif arg == "all":
        _play_all(args)
        return
    if arg in lib.get_album_names():
        _play_album(arg, args)
        return

    if arg.isdigit():
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
        else:
            _last_results = results
            m("Multiple matches:")
            for i, p in enumerate(results, 1):
                m(f"  {i}. {p.stem}")
            return

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
                player.play_file(song_path, song_path.stem, args)
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt:
            pass
    else:
        player.play_file(song_path, song_path.stem, args)


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
            for song in songs:
                _last_played = song
                player.play_file(song, song.stem, args)
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt:
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
            for song in songs:
                _last_played = song
                player.play_file(song, song.stem, args)
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt:
        pass


def _play_album(album: str, args):
    global _last_played
    songs = lib.get_album_songs(album)
    if not songs:
        e(f"No songs found in album '{album}'")
        return
    tracks = list(songs)
    if getattr(args, "shuffle", False):
        random.shuffle(tracks)
    repeat = getattr(args, "repeat", False)
    repeat_count = getattr(args, "repeat_count", 0)
    iteration = 0
    if getattr(args, "bg", False):
        if not _fork_bg(f"Playing album: {album}"):
            return
    try:
        while True:
            for song in tracks:
                _last_played = song
                player.play_file(song, song.stem, args)
            if not repeat:
                break
            iteration += 1
            if repeat_count > 0 and iteration >= repeat_count:
                break
    except KeyboardInterrupt:
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
        i(f"Unliked: {song_path.stem}")
    else:
        dest = lib.like_song(song_path)
        if dest:
            i(f"Liked: {song_path.stem}")
        else:
            m(f"{song_path.stem} is already liked")


def playlist_cmd(extra, args=None):
    if not extra:
        names = playlist.list_all()
        if not names:
            m("No playlists")
            return
        i("Playlists:")
        for name in names:
            songs = playlist.get(name)
            m(f"  {name}  ({len(songs)} songs)")
        return

    subcmd = playlist.resolve_subcmd(extra[0])

    if subcmd == "create":
        if len(extra) < 2:
            e("Usage: playlist create <name>")
            return
        name = " ".join(extra[1:])
        if playlist.create(name):
            i(f"Created playlist: {name}")
        else:
            m(f"Playlist '{name}' already exists")

    elif subcmd == "delete":
        if len(extra) < 2:
            e("Usage: playlist delete <name>")
            return
        name = " ".join(extra[1:])
        if playlist.delete(name):
            i(f"Deleted playlist: {name}")
        else:
            m(f"Playlist '{name}' not found")

    elif subcmd == "add":
        if len(extra) < 3:
            e("Usage: playlist add <name> <index_or_name>")
            return
        name = extra[1]
        target = extra[2]
        if target.isdigit():
            idx = int(target) - 1
            if idx < 0 or idx >= len(_last_results):
                e("Index out of range")
                return
            song_path = _last_results[idx]
            playlist.add_song(name, song_path.stem, "", str(song_path))
            i(f"Added: {song_path.stem} to {name}")
        else:
            results = lib.find_songs(target)
            if not results:
                e(f"No songs found matching '{target}'")
                return
            song_path = results[0]
            playlist.add_song(name, song_path.stem, "", str(song_path))
            i(f"Added: {song_path.stem} to {name}")

    elif subcmd == "remove":
        if len(extra) < 3:
            e("Usage: playlist remove <name> <index_or_name>")
            return
        name = extra[1]
        target = " ".join(extra[2:])
        if target.isdigit():
            ok, msg = playlist.remove_song(name, index=int(target) - 1)
        else:
            ok, msg = playlist.remove_song(name, title_match=target)
        if ok:
            i(f"Removed: {msg} from {name}")
        else:
            e(f"     {msg}")

    elif subcmd == "list":
        if len(extra) < 2:
            e("Usage: playlist list <name>")
            return
        name = extra[1]
        songs = playlist.get(name)
        if not songs:
            m(f"Playlist '{name}' is empty or not found")
            return
        i(f"  {name}:")
        for idx, s in enumerate(songs, 1):
            m(f"  {idx}. {s['title']}")

    elif subcmd == "play":
        if len(extra) < 2:
            e("Usage: playlist play <name>")
            return
        name = extra[1]
        songs = playlist.get(name)
        if not songs:
            m(f"Playlist '{name}' is empty or not found")
            return
        tracks = list(songs)
        if getattr(args, "shuffle", False):
            random.shuffle(tracks)
        repeat = getattr(args, "repeat", False)
        repeat_count = getattr(args, "repeat_count", 0)
        iteration = 0
        if getattr(args, "bg", False):
            if not _fork_bg(f"Playing playlist: {name}"):
                return
        try:
            while True:
                for s in tracks:
                    fpath = pathlib.Path(s.get("url", ""))
                    if not fpath.exists():
                        m(f"    Skipping {s.get('title', 'Unknown')} (file not found)")
                        continue
                    _last_played = fpath
                    player.play_file(fpath, s.get("title", "Unknown"), args)
                if not repeat:
                    break
                iteration += 1
                if repeat_count > 0 and iteration >= repeat_count:
                    break
        except KeyboardInterrupt:
            pass

    else:
        name = extra[0]
        songs = playlist.get(name)
        if not songs:
            m(f"Playlist '{name}' is empty or not found")
            return
        i(f"  {name}:")
        for idx, s in enumerate(songs, 1):
            m(f"  {idx}. {s['title']}")


def search(query: str):
    global _last_results
    if not query:
        e("Search query required")
        return
    results = lib.find_songs(query)
    if not results:
        e("No results found")
        return
    _last_results = results
    for i, p in enumerate(results, 1):
        m(f"  {i}. {p.stem}")


def list_library():
    global _last_results
    songs = lib.get_songs()
    albums = lib.get_albums()
    liked = lib.get_liked_songs()

    if songs:
        _last_results = songs
        i("\nSongs:")
        for idx, p in enumerate(songs, 1):
            m(f"  {idx}. {p.stem}")
    if albums:
        i("\nAlbums:")
        for a in albums:
            m(f"  {a}/")
    if liked:
        i("\nLiked Songs:")
        for p in liked:
            m(f"  {p.stem}")
    if not songs and not albums and not liked:
        e("No music in library")


def switch_mode():
    if is_connected():
        config.Mode = "Online"
    else:
        e("No internet connection")


def radio(extra, args):
    global _last_played, _radio_quit, _radio_skip
    tracks = lib.get_all_songs()
    if not tracks:
        e("No songs in library")
        return
    tracks = list(tracks)
    random.shuffle(tracks)

    if getattr(args, "bg", False):
        if not _fork_bg(f"Radio playing {len(tracks)} tracks"):
            return

    _radio_quit = False
    _radio_skip = False

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
    except (termios.error, OSError):
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

    i(f"\n[Radio] Playing {len(tracks)} songs (Ctrl+C next, Ctrl+Q quit)")
    try:
        while True:
            for song in tracks:
                _radio_skip = False
                _last_played = song
                player.play_file(song, song.stem, args, flags=flags)
                if _radio_quit:
                    break
            if _radio_quit:
                break
    except KeyboardInterrupt:
        pass
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
            except (termios.error, OSError):
                pass
        signal.signal(signal.SIGINT, old_sigint)
        signal.signal(signal.SIGQUIT, old_sigquit)
        signal.signal(signal.SIGUSR1, old_sigusr1)


def show_help(inf=False):
    if inf:
        print(f"{T}Offline Commands (detailed):{R}")
        for cmd, lines in help_detail.OFFLINE_HELP.items():
            for line in lines:
                print(f"  {line}")
            print()
    else:
        print(f"{T}Offline Commands:{R}")
        for cmd, desc in COMMANDS.items():
            print(f"  {T}{cmd:12s}{R} {G}{desc}{R}")
        print(f"{G}  Use 'help -i' for detailed usage{R}")
