"""`flow scrobbler` — auth, status, and logout for Last.fm / ListenBrainz.

Mode-agnostic: dispatched by both command modules before any player or VLC
work. Last.fm auth walks the browser token flow (getToken → approve →
getSession) and stores the session key in `backend.credentials`;
ListenBrainz just needs the user token from listenbrainz.org/profile.
"""

import getpass
import webbrowser

from backend import config, credentials
from backend.scrobbler import lastfm, listenbrainz

P = config.Primary
T = config.Tertiary
M = config.Muted
E = config.RED
R = config.Reset
config.keep_live(globals())


def _print_status():
    print(f"{P}Scrobbler{R}")
    print(f"  {T}lastfm{R}       "
          f"{'ready' if scrobbler_ready('lastfm') else 'not configured'}")
    print(f"  {T}listenbrainz{R} "
          f"{'ready' if scrobbler_ready('listenbrainz') else 'not configured'}")
    print(f"  {M}active: {config.ScrobbleBackend or 'off'} "
          f"— `flow config scrobble lastfm|listenbrainz|off`{R}")


def scrobbler_ready(name):
    if name == "lastfm":
        return bool(lastfm.get_api_key() and lastfm.get_secret()
                    and lastfm.get_session())
    return bool(listenbrainz.get_token())


def auth_lastfm(extra):
    if len(extra) >= 2:
        lastfm.set_api_key(extra[0])
        lastfm.set_secret(extra[1])
        print(f"{T}API key + secret stored in {credentials.stored_in('lastfm:api_key')}{R}")
    elif not (lastfm.get_api_key() and lastfm.get_secret()):
        print(
            f"{E}Need an API key + secret first. Create one at "
            f"https://www.last.fm/api/account/create then run:{R}\n"
            f"  {T}flow scrobbler auth lastfm <api_key> <api_secret>{R}"
        )
        return
    try:
        token = lastfm.get_auth_token()
    except Exception as exc:
        print(f"{E}Auth failed: {exc}{R}")
        return
    url = lastfm.auth_page(token)
    print(f"{T}Approve flow in your browser (already opened, or paste):{R}\n  {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        input(f"{M}Press Enter after approving...{R}")
    except KeyboardInterrupt:
        return
    try:
        key, name = lastfm.fetch_session(token)
    except Exception as exc:
        print(f"{E}Session exchange failed: {exc}{R}")
        return
    if not key:
        print(f"{E}Last.fm did not return a session — run auth again{R}")
        return
    lastfm.set_session(key)
    print(f"{T}Scrobbling ready as {name} (session stored in "
          f"{credentials.stored_in('lastfm:session_key')}){R}")
    config.cmd_config(["scrobble", "lastfm"])


def auth_listenbrainz(extra):
    if extra:
        token = extra[0]
    else:
        print(f"{T}Copy your User Token from https://listenbrainz.org/profile/{R}")
        token = getpass.getpass("Token: ")
    if not token.strip():
        print(f"{E}No token given{R}")
        return
    token = token.strip()
    try:
        data = listenbrainz.validate_token(token)
    except Exception as exc:
        print(f"{E}Could not validate token: {exc}{R}")
        return
    if not data.get("valid"):
        print(f"{E}ListenBrainz says that token is invalid{R}")
        return
    listenbrainz.set_token(token)
    user = data.get("musicbrainz_id") or ""
    if user:
        _set_lb_user(user)
    print(f"{T}ListenBrainz ready as {user} (token stored in "
          f"{credentials.stored_in('listenbrainz:token')}){R}")
    config.cmd_config(["scrobble", "listenbrainz"])


def _set_lb_user(user):
    global_ok = hasattr(config, "ListenbrainzUsername")
    if global_ok:
        config.ListenbrainzUsername = user
        config._save_config()


def _set_lfm_user(user):
    if hasattr(config, "LastfmUsername"):
        config.LastfmUsername = user
        config._save_config()


def logout(name):
    keys = {
        "lastfm": ["lastfm:session_key"],
        "listenbrainz": ["listenbrainz:token"],
    }
    if name not in keys:
        print(f"{E}Unknown scrobbler '{name}'{R}")
        return
    for key in keys[name]:
        credentials.delete(key)
    if name == "listenbrainz":
        config.ListenbrainzUsername = ""
    else:
        config.LastfmUsername = ""
    config._save_config()
    print(f"{T}Logged out of {name}{' and scrobbling disabled' if config.ScrobbleBackend == name else ''}{R}")
    if config.ScrobbleBackend == name:
        config.cmd_config(["scrobble", "off"])


def handle(extra, args=None):
    """Entry for `flow scrobbler ...` (both Online and Offline dispatch)."""
    cmd = extra[0].lower() if extra else "status"
    rest = extra[1:]
    if cmd in ("status", "s", ""):
        _print_status()
    elif cmd in ("auth", "login"):
        target = (rest[0].lower() if rest else "").strip()
        rest = rest[1:]
        if target in ("lastfm", "lf"):
            auth_lastfm(rest)
        elif target in ("listenbrainz", "lb"):
            auth_listenbrainz(rest)
        else:
            print(f"Usage: scrobbler auth lastfm [<api_key> <api_secret>] | "
                  f"auth listenbrainz [<token>]")
    elif cmd in ("out", "logout"):
        logout((rest[0].lower() if rest else config.ScrobbleBackend or "").strip())
    elif cmd in ("help", "-h"):
        print(f"{T}scrobbler{R} — scrobble to Last.fm / ListenBrainz")
        print(f"  {P}scrobbler status{R}                    which backends are ready")
        print(f"  {P}scrobbler auth lastfm [key secret]{R}  browser flow → session key")
        print(f"  {P}scrobbler auth listenbrainz [token]{R} token from listenbrainz.org/profile")
        print(f"  {P}scrobbler logout lastfm|listenbrainz{R}")
        print(f"  {M}then: flow config scrobble lastfm|listenbrainz|off{R}")
    else:
        print(f"{E}Unknown scrobbler command '{cmd}' — try `scrobbler help`{R}")