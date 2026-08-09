import argparse
import builtins
import importlib
import sys
import threading
import time
from pathlib import Path

import psutil

if __name__ == "__main__" and __package__ is None:
    __package__ = "flow_twinx"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warnings

from flow_twinx import shortcuts
from flow_twinx.Offline import commands as _offline_commands
from flow_twinx.Online import commands as _online_commands

from .imports import config, is_connected, show_banner, tui_input

_COMMAND_MODULES = {
    "Online": _online_commands,
    "Offline": _offline_commands,
}


P = config.Primary
S = config.Secondary
M = config.Muted
R = config.Reset

SHELL_AUTO_BG = {"radio", "savan"}


def kill_port(port):
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr and conn.laddr.port == port:
            try:
                proc = psutil.Process(conn.pid)
                proc.kill()
                return True
            except psutil.NoSuchProcess, psutil.AccessDenied:
                return False
    return False


def _run_web(port):
    from flow_twinx.web.app import app

    WEB_PID = Path.home() / ".flow/web.pid"
    WEB_PORT = Path.home() / ".flow/web_port"
    try:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    finally:
        WEB_PID.unlink(missing_ok=True)
        WEB_PORT.unlink(missing_ok=True)


def _spinner(stop):
    chars = "|/-\\"
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


def _check_vlc():
    try:
        import vlc
    except ImportError:
        print(
            f"{config.Red}VLC is not installed. Flow requires VLC to play audio.{config.Reset}\n"
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


def main():
    _check_vlc()

    parser = argparse.ArgumentParser(description="Flow Music Player")
    parser.add_argument("--play", nargs="+", help="play a song")
    parser.add_argument("--rd", nargs="+", help="play radio mix")
    parser.add_argument("--stop", action="store_true", help="stop background VLC")
    parser.add_argument(
        "--pause", action="store_true", help="toggle pause on background VLC"
    )
    parser.add_argument(
        "--web", action="store_true", help="start web server with API and player UI"
    )
    parser.add_argument(
        "--web-stop", action="store_true", help="stop running web server"
    )
    parser.add_argument(
        "--web-new",
        action="store_true",
        help="start web server on next available port without prompting",
    )
    parser.add_argument(
        "--stop-all",
        action="store_true",
        help="stop all background processes (VLC + web server)",
    )
    parser.add_argument(
        "--status", action="store_true", help="show playback and web mode status"
    )
    parser.add_argument(
        "command", nargs="?", default=None, help="subcommand (play, search, list, ...)"
    )
    parser.add_argument("--check", action="store_true", help="check all dependencies")

    args, unknown = parser.parse_known_args()

    if getattr(args, "check", False):
        print(f"{P}Dependency Check:{R}\n")
        config.check_deps()
        sys.exit(0)

    WEB_PID = Path.home() / ".flow/web.pid"
    WEB_PORT = Path.home() / ".flow/web_port"

    if getattr(args, "stop_all", False):
        stopped = []
        if config.kill_stored():
            stopped.append("VLC")
        if WEB_PID.exists():
            try:
                pid = int(WEB_PID.read_text().strip())
                port = int(WEB_PORT.read_text().strip()) if WEB_PORT.exists() else 5000
                kill_port(port)
                stopped.append(f"web server (PID: {pid})")
            except ProcessLookupError, ValueError, OSError:
                stopped.append("web server (zombie, cleaned up)")
            WEB_PID.unlink(missing_ok=True)
            WEB_PORT.unlink(missing_ok=True)
        if stopped:
            print(f"{P}Stopped: {', '.join(stopped)}{R}")
        else:
            print(f"{M}No background processes running{R}")
        sys.exit(0)

    if getattr(args, "web_stop", False):
        if WEB_PID.exists():
            try:
                import os

                pid = int(WEB_PID.read_text().strip())
                port = int(WEB_PORT.read_text().strip()) if WEB_PORT.exists() else 5000
                kill_port(port)
                print(f"{P}Stopped web server (PID: {pid}){R}")
            except ProcessLookupError, ValueError:
                print(f"{M}Web server not running{R}")
            WEB_PID.unlink(missing_ok=True)
            WEB_PORT.unlink(missing_ok=True)
        else:
            print(f"{M}Web server not running{R}")
        sys.exit(0)

    if getattr(args, "web", False) or getattr(args, "web_new", False):
        import os
        import signal

        WEB_PID.parent.mkdir(parents=True, exist_ok=True)

        if getattr(args, "web", False):
            existing_pid = None
            existing_port = None
            if WEB_PID.exists():
                try:
                    existing_pid = int(WEB_PID.read_text().strip())
                    existing_port = (
                        int(WEB_PORT.read_text().strip()) if WEB_PORT.exists() else None
                    )
                except ValueError, OSError:
                    pass

            existing_alive = False
            if existing_pid is not None:
                try:
                    proc = psutil.Process(existing_pid)
                    existing_alive = proc.is_running()
                except psutil.NoSuchProcess:
                    pass

            if existing_alive:
                port_str = f" on port {existing_port}" if existing_port else ""
                answer = builtins.input(
                    f"{P}A web server is already running{port_str}. "
                    f"Kill it and restart? (y/N) {R}"
                )
                if answer.lower() not in ("y", "yes"):
                    print(f"{M}Aborted.{R}")
                    print(f"{M}Use -new to start a new server.{R}")
                    sys.exit(0)
                if existing_port:
                    kill_port(existing_port)
                    for _ in range(10):
                        if not any(
                            c.laddr and c.laddr.port == existing_port
                            for c in psutil.net_connections(kind="inet")
                        ):
                            break
                        time.sleep(0.2)
                else:
                    try:
                        os.kill(existing_pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                WEB_PID.unlink(missing_ok=True)
                WEB_PORT.unlink(missing_ok=True)

        port = None
        for p in range(5000, 5006):
            if not any(
                c.laddr and c.laddr.port == p
                for c in psutil.net_connections(kind="inet")
            ):
                port = p
                break
        if port is None:
            print(
                f"{M}All ports 5000-5005 are busy. Pls free your port to use flow web.{R}"
            )
            sys.exit(1)

        if not config.DEV_MODE:
            warnings.filterwarnings(
                "ignore", category=DeprecationWarning, message=".*fork.*"
            )
            pid = os.fork()
            if pid > 0:
                WEB_PID.write_text(str(pid))
                WEB_PORT.write_text(str(port))
                print(f"{P}Flow web server → http://127.0.0.1:{port}{R}")
                return
            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            _run_web(port)
        else:
            WEB_PID.write_text(str(os.getpid()))
            WEB_PORT.write_text(str(port))
            print(f"{P}Flow web server → http://127.0.0.1:{port} (dev){R}")
            _run_web(port)
        return

    if getattr(args, "status", False):
        from .status import show as show_status

        show_status()
        sys.exit(0)

    shortcuts.load()

    if getattr(args, "stop", False):
        if config.kill_stored():
            print(f"{P}Stopped VLC{R}")
        else:
            print(f"{M}No background VLC running{R}")
        sys.exit(0)

    if getattr(args, "pause", False):
        import os as _os
        import signal as _signal

        pid = config.read_pid()
        if pid is not None:
            try:
                _os.kill(pid, _signal.SIGUSR1)
                print(f"{P}Toggled pause on background VLC (PID: {pid}){R}")
            except ProcessLookupError:
                print(f"{M}No background VLC running{R}")
                config.clear_pid()
        else:
            print(f"{M}No background VLC running{R}")
        sys.exit(0)

    if getattr(args, "play", None) is not None:
        args.command = "play"
        unknown = args.play + unknown
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
        "download",
        "delete",
        "dl-d",
        "switch",
        "help",
        "short",
        "config",
        "check",
        "radio",
        "rd",
        "playlist",
        "plist",
        "exit",
    ):
        unknown = [args.command] + unknown
        args.command = "play"

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

        try:
            commands.run(args.command, unknown, args)
        except KeyboardInterrupt:
            pass
    else:
        show_banner()
        if unknown:
            print(f"{M}Unknown command: {' '.join(unknown)}{R}")
        while True:
            try:
                parts = tui_input().strip().split()
                if not parts:
                    continue
                cmd = parts[0].lower()
                extra = parts[1:]
                cmd = shortcuts.resolve(cmd)
                if cmd in ("exit", "quit", "q"):
                    print(f"{M}Goodbye!{R}")
                    break
                cmd_args = argparse.Namespace(**vars(args))
                for flag in ("bg", "repeat", "shuffle"):
                    setattr(cmd_args, flag, False)
                cmd_args.repeat_count = 0
                try:
                    commands.run(cmd, extra, cmd_args)
                except KeyboardInterrupt:
                    pass
                if getattr(cmd_args, "bg", False):
                    break
                if cmd == "switch":
                    commands = _load_commands()
                    show_banner()
            except EOFError, KeyboardInterrupt:
                print(f"{M}\nGoodbye!{R}")
                break


if __name__ == "__main__":
    main()
