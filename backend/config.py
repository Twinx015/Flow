import json
import os
import pathlib
import re
import shutil
import signal as _signal
import subprocess
import sys

CONFIG_FILE = pathlib.Path.home() / ".flow/config.json"
COLOR_FILE = pathlib.Path.home() / ".flow/color.json"

SIG_STOP = getattr(_signal, "SIGUSR1", None)
SIG_NEXT = getattr(_signal, "SIGUSR2", None)
if hasattr(_signal, "SIGRTMIN"):
    SIG_PREV = _signal.SIGRTMIN + 2
    SIG_SEEK_FWD = _signal.SIGRTMIN + 3
    SIG_SEEK_BWD = _signal.SIGRTMIN + 4
    SIG_REPEAT = _signal.SIGRTMIN + 5
    SIG_SHUFFLE = _signal.SIGRTMIN + 6
    SIG_STOP_ALL = _signal.SIGRTMIN + 7
else:
    SIG_PREV = SIG_SEEK_FWD = SIG_SEEK_BWD = None
    SIG_REPEAT = SIG_SHUFFLE = SIG_STOP_ALL = None


_FLAG_MAP = {"-bg": "bg", "-s": "shuffle", "-d": "download", "-m": "multi"}
_SHORT_FLAGS = {"d": "download", "s": "shuffle", "m": "multi"}


def merge_flags(extra: list[str], args) -> tuple[list[str], object]:
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
        elif item == "-f":
            if i + 1 < len(extra):
                setattr(args, "format", extra[i + 1])
                i += 1
            else:
                print(f"Unknown flag: {item}")
        elif item in _FLAG_MAP:
            setattr(args, _FLAG_MAP[item], True)
        elif (
            item.startswith("-")
            and not item.startswith("--")
            and len(item) > 2
            and all(ch in _SHORT_FLAGS for ch in item[1:])
        ):
            for ch in item[1:]:
                setattr(args, _SHORT_FLAGS[ch], True)
        elif item.startswith("-"):
            print(f"Unknown flag: {item}")
        else:
            rest.append(item)
        i += 1
    return rest, args


try:
    from rich.color import ANSI_COLOR_NAMES
    from rich.console import Console as _RichConsole
    from rich.style import Style as _RichStyle

    _FORCE = _RichConsole(
        force_terminal=True, color_system="truecolor", legacy_windows=False
    )
    _HAS_RICH = True
except Exception:
    ANSI_COLOR_NAMES = {}
    _FORCE = None
    _RichStyle = None
    _HAS_RICH = False


def _norm_style(value):
    """Collapse whitespace inside rgb()/hsl() (rich's parser wants rgb(1,2,3))."""
    return re.sub(
        r"(rgb|hsl)\(([^)]*)\)",
        lambda m: f"{m.group(1)}({''.join(m.group(2).split())})",
        str(value).strip(),
    )


def _sgr(style):
    """Render a rich style string to its ANSI SGR prefix."""
    if not _HAS_RICH:
        return ""
    try:
        with _FORCE.capture() as cap:
            _FORCE.print("\u2593", style=_norm_style(style), end="")
        out = cap.get()
        if out.endswith("\x1b[0m"):
            out = out[:-4]
        if out.endswith("\u2593"):
            out = out[:-1]
        return out
    except Exception:
        return ""


def _valid_style(value):
    """True when `value` is a parseable rich style (named color, #hex, rgb(), ...)."""
    if not _HAS_RICH:
        return str(value).lower() in (
            "red",
            "green",
            "yellow",
            "blue",
            "purple",
            "cyan",
            "grey",
            "white",
            "black",
            "orange",
            "pink",
        )
    try:
        _RichStyle.parse(_norm_style(value))
        return True
    except Exception:
        return False


RICH_COLORS = sorted(ANSI_COLOR_NAMES)

RED = _sgr("red")
GREEN = _sgr("green")
BROWN = _sgr("dark_goldenrod")
BLUE = _sgr("blue")
PURPLE = _sgr("purple")
CYAN = _sgr("cyan")
GREY = _sgr("grey62")
YELLOW = _sgr("bold yellow")
WHITE = _sgr("bold white")
MAROON = _sgr("red3")
OLIVE = _sgr("yellow4")
DARK_KHAKI = _sgr("dark_khaki")
GOLD = _sgr("gold1")
TAN = _sgr("tan")
SALMON = _sgr("salmon1")
CORAL = _sgr("orange_red1")
HOT_PINK = _sgr("hot_pink")
VIOLET = _sgr("violet")
DEEP_PURPLE = _sgr("purple3")
TEAL = _sgr("dark_cyan")
SKY_BLUE = _sgr("light_sky_blue1")
STEEL_BLUE = _sgr("steel_blue")
NAVY = _sgr("navy_blue")
INDIGO = _sgr("purple4")
ORANGE = _sgr("orange1")
PINK = _sgr("pink1")
LIME = _sgr("spring_green3")
Reset = "\033[0m"

_TARGET_ALIASES = {
    "pri": "primary",
    "sec": "secondary",
    "ter": "tertiary",
    "spin": "spinner",
    "richcols": "progress_columns",
    "rich_columns": "progress_columns",
    "progtype": "progress_type",
    "richspin": "rich_spinner",
    "rich_spin": "rich_spinner",
    "customcolor": "custom_color",
    "cc": "custom_color",
    "refresh": "reload",
    "rr": "reload",
    "clearcolors": "clear_colors",
    "ccol": "clear_colors",
    "pri_color": "primary_color",
    "pricolor": "primary_color",
    "sec_color": "secondary_color",
    "seccolor": "secondary_color",
    "ter_color": "tertiary_color",
    "tercolor": "tertiary_color",
}
_TARGETS = {
    "primary",
    "secondary",
    "tertiary",
    "custom_color",
    "primary_color",
    "secondary_color",
    "tertiary_color",
    "reload",
    "clear_colors",
    "display",
    "progress_columns",
    "progress_type",
    "rich_spinner",
}
_DISPLAY_MODES = {"none", "bars", "lyrics", "progress", "rich"}
_BAR_SPACING = {"min", "fit", "max"}

_STYLE = {"primary": "cyan", "secondary": "purple", "tertiary": "blue"}

_CUSTOM_COLOR_KEYS = (
    ("primary_color", "primary"),
    ("secondary_color", "secondary"),
    ("tertiary_color", "tertiary"),
)
_CUSTOM = {"primary": None, "secondary": None, "tertiary": None}
_custom_mtime = None
_color_mtime = None


_LIVE_NAMESPACES = []
_ALIAS_SOURCES = {
    "P": "Primary",
    "S": "Secondary",
    "T": "Tertiary",
    "M": "Muted",
    "G": "GREY",
    "E": "RED",
    "R": "Reset",
}


def keep_live(ns):
    """Register a module globals() so its P/S/T/… color aliases re-bind on every _render()."""
    if ns not in _LIVE_NAMESPACES:
        _LIVE_NAMESPACES.append(ns)


def _sync_aliases():
    """Re-bind the snapshot color aliases (P, S, T, …) in all registered namespaces."""
    for ns in _LIVE_NAMESPACES:
        for alias, source in _ALIAS_SOURCES.items():
            if alias in ns:
                ns[alias] = globals()[source]


def _render():
    """Recompute Primary/Secondary/Tertiary ANSI from the chosen rich styles."""
    global Primary, Secondary, Tertiary
    Primary = _sgr(_STYLE["primary"]) or CYAN
    Secondary = _sgr(_STYLE["secondary"]) or PURPLE
    Tertiary = _sgr(_STYLE["tertiary"]) or BLUE
    if CustomColor:
        for slot, fallback in (
            ("primary", Primary),
            ("secondary", Secondary),
            ("tertiary", Tertiary),
        ):
            style = _sgr(_CUSTOM[slot]) if _CUSTOM[slot] else None
            if slot == "primary":
                Primary = style or fallback
            elif slot == "secondary":
                Secondary = style or fallback
            else:
                Tertiary = style or fallback
    _sync_aliases()


CustomColor = False
Primary = _sgr("cyan")
Secondary = _sgr("purple")
Tertiary = _sgr("blue")
Muted = GREY
Display = "bars"
Banner = "classic"
_BANNER_MODES = {"classic", "random"}
BarWidth = 20
BarHeight = 40
BarSpacing = 1
BarChar = "\u2588"
ProgChar = "\u2588"
ProgCharEm = "\u2591"
Sensitivity = 1.0
SPINNER = "|/-\\"
RichSpinner = "dots"
ProgressType = "default"
ProgressColumns = ["bar", "percentage", "time_remaining"]

_PROGRESS_TYPES = {
    "default": ["bar", "percentage", "time_remaining"],
    "download": ["download", "file_size", "total_size", "transfer_speed"],
    "pulse": ["spinner"],
}

_RICH_COLUMN_NAMES = (
    "bar",
    "download",
    "file_size",
    "m_of_n",
    "percentage",
    "spinner",
    "task",
    "time_elapsed",
    "time_remaining",
    "total_size",
    "transfer_speed",
)

THEMES = {
    "ocean": ("cyan", "purple", "blue"),
    "sunset": ("orange1", "pink1", "gold1"),
    "forest": ("green", "spring_green3", "dark_cyan"),
    "fire": ("red", "orange1", "gold1"),
    "mono": ("grey62", "white", "red3"),
    "royal": ("purple4", "violet", "light_sky_blue1"),
}

####### Be carefull this will make everything print on screen including links title view and all things ###
DEV_MODE = False
###########################################################################################################

FFMPEG = False
_ffmpeg_configured = False  # True when the user explicitly set "ffmpeg" in config
FORMAT = "webm"
_VALID_FORMATS = {"opus", "m4a", "mp3", "webm"}

AD_SKIP = True
SPONSOR_CATEGORIES = ["sponsor", "selfpromo", "intro", "outro"]
DOWN_ON_LIKE = True
NOTIFY = True


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
    # Log to new logger as well
    try:
        from backend import logger

        logger.debug("system", "dev_print", label, {"data": data} if data is not None else None)
    except Exception:
        pass

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


AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".ogg",
    ".opus",
    ".wma",
    ".aac",
    ".webm",
}

_EXPORT_TAGS = ("title", "artist", "album")

_ART_EXTENSIONS = {".mp3", ".m4a", ".flac", ".wav"}


def export_dest(extra: list[str]) -> str | None:
    """The ``-p PATH`` destination in a command's extra arguments, if any.

    ``None`` means "no path given" — the caller then falls back to ~/Downloads.
    """
    rest = list(extra)
    dest = None
    for flag in ("-p", "--path"):
        while flag in rest:
            idx = rest.index(flag)
            rest.pop(idx)
            if idx < len(rest) and not rest[idx].startswith("-"):
                dest = rest.pop(idx)
    if dest is not None:
        return dest
    if any(f in extra for f in ("-p", "--path")):
        print(f"{YELLOW}Path flag needs a directory, e.g. -p ~/Music{Reset}")
    return None


def _safe_filename(name: str) -> str:
    """Strip separators and control characters so a title can be a file name."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip(" .")
    return cleaned[:120].strip(" .") or "song"


def _export_sources() -> list:
    from backend import library

    if not DOWNLOAD_DIR.exists():
        return []
    try:
        index = library.load()
    except Exception:
        index = {}
    paths = sorted(
        (p for p in DOWNLOAD_DIR.rglob("*") if p.is_file()),
        key=lambda p: (len(p.relative_to(DOWNLOAD_DIR).parts), p.stem.lower()),
    )
    sources, seen = [], set()
    for path in paths:
        if path.suffix.lower() not in AUDIO_EXTENSIONS or path.stem in seen:
            continue
        seen.add(path.stem)
        entry = index.get(path.stem) or {}
        tags = {k: str(entry.get(k) or "").strip() for k in _EXPORT_TAGS}
        tags["title"] = tags["title"] or path.stem
        tags["cover"] = str(entry.get("thumbnail") or library.thumbnail_path(path.stem))
        sources.append((path, tags))
    return sources


def _ffmpeg_exe() -> str | None:
    """Path to ffmpeg, or None when tagging is not possible."""
    if not FFMPEG:
        return None
    return shutil.which("ffmpeg")


def _ffmpeg_tag(exe, src, dst, tags, cover=""):
    """Run one tagging pass, stream-copying the audio. True when it worked."""
    cmd = [exe, "-y", "-loglevel", "error", "-i", str(src)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v"]
    else:
        cmd += ["-map", "0"]
    for key in _EXPORT_TAGS:
        if tags.get(key):
            cmd += ["-metadata", f"{key}={tags[key]}"]
    if cover:
        cmd += ["-c:a", "copy", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(dst)]
    try:
        return subprocess.run(cmd, check=True, capture_output=True).returncode == 0
    except OSError, subprocess.CalledProcessError:
        return False


def _tag_song(path: pathlib.Path, tags: dict) -> bool:

    exe = _ffmpeg_exe()
    if not exe:
        return False
    cover = tags.get("cover") if path.suffix.lower() in _ART_EXTENSIONS else ""
    if cover and not pathlib.Path(cover).exists():
        cover = ""
    tmp = path.parent / f".{path.stem}.flowtag{path.suffix}"
    try:
        ok = _ffmpeg_tag(exe, path, tmp, tags, cover)
        if not ok and cover:
            ok = _ffmpeg_tag(exe, path, tmp, tags)
        if not ok:
            return False
        tmp.replace(path)
        return True
    finally:
        tmp.unlink(missing_ok=True)


def export_flow(dest: str | None = None):
    out_dir = (
        pathlib.Path(dest).expanduser()
        if dest
        else pathlib.Path.home() / "Downloads" / "songs"
    )
    sources = _export_sources()
    if not sources:
        print(f"{Muted}No downloaded songs in {DOWNLOAD_DIR}{Reset}")
        return
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"{RED}Cannot write to {out_dir}: {exc}{Reset}")
        return
    if not _ffmpeg_exe():
        print(f"{YELLOW}ffmpeg not found — copying songs without tags.{Reset}")
        print(f"{GREY}  Install ffmpeg to write title/artist/album into them.{Reset}")

    copied = tagged = 0
    used: set = set()
    for src, tags in sources:
        stem = _safe_filename(tags["title"])
        name = f"{stem}{src.suffix.lower()}"
        count = 2
        while name in used:
            name = f"{stem} ({count}){src.suffix.lower()}"
            count += 1
        used.add(name)
        out = out_dir / name
        try:
            shutil.copy2(src, out)
        except OSError as exc:
            print(f"{RED}  {src.name}: {exc}{Reset}")
            continue
        copied += 1
        if _tag_song(out, tags):
            tagged += 1
        print(f"  {Primary}{out.name}{Reset} {Muted}<- {src.name}{Reset}")
    line = f"Exported {copied} song{'' if copied == 1 else 's'} to {out_dir}"
    print(f"{GREEN}{line}{Reset} {GREY}({tagged} tagged){Reset}")


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
    "lyrical",
}

MAX_WORDS = 6
IGNORE_FILE = pathlib.Path.home() / ".flow/ignore.txt"
_APOSTROPHES = re.compile(r"['’`]")
_NON_WORD = re.compile(r"[^\w\s]|_")
_SPACES = re.compile(r"\s+")
_DASH = re.compile(r"\s+[-–—]\s+")
_PIPE = re.compile(r"\s*[|｜ǀ•·]\s*")


def _normalize(text):
    """Drop apostrophes, turn symbols into spaces, collapse whitespace."""
    text = _APOSTROPHES.sub("", text)
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


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
        line = line.strip()
        if line and not line.startswith("#"):
            phrase = _normalize(line).lower()
            if phrase:
                words.add(phrase)
    return words


def _build_filler_regex(phrases):
    if not phrases:
        return None
    parts = [
        r"\s+".join(re.escape(w) for w in p.split())
        for p in sorted(phrases, key=len, reverse=True)
    ]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


FILLER_WORDS = _load_filler_words()
_FILLER_RE = _build_filler_regex(FILLER_WORDS)


_LEAD = re.compile(r"^[\s|｜ǀ•·:\-–—]+")
_DASH_BEFORE_PIPE = re.compile(r"\s+[-–—]\s*(?=[|｜ǀ•·])")


def _strip_filler(text):
    text = _normalize(text)
    if _FILLER_RE:
        text = _SPACES.sub(" ", _FILLER_RE.sub(" ", text)).strip()
    return text


_TILE_CONTEXTS: dict = {}


def _tile_context():
    """Tile's junk/artist rules plus flow's `~/.flow/ignore.txt` words (cached)."""
    from Tile import (
        DEFAULT_ARTIST_FILE,
        DEFAULT_IGNORE_FILE,
        Context,
        get_context,
    )

    def mtime(path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return -1

    key = (
        str(IGNORE_FILE),
        mtime(IGNORE_FILE),
        str(DEFAULT_IGNORE_FILE),
        mtime(DEFAULT_IGNORE_FILE),
        str(DEFAULT_ARTIST_FILE),
        mtime(DEFAULT_ARTIST_FILE),
    )
    if key not in _TILE_CONTEXTS:
        tile = get_context(DEFAULT_IGNORE_FILE, DEFAULT_ARTIST_FILE)
        flow = get_context(IGNORE_FILE, DEFAULT_ARTIST_FILE)
        _TILE_CONTEXTS.clear()
        _TILE_CONTEXTS[key] = Context(
            strip_words=tile.strip_words | flow.strip_words,
            soft_words=tile.soft_words | flow.soft_words,
            phrases=tile.phrases | flow.phrases,
            artists=tile.artists,
            labels=tile.labels,
        )
    return _TILE_CONTEXTS[key]


def extract_song(title):
    """The song name from a raw title, parsed by the Tile package."""
    from Tile import parse_title

    return parse_title(title or "", _tile_context())["title"]


def _truncate_title(title):
    """Tile-clean plain-YouTube titles; YouTube Music titles are kept as-is."""
    if SearchSource != "youtube":
        return title or ""
    words = extract_song(title).split()
    result = " ".join(words[:MAX_WORDS])
    return result + "..." if len(words) > MAX_WORDS else result


def _load_colors():
    """Read the three custom colors from ~/.flow/color.json into `_CUSTOM`."""
    global _color_mtime
    if not COLOR_FILE.exists():
        return
    try:
        data = json.loads(COLOR_FILE.read_text())
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for key, slot in _CUSTOM_COLOR_KEYS:
        val = data.get(key)
        val = str(val).strip() if isinstance(val, str) else ""
        _CUSTOM[slot] = val if val and _valid_style(val) else None
    try:
        _color_mtime = COLOR_FILE.stat().st_mtime_ns
    except OSError:
        pass


def _save_colors():
    """Write the three custom colors back to ~/.flow/color.json (merge mode)."""
    global _color_mtime
    COLOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if COLOR_FILE.exists():
        try:
            loaded = json.loads(COLOR_FILE.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass  # unreadable file gets rewritten with just our keys
    for key, slot in _CUSTOM_COLOR_KEYS:
        data[key] = _CUSTOM[slot] or ""
    COLOR_FILE.write_text(json.dumps(data, indent=2))
    try:
        _color_mtime = COLOR_FILE.stat().st_mtime_ns
    except OSError:
        pass


def _apply_reload():
    """`config reload` — force re-read config.json + color.json right now."""
    _load_config()
    return (
        f"{Tertiary}Colors reloaded from disk{Reset} {Muted}"
        f"({'custom_color' if CustomColor else 'custom_color is off'}){Reset}"
    )


def _apply_clear_colors():
    """`config clear_colors` — drop all custom overrides, back to the theme."""
    for slot in _CUSTOM:
        _CUSTOM[slot] = None
    _render()
    _save_colors()
    if CustomColor:
        return (
            f"{Tertiary}Custom colors cleared{Reset} {Muted}"
            f"— every slot uses the theme now (color.json emptied){Reset}"
        )
    return f"{Tertiary}Custom colors cleared{Reset} {Muted}— color.json emptied{Reset}"


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
        ProgChar, \
        ProgCharEm, \
        Sensitivity, \
        SPINNER, \
        RichSpinner, \
        ProgressType, \
        DEV_MODE, \
        FFMPEG, \
        _ffmpeg_configured, \
        FORMAT, \
        AD_SKIP, \
        SPONSOR_CATEGORIES, \
        DOWN_ON_LIKE, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO, \
        SearchSource, \
        NOTIFY, \
        ScrobbleBackend, \
        LastfmUsername, \
        ListenbrainzUsername, \
        ProgressColumns, \
        CustomColor, \
        Banner
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text())
        if "primary" in data and _valid_style(data["primary"]):
            _STYLE["primary"] = str(data["primary"])
        if "secondary" in data and _valid_style(data["secondary"]):
            _STYLE["secondary"] = str(data["secondary"])
        if "tertiary" in data and _valid_style(data["tertiary"]):
            _STYLE["tertiary"] = str(data["tertiary"])
        if "custom_color" in data and isinstance(data["custom_color"], bool):
            CustomColor = data["custom_color"]
        try:
            global _custom_mtime
            _custom_mtime = CONFIG_FILE.stat().st_mtime_ns
        except OSError:
            pass
        _load_colors()
        _render()
        if "display" in data and data["display"] in _DISPLAY_MODES:
            Display = data["display"]
        if data.get("banner") in _BANNER_MODES:
            Banner = data["banner"]
        if "progress_columns" in data and isinstance(data["progress_columns"], list):
            cols = [
                c
                for c in data["progress_columns"]
                if isinstance(c, str) and c in _RICH_COLUMN_NAMES
            ]
            if cols:
                ProgressColumns = cols
        if "progress_type" in data and data["progress_type"] in _PROGRESS_TYPES:
            ProgressType = data["progress_type"]
            ProgressColumns = list(_PROGRESS_TYPES[ProgressType])
        elif "progress_type" in data and data["progress_type"] == "custom":
            ProgressType = "custom"
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
        if (
            "bar_char" in data
            and isinstance(data["bar_char"], str)
            and data["bar_char"]
        ):
            BarChar = data["bar_char"][:1]
        if (
            "prog_char" in data
            and isinstance(data["prog_char"], str)
            and data["prog_char"]
        ):
            ProgChar = data["prog_char"][:1]
        if (
            "prog_char_em" in data
            and isinstance(data["prog_char_em"], str)
            and data["prog_char_em"]
        ):
            ProgCharEm = data["prog_char_em"][:1]
        if (
            "spinner" in data
            and isinstance(data["spinner"], str)
            and 2 <= len(data["spinner"]) <= 16
        ):
            SPINNER = data["spinner"]
        if (
            "rich_spinner" in data
            and isinstance(data["rich_spinner"], str)
            and data["rich_spinner"]
        ):
            RichSpinner = data["rich_spinner"][:16]
        if "dev" in data and isinstance(data["dev"], bool):
            DEV_MODE = data["dev"]
        if "ffmpeg" in data and isinstance(data["ffmpeg"], bool):
            FFMPEG = data["ffmpeg"]
            _ffmpeg_configured = True
        if "ad_skip" in data and isinstance(data["ad_skip"], bool):
            AD_SKIP = data["ad_skip"]
        if "sponsor_categories" in data and isinstance(
            data["sponsor_categories"], list
        ):
            cats = [c for c in data["sponsor_categories"] if isinstance(c, str)]
            if cats:
                SPONSOR_CATEGORIES = cats
        if "down_on_like" in data and isinstance(data["down_on_like"], bool):
            DOWN_ON_LIKE = data["down_on_like"]
        if "notify" in data and isinstance(data["notify"], bool):
            NOTIFY = data["notify"]
        if "format" in data and data["format"] in _VALID_FORMATS:
            FORMAT = data["format"]
        if (
            "max_search" in data
            and isinstance(data["max_search"], int)
            and 1 <= data["max_search"] <= 20
        ):
            MAX_SEARCH_RESULTS = data["max_search"]
        if (
            "max_radio" in data
            and isinstance(data["max_radio"], int)
            and 1 <= data["max_radio"] <= 50
        ):
            MAX_RESULTS_RADIO = data["max_radio"]
        if data.get("search_source") in ("youtube", "ytmusic"):
            SearchSource = data["search_source"]
        if data.get("scrobble_backend") in ("lastfm", "listenbrainz", ""):
            ScrobbleBackend = data["scrobble_backend"]
        for _ukey, _uglobal in (
            ("lastfm_username", "LastfmUsername"),
            ("listenbrainz_username", "ListenbrainzUsername"),
        ):
            if isinstance(data.get(_ukey), str):
                globals()[_uglobal] = data[_ukey].strip()
    except (json.JSONDecodeError, OSError):
        pass


def _save_config():
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "primary": _STYLE["primary"],
        "secondary": _STYLE["secondary"],
        "tertiary": _STYLE["tertiary"],
        "custom_color": CustomColor,
        "display": Display,
        "banner": Banner,
        "progress_columns": ProgressColumns,
        "progress_type": ProgressType,
        "bar_width": BarWidth,
        "bar_height": BarHeight,
        "bar_spacing": BarSpacing,
        "bar_char": BarChar,
        "prog_char": ProgChar,
        "prog_char_em": ProgCharEm,
        "sensitivity": Sensitivity,
        "spinner": SPINNER,
        "rich_spinner": RichSpinner,
        "dev": DEV_MODE,
        "ffmpeg": FFMPEG,
        "ad_skip": AD_SKIP,
        "sponsor_categories": SPONSOR_CATEGORIES,
        "down_on_like": DOWN_ON_LIKE,
        "notify": NOTIFY,
        "format": FORMAT,
        "max_search": MAX_SEARCH_RESULTS,
        "max_radio": MAX_RESULTS_RADIO,
        "search_source": SearchSource,
        "scrobble_backend": ScrobbleBackend,
        "lastfm_username": LastfmUsername,
        "listenbrainz_username": ListenbrainzUsername,
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    try:
        global _custom_mtime
        _custom_mtime = CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        pass


def maybe_reload():
    """Hot-reload custom_color (config.json) and the colors (color.json).

    Called from the display loops (and the shell prompt); mtime-stat only,
    so polling costs nothing, and the first sighting of a file also applies
    it (handles color.json being created after flow started).
    """
    global _custom_mtime, _color_mtime, CustomColor
    changed = False
    if CONFIG_FILE.exists():
        try:
            mtime = CONFIG_FILE.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime is not None and (_custom_mtime is None or mtime != _custom_mtime):
            _custom_mtime = mtime
            try:
                data = json.loads(CONFIG_FILE.read_text())
            except Exception:
                data = {}
            if "primary" in data and _valid_style(data["primary"]):
                _STYLE["primary"] = str(data["primary"])
            if "secondary" in data and _valid_style(data["secondary"]):
                _STYLE["secondary"] = str(data["secondary"])
            if "tertiary" in data and _valid_style(data["tertiary"]):
                _STYLE["tertiary"] = str(data["tertiary"])
            CustomColor = bool(data.get("custom_color"))
            _load_colors()
            changed = True
    if COLOR_FILE.exists():
        try:
            mtime = COLOR_FILE.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime is not None and (_color_mtime is None or mtime != _color_mtime):
            _color_mtime = mtime
            _load_colors()
            changed = True
    if changed:
        _render()


DOWNLOAD_DIR = pathlib.Path.home() / ".flow/downloads"

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version

    VERSION = _version("flow-twinx")
except PackageNotFoundError:
    VERSION = "0.8.4"

Mode = "Online"

MAX_RESULTS_RADIO = 35
MAX_SEARCH_RESULTS = 5
SearchSource = "ytmusic"
ScrobbleBackend = ""
LastfmUsername = ""
ListenbrainzUsername = ""

PID_FILE = pathlib.Path.home() / ".flow/vlc.pid"
SEEK_FILE = pathlib.Path.home() / ".flow/seek.txt"
TUI_PID_FILE = pathlib.Path.home() / ".flow/tui.pid"


def write_seek(delta_ms: int):
    SEEK_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEK_FILE.write_text(str(int(delta_ms)))


def read_seek() -> int:
    try:
        return int(SEEK_FILE.read_text().strip())
    except (ValueError, OSError):
        return 0


def clear_seek():
    SEEK_FILE.unlink(missing_ok=True)


def save_pid(pid: int, ctl_port: int | None = None):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid))
    from backend import registry

    registry.register("vlc", pid, ctl_port=ctl_port)


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
    from backend import registry

    registry.unregister("vlc")


def save_tui_pid(pid: int, ctl_port: int | None = None):
    TUI_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUI_PID_FILE.write_text(str(pid))
    from backend import registry

    registry.register("tui", pid, ctl_port=ctl_port)


def read_tui_pid() -> int | None:
    if not TUI_PID_FILE.exists():
        return None
    try:
        return int(TUI_PID_FILE.read_text().strip())
    except ValueError, OSError:
        return None


def clear_tui_pid():
    if TUI_PID_FILE.exists():
        TUI_PID_FILE.unlink()
    from backend import registry

    registry.unregister("tui")


def save_pid_if_free(pid: int, ctl_port: int | None = None) -> bool:
    """Claim the player pid slot unless another live player already holds it."""
    existing = read_pid()
    if existing is not None and existing != pid:
        try:
            import psutil

            if psutil.Process(existing).is_running():
                return False
        except Exception:
            pass
    if ctl_port is not None:
        save_pid(pid, ctl_port=ctl_port)
    else:
        save_pid(pid)
    return True


def clear_pid_if(pid: int):
    """Clear the player pid slot only when it belongs to ``pid``."""
    if read_pid() == pid:
        clear_pid()


def clear_tui_pid_if(pid: int):
    """Clear the TUI pid slot only when it belongs to ``pid``."""
    if read_tui_pid() == pid:
        clear_tui_pid()


def kill_stored():
    from backend import platform

    pid = read_pid()
    if pid is None:
        return False
    platform.kill_pid(pid)
    clear_pid()
    return True


_BAR_CHARS = {"dot": "\u25aa", "block": "\u2588", "circle": "\u2688"}


def _apply_color(which, value):
    if not _valid_style(value):
        return (
            f"Unknown color '{value}'. Any rich style works: a named color, "
            "#hex, rgb(r,g,b), bold/italic."
        )
    _STYLE[which] = str(value)
    _render()
    _save_config()
    code = {"primary": Primary, "secondary": Secondary, "tertiary": Tertiary}[which]
    tail = (
        f" {Muted}(custom_color is on — this only feeds empty slots){Reset}"
        if CustomColor
        else ""
    )
    return f"{code}{which.capitalize()} color changed to {value}{Reset}{tail}"


def _apply_custom_color(value):
    global CustomColor
    v = str(value or "").strip().lower()
    if v in ("true", "on", "yes"):
        CustomColor = True
    elif v in ("false", "off", "no", ""):
        CustomColor = False
    else:
        return "Usage: config custom_color true/false"
    _render()
    _save_config()
    if CustomColor:
        return (
            f"{Primary}Custom colors on{Reset} {Muted}— Primary/Secondary/Tertiary now "
            f"come from primary_color/secondary_color/tertiary_color (falling back to "
            f"the theme for any unset one){Reset}"
        )
    return f"{Tertiary}Custom colors off{Reset}"


def _apply_custom_color_slot(slot, value):
    v = str(value or "").strip()
    if v and not _valid_style(v):
        return (
            f"Unknown color '{v}'. Any rich style works: a named color, "
            "#hex, rgb(r,g,b), bold/italic."
        )
    _CUSTOM[slot] = v or None
    _render()
    _save_colors()
    label = f"{slot}_color set to {v}" if v else f"{slot}_color cleared"
    if not CustomColor:
        return f"{Tertiary}{label}{Reset} {Muted}— enable with config custom_color true{Reset}"
    code = {"primary": Primary, "secondary": Secondary, "tertiary": Tertiary}[slot]
    return f"{code}{label}{Reset}"


def _apply_display(value):
    global Display
    if value not in _DISPLAY_MODES:
        return f"Unknown display mode '{value}'. Options: none, bars, lyrics, progress, rich"
    Display = value
    _save_config()
    return f"{Tertiary}Display mode changed to {value}{Reset}"


def _apply_banner(value):
    global Banner
    name = str(value or "").strip().lower()
    if name not in _BANNER_MODES:
        return f"Unknown banner '{value}'. Options: classic, random"
    Banner = name
    _save_config()
    return f"{Tertiary}Banner changed to {name}{Reset}"


def _apply_progress_columns(value):
    global ProgressColumns, ProgressType
    parts = [p.strip().lower() for p in re.split(r"[,\s]+", str(value)) if p.strip()]
    if not parts or any(p not in _RICH_COLUMN_NAMES for p in parts):
        return (
            f"Unknown progress column(s). Rich options: {', '.join(_RICH_COLUMN_NAMES)}"
        )
    ProgressColumns = parts
    ProgressType = "custom"
    _save_config()
    return f"{Tertiary}Rich progress columns set to {', '.join(parts)}{Reset}"


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


def _apply_prog_char(v):
    global ProgChar
    char = _BAR_CHARS.get(str(v).lower(), v)
    ProgChar = str(char)[:1]
    _save_config()
    return f"{Tertiary}Progress char changed to {ProgChar}{Reset}"


def _apply_prog_char_em(v):
    global ProgCharEm
    char = _BAR_CHARS.get(str(v).lower(), v)
    ProgCharEm = str(char)[:1]
    _save_config()
    return f"{Tertiary}Progress empty char changed to {ProgCharEm}{Reset}"


MIN_BAR = 8


def bar_width(reserved=0, preferred=None):
    preferred = preferred or BarWidth
    cols = shutil.get_terminal_size((80, 24)).columns
    avail = cols - reserved - 1
    if avail < MIN_BAR:
        return 0
    return min(preferred, avail)


def progress_bar(frac, width=None):
    """A block bar filled to `frac` in Primary, remainder muted."""
    if width is None:
        width = bar_width()
    if width <= 0:
        return ""
    frac = max(0.0, min(1.0, float(frac)))
    filled = int(round(frac * width))
    color = Primary if Mode == "Online" else Secondary
    return f"{color}{ProgChar * filled}{Reset}{Muted}{ProgCharEm * (width - filled)}{Reset}"


def render_progress(elapsed, duration, width=None):
    """Draw a live `\\r` progress line for the playing track."""
    duration = max(int(duration or 0), 0)
    elapsed = max(int(elapsed or 0), 0)
    frac = min(elapsed / duration, 1.0) if duration else 0.0
    total = f"{duration // 60}:{duration % 60:02d}" if duration else "--:--"
    now = f"{elapsed // 60}:{elapsed % 60:02d}"
    text = f"{now} / {total}  {int(frac * 100):>3}%"

    reserved = 2 + 2 + len(text)
    if width is None:
        width = bar_width(reserved=reserved)

    cols = shutil.get_terminal_size((80, 24)).columns
    if width > 0:
        line = f"  {progress_bar(frac, width)}  {text}"
    elif len(text) + 2 < cols:
        line = f"  {text}"
    else:
        line = f"{int(frac * 100)}%"  # ultra-narrow fallback

    sys.stdout.write(f"\r\033[2K{line}")
    sys.stdout.flush()


def _apply_sensitivity(v):
    global Sensitivity
    Sensitivity = v
    _save_config()
    return f"{Tertiary}Sensitivity changed to {v}{Reset}"


def _apply_spinner(value):
    global SPINNER
    if not (2 <= len(value) <= 16):
        return "Spinner must be 2-16 characters"
    SPINNER = value
    _save_config()
    return f"{Tertiary}Spinner set to '{value}'{Reset}"


def rich_spinner_names():
    """Every spinner name rich knows (the `python -m rich.spinner` list)."""
    try:
        from rich.spinner import SPINNERS

        return sorted(SPINNERS)
    except Exception:
        return []


def _spinner_choices():
    """Rich spinner picker options: every name plus the custom escape hatch."""
    return rich_spinner_names() + ["Custom…"]


def _apply_rich_spinner(value):
    global RichSpinner
    name = str(value).strip()
    if not (1 <= len(name) <= 16):
        return "Rich spinner must be a name or 1-16 characters"
    RichSpinner = name
    _save_config()
    return f"{Tertiary}Rich spinner set to '{name}'{Reset}"


def _apply_progress_type(value):
    global ProgressType, ProgressColumns
    key = str(value).strip().lower()
    if key == "custom":
        ProgressType = "custom"
        _save_config()
        return f"{Tertiary}Progress type set to custom (edit the columns as you like){Reset}"
    cols = _PROGRESS_TYPES.get(key)
    if cols is None:
        return (
            f"Unknown progress type '{value}'. Options: "
            f"{', '.join(sorted(_PROGRESS_TYPES))}, custom"
        )
    ProgressType = key
    ProgressColumns = list(cols)
    _save_config()
    return f"{Tertiary}Progress type changed to {key} ({', '.join(cols)}){Reset}"


def _apply_theme(name):
    if name == "list":
        return f"{Muted}Themes: {', '.join(sorted(THEMES))}{Reset}"
    trio = THEMES.get(name.lower())
    if trio is None:
        return f"Unknown theme '{name}'. Themes: {', '.join(sorted(THEMES))}"
    _STYLE["primary"], _STYLE["secondary"], _STYLE["tertiary"] = trio
    _render()
    _save_config()
    return f"{Tertiary}Theme changed to '{name}'{Reset}"


def _apply_format(value):
    if not set_format(value):
        if value not in _VALID_FORMATS:
            return f"Unknown format '{value}'. Options: opus, m4a, mp3, webm"
        return (
            f"{YELLOW}ffmpeg not found. Install ffmpeg to use {value} format.{Reset}\n"
            f"{GREY}  Keeping current format: {FORMAT}{Reset}"
        )
    return f"{Tertiary}Default download format changed to {value}{Reset}"


PLUGIN_SAFE_KEYS = {
    "primary",
    "secondary",
    "tertiary",
    "custom_color",
    "primary_color",
    "secondary_color",
    "tertiary_color",
    "theme",
    "spinner",
    "rich_spinner",
    "display",
    "banner",
    "progress_columns",
    "progress_type",
    "barwidth",
    "barheight",
    "barspacing",
    "barchar",
    "progchar",
    "progcharem",
    "sensitivity",
    "format",
    "max_search",
    "max_radio",
    "ad_skip",
    "down_on_like",
    "notify",
    "scrobble_backend",
    "reload",
    "clear_colors",
}


def apply_config(key, value):
    global AD_SKIP, DOWN_ON_LIKE, NOTIFY
    target = _TARGET_ALIASES.get(key.lower(), key.lower())
    if target not in PLUGIN_SAFE_KEYS:
        return f"Unknown config key '{key}'"
    if target == "theme":
        return _apply_theme(value)
    if target == "spinner":
        return _apply_spinner(value)
    if target == "rich_spinner":
        return _apply_rich_spinner(value)
    if target == "progress_type":
        return _apply_progress_type(value)
    if target == "primary":
        return _apply_color("primary", value)
    if target == "secondary":
        return _apply_color("secondary", value)
    if target == "tertiary":
        return _apply_color("tertiary", value)
    if target == "custom_color":
        return _apply_custom_color(value)
    if target == "primary_color":
        return _apply_custom_color_slot("primary", value)
    if target == "secondary_color":
        return _apply_custom_color_slot("secondary", value)
    if target == "tertiary_color":
        return _apply_custom_color_slot("tertiary", value)
    if target == "reload":
        return _apply_reload()
    if target == "clear_colors":
        return _apply_clear_colors()
    if target == "display":
        return _apply_display(value)
    if target == "banner":
        return _apply_banner(value)
    if target == "progress_columns":
        return _apply_progress_columns(value)
    if target in ("barwidth", "width"):
        return _apply_int("BarWidth", value, 4, 80, "Bar width changed")
    if target in ("barheight", "height"):
        return _apply_int("BarHeight", value, 10, 90, "Bar height changed")
    if target in ("barspacing", "spacing"):
        if value in _BAR_SPACING:
            return _apply_bar_spacing(value)
        return _apply_int("BarSpacing", value, 0, 4, "Bar spacing changed")
    if target == "sensitivity":
        try:
            v = float(value)
        except ValueError:
            return "sensitivity must be a number (0.5-5.0)"
        if 0.5 <= v <= 5.0:
            return _apply_sensitivity(v)
        return "sensitivity must be between 0.5 and 5.0"
    if target in ("barchar", "bar_char"):
        return _apply_bar_char(value)
    if target in ("progchar", "prog_char"):
        return _apply_prog_char(value)
    if target in ("progcharem", "prog_char_em"):
        return _apply_prog_char_em(value)
    if target == "format":
        return _apply_format(value)
    if target == "ad_skip":
        if value in ("true", "false"):
            AD_SKIP = value == "true"
            _save_config()
            return f"{Tertiary}Sponsor segment skipping set to {AD_SKIP}{Reset}"
        return "ad_skip must be true/false"
    if target in ("down_on_like", "downlike"):
        if value in ("true", "false"):
            DOWN_ON_LIKE = value == "true"
            _save_config()
            return f"{Tertiary}Auto-download on like set to {DOWN_ON_LIKE}{Reset}"
        return "down_on_like must be true/false"
    if target == "notify":
        if value in ("true", "false"):
            NOTIFY = value == "true"
            _save_config()
            return f"{Tertiary}Desktop notifications set to {NOTIFY}{Reset}"
        return "notify must be true/false"
    if target in ("max_search", "maxresults"):
        return _apply_int(
            "MAX_SEARCH_RESULTS", value, 1, 20, "Max search results changed"
        )
    if target in ("max_radio", "maxradio"):
        return _apply_int("MAX_RESULTS_RADIO", value, 1, 50, "Max radio tracks changed")
    return f"Unknown config key '{key}'"


def _current_theme():
    cur = (_STYLE["primary"], _STYLE["secondary"], _STYLE["tertiary"])
    for name, trio in THEMES.items():
        if tuple(trio) == cur:
            return name
    return None


def config_get(key):
    target = _TARGET_ALIASES.get(key.lower(), key.lower())
    getters = {
        "primary": lambda: _STYLE["primary"],
        "secondary": lambda: _STYLE["secondary"],
        "tertiary": lambda: _STYLE["tertiary"],
        "custom_color": lambda: CustomColor,
        "primary_color": lambda: _CUSTOM["primary"] or "",
        "secondary_color": lambda: _CUSTOM["secondary"] or "",
        "tertiary_color": lambda: _CUSTOM["tertiary"] or "",
        "theme": _current_theme,
        "spinner": lambda: SPINNER,
        "rich_spinner": lambda: RichSpinner,
        "display": lambda: Display,
        "banner": lambda: Banner,
        "progress_columns": lambda: ProgressColumns,
        "progress_type": lambda: ProgressType,
        "barwidth": lambda: BarWidth,
        "barheight": lambda: BarHeight,
        "barspacing": lambda: BarSpacing,
        "barchar": lambda: BarChar,
        "progchar": lambda: ProgChar,
        "progcharem": lambda: ProgCharEm,
        "sensitivity": lambda: Sensitivity,
        "format": lambda: FORMAT,
        "dev": lambda: DEV_MODE,
        "ad_skip": lambda: AD_SKIP,
        "down_on_like": lambda: DOWN_ON_LIKE,
        "notify": lambda: NOTIFY,
        "max_search": lambda: MAX_SEARCH_RESULTS,
        "max_radio": lambda: MAX_RESULTS_RADIO,
        "search_source": lambda: SearchSource,
        "scrobble": lambda: ScrobbleBackend,
        "scrobbler": lambda: ScrobbleBackend,
        "lastfm_user": lambda: LastfmUsername,
        "lb_user": lambda: ListenbrainzUsername,
    }
    getter = getters.get(target)
    if getter is None:
        return None, False
    return getter(), True


def _apply_int(attr, value, lo, hi, ok_msg):
    global BarWidth, BarHeight, BarSpacing, MAX_SEARCH_RESULTS, MAX_RESULTS_RADIO
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
        ProgChar, \
        ProgCharEm, \
        Sensitivity, \
        DEV_MODE, \
        FORMAT, \
        AD_SKIP, \
        DOWN_ON_LIKE, \
        MAX_SEARCH_RESULTS, \
        MAX_RESULTS_RADIO, \
        SearchSource, \
        NOTIFY, \
        ScrobbleBackend, \
        LastfmUsername, \
        ListenbrainzUsername
    if extra and (extra[0] in ("help", "-h")):
        print(f"{Tertiary}Available targets:{Reset}")
        print(f"  {Primary}primary{Reset}   (aliases: pri)")
        print(f"  {Secondary}secondary{Reset} (aliases: sec)")
        print(f"  {Tertiary}tertiary{Reset}  (aliases: ter)")
        print(f"  {GREY}display{Reset}    (none, bars, lyrics, progress, rich)")
        print(
            f"  {GREY}banner{Reset}     (classic, random — current: {Banner})"
        )
        print(
            f"  {GREY}progress_columns{Reset} (rich progress bar columns — "
            f"{', '.join(_RICH_COLUMN_NAMES)}; aliases: richcols, rich_columns)"
        )
        print(
            f"  {GREY}progress_type{Reset} (rich progress layout — default, download, "
            f"pulse, custom; current: {ProgressType})"
        )
        print(f"  {GREY}barwidth{Reset}   (4-80, current: {BarWidth})")
        print(f"  {GREY}barheight{Reset}  (10-90, current: {BarHeight})")
        print(f"  {GREY}barspacing{Reset} (0-4, min, fit, max — current: {BarSpacing})")
        print(
            f"  {GREY}barchar{Reset}    (dot, block, circle, or any single char — current: {BarChar})"
        )
        print(
            f"  {GREY}progchar{Reset}   (progress bar fill — dot/block/circle or any single char, current: {ProgChar})"
        )
        print(
            f"  {GREY}progcharem{Reset} (progress bar empty part — dot/block/circle or any single char, current: {ProgCharEm})"
        )
        print(f"  {GREY}sensitivity{Reset} (0.5-5.0, current: {Sensitivity})")
        print(
            f"  {GREY}theme{Reset}      (ocean, sunset, forest, fire, mono, royal — or 'list')"
        )
        print(
            f"  {GREY}custom_color{Reset} (true/false — take Primary/Secondary/Tertiary from "
            f"~/.flow/color.json when on; current: {'on' if CustomColor else 'off'})"
        )
        print(
            f"  {GREY}primary_color{Reset} / secondary_color / tertiary_color (any rich style: "
            f"named color, #hex, rgb(r,g,b), bold/italic — stored in ~/.flow/color.json)"
        )
        print(
            f"  {GREY}reload{Reset}      (force re-read config.json + color.json from disk right now)"
        )
        print(
            f"  {GREY}clear_colors{Reset} (drop every custom color — every slot back to the theme)"
        )
        print(
            f"  {GREY}rich_spinner{Reset} (rich spinner — a name from `python -m "
            f"rich.spinner`, or 1-16 custom chars; current: {RichSpinner})"
        )
        print(f"  {GREY}spinner{Reset}     (2-16 chars, plain-text spinner, current: {SPINNER})")
        print(f"  {GREY}format{Reset}     (opus, m4a, mp3, webm — current: {FORMAT})")
        print(
            f"  {GREY}ad_skip{Reset}     (true/false — SponsorBlock segment skipping, current: {AD_SKIP})"
        )
        print(
            f"  {GREY}down_on_like{Reset} (true/false — auto-download when liking online, current: {DOWN_ON_LIKE})"
        )
        print(
            f"  {GREY}notify{Reset}      (true/false — desktop notifications, current: {NOTIFY})"
        )
        print(
            f"  {GREY}sponsor_categories{Reset} (in config file: sponsor, selfpromo, intro, outro, ...)"
        )
        print(f"  {GREY}max_search{Reset} (1-20, current: {MAX_SEARCH_RESULTS})")
        print(f"  {GREY}max_radio{Reset}  (1-50, current: {MAX_RESULTS_RADIO})")
        print(
            f"  {GREY}search_source{Reset} (youtube/ytmusic — youtube searches yt-dlp and "
            f"Tile-truncates titles; ytmusic keeps them as-is, current: {SearchSource})"
        )
        print(
            f"  {GREY}scrobble{Reset}      (lastfm/listenbrainz/off — track scrobbling backend, "
            f"current: {ScrobbleBackend or 'off'}; secrets live in the OS keyring, see `flow scrobbler --help`)"
        )
        print(
            f"\n{Tertiary}Available colors (any rich style: named color, #hex, rgb(r,g,b), bold/italic):{Reset}"
        )
        for name in RICH_COLORS:
            print(f"  {_sgr(name)}{name}{Reset}")
        print(f"\n{GREY}Config file: {CONFIG_FILE}{Reset}")
        return
    if not extra:
        _interactive_config()
        return
    target = _TARGET_ALIASES.get(extra[0].lower(), extra[0].lower())
    if target in ("reload", "clear_colors"):
        value = ""
    elif len(extra) < 2:
        print(f"Usage: config <target> <value>{Reset}")
        return
    else:
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
    elif target == "banner":
        emit(_apply_banner(value))
    elif target == "progress_columns":
        emit(_apply_progress_columns(value))
    elif target == "progress_type":
        emit(_apply_progress_type(value))
    elif target in ("rich_spinner", "richspin", "rich_spin"):
        emit(_apply_rich_spinner(value))
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
    elif target in ("progchar", "prog_char"):
        print(_apply_prog_char(value))
    elif target in ("progcharem", "prog_char_em"):
        print(_apply_prog_char_em(value))
    elif target == "dev":
        if value not in ("true", "false"):
            print("Usage: config dev true/false")
            return
        DEV_MODE = value == "true"
        _save_config()
        print(f"{Tertiary}Dev mode set to {DEV_MODE}{Reset}")
        try:
            from backend import logger

            logger.info("system", "config_change", f"Dev mode set to {DEV_MODE}", {"dev_mode": DEV_MODE})
        except Exception:
            pass
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
    elif target == "notify":
        if value not in ("true", "false"):
            print("Usage: config notify true/false")
            return
        NOTIFY = value == "true"
        _save_config()
        print(f"{Tertiary}Desktop notifications set to {NOTIFY}{Reset}")
    elif target in ("scrobble", "scrobbler"):
        backends = {"lastfm": "lastfm", "listenbrainz": "listenbrainz",
                    "lb": "listenbrainz", "lf": "lastfm", "off": "", "": ""}
        if value not in backends:
            print("Usage: config scrobble lastfm/listenbrainz/off")
            return
        ScrobbleBackend = backends[value]
        _save_config()
        print(f"{Tertiary}Scrobbler {'disabled' if not ScrobbleBackend else 'set to ' + ScrobbleBackend}{Reset}")
    elif target in ("lastfm_user", "lastfm_username"):
        LastfmUsername = " ".join(extra[1:]).strip()
        _save_config()
        print(f"{Tertiary}Last.fm username set to {LastfmUsername or '(empty)'}{Reset}")
    elif target in ("lb_user", "listenbrainz_username"):
        ListenbrainzUsername = " ".join(extra[1:]).strip()
        _save_config()
        print(f"{Tertiary}ListenBrainz username set to {ListenbrainzUsername or '(empty)'}{Reset}")
    elif target in ("max_search", "maxresults"):
        print(
            _apply_int("MAX_SEARCH_RESULTS", value, 1, 20, "Max search results changed")
        )
    elif target in ("max_radio", "maxradio"):
        print(_apply_int("MAX_RESULTS_RADIO", value, 1, 50, "Max radio tracks changed"))
    elif target in ("search_source", "searchsource"):
        if value not in ("youtube", "ytmusic"):
            print("Usage: config search_source youtube/ytmusic")
            return
        SearchSource = value
        _save_config()
        print(f"{Tertiary}Search source set to {SearchSource}{Reset}")
        try:
            from backend import logger

            logger.info(
                "system",
                "config_change",
                f"Search source set to {SearchSource}",
                {"search_source": SearchSource},
            )
        except Exception:
            pass
    elif target == "theme":
        print(_apply_theme(value))
    elif target == "custom_color":
        print(_apply_custom_color(value))
    elif target == "primary_color":
        print(_apply_custom_color_slot("primary", value))
    elif target == "secondary_color":
        print(_apply_custom_color_slot("secondary", value))
    elif target == "tertiary_color":
        print(_apply_custom_color_slot("tertiary", value))
    elif target == "reload":
        print(_apply_reload())
    elif target == "clear_colors":
        print(_apply_clear_colors())
    elif target == "spinner":
        print(_apply_spinner(value))
    else:
        aliases = ", ".join(f"{k}->{v}" for k, v in _TARGET_ALIASES.items())
        print(
            f"Unknown target '{target}'. Use: primary, sec, ter, display ({aliases}){Reset}"
        )


def notify(title, body=""):
    if not NOTIFY:
        return
    try:
        if sys.platform == "darwin":
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display notification "{body}" with title "{title}"',
                ],
                check=False,
            )
        elif os.name != "nt":
            subprocess.run(["notify-send", title, body], check=False)
    except OSError:
        pass


def down_notify(song_name, error=False):
    if error:
        notify("Download Failed", f"Error occurred during download: {song_name}")
    else:
        notify("Downloaded Song", f"song: {song_name}")


def _apply_bool(attr, ok_msg, v):
    globals()[attr] = bool(v)
    _save_config()
    return f"{Tertiary}{ok_msg} {v}{Reset}"


def _apply_sensitivity_io(v):
    try:
        val = float(v)
    except ValueError:
        return "sensitivity must be a number (0.5-5.0)"
    if not (0.5 <= val <= 5.0):
        return "sensitivity must be between 0.5 and 5.0"
    return _apply_sensitivity(val)


def _apply_bar_spacing_io(v):
    s = str(v).strip().lower()
    if s in _BAR_SPACING:
        return _apply_bar_spacing(s)
    try:
        return _apply_bar_spacing(int(s))
    except ValueError:
        return "bar_spacing must be min/fit/max or 0-4"


def _interactive_rows():
    if Display == "rich":
        spinner_row = (
            "spinner",
            "Spinner",
            lambda: RichSpinner,
            "select",
            _spinner_choices(),
            lambda v: _apply_rich_spinner(v) if v != "Custom…" else None,
        )
    else:
        spinner_row = (
            "spinner",
            "Spinner",
            lambda: SPINNER,
            "text",
            None,
            _apply_spinner,
        )
    rows = [
        (
            "display",
            "Display mode",
            lambda: Display,
            "select",
            ["none", "bars", "lyrics", "progress", "rich"],
            lambda v: _apply_display(str(v)),
        ),
        (
            "banner",
            "Banner",
            lambda: Banner,
            "select",
            sorted(_BANNER_MODES),
            lambda v: _apply_banner(str(v)),
        ),
        (
            "primary",
            "Primary color",
            lambda: _STYLE["primary"],
            "select",
            RICH_COLORS,
            lambda v: _apply_color("primary", str(v)),
        ),
        (
            "secondary",
            "Secondary color",
            lambda: _STYLE["secondary"],
            "select",
            RICH_COLORS,
            lambda v: _apply_color("secondary", str(v)),
        ),
        (
            "tertiary",
            "Tertiary color",
            lambda: _STYLE["tertiary"],
            "select",
            RICH_COLORS,
            lambda v: _apply_color("tertiary", str(v)),
        ),
        (
            "theme",
            "Color theme",
            _current_theme,
            "select",
            sorted(THEMES),
            lambda v: _apply_theme(str(v)),
        ),
        (
            "custom_color",
            "Custom colors on/off (takes colors from color.json)",
            lambda: bool(CustomColor),
            "confirm",
            None,
            _apply_custom_color,
        ),
        (
            "primary_color",
            "Custom primary color (~/.flow/color.json; #hex / rgb / name)",
            lambda: _CUSTOM["primary"] or "",
            "text",
            None,
            lambda v: _apply_custom_color_slot("primary", str(v)),
        ),
        (
            "secondary_color",
            "Custom secondary color (~/.flow/color.json)",
            lambda: _CUSTOM["secondary"] or "",
            "text",
            None,
            lambda v: _apply_custom_color_slot("secondary", str(v)),
        ),
        (
            "tertiary_color",
            "Custom tertiary color (~/.flow/color.json)",
            lambda: _CUSTOM["tertiary"] or "",
            "text",
            None,
            lambda v: _apply_custom_color_slot("tertiary", str(v)),
        ),
        spinner_row,
        (
            "progress_type",
            "Progress type",
            lambda: ProgressType,
            "select",
            sorted(_PROGRESS_TYPES) + ["custom"],
            _apply_progress_type,
        ),
        (
            "progress_columns",
            "Rich progress columns",
            lambda: ", ".join(ProgressColumns),
            "text",
            None,
            lambda v: _apply_progress_columns(str(v)),
        ),
        (
            "format",
            "Default download format",
            lambda: FORMAT,
            "select",
            sorted(_VALID_FORMATS),
            lambda v: _apply_format(str(v)),
        ),
        (
            "bar_width",
            "Bar width (4-80)",
            lambda: BarWidth,
            "text",
            None,
            lambda v: _apply_int("BarWidth", v, 4, 80, "Bar width changed"),
        ),
        (
            "bar_height",
            "Bar height (10-90)",
            lambda: BarHeight,
            "text",
            None,
            lambda v: _apply_int("BarHeight", v, 10, 90, "Bar height changed"),
        ),
        (
            "bar_spacing",
            "Bar spacing",
            lambda: BarSpacing,
            "select",
            ["min", "fit", "max", "0", "1", "2", "3", "4"],
            _apply_bar_spacing_io,
        ),
        (
            "bar_char",
            "Bar char",
            lambda: _BC_NAME(BarChar),
            "text",
            None,
            _apply_bar_char,
        ),
        (
            "prog_char",
            "Progress bar fill char",
            lambda: _BC_NAME(ProgChar),
            "text",
            None,
            _apply_prog_char,
        ),
        (
            "prog_char_em",
            "Progress bar empty char",
            lambda: _BC_NAME(ProgCharEm),
            "text",
            None,
            _apply_prog_char_em,
        ),
        (
            "sensitivity",
            "Sensitivity (0.5-5.0)",
            lambda: Sensitivity,
            "text",
            None,
            _apply_sensitivity_io,
        ),
        (
            "ad_skip",
            "Ad skip",
            lambda: AD_SKIP,
            "confirm",
            None,
            lambda v: _apply_bool("AD_SKIP", "Ad skip set to", v),
        ),
        (
            "down_on_like",
            "Auto-download on like",
            lambda: DOWN_ON_LIKE,
            "confirm",
            None,
            lambda v: _apply_bool("DOWN_ON_LIKE", "Auto-download on like set to", v),
        ),
        (
            "notify",
            "Desktop notifications",
            lambda: NOTIFY,
            "confirm",
            None,
            lambda v: _apply_bool("NOTIFY", "Desktop notifications set to", v),
        ),
        (
            "max_search",
            "Max search results (1-20)",
            lambda: MAX_SEARCH_RESULTS,
            "text",
            None,
            lambda v: _apply_int(
                "MAX_SEARCH_RESULTS", v, 1, 20, "Max search results changed"
            ),
        ),
        (
            "max_radio",
            "Max radio tracks (1-50)",
            lambda: MAX_RESULTS_RADIO,
            "text",
            None,
            lambda v: _apply_int(
                "MAX_RESULTS_RADIO", v, 1, 50, "Max radio tracks changed"
            ),
        ),
    ]
    if Display == "rich":
        rows = [
            r
            for r in rows
            if r[0]
            not in (
                "bar_width",
                "bar_height",
                "bar_spacing",
                "bar_char",
                "prog_char",
                "prog_char_em",
            )
        ]
    else:
        rows = [r for r in rows if r[0] not in ("progress_columns", "progress_type")]
    if CustomColor:
        # theme rows are inert while custom_color feeds the colors
        rows = [
            r for r in rows if r[0] not in ("primary", "secondary", "tertiary", "theme")
        ]
    return rows


def _interactive_config():
    maybe_reload()
    try:
        import questionary
        from questionary import Style
    except ImportError:
        print(f"{Primary}Usage: config <target> <value>{Reset}")
        print(f"       config -h{Reset}")
        print(
            f"{GREY}  (interactive mode requires 'questionary', install with: pip install questionary){Reset}"
        )
        return

    py_style = Style(
        [
            ("qmark", f"fg:{_cname(_eff_style('tertiary'))}"),
            ("question", f"fg:{_cname(_eff_style('tertiary'))}"),
            ("answer", f"fg:{_cname(_eff_style('secondary'))} bold"),
            ("pointer", f"fg:{_cname(_eff_style('primary'))} bold"),
            ("highlighted", f"fg:{_cname(_eff_style('primary'))} bold"),
            ("selected", f"fg:{_cname(_eff_style('primary'))}"),
            ("separator", f"fg:{_cname('grey62')}"),
            ("instruction", f"fg:{_cname(_eff_style('tertiary'))}"),
            ("text", ""),
        ]
    )

    rows = _interactive_rows()
    screen = [
        {
            "type": "select",
            "name": "setting",
            "message": "Which setting?",
            "choices": [
                questionary.Choice(title=f"{label}  (current: {current()})", value=key)
                for key, label, current, *_ in rows
            ],
        }
    ]
    try:
        answers = questionary.prompt(screen, style=py_style)
    except KeyboardInterrupt, EOFError:
        answers = None
    if not answers:
        print(f"\n{GREY}Config cancelled. Nothing changed.{Reset}")
        return

    key = answers["setting"]
    row = next((r for r in rows if r[0] == key), None)
    if row is None:
        return
    _, label, current, kind, spec, apply = row
    question = {"type": kind, "name": "value", "message": label}
    if kind == "select":
        question["choices"] = spec or []
        cur = current()
        if cur in (spec or []):
            question["default"] = cur
    elif kind == "confirm":
        question["default"] = bool(current())
    else:
        question["default"] = str(current())
    try:
        edit = questionary.prompt([question], style=py_style)
    except KeyboardInterrupt, EOFError:
        edit = None
    if not edit or edit.get("value") is None:
        print(f"\n{GREY}{label} unchanged.{Reset}")
        return
    value = edit["value"]
    if value == "Custom…":
        try:
            custom = questionary.prompt(
                [
                    {
                        "type": "text",
                        "name": "value",
                        "message": "Custom spinner — a rich spinner name or 1-16 characters",
                        "default": str(current()),
                    }
                ],
                style=py_style,
            )
        except KeyboardInterrupt, EOFError:
            custom = None
        if not custom or custom.get("value") is None or not str(custom["value"]).strip():
            print(f"\n{GREY}Spinner unchanged.{Reset}")
            return
        value = str(custom["value"]).strip()
    msg = apply(value)
    if msg:
        print(msg)


def _eff_style(slot):
    """Effective rich style for a slot — custom_color override, else the theme."""
    if CustomColor and _CUSTOM[slot]:
        return _CUSTOM[slot]
    return _STYLE[slot]


def _cname(style):
    """Last color word of a style, as a prompt_toolkit-friendly hex or name."""
    s = _norm_style(style)
    if s.startswith("\x1b"):
        # ANSI escape code: map back to the chosen rich style string.
        resolved = None
        for which in ("primary", "secondary", "tertiary"):
            if CustomColor and _CUSTOM[which] and s == _sgr(_CUSTOM[which]):
                resolved = _CUSTOM[which]
                break
            if s == _sgr(_STYLE[which]):
                resolved = _STYLE[which]
                break
        s = resolved or "white"
    name = s.rsplit(" ", 1)[-1]
    try:
        from rich.color import Color

        rgb = Color.parse(name).get_truecolor()
        if rgb is not None:
            return rgb.hex
    except Exception:
        pass
    return name or "white"


def _BC_NAME(char):
    for name, code in _BAR_CHARS.items():
        if code == char:
            return name
    return char


_load_config()

if not _ffmpeg_configured:
    FFMPEG = _detect_ffmpeg()
if FORMAT != "webm" and not FFMPEG:
    FORMAT = "webm"
