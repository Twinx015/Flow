# -*- mode: python ; coding: utf-8 -*-
# Windows onefile build: `pyinstaller packaging/flow.windows.spec`
#
# VLC is an external install on Windows (the portable zip or an installer).
# python-vlc resolves libvlc.dll at import time; `flow` calls
# backend.platform.bootstrap_vlc() before importing vlc, which honours
# PYTHON_VLC_LIB_PATH and exports VLC_PLUGIN_PATH, falling back to common
# install locations. The onefile must NOT bundle libvlc.

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
        "PIL",
        "PIL.Image",
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
        "dbus_fast",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

# If PyInstaller ever picks libvlc.dll up (it is only referenced via
# ctypes at runtime, so normally it will not), drop it so the runtime
# bootstrap keeps working against the external VLC install.
_VLC_BUNDLED = {"libvlc.dll", "libvlccore.dll"}
_dropped = [b for b in a.binaries if os.path.basename(b[0]) not in _VLC_BUNDLED]
if len(_dropped) != len(a.binaries):
    print("[flow.windows.spec] dropping bundled VLC libs: libvlc must come from the VLC install")
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