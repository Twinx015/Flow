# Offline mode

Offline mode plays local audio files from `~/.flow/downloads/`. Its command
module is `backend/Offline/commands.py`, selected when
`config.Mode == "Offline"`.

## The library

`backend/Offline/file.py` is the local-library front end:

- `get_all_songs()` recursively scans `~/.flow/downloads/` for files with
  known audio extensions (`.mp3 .flac .wav .m4a .ogg .opus .wma .aac
  .webm`).
- `get_songs()` excludes the `liked songs/` subfolder; `get_liked_songs()`
  scans just that folder.
- Songs are sorted by their display title from `library.db`
  (`display_name()` → `library.title_for_stem(stem)`); files whose video-id
  stem has no library entry fall back to the filename.
- `like_song()` / `unlike_song()` copy/move a file into
  `~/.flow/downloads/liked songs/` (a copy is kept in the main list).
- `delete_file()` removes a song and every same-stem sibling plus any copy
  in the liked folder.

Track titles for display are taken from `library.db` and cleaned with
`config._truncate_title` (filler words per `~/.flow/ignore.txt`), so the
offline library reads like a tagged music collection even though the files
are named by video id.

## Commands

`backend/Offline/commands.py` mirrors the online surface
(`run(cmd, extra, args)` + `COMMANDS` dict):

| Command | Behavior |
| ------- | -------- |
| `play` | Play song(s) from the library; `play all` plays everything, `play liked` plays the liked folder; multiple matches prompt for a pick |
| `random [n]` | Play `n` random songs from the library (default 1) |
| `search` | Filter the library by substring (file name or display title) |
| `list` | List the local library |
| `radio` | Shuffle and loop the library (or a seed), `Ctrl+C` next, `Ctrl+Q` quit |
| `like` / `unlike` | Like/unlike the currently playing song (copies the file into `liked songs/`) |
| `delete` | Delete a downloaded song (alias `dl-d`) |
| `playlist` / `switch` / `help` / `short` / `config` / `check` / `export` / `exit` | Shared command surface |

### Tab completion

When `readline` is available, `_setup_completion()` installs a completer
that completes command names, local song titles for `play`, and local song
titles for `delete`/`dl-d`.

## Playback

`backend/Offline/player.py` is a near copy of the online player but built
around local files:

- `play_file(filepath, title, ...)` plays a local path with VLC, rotates a
  queue built from the current command's selection, saves the pid to
  `~/.flow/vlc.pid`, updates `status.json` (thumbnail resolved to the local
  cache path), publishes MPRIS metadata, and runs `_display_loop` (same
  `bars`/`lyrics`/`progress`/`none` renderers as online mode).
- The same signal set from online mode is installed
  (`setup_nav_signals()`): play/pause, next/previous, seek, stop.
- `play_file` records the play with `history.record_play(stem, ..., mode="offline")`.
  Offline playback moves `song_count` and today's `play_days` bucket in
  `library.db` but does **not** add a row to `history.db` — the online play
  log stays online-only. The filename
  stem *is* the video id, so a downloaded song shares one counter with its
  online plays. See [Play counting](storage.md#play-counting).

## `--resume` from offline

`cli.main._resume` decides the mode by the stored thumbnail: a path
containing `.cache/` or under `~/.flow` means the last track was offline, and
it replays the file whose stem matches the recorded title via
`offline_commands.resume(title, args, thumb)`.