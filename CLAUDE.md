# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 開発コマンド

```bash
# シミュレーション起動（ROS2 不要）
python3 main.py

# 設定ファイルを指定して起動
python3 main.py /path/to/config.yaml

# 単体テスト実行
~/.local/bin/pytest tests/unit/ -v

# 単一テスト実行
~/.local/bin/pytest tests/unit/test_capabilities.py::test_speed_map_values -v

# パッケージインストール
pip install -r requirements.txt
# ※ rclpy / geometry_msgs / sensor_msgs は ROS2 付属のため pip 不可
```

## アーキテクチャ

### 処理の流れ

`main.py` が入力を受け取り、緊急キーワード（`capabilities.py` の `EMERGENCY_KEYWORDS`）に一致すれば LLM を経由せず即時停止する。通常コマンドは `agent.py` が生成した `LlmAgent` に渡し、ADK の Function Calling で `tools.py` の 8 ツールが呼ばれる。ツールは `RobotInterface` 経由でロボットを動かす。

```
main.py → (緊急) → SharedState.stop_event
        → (通常) → agent.py (LlmAgent) → tools.py → RobotInterface
                                                    → MockRobot (simulate)
                                                    → ROS2Robot (real)
```

### 設定の単一ソース

`config.yaml` が唯一の設定ファイル。`robot.mode` で動作モードを切り替える：
- `simulate` — ROS2 不要、MockRobot が動作をターミナルに表示（デフォルト）
- `real` — ROS2 必要、`/cmd_vel` に Twist をパブリッシュ
- `dry_run` — LLM だけ動かしてロボットへの指令なし

### ロボット能力の定義場所

`capabilities.py` が唯一の能力定義ファイル。`SPEED_MAP`・`EMERGENCY_KEYWORDS`・`SPEED_KEYWORDS` を変更すると、`build_system_prompt()` が自動的に新しい定義を LLM のシステムプロンプトに反映する。速度値やキーワードを変えるときはここだけ編集すればよい。

### ツール登録

`tools.py` の末尾にある `ALL_TOOLS` リストが `agent.py` に渡される。新しいツールを追加するときは、`async def` 関数を実装して `ALL_TOOLS` に追加するだけでよい（ADK が型アノテーションと docstring から自動的にスキーマを生成する）。

### スレッド安全性

`shared_state.py` の `SharedState` シングルトン（`get_state()`）が状態を一元管理する。`stop_event`（緊急停止）と `shutdown_event`（終了）は `threading.Event` で実装されており、Watchdog スレッドと async ループの両方から安全にアクセスできる。

## モデル設定

`config.yaml` の `llm.model` で切り替える：

| モデル | 前提 |
|---|---|
| `gemini-2.5-flash`（デフォルト） | Vertex AI 有効化のみ |
| `gemini-2.5-pro` | Vertex AI 有効化のみ |
| `claude-sonnet-4-5@20250514` | Vertex AI Model Garden で Claude を有効化 |

Claude を使う場合は `agent.py` が `LLMRegistry.register(Claude)` を自動実行する。`susumu-robo` プロジェクトでは Claude が未有効化のため Gemini を使用中。

## テスト構造

`tests/unit/` — `sys.path` に `../..` を追加してリポジトリルートのモジュールを直接インポートしている。ROS2 不要で実行できる。`tests/mock/` と `tests/golden/` のディレクトリは存在するが現時点では未実装。
