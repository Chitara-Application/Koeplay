"""音声ファイルのデコーダー(PyAV = FFmpeg)。

どんな形式でも、エンジンのサンプルレートのステレオfloat32に変換して流し込む。
全部をメモリに展開せず、別スレッドで少しずつデコードして先読みするので、
長い音声(1時間のポッドキャストなど)でもメモリを食わない。
"""
from __future__ import annotations

import threading
from pathlib import Path

import av
import numpy as np


class AudioSource:
    def __init__(self, path: Path | str, rate: int, start: float = 0.0) -> None:
        self.path = Path(path)
        self.rate = int(rate)

        self._container = av.open(str(self.path))
        streams = self._container.streams.audio
        if not streams:
            self._container.close()
            raise ValueError("音声トラックが見つかりません。")
        self._stream = streams[0]

        self.duration = self._probe_duration()
        meta = {
            str(k).lower(): str(v)
            for k, v in (self._container.metadata or {}).items()
        }
        self.title = meta.get("title", "")
        self.artist = meta.get("artist", "")
        codec = getattr(self._stream.codec_context, "name", "") or ""
        self.codec = codec.upper()
        self.error = ""
        # モノラル音源はステレオ化すると-3dB小さくなるので、その分を持ち上げる。
        try:
            mono = int(self._stream.codec_context.channels) == 1
        except Exception:  # noqa: BLE001
            mono = False
        self._gain = float(np.sqrt(2.0)) if mono else 1.0

        # 先読み用のリングバッファ(約6秒分)。
        self._cap = self.rate * 6
        self._buf = np.zeros((self._cap, 2), dtype=np.float32)
        self._rpos = 0
        self._count = 0
        self._consumed = 0          # 再生側が読み出したフレーム数
        self._base = float(start)   # 読み出し開始位置(秒)
        self._eof = False
        self._stop = False
        self._gen = 0               # シークのたびに増やし、古いデータを捨てる
        self._seek_target: float | None = float(start)
        self._cond = threading.Condition(threading.Lock())

        self._thread = threading.Thread(
            target=self._run, name="decoder", daemon=True
        )
        self._thread.start()

    # ---- 情報 -------------------------------------------------------
    def _probe_duration(self) -> float:
        try:
            if self._container.duration:
                return float(self._container.duration) / av.time_base
            if self._stream.duration and self._stream.time_base:
                return float(self._stream.duration * self._stream.time_base)
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def position(self) -> float:
        with self._cond:
            return self._base + self._consumed / self.rate

    # ---- 再生側(オーディオコールバック)から使う --------------------
    def read(self, frames: int) -> tuple[np.ndarray, int, bool]:
        """(frames, 2)の配列、読めたフレーム数、終端に達したか を返す。"""
        out = np.zeros((frames, 2), dtype=np.float32)
        with self._cond:
            k = min(frames, self._count)
            if k > 0:
                r = self._rpos
                first = min(k, self._cap - r)
                out[:first] = self._buf[r:r + first]
                if k > first:
                    out[first:k] = self._buf[:k - first]
                self._rpos = (r + k) % self._cap
                self._count -= k
                self._consumed += k
                self._cond.notify()
            finished = self._eof and self._count == 0
        return out, k, finished

    def seek(self, seconds: float) -> None:
        seconds = max(0.0, float(seconds))
        if self.duration > 0:
            seconds = min(seconds, max(0.0, self.duration - 0.05))
        with self._cond:
            self._gen += 1
            self._seek_target = seconds
            self._rpos = 0
            self._count = 0
            self._consumed = 0
            self._base = seconds
            self._eof = False
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        self._thread.join(timeout=2.0)
        try:
            self._container.close()
        except Exception:  # noqa: BLE001
            pass

    # ---- デコードスレッド -------------------------------------------
    def _new_resampler(self) -> av.AudioResampler:
        return av.AudioResampler(format="flt", layout="stereo", rate=self.rate)

    def _convert(self, resampler: av.AudioResampler, frame) -> list[np.ndarray]:
        arrays: list[np.ndarray] = []
        try:
            result = resampler.resample(frame)
        except Exception:  # noqa: BLE001
            return arrays
        if result is None:
            return arrays
        if not isinstance(result, (list, tuple)):
            result = [result]
        for item in result:
            data = item.to_ndarray()
            block = np.ascontiguousarray(data, dtype=np.float32).reshape(-1, 2)
            if self._gain != 1.0:
                block *= self._gain
            arrays.append(block)
        return arrays

    def _push(self, data: np.ndarray, gen: int) -> bool:
        pos = 0
        total = len(data)
        with self._cond:
            while pos < total:
                if self._stop or self._gen != gen:
                    return False
                free = self._cap - self._count
                if free <= 0:
                    self._cond.wait(0.05)
                    continue
                k = min(free, total - pos)
                w = (self._rpos + self._count) % self._cap
                first = min(k, self._cap - w)
                self._buf[w:w + first] = data[pos:pos + first]
                if k > first:
                    self._buf[:k - first] = data[pos + first:pos + k]
                self._count += k
                pos += k
        return True

    def _mark_eof(self, gen: int) -> None:
        with self._cond:
            if self._gen == gen:
                self._eof = True

    def _run(self) -> None:
        decoder = None
        resampler = None
        skip_until: float | None = None
        my_gen = 0
        done = False

        while True:
            # 1) 停止・シーク要求の確認
            with self._cond:
                if self._stop:
                    return
                target = self._seek_target
                if target is not None:
                    self._seek_target = None
                    my_gen = self._gen
            if target is not None:
                try:
                    self._container.seek(
                        int(target * 1_000_000), backward=True, any_frame=False
                    )
                except Exception:  # noqa: BLE001
                    pass
                decoder = self._container.decode(self._stream)
                resampler = self._new_resampler()
                skip_until = target if target > 0 else None
                done = False
                continue

            # 2) 終端に達していたら次の要求を待つ
            if decoder is None or done:
                with self._cond:
                    if not self._stop and self._seek_target is None:
                        self._cond.wait(0.1)
                continue

            # 3) バッファに空きができるまで待つ
            with self._cond:
                while (
                    self._cap - self._count < self.rate // 4
                    and not self._stop
                    and self._seek_target is None
                ):
                    self._cond.wait(0.05)
                if self._stop:
                    return
                if self._seek_target is not None:
                    continue

            # 4) 1フレームだけデコードして流し込む
            try:
                frame = next(decoder)
            except StopIteration:
                for chunk in self._convert(resampler, None):
                    if not self._push(chunk, my_gen):
                        break
                self._mark_eof(my_gen)
                done = True
                continue
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                self._mark_eof(my_gen)
                done = True
                continue

            if skip_until is not None:
                if frame.pts is not None and frame.time_base is not None:
                    start = float(frame.pts * frame.time_base)
                    length = frame.samples / float(frame.sample_rate or self.rate)
                    if start + length <= skip_until:
                        continue
                skip_until = None

            for chunk in self._convert(resampler, frame):
                if not self._push(chunk, my_gen):
                    break
