"""Tests for `minimal/`, the plain non-interactive front end.

`minimal` is the surface an agent or a bare ssh terminal uses, so what matters
here is not the music but the contract around it:

* output is plain lines, or exactly one JSON document with `--json`, and never
  ANSI escapes;
* every backend call runs inside `out.quiet()`, so spinners, questionary and
  yt-dlp chatter cannot leak into that output (including from threads);
* failures exit non-zero with a message on stderr, and `--json` callers get an
  error document instead of a half-printed list;
* control commands signal a running player and never raise on their own;
* the parser keeps multi-word arguments in one piece, which is the one thing
  that silently broke plain usage before (`rename Foo` became `F o o`);
* `search` remembers its rows so `play <index>` can pick one without
  searching again, and says so plainly when nothing is saved.

Tests share the scratch `HOME` from `conftest.py` and never fork or open an
audio stream, so every row they add uses a video id unique to this module.

Titles here avoid the filler words `backend.config` strips on write
(`song`, `old`, `official`, ...), since `library.track_download` runs them
through `config._truncate_title`.
"""

import json
import os
import pathlib
import signal
import sys
import threading
import time

import pytest

from backend import config, history, library, registry, status
from minimal import core, extras, local, main, out, stats

IDS = {
    "list": "minlist000001",
    "list_other": "minlist000002",
    "delete": "mindelete00001",
    "rename": "minrename00001",
    "status": "minstatus00001",
    "tags": "mintags0000001",
    "history": "minhistory0001",
}

SIGNALS = (
    "SIG_STOP",
    "SIG_NEXT",
    "SIG_PREV",
    "SIG_SEEK_FWD",
    "SIG_SEEK_BWD",
    "SIG_STOP_ALL",
)


@pytest.fixture(autouse=True)
def harmless_signals():
    """Control tests signal the test process itself; a real-time signal would kill it."""
    saved = {}
    for name in SIGNALS:
        sig = getattr(config, name, None)
        if sig is None:
            continue
        try:
            saved[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_: None)
        except (OSError, ValueError):
            pass
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture(autouse=True)
def clean_state():
    """Drop the rows, status file and player records this module adds."""
    before = set(library.load())
    registry.clear()
    status.STATUS_FILE.unlink(missing_ok=True)
    core.SEARCH_FILE.unlink(missing_ok=True)
    yield
    for video_id in set(library.load()) - before:
        library._mutate(lambda data, v=video_id: data.pop(v, None) or True)
        library.clear_song_tags(video_id)
    registry.clear()
    status.STATUS_FILE.unlink(missing_ok=True)
    core.SEARCH_FILE.unlink(missing_ok=True)


def start(as_json=False):
    """Point `out` at the descriptors pytest is capturing for this call phase."""
    out.init(as_json)


def read(capfd):
    """Everything `out`, `print` and stderr produced since the last read."""
    captured = capfd.readouterr()
    return captured.out, captured.err


def _downloaded(video_id, title, meta=None):
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = config.DOWNLOAD_DIR / f"{video_id}.opus"
    path.write_bytes(b"not really audio")
    library.track_download(video_id, str(path), title, meta=meta or {})
    return path


def test_emit_prints_plain_lines(capfd):
    start()
    out.emit({"a": 1}, ["first", "second"])
    assert read(capfd)[0] == "first\nsecond\n"


def test_emit_single_text(capfd):
    start()
    out.emit(None, "only")
    assert read(capfd)[0] == "only\n"


def test_json_mode_emits_one_document(capfd):
    start(as_json=True)
    out.emit([{"video_id": "abc"}], "ignored in json mode")
    assert json.loads(read(capfd)[0]) == [{"video_id": "abc"}]


def test_fail_exits_non_zero_with_a_message(capfd):
    start()
    with pytest.raises(SystemExit) as exit_info:
        out.fail("nothing to play")
    assert exit_info.value.code == 1
    stdout, stderr = read(capfd)
    assert stdout == ""
    assert stderr == "flow-min: nothing to play\n"


def test_fail_gives_json_callers_an_error_document(capfd):
    start(as_json=True)
    with pytest.raises(SystemExit):
        out.fail("nothing to play")
    stdout, stderr = read(capfd)
    assert json.loads(stdout) == {"error": "nothing to play"}
    assert "nothing to play" in stderr


def test_quiet_drops_stdout_and_stderr(capfd):
    start()
    with out.quiet():
        os.write(1, b"backend noise\n")
        os.write(2, b"warning\n")
    out.emit(None, "mine")
    assert read(capfd) == ("mine\n", "")


def test_quiet_drops_output_from_threads(capfd):
    def spin():
        for _ in range(50):
            os.write(1, b"spinner frame\n")
            time.sleep(0.001)

    start()
    worker = threading.Thread(target=spin)
    with out.quiet():
        worker.start()
        worker.join()
    out.emit(None, "mine")
    assert read(capfd)[0] == "mine\n"


def test_output_carries_no_ansi_escapes(capfd):
    _downloaded(IDS["list"], "Plain Anthem", {"artist": "Nobody", "language": "hindi"})
    start()
    local.list_songs()
    text = read(capfd)[0]
    assert "\033[" not in text
    assert "Plain Anthem - Nobody" in text


def _fake_search(*_args, **_kwargs):
    return [
        ({"id": "minsrch000001"}, "First Result", 180),
        ({"id": "minsrch000002"}, "Second Result", 200),
    ]


def test_search_saves_rows_for_play(capfd, monkeypatch):
    monkeypatch.setattr(core.youtube, "search", _fake_search)
    start()
    core.search("some query")
    assert read(capfd)[0].startswith("1. First Result (3:00)\n")
    saved = json.loads(core.SEARCH_FILE.read_text())
    assert saved["query"] == "some query"
    assert [r["title"] for r in saved["results"]] == ["First Result", "Second Result"]
    assert saved["results"][1]["url"].endswith("minsrch000002")


def test_play_bare_index_plays_the_saved_row(capfd, monkeypatch):
    core.SEARCH_FILE.write_text(
        json.dumps(
            {
                "query": "q",
                "results": [
                    {
                        "url": "https://www.youtube.com/watch?v=first",
                        "title": "First Result",
                    },
                    {
                        "url": "https://www.youtube.com/watch?v=second",
                        "title": "Second Result",
                    },
                ],
            }
        )
    )
    seen = {}
    monkeypatch.setattr(
        core.youtube, "get_entry", lambda url: seen.update(url=url) or {"id": "x"}
    )
    monkeypatch.setattr(
        core, "_play_online", lambda info, title, **kw: seen.update(title=title)
    )
    start()
    core.play("2")
    assert seen["url"].endswith("second")
    assert seen["title"] == "Second Result"


def test_play_index_without_a_saved_search_fails(capfd):
    core.SEARCH_FILE.unlink(missing_ok=True)
    start()
    with pytest.raises(SystemExit) as exc:
        core.play("1")
    assert exc.value.code == 1
    assert "no saved search" in read(capfd)[1]


def test_play_index_out_of_range_fails(capfd):
    core.SEARCH_FILE.write_text(
        json.dumps({"query": "q", "results": [{"url": "u", "title": "Only Result"}]})
    )
    start()
    with pytest.raises(SystemExit) as exc:
        core.play("5")
    assert exc.value.code == 1
    assert "out of range (1-1)" in read(capfd)[1]


def test_play_with_words_still_searches(capfd, monkeypatch):
    calls = {"search": 0}

    def fake_search(query, limit):
        calls["search"] += 1
        return _fake_search()

    monkeypatch.setattr(core.youtube, "search", fake_search)
    monkeypatch.setattr(core.youtube, "get_entry", lambda url: {"id": "minsrch000002"})
    monkeypatch.setattr(core, "_play_online", lambda info, title, **kw: None)
    start()
    core.play("some words", index=2)
    assert calls["search"] == 1


def test_status_without_a_player_is_stopped(capfd):
    start()
    core.status_cmd()
    assert read(capfd)[0] == "stopped\n"


def test_status_reports_the_playing_track(capfd):
    _downloaded(IDS["status"], "Status Anthem", {"artist": "Someone", "duration": 100})
    status.update("Status Anthem", 100, playing=True, thumbnail=library.thumbnail_path(IDS["status"]))
    registry.register("vlc", os.getpid())
    start(as_json=True)
    core.status_cmd()
    payload = json.loads(read(capfd)[0])
    assert payload["state"] == "playing"
    assert payload["title"] == "Status Anthem"
    assert payload["artist"] == "Someone"
    assert payload["video_id"] == IDS["status"]


def test_status_reports_paused(capfd):
    status.update("Marathon", 100, playing=False)
    registry.register("vlc", os.getpid())
    start(as_json=True)
    core.status_cmd()
    assert json.loads(read(capfd)[0])["state"] == "paused"


def test_status_json_still_answers_when_stopped(capfd):
    _downloaded(IDS["status"], "Marathon", {"artist": "Someone"})
    status.update("Marathon", 100, playing=False)
    start(as_json=True)
    core.status_cmd()
    payload = json.loads(read(capfd)[0])
    assert payload["state"] == "stopped"
    assert payload["title"] == "Marathon"
    assert payload["pid"] is None


def test_control_without_a_player_fails(capfd):
    start()
    for command in (core.pause, core.next_track, core.prev_track):
        with pytest.raises(SystemExit) as exit_info:
            command()
        assert exit_info.value.code == 1
    assert read(capfd)[1].count("no player running") == 3


def test_seek_writes_the_delta_before_signalling(capfd):
    from backend import ipc as _ipc

    # Linux signals the player; macOS/Windows have no seek signal, so deliver
    # over the same localhost control socket a real player would use.
    port = None if _ipc.signal_for("seek_fwd") is not None else _ipc._start_server()
    registry.register("vlc", os.getpid(), ctl_port=port)
    try:
        start()
        core.seek(30)
        assert "ok  seek forward 30s" in read(capfd)[0]
        assert config.read_seek() == 30000
        core.seek(10, back=True)
        assert "ok  seek back 10s" in read(capfd)[0]
        assert config.read_seek() == -10000
        config.clear_seek()
    finally:
        registry.clear()
        config.clear_seek()


def test_list_songs_is_sorted_and_filterable(capfd):
    _downloaded(IDS["list_other"], "Zebra Anthem", {"artist": "Beta", "duration": 10})
    _downloaded(IDS["list"], "Apple Anthem", {"artist": "Alpha", "duration": 20})
    start()
    local.list_songs(query="Anthem")
    titles = [line.split(" - ")[0] for line in read(capfd)[0].strip().splitlines()]
    assert titles == sorted(titles, key=str.lower)
    assert "Apple Anthem" in titles and "Zebra Anthem" in titles

    local.list_songs(query="alpha")
    filtered = read(capfd)[0]
    assert "Apple Anthem" in filtered and "Zebra Anthem" not in filtered


def test_list_songs_json_keeps_metadata(capfd):
    _downloaded(IDS["list"], "Json Anthem", {"artist": "Someone", "language": "punjabi", "duration": 42})
    start(as_json=True)
    local.list_songs(query="Json Anthem")
    row = json.loads(read(capfd)[0])["songs"][0]
    assert row["title"] == "Json Anthem"
    assert row["artist"] == "Someone"
    assert row["language"] == "punjabi"
    assert row["duration"] == 42


def test_list_info_shows_artist_paths_and_thumbnail(capfd):
    path = _downloaded(IDS["list"], "Info Anthem", {"artist": "Alpha"})
    start()
    local.list_songs(query="Info Anthem", info=True)
    line = read(capfd)[0].strip()
    assert line.startswith("1. Info Anthem | Alpha | ")
    assert str(path) in line
    assert str(library.thumbnail_path(IDS["list"])) in line


def test_list_info_json_includes_the_thumbnail_path(capfd):
    path = _downloaded(IDS["list"], "Info Anthem", {"artist": "Alpha"})
    start(as_json=True)
    local.list_songs(query="Info Anthem", info=True)
    row = json.loads(read(capfd)[0])["songs"][0]
    assert row["path"] == str(path)
    assert row["thumbnail"] == str(library.thumbnail_path(IDS["list"]))


def test_play_random_samples_the_library(monkeypatch):
    paths = [pathlib.Path(f"/tmp/rand{index}.opus") for index in range(5)]
    seen = []
    monkeypatch.setattr(core.lib, "get_songs", lambda: paths)
    monkeypatch.setattr(core, "play_paths", lambda picks, **kw: seen.extend(picks))
    core.play_random(3)
    assert len(seen) == 3
    assert set(seen) <= set(paths)


def test_play_random_caps_at_the_library_size(monkeypatch):
    paths = [pathlib.Path("/tmp/only.opus")]
    seen = []
    monkeypatch.setattr(core.lib, "get_songs", lambda: paths)
    monkeypatch.setattr(core, "play_paths", lambda picks, **kw: seen.extend(picks))
    core.play_random(10)
    assert seen == paths


def test_rename_uses_the_previous_name(capfd):
    _downloaded(IDS["rename"], "Anthem")
    start()
    local.rename("Anthem", "Marathon")
    assert read(capfd)[0].strip() == "renamed  Anthem -> Marathon"
    assert library.get_title(IDS["rename"]) == "Marathon"


def test_delete_removes_the_file_and_the_row(capfd):
    path = _downloaded(IDS["delete"], "Doomed Anthem")
    start()
    local.delete("Doomed Anthem")
    assert "deleted  Doomed Anthem" in read(capfd)[0]
    assert not path.exists()
    assert not library.get_download_path(IDS["delete"])


def test_delete_refuses_an_ambiguous_name(capfd):
    _downloaded(IDS["list"], "Twin Anthem One")
    kept = _downloaded(IDS["list_other"], "Twin Anthem Two")
    start()
    with pytest.raises(SystemExit) as exit_info:
        local.delete("Twin Anthem")
    assert exit_info.value.code == 2
    stdout, stderr = read(capfd)
    assert "be more specific" in stderr
    assert "Twin Anthem One" in stdout and "Twin Anthem Two" in stdout
    assert kept.exists()


def test_tags_lists_user_tags(capfd):
    _downloaded(IDS["tags"], "Tagged Anthem")
    library.set_song_tag(IDS["tags"], "workout", True)
    start(as_json=True)
    extras.tags()
    rows = json.loads(read(capfd)[0])
    assert {"kind": "tag", "tag": "workout", "count": 1} in rows
    assert all(row["kind"] == "tag" for row in rows)


def test_tags_play_loads_every_tagged_song(monkeypatch):
    first = _downloaded(IDS["tags"], "Tagged Anthem")
    second = _downloaded(IDS["list_other"], "Second Tagged")
    library.set_song_tag(IDS["tags"], "workout", True)
    library.set_song_tag(IDS["list_other"], "workout", True)
    seen = {}
    monkeypatch.setattr(
        core, "play_paths", lambda paths, **kw: seen.update(paths=paths, **kw)
    )
    start()
    extras.tags("play", ["workout"], shuffle=True, repeat=True)
    assert {pathlib.Path(p).stem for p in seen["paths"]} == {first.stem, second.stem}
    assert seen["shuffle"] is True
    assert seen["repeat"] is True


def test_tags_random_plays_one_tagged_song(monkeypatch):
    _downloaded(IDS["tags"], "Tagged Anthem")
    library.set_song_tag(IDS["tags"], "workout", True)
    seen = {}
    monkeypatch.setattr(
        core, "play_paths", lambda paths, **kw: seen.update(paths=paths, **kw)
    )
    start()
    extras.tags("random", ["workout"])
    assert [pathlib.Path(p).stem for p in seen["paths"]] == [IDS["tags"]]
    assert seen["shuffle"] is False
    assert seen["repeat"] is False


def test_tags_export_only_copies_that_tags_songs(capfd, monkeypatch, tmp_path):
    _downloaded(IDS["tags"], "Tagged Anthem")
    library.set_song_tag(IDS["tags"], "workout", True)
    seen = {}
    monkeypatch.setattr(
        config,
        "export_flow",
        lambda dest, stems: seen.update(dest=dest, stems=stems) or (1, 0, dest),
    )
    start(as_json=True)
    dest = tmp_path / "out"
    extras.tags("export", ["workout", "-p", str(dest)])
    payload = json.loads(read(capfd)[0])
    assert seen["dest"] == str(dest)
    assert seen["stems"] == {IDS["tags"]}
    assert payload["status"] == "exported"
    assert payload["songs"] == 1


def test_history_and_stats_read_the_log(capfd):
    history.clear()
    history.record_play(IDS["history"], "Logged Anthem", "Someone")
    start(as_json=True)
    stats.history_cmd(limit=5)
    log = json.loads(read(capfd)[0])
    stats.stats()
    summary = json.loads(read(capfd)[0])
    assert log[0]["title"] == "Logged Anthem"
    assert summary["online_plays"] >= 1
    assert summary["unique_songs"] >= 1


def test_unknown_history_range_fails(capfd):
    start()
    with pytest.raises(SystemExit):
        stats.history_cmd(since="lastweek")
    assert "unknown range" in read(capfd)[1]


def test_parser_covers_every_command():
    samples = [
        ["status"],
        ["play", "karan", "aujla"],
        ["play", "anthem", "-i", "2", "-s"],
        ["play", "anthem", "--fg"],
        ["play-off", "52", "bars"],
        ["resume"],
        ["resume", "--fg"],
        ["search", "arijit", "singh", "--limit", "3"],
        ["stop"],
        ["pause"],
        ["next"],
        ["prev"],
        ["seek", "30"],
        ["seek-back", "10"],
        ["list", "--query", "karan", "--limit", "5"],
        ["ls"],
        ["ls", "-i"],
        ["ls", "--info"],
        ["liked"],
        ["liked", "--limit", "2"],
        ["like"],
        ["unlike"],
        ["download", "karan", "aujla", "-f", "opus"],
        ["dl", "anthem"],
        ["delete", "some", "anthem"],
        ["rename", "some", "anthem", "--to", "New", "Name"],
        ["radio", "karan", "aujla"],
        ["radio", "--limit", "10"],
        ["radio-off", "--limit", "5"],
        ["tags"],
        ["tags", "list"],
        ["tags", "add", "some", "anthem", "workout"],
        ["tags", "remove", "some", "anthem", "workout"],
        ["tags", "rename", "workout", "gym"],
        ["tags", "delete", "workout"],
        ["tags", "play", "workout", "-s"],
        ["tags", "play", "workout", "-r"],
        ["tags", "random", "workout"],
        ["tags", "export", "workout", "-p", "/tmp/out"],
        ["lyrics"],
        ["playlist", "chill"],
        ["pl", "chill", "create"],
        ["playlist", "chill", "add", "some", "anthem"],
        ["playlist", "chill", "remove", "-i", "2"],
        ["playlist", "chill", "play"],
        ["playlist", "chill", "delete"],
        ["history", "--sort", "most", "--limit", "3", "--since", "7d"],
        ["history", "--sort", "oldest"],
        ["stats"],
    ]
    parser = main.build_parser()
    for argv in samples:
        args = parser.parse_args(argv)
        assert callable(getattr(args, "func", None)), argv


def test_parser_keeps_multi_word_arguments_whole():
    parser = main.build_parser()
    assert parser.parse_args(["play", "karan", "aujla"]).query == ["karan", "aujla"]
    assert parser.parse_args(["play-off", "52", "bars"]).query == ["52", "bars"]
    assert parser.parse_args(["search", "arijit", "singh"]).query == ["arijit", "singh"]
    assert parser.parse_args(["delete", "some", "anthem"]).query == ["some", "anthem"]
    assert parser.parse_args(["rename", "old", "anthem", "--to", "New", "Name"]).new_name == ["New", "Name"]
    assert parser.parse_args(["rename", "old", "anthem", "--to", "New", "Name"]).query == ["old", "anthem"]


def test_random_flag_defaults_to_one_song():
    parser = main.build_parser()
    assert parser.parse_args(["--random"]).random == 1
    assert parser.parse_args(["--random", "4"]).random == 4
    assert parser.parse_args(["ls", "-i"]).info is True


def test_repeat_flag_parses_for_playback_and_random():
    parser = main.build_parser()
    assert parser.parse_args(["play", "anthem", "-r"]).repeat == 0
    assert parser.parse_args(["play", "anthem", "-r", "3"]).repeat == 3
    assert parser.parse_args(["play-off", "anthem", "--repeat", "2"]).repeat == 2
    assert parser.parse_args(["--random", "3", "-r"]).global_repeat == 0
    assert parser.parse_args(["--random", "3", "-r", "4"]).global_repeat == 4


def test_play_off_forwards_repeat_to_the_queue(monkeypatch):
    seen = {}
    monkeypatch.setattr(core.lib, "find_songs", lambda query: ["/tmp/anthem.opus"])
    monkeypatch.setattr(core, "_play_file", lambda path, **kw: seen.update(kw))
    core.play_off("anthem", repeat=True, repeat_count=2)
    assert seen["repeat"] is True
    assert seen["repeat_count"] == 2


def test_play_random_forwards_repeat(monkeypatch):
    paths = [pathlib.Path(f"/tmp/rand{index}.opus") for index in range(3)]
    seen = {}
    monkeypatch.setattr(core.lib, "get_songs", lambda: paths)
    monkeypatch.setattr(
        core, "play_paths", lambda picks, **kw: seen.update(kw)
    )
    core.play_random(2, repeat=True, repeat_count=5)
    assert seen["repeat"] is True
    assert seen["repeat_count"] == 5


def test_online_repeat_uses_the_backend_queue(monkeypatch, capfd):
    seen = {}
    monkeypatch.setattr(
        core.on_commands,
        "_play_queue",
        lambda results, args: seen.update(results=results, args=args),
    )
    info = {"id": "minsrch000001", "duration": 10}
    start()
    core._play_online(info, "Repeat Anthem", foreground=True, repeat=True, repeat_count=3)
    assert seen["args"].repeat is True
    assert seen["args"].repeat_count == 3
    assert seen["results"] == [(info, "Repeat Anthem", 10)]
    assert "played  Repeat Anthem" in read(capfd)[0]


def test_local_repeat_uses_the_backend_queue(monkeypatch, capfd):
    seen = {}
    monkeypatch.setattr(
        core.off_commands,
        "_play_queue",
        lambda paths, args: seen.update(paths=paths, args=args),
    )
    monkeypatch.setattr(core.lib, "display_name", lambda path: "Repeat Anthem")
    start()
    core._play_file("/tmp/anthem.opus", foreground=True, repeat=True, repeat_count=2)
    assert seen["args"].repeat is True
    assert seen["args"].repeat_count == 2
    assert [str(path) for path in seen["paths"]] == ["/tmp/anthem.opus"]


def test_namespace_defaults_do_not_double_fork():
    """`minimal` forks itself, so the args it hands the backend must say bg=False."""
    from minimal.common import ns

    assert ns().bg is True
    assert ns(bg=False).bg is False


def test_entry_url_covers_both_shapes():
    from minimal.common import entry_url

    assert entry_url({"id": "abc"}) == "https://www.youtube.com/watch?v=abc"
    assert entry_url({"video_id": "xyz"}) == "https://www.youtube.com/watch?v=xyz"
    assert entry_url("https://youtu.be/direct") == "https://youtu.be/direct"
