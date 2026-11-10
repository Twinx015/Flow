"""YouTube link support for `play`, `search` and `download`.

A pasted watch/short/share link must play (or download) that exact video
instead of being sent to the search API. The parsing lives in
`youtube.video_id_from_url`; `youtube.search` returns a single resolved result
for a link, and the commands skip their result picker for it.
"""

import argparse

import pytest

from backend.Online import commands as online
from backend.Online import youtube
from minimal import core

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "text",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&list=RD{VIDEO_ID}",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?t=42",
        f"youtu.be/{VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
    ],
)
def test_video_id_from_url_accepts_links(text):
    assert youtube.video_id_from_url(text) == VIDEO_ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "never gonna give you up",
        f"https://example.com/watch?v={VIDEO_ID}",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch",
        f"https://www.youtube.com/watch?v={VIDEO_ID} extra",
    ],
)
def test_video_id_from_url_rejects_other_input(text):
    assert youtube.video_id_from_url(text) is None


def _entry():
    return {
        "id": VIDEO_ID,
        "title": "Never Gonna Give You Up",
        "duration": 213,
        "formats": [{"url": "https://example.invalid/audio"}],
        "webpage_url": f"https://www.youtube.com/watch?v={VIDEO_ID}",
    }


def test_search_resolves_a_link_instead_of_searching(monkeypatch):
    entry = _entry()
    seen = []
    monkeypatch.setattr(youtube, "get_entry", lambda url: seen.append(url) or entry)
    monkeypatch.setattr(
        youtube, "_search_music", lambda *a, **k: pytest.fail("searched music")
    )
    monkeypatch.setattr(
        youtube, "_search_youtube", lambda *a, **k: pytest.fail("searched youtube")
    )
    results = youtube.search(f"https://youtu.be/{VIDEO_ID}")
    assert results == [(entry, "Never Gonna Give You Up", 213)]
    assert seen == [f"https://www.youtube.com/watch?v={VIDEO_ID}"]


def _args(**flags):
    args = argparse.Namespace(
        bg=False,
        download=False,
        repeat=False,
        repeat_count=0,
        shuffle=False,
        multi=False,
        format=None,
    )
    for key, value in flags.items():
        setattr(args, key, value)
    return args


def _quiet_online(monkeypatch):
    monkeypatch.setattr(online.config, "kill_stored", lambda: False)
    monkeypatch.setattr(online, "_clear_all_nav", lambda: None)
    monkeypatch.setattr(
        online, "_pick_indices", lambda *a, **k: pytest.fail("picker was shown")
    )


def test_play_a_link_skips_the_picker(monkeypatch):
    entry = _entry()
    seen = []
    played = []
    _quiet_online(monkeypatch)
    monkeypatch.setattr(
        online,
        "_do_search",
        lambda query: seen.append(query)
        or setattr(online, "_last_results", [(entry, entry["title"], 213)]),
    )
    monkeypatch.setattr(
        online.player, "play_entry", lambda e, t, a, **k: played.append((e, t))
    )
    url = f"https://youtu.be/{VIDEO_ID}"
    online.play([url], _args())
    assert seen == [url]
    assert played == [(entry, "Never Gonna Give You Up")]


def test_search_a_link_plays_it_without_a_picker(monkeypatch):
    entry = _entry()
    played = []
    _quiet_online(monkeypatch)
    monkeypatch.setattr(
        online,
        "_do_search",
        lambda query: setattr(online, "_last_results", [(entry, entry["title"], 213)]),
    )
    monkeypatch.setattr(
        online.player, "play_entry", lambda e, t, a, **k: played.append((e, t))
    )
    online.search(f"https://www.youtube.com/watch?v={VIDEO_ID}", _args())
    assert played == [(entry, "Never Gonna Give You Up")]


def test_download_a_link_skips_the_picker(monkeypatch):
    entry = _entry()
    downloaded = []
    _quiet_online(monkeypatch)
    monkeypatch.setattr(
        online,
        "_do_search",
        lambda query: setattr(online, "_last_results", [(entry, entry["title"], 213)]),
    )
    monkeypatch.setattr(
        online, "_download_one", lambda e, fmt: downloaded.append((e, fmt))
    )
    online.download([f"https://youtu.be/{VIDEO_ID}"], _args(format="webm"))
    assert downloaded == [(entry, "webm")]


def test_flow_min_play_a_link_fetches_only_that_video(monkeypatch):
    entry = _entry()
    seen = []
    played = []
    monkeypatch.setattr(youtube, "get_entry", lambda url: seen.append(url) or entry)
    monkeypatch.setattr(
        core.youtube, "search", lambda *a, **k: pytest.fail("search was called")
    )
    monkeypatch.setattr(
        core, "_play_online", lambda info, title, **k: played.append((info, title))
    )
    core.play(f"https://youtu.be/{VIDEO_ID}")
    assert seen == [f"https://www.youtube.com/watch?v={VIDEO_ID}"]
    assert played == [(entry, "Never Gonna Give You Up")]
