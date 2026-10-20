"""`youtube.download_url` retries transient failures before giving up.

The web `/download` route used to wrap its download in an outer 3-attempt
loop; that loop now lives in the backend so the CLI, `flow-min` and the web
all retry the same way (2s, then 4s, between attempts).
"""

from backend.Online import youtube


class FlakyYDL:
    """A YoutubeDL stand-in whose first `fail` extract_info calls raise."""

    calls = 0
    fail = 0

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        FlakyYDL.calls += 1
        if FlakyYDL.calls <= FlakyYDL.fail:
            raise RuntimeError("transient failure")
        return {"id": "vid00000001", "title": "Song"}

    def prepare_filename(self, info):
        return "/downloads/vid00000001.webm"


def _patch_side_effects(monkeypatch):
    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", FlakyYDL)
    monkeypatch.setattr(youtube.library, "track_download", lambda *a, **k: None)
    monkeypatch.setattr(youtube.library, "download_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(youtube.library, "meta_from_info", lambda info: {})
    monkeypatch.setattr(youtube.config, "down_notify", lambda *a, **k: None)
    monkeypatch.setattr(youtube.time, "sleep", lambda s: None)


def test_succeeds_after_transient_failures(monkeypatch):
    _patch_side_effects(monkeypatch)
    FlakyYDL.calls = 0
    FlakyYDL.fail = 2
    result = youtube.download_url("https://www.youtube.com/watch?v=vid00000001", "/downloads")
    assert result == "/downloads/vid00000001.webm"
    assert FlakyYDL.calls == 3


def test_gives_up_after_three_attempts(monkeypatch):
    _patch_side_effects(monkeypatch)
    FlakyYDL.calls = 0
    FlakyYDL.fail = 99
    try:
        youtube.download_url("https://www.youtube.com/watch?v=vid00000001", "/downloads")
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    assert FlakyYDL.calls == youtube.DOWNLOAD_ATTEMPTS
