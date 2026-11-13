# Interfaces

Flow ships two graphical interfaces alongside the CLI shell: the
full-screen **Textual TUI** and the **web GUI**.

## TUI (`flow-tui`)

Launch with:

```bash
flow-tui
```

The screen has two panels:

- **Left — track list.** In offline mode this is your local library (from
  `~/.flow/downloads/`, titles resolved from `~/.flow/library.db`). In
  online mode it starts empty; type a query in the search box and press Enter
  to search YouTube.
- **Right — Now Playing.** Current track title, a live progress bar,
  position/total time, the current mode, and a status line showing
  shuffle/repeat/volume. Previous/play/next buttons sit below it.

### Keys

| Key | Action |
| --- | ------ |
| `Enter` / click | Play the selected track (starts immediately) |
| `space` | Play / pause |
| `n` / `p` | Next / previous track |
| `s` / `r` | Toggle shuffle / repeat |
| `Ctrl+R` | Set a finite repeat count (empty or `0` = forever) |
| `S` | Focus the search box (both modes) |
| `d` | Download the highlighted or current track (online mode only) |
| `R` | Rename the highlighted or current track (offline mode only) |
| `+` / `-` | Volume up / down |
| `Tab` | Switch online/offline mode |
| `q` / `Ctrl+Q` | Quit |

Searching in online mode replaces the list with YouTube results; searching in
offline mode filters the local library.

### TUI and the rest of Flow

The TUI is fully wired into Flow's control system:

- It writes playback state to `~/.flow/status.json` and registers itself in
  `~/.flow/players.json` (plus the legacy `~/.flow/tui.pid` mirror), so
  `flow --status`, `flow --pause`, `flow --next`, and
  `flow --previous` work against a running TUI.
- It accepts the standard control flags itself (run `flow-tui --pause` while
  a TUI is running to toggle playback from another terminal):

| Flag | Description |
| ---- | ----------- |
| `--status` | Print the playback status card and exit |
| `--pause` | Toggle play/pause in a running Flow session (TUI or background VLC) |
| `--next` | Skip to the next track |
| `--previous` | Go back to the previous track |
| `--repeat [N]` | Toggle repeat in a running TUI, or start the TUI repeating (`N` times; empty or `0` = forever) |
| `--shuffle` | Toggle shuffle in a running TUI, or start the TUI with shuffle on |

## Web GUI (`flow-web`)

```bash
flow-web
```

starts the web server on the first free port starting at 5000, daemonizes,
and prints the URL (normally `http://127.0.0.1:5000`).

| Command | Action |
| ------- | ------ |
| `flow-web` | Start the web server (prompts to kill and restart if one is already running) |
| `flow-web --new` | Start another instance on the next free port |
| `flow-web --port 8080` | Start on a specific port |
| `flow-web --stop [PORT]` | Stop one web server (defaults to the running port) |
| `flow-web --stop-all` | Stop all web servers and VLC |

The web UI can:

- **Search YouTube** (results cached for up to 50 queries), browse trending
  tracks, and generate **radio/recommend** mixes from any track.
- **Play** directly in the browser. Playback is a player running on the same
  machine; the page reports back through `~/.flow/status.json`.
- **Manage the library and playlists** — browse downloaded tracks and albums
  (including `~/.flow/music/<album>/` folders), like/unlike, delete
  downloads, and create/add/remove/rename/duplicate/merge/reorder/export
  playlists. Every song list (Local Files, Liked, albums, local search) is
  ascending by name, matching the CLI, so a rename moves the song to its new
  alphabetical spot.
- **Browse your play history** in the **History** panel — an online-only
  timeline you can sort by newest, oldest, most played or least played,
  filter to today / 7 days / 30 days / all time, and tick **Unique songs**
  to collapse repeats into a ranked list. Click a row to play it again.
  Local playback is counted but not listed here; use
  [`flow summary`](command-line.md#summary) for per-song counts across both
  modes.
- **See synced lyrics** with the lyrics button in the player bar (or `l`) —
  the current line highlights as the track plays, clicking a line seeks to it,
  and the badge shows whether the lyrics are synced and which source they came
  from ([LRCLIB](https://lrclib.net), falling back to YouTube Music). The box
  above the lyrics is editable: correct a misspelt title there and press Enter
  (or the search button) to look the lyrics up again without renaming the song.
- **Rename a song** from the ⋮ menu on any row (pencil icon) — the new name
  follows you into the CLI, TUI and lyrics search, and survives re-downloads.
- **Download** tracks (also in opus/m4a/mp3/webm when ffmpeg is present).
- **Auto-skip SponsorBlock segments** while playing (toggleable via
  `ad_skip`).
- **Remember favorites** as speed-dials on the home screen, and set a default
  download format in Settings.

Control from the CLI works against the web player too: `flow --pause`,
`flow --next`, `flow --seek 30`, and `flow --status` reach a running web
player through `POST /api/control`.