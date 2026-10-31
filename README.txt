Koeplay 1.0  (Chitara-Applications)
マイクと音声ファイルをミックスして、VB-CABLE経由でDiscordへ送るアプリ

【配置】
  C:\Application\Mp3Player に、このフォルダーの中身をそのままコピーします。
  ・古い MP3Player.spec / MP3Player.iss / .bat / README_INSTALL.txt は使いません(削除してかまいません)。
  ・旧版(MP3 Player + Mic Mixer)の設定は、初回起動時に自動で引き継ぎます。

【準備】(PowerShell。.venv を有効にした状態で)
  pip install -r requirements.txt

【起動(開発中の確認)】
  python main.py

【EXE化 → インストーラー化】
  1) python -m PyInstaller --noconfirm --clean Koeplay.spec
       → dist\Koeplay\Koeplay.exe ができます(フォルダーごと使います)
  2) Koeplay.iss を Inno Setup Compiler で開いて Compile
       → dist_installer\Koeplay_Setup_1.0.exe ができます
  ※ VBCABLE_Driver_Pack45.zip を Koeplay.iss と同じフォルダーに置いておくこと。

【インストーラーの動き】
  1. VB-CABLEが未導入の場合だけ、「VB-CABLEを導入する」が表示されます(既定でON)。
  2. Koeplay本体をコピーしたあと、同梱のZIPを解凍し、VB-CABLEのセットアップを開きます。
  3. 利用者が「Install Driver」を押して閉じると、使える状態かを自動で判定します。
       使える   → 再起動なし。完了ページの「Koeplayを起動する」で起動できます。
       まだ不可 → 完了ページで再起動を確認し、再起動後にKoeplayが1回だけ自動で起動します。
  4. 導入済みの場合は、VB-CABLEの手順は出ません(誤って削除しないため)。

【ファイルの役割】
  main.py                      起動・二重起動の防止・エラーログ
  mp3player\config.py          定数(アプリ名、バージョン、対応拡張子、保存先)
  mp3player\settings.py        設定の読み書き(旧版の設定を引き継ぐ)
  mp3player\devices.py         デバイス一覧、マイクのみ表示、VB-CABLE検出
  mp3player\ring.py            マイク/モニター用の受け渡しバッファ
  mp3player\source.py          音声ファイルのデコード(FFmpeg。ほぼ全形式)
  mp3player\engine.py          ミキサー本体(マイク+音声→CABLE、モニター)
  mp3player\ui\theme.py        配色とスタイル
  mp3player\ui\widgets.py      メーター、シークバー、アイコンなどの部品
  mp3player\ui\main_window.py  メイン画面
  mp3player\ui\settings_dialog.py  設定ウィンドウ
  Koeplay.spec                 EXE化の設定(PyInstaller)
  Koeplay.iss                  インストーラーの設定(Inno Setup)

【保存先】
  設定       %APPDATA%\Koeplay\settings.json
  エラー記録  %APPDATA%\Koeplay\error.log

【Discordの設定】
  入力デバイス: CABLE Output (VB-Audio Virtual Cable)
  ノイズ抑制・エコー除去・自動音量調整: OFF
