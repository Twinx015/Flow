import json
import os
import pathlib
import re
import shutil
import signal as _signal

CONFIG_FILE = pathlib.Path.home() / ".flow/config.json"

SIG_STOP = _signal.SIGUSR1
SIG_NEXT = _signal.SIGUSR2
SIG_PREV = _signal.SIGRTMIN + 2


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
BarHeight = 40
BarSpacing = 1
BarChar = "\u2588"
Sensitivity = 1.0

####### Be carefull this will make everything print on screen including links title view and all things ###
DEV_MODE = False
###########################################################################################################

FFMPEG = False
FORMAT = "webm"
_VALID_FORMATS = {"opus", "m4a", "mp3", "webm"}

AD_SKIP = True
SPONSOR_CATEGORIES = ["sponsor", "selfpromo", "intro", "outro"]
DOWN_ON_LIKE = True


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
        ("flask", _try_import("flask")),
        ("numpy", _try_import("numpy")),
        ("sounddevice", _try_import("sounddevice")),
        ("ytmusicapi", _try_import("ytmusicapi")),
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
    skip_dirs = {"downloads", "playlist", "playlists", "LOGS"}
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


_FILLER_WORDS = {
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
}

IGNORE_FILE = pathlib.Path.home() / ".flow/ignore.txt"


def _load_filler_words():
    if not IGNORE_FILE.exists():
        IGNORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        header = (
            "# Add one word or phrase per line. Words listed here are"
            " removed from song titles.\n"
            "# Lines starting with '#' are ignored.\n"
        )
        IGNORE_FILE.write_text(header + "\n".join(sorted(_FILLER_WORDS)) + "\n")
    words = set()
    for line in IGNORE_FILE.read_text().splitlines():
        word = line.strip().lower()
        if word and not word.startswith("#"):
            words.add(word)
    return words


FILLER_WORDS = _load_filler_words()


def _truncate_title(title):
    words = [word for word in title.split() if word.lower() not in FILLER_WORDS]
    return " ".join(words[:6]) + "..." if len(words) > 6 else " ".join(words)


def _load_config():
    global \
        Primary, \
        Secondary, \
        Tertiary, \
        Display, \
        BarWidth, \
        BarHeight, \
        BarSpacing, \
        BarChar, \
        Sensitivity, \
        DEV_MODE, \
        FFMPEG, \
        FORMAT, \
        AD_SKIP, \
        SPONSOR_CATEGORIES, \
        DOWN_ON_LIKE, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO, \
        ImgSize, \
        ImgColors
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
            and 10 <= data["bar_height"] <= 90
        ):
            BarHeight = data["bar_height"]
        if (
            "bar_spacing" in data
            and isinstance(data["bar_spacing"], int)
            and 0 <= data["bar_spacing"] <= 4
        ):
            BarSpacing = data["bar_spacing"]
        elif "bar_spacing" in data and data["bar_spacing"] in _BAR_SPACING:
            BarSpacing = data["bar_spacing"]
        if (
            "sensitivity" in data
            and isinstance(data["sensitivity"], (int, float))
            and 0.5 <= data["sensitivity"] <= 5.0
        ):
            Sensitivity = data["sensitivity"]
        if "bar_char" in data and isinstance(data["bar_char"], str) and data["bar_char"]:
            BarChar = data["bar_char"][:1]
        if "dev" in data and isinstance(data["dev"], bool):
            DEV_MODE = data["dev"]
        if "ffmpeg" in data and isinstance(data["ffmpeg"], bool):
            FFMPEG = data["ffmpeg"]
        if "ad_skip" in data and isinstance(data["ad_skip"], bool):
            AD_SKIP = data["ad_skip"]
        if "sponsor_categories" in data and isinstance(data["sponsor_categories"], list):
            cats = [c for c in data["sponsor_categories"] if isinstance(c, str)]
            if cats:
                SPONSOR_CATEGORIES = cats
        if "down_on_like" in data and isinstance(data["down_on_like"], bool):
            DOWN_ON_LIKE = data["down_on_like"]
        if "format" in data and data["format"] in _VALID_FORMATS:
            FORMAT = data["format"]
        if "max_search" in data and isinstance(data["max_search"], int) and 1 <= data["max_search"] <= 20:
            MAX_SEARCH_RESULTS = data["max_search"]
        if "max_radio" in data and isinstance(data["max_radio"], int) and 1 <= data["max_radio"] <= 50:
            MAX_RESULTS_RADIO = data["max_radio"]
        if "img_size" in data and isinstance(data["img_size"], int) and 3 <= data["img_size"] <= 20:
            ImgSize = data["img_size"]
        if "img_colors" in data and isinstance(data["img_colors"], int) and 1 <= data["img_colors"] <= 3:
            ImgColors = data["img_colors"]
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
        "bar_char": BarChar,
        "sensitivity": Sensitivity,
        "dev": DEV_MODE,
        "ffmpeg": FFMPEG,
        "ad_skip": AD_SKIP,
        "sponsor_categories": SPONSOR_CATEGORIES,
        "down_on_like": DOWN_ON_LIKE,
        "format": FORMAT,
        "max_search": MAX_SEARCH_RESULTS,
        "max_radio": MAX_RESULTS_RADIO,
        "img_size": ImgSize,
        "img_colors": ImgColors,
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

MAX_RESULTS_RADIO = 35
MAX_SEARCH_RESULTS = 5

ImgSize = 6
ImgColors = 1

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


_BAR_CHARS = {"dot": "\u25aa", "block": "\u2588", "circle": "\u2688"}


def _apply_color(which, value):
    global Primary, Secondary, Tertiary
    color = _COLORS.get(value)
    if color is None:
        return f"Unknown color '{value}'. Use 'config -h' to see available colors."
    if which == "primary":
        Primary = _COLORS[value]
    elif which == "secondary":
        Secondary = _COLORS[value]
    else:
        Tertiary = _COLORS[value]
    _save_config()
    code = {"primary": Primary, "secondary": Secondary, "tertiary": Tertiary}[which]
    return f"{code}{which.capitalize()} color changed to {value}{Reset}"


def _apply_display(value):
    global Display
    if value not in _DISPLAY_MODES:
        return f"Unknown display mode '{value}'. Options: none, bars, lyrics"
    Display = value
    _save_config()
    return f"{Tertiary}Display mode changed to {value}{Reset}"


def _apply_bar_width(v):
    global BarWidth
    BarWidth = v
    _save_config()
    return f"{Tertiary}Bar width changed to {v}{Reset}"


def _apply_bar_height(v):
    global BarHeight
    BarHeight = v
    _save_config()
    return f"{Tertiary}Bar height changed to {v}{Reset}"


def _apply_bar_spacing(v):
    global BarSpacing
    BarSpacing = v
    _save_config()
    return f"{Tertiary}Bar spacing changed to {v}{Reset}"


def _apply_bar_char(v):
    global BarChar
    char = _BAR_CHARS.get(str(v).lower(), v)
    BarChar = str(char)[:1]
    _save_config()
    return f"{Tertiary}Bar char changed to {BarChar}{Reset}"


def _apply_sensitivity(v):
    global Sensitivity
    Sensitivity = v
    _save_config()
    return f"{Tertiary}Sensitivity changed to {v}{Reset}"


def _apply_format(value):
    if not set_format(value):
        if value not in _VALID_FORMATS:
            return f"Unknown format '{value}'. Options: opus, m4a, mp3, webm"
        return (
            f"{YELLOW}ffmpeg not found. Install ffmpeg to use {value} format.{Reset}\n"
            f"{Grey}  Keeping current format: {FORMAT}{Reset}"
        )
    return f"{Tertiary}Default download format changed to {value}{Reset}"


def _apply_int(attr, value, lo, hi, ok_msg):
    global BarWidth, BarHeight, BarSpacing, MAX_SEARCH_RESULTS, MAX_RESULTS_RADIO, ImgSize, ImgColors
    try:
        v = int(value)
    except ValueError:
        return f"{attr} must be an integer ({lo}-{hi})"
    if not (lo <= v <= hi):
        return f"{attr} must be between {lo} and {hi}"
    globals()[attr] = v
    _save_config()
    return f"{Tertiary}{ok_msg} to {v}{Reset}"


def cmd_config(extra: list[str], args=None):
    global \
        Primary, \
        Secondary, \
        Tertiary, \
        Display, \
        BarWidth, \
        BarHeight, \
        BarSpacing, \
        BarChar, \
        Sensitivity, \
        DEV_MODE, \
        FORMAT, \
        AD_SKIP, \
        DOWN_ON_LIKE, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO, \
        ImgSize, \
        ImgColors
    if extra and (extra[0] in ("help", "-h")):
        print(f"{Tertiary}Available targets:{Reset}")
        print(f"  {Primary}primary{Reset}   (aliases: pri)")
        print(f"  {Secondary}secondary{Reset} (aliases: sec)")
        print(f"  {Tertiary}tertiary{Reset}  (aliases: ter)")
        print(f"  {Grey}display{Reset}    (none, bars, lyrics)")
        print(f"  {Grey}barwidth{Reset}   (4-80, current: {BarWidth})")
        print(f"  {Grey}barheight{Reset}  (10-90, current: {BarHeight})")
        print(f"  {Grey}barspacing{Reset} (0-4, min, fit, max — current: {BarSpacing})")
        print(f"  {Grey}barchar{Reset}    (dot, block, circle, or any single char — current: {BarChar})")
        print(f"  {Grey}sensitivity{Reset} (0.5-5.0, current: {Sensitivity})")
        print(f"  {Grey}format{Reset}     (opus, m4a, mp3, webm — current: {FORMAT})")
        print(f"  {Grey}ad_skip{Reset}     (true/false — SponsorBlock segment skipping, current: {AD_SKIP})")
        print(f"  {Grey}down_on_like{Reset} (true/false — auto-download when liking online, current: {DOWN_ON_LIKE})")
        print(f"  {Grey}sponsor_categories{Reset} (in config file: sponsor, selfpromo, intro, outro, ...)")
        print(f"  {Grey}max_search{Reset} (1-20, current: {MAX_SEARCH_RESULTS})")
        print(f"  {Grey}max_radio{Reset}  (1-50, current: {MAX_RESULTS_RADIO})")
        print(f"  {Grey}img_size{Reset}   (3-20, status card image height in rows, current: {ImgSize})")
        print(f"  {Grey}img_colors{Reset} (1-3, number of colors+swatches shown, current: {ImgColors})")
        print(f"\n{Tertiary}Available colors:{Reset}")
        for name, code in _COLORS.items():
            print(f"  {code}{name}{Reset}")
        print(f"\n{Grey}Config file: {CONFIG_FILE}{Reset}")
        return
    if not extra:
        _interactive_config()
        return
    if len(extra) < 2:
        print(f"Usage: config <target> <value>{Reset}")
        return
    target = _TARGET_ALIASES.get(extra[0].lower(), extra[0].lower())
    value = extra[1].lower()

    def emit(msg):
        print(msg)

    if target == "primary":
        emit(_apply_color("primary", value))
    elif target == "secondary":
        emit(_apply_color("secondary", value))
    elif target == "tertiary":
        emit(_apply_color("tertiary", value))
    elif target == "display":
        emit(_apply_display(value))
    elif target in ("barwidth", "width"):
        print(_apply_int("BarWidth", value, 4, 80, "Bar width changed"))
    elif target in ("barheight", "height"):
        print(_apply_int("BarHeight", value, 10, 90, "Bar height changed"))
    elif target in ("barspacing", "spacing"):
        if value in _BAR_SPACING:
            print(_apply_bar_spacing(value))
        else:
            print(_apply_int("BarSpacing", value, 0, 4, "Bar spacing changed"))
    elif target == "sensitivity":
        try:
            v = float(value)
        except ValueError:
            print("sensitivity must be a number (0.5-5.0)")
            return
        if not (0.5 <= v <= 5.0):
            print("sensitivity must be between 0.5 and 5.0")
            return
        print(_apply_sensitivity(v))
    elif target in ("barchar", "bar_char"):
        print(_apply_bar_char(value))
    elif target == "dev":
        if value not in ("true", "false"):
            print("Usage: config dev true/false")
            return
        DEV_MODE = value == "true"
        _save_config()
        print(f"{Tertiary}Dev mode set to {DEV_MODE}{Reset}")
    elif target == "format":
        print(_apply_format(value))
    elif target == "ad_skip":
        if value not in ("true", "false"):
            print("Usage: config ad_skip true/false")
            return
        AD_SKIP = value == "true"
        _save_config()
        print(f"{Tertiary}Sponsor segment skipping set to {AD_SKIP}{Reset}")
    elif target in ("down_on_like", "downlike"):
        if value not in ("true", "false"):
            print("Usage: config down_on_like true/false")
            return
        DOWN_ON_LIKE = value == "true"
        _save_config()
        print(f"{Tertiary}Auto-download on like set to {DOWN_ON_LIKE}{Reset}")
    elif target in ("max_search", "maxresults"):
        print(_apply_int("MAX_SEARCH_RESULTS", value, 1, 20, "Max search results changed"))
    elif target in ("max_radio", "maxradio"):
        print(_apply_int("MAX_RESULTS_RADIO", value, 1, 50, "Max radio tracks changed"))
    elif target in ("img_size", "imgsize"):
        print(_apply_int("ImgSize", value, 3, 20, "Status image size changed"))
    elif target in ("img_colors", "imgcolors"):
        print(_apply_int("ImgColors", value, 1, 3, "Status color swatches changed"))
    else:
        aliases = ", ".join(f"{k}->{v}" for k, v in _TARGET_ALIASES.items())
        print(
            f"Unknown target '{target}'. Use: primary, sec, ter, display ({aliases}){Reset}"
        )


def _interactive_config():
    global AD_SKIP, DOWN_ON_LIKE
    try:
        import questionary
        from questionary import Style
    except ImportError:
        print(f"{Primary}Usage: config <target> <value>{Reset}")
        print(f"       config -h{Reset}")
        print(f"{Grey}  (interactive mode requires 'questionary', install with: pip install questionary){Reset}")
        return

    color_names = sorted(_COLORS.keys())
    color_choices = [questionary.Choice(title=n, value=n) for n in color_names]
    py_style = Style(
        [
            ("qmark", "fg:cyan bold"),
            ("question", "fg:cyan bold"),
            ("answer", f"fg:{_cname(Secondary)} bold"),
            ("pointer", f"fg:{_cname(Primary)} bold"),
            ("highlighted", f"fg:{_cname(Primary)} bold"),
            ("selected", f"fg:{_cname(Primary)}"),
            ("separator", f"fg:{_cname(Muted)}"),
            ("instruction", f"fg:{_cname(Tertiary)}"),
            ("text", ""),
        ]
    )

    questions = [
        {
            "type": "select",
            "name": "display",
            "message": "Display mode",
            "choices": ["none", "bars", "lyrics"],
            "default": Display,
        },
        {
            "type": "select",
            "name": "primary",
            "message": "Primary color",
            "choices": color_choices,
            "default": _COLOR_NAMES.get(Primary, "cyan"),
        },
        {
            "type": "select",
            "name": "secondary",
            "message": "Secondary color",
            "choices": color_choices,
            "default": _COLOR_NAMES.get(Secondary, "purple"),
        },
        {
            "type": "select",
            "name": "tertiary",
            "message": "Tertiary color",
            "choices": color_choices,
            "default": _COLOR_NAMES.get(Tertiary, "blue"),
        },
        {
            "type": "select",
            "name": "format",
            "message": "Default download format",
            "choices": sorted(_VALID_FORMATS),
            "default": FORMAT if FORMAT in _VALID_FORMATS else "webm",
        },
        {
            "type": "text",
            "name": "bar_width",
            "message": "Bar width (4-80)",
            "default": str(BarWidth),
            "when": lambda a: a["display"] == "bars",
        },
        {
            "type": "text",
            "name": "bar_height",
            "message": "Bar height (10-90)",
            "default": str(BarHeight),
            "when": lambda a: a["display"] == "bars",
        },
        {
            "type": "select",
            "name": "bar_spacing",
            "message": "Bar spacing",
            "choices": ["min", "fit", "max", "0", "1", "2", "3", "4"],
            "default": str(BarSpacing),
            "when": lambda a: a["display"] == "bars",
        },
        {
            "type": "text",
            "name": "bar_char",
            "message": "Bar char (dot/block/circle or single char)",
            "default": _BC_NAME(BarChar),
            "when": lambda a: a["display"] == "bars",
        },
        {
            "type": "text",
            "name": "sensitivity",
            "message": "Sensitivity (0.5-5.0)",
            "default": str(Sensitivity),
            "when": lambda a: a["display"] == "bars",
        },
        {
            "type": "confirm",
            "name": "ad_skip",
            "message": "Sponsor segment skipping (ad skip)",
            "default": AD_SKIP,
        },
        {
            "type": "confirm",
            "name": "down_on_like",
            "message": "Auto-download when liking online",
            "default": DOWN_ON_LIKE,
        },
        {
            "type": "text",
            "name": "max_search",
            "message": "Max search results (1-20)",
            "default": str(MAX_SEARCH_RESULTS),
        },
        {
            "type": "text",
            "name": "max_radio",
            "message": "Max radio tracks (1-50)",
            "default": str(MAX_RESULTS_RADIO),
        },
        {
            "type": "text",
            "name": "img_size",
            "message": "Status image size in rows (3-20)",
            "default": str(ImgSize),
        },
        {
            "type": "text",
            "name": "img_colors",
            "message": "Status image color swatches (1-3)",
            "default": str(ImgColors),
        },
    ]

    try:
        answers = questionary.prompt(questions, style=py_style)
    except KeyboardInterrupt:
        print(f"\n{Grey}Config setup cancelled.{Reset}")
        return
    if not answers:
        print(f"\n{Grey}Config setup cancelled.{Reset}")
        return

    print(_apply_display(answers["display"]))
    print(_apply_color("primary", answers["primary"]))
    print(_apply_color("secondary", answers["secondary"]))
    print(_apply_color("tertiary", answers["tertiary"]))

    bar_width_v = int(answers["bar_width"]) if answers["bar_width"].strip() and answers["display"] == "bars" else None
    if bar_width_v is not None and 4 <= bar_width_v <= 80:
        print(_apply_bar_width(bar_width_v))
    bar_height_v = int(answers["bar_height"]) if answers["bar_height"].strip() and answers["display"] == "bars" else None
    if bar_height_v is not None and 10 <= bar_height_v <= 90:
        print(_apply_bar_height(bar_height_v))
    if answers["display"] == "bars":
        if str(answers["bar_spacing"]) in _BAR_SPACING:
            print(_apply_bar_spacing(answers["bar_spacing"]))
        else:
            print(_apply_bar_spacing(int(answers["bar_spacing"])))
        print(_apply_bar_char(answers["bar_char"]))
        sens_v = float(answers["sensitivity"]) if answers["sensitivity"].strip() else None
        if sens_v is not None and 0.5 <= sens_v <= 5.0:
            print(_apply_sensitivity(sens_v))

    print(_apply_format(answers["format"]))
    print(_apply_int("MAX_SEARCH_RESULTS", answers["max_search"], 1, 20, "Max search results changed"))
    print(_apply_int("MAX_RESULTS_RADIO", answers["max_radio"], 1, 50, "Max radio tracks changed"))
    print(_apply_int("ImgSize", answers["img_size"], 3, 20, "Status image size changed"))
    print(_apply_int("ImgColors", answers["img_colors"], 1, 3, "Status color swatches changed"))
    AD_SKIP = answers["ad_skip"]
    DOWN_ON_LIKE = answers["down_on_like"]
    _save_config()
    print(f"{Tertiary}Ad skip set to {AD_SKIP}{Reset}")
    print(f"{Tertiary}Auto-download on like set to {DOWN_ON_LIKE}{Reset}")
    print(f"\n{Grey}Config saved.{Reset}")


def _cname(ansi_code):
    return _COLOR_NAMES.get(ansi_code, "white")


def _BC_NAME(char):
    for name, code in _BAR_CHARS.items():
        if code == char:
            return name
    return char


_load_config()

FFMPEG = _detect_ffmpeg()
