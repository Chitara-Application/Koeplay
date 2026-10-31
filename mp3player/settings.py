"""設定ファイル(settings.json)の読み書き。

- 旧バージョン(Tkinter版)の settings.json を読んでも壊れないよう、
  足りない項目は初期値で補い、型や範囲がおかしい値は初期値に戻す。
- 保存は一時ファイル経由で行い、書き込み途中の破損を防ぐ。
"""
from __future__ import annotations

import json
from typing import Any

from .config import APPDATA_DIR, LEGACY_SETTINGS_PATH, SETTINGS_PATH

SETTINGS_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    # 再生
    "folder": "",
    "last_file": "",
    "repeat": "off",          # off / all / one
    "shuffle": False,
    "auto_next": True,
    # 音声デバイス
    "host_api": "auto",       # auto / Windows WASAPI / MME / Windows DirectSound
    "input_device_name": "",  # 空 = 既定のマイク
    "output_device_name": "", # 空 = 自動(VB-CABLE)
    "monitor_device_name": "",# 空 = Windowsの既定の出力
    "show_all_inputs": False, # False = マイクだけ表示
    "sample_rate": "auto",    # auto / 48000 / 44100
    "latency": "normal",      # low / normal / safe
    # ミキサー
    "mp3_volume": 80.0,
    "mic_volume": 100.0,
    "monitor_volume": 80.0,
    "mic_enabled": True,
    "monitor_enabled": True,
    "monitor_mic": False,
    "limiter": True,
    "autostart_mixer": True,
    # 一般
    "close_to_tray": True,
    "start_minimized": False,
    "window_geometry": "",
}

_ENUMS: dict[str, tuple[str, ...]] = {
    "repeat": ("off", "all", "one"),
    "sample_rate": ("auto", "48000", "44100"),
    "latency": ("low", "normal", "safe"),
}
_VOLUME_KEYS = ("mp3_volume", "mic_volume", "monitor_volume")


def _coerce(key: str, value: Any) -> Any:
    """値を項目の型に合わせる。変換できなければ初期値を返す。"""
    default = DEFAULTS[key]
    try:
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, float):
            number = float(value)
            if key in _VOLUME_KEYS:
                number = max(0.0, min(150.0, number))
            return number
        if isinstance(default, int):
            return int(value)
        text = str(value) if value is not None else ""
        if key in _ENUMS and text not in _ENUMS[key]:
            return default
        return text
    except (TypeError, ValueError):
        return default


class Settings:
    def __init__(self) -> None:
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        # Koeplayの設定が無ければ、旧版(MP3Player)の設定を読む。
        source = SETTINGS_PATH if SETTINGS_PATH.exists() else LEGACY_SETTINGS_PATH
        try:
            if not source.exists():
                return
            with source.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        for key in DEFAULTS:
            if key in raw and key != "version":
                self.data[key] = _coerce(key, raw[key])

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in DEFAULTS:
            self.data[key] = _coerce(key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self[key] = value

    def save(self) -> bool:
        try:
            APPDATA_DIR.mkdir(parents=True, exist_ok=True)
            temp = SETTINGS_PATH.with_suffix(".tmp")
            payload = dict(self.data)
            payload["version"] = SETTINGS_VERSION
            with temp.open("w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            temp.replace(SETTINGS_PATH)
            return True
        except OSError:
            return False
