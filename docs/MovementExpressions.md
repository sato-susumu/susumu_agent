# 移動表現拡張の方針

自然言語の移動表現を増やすときは、既存の移動性能と安全性能を落とさないことを優先する。
そのため、表現追加はプロンプトへの追記だけで行わず、テスト可能な business 層のカタログと解釈ロジックに集約する。

## 基本方針

- 物理挙動を担う `RobotTools` / `RobotInterface` / `/cmd_vel` 送信層は、必要がない限り変更しない。
- 明確な移動表現は `MovementInterpreter` で LLM なしに `ToolPlan` へ変換する。
- 曖昧な入力や未対応の複合指示は、従来通り ADK/LLM へフォールバックする。
- 破壊、衝突、追跡、自律ナビゲーション、条件付き自律判断は `report_unsupported` に倒す。
- 表現カタログ、プロンプト生成、golden ケースを同じソースから管理し、追加時の回帰を `pytest` で検出する。
- LLM プロンプトは肥大化させない。代表ルールを短く載せ、細かい検証は golden ケースで担保する。

## 評価基準

- 既存の速度値、角度 clamp、時間 clamp の単体テストを維持する。
- `GOLDEN_CASES` に登録した入力は、期待する tool 名と主要引数に変換できること。
- プロンプトに主要な追加表現が含まれること。
- `build_system_prompt()` の文字数を一定以下に保ち、LLM への入力量を増やしすぎないこと。
- 認識できない入力は direct path で無理に解釈せず、ADK/LLM にフォールバックすること。

## 今回の結果

追加した主要ファイル:

- `susumu_agent/business/movement_expressions.py`
  - `MovementInterpreter`: 明確な移動表現を `ToolPlan` に変換する純粋な解釈層
  - `ASR_RULES` / `MOTION_RULES` / `UNSUPPORTED_RULES`: プロンプト生成にも使う表現カタログ
  - `GOLDEN_CASES`: LLM なしで検証する移動表現の回帰ケース
- `tests/test_movement_expressions.py`
  - 既存・追加表現の golden テスト
  - プロンプト内の主要表現チェック
  - プロンプトサイズ上限チェック
- `tests/test_tools_sequence_state.py`
  - `execute_sequence` 後にシーケンス全体が `SharedState.last_command` に残ることを確認
- `tests/test_debug_tools.py`
  - `debug_tools parse` が direct path の解釈結果を JSON で返すことを確認

検証結果:

- `pytest`: 18件成功
- `ruff check .`: 成功
- `build_system_prompt()` の長さ: 3363文字（上限テストは3800文字）

対応を広げた代表例:

- 前進: `進め`, `前へ`, `前に進んで`, `まっすぐ`, `直進して`
- 後退: `バックして`, `下がって`, `後ろへ`, `うしろに進んで`
- 停止: `止まって`, `停止して`, `止めて`, `待って`
- 旋回: `右向け右`, `左向け左`, `半回転して`, `Uターンして`, `時計回りに回って`
- 経路: `左に進んで`, `右に進んで`, `円を描いて`, `ジグザグに進んで`, `S字に進む`
- 図形: `三角形`, `四角形`, `正方形`
- 直前参照: `もう一回`, `さっきと同じ`, `さっきより速く`, `もっとゆっくり`, `逆方向`, `反対方向`
- 数量指定: `三秒`, `一メートル`, `半メートル`, `五十センチ`, `九十度`, `百八十度`
- 安全側の拒否: `人にぶつけて`, `追いかけて`, `障害物を避けながら進んで`

## 数量表現

時間・距離・角度は、算用数字と漢数字の両方を `MovementInterpreter` で扱う。

- 時間: `3秒`, `三秒`, `半秒`
- 距離: `50cm`, `五十センチ`, `1メートル`, `一メートル`, `半メートル`
- 角度: `90度`, `九十度`, `180度`, `百八十度`

漢数字は `十`、`百` を含む整数と `半` を扱う。
これにより、数値抽出のためだけに LLM へ落ちるケースを減らす。

## 直前コマンド参照

`MovementInterpreter.interpret_with_context()` は `SharedState.last_command` を受け取り、以下の表現を LLM なしで解釈する。
ただし、同じ入力に明示的な移動指示が含まれる場合は、文脈再実行よりその移動指示を優先する。
例: `さっきより速く前進して` は直前コマンドの再実行ではなく、`前進` を `high` で実行する。

- `もう一回`, `さっきと同じ`, `繰り返して`: 直前コマンドを再実行する。
- `さっきより速く`, `もっと速く`: `low → medium → high` の順に速度を1段階上げる。
- `さっきより遅く`, `もっとゆっくり`: `high → medium → low` の順に速度を1段階下げる。
- `逆方向`, `反対方向`, `逆にして`: `direction`, `turn`, `angle_deg` を反転する。

`execute_sequence` は内部で `move_robot` / `rotate_robot` / `curve_robot` を呼ぶため、以前は最後の小ステップが `last_command` に残りやすかった。
今回、`execute_sequence` 完了時にはシーケンス全体を `last_command` に戻すようにした。
これにより、`正方形を描いて` の後の `もう一回` は、最後の旋回だけではなく正方形全体を再実行する。

## 追加時の手順

1. `movement_expressions.py` の該当ルールに表現を追加する。
2. 明確に tool plan 化できる表現なら `MovementInterpreter` に最小限の判定を追加する。
3. `GOLDEN_CASES` に期待 tool と主要引数を追加する。
4. `pytest` を実行し、既存 golden ケースとプロンプトサイズが維持されていることを確認する。
5. 曖昧な表現は direct path に入れず、プロンプトルールに留める。

## デバッグ

LLM やロボット実行を使わず、自然言語が direct path でどう解釈されるかを確認できる。

```bash
python3 -m susumu_agent.cli.debug_tools parse "一メートル進んで"
python3 -m susumu_agent.cli.debug_tools parse "逆方向" \
  --last-command '{"tool":"move_robot","direction":"forward","speed":"medium","duration_sec":2.0}'
```

`status` が `direct` なら `MovementInterpreter` で解釈できている。
`fallback` なら ADK/LLM に処理が渡る。
