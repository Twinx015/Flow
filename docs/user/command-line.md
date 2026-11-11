# Command line

`flow` has three personalities:

1. **Interactive shell** — run `flow` with no arguments to get a prompt.
2. **One-shot flags** — `flow --play "song"`, `flow --status`, `flow --summary`, control flags, etc.
3. **Shell-mode commands** — `flow <command> <args>` runs a single command and exits.

There is also a fourth front end, [`flow-min`](#flow-min-plain-non-interactive), for
scripts, ssh sessions and agents.

## One-shot flags

| Flag                | Description                                                               |
| ------------------- | ------------------------------------------------------------------------- |
| `-bg`               | Play in the background and return to the shell                            |
| `-s`                | Shuffle (used with play/radio)                                            |
| `-r [n]`            | Repeat `n` times, or repeat forever when no number is given               |
| `-d`                | Download the played song                                                  |
| `--play <name>`     | Play a song from YouTube                                                  |
| `--play-off <name>` | Play from the local library without going online (auto-background)        |
| `--rd <name>`       | Radio mix from YouTube (auto-background)                                  |
| `--radio-off`       | Radio over the shuffled local library (auto-background)                   |
| `--resume`          | Resume the last played track from `~/.flow/status.json` (auto-background) |
| `--pause`           | Toggle play/pause in the running player (VLC, TUI, or web)                |
| `--next`            | Skip to the next track in the running player                              |
| `--previous`        | Go back to the previous track in the running player                       |
| `--seek SEC`        | Seek SEC seconds forward in the running player                            |
| `--seekb SEC`       | Seek SEC seconds backward in the running player                           |
| `--status`          | Print the playback status card and exit                                   |
| `--full`            | Full-screen now-playing view: clear the terminal, show the logo and a live progress card (refreshes every second; Ctrl-C to exit) |
| `--summary`         | Play statistics; see [summary](#summary) below                            |
| `--meta [force]`    | Re-fetch metadata for every downloaded song; resumes after a block, `force` restarts from the beginning |
| `--like`            | Like the currently playing song (requires an active player)               |
| `--unlike`          | Unlike the currently playing song                                         |
| `--download`        | Download the currently playing song                                       |
| `--import FILE`     | Import a CSV, m3u, or txt track list (see [importing](#importing-a-list)) |
| `--setup-island`    | Install the Hyprland music island into `~/.config/quickshell`             |
| `--check`           | Check all dependencies                                                    |

`-bg`, `-s`, `-r`, `-d`, and `-m` are also accepted inline at the end of
shell-mode commands, e.g. `flow play daft punk -s -r 3`. Single-letter flags
combine, so `-dm` is the same as `-d -m` (`-ms`, `-dms` work too).

### Multi-select (`-m`)

`-m` turns the result picker into a checkbox so you can act on several results
at once. Without `questionary` installed the picker falls back to a prompt where
you type `1,3,5-7`, `1-`, `-3`, or `all`.

| Command                          | Result                                 |
| -------------------------------- | -------------------------------------- |
| `flow download <query> -m`       | download every ticked track            |
| `flow search <query> -dm`        | download every ticked track            |
| `flow play <query> -dm`          | download every ticked track, then play |
| `flow search <query> -m`         | play the ticked tracks as a queue      |
| `flow play <query> -m`           | play the ticked tracks as a queue      |
| `flow play <query> -m` (offline) | play the ticked songs as a queue       |

Queued playback wires up next/prev between the selected tracks, and `-r` still
repeats the queue.

## Shell mode

Run a command from your shell without entering interactive mode. When the
command plays music it stays in the foreground — like the interactive shell —
unless it backgrounds itself:

- `radio`, `savan`, `--rd`, `--radio-off`, `--play-off`, and `--resume`
  automatically spawn a background player and return to the shell.
- Everything else (`play`, `--play`, `-pl ...`) plays in the foreground;
  add `-bg` to background it, e.g. `flow play daft punk -bg`.

```bash
flow play never gonna give you up     # foreground playback
flow play never gonna give you up -bg # background playback
flow play https://youtu.be/dQw4w9WgXcQ # play a link directly
flow search daft punk          # print results, exit
flow search https://youtu.be/dQw4w9WgXcQ # resolve one link
flow radio daft punk           # radio mix (auto-bg)
flow playlist list
flow plist list                 # plist is the playlist alias
```

The control flags above (`--pause`, `--next`, `--previous`, `--seek`,
`--seekb`, `--like`, `--unlike`, `--download`, `--status`) talk to whatever
player is currently running — a background VLC, the TUI, or the web player —
and work whether or not a `flow` session is active.

### Shortcuts

Shell-mode and interactive commands accept your user-defined shortcuts as
aliases, with a `-` prefix:

```bash
flow -pl never gonna give you up    # pl -> play (foreground; add -bg for background)
flow -rd daft punk                  # rd -> radio (auto-bg)
flow -sh daft punk                  # sh -> search
flow -svn hello                     # svn -> savan (auto-bg)
flow -dl never gonna give you up    # dl -> download
```

Built-in aliases (overridable/extendable via `~/.flow/shortcuts.json`):

`pl` play · `sh` search · `ls` list · `lk` like · `ul` unlike · `dl` download
· `dl-d` delete · `re` rename · `rd` radio · `sw` switch · `hl` help ·
`cf` config · `ex` exit · `svn` savan · `svn-s` savan-s · `plist` playlist

Manage them inside Flow with the `short` command:

```bash
short                     # list all shortcuts
short add <key> <cmd>     # add or update an alias
short remove <idx>        # remove by list index
short <idx> <new_cmd>     # update by index
```

## Commands

These work in both the interactive prompt and shell mode. `search` shows
results with indices; `play <index>` plays a result by number, and after a
download the matching index can be used the same way.

| Command                        | Description                                                                                                                                                                                                                       |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `play <name, link, index, or liked>` | Play a song by name, YouTube link or search-result number; offline also supports `play liked` and `play all`. `-m` plays a ticked selection as a queue                                                                          |
| `random [n]`                   | Play `n` random songs from the downloaded library (default 1)                                                                                                                                                                     |
| `search <query or link>`       | Search YouTube (online) or the local library (offline); a YouTube link resolves to that one track; `-dm` downloads a ticked selection                                                                                             |
| `list`                         | List the local library (offline; alias `ls`)                                                                                                                                                                                      |
| `savan <name>`                 | Play a song from JioSaavn (online)                                                                                                                                                                                                |
| `savan-s <query>`              | Search JioSaavn (online)                                                                                                                                                                                                          |
| `radio <name> [index]`         | Radio mix (online) or shuffle-loop library (offline). Bare `radio` shuffles everything; a name seeds the loop with that song. `-p` saves as playlist                                                                              |
| `like` / `unlike`              | Like/unlike the current song; liked songs are saved to the library and played with `play liked`                                                                                                                                   |
| `download <query, link or index>`    | Save a streamed song (online; `-f <format>` picks opus/m4a/mp3/webm). Add `-m` to tick and download several                                                                                                                       |
| `delete <name or index>`       | Delete a downloaded song (alias: `dl-d`)                                                                                                                                                                                          |
| `rename <name or index>`       | Rename a downloaded song (offline; alias: `re`). You are then asked for the new name. An index is the number in the `list` output (ascending by name) and the prompt repeats it                                                   |
| `tags [list \| add \| remove \| rename \| delete \| play \| random \| export]` | Inspect or maintain user tags. Bare `tags` opens an interactive menu (play all, play one/random, export, add/remove songs, rename, delete, list); `tags play <tag> [-r] [-s]` plays every song in a tag (repeat/shuffle), `tags random <tag>` plays one, `tags export <tag> [-p <dir>]` copies only that tag's songs, `tags add <song> <tag>` / `tags remove <song> <tag>` tag one song, `tags rename <old> <new>` renames a tag everywhere, `tags delete <tag>` drops it everywhere |
| `playlist <sub>`               | Manage playlists — see below                                                                                                                                                                                                      |
| `switch`                       | Toggle between online and offline mode                                                                                                                                                                                            |
| `config [target [value]]`      | Change settings; run bare for an interactive wizard                                                                                                                                                                               |
| `short`                        | Show/update command shortcuts                                                                                                                                                                                                     |
| `check`                        | Check all dependencies                                                                                                                                                                                                            |
| `summary`                      | Play statistics and the ranked per-song table — see below                                                                                                                                                                         |
| `export [-p <path>]`           | Copy downloaded songs (tagged) to `~/Downloads`, or to `<path>`                                                                                                                                                                   |
| `help` / `help -i`             | Command list / detailed help                                                                                                                                                                                                      |
| `exit`                         | Leave the interactive shell                                                                                                                                                                                                       |
| `clear`                        | Clear the terminal and reprint the flow logo (alias: `cls`)                                                                                                                                                                       |

### summary

`summary` reports what you've been playing. The stats card splits the
numbers — **combined** plays (both modes, from `~/.flow/library.db`),
**online** plays (`~/.flow/history.db`) and **offline** (the difference) —
then lists your top artist and top song, and charts the last
7 days: one bar per calendar day with online (`█`) and offline (`░`)
stacked, ending in `online/offline` counts, plus a progress bar comparing
**this week vs last week**. Days run midnight to midnight, so `today` and the
card's `played today` always mean *since midnight*.

```bash
flow summary                          # stats card + a 7-day online/offline chart
flow summary -l                       # the ranked per-song table
flow summary -l -s artist --top 50    # sort by artist, 50 rows
flow summary -c                       # clear play history (both stores)
```

| Flag        | Description                                                         |
| ----------- | ------------------------------------------------------------------- |
| `-l`        | Show the per-song table instead of the stats card                   |
| `-s <sort>` | Table sort: `plays` (default), `recent`, `name`, `artist`           |
| `--top <N>` | Rows to show in the table (default: 20)                             |
| `-c`        | Clear all play history (`history.db` rows and `library.db` counts)  |

`-c` wipes both stores so the online/offline split stays honest: the play
timeline empties and every `song_count` in `library.db` drops to zero.
Likes, downloads, tags and renames are untouched.

In shell mode `flow summary …` takes the same flags. As a one-shot flag,
`flow --summary …` also accepts the long `--sort <key>` and `--top <N>`
spellings:

```bash
flow --summary -l --sort recent --top 10
```

The **web History panel** shows the other half of the data: an online-only
timeline you can sort by _newest_, _oldest_, _most played_ or _least played_
and filter to today / 7 days / 30 days. The split is deliberate — the CLI
ranks a per-song table (a terminal is bad at a long event log), the web panel
sorts an event stream (a scrollable column is bad at aggregates).

### tags

Tags are yours. Downloads no longer create language or artist tags, and values
left by an older version are cleared once; the `language` and `artist` columns
stay only so old databases open cleanly. Assign whatever tags help you —
`workout`, `roadtrip`, a mood, a language, an artist — with `tags add`.

```bash
flow tags                      # interactive menu (in the shell)
flow tags list                 # every tag and how many songs use it
flow tags play workout         # play the whole tag, ascending by name
flow tags play workout -s      # shuffled
flow tags play workout -r 3    # repeat the queue three times (0 = forever)
flow tags random workout       # play one random song from the tag
flow tags export workout       # copy the tag's songs to ~/Downloads/workout
flow tags export workout -p ~/Music/workout
flow tags add "Mitti" workout  # tag one downloaded song
flow tags remove "Mitti" workout
flow tags rename workout gym   # on every song that has it
flow tags delete workout       # drop it everywhere
```

Bare `tags` is the interactive menu: play all songs in a tag, play a single or
random one, export a tag, add or remove songs (checkbox lists), rename, delete
and list. Every action is available without the menu through the forms above.

`tags export` uses the same copy-and-write-metadata path as `export`, but only
for the selected tag's songs; without `-p` it writes to
`~/Downloads/<tag>`.

### export

`export` copies every song in `~/.flow/downloads` somewhere you can reach it
with a file manager, and writes the library's metadata into each copy.

```bash
flow export                    # -> ~/Downloads
flow export -p ~/Music/flow    # -> anywhere else
```

| Flag        | Description                                                           |
| ----------- | --------------------------------------------------------------------- |
| `-p <path>` | Destination directory (created if missing). Defaults to `~/Downloads` |

Each copy is named after the song — `Never Gonna Give You Up.webm`, not
`dQw4w9WgXcQ.webm` — and tagged with the title, artist and album from
`library.db`. A song the library has no title for is tagged with its own file
name. Cover art is attached where the format allows it, and the audio itself
is never re-encoded.

Re-running `export` refreshes the files it already wrote instead of creating
`… (2).webm` copies, so a song that changed in the library gets re-tagged in
place.

Tagging needs `ffmpeg` (`flow check` will tell you if it's missing). Without
it the songs are still copied, just untagged.

### metadata refresh

`flow --meta` re-fetches title, artist, album and duration for every
downloaded song, and fills in any missing thumbnail. The video id is taken from
the audio file name (`~/.flow/downloads/<video_id>.opus`), so no extra
bookkeeping is needed.

```bash
flow --meta          # re-fetch, resuming an unfinished run
flow --meta force    # ignore saved progress and start from the first song
```

Metadata requests can make YouTube temporarily block your IP. When that
happens the command stops, prints how far it got, and saves progress in
`~/.flow/meta.json`. Run the same command again after a break and it resumes
from the first unfinished song instead of starting over. `flow --meta force`
deletes that state and starts again from zero. The state file is removed once
a run finishes. Files whose names are not a YouTube video id are skipped.

### Playlist subcommands

`playlist` (alias `plist`): `create` · `add` · `remove` · `list` · `play` ·
`rename` · `move` · `duplicate` · `merge` · `sort` · `clear` · `dedupe` ·
`info` · `export` · `import` · `download`

```bash
flow playlist create roadtrip
flow playlist add roadtrip "some song"
flow playlist add -m roadtrip 3 7 9   # several songs at once (search index or query each)
flow playlist remove -m roadtrip 2 5  # several by index; indices are resolved high-to-low
flow playlist remove -m roadtrip a b  # several by title match (first match each)
flow playlist list
flow playlist play roadtrip
flow playlist export roadtrip   # writes roadtrip.m3u to ~/Downloads
flow playlist import songs.m3u  # name defaults to the file name
flow playlist download roadtrip # download all YouTube tracks in it
```

`-m` may appear right after the subcommand (`playlist add -m pl ...`) or
after the name (`playlist add pl -m ...`). Without it, `add`/`remove` behave
as before: every word after the name is one query or one title.

`liked` is a reserved playlist name.

### Importing a list

`flow --import FILE` turns a song list you already have into flow tracks.
The format follows the file extension, with content sniffing for anything
else:

- **`.csv`** — the header row picks the columns. Common names are
  auto-detected: a URL or video-id column is used directly, otherwise
  title/artist (aliases like Spotify's `Track Name`, `Artist Name(s)`, or
  YouTube Takeout's `Video Id`) become a YouTube search. `Duration` accepts
  `m:ss`, plain seconds, or milliseconds (`Duration(ms)`).
- **`.m3u` / `.m3u8`** — `#EXTINF` titles and durations plus URL lines.
  Local file paths that exist are kept as offline tracks; other lines
  become queries.
- **`.txt`** — one song per line: a URL (with an optional label before it)
  or a plain search query. `#` lines are comments.
- **anything else** — sniffed: `#EXTM3U`/`#EXTINF` parses as m3u, a
  `title/url/artist…` header line as CSV, the rest as txt.

The file is previewed first (`url`/`search` marks show how each row
resolves), then an interactive panel offers:

1. **Download all as a playlist** — asks for a playlist name (the file name
   is the default), adds every track, and downloads them;
   already-downloaded songs are skipped.
2. **Download (no playlist)** — just the downloads.
3. **Play online one by one** — a queue played straight through; Ctrl-C
   exits, player next/previous keys navigate.

`-f <fmt>` works with the download actions (`flow --import list.csv -f m4a`).
Imports need online mode.

## flow-min: plain, non-interactive

`flow-min` is a fourth front end over the same player and library, with every
interactive affordance removed: no colour, no spinner, no prompts. It is for
the places where a prompt is a bug — an ssh session on a terminal with no
colour, a pipe, a cron job, or an agent driving the player.

```bash
flow-min status                     one line of player state
flow-min play "karan aujla 52 bars" search YouTube and play, then return
flow-min play-off 52 bars           play a downloaded song
flow-min search "arijit singh"      list the results as 1..N
flow-min play 2                     play row 2 of that search
flow-min --json search "arijit singh" | jq '.[0].video_id'
flow-min tags play workout -s       play every downloaded "workout" song, shuffled
flow-min ls -i                      title | artist | file path | thumbnail path
flow-min --random                   play one random downloaded song
flow-min --random 5                 play five random downloaded songs
flow-min next                       skip, from any terminal
```

`search` remembers the rows it printed, so a bare `play <index>` picks one of
them instead of searching again — no prompt in between, and nothing to copy
by hand. With no saved search it exits `1` and says so; a number past the end
reports the range.

`ls -i` (or `list -i`) prints one numbered row per downloaded song with the
artist, file path and thumbnail path:

```console
$ flow-min ls -i
1. Night Changes | One Direction | /home/me/.flow/downloads/abc123.opus | /home/me/.flow/thumbnails/abc123.jpg
2. Mitti | Karan Aujla | /home/me/.flow/downloads/def456.opus | /home/me/.flow/thumbnails/def456.jpg
```

`--random [N]` plays `N` random downloaded songs (one when `N` is omitted).

The commands are the part of the table above that never needs a conversation:
`status`, `play`, `play-off`, `random`, `resume`, `search`, `stop`, `pause`,
`next`, `prev`, `seek`, `seek-back`, `list`, `liked`, `like`, `unlike`,
`download`, `delete`, `rename`, `radio`, `radio-off`, `tags`, `lyrics`,
`playlist`, `history`, `stats`. The conversational ones — `config`, `switch`,
`summary`, `export`, the shortcuts and the dependency check — stay with
`flow`.

Three rules:

- **One line by default, one JSON document with `--json`** — before or after
  the command: `flow-min --json status`, `flow-min status --json`.
- **It never asks.** Where the shell prompts you for the new name, `flow-min`
  takes `rename <song> --to <new name>`; where a name matches several songs
  it prints the candidates and exits `2` so the caller can retry with a
  longer one.
- **It never blocks by accident.** Playback detaches and prints the new pid;
  add `--fg` to keep it in the foreground.

Exit codes: `0` success, `1` failure, `2` ambiguous input, `130` interrupted.

```console
$ flow-min delete bars
52 Bars  /home/me/.flow/downloads/4DfVxVeqk2o.opus
Achha Ji  /home/me/.flow/downloads/ZN_XrB_St-8.opus
flow-min: 2 songs match 'bars'; be more specific
$ echo $?
2
```

`flow` and `flow-min` share `~/.flow` completely: a song downloaded by one is
listed by the other, and either can control a player the other started.
