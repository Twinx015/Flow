"""Re-fetch downloaded-song metadata, resuming after a YouTube IP block."""

import json
import os
import re
import time

from backend import config, library
from backend.Online import youtube

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _ids_from_files():
    """Video ids taken from the audio file names under the download folder."""
    if not config.DOWNLOAD_DIR.exists():
        return []
    ids, seen = [], set()
    for path in sorted(config.DOWNLOAD_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        video_id = path.stem
        if not _VIDEO_ID.match(video_id) or video_id in seen:
            continue
        seen.add(video_id)
        ids.append(video_id)
    return ids


def _load_state():
    try:
        data = json.loads(config.META_FILE.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(done, failed, total):
    payload = {
        "total": total,
        "done": sorted(done),
        "failed": dict(failed),
        "saved_at": int(time.time()),
    }
    config.META_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.META_FILE.with_suffix(config.META_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, config.META_FILE)


def _clear_state():
    try:
        config.META_FILE.unlink()
    except FileNotFoundError:
        pass


def _meta_from_info(info):
    """Library fields a fresh metadata lookup should populate."""
    meta = library.meta_from_info(info)
    title = config.clean_title(str(info.get("title") or ""), config.MAX_WORDS)
    if title:
        meta["title"] = title
    artist = str(
        info.get("artist") or info.get("creator") or info.get("uploader") or ""
    ).strip()
    if artist:
        meta["artist"] = artist
    return meta


def _short_error(exc):
    first = str(exc).splitlines()[0].strip()
    return first[:160] or exc.__class__.__name__


def _report(title, artist, done, total):
    suffix = f" - {artist}" if artist else ""
    print(f"  [{len(done)}/{total}] {title}{suffix}")


def refetch_all(force=False):
    """Refresh metadata for every downloaded song; a blocked run resumes later."""
    if force:
        _clear_state()
    ids = _ids_from_files()
    if not ids:
        print("No downloaded songs with a video id in the file name.")
        return {"total": 0, "updated": 0, "failed": {}, "blocked": False}

    current = set(ids)
    state = _load_state()
    done = {video_id for video_id in state.get("done", []) if video_id in current}
    failed = {
        video_id: reason
        for video_id, reason in (state.get("failed") or {}).items()
        if video_id in current
    }
    total = len(ids)
    if done:
        print(f"Resuming metadata refresh: {len(done)}/{total} already done.")
    else:
        print(f"Re-fetching metadata for {total} downloaded songs...")

    blocked = False
    interrupted = False
    video_id = ""
    for video_id in ids:
        if video_id in done:
            continue
        try:
            info = youtube.fetch_info(video_id, raise_errors=True)
        except KeyboardInterrupt:
            interrupted = True
            break
        except Exception as exc:
            if youtube.is_rate_limited(exc):
                blocked = True
                break
            failed[video_id] = _short_error(exc)
            done.add(video_id)
            _save_state(done, failed, total)
            print(f"  [{len(done)}/{total}] {video_id}: {failed[video_id]}")
            continue

        if not info:
            failed[video_id] = "no metadata"
            done.add(video_id)
            _save_state(done, failed, total)
            print(f"  [{len(done)}/{total}] {video_id}: no metadata")
            continue

        try:
            library.update_meta(video_id, _meta_from_info(info))
            library.download_thumbnail(video_id, info.get("thumbnail"))
        except Exception as exc:
            failed[video_id] = _short_error(exc)
            done.add(video_id)
            _save_state(done, failed, total)
            print(f"  [{len(done)}/{total}] {video_id}: {failed[video_id]}")
            continue

        done.add(video_id)
        _save_state(done, failed, total)
        title = info.get("title") or library.get_title(video_id)
        artist = info.get("artist") or info.get("uploader") or ""
        _report(title, artist, done, total)

    if blocked:
        _save_state(done, failed, total)
        print(
            f"YouTube is rate-limiting this IP at {video_id}. "
            f"Progress saved ({len(done)}/{total})."
        )
        print("Wait a while, then run `flow --meta` again to continue.")
    elif interrupted:
        _save_state(done, failed, total)
        print(f"Interrupted at {len(done)}/{total}; run `flow --meta` to continue.")
    else:
        _clear_state()
        updated = total - len(failed)
        tail = f", {len(failed)} skipped" if failed else ""
        print(f"Metadata refreshed for {updated} song(s){tail}.")

    return {
        "total": total,
        "updated": len(done) - len(failed),
        "failed": failed,
        "blocked": blocked or interrupted,
    }
