"""Storage tests for `library.db` and `history.db`.

Both are SQLite, and both are the only place play state lives, so these cover
the three things that are easy to get wrong:

* the public dict-shaped API survives the move off `library.json`,
* a play count outlives an unlike / delete (the row is only dropped when
  nothing at all is left to remember), and
* online and offline playback are counted in `library.db` but only online
  playback is logged as an event in `history.db`,
* a user rename (`library.rename`) outranks whatever metadata a later
  download or refresh writes, and the web route that exposes it.

Tests share the scratch `HOME` from `conftest.py`, and both modules resolve
their paths at import time, so every test uses video ids unique to itself.
"""

import json
import time

import pytest

from backend import config, history, library


@pytest.fixture(autouse=True)
def clean_history():
    """`history.db` is append-only, so start every test from an empty log.

    Without this the timeline tests would see rows left by whichever tests ran
    before them and their ordering assertions would be order-dependent.
    """
    history.clear()
    yield
    history.clear()


@pytest.fixture(autouse=True)
def clean_library():
    """Drop any row this test adds, so the shared scratch `library.db` does
    not leak state into other test modules (`test_summary.py` reads the same
    database and asserts on absolute totals)."""
    before = set(library.load())
    yield
    added = set(library.load()) - before

    def drop(data):
        for video_id in added:
            data.pop(video_id, None)
        return True

    if added:
        library._mutate(drop)
        with library._write() as conn:
            conn.executemany(
                "DELETE FROM song_tags WHERE video_id = ?",
                [(video_id,) for video_id in added],
            )


@pytest.fixture
def song():
    """A fresh video id per test, so counts never bleed between tests."""
    song.counter = getattr(song, "counter", 0) + 1
    return f"testvid{song.counter:03d}"


# Titles are cleaned by `config._truncate_title` before they are stored, which
# drops filler words ("song", "music", "official", ...) and caps at six words.
# These are deliberately filler-free so the assertions below read literally.
SONG_TITLE = "Around the World"
OTHER_TITLE = "Teardrop"
ARTIST = "Daft Punk"


# ---------------------------------------------------------------------------
# library.db — the public API
# ---------------------------------------------------------------------------

def test_load_returns_empty_dict_initially():
    assert isinstance(library.load(), dict)


def test_mark_liked_then_read_back(song):
    library.mark_liked(song, SONG_TITLE)
    entry = library.get(song)
    assert entry["liked"] is True
    assert entry["title"] == SONG_TITLE
    assert song in library.get_liked_ids()
    assert library.is_liked(song) is True


def test_get_returns_none_for_unknown_video_id():
    assert library.get("definitely-not-a-real-id") is None
    assert library.get("") is None
    assert library.get_title("definitely-not-a-real-id") == "definitely-not-a-real-id"


def test_mark_unliked_drops_a_never_played_row(song):
    library.mark_liked(song, SONG_TITLE)
    library.mark_unliked(song)
    assert library.get(song) is None
    assert song not in library.get_liked_ids()


def test_track_download_and_clear(song):
    library.track_download(song, "/tmp/nope.webm", SONG_TITLE)
    assert library.get_download_path(song) == "/tmp/nope.webm"
    assert library.is_downloaded(song) is True
    assert song in library.get_downloaded_ids()
    library.clear_download(song)
    assert library.get_download_path(song) is None
    assert library.is_downloaded(song) is False


def test_mutate_rollback_when_mutation_declines(song):
    """A mutator returning False must not persist anything."""
    library.mark_liked(song, SONG_TITLE)

    def mutate(data):
        data[song]["liked"] = False
        return False

    library._mutate(mutate)
    assert library.is_liked(song) is True


def test_titles_are_cleaned_on_write(song, monkeypatch):
    """`config._truncate_title` drops filler words and caps at six words."""
    monkeypatch.setattr(config, "SearchSource", "youtube")
    library.mark_liked(song, "One Two Three Four Five Six Seven Eight")
    assert library.get(song)["title"] == "One Two Three Four Five Six..."
    library.mark_liked("filler-" + song, "Around the World Official Music Video")
    assert library.get("filler-" + song)["title"] == "Around the World"


def test_ytmusic_titles_are_kept_as_is(song, monkeypatch):
    """YouTube Music titles are already clean, so writes keep them untouched."""
    monkeypatch.setattr(config, "SearchSource", "ytmusic")
    title = "Don't Worry (feat. Gurlez Akhtar)"
    library.mark_liked("music-" + song, title)
    assert library.get("music-" + song)["title"] == title


def test_rename_replaces_the_shown_title(song):
    library.mark_liked(song, "52 bars karan")
    assert library.rename(song, "52 Bars") is True
    assert library.get_title(song) == "52 Bars"
    assert library.get(song)["custom_title"] == "52 Bars"


def test_rename_survives_a_redownload_and_metadata_refresh(song):
    library.rename(song, "52 Bars")
    library.track_download(song, "/tmp/nope.webm", "52 bars karan", {"artist": ARTIST})
    assert library.get_title(song) == "52 Bars"
    library.update_meta(song, {"title": "52 bars karan", "album": "Somewhere"})
    assert library.get_title(song) == "52 Bars"
    assert library.get(song)["artist"] == ARTIST


def test_rename_reaches_every_listing(song):
    library.rename(song, "52 Bars")
    library.mark_liked(song, "52 bars karan")
    library.mark_speed_dial(song, "52 bars karan")
    library.bump_play(song, "52 bars karan", ARTIST, 180)
    assert library.get_liked_entries()[0]["title"] == "52 Bars"
    assert library.get_speed_dial_entries()[0]["title"] == "52 Bars"
    assert [row["title"] for row in library.play_rows()] == ["52 Bars"]


def test_rename_creates_a_row_for_an_unknown_track():
    assert library.rename("never-seen-before", "Fresh Name") is True
    assert library.get_title("never-seen-before") == "Fresh Name"


def test_rename_rejects_a_blank_name(song):
    library.mark_liked(song, SONG_TITLE)
    assert library.rename(song, "   ") is False
    assert library.rename("", SONG_TITLE) is False
    assert library.get_title(song) == SONG_TITLE


def test_web_rename_route_stores_the_name(song):
    from web import app as web_app

    web_app.app.config["TESTING"] = True
    library.mark_liked(song, "52 bars karan")
    with web_app.app.test_client() as client:
        ok = client.post(
            "/api/library/rename",
            json={"video_id": song, "title": "52 Bars"},
        )
        assert ok.status_code == 200
        assert ok.get_json()["title"] == "52 Bars"
        assert library.get_title(song) == "52 Bars"
        listed = client.get("/api/library").get_json()["songs"]
        assert [s["title"] for s in listed if s["video_id"] == song] == ["52 Bars"]

        assert client.post("/api/library/rename", json={"title": "x"}).status_code == 400
        assert (
            client.post(
                "/api/library/rename", json={"video_id": song, "title": "  "}
            ).status_code
            == 400
        )


def test_songs_with_tag_filters_downloaded_and_sorts_by_name(tmp_path):
    """Only this test's rows matter: the scratch `library.db` is shared."""
    mine = {}
    for idx, name in enumerate(("Zed Track", "Alpha Track", "Mid Track")):
        video_id = f"tagvid{idx}"
        path = tmp_path / f"{video_id}.opus"
        path.write_bytes(b"")
        mine[video_id] = name
        library.track_download(video_id, str(path), name)

    library.set_song_tag("tagvid0", "RoadTrip", True)
    library.set_song_tag("tagvid2", "roadtrip", True)
    library.set_song_tag("tagvid1", "gym", True)

    rows = [r for r in library.songs_with_tag("roadtrip") if r["video_id"] in mine]
    assert [r["title"] for r in rows] == ["Mid Track", "Zed Track"]
    assert library.songs_with_tag("") == []
    assert library.songs_with_tag("no-such-tag") == []


def test_songs_with_tag_ignores_undownloaded_songs(song):
    """A liked or searched track that was never downloaded cannot leak in."""
    library.update_meta(song, {"title": "Never Downloaded"})
    library.set_song_tag(song, "ghost-tag", True)
    assert library.songs_with_tag("ghost-tag") == []


def test_purge_auto_tags_wipes_language_and_artist_once(song):
    library.track_download(song, "/tmp/nope.opus", "Old Auto Track")
    library.update_meta(song, {"language": "hindi", "artist": "Auto Artist"})
    library.set_song_tag(song, "kept", True)
    with library._write() as conn:
        library._meta_set(conn, "auto_tags_purged", "0")
        library._purge_auto_tags(conn)
        assert library._meta_get(conn, "auto_tags_purged") == "1"

    entry = library.get(song)
    assert entry["language"] is None
    assert entry["artist"] is None
    assert library.song_tags(song) == ["kept"]


def test_meta_from_info_no_longer_writes_language_or_artist():
    meta = library.meta_from_info(
        {"language": "punjabi", "artist": "Karan Aujla", "album": "Album", "duration": "180"}
    )
    assert meta == {"album": "Album", "duration": 180}


# ---------------------------------------------------------------------------
# library.db — play counting (both modes)
# ---------------------------------------------------------------------------

def test_bump_play_counts_and_stamps_timestamps(song):
    before = time.time()
    assert library.bump_play(song, SONG_TITLE, ARTIST, 200) == 1
    assert library.bump_play(song) == 2
    entry = library.get(song)
    assert entry["song_count"] == 2
    assert entry["first_played"] >= before
    assert entry["last_played"] >= entry["first_played"]


def test_bump_play_fills_missing_metadata_only(song):
    library.bump_play(song, SONG_TITLE, ARTIST, 111)
    # A later play must not overwrite metadata we already know.
    library.bump_play(song, OTHER_TITLE, "Massive Attack", 222)
    entry = library.get(song)
    assert entry["title"] == SONG_TITLE
    assert entry["artist"] == ARTIST
    assert entry["duration"] == 111


def test_bump_play_ignores_empty_video_id():
    assert library.bump_play("", SONG_TITLE) == 0


def test_bump_play_coerces_a_bad_duration(song):
    """Callers pass whatever their player had; the column is an INTEGER."""
    assert library.bump_play(song, SONG_TITLE, duration=214.6) == 1
    assert library.get(song)["duration"] == 214
    library.bump_play(song + "b", SONG_TITLE, duration="not a number")
    assert library.get(song + "b")["duration"] is None


def test_play_count_survives_unlike(song):
    library.mark_liked(song, SONG_TITLE)
    library.bump_play(song)
    library.mark_unliked(song)
    # The row is kept so the count is not lost, even though nothing is liked.
    assert library.get_song_count(song) == 1
    assert library.is_liked(song) is False


def test_play_count_survives_download_delete(song):
    library.track_download(song, "/tmp/gone.webm", SONG_TITLE)
    library.bump_play(song)
    library.clear_download(song)
    assert library.get_song_count(song) == 1


def test_play_rows_exclude_unplayed_and_report_totals(song):
    library.mark_liked(f"unplayed-{song}", "Midnight City")
    for _ in range(3):
        library.bump_play(song, SONG_TITLE)
    rows = {r["video_id"]: r for r in library.play_rows()}
    assert f"unplayed-{song}" not in rows
    assert rows[song]["song_count"] == 3
    stats = library.stats()
    assert stats["total_plays"] >= 3
    assert stats["unique_songs"] == len(rows)


def test_clear_plays_zeroes_counts_but_keeps_the_row(song):
    library.mark_liked(song, "Kept Anthem")
    library.bump_play(song, "Kept Anthem", ARTIST, 180)
    assert library.get_song_count(song) == 1

    assert library.clear_plays() >= 1

    assert library.get_song_count(song) == 0
    assert song not in {r["video_id"] for r in library.play_rows()}
    entry = library.get(song)
    assert entry and entry["liked"] is True
    assert entry["title"] == "Kept Anthem"


def test_play_days_counts_a_play_and_clear_drops_the_bucket(song):
    before = dict(library.play_days(7))[0]
    library.bump_play(song, SONG_TITLE, ARTIST, 120)
    assert dict(library.play_days(7))[0] == before + 1

    library.clear_plays()

    assert all(count == 0 for _, count in library.play_days(7))


# ---------------------------------------------------------------------------
# history.db — online-only event log
# ---------------------------------------------------------------------------

def test_record_appends_one_event(song):
    history.record(song, SONG_TITLE, ARTIST)
    plays = history.timeline(limit=5)
    assert history.count() == 1
    assert plays[0]["title"] == SONG_TITLE
    assert plays[0]["artist"] == ARTIST
    assert plays[0]["play_count"] == 1


def test_record_drops_events_with_no_title(song):
    history.record(song, "")
    assert history.count() == 0


def test_online_play_logs_event_and_bumps_count(song):
    assert history.record_play(song, SONG_TITLE, ARTIST, mode="online") == 1
    assert history.count() == 1
    assert library.get_song_count(song) == 1


def test_offline_play_bumps_count_but_logs_no_event(song):
    assert history.record_play(song, SONG_TITLE, ARTIST, mode="offline") == 1
    # The whole point of the split: counted, but not on the timeline.
    assert history.count() == 0
    assert library.get_song_count(song) == 1


def test_offline_and_online_share_one_counter(song):
    history.record_play(song, SONG_TITLE, mode="online")
    history.record_play(song, SONG_TITLE, mode="offline")
    assert library.get_song_count(song) == 2


def test_timeline_orders_newest_first_by_default(song):
    history.record(song, "First", "A")
    time.sleep(0.01)
    history.record(song, "Second", "A")
    assert [p["title"] for p in history.timeline(sort="recent")] == ["Second", "First"]
    assert [p["title"] for p in history.timeline(sort="oldest")] == ["First", "Second"]


def test_timeline_unique_collapses_repeats_with_a_count(song):
    for _ in range(3):
        history.record(song, SONG_TITLE, ARTIST)
    history.record("other-" + song, "Midnight City", "M83")
    rows = {r["title"]: r for r in history.timeline(unique=True)}
    assert set(rows) == {SONG_TITLE, "Midnight City"}
    assert rows[SONG_TITLE]["play_count"] == 3
    assert rows["Midnight City"]["play_count"] == 1


def test_timeline_most_and_least_rank_by_play_count(song):
    for _ in range(4):
        history.record(song, SONG_TITLE, ARTIST)
    for _ in range(2):
        history.record("few-" + song, "Teardrop", "Massive Attack")

    most = history.timeline(sort="most")
    assert [p["title"] for p in most] == [SONG_TITLE, "Teardrop"]
    assert most[0]["play_count"] == 4

    least = history.timeline(sort="least")
    assert [p["title"] for p in least] == ["Teardrop", SONG_TITLE]
    assert least[0]["play_count"] == 2


def test_timeline_respects_limit_and_offset(song):
    for i in range(5):
        history.record(song, f"Play {i}", "A")
    assert len(history.timeline(limit=2)) == 2
    assert len(history.timeline(limit=2, offset=3)) == 2
    # Nonsense inputs are clamped, never raised.
    assert history.timeline(limit="nope") != []
    assert history.timeline(offset=-5) != []


def test_timeline_since_filters_by_time(song):
    history.record(song, SONG_TITLE, "A")
    assert history.timeline(since=time.time() - 3600)
    assert history.timeline(since=time.time() + 3600) == []


def test_top_ranks_by_play_count(song):
    for _ in range(2):
        history.record(song, SONG_TITLE, ARTIST)
    history.record("low-" + song, "Teardrop", "Massive Attack")
    assert history.top(limit=1)[0]["title"] == SONG_TITLE
    assert history.top(limit=1)[0]["play_count"] == 2


def test_clear_empties_the_log(song):
    history.record(song, SONG_TITLE)
    assert history.clear() == 1
    assert history.count() == 0
    assert history.timeline() == []


def test_totals_and_per_day_agree(song):
    history.record(song, SONG_TITLE, ARTIST)
    history.record(song + "b", "Teardrop", "Massive Attack")
    totals = history.totals()
    assert totals["online_plays"] == history.count() == 2
    assert totals["online_songs"] == 2
    assert totals["online_today"] == 2
    days = history.per_day(7)
    assert len(days) == 7
    assert days[-1][0] == 0
    assert sum(c for _, c in days) == totals["online_plays"]


# ---------------------------------------------------------------------------
# The one-time library.json -> library.db import
# ---------------------------------------------------------------------------

def test_legacy_json_is_imported_once_and_kept_as_bak():
    """The v0.8 -> v0.9 migration path.

    `library` resolves its paths at import time, so the legacy file is dropped
    at the real scratch `~/.flow/library.json` — the same place the real
    migration would find it — and the import is guarded by a `meta` flag.
    """
    legacy = library.LEGACY_FILE
    if legacy.exists():
        pytest.skip("library.json already migrated by an earlier test")
    legacy.write_text(
        json.dumps(
            {
                "legacyA": {
                    "liked": True,
                    "downloaded": True,
                    "title": "Around the World",
                    "artist": "Daft Punk",
                    "song": "/tmp/legacy.webm",
                    "song_count": 4,
                    # Metadata the v0.8 store kept but v0.9 drops.
                    "uploader": "Someone",
                    "view_count": 99,
                },
                "legacyB": {"liked": False, "title": "Midnight City"},
            }
        )
    )
    bak = legacy.with_name(legacy.name + ".bak")

    entry = library.get("legacyA")
    assert entry["liked"] is True
    assert entry["downloaded"] is True
    assert entry["title"] == "Around the World"
    assert entry["artist"] == "Daft Punk"
    assert entry["song_count"] == 4
    assert entry["duration"] is None
    assert not legacy.exists()
    assert bak.exists()

    # A second read must not re-import or resurrect the legacy file.
    library.clear_download("legacyA")
    assert bak.exists()
    assert library.get_song_count("legacyA") == 4
    assert library.get("legacyB")["liked"] is False
