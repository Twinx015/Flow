# Interfaces

## Daemon host (`backend/daemon.py` + `backend/rpc.py`)

The resident daemon is the always-on owner of the plugin socket
(`~/.flow/flow.sock`, mode 0600) and its pid file (`~/.flow/flowd.pid`). It
is an interface in its own right: plugins reach every other interface
through it rather than spawning the `flow` CLI.

- **Transport** — line-delimited JSON-RPC over AF_UNIX. Frames are
  `{"method", "params"}` → `{"result"}` or `{"error"}`; connections get
  their own thread so one slow plugin can't stall others; frames are capped
  at 1 MiB.
- **Handshake** — the first frame is `hello` with the plugin name (`FLOW_PLUGIN_NAME`); the daemon stamps it on the connection and uses it for capability gating (raw).
- **Typed surface** — `status` / `current_track` / `is_playing` read
  `status.json` file state; `library_stats` / `history` read the two SQLite
  stores through `backend.library` / `backend.history` (never as raw files);
  `pause`/`resume`/`next`/`previous`/`seek`/`seek_back`/`like`/`unlike`/
  `download` use `_send_player` (host routing mirroring `_send_control`);
  `players` lists the live player registry (kind/pid/port);
  `get_config`/`get_configs`/`set_config`/`set_theme`/`list_themes`/
  `set_spinner` are host-validated against `PLUGIN_SAFE_KEYS`; `raw_cli` is
  the gated flag passthrough behind the installed manifest's `raw`;
  `introspect` lists the method surface/version.
- **Lifecycle** — started/stopped via `flow daemon start|quit|status|socket`, and lazily by `flow run` (`_ensure_daemon`). Stale pid/socket are cleaned on start via `_alive()`.

See [plugins.md](plugins.md) for the protocol contract and
[control.md](control.md) for how player control is routed through it.

## Minimal CLI (`flow-min`, `minimal/`)

The non-interactive front end: the same backend with every affordance
removed — one plain line (or one `--json` document) per command, no colour,
no spinner, no prompt, exit codes `0`/`1`/`2` (ambiguous)/`130` (interrupted).
It never asks: ambiguous names print the candidates and exit `2`, and playback
detaches unless `--fg` is given.

All I/O lives in the package. `minimal/out.py` keeps a private dup of fd 1 and
wraps backend calls in `out.quiet()`, which dup2's fds 1/2 onto `/dev/null` so
the backend's banners, prompts and yt-dlp writes cannot reach stdout.
`minimal/main.py` is argparse wiring only; the behaviour sits in `core.py`,
`local.py`, `extras.py` and `stats.py`, which import `backend.*` directly —
nothing in `backend/` imports `minimal`.

Module map, output contract and test notes: [minimal.md](minimal.md).

## TUI (`tui/main.py`)

`Flow(App)` is a single Textual screen composed of two panels: the
playlist/search panel and the Now Playing panel, with a footer binding bar.

### Track model

Tracks are `Track` dataclasses (`title`, `ref`, `kind`,
`duration`, `video_id`), where `kind` is `"local"` or `"stream"`.

- Offline lists come from `offline_file.get_songs()` with display titles
  resolved through `library.db`, ascending by name. The web routes that list
  songs (`/offline`, `/api/liked`, `/api/album/<name>`,
  `/api/local-search`) sort on the displayed title via `_by_title` rather than
  the filename, which is the YouTube id.
- Online lists come from `stream_tracks(query)` → `youtube.search(query,
  limit=10)`. Search responses are tagged with a monotonic `_search_seq`;
  stale responses (a newer query landed first) are dropped.

### Playback

- A VLC instance is created with `--no-video --quiet`; if `python-vlc` is
  unavailable, playback gracefully falls back to *simulated mode* — the UI
  clocks run on a 1 s interval timer instead of VLC positions.
- `_vlc_play()` starts a media, waits briefly for a real playback state, and
  retries once with a fresh media before giving up; returns
  `"vlc"`/`"sim"`/`""`.
- Durations for local tracks are probed in a background thread using
  `vlc.Media.parse`/`parse_with_options`.
- `_on_tick` polls VLC every second: position/total drive the progress bar
  and MPRIS position. Reaching the end (or VLC's `Ended` state) calls
  `_track_finished()`: repeat replays the track, otherwise `_advance()` moves
  on. A finite repeat count decrements once per play; `Ctrl+R` sets it. VLC
  `Error` state triggers `_recover_playback` (fresh media retry, then
  simulated mode).

### Sharing state

The TUI participates in Flow's control plane fully:

- `config.save_pid_if_free(os.getpid())` + `config.save_tui_pid(...)` claim
  the player slots on mount; both are cleared on quit. Each registers the
  TUI in `~/.flow/players.json` (`backend/registry.py`) alongside the legacy
  pid files, so routing and status see the TUI as a live player.
- `_update_status()` writes `status.json` with a thumbnail resolved to the
  local cache path (offline) or the remote URL (online).
- All control signals are installed and dispatched onto the asyncio loop
  (`_install_signals`, `_signal_action`), so `flow --pause --next` etc. work
  against the TUI.
- MPRIS metadata is built from the library entry (`artist`, `album`,
  `artwork`) with `load_track`, plus a live position getter.

## Web app (`web/app.py`)

A single-file Flask app; the root and every unmatched path render
`templates/index.html` (SPA) with static assets served from the same
directory. In `DEV_MODE` it injects Flask/Werkzeug logging into the rotating
`LOGS/flow2.log` via `devlog.py`.

### Lookup pipeline

All YouTube fetches go through `backend.Online.youtube` (no own yt-dlp
calls), so `config.SearchSource` decides the search backend and title
cleanup here too.

- `_entry_to_dict()` normalizes an yt-dlp entry into `{title, video_id,
  stream_url, thumbnail, channel, duration, segments}`. Thumbnails are
  upgraded to `maxresdefault` when available.
- **Search cache** — `_cached_search()` wraps `youtube.search()` and keeps
  the last 50 queries in memory.
- **Play cache** — `_get_full_entry()` caches `youtube.get_entry()` results
  for 20 minutes, triggering a background SponsorBlock segment fetch
  (`_ensure_segments`).
- **Segment cache** — segments are cached 20 minutes; each video fetches
  once (a `_seg_inflight` set prevents duplicate concurrent fetches).

### Routes

| Route | Purpose |
| ----- | ------- |
| `GET /search?q=&limit=` | YouTube search (limit ≤ 25) |
| `GET /trend` | Trending search results |
| `GET /recommend?video_id=&limit=` | Radio mix from a video (limit ≤ 50) |
| `GET /play?video_id=&fresh=` | Playable entry (fresh=1 bypasses cache) |
| `GET /api/segments` | SponsorBlock segments for a video |
| `GET /api/lyrics` | Lyrics for a track (`video_id`/`title`/`artist`/`duration`, `fresh=1` refetches) |
| `GET /offline` | Scan `~/.flow/downloads/` for local songs, ascending by display name |
| `POST /download` | Download audio (`save_dir`, `format`) via `youtube.download_url`, registers in library + thumbnail + notify |
| `GET /api/is-downloaded`, `/api/downloaded-ids` | Library download state |
| `GET /api/library` | Full library listing (liked/downloaded/speed_dial flags) |
| `POST /api/library/rename` | Pin a display name (`video_id`, `title`) — 400 on either missing |
| `GET/POST /api/speed-dial` | Get/set home-screen favorites |
| `GET /api/home` | Last played + speed dials |
| `POST /api/delete-download` | Delete via library entry or file path (path-validated) |
| `GET /api/history?sort=&range=&unique=&limit=&offset=` | Online play timeline from `history.db` (sorts `recent`/`oldest`/`most`/`least`; `most`/`least` imply `unique`) |
| `GET /api/history/top?limit=` | Most-played online songs, ranked |
| `POST /api/history/play` | Count one play (browser player); online plays also append a `history.db` row |
| `POST /api/history/clear` | Empty `history.db` (leaves `song_count` alone) |
| `POST /api/now-playing` | Browser → `status.update()` |
| `POST /api/control` + `GET /api/control/poll` | Web control bridge (see control.md) |
| `GET/POST /api/playlists`, `/api/playlist`, `/api/playlist/*` | Playlist CRUD, reorder, dedupe, export `.m3u`, save |
| `GET /local/<path>` | Serve local media/thumbnails — resolves to a real path, rejects anything outside `$HOME` and non-media extensions |
| `GET /api/albums`, `/api/album/<name>` | Albums from `~/.flow/music/`; songs ascending by display name |
| `GET /api/local-search` | Substring search over downloads + music dirs, ascending by display name |
| `GET /api/liked`, `POST /api/like`, `GET /api/is-liked` | Liked UI (ascending by display name); like triggers a background auto-download thread when `down_on_like` |
| `GET /thumb/<video_id>` | Cached thumbnail |
| `GET/POST /api/settings` | Web settings persisted to `web_ui.json`, format via `config.set_format` |

Downloads go through `_download_audio()`, a thin wrapper over
`youtube.download_url()` (sponsor post-processors, optional
`FFmpegExtractAudio` for non-webm formats, then `library.track_download()` +
`download_thumbnail()` + notification in the backend).

### History panel

The sidebar's **History** panel is the web half of the play-history feature
and deliberately answers a different question from the CLI's
`flow summary -l`: it sorts the play *event* stream (online only), not a
per-song table. The panel is a lazy panel — `setPanel()` fires the loader in
`lazyPanels` rather than at boot — and its Sort / Range dropdowns are
excluded from the global `keydown` handler so arrow keys and space keep
working on them.

### Server process (`web/main.py`)

- Port selection scans 5000–5005 (`BUSY_PORTS`) for a free one
  (`_first_free_port`), or uses `--port PORT`.
- `flow-web` forks; the parent writes `web.pid`/`web_port` and prints the
  URL, the child serves `127.0.0.1` with the reloader off. `DEV_MODE` runs
  in the foreground for logs.
- `--stop [PORT]` kills the tracked/default port; `--stop-all` kills every
  Flow web server on 5000–5005 and clears the tracking files.

## Visualizer (`backend/visualizer.py`)

The `bars` display mode:

- Captures the system audio monitor through `sounddevice` (`AudioInputStream`
  with `numpy`), computes an FFT, and maps magnitude into `BarWidth`
  log-spaced bins. Bars render at `BarHeight` with `BarSpacing` gap;
  `sensitivity` scales the signal.
- ANSI colors are mapped to curses colors for the full-screen draw.
- It temporarily switches the default recording source to the monitor device
  and restores it on stop, so audio flows whichever way your mixer was set.
- Falls back to drawing `none`-style output when stdout isn't a TTY.

## Lyrics (`backend/lyrics.py`)

Lyrics come from **LRCLIB** first and **YouTube Music** second, and every
source is normalized to the same dict — `{lines: [{text, start, end}], plain,
synced, source}` — so callers never branch on where they came from.

- `fetch_lyrics(video_id, title, artist, album, duration)` →
  `clean_title()` strips the `Artist - Song (Official Video)` furniture off a
  YouTube title, then LRCLIB `/api/get` (needs `track_name` + `artist_name`)
  is asked for the record. A record without timings is kept aside and
  `/api/search` (needs only `track_name`) is asked for a synced twin; only
  then does YouTube Music run (`get_watch_playlist` → `get_lyrics(
  timestamps=True)`, with the original title-search fallback). A synced answer
  always beats an untimed one, and `None` means "nothing anywhere".
- `parse_lrc()` reads `[mm:ss.xx]` (also `[hh:mm:ss.xx]` and repeated stamps),
  drops metadata tags and enhanced-LRC `<word>` tags, and derives each line's
  `end` from the next line's `start`.
- `find_index()` / `find_line()` binary-search the sorted start times, so the
  terminal ticker (12 calls/s) and the web player (one per `timeupdate`) stay
  cheap on 300-line songs.
- Results are cached in-process: 1 hour for a hit, 10 minutes for a miss
  (a miss can become a hit on either source). `clear_cache()` forces a refetch.

### Lyrics in the web GUI

`lyricsBtn` in the player bar (and `l`) opens the lyrics modal; `GET
/api/lyrics?video_id=&title=&artist=&duration=&fresh=` serves it, preferring
`artist`/`album`/`duration` from the warm play cache over what the browser sent
and returning `{lyrics, found}`. The browser highlights lines off
`audio.currentTime` — never a wall clock — auto-scrolls the active line to
center, seeks when a line is clicked, and yields auto-scroll for 4 seconds
after a manual scroll. An unsynced record renders as static text tagged
`unsynced`; the badge names the source.

`lyricsQuery` is prefilled with the current title and editable: Enter or the
search button re-requests with the typed text, so a misspelt title can be
corrected for the lookup without renaming the track. Opening the modal for a
new track resets the box.

## SponsorBlock (`backend/sponsor.py`)

Toggles via `config.AD_SKIP` (`ad_skip`) and `sponsor_categories`
(default sponsor/selfpromo/intro/outro):

- `fetch_segments(video_id)` queries `https://sponsor.ajay.app` directly and
  degrades to `[]` on failure.
- `stream_url()`/`stream_info()` rewrite a watch URL into a downloadable
  audio URL and stitch segments in as `sponsorblock_chapters` so the
  in-page web player can seek past them.
- `download_postprocessors()` cuts sponsor segments out of downloads with
  ffmpeg (`remove_sponsor_segments`) when available and enabled.
- The background player runs a `SponsorBlockPoller` that watches the VLC
  position and seeks over segments as they arrive, remembering skipped ids.