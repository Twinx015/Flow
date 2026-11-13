"""A finished track must end the display loop, not leave the player alive.

VLC can report `Stopped` instead of `Ended` when the audio output finishes a
track. The loop only knew about `Ended`/`Error`, so `flow-min play-off` stayed
in the background forever, kept `~/.flow/status.json` at the old track, and
held the `org.mpris.MediaPlayer2.flow` bus name after the song was over.

The background child is forked, and importing PortAudio (via `sounddevice`)
in the parent first made VLC hang at end-of-stream in that child: state stayed
`Playing`, position 0, forever. `visualizer` therefore loads `sounddevice`
lazily, only when bars are actually drawn.
"""

import os
import pathlib
import subprocess
import sys

import pytest

from backend import config
from backend.Offline import player as offline
from backend.Online import player as online

MODULES = [offline, online]
ROOT = pathlib.Path(__file__).resolve().parents[1]


class _FakePlayer:
    def __init__(self, state):
        self._state = state

    def get_state(self):
        return self._state

    def get_time(self):
        return 0


class _NoSleep:
    """`time` replacement that fails if the loop keeps waiting."""

    def __init__(self):
        self.sleeps = 0

    def sleep(self, _seconds):
        self.sleeps += 1
        raise AssertionError("display loop kept running on a terminal VLC state")

    def time(self):
        return 0.0


@pytest.mark.parametrize("module", MODULES, ids=["offline", "online"])
@pytest.mark.parametrize("state_name", ["Ended", "Error", "Stopped"])
def test_display_loop_exits_on_terminal_vlc_state(module, state_name, monkeypatch):
    monkeypatch.setattr(config, "Display", "none")
    module._paused = False
    module._next_req = False
    module._prev_req = False
    module._stop_req = False

    fake_time = _NoSleep()
    monkeypatch.setattr(module, "time", fake_time)
    state = getattr(module.vlc.State, state_name)

    module._display_loop(_FakePlayer(state), "Finished Track")

    assert fake_time.sleeps == 0


def test_player_import_does_not_load_portaudio():
    """The pre-fork import path must stay clean for VLC in the child."""
    code = (
        "import sys;"
        "import backend.Offline.player, backend.Online.player;"
        "print('sounddevice' in sys.modules)"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"

