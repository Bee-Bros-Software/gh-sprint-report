# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the sprint-report CLI.

Build on the platform you intend to ship to — PyInstaller does not
cross-compile. See packaging/build.sh.
"""

block_cipher = None

a = Analysis(
    ["entry.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=[
        "sprint_report.cli",
        "sprint_report.deck",
        "sprint_report.workbook",
        "sprint_report.gh_source",
        "sprint_report.graph",
        "openpyxl.cell._writer",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="sprint-report",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
