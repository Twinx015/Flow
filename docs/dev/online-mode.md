# Online mode

Online mode streams audio from YouTube (via `yt-dlp` + `python-vlc`) and
JioSaavn. The command module is `backend/Online/commands.py`, selected when
`config.Mode == "Online"`.

## Commands

`backend/Online/commands.py` exports `COMMANDS` (a `{name: description}`
dict, shown by `help`) and `run(cmd, extra, args)`, which normalizes the
command (`-i` → detailed help, `merge_flags` for `-bg`/`-s`/`-r`/`-d`/`-f`)
and dispatches to handler functions.

| Command | Handler behavior |
| ------- | ---------------- |
| `play` | Search YouTube, pick the top result (or result index / `liked`), stream it |
| `random [n]` | Play `n` random songs from the downloaded library |
| `search` | Search YouTube, number the results for later `play <index>` |
| `savan` / `savan-s` | JioSaavn play / search (aliases `svn`, `svn-s`) |
| `radio` | Build a mix from a seed track (`-p` saves it as a playlist, `-d` downloads) |
| `like` / `unlike` | Toggle the flag in `~/.flow/library.db`; liking downloads the thumbnail and, when `down_on_like` is on, auto-downloads the audio |
| `download` | Download audio to `~/.flow/downloads/` (skip if already downloaded) |
| `delete` | Remove a downloaded song (alias `dl-d`) |
| `playlist` / `switch` / `help` / `short` / `config` / `check` / `export` / `exit` | Shared command surface |

## Fetching

`backend/Online/youtube.py` wraps `yt_dlp` and `ytmusicapi` and dispatches on
`config.SearchSource` (`"ytmusic"` by default, `youtube` for the old path):

- `search(query, limit)` — YouTube Music (`ytmusicapi`, `filter="songs"`)
  or `ytsearchN` flat search; both reshape results into flat yt-dlp entries
  and return `(info, title, duration)` tuples, trimmed to `limit`. Titles are
  only Tile-truncated (`config._truncate_title`) in `youtube` mode; Music
  titles are already clean and are kept as-is everywhere (search, playback,
  downloads, the library, MPRIS/DBus metadata).
- `get_entry(url)` — full entry for a watch URL, run through
  `sponsor.stream_info()` so SponsorBlock segments are attached. Music ids
  are resolved through yt-dlp like any other video, so playback and downloads
  are unchanged.
- `download_url(url, outdir, fmt)` — downloads and post-processes the audio;
  non-`webm` formats go through ffmpeg (`FFmpegExtractAudio`).
- `fetch_radio(query, max_results)` — `RDMM<id>` auto-mix playlist extraction
  (still seeded through a yt-dlp `ytsearch1` lookup).

Shared `yt_dlp` options pin the player client (`youtube: android`) and set
sane timeouts/retries (`socket_timeout`, `retries`, `extractor_retries`).

## Playback

`backend/Online/player.py` owns the VLC instance:

- `play_entry(entry, title, ...)` resolves a playable stream URL —
  `sponsor.stream_url()` rewrites `webpage_url` to the direct audio format
  when available — creates the player, saves its pid to
  `~/.flow/vlc.pid`, updates `status.json`, publishes MPRIS metadata, then
  runs `_display_loop`.
- `play_url(...)` is the stream-URL variant (used by radio/savan).
- Both record the play once metadata is resolved, via
  `history.record_play(video_id, title, artist, mode="online")` — see
  [Play counting](storage.md#play-counting). JioSaavn has no video id, so
  `play_url` namespaces its song id as `j:<song_id>`.
- `setup_nav_signals()` installs the signal handlers; `_attach_vlc_events()`
  forwards VLC state changes (playing/paused/stopped) to MPRIS.
- A `SponsorBlockPoller` runs during playback and seeks past sponsor
  segments as they approach, remembering already-skipped segment ids.
- Playback is synchronous — `play_entry`/`play_url` block for the track
  (VLC + `_display_loop`), with an input reader thread for interactive keys.
  With `-bg`, `_fork_bg()` forks: the parent records the child's pid in
  `~/.flow/vlc.pid` and returns to the shell immediately; the child
  redirects stdin/stdout/stderr to `/dev/null` and plays in the background.

### Signal handlers

Installed by `setup_nav_signals()`:

| Signal | Action |
| ------ | ------ |
| `SIGUSR1` | Toggle play/pause |
| `SIGUSR2` | Next track |
| `SIGRTMIN+2` | Previous track |
| `SIGRTMIN+3` / `+4` | Seek forward/backward (delta read from `seek.txt`, milliseconds) |
| `SIGRTMIN+7` | Stop (clean up pid file, status, display) |

See [Playback control](control.md) for the full picture.

## Display loop

`_display_loop` picks a renderer from `config.Display`:

- `bars` — `backend/visualizer.py` reads the system audio monitor through
  `sounddevice` and renders a spectrum with `numpy`, colored per the current
  mode. It temporarily switches the default audio source to the monitor and
  restores it on exit.
- `lyrics` — `backend/lyrics.py` fetches timed lyrics (LRCLIB, then
  YouTube Music) and prints the current line; untimed lyrics print once as a
  static block.
- `progress` — a live `\r` block bar (elapsed/total, percent) via
  `config.render_progress`, drawn from `config.progress_bar`.
- `none` — minimal progress output.

## Downloads

Downloaded files land in `~/.flow/downloads/<video_id>.<ext>` (default
`webm`; `opus`/`m4a`/`mp3` when ffmpeg is present and
`config.FORMAT`/`-f <fmt>` says so). Every download is recorded in
`library.db` via `library.track_download()`, which also stores
artist/album/duration metadata extracted from the yt-dlp info dict
(`library.meta_from_info`). Thumbnails are cached to
`~/.flow/downloads/.cache/<video_id>.jpg` on like/download so the TUI, web
UI, and status cards can show art offline.

Success/failure can raise a desktop notification via `notify-send`
(`config.down_notify`).

## Radio

`radio <song> [index]` works like `play` but then seeds an auto-generated
mix and plays through it, respecting `-r` (repeat) and `-s` (shuffle). With
`-p`, the mix is saved as a playlist; with `-d`, tracks are downloaded while
playing.