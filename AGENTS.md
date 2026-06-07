# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 開発コマンド

```bash
# シミュレーション起動（ROS2 不要）
python3 -m susumu_agent

# 設定ファイルを指定して起動
python3 -m susumu_agent /path/to/config.yaml

# 単体テスト実行
pytest

# 単一テスト実行
pytest tests/test_capabilities.py::test_speed_map_values -v

# パッケージインストール（uv を使用）
uv sync
# ※ rclpy / geometry_msgs / sensor_msgs は ROS2 付属のため pip 不可

# ROS2 ビルド
colcon build --packages-select susumu_agent

# launch ファイル（通常版）
ros2 launch susumu_agent mock.launch.py              # MockRobot（ROS2 なしでも動く）
ros2 launch susumu_agent real.launch.py              # 実機（config の mode を real にしておく）
ros2 launch susumu_agent turtlesim.launch.py         # turtlesim + インタラクティブ操作
ros2 launch susumu_agent turtlesim_demo.launch.py    # turtlesim + 自動デモ（完了後自動終了）

# launch ファイル（デバッグ版：debug/ にログ・ラベル・録画を保存）
ros2 launch susumu_agent mock_debug.launch.py
ros2 launch susumu_agent real_debug.launch.py
ros2 launch susumu_agent turtlesim_debug.launch.py
ros2 launch susumu_agent turtlesim_demo_debug.launch.py

# cmd_vel メッセージ型の切り替え
# turtlesim 系 launch は cmd_vel_stamped:=false（Twist）がデフォルト
# それ以外の launch は cmd_vel_stamped:=true（TwistStamped）がデフォルト
ros2 launch susumu_agent real.launch.py cmd_vel_stamped:=true
ros2 launch susumu_agent turtlesim.launch.py cmd_vel_stamped:=false

# LLM なしでツールを直接テスト
python3 -m susumu_agent.cli.debug_tools move forward medium 2.0
python3 -m susumu_agent.cli.debug_tools rotate 90 medium
python3 -m susumu_agent.cli.debug_tools sequence square
python3 -m susumu_agent.cli.debug_tools --real --cmd-vel-topic /turtle1/cmd_vel move forward medium 2.0
```

## アーキテクチャ

### パッケージ構成

```
susumu_agent/
├── business/   # ビジネスロジック中核（ROS2・ADK 依存ゼロ）
│   ├── capabilities.py   # 速度定数・キーワード（RobotCapabilities クラス）
│   ├── shared_state.py   # SharedState シングルトン
│   └── watchdog.py       # 安全監視スレッド
├── agent/      # LLM エージェント層
│   ├── factory.py        # AgentFactory / LlmAgent 定義
│   ├── tools.py          # RobotTools（8ツール実装）
│   └── prompt.py         # build_system_prompt()
├── storage/    # 永続化層
│   ├── session_store.py  # SessionStore
│   └── macro_store.py    # MacroStore
├── sensors/    # センサー系
│   └── camera.py         # CameraClient
├── logging/    # ログ基盤
│   └── ros_logger.py     # RosLogger（loguru → ROS2 ブリッジ）
├── demo/       # turtlesim デモ・録画（ROS2 専用）
│   ├── demo_node.py      # DemoRunner（/from_human を受けて実行）
│   ├── command_publisher.py # デモ入力を /from_human に publish
│   ├── commands.py       # デモコマンド定義
│   └── recorder.py       # TurtlesimRecorder（ffmpeg x11grab）
├── cli/        # CLIエントリポイント
│   ├── main.py           # RobotController・入力ループ
│   └── debug_tools.py    # DebugRunner（LLM なし直接テスト）
├── robot/      # ロボット抽象化（変更なし）
└── voice/      # 音声 I/F 抽象クラス（変更なし）
```

### 処理の流れ

`cli/main.py` が入力を受け取り、緊急キーワード（`business/capabilities.py` の `EMERGENCY_KEYWORDS`）に一致すれば LLM を経由せず即時停止する。通常コマンドは `agent/factory.py` が生成した `LlmAgent` に渡し、ADK の Function Calling で `agent/tools.py` の 8 ツールが呼ばれる。ツールは `RobotInterface` 経由でロボットを動かす。

ROS2 launch 経由では `input("あなた: ").strip()` を使わず、ADK への入力は `/from_human` (`std_msgs/msg/String`) で受け取る。`/to_human` (`std_msgs/msg/String`) への publish タイミングはケースによって異なる：

| ケース | `/to_human` の内容・タイミング |
|---|---|
| 移動・旋回・シーケンス | LLM がツール呼び出しを含む応答を返した時点（動作開始前）の宣言テキストを即時 publish（1回のみ） |
| カメラ確認（observe） | 動作開始前の宣言テキストを即時 publish した後、最終応答から宣言部分を除いた差分（カメラに映った内容）を追加 publish |
| ツール呼び出しなし（エラー・unsupported など） | 最終応答テキストを publish |

ツール呼び出し開始・完了・行動完了などの状態イベントは `/agent_event` (`std_msgs/msg/String`) に JSON 形式で publish する。イベント種別：

| type | タイミング | 主なフィールド |
|---|---|---|
| `tool_start` | ツール呼び出し開始直前 | `tool`, パラメータ各種 |
| `tool_done` | ツール呼び出し完了直後 | `tool`, `status`, 結果各種 |
| `action_completed` | LLM 最終応答確定後 | `response`（全文） |

`turtlesim_demo.launch.py` / `turtlesim_demo_debug.launch.py` では `susumu_agent_demo_feeder` がデモ内容を `/from_human` に流し、`susumu_agent_demo` がそれを受けて実行・録画する。feeder は `/agent_event` の `action_completed` イベントを受信したら次のコマンドを送信する。

`DemoCommand` の `interrupt_after_sec > 0` のコマンドは割り込み方式で動作する。コマンド送信後、`/agent_event` の最初の `tool_start` を受信した時点からタイマーをスタートし、`interrupt_after_sec` 秒後に `interrupt_text`（デフォルト `"ストップ"`）を `/from_human` に送信する。割り込みコマンドの `action_completed` を待ってから次のコマンドへ進む。`DEMO_COMMANDS` の末尾に固定の `ストップ` を追加すると字幕が二重になるため追加しない。feeder は最後のコマンドの全処理（割り込み含む）が完了した後、`final_hold_sec`（デフォルト5秒）待ってから終了する。

現在のデモコマンド（`demo/commands.py`）:
- 正方形: `interrupt_after_sec=3.0`、`interrupt_text="ストップ"`（`tool_start` から3秒後に停止）
- くるっと回って: `interrupt_after_sec=1.0`、`interrupt_text="前進して"`（`tool_start` から1秒後に前進割り込み）

```
CLI直起動 input() / ROS2 /from_human
            → (緊急) → SharedState.stop_event
            → (通常) → agent/factory.py (LlmAgent) → agent/tools.py → RobotInterface
                                                    ↓ ツール呼び出し前の発話    → MockRobot (simulate)
                                                    → ROS2 /to_human（即時）   → ROS2Robot (real)
                                                    ↓ ツール状態イベント
                                                    → ROS2 /agent_event（tool_start / tool_done / action_completed）
```

### 認証情報・環境変数

`.env`（gitignore 対象）に GCP プロジェクト ID のみ記載する。`cli/main.py` が起動時に `load_dotenv()` で読み込む。

```dotenv
GOOGLE_CLOUD_PROJECT=your-project-id
```

モデルやリージョンなどその他の設定は `config.yaml` で管理する。`.env.sample` をコピーして編集する。launch ファイルの `_ENV_FILE` 定数が自動的にパスを渡す。

### 設定の単一ソース

`config.yaml` が唯一の設定ファイル。`robot.mode` で動作モードを切り替える：
- `simulate` — ROS2 不要、MockRobot が動作をターミナルに表示（デフォルト）
- `real` — ROS2 必要、`/cmd_vel` に Twist / TwistStamped をパブリッシュ
- `dry_run` — LLM だけ動かしてロボットへの指令なし

`robot.cmd_vel_stamped` で `/cmd_vel` のメッセージ型を切り替える。`true` は `geometry_msgs/msg/TwistStamped`、`false` は `geometry_msgs/msg/Twist`。launch ファイルの `cmd_vel_stamped` パラメータで上書きでき、turtlesim 系 launch は `false`、それ以外の launch は `true` がデフォルト。

### ロボット能力の定義場所

`susumu_agent/business/capabilities.py` が唯一の能力定義ファイル。`SPEED_MAP`・`EMERGENCY_KEYWORDS`・`SPEED_KEYWORDS` を変更すると、`agent/prompt.py` の `build_system_prompt()` が自動的に新しい定義を LLM のシステムプロンプトに反映する。速度値やキーワードを変えるときはここだけ編集すればよい。

### ツール登録

`susumu_agent/agent/tools.py` の `RobotTools.get_all_tools()` が `agent/factory.py` に渡される。新しいツールを追加するときは、`async def` メソッドを実装して `get_all_tools()` に追加するだけでよい（ADK が型アノテーションと docstring から自動的にスキーマを生成する）。

### スレッド安全性

`susumu_agent/business/shared_state.py` の `SharedState` シングルトン（`get_state()`）が状態を一元管理する。`stop_event`（緊急停止）と `shutdown_event`（終了）は `threading.Event` で実装されており、Watchdog スレッドと async ループの両方から安全にアクセスできる。

## モデル設定

`config.yaml` の `llm.model` で切り替える：

| モデル | 前提 |
|---|---|
| `gemini-2.5-flash`（デフォルト） | Vertex AI 有効化のみ |
| `gemini-2.5-pro` | Vertex AI 有効化のみ |
| `claude-sonnet-4-5@20250514` | Vertex AI Model Garden で Claude を有効化 |

Claude を使う場合は `agent.py` が `LLMRegistry.register(Claude)` を自動実行する。`susumu-robo` プロジェクトでは Claude が未有効化のため Gemini を使用中。

### ログ・デバッグ

全ファイルで `print()` を使わず `loguru` の `logger` を使う。

- 通常モード: loguru → stderr（ROS2 コンソール経由）
- デバッグモード: `setup_loguru(log_path)` で ROS2 + ファイルへ同時出力
- `ros_logger.py` が `loguru → rclpy.logging` へブリッジする

`debug/` フォルダには以下が生成される（gitignore 対象）:
- `{ts}_susumu_agent.log` — ログ
- `{ts}_susumu_agent_demo.log` — デモノードのログ（デモ時のみ）
- `{ts}_demo_labels.jsonl` — 指示・応答ラベル（デモ時のみ）
- `{ts}_command_log.jsonl` — ツール呼び出し履歴（デバッグモード時のみ）
- `{ts}_turtlesim_raw.mp4` — 元の録画（デモ時のみ、ffmpeg x11grab）
- `{ts}_turtlesim.srt` — 字幕ファイル（日本語＋英語、短い字幕は最低2秒表示）
- `{ts}_turtlesim.mp4` — 字幕付き動画
- `{ts}_turtlesim.gif` — アニメーション GIF（480px、GitHub 掲載用）

## テスト構造

`tests/unit/` — `susumu_agent` パッケージとして直接インポートしている。ROS2 不要で実行できる。`tests/mock/` と `tests/golden/` のディレクトリは存在するが現時点では未実装。
