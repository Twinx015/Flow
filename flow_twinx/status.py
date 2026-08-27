import json
import pathlib
import sys
import time

STATUS_FILE = pathlib.Path.home() / ".flow/status.json"
WEB_PID_FILE = pathlib.Path.home() / ".flow/web.pid"
WEB_PORT_FILE = pathlib.Path.home() / ".flow/web_port"

IMG_ROWS = 6
PAD_L = 2
GAP = 3
PAD_R = 2


def update(title, duration=0, playing=True, thumbnail=None):
    data = {
        "title": title or "Unknown",
        "duration": int(duration or 0),
        "playing": bool(playing),
        "thumbnail": thumbnail or "",
        "ts": time.time(),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data))


def _read():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}


def _web_active():
    try:
        if not WEB_PID_FILE.exists():
            return False
        import psutil

        pid = int(WEB_PID_FILE.read_text().strip())
        return psutil.Process(pid).is_running()
    except Exception:
        return False


def _web_port():
    try:
        return int(WEB_PORT_FILE.read_text().strip())
    except Exception:
        return None


def _fresh(data):
    ts = data.get("ts", 0)
    dur = data.get("duration", 0)
    return time.time() - ts <= max(120.0, dur + 30.0)


def _img_rows():
    try:
        from .config import ImgSize

        return max(3, min(20, int(ImgSize)))
    except Exception:
        return IMG_ROWS


def _card_ready(thumb):
    try:
        from . import terminal_img as ti

        if not ti.detect_kitty():
            return None
        src = ti.resolve_source(thumb)
        if src is None:
            return None
        prep = ti.prepare(src, _img_rows())
        if prep is None:
            return None
        return ti, src, prep
    except Exception:
        return None


def _print_plain(Primary, Grey, Reset, entries):
    sep = f"{Grey}{'─' * 44}{Reset}"
    print(f"\n{Primary}┌─ Flow Status{Reset}")
    print(sep)
    for label, rendered, _ in entries:
        print(f"{Primary}│{Reset}  {label:<17}: {rendered}")
    print(sep)
    print(f"{Primary}└─{Reset}\n")


def _print_card(Primary, Grey, Reset, entries, card):
    ti, src, (pw, ph, icols, irows) = card
    label_w = 17
    text_area = max(PAD_L + label_w + 2 + v for _, _, v in entries)
    inner = max(PAD_L + icols + GAP + text_area + PAD_R, 44)

    header_label = "┌─ Flow Status "
    print(f"{Primary}{header_label}{Reset}{Grey}{'─' * (inner - len(header_label))}{Reset}{Primary}┐{Reset}")

    offset = max(0, (irows - len(entries)) // 2)
    body = max(irows, len(entries))
    gutter = " " * (PAD_L + icols + GAP)
    for i in range(body):
        idx = i - offset
        if 0 <= idx < len(entries):
            label, rendered, vlen = entries[idx]
            content = f"{' ' * PAD_L}{label:<{label_w}}: {rendered}"
            vis = PAD_L + label_w + 2 + vlen
        else:
            content = ""
            vis = 0
        pad = " " * max(0, inner - vis)
        print(f"{Primary}│{Reset}{gutter}{content}{pad}{Primary}│{Reset}")

    print(f"{Primary}└{Reset}{Grey}{'─' * inner}{Reset}{Primary}┘{Reset}")

    up_down = body + 1
    sys.stdout.write(f"\x1b[{up_down}A\r\x1b[{1 + PAD_L}C")
    try:
        ti.render(str(src), pw, ph, icols, irows)
    except Exception:
        pass
    sys.stdout.write(f"\x1b[{up_down}B\r")
    sys.stdout.flush()


def show():
    from .config import Cyan, Grey, Muted, Primary, Reset, White

    data = _read()
    web = _web_active()
    port = _web_port()
    playing = bool(data.get("playing")) and _fresh(data)

    title = data.get("title", "None")
    if len(title) > 42:
        title = title[:42] + "..."
    thumb_raw = data.get("thumbnail", "")
    thumb = thumb_raw
    flow_prefix = str(pathlib.Path.home() / ".flow")
    if thumb.startswith(flow_prefix):
        thumb = thumb[len(flow_prefix):]
    if len(thumb) > 120:
        thumb = thumb[:120] + "..."
    dur = int(data.get("duration", 0))
    mins, secs = divmod(dur, 60)
    dur_str = f"{mins}:{secs:02d}"

    status_val = "playing" if playing else "not playing"
    status_col = Cyan if playing else Muted
    web_val = f"{port} active" if web else "not active"
    stat = "currently playing" if playing else "last played"
    web_col = Cyan if web else Muted

    dom_palette = []
    if thumb_raw:
        try:
            from .img_color import hex_str, palette

            dom_palette = palette(thumb_raw)
        except Exception:
            dom_palette = []
    if dom_palette:
        segs = [
            (f"\x1b[38;2;{r};{g};{b}m██{Reset} {White}{hex_str((r, g, b))}{Reset}",
             3 + len(hex_str((r, g, b))))
            for r, g, b in dom_palette
        ]
        color_entry = (
            " ".join(s for s, _ in segs),
            sum(v for _, v in segs) + len(segs) - 1,
        )
    else:
        color_entry = (f"{Muted}n/a{Reset}", 3)

    entries = [
        ("status", f"{status_col}{status_val}{Reset}", len(status_val)),
        ("web_mode", f"{web_col}{web_val}{Reset}", len(web_val)),
        (stat, f"{White}{title}{Reset}", len(title)),
        ("thumbnail", f"{White}{thumb}{Reset}", len(thumb)),
        ("color", *color_entry),
        ("total duration", f"{White}{dur_str}{Reset}", len(dur_str)),
    ]

    card = _card_ready(thumb_raw) if thumb_raw else None
    if card is not None:
        _print_card(Primary, Grey, Reset, entries, card)
    else:
        _print_plain(Primary, Grey, Reset, entries)
