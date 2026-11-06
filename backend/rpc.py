import json
import os
import pathlib
import signal as _signal_mod
import socket
import sys
import time

from backend import config, control
from backend import status as _status
from backend.config import GREY, RED, YELLOW, Muted, Primary, Reset

E = RED
G = GREY
M = Muted
P = Primary
R = Reset
config.keep_live(globals())
Y = YELLOW

#: Typed-only, gated-raw version of the plugin API.
API_VERSION = 4


def _plugin_manifest(name: str) -> dict | None:
    """Read an installed plugin's plugin.json (host-validated surface)."""
    manifest_file = pathlib.Path.home() / ".flow/plugins" / name / "plugin.json"
    if not manifest_file.exists():
        return None
    try:
        return json.loads(manifest_file.read_text())
    except Exception:
        return None


def _conn_capabilities(conn: socket.socket) -> dict:
    """Capabilities for a plugin connection, host-validated from its manifest.

    `raw` is a *host-side* decision: the launcher sends the plugin name on
    connect (FLOW_PLUGIN_NAME), and the host checks the installed manifest for
    ``"raw": true`` (or the env override from the launcher). A plugin cannot
    grant itself raw by editing its own copy of flow_api.py.
    """
    name = _conn_plugin_name(conn)
    caps = {"raw": False}
    manifest = _plugin_manifest(name) if name else None
    if manifest and manifest.get("raw"):
        caps["raw"] = True
    return caps


def _conn_plugin_name(conn: socket.socket) -> str | None:
    return getattr(conn, "_flow_plugin_name", None)


def rpc_status():
    return _status.read()


def rpc_current_track():
    return _status.read() or {}


def rpc_is_playing():
    data = _status._read()
    return bool(data.get("playing"))


def rpc_library_stats():
    """Counts from `library.db` (SQLite — read through `backend.library`)."""
    try:
        from backend import library

        liked = library.get_liked_ids()
        downloaded = library.get_downloaded_ids()
        plays = library.play_rows()
        return {
            "songs": len(plays) + len(liked) + len(downloaded),
            "liked": len(liked),
            "downloaded": len(downloaded),
            "duration": sum(row["duration"] for row in plays),
            "plays": sum(row["song_count"] for row in plays),
            "played": len(plays),
        }
    except Exception:
        return {}


def rpc_history(params: dict | None = None) -> list:
    """Online play log from `history.db` (SQLite — read through `backend.history`)."""
    from backend import history

    params = params or {}
    sort = str(params.get("sort", "recent"))
    if sort not in history.SORTS:
        sort = "recent"
    range_key = str(params.get("range", "all"))
    days = history.RANGES.get(range_key)
    since = time.time() - days * 86400 if days else None
    try:
        limit = int(params.get("limit", 25))
    except TypeError, ValueError:
        limit = 25
    return history.timeline(
        sort=sort,
        limit=limit,
        since=since,
        unique=bool(params.get("unique")) or sort in ("most", "least"),
    )


def _player_running() -> bool:
    from backend import registry

    return registry.resolve("vlc") is not None or registry.resolve("web") is not None


def _send_player(action: str, label: str, delta=None):
    """Host-authoritative player routing — same as the CLI does it."""
    from backend import ipc, registry

    entry = registry.resolve("vlc")
    if entry is not None:
        pid = entry["pid"]
        if delta is not None:
            config.write_seek(int(delta))
        payload = {"delta": delta} if delta is not None else None
        if ipc.send(entry, action, payload):
            return f"{label} (VLC pid {pid})"
        config.clear_pid_if(pid)
    command = ipc.WEB_COMMANDS.get(action, action)
    control.send(command, delta)
    return f"{label} (web player)"


def rpc_pause() -> str:
    return _send_player("pause", "Toggled pause/resume")


def rpc_resume() -> str:
    return _send_player("pause", "Resumed playback")


def rpc_next() -> str:
    return _send_player("next", "Skipped to next track")


def rpc_previous() -> str:
    return _send_player("prev", "Went to previous track")


def rpc_seek(sec: float) -> str:
    return _send_player("seek_fwd", f"Seeked forward {int(sec)}s", int(sec) * 1000)


def rpc_seek_back(sec: float) -> str:
    return _send_player("seek_bwd", f"Seeked backward {int(sec)}s", -int(sec) * 1000)


def _act_current(action: str) -> str:
    data = _status._read()
    title = (data.get("title") or "").strip()
    thumb = data.get("thumbnail") or ""
    if not title:
        return "No last-played track in ~/.flow/status.json"

    from backend import registry

    if registry.resolve("vlc") is None and registry.resolve("web") is None:
        return "No player is currently running (no pid file)"
    if not (data.get("playing") and _status._fresh(data)):
        return "No track is currently playing"

    flow_dir = str(pathlib.Path.home() / ".flow")
    if thumb.startswith(("http://", "https://")):
        config.Mode = "Online"
        from backend.Online import commands as module
    elif (".cache/" in thumb) or thumb.startswith(flow_dir):
        config.Mode = "Offline"
        from backend.Offline import commands as module
    else:
        return f"Could not tell if the current track is online or offline (thumbnail: {thumb})"

    module.act_on_current(action, title, thumb)
    return f"{action}: {title}"


def rpc_like() -> str:
    return _act_current("like")


def rpc_unlike() -> str:
    return _act_current("unlike")


def rpc_download() -> str:
    return _act_current("download")


def rpc_players():
    from backend import registry

    return registry.live()


def rpc_get_config(key: str):
    value, ok = config.config_get(key)
    if not ok:
        return {"error": f"Unknown config key '{key}'"}
    return {"value": value}


def rpc_get_configs(params: dict | None = None):
    """Fetch a set of configs by key; returns {key: value}.

    `params["keys"]` is the requested list (what `flow_api.get_configs(keys)`
    sends). With no list, every readable key is returned, matching the
    client's "give me what I asked for" contract.
    """
    params = params or {}
    keys = params.get("keys")
    if not isinstance(keys, list) or not keys:
        keys = sorted(config.PLUGIN_SAFE_KEYS)
    out = {}
    for key in keys:
        value, ok = config.config_get(str(key))
        if ok:
            out[str(key).lower()] = value
    return out


def rpc_set_config(key: str, value):
    if value is None:
        return {"error": f"Config value for '{key}' cannot be None"}
    if key.lower() not in config.PLUGIN_SAFE_KEYS:
        return {"error": f"Config key '{key}' is not writable by plugins"}
    msg = config.apply_config(key, value)
    return {"message": msg}


def rpc_set_theme(name: str):
    msg = config.apply_config("theme", name)
    return {"message": msg}


def rpc_list_themes():
    return sorted(config.THEMES)


def rpc_set_spinner(chars: str):
    msg = config.apply_config("spinner", chars)
    return {"message": msg}


def rpc_raw_cli(conn, args: list[str]):
    caps = _conn_capabilities(conn)
    if not caps.get("raw"):
        return {
            "error": (
                "raw_cli() is disabled for this plugin. Enable it by adding "
                '"raw": true to plugin.json (docs/dev/plugins.md) or install '
                "with FLOW_PLUGIN_RAW=1."
            )
        }
    from backend import cli_raw

    code, out = cli_raw.run(*args)
    return {"code": code, "output": out}


METHODS = (
    "status",
    "current_track",
    "is_playing",
    "library_stats",
    "history",
    "pause",
    "resume",
    "next",
    "previous",
    "seek",
    "seek_back",
    "like",
    "unlike",
    "download",
    "players",
    "get_config",
    "get_configs",
    "set_config",
    "set_theme",
    "list_themes",
    "set_spinner",
    "raw_cli",
    "introspect",
)


def rpc_introspect():
    return {
        "api_version": API_VERSION,
        "protocol": "socket",
        "methods": list(METHODS),
        "safe_keys": sorted(config.PLUGIN_SAFE_KEYS),
        "transport": "socket",
    }


def handle(frame: dict, conn: socket.socket | None = None) -> dict | None:
    """Dispatch a single `{method, params}` frame. Returns a response dict."""
    method = frame.get("method")
    params = frame.get("params") or {}

    if method == "hello":
        name = params.get("name")
        if conn is not None:
            setattr(conn, "_flow_plugin_name", name)
        return {
            "api_version": API_VERSION,
            "protocol": "socket",
            "capabilities": _conn_capabilities(conn) if conn else {"raw": False},
        }

    try:
        if method == "status":
            return {"result": rpc_status()}
        if method == "current_track":
            return {"result": rpc_current_track()}
        if method == "is_playing":
            return {"result": rpc_is_playing()}
        if method == "library_stats":
            return {"result": rpc_library_stats()}
        if method == "history":
            return {"result": rpc_history(params)}
        if method == "pause":
            return {"result": rpc_pause()}
        if method == "resume":
            return {"result": rpc_resume()}
        if method == "next":
            return {"result": rpc_next()}
        if method == "previous":
            return {"result": rpc_previous()}
        if method == "seek":
            return {"result": rpc_seek(float(params.get("seconds", 0)))}
        if method == "seek_back":
            return {"result": rpc_seek_back(float(params.get("seconds", 0)))}
        if method == "like":
            return {"result": rpc_like()}
        if method == "unlike":
            return {"result": rpc_unlike()}
        if method == "download":
            return {"result": rpc_download()}
        if method == "players":
            return {"result": rpc_players()}
        if method == "get_config":
            return {"result": rpc_get_config(str(params.get("key", "")))}
        if method == "get_configs":
            return {"result": rpc_get_configs(params)}
        if method == "set_config":
            return {
                "result": rpc_set_config(
                    str(params.get("key", "")), params.get("value")
                )
            }
        if method == "set_theme":
            return {"result": rpc_set_theme(str(params.get("name", "")))}
        if method == "list_themes":
            return {"result": rpc_list_themes()}
        if method == "set_spinner":
            return {"result": rpc_set_spinner(str(params.get("chars", "")))}
        if method == "raw_cli":
            return rpc_raw_cli(conn, list(params.get("args") or []))
        if method == "introspect":
            return {"result": rpc_introspect()}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    return {"error": f"Unknown method '{method}'"}
