import argparse
import builtins
import os
import subprocess
import sys
import time
import warnings
from pathlib import Path

import psutil

from backend.platform import bootstrap_vlc

bootstrap_vlc()
from backend import platform

WEB_PID = Path.home() / ".flow/web.pid"
WEB_PORT_FILE = Path.home() / ".flow/web_port"

BUSY_PORTS = range(5000, 5006)


def _port_busy(port):
    return any(
        c.laddr and c.laddr.port == port for c in psutil.net_connections(kind="inet")
    )


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
    from web.app import app

    try:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    finally:
        WEB_PID.unlink(missing_ok=True)
        WEB_PORT_FILE.unlink(missing_ok=True)
        from backend import registry

        registry.unregister("web")


def _web_alive():
    if not WEB_PID.exists():
        return False
    try:
        return psutil.Process(int(WEB_PID.read_text().strip())).is_running()
    except Exception:
        return False


def _first_free_port():
    for p in BUSY_PORTS:
        if not _port_busy(p):
            return p
    return None


def _default_web_port():
    """Port of the tracked server, else the lowest busy flow port."""
    if WEB_PORT_FILE.exists():
        try:
            return int(WEB_PORT_FILE.read_text().strip())
        except ValueError, OSError:
            pass
    for p in BUSY_PORTS:
        if _port_busy(p):
            return p
    return None


def _stop_port(port):
    from backend import config

    P = config.Primary
    M = config.Muted
    R = config.Reset

    if port is None:
        print(f"{M}No web server running.{R}")
        return 1

    if not kill_port(port):
        print(f"{M}No web server running on port {port}{R}")
        return 1

    pid = None
    try:
        if WEB_PORT_FILE.exists() and int(WEB_PORT_FILE.read_text().strip()) == port:
            if WEB_PID.exists():
                pid = int(WEB_PID.read_text().strip())
            WEB_PID.unlink(missing_ok=True)
            WEB_PORT_FILE.unlink(missing_ok=True)
            from backend import registry

            registry.unregister("web", pid)
    except ValueError, OSError:
        pass

    pid_str = f" (PID: {pid})" if pid else ""
    print(f"{P}Stopped web server on port {port}{pid_str}{R}")
    return 0


def _stop_all():
    from backend import config

    P = config.Primary
    M = config.Muted
    R = config.Reset

    stopped = []
    for p in BUSY_PORTS:
        if _port_busy(p) and kill_port(p):
            stopped.append(f"web server on port {p}")
    WEB_PID.unlink(missing_ok=True)
    WEB_PORT_FILE.unlink(missing_ok=True)
    from backend import registry

    registry.unregister("web")
    if stopped:
        print(f"{P}Stopped: {', '.join(stopped)}{R}")
    else:
        print(f"{M}No background processes running{R}")
    return 0


def _start_server(new, port, spawned=False):
    from backend import config

    P = config.Primary
    M = config.Muted
    R = config.Reset

    WEB_PID.parent.mkdir(parents=True, exist_ok=True)

    if not new and port is None:
        existing_pid = None
        existing_port = None
        if WEB_PID.exists():
            try:
                existing_pid = int(WEB_PID.read_text().strip())
                existing_port = (
                    int(WEB_PORT_FILE.read_text().strip())
                    if WEB_PORT_FILE.exists()
                    else None
                )
            except ValueError, OSError:
                pass

        if _web_alive():
            port_str = f" on port {existing_port}" if existing_port else ""
            answer = builtins.input(
                f"{P}A web server is already running{port_str}. "
                f"Kill it and restart? (y/N) {R}"
            )
            if answer.lower() not in ("y", "yes"):
                print(f"{M}Aborted.{R}")
                print(f"{M}Use 'flow-web --new' to start another server.{R}")
                sys.exit(0)
            if existing_port:
                kill_port(existing_port)
                for _ in range(10):
                    if not _port_busy(existing_port):
                        break
                    time.sleep(0.2)
            else:
                platform.kill_pid(existing_pid)
            WEB_PID.unlink(missing_ok=True)
            WEB_PORT_FILE.unlink(missing_ok=True)
            from backend import registry

            registry.unregister("web", existing_pid)

    if port is None:
        port = _first_free_port()
        if port is None:
            print(
                f"{M}All ports 5000-5005 are busy. Pls free your port to use flow web.{R}"
            )
            sys.exit(1)

    if not config.DEV_MODE:
        warnings.filterwarnings(
            "ignore", category=DeprecationWarning, message=".*fork.*"
        )
        if not spawned and platform.can_fork():
            pid = os.fork()
            if pid > 0:
                WEB_PID.write_text(str(pid))
                WEB_PORT_FILE.write_text(str(port))
                from backend import registry

                registry.register("web", pid, port=port)
                print(f"{P}Flow web server → http://127.0.0.1:{port}{R}")
                return
            devnull = os.open(os.devnull, os.O_RDWR)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            _run_web(port)
            return
        if not spawned:
            proc = platform.spawn_detached(
                [sys.executable, "-m", "web.main", f"--_spawn={port}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            WEB_PID.write_text(str(proc.pid))
            WEB_PORT_FILE.write_text(str(port))
            from backend import registry

            registry.register("web", proc.pid, port=port)
            print(f"{P}Flow web server → http://127.0.0.1:{port}{R}")
            return
        WEB_PID.write_text(str(os.getpid()))
        WEB_PORT_FILE.write_text(str(port))
        from backend import registry

        registry.register("web", os.getpid(), port=port)
        _run_web(port)
    else:
        WEB_PID.write_text(str(os.getpid()))
        WEB_PORT_FILE.write_text(str(port))
        from backend import registry

        registry.register("web", os.getpid(), port=port)
        print(f"{P}Flow web server → http://127.0.0.1:{port} (dev){R}")
        _run_web(port)


def main():
    from backend import config

    parser = argparse.ArgumentParser(
        prog="flow-web",
        description="Start or stop the Flow web server on the first free port from 5000.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {config.VERSION}",
        help="print the Flow version and exit",
    )
    parser.add_argument(
        "--stop",
        nargs="?",
        type=int,
        const=0,
        default=None,
        metavar="PORT",
        help="stop one web server on PORT (default: the running port)",
    )
    parser.add_argument(
        "--stop-all",
        action="store_true",
        help="stop all running web servers and VLC",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="start a new server on the next free port without prompting",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="start the web server on a specific port",
    )
    parser.add_argument(
        "--_spawn",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.stop_all:
        sys.exit(_stop_all())
    if args.stop is not None:
        sys.exit(_stop_port(args.stop or _default_web_port()))
    _start_server(new=args.new, port=args.port or args._spawn, spawned=args._spawn is not None)


if __name__ == "__main__":
    main()
