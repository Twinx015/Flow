import hashlib
import json
import logging
import shutil
import threading
import urllib.parse
import urllib.request

import yt_dlp

from .imports import config

logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = ("sponsor", "selfpromo", "intro", "outro")

SB_API_URL = "https://sponsor.ajay.app"
SB_TIMEOUT = 5


def enabled():
    """True when the user wants any SponsorBlock handling at all."""
    return bool(config.AD_SKIP)


def _valid_categories():
    try:
        from yt_dlp.postprocessor.sponsorblock import SponsorBlockPP

        return set(SponsorBlockPP.CATEGORIES)
    except Exception:
        return set(DEFAULT_CATEGORIES)


def categories():
    """SponsorBlock categories to fetch/skip, from config (validated)."""
    cats = config.SPONSOR_CATEGORIES
    if not isinstance(cats, (list, tuple)):
        cats = DEFAULT_CATEGORIES
    valid = _valid_categories()
    cleaned = [c for c in cats if isinstance(c, str) and c in valid]
    return cleaned or list(DEFAULT_CATEGORIES)


_ffmpeg_warned = False


def ffmpeg_available():
    """True when the config wants physical cutting AND ffmpeg is actually installed.

    The `ffmpeg` config flag is never trusted on its own: if it says true but the
    binary is missing we warn once and report false (no crash, just no cutting).
    """
    global _ffmpeg_warned
    if not config.FFMPEG:
        return False
    if shutil.which("ffmpeg") is None:
        if not _ffmpeg_warned:
            _ffmpeg_warned = True
            logger.warning(
                "Config has ffmpeg=true but no ffmpeg binary was found on PATH; "
                "sponsor segments will not be physically cut during download."
            )
        return False
    return True


def sponsorblock_pp():
    """Metadata-only SponsorBlock postprocessor (populates sponsorblock_chapters)."""
    return {"key": "SponsorBlock", "categories": categories()}


def _modify_chapters_pp():
    return {
        "key": "ModifyChapters",
        "remove_sponsor_segments": categories(),
        "force_keyframes": True,
    }


def download_postprocessors():
    """Postprocessor list for download mode, per the gating table above.

    ModifyChapters (the ffmpeg-based physical cut) is only attached when both
    `ad_skip` and `ffmpeg_available()` are true. Returns [] when disabled so
    downloaders behave exactly as if the feature did not exist.
    """
    if not enabled():
        return []
    pps = [sponsorblock_pp()]
    if ffmpeg_available():
        pps.append(_modify_chapters_pp())
    return pps


def stream_postprocessors():
    """Postprocessor list for stream-mode extraction.

    Attaches the metadata-only SponsorBlock pp (never ModifyChapters — nothing
    is being cut). Note: yt-dlp only runs postprocessors during a real download,
    so this alone will not populate `sponsorblock_chapters`; `stream_info()`
    additionally fetches segments directly from the SponsorBlock API.
    """
    if not enabled():
        return []
    return [sponsorblock_pp()]


def fetch_segments(video_id, duration=None):
    """Fetch SponsorBlock segments directly from the public API.

    Falls back gracefully (logs a warning, returns []) if the API is down,
    times out, or has no data for the video — never raises.
    """
    if not video_id:
        return []
    try:
        digest = hashlib.sha256(video_id.encode("ascii")).hexdigest()[:4]
        query = urllib.parse.urlencode(
            {
                "service": "YouTube",
                "categories": json.dumps(categories()),
                "actionTypes": json.dumps(["skip", "poi", "chapter"]),
            }
        )
        req = urllib.request.Request(
            f"{SB_API_URL}/api/skipSegments/{digest}?{query}",
            headers={"User-Agent": "flow-twinx"},
        )
        with urllib.request.urlopen(req, timeout=SB_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("SponsorBlock API request failed for %s: %s", video_id, exc)
        return []

    for item in payload or []:
        if item.get("videoID") != video_id:
            continue
        chapters = []
        for seg in item.get("segments") or []:
            start_end = seg.get("segment")
            if not start_end or len(start_end) != 2:
                continue
            start, end = float(start_end[0]), float(start_end[1])
            if start == 0 and end == 0:
                continue
            if duration:
                end = min(end, float(duration))
            if end > start:
                chapters.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "category": seg.get("category", ""),
                        "title": seg.get("description") or seg.get("category", ""),
                        "type": seg.get("actionType", "skip"),
                    }
                )
        return chapters
    return []


def segments(info):
    """Normalize `sponsorblock_chapters` into a clean list of skip ranges.

    Handles missing/empty data (returns []) so callers never treat "no
    sponsor segments" as an error.
    """
    raw = info.get("sponsorblock_chapters") or []
    out = []
    for ch in raw:
        if not isinstance(ch, dict):
            continue
        try:
            start = float(ch.get("start_time"))
            end = float(ch.get("end_time"))
        except (TypeError, ValueError):
            continue
        if end > start:
            out.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "category": ch.get("category", "") or "",
                }
            )
    return out


def stream_url(info):
    """Pick the best audio-only stream URL from an extracted entry.

    Adaptive formats may put the direct (expiring) URL on each requested
    format rather than on the top-level entry, so check `requested_formats`
    first. These URLs are time-limited: use promptly, do not cache long-term.
    """
    for fmt in info.get("requested_formats") or []:
        if (
            fmt.get("acodec") != "none"
            and fmt.get("vcodec") == "none"
            and fmt.get("url")
        ):
            return fmt["url"]
    for fmt in reversed(info.get("formats") or []):
        if (
            fmt.get("acodec") != "none"
            and fmt.get("vcodec") == "none"
            and fmt.get("url")
        ):
            return fmt["url"]
    for fmt in reversed(info.get("formats") or []):
        if fmt.get("acodec") != "none" and fmt.get("url"):
            return fmt["url"]
    return info.get("url")


def stream_info(url, opts=None, with_segments=True):
    """Stream-mode extraction + SponsorBlock segment fetch.

    Calls `extract_info(url, download=False)` with the metadata-only
    SponsorBlock postprocessor attached (per spec). Because yt-dlp only runs
    postprocessors during a real download, we then fill in
    `sponsorblock_chapters` from the SponsorBlock API ourselves when the pp
    left it empty. Never raises for missing sponsor data — the caller gets an
    entry with `sponsorblock_chapters == []`.

    Pass `with_segments=False` to skip the (blocking) SponsorBlock API call —
    useful for latency-sensitive callers such as the web `/play` endpoint, so
    the SponsorBlock round trip never delays playback startup.
    """
    ydl_opts = dict(opts or {})
    if enabled():
        ydl_opts.setdefault("postprocessors", [])
        if not any(p.get("key") == "SponsorBlock" for p in ydl_opts["postprocessors"]):
            ydl_opts["postprocessors"].append(sponsorblock_pp())
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if (
        with_segments
        and info
        and enabled()
        and not info.get("sponsorblock_chapters")
    ):
        info = dict(info)
        info["sponsorblock_chapters"] = fetch_segments(
            info.get("id"), info.get("duration")
        )
    return info


class VlcSkipThread(threading.Thread):
    """Background poller that jumps over SponsorBlock segments during playback.

    Polls `player.get_time()` every `interval` seconds; when the current time
    falls inside a segment it seeks to that segment's end once (tracked in
    `_skipped` so the same segment is never re-skipped repeatedly). Stop it
    cleanly from the main thread when playback ends.
    """

    def __init__(self, player, segments_list, interval=0.35):
        super().__init__(name="sponsor-skip", daemon=True)
        self._player = player
        self._segments = sorted(
            segments_list, key=lambda s: s.get("start_time", 0)
        )
        self._interval = interval
        self._stop_event = threading.Event()
        self._skipped = set()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(self._interval):
            try:
                ms = self._player.get_time()
            except Exception:
                return
            if ms is None or ms < 0:
                continue
            t = ms / 1000.0
            for i, seg in enumerate(self._segments):
                if i in self._skipped:
                    continue
                if seg["start_time"] <= t < seg["end_time"]:
                    try:
                        self._player.set_time(int(seg["end_time"] * 1000))
                    except Exception:
                        continue
                    self._skipped.add(i)
                    break
