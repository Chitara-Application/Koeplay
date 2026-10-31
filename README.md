## <img width="256" height="256" alt="icon" src="https://github.com/user-attachments/assets/fb97b081-6787-4666-8108-b54515a69412" />

# Koeplay

マイクと音声ファイルをミックスして、**VB-CABLE 経由で Discord などへ送る** Windows 向けのミキサー兼プレイヤーです。
BGM や効果音を流しながら、自分の声も同時に届けられます。

<img width="1100" height="740" alt="screenshot" src="https://github.com/user-attachments/assets/263323f4-b7ce-49c3-a11d-22134d195c4d" />
## 特長

- **マイク + 音声ファイルを1つにミックス**して、仮想マイク(VB-CABLE)へ出力
- **自分にも聞こえる「モニター出力」**: チェックボックスで切り替え。専用の音量つき。出力先は Windows の既定または選択
- **ほぼすべての音声形式に対応**(FFmpeg): MP3 / WAV / FLAC / OGG / Opus / M4A・AAC / WMA ほか
- **マイクだけを表示するデバイス選択**(重複なし)。WASAPI / MME / DirectSound から選択可能
- 音量メーター、シークバー、リピート、シャッフル、ドラッグ&ドロップ、リミッター(音割れ防止)
- **VB-CABLE の自動検出**。導入されていなければ案内を表示
- タスクトレイ常駐。オーディオデバイスが切断されても自動で復旧
- 長い音声でもメモリを食わない、ストリーミング方式のデコード

## 動作環境

- Windows 10 / 11(64bit)
- [VB-CABLE](https://vb-audio.com/Cable/)(インストーラーが導入を案内します)

## インストール

1. [Releases](https://github.com/Chitara-Application/Koeplay/releases) から `Koeplay_Setup_1.0.exe` をダウンロードして実行します。
2. VB-CABLE が未導入の場合だけ、「VB-CABLE を導入する」の項目が表示されます(既定でON)。
   導入画面が開いたら **「Install Driver」を押し、完了したら閉じて**ください。
3. 再起動が必要な場合は、インストーラーの最後に確認が出ます。再起動後に Koeplay が自動で起動します。

> **「WindowsによってPCが保護されました」と表示された場合**
> 署名していない実行ファイルのためです。「詳細情報」→「実行」で続けられます。

## 使い方

1. **Discord の設定**: 音声・ビデオ → 入力デバイスを **`CABLE Output (VB-Audio Virtual Cable)`** にします。
   あわせて **ノイズ抑制・エコー除去・自動音量調整を OFF** にします(BGM が途切れたり歪んだりします)。
2. Koeplay を起動します。ヘッダーが「VB-CABLE 検出済み」「ミキサー動作中」になっていれば準備完了です。
3. フォルダーを選んで、曲をダブルクリックで再生します。あなたの声と曲が Discord に届きます。
4. 自分でも曲を聞きたい時は、「MP3を自分にも聞く(モニター)」をオンにします。

**ご注意**

- Koeplay が止まっていると、Discord にマイクの声も届きません。ウィンドウを閉じてもトレイに常駐して動き続けます。完全に終了するには、トレイアイコンの「終了」を選びます。
- モニターを**スピーカー**で聞くと、マイクがその音を拾い、相手に曲が二重に聞こえます。**ヘッドホンの使用をおすすめ**します。

## 設定

メイン画面右上の「設定」から変更できます。

| タブ | 主な項目 |
|---|---|
| 音声デバイス | ホストAPI、マイク、Discordへの出力、モニター出力、サンプルレート、バッファ |
| ミキサー | 起動時の自動開始、モニター、マイクをモニターに混ぜる、リミッター |
| 再生 | リピート、シャッフル、自動で次へ |
| 一般 | 音声フォルダー、トレイ常駐、起動時にトレイへ最小化 |
| VB-CABLE | 検出状況、再検出、公式ページ、Discord の設定案内 |

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| 「VB-CABLE 未検出」と出る | 導入直後は Windows の再起動が必要です。再起動後に、設定 → VB-CABLE → 「再検出」を押してください |
| Discord に声が届かない | ① ヘッダーが「ミキサー動作中」か ② Discord の入力が `CABLE Output` か ③ 「マイクをDiscordへ送る」がオンか ④ 設定でマイクが正しく選ばれているか |
| 曲が自分に聞こえない | 「MP3を自分にも聞く」をオンにします。それでも聞こえない場合は、設定でモニター出力を指定してください。VB-CABLE の導入後に Windows の既定の出力が CABLE に切り替わることがあるため、元のスピーカーに戻してください |
| 音が途切れる・歪む | 設定のバッファを「安定重視」にする、ホストAPIを MME にする、Discord のノイズ抑制などを OFF にする、を順に試してください |
| 起動しない・エラーが出る | `%APPDATA%\Koeplay\error.log` を確認してください |

## ソースから実行・ビルド(開発者向け)

Python 3.13 で開発しています。

```powershell
# 準備
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 実行
python main.py

# EXE化(dist\Koeplay\Koeplay.exe ができます)
python -m PyInstaller --noconfirm --clean Koeplay.spec

# インストーラー化: Koeplay.iss を Inno Setup Compiler で開いて Compile
#   → dist_installer\Koeplay_Setup_1.0.exe
```

インストーラーを作る時は、公式サイトから取得した **`VBCABLE_Driver_Pack45.zip`**(https://vb-audio.com/Cable/)を `Koeplay.iss` と同じフォルダーに置いてください。
VB-Audio の配布条件があるため、このリポジトリには含めていません。

アイコンを作り直す場合は `python tools\make_icon.py` を実行します(`assets\icon.ico` と `assets\icon.png` が更新されます)。

### 構成

```
main.py                      起動、二重起動の防止、エラーログ
mp3player/
  config.py                  定数(アプリ名、バージョン、対応拡張子、保存先)
  settings.py                設定の読み書き
  devices.py                 デバイス一覧、マイクのみ表示、VB-CABLE 検出
  ring.py                    マイク/モニターの受け渡しバッファ
  source.py                  音声ファイルのデコード(PyAV / FFmpeg)
  engine.py                  ミキサー本体(マイク+音声 → CABLE、モニター)
  ui/                        画面(PySide6)
tools/make_icon.py           アイコンの生成
Koeplay.spec                 EXE化の設定(PyInstaller)
Koeplay.iss                  インストーラーの設定(Inno Setup)
```

## クレジットとライセンス

- **VB-CABLE** は [VB-Audio Software](https://vb-audio.com/) のドネーションウェアです(www.vb-cable.com)。
- 使用ライブラリ: PySide6(Qt)、PyAV(FFmpeg)、sounddevice(PortAudio)、NumPy。ライセンスは各プロジェクトに従います。
- Koeplay 本体のライセンスは現時点では設定していません。
