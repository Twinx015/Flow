import json
import os
import pathlib
import re
import shutil

CONFIG_FILE = pathlib.Path.home() / ".flow/config.json"


def merge_flags(extra: list[str], args) -> tuple[list[str], object]:
    mapping = {"-bg": "bg", "-s": "shuffle", "-d": "download"}
    rest = []
    i = 0
    while i < len(extra):
        item = extra[i]
        if item == "-r":
            setattr(args, "repeat", True)
            if i + 1 < len(extra) and extra[i + 1].isdigit():
                setattr(args, "repeat_count", int(extra[i + 1]))
                i += 1
            else:
                setattr(args, "repeat_count", -1)
        elif item in mapping:
            setattr(args, mapping[item], True)
        elif item.startswith("-"):
            print(f"Unknown flag: {item}")
        else:
            rest.append(item)
        i += 1
    return rest, args


Red = "\033[0;31m"
Green = "\033[0;32m"
Brown = "\033[0;33m"
Blue = "\033[0;34m"
Purple = "\033[0;35m"
Cyan = "\033[0;36m"
Grey = "\033[90m"
YELLOW = "\033[1;33m"
White = "\033[1;37m"
MAROON = "\033[38;5;124m"
OLIVE = "\033[38;5;100m"
DARK_KHAKI = "\033[38;5;136m"
GOLD = "\033[38;5;220m"
TAN = "\033[38;5;215m"
SALMON = "\033[38;5;209m"
CORAL = "\033[38;5;203m"
HOT_PINK = "\033[38;5;205m"
VIOLET = "\033[38;5;141m"
DEEP_PURPLE = "\033[38;5;129m"
TEAL = "\033[38;5;30m"
SKY_BLUE = "\033[38;5;117m"
STEEL_BLUE = "\033[38;5;67m"
NAVY = "\033[38;5;18m"
INDIGO = "\033[38;5;54m"
ORANGE = "\033[38;5;202m"
PINK = "\033[38;5;205m"
LIME = "\033[38;5;154m"
Reset = "\033[0m"

_COLORS = {
    k.lower().replace("_", ""): v
    for k, v in vars().items()
    if isinstance(v, str) and v.startswith("\033") and k != "Reset"
}

_COLOR_NAMES = {v: k for k, v in _COLORS.items()}

_TARGET_ALIASES = {"pri": "primary", "sec": "secondary", "ter": "tertiary"}
_TARGETS = {"primary", "secondary", "tertiary", "display"}
_DISPLAY_MODES = {"none", "bars", "lyrics"}
_BAR_SPACING = {"min", "fit", "max"}

Primary = Cyan
Secondary = Purple
Tertiary = Blue
Muted = Grey
Display = "bars"
BarWidth = 20
BarHeight = 10
BarSpacing = 1
Sensitivity = 1.0

####### Be carefull this will make everything print on screen including links title view and all things ###
DEV_MODE = False
###########################################################################################################

FFMPEG = False
FORMAT = "webm"
_VALID_FORMATS = {"opus", "m4a", "mp3", "webm"}


def set_format(fmt):
    global FORMAT
    fmt = fmt.lower()
    if fmt not in _VALID_FORMATS:
        return False
    if fmt != "webm" and not FFMPEG:
        return False
    FORMAT = fmt
    _save_config()
    return True


def dev_print(label: str, data: dict | list | str | None = None):
    if not DEV_MODE:
        return
    Y = "\033[1;33m"
    D = "\033[90m"
    RST = "\033[0m"
    sep = f"{D}{'─' * 50}{RST}"
    print(f"\n{Y}┌─ [DEV] {label} ─{RST}")
    print(sep)
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (list, tuple)):
                print(f"{Y}│{RST} {D}{k}:{RST}")
                for item in v:
                    if isinstance(item, dict):
                        for ik, iv in item.items():
                            print(f"{Y}│{RST}   {D}{ik}:{RST} {iv}")
                    else:
                        print(f"{Y}│{RST}   {item}")
            else:
                print(f"{Y}│{RST} {D}{k}:{RST} {v}")
    elif isinstance(data, (list, tuple)):
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                print(f"{Y}│{RST} {D}[{idx}]{RST}")
                for k, v in item.items():
                    print(f"{Y}│{RST}   {D}{k}:{RST} {v}")
            else:
                print(f"{Y}│{RST} {D}[{idx}]{RST} {item}")
    elif data is not None:
        text = str(data)
        while text:
            chunk, text = text[:70], text[70:]
            print(f"{Y}│{RST} {chunk}")
    print(sep)
    print(f"{Y}└─{RST}\n")


def get_bar_spacing():
    import os

    if BarSpacing == "min":
        return 0
    if BarSpacing == "max":
        return 4
    if BarSpacing == "fit":
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        return max(0, min(4, (cols - BarWidth) // max(BarWidth - 1, 1)))
    return int(BarSpacing)


def _detect_ffmpeg():
    return shutil.which("ffmpeg") is not None


def check_deps():
    def _try_import(name):
        try:
            __import__(name)
            return True
        except ImportError:
            return False

    deps = [
        ("ffmpeg", shutil.which("ffmpeg") is not None),
        ("vlc", _try_import("vlc")),
        ("yt-dlp", _try_import("yt_dlp")),
        ("psutil", _try_import("psutil")),
    ]
    print(f"  | {'dep':10s} | {'status':13s} | {'test':6s} |")
    print(f"  | {'─' * 10} | {'─' * 13} | {'─' * 6} |")
    for name, ok in deps:
        status = "installed" if ok else "not installed"
        test = "passed" if ok else "failed"
        print(f"  | {name:10s} | {status:13s} | {test:6s} |")


def export_flow():
    import zipfile

    flow_dir = pathlib.Path.home() / ".flow"
    dest = pathlib.Path.home() / "Downloads" / "flow_backup.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    skip_dirs = {"downloads", "playlist", "LOGS"}
    skip_files = {"vlc.pid"}
    included = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(flow_dir):
            rel_root = pathlib.Path(root).relative_to(flow_dir)
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in files:
                if fname in skip_files:
                    continue
                fpath = pathlib.Path(root) / fname
                arcname = rel_root / fname
                zf.write(fpath, arcname)
                included += 1
    size_kb = dest.stat().st_size // 1024
    print(f"Exported {included} files to {dest} ({size_kb} KB)")


FILLER_WORDS = {
    "official",
    "officials",
    "video",
    "videos",
    "music",
    "audio",
    "lyrics",
    "lyric",
    "hd",
    "hq",
    "4k",
    "full",
    "song",
    "songs",
    "ft",
    "feat",
    "featuring",
    "remix",
    "cover",
    "live",
    "version",
    "original",
    "new",
    "latest",
    "trailer",
    "teaser",
    "release",
    "mv",
    "visualizer",
    "explicit",
    "clip",
    "old",
    "#video",
    "#song"
}


def _truncate_title(title):
    title = re.sub(r"[^A-Za-z0-9\s]", "", title)

    words = [word for word in title.split() if word.lower() not in FILLER_WORDS]

    return " ".join(words[:4]) + "..." if len(words) > 4 else " ".join(words)


def _load_config():
    global \
        Primary, \
        Secondary, \
        Tertiary, \
        Display, \
        BarWidth, \
        BarHeight, \
        BarSpacing, \
        Sensitivity, \
        DEV_MODE, \
        FFMPEG, \
        FORMAT, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if "primary" in data and data["primary"] in _COLORS:
            Primary = _COLORS[data["primary"]]
        if "secondary" in data and data["secondary"] in _COLORS:
            Secondary = _COLORS[data["secondary"]]
        if "tertiary" in data and data["tertiary"] in _COLORS:
            Tertiary = _COLORS[data["tertiary"]]
        if "display" in data and data["display"] in _DISPLAY_MODES:
            Display = data["display"]
        if (
            "bar_width" in data
            and isinstance(data["bar_width"], int)
            and 4 <= data["bar_width"] <= 80
        ):
            BarWidth = data["bar_width"]
        if (
            "bar_height" in data
            and isinstance(data["bar_height"], int)
            and 2 <= data["bar_height"] <= 24
        ):
            BarHeight = data["bar_height"]
        if (
            "bar_spacing" in data
            and isinstance(data["bar_spacing"], int)
            and 0 <= data["bar_spacing"] <= 4
        ):
            BarSpacing = data["bar_spacing"]
        if (
            "sensitivity" in data
            and isinstance(data["sensitivity"], (int, float))
            and 0.5 <= data["sensitivity"] <= 5.0
        ):
            Sensitivity = data["sensitivity"]
        if "dev" in data and isinstance(data["dev"], bool):
            DEV_MODE = data["dev"]
        if "ffmpeg" in data and isinstance(data["ffmpeg"], bool):
            FFMPEG = data["ffmpeg"]
        if "format" in data and data["format"] in _VALID_FORMATS:
            FORMAT = data["format"]
        if "max_search" in data and isinstance(data["max_search"], int) and 1 <= data["max_search"] <= 20:
            MAX_SEARCH_RESULTS = data["max_search"]
        if "max_radio" in data and isinstance(data["max_radio"], int) and 1 <= data["max_radio"] <= 50:
            MAX_RESULTS_RADIO = data["max_radio"]
    except json.JSONDecodeError, OSError:
        pass


def _save_config():
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "primary": _COLOR_NAMES.get(Primary, "cyan"),
        "secondary": _COLOR_NAMES.get(Secondary, "purple"),
        "tertiary": _COLOR_NAMES.get(Tertiary, "blue"),
        "display": Display,
        "bar_width": BarWidth,
        "bar_height": BarHeight,
        "bar_spacing": BarSpacing,
        "sensitivity": Sensitivity,
        "dev": DEV_MODE,
        "ffmpeg": FFMPEG,
        "format": FORMAT,
        "max_search": MAX_SEARCH_RESULTS,
        "max_radio": MAX_RESULTS_RADIO,
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


DOWNLOAD_DIR = pathlib.Path.home() / ".flow/downloads"

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version

    VERSION = _version("flow-twinx")
except PackageNotFoundError:
    VERSION = "0.5.1"

Mode = "Online"

liked_music = pathlib.Path.home() / ".flow/liked.json"

MAX_RESULTS_RADIO = 35
MAX_SEARCH_RESULTS = 5

PID_FILE = pathlib.Path.home() / ".flow/vlc.pid"


def save_pid(pid: int):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except ValueError, OSError:
        return None


def clear_pid():
    if PID_FILE.exists():
        PID_FILE.unlink()


def kill_stored():
    import os
    import signal

    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    clear_pid()
    return True


def cmd_config(extra: list[str], args=None):
    global \
        Primary, \
        Secondary, \
        Tertiary, \
        Display, \
        BarWidth, \
        BarHeight, \
        BarSpacing, \
        Sensitivity, \
        DEV_MODE, \
        FFMPEG, \
        FORMAT, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO
    if extra and (extra[0] in ("help", "-h")):
        print(f"{Tertiary}Available targets:{Reset}")
        print(f"  {Primary}primary{Reset}   (aliases: pri)")
        print(f"  {Secondary}secondary{Reset} (aliases: sec)")
        print(f"  {Tertiary}tertiary{Reset}  (aliases: ter)")
        print(f"  {Grey}display{Reset}    (none, bars, lyrics)")
        print(f"  {Grey}barwidth{Reset}   (4-80, current: {BarWidth})")
        print(f"  {Grey}barheight{Reset}  (2-24, current: {BarHeight})")
        print(f"  {Grey}barspacing{Reset} (0-4, min, fit, max — current: {BarSpacing})")
        print(f"  {Grey}sensitivity{Reset} (0.5-5.0, current: {Sensitivity})")
        print(f"  {Grey}format{Reset}     (opus, m4a, mp3, webm — current: {FORMAT})")
        print(f"  {Grey}max_search{Reset} (1-20, current: {MAX_SEARCH_RESULTS})")
        print(f"  {Grey}max_radio{Reset}  (1-50, current: {MAX_RESULTS_RADIO})")
        print(f"\n{Tertiary}Available colors:{Reset}")
        for name, code in _COLORS.items():
            print(f"  {code}{name}{Reset}")
        print(f"\n{Grey}Config file: {CONFIG_FILE}{Reset}")
        return
    if not extra:
        print(f"{Primary}Usage: config <target> <value>{Reset}")
        print(f"       config -h{Reset}")
        return
    if len(extra) < 2:
        print(f"Usage: config <target> <value>{Reset}")
        return
    target = _TARGET_ALIASES.get(extra[0].lower(), extra[0].lower())
    value = extra[1].lower()
    if target == "primary":
        if value not in _COLORS:
            print(f"Unknown color '{value}'. Use 'config -h' to see available colors.")
            return
        Primary = _COLORS[value]
        _save_config()
        print(f"{Primary}Primary color changed to {value}{Reset}")
    elif target == "secondary":
        if value not in _COLORS:
            print(f"Unknown color '{value}'. Use 'config -h' to see available colors.")
            return
        Secondary = _COLORS[value]
        _save_config()
        print(f"{Secondary}Secondary color changed to {value}{Reset}")
    elif target == "tertiary":
        if value not in _COLORS:
            print(f"Unknown color '{value}'. Use 'config -h' to see available colors.")
            return
        Tertiary = _COLORS[value]
        _save_config()
        print(f"{Tertiary}Tertiary color changed to {value}{Reset}")
    elif target == "display":
        if value not in _DISPLAY_MODES:
            print(f"Unknown display mode '{value}'. Options: none, bars, lyrics")
            return
        Display = value
        _save_config()
        print(f"{Tertiary}Display mode changed to {value}{Reset}")
    elif target in ("barwidth", "width"):
        try:
            v = int(extra[1])
        except ValueError:
            print("barwidth must be an integer (4-80)")
            return
        if not (4 <= v <= 80):
            print("barwidth must be between 4 and 80")
            return
        BarWidth = v
        _save_config()
        print(f"{Tertiary}Bar width changed to {v}{Reset}")
    elif target in ("barheight", "height"):
        try:
            v = int(extra[1])
        except ValueError:
            print("barheight must be an integer (2-24)")
            return
        if not (2 <= v <= 24):
            print("barheight must be between 2 and 24")
            return
        BarHeight = v
        _save_config()
        print(f"{Tertiary}Bar height changed to {v}{Reset}")
    elif target in ("barspacing", "spacing"):
        if value in _BAR_SPACING:
            BarSpacing = value
            _save_config()
            print(f"{Tertiary}Bar spacing changed to {value}{Reset}")
        else:
            try:
                v = int(extra[1])
            except ValueError:
                print("barspacing must be 0-4, min, fit, or max")
                return
            if not (0 <= v <= 4):
                print("barspacing must be between 0 and 4")
                return
            BarSpacing = v
            _save_config()
            print(f"{Tertiary}Bar spacing changed to {v}{Reset}")
    elif target == "sensitivity":
        try:
            v = float(extra[1])
        except ValueError:
            print("sensitivity must be a number (0.5-5.0)")
            return
        if not (0.5 <= v <= 5.0):
            print("sensitivity must be between 0.5 and 5.0")
            return
        Sensitivity = v
        _save_config()
        print(f"{Tertiary}Sensitivity changed to {v}{Reset}")
    elif target == "dev":
        if value not in ("true", "false"):
            print("Usage: config dev true/false")
            return
        DEV_MODE = value == "true"
        _save_config()
        print(f"{Tertiary}Dev mode set to {DEV_MODE}{Reset}")
    elif target == "format":
        if value not in _VALID_FORMATS:
            print(f"Unknown format '{value}'. Options: opus, m4a, mp3, webm")
            return
        FORMAT = value
        if FORMAT != "webm" and not FFMPEG:
            print(
                f"{YELLOW}ffmpeg not found. Install ffmpeg to use {FORMAT} format.{Reset}\n"
                f"{Grey}  Defaulting to webm until ffmpeg is installed.{Reset}"
            )
        _save_config()
        print(f"{Tertiary}Default download format changed to {value}{Reset}")
    elif target in ("max_search", "maxresults"):
        try:
            v = int(extra[1])
        except ValueError:
            print("max_search must be an integer (1-20)")
            return
        if not (1 <= v <= 20):
            print("max_search must be between 1 and 20")
            return
        MAX_SEARCH_RESULTS = v
        _save_config()
        print(f"{Tertiary}Max search results changed to {v}{Reset}")
    elif target in ("max_radio", "maxradio"):
        try:
            v = int(extra[1])
        except ValueError:
            print("max_radio must be an integer (1-50)")
            return
        if not (1 <= v <= 50):
            print("max_radio must be between 1 and 50")
            return
        MAX_RESULTS_RADIO = v
        _save_config()
        print(f"{Tertiary}Max radio tracks changed to {v}{Reset}")
    else:
        aliases = ", ".join(f"{k}->{v}" for k, v in _TARGET_ALIASES.items())
        print(
            f"Unknown target '{target}'. Use: primary, sec, ter, display ({aliases}){Reset}"
        )


_load_config()

FFMPEG = _detect_ffmpeg()
_save_config()
