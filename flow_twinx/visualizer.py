import curses
import re
import threading

import numpy as np
import sounddevice as sd
from .imports import config

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
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for i, d in enumerate(devices):
        name = d["name"].lower()
        if "monitor" in name and d["max_input_channels"] > 0:
            return i
    for i, d in enumerate(devices):
        name = d["name"].lower()
        if name in ("pulse", "pipewire") and d["max_input_channels"] > 0:
            return i
    return None


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
    global _stream, _bins, _bars, _peak, _stdscr
    if _stream is not None:
        return
    _stdscr = stdscr
    curses.start_color()
    curses.use_default_colors()
    color_num = _ansi_to_curses_color(ansi_color)
    curses.init_pair(_color_pair, color_num, -1)
    dev = _find_monitor()
    if dev is None:
        return False
    _bars = np.zeros(config.BarWidth)
    _peak = None
    _bins = _log_bins(BLOCK_SIZE, SAMPLE_RATE, config.BarWidth)
    try:
        _stream = sd.InputStream(
            device=dev,
            channels=1,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            callback=_audio_callback,
        )
        _stream.start()
    except Exception:
        _stream = None
        return False
    return True


def stop():
    global _stream, _bars, _peak, _stdscr
    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None
    with _lock:
        _bars = None
        _peak = None
    _stdscr = None


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
    bar_height = max(10, min(config.BarHeight, max_y - 2))
    num_bars = len(bars)
    spacing = config.get_bar_spacing()
    bar_col = spacing + 1  # total stride per bar, including its trailing gap
    _stdscr.erase()
    for row in range(bar_height):
        y = max_y - 1 - row
        for col_idx in range(num_bars):
            level = bars[col_idx]
            x = col_idx * bar_col
            if int(level * bar_height) > row:
                cell = config.BarChar[:1]
                attr = curses.color_pair(_color_pair) | curses.A_BOLD
                if y < max_y and x < max_x:
                    try:
                        _stdscr.addstr(y, x, cell, attr)
                    except curses.error:
                        pass
            # Unlit cells: nothing to draw, screen was already erased.
    _stdscr.refresh()
