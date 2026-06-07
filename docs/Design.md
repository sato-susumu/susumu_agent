# susumu_agent 設計ドキュメント

---

## 目次

- [1. システム概要](#1-システム概要)
- [2. 仕様](#2-仕様)
  - [2.1 動作モード](#21-動作モード)
  - [2.2 ロボット能力定義](#22-ロボット能力定義)
  - [2.3 ツール一覧](#23-ツール一覧)
  - [2.4 自然言語解釈ルール](#24-自然言語解釈ルール)
  - [2.5 安全仕様](#25-安全仕様)
  - [2.6 入出力インターフェース](#26-入出力インターフェース)
- [3. アーキテクチャ](#3-アーキテクチャ)
  - [3.1 全体構成図](#31-全体構成図)
  - [3.2 コンポーネント一覧](#32-コンポーネント一覧)
  - [3.3 データフロー](#33-データフロー)
  - [3.4 スレッドモデル](#34-スレッドモデル)
- [4. 実装](#4-実装)
  - [4.1 ファイル構成](#41-ファイル構成)
  - [4.2 設定ファイル（config.yaml）](#42-設定ファイルconfigyaml)
  - [4.3 依存パッケージ](#43-依存パッケージ)
  - [4.4 LLM・ADK 設計](#44-llmadk-設計)
  - [4.5 システムプロンプト設計](#45-システムプロンプト設計)
  - [4.6 コードアーキテクチャ](#46-コードアーキテクチャ)
- [5. 運用](#5-運用)
  - [5.1 起動方法](#51-起動方法)
  - [5.2 デプロイ](#52-デプロイ)
  - [5.3 ログ・デバッグ](#53-ログデバッグ)
  - [5.4 テスト戦略](#54-テスト戦略)
  - [5.5 モデル更新フロー](#55-モデル更新フロー)
  - [5.6 コスト管理](#56-コスト管理)
- [6. 拡張・制約](#6-拡張制約)
  - [6.1 将来拡張の方針](#61-将来拡張の方針)
  - [6.2 プライバシー・倫理](#62-プライバシー倫理)
  - [6.3 フィールド運用オプション](#63-フィールド運用オプション)
  - [6.4 未決事項](#64-未決事項)

---

## 1. システム概要

自然言語（日本語・英語）でロボットを制御するシステム。
ユーザーが「ゆっくり前進して」「右に90度回転して」などと入力すると、
LLM がコマンドを解釈してロボットへの動作指令に変換する。

**技術スタック：**

| 要素 | 採用技術 |
|---|---|
| エージェントフレームワーク | Google ADK（`google-adk>=2.1.0`） |
| LLM（デフォルト） | Gemini 2.5 Flash（Vertex AI） |
| LLM（オプション） | Claude on Vertex AI（Model Garden で有効化が必要） |
| ロボット制御 | ROS2（`/cmd_vel` トピックへ Twist をパブリッシュ） |
| 言語 | Python 3.10+ |
| パッケージ管理 | uv |

---

## 2. 仕様

### 2.1 動作モード

`config.yaml` の `robot.mode` で切り替える。

| モード | ROS2 | ロボット指令 | 用途 |
|---|---|---|---|
| `simulate` | 不要 | MockRobot がログ表示 | 開発・動作確認（デフォルト） |
| `real` | 必要 | `/cmd_vel` に Twist をパブリッシュ | 実機運用 |
| `dry_run` | 不要 | なし（LLM のみ動かす） | プロンプト調整 |

```mermaid
flowchart TD
    Start["起動"]
    Config{"config.yaml\nrobot.mode"}
    Simulate["simulate\nROS2 不要 / MockRobot"]
    Real["real\nROS2 必要 / /cmd_vel"]
    DryRun["dry_run\nLLM のみ / ロボット指令なし"]
    ADK{"Google ADK\n利用可能？"}
    UseADK["ADK + LLM\n自然言語処理"]
    RuleBased["ルールベース\n（ADK なし）"]

    Start --> Config
    Config -->|simulate| Simulate
    Config -->|real| Real
    Config -->|dry_run| DryRun
    Simulate & Real & DryRun --> ADK
    ADK -->|Yes| UseADK
    ADK -->|No| RuleBased
```

---

### 2.2 ロボット能力定義

**対応コマンド（ホワイトリスト）：**

| 操作 | パラメータ | 例 |
|---|---|---|
| 前進 | speed / duration_sec | 「ゆっくり3秒前進」 |
| 後退 | speed / duration_sec | 「少し後退して」 |
| 停止 | — | 「止まれ」 |
| 旋回 | angle_deg / speed | 「右に90度回転」 |
| シーケンス | 複数ステップ | 「三角形を描いて」 |
| カメラ確認 | question | 「前方に何がある？」 |
| 状態確認 | — | 「今動いてる？」 |
| 直前コマンド参照 | — | 「さっきと同じ動きを」 |
| マクロ登録・実行 | name / steps | 「この動きをAとして登録」 |

**速度マッピング（`capabilities.py` の `RobotCapabilities.SPEED_MAP` が唯一の定義源）：**

| speed | キーワード例 | linear (m/s) | angular (rad/s) |
|---|---|---|---|
| `low` | ゆっくり / ゆったり / slowly | 0.1 | 0.3 |
| `medium` | 指定なし（デフォルト） | 0.3 | 0.8 |
| `high` | 素早く / 速く / fast | 0.5 | 1.5 |

**旋回 duration の計算：**

```
duration_sec = abs(radians(angle_deg)) / angular_vel
```

旋回精度は角速度×時間の理論値。スリップ・摩擦による誤差があり、精度が必要な場合はエンコーダーフィードバックを別途実装すること。

**対応しないコマンド（`report_unsupported` を呼ぶ）：**

| 例 | 理由 |
|---|---|
| 「コップを取って」 | マニピュレーター未定義 |
| 「充電ステーションへ戻って」 | 自律ナビゲーション未定義 |
| 「地図を作って」 | SLAM 未定義 |
| 「人を追いかけて」 | 安全・倫理ルール違反 |

---

### 2.3 ツール一覧

LLM が Function Calling で呼び出す 8 ツール。`tools.py` の `RobotTools` クラスに実装。

| # | ツール | シグネチャ | 役割 |
|---|---|---|---|
| 1 | `move_robot` | `(direction, speed, duration_sec)` | 直進・後退・停止 |
| 2 | `rotate_robot` | `(angle_deg, speed)` | 旋回（duration はコード側で計算） |
| 3 | `execute_sequence` | `(steps: list[MoveStep\|RotateStep])` | 複数ステップ連続実行・進捗追跡 |
| 4 | `observe` | `(question, sensor)` | カメラ画像取得（解析は LLM が行う） |
| 5 | `query_status` | `()` | 現在の移動状態 |
| 6 | `query_last_command` | `()` | 直前コマンド参照 |
| 7 | `manage_macro` | `(action, name, steps)` | マクロ登録・実行・削除・一覧 |
| 8 | `report_unsupported` | `(reason)` | 能力範囲外を通知 |

ツールのパラメータ境界値：

| パラメータ | 許容範囲 | 超過時 |
|---|---|---|
| `speed` | `low` / `medium` / `high` のみ | ADK スキーマ違反で拒否 |
| `direction` | `forward` / `backward` / `stop` のみ | ADK スキーマ違反で拒否 |
| `duration_sec` | 0.1〜30.0 秒 | clamp（上限30秒） |
| `angle_deg` | -360〜+360 度 | clamp |

---

### 2.4 自然言語解釈ルール

**速度キーワード：**

| speed | キーワード |
|---|---|
| `low` | ゆっくり / ゆったり / ちょっとずつ / ちょい / そろそろ / のんびり / 少し / slowly / gently |
| `medium` | 普通 / 通常 / 指定なし |
| `high` | 素早く / 速く / ダッシュ / 全力 / 急いで / fast / quickly |

**時間・距離変換：**

| 入力 | 変換 |
|---|---|
| 「3秒前進」 | `duration_sec = 3.0` |
| 「50cm前進」 | `duration = 0.5 / speed_linear` 秒 |
| 「1メートル動いて」 | `duration = 1.0 / speed_linear` 秒 |
| 「3歩分進んで」 | 1歩 = 0.5m として計算 |
| 指定なし | `duration_sec = 2.0` |

**コンテキスト参照：**

| 入力 | 解釈 |
|---|---|
| 「さっきと同じ動きを」 | `query_last_command()` で再実行 |
| 「逆方向に戻って」 | 直前 direction を反転 |
| 「同じ速さでもっと長く」 | 直前 speed 保持・duration_sec を2倍 |

**曖昧指示：**

| 入力パターン | 解釈 |
|---|---|
| 「もうちょっと」「少し」 | speed=`low`, duration_sec=1.0 |
| 「さっきより速く」 | 直前 speed を1段階上げる |
| 解釈不能な相対指示 | 「どのくらいですか？」と確認 |

条件付き指示（「〜なければ〜して」）は `report_unsupported` を呼ぶ。
日本語・英語・ローマ字・口語・敬語・命令形すべてを受け付ける。

---

### 2.5 安全仕様

**3重安全レイヤー：**

```mermaid
flowchart LR
    Input["ユーザー入力"]

    subgraph "層1: 緊急キーワード検出"
        EK["ストップ / 止まれ / stop 等\n→ LLM を経由せず即時停止"]
    end

    subgraph "層2: Watchdog"
        WD["最後のコマンドから5秒経過\n→ 自動で zero_twist()"]
    end

    subgraph "層3: ロボット側安全機構"
        HW["ハードウェア・ファームウェア\nレベルの安全機能"]
    end

    Input --> EK
    EK -->|"stop_event.set()"| WD
    WD --> HW
```

| レイヤー | 仕組み | 発動条件 |
|---|---|---|
| ① 緊急停止 | `stop_event`（threading.Event） | 「ストップ」「止まれ」等のキーワード |
| ② Watchdog | 最終コマンド時刻監視 | 5秒間コマンドなし |
| ③ 外部安全機構 | ハードウェア・ファームウェア | 障害物・転倒等 |

**倫理ガードレール（システムプロンプト最優先）：**

1. 人物・動物への突進・追跡指示 → `report_unsupported`
2. 「壊して」「ぶつけて」「攻撃して」等の破壊的指示 → `report_unsupported`
3. 緊急停止を無効化する指示 → `report_unsupported`

---

### 2.6 入出力インターフェース

**入力：** テキスト（CLI）または音声（voice/ モジュール経由）

**フィードバック：**

| タイミング | 内容 |
|---|---|
| コマンド受信直後 | 「考え中...」 |
| ツール実行開始時 | 「前進中（0.1 m/s）...」 |
| ツール完了時 | 「前進しました（2秒間）」 |
| 緊急停止時 | 「緊急停止しました」 |
| エラー時 | 「エラー：{日本語説明}」 |

**起動時メッセージ：** `help` / 「ヘルプ」 で LLM を経由せず能力一覧を表示。

**verbosity 設定：**

| 設定値 | 返答スタイル |
|---|---|
| `brief` | 「了解」「前進します」など極短文 |
| `normal` | 速度・時間を含む1〜2文（デフォルト） |
| `verbose` | 実行内容・速度・時間・完了後の状態を詳述 |

---

## 3. アーキテクチャ

### 3.1 全体構成図

```mermaid
graph TD
    User["👤 ユーザー入力\n（テキスト / 音声）"]
    Emergency["🛑 緊急停止\n即時実行 / LLM経由なし"]
    ADK["🤖 Google ADK\nLlmAgent"]
    Tools["🔧 RobotTools\n8ツール"]
    Robot["🦾 RobotInterface"]
    Mock["💻 MockRobot\nsimulate モード"]
    ROS2["🤖 ROS2Robot\n/cmd_vel"]
    State["📊 SharedState\nスレッドセーフ"]
    Watchdog["⏱️ Watchdog\n5秒タイムアウト"]
    Camera["📷 CameraClient\n画像取得"]
    Macro["💾 MacroStore\nmacros.json"]
    Session["📝 SessionStore\nJSONL ログ"]

    User -->|"緊急キーワード"| Emergency
    User -->|"通常コマンド"| ADK
    Emergency --> State
    ADK -->|"Function Calling"| Tools
    Tools --> Robot
    Tools --> State
    Tools --> Macro
    Tools --> Session
    Tools --> Camera
    Robot --> Mock
    Robot --> ROS2
    State --> Watchdog
    Watchdog -->|"無通信5秒で停止"| State
```

---

### 3.2 コンポーネント一覧

| コンポーネント | ファイル | 責務 |
|---|---|---|
| エントリポイント | `main.py` | 入力ループ・緊急停止検出・ADK Runner 起動 |
| ADK エージェント | `agent.py` | LlmAgent 定義・モデル設定 |
| ツール実装 | `tools.py` | 8ツール（RobotTools クラス） |
| 能力・定数定義 | `capabilities.py` | 速度定数・プロンプト自動生成（RobotCapabilities クラス） |
| 共有状態 | `shared_state.py` | SharedState シングルトン・スレッド安全な状態管理 |
| Watchdog | `watchdog.py` | 無通信タイムアウト監視・自動停止 |
| カメラ | `camera.py` | Image Subscriber・base64変換・鮮度チェック |
| セッション管理 | `session_store.py` | セッション履歴・コマンドログ JSONL |
| マクロ管理 | `macro_store.py` | マクロ登録・読み込み（macros.json） |
| ROS2 ロガーブリッジ | `ros_logger.py` | loguru → rclpy.logging（RosLogger クラス） |
| ロボット抽象 | `robot/interface.py` | RobotInterface 抽象クラス |
| 実機実装 | `robot/ros2_robot.py` | ROS2 / Twist パブリッシュ |
| モック実装 | `robot/mock_robot.py` | simulate / dry_run モード用 |
| デバッグ CLI | `debug_tools.py` | LLM なしでツールを直接テスト |
| デモノード | `demo_node.py` | turtlesim 自動デモ・録画・字幕生成 |

---

### 3.3 データフロー

**通常コマンド：**

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant Main as main.py
    participant ADK as Google ADK / LlmAgent
    participant Tool as RobotTools
    participant Robot as RobotInterface
    participant State as SharedState

    User->>Main: "ゆっくり前進"
    Main->>Main: 緊急キーワード判定 → 該当なし
    Main->>ADK: run_async()
    ADK->>ADK: "ゆっくり" → speed=low / "前進" → direction=forward
    ADK->>Tool: move_robot("forward", "low", 2.0)
    Tool->>State: stop_event 確認
    Tool->>Robot: move("forward", "low", 2.0)
    Robot-->>Tool: 完了
    Tool-->>ADK: {status: ok, linear_x: 0.1, duration_sec: 2.0}
    ADK-->>Main: "低速で2.0秒前進しました。"
    Main-->>User: 低速で2.0秒前進しました。
```

**緊急停止：**

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant Main as main.py
    participant State as SharedState

    Note over Main: LLM処理中・移動中いつでも発動
    User->>Main: "ストップ"
    Main->>State: stop_event.set()
    Main->>Robot: stop()
    Note over State: Watchdog が zero_twist() を送信
```

**observe フロー：**

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant ADK as Google ADK / LlmAgent
    participant CB as before_model_callback
    participant Tool as observe()
    participant Camera as CameraClient

    User->>ADK: "前方に障害物はある？"
    ADK->>Tool: observe(question="...")
    Tool->>Camera: get_latest_image()
    alt 正常（1秒以内のフレーム）
        Camera-->>Tool: {status:"ok", image_base64:"..."}
        Note over Tool: _pending_image_parts に画像 Part を保持
        Tool-->>ADK: {status:"ok"} （dict のみ返す）
        Note over ADK: 次回 LLM 呼び出し前に before_model_callback 発火
        ADK->>CB: llm_request
        CB->>CB: pop_pending_image_parts()
        CB-->>ADK: contents に Content(role="user", parts=[text, image]) を追加
        ADK-->>User: "前方に段差が見えます..."
    else カメラ未接続
        Camera-->>Tool: {status:"error"}
        ADK-->>User: "カメラが接続されていません"
    else フレームが古い（>1秒）
        Camera-->>Tool: {status:"stale"}
        ADK-->>User: "最新の画像を取得できませんでした"
    end
```

---

### 3.4 スレッドモデル

**スレッド構成：**

| スレッド | 役割 |
|---|---|
| メインスレッド | 入力ループ・緊急停止検出・ADK Runner（asyncio） |
| ROS2スレッド | `rclpy.spin()` + 20Hz cmd_vel パブリッシュ |
| Watchdogスレッド | 無通信タイムアウト監視（daemon=True） |

**共有状態の保護：**

| 変数 | 保護方法 |
|---|---|
| `current_twist` | `threading.Lock` で read/write を保護 |
| `last_command_time` | `threading.Lock` で保護 |
| `stop_event` | `threading.Event`（スレッドセーフ） |
| `shutdown_event` | `threading.Event`（スレッドセーフ） |

**stop_event のライフサイクル：**

```mermaid
stateDiagram-v2
    [*] --> 未セット
    未セット --> セット済み : 緊急停止入力 / Watchdog
    セット済み --> 未セット : zero_twist() 送信後に clear
    セット済み --> [*] : プログラム終了
```

**シャットダウン順序：**

```mermaid
flowchart LR
    A["Ctrl+C"] --> B["shutdown_event.set()"]
    B --> C["Watchdog スレッド終了\ndaemon=True"]
    B --> D["ADK Runner キャンセル"]
    D --> E["rclpy.shutdown()"]
    E --> F["ROS2 スレッド終了"]
    F --> G["プロセス終了"]
```

**execute_sequence の割り込み：**

```python
for step in steps:
    if stop_event.is_set():   # 各ステップ開始前にチェック
        break
    execute_step(step)
```

---

## 4. 実装

### 4.1 ファイル構成

```
susumu_agent/
├── config.yaml               # 全設定（トピック・モデル・モード等）
├── pyproject.toml            # 依存定義（uv 管理）
├── .env                      # 認証情報（gitignore 対象）
├── .env.sample               # .env テンプレート
├── debug/                    # デバッグ出力先（gitignore 対象）
│   ├── {ts}_susumu_agent.log
│   ├── {ts}_command_log.jsonl
│   ├── {ts}_demo_labels.jsonl
│   ├── {ts}_turtlesim_raw.mp4
│   ├── {ts}_turtlesim.srt
│   ├── {ts}_turtlesim.mp4
│   └── {ts}_turtlesim.gif
├── launch/
│   ├── mock.launch.py
│   ├── mock_debug.launch.py
│   ├── real.launch.py
│   ├── real_debug.launch.py
│   ├── turtlesim.launch.py
│   ├── turtlesim_debug.launch.py
│   ├── turtlesim_demo.launch.py
│   └── turtlesim_demo_debug.launch.py
├── tests/
│   ├── unit/                 # ROS2 不要の単体テスト（pytest）
│   ├── mock/                 # MockRobot 使用（未実装）
│   └── golden/               # 実 LLM・週1回（未実装）
└── susumu_agent/
    ├── main.py               # 入力ループ・緊急停止・フィードバック表示
    ├── agent.py              # AgentFactory / LlmAgent 定義
    ├── tools.py              # RobotTools（8ツール実装）
    ├── capabilities.py       # RobotCapabilities（速度定数・プロンプト生成）
    ├── shared_state.py       # SharedState シングルトン
    ├── watchdog.py           # Watchdog
    ├── camera.py             # CameraClient
    ├── session_store.py      # SessionStore
    ├── macro_store.py        # MacroStore
    ├── demo_node.py          # DemoRunner（turtlesim 自動デモ）
    ├── debug_tools.py        # DebugRunner（LLM なし直接テスト CLI）
    ├── ros_logger.py         # RosLogger（loguru → ROS2 ブリッジ）
    ├── turtlesim_recorder.py # TurtlesimRecorder（ffmpeg x11grab）
    ├── voice/
    │   ├── recognizer.py     # BaseSpeechRecognizer 抽象クラス
    │   └── synthesizer.py    # BaseSynthesizer 抽象クラス
    └── robot/
        ├── interface.py      # RobotInterface 抽象クラス
        ├── ros2_robot.py     # ROS2Robot
        └── mock_robot.py     # MockRobot
```

---

### 4.2 設定ファイル（config.yaml）

```yaml
robot:
  namespace: ""                   # 複数台時は "/robot_a" 等を設定
  cmd_vel_topic: "/cmd_vel"
  image_topic: "/camera/image_raw"
  battery_topic: ""               # 空の場合は無視
  battery_low_threshold: 20
  battery_critical_threshold: 10
  watchdog_timeout_sec: 5.0
  max_duration_sec: 30.0
  max_angle_deg: 360.0
  ramp_down_enabled: true
  ramp_down_steps: 5
  mode: "simulate"                # real / simulate / dry_run
  compliance_mode: false
  human_presence_max_speed: 0.25
  offline_fallback: true

llm:
  model: "gemini-2.5-flash"       # gemini-2.5-flash / gemini-2.5-pro / claude-sonnet-4-5@20250514
  project: "your-project-id"
  location: "asia-northeast1"
  backend: "vertex_ai"
  timeout_sec: 5
  timeout_observe_sec: 10
  retry_max: 1
  backoff_base_sec: 1.0

interface:
  language: "auto"                # ja / en / auto
  verbosity: "normal"             # brief / normal / verbose
  feedback_modes: ["text"]
  camera_send_to_cloud: true

auth:
  mode: "none"                    # none / single_token / multi_user
  token: ""

cost_control:
  daily_command_limit: 500
  daily_observe_limit: 50
  alert_threshold_usd: 10.0
```

**変更時の影響局所化：**

| 変更内容 | 変更箇所 |
|---|---|
| モデル文字列の更新 | `config.yaml` の `llm.model` 1行のみ |
| ROS2 トピック変更 | `config.yaml` の `robot.cmd_vel_topic` 1行のみ |
| 速度パラメータ調整 | `capabilities.py` の `RobotCapabilities.SPEED_MAP` のみ |
| 緊急停止キーワード追加 | `capabilities.py` の `RobotCapabilities.EMERGENCY_KEYWORDS` のみ |

---

### 4.3 依存パッケージ

**pyproject.toml（`uv sync` でインストール）：**

| パッケージ | バージョン | 用途 |
|---|---|---|
| `google-adk` | `>=2.1.0,<3.0.0` | ADK 本体 |
| `anthropic[vertex]` | `>=0.50.0,<1.0.0` | Claude on Vertex AI |
| `google-cloud-aiplatform` | `>=1.90.0,<2.0.0` | Vertex AI 認証 |
| `opencv-python` | `>=4.9.0,<5.0.0` | カメラ画像処理 |
| `pyyaml` | `>=6.0,<7.0` | 設定ファイル読み込み |
| `loguru` | `>=0.7.0,<1.0.0` | ログ出力 |
| `python-dotenv` | `>=1.0.0,<2.0.0` | .env 読み込み |

**ROS2 付属（pip 不可）：**

| パッケージ | 取得方法 |
|---|---|
| `rclpy` | ROS2 インストール済み環境 |
| `geometry_msgs` | ROS2 インストール済み環境 |
| `sensor_msgs` | ROS2 インストール済み環境 |

`pyproject.toml` にメジャーバージョン上限付きで依存を定義し、`uv.lock` で再現可能ビルドを保証。週1回 `pip-audit` でセキュリティ脆弱性チェックを実施。

---

### 4.4 LLM・ADK 設計

**モデル設定（`config.yaml` の `llm.model` で一元管理）：**

| モデル | 前提 |
|---|---|
| `gemini-2.5-flash`（デフォルト） | Vertex AI 有効化のみ |
| `gemini-2.5-pro` | Vertex AI 有効化のみ |
| `claude-sonnet-4-5@20250514` | Vertex AI Model Garden で Claude を有効化 |

Claude を使う場合は `agent.py` が `LLMRegistry.register(Claude)` を自動実行する。

**認証（.env ファイルで管理）：**

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
```

`agent.py` が `load_dotenv()` で読み込み、`GOOGLE_GENAI_USE_VERTEXAI=TRUE` は自動設定される。

**ADK 固有の実装方針：**

- 全ツールを `async def` で実装。`duration` の待機は `asyncio.sleep` を使用（イベントループをブロックしない）
- `runner.run_async()` でストリーミング実行し、`tool_call` イベントをフィードバック表示に活用
- `LLMRegistry.register(Claude)` はモジュールロード時（`agent.py` 先頭）に実行

**カメラ画像の LLM への渡し方：**

Vertex AI Gemini は `FunctionResponse.parts` に `inline_data` を付けることを非対応（`400 INVALID_ARGUMENT`）。
代わりに `before_model_callback` で `llm_request.contents` に `Content(role="user", parts=[image_part])` を追加する方式を採用。

```
observe() → RobotTools._pending_image_parts に画像 Part を保持
          → before_model_callback が pop して llm_request.contents に追加
          → LLM が画像を user Content として受け取り解析
```

`InMemorySessionService` の `_copy_session` が `copy.deepcopy(session)` を呼ぶため、
session state に大きなバイナリを保持するとハングする（ADK issue #3064）。
`tools` インスタンス変数で保持することでこの問題を回避している。

**ROS2 QoS 設定：**

```python
qos = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
```

安全機構側のサブスクライバーとの QoS 互換性を実装時に確認すること。

---

### 4.5 システムプロンプト設計

`capabilities.py` の `RobotCapabilities.build_system_prompt()` が唯一の定義源。
定数（SPEED_MAP 等）を変更するとプロンプトに自動反映される。

**プロンプト優先順位：**

```
1. 安全・倫理ルール（最優先・絶対）
2. できること（能力ホワイトリスト）
3. できないこと
4. 解釈ルール（速度・時間・距離・言語）
5. 返答フォーマット
```

---

### 4.6 コードアーキテクチャ

**`RobotInterface` で ROS2 への依存を逆転：**

```
robot/
├── interface.py    # 抽象クラス（ROS2 依存ゼロ）
├── ros2_robot.py   # 実機実装
└── mock_robot.py   # simulate / dry_run モード用
```

**`SharedState` クラスで全共有変数を集約（シングルトン）：**

```python
@dataclass
class SharedState:
    _twist: TwistValue
    _lock: threading.Lock
    stop_event: threading.Event
    shutdown_event: threading.Event
    last_command: dict | None

    @classmethod
    def instance(cls) -> SharedState: ...
```

**`RobotCapabilities` クラスで定数・ロジックを集約：**

```python
class RobotCapabilities:
    SPEED_MAP: dict            # 速度定数の唯一の定義源
    EMERGENCY_KEYWORDS: frozenset
    SPEED_KEYWORDS: dict

    @classmethod
    def clamp_duration(cls, value: float) -> float: ...
    @classmethod
    def build_system_prompt(cls, ...) -> str: ...
```

---

## 5. 運用

### 5.1 起動方法

```bash
# シミュレーション（ROS2 不要）
python3 -m susumu_agent.main

# 設定ファイルを指定
python3 -m susumu_agent.main /path/to/config.yaml

# ROS2 launch（通常）
ros2 launch susumu_agent mock.launch.py
ros2 launch susumu_agent real.launch.py
ros2 launch susumu_agent turtlesim.launch.py
ros2 launch susumu_agent turtlesim_demo.launch.py

# ROS2 launch（デバッグ：ログ・録画を debug/ に保存）
ros2 launch susumu_agent mock_debug.launch.py
ros2 launch susumu_agent real_debug.launch.py
ros2 launch susumu_agent turtlesim_demo_debug.launch.py

# LLM なしでツールを直接テスト
python3 -m susumu_agent.debug_tools move forward medium 2.0
python3 -m susumu_agent.debug_tools rotate 90 medium
python3 -m susumu_agent.debug_tools sequence square
python3 -m susumu_agent.debug_tools --real --cmd-vel-topic /turtle1/cmd_vel move forward medium 2.0
```

---

### 5.2 デプロイ

systemd サービス化により電源 ON で自動起動・クラッシュ時自動再起動。
GCP 資格情報は `/etc/robot_nl/secrets.env`（`chmod 600`）で管理。

**障害・リカバリ：**

```mermaid
flowchart TD
    A["起動"] --> B{"ROS2ノード ready?"}
    B -->|"未起動"| C["5秒待ちリトライ×3 → 失敗で終了"]
    B -->|"OK"| D{"Vertex AI 疎通確認"}
    D -->|"失敗"| E["オフラインモードで起動"]
    D -->|"OK"| F["通常動作"]
```

| 障害 | 対応 |
|---|---|
| Vertex AI タイムアウト | 再試行1回 → エラー通知 → ロボット停止 |
| Vertex AI 完全障害 | オフラインモード（キーワードマッチのみ） |
| ROS2 ノード未起動 | 起動失敗で終了 |
| カメラ切断 | observe のみ失敗、移動は継続 |

**オフラインモード（Vertex AI 障害時）：** LLM を使わずキーワードマッチで停止・前進・後退のみ受け付ける。

---

### 5.3 ログ・デバッグ

**ログレベル：**

| レベル | 記録内容 |
|---|---|
| `INFO` | ユーザー入力・ツール名・応答テキスト・cmd_vel 値 |
| `DEBUG` | LLM 生レスポンス・パラメータ詳細・レイテンシ |
| `WARNING` | clamp 発動・stale カメラ・再試行 |
| `ERROR` | API エラー・ROS2 エラー・タイムアウト |

**デバッグモード出力ファイル（`debug/` フォルダ）：**

| ファイル | 内容 |
|---|---|
| `{ts}_susumu_agent.log` | loguru ログ（通常ノード） |
| `{ts}_susumu_agent_demo.log` | loguru ログ（デモノード） |
| `{ts}_command_log.jsonl` | ツール呼び出し履歴 |
| `{ts}_demo_labels.jsonl` | 指示・応答のラベル情報（デモ時のみ） |
| `{ts}_turtlesim_raw.mp4` | turtlesim 元録画（デモ時のみ） |
| `{ts}_turtlesim.srt` | 字幕ファイル・日本語＋英語（デモ時のみ） |
| `{ts}_turtlesim.mp4` | 字幕付き動画（デモ時のみ） |
| `{ts}_turtlesim.gif` | アニメーション GIF・480px（デモ時のみ） |

```bash
# debug_dir を変更して起動
ros2 launch susumu_agent turtlesim_demo_debug.launch.py debug_dir:=/tmp/mydbg
```

**構造化ログ形式（command_log.jsonl）：**

```json
{"ts": "2026-06-07T12:34:56", "level": "INFO", "event": "tool_call", "tool": "move_robot", "params": {"direction": "forward", "speed": "low", "duration_sec": 2.0}}
{"ts": "2026-06-07T12:35:00", "level": "INFO", "event": "tool_result", "status": "ok", "latency_ms": 1823}
{"ts": "2026-06-07T12:35:01", "level": "WARN", "event": "clamp", "param": "duration_sec", "original": 99.0, "clamped": 30.0}
```

---

### 5.4 テスト戦略

```mermaid
flowchart LR
    A["Layer 1\nPython のみ"] --> B["Layer 2\nLLM モック"] --> C["Layer 3\n実 Vertex AI"]
```

| レイヤー | 環境 | テスト内容 | 頻度 |
|---|---|---|---|
| Layer 1 | Python のみ（ROS2 不要） | 速度マッピング・duration 計算・clamp・バリデーション | PR 毎 |
| Layer 2 | Python + LLM モック | ツール呼び出し名・report_unsupported 判定 | PR 毎 |
| Layer 3 | 実 Vertex AI | 20種の代表的な指示でゴールデンテスト | 週1回 |

**必須テストケース（Layer 1）：**

| テスト | 確認内容 |
|---|---|
| 速度マッピング | low=0.1 / medium=0.3 / high=0.5 |
| 旋回計算 | 90°・180°・360° の duration 精度 |
| clamp | duration=99→30.0 / angle=720→360.0 |

```bash
pytest                                              # 全テスト
pytest tests/test_capabilities.py -v               # capabilities のみ
```

---

### 5.5 モデル更新フロー

1. 新モデル文字列を `config-staging.yaml` に設定
2. Layer 3 ゴールデンテスト（`tests/golden/run_golden.py`）を実行
3. 全件パスで `config.yaml` に反映。失敗時はプロンプト調整またはロールバック

モデル文字列は `config.yaml` の `llm.model` のみで管理する。

```bash
# 利用可能なモデルを確認
gcloud ai models list --region=asia-northeast1
```

---

### 5.6 コスト管理

```yaml
cost_control:
  daily_command_limit: 500    # コマンド上限
  daily_observe_limit: 50     # observe 上限
  alert_threshold_usd: 10.0   # アラートしきい値
```

上限到達時はオフラインモードに自動切り替え。

**トークン節約の方針：**

| 対策 | 方法 |
|---|---|
| セッション履歴上限 | 直近5ターンのみ保持 |
| observe 画像縮小 | 送信前に 640×480 へリサイズ（OpenCV） |

**応答時間目標：**

| 処理 | 目標 | 超過時 |
|---|---|---|
| LLM 応答（単純コマンド） | 3秒以内 | 再試行1回 → エラー |
| LLM 応答（observe） | 5秒以内 | エラー通知 |

---

## 6. 拡張・制約

### 6.1 将来拡張の方針

**マルチロボット対応：** 現設計は 1ユーザー × 1ロボットを対象。将来拡張は namespace で対応。

```yaml
robot:
  namespace: ""   # 複数台時は "/robot_a" 等を設定
```

**センサー拡張：** `observe(sensor="camera"|"lidar"|"ultrasonic")` の sensor パラメータで拡張。`SensorBase` 抽象クラスを定義し実装を分離。

**音声 I/F：** `voice/` モジュール（`BaseSpeechRecognizer` / `BaseSynthesizer`）を継承して実装。音声認識レイヤーでも緊急停止キーワードを LLM 経由なしで検出すること。

**アクセス制御（オプション）：**

```yaml
auth:
  mode: "none"   # none / single_token / multi_user
```

**モニタリング（オプション）：** Prometheus メトリクス（`robot_commands_total` / `robot_api_latency_seconds` / `robot_emergency_stops_total` 等）を `/metrics` で公開。緊急停止が5分で3回以上の場合にアラート。

---

### 6.2 プライバシー・倫理

- カメラ画像は送信前に顔検出＋ブラー処理（OpenCV）を適用（`camera_send_to_cloud: false` で無効化可）
- ユーザー入力テキストはログの DEBUG レベルのみ記録（INFO には残さない）
- 画像 base64 はログに残さない
- セッション履歴の保存期間は24時間
- `compliance_mode: true` で移動速度を 0.25 m/s 以下に制限（ISO/TS 15066 参考値）

---

### 6.3 フィールド運用オプション

- **バッテリー残量連携（オプション）：** 20% で警告、10% で移動禁止
- **スタック検知（オプション）：** cmd_vel 送信中に `/odom` が変化しない場合、停止＋通知
- **減速ランプ（`ramp_down_enabled: true`）：** 停止時に5ステップで段階的に速度を下げる（衝撃軽減）

---

### 6.4 未決事項

| 項目 | 状態 | アクション |
|---|---|---|
| Vertex AI 利用可能なモデル文字列 | 未確定 | 実装時 `gcloud ai models list --region=asia-northeast1` で確認後 config.yaml に記載 |
| ADK の multimodal tool_result の書き方 | **解決済み** | `before_model_callback` で `llm_request.contents` に追加（Vertex AI は `function_response.parts` 非対応のため） |
| runner.run_async / run_live の API | **解決済み** | `runner.run_async()` を使用。`InMemorySessionService` + `Runner` の組み合わせで動作確認済み |
| 顔検出ブラーの精度・パフォーマンス | 要検証 | OpenCV の軽量モデル選定 |
| 禁止パターンの具体的なリスト | 要定義 | 実装時に確定 |
| バッテリートピックのメッセージ型 | 要確認 | 使用ロボットに依存 |
| スタック検知の `/odom` トピック型 | 要確認 | 使用ロボットに依存 |
