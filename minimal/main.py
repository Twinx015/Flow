"""flow-min: plain, non-interactive flow. No colour, no spinner, no prompts."""

import argparse
import sys

from backend.platform import bootstrap_vlc

bootstrap_vlc()
from backend import config as backend_config
from backend import history as history_mod

from . import core, extras, local, out, stats

EXAMPLES = """\
examples:
  flow-min status                     one line of player state
  flow-min play "karan aujla 52 bars" search YouTube and play the top hit
  flow-min play-off 52 bars           play a downloaded song
  flow-min --json search "arijit singh" | jq '.[0].video_id'
  flow-min search "arijit singh"      list the results as 1..N
  flow-min play 2                     play row 2 of that search
  flow-min tags play workout -s       play every downloaded "workout" song, shuffled
  flow-min ls -i                      list title | artist | file | thumbnail
  flow-min --random 3                 play three random downloaded songs
  flow-min next                       skip, from anywhere
  flow-min tags list --json           list tags as JSON
"""


def build_parser():
    """The whole command surface."""
    parser = argparse.ArgumentParser(
        prog="flow-min",
        description="Plain, non-interactive flow: no colour, no spinner, no prompts.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="print one JSON document instead of lines")
    parser.add_argument(
        "--random",
        nargs="?",
        const=1,
        type=int,
        metavar="N",
        help="play N random downloaded songs (default 1)",
    )
    parser.add_argument(
        "-r",
        "--repeat",
        dest="global_repeat",
        nargs="?",
        const=0,
        type=int,
        metavar="N",
        help="with --random: repeat the queue (N times; empty or 0 = forever)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {backend_config.VERSION}",
        help="print the Flow version and exit",
    )
    subs = parser.add_subparsers(dest="command", metavar="<command>")

    def add(name, help_text, aliases=()):
        sub = subs.add_parser(name, help=help_text, aliases=list(aliases))
        sub.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
        return sub

    def playback_flags(sub, index=True):
        sub.add_argument("query", nargs="*", help="song name")
        if index:
            sub.add_argument("-i", "--index", type=int, default=1, help="which search result (default 1)")
        sub.add_argument("-s", "--shuffle", action="store_true", help="shuffle the queue")
        sub.add_argument(
            "-r",
            "--repeat",
            nargs="?",
            const=0,
            type=int,
            metavar="N",
            help="repeat the queue (N times; empty or 0 = forever)",
        )
        sub.add_argument("--fg", action="store_true", help="stay in the foreground instead of detaching")
        return sub

    add("status", "what is playing right now").set_defaults(func=lambda a: core.status_cmd())
    playback_flags(add("play", "search YouTube or play a link; a bare number plays that row of the last search")).set_defaults(func=lambda a: core.play(" ".join(a.query), index=a.index, shuffle=a.shuffle, foreground=a.fg, repeat=a.repeat is not None, repeat_count=a.repeat or 0))
    playback_flags(add("play-off", "play a downloaded song"), index=False).set_defaults(func=lambda a: core.play_off(" ".join(a.query), shuffle=a.shuffle, foreground=a.fg, repeat=a.repeat is not None, repeat_count=a.repeat or 0))
    resume = add("resume", "play the current or last track again")
    resume.add_argument("--fg", action="store_true", help="stay in the foreground instead of detaching")
    resume.set_defaults(func=lambda a: core.resume(foreground=a.fg))

    search = add("search", "search YouTube or resolve a link without playing")
    search.add_argument("query", nargs="*")
    search.add_argument("--limit", type=int, help="how many results")
    search.set_defaults(func=lambda a: core.search(" ".join(a.query), limit=a.limit))

    add("stop", "stop the player").set_defaults(func=lambda a: core.stop())
    add("pause", "toggle pause").set_defaults(func=lambda a: core.pause())
    add("next", "skip to the next track").set_defaults(func=lambda a: core.next_track())
    add("prev", "go back a track").set_defaults(func=lambda a: core.prev_track())
    for name, help_text in (("seek", "seek forward N seconds"), ("seek-back", "seek back N seconds")):
        seek = add(name, help_text)
        seek.add_argument("seconds", type=int)
        seek.set_defaults(func=(lambda a: core.seek(a.seconds, False)) if name == "seek" else (lambda a: core.seek(a.seconds, True)))

    listing = add("list", "list downloaded songs", aliases=["ls"])
    listing.add_argument("--query", help="filter by title or artist")
    listing.add_argument("--limit", type=int)
    listing.add_argument(
        "-i",
        "--info",
        action="store_true",
        help="show title | artist | file path | thumbnail path",
    )
    listing.set_defaults(
        func=lambda a: local.list_songs(query=a.query, limit=a.limit, info=a.info)
    )
    liked = add("liked", "list liked songs")
    liked.add_argument("--limit", type=int)
    liked.set_defaults(func=lambda a: local.liked(limit=a.limit))
    add("like", "like the current track").set_defaults(func=lambda a: local.like())
    add("unlike", "unlike the current track").set_defaults(func=lambda a: local.unlike())

    download = add("download", "download a search result or direct link", aliases=["dl"])
    download.add_argument("query", nargs="*")
    download.add_argument("-i", "--index", type=int, default=1, help="which search result (default 1)")
    download.add_argument("-f", "--format", help="opus, m4a, mp3 or webm")
    download.set_defaults(func=lambda a: local.download(" ".join(a.query), index=a.index, fmt=a.format))

    delete = add("delete", "delete a downloaded song")
    delete.add_argument("query", nargs="*")
    delete.set_defaults(func=lambda a: local.delete(" ".join(a.query)))

    rename = add("rename", "rename a downloaded song")
    rename.add_argument("query", nargs="+")
    rename.add_argument("--to", dest="new_name", required=True, nargs="+", metavar="NAME", help="the new name")
    rename.set_defaults(func=lambda a: local.rename(" ".join(a.query), " ".join(a.new_name)))

    for name, help_text, func in (
        ("radio", "stream a radio mix from a song or artist", extras.radio),
        ("radio-off", "shuffle the downloaded library", extras.radio_off),
    ):
        radio = add(name, help_text)
        radio.add_argument("seed", nargs="*", help="defaults to the last played track")
        radio.add_argument("--limit", type=int)
        radio.set_defaults(func=(lambda a, f=func: f(" ".join(a.seed) or None, limit=a.limit)))

    tags = add("tags", "show, play, export or maintain user tags")
    tags.add_argument(
        "action",
        nargs="?",
        choices=["list", "add", "remove", "rename", "delete", "play", "random", "export"],
        default="list",
    )
    tags.add_argument(
        "args",
        nargs="*",
        help="add/remove: <song> <tag>   play/random/export: <tag>   rename: <tag> <new>   delete: <tag>",
    )
    tags.add_argument("-s", "--shuffle", action="store_true", help="shuffle a tag queue")
    tags.add_argument(
        "-r",
        "--repeat",
        nargs="?",
        const=0,
        type=int,
        help="repeat a tag queue (N times; empty or 0 = forever)",
    )
    tags.add_argument("-p", "--path", help="export destination folder")
    tags.set_defaults(
        func=lambda a: extras.tags(
            a.action,
            list(a.args),
            shuffle=a.shuffle,
            repeat=a.repeat is not None,
            repeat_count=a.repeat or 0,
            path=a.path,
        )
    )

    add("lyrics", "plain lyrics for the current track").set_defaults(func=lambda a: extras.lyrics())

    pl = add("playlist", "playlist subcommands", aliases=["pl"])
    pl.add_argument("name")
    pl.add_argument(
        "action",
        nargs="?",
        choices=["show", "add", "play", "remove", "clear", "create", "delete"],
        default="show",
    )
    pl.add_argument("argument", nargs="*")
    pl.add_argument("-i", "--index", type=int, help="track index for remove")
    pl.set_defaults(
        func=lambda a: extras.playlist_cmd(a.name, a.action, " ".join(a.argument) or None, index=a.index)
    )

    hist = add("history", "what was played")
    hist.add_argument("-s", "--sort", choices=list(history_mod.SORTS), default="recent")
    hist.add_argument("-n", "--limit", type=int, default=20)
    hist.add_argument("--since", help="today, 7d, 30d or all")
    hist.set_defaults(func=lambda a: stats.history_cmd(sort=a.sort, limit=a.limit, since=a.since))

    add("stats", "library and play totals").set_defaults(func=lambda a: stats.stats())
    return parser


def main(argv=None):
    """Entry point for the flow-min script."""
    argv = list(sys.argv[1:] if argv is None else argv)
    out.init("--json" in argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.random is not None:
        core.play_random(
            args.random,
            repeat=args.global_repeat is not None,
            repeat_count=args.global_repeat or 0,
        )
        return 0
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        args.func(args)
    except KeyboardInterrupt:
        out.fail("interrupted", 130)
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
