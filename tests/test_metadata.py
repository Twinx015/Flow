"""`flow --meta` re-fetches metadata from the video id in each file name.

A run that hits YouTube's IP rate limit keeps `~/.flow/meta.json` and the next
invocation resumes from the first unfinished song. Non-block failures are
reported and skipped so one dead video cannot stall the whole library.
"""

import json

import pytest

from backend import config, library, metadata
from backend.Online import youtube

IDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]


def _write(directory, video_id, suffix=".opus"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{video_id}{suffix}"
    path.write_bytes(b"x")
    return path


def _info(video_id):
    return {
        "id": video_id,
        "title": f"Title {video_id}",
        "artist": "Artist",
        "album": "Album",
        "duration": 42,
        "thumbnail": "https://example.invalid/thumb.jpg",
    }


def test_ids_from_files_uses_video_id_stems(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", tmp_path)
    _write(tmp_path, IDS[0])
    _write(tmp_path, IDS[1], ".mp3")
    _write(tmp_path / "liked songs", IDS[0])
    _write(tmp_path, "not-an-id")
    (tmp_path / "ccccccccccc.txt").write_text("x")
    assert metadata._ids_from_files() == [IDS[0], IDS[1]]


def test_refetch_resumes_after_a_rate_limit(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(metadata, "_ids_from_files", lambda: list(IDS))
    monkeypatch.setattr(config, "META_FILE", tmp_path / "meta.json")
    updates = []
    monkeypatch.setattr(
        library, "update_meta", lambda video_id, meta: updates.append((video_id, meta))
    )
    monkeypatch.setattr(library, "download_thumbnail", lambda *a, **kw: None)
    monkeypatch.setattr(library, "get_title", lambda video_id: f"Title {video_id}")

    def blocked(video_id, raise_errors=False):
        if video_id == IDS[1]:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return _info(video_id)

    monkeypatch.setattr(youtube, "fetch_info", blocked)
    result = metadata.refetch_all()
    assert result["blocked"] is True
    assert [video_id for video_id, _ in updates] == [IDS[0]]
    state = json.loads(config.META_FILE.read_text())
    assert state["done"] == [IDS[0]]
    assert "rate-limiting" in capsys.readouterr().out

    calls = []

    def resumed(video_id, raise_errors=False):
        calls.append(video_id)
        return _info(video_id)

    monkeypatch.setattr(youtube, "fetch_info", resumed)
    result = metadata.refetch_all()
    assert result["blocked"] is False
    assert calls == [IDS[1], IDS[2]]
    assert not config.META_FILE.exists()
    assert [video_id for video_id, _ in updates] == IDS


def test_force_restarts_from_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(metadata, "_ids_from_files", lambda: list(IDS))
    monkeypatch.setattr(config, "META_FILE", tmp_path / "meta.json")
    config.META_FILE.write_text(
        json.dumps({"total": len(IDS), "done": list(IDS), "failed": {}})
    )
    calls = []
    monkeypatch.setattr(
        youtube,
        "fetch_info",
        lambda video_id, raise_errors=False: calls.append(video_id) or _info(video_id),
    )
    monkeypatch.setattr(library, "update_meta", lambda *a, **kw: None)
    monkeypatch.setattr(library, "download_thumbnail", lambda *a, **kw: None)
    result = metadata.refetch_all(force=True)
    assert calls == IDS
    assert result["blocked"] is False
    assert not config.META_FILE.exists()


def test_a_failed_song_is_skipped_and_the_run_finishes(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(metadata, "_ids_from_files", lambda: list(IDS))
    monkeypatch.setattr(config, "META_FILE", tmp_path / "meta.json")
    monkeypatch.setattr(library, "update_meta", lambda *a, **kw: None)
    monkeypatch.setattr(library, "download_thumbnail", lambda *a, **kw: None)
    monkeypatch.setattr(library, "get_title", lambda video_id: video_id)

    def fetch(video_id, raise_errors=False):
        if video_id == IDS[0]:
            raise RuntimeError("Video unavailable")
        return _info(video_id)

    monkeypatch.setattr(youtube, "fetch_info", fetch)
    result = metadata.refetch_all()
    assert result["blocked"] is False
    assert result["failed"] == {IDS[0]: "Video unavailable"}
    assert not config.META_FILE.exists()
    assert "1 skipped" in capsys.readouterr().out


def test_meta_from_info_populates_title_artist_album_and_duration():
    meta = metadata._meta_from_info(
        {"title": "Night Changes", "artist": "Artist", "album": "Album", "duration": "180"}
    )
    assert meta == {
        "album": "Album",
        "duration": 180,
        "title": "Night Changes",
        "artist": "Artist",
    }


def test_meta_from_info_tile_cleans_raw_youtube_titles(monkeypatch):
    monkeypatch.setattr(config, "SearchSource", "ytmusic")
    meta = metadata._meta_from_info(
        {"title": "One Direction - Night Changes (Official Video)"}
    )
    assert meta["title"] == "Night Changes"


def test_meta_from_info_falls_back_to_uploader():
    assert metadata._meta_from_info({"title": "Song", "uploader": "Channel"})["artist"] == "Channel"


@pytest.mark.parametrize(
    "text",
    [
        "HTTP Error 429: Too Many Requests",
        "Sign in to confirm you're not a bot",
        "This request was blocked",
        "Too many requests",
        "Unusual traffic detected",
        "Please solve the captcha",
    ],
)
def test_block_messages_are_recognised(text):
    assert youtube.is_rate_limited(RuntimeError(text)) is True


@pytest.mark.parametrize(
    "text",
    [
        "Video unavailable",
        "Sign in to confirm your age",
        "Private video",
        "Requested format is not available",
    ],
)
def test_other_failures_are_not_treated_as_a_block(text):
    assert youtube.is_rate_limited(RuntimeError(text)) is False


def test_fetch_info_only_raises_when_asked(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(youtube.sponsor, "stream_info", boom)
    assert youtube.fetch_info(IDS[0]) is None
    with pytest.raises(RuntimeError):
        youtube.fetch_info(IDS[0], raise_errors=True)
