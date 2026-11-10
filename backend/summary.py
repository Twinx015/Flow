import re
import shutil
import time

from backend import config, history, library

P = config.Primary
T = config.Tertiary
M = config.Muted
E = config.RED
G = config.GREY
R = config.Reset
config.keep_live(globals())

SORTS = ("plays", "recent", "name", "artist")

COMMANDS = {
    "summary": "Play summary | -l per-song table | -s <sort> | --top N | -c clear all plays",
}

DEFAULT_SORT = "plays"
DEFAULT_TOP = 20


def _tty_width(default: int = 96) -> int:
    try:
        return max(72, min(140, shutil.get_terminal_size().columns))
    except Exception:
        return default


def _ago(ts: float) -> str:
    if not ts:
        return "never"
    delta = max(0.0, time.time() - ts)
    mins = delta / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    hours = mins / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d ago"
    if days < 365:
        return f"{int(days / 7)}w ago"
    return f"{int(days / 365)}y ago"


def _truncate(text: str, width: int) -> str:
    text = text or ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _parse_args(extra: list[str]) -> dict:
    opts = {
        "list": False,
        "sort": DEFAULT_SORT,
        "top": DEFAULT_TOP,
        "clear": False,
        "help": False,
        "rest": [],
    }
    i = 0
    while i < len(extra):
        token = extra[i]
        if token in ("-l", "--list"):
            opts["list"] = True
        elif token in ("-h", "--help", "-?"):
            opts["help"] = True
        elif token == "-c" or token == "--clear":
            opts["clear"] = True
        elif token in ("-s", "--sort"):
            i += 1
            if i >= len(extra):
                opts["sort"] = None
                break
            value = extra[i].lower()
            opts["sort"] = value if value in SORTS else None
        elif token.startswith("--sort="):
            value = token.split("=", 1)[1].lower()
            opts["sort"] = value if value in SORTS else None
        elif token in ("-n", "--top"):
            i += 1
            if i >= len(extra):
                opts["top"] = DEFAULT_TOP
                break
            opts["top"] = extra[i]
        elif token.startswith("--top="):
            opts["top"] = token.split("=", 1)[1]
        else:
            opts["rest"].append(token)
        i += 1
    try:
        opts["top"] = max(1, min(int(opts["top"]), 500))
    except TypeError, ValueError:
        opts["top"] = DEFAULT_TOP
    return opts


def _sort_rows(rows: list[dict], sort: str) -> list[dict]:
    if sort == "recent":
        return sorted(rows, key=lambda r: r["last_played"], reverse=True)
    if sort == "name":
        return sorted(rows, key=lambda r: r["title"].lower())
    if sort == "artist":
        return sorted(rows, key=lambda r: (r["artist"].lower(), r["title"].lower()))
    return sorted(
        rows,
        key=lambda r: (r["song_count"], r["last_played"]),
        reverse=True,
    )


def _box(title: str, rows: list[tuple], width: int) -> None:
    """The full-width `┌─ Title ─┐` card `flow --status` also prints."""
    inner = width - 2
    print(f"{P}┌─ {title} {'─' * max(0, inner - len(title) - 3)}┐{R}")
    for label, value in rows:
        line = f"  {label:<16}{value}"
        plain = len(re.sub(r"\x1b\[[0-9;]*m", "", line))
        print(
            f"{P}│{R} {_truncate(line, inner - 1)}"
            f"{' ' * max(0, inner - 1 - plain)}{P}│{R}"
        )
    print(f"{P}└{'─' * inner}┘{R}\n")


def _top_tag(rows: list[dict], key: str) -> str:
    """`<tag> (N plays)` for the artist that owns the most plays."""
    counts: dict[str, int] = {}
    for row in rows:
        for part in re.split(r",\s*", (row.get(key) or "").strip()):
            if part:
                counts[part] = counts.get(part, 0) + row["song_count"]
    if not counts:
        return f"{M}-{R}"
    best = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return f"{best[0]} {G}({best[1]} plays){R}"


def _top_song(rows: list[dict]) -> str:
    """`<title> (N plays)` for the most-played song."""
    best = max(rows, key=lambda r: (r["song_count"], r["last_played"]))
    return f"{best['title']} {G}({best['song_count']} plays){R}"


def _week_rows() -> list[tuple]:
    """`(day_offset, online, offline)` per calendar day, oldest first."""
    buckets = dict(library.play_days(7))
    rows = []
    for offset, online in history.per_day(7):
        combined = max(online, buckets.get(offset, 0))
        rows.append((offset, online, combined - online))
    return rows


def _week_sums() -> tuple[int, int]:
    """`(this_week, last_week)` combined plays over the last 14 days."""
    online = dict(history.per_day(14))
    buckets = dict(library.play_days(14))
    this = last = 0
    for offset in range(14):
        combined = max(online.get(offset, 0), buckets.get(offset, 0))
        if offset < 7:
            this += combined
        else:
            last += combined
    return this, last


def show_stats() -> None:
    """The stats card: the online/offline split, the three tops, the 7-day bars."""
    lib = library.stats()
    online = history.totals()["online_plays"]
    rows = library.play_rows()
    width = _tty_width()
    combined = lib["total_plays"]
    offline = max(combined - online, 0)
    print()
    _box(
        "Flow Summary",
        [
            ("combined plays", f"{G}{combined}{R} {M}(both modes){R}"),
            ("online plays", f"{G}{online}{R} {M}(history.db){R}"),
            ("offline plays", f"{G}{offline}{R} {M}(combined - online){R}"),
            ("unique songs", f"{G}{lib['unique_songs']}{R}"),
            ("played today", f"{G}{lib['played_today']}{R}"),
        ],
        width,
    )
    if not rows:
        return
    _box(
        "Top plays",
        [
            ("top artist", _top_tag(rows, "artist")),
            ("top song", _top_song(rows)),
        ],
        width,
    )
    week = _week_rows()
    bar_width = 24
    peak = max((on + off for _, on, off in week), default=0)
    count_w = max((len(f"{on}/{off}") for _, on, off in week), default=3)
    print(f"{T}  last 7 days · online/offline plays{R}")
    if peak:
        for offset, on, off in week:
            filled = int(round((on + off) / peak * bar_width))
            online_w = min(int(round(on / peak * bar_width)), filled)
            offline_w = filled - online_w
            label = "today" if offset == 0 else f"-{offset}d"
            counts = str(on).rjust(count_w - len(str(off)) - 1) + "/" + str(off)
            print(
                f"  {M}{label:>6}{R} {P}{'█' * online_w}{M}{'░' * offline_w}{R}"
                f"{G}{' ' * (bar_width - filled)}{R} {P}{counts}{R}"
            )
    else:
        print(f"  {M}no plays logged in the last 7 days{R}")

    this_w, last_w = _week_sums()
    if this_w or last_w:
        frac = this_w / last_w if last_w else 1.0
        pct = int(round(frac * 100)) if last_w else None
        note = f"{pct}% of last week" if pct is not None else "no last-week plays"
        print(
            f"{T}  \nthis week{R} {config.progress_bar(frac, bar_width)}{M} "
            f"{this_w} vs {last_w} plays · {note}{R}"
        )

    print()


def show_table(sort: str = DEFAULT_SORT, top: int = DEFAULT_TOP) -> None:
    rows = _sort_rows(library.play_rows(), sort)
    if not rows:
        print(f"{M}Nothing has been played yet{R}")
        return
    shown = rows[:top]
    title_w = max(12, _tty_width() - 52)
    # Width of the header rule, measured without the colour codes.
    rule_w = 2 + 6 + 2 + 12 + 2 + 16 + 2 + 5
    print()
    print(f"  {T}{'PLAYS':>6}  {'LAST PLAYED':<12}  {'ARTIST':<16}  TITLE{R}")
    print(f"  {G}{'─' * rule_w}{R}")
    for row in shown:
        plays = row["song_count"]
        color = P if plays > 1 else M
        artist = _truncate(row["artist"] or "-", 16).ljust(16)
        print(
            f"  {color}{plays:>6}{R}  "
            f"{M}{_ago(row['last_played']):<12}{R}  "
            f"{G}{artist}{R}  "
            f"{_truncate(row['title'], title_w)}"
        )
    print()
    if len(rows) > len(shown):
        print(f"{M}  showing {len(shown)} of {len(rows)} — --top N for more{R}")
    print()


def clear_history() -> None:
    """Wipe both stores: the online log rows and the library play counters."""
    removed = history.clear()
    reset = library.clear_plays()
    print(f"{P}Cleared {removed} online play(s) and reset {reset} song count(s){R}")
    print(f"{M}  both stores wiped: history.db rows + library.db song_count{R}")


def cmd_summary(extra: list[str], args=None) -> None:
    opts = _parse_args(list(extra or []))
    if opts["help"]:
        print_help()
        return
    if opts["sort"] is None:
        print(f"{E}Unknown sort key. Use one of: {', '.join(SORTS)}{R}")
        return
    if opts["clear"]:
        clear_history()
        return
    if opts["list"]:
        show_table(opts["sort"], opts["top"])
    else:
        show_stats()


def print_help() -> None:
    print(f"{T}summary{R} {M}[-l] [-s sort] [--top N] [-c]{R}")
    print(f"{G}  Play statistics: the online/offline split, the top artist{R}")
    print(f"{G}  and song, and the ranked per-song table.{R}")
    print(
        f"  {M}-l{R}          {G}List the per-song table instead of the stats card{R}"
    )
    print(
        f"  {M}-s{R} {M}<sort>{R}   {G}Table sort: {', '.join(SORTS)} (default: {DEFAULT_SORT}){R}"
    )
    print(
        f"  {M}--top{R} {M}<N>{R}    {G}Rows to show in the table (default: {DEFAULT_TOP}){R}"
    )
    print(
        f"  {M}-c{R}          {G}Clear all play history (history.db + library.db counts){R}"
    )
    print(f"{G}  combined = library.db (every mode); online = history.db rows;{R}")
    print(f"{G}  offline = combined - online. The web History panel shows the{R}")
    print(f"{G}  online-only timeline from history.db.{R}")
    print()
