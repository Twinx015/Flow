<div align="center">

  <pre>
███████╗██╗      ██████╗ ██╗    ██╗
██╔════╝██║     ██╔═══██╗██║    ██║
█████╗  ██║     ██║   ██║██║ █╗ ██║
██╔══╝  ██║     ██║   ██║██║███╗██║
██║     ███████╗╚██████╔╝╚███╔███╔╝
╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝
  </pre>

  <h1>Flow</h1>

  <p><b>A modern terminal music player with online streaming, an offline library, a TUI and a web GUI.</b></p>

<p>
    <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square&labelColor=black"></a>
    <img alt="Python 3.14+" src="https://img.shields.io/badge/python-3.14%2B-blue?style=flat-square&labelColor=black&logo=python&logoColor=white">
    <img alt="Platform: Linux, macOS, Windows" src="https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-blue?style=flat-square&labelColor=black">
    <a href="https://github.com/flow-twinx/flow">
        <img alt="Stars" src="https://img.shields.io/github/stars/flow-twinx/flow?style=flat-square&labelColor=black&color=blue"/></a>
    <a href="https://pypi.org/project/flow-twinx/">
        <img alt="PyPI" src="https://img.shields.io/pypi/v/flow-twinx?style=flat-square&labelColor=black&color=blue&logo=pypi&logoColor=white"/></a>
    <a href="https://pepy.tech/project/flow-twinx">
        <img alt="Downloads" src="https://static.pepy.tech/personalized-badge/flow-twinx?period=total&units=international_system&left_color=black&right_color=blue&left_text=Downloads"></a>
</p>

  <p>
    <a href="#installation">Installation</a> ·
    <a href="#quick-start">Quick start</a> ·
    <a href="#documentation">Documentation</a> ·
    <a href="#plugins">Plugins</a> ·
    <a href="#contributing">Contributing</a>
  </p>
</div>

---

## Overview

Flow is a terminal music player with two modes. **Online mode** streams from
YouTube (through `yt-dlp` and VLC) and JioSaavn. **Offline mode** plays the
songs you have already downloaded. Flow checks your connection on startup and
picks the right mode for you; `switch` flips it whenever you like.

Everything Flow stores (downloads, likes, playlists, history, settings) lives
in a single folder, `~/.flow/`, and is shared by every interface. Like a song
in the TUI and it is liked in the web GUI and the shell too.

▶ **[Watch the demo](demo.mp4)**

## Features

**Playback**

- Automatic online/offline detection with a manual `switch`
- YouTube search and streaming, radio mixes and JioSaavn (`savan`)
- Offline library with search, tab completion and liked songs
- Repeat (`-r [n]`), shuffle (`-s`) and background play (`-bg`)
- Audio-reactive spectrum visualizer, or synced lyrics, while a track plays

**Library**

- Downloads from YouTube (`-d`) as webm, opus, m4a or mp3
- Playlists: create, edit, merge, dedupe, reorder, and export or import `.m3u`
- Like and unlike, with optional auto-download on like
- Play counts in both modes, `flow summary` in the CLI and a History panel in the web GUI
- Rename a misspelt title once and every surface, lyrics search included, uses the new name
- User tags: play a whole tag, one random song, or export just that tag's songs

**Lyrics**

- Synced lines from [LRCLIB](https://lrclib.net), with YouTube Music as a fallback
- Printed in the terminal in `lyrics` display mode, or scrolled with the track in the web GUI

**Interfaces**

- An interactive CLI shell, a full-screen TUI and a local web GUI
- `flow-min`, a plain non-interactive CLI for scripts, ssh and agents (see below)

**Extensible**

- Community plugins that run as isolated processes and talk to Flow through a typed, host-validated API

## Interfaces

| Command    | What it is                                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `flow`     | Interactive shell with commands, tab completion and one-shot playback flags                                                     |
| `flow-tui` | Full-screen [Textual](https://textual.textualize.io) UI with a track list and Now Playing panel                                 |
| `flow-web` | Local web GUI served on `127.0.0.1`, on the first free port from 5000 to 5005                                                   |
| `flow-min` | Plain output, no colour, spinner or prompt: one line or one `--json` document per command, documented exit codes, safe in pipes |

All four share the same library and settings, and playback control works
across them: `flow-min next` skips a track started from the shell, the TUI or
the web GUI. See [Interfaces](docs/user/interface.md) for how to use the TUI
and web GUI.

## Requirements

- **Linux or macOS.** Flow uses Unix-only APIs, so on Windows run it under WSL.
- **Python 3.14+**
- **[VLC](https://www.videolan.org/vlc/)**, used through `python-vlc` for all audio playback
- **ffmpeg** (optional), only needed to download in a format other than webm
- **git** (optional), only needed to install plugins

## Installation

From PyPI:

```bash
pip install flow-twinx
flow
```

From source, with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/flow-twinx/flow.git
cd flow
uv sync            # or: pip install .
uv run flow
```

Check that your environment is ready:

```bash
flow --check
```

This prints a pass/fail table for ffmpeg, VLC, yt-dlp and the other core
dependencies. There is no setup step: Flow creates `~/.flow/` on demand. More
detail is in [Installation](docs/user/installation.md).

## Quick start

```bash
flow -pl "never gonna give you up"        # stream from YouTube (foreground)
flow -pl "never gonna give you up" -bg    # ...in the background
flow -sh "daft punk"                      # search and show results
flow --play-off "my song"                 # play from the local library
flow --radio-off                          # shuffle-loop the whole library
flow                                      # interactive shell (type `help`)
flow-tui                                  # full-screen TUI
flow-web                                  # web GUI at http://127.0.0.1:5000
flow-min status --json                    # one JSON document, script-friendly
```

`-pl` and `-sh` are built-in shortcuts for `play` and `search`. You can add
your own with the `short` command (see [Command line](docs/user/command-line.md)).

Playback control works across interfaces, from any terminal:

```bash
flow --status      # show the current track
flow --pause       # play/pause the running player
flow --next        # skip
flow --seek 30     # seek 30 seconds forward
```

Inside the shell, `help` lists every command and `help -i` explains them in
detail. The full reference is in [Command line](docs/user/command-line.md).

## Plugins

Plugins are small programs installed from git repositories. They run in their
own processes and use only the `flow_api` module, which Flow provides, to read
the current track, control playback and change a safe set of settings.

```bash
flow plugins list              # browse available plugins
flow install <name>            # install by name
flow install owner/repo        # install from GitHub
flow run <name>                # run in the background (-t for foreground)
flow plugin kill <name>        # stop a running plugin
```

Read the [user guide](docs/user/plugins.md) to use plugins, or the
[developer guide](docs/dev/plugins.md) to write one.

## Documentation

- **[User guide](docs/user/index.md)**: commands and flags, TUI and web usage, configuration and storage, plugins
- **[Developer guide](docs/dev/index.md)**: architecture, online and offline internals, storage schemas, the control protocol, interfaces

## Development

```bash
uv sync                    # install dependencies
uv run flow --check        # verify the environment
uv run pytest              # run the test suite
```

The tests run against a scratch `HOME`, so they never touch your real
`~/.flow/`. The backend in `backend/` owns all logic; the `cli/`, `tui/`,
`web/` and `minimal/` packages are thin front ends over it. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Contributing

Bug reports, feature ideas and pull requests are welcome. Please read the
[contributing guide](CONTRIBUTING.md) and the
[code of conduct](CODE_OF_CONDUCT.md) first. To report a security issue, follow
[SECURITY.md](SECURITY.md) rather than opening a public issue.

## Disclaimer

Flow is a personal-use tool. It is not affiliated with or endorsed by YouTube,
JioSaavn, VLC or any other service it connects to. You are responsible for
following the terms of service of those services and the copyright laws that
apply to you when you stream or download content.

## Acknowledgements

Flow is built on the work of many open-source projects, including
[yt-dlp](https://github.com/yt-dlp/yt-dlp), [VLC](https://www.videolan.org/vlc/)
and [python-vlc](https://github.com/oaubert/python-vlc),
[Textual](https://github.com/Textualize/textual),
[Flask](https://flask.palletsprojects.com),
[ytmusicapi](https://github.com/sigma67/ytmusicapi) and
[questionary](https://github.com/tmbo/questionary). Synced lyrics come from
[LRCLIB](https://lrclib.net).

## License

Flow is released under the [MIT License](LICENSE). You can use, modify and
share it freely, as long as the copyright notice stays with it.
