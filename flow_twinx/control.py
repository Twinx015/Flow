import json
import pathlib
import time

CONTROL_FILE = pathlib.Path.home() / ".flow/web_command.json"

COMMANDS = {"stop", "next", "previous"}


def send(command: str):
    if command not in COMMANDS:
        return
    CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTROL_FILE.write_text(json.dumps({"command": command, "ts": time.time()}))


def take() -> str:
    if not CONTROL_FILE.exists():
        return ""
    try:
        data = json.loads(CONTROL_FILE.read_text())
        return data.get("command", "")
    except (json.JSONDecodeError, OSError):
        return ""
    finally:
        CONTROL_FILE.unlink(missing_ok=True)
