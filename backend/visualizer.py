import re
import shutil
import subprocess
import threading

import numpy as np
from backend import config

try:
    import curses
except ImportError:
    curses = None

BLOCK_SIZE = 4096
SAMPLE_RATE = 48000
MIN_FREQ = 60
MAX_FREQ = 18000

_bars = None
_peak = None
_stream = None
_lock = threading.Lock()
_stdscr = None
_color_pair = 1
_tertiary_pair = 2

_orig_source = None

_FOOTER_ROWS = 2
_status_title = None
_status_shuffle = False
_status_repeat = False
_status_next = None
_status_paused = False
_status_artist = ""
_status_album = ""


def _ansi_to_curses_color(ansi_code):
    basic = {
        "30": 0, "31": 1, "32": 2, "33": 3,
        "34": 4, "35": 5, "36": 6, "37": 7,
        "90": 8, "91": 9, "92": 10, "93": 11,
        "94": 12, "95": 13, "96": 14, "97": 15,
    }

    m = re.search(r"38;2;(\d+);(\d+);(\d+)", ansi_code)
    if m:
        # Truecolor requires a terminal that supports palette redefinition
        # and at least 17 color slots. Fall back safely otherwise.
        if curses.can_change_color() and curses.COLORS > 16:
            r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                curses.init_color(16, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
                return 16
            except curses.error:
                pass
        return 6

    m = re.search(r"38;5;(\d+)", ansi_code)
    if m:
        color_num = int(m.group(1))
        if color_num < curses.COLORS:
            return color_num
        return 6

    for code, num in basic.items():
        if f";{code}m" in ansi_code or ansi_code.endswith(f"{code}m"):
            return num
    return 6


def _log_bins(nfft, sr, num_bars):
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    edges = np.logspace(np.log10(MIN_FREQ), np.log10(MAX_FREQ), num_bars + 1)
    bins = []
    for i in range(num_bars):
        lo, hi = edges[i], edges[i + 1]
        mask = (freqs >= lo) & (freqs < hi)
        bins.append(mask)
    return bins


def _rebuild():
    global _bars, _peak
    n = config.BarWidth
    _bars = np.zeros(n)
    _peak = None
    return _log_bins(BLOCK_SIZE, SAMPLE_RATE, n)


_bins = _rebuild()


def _find_monitor():
    # The system output monitor (.monitor source) is what actually carries the
    # music. On PulseAudio/PipeWire these are exposed as "XXX.monitor" sources,
    # which PortAudio does not surface by name, so we resolve them via pactl and
    # temporarily make them the capture source for the "pulse" device.
    pactl = shutil.which("pactl")
    if pactl:
        try:
            out = subprocess.run(
                [pactl, "list", "short", "sources"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:
            out = ""
        monitor = None
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1]
            state = parts[2] if len(parts) > 2 else ""
            if ".monitor" in name.lower():
                monitor = name
                if "running" in state.lower():
                    return name
        if monitor:
            return monitor

    # Fallback: any sounddevice device named like a monitor.
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return None
    for i, d in enumerate(devices):
        name = d["name"].lower()
        if "monitor" in name and d["max_input_channels"] > 0:
            return i
    return None


def _switch_default_source(monitor):
    """Temporarily route the 'pulse' capture to the monitor source.

    Returns the name of the previous default source (to restore later), or None.
    """
    pactl = shutil.which("pactl")
    if not pactl or not isinstance(monitor, str):
        return None
    try:
        old = subprocess.run(
            [pactl, "get-default-source"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        subprocess.run(
            [pactl, "set-default-source", monitor],
            capture_output=True,
            timeout=5,
        )
        return old
    except Exception:
        return None


def _restore_default_source(old):
    if not old:
        return
    pactl = shutil.which("pactl")
    if not pactl:
        return
    try:
        subprocess.run(
            [pactl, "set-default-source", old], capture_output=True, timeout=5
        )
    except Exception:
        pass


def _audio_callback(indata, frames, time_info, status):
    global _bars, _peak
    mono = np.mean(indata, axis=1)
    fft = np.abs(np.fft.rfft(mono))

    n = config.BarWidth
    if _bars is None or len(_bars) != n:
        return

    overall_rms = np.sqrt(np.mean(mono ** 2))
    if overall_rms <= 0.01:
        with _lock:
            _bars *= 0.4
        if _peak is not None:
            _peak *= 0.9
        return

    levels = np.zeros(n)
    for i, mask in enumerate(_bins):
        if np.any(mask):
            levels[i] = np.sqrt(np.mean(fft[mask] ** 2))

    peak = np.max(levels)
    if _peak is None:
        _peak = peak
    else:
        _peak = max(peak, 0.7 * _peak + 0.3 * peak)

    if _peak > 1e-6:
        normalized = np.clip(levels / _peak * config.Sensitivity, 0, 1)
    else:
        normalized = np.zeros(n)

    with _lock:
        _bars = 0.4 * _bars + 0.6 * normalized


def start(stdscr, ansi_color):
    global _stream, _bins, _bars, _peak, _stdscr, _orig_source
    if curses is None:
        return False
    if _stream is not None:
        return
    import sounddevice as sd
    _stdscr = stdscr
    curses.start_color()
    curses.use_default_colors()
    color_num = _ansi_to_curses_color(ansi_color)
    curses.init_pair(_color_pair, color_num, -1)
    tertiary_num = _ansi_to_curses_color(config.Tertiary)
    curses.init_pair(_tertiary_pair, tertiary_num, -1)
    monitor = _find_monitor()
    if monitor is None:
        return False
    _orig_source = _switch_default_source(monitor)
    _bars = np.zeros(config.BarWidth)
    _peak = None
    _bins = _log_bins(BLOCK_SIZE, SAMPLE_RATE, config.BarWidth)
    try:
        _stream = sd.InputStream(
            device="pulse",
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            callback=_audio_callback,
        )
        _stream.start()
    except Exception:
        try:
            _stream = sd.InputStream(
                device=monitor,
                channels=1,
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                callback=_audio_callback,
            )
            _stream.start()
        except Exception:
            _stream = None
            _restore_default_source(_orig_source)
            _orig_source = None
            return False
    return True


def set_status(title=None, shuffle=False, repeat=False, next_title=None,
               artist="", album=""):
    global _status_title, _status_shuffle, _status_repeat, _status_next
    global _status_artist, _status_album
    _status_title = title
    _status_shuffle = shuffle
    _status_repeat = repeat
    _status_next = next_title
    _status_artist = artist or ""
    _status_album = album or ""


def set_paused(paused):
    global _status_paused
    _status_paused = paused


def stop():
    global _stream, _bars, _peak, _stdscr, _orig_source
    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None
    _restore_default_source(_orig_source)
    _orig_source = None
    with _lock:
        _bars = None
        _peak = None
    _stdscr = None
    set_status()


def draw():
    if _stdscr is None:
        return
    with _lock:
        if _bars is None:
            _stdscr.erase()
            _stdscr.refresh()
            return
        bars = _bars.copy()
    max_y, max_x = _stdscr.getmaxyx()
    available_height = max(1, max_y - _FOOTER_ROWS)
    bar_height = max(1, min(config.BarHeight, available_height))
    num_bars = len(bars)
    spacing = config.get_bar_spacing()
    bar_col = spacing + 1
    _stdscr.erase()

    base_y = max_y - _FOOTER_ROWS
    for row in range(bar_height):
        y = base_y - 1 - row
        for col_idx in range(num_bars):
            level = bars[col_idx]
            x = col_idx * bar_col
            if int(level * bar_height) > row:
                cell = config.BarChar[:1]
                attr = curses.color_pair(_color_pair) | curses.A_BOLD
                if y >= 0 and x < max_x:
                    try:
                        _stdscr.addstr(y, x, cell, attr)
                    except curses.error:
                        pass

    _draw_footer(max_y, max_x)
    _stdscr.refresh()


def _draw_footer(max_y, max_x):
    if (
        _status_title is None
        and not _status_shuffle
        and not _status_repeat
        and not _status_next
        and not _status_artist
        and not _status_album
        and not _status_paused
    ):
        return

    badges = []
    if _status_paused:
        badges.append("[Paused]")
    if _status_repeat:
        badges.append("[Repeat]")
    if _status_shuffle:
        badges.append("[Shuffle]")
    if _status_next:
        n = _status_next
        if len(n) > 24:
            n = n[:23] + "…"
        badges.append(f"[Next: {n}]")
    for extra in (_status_artist, _status_album):
        if extra:
            e = extra
            if len(e) > 24:
                e = e[:23] + "…"
            badges.append(f"[{e}]")

    title_row = max_y - 1
    badge_row = max_y - 2
    if _status_title is not None:
        title = f"[{_status_title}]"
        if len(title) > max_x:
            title = title[: max_x - 1]
        try:
            _stdscr.addstr(
                title_row,
                0,
                title,
                curses.color_pair(_tertiary_pair) | curses.A_BOLD,
            )
        except curses.error:
            pass
    elif badges:
        badge_row = title_row

    if badges:
        line = "  ".join(badges)
        if len(line) > max_x:
            line = line[: max_x - 1]
        try:
            _stdscr.addstr(
                badge_row,
                0,
                line,
                curses.color_pair(_tertiary_pair) | curses.A_DIM,
            )
        except curses.error:
            pass
