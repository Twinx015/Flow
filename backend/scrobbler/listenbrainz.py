"""ListenBrainz client — playing_now and single listens via submit-listens.

Auth is just the user token from listenbrainz.org/profile (stored in
`backend.credentials` as `listenbrainz:token`), sent as `Authorization:
Token <token>`. `playing_now` payloads never include `listened_at`; `single`
listens do, set to the playback start time. Also works against Maloja and
other servers speaking the LB API by overriding FLOW_LB_URL.
"""

import json
import os
import time
import urllib.request

from backend import credentials

ROOT = os.environ.get("FLOW_LB_URL") or "https://api.listenbrainz.org"
USER_AGENT = "flow-twinx"
TIMEOUT = 5
TOKEN_KEY = "listenbrainz:token"


def get_token():
    return credentials.get(TOKEN_KEY)


def set_token(value):
    credentials.set(TOKEN_KEY, value)


def _submit(document):
    request = urllib.request.Request(
        f"{ROOT}/1/submit-listens",
        data=json.dumps(document).encode(),
        headers={
            "Authorization": f"Token {get_token()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        return json.loads(resp.read() or b"{}")


def validate_token(token=None):
    """`validate-token` — returns the parsed JSON (`valid`, `musicbrainz_id`)."""
    from urllib.parse import quote

    qs = f"?token={quote(token or get_token())}"
    request = urllib.request.Request(
        f"{ROOT}/1/validate-token{qs}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
        return json.loads(resp.read() or b"{}")


def _metadata(title, artist, album, duration_ms):
    md = {"artist_name": artist or "", "track_name": title or ""}
    if album:
        md["release_name"] = album
    md["additional_info"] = {
        "media_player": "flow",
        "submission_client": "flow",
        "submission_client_version": "flow",
        "music_service_name": "youtube.com",
    }
    if duration_ms:
        md["additional_info"]["duration_ms"] = int(duration_ms)
    return md


def now_playing(title, artist="", album="", duration_ms=0):
    """`playing_now` — no `listened_at`; only shows "now" on the profile."""
    return _submit({
        "listen_type": "playing_now",
        "payload": [{"track_metadata": _metadata(title, artist, album, duration_ms)}],
    })


def scrobble(title, artist="", album="", started_at=0, duration_ms=0):
    """`single` listen — `listened_at` is the playback start time."""
    listened_at = int(started_at or time.time())
    return _submit({
        "listen_type": "single",
        "payload": [{
            "listened_at": listened_at,
            "track_metadata": _metadata(title, artist, album, duration_ms),
        }],
    })
