import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

from backend import config as _colors
from backend import platform
from backend.config import GREY, RED, Muted, Primary, Reset

E = RED
G = GREY
M = Muted
P = Primary
R = Reset
_colors.keep_live(globals())

from backend import config as _config

HOME = pathlib.Path.home()
FLOW_DIR = HOME / ".flow"
SOCKET_FILE = FLOW_DIR / "flow.sock"
PID_FILE = FLOW_DIR / "flowd.pid"

#: Bumped whenever the RPC protocol / method surface changes.
PROTOCOL_VERSION = 4
#: 1 MiB cap on any single frame.
MAX_FRAME = 1 << 20


def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return False
    return _alive(pid)


def _alive(pid: int) -> bool:
    return platform.pid_exists(pid)


def _cleanup_stale():
    if not PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)
        SOCKET_FILE.unlink(missing_ok=True)
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        if _alive(pid):
            return
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)
    SOCKET_FILE.unlink(missing_ok=True)


def stop_signal(pid: int) -> bool:
    if not platform.kill_pid(pid):
        return False
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    else:
        platform.kill_pid(pid, force=True)
    return True


def cmd_quit() -> int:
    if not PID_FILE.exists():
        print(f"{M}Flow daemon is not running{R}")
        return 1
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        print(f"{E}Corrupt pid file{R}")
        return 1
    if not _alive(pid):
        PID_FILE.unlink(missing_ok=True)
        SOCKET_FILE.unlink(missing_ok=True)
        print(f"{P}No live daemon (stale pid cleaned){R}")
        return 0
    stop_signal(pid)
    PID_FILE.unlink(missing_ok=True)
    SOCKET_FILE.unlink(missing_ok=True)
    print(f"{P}Flow daemon stopped{R}")
    return 0


def cmd_status() -> int:
    if not is_running():
        print(f"{M}Flow daemon is not running{R}")
        print(f"{G}Start it with: flow daemon start{R}")
        return 1
    pid = int(PID_FILE.read_text().strip())
    print(f"{P}Flow daemon running (pid {pid}, socket {SOCKET_FILE}){R}")
    return 0


def socket_path() -> pathlib.Path:
    return SOCKET_FILE


def serve(foreground: bool = False) -> int:
    """Run the daemon until killed. Returns exit code for the foreground case."""
    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_stale()

    if platform.is_windows():
        # Windows has no AF_UNIX daemon socket in this design: bind a
        # loopback TCP port and advertise "host:port" in the socket file.
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        SOCKET_FILE.write_text(f"127.0.0.1:{server.getsockname()[1]}")
    else:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(SOCKET_FILE))
        except OSError:
            # Socket exists — either stale or a live daemon owns it.
            if is_running():
                print(f"{P}Flow daemon is already running{R}")
                return 0
            SOCKET_FILE.unlink(missing_ok=True)
            try:
                server.bind(str(SOCKET_FILE))
            except OSError as exc:
                print(f"{E}Could not bind {SOCKET_FILE}: {exc}{R}")
                return 1
        os.chmod(SOCKET_FILE, 0o600)
    server.listen(32)

    if not foreground:
        try:
            _daemonize()
        except Exception as exc:
            print(f"{E}Daemonization failed: {exc}{R}")
            return 1

    PID_FILE.write_text(str(os.getpid()))
    print(f"{P}Flow daemon started (pid {os.getpid()}, socket {SOCKET_FILE}){R}")

    server.settimeout(0.5)
    try:
        while True:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        SOCKET_FILE.unlink(missing_ok=True)
        if int(PID_FILE.read_text().strip()) == os.getpid():
            PID_FILE.unlink(missing_ok=True)
    return 0


class _FlowConn:
    """Raw socket wrapper that lets the RPC layer stamp per-connection state
    (a socket object itself has no __dict__, so rpc can't setattr directly)."""

    __slots__ = ("sock", "_flow_plugin_name")

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._flow_plugin_name = None


def _handle_conn(conn: socket.socket):
    from backend import rpc

    flow_conn = _FlowConn(conn)
    buffered = b""
    with conn:
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffered += chunk
                while b"\n" in buffered:
                    line, _, buffered = buffered.partition(b"\n")
                    if not line.strip():
                        continue
                    try:
                        frame = json.loads(line.decode())
                    except Exception:
                        continue
                    resp = rpc.handle(frame, flow_conn)
                    if resp is not None:
                        conn.sendall((json.dumps(resp) + "\n").encode())
        except ConnectionError, OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def _daemonize():
    if not platform.can_fork():
        return
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)


def cmd_start(foreground: bool = False) -> int:
    if is_running():
        print(f"{P}Flow daemon is already running{R}")
        print(f"{G}Socket: {SOCKET_FILE}{R}")
        return 0
    from backend import registry

    registry.prune()  # drop dead players before we start serving
    if not foreground and not platform.can_fork():
        # Windows: relaunch ourselves detached in foreground mode.
        platform.spawn_detached(
            [sys.executable, "-m", "backend.daemon", "start", "-f"],
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return 0
    return serve(foreground=foreground)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("start",):
        fg = "-f" in args or "--foreground" in args
        sys.exit(cmd_start(foreground=fg))
    if args[0] == "quit":
        sys.exit(cmd_quit())
    if args[0] == "status":
        sys.exit(cmd_status())
    if args[0] == "socket":
        print(SOCKET_FILE)
        sys.exit(0)
    print(f"Usage: python backend/daemon.py {{start [-f]|quit|status|socket}}")
    sys.exit(2)
