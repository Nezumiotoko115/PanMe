# PanMe IoT Demo System — STEP FINAL DEMO

Raspberry PiからI2CでPCA9685を制御し、16個のSG90を個別に動かすPythonプログラムです。
STEP3ではSTEP2の安全制御へ、Freenove FNK0078向けフルスクリーンUIとコンテスト用
デモフローを統合しています。Web API、NFC、MySQL、オンライン決済は含みません。

## STEP3でできること

```text
待機 → デモ認証 → ようこそ → 4×4商品一覧 → 商品詳細
     → ロッカー確認 → 非同期解錠 → 商品受取 → 非同期施錠
     → 利用完了 → 待機
```

- タッチを前提にした大きなボタンと4×4商品カード
- FNK0078の解像度に応じたフォント・余白調整
- デモ認証ユーザー「山田太郎」
- 16ロッカー分のJSON商品データ
- 売り切れ、使用中、ERROR、DISABLEDの選択禁止
- SG90動作中も止まらないローディング画面
- 安全状態だけに適用される60秒タイムアウト
- デモモード限定の右クリック認証
- UI操作のJSON Linesログ

## 採用ライブラリ

`adafruit-circuitpython-pca9685` と、そのLinux互換層である `adafruit-blinka` を
採用しました。PCA9685の初期化やI2C通信を信頼性のあるライブラリへ任せつつ、
角度・パルス幅・状態遷移はPanMe側の短いPythonコードで読めるためです。

- [Adafruit PCA9685公式ドキュメント](https://docs.circuitpython.org/projects/pca9685/en/latest/)
- [Raspberry PiでのBlinka導入ガイド](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/installing-circuitpython-on-raspberry-pi)

## ファイル構成

```text
panme_iot/
├── main.py                  UI起動／--cliで保守CLI
├── ui_main.py               UIとSTEP2制御層の組み立て
├── config.py                配線・角度・安全設定
├── hardware.py              PCA9685・サーボ制御・起動前診断
├── locker_manager.py        16室・状態モデル・操作キュー
├── logging_utils.py         端末・操作・UIイベントログ
├── ui/
│   ├── app.py               Tkinter画面
│   ├── controller.py        画面状態と利用フロー
│   └── services.py          デモ認証・商品取得
├── data/
│   └── demo_products.json   16商品のデモデータ
├── errors.py                エラーコード
├── requirements.txt         Pythonライブラリ
├── README.md
└── tests/
    └── test_locker.py       実機不要の自動テスト
```

UIは次のレイヤー構造でSTEP2と接続しています。

```text
PanMe UI / Web API / NFC
          ↓
    LockerManager
          ↓
    ServoController
          ↓
 PCA9685Controller
          ↓
    PCA9685 → SG90
```

UIはPCA9685を直接呼びません。`PanMeController → LockerManager`だけを使用します。

## GUIフレームワーク

Tkinterを採用しています。Python標準ライブラリで構造が理解しやすく、Raspberry Piで
軽量に動作し、FNK0078を通常のHDMI/DSIタッチディスプレイとしてフルスクリーン表示
できるためです。CustomTkinterやPySide6のような大型追加ランタイムは不要です。
Python 3.9以降を対象とし、Raspberry Pi OSの標準Python 3を推奨します。

## UIの起動

モックモードで起動する場合:

```bash
cd panme_iot
source .venv/bin/activate
python main.py
```

保守用CLI:

```bash
python main.py --cli
```

`Escape`でフルスクリーンを解除し、`F11`で切り替えられます。

## デモモード

`config.py`の初期値は次のとおりです。

```python
DEMO_MODE = True
MOCK_MODE = True
FULLSCREEN = True
SCREEN_TIMEOUT = 60
DEBUG_MODE = True
```

`DEMO_MODE=True`ではNFCやAPIを使わず、`DemoAuthentication`が次のユーザーを返します。

```text
user_id: 001
user_name: 山田太郎
student_id: 123456
authentication_method: DEMO
```

待機画面をタッチすると認証画面へ進み、もう一度タッチすると認証します。撮影時の
バックアップとして、待機または認証画面で右クリックしても認証できます。右クリックは
`DEMO_MODE=False`では無効です。

`MOCK_MODE=True`では画面フローとログだけが動き、SG90は動きません。配線・電源・角度を
実機で確認した後だけ`False`にしてください。

## FNK0078での表示

FNK0078をRaspberry Piへ接続し、Raspberry Pi OSのディスプレイ設定で推奨解像度と
タッチ入力を確認します。本UIは起動時の画面サイズを取得し、1024×600程度の16:9横長を
基準にフォントと余白を調整します。

デスクトップ上のターミナルから起動してください。

```bash
cd /path/to/PanMe/panme_iot
source .venv/bin/activate
python main.py
```

SSHだけのセッションで`no display name and no $DISPLAY environment variable`と表示された
場合は、Raspberry Piのデスクトップセッションから起動するか、正しい`DISPLAY`と
ユーザー権限を確認してください。

自動起動する場合は、最初に手動起動と安全終了を十分確認してから、Raspberry Pi OSの
デスクトップ自動起動へ次のコマンドを登録します。

```text
/absolute/path/to/panme_iot/.venv/bin/python /absolute/path/to/panme_iot/main.py
```

相対パスや`sudo`起動は避けてください。緊急時にUIを閉じられる方法と、サーボ外部電源を
遮断できる方法を必ず用意します。

## 画面タイムアウトとキャンセル

認証、ウェルカム、商品一覧、商品詳細、確認画面、完了画面は無操作60秒で待機画面へ
戻ります。解錠中、解錠済み、商品受取、扉閉鎖待ち、施錠中は安全のためタイムアウトを
無視します。商品一覧・詳細・確認までは戻れますが、解錠開始後はキャンセルできません。

## 商品データ

デモ商品は`data/demo_products.json`に16件あります。UIへ直接埋め込まず、
`DemoProductService`から取得します。在庫0は「売り切れ」、在庫1～2は「残りわずか」
として表示し、選択できません。将来は同じ`ProductService`インターフェースを実装する
`PanmeApiProductService`へ交換します。

## 認証・API・NFCの将来統合

UIは`AuthenticationService.authenticate()`だけを呼びます。STEP8では
`DemoAuthentication`を`NFCAuthentication`へ交換し、NFC UIDやAPI認証をサービス層で
処理できます。認証情報を画面コードへ埋め込む必要はありません。

PanMe API連携もUIへHTTP処理を書かず、`PanmeApiProductService`などのサービスを追加
します。認証・在庫・予約確認の成功後に既存`LockerManager`を呼ぶ構造を維持します。

## UIイベントログ

`logs/ui_events.jsonl`へ次を保存します。

- アプリ起動
- 認証成功
- 商品・ロッカー選択
- 解錠開始・成功
- 商品受取
- 施錠開始・成功
- エラー

画面には利用者向けの短いエラーだけを表示し、技術的なエラーコードと対象ロッカーは
ログへ保存します。STEP2の物理操作ログ`logs/locker_operations.jsonl`も継続します。

## STEP2の制御構造

- 起動時は16室をソフトウェア上で`LOCKED`にするだけで、サーボは動かしません。
- `initialize all`を明示実行した場合だけ、CH0からCH15を順番に施錠位置へ動かします。
- `unlock_locker()`と`lock_locker()`は内部のFIFOキューを必ず通ります。
- ワーカースレッドは1本だけなので、16台が同時に動きません。
- `ServoController`にも排他ロックがあり、チャンネルテストとの競合を防止します。
- 同じロッカーが待機中または動作中なら`LOCKER_BUSY`で重複を拒否します。
- ロッカーごとの角度補正は`LOCKER_ANGLES`へ追加できます。

各ロッカーは次の情報を持ちます。

```json
{
  "locker_id": "A-01",
  "channel": 0,
  "status": "LOCKED",
  "enabled": true,
  "last_action": "INITIALIZE_SOFTWARE",
  "last_action_time": "",
  "error": null
}
```

状態は`LOCKED`, `UNLOCKED`, `OPEN`, `CLOSED`, `ERROR`, `DISABLED`です。

## 最初はモックで確認

初期設定は `config.py` の `MOCK_MODE = True` です。この状態ではハードウェアを
動かさず、PCやRaspberry Piで制御フローを確認できます。

```bash
cd panme_iot
python3 main.py --cli
```

```text
> unlock A-01
> set_status A-01 OPEN
> set_status A-01 CLOSED
> status A-01
> lock A-01
> status all
> exit
```

扉センサーがないSTEP1では、次の操作で状態遷移も確認できます。

```text
> unlock A-01
> open A-01
> close A-01
> lock A-01
```

## Raspberry Piの準備

### 1. I2Cを有効化

Raspberry Piのターミナルで次を実行します。

```bash
sudo raspi-config
```

`Interface Options` → `I2C` → `Yes` を選択し、必要に応じて再起動します。現在の
公式手順も[Raspberry Pi公式設定ドキュメント](https://www.raspberrypi.com/documentation/configuration/computers/raspberry-pi.html#enable-or-disable-i2c)
で確認できます。

### 2. PCA9685を確認

```bash
sudo apt update
sudo apt install -y i2c-tools python3-venv python3-tk fonts-noto-cjk
i2cdetect -y 1
```

表の行`40`・列`0`に`40`と表示されれば、初期アドレス`0x40`で認識されています。
`--`の場合は電源、SDA/SCL、GND、I2C有効化、アドレスジャンパーを確認します。

### 3. Python環境を作成

```bash
cd panme_iot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. 実機モード

配線を再確認し、まずサーボホーンを機構から外した状態で、`config.py` を変更します。

```python
MOCK_MODE = False
```

その後に起動します。

```bash
python main.py --cli
```

権限エラーになる場合、最初に`ls -l /dev/i2c-1`でI2Cデバイスとグループを確認して
ください。常用時に安易に`sudo python`へ切り替えるのではなく、ユーザーのI2Cグループ
設定を確認します。

## 保守用CLIコマンド

| コマンド | 内容 |
|---|---|
| `unlock A-01` | A-01を解錠 |
| `lock A-01` | A-01を施錠 |
| `set_status A-01 OPEN` | 扉OPENを手動入力 |
| `set_status A-01 CLOSED` | 扉CLOSEDを手動入力 |
| `status A-01` | 1室の詳細情報 |
| `status all` | 16室を物理配置と同じ4×4で表示 |
| `disable A-01` | LOCKED状態のロッカーを無効化 |
| `enable A-01` | 有効化してLOCKEDへ戻す |
| `reset_error A-01` | PCA9685確認後にERRORを解除 |
| `initialize all` | 確認後、全室を順番に施錠位置へ初期化 |
| `test all` | 確認後、ID順に1室ずつ解錠・施錠 |
| `test channel` | 確認後、CH0～15をLOCK→UNLOCKで確認 |
| `queue` | 待機中・動作中ロッカーを表示 |
| `help` | コマンド一覧 |
| `exit` | 全PWMを停止して終了 |

`initialize all`、`test all`、`test channel`は`yes`と入力した場合だけ実行されます。
実際に全サーボを動かすため、ロッカー内部に人や物が挟まれない状態、十分な電源、
ホーン角度を確認してから実行してください。

## ローカル操作ログ

操作は既定で`logs/locker_operations.jsonl`へ追記されます。1行が1件のJSONなので、
テキストエディターで確認でき、将来APIやデータベースへ移行しやすい形式です。

```json
{"timestamp":"2026-07-27T10:00:00+09:00","locker_id":"A-01","action":"UNLOCK","status_before":"LOCKED","status_after":"UNLOCKED","channel":0,"angle":90,"result":"SUCCESS","error":null}
```

保存項目は日時、ID、操作、操作前後状態、CH、角度、結果、エラーです。
ログを止める場合は`OPERATION_LOG_ENABLED=False`にします。

## エラーと復旧

主なコードは`PCA9685_ERROR`, `I2C_ERROR`, `SERVO_ERROR`, `INVALID_LOCKER`,
`INVALID_CHANNEL`, `INVALID_ANGLE`, `LOCKER_BUSY`, `ALREADY_LOCKED`,
`ALREADY_UNLOCKED`, `LOCKER_DISABLED`, `LOCKER_ERROR`です。

サーボまたはI2C操作失敗時はロッカーを`ERROR`にし、通常操作を拒否します。
`reset_error A-01`はPCA9685の接続確認に成功した場合だけ、ソフトウェア状態を
`LOCKED`へ戻します。物理位置を動かす処理ではないため、復旧後は必要に応じて
安全確認の上で`initialize all`を使うか、対象ロッカーを個別点検してください。

## ロッカーとチャンネル

| ロッカー | CH | ロッカー | CH |
|---|---:|---|---:|
| A-01 | 0 | C-01 | 8 |
| A-02 | 1 | C-02 | 9 |
| A-03 | 2 | C-03 | 10 |
| A-04 | 3 | C-04 | 11 |
| B-01 | 4 | D-01 | 12 |
| B-02 | 5 | D-02 | 13 |
| B-03 | 6 | D-03 | 14 |
| B-04 | 7 | D-04 | 15 |

配線変更時は `config.py` の `LOCKER_CHANNELS` だけを編集します。

## 配線例

### Raspberry Pi → PCA9685

| Raspberry Pi 40ピン | PCA9685 | 用途 |
|---|---|---|
| 物理ピン1（3.3V） | VCC | PCA9685ロジック電源 |
| 物理ピン3（GPIO2/SDA1） | SDA | I2Cデータ |
| 物理ピン5（GPIO3/SCL1） | SCL | I2Cクロック |
| 物理ピン6（GND） | GND | 共通GND |

### PCA9685 → SG90

各CHへSG90のGND、V+、信号線を正しい向きで接続します。一般的な配色は茶/黒=GND、
赤=電源、橙/黄=信号ですが、必ず使用するSG90の仕様を確認してください。

### 電源に関する重要事項

- 16個のSG90をRaspberry Piの3.3V/5Vピンから給電しません。
- SG90側は、実測した最大電流と同時起動電流に余裕を持つ安定化5V外部電源を使います。
- 外部電源のプラスをPCA9685の`V+`、マイナスをサーボGNDへ接続します。
- Raspberry Pi、PCA9685、外部サーボ電源のGNDは共通化します。
- Raspberry Pi本体の電源とサーボ電源は分離し、逆流や極性間違いを防ぎます。
- 電源投入前にテスターで電圧と極性を確認し、ヒューズや非常停止も検討してください。

## 角度調整と安全設計

初期値は50Hz、施錠0度、解錠90度です。ただし、SG90の個体や機構によって安全範囲は
異なります。

1. サーボホーンをロック機構から外します。
2. `SERVO_MIN_PULSE`と`SERVO_MAX_PULSE`は初期値のまま、中央付近の角度から試します。
3. 異音、停止、発熱、過電流があれば直ちに電源を切ります。
4. 機械的な端まで押し続けない角度を確認してからホーンを取り付けます。
5. `LOCK_ANGLE`と`UNLOCK_ANGLE`を少しずつ調整します。

安全機能として、角度を0～180度に制限し、同じチャンネルの連続操作に待機時間を設け、
一括テストも1室ずつ実行します。`SERVO_HOLD_ENABLED=False`なら移動後にPWMを停止します。
保持力が必要な機構だけ`True`にし、電流と温度を監視してください。

## 自動テスト

```bash
cd panme_iot
python -m unittest discover -s tests -v
```

テストは偽のPCA9685を使い、16 ID/16 CH、起動時に動かないこと、解錠・施錠、
OPEN/CLOSED、無効化・有効化、エラー復旧、重複キュー拒否、一括初期化、
イベント、JSON Linesログ、4×4表示、安全確認を検証します。実機サーボは動きません。

## STEP2 実機テスト手順

一度に16台を接続せず、次の順番で増やしてください。

1. Raspberry Piを起動し、I2Cを有効化します。
2. `i2cdetect -y 1`で`0x40`を確認します。
3. 外部5V電源とGND共通化を確認します。
4. SG90をCH0へ1個だけ接続し、機構からホーンを外します。
5. `MOCK_MODE=False`にします。
6. `python main.py --cli`を起動します。起動しただけではサーボは動きません。
7. `lock A-01`は初期状態がLOCKEDなので`ALREADY_LOCKED`になることを確認します。
8. 安全を確認して`initialize all`ではなく、最初は`test channel`を避け、
   `unlock A-01`、`lock A-01`でCH0だけ確認します。
9. 角度と発熱を確認し、問題がなければCH1へ2個目を追加します。
10. A-02を同様に確認し、1台ずつCH15まで増やします。
11. 全台個別確認後に初めて`test all`を実行します。

途中で異音、拘束、発熱、電圧降下、Raspberry Pi再起動があれば直ちにサーボ電源を
切り、原因を解消してください。

## トラブルシューティング

### `0x40`が表示されない

I2C有効化、配線、VCC、GND、アドレスジャンパーを確認します。SDAとSCLの入れ替え、
サーボ電源だけ接続してロジックVCCが未接続、というケースにも注意します。

### `ModuleNotFoundError`

`.venv`を有効にしてから`python -m pip install -r requirements.txt`を再実行します。

### サーボが震える・Raspberry Piが再起動する

電源容量不足や電圧降下が疑われます。サーボ電源をRaspberry Piから分離し、太さと長さが
適切な配線、電源容量、GND共通化を確認します。

### 角度が逆・ロック機構に当たる

直ちに停止し、ホーンを外して`LOCK_ANGLE`と`UNLOCK_ANGLE`を安全な値から再調整します。
必要なら`config.py`の`LOCKER_ANGLES`でロッカー別角度を調整します。

### PWM解除後にロックが戻る

機構が保持力を必要としています。電流と発熱を確認した上で
`SERVO_HOLD_ENABLED=True`を検討するか、電力なしで保持できる機械設計に変更します。

## UI/APIからのプログラム呼び出し

STEP3のFNK0078 UIは、CLIを経由せず次の公開APIを呼び出しています。

```python
result = locker_manager.unlock_locker("A-01")
if result["success"]:
    print("解錠成功")
else:
    print(result["error_code"])
```

Web APIやNFCも`LockerManager`より上の層へ追加します。認証・在庫確認が成功した後だけ
`unlock_locker()`を呼ぶことで、ハードウェア制御コードを変更せず拡張できます。

UIを止めずに投入する場合は非同期APIを使用できます。

```python
ticket = locker_manager.enqueue_unlock("A-01")
if hasattr(ticket, "wait"):
    result = ticket.wait()
else:
    result = ticket  # LOCKER_BUSYなどの即時エラー
```

イベントは`locker_manager.subscribe(callback)`で受け取れます。現在は
`LOCKER_UNLOCKED`, `LOCKER_LOCKED`, `LOCKER_ERROR`, `LOCKER_DISABLED`,
`LOCKER_ENABLED`, `LOCKER_STATUS_CHANGED`を発行し、STEP3以降でUI更新やAPI通知へ
接続できます。

## STEP4 Web API連携

`DEMO_MODE=True` の既存デモはそのまま利用できます。`False` のときはPHP APIから認証、商品、在庫、ロッカー状態を取得し、APIの許可後だけ解錠します。再施錠に成功してから在庫と利用履歴をAPIで確定します。

設定、DBマイグレーション、API仕様、通信フロー、テスト手順は `../docs/STEP4_IOT_API.md` を参照してください。

## FINAL DEMO 統合版

### 正式版と旧版

正式なRaspberry Pi版はこの `panme_iot/` フォルダーです。ルートの `api/iot/` がPHP API、`database/002_iot_integration.sql` がDB追加定義です。

`iot-locker/` は以前のESP32/C++版であり、今回の起動対象ではありません。`tmp/` は管理者Web開発時の作業資料です。既存資料を保護するため削除・移動していません。

### 統合ファイル構成

```text
PanMe/
├── api/iot/                       PHP REST API
├── database/002_iot_integration.sql
├── scripts/provision_iot_device.php
├── docs/STEP4_IOT_API.md
└── panme_iot/
    ├── main.py                    UI / CLI / 診断の入口
    ├── config.py                  .envを読む共通設定
    ├── hardware.py                PCA9685 / サーボ / 起動前診断
    ├── locker_manager.py          状態モデル / 操作キューを含む
    ├── logging_utils.py           全ローカルログ
    ├── api_client.py
    ├── integration_services.py
    ├── ui_main.py
    ├── ui/
    ├── data/demo_products.json
    ├── deploy/panme-iot-demo.service
    ├── tests/
    ├── .env.example
    └── requirements.txt
```

UIはPCA9685を直接操作しません。`UI → ApiAuthorizedLockerService → LockerManager → ServoController → PCA9685Controller` の順に呼びます。Web DBもRaspberry Piから直接操作せずPHP APIだけを使用します。

### 必要環境

- Raspberry Pi OS 64-bit
- Python 3.9以上
- `python3-tk`、`python3-venv`、`i2c-tools`
- Freenove FNK0078
- PCA9685
- SG90 × 16
- 5V外部サーボ電源と共通GND

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk i2c-tools
cd ~/PanMe/panme_iot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### デモ当日の設定

設定は `panme_iot/.env` の1か所へまとめます。秘密を含む `.env` はGit管理対象外です。

#### 1. PC上の完全モック

```dotenv
PANME_DEMO_MODE=true
PANME_USE_API=false
PANME_MOCK_MODE=true
PANME_FULLSCREEN=false
PANME_DEBUG_MODE=true
```

#### 2. 最も確実なコンテスト実機デモ

デモユーザー・デモ商品を使い、SG90だけ実際に動かします。

```dotenv
PANME_DEMO_MODE=true
PANME_USE_API=false
PANME_MOCK_MODE=false
PANME_FULLSCREEN=true
PANME_DEBUG_MODE=false
PANME_DEMO_DECREASE_STOCK=false
```

#### 3. Web API統合デモ

認証表示はデモ、商品・在庫・履歴はWeb API、ロッカーは実機です。

```dotenv
PANME_DEMO_MODE=true
PANME_USE_API=true
PANME_MOCK_MODE=false
PANME_FULLSCREEN=true
PANME_DEBUG_MODE=false
PANME_DEMO_API_FALLBACK=true

PANME_API_BASE_URL=http://SERVER/PanMe
PANME_API_KEY=発行したデバイスキー
PANME_DEVICE_ID=PANME-LOCKER-01
PANME_USER_ID=1
```

`PANME_USER_ID` はDBに存在するデモ利用者IDです。画面には `PANME_DEMO_USER_NAME` を表示しますが、利用履歴はこのDB利用者へ安全に紐付きます。

`PANME_DEMO_API_FALLBACK=true` の場合、起動時にAPIへ接続できなければデモ商品へ退避します。この場合はDBの在庫・履歴を更新しません。API必須の試験では `false` にしてください。

### 起動方法

```bash
cd ~/PanMe/panme_iot
source .venv/bin/activate
python3 main.py --check
python3 main.py
```

つまり、通常は `python3 main.py` だけでFNK0078にUIが表示されます。`Esc` でフルスクリーン解除、`F11` で切替できます。デモモードでは待機・認証画面をタッチするか、マウス右クリックで認証を進められます。

### 画面デモ手順

1. 待機画面でタッチ
2. デモ認証
3. 「山田太郎さん、ようこそ」
4. 4×4商品一覧から在庫のある商品を選択
5. 詳細で「この商品を利用する」
6. 確認画面で「ロッカーを開ける」
7. API使用時は許可取得後、対象SG90が解錠位置へ移動
8. 「商品をお取りください」
9. 「商品を受け取りました」
10. 扉を閉じて「ロッカーを閉めました」
11. SG90が施錠位置へ移動
12. API使用時は在庫-1と利用履歴を同一DBトランザクションで確定
13. 完了画面から自動的に待機画面へ戻る

`PANME_DEMO_DECREASE_STOCK=false` ならデモJSONの在庫は減らず、アプリを終了せず同じ撮影を繰り返せます。本番DBの在庫をリセットする機能はありません。

### 16ロッカー対応

| ロッカー | CH | ロッカー | CH | ロッカー | CH | ロッカー | CH |
|---|---:|---|---:|---|---:|---|---:|
| A-01 | 0 | A-02 | 1 | A-03 | 2 | A-04 | 3 |
| B-01 | 4 | B-02 | 5 | B-03 | 6 | B-04 | 7 |
| C-01 | 8 | C-02 | 9 | C-03 | 10 | C-04 | 11 |
| D-01 | 12 | D-02 | 13 | D-03 | 14 | D-04 | 15 |

設定とPCA9685接続だけを確認し、サーボを動かさない診断:

```bash
python3 main.py --check
```

1台ずつ配線を確認する保守CLI:

```bash
python3 main.py --cli
```

CLIで `test channel` を入力し、安全確認へ `yes` と答えるとCH0〜15を順番に動かします。ロッカー単位は `unlock A-01`、`lock A-01` を使います。全16室の往復試験は `test all` です。一般利用者向けUIにこれらの操作は表示されません。

いきなり16台を接続せず、CH0の1台から始めて角度・電源・発熱を確認し、1台ずつ増やしてください。16台のSG90へRaspberry Piの5Vピンから給電してはいけません。

### API・DB準備

詳細は `../docs/STEP4_IOT_API.md` を参照してください。概要:

```bash
mysql -u root -p panme < ../database/002_iot_integration.sql
php ../scripts/provision_iot_device.php PANME-LOCKER-01 "PanMe Demo"
```

API疎通:

```bash
curl -H "X-Device-ID: PANME-LOCKER-01" \
     -H "X-API-Key: SECRET" \
     http://SERVER/PanMe/api/iot/status
```

利用完了後は `products.stock` が1減り、`usage_history`、`iot_transactions`、`iot_events` に記録されます。解錠失敗・在庫0・API拒否の場合は在庫を減らしません。

### Raspberry Pi自動起動

付属サービスのユーザー名とパスを実環境に合わせて編集します。

```bash
sudo cp deploy/panme-iot-demo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable panme-iot-demo.service
sudo systemctl start panme-iot-demo.service
sudo systemctl status panme-iot-demo.service
```

ログ確認:

```bash
journalctl -u panme-iot-demo.service -f
```

ハードウェア・設定・画面起動に失敗した場合は終了コード1となり、systemdが5秒後に再起動します。ロッカー操作中の画面タイムアウトは禁止されており、解錠状態のまま待機画面へ戻りません。

### ログ

- `logs/ui_events.jsonl`: 起動、API接続、認証、商品選択、解錠、受取、施錠、完了、エラー
- `logs/locker_operations.jsonl`: チャンネル、角度、状態遷移、実機操作結果
- API使用時の `iot_events`: サーバー側イベント
- `device_status_logs`: 起動状態と定期ハートビート

### トラブルシューティング

- `PCA9685_ERROR`: `i2cdetect -y 1` で `40`、SDA/SCL/VCC/GNDを確認
- サーボが震える・Piが再起動: 外部5V電源容量、太い配線、共通GND、電圧降下を確認
- APIがOFFLINE: URLにXAMPPの `/PanMe` が必要か、APIキー、デバイスID、Apache rewriteを確認
- 商品が空: `GET /api/iot/products` と `products.locker_number`、`lockers` の16IDを確認
- 画面が出ない: `DISPLAY=:0`、`python3-tk`、FNK0078のHDMI/USBタッチ接続を確認
- API必須なのにデモ商品へ切り替わる: `PANME_DEMO_API_FALLBACK=false` にして原因を表示

### 今後の認証

UIは `AuthenticationService.authenticate()` だけを呼びます。現在の `DemoAuthentication` または `DemoApiAuthenticationService` を、将来 `NFCAuthenticationService` / `QRAuthenticationService` に交換できます。LockerManager、UI画面、PCA9685制御を変更する必要はありません。

### 統合時の変更一覧

変更:

- `config.py`: `.env`によるデモ/API/実機の独立設定
- `ui_main.py`: デモ認証＋API商品＋実機制御の組み立て
- `integration_services.py`: デモ表示付きAPI認証
- `ui/services.py`: 繰り返し撮影用のデモ在庫設定
- `main.py`: `--check` と終了コード
- `.env.example`、`requirements.txt`、本README

新規:

- `hardware.py` 内のサーボ非動作診断
- `deploy/panme-iot-demo.service`
- STEP4で追加したPHP API、DBマイグレーション、API仕様書

削除・アーカイブ:

- なし
