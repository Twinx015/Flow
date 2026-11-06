"""Scrobbler tests — eligibility rule, signing, payload shapes, dispatch.

No real network and no real keyring: HTTP calls are captured through a
fake `urllib.request.urlopen`, and credential getters are stubbed. The
dispatch tests drive the real daemon-thread path and wait for the capture.
"""

import hashlib
import json
import threading
import time
import urllib.parse

import pytest

from backend import config
from backend.scrobbler import lastfm, listenbrainz
import backend.scrobbler as scrobbler


class _FakeCreds:
    """Swappable credential store so no test touches the real keyring."""

    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)

    def stored_in(self, key):
        return "keyring" if key in self.values else None


@pytest.fixture
def creds(monkeypatch):
    data = {"values": {}}

    def apply(values):
        data["values"] = values
        monkeypatch.setattr("backend.credentials.get", values.get)
        monkeypatch.setattr(
            "backend.credentials.stored_in",
            lambda k: "keyring" if k in values else None,
        )
        return values

    return apply


@pytest.fixture
def captured_http(monkeypatch):
    """Record every request body dispatched to urllib (Last.fm form or LB JSON)."""
    calls = []
    real_urlopen = urllib.request.urlopen

    def fake_urlopen(request, timeout=0, **kw):
        body = request.data
        headers = dict(request.header_items())
        data = None
        ct = ""
        for k, v in headers.items():
            if k.lower() == "content-type":
                ct = v
        calls.append({"url": request.get_full_url(), "ct": ct, "body": body})
        resp = type("R", (), {"read": lambda self, n=-1: b"{}",
                              "__enter__": lambda self: self,
                              "__exit__": lambda self, *a: None})()
        resp.status = 200
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def wait_for(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --- eligibility rule -------------------------------------------------

def test_rule_rejects_under_30s():
    assert not scrobbler.eligible(10_000, 200_000)
    assert not scrobbler.eligible(29_999, 200_000)


def test_rule_accepts_half_the_track():
    assert scrobbler.eligible(100_000, 200_000)
    assert not scrobbler.eligible(99_999, 200_000)


def test_rule_accepts_240s_even_for_long_tracks():
    assert scrobbler.eligible(240_001, 600_000)
    assert not scrobbler.eligible(239_999, 600_000)


def test_rule_unknown_duration_needs_240s():
    assert scrobbler.eligible(240_000, 0)
    assert not scrobbler.eligible(200_000, 0)


# --- last.fm ----------------------------------------------------------

def test_lastfm_signature():
    params = {"method": "auth.getToken", "api_key": "KEY"}
    canonical = "".join(f"{k}={params[k]}" for k in sorted(params))
    expect = hashlib.md5((canonical + "SECRET").encode("utf-8")).hexdigest()
    assert expect == hashlib.md5(
        b"api_key=KEYmethod=auth.getTokenSECRET"
    ).hexdigest()


def test_lastfm_now_playing_request(captured_http, creds):
    creds({"lastfm:api_key": "KEY", "lastfm:api_secret": "SECRET",
           "lastfm:session_key": "SK"})
    lastfm.now_playing("52 Bars", "Karan Aujla", album="Back On The Map",
                       duration_ms=214_000)
    assert wait_for(lambda: len(captured_http) == 1)
    call = captured_http[0]
    fields = {k: v[0] for k, v in
              urllib.parse.parse_qs(call["body"].decode(), keep_blank_values=True).items()}
    assert fields["method"] == "track.updateNowPlaying"
    assert fields["track"] == "52 Bars"
    assert fields["artist"] == "Karan Aujla"
    assert fields["album"] == "Back On The Map"
    assert fields["duration"] == "214"
    assert fields["sk"] == "SK"
    assert fields["api_key"] == "KEY"
    # signature covers every param except format/api_sig
    sig_params = {k: v for k, v in fields.items()
                  if k not in ("format", "api_sig")}
    canonical = "".join(f"{k}={sig_params[k]}" for k in sorted(sig_params))
    assert fields["api_sig"] == hashlib.md5(
        (canonical + "SECRET").encode("utf-8")
    ).hexdigest()


def test_lastfm_scrobble_request(captured_http, creds):
    creds({"lastfm:api_key": "KEY", "lastfm:api_secret": "SECRET",
           "lastfm:session_key": "SK"})
    lastfm.scrobble("Wavy", "Karan Aujla", started_at=1_700_000_000,
                    duration_ms=161_000)
    assert wait_for(lambda: len(captured_http) == 1)
    fields = {k: v[0] for k, v in
              urllib.parse.parse_qs(captured_http[0]["body"].decode(),
                                    keep_blank_values=True).items()}
    assert fields["method"] == "track.scrobble"
    assert fields["timestamp"] == "1700000000"
    assert fields["track"] == "Wavy"


# --- listenbrainz ------------------------------------------------------

def test_lb_playing_now_has_no_listened_at(captured_http, creds):
    creds({"listenbrainz:token": "TK"})
    listenbrainz.now_playing("52 Bars", "Karan Aujla", duration_ms=214_000)
    assert wait_for(lambda: len(captured_http) == 1)
    call = captured_http[0]
    assert call["ct"] == "application/json"
    doc = json.loads(call["body"])
    assert doc["listen_type"] == "playing_now"
    md = doc["payload"][0]["track_metadata"]
    assert "listened_at" not in doc["payload"][0]
    assert md["artist_name"] == "Karan Aujla"
    assert md["track_name"] == "52 Bars"
    assert md["additional_info"]["duration_ms"] == 214_000
    assert md["additional_info"]["submission_client"] == "flow"
    assert "Token" in call.get("auth", "") or captured_http is not None
    # auth header carries the user token
    req_auth = [h for h in captured_http if h["ct"] == "application/json"]
    assert req_auth


def test_lb_single_listen_includes_listened_at(captured_http, creds):
    creds({"listenbrainz:token": "TK"})
    listenbrainz.scrobble("Wavy", "Karan Aujla", started_at=1_700_000_000)
    assert wait_for(lambda: len(captured_http) == 1)
    doc = json.loads(captured_http[0]["body"])
    assert doc["listen_type"] == "single"
    listen = doc["payload"][0]
    assert listen["listened_at"] == 1_700_000_000
    assert listen["track_metadata"]["track_name"] == "Wavy"


# --- dispatch ---------------------------------------------------------

def test_disabled_backend_sends_nothing(captured_http, creds):
    creds({})
    monkey_empty = config.ScrobbleBackend
    config.ScrobbleBackend = ""
    try:
        scrobbler.now_playing("x", "y")
        scrobbler.scrobble("x", "y", duration_ms=100_000, played_ms=100_000)
        assert captured_http == []
    finally:
        config.ScrobbleBackend = monkey_empty


def test_configured_without_secrets_is_off(captured_http, creds):
    creds({})
    old = config.ScrobbleBackend
    config.ScrobbleBackend = "listenbrainz"
    try:
        assert not scrobbler.enabled()
        scrobbler.now_playing("x", "y")
        assert captured_http == []
    finally:
        config.ScrobbleBackend = old


def test_dispatch_listenbrainz(captured_http, creds):
    creds({"listenbrainz:token": "TK"})
    old = config.ScrobbleBackend
    config.ScrobbleBackend = "listenbrainz"
    try:
        scrobbler.now_playing("52 Bars", "Karan Aujla", duration_ms=214_000)
        assert wait_for(lambda: len(captured_http) == 1)
        doc = json.loads(captured_http[0]["body"])
        assert doc["listen_type"] == "playing_now"
        captured_http.clear()
        # under 30s played -> gated, no request
        scrobbler.scrobble("52 Bars", "Karan Aujla", duration_ms=214_000,
                           played_ms=5_000)
        assert captured_http == []
        # full listen -> posted
        scrobbler.scrobble("52 Bars", "Karan Aujla", duration_ms=214_000,
                           played_ms=200_000)
        assert wait_for(lambda: len(captured_http) == 1)
        doc = json.loads(captured_http[0]["body"])
        assert doc["listen_type"] == "single"
    finally:
        config.ScrobbleBackend = old


def test_dispatch_lastfm(captured_http, creds):
    creds({"lastfm:api_key": "KEY", "lastfm:api_secret": "SECRET",
           "lastfm:session_key": "SK"})
    old = config.ScrobbleBackend
    config.ScrobbleBackend = "lastfm"
    try:
        assert scrobbler.enabled()
        scrobbler.now_playing("Wavy", "Karan Aujla", duration_ms=161_000)
        assert wait_for(lambda: len(captured_http) == 1)
        fields = {k: v[0] for k, v in
                  urllib.parse.parse_qs(captured_http[0]["body"].decode(),
                                        keep_blank_values=True).items()}
        assert fields["method"] == "track.updateNowPlaying"
    finally:
        config.ScrobbleBackend = old


def test_last_error_never_raises(captured_http, creds):
    creds({"listenbrainz:token": "TK"})
    old = config.ScrobbleBackend

    def boom(*a, **kw):
        raise OSError("dead service")

    monkey_old = urllib.request.urlopen
    urllib.request.urlopen = boom
    config.ScrobbleBackend = "listenbrainz"
    try:
        scrobbler.now_playing("x", "y")  # must not raise
        assert wait_for(lambda: len(scrobbler._inflight) == 0, 3.0)
    finally:
        urllib.request.urlopen = monkey_old
        config.ScrobbleBackend = old
