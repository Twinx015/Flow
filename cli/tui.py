import builtins
import os
import random
import sys
from pathlib import Path

from backend import config, keys

BANNERS_DIR = Path(__file__).resolve().parent / "banners"


def banner_names():
    """Banner file stems (without .txt), sorted."""
    try:
        return sorted(path.stem for path in BANNERS_DIR.glob("*.txt"))
    except OSError:
        return []


def load_banner(name=None):
    """Banner text for `name`, or a random one when `name` is "random"."""
    if name is None:
        name = getattr(config, "Banner", "classic")
    if name == "random":
        names = banner_names()
        if names:
            name = random.choice(names)
    path = BANNERS_DIR / f"{name}.txt"
    if not path.exists():
        path = BANNERS_DIR / "classic.txt"
    try:
        return path.read_text(encoding="utf-8").rstrip("\n")
    except OSError:
        return ""


def show_banner():
    c = config.Primary if config.Mode == "Online" else config.Secondary
    banner = load_banner()
    if banner:
        builtins.print(f"{c}{banner}{config.Reset}")
    builtins.print(
        f"{config.Muted}         Flow Music Player v{config.VERSION}{config.Reset}"
    )
    builtins.print(f"{c}         Mode : {config.Mode}{config.Reset}")
    if config.DEV_MODE:
        print(f"     {config.RED}       [Dev Mode]{config.Reset}")
    try:
        from backend import logger

        logger.debug(
            "tui",
            "ui",
            "show_banner called",
            {"mode": config.Mode, "dev_mode": config.DEV_MODE},
        )
    except Exception:
        pass
    builtins.print()


def clear_screen():
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()


def input(prompt: str = "") -> str:
    if config.Mode == "Online":
        return builtins.input(f"{config.Primary}{prompt}$ {config.Reset}")
    elif config.Mode == "Offline":
        return builtins.input(f"{config.Secondary}{prompt}$ {config.Reset}")
    return builtins.input(prompt)


_CTRL_Q = 0x11


def install_quit_key(fd=None):
    """Map Ctrl+Q to Ctrl+C so it leaves the shell like Ctrl+C does.

    Ctrl+Q raises no signal on a stock terminal: it is XON (resume output), so
    it is swallowed by flow control while a command is running and arrives as a
    plain byte while readline is editing a line. The only way to make it quit
    is to take XON away and hand the terminal's QUIT character to it, then
    catch SIGQUIT and re-raise it as the KeyboardInterrupt the shell loop
    already treats as "leave". Implementation lives in backend.keys; anything
    that is not a real terminal (piped stdin, background fork) is a no-op,
    as is the whole remap on Windows.

    `fd` exists so tests can point this at a pty slave; it defaults to stdin.

    Returns the callable that puts the terminal and handler back.
    """
    return keys.install_quit_key(fd)
