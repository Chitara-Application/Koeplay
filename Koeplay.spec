# -*- mode: python ; coding: utf-8 -*-
# ビルド: python -m PyInstaller --noconfirm --clean Koeplay.spec
# 出力  : dist\Koeplay\Koeplay.exe (フォルダー形式)
#
# フォルダー形式(onedir)にしている理由:
#   PySide6とFFmpeg(PyAV)は合計が大きく、1ファイル形式だと起動のたびに展開されて
#   遅くなる。また、ウイルス対策ソフトの誤検知も起きにくい。

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# PyAV(FFmpegのDLL)とsounddevice(PortAudioのDLL)は、DLLごとまとめて取り込む。
for package in ("av", "sounddevice", "_sounddevice_data"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pygame"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Koeplay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPXはQtのDLLを壊すことがあるので使わない
    console=False,      # 黒い窓を出さない
    disable_windowed_traceback=False,
    icon="assets/icon.ico",   # EXEのアイコン(作り直す時は tools/make_icon.py)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Koeplay",
)
