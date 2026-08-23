import pathlib
import shutil

from ..imports import config
from .. import library

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
LIKED_DIR_NAME = "liked songs"


def _liked_dir() -> pathlib.Path:
    return config.DOWNLOAD_DIR / LIKED_DIR_NAME


def get_all_songs() -> list[pathlib.Path]:
    if not config.DOWNLOAD_DIR.exists():
        return []
    return sorted(
        [
            p
            for p in config.DOWNLOAD_DIR.rglob("*")
            if p.suffix.lower() in AUDIO_EXTENSIONS
        ]
    )


def get_songs() -> list[pathlib.Path]:
    liked = _liked_dir()
    return [s for s in get_all_songs() if liked not in s.parents]


def get_albums() -> list[str]:
    if not config.DOWNLOAD_DIR.exists():
        return []
    liked = _liked_dir()
    return sorted(
        [d.name for d in config.DOWNLOAD_DIR.iterdir() if d.is_dir() and d != liked]
    )


def get_album_songs(album: str) -> list[pathlib.Path]:
    album_dir = config.DOWNLOAD_DIR / album
    if not album_dir.exists() or not album_dir.is_dir():
        return []
    return sorted(
        [p for p in album_dir.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS]
    )


def get_liked_songs() -> list[pathlib.Path]:
    liked = _liked_dir()
    if not liked.exists():
        return []
    return sorted([p for p in liked.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS])


def like_song(song_path: pathlib.Path) -> pathlib.Path | None:
    liked = _liked_dir()
    liked.mkdir(parents=True, exist_ok=True)
    dest = liked / song_path.name
    if dest.exists():
        return None
    shutil.copy2(song_path, dest)
    return dest


def unlike_song(song_path: pathlib.Path) -> bool:
    liked = _liked_dir()
    dest = liked / song_path.name
    if dest.exists():
        dest.unlink()
        return True
    return False


def display_name(song_path: pathlib.Path) -> str:
    return library.title_for_stem(song_path.stem)


def find_songs(query: str) -> list[pathlib.Path]:
    q = query.lower()
    return [
        s for s in get_songs() if q in s.stem.lower() or q in display_name(s).lower()
    ]


def get_song_names() -> list[str]:
    return sorted(set(display_name(s) for s in get_songs()))


def get_album_names() -> list[str]:
    return get_albums()
