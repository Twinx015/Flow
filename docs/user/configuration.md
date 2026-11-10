# Configuration

## You don't actually need this most of the time use `config` for an interactive one.

## The `config` command

Inside the `flow` shell, `config` changes settings. Run it bare for an
interactive wizard, `config -h` for the full list of targets and available
color names, or `config <target> <value>` for one-off changes.

| Target            | Description                                | Values                                               |
| ----------------- | ------------------------------------------ | ---------------------------------------------------- |
| `primary` (pri)   | Color for online songs                     | any color name                                       |
| `secondary` (sec) | Color for offline songs                    | any color name                                       |
| `tertiary` (ter)  | Color for labels                           | any color name                                       |
| `display`         | Playback display mode                      | `none`, `bars`, `lyrics`, `progress`, `rich`            |
| `progress_type`   | Rich progress layout (when `display rich`) | `default`, `download`, `pulse`, `custom`                |
| `rich_spinner`    | Rich spinner (when `display rich`)         | any name from `python -m rich.spinner`, or custom chars |
| `barwidth`        | Number of bars in the visualizer           | 4–80                                                 |
| `barheight`       | Height of bars                             | 10–90                                                |
| `barspacing`      | Space between bars                         | 0–4, or `min` / `fit` / `max`                        |
| `barchar`         | Visualizer bar character                   | `dot`, `block`, `circle`, or any single char         |
| `progchar`        | Filled part of progress/summary bars       | `dot`, `block`, `circle`, or any single char         |
| `progcharem`      | Empty part of progress/summary bars        | `dot`, `block`, `circle`, or any single char         |
| `sensitivity`     | Visualizer sensitivity                     | 0.5–5.0                                              |
| `format`          | Default download format                    | `opus`, `m4a`, `mp3`, `webm` (non-webm needs ffmpeg) |
| `ad_skip`         | Skip SponsorBlock segments during playback | `true` / `false`                                     |
| `down_on_like`    | Auto-download when liking an online track  | `true` / `false`                                     |
| `notify`          | Desktop notifications                      | `true` / `false`                                     |
| `max_search`      | Max YouTube search results                 | 1–20 (default 5)                                     |
| `max_radio`       | Max radio mix tracks                       | 1–50 (default 35)                                    |
| `search_source`   | Where online songs are searched            | `ytmusic` (default) or `youtube` — see below         |
| `api`             | URL flow pushes play state to              | empty (default) or an `http(s)` URL — see below      |

`search_source` picks the search backend and title handling together:

- `ytmusic` — songs are searched on music.youtube.com (`ytmusicapi`), whose
  titles are already clean (`52 Bars`, `Don't Worry (feat. Gurlez Akhtar)`),
  so they are kept as-is everywhere: search, playback, downloads, the
  library, and MPRIS metadata.
- `youtube` — songs are searched with yt-dlp's `ytsearch`, whose titles are
  noisy (`52 Bars (Official Video) Karan Aujla | Ikky`), so Tile cleanup and
  the six-word cap apply again at display and write time.

`sponsor_categories` (which SponsorBlock segment types are skipped) is set as
a list in the config file — `sponsor`, `selfpromo`, `intro`, `outro` by
default.

`api` points flow at a small HTTP endpoint of your own. While it is set,
after every recorded play flow POSTs two JSON documents to it (fire and
forget — a dead API never breaks playback):

```bash
flow config api http://127.0.0.1:8000   # empty disables
```

- **`POST /now`** — the current song as it starts: `title`, `artist`,
  `playlist` (the name when playing from a playlist, otherwise `""`),
  `mode` (`online`/`offline`), and `at` (unix time).
- **`POST /summary`** — everything `flow --summary` shows: play totals
  (combined/online/offline/unique/today/downloaded/liked), the top artist
  and song, the per-day 7-day split, this/last week counts, and
  the full per-song table.

Settings persist to `~/.flow/config.json`:

```json
{
  "primary": "cyan",
  "secondary": "purple",
  "tertiary": "blue",
  "display": "bars",
  "progress_columns": ["bar", "percentage", "time_remaining"],
  "progress_type": "default",
  "bar_width": 20,
  "bar_height": 40,
  "bar_spacing": 1,
  "bar_char": "█",
  "prog_char": "█",
  "prog_char_em": "░",
  "sensitivity": 1.0,
  "spinner": "|/-\\",
  "rich_spinner": "dots",
  "dev": false,
  "ffmpeg": true,
  "ad_skip": true,
  "sponsor_categories": ["sponsor", "selfpromo", "intro", "outro"],
  "down_on_like": true,
  "notify": true,
  "format": "webm",
  "max_search": 5,
  "max_radio": 35
}
```

## Where Flow stores things

Everything lives under `~/.flow/`.

| Path                                        | Purpose                                                            |
| ------------------------------------------- | ------------------------------------------------------------------ |
| `config.json`                               | Settings above                                                     |
| `library.db`                                | Per-song data + play counts, keyed by YouTube video id             |
| `history.db`                                | Play log for online streams (song name, artist, when)              |
| `status.json`                               | Current/last played track                                          |
| `search.json`                               | Rows of the last `flow-min search`, so `flow-min play <index>` can pick one |
| `downloads/`                                | Downloaded audio, named by video id (e.g. `TucWbkH5WX0.webm`)      |
| `downloads/.cache/`                         | Thumbnails (`<video_id>.jpg`)                                      |
| `downloads/liked songs/`                    | Copies of liked songs (offline liked list)                         |
| `music/`                                    | Album folders browsable as albums in the web UI                    |
| `playlists/`                                | One JSON file per playlist (schema v2)                             |
| `shortcuts.json`                            | User command shortcuts                                             |
| `ignore.txt`                                | Filler words stripped from titles (edit freely; `#` lines ignored) |
| `plugins/`                                  | Installed plugins and plugin repo caches                           |
| `players.json`                             | Live-player registry (`kind`, `pid`, `port` for the web player)    |
| `vlc.pid`, `tui.pid`, `web.pid`, `web_port` | Legacy pid/port mirrors of `players.json` (kept for compat)        |
| `seek.txt`                                  | Pending seek delta (milliseconds) for `--seek`/`--seekb`           |
| `web_command.json`                          | Pending control command for the web player                         |
| `web_ui.json`                               | Web UI settings (e.g. chosen download format)                      |
| `library.json.bak`                          | Pre-0.9 store, kept as a backup after the one-time import          |

### library.db

A SQLite database with one row per song, keyed by video id:

| Column                     | Meaning                                             |
| -------------------------- | --------------------------------------------------- |
| `liked`, `downloaded`, `speed_dial` | Flags                                    |
| `title`, `artist`, `album`, `duration` | Cleaned metadata                       |
| `song`                     | Local file path of a download (empty if not)          |
| `thumbnail`                | Cached thumbnail path                                |
| `song_count`               | How many times you've played it, online **and** offline |
| `first_played`, `last_played` | Unix timestamps of the first / most recent play    |

Titles are cleaned on save (see [Title cleanup](#title-cleanup); extra
metadata like uploader/channel/view counts is dropped intentionally).

A song's row is only removed once you have unliked it, deleted the download,
removed it from Speed Dial **and** never played it — so `song_count` survives
an unlike.

Alongside the songs, `library.db` keeps `play_days`: one bucket per calendar
day counting **both** modes. `bump_play` moves it in the same transaction as
`song_count`, and `flow summary` reads it to chart offline plays per day —
`history.db` only timestamps streams. Buckets start at the first play after
this shipped; there is no backfill.

### history.db

A SQLite database with one row per **online** play: the song name, the
artist, and when you played it. Local playback is not logged here; it only
moves `song_count` and today's `play_days` bucket in `library.db`. See
[`flow summary`](../user/command-line.md) and the web **History** panel.

### Title cleanup

Names shown for downloaded tracks come from `library.db` titles. Extra
words like "official", "lyrics", "video" are stripped using the word list in
`~/.flow/ignore.txt` — edit it to customize what gets removed.

## Backups

`flow export` copies every downloaded song to `~/Downloads` (or to the
directory given with `-p <path>`), named after the song and tagged with the
title, artist and album from `library.db` — see
[command-line.md](command-line.md#export). It needs `ffmpeg` to write those
tags; without it the songs are still copied, just untagged.

For config and database backups, copy `~/.flow` itself — `config.json`,
`library.db` and `history.db` (with their WAL sidecars, so close Flow first for
a consistent copy) hold everything Flow remembers. Use
`playlist export <name>` to get a single playlist as `.m3u`.
