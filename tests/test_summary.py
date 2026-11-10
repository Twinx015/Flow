"""`summary` / `--summary` output tests.

`summary` is the CLI half of the play-history feature and reads both stores:
`library.db` for the per-song table (every mode) and `history.db` for the
online-only totals. These tests pin the sort keys, the flag parsing and the
online/offline split, without asserting on colours or column widths.
"""

import re

import pytest

from backend import history, library, summary

ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture(autouse=True)
def seeded(capsys):
    """Three known songs with known counts, and an empty online log.

    `library.db` counts every mode; `history.db` only logs online streams, so
    the seed plays half of its events offline to keep the two apart.
    """
    history.clear()
    library.mark_unliked("sum-test-1")
    library.mark_unliked("sum-test-2")
    library.mark_unliked("sum-test-3")
    # 4x Around the World (2 online), 2x Teardrop (2 online), 1x Midnight City.
    plays = [
        ("sum-test-1", "Around the World", "Daft Punk", "online"),
        ("sum-test-1", "Around the World", "Daft Punk", "offline"),
        ("sum-test-1", "Around the World", "Daft Punk", "online"),
        ("sum-test-1", "Around the World", "Daft Punk", "offline"),
        ("sum-test-2", "Teardrop", "Massive Attack", "online"),
        ("sum-test-2", "Teardrop", "Massive Attack", "online"),
        ("sum-test-3", "Midnight City", "M83", "offline"),
    ]
    for video_id, title, artist, mode in plays:
        history.record_play(video_id, title, artist, mode=mode)
    yield
    for video_id in ("sum-test-1", "sum-test-2", "sum-test-3"):
        library._mutate(lambda data, v=video_id: data.pop(v, None) or True)
    history.clear()


def run(capsys, extra):
    summary.cmd_summary(extra)
    return ANSI.sub("", capsys.readouterr().out)


# ---------------------------------------------------------------------------
# Flag parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "extra,expected",
    [
        ([], {"list": False, "sort": "plays", "top": 20, "clear": False}),
        (["-l"], {"list": True, "sort": "plays", "top": 20}),
        (["--list"], {"list": True}),
        (["-s", "artist"], {"sort": "artist"}),
        (["--sort", "name"], {"sort": "name"}),
        (["--sort=recent"], {"sort": "recent"}),
        (["-s", "ARTIST"], {"sort": "artist"}),
        (["--top", "5"], {"top": 5}),
        (["-n", "7"], {"top": 7}),
        (["--top=9"], {"top": 9}),
        (["-c"], {"clear": True}),
        (["--clear"], {"clear": True}),
        (["-h"], {"help": True}),
        (["-l", "-s", "name", "--top", "3"], {"list": True, "sort": "name", "top": 3}),
    ],
)
def test_parse_args(extra, expected):
    parsed = summary._parse_args(extra)
    for key, value in expected.items():
        assert parsed[key] == value, f"{extra} -> {key} was {parsed[key]!r}"


@pytest.mark.parametrize(
    "extra", [["-s", "bogus"], ["--sort=bogus"], ["--top", "abc"], ["--top", "0"], ["-s"]]
)
def test_parse_args_clamps_and_rejects(extra):
    parsed = summary._parse_args(extra)
    # A bad sort is signalled as None (the caller prints the error); a bad or
    # out-of-range --top falls back to the default rather than exploding.
    if "-s" in extra or any(a.startswith("--sort") for a in extra):
        assert parsed["sort"] is None or parsed["list"] is False
    assert 1 <= parsed["top"] <= 500


def test_parse_args_keeps_unknown_tokens_as_rest():
    parsed = summary._parse_args(["-l", "hello", "world"])
    assert parsed["rest"] == ["hello", "world"]


# ---------------------------------------------------------------------------
# Sorting — the CLI's per-song table
# ---------------------------------------------------------------------------

def test_default_sort_is_plays_descending(capsys):
    out = run(capsys, ["-l"])
    assert out.index("Around the World") < out.index("Teardrop")
    assert out.index("Teardrop") < out.index("Midnight City")


def test_sort_by_name(capsys):
    out = run(capsys, ["-l", "-s", "name"])
    assert out.index("Around the World") < out.index("Midnight City")
    assert out.index("Midnight City") < out.index("Teardrop")


def test_sort_by_artist(capsys):
    out = run(capsys, ["-l", "-s", "artist"])
    # Alphabetical by artist, then by title within an artist.
    assert out.index("Daft Punk") < out.index("M83")
    assert out.index("M83") < out.index("Massive Attack")


def test_sort_by_recent(capsys):
    out = run(capsys, ["-l", "-s", "recent"])
    # Midnight City was played last, so it leads the recent ordering.
    assert out.index("Midnight City") < out.index("Around the World")


def test_top_limits_the_table(capsys):
    out = run(capsys, ["-l", "--top", "1"])
    assert "Around the World" in out
    assert "Midnight City" not in out
    assert "showing 1 of 3" in out


def test_unknown_sort_prints_the_valid_keys(capsys):
    out = run(capsys, ["-l", "-s", "bogus"])
    assert "Unknown sort key" in out
    for key in summary.SORTS:
        assert key in out


def test_table_is_empty_before_anything_is_played(capsys):
    for video_id in ("sum-test-1", "sum-test-2", "sum-test-3"):
        library._mutate(lambda data, v=video_id: data.pop(v, None) or True)
    out = run(capsys, ["-l"])
    assert "Nothing has been played yet" in out


# ---------------------------------------------------------------------------
# The stats card
# ---------------------------------------------------------------------------

def test_stats_card_reports_both_stores(capsys):
    out = run(capsys, [])
    assert "combined plays" in out
    # 7 plays across 3 songs in library.db, 4 of them online events logged.
    assert re.search(r"combined plays\s+7\b", out)
    assert re.search(r"online plays\s+4\b", out)
    assert re.search(r"offline plays\s+3\b", out)
    assert re.search(r"unique songs\s+3\b", out)
    assert "history.db" in out


def test_stats_card_lists_the_top_artist(capsys):
    out = run(capsys, [])
    assert "Daft Punk" in out
    assert "4 plays" in out


def test_stats_card_lists_the_top_song(capsys):
    out = run(capsys, [])
    assert "top song" in out
    assert "Around the World (4 plays)" in out


def test_chart_stacks_online_and_offline_for_today(capsys):
    online = history.totals()["online_today"]
    offline = max(dict(library.play_days(7))[0] - online, 0)
    out = run(capsys, [])
    # The seed logs 4 streams today; the offline count comes from the bucket.
    assert online == 4
    assert offline >= 3
    assert re.search(rf"today\s+[█░]+\s*{online}/{offline}", out)


def test_summary_renders_week_progress_line(capsys):
    out = run(capsys, [])
    assert re.search(
        r"this week\s+[█░]+\s+\d+ vs \d+ plays · (no last-week plays|\d+% of last week)",
        out,
    )


def test_clear_wipes_both_stores(capsys):
    out = run(capsys, ["-c"])
    assert "Cleared 4" in out
    assert history.count() == 0
    # Both modes go to zero together, otherwise offline would swallow the lot.
    assert library.get_song_count("sum-test-1") == 0
    assert all(count == 0 for _, count in library.play_days(7))
    out = run(capsys, [])
    assert re.search(r"combined plays\s+0\b", out)
    assert re.search(r"online plays\s+0\b", out)
    assert re.search(r"offline plays\s+0\b", out)


def test_help_lists_every_flag(capsys):
    out = run(capsys, ["-h"])
    for flag in ("-l", "-s", "--top", "-c"):
        assert flag in out


# ---------------------------------------------------------------------------
# Sorting split: the CLI table is not the web timeline
# ---------------------------------------------------------------------------

def test_cli_sorts_and_web_sorts_are_different_sets():
    """The two halves of the feature rank different things on purpose."""
    assert set(summary.SORTS) == {"plays", "recent", "name", "artist"}
    assert set(history.SORTS) == {"recent", "oldest", "most", "least"}
    assert summary.SORTS != history.SORTS


# ---------------------------------------------------------------------------
# Full-width boxes — `flow --status` and `--summary` cards fill the terminal
# ---------------------------------------------------------------------------

def test_summary_box_spans_the_full_width(capsys):
    summary._box("Flow Summary", [("combined plays", "12")], 96)
    lines = ANSI.sub("", capsys.readouterr().out).splitlines()
    top, row, bottom, empty = lines
    assert top.startswith("┌─ Flow Summary ") and top.endswith("┐")
    assert len(top) == 96
    assert len(row) == 96 and row.endswith("│")
    assert len(bottom) == 96
    assert bottom.startswith("└") and bottom.endswith("┘")
    assert empty == ""


def test_status_box_spans_the_full_width(capsys, monkeypatch):
    from backend import config, status

    monkeypatch.setattr(status, "_tty_width", lambda: 96)
    status._print_plain(
        config.Primary, config.GREY, config.Reset, [("status", "playing", 7)]
    )
    lines = ANSI.sub("", capsys.readouterr().out).splitlines()
    _, top, row, bottom, empty = lines
    assert top.startswith("┌─ Flow Status ") and top.endswith("┐")
    assert len(top) == 96
    assert len(row) == 96 and row.endswith("│")
    assert len(bottom) == 96
    assert bottom.startswith("└") and bottom.endswith("┘")
    assert empty == ""
