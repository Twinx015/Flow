import json
import urllib.request
import urllib.parse
import urllib.error

from ..imports import config

API_BASE = "https://teenapi.dino.icu/api"


def search(query, limit=10):
    params = urllib.parse.urlencode({"query": query, "limit": str(limit)})
    url = f"{API_BASE}/search/songs?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []
    if not data.get("success"):
        return []
    results = data["data"].get("results", [])
    out = []
    for r in results:
        name = r.get("name", "Unknown")
        dur = r.get("duration", 0)
        primary = r["artists"].get("primary", [])
        artist = primary[0]["name"] if primary else "Unknown"
        out.append((r, f"{name} - {artist}", dur))
    for entry, title, dur in out:
        config.dev_print("Savan Search Result", {
            "title": title,
            "song_id": entry.get("id"),
            "duration": f"{dur}s",
            "album": entry.get("album", {}).get("name"),
            "download_urls": len(entry.get("downloadUrl", [])),
        })
    return out


def thumb_url(entry) -> str:
    images = entry.get("image") or []
    for img in images:
        if img.get("quality") == "500x500" and img.get("url"):
            return img["url"]
    for img in images:
        if img.get("url"):
            return img["url"]
    return ""


def best_url(entry):
    dls = entry.get("downloadUrl", [])
    if not dls:
        return None
    pref = {"320kbps", "160kbps", "96kbps", "48kbps", "12kbps"}
    best = None
    for q in pref:
        for dl in dls:
            if dl["quality"] == q:
                best = dl["url"]
                break
        if best:
            break
    url = best or dls[0]["url"]
    config.dev_print("Savan Best URL", {
        "title": entry.get("name", "Unknown"),
        "selected_url": url[:80] + "..." if len(url) > 80 else url,
        "available_qualities": [dl["quality"] for dl in dls],
    })
    return url


def download(url, dest):
    urllib.request.urlretrieve(url, dest)
    return dest
