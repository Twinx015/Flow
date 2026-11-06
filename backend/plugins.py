import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from backend import config, platform
from backend.config import GREY, RED, Muted, Primary, Reset, Secondary

P = Primary
S = Secondary
M = Muted
R = Reset
config.keep_live(globals())
G = GREY
E = RED

PLUGINS_DIR = pathlib.Path.home() / ".flow/plugins"
REPO_CACHE = PLUGINS_DIR / "_repo"
OTHER_CACHE = PLUGINS_DIR / "_src"
PIDS_DIR = PLUGINS_DIR / "_pids"
LOGS_DIR = PLUGINS_DIR / "_logs"

DEFAULT_REPO = "https://github.com/Twinx015/flow-plugins.git"

# The plugin SDK is shipped as a data file next to this module, not imported,
# so in the frozen build it lives in the unpack dir rather than beside
# `__file__` (which points inside the PYZ).
_BUNDLE_ROOT = (
    pathlib.Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else pathlib.Path(__file__).resolve().parent
)

API_SOURCE = _BUNDLE_ROOT / "plugin_api" / "flow_api.py"


def _ensure_plugins_dir():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)


def _repo_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def _git(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _has_commits(cache: pathlib.Path) -> bool:
    return _git(["-C", str(cache), "rev-parse", "HEAD"]).returncode == 0


def _ensure_repo(url: str) -> pathlib.Path:
    _ensure_plugins_dir()
    cache = REPO_CACHE if url == DEFAULT_REPO else OTHER_CACHE / _repo_key(url)
    if (cache / ".git").exists():
        if _has_commits(cache):
            _git(["-C", str(cache), "pull", "--ff-only", "-q"], timeout=30)
        else:
            shutil.rmtree(cache, ignore_errors=True)
    if not (cache / ".git").exists():
        cache.mkdir(parents=True, exist_ok=True)
        r = _git(["clone", "--depth", "1", url, str(cache)])
        if r.returncode != 0:
            shutil.rmtree(cache, ignore_errors=True)
            raise RuntimeError(
                f"git clone failed for {url}:\n{(r.stderr or r.stdout).strip()}"
            )
        if not _has_commits(cache):
            shutil.rmtree(cache, ignore_errors=True)
            raise RuntimeError(f"repo {url} has no commits")
    return cache


def _read_manifest(cache_dir: pathlib.Path):
    manifest_file = cache_dir / "manifest.json"
    if not manifest_file.exists():
        return None
    try:
        return json.loads(manifest_file.read_text())
    except Exception:
        return None


def _find_entry(manifest, name: str):
    if not manifest:
        return None
    for p in manifest.get("plugins", []):
        if p.get("name") == name:
            return p
    return None


def _resolve_ref(ref: str) -> tuple[str, str]:
    select = None
    if "#" in ref:
        ref, _, select = ref.partition("#")
    if ref.startswith(("http://", "https://", "git@")):
        url = ref
        name = ref.rstrip("/").split("/")[-1].removesuffix(".git")
        return url, select or name
    expanded = pathlib.Path(os.path.expanduser(ref))
    if expanded.exists():
        return expanded.resolve().as_posix(), select or expanded.name
    if "/" in ref:
        owner, _, name = ref.partition("/")
        return f"https://github.com/{owner}/{name}.git", select or name
    return DEFAULT_REPO, select or ref


def _write_api(plugin_dir: pathlib.Path):
    shutil.copyfile(API_SOURCE, plugin_dir / "flow_api.py")


def _sync_api(plugin_dir: pathlib.Path):
    target = plugin_dir / "flow_api.py"
    if not target.exists() or target.read_bytes() != API_SOURCE.read_bytes():
        _write_api(plugin_dir)


def _write_plugin_json(plugin_dir: pathlib.Path, entry: dict):
    (plugin_dir / "plugin.json").write_text(json.dumps(entry, indent=2) + "\n")


def _ensure_daemon() -> bool:
    """Lazily start the resident daemon so plugins have a socket to talk to.

    One host owns the socket (`~/.flow/flow.sock`); the daemon is idempotent:
    if it's already running this is a no-op. Returns True when up.

    This must NOT call `daemon.cmd_start()` directly — that daemonizes the
    *current* process (first fork's parent `os._exit(0)`), killing the CLI.
    Instead we spawn the daemon as a detached subprocess and wait for its
    socket.
    """
    from backend import daemon as _daemon

    if _daemon.is_running():
        return True
    try:
        # `-m backend.daemon` resolves the package the same way the flow
        # entry point does (editable install, site-packages, or a source
        # checkout on sys.path) — a bare script path would depend on the
        # cwd/editable-finder and can break for users.
        platform.spawn_detached(
            [sys.executable, "-m", "backend.daemon", "start"],
            env=dict(os.environ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    # Give the daemon a moment to bind + write its pid file.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if _daemon.is_running():
            return True
        time.sleep(0.1)
    return _daemon.is_running()


def _daemon_socket() -> str:
    from backend import daemon as _daemon

    return str(_daemon.socket_path())


def installed() -> dict[str, dict]:
    _ensure_plugins_dir()
    result = {}
    for child in PLUGINS_DIR.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        pj = child / "plugin.json"
        if not pj.exists():
            continue
        try:
            info = json.loads(pj.read_text())
        except Exception:
            continue
        if info.get("name"):
            result[info["name"]] = info
    return result


def _catalog() -> list[dict]:
    manifest = _read_manifest(REPO_CACHE)
    if manifest is None:
        _ensure_repo(DEFAULT_REPO)
        manifest = _read_manifest(REPO_CACHE)
    return (manifest or {}).get("plugins") or []


def cmd_list(extra=None) -> int:
    try:
        plugins = _catalog()
    except Exception as exc:
        print(f"{E}Could not fetch plugin repo: {exc}{R}")
        return 1
    if not plugins:
        print(f"{E}No plugins available in the repository{R}")
        return 1

    inst = installed()
    lefts = []
    name_w = max(len(p.get("name", "?")) for p in plugins) + 2
    for p in plugins:
        name = p.get("name", "?")
        ver = p.get("version", "?")
        desc = p.get("description", "")
        lefts.append(f"  {P}{name:<{name_w}}{R} {G}v{ver:<6}{R} {desc}")
    max_left = max(len(l) for l in lefts)

    print(f"\n{P}Available plugins:{R}\n")
    for p, left in zip(plugins, lefts):
        name = p.get("name", "?")
        marker = ""
        if name in inst:
            iv = inst[name].get("version")
            ver = p.get("version")
            marker = (
                G + ("[installed]" if iv == ver else f"[installed v{iv}→update]") + R
            )
        line = left + " " * (max_left - len(left))
        if marker:
            line += "  " + marker
        print(line)
    print()
    return 0


def _install_one(ref: str, force: bool) -> int:
    repo_url, plugin_name = _resolve_ref(ref)
    print(f"{P}Fetching plugin '{plugin_name}'...{R}")
    try:
        cache = _ensure_repo(repo_url)
    except Exception as exc:
        print(f"{E}Failed to fetch repo: {exc}{R}")
        return 1

    manifest = _read_manifest(cache)
    entry = _find_entry(manifest, plugin_name)
    if not entry:
        names = [
            p.get("name") for p in (manifest or {}).get("plugins", []) if p.get("name")
        ]
        print(f"{E}Plugin '{plugin_name}' not found in the repo{R}")
        if names:
            print(f"{G}Available: {', '.join(names)}{R}")
        return 1

    _ensure_plugins_dir()
    dest = PLUGINS_DIR / plugin_name
    if dest.exists() and not force:
        print(
            f"{M}Plugin '{plugin_name}' is already installed (v{entry.get('version', '?')}){R}"
        )
        print(f"{G}Use --force to reinstall{R}")
        return 0

    src = cache / "plugins" / plugin_name
    if not src.is_dir():
        print(f"{E}Plugin source not found: plugins/{plugin_name}/ in the repo{R}")
        return 1

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    _write_api(dest)

    entry = dict(entry)
    if os.environ.get("FLOW_PLUGIN_RAW") == "1":
        entry["raw"] = True
    _write_plugin_json(dest, entry)

    ver = entry.get("version", "?")
    print(f"{P}Installed {plugin_name} v{ver}{R}")
    if entry.get("deps"):
        print(f"{G}Dependencies: pip install {' '.join(entry['deps'])}{R}")
    kind = "GUI plugin — run" if entry.get("gui") else "Run"
    print(f"{G}{kind} it with: flow run {plugin_name}{R}")
    return 0


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _interactive_install(force: bool) -> int:
    try:
        plugins = _catalog()
    except Exception as exc:
        print(f"{E}Could not fetch plugin repo: {exc}{R}")
        return 1
    if not plugins:
        print(f"{M}No plugins available in the repository{R}")
        return 0

    inst = installed()
    choices = [
        dict(
            name=f"{p.get('name')}  v{p.get('version', '?')}  {p.get('description', '')}",
            value=p.get("name"),
            checked=p.get("name") in inst,
        )
        for p in plugins
    ]

    if not _is_tty():
        names = ", ".join(p.get("name") for p in plugins)
        print(f"{M}Interactive install needs a terminal.{R}")
        print(f"{G}Install directly: flow install {names}{R}")
        return 1

    try:
        from questionary import checkbox
    except ImportError:
        print(
            f"{M}Interactive install requires 'questionary' (pip install questionary){R}"
        )
        return 1

    try:
        from backend.ui import questionary_style

        qstyle = questionary_style()
    except Exception:
        qstyle = None

    selected = checkbox(
        "Plugins to install",
        choices=choices,
        style=qstyle,
        instruction="(space to toggle, enter to install)",
    ).ask()
    if not selected:
        print(f"{M}No plugins selected{R}")
        return 0

    rc = 0
    for name in selected:
        rc |= _install_one(name, force)
    return rc


def cmd_install(extra) -> int:
    force = "--force" in extra
    extra = [x for x in extra if x != "--force"]
    if not extra:
        return _interactive_install(force)
    rc = 0
    for ref in extra:
        rc |= _install_one(ref, force)
    return rc


def cmd_uninstall(extra) -> int:
    if not extra:
        print(f"{E}Usage: flow uninstall <plugin-name>{R}")
        return 1
    name = extra[0]
    dest = PLUGINS_DIR / name
    if not dest.exists():
        print(f"{E}Plugin '{name}' is not installed{R}")
        return 1
    shutil.rmtree(dest)
    _pid_file(name).unlink(missing_ok=True)
    print(f"{P}Uninstalled plugin '{name}'{R}")
    return 0


def _pid_file(name: str) -> pathlib.Path:
    return PIDS_DIR / f"{name}.pid"


def _alive(pid: int) -> bool:
    return platform.pid_exists(pid)


def running() -> dict[str, int]:
    result = {}
    if not PIDS_DIR.exists():
        return result
    for f in PIDS_DIR.glob("*.pid"):
        try:
            pid = int(f.read_text().strip())
        except Exception:
            continue
        if _alive(pid):
            result[f.stem] = pid
        else:
            f.unlink(missing_ok=True)
    return result


def cmd_run(extra) -> int:
    if not extra:
        print(f"{E}Usage: flow run <plugin-name> [args...] [-t]{R}")
        return 1

    name = extra[0]
    plugin_args = [x for x in extra[1:] if x not in ("-t", "-bg")]

    dest = PLUGINS_DIR / name
    if not dest.exists():
        print(f"{E}Plugin '{name}' is not installed{R}")
        return 1

    pj = dest / "plugin.json"
    if not pj.exists():
        print(f"{E}Plugin '{name}' has no plugin.json{R}")
        return 1
    try:
        info = json.loads(pj.read_text())
    except Exception:
        print(f"{E}Plugin '{name}' has a corrupt plugin.json{R}")
        return 1

    entry_name = info.get("entry") or "main.py"
    entry_path = dest / entry_name
    if not entry_path.exists():
        print(f"{E}Plugin entry point not found: {entry_name}{R}")
        return 1

    # Background/foreground: explicit flags win, then the plugin's own
    # manifest ("bg": false = runs in the foreground, e.g. console plugins
    # that need Ctrl-C / the terminal), then the DEV_MODE default.
    if "-t" in extra:
        bg = False
    elif "-bg" in extra:
        bg = True
    elif isinstance(info.get("bg"), bool):
        bg = info["bg"]
    else:
        bg = not config.DEV_MODE

    _sync_api(dest)

    flow_bin = shutil.which("flow") or f"{sys.executable} -m cli.main"
    env = os.environ.copy()
    env["FLOW_PLUGIN_NAME"] = name
    env["FLOW_PLUGIN_HOME"] = str(dest)
    env["FLOW_BIN"] = flow_bin
    env["FLOW_PLUGIN_BG"] = "1" if bg else "0"

    if not _ensure_daemon():
        print(f"{E}Could not start the flow daemon (needed for plugin API v3){R}")
        print(f"{G}Start it manually with: flow daemon start{R}")
        return 1
    env["FLOW_SOCKET"] = str(_daemon_socket())
    env["FLOW_PLUGIN_RAW"] = "1" if info.get("raw") else "0"

    PIDS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = None
    if bg:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = open(LOGS_DIR / f"{name}.log", "ab", buffering=0)

    proc = platform.spawn_detached(
        [sys.executable, str(entry_path), *plugin_args],
        cwd=str(dest),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _pid_file(name).write_text(str(proc.pid))

    # Start threads to log plugin stdout/stderr
    try:
        from backend import logger

        def _log_stream(stream_name):
            try:
                stream = getattr(proc, stream_name)
                if stream is None:
                    return
                for line in iter(stream.readline, b""):
                    try:
                        text = line.decode("utf-8", errors="replace")
                    except Exception:
                        text = str(line)
                    logger.log_process_output("plugin", name, stream_name, text)
            except Exception:
                pass

        import threading
        threading.Thread(target=_log_stream, args=("stdout",), daemon=True).start()
        threading.Thread(target=_log_stream, args=("stderr",), daemon=True).start()
        logger.info("plugin", "start", f"plugin '{name}' started", {"name": name, "pid": proc.pid, "bg": bg})
    except Exception:
        pass

    if bg:
        print(f"{P}Running plugin '{name}' in background (pid {proc.pid}){R}")
        print(f"{G}Stop it with: flow plugin kill {name}{R}")
        return 0

    print(f"{P}Running plugin '{name}'{R}")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        _kill_pid(name, proc.pid)
        return 130
    finally:
        try:
            from backend import logger
            logger.info("plugin", "stop", f"plugin '{name}' stopped", {"name": name})
        except Exception:
            pass
        _pid_file(name).unlink(missing_ok=True)


def _kill_pid(name: str, pid: int):
    platform.kill_pid(pid)
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    else:
        platform.kill_pid(pid, force=True)
    _pid_file(name).unlink(missing_ok=True)
    print(f"{P}Stopped plugin '{name}'{R}")


def cmd_kill(extra) -> int:
    running_ = running()
    if not running_:
        print(f"{M}No plugins running{R}")
        return 0

    if extra:
        target = extra[0]
        if target == "all":
            names = list(running_)
        elif target in running_:
            names = [target]
        else:
            print(f"{E}Plugin '{target}' is not running{R}")
            print(f"{G}Running: {', '.join(running_)}{R}")
            return 1
    else:
        if not _is_tty():
            names = ", ".join(running_)
            print(f"{M}Plugins running: {names}{R}")
            print(f"{G}Kill with: flow plugin kill all{R}")
            return 0
        try:
            from backend.ui import pick

            selection, _ = pick(
                "Kill running plugin",
                [(f"{n} (pid {p})", n) for n, p in running_.items()]
                + [("All plugins", "all"), ("Cancel", None)],
                instruction="(↑↓ navigate, Enter to select)",
            )
        except Exception:
            selection = None
        if not selection or selection not in ("all", *running_):
            return 0
        names = list(running_) if selection == "all" else [selection]

    for name in names:
        _kill_pid(name, running_[name])
    return 0


def cmd_update() -> int:
    caches = [REPO_CACHE]
    if OTHER_CACHE.exists():
        caches += [d for d in OTHER_CACHE.iterdir() if d.is_dir()]

    updated = 0
    for cache_dir in caches:
        if not (cache_dir / ".git").exists():
            continue
        if not _has_commits(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)
            updated += 1
            continue
        r = _git(["-C", str(cache_dir), "pull", "--ff-only", "-q"], timeout=30)
        if r.returncode == 0:
            updated += 1
        else:
            print(
                f"{E}Failed to update {cache_dir}: {(r.stderr or r.stdout).strip()}{R}"
            )

    print(f"{P}Updated {updated} plugin repo(s){R}")

    inst = installed()
    for name in inst:
        _sync_api(PLUGINS_DIR / name)
    diffs = []
    try:
        plugins = _catalog()
    except Exception:
        plugins = []
    for p in plugins:
        name = p.get("name")
        if name in inst and inst[name].get("version") != p.get("version"):
            diffs.append(f"  {name}: {inst[name].get('version')} → {p.get('version')}")
    if diffs:
        print(f"\n{P}Available updates (run 'flow install <name> --force'):{R}")
        print("\n".join(diffs))
    else:
        print(f"{G}All installed plugins are up to date{R}")
    return 0


def cmd_refresh() -> int:
    repos = [DEFAULT_REPO]
    if OTHER_CACHE.exists():
        for d in OTHER_CACHE.iterdir():
            if d.is_dir() and (d / ".git").exists():
                r = _git(["-C", str(d), "remote", "get-url", "origin"], timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    repos.append(r.stdout.strip())
    ok = True
    for url in repos:
        try:
            _ensure_repo(url)
        except Exception as exc:
            ok = False
            print(f"{E}Failed to refresh {url}: {exc}{R}")
    print(f"{P}Refreshed {len(repos)} plugin repo(s){R}")
    return 0 if ok else 1


def _dispatch_daemon(extra: list[str]) -> int:
    """flow daemon start|quit|status|socket — manage the resident host."""
    from backend import daemon as _daemon

    sub = extra[0] if extra else "status"
    rest = extra[1:]
    if sub == "start":
        fg = "-f" in rest or "--foreground" in rest
        return _daemon.cmd_start(foreground=fg)
    if sub == "quit":
        return _daemon.cmd_quit()
    if sub == "status":
        return _daemon.cmd_status()
    if sub == "socket":
        print(_daemon.socket_path())
        return 0
    print(f"{E}Unknown daemon subcommand: {sub}{R}")
    print(f"{G}Usage: {P}daemon {S}start|quit|status|socket{R}")
    return 1


def dispatch(cmd: str, extra: list[str], args: argparse.Namespace | None = None):
    if cmd == "daemon":
        return _dispatch_daemon(extra)
    if cmd in ("plugins", "plugin", "pl"):
        subcmd = extra[0] if extra else "list"
        rest = extra[1:] if len(extra) > 1 else []
        if subcmd == "list":
            return cmd_list(rest)
        if subcmd == "install":
            return cmd_install(rest)
        if subcmd in ("uninstall", "remove"):
            return cmd_uninstall(rest)
        if subcmd == "run":
            return cmd_run(rest)
        if subcmd == "update":
            return cmd_update()
        if subcmd == "refresh":
            return cmd_refresh()
        if subcmd == "kill":
            return cmd_kill(rest)
        print(f"{E}Unknown plugin subcommand: {subcmd}{R}")
        print(
            f"{G}Usage: {P}plugins {S}list|install|uninstall|run|update|refresh|kill{R}"
        )
        return 1
    if cmd == "install":
        return cmd_install(list(extra))
    if cmd in ("uninstall", "remove"):
        return cmd_uninstall(list(extra))
    if cmd == "run":
        return cmd_run(list(extra))
    if cmd == "update":
        return cmd_update()
    if cmd == "refresh":
        return cmd_refresh()
    if cmd == "kill":
        return cmd_kill(list(extra))
    return None
