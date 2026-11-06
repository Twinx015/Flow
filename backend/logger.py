import datetime
import json
import logging
import logging.handlers
import os
import pathlib
import threading
import traceback
import uuid

from backend import config

LOGS_DIR = pathlib.Path.home() / ".flow/LOGS"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Global run context
_run_id = str(uuid.uuid4())[:8]
_run_start = datetime.datetime.now(datetime.timezone.utc)
_run_start_str = _run_start.strftime("%Y%m%d_%H%M%S")

# File handlers and locks
_main_handler = None
_component_handlers: dict[str, logging.handlers.RotatingFileHandler] = {}
_lock = threading.Lock()


def _get_main_log_path() -> pathlib.Path:
    """Get the main log file path based on dev mode."""
    if config.DEV_MODE:
        return LOGS_DIR / f"{_run_start_str}_dev.jsonl"
    return LOGS_DIR / f"{_run_start_str}.jsonl"


def _get_component_log_path(component: str) -> pathlib.Path:
    """Get component-specific log file path (only used in dev mode)."""
    if not config.DEV_MODE:
        return _get_main_log_path()
    return LOGS_DIR / f"{_run_start_str}_dev_{component}.jsonl"


def _make_json_formatter():
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            try:
                app_version = getattr(config, "VERSION", "unknown")
            except Exception:
                app_version = "unknown"
            log_entry = {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
                "level": record.levelname,
                "component": getattr(record, "component", "system"),
                "event": getattr(record, "event", "log"),
                "message": record.getMessage(),
                "data": getattr(record, "data", None),
                "pid": os.getpid(),
                "thread": record.threadName,
                "correlation_id": _run_id,
                "app_version": app_version,
                "mode": getattr(config, "Mode", "unknown"),
            }
            if record.exc_info:
                log_entry["error"] = {
                    "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                    "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                    "traceback": "".join(traceback.format_exception(*record.exc_info)),
                }
            if log_entry["data"] is None:
                del log_entry["data"]
            if log_entry.get("error"):
                if not log_entry["error"].get("message") and not log_entry["error"].get("traceback"):
                    del log_entry["error"]
            # default=str keeps payloads with Paths/datetimes from crashing
            # the formatter (a logging error drops the line entirely).
            return json.dumps(log_entry, ensure_ascii=False, default=str)

    return JsonFormatter()


def _ensure_handlers():
    global _main_handler
    with _lock:
        if _main_handler is None:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            _main_handler = logging.handlers.RotatingFileHandler(
                _get_main_log_path(),
                maxBytes=512_000,
                backupCount=5,
                encoding="utf-8",
            )
            _main_handler.setFormatter(_make_json_formatter())


def _ensure_component_handler(component: str):
    with _lock:
        if component not in _component_handlers:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                _get_component_log_path(component),
                maxBytes=512_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(_make_json_formatter())
            _component_handlers[component] = handler


def _get_logger(component: str) -> logging.Logger:
    logger = logging.getLogger(f"flow.{component}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    _ensure_handlers()
    handler_ids = {id(h) for h in logger.handlers}
    if id(_main_handler) not in handler_ids:
        logger.handlers.clear()
        logger.addHandler(_main_handler)

    if config.DEV_MODE:
        _ensure_component_handler(component)
        comp_handler = _component_handlers[component]
        if id(comp_handler) not in handler_ids:
            logger.addHandler(comp_handler)

    return logger


def log(component: str, level: str, event: str, message: str, data: dict | None = None, exc_info=None):
    """Core logging function."""
    _ensure_handlers()
    logger = _get_logger(component)
    level_map = {
        "TRACE": logging.DEBUG,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "FATAL": logging.CRITICAL,
        "CRITICAL": logging.CRITICAL,
    }
    log_level = level_map.get(str(level).upper(), logging.INFO)
    extra = {"component": component, "event": event, "data": data}
    logger.log(log_level, message, extra=extra, exc_info=exc_info)


def trace(component: str, event: str, message: str, data: dict | None = None):
    log(component, "TRACE", event, message, data)


def debug(component: str, event: str, message: str, data: dict | None = None):
    log(component, "DEBUG", event, message, data)


def info(component: str, event: str, message: str, data: dict | None = None):
    log(component, "INFO", event, message, data)


def warn(component: str, event: str, message: str, data: dict | None = None):
    log(component, "WARN", event, message, data)


def error(component: str, event: str, message: str, data: dict | None = None, exc_info=None):
    log(component, "ERROR", event, message, data, exc_info=exc_info)


def fatal(component: str, event: str, message: str, data: dict | None = None, exc_info=None):
    log(component, "FATAL", event, message, data, exc_info=exc_info)


def log_user_input(component: str, raw_input: str, data: dict | None = None):
    info(component, "user_input", raw_input, data)


def log_command(component: str, command: str, args: list | str | None = None, data: dict | None = None):
    cmd_data = {"command": command}
    if args is not None:
        cmd_data["args"] = args if isinstance(args, (list, dict)) else str(args)
    if data:
        cmd_data.update(data)
    arg_str = ""
    if isinstance(args, list):
        arg_str = " ".join(str(a) for a in args)
    elif args:
        arg_str = str(args)
    info(component, "command", f"{command} {arg_str}".strip(), cmd_data)


def log_response(component: str, event: str = "response", message: str = "", data: dict | None = None):
    info(component, event, message, data)


def log_process_output(component: str, process: str, stream: str, line: str, data: dict | None = None):
    proc_data = {"process": process, "stream": stream}
    if data:
        proc_data.update(data)
    level = "INFO" if stream == "stdout" else "WARN"
    log(component, level, f"process_{stream}", line.rstrip(), proc_data)


def log_http(component: str, method: str, path: str, status: int, duration_ms: float | None = None, data: dict | None = None):
    http_data = {"method": method, "path": path, "status": status}
    if duration_ms is not None:
        http_data["duration_ms"] = duration_ms
    if data:
        http_data.update(data)
    level = "INFO"
    if status >= 500:
        level = "ERROR"
    elif status >= 400:
        level = "WARN"
    log(component, level, "http_request", f"{method} {path} -> {status}", http_data)


def log_track_play(component: str, track_info: dict, data: dict | None = None):
    play_data = {}
    if track_info:
        play_data.update(track_info)
    if data:
        play_data.update(data)
    title = track_info.get('title', 'Unknown') if track_info else 'Unknown'
    artist = track_info.get('artist') or track_info.get('uploader') or ''
    msg = f"{title} - {artist}".strip() if artist else title
    log(component, "INFO", "track_play", msg, play_data)


def log_track_event(component: str, event_type: str, track_info: dict, data: dict | None = None):
    evt_data = {"event_type": event_type}
    if track_info:
        evt_data.update(track_info)
    if data:
        evt_data.update(data)
    title = track_info.get('title', 'Unknown') if track_info else 'Unknown'
    log(component, "INFO", event_type, title, evt_data)


def get_run_id() -> str:
    return _run_id


def get_run_start_str() -> str:
    return _run_start_str


def get_main_log_path() -> pathlib.Path:
    return _get_main_log_path()


def get_logs_dir() -> pathlib.Path:
    return LOGS_DIR
