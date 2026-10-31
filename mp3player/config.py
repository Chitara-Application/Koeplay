"""アプリ全体で使う定数。"""
from __future__ import annotations

import os
from pathlib import Path

APP_TITLE = "Koeplay"
APP_VERSION = "1.0"
APP_ID = "Koeplay"             # 設定フォルダー名
LEGACY_APP_ID = "MP3Player"    # 旧版(MP3 Player + Mic Mixer)の設定フォルダー名

# 設定の保存先。インストール先ではなくユーザーのAppDataに置く。
APPDATA_DIR = Path(
    os.environ.get("APPDATA") or (Path.home() / ".config")
) / APP_ID
SETTINGS_PATH = APPDATA_DIR / "settings.json"
# 旧版の設定。Koeplayの設定がまだ無い時だけ、ここから引き継ぐ。
LEGACY_SETTINGS_PATH = (
    Path(os.environ.get("APPDATA") or (Path.home() / ".config"))
    / LEGACY_APP_ID / "settings.json"
)
LOG_PATH = APPDATA_DIR / "error.log"

# FFmpeg(PyAV)が読める代表的な音声拡張子。フォルダー一覧に表示する対象。
# 一覧に無い拡張子でも「ファイルを開く」から「すべてのファイル」で試せる。
AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".ogg", ".oga", ".opus", ".flac", ".m4a", ".aac",
    ".wma", ".aiff", ".aif", ".aifc", ".ape", ".wv", ".mka", ".mp2",
    ".mpc", ".amr", ".ac3", ".eac3", ".dts", ".tta", ".caf", ".m4b",
    ".webm", ".3gp", ".au", ".snd", ".spx", ".tak",
)

VB_CABLE_URL = "https://vb-audio.com/Cable/"
SOUND_SETTINGS_URL = "ms-settings:sound"
