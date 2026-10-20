"""`api` push tests.

When `config api <url>` is set, flow POSTs `/now` (current song, artist,
playlist) and `/summary` (the full --summary payload) after every recorded
play. These tests stand up a local HTTP capture server and pin the payload
shapes, the disabled short-circuit, and the config-key validation.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend import api, config, history, library


class _Capture(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.received.append((self.path, body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def capture():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Capture)
    server.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old_url = config.ApiUrl
    config.ApiUrl = f"http://127.0.0.1:{server.server_port}"
    api.set_playlist("")
    api._inflight.clear()
    yield server.received
    config.ApiUrl = old_url
    api._inflight.clear()
    api.set_playlist("")
    server.shutdown()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    history.clear()
    library._mutate(lambda data: data.pop("api-t1", None) or True)


def _wait(capture, count, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline and len(capture) < count:
        time.sleep(0.02)
    assert len(capture) >= count, f"only {len(capture)}/{count} pushes arrived"


def test_push_now_payload(capture):
    api.set_playlist("Road Mix")
    api.push_now("52 Bars", "Karan Aujla")
    _wait(capture, 1)
    path, body = capture[0]
    assert path == "/now"
    assert body["title"] == "52 Bars"
    assert body["artist"] == "Karan Aujla"
    assert body["playlist"] == "Road Mix"
    assert body["mode"] == config.Mode
    assert "at" in body


def test_disabled_url_sends_nothing():
    old = config.ApiUrl
    config.ApiUrl = ""
    try:
        api.push_now("x", "y")
        assert api.playlist_name() == ""
        assert not api._inflight
    finally:
        config.ApiUrl = old


def test_summary_payload_shape():
    history.record_play("api-t1", "Song A", "Artist A", mode="offline")
    payload = api.summary_payload()
    assert set(payload) >= {"totals", "tops", "last_7_days", "songs", "mode"}
    assert payload["totals"]["unique_songs"] >= 1
    assert payload["totals"]["offline_plays"] >= 1
    row = next(r for r in payload["songs"] if r["title"] == "Song A")
    assert row["artist"] == "Artist A"
    assert row["song_count"] == 1
    assert payload["tops"]["artist"] == "Artist A"
    assert len(payload["last_7_days"]) == 7


def test_push_summary_posts_document(capture):
    history.record_play("api-t1", "Song A", "Artist A", mode="offline")
    api.push_summary()
    _wait(capture, 1)
    path, body = capture[0]
    assert path == "/summary"
    assert any(r["title"] == "Song A" for r in body["songs"])
    assert body["totals"]["unique_songs"] >= 1


def test_apply_api_validation_and_roundtrip():
    old = config.ApiUrl
    try:
        assert "set to" in config._apply_api("http://127.0.0.1:8000")
        assert config.ApiUrl == "http://127.0.0.1:8000"
        assert "disabled" in config._apply_api("")
        assert config.ApiUrl == ""
        assert "http(s)" in config._apply_api("notaurl")
        assert config.ApiUrl == ""
    finally:
        config._apply_api(old)
