"""オーディオエンジン。

  マイク ─┐
          ├─ ミックス ─ リミッター ─→ VB-CABLE(Discordへ)
  音声ファイル ┘                  └→ モニター出力(自分のヘッドホン/スピーカー、任意)

3本のストリーム(マイク入力 / CABLE出力 / モニター出力)は別々のクロックで動くため、
リングバッファで受け渡す。コールバック内ではTkinter/Qtを絶対に触らない。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd

from .devices import API_WASAPI, DeviceCatalog
from .ring import Ring
from .source import AudioSource

# (PortAudioへの希望遅延, マイクバッファの目標ミリ秒)
LATENCY_PRESETS: dict[str, tuple[object, int]] = {
    "low": ("low", 20),
    "normal": (0.06, 40),
    "safe": ("high", 80),
}
RATE_CANDIDATES = (48000, 44100)


class EngineError(Exception):
    pass


@dataclass
class EngineConfig:
    host_api: str = "auto"
    mic_name: str = ""
    out_name: str = ""
    monitor_name: str = ""
    sample_rate: str = "auto"
    latency: str = "normal"
    monitor_enabled: bool = True


@dataclass
class EngineSnapshot:
    running: bool
    healthy: bool
    playing: bool
    paused: bool
    position: float
    duration: float
    mic_peak: float
    out_peak: float
    finished: bool
    underruns: int
    error: str


def soft_limit(x: np.ndarray, threshold: float = 0.85) -> np.ndarray:
    """しきい値を超えた分だけをなめらかに丸める(ハードクリップより歪みが目立たない)。"""
    ax = np.abs(x)
    over = ax > threshold
    if not over.any():
        return x
    y = x.copy()
    span = 1.0 - threshold
    y[over] = np.sign(x[over]) * (
        threshold + span * np.tanh((ax[over] - threshold) / span)
    )
    return y


def _ramp(prev: float, cur: float, frames: int):
    """音量が変わった時、ブロック内でなめらかに変化させる(プチッという音を防ぐ)。"""
    if prev == cur:
        return cur
    return np.linspace(prev, cur, frames, endpoint=False, dtype=np.float32)[:, None]


class AudioEngine:
    def __init__(self, catalog: DeviceCatalog) -> None:
        self.catalog = catalog

        # ミキサーの状態(UIスレッドが書き、コールバックが読む)
        self.mp3_volume = 0.8
        self.mic_volume = 1.0
        self.monitor_volume = 0.8
        self.mic_enabled = True
        self.monitor_enabled = True
        self.monitor_mic = False
        self.limiter = True

        # ストリーム
        self._in_stream: sd.InputStream | None = None
        self._out_stream: sd.OutputStream | None = None
        self._mon_stream: sd.OutputStream | None = None
        self.running = False
        self.rate = 48000
        self.api = ""
        self.mic_device_name = ""
        self.out_device_name = ""
        self.monitor_label = "モニター: オフ"
        self.config = EngineConfig()
        self._latency = LATENCY_PRESETS["normal"]

        self._mic_ring = Ring(1, self.rate * 2)
        self._mon_ring = Ring(2, self.rate * 2)
        self._mic_target = 2048
        self._mon_active = False

        # 再生
        self._source: AudioSource | None = None
        self._playing = False
        self._paused = False
        self._finished = False

        # メーター・統計
        self._mic_peak = 0.0
        self._out_peak = 0.0
        self.underruns = 0
        self.last_callback_error = ""

        self._prev_mp3 = self.mp3_volume
        self._prev_mic = self.mic_volume
        self._prev_mon = self.monitor_volume
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # ストリームの開始・停止
    # ------------------------------------------------------------------
    @staticmethod
    def _extra(api: str):
        # WASAPI共有モードでは、サンプルレート不一致を自動変換させる。
        if api == API_WASAPI:
            try:
                return sd.WasapiSettings(auto_convert=True)
            except Exception:  # noqa: BLE001
                return None
        return None

    def start(self, cfg: EngineConfig) -> list[str]:
        """ストリームを開く。成功時は注意事項(警告)のリストを返す。失敗時は例外。"""
        self.shutdown()
        self.config = cfg
        self._latency = LATENCY_PRESETS.get(cfg.latency, LATENCY_PRESETS["normal"])
        self.monitor_enabled = cfg.monitor_enabled

        if cfg.sample_rate in ("48000", "44100"):
            rates = (int(cfg.sample_rate),)
        else:
            rates = RATE_CANDIDATES

        errors: list[str] = []
        apis = self.catalog.api_order(cfg.host_api)
        if not apis:
            raise EngineError("使える音声デバイスのAPIが見つかりません。")

        for api in apis:
            for rate in rates:
                notes: list[str] = []
                try:
                    self._open(api, rate, cfg, notes)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{api} / {rate}Hz: {exc}")
                    self._close_streams()
                    continue
                self.running = True
                return notes

        detail = "\n".join(errors[:4]) if errors else "原因不明"
        raise EngineError(
            "音声デバイスを開けませんでした。\n\n" + detail
        )

    def _open(self, api: str, rate: int, cfg: EngineConfig, notes: list[str]) -> None:
        mic, note_in = self.catalog.resolve_input(api, cfg.mic_name)
        out, note_out = self.catalog.resolve_cable_output(api, cfg.out_name)
        for note in (note_in, note_out):
            if note:
                notes.append(note)
        if mic is None:
            raise RuntimeError("マイク(入力デバイス)が見つかりません。")
        if out is None:
            raise RuntimeError(
                "VB-CABLEの出力デバイスが見つかりません。"
                "VB-CABLEを導入し、再起動してください。"
            )

        suggested, target_ms = self._latency
        self.rate = rate
        self.api = api
        self._mic_target = max(int(rate * target_ms / 1000), 256)
        self._mic_ring = Ring(1, rate * 2)
        self._mon_ring = Ring(2, rate * 2)
        self._reopen_source(rate)

        in_ch = 1 if mic.in_ch <= 1 else 2
        self._in_stream = sd.InputStream(
            device=mic.index, channels=in_ch, samplerate=rate, dtype="float32",
            latency=suggested, callback=self._in_cb,
            extra_settings=self._extra(api),
        )
        self._out_stream = sd.OutputStream(
            device=out.index, channels=2, samplerate=rate, dtype="float32",
            latency=suggested, callback=self._out_cb,
            extra_settings=self._extra(api),
        )
        self._out_stream.start()
        self._in_stream.start()
        self.mic_device_name = mic.name
        self.out_device_name = out.name

        if self.monitor_enabled:
            self._open_monitor(notes)
        else:
            self.monitor_label = "モニター: オフ"

    def _open_monitor(self, notes: list[str] | None = None) -> bool:
        """モニター用のストリームを開く。失敗してもミキサー本体は止めない。"""
        if self._mon_stream is not None:
            return True
        device, note = self.catalog.resolve_monitor(
            self.api, self.config.monitor_name
        )
        if note and notes is not None:
            notes.append(note)
        if device is None:
            self.monitor_label = f"モニター: 使えません({note})"
            return False
        suggested, _ = self._latency
        try:
            stream = sd.OutputStream(
                device=device.index, channels=2, samplerate=self.rate,
                dtype="float32", latency=suggested, callback=self._mon_cb,
                extra_settings=self._extra(self.api),
            )
            self._mon_ring.clear()
            self._mon_stream = stream
            stream.start()
        except Exception as exc:  # noqa: BLE001
            self._mon_stream = None
            self._mon_active = False
            self.monitor_label = f"モニター: 開けません({exc})"
            if notes is not None:
                notes.append(f"モニター出力を開けませんでした: {exc}")
            return False
        self._mon_active = True
        self.monitor_label = f"モニター先: {device.name}"
        return True

    def _close_monitor(self) -> None:
        self._mon_active = False
        stream, self._mon_stream = self._mon_stream, None
        self._close_one(stream)
        self._mon_ring.clear()
        self.monitor_label = "モニター: オフ"

    @staticmethod
    def _close_one(stream) -> None:
        if stream is None:
            return
        try:
            stream.abort()
        except Exception:  # noqa: BLE001
            pass
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    def _close_streams(self) -> None:
        self._mon_active = False
        for attr in ("_in_stream", "_out_stream", "_mon_stream"):
            stream = getattr(self, attr)
            setattr(self, attr, None)
            self._close_one(stream)
        self._mic_ring.clear()
        self._mon_ring.clear()

    def shutdown(self) -> None:
        """ストリームを閉じる(再生中の曲は一時停止にする)。"""
        if self._playing:
            self._paused = True
        self._close_streams()
        self.running = False
        self.monitor_label = "モニター: オフ"

    def healthy(self) -> bool:
        if not self.running:
            return True
        try:
            streams = [self._in_stream, self._out_stream]
            if self._mon_stream is not None:
                streams.append(self._mon_stream)
            return all(s is not None and s.active for s in streams)
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # 設定値
    # ------------------------------------------------------------------
    def set_monitor_enabled(self, enabled: bool) -> bool:
        """モニターのON/OFF。ONにできなかった時はFalseを返す。"""
        self.monitor_enabled = bool(enabled)
        if not self.running:
            return True
        if enabled:
            return self._open_monitor()
        self._close_monitor()
        return True

    # ------------------------------------------------------------------
    # 再生制御
    # ------------------------------------------------------------------
    def _reopen_source(self, rate: int) -> None:
        """サンプルレートが変わった時、今の位置から読み直す。"""
        src = self._source
        if src is None or src.rate == rate:
            return
        path, pos = src.path, src.position()
        try:
            new = AudioSource(path, rate, start=pos)
        except Exception:  # noqa: BLE001
            self._source = None
            self._playing = False
            return
        self._source = new
        src.close()

    @property
    def source(self) -> AudioSource | None:
        return self._source

    def load(self, path: Path | str) -> AudioSource:
        """ファイルを読み込む(再生はしない)。失敗時は例外。"""
        new = AudioSource(path, self.rate, start=0.0)
        old, self._source = self._source, new
        self._playing = False
        self._paused = False
        self._finished = False
        if old is not None:
            old.close()
        return new

    def play(self) -> None:
        src = self._source
        if src is None:
            return
        if self._finished or (not self._playing and src.position() >= src.duration > 0):
            src.seek(0.0)
        self._finished = False
        self._paused = False
        self._playing = True

    def pause(self) -> None:
        if self._playing:
            self._paused = True

    def stop_playback(self) -> None:
        self._playing = False
        self._paused = False
        self._finished = False
        if self._source is not None:
            self._source.seek(0.0)

    def seek(self, seconds: float) -> None:
        if self._source is not None:
            self._source.seek(seconds)
            self._finished = False

    def unload(self) -> None:
        old, self._source = self._source, None
        self._playing = False
        self._paused = False
        if old is not None:
            old.close()

    # ------------------------------------------------------------------
    # UIが定期的に呼ぶ(メーターは読み出すとリセットされる)
    # ------------------------------------------------------------------
    def poll(self, reset: bool = True) -> EngineSnapshot:
        """現在の状態を返す。reset=Trueの時だけ、メーターと「曲の終了」フラグを消費する。

        画面の定期更新だけがreset=Trueで呼ぶ。それ以外(ボタン操作中の状態確認など)は
        reset=Falseにして、曲の終了通知を取りこぼさないようにする。
        """
        src = self._source
        mic_peak = self._mic_peak * (self.mic_volume if self.mic_enabled else 0.0)
        out_peak = self._out_peak
        finished = self._finished
        if reset:
            self._mic_peak = 0.0
            self._out_peak = 0.0
            self._finished = False
        return EngineSnapshot(
            running=self.running,
            healthy=self.healthy(),
            playing=self._playing,
            paused=self._paused,
            position=src.position() if src else 0.0,
            duration=src.duration if src else 0.0,
            mic_peak=mic_peak,
            out_peak=out_peak,
            finished=finished,
            underruns=self.underruns,
            error=(src.error if src else "") or self.last_callback_error,
        )

    # ------------------------------------------------------------------
    # オーディオコールバック(PortAudioのスレッドで動く)
    # ------------------------------------------------------------------
    def _in_cb(self, indata, frames, time_info, status) -> None:
        try:
            if indata.shape[1] == 1:
                mono = indata[:, 0:1]
            else:
                mono = indata.mean(axis=1, keepdims=True)
            peak = float(np.max(np.abs(mono))) if frames else 0.0
            if peak > self._mic_peak:
                self._mic_peak = peak
            self._mic_ring.write(mono, self._mic_target * 4)
        except Exception as exc:  # noqa: BLE001
            self.last_callback_error = f"入力: {exc}"

    def _out_cb(self, outdata, frames, time_info, status) -> None:
        try:
            if status:
                self.underruns += 1

            mp3 = None
            src = self._source
            if src is not None and self._playing and not self._paused:
                mp3, _got, finished = src.read(frames)
                if finished:
                    self._playing = False
                    self._finished = True

            mic, _ = self._mic_ring.read(frames, self._mic_target)

            g_mp3 = self.mp3_volume
            g_mic = self.mic_volume if self.mic_enabled else 0.0
            mix = np.zeros((frames, 2), dtype=np.float32)
            if mp3 is not None:
                mix += mp3 * _ramp(self._prev_mp3, g_mp3, frames)
            if g_mic > 0.0 or self._prev_mic > 0.0:
                mix += mic * _ramp(self._prev_mic, g_mic, frames)
            self._prev_mp3 = g_mp3
            self._prev_mic = g_mic

            # モニター(自分用)へ分岐。CABLEへ送る音量とは独立。
            if self._mon_active:
                g_mon = self.monitor_volume
                mon = None
                if mp3 is not None:
                    mon = mp3 * _ramp(self._prev_mon, g_mon, frames)
                if self.monitor_mic:
                    side = mic * _ramp(self._prev_mon, g_mon, frames)
                    mon = side if mon is None else mon + side
                self._prev_mon = g_mon
                if mon is not None:
                    if mon.shape[1] == 1:
                        mon = np.repeat(mon, 2, axis=1)
                    self._mon_ring.write(
                        soft_limit(mon), self._mic_target * 4
                    )

            mix = soft_limit(mix) if self.limiter else np.clip(mix, -1.0, 1.0)
            peak = float(np.max(np.abs(mix))) if frames else 0.0
            if peak > self._out_peak:
                self._out_peak = peak
            outdata[:] = mix
        except Exception as exc:  # noqa: BLE001
            outdata.fill(0)
            self.last_callback_error = f"出力: {exc}"

    def _mon_cb(self, outdata, frames, time_info, status) -> None:
        try:
            data, _ = self._mon_ring.read(frames, self._mic_target)
            if outdata.shape[1] == 2:
                outdata[:] = data
            else:
                outdata.fill(0)
                outdata[:, 0] = data.mean(axis=1)
        except Exception as exc:  # noqa: BLE001
            outdata.fill(0)
            self.last_callback_error = f"モニター: {exc}"
