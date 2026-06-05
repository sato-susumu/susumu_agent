# robot_nl_controller

自然言語（日本語・英語）でロボットを制御するシステム。  
Google ADK + Gemini（または Claude on Vertex AI）が音声・テキストの指示を ROS2 `/cmd_vel` コマンドに変換する。

---

## アーキテクチャ

```
ユーザー入力（テキスト）
        │
        ▼
┌───────────────────┐
│      main.py      │  入力ループ・緊急停止判定
└────────┬──────────┘
         │ 緊急キーワード → 即時停止（LLM経由しない）
         │ 通常コマンド ↓
┌────────▼──────────┐
│    Google ADK     │  LlmAgent（Gemini 2.5 Flash / Claude on Vertex AI）
│   + LlmAgent      │  自然言語を解釈してツールを選択・呼び出す
└────────┬──────────┘
         │ ツール呼び出し（Function Calling）
         ▼
┌─────────────────────────────────────────┐
│              tools.py（8ツール）         │
│  move_robot / rotate_robot /            │
│  execute_sequence / observe /           │
│  query_status / query_last_command /    │
│  manage_macro / report_unsupported      │
└──────┬────────────────────┬────────────┘
       │                    │
┌──────▼──────┐    ┌────────▼────────┐
│ RobotInterface│    │  SharedState    │
│  (抽象クラス) │    │  スレッドセーフ  │
└──┬───────┬──┘    │  stop_event     │
   │       │        │  shutdown_event │
   ▼       ▼        └────────┬────────┘
MockRobot  ROS2Robot          │
(simulate) (/cmd_vel)         │
                     ┌────────▼────────┐
                     │    Watchdog     │
                     │  5秒無通信で停止 │
                     └─────────────────┘
```

### データフロー（例：「ゆっくり前進」）

```
1. ユーザー入力: "ゆっくり前進"
2. 緊急キーワード判定 → 該当なし
3. ADK LlmAgent が解釈:
     "ゆっくり" → speed="low"、前進 → direction="forward"
4. move_robot(direction="forward", speed="low", duration_sec=2.0) を呼び出し
5. RobotInterface.move() → MockRobot or ROS2Robot
6. ROS2Robot: /cmd_vel に Twist(linear.x=0.1) をパブリッシュ
7. 応答: "ロボットは低速で2.0秒前進しました。"
```

---

## 主要コンポーネント

| ファイル | 役割 |
|---|---|
| `main.py` | エントリポイント。入力ループ、緊急停止、ADK 呼び出し |
| `agent.py` | Google ADK の `LlmAgent` 設定。モデル・ツール・プロンプト登録 |
| `tools.py` | 8つのロボット操作ツール。ADK の Function Calling で呼ばれる |
| `capabilities.py` | 速度定数、入力バリデーション、システムプロンプト自動生成 |
| `shared_state.py` | プロセス内シングルトン。スレッドセーフな状態管理 |
| `watchdog.py` | 無通信タイムアウト監視（デフォルト 5 秒で自動停止） |
| `camera.py` | カメラ画像取得（ROS2 または simulate ダミー） |
| `session_store.py` | 会話履歴・コマンドログの保存（JSONL） |
| `macro_store.py` | マクロの登録・保存（macros.json） |
| `robot/interface.py` | `RobotInterface` 抽象クラス（DI パターン） |
| `robot/mock_robot.py` | simulate モード用。動作をターミナルに表示 |
| `robot/ros2_robot.py` | 実機用。`/cmd_vel` に Twist をパブリッシュ |
| `voice/` | 音声認識・音声合成の抽象基底クラス |

### ツール一覧

| ツール | 説明 | 主なパラメータ |
|---|---|---|
| `move_robot` | 前進・後退・停止 | `direction`, `speed`, `duration_sec` |
| `rotate_robot` | その場旋回 | `angle_deg`（正=左、負=右）, `speed` |
| `execute_sequence` | 複数動作の連続実行 | `steps`（moveとrotateのリスト） |
| `observe` | カメラで前方確認 | `question` |
| `query_status` | 現在の移動状態取得 | なし |
| `query_last_command` | 直前のコマンド取得 | なし |
| `manage_macro` | マクロ登録・実行・削除・一覧 | `action`, `name`, `steps` |
| `report_unsupported` | 能力範囲外の場合に呼ばれる | `reason` |

### 速度マッピング

| レベル | キーワード例 | linear (m/s) | angular (rad/s) |
|---|---|---|---|
| `low` | ゆっくり、slowly | 0.1 | 0.3 |
| `medium` | （指定なし） | 0.3 | 0.8 |
| `high` | 速く、fast | 0.5 | 1.5 |

### 安全設計

安全は 3 層構造になっている。

```
層1: 緊急キーワード検出（main.py）
     「ストップ」「止まれ」「stop」等 → LLM を経由せず即時停止
     stop_event をセット → 実行中のシーケンスも中断

層2: Watchdog（watchdog.py）
     最後のコマンドから 5 秒間無通信 → 自動で zero_twist()
     daemon スレッドで常時監視

層3: 既存の安全機構（ロボット側）
     ハードウェア・ファームウェアレベルの安全機能はそのまま活用
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
  mode: "simulate"        # simulate（開発用）/ real（実機）/ dry_run

llm:
  model: "gemini-2.5-flash"          # 使用モデル（下記参照）
  project: "your-gcp-project-id"     # GCP プロジェクト ID
  location: "us-central1"            # Vertex AI リージョン
  timeout_sec: 60                    # LLM 応答タイムアウト

interface:
  verbosity: "normal"     # brief / normal / verbose
```

**使用できるモデル:**

| モデル文字列 | 説明 | 前提 |
|---|---|---|
| `gemini-2.5-flash` | Gemini 2.5 Flash（デフォルト） | Vertex AI 有効化のみ |
| `gemini-2.5-pro` | Gemini 2.5 Pro（高精度） | Vertex AI 有効化のみ |
| `claude-sonnet-4-5@20250514` | Claude Sonnet（Anthropic） | Model Garden で Claude を有効化 |

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
sudo journalctl -u robot-nl -f        # ログ確認
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

よく使う動作シーケンスを名前で登録して再利用できる。

```
あなた: ゆっくり前進してから右に90度向いて
あなた: 「パトロール」として登録して
🤖 マクロ「パトロール」を登録しました

あなた: パトロールして     ← 登録した動作を呼び出す
あなた: マクロ一覧          ← 登録済みマクロを確認
```

マクロは `macros.json` に保存され、再起動後も維持される。

---

## 能力定義のカスタマイズ

`capabilities.py` を編集するとロボットの能力定義を変更できる。変更後はシステムプロンプトに自動で反映される。

```python
# 速度の変更
SPEED_MAP = {
    "low":    {"linear": 0.05, "angular": 0.2},   # より遅くする
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
# 単体テスト（ROS2 不要）
~/.local/bin/pytest tests/unit/ -v
```

---

## ファイル構成

```
robot_nl_controller/
├── config.yaml               # 全設定（速度・モデル・モード等）
├── main.py                   # エントリポイント・入力ループ・緊急停止
├── agent.py                  # Google ADK LlmAgent 設定
├── tools.py                  # 8ツール実装（ADK Function Calling）
├── capabilities.py           # 速度定数・バリデーション・プロンプト生成
├── shared_state.py           # プロセス内共有状態（スレッドセーフ）
├── watchdog.py               # 無通信タイムアウト監視
├── camera.py                 # カメラ画像取得
├── session_store.py          # セッション・コマンド履歴（JSONL）
├── macro_store.py            # マクロ登録・管理（macros.json）
├── robot/
│   ├── interface.py          # RobotInterface 抽象クラス
│   ├── ros2_robot.py         # 実機用（/cmd_vel パブリッシュ）
│   └── mock_robot.py         # simulate 用（ターミナル出力）
├── launch/
│   ├── robot_nl.launch.py          # 実機用 ROS2 launch
│   └── robot_nl_simulate.launch.py # simulate 用 launch
├── deploy/
│   ├── robot-nl.service      # systemd unit
│   ├── secrets.env.example   # 環境変数テンプレート
│   └── install.sh            # デプロイスクリプト
├── voice/
│   ├── recognizer.py         # 音声認識 抽象基底クラス
│   └── synthesizer.py        # 音声合成 抽象基底クラス
├── tests/unit/               # 単体テスト（ROS2 不要）
├── requirements.txt
├── package.xml               # ROS2 パッケージ定義
└── setup.py                  # ROS2 ament_python 設定
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

### 「ADK 初期化失敗」と表示される

1. `pip install google-adk` でパッケージを確認
2. `config.yaml` の `llm.project` に正しい GCP プロジェクト ID を設定
3. `gcloud auth application-default login` で認証を確認

### モデルが 404 エラーになる（Claude 使用時）

Vertex AI Model Garden で Claude の利用を有効化する必要がある。  
有効化するまでは `config.yaml` の `llm.model` を `gemini-2.5-flash` にする。

### 「タイムアウトしました」と表示される

`config.yaml` の `llm.timeout_sec` を大きくする（デフォルト: `60`）。

### Watchdog が誤作動する（すぐ停止してしまう）

`config.yaml` の `robot.watchdog_timeout_sec` を大きくする（デフォルト: `5.0`）。

### ロボットが動かない（実機モード）

```bash
ros2 topic list | grep cmd_vel          # トピックの存在確認
ros2 topic echo /cmd_vel                # 値が届いているか確認
```

`config.yaml` の `robot.cmd_vel_topic` がロボット側のトピック名と一致しているか確認する。

---

## ライセンス

MIT
