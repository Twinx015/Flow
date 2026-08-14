import errno
import fcntl
import os
import signal
import sys
import termios
import threading
import time

import vlc

from .. import status, visualizer
from ..imports import config

_truncate_title = config._truncate_title

P = config.Primary
S = config.Secondary
T = config.Tertiary


M = config.Muted
E = config.Red
R = config.Reset

m = lambda t: print(f"{M}{t}{R}")
e = lambda t: print(f"{E}{t}{R}")
i = lambda t: print(f"{P if config.Mode == 'Online' else S}{t}{R}")
t = lambda t: print(f"{T}{t}{R}")

_paused = False
_player = None
_original_term = None
_radio_active = False
_stop_reader = threading.Event()
_reader_thread = None

_next_req = False
_prev_req = False


def _sigusr1_toggle(sig, frame):
    global _paused
    _paused = not _paused
    if _player:
        _player.pause()


def _sigusr2_next(sig, frame):
    global _next_req
    _next_req = True
    if _player:
        _player.stop()


def _sigusr3_prev(sig, frame):
    global _prev_req
    _prev_req = True
    if _player:
        _player.stop()


def setup_nav_signals():
    signal.signal(signal.SIGUSR1, _sigusr1_toggle)
    signal.signal(signal.SIGUSR2, _sigusr2_next)
    signal.signal(config.SIG_PREV, _sigusr3_prev)


def _setup_pause_input():
    global _original_term
    if _radio_active:
        signal.signal(signal.SIGUSR1, _sigusr1_toggle)
        setup_nav_signals()
        return
    fd = sys.stdin.fileno()
    try:
        _original_term = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[0] &= ~termios.IXON
        new[6][termios.VSUSP] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)
    except termios.error, OSError:
        _original_term = None
        return
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    signal.signal(signal.SIGUSR1, _sigusr1_toggle)
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    setup_nav_signals()
    _stop_reader.clear()
    _reader_thread = threading.Thread(target=_input_reader, daemon=True)
    _reader_thread.start()


def _input_reader():
    fd = sys.stdin.fileno()
    try:
        while not _stop_reader.is_set():
            try:
                ch = os.read(fd, 1)
            except OSError as ex:
                if ex.errno == errno.EAGAIN:
                    time.sleep(0.05)
                    continue
                break
            if ch == b"\x10":
                os.kill(os.getpid(), signal.SIGUSR1)
    except OSError:
        pass


def _restore_pause_input():
    global _original_term, _reader_thread
    _stop_reader.set()
    if _reader_thread and _reader_thread.is_alive():
        _reader_thread.join(timeout=0.2)
    _reader_thread = None
    if _original_term is not None:
        try:
            fd = sys.stdin.fileno()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
            termios.tcsetattr(fd, termios.TCSADRAIN, _original_term)
        except termios.error, OSError:
            pass
        _original_term = None


def _flags_str(args):
    if not args:
        return ""
    parts = []
    if getattr(args, "repeat", False):
        count = getattr(args, "repeat_count", 0)
        parts.append(f"[Repeat:{'∞' if count < 0 else count}]")
    if getattr(args, "shuffle", False):
        parts.append("[Shuffle:On]")
    return "  ".join(parts)


def _display_loop(player, stop_check=None):
    global _paused
    display = config.Display
    if display == "none":
        return

    if display == "bars":
        visualizer.start()

    paused_printed = False
    try:
        while player.get_state() not in (vlc.State.Ended, vlc.State.Error):
            if stop_check and stop_check():
                break
            if _next_req or _prev_req:
                break
            if _paused:
                if not paused_printed:
                    sys.stdout.write(f"\r  {T}[Paused]{R}  ")
                    sys.stdout.flush()
                    paused_printed = True
                try:
                    time.sleep(0.1)
                except OSError:
                    pass
                continue
            if paused_printed:
                paused_printed = False
            if display == "bars":
                bar_str = visualizer.render(color=S, reset=R)
                sys.stdout.write(f"\r{bar_str}")
                sys.stdout.flush()
            try:
                time.sleep(0.08)
            except OSError:
                pass
    finally:
        if display == "bars":
            visualizer.stop()
        sys.stdout.write("\r" + " " * 60 + "\r\n")
        sys.stdout.flush()


def play_file(filepath, title, args=None, flags=None):
    global _player, _paused, _next_req, _prev_req
    _paused = False
    _next_req = False
    _prev_req = False
    devnull = os.open(os.devnull, os.O_RDWR)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    try:
        instance = vlc.Instance("--no-video --quiet")
        _player = instance.media_player_new()
        media = instance.media_new(str(filepath))
        _player.set_media(media)
        _player.play()
        _setup_pause_input()

        duration = 0
        for _ in range(50):
            duration = _player.get_length() / 1000
            if duration > 0:
                break
            time.sleep(0.1)
        if duration <= 0:
            duration = 0
        status.update(title, duration)
        dur_min, dur_sec = divmod(int(duration), 60)
        flags_str = _flags_str(args)
        i(f"\nPlaying : {_truncate_title(title)}")
        m(
            f"    [{dur_min}:{dur_sec:02d}]  {flags_str}"
            if flags_str
            else f"    [{dur_min}:{dur_sec:02d}]"
        )

        def stop_check():
            if flags:
                if flags.get("quit", lambda: False)():
                    _player.stop()
                    return True
                if flags.get("skip", lambda: False)():
                    _player.stop()
                    return True
            return False

        try:
            _display_loop(_player, stop_check=stop_check)
        except KeyboardInterrupt:
            _player.stop()
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise
        finally:
            _restore_pause_input()
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)
