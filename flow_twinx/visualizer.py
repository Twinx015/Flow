import sys
import numpy as np
import sounddevice as sd
from .imports import config

BLOCK_SIZE = 4096
SAMPLE_RATE = 48000
MIN_FREQ = 60
MAX_FREQ = 18000

FULL_CHARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"

_bars = None
_peak = None
_stream = None


def _build_chars(height):
    n = min(height, len(FULL_CHARS))
    return FULL_CHARS[:n]


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
    devices = sd.query_devices()
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

    _bars = 0.4 * _bars + 0.6 * normalized


def start():
    global _stream, _bins, _bars, _peak
    if _stream is not None:
        return
    dev = _find_monitor()
    if dev is None:
        return False
    _bars = np.zeros(config.BarWidth)
    _peak = None
    _bins = _log_bins(BLOCK_SIZE, SAMPLE_RATE, config.BarWidth)
    _stream = sd.InputStream(
        device=dev,
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        callback=_audio_callback,
    )
    _stream.start()
    return True


def stop():
    global _stream
    if _stream is not None:
        _stream.stop()
        _stream.close()
        _stream = None


def render(color="\033[0m", reset="\033[0m"):
    if _bars is None:
        return ""
    bars = _bars.copy()
    chars = _build_chars(config.BarHeight)
    max_h = len(chars) - 1
    space = " " * config.get_bar_spacing()
    line = ""
    for i, level in enumerate(bars):
        idx = int(level * max_h)
        idx = min(idx, max_h)
        ch = chars[idx]
        sep = "" if i == len(bars) - 1 else space
        line += f"{color}{ch}{reset}{sep}"
    return line
