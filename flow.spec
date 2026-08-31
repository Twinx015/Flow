# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['flow_twinx/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('flow_twinx/web/templates', 'flow_twinx/web/templates'),
        ('flow_twinx/Hyprland/island.qml', 'flow_twinx/Hyprland'),
        ('pyproject.toml', '.'),
    ],
    hiddenimports=[
        'vlc',
        'psutil',
        'PIL',
        'sounddevice',
        'ytmusicapi',
        'yt_dlp',
        'flask',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='flow',
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
