import pathlib

_CACHE = {}
_CACHE_MAX = 128


def _resolve(source):
    if isinstance(source, (bytes, bytearray)):
        return source
    try:
        from .terminal_img import resolve_source
    except ImportError:
        from terminal_img import resolve_source

    return resolve_source(str(source))


def _default_colors():
    try:
        from .config import ImgColors
    except ImportError:
        try:
            from config import ImgColors
        except Exception:
            return 1
    try:
        return max(1, min(3, int(ImgColors)))
    except Exception:
        return 1


def palette(source, n=None):
    """Return the n most common colors as a list of (r, g, b) tuples."""
    if n is None:
        n = _default_colors()
    n = max(1, min(3, int(n)))
    try:
        src = _resolve(source)
        if src is None:
            return []
        key = None
        if isinstance(src, pathlib.Path):
            key = (str(src), src.stat().st_mtime_ns, n)
            cached = _CACHE.get(key)
            if cached is not None:
                return cached
        from PIL import Image

        with Image.open(src) as im:
            rgb = im.convert("RGB")
            rgb.thumbnail((64, 64))
            q = rgb.quantize(colors=max(8, n * 6))
        pal = q.getpalette() or []
        buckets = sorted(q.getcolors(64 * 64) or [], reverse=True)
        out = []
        for _, idx in buckets:
            i = idx * 3
            if i + 3 > len(pal):
                break
            out.append(tuple(pal[i : i + 3]))
            if len(out) >= n:
                break
        if key is not None and out:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = out
        return out
    except Exception:
        return []


def hex_str(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def dominant_color(source, fallback=(40, 40, 40)):
    p = palette(source)
    return p[0] if p else fallback


def dominant_hex(source, fallback="#282828"):
    fb = tuple(int(fallback[i : i + 2], 16) for i in (1, 3, 5))
    return hex_str(dominant_color(source, fb))


if __name__ == "__main__":
    import sys

    if len(sys.argv) not in (2, 3):
        print(f"usage: {sys.argv[0]} <image-path-or-url> [colors 1-3]")
        sys.exit(1)
    n = int(sys.argv[2]) if len(sys.argv) == 3 else None
    cols = palette(sys.argv[1], n)
    print(" ".join(hex_str(c) for c in cols) if cols else "-")
