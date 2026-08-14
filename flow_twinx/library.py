import hashlib
import json
import pathlib
import urllib.request

LIBRARY_FILE = pathlib.Path.home() / ".flow/library.json"
THUMB_CACHE = pathlib.Path.home() / ".flow/downloads/.cache"


def load() -> dict:
    if not LIBRARY_FILE.exists():
        return {}
    try:
        data = json.loads(LIBRARY_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save(library: dict):
    LIBRARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_FILE.write_text(json.dumps(library, indent=2))


def thumbnail_path(video_id: str) -> str:
    return str(THUMB_CACHE / f"{video_id}.jpg")


def thumbnail_url_for(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _set_thumbnail(video_id: str, path: str):
    library = load()
    entry = library.get(video_id)
    if entry is not None:
        entry["thumbnail"] = path
        library[video_id] = entry
        save(library)


def download_thumbnail(video_id: str, thumb_url: str = "") -> str | None:
    if not video_id:
        return None
    path = thumbnail_path(video_id)
    if pathlib.Path(path).exists():
        _set_thumbnail(video_id, path)
        return path
    if not thumb_url:
        thumb_url = thumbnail_url_for(video_id)
    candidates = [thumb_url]
    if "i.ytimg.com/vi/" in thumb_url:
        try:
            vid = thumb_url.split("/vi/")[1].split("/")[0]
            candidates.insert(0, f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
        except IndexError:
            pass
    for url in candidates:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            if not data:
                continue
            THUMB_CACHE.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_bytes(data)
            _set_thumbnail(video_id, path)
            return path
        except Exception:
            continue
    return None


def key_for(url: str, video_id: str = "") -> str:
    if video_id:
        return video_id
    if url:
        return f"s:{hashlib.sha1(url.encode()).hexdigest()}"
    return ""


def _default_entry(video_id: str, title: str = "") -> dict:
    return {
        "liked": False,
        "downloaded": False,
        "title": title,
        "song": None,
        "thumbnail": thumbnail_path(video_id),
    }


def get(video_id: str) -> dict | None:
    return load().get(video_id)


def get_title(video_id: str) -> str:
    entry = get(video_id)
    if entry and entry.get("title"):
        return entry["title"]
    return video_id


def title_for_stem(stem: str) -> str:
    return get_title(stem)


def is_liked(video_id: str) -> bool:
    entry = get(video_id)
    return bool(entry and entry.get("liked"))


def is_downloaded(video_id: str) -> bool:
    return get_download_path(video_id) is not None


def get_download_path(video_id: str) -> str | None:
    entry = get(video_id)
    if not entry or not entry.get("downloaded"):
        return None
    return entry.get("song")


def get_downloaded_ids() -> list:
    return sorted(
        k for k, v in load().items() if v.get("downloaded") and v.get("song")
    )


def get_liked_ids() -> list:
    return sorted(k for k, v in load().items() if v.get("liked"))


def get_liked_entries() -> list:
    return [
        {"video_id": k, "title": v.get("title", "")}
        for k, v in load().items()
        if v.get("liked")
    ]


def mark_liked(video_id: str, title: str = ""):
    if not video_id:
        return
    library = load()
    entry = library.get(video_id)
    if entry is None:
        entry = _default_entry(video_id, title)
    entry["liked"] = True
    if title and not entry.get("title"):
        entry["title"] = title
    entry["thumbnail"] = thumbnail_path(video_id)
    library[video_id] = entry
    save(library)


def mark_unliked(video_id: str):
    if not video_id:
        return
    library = load()
    entry = library.get(video_id)
    if entry is None:
        return
    entry["liked"] = False
    if not entry.get("downloaded"):
        library.pop(video_id, None)
    else:
        library[video_id] = entry
    save(library)


def track_download(video_id: str, path: str, title: str = ""):
    if not video_id:
        return
    library = load()
    entry = library.get(video_id)
    if entry is None:
        entry = _default_entry(video_id, title)
    entry["downloaded"] = True
    entry["song"] = path
    if title and not entry.get("title"):
        entry["title"] = title
    entry["thumbnail"] = thumbnail_path(video_id)
    library[video_id] = entry
    save(library)


def clear_download(video_id: str):
    if not video_id:
        return
    library = load()
    entry = library.get(video_id)
    if entry is None:
        return
    entry["downloaded"] = False
    entry["song"] = None
    if not entry.get("liked"):
        library.pop(video_id, None)
    else:
        library[video_id] = entry
    save(library)


def delete(video_id: str) -> bool:
    path = get_download_path(video_id)
    removed = bool(path)
    if path:
        p = pathlib.Path(path)
        if p.exists():
            p.unlink()
        stem = p.stem if p.suffix else p.name
        for other in p.parent.glob(f"{stem}*"):
            if other != p:
                try:
                    other.unlink()
                except OSError:
                    pass
    thumb = THUMB_CACHE / video_id
    for other in THUMB_CACHE.glob(f"{thumb.name}*"):
        try:
            other.unlink()
        except OSError:
            pass
    clear_download(video_id)
    return removed
