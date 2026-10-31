"""Koeplay 起動ファイル。"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime


def _install_excepthook() -> None:
    """窓なし(console=False)のexeでも、原因が分かるようにログへ残す。"""
    from mp3player.config import APPDATA_DIR, LOG_PATH

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            APPDATA_DIR.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as file:
                file.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}")
        except OSError:
            pass
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, "エラー",
                f"予期しないエラーが発生しました。\n\n{exc}\n\n"
                f"詳細は次のファイルに記録しました。\n{LOG_PATH}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def main() -> int:
    from PySide6.QtCore import QDir, QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from mp3player.config import APP_TITLE
    from mp3player.devices import DeviceCatalog
    from mp3player.engine import AudioEngine
    from mp3player.settings import Settings
    from mp3player.ui import theme, widgets
    from mp3player.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    theme.apply_theme(app)
    _install_excepthook()

    # 二重起動の防止(同じマイク/CABLEを2つのアプリが開くとエラーになるため)
    lock = QLockFile(QDir.temp().filePath("Koeplay.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, APP_TITLE,
            "すでに起動しています。タスクトレイのアイコンを確認してください。",
        )
        return 0

    icon = widgets.make_app_icon()
    app.setWindowIcon(icon)

    settings = Settings()
    catalog = DeviceCatalog()
    engine = AudioEngine(catalog)
    window = MainWindow(settings, catalog, engine, icon)

    if window.has_tray:
        app.setQuitOnLastWindowClosed(False)
    if not (settings["start_minimized"] and window.has_tray):
        window.show()
    window.startup()

    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
