import atexit
import os
import sys
import threading
import time

from backend import (
    api,
    config,
    history,
    ipc,
    keys,
    library,
    lyrics,
    mpris,
    platform,
    rich_display,
    sponsor,
    status,
    visualizer,
)

platform.bootstrap_vlc()
import vlc

try:
    import curses
except ImportError:
    curses = None

_truncate_title = config._truncate_title

P = config.Primary
S = config.Secondary
T = config.Tertiary
M = config.Muted
E = config.RED
R = config.Reset


m = lambda t: print(f"{M}{t}{R}")
e = lambda t: print(f"{E}{t}{R}")
i = lambda t: print(f"{P if config.Mode == 'Online' else S}{t}{R}")
ter = lambda t: print(f"{T}{t}{R}")

_paused = False
_player = None
_reader = None
_radio_active = False

_next_req = False
_prev_req = False
_stop_req = False
_nav = (False, False)


_now = {"title": "", "duration": 0, "thumbnail": None}


def _publish_play_state():
    if not _now.get("title"):
        return
    try:
        status.update(
            _now["title"],
            duration=_now.get("duration", 0),
            playing=not _paused,
            thumbnail=_now.get("thumbnail"),
        )
    except Exception:
        pass


_pos_pub_at = 0.0


def _tick_position(player, elapsed=None):
    """Publish live position ~1/s so `flow --full` can render progress."""
    global _pos_pub_at
    now = time.time()
    if now - _pos_pub_at < 1.0:
        return
    _pos_pub_at = now
    try:
        pos = elapsed if elapsed is not None else player.get_time() / 1000.0
        status.update_elapsed(pos)
    except Exception:
        pass


def _teardown():

    global _player
    p, _player = _player, None
    if p is None:
        return
    try:
        p.stop()
    except Exception:
        pass
    try:
        p.release()
    except Exception:
        pass


def _clear_stale_pid():
    if config.read_pid() == os.getpid():
        config.clear_pid()


atexit.register(_clear_stale_pid)


def _sigusr1_toggle():
    global _paused
    _paused = not _paused
    if _player:
        _player.pause()


def _sigusr2_next():
    global _next_req
    _next_req = True
    if _player:
        _player.stop()


def _sigusr3_prev():
    global _prev_req
    _prev_req = True
    if _player:
        _player.stop()


def _sigusr4_stop():
    global _stop_req
    _stop_req = True
    if _player:
        _player.stop()


def _seek_current(payload=None):
    delta_ms = (payload or {}).get("delta") if payload else None
    if delta_ms is None:
        delta_ms = config.read_seek()
    config.clear_seek()
    if _player and delta_ms:
        cur = _player.get_time()
        if cur is not None and cur >= 0:
            _player.set_time(max(0, int(cur) + int(delta_ms)))


def _dispatch_action(action, payload=None):
    if action == "pause":
        try:
            from backend import logger
            logger.log_track_event("player", "pause_toggle", {"title": _now.get("title")})
        except Exception:
            pass
        _sigusr1_toggle()
    elif action == "next":
        try:
            from backend import logger
            logger.log_track_event("player", "next", {"title": _now.get("title")})
        except Exception:
            pass
        _sigusr2_next()
    elif action == "prev":
        try:
            from backend import logger
            logger.log_track_event("player", "prev", {"title": _now.get("title")})
        except Exception:
            pass
        _sigusr3_prev()
    elif action == "stop_all":
        try:
            from backend import logger
            logger.log_track_event("player", "stop_all", {"title": _now.get("title")})
        except Exception:
            pass
        _sigusr4_stop()
    elif action in ("seek_fwd", "seek_bwd"):
        try:
            from backend import logger
            logger.log_track_event("player", "seek", {"title": _now.get("title"), "action": action, "payload": payload})
        except Exception:
            pass
        _seek_current(payload)


def _install_controls():
    port = ipc.serve(_dispatch_action, kind="vlc")
    config.save_pid(os.getpid(), ctl_port=port)


def _setup_pause_input():
    global _reader
    if _radio_active:
        return
    _reader = keys.RawReader(_on_pause_key)
    _reader.start()


def _on_pause_key(ch):
    if ch == 0x10:
        ipc.dispatch("pause")


def _restore_pause_input():
    global _reader
    if _reader is not None:
        _reader.stop()
        _reader = None


def _flags_str(args):
    if not args:
        return ""
    parts = []
    if getattr(args, "repeat", False):
        count = getattr(args, "repeat_count", 0)
        parts.append(f"[Repeat:{'∞' if count < 0 else count}]")
    if getattr(args, "shuffle", False):
        parts.append("[Shuffle:On]")
    return "  ".join(parts)


def _restart_current(player):
    global _prev_req, _paused
    if _next_req or _stop_req:
        return False
    if not _nav[1]:
        _prev_req = False
        _paused = False
        try:
            player.play()
            player.set_time(0)
        except Exception:
            return False
        return True
    return False


def _attach_vlc_events():
    p = _player
    if p is None:
        return
    try:
        em = p.event_manager()
    except Exception:
        return

    def _on_event(event):
        try:
            t = event.type
            if t == vlc.EventType.MediaPlayerPlaying:
                mpris.set_status(mpris.PLAYING)
            elif t == vlc.EventType.MediaPlayerPaused:
                mpris.set_status(mpris.PAUSED)
            elif t in (
                vlc.EventType.MediaPlayerStopped,
                vlc.EventType.MediaPlayerEndReached,
            ):
                mpris.set_status(mpris.STOPPED)
        except Exception:
            pass

    for etype in (
        vlc.EventType.MediaPlayerPlaying,
        vlc.EventType.MediaPlayerPaused,
        vlc.EventType.MediaPlayerStopped,
        vlc.EventType.MediaPlayerEndReached,
    ):
        try:
            em.event_attach(etype, _on_event)
        except Exception:
            pass


def _display_loop(
    player,
    title,
    video_id=None,
    stop_check=None,
    args=None,
    next_title=None,
    artist="",
    album="",
    duration=0,
):
    global _paused
    display = config.Display
    if display == "bars" and (curses is None or not platform.is_linux()):
        display = "none"
    if display in ("bars", "progress", "rich") and not (
        sys.stdin.isatty() and sys.stdout.isatty()
    ):
        display = "none"
    if display == "none":
        paused_printed = False
        while player.get_state() not in (vlc.State.Ended, vlc.State.Error):
            if stop_check and stop_check():
                break
            if _stop_req or _next_req:
                break
            if _prev_req:
                if _restart_current(player):
                    continue
                break
            if _paused:
                if not paused_printed:
                    paused_printed = True
                    _publish_play_state()
            elif paused_printed:
                paused_printed = False
                _publish_play_state()
            _tick_position(player)
            time.sleep(0.1)
        return

    if display == "bars":
        shuffle = bool(getattr(args, "shuffle", False))
        repeat = bool(getattr(args, "repeat", False))
        visualizer.set_status(
            title, shuffle=shuffle, repeat=repeat, next_title=next_title,
            artist=artist, album=album,
        )

    fetched_lyrics = None
    if display == "lyrics":
        track_lyrics = lyrics.fetch_lyrics(
            video_id, title=title, artist=artist, album=album, duration=duration
        )
        if track_lyrics:
            fetched_lyrics = track_lyrics["lines"] or None
            if not fetched_lyrics:
                for line in track_lyrics["plain"]:
                    print(f"  {P}{line}{R}" if line else "")
        else:
            m("    No lyrics found")

    if display == "bars":
        stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        stdscr.keypad(True)
        if not visualizer.start(stdscr, P):
            curses.nocbreak()
            stdscr.keypad(False)
            curses.echo()
            curses.curs_set(1)
            curses.endwin()
            return

    last_lyric_line = None
    paused_printed = False
    rich_disp = None
    if display == "rich":
        rich_disp = rich_display.NowPlaying(
            title, artist=artist, album=album, duration=duration
        )
        rich_disp.start()
    try:
        while player.get_state() not in (vlc.State.Ended, vlc.State.Error):
            if stop_check and stop_check():
                break
            if _stop_req or _next_req:
                break
            if _prev_req:
                if _restart_current(player):
                    continue
                break
            if _paused:
                if not paused_printed:
                    visualizer.set_paused(True)
                    if display == "bars":
                        try:
                            y, x = stdscr.getmaxyx()
                            stdscr.addstr(0, 0, "  [Paused]  ", curses.A_BOLD)
                            stdscr.refresh()
                        except curses.error:
                            pass
                    elif display == "rich":
                        if rich_disp:
                            rich_disp.update(
                                max(0.0, player.get_time() / 1000.0), paused=True
                            )
                    else:
                        sys.stdout.write(f"\r  {T}[Paused]{R}  ")
                        sys.stdout.flush()
                    paused_printed = True
                    _publish_play_state()
                try:
                    time.sleep(0.1)
                except OSError:
                    pass
                continue
            if paused_printed:
                visualizer.set_paused(False)
                paused_printed = False
                _publish_play_state()
            elapsed = max(0.0, player.get_time() / 1000.0)
            _tick_position(player, elapsed)
            if display == "bars":
                visualizer.draw()
            elif display == "rich":
                if rich_disp:
                    rich_disp.update(elapsed, _paused)
            elif display == "progress":
                config.render_progress(elapsed, duration)
            elif display == "lyrics" and fetched_lyrics:
                line = lyrics.find_line(fetched_lyrics, elapsed)
                if line and line != last_lyric_line:
                    last_lyric_line = line
                    try:
                        time.sleep(0.3)
                    except OSError:
                        pass
                    print(f"  {P}{line}{R}")
            try:
                time.sleep(0.08)
            except OSError:
                pass
    finally:
        if rich_disp is not None:
            rich_disp.stop()
        if display == "bars":
            visualizer.stop()
            curses.nocbreak()
            stdscr.keypad(False)
            curses.echo()
            curses.curs_set(1)
            curses.endwin()
        else:
            sys.stdout.write("\r" + " " * 60 + "\r\n")
            sys.stdout.flush()


def play_url(
    url,
    title,
    args=None,
    duration=0,
    thumbnail=None,
    next_title=None,
    entry=None,
    nav=None,
):
    global _player, _paused, _next_req, _prev_req, _stop_req, _nav
    _paused = False
    _next_req = False
    _prev_req = False
    _stop_req = False
    _nav = tuple(nav) if nav else (False, False)
    config.save_pid(os.getpid())
    config.clear_seek()
    devnull = os.open(os.devnull, os.O_RDWR)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    try:
        _teardown()
        instance = vlc.Instance("--no-video --quiet")
        _player = instance.media_player_new()
        media = instance.media_new(url)
        _player.set_media(media)
        _player.play()
        _install_controls()
        _setup_pause_input()

        config.dev_print(
            "Player (Savan URL)",
            {
                "title": title,
                "stream_url": url[:80] + "..." if len(url) > 80 else url,
                "duration": f"{duration}s",
                "thumbnail": thumbnail,
            },
        )

        _now.update(title=title, duration=duration, thumbnail=thumbnail)
        status.update(title, duration, thumbnail=thumbnail)
        dur_min, dur_sec = divmod(int(duration), 60)
        flags = _flags_str(args)
        artist = ""
        album = ""
        if entry:
            primary = (entry.get("artists") or {}).get("primary") or []
            if primary:
                artist = primary[0].get("name", "") or ""
            album = (entry.get("album") or {}).get("name") or ""
        if config.Display != "bars":
            i(f"\n[⥤ Now : {_truncate_title(title)}]")
            if artist:
                m(f"    {artist}")
            if album:
                m(f"    {album}")
            m(
                f"    [{dur_min}:{dur_sec:02d}]  {flags}"
                if flags
                else f"    [{dur_min}:{dur_sec:02d}]"
            )
        # JioSaavn tracks have no YouTube id; namespace the song id so it can
        # never collide with a real video id in the library.
        savan_id = (entry or {}).get("id") or ""
        history.record_play(
            f"j:{savan_id}" if savan_id else "",
            title,
            artist,
            mode="online",
            duration=duration,
        )
        api.push_now(title, artist, "online")
        api.push_summary()
        mpris.load_track(
            None,
            title,
            duration,
            artist=artist,
            album=album,
            art=thumbnail,
            has_next=_nav[0],
            has_prev=True,
        )
        mpris.set_position_getter(lambda: _player.get_time() if _player else 0)
        _attach_vlc_events()

        try:
            _display_loop(
                _player,
                title,
                args=args,
                artist=artist,
                album=album,
                duration=duration,
            )
        except KeyboardInterrupt:
            _player.stop()
            config.clear_pid()
            status.update(title, duration, playing=False, thumbnail=thumbnail)
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise
        finally:
            config.clear_pid()
            status.update(title, duration, playing=False, thumbnail=thumbnail)
            _restore_pause_input()
    finally:
        _restore_pause_input()
        _teardown()
        os.dup2(old_stderr, 2)
        os.close(old_stderr)
        os.close(devnull)


def play_entry(entry, title, args=None, flags=None, next_title=None, nav=None):
    global _player, _paused, _next_req, _prev_req, _stop_req, _nav
    _paused = False
    _next_req = False
    _prev_req = False
    _stop_req = False
    _nav = tuple(nav) if nav else (False, False)
    config.save_pid(os.getpid())
    config.clear_seek()
    title = title.split("|")[0]

    _teardown()
    instance = vlc.Instance("--no-video --quiet")
    _player = instance.media_player_new()

    stream_url = sponsor.stream_url(entry)
    if not stream_url or stream_url.startswith(
        ("https://www.youtube.com/watch", "https://youtu.be/")
    ):
        e("     No playable stream found for this video")
        _teardown()
        return
    media = instance.media_new(stream_url)

    _player.set_media(media)
    _player.play()
    _install_controls()
    _setup_pause_input()
    skip_thread = None
    try:
        duration = entry.get("duration", 0)
        video_id = entry.get("id")
        thumb = entry.get("thumbnail") or (
            library.thumbnail_url_for(video_id) if video_id else None
        )

        config.dev_print(
            "Player (YouTube Entry)",
            {
                "title": title,
                "video_id": video_id,
                "stream_url": stream_url,
                "duration": f"{duration}s | {duration / 60}min",
                "uploader": entry.get("uploader"),
                "webpage_url": entry.get("webpage_url"),
                "thumbnail": thumb,
            },
        )

        _now.update(title=title, duration=duration, thumbnail=thumb)
        status.update(title, duration, thumbnail=thumb)
        dur_min, dur_sec = divmod(int(duration), 60)
        fstr = _flags_str(args)
        artist = ""
        album = ""
        if video_id:
            lib_entry = library.get(video_id)
            if lib_entry:
                artist = lib_entry.get("artist") or ""
                album = lib_entry.get("album") or ""
        if not artist:
            artist = entry.get("artist") or ""
        if not album:
            album = entry.get("album") or ""
        if config.Display != "bars":
            i(f"\n[⥤ Now : {_truncate_title(title)}]")
            if artist:
                m(f"    {artist}")
            if album:
                m(f"    {album}")
            m(
                f"    [{dur_min}:{dur_sec:02d}]  {fstr}"
                if fstr
                else f"    [{dur_min}:{dur_sec:02d}]"
            )
        history.record_play(
            video_id or "", title, artist, mode="online", duration=duration
        )
        api.push_now(title, artist, "online")
        api.push_summary()
        art_path = ""
        if video_id:
            cached = library.thumbnail_path(video_id)
            if os.path.exists(cached):
                art_path = cached
        if not art_path:
            art_path = thumb
        mpris.load_track(
            video_id,
            title,
            duration,
            artist=artist,
            album=album,
            art=art_path,
            has_next=_nav[0],
            has_prev=True,
        )
        mpris.set_position_getter(lambda: _player.get_time() if _player else 0)
        _attach_vlc_events()

        skipped = False

        skip_segments = sponsor.segments(entry) if sponsor.enabled() else []
        if skip_segments:
            skip_thread = sponsor.VlcSkipThread(_player, skip_segments)
            skip_thread.start()

        def stop_check():
            nonlocal skipped
            if flags:
                if flags.get("quit", lambda: False)():
                    _player.stop()
                    return True
                if flags.get("skip", lambda: False)():
                    skipped = True
                    _player.stop()
                    return True
            return False

        try:
            _display_loop(
                _player,
                title,
                video_id=video_id,
                stop_check=stop_check,
                args=args,
                next_title=next_title,
                artist=artist,
                album=album,
                duration=duration,
            )
        except KeyboardInterrupt:
            _player.stop()
            config.clear_pid()
            status.update(title, duration, playing=False, thumbnail=thumb)
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise
    finally:
        if _stop_req or (next_title is None and not (_next_req or _prev_req)):
            config.clear_pid()
            status.update(title, duration, playing=False, thumbnail=thumb)
        if skip_thread:
            skip_thread.stop()
        _restore_pause_input()
        _teardown()
