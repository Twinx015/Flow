# Flow

A terminal-based music player with online streaming and offline library modes.

## Features

- **Dual-mode operation** — It will automatically detect internet and switch between online streaming and offline playback.
- **Online mode** — Search and stream audio from YouTube via `yt-dlp` and `python-vlc`
- **Offline mode** — Play local audio files with album support, search, and a liked-songs collection
- **Download** — Save tracks from YouTube to your local library with the `-d` flag
- **Repeat & shuffle** — Loop tracks n times or play in random order
- **Like/unlike** — Toggle favorites on/off, stored in `~/.flow/library.json`
- **Playlist play** — Create playlists and play them with `playlist play <name>`
- **Tab completion** — Auto-complete commands and song names in offline mode
- **Colored TUI** — Cyan theme for online, magenta for offline, with borders and banners
- **Background play** — Play music in background and return to your shell
- **Audio-reactive bars** — Real-time spectrum analyzer with configurable width, height, and spacing
- **Synced lyrics** — Display color-coded lyrics that scroll with the song
- **Gui for GUI lovers** - Get a gui in web using flask for you to enjoy

## Requirements

- Python 3
- [VLC](https://www.videolan.org/vlc/) media player (for `python-vlc` bindings)

## Installation

```bash
git clone https://github.com/Philast-015/Flow.git
cd flow
uv run flow_twinx/main.py
```

Or through pip:

```bash
pip install flow-twinx
flow
```

### Note: Make sure vlc is installed it can break on some PC but mostly work without vlc.

## Usage

```bash
flow
```

OR if you cloned the repo:

```bash
cd flow_twinx
uv run main.py
```

### Flags

| Flag    | Description                                                           |
| ------- | --------------------------------------------------------------------- |
| `-bg`   | Play in background and exit to shell                                  |
| `-kill` | Kill all background VLC processes                                     |
| `-i`    | Use it in help command to show detailed help                          |
| `-s`    | Use it shuffle or play random songs                                   |
| `-r`    | Use it to repeat songs no of time [ -r n ] [ -r ] ( n = no of times ) |
| `-d`    | Use it to download songs                                              |

### Shell Mode

Run commands directly from your shell without entering interactive mode.
Play-like commands (`-pl`, `-rd`) automatically run in background.

```bash
flow -pl never gonna give you up    # play (auto-bg)
flow -rd daft punk                  # radio (auto-bg)
flow -sh daft punk                  # search (show results, exit)
flow -kill                          # kill VLC
```

Also works with positional commands:

```bash
flow play never gonna give you up
flow radio daft punk
flow search daft punk
```

Shell shortcuts use your user-defined shortcuts with `-` prefix:

```bash
flow -svn hello                     # svn → savan
flow -dl never gonna give you up    # dl → download
```

### Gui Mode:

To launch gui mode just type :

```bash
flow --web
```

### Commands

| Command                | Description                                       |
| ---------------------- | ------------------------------------------------- |
| `play <name or #>`     | Play a song by name or search result number       |
| `search <query>`       | Search YouTube (online) or library (offline)      |
| `list`                 | Show all songs, albums, or liked tracks           |
| `like`                 | Like/unlike the currently playing song            |
| `download <name or #>` | Save a streamed song to the local library         |
| `delete <name or #>`   | Delete a downloaded song (alias: `dl-d`)         |
| `radio <name> [#]`     | Radio mix (online) or shuffle-loop library (offline) |
| `playlist <sub>`       | Manage playlists (create/add/remove/play)        |
| `export`               | Backup ~/.flow config to ~/Downloads              |
| `switch`               | Toggle between online and offline mode            |
| `help`                 | Show available commands                           |
| `help -i`              | Show available commands with detailed explanation |

### Config Options

| Target       | Description                  | Range              |
| ------------ | ---------------------------- | ------------------ |
| `primary`    | Color for online songs       | Any color          |
| `secondary`  | Color for offline songs      | Any color          |
| `tertiary`   | Color for labels             | Any color          |
| `display`    | Playback display mode        | none, bars, lyrics |
| `barwidth`   | Number of bars in visualizer | 4-80               |
| `barheight`  | Height of bars               | 2-16               |
| `barspacing` | Space between bars           | 0-4                |

Usage: `config <target> <value>`

## Configuration

- Downloads are stored in `~/.flow/downloads/` (named by video id, e.g. `TucWbkH5WX0.opus`)
- All per-song data (liked/downloaded/title/paths) lives in the single file `~/.flow/library.json`, keyed by video id
- Thumbnails are downloaded on like/download to `~/.flow/downloads/.cache/<video_id>.jpg`
- User shortcuts are stored in `~/.flow/shortcuts.json`
- Config file: `~/.flow/config.json`

## License

Use however you want just mention me for inspiration.
