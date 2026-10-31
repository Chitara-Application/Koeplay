"""スレッド間でオーディオを受け渡すリングバッファ。

マイク入力とVB-CABLE出力は別々のストリーム(別々のクロック)で動くため、
間にこのバッファを挟んで受け渡す。クロックのずれで溜まりすぎた分は古い方から
捨て、足りなくなった時は無音で埋めて、一定量溜まるまで再生を待つ。
"""
from __future__ import annotations

import threading

import numpy as np


class Ring:
    def __init__(self, channels: int, capacity: int) -> None:
        self.channels = int(channels)
        self.capacity = int(capacity)
        self._buf = np.zeros((self.capacity, self.channels), dtype=np.float32)
        self._rpos = 0
        self._count = 0
        self._primed = False
        self._lock = threading.Lock()
        self.dropped = 0
        self.underruns = 0

    def clear(self) -> None:
        with self._lock:
            self._rpos = 0
            self._count = 0
            self._primed = False

    def fill(self) -> int:
        return self._count

    def write(self, data: np.ndarray, max_fill: int | None = None) -> None:
        """data: (frames, channels)。max_fillを超える分は古い方から捨てる。"""
        n = len(data)
        if n == 0:
            return
        with self._lock:
            cap = self.capacity
            limit = cap if max_fill is None else min(cap, int(max_fill))
            if n > limit:
                data = data[n - limit:]
                n = limit
            overflow = self._count + n - limit
            if overflow > 0:
                overflow = min(overflow, self._count)
                self._rpos = (self._rpos + overflow) % cap
                self._count -= overflow
                self.dropped += overflow
            w = (self._rpos + self._count) % cap
            first = min(n, cap - w)
            self._buf[w:w + first] = data[:first]
            if n > first:
                self._buf[:n - first] = data[first:]
            self._count += n

    def read(self, frames: int, prefill: int = 0) -> tuple[np.ndarray, int]:
        """(frames, channels)の配列と、実際に読めたフレーム数を返す。

        足りない分は無音。prefillに達するまでは読まずに待つ(出だしの途切れ防止)。
        """
        out = np.zeros((frames, self.channels), dtype=np.float32)
        with self._lock:
            was_primed = self._primed
            if not was_primed:
                if self._count >= max(prefill, 1):
                    self._primed = True
                else:
                    return out, 0
            k = min(frames, self._count)
            if k > 0:
                r = self._rpos
                cap = self.capacity
                first = min(k, cap - r)
                out[:first] = self._buf[r:r + first]
                if k > first:
                    out[first:k] = self._buf[:k - first]
                self._rpos = (r + k) % cap
                self._count -= k
            if k < frames:
                self._primed = False
                self.underruns += 1
        return out, k
