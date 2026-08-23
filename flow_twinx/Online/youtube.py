import logging
import pathlib

import yt_dlp

from .. import library, sponsor
from ..imports import config

logger = logging.getLogger(__name__)

SEARCH_CACHE_MAX = 50
_search_cache = {}

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


def search(query, limit=3):
    key = f"{query}:{limit}"
    if key in _search_cache:
        return _search_cache[key]
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        logger.warning("Search failed for %r: %s", query, exc)
        return []
    if not info or not info.get("entries"):
        return []
    results = []
    for entry in info["entries"]:
        title = entry.get("title", "Unknown")
        dur = entry.get("duration", 0)
        results.append((entry, title, dur))
    _search_cache[key] = results
    if len(_search_cache) > SEARCH_CACHE_MAX:
        oldest = next(iter(_search_cache))
        del _search_cache[oldest]
    for entry, title, dur in results:
        config.dev_print(
            "YouTube Search Result",
            {
                "title": entry.get("title", "Unknown"),
                "video_id": entry.get("id"),
                "url": entry.get("webpage_url")
                or entry.get("original_url")
                or entry.get("url")
                or (
                    f"https://www.youtube.com/watch?v={entry['id']}"
                    if entry.get("id")
                    else None
                ),
                "duration": f"{dur}s",
                "uploader": entry.get("uploader", "Unknown"),
                "channel_id": entry.get("channel_id"),
                "view_count": entry.get("view_count"),
                "upload_date": entry.get("upload_date"),
            },
        )
    return results


def download_url(url, outdir, fmt=None):
    opts = {**ydl_opts_dwn, "outtmpl": f"{outdir}/%(id)s.%(ext)s"}
    pps = sponsor.download_postprocessors()
    if fmt and fmt != "webm":
        pps = pps + [{"key": "FFmpegExtractAudio", "preferredcodec": fmt}]
    if pps:
        opts["postprocessors"] = pps
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if fmt and fmt != "webm":
                stem = pathlib.Path(filename).stem
                filename = str(pathlib.Path(outdir) / f"{stem}.{fmt}")
    except Exception as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        raise
    config.dev_print(
        "YouTube Download",
        {
            "url": url,
            "title": info.get("title", "Unknown"),
            "video_id": info.get("id"),
            "filename": filename,
            "filesize": info.get("filesize") or info.get("filesize_approx"),
        },
    )
    library.track_download(info.get("id"), filename, info.get("title", "Unknown"))
    try:
        library.download_thumbnail(info.get("id"), info.get("thumbnail"))
    except Exception:
        pass
    return filename


def fetch_radio(query, max_results=30):
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception as exc:
        logger.warning("Radio seed search failed for %r: %s", query, exc)
        return []
    if not info or not info.get("entries"):
        return []
    video_id = info["entries"][0].get("id")
    if not video_id:
        return []

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


def get_entry(url):
    try:
        entry = sponsor.stream_info(url, opts=ydl_opts_play)
    except Exception as exc:
        logger.warning("Failed to get entry for %s: %s", url, exc)
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
