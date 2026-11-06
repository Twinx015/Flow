import argparse


def _running_pid():
    """Pid of a live Flow player: registry first, legacy pid files as fallback."""
    from backend import registry

    for kind in ("tui", "vlc"):
        entry = registry.resolve(kind)
        if entry is not None:
            return entry["pid"]
    return None


def _control(action, label, require_tui=False):
    from backend import ipc, registry

    pid = _running_pid()
    if pid is None:
        return False, f"{label}: no running Flow player (start `flowt` first)"
    if require_tui:
        entry = registry.resolve("tui")
        if entry is None or entry["pid"] != pid:
            return False, f"{label}: no running Flow TUI (start `flowt` first)"
    else:
        entry = registry.resolve("vlc") or registry.resolve("tui")
    if not ipc.send(entry, action):
        return False, f"{label}: player PID {pid} is gone"
    return True, f"{label} (PID {pid})"


def _show_status() -> None:
    from backend.status import show as show_status

    show_status()


def main():
    from backend import config

    parser = argparse.ArgumentParser(
        prog="flowt",
        description="Flow — terminal UI music player",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="toggle play/pause in a running Flow session (flowt or background VLC)",
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="skip to the next track in a running Flow session",
    )
    parser.add_argument(
        "--previous",
        action="store_true",
        help="go back to the previous track in a running Flow session",
    )
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="toggle repeat in a running Flow TUI; otherwise start the TUI with repeat enabled",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="toggle shuffle in a running Flow TUI; otherwise start the TUI with shuffle enabled",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="show playback and web mode status, then exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {config.VERSION}",
        help="print the Flow version and exit",
    )
    args = parser.parse_args()

    if args.status:
        _show_status()
        return

    controls = (
        (args.pause, "pause", "Pause toggled", False),
        (args.next, "next", "Next", False),
        (args.previous, "prev", "Previous", False),
        (args.repeat, "repeat", "Repeat toggled", True),
        (args.shuffle, "shuffle", "Shuffle toggled", True),
    )
    active = [
        (action, label, require_tui)
        for flag, action, label, require_tui in controls
        if flag
    ]
    hard = args.pause or args.next or args.previous

    if active and _running_pid() is not None:
        delivered = True
        for action, label, require_tui in active:
            ok, msg = _control(action, label, require_tui=require_tui)
            print(msg)
            if require_tui and not ok:
                delivered = False
        if delivered:
            return
        if hard:
            return

    if active and hard and _running_pid() is None:
        print("No running Flow player to control. Start `flowt` first.")
        return

    from .main import Flow

    Flow(mode=None, repeat=args.repeat, shuffle=args.shuffle).run()


if __name__ == "__main__":
    main()
