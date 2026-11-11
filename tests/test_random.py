"""`random [n]` plays random songs from the downloaded library.

The command is shared by both modes; online and offline dispatch to the same
offline queue helper, so these tests patch that helper and the song list.
"""

import argparse
import pathlib

import pytest

from backend.Offline import commands as offline
from backend.Online import commands as online


def _args():
    return argparse.Namespace(
        bg=False, download=False, repeat=False, shuffle=False, repeat_count=0, multi=False
    )


@pytest.fixture
def songs(monkeypatch):
    paths = [pathlib.Path(f"/tmp/random{index}.opus") for index in range(5)]
    played = []
    monkeypatch.setattr(offline.lib, "get_songs", lambda: paths)
    monkeypatch.setattr(
        offline, "_play_queue", lambda picks, args: played.extend(picks)
    )
    return paths, played


def test_random_plays_one_song_by_default(songs):
    paths, played = songs
    offline.random_songs([], _args())
    assert len(played) == 1
    assert played[0] in paths


def test_random_n_plays_that_many_songs(songs):
    paths, played = songs
    offline.random_songs(["3"], _args())
    assert len(played) == 3
    assert set(played) <= set(paths)


def test_random_caps_at_the_library_size(songs):
    paths, played = songs
    offline.random_songs(["99"], _args())
    assert sorted(played) == sorted(paths)


def test_random_rejects_a_zero_count(songs, capsys):
    _, played = songs
    offline.random_songs(["0"], _args())
    assert played == []
    assert "positive count" in capsys.readouterr().out


def test_random_rejects_extra_words(songs, capsys):
    _, played = songs
    offline.random_songs(["3", "more"], _args())
    assert played == []
    assert "Usage: random [n]" in capsys.readouterr().out


def test_run_dispatches_random(songs):
    paths, played = songs
    offline.run("random", ["2"], _args())
    assert len(played) == 2


def test_online_mode_uses_the_same_random_command(songs):
    paths, played = songs
    online.run("random", ["2"], _args())
    assert len(played) == 2
