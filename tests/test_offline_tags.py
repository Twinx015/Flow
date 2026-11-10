"""Tests for user tags: playback, export and the interactive tag menu.

Tags are now user-owned: a download never creates language or artist tags.
`songs_with_tag` reads the `song_tags` table, `tags play` queues every song in
a tag (`-s` shuffles, `-r` repeats), `tags random` plays one, and `tags export`
copies only that tag's files. The interactive menu is exercised through its
helpers so the real questionary prompts never run in tests.
"""

import argparse
import pathlib

import pytest

from backend import config, library, ui
from backend.Offline import commands as offline


def _args(**flags):
    args = argparse.Namespace(
        bg=False, download=False, repeat=False, shuffle=False, repeat_count=0, multi=False
    )
    for key, value in flags.items():
        setattr(args, key, value)
    return args


@pytest.fixture(autouse=True)
def fake_library(monkeypatch, tmp_path):
    with library._write() as conn:
        conn.execute("DELETE FROM song_tags")
    songs = {}
    for idx, name in enumerate(("Zed Track", "Alpha Track", "Mid Track", "Untuned")):
        video_id = f"tagplay{idx}"
        path = tmp_path / f"{video_id}.opus"
        path.write_bytes(b"")
        library.track_download(video_id, str(path), name)
        songs[name] = path

    library.set_song_tag("tagplay0", "roadtrip", True)
    library.set_song_tag("tagplay2", "roadtrip", True)
    library.set_song_tag("tagplay1", "gym", True)

    played = []
    args_seen = []

    def fake_play_queue(paths, args):
        played.extend(pathlib.Path(p) for p in paths)
        args_seen.append(args)

    monkeypatch.setattr(offline, "_play_queue", fake_play_queue)
    yield played, args_seen


def _names(played):
    """Only this module's rows: the scratch library.db is shared with other tests."""
    return [pathlib.Path(p).stem for p in played if "tagplay" in str(p)]


def test_tags_play_plays_every_song_in_a_tag(fake_library):
    played, _ = fake_library
    offline.tags_cmd(["play", "roadtrip"], _args())
    assert _names(played) == ["tagplay2", "tagplay0"]


def test_tags_play_matches_case_insensitively(fake_library):
    played, _ = fake_library
    offline.tags_cmd(["play", "RoadTrip"], _args())
    assert _names(played) == ["tagplay2", "tagplay0"]


def test_tags_play_with_no_match_says_so(fake_library, capsys):
    played, _ = fake_library
    offline.tags_cmd(["play", "nope"], _args())
    assert played == []
    assert "No downloaded songs tagged 'nope'" in capsys.readouterr().out


def test_s_shuffles_a_tag_queue(fake_library, monkeypatch):
    played, _ = fake_library
    monkeypatch.setattr(offline.random, "shuffle", lambda items: items.reverse())
    offline.run("tags", ["play", "roadtrip", "-s"], _args())
    assert _names(played) == ["tagplay0", "tagplay2"]


def test_r_repeats_a_tag_queue(fake_library):
    _, args_seen = fake_library
    offline.run("tags", ["play", "roadtrip", "-r", "3"], _args())
    assert args_seen[-1].repeat is True
    assert args_seen[-1].repeat_count == 3


def test_tags_random_plays_one_song_from_the_tag(fake_library, monkeypatch):
    played, _ = fake_library
    monkeypatch.setattr(offline.random, "choice", lambda paths: paths[0])
    offline.tags_cmd(["random", "roadtrip"], _args())
    assert len(_names(played)) == 1
    assert _names(played)[0] in {"tagplay0", "tagplay2"}


def test_tags_export_passes_only_that_tags_songs(fake_library, monkeypatch, tmp_path):
    _, _ = fake_library
    seen = {}
    monkeypatch.setattr(
        config,
        "export_flow",
        lambda dest, stems: seen.update(dest=dest, stems=stems) or (2, 0, dest),
    )
    dest = tmp_path / "out"
    offline.run("tags", ["export", "roadtrip", "-p", str(dest)], _args())
    assert seen["dest"] == str(dest)
    assert seen["stems"] == {"tagplay0", "tagplay2"}


def test_tags_add_and_remove_are_scriptable(fake_library):
    offline.tags_cmd(["add", "Untuned", "workout"], _args())
    assert library.song_tags("tagplay3") == ["workout"]
    offline.tags_cmd(["remove", "Untuned", "workout"], _args())
    assert library.song_tags("tagplay3") == []


def test_tags_list_shows_only_user_tags(fake_library, capsys):
    offline.tags_cmd(["list"], _args())
    out = capsys.readouterr().out
    assert "Tags:" in out
    assert "roadtrip (2)" in out
    assert "gym (1)" in out
    assert "Languages:" not in out
    assert "Artists:" not in out


def test_interactive_add_picks_a_tag_then_songs(fake_library, monkeypatch, capsys):
    monkeypatch.setattr(offline, "_pick_tag_or_new", lambda prompt, style: "workout")
    monkeypatch.setattr(
        offline, "_pick_songs", lambda prompt, rows=None: ["tagplay3"]
    )
    offline._edit_custom_add("style")
    assert library.song_tags("tagplay3") == ["workout"]
    assert "Tagged 1 song(s)" in capsys.readouterr().out


def test_interactive_remove_picks_a_tag_then_songs(fake_library, monkeypatch):
    monkeypatch.setattr(offline, "_pick_tag", lambda prompt: "roadtrip")
    monkeypatch.setattr(
        offline, "_pick_songs", lambda prompt, rows=None: ["tagplay0"]
    )
    offline._edit_custom_remove("style")
    assert library.song_tags("tagplay0") == []
    assert library.song_tags("tagplay2") == ["roadtrip"]


def test_interactive_play_all_uses_the_chosen_flags(fake_library, monkeypatch):
    played, args_seen = fake_library
    monkeypatch.setattr(offline, "_pick_tag", lambda prompt: "roadtrip")
    monkeypatch.setattr(ui, "pick", lambda q, c, **kw: ((True, False), True))
    offline._edit_play_all(_args(), "style")
    assert set(_names(played)) == {"tagplay0", "tagplay2"}
    assert args_seen[-1].shuffle is True
    assert args_seen[-1].repeat is False


def test_interactive_play_one_can_pick_random(fake_library, monkeypatch):
    played, _ = fake_library
    monkeypatch.setattr(offline, "_pick_tag", lambda prompt: "roadtrip")
    monkeypatch.setattr(ui, "pick", lambda q, c, **kw: ("random", True))
    monkeypatch.setattr(offline.random, "choice", lambda paths: paths[0])
    offline._edit_play_one(_args(), "style")
    assert len(_names(played)) == 1
    assert _names(played)[0] in {"tagplay0", "tagplay2"}


def test_interactive_export_uses_the_tag_and_typed_folder(
    fake_library, monkeypatch, tmp_path
):
    _, _ = fake_library
    seen = {}
    monkeypatch.setattr(offline, "_pick_tag", lambda prompt: "roadtrip")
    monkeypatch.setattr(offline, "_ask_text", lambda prompt, style, default="": str(tmp_path / "out"))
    monkeypatch.setattr(
        config,
        "export_flow",
        lambda dest, stems: seen.update(dest=dest, stems=stems) or (2, 0, dest),
    )
    offline._edit_export("style")
    assert seen["dest"] == str(tmp_path / "out")
    assert seen["stems"] == {"tagplay0", "tagplay2"}


def test_tags_rename_renames_a_tag_everywhere(fake_library):
    offline.tags_cmd(["rename", "roadtrip", "driving"], _args())
    assert library.song_tags("tagplay0") == ["driving"]
    assert library.song_tags("tagplay2") == ["driving"]
    assert library.all_song_tags() == [("driving", 2), ("gym", 1)]


def test_tags_delete_drops_a_tag_everywhere(fake_library):
    offline.tags_cmd(["delete", "roadtrip"], _args())
    assert library.all_song_tags() == [("gym", 1)]


def test_an_unknown_tags_action_lists_the_ones_that_work(capsys):
    offline.tags_cmd(["frobnicate"], _args())
    out = capsys.readouterr().out
    assert "tags add" in out
    assert "tags play" in out
    assert "tags export" in out


def test_song_tags_are_sorted_and_counted(fake_library):
    library.set_song_tag("tagplay0", "gym", True)
    assert library.song_tags("tagplay0") == ["gym", "roadtrip"]
    assert library.all_song_tags() == [("gym", 2), ("roadtrip", 2)]


def test_rename_tag_merges_instead_of_duplicating(fake_library):
    library.set_song_tag("tagplay0", "gym", True)
    library.set_song_tag("tagplay0", "workout", True)
    library.set_song_tag("tagplay1", "workout", True)
    assert library.rename_tag("workout", "gym") == 2
    assert library.song_tags("tagplay0") == ["gym", "roadtrip"]
    assert ("gym", 2) in library.all_song_tags()


def test_clearing_a_download_drops_its_tags(fake_library):
    library.clear_download("tagplay0")
    assert library.song_tags("tagplay0") == []


def test_tag_mutation_refuses_unknown_songs():
    assert not library.set_song_tag("ghost", "roadtrip", True)
