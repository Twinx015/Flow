import json
import pathlib
import time

STATUS_FILE = pathlib.Path.home() / ".flow/status.json"
WEB_PID_FILE = pathlib.Path.home() / ".flow/web.pid"
WEB_PORT_FILE = pathlib.Path.home() / ".flow/web_port"


def update(title, duration=0, playing=True, thumbnail=None):
    data = {
        "title": title or "Unknown",
        "duration": int(duration or 0),
        "playing": bool(playing),
        "thumbnail": thumbnail or "",
        "ts": time.time(),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data))


def _read():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}


def _web_active():
    try:
        if not WEB_PID_FILE.exists():
            return False
        import psutil

        pid = int(WEB_PID_FILE.read_text().strip())
        return psutil.Process(pid).is_running()
    except Exception:
        return False


def _web_port():
    try:
        return int(WEB_PORT_FILE.read_text().strip())
    except Exception:
        return None


def _fresh(data):
    ts = data.get("ts", 0)
    dur = data.get("duration", 0)
    return time.time() - ts <= max(120.0, dur + 30.0)


def show():
    from .config import Cyan, Grey, Muted, Primary, Reset, White

    data = _read()
    web = _web_active()
    port = _web_port()
    playing = bool(data.get("playing")) and _fresh(data)

    title = data.get("title", "None")
    if len(title) > 42:
        title = title[:42] + "..."
    thumb = data.get("thumbnail", "")
    flow_prefix = str(pathlib.Path.home() / ".flow")
    if thumb.startswith(flow_prefix):
        thumb = thumb[len(flow_prefix):]
    if len(thumb) > 120:
        thumb = thumb[:120] + "..."
    dur = int(data.get("duration", 0))
    mins, secs = divmod(dur, 60)
    dur_str = f"{mins}:{secs:02d}"

    status_val = "playing" if playing else "not playing"
    status_col = Cyan if playing else Muted
    web_val = f"{port} active" if web else "not active"
    stat = "currently playing" if playing else "last played"
    web_col = Cyan if web else Muted

    sep = f"{Grey}{'─' * 44}{Reset}"
    print(f"\n{Primary}┌─ Flow Status{Reset}")
    print(sep)
    print(f"{Primary}│{Reset}  {'status':<17}: {status_col}{status_val}{Reset}")
    print(f"{Primary}│{Reset}  {'web_mode':<17}: {web_col}{web_val}{Reset}")
    print(f"{Primary}│{Reset}  {stat:<17}: {White}{title}{Reset}")
    print(f"{Primary}│{Reset}  {'thumbnail':<17}: {White}{thumb}{Reset}")
    print(f"{Primary}│{Reset}  {'total duration':<17}: {White}{dur_str}{Reset}")
    print(sep)
    print(f"{Primary}└─{Reset}\n")
