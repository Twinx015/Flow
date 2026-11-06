import json
import logging
import mimetypes
import os
import pathlib
import tempfile
import threading
import time

from flask import Flask, jsonify, render_template, request, send_file

from backend import config, control, history, library, lyrics, playlist, sponsor, status
from backend.Online import youtube
from web import devlog

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=pathlib.Path(__file__).resolve().parent / "templates",
    static_url_path="/static",
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _log_response(response):
    status_code = response.status_code
    method = request.method
    route = request.path
    msg = ""
    if (
        hasattr(response, "get_json")
        and response.content_type == "application/json"
    ):
        try:
            body = response.get_json(silent=True)
            if isinstance(body, dict):
                if "error" in body:
                    msg = str(body["error"])
                elif "success" in body:
                    msg = "ok"
        except Exception:
            pass
    try:
        from backend import logger as flog
        flog.log_http("web", method, route, status_code, data={"message": msg, "source": "flask"})
    except Exception:
        pass
    if config.DEV_MODE:
        if status_code >= 500:
            devlog.log_error(method, status_code, route, "flask", msg)
        elif status_code >= 400:
            devlog.log_warn(method, status_code, route, "flask", msg)
        elif method == "POST":
            devlog.log_success(method, status_code, route, "flask", msg)
        else:
            devlog.log_info(method, status_code, route, "flask", msg)
    return response


try:
    devlog.setup_werkzeug_handler()
except Exception:
    pass
for name in ("werkzeug", "werkzeug.serving", "flask.app"):
    try:
        logging.getLogger(name).setLevel(logging.ERROR)
    except Exception:
        pass

SETTINGS_FILE = pathlib.Path.home() / ".flow/web_ui.json"
FLOW_DIR = pathlib.Path.home() / ".flow/downloads"
MUSIC_DIR = pathlib.Path.home() / ".flow/music"

_truncate_title = config._truncate_title

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".ogg",
    ".opus",
    ".wma",
    ".aac",
    ".webm",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

SEARCH_CACHE_MAX = 50
_search_cache = {}


def _get_stream_url(entry):
    return sponsor.stream_url(entry) or entry.get("webpage_url") or ""


def _full_res_thumbnail(url):
    if not url or "i.ytimg.com/vi/" not in url:
        return url or ""
    try:
        video_id = url.split("/vi/")[1].split("/")[0]
        return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"
    except IndexError:
        return url


def _get_thumbnail(entry):
    if entry.get("thumbnail"):
        return _full_res_thumbnail(entry["thumbnail"])
    thumbs = entry.get("thumbnails", [])
    if thumbs:
        return _full_res_thumbnail(thumbs[-1].get("url", ""))
    return ""


def _entry_to_dict(entry):
    return {
        "title": _truncate_title(entry.get("title", "Unknown")),
        "video_id": entry.get("id", ""),
        "stream_url": _get_stream_url(entry) or "",
        "thumbnail": _get_thumbnail(entry),
        "channel": entry.get("uploader", "Unknown"),
        "duration": entry.get("duration", 0),
        "segments": _cached_segments(entry.get("id")) if sponsor.enabled() else [],
    }


def _cached_search(query, limit):
    key = f"{query}:{limit}"
    if key in _search_cache:
        return _search_cache[key]
    results = [_entry_to_dict(entry) for entry, _t, _d in youtube.search(query, limit)]
    devlog.log_info(
        "FETCH", 200, "/search", "backend", f"query={query} {len(results)} results"
    )
    _search_cache[key] = results
    if len(_search_cache) > SEARCH_CACHE_MAX:
        del _search_cache[next(iter(_search_cache))]
    return results


def _fetch_radio(video_id, max_results=30):
    tracks = youtube.fetch_radio_for_id(video_id, max_results)
    return [
        {
            "title": _truncate_title(title),
            "video_id": vid,
            "duration": dur,
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        }
        for title, vid, dur in tracks
    ]


PLAY_CACHE_TTL = 20 * 60
_play_cache = {}

SEG_CACHE_TTL = 20 * 60
_seg_cache = {}
_seg_inflight = set()


def _fetch_segments_background(video_id, duration=None):
    if video_id in _seg_inflight:
        return
    _seg_inflight.add(video_id)
    try:
        segments = sponsor.fetch_segments(video_id, duration)
        _seg_cache[video_id] = (time.time(), segments)
    except Exception as exc:
        logger.warning("Background SponsorBlock fetch failed for %s: %s", video_id, exc)
    finally:
        _seg_inflight.discard(video_id)


def _ensure_segments(video_id, duration=None):
    if not _cached_segments(video_id) and video_id not in _seg_inflight:
        threading.Thread(
            target=_fetch_segments_background, args=(video_id, duration), daemon=True
        ).start()


def _cached_segments(video_id):
    now = time.time()
    cached = _seg_cache.get(video_id)
    if cached and now - cached[0] < SEG_CACHE_TTL:
        return cached[1]
    return []


def _peek_entry(video_id):
    cached = _play_cache.get(video_id)
    if cached and time.time() - cached[0] < PLAY_CACHE_TTL:
        return cached[1]
    return None


def _get_full_entry(video_id, fresh=False):
    now = time.time()
    cached = _play_cache.get(video_id)
    if not fresh and cached and now - cached[0] < PLAY_CACHE_TTL:
        return cached[1]
    _ensure_segments(video_id)
    try:
        entry = youtube.get_entry(f"https://www.youtube.com/watch?v={video_id}")
        if entry:
            _play_cache[video_id] = (now, entry)
            _ensure_segments(entry.get("id"), entry.get("duration"))
            devlog.log_info("FETCH", 200, "/play", "yt_dlp", f"vid={video_id}")
        return entry
    except Exception as exc:
        logger.warning("Failed to get entry for %s: %s", video_id, exc)
        devlog.log_error("FETCH", 500, "/play", "yt_dlp", f"vid={video_id} err={exc}")
        return None


def _thumb_url(stem: str) -> str:
    if pathlib.Path(library.thumbnail_path(stem)).exists():
        return f"/thumb/{stem}"
    return ""


def _resolve_thumbnail(thumb: str) -> str:
    if not thumb:
        return ""
    if thumb.startswith("/thumb/"):
        stem = thumb[len("/thumb/") :].split("?")[0].split("/")[0]
        path = library.thumbnail_path(stem)
        if pathlib.Path(path).exists():
            return path
        return ""
    return thumb


def _by_title(entries):
    """Ascending by displayed name, the order the CLI lists songs in."""
    return sorted(
        entries, key=lambda e: (e.get("title") or e.get("filename") or "").lower()
    )


def _scan_dir(base, depth=0, max_depth=2):
    if not base.exists() or not base.is_dir():
        return []
    results = []
    try:
        for item in sorted(base.iterdir()):
            if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS:
                results.append(
                    {
                        "title": library.title_for_stem(item.stem),
                        "video_id": item.stem,
                        "thumbnail": _thumb_url(item.stem),
                        "path": str(item),
                        "filename": item.name,
                        "source": "library"
                        if str(base).startswith(str(FLOW_DIR))
                        else "custom",
                    }
                )
            elif item.is_dir() and depth < max_depth and item.name != "liked songs":
                results.extend(_scan_dir(item, depth + 1, max_depth))
    except PermissionError:
        pass
    return _by_title(results)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "missing query parameter 'q'"}), 400
    try:
        limit = min(int(request.args.get("limit", 10)), 25)
    except ValueError, TypeError:
        limit = 10
    filt = request.args.get("filter", "").strip()
    if filt:
        try:
            rows = youtube.ytm_search(q, filt, limit)
        except Exception as exc:
            logger.warning("YT Music search failed for %r: %s", q, exc)
            devlog.log_error("FETCH", 500, "/search", "ytmusic", f"filter={filt} err={exc}")
            return jsonify({"error": str(exc)}), 500
        devlog.log_info(
            "FETCH", 200, "/search", "ytmusic", f"query={q} filter={filt}"
        )
        return jsonify({"results": rows})
    return jsonify({"results": _cached_search(q, limit)})


@app.route("/trend")
def trend():
    return jsonify({"results": _cached_search("#trending #english #topsong", 15)})


@app.route("/recommend")
def recommend():
    vid = request.args.get("video_id", "").strip()
    if not vid:
        return jsonify({"error": "missing query parameter 'video_id'"}), 400
    try:
        limit = min(int(request.args.get("limit", 30)), 50)
    except ValueError, TypeError:
        limit = 30
    try:
        return jsonify({"results": _fetch_radio(vid, limit)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


YTM_CACHE_TTL = 10 * 60
_ytm_cache = {}


def _ytm_cached(key, fn):
    now = time.time()
    hit = _ytm_cache.get(key)
    if hit and now - hit[0] < YTM_CACHE_TTL:
        return hit[1]
    value = fn()
    if len(_ytm_cache) > 50:
        del _ytm_cache[next(iter(_ytm_cache))]
    _ytm_cache[key] = (now, value)
    return value


def _ytm_arg(name):
    value = request.args.get(name, "").strip()
    if not value:
        return None, (jsonify({"error": f"missing query parameter '{name}'"}), 400)
    return value, None


@app.route("/api/ytm/home")
def api_ytm_home():
    try:
        sections = _ytm_cached("home", youtube.ytm_home)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"sections": sections})


@app.route("/api/ytm/charts")
def api_ytm_charts():
    try:
        charts = _ytm_cached("charts", youtube.ytm_charts)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(charts)


@app.route("/api/ytm/explore")
def api_ytm_explore():
    try:
        explore = _ytm_cached("explore", youtube.ytm_explore)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(explore)


@app.route("/api/ytm/moods")
def api_ytm_moods():
    try:
        moods = _ytm_cached("moods", youtube.ytm_mood_categories)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"moods": moods})


@app.route("/api/ytm/mood-playlists")
def api_ytm_mood_playlists():
    params, err = _ytm_arg("params")
    if err:
        return err
    try:
        playlists = _ytm_cached(f"mood:{params}", lambda: youtube.ytm_mood_playlists(params))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"playlists": playlists})


@app.route("/api/ytm/playlist")
def api_ytm_playlist():
    pid, err = _ytm_arg("id")
    if err:
        return err
    try:
        limit = int(request.args.get("limit", 0))
    except ValueError, TypeError:
        limit = 0
    try:
        data = _ytm_cached(
            f"pl:{pid}:{limit}", lambda: youtube.ytm_playlist(pid, limit or None)
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if not data:
        return jsonify({"error": "playlist not found"}), 404
    return jsonify(data)


@app.route("/api/ytm/album")
def api_ytm_album():
    album_id, err = _ytm_arg("id")
    if err:
        return err
    try:
        data = _ytm_cached(f"album:{album_id}", lambda: youtube.ytm_album(album_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if not data:
        return jsonify({"error": "album not found"}), 404
    return jsonify(data)


@app.route("/api/ytm/artist")
def api_ytm_artist():
    artist_id, err = _ytm_arg("id")
    if err:
        return err
    try:
        data = _ytm_cached(f"artist:{artist_id}", lambda: youtube.ytm_artist(artist_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if not data:
        return jsonify({"error": "artist not found"}), 404
    return jsonify(data)


@app.route("/play")
def play():
    vid = request.args.get("video_id", "").strip()
    fresh = request.args.get("fresh", "0") == "1"
    if not vid:
        return jsonify({"error": "missing query parameter 'video_id'"}), 400
    try:
        entry = _get_full_entry(vid, fresh=fresh)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if not entry:
        return jsonify({"error": "video not found"}), 404
    return jsonify(_entry_to_dict(entry))


@app.route("/api/lyrics")
def api_lyrics():
    vid = request.args.get("video_id", "").strip()
    title = request.args.get("title", "").strip()
    if not vid and not title:
        return jsonify({"error": "missing 'video_id' or 'title'"}), 400
    fresh = request.args.get("fresh", "0") == "1"
    if fresh:
        lyrics.clear_cache()

    entry = _peek_entry(vid)
    duration = request.args.get("duration", "")
    try:
        duration = float(duration) if duration else 0.0
    except ValueError:
        duration = 0.0
    if entry:
        duration = entry.get("duration") or duration

    try:
        found = lyrics.fetch_lyrics(
            vid or None,
            title=(entry or {}).get("title") or title,
            artist=(entry or {}).get("artist") or request.args.get("artist", ""),
            album=(entry or {}).get("album", ""),
            duration=duration,
        )
    except Exception as exc:
        logger.warning("Lyrics lookup failed for %s: %s", vid or title, exc)
        devlog.log_error("FETCH", 500, "/api/lyrics", "lyrics", f"err={exc}")
        return jsonify({"error": str(exc)}), 500

    devlog.log_info(
        "FETCH",
        200,
        "/api/lyrics",
        found["source"] if found else "none",
        f"vid={vid} synced={bool(found and found['synced'])}",
    )
    return jsonify({"lyrics": found, "found": bool(found)})


@app.route("/api/segments")
def api_segments():
    vid = request.args.get("video_id", "").strip()
    if not vid:
        return jsonify({"error": "missing query parameter 'video_id'"}), 400
    if not sponsor.enabled():
        return jsonify({"segments": []})
    _ensure_segments(vid)
    segments = _cached_segments(vid)
    if not segments and vid in _seg_inflight:
        for _ in range(10):
            time.sleep(0.2)
            segments = _cached_segments(vid)
            if segments or vid not in _seg_inflight:
                break
    return jsonify({"segments": segments})


@app.route("/offline")
def offline():
    songs = _scan_dir(FLOW_DIR)
    return jsonify({"results": songs})


def _download_audio(video_id: str, save_dir: str, fmt: str):
    save_path = pathlib.Path(save_dir).expanduser()
    save_path.mkdir(parents=True, exist_ok=True)
    filename = youtube.download_url(
        f"https://www.youtube.com/watch?v={video_id}", str(save_path), fmt=fmt
    )
    return filename, library.get_title(video_id) or "Unknown"


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True)
    vid = data.get("video_id", "").strip()
    save_dir = data.get("save_dir", str(FLOW_DIR))
    fmt = data.get("format", config.FORMAT)
    if not vid:
        return jsonify({"error": "missing video_id"}), 400
    if fmt not in ("webm", "opus", "m4a", "mp3"):
        return jsonify({"error": f"unsupported format '{fmt}'"}), 400
    if fmt != "webm" and not config.FFMPEG:
        return jsonify({"error": f"ffmpeg not found, cannot convert to {fmt}"}), 400
    try:
        filename, title = _download_audio(vid, save_dir, fmt)
        devlog.log_success("FETCH", 200, "/download", "yt_dlp", f"downloaded {vid}")
        return jsonify(
            {
                "success": True,
                "path": str(filename),
                "title": _truncate_title(title),
                "thumbnail": library.thumbnail_path(vid),
            }
        )
    except Exception as exc:
        logger.warning("Download failed for %s: %s", vid, exc)
        devlog.log_error("FETCH", 500, "/download", "yt_dlp", f"vid={vid} err={exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/is-downloaded")
def api_is_downloaded():
    video_id = request.args.get("video_id", "").strip()
    if not video_id:
        return jsonify({"downloaded": False})
    path = library.get_download_path(video_id)
    if path and not pathlib.Path(path).exists():
        library.clear_download(video_id)
        path = None
    return jsonify({"downloaded": path is not None, "path": path or ""})


@app.route("/api/downloaded-ids")
def api_downloaded_ids():
    return jsonify({"ids": library.get_downloaded_ids()})


@app.route("/api/library")
def api_library():
    songs = []
    for k, v in library.load().items():
        songs.append(
            {
                "video_id": k,
                "title": v.get("title", ""),
                "liked": bool(v.get("liked")),
                "downloaded": bool(v.get("downloaded")),
                "speed_dial": bool(v.get("speed_dial")),
                "thumbnail": v.get("thumbnail") or "",
                "song": v.get("song") or "",
            }
        )
    return jsonify({"songs": songs})


@app.route("/api/speed-dial")
def api_speed_dial():
    results = []
    for k in library.get_speed_dial_ids():
        entry = library.get(k) or {}
        results.append(
            {
                "video_id": k,
                "title": entry.get("title", ""),
                "thumbnail": _thumb_url(k) or entry.get("thumbnail", ""),
            }
        )
    return jsonify({"results": results})


@app.route("/api/speed-dial", methods=["POST"])
def api_speed_dial_set():
    data = request.get_json(force=True)
    video_id = data.get("video_id", "").strip()
    title = data.get("title", "")
    enabled = bool(data.get("enabled"))
    if not video_id:
        return jsonify({"error": "missing video_id"}), 400
    if enabled:
        library.mark_speed_dial(video_id, title, data.get("path", ""))
        devlog.log_success(
            "LIB", 200, "/api/speed-dial", "flow", f"speed-dial +{video_id}"
        )
    else:
        library.unmark_speed_dial(video_id)
        devlog.log_success(
            "LIB", 200, "/api/speed-dial", "flow", f"speed-dial -{video_id}"
        )
    return jsonify({"success": True, "speed_dial": enabled})


@app.route("/api/library/rename", methods=["POST"])
def api_library_rename():
    data = request.get_json(force=True)
    video_id = data.get("video_id", "").strip()
    title = data.get("title", "")
    if not video_id:
        return jsonify({"error": "missing video_id"}), 400
    if not library.rename(video_id, title):
        return jsonify({"error": "missing title"}), 400
    try:
        from backend import logger as flog
        flog.info("web", "api_call", "rename", {"video_id": video_id, "path": "/api/library/rename"})
    except Exception:
        pass
    devlog.log_success("LIB", 200, "/api/library/rename", "flow", f"{video_id}")
    return jsonify({"success": True, "title": library.get_title(video_id)})


@app.route("/api/home")
def api_home():
    status_data = status.read()
    last_played = None
    if status_data:
        last_played = {
            "title": status_data.get("title", "Unknown"),
            "duration": int(status_data.get("duration", 0)),
            "playing": bool(status_data.get("playing")),
            "thumbnail": _resolve_thumbnail(status_data.get("thumbnail", "")),
            "ts": status_data.get("ts", 0),
        }
    speed_dial = []
    for k in library.get_speed_dial_ids():
        entry = library.get(k) or {}
        speed_dial.append(
            {
                "video_id": k,
                "title": entry.get("title", ""),
                "thumbnail": _thumb_url(k) or entry.get("thumbnail", ""),
            }
        )
    return jsonify({"last_played": last_played, "speed_dial": speed_dial})


@app.route("/api/delete-download", methods=["POST"])
def api_delete_download():
    data = request.get_json(force=True)
    video_id = data.get("video_id", "").strip()
    path = data.get("path", "").strip()
    if not video_id and not path:
        return jsonify({"error": "missing video_id"}), 400
    if library.delete(video_id):
        devlog.log_success(
            "FETCH", 200, "/api/delete-download", "flow", f"deleted {video_id}"
        )
        return jsonify({"success": True})
    if path:
        p = pathlib.Path(path).expanduser()
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p.absolute()
        root = FLOW_DIR.resolve()
        if (resolved == root or root in resolved.parents) and p.is_file():
            p.unlink()
            stem = p.stem if p.suffix else p.name
            for other in p.parent.glob(f"{stem}*"):
                if other != p and other.is_file():
                    try:
                        other.unlink()
                    except OSError:
                        pass
            if video_id:
                library.clear_download(video_id)
            devlog.log_success(
                "FETCH",
                200,
                "/api/delete-download",
                "flow",
                f"deleted file {resolved.name}",
            )
            return jsonify({"success": True})
    return jsonify({"error": "not downloaded"}), 404


@app.route("/api/now-playing", methods=["POST"])
def api_now_playing():
    data = request.get_json(force=True)
    status.update(
        data.get("title"),
        data.get("duration", 0),
        data.get("playing", True),
        _resolve_thumbnail(data.get("thumbnail", "")),
    )
    return jsonify({"success": True})


@app.route("/api/history")
def api_history():

    sort = request.args.get("sort", "recent")
    if sort not in history.SORTS:
        sort = "recent"
    if sort in ("most", "least"):
        unique = True
    else:
        unique = request.args.get("unique") in ("1", "true", "yes")
    since = None
    range_key = request.args.get("range", "all")
    days = history.RANGES.get(range_key)
    if days:
        since = time.time() - days * 86400
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except TypeError, ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400
    plays = history.timeline(
        sort=sort,
        limit=limit,
        offset=offset,
        since=since,
        unique=unique,
    )
    for play in plays:
        play["thumbnail"] = _thumb_url(play["video_id"]) if play["video_id"] else ""
    return jsonify(
        {
            "plays": plays,
            "sort": sort,
            "range": range_key,
            "unique": unique,
            "total": history.count(),
            "totals": history.totals(),
        }
    )


@app.route("/api/history/top")
def api_history_top():
    """Most-played online songs, for the History panel's ranked view."""
    try:
        limit = int(request.args.get("limit", 20))
    except TypeError, ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    return jsonify({"top": history.top(limit=max(1, min(limit, 200)))})


@app.route("/api/history/play", methods=["POST"])
def api_history_play():

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "missing title"}), 400
    count = history.record_play(
        (data.get("video_id") or "").strip(),
        title,
        (data.get("artist") or "").strip(),
        mode=data.get("mode", "online"),
        duration=data.get("duration", 0),
    )
    return jsonify({"success": True, "song_count": count})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    removed = history.clear()
    devlog.log_success(
        "HIST", 200, "/api/history/clear", "flow", f"cleared {removed} plays"
    )
    return jsonify({"success": True, "removed": removed})


@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.get_json(force=True)
    command = data.get("command", "").strip()
    if command not in control.COMMANDS:
        return jsonify(
            {"error": f"invalid command, expected one of {sorted(control.COMMANDS)}"}
        ), 400
    control.send(command, delta=data.get("delta"))
    try:
        from backend import logger as flog
        flog.info("web", "control", f"command={command}", {"command": command, "payload": data})
    except Exception:
        pass
    devlog.log_success("CTRL", 200, "/api/control", "flow", f"command={command}")
    return jsonify({"success": True, "command": command})


@app.route("/api/control/poll")
def api_control_poll():
    cmd = control.take()
    if isinstance(cmd, dict):
        return jsonify(cmd)
    return jsonify({"command": cmd})


@app.route("/api/playlists")
def api_playlists():
    out = []
    for n in playlist.list_all():
        inf = playlist.info(n) or {}
        out.append(
            {
                "name": inf.get("name", n),
                "count": inf.get("count", 0),
                "description": inf.get("description", ""),
                "duration": inf.get("duration", 0),
                "local_count": inf.get("local_count", 0),
                "modified": inf.get("modified", 0),
            }
        )
    return jsonify({"playlists": out})


@app.route("/api/playlist")
def api_playlist():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "missing name"}), 400
    actual = playlist.resolve_name(name)
    if actual is None:
        return jsonify({"error": "playlist not found"}), 404
    songs = []
    for s in playlist.get(actual):
        vid = s.get("id", "")
        local = s.get("local_path") or (
            playlist.find_local_copy(vid) if s.get("source") == "youtube" else None
        )
        stored_thumb = s.get("thumb")
        if stored_thumb and pathlib.Path(stored_thumb).exists():
            thumbnail = "/local/" + str(stored_thumb).lstrip("/")
        elif vid and s.get("source") == "youtube":
            thumbnail = _full_res_thumbnail(
                f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
            )
        else:
            thumbnail = ""
        songs.append(
            {
                "title": s.get("title", "Unknown"),
                "video_id": vid,
                "url": s.get("ref", ""),
                "thumbnail": thumbnail,
                "thumb_path": stored_thumb or "",
                "channel": "Local" if s.get("source") == "local" else "",
                "duration": int(s.get("duration") or 0),
                "local": bool(local and pathlib.Path(local).exists()),
            }
        )
    inf = playlist.info(actual) or {}
    return jsonify(
        {
            "name": inf.get("name", actual),
            "description": inf.get("description", ""),
            "songs": songs,
        }
    )


def _resolve_playlist_or_error(name):
    actual = playlist.resolve_name(name) if name else None
    if actual is None:
        return None, (jsonify({"error": "playlist not found"}), 404)
    return actual, None


@app.route("/api/playlists/rename", methods=["POST"])
def api_playlists_rename():
    data = request.get_json(force=True)
    old = data.get("old", "").strip()
    new = data.get("new", "").strip()
    if not old or not new:
        return jsonify({"error": "missing old or new"}), 400
    if new.lower() in playlist.RESERVED_NAMES:
        return jsonify({"error": "'new' is a reserved name"}), 400
    actual, err = _resolve_playlist_or_error(old)
    if err:
        return err
    if playlist.rename(actual, new):
        return jsonify({"success": True, "name": new})
    return jsonify({"error": f"cannot rename to '{new}' (already exists?)"}), 409


@app.route("/api/playlists/duplicate", methods=["POST"])
def api_playlists_duplicate():
    data = request.get_json(force=True)
    src = data.get("src", "").strip()
    new = data.get("name", "").strip()
    if not src or not new:
        return jsonify({"error": "missing src or name"}), 400
    actual, err = _resolve_playlist_or_error(src)
    if err:
        return err
    if playlist.duplicate(actual, new):
        return jsonify({"success": True, "name": new})
    return jsonify({"error": f"cannot duplicate to '{new}' (already exists?)"}), 409


@app.route("/api/playlists/merge", methods=["POST"])
def api_playlists_merge():
    data = request.get_json(force=True)
    dst = data.get("dst", "").strip()
    src = data.get("src", "").strip()
    if not dst or not src:
        return jsonify({"error": "missing dst or src"}), 400
    dst_a, err = _resolve_playlist_or_error(dst)
    if err:
        return err
    src_a, err = _resolve_playlist_or_error(src)
    if err:
        return err
    result = playlist.merge(dst_a, src_a)
    if result is None:
        return jsonify({"error": "merge failed"}), 500
    added, skipped = result
    return jsonify({"success": True, "added": added, "skipped": skipped})


@app.route("/api/playlist/reorder", methods=["POST"])
def api_playlist_reorder():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    order = data.get("order")
    if not name or not isinstance(order, list):
        return jsonify({"error": "missing name or order"}), 400
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    if not playlist.reorder(actual, [str(o) for o in order]):
        return jsonify({"error": "order does not match playlist tracks"}), 400
    return jsonify({"success": True})


@app.route("/api/playlist/description", methods=["POST"])
def api_playlist_description():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    desc = str(data.get("description", ""))
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    playlist.set_description(actual, desc)
    return jsonify({"success": True, "description": desc})


@app.route("/api/playlist/clear", methods=["POST"])
def api_playlist_clear():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    removed = playlist.clear(actual)
    return jsonify({"success": True, "removed": removed})


@app.route("/api/playlist/dedupe", methods=["POST"])
def api_playlist_dedupe():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    removed = playlist.dedupe(actual)
    return jsonify({"success": True, "removed": removed})


DL_FMTS = ("webm", "opus", "m4a", "mp3")
PL_DL_JOB_TTL = 15 * 60
_playlist_dl_jobs = {}


def _resolve_dl_fmt(fmt):
    fmt = str(fmt or "").strip().lower() or config.FORMAT
    if fmt not in DL_FMTS:
        fmt = config.FORMAT
    if fmt not in DL_FMTS or (fmt != "webm" and not config.FFMPEG):
        fmt = "webm"
    return fmt


def _playlist_dl_snapshot(job):
    return {k: v for k, v in job.items() if k != "queue"}


def _playlist_dl_worker(actual):
    job = _playlist_dl_jobs.get(actual)
    if not job:
        return
    for item in job["queue"]:
        if _playlist_dl_jobs.get(actual) is not job:
            return
        vid, url = item["video_id"], item["url"]
        local = playlist.local_path_of(item["track"])
        if local:
            playlist.backfill_local(actual, item["index"], local)
            job["skipped"] += 1
            job["done"] += 1
            continue
        try:
            filename = youtube.download_url(url, config.DOWNLOAD_DIR, fmt=job["format"])
        except Exception as exc:
            job["failed"] += 1
            logger.warning(
                "Playlist download failed: %s (%s)", _truncate_title(item["title"]), exc
            )
            devlog.log_error(
                "FETCH", 500, "/api/playlist/download", "yt_dlp", f"vid={vid} err={exc}"
            )
        else:
            playlist.backfill_local(actual, item["index"], str(filename))
            job["ok"] += 1
            job["files"].append(str(filename))
        job["done"] += 1
    job["running"] = False
    job["finished"] = time.time()
    devlog.log_success(
        "FETCH",
        200,
        "/api/playlist/download",
        "yt_dlp",
        f"{actual}: {job['ok']} ok, {job['failed']} failed",
    )


@app.route("/api/playlist/download", methods=["POST"])
def api_playlist_download():
    """Queue a background download of every track in one playlist."""
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    running = _playlist_dl_jobs.get(actual)
    if running and running["running"]:
        return jsonify(
            {"success": True, "total": running["total"], "running": True, "name": name}
        )
    queue = []
    for idx, s in enumerate(playlist.get(actual)):
        vid = s.get("id", "")
        if not vid:
            continue
        queue.append(
            {
                "video_id": vid,
                "url": s.get("ref", "") or f"https://www.youtube.com/watch?v={vid}",
                "title": s.get("title", "Unknown"),
                "index": idx,
                "track": s,
            }
        )
    if not queue:
        return jsonify({"error": "no online tracks to download"}), 400
    job = {
        "name": name,
        "total": len(queue),
        "done": 0,
        "ok": 0,
        "skipped": 0,
        "failed": 0,
        "running": True,
        "format": _resolve_dl_fmt(data.get("format")),
        "files": [],
        "started": time.time(),
        "queue": queue,
    }
    finished = [n for n, j in _playlist_dl_jobs.items() if not j["running"]]
    for n in finished[: max(0, len(_playlist_dl_jobs) - 7)]:
        _playlist_dl_jobs.pop(n, None)
    _playlist_dl_jobs[actual] = job
    threading.Thread(
        target=_playlist_dl_worker, args=(actual,), name="playlist-dl", daemon=True
    ).start()
    return jsonify(
        {"success": True, "total": len(queue), "name": name, "format": job["format"]}
    )


@app.route("/api/playlist/download")
def api_playlist_download_status():
    now = time.time()
    for n in list(_playlist_dl_jobs):
        job = _playlist_dl_jobs[n]
        if not job["running"] and now - job["finished"] > PL_DL_JOB_TTL:
            del _playlist_dl_jobs[n]
    jobs = {}
    for n, job in list(_playlist_dl_jobs.items()):
        exists = playlist.resolve_name(n)
        if exists is None:
            del _playlist_dl_jobs[n]
            continue
        jobs[n] = _playlist_dl_snapshot(job)
    return jsonify({"jobs": jobs})


@app.route("/api/playlist/export")
def api_playlist_export():
    from io import BytesIO

    name = request.args.get("name", "").strip()
    actual, err = _resolve_playlist_or_error(name)
    if err:
        return err
    tracks = playlist.get(actual)
    lines = ["#EXTM3U"]
    for t in tracks:
        dur = int(t.get("duration") or 0)
        lines.append(f"#EXTINF:{dur},{_truncate_title(t.get('title', 'Unknown'))}")
        lines.append(t.get("local_path") or t.get("ref", ""))
    buf = BytesIO(("\n".join(lines) + "\n").encode())
    filename = f"{playlist._slugify(actual)}.m3u"
    return send_file(
        buf,
        mimetype="audio/x-mpegurl",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/playlist/import", methods=["POST"])
def api_playlist_import():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "missing file"}), 400
    name = (request.form.get("name") or "").strip()
    suffix = pathlib.Path(upload.filename).suffix or ".m3u"
    with tempfile.TemporaryDirectory(prefix="flow-import-") as tmp:
        path = pathlib.Path(tmp) / ("playlist" + suffix)
        upload.save(str(path))
        try:
            result = playlist.import_m3u(
                path, name or pathlib.Path(upload.filename).stem
            )
        except Exception as exc:
            logger.warning("Playlist import failed for %s: %s", upload.filename, exc)
            devlog.log_error("LIB", 500, "/api/playlist/import", "flow", f"err={exc}")
            return jsonify({"error": str(exc)}), 500
    if result is None:
        return jsonify({"error": "could not import playlist file"}), 400
    imported_name, count = result
    devlog.log_success(
        "LIB",
        200,
        "/api/playlist/import",
        "flow",
        f"{upload.filename} -> {count} into {imported_name}",
    )
    return jsonify({"success": True, "name": imported_name, "count": count})


@app.route("/api/playlists/create", methods=["POST"])
def api_playlists_create():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name cannot be empty"}), 400
    if playlist.create(name):
        return jsonify({"success": True, "name": name})
    return jsonify({"error": f"playlist '{name}' already exists"}), 409


@app.route("/api/playlists/delete", methods=["POST"])
def api_playlists_delete():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if playlist.delete(name):
        return jsonify({"success": True})
    return jsonify({"error": "playlist not found"}), 404


@app.route("/api/playlist/add", methods=["POST"])
def api_playlist_add():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    song = data.get("song") or {}
    title = (song.get("title") or "").strip()
    if not name or not title:
        return jsonify({"error": "missing name or song title"}), 400
    if name.lower() in playlist.RESERVED_NAMES:
        return jsonify({"error": f"'{name}' is a reserved playlist name"}), 400
    actual = playlist.resolve_name(name)
    if actual is None and not playlist.create(name):
        return jsonify({"error": "could not create playlist"}), 500
    vid = song.get("video_id", "")
    url = song.get("url", "") or (
        f"https://www.youtube.com/watch?v={vid}" if vid else ""
    )
    state, _ = playlist.add_track(
        actual or name,
        playlist.make_track(
            title=title, ref=url, video_id=vid, duration=int(song.get("duration") or 0)
        ),
    )
    added = state == "added"
    return jsonify({"success": True, "added": added, "name": name})


@app.route("/api/playlist/remove", methods=["POST"])
def api_playlist_remove():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    index = data.get("index")
    try:
        index = int(index)
    except TypeError, ValueError:
        return jsonify({"error": "missing valid index"}), 400
    ok, msg = playlist.remove_song(name, index=index)
    if ok:
        return jsonify({"success": True})
    return jsonify({"error": msg}), 400


@app.route("/api/playlists/save", methods=["POST"])
def api_playlists_save():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    songs = data.get("songs") or []
    mode = data.get("mode", "append")
    if not name:
        return jsonify({"error": "name cannot be empty"}), 400
    actual = playlist.resolve_name(name)
    if actual is None:
        if name.lower() in playlist.RESERVED_NAMES:
            return jsonify({"error": f"'{name}' is a reserved playlist name"}), 400
        playlist.create(name)
    elif mode == "overwrite":
        playlist.delete(actual)
        playlist.create(name)
        actual = name
    target = actual or name
    count = 0
    skipped = 0
    for s in songs:
        title = (s.get("title") or "").strip()
        if not title:
            continue
        vid = s.get("video_id", "")
        url = s.get("url", "") or (
            f"https://www.youtube.com/watch?v={vid}" if vid else ""
        )
        state, _ = playlist.add_track(
            target,
            playlist.make_track(
                title=title, ref=url, video_id=vid, duration=int(s.get("duration") or 0)
            ),
        )
        if state == "added":
            count += 1
        else:
            skipped += 1
    resp = {"success": True, "name": name, "count": count}
    if skipped:
        resp["skipped"] = skipped
    return jsonify(resp)


@app.route("/local/<path:filepath>")
def serve_local(filepath):
    p = pathlib.Path(filepath)
    if not p.is_absolute():
        p = pathlib.Path("/") / p
    home = pathlib.Path.home()
    try:
        p = p.resolve()
    except OSError, ValueError:
        return jsonify({"error": "invalid path"}), 400
    if not p.is_relative_to(home):
        return jsonify({"error": "access denied"}), 403
    if not p.exists() or not p.is_file():
        return jsonify({"error": "file not found"}), 404
    if p.suffix.lower() not in AUDIO_EXTENSIONS | IMAGE_EXTENSIONS:
        return jsonify({"error": "not a media file"}), 400
    mimetype, _ = mimetypes.guess_type(str(p))
    return send_file(str(p), mimetype=mimetype or "audio/mpeg", conditional=True)


@app.route("/api/albums")
def api_albums():
    if not MUSIC_DIR.exists():
        return jsonify({"albums": []})
    albums = sorted([d.name for d in MUSIC_DIR.iterdir() if d.is_dir()])
    return jsonify({"albums": albums})


@app.route("/api/album/<album_name>")
def api_album_songs(album_name):
    album_dir = (MUSIC_DIR / album_name).resolve()
    if not album_dir.is_relative_to(MUSIC_DIR.resolve()):
        return jsonify({"error": "access denied"}), 403
    if not album_dir.exists() or not album_dir.is_dir():
        return jsonify({"error": "album not found"}), 404
    songs = []
    for f in sorted(album_dir.iterdir()):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            songs.append(
                {
                    "title": library.title_for_stem(f.stem),
                    "video_id": f.stem,
                    "thumbnail": _thumb_url(f.stem),
                    "path": str(f),
                    "filename": f.name,
                    "album": album_name,
                }
            )
    return jsonify({"results": _by_title(songs)})


@app.route("/api/local-search")
def api_local_search():
    q = request.args.get("q", "").strip().lower()
    results = []

    def _match(f):
        return q in f.stem.lower() or q in library.title_for_stem(f.stem).lower()

    for f in sorted(FLOW_DIR.rglob("*")):
        if f.suffix.lower() in AUDIO_EXTENSIONS and _match(f):
            results.append(
                {
                    "title": library.title_for_stem(f.stem),
                    "video_id": f.stem,
                    "thumbnail": _thumb_url(f.stem),
                    "path": str(f),
                    "filename": f.name,
                }
            )
    if MUSIC_DIR.exists():
        for f in sorted(MUSIC_DIR.rglob("*")):
            if f.suffix.lower() in AUDIO_EXTENSIONS and _match(f):
                results.append(
                    {
                        "title": library.title_for_stem(f.stem),
                        "video_id": f.stem,
                        "thumbnail": _thumb_url(f.stem),
                        "path": str(f),
                        "filename": f.name,
                    }
                )
    return jsonify({"results": _by_title(results)})


@app.route("/api/liked")
def api_liked():
    liked_ids = library.get_liked_ids()
    liked_entries = library.get_liked_entries()
    huge_liked = pathlib.Path.home() / ".flow/downloads/liked songs"
    songs = []
    if huge_liked.exists():
        for f in sorted(huge_liked.iterdir()):
            if f.suffix.lower() in AUDIO_EXTENSIONS:
                songs.append(
                    {
                        "title": library.title_for_stem(f.stem),
                        "video_id": f.stem,
                        "thumbnail": _thumb_url(f.stem),
                        "path": str(f),
                        "filename": f.name,
                    }
                )
    return jsonify(
        {
            "results": _by_title(songs),
            "liked_ids": liked_ids,
            "liked_entries": liked_entries,
        }
    )


def _like_download(video_id: str, save_dir: str, fmt: str):
    if library.get_download_path(video_id):
        return
    if fmt != "webm" and not config.FFMPEG:
        fmt = "webm"
    try:
        _download_audio(video_id, save_dir, fmt)
        devlog.log_success(
            "FETCH", 200, "/api/like", "yt_dlp", f"auto-downloaded {video_id}"
        )
    except Exception as exc:
        logger.warning("Auto-download for liked %s failed: %s", video_id, exc)
        devlog.log_error(
            "FETCH", 500, "/api/like", "yt_dlp", f"vid={video_id} err={exc}"
        )


@app.route("/api/like", methods=["POST"])
def api_like():
    data = request.get_json(force=True)
    video_id = data.get("video_id", "").strip()
    title = data.get("title", "Unknown")
    if not video_id:
        return jsonify({"error": "missing video_id"}), 400
    if library.is_liked(video_id):
        library.mark_unliked(video_id)
        return jsonify({"liked": False, "video_id": video_id})
    library.mark_liked(video_id, title)
    try:
        library.download_thumbnail(video_id)
    except Exception:
        pass
    if config.DOWN_ON_LIKE:
        fmt = data.get("format", config.FORMAT)
        if fmt not in ("opus", "m4a", "mp3", "webm"):
            fmt = config.FORMAT
            if fmt not in ("opus", "m4a", "mp3", "webm"):
                fmt = "webm"
        save_dir = data.get("save_dir", str(FLOW_DIR))
        threading.Thread(
            target=_like_download, args=(video_id, save_dir, fmt), daemon=True
        ).start()
    return jsonify({"liked": True, "video_id": video_id})


@app.route("/api/is-liked")
def api_is_liked():
    video_id = request.args.get("video_id", "").strip()
    if not video_id:
        return jsonify({"liked": False})
    entry = library.get(video_id)
    return jsonify(
        {
            "liked": library.is_liked(video_id),
            "thumbnail": entry.get("thumbnail", "") if entry else "",
        }
    )


@app.route("/thumb/<video_id>")
def serve_thumb(video_id):
    path = pathlib.Path(library.thumbnail_path(video_id))
    if not path.exists():
        return jsonify({"error": "thumbnail not found"}), 404
    return send_file(str(path), mimetype="image/jpeg", conditional=True)


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if request.method == "POST":
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid JSON payload"}), 400
        existing = {}
        if SETTINGS_FILE.exists():
            try:
                loaded = json.loads(SETTINGS_FILE.read_text())
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                pass
        if "format" in data:
            if not config.set_format(data["format"]):
                return jsonify({"error": f"invalid format '{data['format']}'"}), 400
        existing.update(data)
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, SETTINGS_FILE)
        return jsonify({"saved": True, "settings": existing})
    result = {}
    if SETTINGS_FILE.exists():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text())
            if isinstance(loaded, dict):
                result = loaded
        except Exception:
            pass
    result["format"] = config.FORMAT
    return jsonify(result)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/<path:path>")
def catch_all(path):
    return render_template("index.html")
