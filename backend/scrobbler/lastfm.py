"""Last.fm API v2.0 client — now playing, scrobbles, and the auth handshake.

Credentials (API key, API secret, session key) come from
`backend.credentials` under `lastfm:*`. Every request except auth is signed
with `api_sig = md5(sorted_params + secret)` per Last.fm's spec, and plain
`format=json` responses are parsed. Anything network-side may raise —
`backend.scrobbler` wraps us in threads that never break playback.
"""

import hashlib
import json
import time
import urllib.parse
import urllib.request

from backend import credentials

ROOT = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "flow-twinx"
TIMEOUT = 5


def get_api_key():
    return credentials.get("lastfm:api_key")


def get_secret():
    return credentials.get("lastfm:api_secret")


def get_session():
    return credentials.get("lastfm:session_key")


def set_api_key(value):
    credentials.set("lastfm:api_key", value)


def set_secret(value):
    credentials.set("lastfm:api_secret", value)


def set_session(value):
    credentials.set("lastfm:session_key", value)


def signed_call(method, extra=None, sk=False, api_key=None, secret=None,
                session=None):
    """POST one signed request and return the parsed JSON body."""
    api_key = api_key or get_api_key()
    secret = secret or get_secret()
    session = session or get_session()
    params = {"method": method, "api_key": api_key}
    params.update(extra or {})
    if sk:
        params["sk"] = session
    # Signature covers every parameter except `format` and `api_sig` itself.
    canonical = "".join(
        f"{k}={params[k]}" for k in sorted(params)
    )
    params["api_sig"] = hashlib.md5(
        (canonical + secret).encode("utf-8")
    ).hexdigest()
    params["format"] = "json"
    data = urllib.parse.urlencode(params).encode()
    request = urllib.request.Request(
        ROOT, data=data, headers={"User-Agent": USER_AGENT}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        return json.loads(resp.read() or b"{}")


def get_auth_token(api_key=None, secret=None):
    """`auth.getToken` (a signed call, like every Last.fm write)."""
    return signed_call("auth.getToken", sk=False, api_key=api_key,
                       secret=secret or get_secret())["token"]


def auth_page(token, api_key=None):
    return (
        "https://www.last.fm/api/auth/"
        f"?api_key={api_key or get_api_key()}&token={token}"
    )


def fetch_session(token, api_key=None, secret=None):
    """Exchange an approved token for the permanent session key."""
    data = signed_call(
        "auth.getSession", extra={"token": token}, sk=False,
        api_key=api_key, secret=secret,
    )
    sess = data.get("session") or {}
    return sess.get("key"), sess.get("name")


def now_playing(title, artist="", album="", duration_ms=0):
    """`track.updateNowPlaying` — what shows on the user's profile page."""
    extra = {"track": title}
    if artist:
        extra["artist"] = artist
    if album:
        extra["album"] = album
    if duration_ms:
        extra["duration"] = str(int(duration_ms / 1000))
    return signed_call("track.updateNowPlaying", extra, sk=True)


def scrobble(title, artist="", album="", started_at=0, duration_ms=0):
    """`track.scrobble` — one completed listen, at its start time."""
    extra = {"track": title, "timestamp": str(int(started_at or time.time()))}
    if artist:
        extra["artist"] = artist
    if album:
        extra["album"] = album
    if duration_ms:
        extra["duration"] = str(int(duration_ms / 1000))
    return signed_call("track.scrobble", extra, sk=True)
