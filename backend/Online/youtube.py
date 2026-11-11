import logging
import pathlib
import re
import sys
import threading
import time
import urllib.parse

import yt_dlp

from backend import config, library, rich_display, sponsor

logger = logging.getLogger(__name__)
try:
    from backend import logger as flog
except Exception:
    flog = None

SEARCH_CACHE_MAX = 50
_search_cache = {}

DOWNLOAD_ATTEMPTS = 3

_ytmusic = None
_ytmusic_lock = threading.Lock()

BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "noplaylist": True,
    "format": "bestaudio/best",
    "skip_download": True,
    "socket_timeout": 10,
    "retries": 2,
    "extractor_retries": 2,
    "js_runtimes": {"node": {}},
    "extractor_args": {"youtube": {"player_client": ["android"]}},
}

ydl_opts = {
    **BASE_OPTS,
    "default_search": "ytsearch1",
    "extract_flat": True,
}

ydl_opts_dwn = {
    **BASE_OPTS,
    "skip_download": False,
    "outtmpl": "downloads/%(id)s.%(ext)s",
}

ydl_opts_radio = {
    **BASE_OPTS,
    "noplaylist": False,
    "extract_flat": True,
}

ydl_opts_play = {
    **BASE_OPTS,
}


def _get_ytmusic():
    global _ytmusic
    if _ytmusic is None:
        with _ytmusic_lock:
            if _ytmusic is None:
                from ytmusicapi import YTMusic

                _ytmusic = YTMusic()
    return _ytmusic


def _duration_seconds(item):
    """Song length in seconds, from `duration_seconds` or a `m:ss` string."""
    seconds = item.get("duration_seconds")
    if isinstance(seconds, int) and seconds > 0:
        return seconds
    text = str(item.get("duration") or "")
    if ":" not in text:
        return 0
    try:
        total = 0
        for part in text.split(":"):
            total = total * 60 + int(part)
    except ValueError:
        return 0
    return total


def _music_entry(item):
    """A YouTube Music song reshaped as a flat yt-dlp entry for the rest of flow."""
    video_id = item.get("videoId")
    if not video_id:
        return None
    artists = [a.get("name") for a in item.get("artists") or [] if a.get("name")]
    credits = ", ".join(artists)
    thumbs = item.get("thumbnails") or []
    return {
        "id": video_id,
        "title": item.get("title") or "Unknown",
        "duration": _duration_seconds(item),
        "uploader": credits,
        "artist": credits,
        "album": (item.get("album") or {}).get("name"),
        "channel_id": (item.get("artists") or [{}])[0].get("id"),
        "thumbnail": thumbs[-1].get("url") if thumbs else None,
        "thumbnails": thumbs,
        "view_count": item.get("views"),
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "extractor": "youtube:music",
    }


_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
}


def video_id_from_url(text):
    """The YouTube video id in a watch/short/embed/share link, or None."""
    raw = (text or "").strip()
    if not raw or " " in raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _VIDEO_HOSTS:
        return None
    path = parsed.path or ""
    if host == "youtu.be":
        parts = path.strip("/").split("/")
        video_id = parts[0] if parts else ""
    elif path == "/watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    elif path.startswith(("/shorts/", "/embed/", "/live/")):
        parts = path.strip("/").split("/")
        video_id = parts[1] if len(parts) > 1 else ""
    else:
        return None
    return video_id if _VIDEO_ID.match(video_id) else None


def search(query, limit=3):
    """Search via `config.SearchSource`; returns (entry, title, duration) tuples."""
    video_id = video_id_from_url(query)
    if video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"
        entry = get_entry(url)
        if not entry:
            return []
        title = entry.get("title") or "Unknown"
        duration = int(entry.get("duration") or 0)
        return [(entry, title, duration)]
    key = f"{config.SearchSource}:{query}:{limit}"
    if key in _search_cache:
        return _search_cache[key]
    if config.SearchSource == "youtube":
        results = _search_youtube(query, limit)
    else:
        results = _search_music(query, limit)
    _search_cache[key] = results
    if len(_search_cache) > SEARCH_CACHE_MAX:
        oldest = next(iter(_search_cache))
        del _search_cache[oldest]
    return results


def _search_music(query, limit):
    """YouTube Music song search, reshaped into flat yt-dlp entries."""
    try:
        from backend import logger as flog

        flog.info(
            "youtube_music",
            "search",
            f"songs:{query}",
            {"query": query, "limit": limit},
        )
    except Exception:
        pass
    try:
        raw = _get_ytmusic().search(query, filter="songs", limit=limit)
    except Exception as exc:
        logger.warning("YouTube Music search failed for %r: %s", query, exc)
        try:
            from backend import logger as flog

            flog.error(
                "youtube_music", "search_error", str(exc), {"query": query}, exc_info=True
            )
        except Exception:
            pass
        return []
    results = []
    for item in raw or []:
        entry = _music_entry(item)
        if entry:
            results.append((entry, entry["title"], entry["duration"]))
    return results[:limit]


def _search_youtube(query, limit):
    """Plain yt-dlp `ytsearchN` search, same shape as `_search_music`."""
    try:
        from backend import logger as flog

        flog.info(
            "yt_dlp",
            "search",
            f"ytsearch{limit}:{query}",
            {"query": query, "limit": limit},
        )
    except Exception:
        pass
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        logger.warning("Search failed for %r: %s", query, exc)
        try:
            from backend import logger as flog

            flog.error(
                "yt_dlp", "search_error", str(exc), {"query": query}, exc_info=True
            )
        except Exception:
            pass
        return []
    results = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        title = entry.get("title", "Unknown")
        dur = entry.get("duration", 0)
        results.append((entry, title, dur))
    return results[:limit]


def progress_hook(d):
    """yt-dlp hook: draw a `\\r` block bar while a track downloads."""
    if d.get("status") != "downloading":
        return
    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
    got = d.get("downloaded_bytes") or 0
    if total <= 0:
        return
    pct = got / total * 100
    if rich_display.active():
        rich_display.download_update(got, total)
        return
    title = (d.get("info_dict") or {}).get("title", "") or ""
    if len(title) > 26:
        title = title[:25] + "…"
    label = f"  {title}" if title else ""
    sys.stdout.write(
        f"\r{label}  {config.progress_bar(got / total, config.BarWidth)} {pct:5.1f}%"
    )
    sys.stdout.flush()


def download_url(url, outdir, fmt=None, progress=False):
    opts = {**ydl_opts_dwn, "outtmpl": f"{outdir}/%(id)s.%(ext)s"}
    if progress and sys.stdout.isatty():
        opts["progress_hooks"] = [progress_hook]
        rich_display.download_start()
    pps = sponsor.download_postprocessors()
    if fmt and fmt != "webm":
        pps = pps + [{"key": "FFmpegExtractAudio", "preferredcodec": fmt}]
    if pps:
        opts["postprocessors"] = pps
    try:
        from backend import logger as flog

        flog.log_track_event(
            "yt_dlp",
            "download_start",
            {"url": url, "fmt": fmt, "outdir": str(outdir)},
            {"url": url, "fmt": fmt},
        )
    except Exception:
        try:
            from backend import logger as flog

            flog.info(
                "yt_dlp",
                "download",
                f"downloading {url}",
                {"url": url, "fmt": fmt, "outdir": str(outdir)},
            )
        except Exception:
            pass
    last_exc = None
    filename = ""
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if fmt and fmt != "webm":
                    stem = pathlib.Path(filename).stem
                    filename = str(pathlib.Path(outdir) / f"{stem}.{fmt}")
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Download attempt %s/%s failed for %s: %s",
                attempt,
                DOWNLOAD_ATTEMPTS,
                url,
                exc,
            )
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(2 * attempt)
        else:
            last_exc = None
    if last_exc is not None:
        rich_display.download_stop()
        logger.warning("Download failed for %s: %s", url, last_exc)
        try:
            from backend import logger as flog

            flog.error(
                "yt_dlp", "download_error", str(last_exc), {"url": url}, exc_info=True
            )
        except Exception:
            pass
        config.down_notify(url, error=True)
        raise last_exc
    rich_display.download_stop()
    if opts.get("progress_hooks"):
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()
    dl_info_full = {
        "url": url,
        "title": info.get("title", "Unknown"),
        "video_id": info.get("id"),
        "uploader": info.get("uploader", "Unknown"),
        "artist": info.get("artist") or info.get("uploader", "Unknown"),
        "duration": info.get("duration", 0),
        "ext": info.get("ext"),
        "filename": filename,
        "filesize": info.get("filesize") or info.get("filesize_approx"),
    }
    try:
        from backend import logger as flog

        flog.log_track_event("yt_dlp", "download_complete", dl_info_full, dl_info_full)
    except Exception:
        pass
    config.dev_print(
        "YouTube Download",
        dl_info_full,
    )
    library.track_download(
        info.get("id"),
        filename,
        info.get("title", "Unknown"),
        meta=library.meta_from_info(info),
    )
    config.down_notify(info.get("title", "Unknown"))
    try:
        library.download_thumbnail(info.get("id"), info.get("thumbnail"))
    except Exception:
        pass
    return filename


_RATE_LIMIT_MARKERS = (
    "429",
    "too many requests",
    "not a bot",
    "captcha",
    "unusual traffic",
    "request was blocked",
)


def is_rate_limited(exc) -> bool:
    """Whether a fetch failure looks like YouTube blocking this IP."""
    low = str(exc).lower()
    return any(marker in low for marker in _RATE_LIMIT_MARKERS)


def fetch_info(video_id: str, raise_errors: bool = False):
    """Full metadata for one video, or None; `raise_errors` lets callers classify failure."""
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    url = (
        video_id if "://" in video_id else f"https://www.youtube.com/watch?v={video_id}"
    )
    try:
        return sponsor.stream_info(url, opts=ydl_opts_play, with_segments=False)
    except Exception as exc:
        logger.warning("Metadata fetch failed for %s: %s", video_id, exc)
        if raise_errors:
            raise
        return None


def fetch_radio_for_id(video_id, max_results=30):
    """Auto-mix tracks seeded from one video id, as (title, id, duration) triples."""
    radio_url = f"https://www.youtube.com/watch?v={video_id}&list=RDMM{video_id}"
    config.dev_print(
        "YouTube Radio Seed",
        {
            "seed_video_id": video_id,
            "radio_url": radio_url,
        },
    )
    opts = {**ydl_opts_radio, "playlistend": max_results}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(radio_url, download=False)
    except Exception as exc:
        logger.warning("Radio fetch failed for %s: %s", radio_url, exc)
        return []
    entries = info.get("entries", [])
    results = []
    for entry in entries:
        if not entry:
            continue
        title = entry.get("title", "Unknown")
        vid = entry.get("id")
        dur = entry.get("duration", 0)
        if vid:
            results.append((title, vid, dur))
    config.dev_print(
        "YouTube Radio Tracks",
        [
            {
                "title": t,
                "video_id": v,
                "url": f"https://www.youtube.com/watch?v={v}",
                "duration": f"{d}s",
            }
            for t, v, d in results
        ],
    )
    return results


def fetch_radio(query, max_results=30):
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception as exc:
        logger.warning("Radio seed search failed for %r: %s", query, exc)
        return []
    if not info or not info.get("entries"):
        return []
    seed = info["entries"][0]
    if not seed:
        return []
    video_id = seed.get("id")
    if not video_id:
        return []
    return fetch_radio_for_id(video_id, max_results)


def _entry_failure(exc) -> str:
    """Classify an entry-extraction failure: age / signin / format / other."""
    low = str(exc).lower()
    if "confirm your age" in low or "age" in low:
        return "age"
    if "signed-in" in low or "sign in" in low:
        return "signin"
    if "requested format is not available" in low:
        return "format"
    return "other"


def _print_entry_failure(exc):
    """Print an actionable hint for entry failures (age gating, empty formats)."""
    kind = _entry_failure(exc)
    if kind in ("age", "signin"):
        print(
            f"{config.RED}This video is age-restricted or sign-in only. {hint}{config.Reset}"
        )
    elif kind == "format":
        print(
            f"{config.RED}This video has no playable audio format available.{config.Reset}"
        )
    else:
        print(f"{config.RED}Could not load this video: {exc}{config.Reset}")


def get_entry(url):
    try:
        entry = sponsor.stream_info(url, opts=ydl_opts_play)
    except Exception as exc:
        logger.debug("Failed to get entry for %s: %s", url, exc)
        _print_entry_failure(exc)
        return None
    if entry:
        formats_info = []
        for fmt in entry.get("formats", []):
            formats_info.append(
                {
                    "format_id": fmt.get("format_id"),
                    "ext": fmt.get("ext"),
                    "acodec": fmt.get("acodec"),
                    "vcodec": fmt.get("vcodec"),
                    "url": fmt.get("url", "")[:80] + "..."
                    if fmt.get("url") and len(fmt.get("url", "")) > 80
                    else fmt.get("url"),
                }
            )
        config.dev_print(
            "YouTube Entry (Full)",
            {
                "title": entry.get("title"),
                "video_id": entry.get("id"),
                "webpage_url": entry.get("webpage_url"),
                "original_url": entry.get("original_url"),
                "uploader": entry.get("uploader"),
                "channel_id": entry.get("channel_id"),
                "channel_url": entry.get("channel_url"),
                "duration": f"{entry.get('duration', 0)}s",
                "view_count": entry.get("view_count"),
                "like_count": entry.get("like_count"),
                "upload_date": entry.get("upload_date"),
                "description": (entry.get("description") or "")[:120],
                "formats_count": len(entry.get("formats", [])),
                "formats": formats_info,
            },
        )
    return entry


YTM_FILTERS = {
    "songs": "songs",
    "videos": "videos",
    "albums": "albums",
    "artists": "artists",
    "playlists": "playlists",
    "community": "community_playlists",
}


def _best_thumb(thumbs):
    """Largest thumbnail URL from a YT Music thumbs list or inline dict."""
    items = thumbs.get("thumbnails") if isinstance(thumbs, dict) else thumbs
    if not items:
        return ""
    best = max(items, key=lambda t: t.get("width") or 0)
    return best.get("url") or ""


def _artist_names(item):
    """Comma-joined artist names of a YT Music item."""
    names = [a.get("name") for a in item.get("artists") or [] if a.get("name")]
    return ", ".join(names) if names else "Unknown"


def _ytm_track(item):
    """A YT Music song flattened into the web track shape, or None."""
    vid = item.get("videoId")
    if not vid or item.get("isAvailable") is False:
        return None
    album = item.get("album")
    if isinstance(album, dict):
        album = album.get("name")
    return {
        "video_id": vid,
        "title": item.get("title") or "Unknown",
        "artist": _artist_names(item),
        "album": album or "",
        "duration": _duration_seconds(item),
        "thumbnail": _best_thumb(item.get("thumbnails")),
    }


def _ytm_card(item):
    """Shape any YT Music browse entry as a typed card, or None."""
    vid = item.get("videoId")
    if vid:
        track = _ytm_track(item)
        if not track:
            return None
        track["type"] = "video" if item.get("resultType") == "video" else "song"
        views = item.get("view_count") or item.get("views")
        if views:
            track["views"] = views
        return track
    bid = item.get("browseId") or ""
    if bid.startswith("MPREb"):
        return {
            "type": "album",
            "album_id": bid,
            "playlist_id": item.get("audioPlaylistId") or item.get("playlistId") or "",
            "title": item.get("title") or "Unknown",
            "artist": _artist_names(item),
            "year": item.get("year") or "",
            "thumbnail": _best_thumb(item.get("thumbnails")),
        }
    if item.get("resultType") == "artist" or bid.startswith("UC"):
        return {
            "type": "artist",
            "artist_id": bid,
            "title": item.get("artist") or item.get("name") or "Unknown",
            "thumbnail": _best_thumb(item.get("thumbnails")),
            "subscribers": item.get("subscribers") or "",
        }
    pid = item.get("playlistId") or item.get("audioPlaylistId") or (
        bid if bid.startswith("VL") else ""
    )
    if pid:
        return {
            "type": "playlist",
            "playlist_id": pid,
            "title": item.get("title") or "Unknown",
            "artist": item.get("author") or item.get("subtitle") or "",
            "item_count": item.get("itemCount") or item.get("trackCount") or item.get("playlistLength") or "",
            "thumbnail": _best_thumb(item.get("thumbnails")),
        }
    return None


def _ytm_cards(entries, per=None):
    """Typed cards from a list of raw browse entries, optionally capped."""
    cards = []
    for entry in entries or []:
        card = _ytm_card(entry)
        if card:
            cards.append(card)
        if per is not None and len(cards) >= per:
            break
    return cards


def ytm_home(per_shelf=8, max_shelves=6):
    """YT Music home shelves as titled sections of typed cards."""
    try:
        shelves = _get_ytmusic().get_home(limit=max_shelves)
    except Exception as exc:
        logger.warning("YT Music home failed: %s", exc)
        return []
    sections = []
    for shelf in shelves or []:
        cards = _ytm_cards(shelf.get("contents"), per=per_shelf)
        if cards:
            sections.append(
                {"title": shelf.get("title") or "For You", "items": cards}
            )
    return sections[:max_shelves]


def ytm_charts():
    """YT Music charts: top-video chart playlists plus trending artists."""
    try:
        charts = _get_ytmusic().get_charts()
    except Exception as exc:
        logger.warning("YT Music charts failed: %s", exc)
        return {"playlists": [], "artists": []}
    playlists = []
    for item in charts.get("videos") or []:
        pid = item.get("playlistId")
        if not pid:
            continue
        playlists.append(
            {
                "type": "playlist",
                "playlist_id": pid,
                "title": item.get("title") or "Top videos",
                "artist": "YouTube Music Charts",
                "thumbnail": _best_thumb(item.get("thumbnails")),
            }
        )
    artists = []
    for item in charts.get("artists") or []:
        if not item.get("browseId"):
            continue
        artists.append(
            {
                "type": "artist",
                "artist_id": item["browseId"],
                "title": item.get("title") or "Unknown",
                "thumbnail": _best_thumb(item.get("thumbnails")),
                "subscribers": item.get("subscribers") or "",
                "rank": str(item.get("rank") or ""),
            }
        )
    return {"playlists": playlists, "artists": artists}


def ytm_explore():
    """YT Music explore: trending songs, new releases and mood/genre chips."""
    try:
        explore = _get_ytmusic().get_explore()
    except Exception as exc:
        logger.warning("YT Music explore failed: %s", exc)
        return {"trending": [], "new_releases": [], "moods": []}
    trending = _ytm_cards((explore.get("trending") or {}).get("items"))
    releases = [
        card
        for card in _ytm_cards(explore.get("new_releases"))
        if card.get("type") == "album"
    ]
    moods = [
        {"title": item.get("title") or "", "params": item.get("params") or ""}
        for item in explore.get("moods_and_genres") or []
        if item.get("params")
    ]
    return {
        "trending": trending[:20],
        "new_releases": releases[:20],
        "moods": moods,
    }


def ytm_mood_categories():
    """All mood/genre categories flattened to {group,title,params} rows."""
    try:
        cats = _get_ytmusic().get_mood_categories()
    except Exception as exc:
        logger.warning("YT Music mood categories failed: %s", exc)
        return []
    rows = []
    for group, items in cats.items():
        for item in items:
            if item.get("params"):
                rows.append(
                    {
                        "group": group,
                        "title": item.get("title") or "",
                        "params": item["params"],
                    }
                )
    return rows


def ytm_mood_playlists(params):
    """Community/RD playlists under one mood or genre category."""
    try:
        raw = _get_ytmusic().get_mood_playlists(params)
    except Exception as exc:
        logger.warning("YT Music mood playlists failed for %r: %s", params, exc)
        return []
    return _ytm_cards(raw)


def ytm_playlist(playlist_id, limit=None):
    """A YouTube Music playlist reshaped with its tracks as web rows."""
    try:
        ytm = _get_ytmusic()
        info = ytm.get_playlist(playlist_id, limit=limit)
    except Exception as exc:
        logger.warning("YT Music playlist failed for %r: %s", playlist_id, exc)
        return {}
    author = info.get("author")
    if isinstance(author, dict):
        author = author.get("name") or ""
    return {
        "playlist_id": playlist_id,
        "title": info.get("title") or "Unknown",
        "author": author or "",
        "description": (info.get("description") or "").strip(),
        "track_count": info.get("trackCount") or 0,
        "duration": info.get("duration") or "",
        "year": info.get("year") or "",
        "thumbnail": _best_thumb(info.get("thumbnails")),
        "tracks": [c for c in _ytm_cards(info.get("tracks")) if c.get("video_id")],
    }


def ytm_album(album_id):
    """A YouTube Music album reshaped with its tracks."""
    try:
        info = _get_ytmusic().get_album(album_id)
    except Exception as exc:
        logger.warning("YT Music album failed for %r: %s", album_id, exc)
        return {}
    artist = _artist_names(info)
    thumb = _best_thumb(info.get("thumbnails"))
    tracks = [c for c in _ytm_cards(info.get("tracks")) if c.get("video_id")]
    for track in tracks:
        if not track.get("thumbnail"):
            track["thumbnail"] = thumb
    return {
        "album_id": album_id,
        "playlist_id": info.get("audioPlaylistId") or "",
        "title": info.get("title") or "Unknown",
        "artist": artist,
        "year": info.get("year") or "",
        "track_count": info.get("trackCount") or 0,
        "duration": info.get("duration") or "",
        "description": (info.get("description") or "").strip(),
        "thumbnail": thumb,
        "tracks": tracks,
    }


def ytm_artist(artist_id):
    """A YouTube Music artist page: top songs, videos and releases."""
    try:
        info = _get_ytmusic().get_artist(artist_id)
    except Exception as exc:
        logger.warning("YT Music artist failed for %r: %s", artist_id, exc)
        return {}

    def section(name):
        items = (info.get(name) or {}).get("results") or []
        first = items[0] if items else {}
        if isinstance(first, dict) and first.get("title") in ("Top songs", "Videos"):
            items = items[1:]
        return _ytm_cards(items)

    songs = [c for c in section("songs") if c.get("video_id")]
    videos = [c for c in section("videos") if c.get("video_id")]
    albums = [c for c in section("albums") if c.get("type") == "album"]
    return {
        "artist_id": artist_id,
        "name": info.get("name") or "Unknown",
        "description": (info.get("description") or "").strip(),
        "subscribers": info.get("subscribers") or "",
        "monthly_listeners": info.get("monthlyListeners") or "",
        "thumbnail": _best_thumb(info.get("thumbnails")),
        "shuffle_id": info.get("shuffleId") or "",
        "radio_id": info.get("radioId") or "",
        "songs": songs[:20],
        "videos": videos[:20],
        "albums": albums[:20],
    }


def ytm_search(query, filter_name=None, limit=10):
    """YT Music search rows, optionally narrowed by a YTM_FILTERS name."""
    try:
        raw = _get_ytmusic().search(
            query, filter=YTM_FILTERS.get(filter_name), limit=limit
        )
    except Exception as exc:
        logger.warning("YT Music search failed for %r: %s", query, exc)
        return []
    rows = []
    for item in raw or []:
        card = _ytm_card(item)
        if card:
            rows.append(card)
    return rows[:limit]
