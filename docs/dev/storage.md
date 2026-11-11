# Storage

All persistent state lives in `~/.flow/`. Most files are plain JSON written
atomically (write to a `.tmp` sibling, `os.replace` onto the target) so a
crash mid-write can never truncate them. The two databases
(`library.db`, `history.db`) are SQLite and use WAL journaling instead.

```
~/.flow/
├── config.json            # settings (backend/config.py)
├── library.db             # per-song data + play counts (backend/library.py)
├── history.db             # online play log (backend/history.py)
├── library.json.bak       # pre-v0.9 store, kept after the one-time import
├── status.json            # current/last track (backend/status.py)
├── search.json            # rows of the last `flow-min search` (minimal/core.py)
├── meta.json              # unfinished `flow --meta` pass (backend/metadata.py)
├── shortcuts.json         # command aliases (backend/shortcuts.py)
├── ignore.txt             # filler words stripped from titles
├── seek.txt               # pending seek delta in milliseconds
├── players.json           # live-player registry (backend/registry.py)
├── vlc.pid                # legacy mirror: pid of the background VLC player
├── tui.pid                # legacy mirror: pid of a running TUI
├── web.pid                # legacy mirror: pid of the web server
├── web_port               # legacy mirror: port of the web server
├── web_command.json       # pending control command for the web player
├── web_ui.json            # web UI settings (download format)
├── downloads/             # downloaded audio (named by video id)
│   ├── .cache/            #   thumbnails  <video_id>.jpg
│   └── liked songs/       #   copies of liked songs
├── music/                 # album folders browsable as albums
├── playlists/             # one JSON file per playlist (schema v2)
│   └── .lock              # flock guard for playlist ops
├── playlists.json         # legacy single-file store (migrated once → .bak)
├── plugins/               # installed plugins + repo caches
│   ├── <name>/            #   plugin.json, flow_api.py, entry source
│   ├── _repo/             #   clone of the default plugin repo
│   └── _src/              #   clones of other repos
└── LOGS/                  # flow2.log rotating log (dev mode only)
```

WAL mode means each database also has a `-wal` and `-shm` sidecar next to it
while a process holds it open. They are recreated automatically; deleting them
while no process is running is safe.

## config.json

Loaded at import by `config._load_config()` and saved on every change; keys
are validated against ranges. See the [user configuration
guide](../user/configuration.md) for the full key list. `format` may be
`opus|m4a|mp3|webm` (non-webm requires ffmpeg, which is auto-detected at
startup unless explicitly configured).

## library.db

SQLite (`backend/library.py`), one row per song keyed by video id:

```sql
CREATE TABLE songs (
    video_id     TEXT PRIMARY KEY,
    liked        INTEGER NOT NULL DEFAULT 0,
    downloaded   INTEGER NOT NULL DEFAULT 0,
    speed_dial   INTEGER NOT NULL DEFAULT 0,
    title        TEXT    NOT NULL DEFAULT '',
    custom_title TEXT,
    artist       TEXT,
    album        TEXT,
    language     TEXT,
    duration     INTEGER,
    song         TEXT,
    thumbnail    TEXT    NOT NULL DEFAULT '',
    song_count   INTEGER NOT NULL DEFAULT 0,
    first_played REAL,
    last_played  REAL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE play_days (day TEXT PRIMARY KEY, plays INTEGER NOT NULL DEFAULT 0);
```

`meta` holds migration flags only. `song` is the download path (`NULL`
unless downloaded) and `speed_dial` marks web-UI favorites. `play_days` is
one bucket per calendar day, bumped alongside `song_count` by
`library.bump_play()`: `history.db` only timestamps streams, so this table
is what lets `flow summary` chart *offline* plays per day. There is no
backfill — buckets only exist from the first play after this shipped.

**The API is still dict-shaped.** `library.load()` returns
`{video_id: {...}}` and every write goes through `library._mutate(fn)`, so
the four external callers (`web/app.py`, `tui/main.py`, `Offline/file.py`,
the mode command modules) needed no changes when this moved off JSON.

Notes:

- Every write goes through `_mutate(fn)`, which opens `BEGIN IMMEDIATE`,
  loads, applies `fn`, and diffs the result — only rows that actually changed
  are written. A mutator that returns `False` rolls back, so "no change
  needed" never touches the database. This is what replaced the `flock` on
  `~/.flow/library.lock`.
- Connections are per-call (the Flask server and the daemon are both
  threaded, so a shared connection is not safe), opened with
  `journal_mode=WAL`, `synchronous=NORMAL` and a 10 s `busy_timeout`. WAL
  lets readers run while a writer holds the write lock, which is what makes
  the TUI, web server and CLI safe against each other.
- Titles are cleaned on write (`config._truncate_title`: drops filler words
  from `ignore.txt`, caps at six words). Only artist/album/duration are kept
  as metadata.
- `custom_title` holds a user rename (`library.rename(video_id, title)`), and
  `_row_to_entry` resolves `title = custom_title or title`, so every read path
  (CLI, TUI, web, lyrics search) shows it without knowing the column exists.
  Fresh downloads and metadata rebuilds only write `title`, so a rename is
  never overwritten. The column is added by `_ensure_schema` on first open.
- `language` and `artist` are kept for schema compatibility but are **not**
  tags any more: nothing writes them at download time (`library.meta_from_info`
  only keeps album and duration) and `_purge_auto_tags` clears any values left
  by an older version once, guarded by the `auto_tags_purged` meta key.
- `song_tags` is a table of **user-owned** tags: one `(video_id, tag)` row per
  tag. `library.set_song_tag` adds or removes one, `rename_tag` / `delete_tag`
  act on a whole tag across songs, `clear_song_tags` empties a song, and
  `downloaded_rows` joins them for the editor's pickers. `library.clear_download`
  drops them with the download.
- `library.songs_with_tag(tag)` is the read side for playback and export:
  downloaded rows only, exact case-insensitive tag match, ascending by display
  name. `Offline.tags_play` / `tags_random` / `tags_export` use it, as do the
  interactive tag menu and `flow-min tags play|random|export`.
- **A row is only deleted when nothing is left to remember** — not liked, not
  downloaded, not on speed dial, no `song` path, *and* `song_count == 0` —
  so a play count survives an unlike or a delete.

### Play counting

`library.bump_play(video_id, title, artist, duration)` increments
`song_count`, stamps `first_played` / `last_played` and upserts today's
`play_days` bucket, filling in title/artist/duration only when they are not
already known. It is called for **every** play in both modes, from four
entry points:

| Entry point | File |
| --- | --- |
| `play_entry` (YouTube) | `backend/Online/player.py` |
| `play_url` (JioSaavn) | `backend/Online/player.py` |
| `play_file` | `backend/Offline/player.py` |
| `_play` | `tui/main.py` |

Offline playback identifies a track by its filename stem, which *is* its
video id, so a downloaded song shares one counter with its online plays.
JioSaavn tracks have no video id, so `play_url` namespaces the JioSaavn song
id as `j:<song_id>` to keep it from colliding with a real video id.

The web player counts through `POST /api/history/play` (see
[history.db](#historydb)) rather than `/api/now-playing`, because the player
bar posts to the latter on play, pause *and* `loadedmetadata`.

`library.clear_plays()` is the other writer: it zeroes `song_count` and the
two play stamps for every row and drops the `play_days` buckets, keeping
likes, downloads, tags and renames. It backs `summary -c`, which empties
`history.db` in the same pass so the CLI's online/offline split stays
honest.

## history.db

SQLite (`backend/history.py`) — the online-only play log:

```sql
CREATE TABLE plays (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id  TEXT NOT NULL DEFAULT '',
    title     TEXT NOT NULL,
    artist    TEXT,
    played_at REAL NOT NULL
);
```

One row per play event, holding only the song name, the artist and the
timestamp. **Local playback is deliberately not logged here** — it is counted
by `song_count` and today's `play_days` bucket in `library.db` but never
produces a timeline row, so the history stays a record of what you streamed.

The two databases answer different questions on purpose:

| | `library.db` | `history.db` |
| --- | --- | --- |
| Question | how many times have I played this song | what did I stream, and when |
| Scope | every mode | online only |
| Shape | one row per song | one row per play event |
| Surfaced by | `flow summary` (CLI) | `history` (web panel) |

`video_id` is stored even though the UI never shows it: the web History panel
needs it to re-play a row, and the `most` / `least` sorts group by it.

## Migration from library.json

`library._migrate_from_json()` runs once, guarded by the `meta` flag
`json_migrated`. If a pre-v0.9 `~/.flow/library.json` exists it is imported
into `songs` and then renamed to `library.json.bak` (the same convention as
the `playlists.json` migration). Keys the new schema dropped
(`track`, `uploader`, `channel`, `upload_date`, `release_date`, `view_count`,
`like_count`, `url`) are discarded.

> **TODO(remove after v0.9):** delete `_migrate_from_json`, `_legacy_to_row`,
> `LEGACY_FILE` and `_REMOVED_META_KEYS` once v0.9 ships — no pre-v0.9 install
> will be left to upgrade from.

## status.json

The single "what's playing" source, written by every player (CLI VLC, TUI,
web frontend via `/api/now-playing`):

```json
{ "title": "...", "duration": 214, "playing": true, "thumbnail": "<url or path>", "ts": 1740000000.0 }
```

`ts` is a Unix timestamp; state is only considered current while
`time.time() - ts <= max(120, duration + 30)` (`status._fresh`). The
thumbnail encodes the mode: an `http(s)` URL means the track came from
online, a local path (`.cache/` or under `~/.flow`) means offline — used by
`--resume` and `--like/--unlike/--download`.

## Playlists

`backend/playlist.py` stores one JSON file per playlist in `playlists/`:

```json
{
  "version": 2,
  "name": "roadtrip",
  "description": "",
  "created": 1740000000,
  "modified": 1740000000,
  "tracks": [
    {
      "id": "AbCdEf12345",
      "title": "Song",
      "source": "youtube",
      "ref": "https://www.youtube.com/watch?v=...",
      "local_path": null,
      "duration": 214,
      "added": 1740000000,
      "thumb": "/home/you/.flow/downloads/.cache/AbCdEf12345.jpg"
    }
  ]
}
```

- Filenames are slugified display names (`_slugify`), disambiguated with
  numeric suffixes as needed.
- Name lookups are case-insensitive; `resolve_name()` falls back to
  prefix/substring matching when the query isn't exact.
- All mutations run under an exclusive `flock` on `playlists/.lock` and
  bump `modified`. `add_track` de-duplicates by track `id`. `reorder`
  requires the new id list to be an exact permutation.
- A legacy single-file store (`~/.flow/playlists.json`, pre-v2) is migrated
  on first use — entries are split into per-file stores and the legacy file
  is renamed to `playlists.json.bak`.
- `liked` is a reserved name; `playlist download` saves every track into
  the default `downloads/` folder alongside the rest of the library, and
  backfills `local_path` on the track so `resolve_track` finds it.

## Shortcuts

`shortcuts.json` is `{alias: command}` and merges over the built-in defaults
in `backend/shortcuts.py` (pl→play, sh→search, rd→radio, svn→savan, ...).
Loaded by `shortcuts.load()` in `cli.main`; aliases starting with `-` in
shell mode and bare aliases in the prompt are resolved through
`shortcuts.resolve()`.

## Ephemeral control files

- `players.json` — the live-player registry (see [Playback
  control](control.md)). Keyed by kind (`vlc`, `tui`, `web`), each record has
  `pid` + `ts` (and `port` for `web`). Written atomically
  (`backend/registry.py`). Routing reads it first.
- `vlc.pid` / `tui.pid` / `web.pid` + `web_port` — **legacy mirrors** of the
  same state, still written so pre-registry readers keep working.
  `vlc.pid` is the "player slot" (`save_pid_if_free` refuses to overwrite a
  live player's pid); cleared on exit.
- `seek.txt` — `--seek N` writes `N*1000`, `--seekb N` writes `-N*1000`
  (milliseconds); the receiver reads and clears it.
- `web_command.json` — see [Playback control](control.md).