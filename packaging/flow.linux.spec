# -*- mode: python ; coding: utf-8 -*-
# Linux onefile build: `pyinstaller packaging/flow.linux.spec`

import os

_SPEC_DIR = os.path.dirname(os.path.abspath(SPECPATH))
_ROOT = os.path.dirname(_SPEC_DIR) if os.path.basename(_SPEC_DIR) == "packaging" else _SPEC_DIR

a = Analysis(
    [os.path.join(_ROOT, "cli/main.py")],
    pathex=[_ROOT],
    binaries=[],
    datas=[
        (os.path.join(_ROOT, "web/templates"), "web/templates"),
        (os.path.join(_ROOT, "backend/plugin_api/flow_api.py"), "backend/plugin_api"),
        (os.path.join(_ROOT, "pyproject.toml"), "."),
    ],
    hiddenimports=[
        "vlc",
        "psutil",
        "sounddevice",
        "ytmusicapi",
        "yt_dlp",
        "flask",
        "cli",
        "cli.tui",
        "backend",
        "backend.Online",
        "backend.Online.commands",
        "backend.Online.player",
        "backend.Online.youtube",
        "backend.Online.savan",
        "backend.Offline",
        "backend.Offline.commands",
        "backend.Offline.player",
        "backend.Offline.file",
        "web",
        "web.app",
        "web.devlog",
        "dbus",
        "dbus.mainloop",
        "dbus.mainloop.glib",
        "dbus.service",
        "gi",
        "gi.repository",
        "gi.repository.GLib",
        "dbus_fast",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

# python-vlc loads libvlc with ctypes and needs the *system* libvlc plus its
# plugin directory. PyInstaller picks libvlc.so.5/libvlccore.so.9 up from the
# ctypes.CDLL() literals in vlc.py, and inside the onefile bundle they are
# loaded from _MEIPASS -- so libvlccore searches for its plugins next to itself
# instead of /usr/lib/vlc/plugins, finds none, and libvlc_new() returns NULL
# (Instance() becomes None -> "'NoneType' object has no attribute
# 'media_player_new'"). Drop the bundled copies and let ctypes resolve the
# system library through ldconfig.
_VLC_BUNDLED = {"libvlc.so.5", "libvlccore.so.9"}
_dropped = [b for b in a.binaries if os.path.basename(b[0]) not in _VLC_BUNDLED]
if len(_dropped) != len(a.binaries):
    print("[flow.linux.spec] dropping bundled VLC libs: libvlc/libvlccore must come from the system")
a.binaries = _dropped

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="flow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
