"""設定ウィンドウ。OK/適用を押すと applied シグナルで設定値(dict)を渡す。"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ..config import SOUND_SETTINGS_URL, VB_CABLE_URL
from ..devices import API_CHOICES, DeviceCatalog, names_match
from ..settings import Settings
from . import widgets

# これらが変わったらオーディオを開き直す必要がある。
AUDIO_KEYS = (
    "host_api", "input_device_name", "output_device_name",
    "monitor_device_name", "sample_rate", "latency",
)


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


class SettingsDialog(QDialog):
    applied = Signal(dict)

    def __init__(
        self,
        parent: QWidget,
        settings: Settings,
        catalog: DeviceCatalog,
        on_rescan: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumSize(640, 560)
        self.settings = settings
        self.catalog = catalog
        self.on_rescan = on_rescan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_device_tab()
        self._build_mixer_tab()
        self._build_play_tab()
        self._build_general_tab()
        self._build_cable_tab()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("OK")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("適用")
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            lambda: self.applied.emit(self.values())
        )
        layout.addWidget(buttons)

        self._load_from_settings()
        self._fill_devices()
        self._refresh_cable_tab()

    # ------------------------------------------------------------------
    # タブの組み立て
    # ------------------------------------------------------------------
    def _page(self, title: str) -> QFormLayout:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        self.tabs.addTab(page, title)
        return form

    def _build_device_tab(self) -> None:
        form = self._page("音声デバイス")
        self.api_combo = QComboBox()
        for value, label in API_CHOICES:
            self.api_combo.addItem(label, value)
        self.mic_combo = QComboBox()
        self.show_all_check = QCheckBox("マイク以外の入力デバイスも表示する")
        self.out_combo = QComboBox()
        self.monitor_combo = QComboBox()
        self.rate_combo = QComboBox()
        self.rate_combo.addItem("自動(48000Hz → 44100Hz)", "auto")
        self.rate_combo.addItem("48000 Hz", "48000")
        self.rate_combo.addItem("44100 Hz", "44100")
        self.latency_combo = QComboBox()
        self.latency_combo.addItem("低遅延(音が途切れやすい)", "low")
        self.latency_combo.addItem("標準", "normal")
        self.latency_combo.addItem("安定重視(遅延が増える)", "safe")

        form.addRow("ホストAPI", self.api_combo)
        form.addRow("マイク", self.mic_combo)
        form.addRow("", self.show_all_check)
        form.addRow("Discordへの出力", self.out_combo)
        form.addRow("モニター出力", self.monitor_combo)
        form.addRow("サンプルレート", self.rate_combo)
        form.addRow("バッファ", self.latency_combo)
        form.addRow("", _note(
            "ホストAPIは通常「自動」のままで大丈夫です。音が途切れる・開けない場合は"
            "MMEを試してください。モニター出力にはVB-CABLEを選べません。"
        ))
        rescan = QPushButton("デバイスを再読み込み")
        rescan.clicked.connect(self._rescan)
        form.addRow("", rescan)

        self.api_combo.currentIndexChanged.connect(lambda _i: self._fill_devices())
        self.show_all_check.toggled.connect(lambda _c: self._fill_devices())

    def _build_mixer_tab(self) -> None:
        form = self._page("ミキサー")
        self.autostart_check = QCheckBox("起動したらミキサーを自動で開始する")
        self.monitor_check = QCheckBox("MP3を自分にも聞く(モニター出力へ同時に再生)")
        self.monitor_mic_check = QCheckBox("モニターに自分のマイクも混ぜる")
        self.limiter_check = QCheckBox("リミッターを使う(音割れを防ぐ)")
        form.addRow(self.autostart_check)
        form.addRow(_note(
            "ミキサーが止まっていると、Discordにマイクの声も届きません。"
            "普段は自動開始のままにしてください。"
        ))
        form.addRow(self.monitor_check)
        form.addRow(self.monitor_mic_check)
        form.addRow(_note(
            "スピーカーで聞くと、マイクがその音を拾って相手に二重に聞こえます。"
            "ヘッドホンの使用をおすすめします。マイクの混ぜ込みは遅延で声が"
            "ずれて聞こえるため、通常はOFFで使ってください。"
        ))
        form.addRow(self.limiter_check)

    def _build_play_tab(self) -> None:
        form = self._page("再生")
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItem("オフ", "off")
        self.repeat_combo.addItem("全曲リピート", "all")
        self.repeat_combo.addItem("1曲リピート", "one")
        self.shuffle_check = QCheckBox("シャッフル再生")
        self.auto_next_check = QCheckBox("曲が終わったら次の曲へ進む")
        form.addRow("リピート", self.repeat_combo)
        form.addRow(self.shuffle_check)
        form.addRow(self.auto_next_check)

    def _build_general_tab(self) -> None:
        form = self._page("一般")
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit()
        browse = QPushButton("参照…")
        browse.clicked.connect(self._browse_folder)
        row_layout.addWidget(self.folder_edit, 1)
        row_layout.addWidget(browse)
        self.tray_check = QCheckBox("閉じるボタンでタスクトレイに常駐する")
        self.minimized_check = QCheckBox("起動時はトレイに最小化する")
        form.addRow("音声フォルダー", row)
        form.addRow(self.tray_check)
        form.addRow(_note(
            "ウィンドウを閉じてもミキサーが動き続けます。完全に終了するには"
            "トレイアイコンの「終了」を選んでください。"
        ))
        form.addRow(self.minimized_check)

    def _build_cable_tab(self) -> None:
        form = self._page("VB-CABLE")
        self.cable_label = QLabel()
        self.cable_label.setWordWrap(True)
        self.cable_label.setObjectName("note")
        form.addRow(self.cable_label)
        self.cable_detail = _note("")
        form.addRow(self.cable_detail)

        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        redetect = QPushButton("再検出")
        redetect.clicked.connect(self._rescan)
        official = QPushButton("公式ページを開く")
        official.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(VB_CABLE_URL))
        )
        sound = QPushButton("Windowsのサウンド設定を開く")
        sound.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(SOUND_SETTINGS_URL))
        )
        row.addWidget(redetect)
        row.addWidget(official)
        row.addWidget(sound)
        row.addStretch(1)
        form.addRow(buttons)

        form.addRow(_note(
            "【Discordの設定】音声・ビデオ → 入力デバイスを "
            "「CABLE Output (VB-Audio Virtual Cable)」にします。"
            "ノイズ抑制・エコー除去・自動音量調整はOFFにしてください"
            "(BGMが途切れたり歪んだりします)。"
        ))
        form.addRow(_note(
            "VB-CABLEの導入直後は、Windowsの再起動が必要です。"
            "導入後にWindowsの既定の出力がCABLEに切り替わることがあるので、"
            "その場合は元のスピーカーに戻してください。"
        ))
        form.addRow(_note(
            "VB-CABLE は VB-Audio Software のドネーションウェアです"
            "(www.vb-cable.com)。"
        ))

    # ------------------------------------------------------------------
    # 値の出し入れ
    # ------------------------------------------------------------------
    @staticmethod
    def _select(combo: QComboBox, data: Any) -> None:
        index = combo.findData(data)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_from_settings(self) -> None:
        s = self.settings
        self._select(self.api_combo, s["host_api"])
        self._saved_mic = s["input_device_name"]
        self._saved_out = s["output_device_name"]
        self._saved_monitor = s["monitor_device_name"]
        self.show_all_check.setChecked(s["show_all_inputs"])
        self._select(self.rate_combo, s["sample_rate"])
        self._select(self.latency_combo, s["latency"])
        self.autostart_check.setChecked(s["autostart_mixer"])
        self.monitor_check.setChecked(s["monitor_enabled"])
        self.monitor_mic_check.setChecked(s["monitor_mic"])
        self.limiter_check.setChecked(s["limiter"])
        self._select(self.repeat_combo, s["repeat"])
        self.shuffle_check.setChecked(s["shuffle"])
        self.auto_next_check.setChecked(s["auto_next"])
        self.folder_edit.setText(s["folder"])
        self.tray_check.setChecked(s["close_to_tray"])
        self.minimized_check.setChecked(s["start_minimized"])

    def values(self) -> dict[str, Any]:
        return {
            "host_api": self.api_combo.currentData(),
            "input_device_name": self.mic_combo.currentData() or "",
            "output_device_name": self.out_combo.currentData() or "",
            "monitor_device_name": self.monitor_combo.currentData() or "",
            "show_all_inputs": self.show_all_check.isChecked(),
            "sample_rate": self.rate_combo.currentData(),
            "latency": self.latency_combo.currentData(),
            "autostart_mixer": self.autostart_check.isChecked(),
            "monitor_enabled": self.monitor_check.isChecked(),
            "monitor_mic": self.monitor_mic_check.isChecked(),
            "limiter": self.limiter_check.isChecked(),
            "repeat": self.repeat_combo.currentData(),
            "shuffle": self.shuffle_check.isChecked(),
            "auto_next": self.auto_next_check.isChecked(),
            "folder": self.folder_edit.text().strip(),
            "close_to_tray": self.tray_check.isChecked(),
            "start_minimized": self.minimized_check.isChecked(),
        }

    def _fill_devices(self) -> None:
        """今選ばれているホストAPIのデバイスだけを各コンボボックスに並べる。"""
        # 直前の選択を覚えておく(再構築で消えないように)
        if self.mic_combo.count():
            self._saved_mic = self.mic_combo.currentData() or ""
            self._saved_out = self.out_combo.currentData() or ""
            self._saved_monitor = self.monitor_combo.currentData() or ""

        api = self.catalog.display_api(self.api_combo.currentData())
        show_all = self.show_all_check.isChecked()

        def refill(combo: QComboBox, first_label: str, devices, saved: str) -> None:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(first_label, "")
            for device in devices:
                combo.addItem(device.name, device.name)
            if saved:
                index = -1
                for i in range(1, combo.count()):
                    if names_match(combo.itemData(i), saved):
                        index = i
                        break
                if index < 0:
                    combo.addItem(f"{saved}(見つかりません)", saved)
                    index = combo.count() - 1
                combo.setCurrentIndex(index)
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

        refill(self.mic_combo, "既定のマイク", self.catalog.inputs(api, show_all),
               self._saved_mic)
        outputs = self.catalog.cable_outputs(api)
        others = [d for d in self.catalog.outputs(api) if not d.is_cable]
        refill(self.out_combo, "自動(VB-CABLE)", outputs + others, self._saved_out)
        refill(self.monitor_combo, "Windowsの既定の出力",
               self.catalog.monitor_outputs(api), self._saved_monitor)

    def _rescan(self) -> None:
        self._saved_mic = self.mic_combo.currentData() or ""
        self._saved_out = self.out_combo.currentData() or ""
        self._saved_monitor = self.monitor_combo.currentData() or ""
        self.on_rescan()
        self._fill_devices()
        self._refresh_cable_tab()

    def _refresh_cable_tab(self) -> None:
        status = self.catalog.cable_status()
        if status.ok:
            text, state = "VB-CABLE が検出されました。", "ok"
        elif status.playback_found or status.recorder_found:
            text, state = (
                "VB-CABLE の一部しか検出できません。再導入と再起動をお試しください。",
                "warn",
            )
        else:
            text, state = (
                "VB-CABLE が見つかりません。導入後にWindowsを再起動してください。",
                "bad",
            )
        if status.default_output_is_cable:
            text += "\nWindowsの既定の出力がVB-CABLEになっています(音が聞こえない原因になります)。"
            if state == "ok":
                state = "warn"
        self.cable_label.setText(text)
        widgets.set_state(self.cable_label, state)
        lines = []
        if status.playback_names:
            lines.append("再生側: " + " / ".join(status.playback_names))
        if status.recorder_names:
            lines.append("録音側(Discordの入力): " + " / ".join(status.recorder_names))
        self.cable_detail.setText("\n".join(lines))

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "音声フォルダーを選択", self.folder_edit.text() or ""
        )
        if folder:
            self.folder_edit.setText(folder)

    def _on_ok(self) -> None:
        self.applied.emit(self.values())
        self.accept()
