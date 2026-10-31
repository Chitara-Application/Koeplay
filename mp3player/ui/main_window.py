"""メインウィンドウ。

構成:
  ヘッダー(タイトル / VB-CABLE状態 / ミキサー開始停止 / 設定)
  左: 曲リスト   右: ミキサー(音量・マイク・モニター・メーター)
  下: プレイヤー(曲名・シークバー・再生ボタン)
音声処理は engine.py が担当し、このファイルは「表示と操作」だけを担当する。
タイマー(50ms)でエンジンの状態を読み取って画面を更新する。
"""
from __future__ import annotations

import os
import random
import re
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..config import APP_TITLE, APP_VERSION, AUDIO_EXTENSIONS, VB_CABLE_URL
from ..devices import DeviceCatalog
from ..engine import AudioEngine, EngineConfig, EngineError
from ..settings import Settings
from . import widgets
from . import theme
from .settings_dialog import AUDIO_KEYS, SettingsDialog

_DIGITS = re.compile(r"(\d+)")
_PATH_ROLE = Qt.ItemDataRole.UserRole


def natural_key(path: Path) -> list:
    """「2.mp3」が「10.mp3」より前に来る並べ替え用のキー。"""
    return [int(t) if t.isdigit() else t.casefold() for t in _DIGITS.split(path.name)]


def scan_folder(folder: Path) -> list[Path]:
    try:
        with os.scandir(folder) as entries:
            files = [
                Path(e.path) for e in entries
                if e.is_file() and e.name.lower().endswith(AUDIO_EXTENSIONS)
            ]
    except OSError:
        return []
    files.sort(key=natural_key)
    return files


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def audio_file_filter() -> str:
    patterns = " ".join(f"*{ext}" for ext in AUDIO_EXTENSIONS)
    return f"音声ファイル ({patterns});;すべてのファイル (*.*)"


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings,
        catalog: DeviceCatalog,
        engine: AudioEngine,
        icon,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.catalog = catalog
        self.engine = engine
        self.app_icon = icon

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(icon)
        self.resize(1100, 740)
        self.setMinimumSize(920, 640)
        self.setAcceptDrops(True)

        self.files: list[Path] = []
        self.visible_files: list[Path] = []
        self.current_path: Path | None = None
        self.history: list[Path] = []
        self._quitting = False
        self._want_running = False
        self._last_recover = 0.0
        self._engine_text = ""
        self._tray_hint_shown = False
        self._cable_help_shown = False
        self._cable_status = None

        folder = Path(settings["folder"]).expanduser() if settings["folder"] else None
        if folder is None or not folder.is_dir():
            music = Path.home() / "Music"
            folder = music if music.is_dir() else Path.home()
        self.folder = folder

        self._build_ui()
        self._build_tray()
        self._restore_geometry()

        # 設定の保存は、操作のたびではなく少し待ってまとめて行う。
        self._save_timer = QTimer(self, singleShot=True, interval=800)
        self._save_timer.timeout.connect(self._save_now)

        # フォルダー内の増減を監視して一覧を更新する。
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._rescan_timer.start())
        self._rescan_timer = QTimer(self, singleShot=True, interval=600)
        self._rescan_timer.timeout.connect(self._rescan)

        self._tick_timer = QTimer(self, interval=50)
        self._tick_timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------
    # 画面の組み立て
    # ------------------------------------------------------------------
    @staticmethod
    def _panel() -> QFrame:
        frame = QFrame()
        frame.setObjectName("panel")
        return frame

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 8)
        outer.setSpacing(12)

        outer.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._build_playlist_panel(), 3)
        body.addWidget(self._build_mixer_panel(), 0)
        outer.addLayout(body, 1)

        outer.addWidget(self._build_player_panel())

        self.engine_label = QLabel("")
        self.statusBar().addPermanentWidget(self.engine_label)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage(f"v{APP_VERSION}")

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        title = QLabel(APP_TITLE)
        title.setObjectName("appTitle")
        self.cable_chip = QLabel("VB-CABLE 確認中")
        self.cable_chip.setObjectName("chip")
        self.mixer_button = QPushButton("ミキサー停止中")
        self.mixer_button.setCheckable(True)
        self.mixer_button.setToolTip(
            "オンの間、マイクとMP3をミックスしてDiscordへ送ります"
        )
        self.mixer_button.clicked.connect(self._on_mixer_clicked)
        settings_button = QPushButton("設定")
        settings_button.clicked.connect(self.open_settings)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.cable_chip)
        row.addWidget(self.mixer_button)
        row.addWidget(settings_button)
        return row

    def _build_playlist_panel(self) -> QFrame:
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("曲名で絞り込み")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _t: self._populate_list())
        folder_button = QPushButton("フォルダー…")
        folder_button.clicked.connect(self._choose_folder)
        file_button = QPushButton("ファイルを開く…")
        file_button.clicked.connect(self._choose_file)
        top.addWidget(self.search_edit, 1)
        top.addWidget(folder_button)
        top.addWidget(file_button)
        layout.addLayout(top)

        self.folder_label = widgets.ElidedLabel(str(self.folder))
        self.folder_label.setObjectName("muted")
        layout.addWidget(self.folder_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_activated)
        self.list_widget.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.list_widget, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("muted")
        layout.addWidget(self.count_label)
        return panel

    def _build_mixer_panel(self) -> QFrame:
        panel = self._panel()
        panel.setFixedWidth(350)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        heading = QLabel("ミキサー")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        s = self.settings
        self.mp3_row = widgets.VolumeRow("MP3", s["mp3_volume"])
        self.mic_row = widgets.VolumeRow("マイク", s["mic_volume"])
        self.mon_row = widgets.VolumeRow("モニター", s["monitor_volume"])
        self.mp3_row.changed.connect(self._on_mp3_volume)
        self.mic_row.changed.connect(self._on_mic_volume)
        self.mon_row.changed.connect(self._on_monitor_volume)
        layout.addWidget(self.mp3_row)
        layout.addWidget(self.mic_row)
        layout.addWidget(self.mon_row)

        self.mic_check = QCheckBox("マイクをDiscordへ送る")
        self.mic_check.setChecked(s["mic_enabled"])
        self.mic_check.toggled.connect(self._on_mic_toggled)
        self.monitor_check = QCheckBox("MP3を自分にも聞く(モニター)")
        self.monitor_check.setChecked(s["monitor_enabled"])
        self.monitor_check.toggled.connect(self._on_monitor_toggled)
        layout.addSpacing(4)
        layout.addWidget(self.mic_check)
        layout.addWidget(self.monitor_check)

        self.monitor_note = QLabel("")
        self.monitor_note.setObjectName("note")
        self.monitor_note.setWordWrap(True)
        self.monitor_note.setMinimumHeight(40)
        self.monitor_note.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.monitor_note)

        layout.addSpacing(6)
        mic_caption = QLabel("マイクの入力レベル")
        mic_caption.setObjectName("muted")
        self.mic_meter = widgets.LevelMeter()
        out_caption = QLabel("Discordへの出力レベル")
        out_caption.setObjectName("muted")
        self.out_meter = widgets.LevelMeter()
        layout.addWidget(mic_caption)
        layout.addWidget(self.mic_meter)
        layout.addWidget(out_caption)
        layout.addWidget(self.out_meter)
        layout.addStretch(1)

        self.engine.mp3_volume = s["mp3_volume"] / 100.0
        self.engine.mic_volume = s["mic_volume"] / 100.0
        self.engine.monitor_volume = s["monitor_volume"] / 100.0
        self.engine.mic_enabled = s["mic_enabled"]
        self.engine.monitor_enabled = s["monitor_enabled"]
        self.engine.monitor_mic = s["monitor_mic"]
        self.engine.limiter = s["limiter"]
        return panel

    def _build_player_panel(self) -> QFrame:
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        self.title_label = widgets.ElidedLabel("曲を選んでください")
        self.title_label.setObjectName("trackTitle")
        self.sub_label = widgets.ElidedLabel("")
        self.sub_label.setObjectName("muted")
        layout.addWidget(self.title_label)
        layout.addWidget(self.sub_label)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.time_now = QLabel("00:00")
        self.time_now.setObjectName("time")
        self.time_total = QLabel("00:00")
        self.time_total.setObjectName("time")
        self.seek_slider = widgets.SeekSlider()
        self.seek_slider.sliderMoved.connect(
            lambda v: self.time_now.setText(format_time(v / 1000.0))
        )
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_row.addWidget(self.time_now)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.time_total)
        layout.addLayout(seek_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        icon_size = QSize(22, 22)

        self.prev_button = QPushButton()
        self.prev_button.setObjectName("transport")
        self.prev_button.setIcon(widgets.make_icon("prev"))
        self.prev_button.setIconSize(icon_size)
        self.prev_button.setToolTip("前の曲")
        self.prev_button.clicked.connect(self.prev_track)

        self.play_button = QPushButton()
        self.play_button.setObjectName("play")
        self.play_icon = widgets.make_icon("play", theme.ON_ACCENT)
        self.pause_icon = widgets.make_icon("pause", theme.ON_ACCENT)
        self.play_button.setIcon(self.play_icon)
        self.play_button.setIconSize(QSize(26, 26))
        self.play_button.setFixedSize(48, 48)
        self.play_button.setToolTip("再生 / 一時停止")
        self.play_button.clicked.connect(self.toggle_play)

        self.stop_button = QPushButton()
        self.stop_button.setObjectName("transport")
        self.stop_button.setIcon(widgets.make_icon("stop"))
        self.stop_button.setIconSize(icon_size)
        self.stop_button.setToolTip("停止")
        self.stop_button.clicked.connect(self.stop)

        self.next_button = QPushButton()
        self.next_button.setObjectName("transport")
        self.next_button.setIcon(widgets.make_icon("next"))
        self.next_button.setIconSize(icon_size)
        self.next_button.setToolTip("次の曲")
        self.next_button.clicked.connect(lambda: self.next_track(auto=False))

        self.shuffle_button = QPushButton("シャッフル")
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.setChecked(self.settings["shuffle"])
        self.shuffle_button.toggled.connect(self._on_shuffle_toggled)
        self.repeat_button = QPushButton()
        self.repeat_button.clicked.connect(self._cycle_repeat)
        self._update_repeat_button()

        controls.addStretch(1)
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.next_button)
        controls.addSpacing(18)
        controls.addWidget(self.shuffle_button)
        controls.addWidget(self.repeat_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        return panel

    # ------------------------------------------------------------------
    # タスクトレイ
    # ------------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_TITLE)
        menu = QMenu()
        show_action = QAction("ウィンドウを表示", self)
        show_action.triggered.connect(self.show_window)
        play_action = QAction("再生 / 一時停止", self)
        play_action.triggered.connect(self.toggle_play)
        self.tray_mic_action = QAction("マイクをDiscordへ送る", self)
        self.tray_mic_action.setCheckable(True)
        self.tray_mic_action.setChecked(self.settings["mic_enabled"])
        self.tray_mic_action.toggled.connect(self.mic_check.setChecked)
        quit_action = QAction("終了", self)
        quit_action.triggered.connect(self.quit_app)
        for action in (show_action, play_action, self.tray_mic_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @property
    def has_tray(self) -> bool:
        return self.tray is not None

    # ------------------------------------------------------------------
    # 起動・終了
    # ------------------------------------------------------------------
    def startup(self) -> None:
        """ウィンドウ表示後に1回だけ呼ぶ。"""
        self._set_folder(self.folder, save=False)
        self._refresh_cable_status()
        if self.settings["autostart_mixer"]:
            self._start_engine(interactive=False)
        self._sync_mixer_button()
        self._update_monitor_note()
        self._restore_last_file()
        self._tick_timer.start()
        QTimer.singleShot(500, self._maybe_show_cable_help)

    def _restore_geometry(self) -> None:
        text = self.settings["window_geometry"]
        if text:
            self.restoreGeometry(QByteArray.fromBase64(text.encode("ascii")))

    def _save_now(self) -> None:
        self.settings["window_geometry"] = bytes(
            self.saveGeometry().toBase64()
        ).decode("ascii")
        self.settings.save()

    def _save_soon(self) -> None:
        self._save_timer.start()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if (
            not self._quitting
            and self.settings["close_to_tray"]
            and self.has_tray
        ):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown and self.tray is not None:
                self._tray_hint_shown = True
                self.tray.showMessage(
                    APP_TITLE,
                    "トレイに常駐しています。終了するにはトレイアイコンの「終了」を選びます。",
                    QSystemTrayIcon.MessageIcon.Information, 4000,
                )
            return
        self._tick_timer.stop()
        self._save_timer.stop()
        self._save_now()
        self.engine.shutdown()
        self.engine.unload()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        QApplication.quit()

    # ------------------------------------------------------------------
    # フォルダーと曲リスト
    # ------------------------------------------------------------------
    def _set_folder(self, folder: Path, save: bool = True) -> None:
        self.folder = folder
        self.folder_label.setText(str(folder))
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        if folder.is_dir():
            self.watcher.addPath(str(folder))
        self.settings["folder"] = str(folder)
        if save:
            self._save_soon()
        self._rescan()

    def _rescan(self) -> None:
        self.files = scan_folder(self.folder)
        if self.folder.is_dir() and str(self.folder) not in self.watcher.directories():
            self.watcher.addPath(str(self.folder))
        self._populate_list()

    def _populate_list(self) -> None:
        query = self.search_edit.text().strip().casefold()
        self.visible_files = [
            p for p in self.files if not query or query in p.name.casefold()
        ]
        self.list_widget.clear()
        for path in self.visible_files:
            item = QListWidgetItem(path.stem)
            item.setData(_PATH_ROLE, str(path))
            item.setToolTip(path.name)
            self.list_widget.addItem(item)
        if not self.visible_files:
            hint = (
                "該当する曲がありません。" if self.files else
                "音声ファイルがありません。フォルダーを選ぶか、ファイルをここにドロップしてください。"
            )
            item = QListWidgetItem(hint)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(item)
        self.count_label.setText(f"{len(self.visible_files)} 曲")
        self._mark_current()

    def _mark_current(self) -> None:
        current = str(self.current_path) if self.current_path else ""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(_PATH_ROLE)
            if not path:
                continue
            is_current = path == current
            font = item.font()
            font.setBold(is_current)
            item.setFont(font)
            item.setForeground(
                self.palette().highlight() if is_current else self.palette().text()
            )

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "音声フォルダーを選択", str(self.folder)
        )
        if folder:
            self._set_folder(Path(folder))

    def _choose_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "音声ファイルを選択", str(self.folder), audio_file_filter()
        )
        if selected:
            self._open_external_file(Path(selected))

    def _open_external_file(self, path: Path) -> None:
        """一覧に無い場所のファイルを開いた時は、そのフォルダーに切り替える。"""
        if path.parent != self.folder:
            self._set_folder(path.parent)
        self.play_path(path)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        path = item.data(_PATH_ROLE)
        if path:
            self.play_path(Path(path))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir():
                self._set_folder(path)
            elif path.is_file():
                self._open_external_file(path)
            break

    # ------------------------------------------------------------------
    # 再生操作
    # ------------------------------------------------------------------
    def _restore_last_file(self) -> None:
        last = self.settings["last_file"]
        if not last:
            return
        path = Path(last)
        if path.is_file():
            try:
                src = self.engine.load(path)
            except Exception:  # noqa: BLE001
                return
            self.current_path = path
            self._show_track_info(src)
            self._mark_current()

    def _show_track_info(self, src) -> None:
        self.title_label.setText(src.title or src.path.stem)
        parts = [p for p in (src.artist, src.codec, src.path.suffix.lstrip(".").upper()) if p]
        self.sub_label.setText("  /  ".join(dict.fromkeys(parts)))

    def play_path(self, path: Path) -> bool:
        if not self._ensure_engine():
            return False
        try:
            src = self.engine.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self, "音声ファイルを開けません",
                f"{path.name}\n\n{exc}\n\n"
                "対応していない形式か、ファイルが壊れている可能性があります。",
            )
            return False
        previous = self.current_path
        if previous and previous != path:
            self.history.append(previous)
            del self.history[:-50]
        self.current_path = path
        self.engine.play()
        self._show_track_info(src)
        self.settings["last_file"] = str(path)
        self._save_soon()
        self._mark_current()
        return True

    def toggle_play(self) -> None:
        snap = self.engine.poll(reset=False)
        if self.engine.source is None:
            # まだ曲を選んでいない: 選択中の曲、無ければ先頭を再生する。
            item = self.list_widget.currentItem()
            path = item.data(_PATH_ROLE) if item else None
            if path:
                self.play_path(Path(path))
            elif self.visible_files:
                self.play_path(self.visible_files[0])
            else:
                self._choose_file()
            return
        if not self._ensure_engine():
            return
        if snap.playing and not snap.paused:
            self.engine.pause()
        else:
            self.engine.play()

    def stop(self) -> None:
        self.engine.stop_playback()

    def _pick_next(self, auto: bool) -> Path | None:
        files = self.visible_files
        if not files:
            return None
        repeat = self.settings["repeat"]
        if auto and repeat == "one" and self.current_path in files:
            return self.current_path
        if self.settings["shuffle"]:
            pool = [f for f in files if f != self.current_path] or files
            return random.choice(pool)
        if self.current_path in files:
            index = files.index(self.current_path) + 1
            if index >= len(files):
                return files[0] if (repeat == "all" or not auto) else None
            return files[index]
        return files[0]

    def next_track(self, auto: bool = False) -> None:
        path = self._pick_next(auto)
        if path is not None:
            self.play_path(path)
        elif auto:
            self.engine.stop_playback()

    def prev_track(self) -> None:
        snap = self.engine.poll(reset=False)
        if snap.position > 3.0 or not self.history:
            self.engine.seek(0.0)
            return
        path = self.history.pop()
        # 履歴を戻る時は、今の曲を履歴に積まない。
        current = self.current_path
        self.current_path = None
        if not self.play_path(path):
            self.current_path = current

    def _on_track_finished(self) -> None:
        if self.settings["auto_next"] or self.settings["repeat"] == "one":
            self.next_track(auto=True)
        else:
            self.engine.stop_playback()

    def _on_seek_released(self) -> None:
        self.engine.seek(self.seek_slider.value() / 1000.0)

    def _on_shuffle_toggled(self, checked: bool) -> None:
        self.settings["shuffle"] = checked
        self._save_soon()

    _REPEAT_LABELS = {"off": "リピート: オフ", "all": "リピート: 全曲", "one": "リピート: 1曲"}

    def _update_repeat_button(self) -> None:
        self.repeat_button.setText(self._REPEAT_LABELS[self.settings["repeat"]])

    def _cycle_repeat(self) -> None:
        order = ["off", "all", "one"]
        current = self.settings["repeat"]
        self.settings["repeat"] = order[(order.index(current) + 1) % len(order)]
        self._update_repeat_button()
        self._save_soon()

    # ------------------------------------------------------------------
    # ミキサー(エンジン)の開始・停止・復旧
    # ------------------------------------------------------------------
    def _engine_config(self) -> EngineConfig:
        s = self.settings
        return EngineConfig(
            host_api=s["host_api"],
            mic_name=s["input_device_name"],
            out_name=s["output_device_name"],
            monitor_name=s["monitor_device_name"],
            sample_rate=s["sample_rate"],
            latency=s["latency"],
            monitor_enabled=s["monitor_enabled"],
        )

    def _start_engine(self, interactive: bool) -> bool:
        try:
            notes = self.engine.start(self._engine_config())
        except EngineError as exc:
            self._want_running = False
            self.statusBar().showMessage("ミキサーを開始できませんでした", 6000)
            self._engine_text = str(exc).splitlines()[0]
            self.engine_label.setText(self._engine_text)
            self._refresh_cable_status()
            if interactive:
                QMessageBox.warning(
                    self, "ミキサーを開始できません",
                    f"{exc}\n\n以下も確認してください。\n"
                    "・VB-CABLEを導入し、Windowsを再起動したか\n"
                    "・他のアプリがCABLEやマイクを占有していないか\n"
                    "・設定の「音声デバイス」で、マイクが正しく選ばれているか",
                )
            self._sync_mixer_button()
            return False
        self._want_running = True
        if notes:
            self.statusBar().showMessage(" ".join(notes), 8000)
        self._refresh_cable_status()
        self._update_monitor_note()
        self._sync_mixer_button()
        return True

    def _ensure_engine(self) -> bool:
        return self.engine.running or self._start_engine(interactive=True)

    def _stop_mixer(self) -> None:
        self._want_running = False
        self.engine.shutdown()
        self._sync_mixer_button()
        self._update_monitor_note()

    def _restart_engine(self, quiet: bool = False) -> bool:
        snap = self.engine.poll(reset=False)
        was_playing = snap.playing and not snap.paused
        self.engine.shutdown()
        self.catalog.refresh(reinit=True)
        ok = self._start_engine(interactive=not quiet)
        if ok and was_playing:
            self.engine.play()
        return ok

    def _on_mixer_clicked(self) -> None:
        if self.engine.running:
            self._stop_mixer()
        else:
            self._start_engine(interactive=True)
        self._sync_mixer_button()

    def _sync_mixer_button(self) -> None:
        running = self.engine.running
        self.mixer_button.blockSignals(True)
        self.mixer_button.setChecked(running)
        self.mixer_button.blockSignals(False)
        self.mixer_button.setText("ミキサー動作中" if running else "ミキサー停止中")

    def _rescan_devices(self) -> None:
        """設定画面の「再読み込み」から呼ばれる。ストリームを閉じてから取り直す。"""
        was_running = self.engine.running
        snap = self.engine.poll(reset=False)
        was_playing = snap.playing and not snap.paused
        self.engine.shutdown()
        self.catalog.refresh(reinit=True)
        self._refresh_cable_status()
        if was_running:
            if self._start_engine(interactive=False) and was_playing:
                self.engine.play()

    def _recover_if_needed(self, snap) -> None:
        if not (self.engine.running and not snap.healthy):
            return
        now = time.monotonic()
        if now - self._last_recover < 3.0:
            return
        self._last_recover = now
        self.statusBar().showMessage("オーディオが停止しました。再接続を試しています…", 3000)
        self._restart_engine(quiet=True)

    # ------------------------------------------------------------------
    # VB-CABLE
    # ------------------------------------------------------------------
    def _refresh_cable_status(self) -> None:
        status = self.catalog.cable_status()
        if not status.playback_found:
            text, state = "VB-CABLE 未検出", "bad"
        elif status.default_output_is_cable:
            text, state = "既定の出力がCABLEです", "warn"
        elif status.ok:
            text, state = "VB-CABLE 検出済み", "ok"
        else:
            text, state = "VB-CABLE 一部のみ検出", "warn"
        self.cable_chip.setText(text)
        widgets.set_state(self.cable_chip, state)
        self._cable_status = status

    def _maybe_show_cable_help(self) -> None:
        if (
            self._cable_help_shown
            or self._cable_status is None
            or self._cable_status.playback_found
        ):
            return
        self._cable_help_shown = True
        box = QMessageBox(self)
        box.setWindowTitle("VB-CABLEが見つかりません")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "Discordへ音を送るには VB-CABLE(仮想オーディオケーブル)が必要です。\n\n"
            "公式ページから導入し、導入後にWindowsを再起動してください。"
            "再起動後にこのアプリを起動すると、自動で検出されます。"
        )
        open_button = box.addButton("公式ページを開く", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("閉じる", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(VB_CABLE_URL))

    # ------------------------------------------------------------------
    # ミキサーの操作
    # ------------------------------------------------------------------
    def _on_mp3_volume(self, value: float) -> None:
        self.engine.mp3_volume = value / 100.0
        self.settings["mp3_volume"] = value
        self._save_soon()

    def _on_mic_volume(self, value: float) -> None:
        self.engine.mic_volume = value / 100.0
        self.settings["mic_volume"] = value
        self._save_soon()

    def _on_monitor_volume(self, value: float) -> None:
        self.engine.monitor_volume = value / 100.0
        self.settings["monitor_volume"] = value
        self._save_soon()

    def _on_mic_toggled(self, enabled: bool) -> None:
        self.engine.mic_enabled = enabled
        self.settings["mic_enabled"] = enabled
        if self.tray is not None and self.tray_mic_action.isChecked() != enabled:
            self.tray_mic_action.blockSignals(True)
            self.tray_mic_action.setChecked(enabled)
            self.tray_mic_action.blockSignals(False)
        self.statusBar().showMessage("マイク ON" if enabled else "マイク OFF", 2000)
        self._save_soon()

    def _on_monitor_toggled(self, enabled: bool) -> None:
        self.settings["monitor_enabled"] = enabled
        ok = self.engine.set_monitor_enabled(enabled)
        self._update_monitor_note()
        if enabled and not ok:
            self.statusBar().showMessage(self.engine.monitor_label, 8000)
        self._save_soon()

    def _update_monitor_note(self) -> None:
        text = self.engine.monitor_label
        if not self.engine.running:
            text = "ミキサー停止中" if self.settings["monitor_enabled"] else "モニター: オフ"
        bad = "使えません" in text or "開けません" in text
        self.monitor_note.setText(text)
        widgets.set_state(self.monitor_note, "bad" if bad else "")

    # ------------------------------------------------------------------
    # 設定ウィンドウ
    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self.settings, self.catalog, self._rescan_devices)
        dialog.applied.connect(self._apply_settings)
        dialog.exec()

    def _apply_settings(self, values: dict) -> None:
        old = {key: self.settings[key] for key in values}
        self.settings.update(values)
        s = self.settings

        audio_changed = any(old[k] != s[k] for k in AUDIO_KEYS if k in old)
        monitor_changed = old.get("monitor_enabled") != s["monitor_enabled"]

        self.engine.limiter = s["limiter"]
        self.engine.monitor_mic = s["monitor_mic"]
        self.monitor_check.blockSignals(True)
        self.monitor_check.setChecked(s["monitor_enabled"])
        self.monitor_check.blockSignals(False)
        self.shuffle_button.blockSignals(True)
        self.shuffle_button.setChecked(s["shuffle"])
        self.shuffle_button.blockSignals(False)
        self._update_repeat_button()

        folder = Path(s["folder"]).expanduser() if s["folder"] else self.folder
        if folder != self.folder and folder.is_dir():
            self._set_folder(folder, save=False)
        else:
            s["folder"] = str(self.folder)

        if audio_changed and self.engine.running:
            self._restart_engine(quiet=False)
        elif monitor_changed:
            self.engine.set_monitor_enabled(s["monitor_enabled"])
        self._update_monitor_note()
        self._save_soon()

    # ------------------------------------------------------------------
    # 定期更新(50msごと)
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        snap = self.engine.poll()

        if snap.running:
            self.mic_meter.set_peak(snap.mic_peak)
            self.out_meter.set_peak(snap.out_peak)
        else:
            self.mic_meter.reset()
            self.out_meter.reset()

        if not self.seek_slider.isSliderDown():
            duration_ms = int(snap.duration * 1000)
            if self.seek_slider.maximum() != duration_ms:
                self.seek_slider.setRange(0, duration_ms)
                self.seek_slider.setEnabled(duration_ms > 0)
            self.seek_slider.setValue(int(snap.position * 1000))
            self.time_now.setText(format_time(snap.position))
        self.time_total.setText(format_time(snap.duration))

        playing = snap.playing and not snap.paused
        self.play_button.setIcon(self.pause_icon if playing else self.play_icon)

        if snap.finished:
            self._on_track_finished()

        self._recover_if_needed(snap)
        self._update_engine_label(snap)

    def _update_engine_label(self, snap) -> None:
        if self.engine.running:
            api = self.engine.api.replace("Windows ", "")
            text = (
                f"{api}  {self.engine.rate}Hz   "
                f"{self.engine.mic_device_name}  →  {self.engine.out_device_name}"
            )
            if snap.underruns:
                text += f"   途切れ {snap.underruns}回"
        else:
            text = self._engine_text or "ミキサー停止中"
        if snap.error:
            text += f"   ⚠ {snap.error}"
        if text != self.engine_label.text():
            self.engine_label.setText(text)
