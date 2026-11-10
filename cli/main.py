import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.platform import bootstrap_vlc

bootstrap_vlc()
from backend import config, platform, shortcuts
from backend.Offline import commands as _offline_commands
from backend.Online import commands as _online_commands
from backend.ping import is_connected
from backend.summary import SORTS as _SUMMARY_SORTS
from cli import tui as tui_shell
from cli.tui import input as tui_input
from cli.tui import show_banner

_COMMAND_MODULES = {
    "Online": _online_commands,
    "Offline": _offline_commands,
}


P = config.Primary
S = config.Secondary
M = config.Muted
R = config.Reset
config.keep_live(globals())

SHELL_AUTO_BG = {"radio", "savan"}


def _send_web_command(port, command, payload=None):
    data = {"command": command}
    if payload:
        data.update(payload)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/control",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def _send_control(action, label, payload=None):
    from backend import ipc, logger, registry

    logger.info("cli", "control", f"send_control {action} {label}", {"action": action, "label": label, "payload": payload})
    entry = registry.resolve("vlc")
    if entry is not None:
        pid = entry["pid"]
        if ipc.send(entry, action, payload):
            print(f"{P}{label} (VLC PID: {pid}){R}")
            logger.info("cli", "control_result", f"sent to vlc pid={pid}", {"target": "vlc", "pid": pid})
            return
        config.clear_pid_if(pid)

    web = registry.resolve("web")
    if web is not None and web.get("port"):
        command = ipc.WEB_COMMANDS.get(action, action)
        if _send_web_command(web["port"], command, payload):
            print(f"{P}{label} (web player){R}")
            logger.info("cli", "control_result", f"sent to web port={web['port']}", {"target": "web", "port": web["port"]})
            return

    print(f"{M}No VLC or web player running{R}")
    logger.warn("cli", "control_result", "no player running", {"action": action})


def _spinner(stop):
    from backend import rich_display

    if rich_display.active():
        rich_display.spinner_run(stop, "Checking connection")
        return
    chars = config.SPINNER
    i = 0
    while not stop():
        sys.stdout.write(f"\r{P}Checking connection... {chars[i]}{R}")
        sys.stdout.flush()
        time.sleep(0.1)
        i = (i + 1) % len(chars)
    sys.stdout.write("\r" + " " * 40 + "\r")
    sys.stdout.flush()


def _load_commands():
    return _COMMAND_MODULES[config.Mode]


def _summary_extra(args, unknown, command="summary"):
    extra = list(unknown)
    if args.sort:
        extra += ["-s", args.sort]
    if args.top is not None:
        extra += ["--top", str(args.top)]
    trailing = args.command
    if trailing and trailing != command:
        if extra and extra[-1] in ("-s", "--sort", "--top", "-n"):
            extra.append(trailing)
        elif trailing in _SUMMARY_SORTS:
            extra += ["-s", trailing]
        elif trailing.isdigit():
            extra += ["--top", trailing]
        else:
            extra.append(trailing)
    return extra


def _check_vlc():
    try:
        import vlc
    except ImportError:
        print(
            f"{config.RED}VLC is not installed. Flow requires VLC to play audio.{config.Reset}\n"
            f"{config.Muted}Install it with:{config.Reset}\n"
            f"  {config.Tertiary}sudo apt install vlc{config.Reset}"
            f"  {config.Muted}  # Debian/Ubuntu{config.Reset}\n"
            f"  {config.Tertiary}sudo dnf install vlc{config.Reset}"
            f"  {config.Muted}  # Fedora{config.Reset}\n"
            f"  {config.Tertiary}sudo pacman -S vlc{config.Reset}"
            f"  {config.Muted}  # Arch Linux{config.Reset}\n"
            f"  {config.Tertiary}brew install vlc{config.Reset}"
            f"  {config.Muted}  # macOS{config.Reset}"
        )
        sys.exit(1)


def _bundle_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _setup_island():
    src = _bundle_root() / "backend" / "Hyprland" / "island.qml"
    dest_dir = Path.home() / ".config" / "quickshell"
    dest = dest_dir / "flow-island.qml"
    if not src.exists():
        print(f"{config.RED}island.qml not found in this installation ({src}){R}")
        sys.exit(1)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"{P}Music island installed → {dest}{R}")
    print(f"{M}Launch it with:{R} {S}quickshell -p {dest}{R}")


def _resume(args):
    from backend import status as _status

    data = _status._read()
    title = (data.get("title") or "").strip()
    thumb = data.get("thumbnail") or ""
    if not title:
        print(f"{M}No last-played track in ~/.flow/status.json{R}")
        return

    online = thumb.startswith(("http://", "https://"))
    offline = (".cache/" in thumb) or thumb.startswith(str(Path.home() / ".flow"))
    args.bg = True

    if online:
        config.Mode = "Online"
        _online_commands.resume(title, args)
    elif offline:
        config.Mode = "Offline"
        _offline_commands.resume(title, args, thumb)
    else:
        print(
            f"{M}Could not tell if last track is online or offline (thumbnail: {thumb}){R}"
        )


def _full_view():
    """Full-screen now-playing view; follows the configured display mode
    (rich live panel, or the bordered progress card). Ctrl-C to exit."""
    if config.Display == "rich":
        _full_view_rich()
        return

    from backend import status as _status

    def _tty_width(default=96):
        try:
            return max(72, min(160, shutil.get_terminal_size().columns))
        except Exception:
            return default

    def _frame():
        from backend import library

        data = _status._read()
        fresh = _status._fresh(data)
        playing = bool(data.get("playing")) and fresh
        paused = fresh and not playing
        title = data.get("title") or "—"
        dur = int(data.get("duration", 0))
        elapsed = int(data.get("elapsed", 0))
        mins, secs = divmod(dur, 60)
        dur_str = f"{mins}:{secs:02d}"
        width = _tty_width()
        inner = width - 2

        thumb = data.get("thumbnail", "")
        vid = _status._vid_from_thumb(thumb)
        artist = album = ""
        entry = {}
        if vid:
            entry = library.get(vid) or {}
            artist = entry.get("artist") or ""
            album = entry.get("album") or ""

        def _vis_len(text):
            return len(re.sub(r"\x1b\[[0-9;]*m", "", text))

        def _fit(text, limit):
            if _vis_len(text) <= limit:
                return text
            return re.sub(r"\x1b\[[0-9;]*m", "", text)[: max(1, limit - 1)] + "…"

        def _row(label, value):
            value = _fit(value, max(8, inner - 22))
            text = f"  {label:<16}{value}"
            return f"{P}│{R} {text}{' ' * max(0, inner - 1 - _vis_len(text))}{P}│{R}"

        if playing:
            status_val = f"{config.CYAN}▶ playing{R}"
        elif paused:
            status_val = f"{config.YELLOW}⏸ paused{R}"
        else:
            status_val = f"{M}⏹ not playing{R}"

        rows = [
            ("status", status_val),
            ("title", f"{config.WHITE}{title}{R}"),
        ]
        if artist:
            rows.append(("artist", f"{config.WHITE}{artist}{R}"))
        if album:
            rows.append(("album", f"{config.WHITE}{album}{R}"))
        if thumb.startswith(("http://", "https://")):
            rows.append(("mode", f"{P}Online{R}"))
        elif thumb and (".cache/" in thumb or thumb.startswith(str(Path.home()))):
            rows.append(("mode", f"{S}Offline{R}"))
        if entry:
            bits = []
            if entry.get("liked"):
                bits.append(f"{config.RED}♥ liked{R}")
            else:
                bits.append(f"{M}♡{R}")
            count = entry.get("song_count") or 0
            if count:
                bits.append(f"{config.CYAN}{count}{R} plays")
            if library.get_download_path(vid):
                bits.append(f"{M}saved locally{R}")
            if bits:
                rows.append(("library", "  ·  ".join(bits)))
        rows.append(("duration", f"{config.WHITE}{dur_str}{R}"))
        if fresh:
            now = f"{elapsed // 60}:{elapsed % 60:02d}"
            frac = min(elapsed / dur, 1.0) if dur else 0.0
            bar_w = min(config.BarWidth, max(4, inner - 40))
            prog = (
                f"{config.progress_bar(frac, bar_w)} "
                f"{config.GREY}{now} / {dur_str}  {int(frac * 100):>3}%{R}"
            )
            rows.append(("progress", prog))
            nxt = (data.get("next_title") or "").strip()
            if nxt:
                rows.append(("up next", f"{config.WHITE}» {nxt}{R}"))

        out = [f"\n{P}┌─ Now Playing {'─' * max(0, inner - 13 - 3)}┐{R}"]
        for label, value in rows:
            out.append(_row(label, value))
        out.append(f"{P}└{'─' * inner}┘{R}")
        out.append(f"{M}  Ctrl-C to exit{R}\n")
        return "\n".join(out)

    if not sys.stdout.isatty():
        show_banner()
        print(_frame())
        return

    tui_shell.clear_screen()
    try:
        while True:
            config.maybe_reload()
            sys.stdout.write("\x1b[H")
            show_banner()
            print(_frame())
            sys.stdout.write("\x1b[J")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        tui_shell.clear_screen()
        print()


def _full_view_rich():
    """`--full` in rich mode: a live rich panel fed from status.json."""
    from backend import library, rich_display
    from backend import status as _status

    def _meta(data):
        vid = _status._vid_from_thumb(data.get("thumbnail", ""))
        artist = album = ""
        if vid:
            entry = library.get(vid) or {}
            artist = entry.get("artist") or ""
            album = entry.get("album") or ""
        return artist, album

    panel = rich_display.NowPlaying("", duration=0)
    if not sys.stdout.isatty():
        data = _status._read()
        artist, album = _meta(data)
        playing = bool(data.get("playing")) and _status._fresh(data)
        panel.set_track(
            data.get("title") or "—",
            artist,
            album,
            int(data.get("duration", 0)),
            status="playing" if playing else "not playing",
        )
        panel.console.print(panel.render(int(data.get("elapsed", 0)), not playing))
        return

    tui_shell.clear_screen()
    panel.start()
    last = None
    try:
        while True:
            config.maybe_reload()
            data = _status._read()
            playing = bool(data.get("playing")) and _status._fresh(data)
            title = data.get("title") or "—"
            dur = int(data.get("duration", 0))
            elapsed = int(data.get("elapsed", 0))
            artist, album = _meta(data)
            status_text = "playing" if playing else "not playing"
            key = (title, artist, album, dur, status_text)
            if key != last:
                panel.set_track(title, artist, album, dur, status=status_text)
                last = key
            panel.update(elapsed, paused=not playing)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        panel.stop()
        tui_shell.clear_screen()
        print()


def _act_current(action):
    from backend import status as _status

    data = _status._read()
    title = (data.get("title") or "").strip()
    thumb = data.get("thumbnail") or ""
    if not title:
        print(f"{M}No last-played track in ~/.flow/status.json{R}")
        return 1

    from backend import registry

    has_player = (
        registry.resolve("vlc") is not None or registry.resolve("web") is not None
    )
    if not has_player:
        print(f"{M}No player is currently running (no pid file){R}")
        return 1

    if not (data.get("playing") and _status._fresh(data)):
        print(f"{M}No track is currently playing{R}")
        return 1

    online = thumb.startswith(("http://", "https://"))
    offline = (".cache/" in thumb) or thumb.startswith(str(Path.home() / ".flow"))
    if online:
        config.Mode = "Online"
        _online_commands.act_on_current(action, title, thumb)
    elif offline:
        config.Mode = "Offline"
        _offline_commands.act_on_current(action, title, thumb)
    else:
        print(
            f"{M}Could not tell if current track is online or offline (thumbnail: {thumb}){R}"
        )
        return 1
    return 0


def main():
    platform.widen_stdio()
    parser = argparse.ArgumentParser(
        description="Flow Music Player",
        epilog=(
            "Plugin commands:\n"
            "  flow install <ref>       install a plugin (name | owner/name | git URL);\n"
            "                           bare 'flow install' opens an interactive picker\n"
            "  flow plugins list        list available plugins\n"
            "  flow plugins refresh     force-refresh plugin repos\n"
            "  flow run <name> [args]   run a plugin (background by default; -t = foreground)\n"
            "  flow plugin kill         stop running plugins (interactive, <name>, or all)\n"
            "  flow uninstall <name>    remove an installed plugin\n"
            "  flow plugins update      update the plugin repos\n"
            "Plugin developer flags:\n"
            "  flow --config-get <key>  print a config value\n"
            "  flow --config-set <k> <v>  set a config value (validated)\n"
            "  flow --theme <name>      apply a theme preset\n"
            "  flow --spinner <chars>   set the loading spinner"
        ),
    )
    parser.add_argument("--play", nargs="+", help="play a song")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {config.VERSION}",
        help="print the Flow version and exit",
    )
    parser.add_argument(
        "--import",
        dest="import_file",
        nargs=1,
        metavar="FILE",
        help="import a CSV/m3u/txt track list; interactive panel offers "
        "playlist-download, plain download, or play online one by one",
    )
    parser.add_argument(
        "--play-off", nargs="+", help="play a song from the local library (offline)"
    )
    parser.add_argument("--rd", nargs="+", help="play radio mix")
    parser.add_argument(
        "--radio-off",
        nargs="*",
        help="play radio (shuffled local library) without going online",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume the last played track from ~/.flow/status.json",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="toggle stop/resume playback (VLC or web player)",
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="play next track (VLC or web player)",
    )
    parser.add_argument(
        "--previous",
        action="store_true",
        help="play previous track (VLC or web player)",
    )
    parser.add_argument(
        "--seek",
        type=int,
        metavar="SEC",
        help="seek forward SEC seconds in the running player (VLC or web player)",
    )
    parser.add_argument(
        "--seekb",
        type=int,
        metavar="SEC",
        help="seek backward SEC seconds in the running player (VLC or web player)",
    )
    parser.add_argument(
        "--status", action="store_true", help="show playback and web mode status"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="full-screen now-playing view: clear, logo, live progress (Ctrl-C to exit)",
    )
    parser.add_argument(
        "--like",
        action="store_true",
        help="like the currently playing song (requires an active player)",
    )
    parser.add_argument(
        "--unlike",
        action="store_true",
        help="unlike the currently playing song (requires an active player)",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="download the currently playing song (requires an active player)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="play statistics; add -l for the ranked per-song table, -c to clear all plays",
    )
    parser.add_argument(
        "--sort",
        choices=sorted(_SUMMARY_SORTS),
        metavar="KEY",
        help=f"per-song table sort for --summary ({'/'.join(_SUMMARY_SORTS)})",
    )
    parser.add_argument(
        "--top",
        type=int,
        metavar="N",
        help="rows to show in the --summary per-song table",
    )
    parser.add_argument(
        "--setup-island",
        action="store_true",
        help="install the Hyprland music island into ~/.config/quickshell",
    )
    parser.add_argument(
        "command", nargs="?", default=None, help="subcommand (play, search, list, ...)"
    )
    parser.add_argument("--check", action="store_true", help="check all dependencies")
    parser.add_argument("--config-get", metavar="KEY", help="print a config value")
    parser.add_argument(
        "--config-set",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="set a config value through the validated setter",
    )
    parser.add_argument(
        "--theme", metavar="NAME", help="apply a theme preset ('list' shows themes)"
    )
    parser.add_argument(
        "--spinner", metavar="CHARS", help="set the loading spinner characters"
    )
    parser.add_argument(
        "-m",
        "--multi",
        action="store_true",
        help=(
            "multi-select in the result picker. Online: 'download q -m' downloads "
            "several, 'search q -dm' and 'play q -dm' download several, 'search q -m' "
            "and 'play q -m' play the ticked tracks as a queue. Offline: 'play q -m' "
            "plays the ticked songs. Short flags combine, e.g. -dm"
        ),
    )

    args, unknown = parser.parse_known_args()

    if getattr(args, "setup_island", False):
        if not platform.is_linux():
            print(f"{config.Muted}--setup-island is Linux-only (Hyprland) and is skipped here{R}")
            sys.exit(0)
        _setup_island()
        sys.exit(0)

    if getattr(args, "config_get", None) is not None:
        val, ok = config.config_get(args.config_get)
        if not ok:
            print(f"{M}Unknown config key: {args.config_get}{R}")
            sys.exit(1)
        print(val if isinstance(val, str) else json.dumps(val))
        sys.exit(0)

    if getattr(args, "config_set", None) is not None:
        key, value = args.config_set
        msg = config.apply_config(key, value)
        print(msg)
        bad = any(
            t in msg for t in ("Unknown", "must be", "not found", "ffmpeg not found")
        )
        sys.exit(1 if bad else 0)

    if getattr(args, "theme", None) is not None:
        msg = config._apply_theme(args.theme)
        print(msg)
        bad = any(
            t in msg for t in ("Unknown", "must be", "not found", "ffmpeg not found")
        )
        sys.exit(1 if bad else 0)

    if getattr(args, "spinner", None) is not None:
        msg = config._apply_spinner(args.spinner)
        print(msg)
        bad = any(
            t in msg for t in ("Unknown", "must be", "not found", "ffmpeg not found")
        )
        sys.exit(1 if bad else 0)

    if args.command in (
        "plugins",
        "plugin",
        "install",
        "uninstall",
        "remove",
        "run",
        "update",
        "refresh",
        "kill",
        "daemon",
    ):
        from backend import plugins

        if args.command != "daemon":
            from backend.plugins import _ensure_daemon

            _ensure_daemon()
        sys.exit(plugins.dispatch(args.command, unknown, args))

    # A storage read — no player, no VLC.
    if getattr(args, "summary", False):
        from backend import summary

        summary.cmd_summary(_summary_extra(args, unknown, command=None))
        sys.exit(0)

    if getattr(args, "full", False):
        _full_view()
        sys.exit(0)

    if args.command == "clear":
        tui_shell.clear_screen()
        show_banner()
        sys.exit(0)

    _check_vlc()

    if getattr(args, "check", False):
        print(f"{P}Dependency Check:{R}\n")
        config.check_deps()
        sys.exit(0)

    if getattr(args, "status", False):
        from backend.status import show as show_status

        show_status()
        sys.exit(0)

    shortcuts.load()

    control_args = []
    if getattr(args, "pause", False):
        control_args.append(("pause", "Toggled pause/resume", None))
    if getattr(args, "next", False):
        control_args.append(("next", "Skipped to next track", None))
    if getattr(args, "previous", False):
        control_args.append(("prev", "Went to previous track", None))
    if getattr(args, "seek", None) is not None:
        control_args.append(("seek_fwd", "Seeked forward", getattr(args, "seek")))
    if getattr(args, "seekb", None) is not None:
        control_args.append(("seek_bwd", "Seeked backward", -getattr(args, "seekb")))
    if control_args:
        for action, label, delta in control_args:
            if delta is not None:
                from backend import registry

                if registry.resolve("vlc") is not None or registry.resolve("tui") is not None:
                    config.write_seek(delta * 1000)
                label = f"{label} {abs(delta)}s"
            _send_control(
                action,
                label,
                payload={"delta": delta * 1000} if delta is not None else None,
            )
        sys.exit(0)

    if getattr(args, "like", False):
        sys.exit(_act_current("like"))
    if getattr(args, "unlike", False):
        sys.exit(_act_current("unlike"))
    if getattr(args, "download", False):
        sys.exit(_act_current("download"))

    forced_offline = False
    if getattr(args, "resume", False):
        _resume(args)
        sys.exit(0)
    if getattr(args, "play_off", None) is not None:
        args.command = "play"
        unknown = args.play_off + unknown
        forced_offline = True
        args.bg = True
    elif getattr(args, "radio_off", None) is not None:
        args.command = "radio"
        unknown = args.radio_off + unknown
        forced_offline = True
    elif getattr(args, "play", None) is not None:
        args.command = "play"
        unknown = args.play + unknown
    elif getattr(args, "import_file", None) is not None:
        args.command = "import"
        unknown = args.import_file + unknown
    elif getattr(args, "rd", None) is not None:
        args.command = "radio"
        unknown = args.rd + unknown
    elif args.command and args.command not in (
        "play",
        "search",
        "savan",
        "svn",
        "savan-s",
        "svn-s",
        "like",
        "unlike",
        "download",
        "delete",
        "dl-d",
        "rename",
        "re",
        "tags",
        "switch",
        "help",
        "short",
        "config",
        "check",
        "radio",
        "rd",
        "playlist",
        "plist",
        "summary",
        "export",
        "exit",
        "scrobbler",
        "scr",
    ):
        unknown = [args.command] + unknown
        args.command = "play"

    if forced_offline:
        config.Mode = "Offline"
    else:
        stop = False
        t = threading.Thread(target=_spinner, args=(lambda: stop,), daemon=True)
        t.start()
        try:
            if is_connected():
                config.Mode = "Online"
            else:
                config.Mode = "Offline"
        finally:
            stop = True
            t.join()

    commands = _load_commands()

    if args.command:
        resolved = []
        for item in unknown:
            if item.startswith("-"):
                alias = item[1:]
                resolved_cmd = shortcuts.resolve(alias)
                if resolved_cmd != alias:
                    if args.command is None:
                        args.command = resolved_cmd
                    continue
            resolved.append(item)
        unknown = resolved

        if args.command in SHELL_AUTO_BG:
            args.bg = True

        if args.command == "summary":
            unknown = _summary_extra(args, unknown)

        try:
            from backend import logger
            logger.log_command("cli", args.command, unknown, {"mode": config.Mode})
        except Exception:
            pass
        try:
            commands.run(args.command, unknown, args)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            try:
                from backend import logger
                logger.error("cli", "command_error", str(e), {"command": args.command}, exc_info=True)
            except Exception:
                pass
            raise
    else:
        show_banner()
        if unknown:
            print(f"{M}Unknown command: {' '.join(unknown)}{R}")
        restore_quit_key = tui_shell.install_quit_key()
        try:
            while True:
                config.maybe_reload()
                try:
                    raw_input = tui_input().strip()
                    try:
                        from backend import logger
                        logger.log_user_input("cli", raw_input)
                    except Exception:
                        pass
                    parts = raw_input.split()
                    if not parts:
                        continue
                    cmd = parts[0].lower()
                    extra = parts[1:]
                    cmd = shortcuts.resolve(cmd)
                    if cmd in ("clear", "cls"):
                        tui_shell.clear_screen()
                        show_banner()
                        continue
                    if cmd in ("exit", "quit", "q"):
                        print(f"{M}Goodbye!{R}")
                        break
                    cmd_args = argparse.Namespace(**vars(args))
                    for flag in ("bg", "download", "repeat", "shuffle"):
                        setattr(cmd_args, flag, False)
                    cmd_args.repeat_count = 0
                    from backend import plugins

                    if plugins.dispatch(cmd, extra, cmd_args) is not None:
                        continue
                    try:
                        from backend import logger
                        logger.log_command("cli", cmd, extra, {"mode": config.Mode, "shell": True})
                    except Exception:
                        pass
                    try:
                        commands.run(cmd, extra, cmd_args)
                    except KeyboardInterrupt:
                        config.clear_pid_if(os.getpid())
                    except Exception as e:
                        try:
                            from backend import logger
                            logger.error("cli", "command_error", str(e), {"command": cmd}, exc_info=True)
                        except Exception:
                            pass
                    if getattr(cmd_args, "bg", False):
                        break
                    if cmd == "switch":
                        commands = _load_commands()
                        show_banner()
                except (EOFError, KeyboardInterrupt):
                    print(f"{M}\nGoodbye!{R}")
                    break
        finally:
            restore_quit_key()


if __name__ == "__main__":
    main()
