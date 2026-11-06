"""Fire-and-forget scrobbling to Last.fm or ListenBrainz.

The backend is `config.ScrobbleBackend` (`lastfm`, `listenbrainz`, or empty
for off); secrets live in `backend.credentials`. Every public call is a
no-op when disabled, runs its HTTP request in a daemon thread, and never
raises — a dead scrobble service must not break playback. A listen counts
only after Last.fm's rule: at least 30 s played, and either half the track
or 4 minutes, whichever comes first.
"""

import atexit
import threading
import time

from backend import config, credentials

from . import lastfm, listenbrainz

BACKENDS = {"lastfm": lastfm, "listenbrainz": listenbrainz}

MIN_PLAYED_MS = 30_000
LONG_PLAY_MS = 240_000

_inflight = set()
_last = {}

_KEYS = {
    "lastfm": ("lastfm:api_key", "lastfm:api_secret", "lastfm:session_key"),
    "listenbrainz": ("listenbrainz:token",),
}


def flush(timeout=6.0):
    """Join in-flight scrobble threads; registered via atexit so a process
    that reaches the end of its playback does not kill its own last POST."""
    deadline = time.time() + timeout
    while _inflight and time.time() < deadline:
        time.sleep(0.05)


atexit.register(flush)


def backend():
    """The configured backend module, or None when scrobbling is off."""
    return BACKENDS.get(config.ScrobbleBackend)


def configured():
    """True when the configured backend has all its secrets stored."""
    mod = backend()
    if mod is None:
        return False
    return all(credentials.get(k) for k in _KEYS[config.ScrobbleBackend])


def enabled():
    return configured()


def status():
    """One-line description for `flow scrobbler status`."""
    name = config.ScrobbleBackend or "off"
    if backend() is None:
        return f"backend: {name}"
    stored = [
        f"{k} ({credentials.stored_in(k)})"
        for k in _KEYS[config.ScrobbleBackend]
        if credentials.stored_in(k)
    ]
    missing = [k for k in _KEYS[config.ScrobbleBackend] if not credentials.get(k)]
    line = f"backend: {name}; secrets: {', '.join(stored) if stored else 'none'}"
    if missing:
        line += f"; missing: {', '.join(missing)}"
    return line


def _dispatch(payload_builder):
    if backend() is None or not configured():
        return
    key = id(payload_builder)
    if key in _inflight:
        return
    _inflight.add(key)

    def worker():
        try:
            payload_builder(backend())
        except Exception as exc:
            if config.DEV_MODE:
                config.dev_print("Scrobble failed", {"error": str(exc)})
        finally:
            _inflight.discard(key)

    threading.Thread(target=worker, name="flow-scrobble", daemon=True).start()


def eligible(played_ms, duration_ms):
    """Scrobble rule: >=30s played and (>=half the track or >=240s)."""
    if played_ms < MIN_PLAYED_MS:
        return False
    if not duration_ms:
        return played_ms >= LONG_PLAY_MS
    return played_ms >= duration_ms / 2 or played_ms >= LONG_PLAY_MS


def now_playing(title, artist="", album="", duration_ms=0):
    """Announce the track that just started; remember it for the scrobble rule."""
    if backend() is None:
        return
    _last.update(title=title or "", artist=artist or "", album=album or "",
                 started_at=time.time())

    def build(mod):
        if mod is lastfm:
            lastfm.now_playing(title, artist, album, duration_ms)
        else:
            listenbrainz.now_playing(title, artist, album, duration_ms)

    _dispatch(build)


def scrobble(title, artist="", album="", duration_ms=0, started_at=None,
             played_ms=0):
    """Record a completed listen if it passed the eligibility rule."""
    if backend() is None:
        return
    if not eligible(played_ms, duration_ms):
        return

    def build(mod):
        started = int(started_at or _last.get("started_at") or time.time())
        if mod is lastfm:
            lastfm.scrobble(title, artist, album, started, duration_ms)
        else:
            listenbrainz.scrobble(title, artist, album, started, duration_ms)

    _dispatch(build)
