# susumu_agent

自然言語（日本語・英語）でロボットを制御するシステム。  
Google ADK + Gemini（または Claude on Vertex AI）が音声・テキストの指示を ROS2 `/cmd_vel` コマンドに変換する。

---

## システム全体構成

```mermaid
graph TD
    User["👤 ユーザー入力<br/>（テキスト）"]
    Emergency["🛑 緊急停止<br/>即時実行<br/>LLM経由なし"]
    ADK["🤖 Google ADK<br/>LlmAgent<br/>Gemini 2.5 Flash"]
    Tools["🔧 tools.py<br/>8ツール"]
    Robot["🦾 RobotInterface"]
    Mock["💻 MockRobot<br/>simulate モード"]
    ROS2["🤖 ROS2Robot<br/>/cmd_vel"]
    State["📊 SharedState<br/>スレッドセーフ"]
    Watchdog["⏱️ Watchdog<br/>5秒タイムアウト"]
    Camera["📷 Camera<br/>画像取得"]
    Macro["💾 MacroStore<br/>macros.json"]
    Session["📝 SessionStore<br/>JSONL ログ"]

    User -->|"ストップ等"| Emergency
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

## データフロー

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant Main as main.py
    participant ADK as Google ADK<br/>LlmAgent
    participant Tools as tools.py
    participant Robot as RobotInterface
    participant State as SharedState

    User->>Main: "ゆっくり前進"
    Main->>Main: 緊急キーワード判定 → 該当なし
    Main->>ADK: run_async()
    ADK->>ADK: 自然言語を解釈<br/>"ゆっくり" → speed=low<br/>"前進" → direction=forward
    ADK->>Tools: move_robot("forward", "low", 2.0)
    Tools->>State: stop_event 確認
    Tools->>Robot: move("forward", "low", 2.0)
    Robot-->>Tools: 完了
    Tools-->>ADK: {status: ok, linear_x: 0.1, duration_sec: 2.0}
    ADK-->>Main: "ロボットは低速で2.0秒前進しました。"
    Main-->>User: 🤖 ロボットは低速で2.0秒前進しました。
```

---

## 安全設計

```mermaid
graph LR
    Input["ユーザー入力"]

    subgraph "層1: 緊急キーワード検出"
        EK["ストップ / 止まれ / stop\n→ LLM を経由せず即時停止"]
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

---

## ツール一覧

```mermaid
graph LR
    ADK["Google ADK<br/>LlmAgent"]

    ADK --> T1["move_robot<br/>前進・後退・停止"]
    ADK --> T2["rotate_robot<br/>その場旋回"]
    ADK --> T3["execute_sequence<br/>複数動作の連続実行"]
    ADK --> T4["observe<br/>カメラで前方確認"]
    ADK --> T5["query_status<br/>移動状態の確認"]
    ADK --> T6["query_last_command<br/>直前コマンド取得"]
    ADK --> T7["manage_macro<br/>マクロ登録・実行・削除"]
    ADK --> T8["report_unsupported<br/>能力範囲外の報告"]
```

---

## 速度マッピング

| レベル | キーワード例 | linear (m/s) | angular (rad/s) |
|---|---|---|---|
| `low` | ゆっくり、slowly | 0.1 | 0.3 |
| `medium` | （指定なし） | 0.3 | 0.8 |
| `high` | 速く、fast | 0.5 | 1.5 |

---

## モード切り替え

```mermaid
flowchart TD
    Start["起動"]
    Config{"config.yaml<br/>robot.mode"}
    Simulate["simulate モード<br/>ROS2 不要<br/>MockRobot が動作を表示"]
    Real["real モード<br/>ROS2 必要<br/>/cmd_vel をパブリッシュ"]
    DryRun["dry_run モード<br/>LLM だけ動かす<br/>ロボットへの指令なし"]
    ADK{"Google ADK<br/>利用可能？"}
    UseADK["ADK + Gemini/Claude<br/>自然言語処理"]
    RuleBased["ルールベース<br/>（ADK なし）"]

    Start --> Config
    Config -->|simulate| Simulate
    Config -->|real| Real
    Config -->|dry_run| DryRun
    Simulate --> ADK
    Real --> ADK
    DryRun --> ADK
    ADK -->|Yes| UseADK
    ADK -->|No| RuleBased
```

---

## ファイル構成

```mermaid
graph TD
    Root["robot_nl_controller/"]

    Root --> main["main.py<br/>エントリポイント・入力ループ"]
    Root --> agent["agent.py<br/>ADK LlmAgent 設定"]
    Root --> tools["tools.py<br/>8ツール実装"]
    Root --> cap["capabilities.py<br/>速度定数・プロンプト生成"]
    Root --> state["shared_state.py<br/>スレッドセーフ共有状態"]
    Root --> wd["watchdog.py<br/>タイムアウト監視"]
    Root --> cam["camera.py<br/>画像取得"]
    Root --> ss["session_store.py<br/>履歴ログ"]
    Root --> ms["macro_store.py<br/>マクロ保存"]
    Root --> cfg["config.yaml<br/>全設定"]

    Root --> robotdir["robot/"]
    robotdir --> iface["interface.py<br/>抽象クラス"]
    robotdir --> mock["mock_robot.py<br/>simulate 用"]
    robotdir --> ros2["ros2_robot.py<br/>実機用"]

    Root --> launch["launch/"]
    launch --> lreal["robot_nl.launch.py<br/>実機用"]
    launch --> lsim["robot_nl_simulate.launch.py<br/>simulate 用"]

    Root --> deploy["deploy/"]
    deploy --> svc["robot-nl.service<br/>systemd unit"]
    deploy --> inst["install.sh<br/>デプロイスクリプト"]

    Root --> voice["voice/"]
    voice --> rec["recognizer.py<br/>音声認識 抽象クラス"]
    voice --> syn["synthesizer.py<br/>音声合成 抽象クラス"]
```

---

## セットアップ

### 前提

| 項目 | バージョン |
|---|---|
| Python | 3.10 以上 |
| ROS2 | Humble（実機モードのみ必要） |
| Google Cloud | Vertex AI が有効なプロジェクト |
| 認証 | `gcloud auth application-default login` 済み |

### インストール

```bash
cd robot_nl_controller
pip install -r requirements.txt
```

> `rclpy` / `geometry_msgs` / `sensor_msgs` は ROS2 インストールに含まれるため pip 不要。

### config.yaml の主要設定

```yaml
robot:
  mode: "simulate"        # simulate / real / dry_run

llm:
  model: "gemini-2.5-flash"       # 使用モデル（下記参照）
  project: "your-gcp-project-id"  # GCP プロジェクト ID
  location: "us-central1"
  timeout_sec: 60

interface:
  verbosity: "normal"     # brief / normal / verbose
```

**使用できるモデル:**

| モデル文字列 | 説明 | 前提条件 |
|---|---|---|
| `gemini-2.5-flash` | Gemini 2.5 Flash（デフォルト） | Vertex AI 有効化のみ |
| `gemini-2.5-pro` | Gemini 2.5 Pro（高精度） | Vertex AI 有効化のみ |
| `claude-sonnet-4-5@20250514` | Claude Sonnet | Vertex AI Model Garden で Claude を有効化 |

---

## 起動方法

### シミュレーションモード（ROS2 不要）

```bash
cd robot_nl_controller
python3 main.py
```

### 実機モード（ROS2 必要）

```bash
# config.yaml の robot.mode を "real" に変更してから:
python3 main.py

# ROS2 launch 経由:
ros2 launch robot_nl_controller robot_nl.launch.py

# 設定ファイルを指定:
ros2 launch robot_nl_controller robot_nl.launch.py config_path:=/path/to/config.yaml
```

### 自動起動（systemd）

```bash
sudo bash deploy/install.sh
sudo nano /etc/robot_nl/secrets.env   # GCP 情報を記入
sudo systemctl start robot-nl
sudo journalctl -u robot-nl -f
```

---

## 使い方

起動するとプロンプトが表示される。

```
あなた: ゆっくり前進
  [考え中...]
  [MockRobot] forward linear_x=0.10 m/s × 2.0s 開始
  [MockRobot] forward 完了 → 停止

🤖 ロボットは低速で2.0秒前進しました。
```

### コマンド例

| 入力例 | 動作 |
|---|---|
| `ゆっくり前進` | 0.1 m/s で 2 秒前進 |
| `素早く前進` | 0.5 m/s で 2 秒前進 |
| `3秒前進して` | 0.3 m/s で 3 秒前進 |
| `1メートル進んで` | 距離から時間を自動計算して前進 |
| `後退` | 0.3 m/s で 2 秒後退 |
| `右向いて` | 右に 90 度旋回 |
| `左向いて` | 左に 90 度旋回 |
| `180度回転して` | その場で 180 度旋回 |
| `三角形を描いて` | 前進 → 120 度旋回 を 3 回繰り返す |
| `四角形を描いて` | 前進 → 90 度旋回 を 4 回繰り返す |
| `何が見える？` | カメラで前方を確認（実機モードのみ有効） |
| `状態確認` | 現在の移動状態を確認 |
| `ヘルプ` | 使い方を表示 |
| `ストップ` | 即時緊急停止（LLM 経由なし） |
| `quit` | 終了 |

### マクロ機能

```mermaid
sequenceDiagram
    actor User as ユーザー
    participant Main as main.py
    participant Tools as manage_macro
    participant Store as macros.json

    User->>Main: "ゆっくり前進してから右に90度向いて"
    Main->>Main: 実行
    User->>Main: "「パトロール」として登録して"
    Main->>Tools: manage_macro("register", "パトロール", steps)
    Tools->>Store: 保存
    Tools-->>Main: "マクロ「パトロール」を登録しました"

    User->>Main: "パトロールして"
    Main->>Tools: manage_macro("run", "パトロール")
    Tools->>Store: ステップ読み込み
    Tools-->>Main: 実行完了
```

---

## 能力定義のカスタマイズ

`capabilities.py` を編集するとロボットの能力定義を変更できる。変更後はシステムプロンプトに自動で反映される。

```python
# 速度の変更
SPEED_MAP = {
    "low":    {"linear": 0.05, "angular": 0.2},
    "medium": {"linear": 0.2,  "angular": 0.6},
    "high":   {"linear": 0.4,  "angular": 1.2},
}

# 緊急停止キーワードの追加
EMERGENCY_KEYWORDS = {
    "ストップ", "止まれ", "stop",
    "危ない",   # 追加例
}
```

---

## テスト

```bash
~/.local/bin/pytest tests/unit/ -v
```

---

## 音声インターフェースの追加

`voice/` の抽象クラスを継承して実装し、`main.py` の `input()` を差し替える。

```python
# voice/my_recognizer.py
from voice.recognizer import BaseRecognizer

class MyRecognizer(BaseRecognizer):
    async def recognize(self) -> str:
        return your_stt_api.transcribe()
```

---

## トラブルシューティング

### ADK 初期化失敗

1. `pip install google-adk` でパッケージを確認
2. `config.yaml` の `llm.project` に正しい GCP プロジェクト ID を設定
3. `gcloud auth application-default login` で認証を確認

### Claude が 404 エラー

Vertex AI Model Garden で Claude の利用を有効化する必要がある。  
有効化するまでは `config.yaml` の `llm.model` を `gemini-2.5-flash` にする。

### Watchdog が誤作動する

`config.yaml` の `robot.watchdog_timeout_sec` を大きくする（デフォルト: `5.0`）。

### ロボットが動かない（実機モード）

```bash
ros2 topic list | grep cmd_vel   # トピックの存在確認
ros2 topic echo /cmd_vel         # 値が届いているか確認
```

---

## ライセンス

MIT
