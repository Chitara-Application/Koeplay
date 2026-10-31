"""アイコン(assets/icon.ico と assets/icon.png)を作るスクリプト。

使い方(プロジェクトのフォルダーで):
    python tools\\make_icon.py

アプリ内のアイコン(mp3player/ui/widgets.py)と同じ絵を、サイズごとに描き分けて
.ico にまとめる。絵を変えた時は、widgets.py を直してからこれを実行し直す。
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mp3player.ui.widgets import _draw_app_icon  # noqa: E402

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(size: int) -> bytes:
    pixmap = _draw_app_icon(size)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def build_ico(sizes: tuple[int, ...]) -> bytes:
    images = [(size, png_bytes(size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    body = b""
    for size, data in images:
        dim = 0 if size >= 256 else size  # 256は0と書く決まり
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset
        )
        body += data
        offset += len(data)
    return header + entries + body


def main() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    out_dir = ROOT / "assets"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "icon.ico").write_bytes(build_ico(ICO_SIZES))
    (out_dir / "icon.png").write_bytes(png_bytes(256))
    print("作成しました:", out_dir / "icon.ico", "/", out_dir / "icon.png")


if __name__ == "__main__":
    main()
