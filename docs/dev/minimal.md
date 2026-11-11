# Minimal CLI (`minimal/`)

`minimal/` is the `flow-min` entry point: the same backend, with every
interactive affordance removed. It exists for places where a prompt or a
progress bar is a bug rather than a feature — an ssh session on a terminal
that has no colour, a cron job, a script, or an agent driving the player.

```
flow-min status                     one line of player state
flow-min play "karan aujla 52 bars" search YouTube and play the top hit
flow-min --json search "arijit singh"
flow-min tags play workout -s       play every downloaded "workout" song, shuffled
flow-min ls -i                      title | artist | file path | thumbnail path
flow-min --random 3                 play three random downloaded songs
flow-min next                       skip, from any terminal
```

Three rules define it:

1. **Plain lines by default**, one JSON document with `--json` (either
   `flow-min --json status` or `flow-min status --json`), never colour,
   never a spinner, never a prompt.
2. **Every backend call is silenced** at the file-descriptor level, so the
   backend's own banners, questionary prompts and yt-dlp warnings can never
   contaminate that output.
3. **No command ever blocks by accident.** Playback detaches unless `--fg`
   is given, so `flow-min play ...` returns immediately with the new pid.

## Module map

| Module | Contents |
| ------ | -------- |
| `minimal/main.py` | `build_parser()` — the whole command surface; the only dispatcher |
| `minimal/out.py` | `init`/`emit`/`fail`/`quiet`/`fork_bg` — output, exit codes, fd silencing, background fork |
| `minimal/common.py` | shared helpers: `ns()`, `live_player()`, `signal()`, `clock`, `entry_url`, `current`, `library_rows`, `song_line` |
| `minimal/core.py` | status, transport control, search, `play`/`play-off`/`resume`, queue playback, `_spawn` |
| `minimal/local.py` | `list`, `liked`, `like`, `unlike`, `download`, `delete`, `rename` |
| `minimal/extras.py` | `radio`, `radio-off`, `tags`, `lyrics`, `playlist` |
| `minimal/stats.py` | `history`, `stats` |
| `minimal/__main__.py` | `python -m minimal` |

`main.py` holds argparse wiring only; the behaviour lives in the four command
modules, which import `backend.*` directly. Nothing in `backend/` imports
`minimal`.

## Output contract (`out.py`)

`out.init()` keeps a **private dup of fd 1**. That is the only stream `out`
ever writes to, so `out.quiet()` can point the *real* fd 1 and 2 at
`/dev/null` while a backend call runs:

```python
with out.quiet():
    path = youtube.download_url(url, config.DOWNLOAD_DIR, fmt=fmt)
```

Duplicating the descriptor rather than reassigning `sys.stdout` is what makes
this airtight: spinner threads and yt-dlp's own writes go to the void too, and
`out.emit` afterwards is unaffected. `quiet()` is the default wrapper around
every backend call in the package; if you add a command, wrap anything that
prints.

- `out.emit(payload, text)` — `text` is a line or a list of lines; with
  `--json` the `payload` is dumped instead, as exactly one document.
- `out.fail(message, code=1)` — writes `flow-min: <message>` to stderr,
  emits `{"error": ...}` for `--json` callers, and raises `SystemExit`.
  `code=2` means "ambiguous, here are the candidates" (see below); `130`
  is used for `KeyboardInterrupt`.
- `out.fork_bg()` — `config.kill_stored()` in the parent, `save_pid(pid)`,
  and the child immediately dup2's `/dev/null` onto fds 0/1/2.

Exit codes: `0` success, `1` failure, `2` ambiguous input, `130` interrupted.

## Ambiguity instead of prompting

The interactive CLI asks. `flow-min` never does: when a name matches more
than one downloaded song, the candidates are printed and the command exits
`2`, so the caller can retry with a longer name.

```console
$ flow-min delete bars
52 Bars  /home/me/.flow/downloads/4DfVxVeqk2o.opus
Achha Ji  /home/me/.flow/downloads/ZN_XrB_St-8.opus
flow-min: 2 songs match 'bars'; be more specific   # exit 2
```

## Playback

`_spawn(setup, run, payload, text)` is the single backgrounding path: stop
whatever is playing, fork, register the child as `vlc` in the registry, and
print one line. The child runs `setup()` (the mode's `setup_nav_signals()`)
then the blocking `run()`.

Two things are deliberate:

- **The backend is called with `bg=False`.** `minimal` forks itself, so the
  `Namespace` handed to `backend.*` must say `bg=False` — otherwise
  `Offline.commands._play_queue` forks *again* and the registered pid is the
  grandchild's, which exits immediately.
- **Online `play` never routes through `Online.commands.play`**, which is a
  silent no-op when stdin is not a TTY. It calls `youtube.search()` →
  `youtube.get_entry()` → `Online.player.play_entry()` instead.

`resume` resolves the exact video id from the `status.json` thumbnail
(`_vid_from_thumb`) rather than re-searching by title.

## Commands

| Group | Commands |
| ----- | -------- |
| Player | `status`, `play`, `play-off`, `resume`, `search`, `stop`, `pause`, `next`, `prev`, `seek`, `seek-back`, `--random [N]` |
| Library | `list`/`ls` (`-i` adds artist, file and thumbnail paths), `liked`, `like`, `unlike`, `download`/`dl`, `delete`, `rename` |
| Tags, radio, lyrics | `tags` (`list`, `play`, `random`, `export`, `add`, `remove`, `rename`, `delete`), `radio`, `radio-off`, `lyrics` |
| Collections, history | `playlist`/`pl`, `history`, `stats` |

Suffixes mirror the main CLI: `play` is online search, `play-off` is a local
file, `radio` is a YouTube mix and `radio-off` a shuffle of the library.
Song names and tags are `nargs="*"` and joined, so multi-word tags work
unquoted; `rename` takes `--to` so the new name can never be mistaken for
part of the query.

`search` writes its rows to `~/.flow/search.json` (tmp + `os.replace`, like
every other JSON file under `~/.flow`) and `play` reads them back when its
argument is a bare number, so the pick costs no second search and no prompt.
A YouTube link passed to `search`, `play` or `download` resolves to that one
video instead of being sent to the search API:

```console
$ flow-min search "night changes"
1. One Direction - Night Changes (3:36)
$ flow-min play 1
playing  One Direction - Night Changes  (pid 4123)
```

Nothing saved means `flow-min: no saved search; run 'flow-min search <query>' first`
and exit `1`; a number past the end reports the range the same way.

`--random [N]` is the only flag that runs without a subcommand. It samples `N`
downloaded songs (default 1) and plays them through the same queue path as
`radio-off`; JSON output is the usual `{"status": "playing", ...}` payload.

Playlist subcommands: `show` (default), `create`, `add`, `play`, `remove`,
`clear`, `delete`.

## Reused backend internals

`minimal` calls a few private helpers that are proven but not part of the
public command surface: `backend.status._fresh` / `_vid_from_thumb`,
`Offline.commands._play_queue`, `Online.commands._play_queue`. They are
stable, tested internals of the same package; promoting any of them to a
public name is a fine follow-up.

## Testing

`tests/test_minimal.py` covers the contract rather than the music: plain vs
JSON output, the absence of ANSI escapes, `quiet()` swallowing fd-level
writes (including from threads), `fail()` exit codes and error documents,
seek writing its delta to `~/.flow/seek.txt` before signalling, the parser
keeping multi-word arguments in one piece, and a smoke test that every
command in the surface parses.

Two things the tests cannot do for real: fork a background player or open an
audio stream, so playback paths are covered by hand. Because `out` prints on
a private dup of fd 1, tests call `out.init()` inside the test body and read
back with `capfd` — pytest swaps fd 1 per phase, so an `out.init()` done in
a fixture would write to the wrong capture file.
