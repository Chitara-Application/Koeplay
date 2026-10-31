"""音声デバイスの一覧取得・絞り込み・VB-CABLEの検出。

sounddevice(PortAudio)は、同じ物理デバイスを「ホストAPI」ごとに別々に列挙する
(MME / DirectSound / WASAPI / WDM-KS)。そのまま並べると重複だらけになるので、
1つのホストAPIに絞って表示する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sounddevice as sd

API_WASAPI = "Windows WASAPI"
API_MME = "MME"
API_DSOUND = "Windows DirectSound"
API_WDMKS = "Windows WDM-KS"
API_ORDER_AUTO = (API_WASAPI, API_MME, API_DSOUND)

# (保存値, 表示名)。WDM-KSは相性問題が多いので選択肢に出さない。
API_CHOICES = (
    ("auto", "自動(WASAPI優先)"),
    (API_WASAPI, "WASAPI"),
    (API_MME, "MME"),
    (API_DSOUND, "DirectSound"),
)

# VB-CABLE系のデバイス名。日本語Windowsでは再生側が
# 「スピーカー (VB-Audio Virtual Cable)」と表示されるため "VB-Audio" で判定する。
_VIRTUAL_CABLE = re.compile(r"vb-audio|vb-cable|cable (in|out)|virtual cable", re.I)
_CABLE_RECORDER = re.compile(r"cable output", re.I)
# 「マイクではない入力」の目印。
_NOT_MIC = re.compile(
    r"cable output|vb-audio|stereo mix|ステレオ ?ミキサー|sound mapper|"
    r"サウンド ?マッパー|プライマリ|primary sound|line input|ライン入力|"
    r"loopback|what u hear|wave out",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def names_match(a: str, b: str) -> bool:
    """デバイス名が同じか。MMEは名前が31文字で切れるため、前方一致も許す。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 12 and long_.startswith(short)


@dataclass(frozen=True)
class Device:
    index: int
    name: str
    api: str
    in_ch: int
    out_ch: int

    @property
    def is_cable(self) -> bool:
        return bool(_VIRTUAL_CABLE.search(self.name))

    @property
    def is_mic_like(self) -> bool:
        return self.in_ch > 0 and not _NOT_MIC.search(self.name)


@dataclass
class CableStatus:
    playback_found: bool = False
    recorder_found: bool = False
    playback_names: list[str] = field(default_factory=list)
    recorder_names: list[str] = field(default_factory=list)
    default_output_is_cable: bool = False

    @property
    def ok(self) -> bool:
        return self.playback_found and self.recorder_found


class DeviceCatalog:
    def __init__(self) -> None:
        self.devices: list[Device] = []
        self._default_in: dict[str, int] = {}
        self._default_out: dict[str, int] = {}
        self.error = ""
        self.refresh()

    # ---- 取得 -------------------------------------------------------
    def refresh(self, reinit: bool = False) -> None:
        """デバイス一覧を取り直す。

        reinit=True はPortAudioを初期化し直す(デバイスの抜き差しやVB-CABLEの
        導入直後に反映させるため)。開いているストリームがある時は呼ばないこと。
        """
        self.error = ""
        if reinit:
            try:
                sd._terminate()
                sd._initialize()
            except Exception as exc:  # noqa: BLE001
                self.error = f"PortAudioの再初期化に失敗: {exc}"
        try:
            apis = sd.query_hostapis()
            raw = sd.query_devices()
        except Exception as exc:  # noqa: BLE001
            self.error = f"デバイス取得に失敗: {exc}"
            self.devices = []
            return

        api_names = {i: str(a["name"]) for i, a in enumerate(apis)}
        self._default_in = {
            str(a["name"]): int(a.get("default_input_device", -1)) for a in apis
        }
        self._default_out = {
            str(a["name"]): int(a.get("default_output_device", -1)) for a in apis
        }
        devices: list[Device] = []
        for index, info in enumerate(raw):
            devices.append(
                Device(
                    index=index,
                    name=str(info["name"]),
                    api=api_names.get(int(info["hostapi"]), "?"),
                    in_ch=int(info["max_input_channels"]),
                    out_ch=int(info["max_output_channels"]),
                )
            )
        self.devices = devices

    def available_apis(self) -> list[str]:
        seen: list[str] = []
        for device in self.devices:
            if device.api not in seen:
                seen.append(device.api)
        return seen

    def api_order(self, preference: str) -> list[str]:
        """試すホストAPIの順番。"""
        available = self.available_apis()
        if preference in ("", "auto"):
            order = [a for a in API_ORDER_AUTO if a in available]
        else:
            order = [preference] if preference in available else []
        if not order:
            order = [a for a in available if a != API_WDMKS][:1]
        return order

    def display_api(self, preference: str) -> str:
        order = self.api_order(preference)
        return order[0] if order else ""

    # ---- 一覧(設定画面用) -------------------------------------------
    def inputs(self, api: str, show_all: bool = False) -> list[Device]:
        result = [d for d in self.devices if d.api == api and d.in_ch > 0]
        if not show_all:
            result = [d for d in result if d.is_mic_like]
        return result

    def outputs(self, api: str) -> list[Device]:
        return [d for d in self.devices if d.api == api and d.out_ch > 0]

    def cable_outputs(self, api: str) -> list[Device]:
        found = [d for d in self.outputs(api) if d.is_cable]
        # 通常のステレオ用(CABLE Input)を先、16ch版を後にする。
        found.sort(key=lambda d: ("16 ch" in d.name.lower(), d.index))
        return found

    def monitor_outputs(self, api: str) -> list[Device]:
        return [d for d in self.outputs(api) if not d.is_cable]

    # ---- 名前から探す -----------------------------------------------
    def find(self, api: str, name: str, kind: str) -> Device | None:
        pool = [
            d for d in self.devices
            if d.api == api and (d.in_ch > 0 if kind == "in" else d.out_ch > 0)
        ]
        for device in pool:
            if _norm(device.name) == _norm(name):
                return device
        for device in pool:
            if names_match(device.name, name):
                return device
        return None

    def _default(self, api: str, kind: str) -> Device | None:
        table = self._default_in if kind == "in" else self._default_out
        index = table.get(api, -1)
        for device in self.devices:
            if device.index == index:
                return device
        return None

    # ---- エンジンが使う「解決」関数 ----------------------------------
    def resolve_input(self, api: str, name: str) -> tuple[Device | None, str]:
        note = ""
        if name:
            found = self.find(api, name, "in")
            if found:
                return found, ""
            note = f"マイク「{name}」が見つからないため、別のマイクを使います。"
        default = self._default(api, "in")
        if default and default.is_mic_like:
            return default, note
        for device in self.inputs(api):
            return device, note
        return None, note

    def resolve_cable_output(self, api: str, name: str) -> tuple[Device | None, str]:
        note = ""
        if name:
            found = self.find(api, name, "out")
            if found:
                return found, ""
            note = f"出力「{name}」が見つからないため、VB-CABLEを自動で選びます。"
        for device in self.cable_outputs(api):
            return device, note
        return None, note

    def resolve_monitor(self, api: str, name: str) -> tuple[Device | None, str]:
        """モニター(自分用)の出力先。VB-CABLEは選ばない(音が二重に流れるため)。"""
        if name:
            found = self.find(api, name, "out")
            if found and not found.is_cable:
                return found, ""
            reason = (
                "モニターにはVB-CABLEを使えないため、Windowsの既定の出力を使います。"
                if found else
                f"モニター出力「{name}」が見つからないため、Windowsの既定の出力を使います。"
            )
        else:
            reason = ""
        default = self._default(api, "out")
        if default and not default.is_cable:
            return default, reason
        candidates = self.monitor_outputs(api)
        candidates.sort(key=lambda d: ("virtual" in d.name.lower(), d.index))
        for device in candidates:
            if default and default.is_cable:
                reason = "Windowsの既定の出力がVB-CABLEになっているため、別の出力を使います。"
            return device, reason
        return None, "モニターに使える出力デバイスがありません。"

    # ---- VB-CABLEの検出 ---------------------------------------------
    def cable_status(self) -> CableStatus:
        status = CableStatus()

        def add(names: list[str], name: str) -> None:
            # MMEは名前が途中で切れるので、同じ物は1つにまとめる(長い方を残す)。
            for i, old in enumerate(names):
                if names_match(old, name):
                    if len(name) > len(old):
                        names[i] = name
                    return
            names.append(name)

        for device in self.devices:
            if device.out_ch > 0 and device.is_cable:
                add(status.playback_names, device.name)
            if device.in_ch > 0 and _CABLE_RECORDER.search(device.name):
                add(status.recorder_names, device.name)
        status.playback_found = bool(status.playback_names)
        status.recorder_found = bool(status.recorder_names)
        for api in self.available_apis():
            default = self._default(api, "out")
            if default and default.is_cable:
                status.default_output_is_cable = True
                break
        return status
