import json
import pathlib

INDEX_FILE = pathlib.Path.home() / ".flow/downloads_index.json"


def load_index() -> dict:
    if not INDEX_FILE.exists():
        return {}
    try:
        data = json.loads(INDEX_FILE.read_text())
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_index(index: dict):
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, indent=2))


def track(video_id: str, path: str, title: str = ""):
    if not video_id:
        return
    index = load_index()
    index[video_id] = {"path": path, "title": title}
    save_index(index)


def get_download_path(video_id: str):
    entry = load_index().get(video_id)
    return entry.get("path") if entry else None


def is_downloaded(video_id: str) -> bool:
    return get_download_path(video_id) is not None


def get_downloaded_ids() -> list:
    return sorted(load_index().keys())


def prune(video_id: str):
    index = load_index()
    if index.pop(video_id, None) is not None:
        save_index(index)


def delete(video_id: str) -> bool:
    path = get_download_path(video_id)
    if not path:
        return False
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
    prune(video_id)
    return True
