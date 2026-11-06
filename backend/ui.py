from backend import config


def questionary_style(mode="online"):
    from questionary import Style

    def name(style):
        return config._cname(style)

    primary = config._eff_style("primary")
    secondary = config._eff_style("secondary")
    tertiary = config._eff_style("tertiary")

    if mode == "online":
        return Style(
            [
                ("qmark", f"fg:{name(primary)} bold"),
                ("question", f"fg:{name(primary)} bold"),
                ("answer", f"fg:{name(primary)} bold"),
                ("pointer", f"fg:{name(primary)} bold"),
                ("highlighted", f"fg:{name(primary)} bold"),
                ("selected", f"fg:{name(primary)}"),
                ("instruction", f"fg:{name(tertiary)}"),
                ("text", ""),
            ]
        )
    else:
        return Style(
            [
                ("qmark", f"fg:{name(secondary)} bold"),
                ("question", f"fg:{name(secondary)} bold"),
                ("answer", f"fg:{name(secondary)} bold"),
                ("pointer", f"fg:{name(secondary)} bold"),
                ("highlighted", f"fg:{name(secondary)} bold"),
                ("selected", f"fg:{name(secondary)}"),
                ("instruction", f"fg:{name(tertiary)}"),
                ("text", ""),
            ]
        )


def pick(
    question,
    choices,
    # default=0,
    instruction="(↑↓ navigate, Enter to select)",
    mode="online",
):
    try:
        import questionary
    except ImportError:
        return None, False

    if not _is_tty():
        return None, False

    q_choices = [
        c
        if isinstance(c, questionary.Choice)
        else questionary.Choice(title=c[0], value=c[1])
        for c in choices
    ]
    # for highlighting a default song is set to 0 or the start of the list for now
    # if (
    #     isinstance(default, int)
    #     and not isinstance(default, bool)
    #     and 0 <= default < len(q_choices)
    # ):
    #     default_value = q_choices[default].value
    # else:
    #     default_value = default

    try:
        choice = questionary.select(
            question,
            choices=q_choices,
            # default=default_value,
            instruction=instruction,
            style=questionary_style()
            if mode == "online"
            else questionary_style("offline"),
        ).ask()
    except KeyboardInterrupt, EOFError:
        return None, True
    return choice, True


def parse_index_list(text, count):
    picks = []
    for chunk in str(text).replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            lo_s, _, hi_s = chunk.partition("-")
            if not lo_s and not hi_s:
                continue
            try:
                lo = int(lo_s) if lo_s else 1
                hi = int(hi_s) if hi_s else count
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            picks.extend(range(lo, hi + 1))
        else:
            try:
                picks.append(int(chunk))
            except ValueError:
                continue
    out = []
    for n in picks:
        idx = n - 1
        if 0 <= idx < count and idx not in out:
            out.append(idx)
    return out


def make_choice(title, value, checked=False):
    try:
        import questionary
    except ImportError:
        return (title, value)
    return questionary.Choice(title=title, value=value, checked=checked)


def pick_many(
    question,
    choices,
    instruction="(Space toggle, a all, Enter confirm)",
    mode="online",
):
    try:
        import questionary
    except ImportError:
        return None, False

    if not _is_tty():
        return None, False

    q_choices = [
        c
        if isinstance(c, questionary.Choice)
        else questionary.Choice(title=c[0], value=c[1])
        for c in choices
    ]

    try:
        picked = questionary.checkbox(
            question,
            choices=q_choices,
            instruction=instruction,
            style=questionary_style()
            if mode == "online"
            else questionary_style("offline"),
        ).ask()
    except KeyboardInterrupt, EOFError:
        return None, True
    return picked, True


def _is_tty():
    try:
        import sys

        return sys.stdin.isatty()
    except Exception:
        return False
